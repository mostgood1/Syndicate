"""Capture Syndicate-native live basketball game state, tick by tick (NBA / WNBA / NCAAB).

Each tick reads ESPN's scoreboard for the date, then, for every game in progress (and each game's final
once), builds a typed `LiveGameState` (`syndicate/features/shared/basketball_live_state.py`) and writes
`<league>_source/data/processed/live_state/<date>/<event_id>.json`, appending a compact line to
`<event_id>.ticks.jsonl` whenever the game advanced. No vendored code.

Phase P2 of `docs/ai_context/basketball_live_native_plan.md`. P3's re-sim will call
`capture_live_states` / `build_live_game_state` in its own tick; this script is the standalone producer
and the instrument for verifying it on the fleet.

    python scripts/capture_basketball_live_state.py --league nba                     # one tick, today
    python scripts/capture_basketball_live_state.py --league nba --loop --interval 20 --until-done

`--until-done` stops once at least one game was seen in progress and none is in progress any more (every
final captured), or at `--max-minutes`. The date defaults to today in US Eastern, ESPN's schedule day.
Run it at low priority on the fleet (`nice -n 19`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import basketball_live_state as live  # noqa: E402
from syndicate.features.shared import basketball_pbp as pbp  # noqa: E402


def eastern_today() -> str:
    try:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:  # noqa: BLE001 -- no tz database: UTC-4 is right for the whole basketball calendar but Nov-Mar
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).date().isoformat()


def tick(leagues: list[str], date: str) -> tuple[list[dict], int]:
    results: list[dict] = []
    in_progress = 0
    for league in leagues:
        try:
            events = pbp.scoreboard_events(pbp.fetch_scoreboard(league, date.replace("-", "")))
        except Exception as exc:  # noqa: BLE001
            results.append({"league": league, "error": f"scoreboard {type(exc).__name__}: {exc}"[:200]})
            continue
        in_progress += sum(1 for e in events if e["state"] == "in")
        board = {e["event_id"]: e for e in events}
        for result in live.capture_live_states(league, date, fetch_scoreboard=lambda *_args, _events=events: _cached(_events)):
            result["league"] = league
            result["scoreboard_state"] = (board.get(result.get("event_id")) or {}).get("state")
            results.append(result)
    return results, in_progress


def _cached(events: list[dict]) -> dict:
    """Re-shape already-parsed scoreboard rows so `capture_live_states` does not fetch the scoreboard twice."""
    return {"events": [
        {"id": e["event_id"], "season": {}, "competitions": [{"status": {"type": {"state": e["state"], "completed": e["completed"], "name": e["status_name"]}}, "competitors": []}]}
        for e in events
    ]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--league", default="nba", help="comma list of nba, wnba, ncaab")
    ap.add_argument("--date", default="", help="YYYY-MM-DD (default: today, US Eastern)")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=float, default=20.0)
    ap.add_argument("--until-done", action="store_true")
    ap.add_argument("--max-minutes", type=float, default=360.0)
    args = ap.parse_args(argv)
    leagues = [x.strip().lower() for x in args.league.split(",") if x.strip()]
    date = args.date or eastern_today()
    started = time.time()
    seen_live = False
    n = 0
    while True:
        n += 1
        results, in_progress = tick(leagues, date)
        seen_live = seen_live or in_progress > 0
        stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        print(f"BASKETBALL_LIVE_STATE_TICK {stamp} n={n} date={date} in_progress={in_progress} " + json.dumps(results, default=str), flush=True)
        if not args.loop:
            return 1 if any("error" in r for r in results) else 0
        if args.until_done and seen_live and in_progress == 0:
            return 0
        if (time.time() - started) / 60.0 >= args.max_minutes:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
