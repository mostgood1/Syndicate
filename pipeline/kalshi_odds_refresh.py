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

--------------------------------------------------------------------------
KALSHI KEEPS ITS OWN CLOCK
--------------------------------------------------------------------------

This used to run once per board build, ~every 3 minutes, because that is when
the caller happened to call it. That is the wrong owner of the cadence in both
directions: OddsAPI's rate limit is what throttles the board build, and Kalshi
is not OddsAPI -- but Kalshi has its own limit, and an unpaced loop over its
series is what produced the `http_429`s on 2026-08-23.

So the interval is stated here, defaults to hourly, and is enforced against a
PERSISTED stamp rather than a process-local one: a worker restart must not
reset the clock and re-fetch, or the cadence is "hourly, plus once per deploy".

When the interval has not elapsed, this returns the LAST FETCHED MARKETS from
the artifact rather than an empty list. `status` says `cached` so the difference
is visible, but the board still gets prices -- skipping the join for 57 minutes
out of every hour would be a strictly worse board in exchange for nothing.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

# The single-market sports series found in the live listing, mapped by
# `kalshi_board_join`. Listed explicitly: a series this cannot map is a series
# whose prices nothing could use.
DEFAULT_SPORTS_SERIES = ("KXMLBKS", "KXMLBOUTS")


def sports_series() -> tuple[str, ...]:
    """Which series to price. Overridable WITHOUT a deploy.

    `discover()` finds new series at runtime, and the useful response to that is
    to start pricing them -- which should not need a code change, because the
    history a new series accumulates only starts when we first ask for it.
    A dashboard env var costs nothing; a `render.yaml` edit fires
    `blueprint_sync` and rewrites every key on every service.
    """
    raw = str(os.environ.get("SYNDICATE_KALSHI_SERIES") or "").strip()
    if not raw:
        return DEFAULT_SPORTS_SERIES
    parsed = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    # An override that parses to nothing is a typo, not an instruction to price
    # nothing. Falling through to an empty tuple would silently stop the feed.
    return parsed or DEFAULT_SPORTS_SERIES


# Kept as a module attribute for callers and tests that read the default set.
SPORTS_SERIES = DEFAULT_SPORTS_SERIES


