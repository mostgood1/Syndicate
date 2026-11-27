"""Write NFL's final-week and final-event archives for weeks that ended before the workers kept them.

    reports_root()/nfl_source/api/game_state_final/game_state_s{season}_t{seasontype}_w{week}.json
    reports_root()/nfl_source/api/player_box_final/player_box_e{event_id}.json

Lane `nfl-request-path-espn` (2026-11-27). Inside a web request, NFL game state
and player boxes are now read from what the workers wrote, never fetched from
ESPN (`syndicate/features/nfl/live_game_state.py`'s docstring says why). The
workers write the archive for a week once they see every game of it final, so
a week that ended before that code loaded has none. This writes it, once.

ARCHIVES ONLY. The keyvalue worker record is never written here (the workers
own it), and a week with any game not final writes nothing: an archive must
never pin a week that can still move. A file that already exists is kept.

One scoreboard GET per week and one summary GET per final game, serially.
Run it at low priority on the fleet host (`nice -n 19`), against the fleet's
`SYNDICATE_REPORTS_ROOT`.

    python scripts/backfill_nfl_final_archives.py --season 2026 --seasontype 2 --weeks 1-11
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _weeks(text: str) -> list[int]:
    out: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, _, high = part.partition("-")
            out.extend(range(int(low), int(high) + 1))
        else:
            out.append(int(part))
    return out


def backfill_week(season: int, seasontype: int, week: int, *, player_box: bool = True, pause: float = 0.2) -> dict:
    from syndicate.features.nfl import live_game_state as lgs
    from syndicate.features.nfl import live_player_box as lpb

    payload = lgs._fetch_scoreboard(season, seasontype, week)
    if payload is None:
        return {"week": week, "status": "error", "reason": "scoreboard_unreachable"}
    states = []
    for event in payload.get("events") or []:
        if isinstance(event, dict):
            state = lgs._state_from_event(event)
            if state is not None:
                states.append(state)
    index = lgs._index_from_states(states)
    week_result = lgs.persist_week(season, seasontype, week, index, archive_only=True)
    result = {"week": week, "status": "ok", **week_result, "boxes_archived": 0, "boxes_unread": 0}
    if not player_box or not week_result.get("archived"):
        return result
    for state in states:
        event_id = str(state.get("event_id") or "").strip()
        if not event_id:
            continue
        if lpb.final_archive_path(event_id).exists():
            result["boxes_archived"] += 1
            continue
        time.sleep(pause)
        rows = lpb.player_rows_from_summary(lpb._fetch_summary(event_id))
        if rows is None:
            result["boxes_unread"] += 1
            continue
        if lpb.persist_event(event_id, rows, final=True, archive_only=True).get("archived"):
            result["boxes_archived"] += 1
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--seasontype", type=int, default=2, help="ESPN: 1 preseason, 2 regular, 3 postseason")
    parser.add_argument("--weeks", required=True, help="e.g. 1-11 or 1,2,5")
    parser.add_argument("--no-player-box", action="store_true", help="archive game state only")
    args = parser.parse_args()

    from syndicate.features.shared.refresh_state_store import reports_root

    print(f"[backfill_nfl_final_archives] reports_root={reports_root()}", flush=True)
    failures = 0
    for week in _weeks(args.weeks):
        result = backfill_week(args.season, args.seasontype, week, player_box=not args.no_player_box)
        failures += result.get("status") != "ok"
        print(json.dumps({"season": args.season, "seasontype": args.seasontype, **result}, sort_keys=True), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
