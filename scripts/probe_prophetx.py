#!/usr/bin/env python3
"""Ask ProphetX's Affiliate API what it lists, and report the SHAPE that came
back.

RUN THIS BEFORE TRUSTING ANYTHING IN `prophetx_client`. This is a PARTNER-
GATED API -- `PROPHETX_API_TOKEN` must be issued by ProphetX directly (no
self-serve signup exists), and `PROPHETX_API_BASE` should be set once a real
production host is confirmed (this module defaults to the sandbox host only,
deliberately -- see `prophetx_client.py`'s header on why a production URL is
never guessed).

    python scripts/probe_prophetx.py --probe
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.prophetx_client import fetch_markets, probe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe ProphetX's Affiliate API.")
    parser.add_argument("--probe", action="store_true", help="report the response shape only")
    parser.add_argument("--fetch", action="store_true", help="fetch the market listing")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.probe:
        report = probe()
        print("[prophetx] PROBE " + json.dumps(report, default=str)[:4000], flush=True)
        return 0 if report.get("status") == "ok" else 2

    if args.fetch:
        report = fetch_markets()
        print(
            "[prophetx] MARKETS"
            f" status={report.get('status')}"
            f" count={report.get('count')}"
            f" base_url={report.get('base_url')}"
            f" reason={report.get('reason')}",
            flush=True,
        )
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(f"[prophetx] WROTE {out} bytes={out.stat().st_size}", flush=True)
        return 0 if report.get("status") == "ok" else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
