"""Buy the 2026 WNBA REGULAR-SEASON player-prop closes from OddsAPI history (lane `signal-engine-wnba`).

User 2026-10-14: "All 8 markets" (the NBA H6 market set), probe one game first. The fleet holds no usable 2026 WNBA
prop close (41 events, snapshots 1-22 h before tip), so the role signals and the NBA under effect cannot be tested
on WNBA without it. Playoffs are excluded (a different population; the Finals are being played as this runs).

  games    the ESPN game log `player_game_log_2026.csv`, season_type regular, BOTH clubs real WNBA teams
           (`canonical_team("wnba")` -- drops the July 25 All-Star game, COOP vs SPO, which the log labels regular).
  events   one GET /historical/sports/basketball_wnba/events per game day at 12:00Z; a game joins the event with
           the same two canonical clubs whose commence_time falls between 12:00Z on its date and 12:00Z the next day.
  props    GET /historical/sports/basketball_wnba/events/<id>/odds, regions=us, 8 markets, at tip - 10 min. OddsAPI bills
           10 credits per market per region: 80 per game.
  safety   dry run unless --execute; --probe buys one day's events + one game's props and stops; --max-credits is a
           hard ceiling; 5 consecutive failures stop the run; failed calls are never cached; a re-run resumes. Each
           call's quota headers are recorded under sport `wnba`.

    py -3 scripts/wnba_props_pull.py --game-log C:/tmp/wnba_props_2026/player_game_log_2026.csv            # dry run
    ODDS_API_KEY= py -3 scripts/wnba_props_pull.py --game-log ... --execute --probe
    ODDS_API_KEY= py -3 scripts/wnba_props_pull.py --game-log ... --execute --max-credits 28000
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
_spec = importlib.util.spec_from_file_location("_bgl", REPO / "scripts" / "backtest_nhl_game_lines.py")
BGL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BGL)

SPORT = "basketball_wnba"
MARKETS = ("player_points", "player_rebounds", "player_assists", "player_threes", "player_points_rebounds_assists",
           "player_points_rebounds", "player_points_assists", "player_rebounds_assists")
CREDITS_PER_GAME = 10 * len(MARKETS)
CLOSE_MINUTES = 10


def regular_season_games(game_log: Path) -> dict[str, dict[str, Any]]:
    """game_id -> {date, teams (canonical)} for regular-season games between two real WNBA clubs."""
    from syndicate.features.shared.team_aliases import canonical_team

    games: dict[str, dict[str, Any]] = {}
    with game_log.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("season_type") or "").strip().lower() not in ("regular", "regular season"):
                continue
            g = games.setdefault(str(r["game_id"]), {"date": str(r["date"])[:10], "teams": set()})
            g["teams"].add(canonical_team("wnba", r.get("TEAM_ABBREVIATION")))
    return {gid: {"date": g["date"], "teams": frozenset(g["teams"])} for gid, g in games.items()
            if None not in g["teams"] and len(g["teams"]) == 2}


def _get(path: str, params: dict[str, Any], key: str, budget: Any) -> Any:
    """`backtest_nhl_game_lines._odds_get`, with the quota attributed to WNBA."""
    url = f"{BGL.ODDS_BASE}{path}?{urllib.parse.urlencode(dict(params, apiKey=key))}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r:
                h = {k.lower(): v for k, v in r.headers.items()}
                budget.charge(h)
                _record(h, path)
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            h = {k.lower(): v for k, v in (exc.headers or {}).items()}
            budget.charge(h)
            _record(h, path)
            if exc.code in (404, 422):
                return None
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def _record(h: dict[str, str], path: str) -> None:
    try:
        from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota
        record_oddsapi_quota(h, sport="wnba", endpoint=f"historical{path}")
    except Exception:  # noqa: BLE001
        pass


def match_event(game: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    from syndicate.features.shared.team_aliases import canonical_team

    lo = datetime.fromisoformat(f"{game['date']}T12:00:00+00:00")
    hi = lo + timedelta(days=1)
    for ev in events:
        teams = frozenset({canonical_team("wnba", ev.get("home_team")), canonical_team("wnba", ev.get("away_team"))})
        try:
            start = datetime.fromisoformat(str(ev["commence_time"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if teams == game["teams"] and lo <= start < hi:
            return ev
    return None


def summarize(snap: dict[str, Any] | None) -> dict[str, Any]:
    data = (snap or {}).get("data") or {}
    books, outcomes = set(), Counter()
    for b in data.get("bookmakers") or []:
        for m in b.get("markets") or []:
            books.add(b.get("key"))
            outcomes[m.get("key")] += len(m.get("outcomes") or [])
    return {"timestamp": (snap or {}).get("timestamp"), "books": sorted(books), "outcomes_by_market": dict(outcomes)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game-log", required=True)
    ap.add_argument("--out", default="C:/tmp/wnba_props_2026")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--max-credits", type=int, default=28000)
    args = ap.parse_args(argv)
    out = Path(args.out)
    games = regular_season_games(Path(args.game_log))
    by_day: dict[str, list[str]] = defaultdict(list)
    for gid, g in games.items():
        by_day[g["date"]].append(gid)
    todo = [gid for gid in sorted(games) if not (out / "odds" / f"{gid}.json").exists()]
    days_needed = sorted({games[g]["date"] for g in todo if not (out / "events" / f"{games[g]['date']}.json").exists()})
    print(f"wnba 2026 regular season: {len(games)} games over {len(by_day)} days; to fetch {len(todo)} games; "
          f"estimate {len(todo) * CREDITS_PER_GAME} props credits + ~{len(days_needed)} event calls", flush=True)
    if not args.execute or not todo:
        print("dry run -- pass --execute to spend" if not args.execute else "nothing to fetch", flush=True)
        return 0
    if args.probe:
        todo = [sorted(by_day[sorted(by_day)[len(by_day) // 2]])[0]]  # one mid-season game
    cap = min(args.max_credits, CREDITS_PER_GAME * 2 + 10) if args.probe else args.max_credits
    key, budget = BGL._api_key(), BGL.Budget(cap)
    (out / "events").mkdir(parents=True, exist_ok=True)
    (out / "odds").mkdir(parents=True, exist_ok=True)
    fails, no_event = 0, 0
    try:
        for i, gid in enumerate(todo):
            game = games[gid]
            ev_path = out / "events" / f"{game['date']}.json"
            if not ev_path.exists():
                evs = _get(f"/historical/sports/{SPORT}/events", {"date": f"{game['date']}T12:00:00Z"}, key, budget)
                if evs is None:
                    fails += 1
                    if fails >= 5:
                        raise SystemExit("stopped: 5 consecutive failed calls (dead key?)")
                    continue
                ev_path.write_text(json.dumps(evs), encoding="utf-8")
            ev = match_event(game, (json.loads(ev_path.read_text(encoding="utf-8")) or {}).get("data") or [])
            if ev is None:
                no_event += 1
                continue
            start = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            snap_at = (start - timedelta(minutes=CLOSE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
            d = _get(f"/historical/sports/{SPORT}/events/{ev['id']}/odds",
                     {"regions": "us", "markets": ",".join(MARKETS), "oddsFormat": "american", "date": snap_at}, key, budget)
            if args.probe:
                print(f"PROBE game={gid} date={game['date']} event={ev['id']} ok={d is not None} credits_so_far={budget.spent} "
                      f"summary={json.dumps(summarize(d)) if d else None}", flush=True)
            if d is None:
                fails += 1
                if fails >= 5:
                    raise SystemExit("stopped: 5 consecutive failed calls (dead key?)")
                continue
            fails = 0
            (out / "odds" / f"{gid}.json").write_text(json.dumps({"game": gid, "date": game["date"],
                                                                  "start": ev["commence_time"], "event": ev["id"], "snap": d}),
                                                      encoding="utf-8")
            if i and i % 50 == 0:
                print(f"  {i}/{len(todo)} spent={budget.spent}", flush=True)
    finally:
        print(f"pull: spent {budget.spent} credits over {budget.calls} calls; games without an event={no_event}; "
              f"header remaining present={budget.remaining is not None}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
