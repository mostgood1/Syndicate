"""Fetch UEFA club-competition RESULTS (UCL / UEL / UECL) from ESPN into per-season CSVs.

    <out-root>/<competition>/history/uefa_results_<season>.csv

Stage 1 input for todo #699 (cross-league offsets and ratings for clubs outside our
leagues). Nothing in production reads these files yet: this is the history source, not a
model. ~2 requests per competition-season-slug, 0.3 s apart (about 60 requests for
2014-2025 across all three competitions).

Usage:
    python scripts/fetch_uefa_history.py --seasons 2021-2025 --out-root data/soccer_source
    python scripts/fetch_uefa_history.py --competition ucl --seasons 2024
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.ingestion.uefa_history import collect  # noqa: E402
from syndicate.features.soccer.ingestion.uefa_history import write_season  # noqa: E402
from syndicate.features.soccer.sources import UEFA_COMPETITIONS  # noqa: E402


def parse_seasons(text: str) -> list[int]:
    text = str(text).strip()
    if "-" in text:
        first, last = (int(part) for part in text.split("-", 1))
        if last < first:
            raise argparse.ArgumentTypeError(f"empty season range {text!r}")
        return list(range(first, last + 1))
    return [int(text)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--competition", choices=sorted(UEFA_COMPETITIONS), action="append",
                        help="Repeatable; default all three.")
    parser.add_argument("--seasons", required=True, type=parse_seasons, help="YYYY or YYYY-YYYY (season start years).")
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    parser.add_argument("--pause-seconds", type=float, default=0.3)
    args = parser.parse_args(argv)

    for competition in args.competition or list(UEFA_COMPETITIONS):
        by_season = collect(competition, args.seasons, pause_seconds=args.pause_seconds)
        for season, rows in sorted(by_season.items()):
            path = write_season(Path(args.out_root), competition, season, rows)
            print(f"UEFA_HISTORY competition={competition} season={season} matches={len(rows)} path={path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
