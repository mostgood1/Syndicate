#!/usr/bin/env python3
"""Report Coinbase Predict's status -- THERE IS NO COINBASE-SPECIFIC ENDPOINT
TO PROBE. See `coinbase_client.py`'s header: Coinbase Predict is a broker
layer over Kalshi's own exchange. This script prints the finding and, when
`--via-kalshi` is passed, asks Kalshi's own client what it lists (the honest
answer to "what does Coinbase Predict show").

    python scripts/probe_coinbase.py
    python scripts/probe_coinbase.py --via-kalshi
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.coinbase_client import (  # noqa: E402
    FINDING,
    discover_via_kalshi,
    probe,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Coinbase Predict's API status.")
    parser.add_argument("--via-kalshi", action="store_true", help="ask Kalshi's client what it lists")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    print("[coinbase] FINDING " + json.dumps(FINDING, default=str), flush=True)

    if args.via_kalshi:
        report = discover_via_kalshi()
        print(
            "[coinbase] VIA_KALSHI"
            f" status={report.get('status')}"
            f" series_count={report.get('series_count')}"
            f" reason={report.get('reason')}",
            flush=True,
        )
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(f"[coinbase] WROTE {out} bytes={out.stat().st_size}", flush=True)
        return 0 if report.get("status") == "ok" else 1

    result = probe()
    print("[coinbase] PROBE " + json.dumps(result, default=str)[:4000], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
