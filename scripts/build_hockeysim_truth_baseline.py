"""Build the hockeysim truth baseline from real NHL StatsWeb game feeds.

Producer-side tooling (never called from a request path). Two modes:

  * default (offline): rebuild the baseline from the local landing cache
    (``data/nhl_source/data/truth/raw``) — deterministic, no network.
  * ``--refresh --from YYYY-MM-DD --to YYYY-MM-DD``: fetch finished regular-season games across the
    date range (cached to disk), then aggregate.

Writes the derived snapshot to ``reports/hockeysim/truth_baseline_{season}.json`` (small, committed)
so the calibration targets are durable and auditable without shipping the ~1.7MB raw cache.

Usage:
    py -3 scripts/build_hockeysim_truth_baseline.py
    py -3 scripts/build_hockeysim_truth_baseline.py --refresh --from 2026-01-05 --to 2026-01-18
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import (  # noqa: E402
    NhlStatsWebTruthLoader,
    build_truth_snapshot,
)
_OUT_DIR = _REPO / "reports" / "hockeysim"


def _date_range(a: str, b: str) -> list[str]:
    d0 = dt.date.fromisoformat(a)
    d1 = dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the hockeysim NHL truth baseline")
    ap.add_argument("--refresh", action="store_true", help="fetch from the network (else offline from cache)")
    ap.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD (with --refresh)")
    ap.add_argument("--to", dest="date_to", default=None, help="YYYY-MM-DD (with --refresh)")
    ap.add_argument("--out", default=None, help="output JSON path (default reports/hockeysim/…)")
    args = ap.parse_args()

    loader = NhlStatsWebTruthLoader(rate_limit_per_sec=6.0)
    if args.refresh:
        if not (args.date_from and args.date_to):
            ap.error("--refresh requires --from and --to")
        dates = _date_range(args.date_from, args.date_to)
        print(f"Fetching finished regular-season games for {len(dates)} dates {dates[0]}..{dates[-1]} …")
        records = loader.load_dates(dates, game_types=(2,))
    else:
        print("Rebuilding from local landing cache (offline) …")
        records = loader.load_from_cache()

    if not records:
        print("No records found. Run with --refresh --from/--to to populate the cache first.")
        return 1

    snap = build_truth_snapshot(records)
    payload = snap.to_dict()
    payload["calibration_targets"] = snap.to_calibration_snapshot()

    out_path = Path(args.out) if args.out else _OUT_DIR / f"truth_baseline_{snap.season or 'latest'}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nTruth baseline over {snap.n_games} games ({snap.date_from}..{snap.date_to}):")
    print(json.dumps(payload["metrics"], indent=2))
    print(f"\nWrote {out_path.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
