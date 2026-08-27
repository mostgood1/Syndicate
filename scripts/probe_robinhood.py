#!/usr/bin/env python3
"""Report Robinhood event contracts' status -- THERE IS NO ROBINHOOD-SPECIFIC
ENDPOINT TO PROBE. See `robinhood_client.py`'s header: Robinhood has no public
market-data API, official or unofficial, for event contracts; contracts are
sourced from KalshiEX, ForecastEx, and Rothera. This script prints the finding
and, when `--via-kalshi` is passed, asks Kalshi's own client what it lists --
the KalshiEX-sourced SLICE only, not the whole Robinhood catalogue.

    python scripts/probe_robinhood.py
    python scripts/probe_robinhood.py --via-kalshi
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.robinhood_client import (  # noqa: E402
    FINDING,
    discover_via_kalshi,
    probe,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Robinhood event contracts' API status.")
    parser.add_argument("--via-kalshi", action="store_true", help="ask Kalshi's client for the KalshiEX-sourced slice")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    print("[robinhood] FINDING " + json.dumps(FINDING, default=str), flush=True)

    if args.via_kalshi:
        report = discover_via_kalshi()
        print(
            "[robinhood] VIA_KALSHI_PARTIAL"
            f" status={report.get('status')}"
            f" series_count={report.get('series_count')}"
            f" reason={report.get('reason')}",
            flush=True,
        )
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(f"[robinhood] WROTE {out} bytes={out.stat().st_size}", flush=True)
        return 0 if report.get("status") == "ok" else 1

    result = probe()
    print("[robinhood] PROBE " + json.dumps(result, default=str)[:4000], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
