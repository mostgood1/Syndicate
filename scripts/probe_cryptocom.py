#!/usr/bin/env python3
"""Has Crypto.com Predictions shipped a SANCTIONED, server-readable market-data
API yet?

See `cryptocom_client.py`'s header. Short version, measured 2026-08-28: the
sports venue is real and priced like Kalshi, its data IS served as JSON, but
only by the consumer app's undocumented Cloudflare-gated internal proxy -- 200
to a challenged browser, 403 to any plain client -- and that JSON carries no
prices. The documented Exchange REST catalogue lists zero event contracts.

This is the one probe script in this lane worth RE-RUNNING periodically rather
than once: the unblock is a venue decision, and the only honest way to track it
is to keep checking.

**Read `unblocked`, not the exit code.** Exit 0 means the probe RAN (at least
one check reached the venue); it does not mean anything shipped. And
`unblocked=True` is a signal to LOOK -- the sanctioned catalogue started
carrying a non-crypto instrument -- not a green light: a human still has to
confirm those rows are sports contracts and carry a price.

    python scripts/probe_cryptocom.py
    python scripts/probe_cryptocom.py --out reports/probes/cryptocom.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.cryptocom_client import FINDING, probe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for a sanctioned, server-readable Crypto.com Predictions API."
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    print("[cryptocom] FINDING " + json.dumps(FINDING, default=str), flush=True)

    result = probe()
    checks = result.get("checks", {})
    exchange = checks.get("exchange_rest", {})
    proxy = checks.get("app_proxy", {})
    instruments = exchange.get("instruments", {}) or {}

    print(
        "[cryptocom] PROBE"
        f" status={result.get('status')}"
        f" unblocked={result.get('unblocked')}"
        f" reason={result.get('blocked_reason')}",
        flush=True,
    )
    # The two readings the conclusion actually rests on, printed separately so
    # a run that is quoted later carries its own evidence rather than a verdict.
    print(
        "[cryptocom] EXCHANGE_REST"
        f" http={exchange.get('http_status')}"
        f" error={exchange.get('error')}"
        f" instruments={instruments.get('instrument_count')}"
        f" non_crypto={instruments.get('non_crypto_count')}"
        f" by_type={json.dumps(instruments.get('by_inst_type') or {})}",
        flush=True,
    )
    print(
        "[cryptocom] APP_PROXY"
        f" http={proxy.get('http_status')}"
        f" error={proxy.get('error')}"
        f" interpretation={proxy.get('interpretation')}",
        flush=True,
    )
    if instruments.get("non_crypto"):
        print(
            "[cryptocom] NON_CRYPTO_ROWS "
            + json.dumps(instruments["non_crypto"][:20], default=str),
            flush=True,
        )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"[cryptocom] WROTE {out} bytes={out.stat().st_size}", flush=True)
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
