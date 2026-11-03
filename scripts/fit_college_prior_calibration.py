"""Fit a college league's PRIOR CALIBRATION by hand and print its hold-out (lane wncaab-module, 2026-11-03).

The pregame child refits it once a day (`build_college_pregame_sims.py --refresh-inputs`); this runs the same fit
(`syndicate/features/college_basketball/prior_calibration.refresh_calibration`) for one date and prints what it
found -- the target it used, the coefficients, and the split-sample check (fit on even ESPN event ids, scored on
the odd ones, raw prior vs calibrated, against the closing line and the final).

    python scripts/fit_college_prior_calibration.py --league ncaab --today 2026-11-04 [--write]

Without `--write` nothing is written. Run it on the fleet (SYNDICATE_DATA_ROOT) for a production claim: the
quote logs and slates it reads live there.
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
    from syndicate.features.college_basketball import prior_calibration as pc

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--league", default="ncaab", choices=("ncaab", "wncaab"))
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date(),
                        help="the first game date the fit applies to (it fits on the days before)")
    parser.add_argument("--window-days", type=int, default=pc.WINDOW_DAYS)
    parser.add_argument("--write", action="store_true", help="write prior_calibration_<season>_asof_<today-1>.json")
    args = parser.parse_args(argv)
    _cal, report = pc.refresh_calibration(args.league, today=args.today, window_days=args.window_days, write=args.write)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
