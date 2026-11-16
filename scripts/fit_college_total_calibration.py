"""Fit a college league's per-line TOTALS calibration by hand and print it (lane ncaab-total-overprojection, #816).

The pregame child refits it once a day (`build_college_pregame_sims.py --refresh-inputs`); this runs the same fit
(`syndicate/features/college_basketball/total_prob_calibration.refresh`) for one date and prints, per phase
(pregame at the close, live from the game-line ledger), the level `a`, the share of disagreement `c`, their errors,
the in-sample Brier (market / raw / calibrated) and the walk-forward (fit on earlier dates, score the next).

    python scripts/fit_college_total_calibration.py --league ncaab --today 2026-11-17 [--write]

Without `--write` nothing is written. Run it on the fleet (SYNDICATE_DATA_ROOT): the ledgers, slates, sims and quote
logs it reads live there.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv: list[str] | None = None) -> int:
    from syndicate.features.college_basketball import total_prob_calibration as tpc

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--league", default="ncaab", choices=tpc.LEAGUES)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date(),
                        help="the first game date the fit applies to (it fits on the days before)")
    parser.add_argument("--window-days", type=int, default=tpc.WINDOW_DAYS)
    parser.add_argument("--floor", type=dt.date.fromisoformat, default=tpc.FIT_FLOOR, help="earliest game date fitted")
    parser.add_argument("--write", action="store_true", help="write total_prob_calibration_<season>_asof_<today-1>.json")
    args = parser.parse_args(argv)
    report = tpc.refresh(args.league, today=args.today, window_days=args.window_days, floor=args.floor, write=args.write)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
