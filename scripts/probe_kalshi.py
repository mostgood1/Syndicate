#!/usr/bin/env python3
"""Ask Kalshi what Kalshi actually lists, and report the SHAPE that came back.

RUN THIS BEFORE TRUSTING ANYTHING IN `kalshi_client`. The module's endpoint and
field names were written without ever calling the API -- the agent proxy denies
the host from a Claude session (`connect_rejected`, 403 to CONNECT), so a local
run of this script is EXPECTED to fail and that failure says nothing about
Kalshi. refresh-worker has outbound access (it already reaches OddsAPI,
statsapi and FotMob), so this is where the schema gets verified.

    python scripts/probe_kalshi.py --probe
    python scripts/probe_kalshi.py --series KXMLBGAME

`--probe` fetches five markets and prints which expected fields were absent and
which unexpected ones arrived. That output is the answer to "is the schema
right", and it is deliberately a separate mode from the fetch: a parser that
reports its own assumptions as satisfied is not evidence.

WHY THIS MATTERS, in one number. Every exchange price on the board comes through
OddsAPI, which carries game lines only for these venues. Measured 2026-08-23 on
a 1,037-row board: kalshi 1.93%, novig 1.74%, polymarket 1.54%, prophetx 1.16%.
Four different businesses inside 0.8 points of each other is a feed limit, not
four independent decisions -- so the "Kalshi covers 3.8% of our board" figure
was always a statement about OddsAPI. This is how that gets corrected with data
instead of argued about.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.kalshi_client import (  # noqa: E402
    KalshiError,
    fetch_markets,
    probe,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch or probe Kalshi market data.")
    parser.add_argument("--probe", action="store_true", help="report the response shape only")
    parser.add_argument("--series", default=None, help="series ticker, e.g. KXMLBGAME")
    parser.add_argument("--status", default="open")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--out", default=None, help="write the fetch result to this path")
    parser.add_argument(
        "--auth",
        action="store_true",
        help="READ-ONLY signed call to /portfolio/balance. Places nothing.",
    )
    args = parser.parse_args()

    if args.auth:
        # THE FIRST STEP OF A LIVE TEST, and the only one that costs nothing.
        # Signing has never once executed against Kalshi -- the agent proxy 403s
        # CONNECT from a dev container -- and `kalshi_client`'s first live run
        # corrected TEN OF SEVENTEEN field names plus a 100x price error. Assume
        # the same rate here, and find out on a read rather than on an order.
        #
        # `/portfolio/balance` is authenticated and READ-ONLY. There is no
        # argument to this script that places anything.
        from syndicate.features.shared.kalshi_auth import probe_auth

        result = probe_auth()
        print(
            "[kalshi_auth] PROBE"
            f" status={result.get('status')}"
            f" reason={result.get('reason')}"
            f" detail={result.get('detail')}"
            f" url={result.get('url')}"
            # KEYS, not values. A balance is not a secret but there is no reason
            # for it to be in a log line whose job is to confirm a signature.
            f" keys={result.get('keys')}"
            f" balance_present={result.get('balance_present')}",
            flush=True,
        )
        # Non-zero on anything but success, so a wrapper cannot read a failed
        # probe as a green light.
        return 0 if result.get("status") == "ok" else 1

    if args.probe:
        report = probe()
        print("[kalshi] PROBE " + json.dumps(report, default=str)[:4000], flush=True)
        ok = any(a.get("ok") for a in report.get("attempts") or [])
        return 0 if ok else 2

    try:
        report = fetch_markets(
            series_ticker=args.series,
            status=args.status,
            limit=args.limit,
            max_pages=args.max_pages,
        )
    except KalshiError as exc:
        # Loud and non-zero. A fetch that cannot be trusted must not look like a
        # venue with nothing listed.
        print(f"[kalshi] FETCH_FAILED series={args.series} error={exc}", flush=True)
        return 1

    print(
        "[kalshi] MARKETS"
        f" series={report.get('series_ticker')}"
        f" count={report.get('count')}"
        f" pages={report.get('pages')}"
        f" truncated={report.get('truncated')}"
        # Non-empty means the schema assumption is wrong, and says which field.
        f" missing_fields={report.get('missing_fields')}"
        f" base={report.get('base_url')}",
        flush=True,
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"[kalshi] WROTE {out} bytes={out.stat().st_size}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
