"""Build the college basketball PREGAME sim artifact for one or more dates (lane wncaab-module, Phase 3).

    python scripts/build_college_pregame_sims.py --league ncaab --dates 2026-11-02,2026-11-03 --budget-seconds 600

Launched by the live-odds-worker (`ncaab/inplay_lane.maybe_launch_pregame_sims`) so it inherits the live
tier's engine switches; see `syndicate/features/college_basketball/pregame_sim.py`. Stops at the budget and
writes what it has; the next launch re-sims only games whose inputs changed. Exit 0 unless the run raised.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv: list[str] | None = None) -> int:
    from syndicate.features.college_basketball.pregame_sim import default_sims, run_pregame_sims

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league", default="ncaab", choices=("ncaab", "wncaab"))
    parser.add_argument("--dates", required=True, help="comma-separated ISO dates (Central slate dates)")
    parser.add_argument("--sims", type=int, default=None, help=f"draws per game (default {default_sims()})")
    parser.add_argument("--budget-seconds", type=float, default=600.0, help="stop starting new games after this long")
    args = parser.parse_args(argv)
    deadline = time.monotonic() + max(1.0, float(args.budget_seconds))
    for date_iso in [d.strip() for d in args.dates.split(",") if d.strip()]:
        run_pregame_sims(date_iso, args.league, sims=args.sims, deadline=deadline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
