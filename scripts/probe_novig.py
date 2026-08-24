#!/usr/bin/env python3
"""Ask Novig what Novig actually lists, on BOTH tiers, and report the SHAPE
that came back.

RUN THIS BEFORE TRUSTING ANYTHING IN `novig_client`. Tier 2 (the official
OAuth-gated REST) needs `NOVIG_CLIENT_ID` / `NOVIG_CLIENT_SECRET` -- founder-
gated, request from Novig directly, not self-serve. Without them this reports
`credential_unavailable` rather than attempting a call. Tier 1 (the daily CSV
mirror) needs no credential and is checked either way.

    python scripts/probe_novig.py --probe
    python scripts/probe_novig.py --csv markets
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.novig_client import fetch_daily_csv, probe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Novig market data (both tiers).")
    parser.add_argument("--probe", action="store_true", help="report the response shape for both tiers")
    parser.add_argument("--csv", choices=["trades", "markets"], default=None, help="fetch a public daily CSV")
    parser.add_argument("--league", default=None)
    args = parser.parse_args()

    if args.csv:
        report = fetch_daily_csv(args.csv)
        print(
            "[novig] CSV"
            f" name={args.csv}"
            f" status={report.get('status')}"
            f" count={report.get('count')}"
            f" columns={report.get('columns')}"
            f" reason={report.get('reason')}",
            flush=True,
        )
        return 0 if report.get("status") == "ok" else 1

    if args.probe:
        report = probe(league=args.league)
        print("[novig] PROBE " + json.dumps(report, default=str)[:4000], flush=True)
        tier2_ok = (report.get("tier2_official_rest") or {}).get("status") == "ok"
        tier1_ok = (report.get("tier1_daily_csv") or {}).get("status") == "ok"
        return 0 if (tier2_ok or tier1_ok) else 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
