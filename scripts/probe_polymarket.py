#!/usr/bin/env python3
"""Ask Polymarket what Polymarket actually lists, and report the SHAPE that
came back.

RUN THIS BEFORE TRUSTING ANYTHING IN `polymarket_client`. The field names were
researched, not called -- the agent proxy denies the host from a Claude
session, so a local run of this script is EXPECTED to fail and that failure
says nothing about Polymarket. refresh-worker has outbound access (it already
reaches OddsAPI, statsapi and FotMob) -- that is where the schema gets
verified, same as `scripts/probe_kalshi.py`.

    python scripts/probe_polymarket.py --probe
    python scripts/probe_polymarket.py --active
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.polymarket_client import (  # noqa: E402
    PolymarketError,
    fetch_markets,
    probe,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch or probe Polymarket market data.")
    parser.add_argument("--probe", action="store_true", help="report the response shape only")
    parser.add_argument("--active", action="store_true", help="fetch active markets")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--out", default=None, help="write the fetch result to this path")
    args = parser.parse_args()

    if args.probe:
        report = probe()
        print("[polymarket] PROBE " + json.dumps(report, default=str)[:4000], flush=True)
        return 0 if report.get("ok") else 2

    if args.active:
        try:
            report = fetch_markets(active=True, limit=args.limit, max_pages=args.max_pages)
        except PolymarketError as exc:
            print(f"[polymarket] FETCH_FAILED error={exc}", flush=True)
            return 1
        print(
            "[polymarket] MARKETS"
            f" count={report.get('count')}"
            f" pages={report.get('pages')}"
            f" truncated={report.get('truncated')}"
            f" missing_fields={report.get('missing_fields')}"
            f" decode_errors={report.get('decode_errors')}",
            flush=True,
        )
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(f"[polymarket] WROTE {out} bytes={out.stat().st_size}", flush=True)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
