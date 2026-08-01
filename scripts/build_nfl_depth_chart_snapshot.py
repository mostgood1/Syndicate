"""Build the real NFL depth-chart snapshot from nflverse's depth_charts release.

Replaces the previous 2-row demo-fixture stub
(data/nfl_source/source_artifacts/data/processed/depth/depth_{season}_snapshot.csv),
which had no real-source wiring at all -- confirmed live: nflverse
publishes real, current depth charts (pos_rank per player per team,
updated today) at the same GitHub-releases host this repo already
downloads pbp/player-stats/roster data from.

Usage:
    python scripts/build_nfl_depth_chart_snapshot.py --season 2026
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.ingestion.depth_chart_snapshot_builder import write_depth_snapshot_csv
from syndicate.features.football.ingestion.nflverse_ingestion import load_nflverse_depth_chart
from syndicate.features.football.ingestion.nflverse_ingestion import load_nflverse_roster
from syndicate.features.nfl.sources import default_nfl_source_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--snapshot-date", type=str, default=None)
    parser.add_argument("--output-path", type=Path, default=None)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()

    roster_rows = load_nflverse_roster(args.season)
    all_depth_rows = load_nflverse_depth_chart(args.season)
    # The real nflverse depth_charts release is a full history of daily
    # snapshots (one row per team/player/position per day it was
    # captured), not just today's -- confirmed live: the same real player
    # appears under many different `dt` values, and different teams'
    # snapshots aren't captured at the exact same timestamp. Keep only
    # each TEAM's own most recent date (not one global max, which would
    # keep only whichever single team happens to have the lexicographically
    # latest timestamp and silently drop every other team) so this is a
    # real current-state snapshot per team, not every historical date at
    # once (which fails validate_depth_snapshot_rows's duplicate-id check
    # by design -- a real player genuinely shouldn't appear twice in a
    # single point-in-time snapshot).
    latest_dt_by_team: dict[str, str] = {}
    for row in all_depth_rows:
        team = row.get("team") or ""
        dt = row.get("dt") or ""
        if dt > latest_dt_by_team.get(team, ""):
            latest_dt_by_team[team] = dt
    same_date_rows = [row for row in all_depth_rows if row.get("dt") == latest_dt_by_team.get(row.get("team") or "")]

    # Real depth charts legitimately list one versatile player across
    # several formation-specific position groups at once (e.g. a DB
    # listed under both "Nickel" and "Base 4-3 D") -- real data, not a
    # bug, but a snapshot conceptually wants one row per player (their
    # primary/best-ranked listed role), and validate_depth_snapshot_rows
    # (shared with the demo-fixture tests, not changed here) assumes
    # exactly that. Keep each player's lowest (best) pos_rank row.
    best_row_by_player: dict[str, dict] = {}
    for row in same_date_rows:
        key = row.get("gsis_id") or row.get("player_name") or ""
        if not key:
            continue
        try:
            rank = int(row.get("pos_rank") or 999)
        except (TypeError, ValueError):
            rank = 999
        current = best_row_by_player.get(key)
        if current is None or rank < int(current.get("pos_rank") or 999):
            best_row_by_player[key] = row
    depth_rows = list(best_row_by_player.values())
    source_file = str(default_nfl_source_root() / "tracking" / "nflverse" / "depth_charts" / f"depth_charts_{args.season}.csv")

    result = write_depth_snapshot_csv(
        season=args.season,
        snapshot_date=args.snapshot_date,
        output_path=args.output_path,
        publish=args.publish,
        roster_rows=roster_rows,
        depth_rows=depth_rows,
        source_file=source_file,
    )
    print(f"season={args.season}")
    print(f"roster_rows_loaded={len(roster_rows)}")
    print(f"depth_rows_loaded={len(depth_rows)}")
    print(f"rows_written={len(result.rows)}")
    print(f"output_path={result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
