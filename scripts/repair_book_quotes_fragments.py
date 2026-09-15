"""Remove splice fragments from book_quotes shards, OUT OF PROCESS (P3).

Spawned by `POST /api/ops/book-quotes/repair` on web, for the same reason the
merge runs in `merge_published_artifact.py`: a child returns its memory on exit,
and web does no heavy work in-process. DRY RUN unless `--apply`.

Usage:
    py -3 scripts/repair_book_quotes_fragments.py --data-root D --sports mlb,soccer --since 2026-09-01
    py -3 scripts/repair_book_quotes_fragments.py --data-root D --sports mlb --since 2026-09-01 --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.book_quotes_repair import repair_book_quotes_shards  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--sports", required=True, help="comma-separated, e.g. mlb,soccer,nfl,ncaaf")
    ap.add_argument("--since", required=True, help="first shard date, YYYY-MM-DD")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    totals = repair_book_quotes_shards(Path(args.data_root), sports=sports, since=args.since, apply=args.apply)
    return 1 if totals.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())
