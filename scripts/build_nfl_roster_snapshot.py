"""Build the real NFL roster snapshot from nflverse's roster release.

Replaces the previous 2-row demo-fixture stub
(data/nfl_source/source_artifacts/data/processed/rosters/roster_{season}_snapshot.csv)
with real data -- syndicate.features.football.ingestion.roster_snapshot_builder
now defaults to syndicate.features.football.ingestion.nflverse_ingestion.load_nflverse_roster
(the real nflverse `rosters` release, confirmed live: 2,930 real 2026 players)
instead of the weekly player-stats feed (which only populates once games
are played, useless pre-season).

Usage:
    python scripts/build_nfl_roster_snapshot.py --season 2026
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.ingestion.roster_snapshot_builder import write_roster_snapshot_csv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--snapshot-date", type=str, default=None)
    parser.add_argument("--output-path", type=Path, default=None)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()

    result = write_roster_snapshot_csv(
        season=args.season,
        snapshot_date=args.snapshot_date,
        output_path=args.output_path,
        publish=args.publish,
    )
    print(f"season={args.season}")
    print(f"rows_written={len(result.rows)}")
    print(f"source_file={result.source_file}")
    print(f"output_path={result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