def kalshi_odds_enabled() -> bool:
    """Default ON. Read-only price data, no credential, nothing tradeable."""
    raw = os.environ.get("SYNDICATE_KALSHI_ODDS_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


DEFAULT_REFRESH_INTERVAL_SECONDS = 3600
# A failed fetch retries sooner than a successful one -- but not immediately.
FAILED_RETRY_SECONDS = 600


def refresh_interval_seconds() -> int:
    """How often to hit Kalshi. Hourly unless told otherwise.

    A bad value falls back to the default rather than to 0. `int("")` raising
    into a bare except that returns 0 would turn a typo into an unpaced loop
    against a venue that rate-limits us -- the failure this gate exists for.
    """
    raw = os.environ.get("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_INTERVAL_SECONDS
    return parsed if parsed >= 0 else DEFAULT_REFRESH_INTERVAL_SECONDS


def markets_artifact_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "kalshi_markets.json"


def _seconds_since(stamp: Any) -> float | None:
    if not stamp:
        return None
    try:
        parsed = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


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
    """Fetch each sports series on Kalshi's own cadence, record, write.

    `force=True` bypasses BOTH the enable flag and the interval gate -- that is
    what a manual probe wants, and what the hourly cron would want if the
    interval were ever raised above the cron period.
    """
    if not (force or kalshi_odds_enabled()):
        return {"status": "skipped", "reason": "disabled"}

    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    path = markets_artifact_path()
    try:
        cached = read_json_file(path) or {}
    except Exception:
        cached = {}

    interval = refresh_interval_seconds()
    age = _seconds_since(cached.get("fetched_at"))

    # A FAILED fetch gets its own, shorter clock. It cannot use `fetched_at`,
    # because stamping that would blank the board for an hour; but it must not
    # be ungated either, or a venue that is 403ing or rate-limiting us gets
    # retried every board build -- every ~3 minutes -- which is how the
    # 2026-08-23 `http_429`s happened in the first place. So failures record
    # `attempted_at` and back off on that.
    if not force and interval > 0:
        since_attempt = _seconds_since(cached.get("attempted_at"))
        retry_after = min(interval, FAILED_RETRY_SECONDS)
        if since_attempt is not None and since_attempt < retry_after and (
            age is None or age >= interval
        ):
            print(
                "[kalshi_odds] BACKOFF"
                f" since_failed_s={int(since_attempt)}"
                f" retry_after_s={retry_after}"
                f" cached_markets={len(cached.get('markets') or [])}",
                flush=True,
            )
            return {
                "status": "backoff",
                "markets": cached.get("markets") or [],
                "per_series": cached.get("per_series") or {},
            }

    if not force and interval > 0 and age is not None and age < interval:
        cached_markets = cached.get("markets") or []
        # CACHED, not skipped, and it says so. The board still gets prices; what
        # it does not get is a fresh HTTP call. Reporting this as a skip would
        # make a working gate look like a broken fetch.
        print(
            "[kalshi_odds] CACHED"
            f" markets={len(cached_markets)}"
            f" age_s={int(age)}"
            f" interval_s={interval}",
            flush=True,
        )
        return {
            "status": "cached",
            "markets": cached_markets,
            "per_series": cached.get("per_series") or {},
            "age_seconds": int(age),
        }

    per_series: dict[str, Any] = {}
    all_markets: list[dict[str, Any]] = []
    for series in sports_series():
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
        f" interval_s={interval}"
        f" prev_age_s={int(age) if age is not None else None}"
        # Per series, with the STRATEGY beside each count -- a zero from a
        # working filter and a zero from an ignored one are different facts.
        f" per_series={ {k: (v['count'], v['strategy']) for k, v in per_series.items()} }",
        flush=True,
    )

    if not all_markets:
        # DO NOT stamp `fetched_at` on a fetch that returned nothing, and do not
        # overwrite the cached markets with an empty list. A failed call would
        # otherwise both blank the board AND start the clock, so the next 59
        # minutes would serve zero markets from a "fresh" artifact.
        print(
            "[kalshi_odds] EMPTY_FETCH"
            f" keeping_cached={len(cached.get('markets') or [])}"
            f" retry_after_s={min(interval, FAILED_RETRY_SECONDS) if interval > 0 else 0}",
            flush=True,
        )
        failed = dict(cached)
        failed["attempted_at"] = _now_stamp()
        failed["last_failure_per_series"] = per_series
        try:
            write_json_file(path, failed)
        except Exception as exc:
            print(f"[kalshi_odds] BACKOFF_WRITE_FAILED error={exc}", flush=True)
        return {
            "status": "empty",
            "markets": cached.get("markets") or [],
            "per_series": per_series,
        }

    record_and_report(all_markets)

    payload = {
        "markets": all_markets,
        "per_series": per_series,
        "count": len(all_markets),
        "fetched_at": _now_stamp(),
        # `attempted_at` tracks `fetched_at` on success, so a past failure's
        # backoff cannot outlive the failure that caused it.
        "attempted_at": _now_stamp(),
    }
    try:
        write_json_file(path, payload)
    except Exception as exc:
        print(f"[kalshi_odds] WRITE_FAILED error={exc}", flush=True)

    return {"status": "ok", "markets": all_markets, "per_series": per_series}


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_and_report(markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep the price point, then say what has moved and what closes when.

    Wrapped and non-fatal: a history write failing must not cost the board the
    prices it just fetched. It is reported rather than swallowed -- a silent
    history failure looks identical to "nothing has moved yet" forever.
    """
    from syndicate.features.shared.kalshi_board import (
        board_by_game_date,
        movement_report,
        record_snapshot,
    )

    try:
        recorded = record_snapshot(markets)
    except Exception as exc:
        print(f"[kalshi_odds] HISTORY_FAILED error={exc}", flush=True)
        return {"status": "error"}

    print(
        "[kalshi_odds] HISTORY"
        f" status={recorded.get('status')}"
        f" opened={recorded.get('opened')}"
        f" appended={recorded.get('appended')}"
        f" unchanged={recorded.get('unchanged')}"
        f" tickers={recorded.get('tickers')}"
        f" trimmed_points={recorded.get('trimmed_points')}"
        f" trimmed_tickers={recorded.get('trimmed_tickers')}",
        flush=True,
    )

    dates = board_by_game_date(markets)
    print(f"[kalshi_odds] BY_GAME_DATE {dates.get('by_date_series')}", flush=True)

    try:
        moves = movement_report(top=8)
    except Exception as exc:
        print(f"[kalshi_odds] MOVES_FAILED error={exc}", flush=True)
        return recorded

    print(
        "[kalshi_odds] MOVES"
        f" tracked={moves.get('tickers')}"
        f" moved={moves.get('moved')}"
        f" unmoved={moves.get('unmoved')}"
        # `too_new` is NOT folded into `unmoved`: one observation means we have
        # not watched long enough, which licenses waiting, while unmoved licenses
        # concluding. Same number, opposite decision.
        f" too_new={moves.get('too_new')}",
        flush=True,
    )
    for mover in (moves.get("movers") or [])[:5]:
        print(
            "[kalshi_odds] MOVER"
            f" {mover.get('ticker')}"
            f" open={mover.get('opening_yes')}"
            f" now={mover.get('current_yes')}"
            f" move_pts={mover.get('move_points')}"
            f" n={mover.get('observations')}"
            f" since={mover.get('opened_at')}",
            flush=True,
        )
    return recorded


def join_to_board(
    markets: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Pair Kalshi's real prices with the board, and report the coverage.

    THE NUMBER THIS WHOLE THREAD HAS BEEN CHASING. Every Kalshi coverage figure
    reported before this one was OddsAPI's view of Kalshi -- game lines only,
    1.2-3.8% of the board. This is the first that is about Kalshi.
    """
    from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board

    report = join_kalshi_to_board(markets, rows, selected_date=selected_date)
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
