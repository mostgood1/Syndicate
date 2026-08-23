"""Refresh Kalshi's own prices for the sports series, on a schedule.

THE PIECE THAT MAKES KALSHI A REAL PRICE SOURCE. `kalshi_discovery` answers
"what does Kalshi list" once per boot; this keeps the PRICES current, which is
what a portfolio decision actually needs. A price fetched at boot and reused for
four hours is not a quote, it is a memory.

--------------------------------------------------------------------------
TWO FETCH STRATEGIES, AND IT REPORTS WHICH ONE WORKED
--------------------------------------------------------------------------

The unfiltered listing is 99.5% multi-leg parlay combinations (39,793 of the
first 40,000, measured 2026-08-23) and it TRUNCATES before reaching most single
markets. So paging everything is not viable: it measures the page cap, not the
catalogue.

The obvious fix is to ask for one series at a time. Whether `series_ticker` is
accepted as a query parameter is NOT something I have verified -- and the
failure mode if it is silently ignored is the worst kind: the request succeeds,
returns the unfiltered firehose, and the first page is all parlays, so the
series looks empty. That reads as "Kalshi delisted it" and is wrong.

So the fetch tries the filter and CHECKS whether it was honoured, by looking at
what came back rather than at the status code. `strategy` on the result says
which path produced the data, and a filter that was ignored is reported as
ignored rather than counted as an empty series.
"""

from __future__ import annotations

import os
from typing import Any

# The single-market sports series found in the live listing, mapped by
# `kalshi_board_join`. Listed explicitly: a series this cannot map is a series
# whose prices nothing could use.
SPORTS_SERIES = ("KXMLBKS", "KXMLBOUTS")


def kalshi_odds_enabled() -> bool:
    """Default ON. Read-only price data, no credential, nothing tradeable."""
    raw = os.environ.get("SYNDICATE_KALSHI_ODDS_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def fetch_series_markets(series: str) -> dict[str, Any]:
    """One series' current markets, by whichever strategy actually works.

    Returns `{"markets": [...], "strategy": ..., "reason": ...}` and never
    raises: one series failing must not cost the others their prices.
    """
    from syndicate.features.shared.kalshi_client import (
        KalshiError,
        fetch_series,
        series_from_ticker,
    )

    try:
        report = fetch_series(series)
    except KalshiError as exc:
        return {"markets": [], "strategy": "failed", "reason": str(exc)}

    markets = report.get("markets") or []
    # DID THE FILTER ACTUALLY APPLY? Checked against the data, not the status
    # code. If the API ignored `series_ticker` we get the unfiltered firehose,
    # whose first page is parlays -- which would look like an empty series.
    matching = [m for m in markets if series_from_ticker(m.get("ticker")) == series]
    if markets and not matching:
        return {
            "markets": [],
            "strategy": "filter_ignored",
            "reason": f"asked for {series}, got {len(markets)} markets none of which are in it",
            "returned": len(markets),
        }
    return {
        "markets": matching,
        "strategy": "series_filter",
        "truncated": bool(report.get("truncated")),
    }


def run_kalshi_odds_refresh(*, force: bool = False) -> dict[str, Any]:
    """Fetch each sports series, join to the board, write the artifact."""
    if not (force or kalshi_odds_enabled()):
        return {"status": "skipped", "reason": "disabled"}

    from syndicate.features.shared.refresh_state_store import reports_root, write_json_file

    per_series: dict[str, Any] = {}
    all_markets: list[dict[str, Any]] = []
    for series in SPORTS_SERIES:
        result = fetch_series_markets(series)
        per_series[series] = {
            "count": len(result.get("markets") or []),
            "strategy": result.get("strategy"),
            "reason": result.get("reason"),
        }
        all_markets.extend(result.get("markets") or [])

    print(
        "[kalshi_odds] FETCHED"
        f" markets={len(all_markets)}"
        # Per series, with the STRATEGY beside each count -- a zero from a
        # working filter and a zero from an ignored one are different facts.
        f" per_series={ {k: (v['count'], v['strategy']) for k, v in per_series.items()} }",
        flush=True,
    )

    payload = {
        "markets": all_markets,
        "per_series": per_series,
        "count": len(all_markets),
    }
    try:
        write_json_file(reports_root() / "intelligence" / "kalshi_markets.json", payload)
    except Exception as exc:
        print(f"[kalshi_odds] WRITE_FAILED error={exc}", flush=True)

    return {"status": "ok", "markets": all_markets, "per_series": per_series}


def join_to_board(markets: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pair Kalshi's real prices with the board, and report the coverage.

    THE NUMBER THIS WHOLE THREAD HAS BEEN CHASING. Every Kalshi coverage figure
    reported before this one was OddsAPI's view of Kalshi -- game lines only,
    1.2-3.8% of the board. This is the first that is about Kalshi.
    """
    from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board

    report = join_kalshi_to_board(markets, rows)
    print(
        "[kalshi_odds] BOARD_JOIN"
        f" kalshi_markets={report.get('kalshi_markets')}"
        f" board_rows={report.get('board_rows')}"
        f" matched={report.get('matched')}"
        # Named refusals: "Kalshi has nothing we bet" and "our join is broken"
        # must never share a number. That confusion is #505.
        f" reasons={report.get('reasons')}",
        flush=True,
    )
    # On a zero-match join, print BOTH SIDES' keys. A count of failures with no
    # way to see the mismatch is the `#505` report, and it took weeks to resolve
    # precisely because nobody could see which field disagreed.
    if not report.get("matched"):
        print(
            "[kalshi_odds] JOIN_KEYS"
            f" kalshi={report.get('kalshi_key_sample')}"
            f" board={report.get('board_key_sample')}"
            f" board_markets={report.get('board_market_vocabulary')}",
            flush=True,
        )
    return report
