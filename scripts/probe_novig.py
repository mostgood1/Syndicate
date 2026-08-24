#!/usr/bin/env python3
"""Ask Novig what Novig actually lists, on BOTH tiers, and report the SHAPE
that came back.

RUN THIS BEFORE TRUSTING ANYTHING IN `novig_client`. Tier 2 (the official
OAuth-gated REST) needs `NOVIG_CLIENT_ID` / `NOVIG_CLIENT_SECRET` -- founder-
gated, request from Novig directly, not self-serve. Without them this reports
`credential_unavailable` rather than attempting a call. Tier 1 (the daily CSV
mirror, `data.novig.com/reporting/trade-data/...`) needs no credential and is
checked either way -- files are DATED, so `--csv` resolves the latest
published date via the index unless `--date` is given explicitly.

    python scripts/probe_novig.py --probe
    python scripts/probe_novig.py --csv markets
    python scripts/probe_novig.py --csv trades --date 2026-08-23
    python scripts/probe_novig.py --index
    python scripts/probe_novig.py --snapshot
    python scripts/probe_novig.py --refresh

`--refresh` runs `pipeline/novig_odds_refresh.py`'s ACTUAL cadence-aware
pipeline (the one `SYNDICATE_NOVIG_ODDS_REFRESH_ON_BOOT=1` starts as a
recurring background loop) once, with `force=True` -- the manual trigger for
testing the pipeline without waiting for its hourly clock.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.novig_client import (  # noqa: E402
    fetch_daily_csv,
    fetch_latest_markets_snapshot,
    fetch_trade_data_index,
    latest_market_date,
    probe,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Novig market data (both tiers).")
    parser.add_argument("--probe", action="store_true", help="report the response shape for both tiers")
    parser.add_argument("--index", action="store_true", help="fetch the trade-data manifest (available dates)")
    parser.add_argument("--csv", choices=["trades", "markets"], default=None, help="fetch a public daily CSV")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; defaults to the latest published date for --csv")
    parser.add_argument(
        "--snapshot", action="store_true", help="fetch_latest_markets_snapshot() -- the odds-population entry point"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="run the cadence-aware refresh pipeline once, forced"
    )
    parser.add_argument("--league", default=None)
    args = parser.parse_args()

    if args.refresh:
        from pipeline.novig_odds_refresh import run_novig_odds_refresh

        report = run_novig_odds_refresh(force=True)
        snapshot = report.get("snapshot") or {}
        print(
            "[novig] REFRESH"
            f" status={report.get('status')}"
            f" date={snapshot.get('date')}"
            f" count={snapshot.get('count')}"
            f" is_stale_by_days={snapshot.get('is_stale_by_days')}"
            f" reason={report.get('reason')}",
            flush=True,
        )
        return 0 if report.get("status") in ("ok", "cached") else 1

    if args.index:
        report = fetch_trade_data_index()
        print(
            "[novig] INDEX"
            f" status={report.get('status')}"
            f" dates={len(report.get('dates') or [])}"
            f" market_dates={len(report.get('market_dates') or [])}"
            f" latest_market_date={(report.get('market_dates') or [None])[-1]}"
            f" reason={report.get('reason')}",
            flush=True,
        )
        return 0 if report.get("status") == "ok" else 1

    if args.snapshot:
        report = fetch_latest_markets_snapshot()
        print(
            "[novig] SNAPSHOT"
            f" status={report.get('status')}"
            f" date={report.get('date')}"
            f" is_stale_by_days={report.get('is_stale_by_days')}"
            f" count={report.get('count')}"
            f" reason={report.get('reason')}",
            flush=True,
        )
        return 0 if report.get("status") == "ok" else 1

    if args.csv:
        date = args.date
        if not date:
            resolved = latest_market_date()
            if resolved.get("status") != "ok":
                print(f"[novig] CSV name={args.csv} status=error reason=no_date_resolved:{resolved.get('reason')}", flush=True)
                return 1
            date = resolved["date"]
        report = fetch_daily_csv(args.csv, date)
        print(
            "[novig] CSV"
            f" name={args.csv}"
            f" date={date}"
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
