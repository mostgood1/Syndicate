#!/usr/bin/env python3
"""Check whether OG.com ("Crypto.com OG") has shipped a public market-data
API yet. See `cryptocom_client.py`'s header: as of the 2026-08-24 research
behind this module, it had not -- REST/WebSocket were listed "coming soon" on
Crypto.com's own Exchange API page, with only FIX (institutional) available.

This is the one probe script in this lane that is worth RE-RUNNING
periodically rather than only once -- "coming soon" is a moving target.

    python scripts/probe_cryptocom.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.cryptocom_client import FINDING, probe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check OG.com's API-landing-page status.")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    print("[cryptocom_og] FINDING " + json.dumps(FINDING, default=str), flush=True)

    result = probe()
    print(
        "[cryptocom_og] PROBE"
        f" status={result.get('status')}"
        f" http_status={result.get('http_status')}"
        f" mentions_coming_soon={result.get('mentions_coming_soon')}"
        f" error={result.get('error')}",
        flush=True,
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"[cryptocom_og] WROTE {out} bytes={out.stat().st_size}", flush=True)
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
