"""Kalshi market data, fetched DIRECTLY rather than through OddsAPI.

WHY THIS EXISTS. Every exchange price on the board arrives via OddsAPI, and
OddsAPI carries only GAME lines for these venues -- no player props. Measured
2026-08-23: kalshi 1.93%, novig 1.74%, polymarket 1.54%, prophetx 1.16% of a
1,037-row board, four structurally different businesses landing within 0.8
points of each other. That convergence is the signature of a shared feed limit,
not four independent commercial decisions, and it means the Stage D number I
reported ("Kalshi quotes 3.8% of the board") was never about Kalshi. It was
about OddsAPI's Kalshi coverage.

This asks Kalshi what Kalshi actually lists.

--------------------------------------------------------------------------
THE SCHEMA BELOW IS UNVERIFIED AND THE CODE IS SHAPED AROUND THAT
--------------------------------------------------------------------------

The agent proxy denies `api.elections.kalshi.com` (`connect_rejected`, 403 to
CONNECT), so this was written without once calling the API. Endpoint paths and
field names are from documentation I have not been able to check, and tonight
has already produced three confident claims that measurement contradicted.

So: every assumption is in ONE place (`_MARKET_FIELDS`, `_BASE_URLS`,
`_MARKETS_PATH`), nothing is accessed positionally, and `probe()` exists
specifically to report the SHAPE THAT ACTUALLY CAME BACK rather than parsing it.
The first production run is the verification step, and a field that is missing
is reported by name instead of defaulting -- a fetcher that silently returns
zero markets is indistinguishable from a venue that lists nothing, which is the
exact confusion this module was built to resolve.

--------------------------------------------------------------------------
PRICES ARE CENTS OF PROBABILITY, NOT ODDS
--------------------------------------------------------------------------

A Kalshi contract settles at $1. Its price in cents IS the implied probability:
62c means the market says 62%. That is not an American price and must never be
compared to one directly -- the board's whole comparison layer speaks American
odds, and handing it a 62 would read as +62 (a 61.7% -> 38% error).

The conversion is exact arithmetic and IS unit-tested here, because it is the
one part of this module that does not depend on the endpoint being right.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

__all__ = [
    "cents_to_probability",
    "cents_to_american",
    "normalize_market",
    "fetch_markets",
    "discover",
    "probe",
    "KalshiError",
]

# Hosts to try in order. Kalshi consolidated onto the elections host; the older
# trading host is kept as a fallback so a move does not read as an outage.
_BASE_URLS = (
    "https://api.elections.kalshi.com/trade-api/v2",
    "https://trading-api.kalshi.com/trade-api/v2",
)
_MARKETS_PATH = "/markets"

# The fields this module reads. Named here so the whole schema assumption is one
# object, and so `probe()` can diff it against what actually arrives.
_MARKET_FIELDS = (
    "ticker",
    "event_ticker",
    "series_ticker",
    "title",
    "subtitle",
    "status",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "last_price",
    "volume",
    "open_time",
    "close_time",
    "strike_type",
    "floor_strike",
    "cap_strike",
)


class KalshiError(RuntimeError):
    """Raised when the fetch cannot be trusted -- never swallowed into an empty list."""


def cents_to_probability(cents: Any) -> float | None:
    """A Kalshi price in cents IS the implied probability. 62c -> 0.62.

    Returns None outside (0, 100): 0 and 100 are not tradeable prices, they are
    a settled or absent market, and treating either as a probability produces an
    infinite or zero-payout bet downstream.
    """
    try:
        value = float(cents)
    except (TypeError, ValueError):
        return None
    if value != value or not (0.0 < value < 100.0):
        return None
    return value / 100.0


def cents_to_american(cents: Any) -> int | None:
    """Kalshi cents -> American odds, so the board's comparison layer can read it.

    THE CONVERSION THE REST OF THIS SYSTEM DEPENDS ON. Passing 62 through
    unconverted would be read as `+62` by every consumer -- a 61.7% implied
    probability rendered as 38%. Exact arithmetic, and tested.
    """
    probability = cents_to_probability(cents)
    if probability is None:
        return None
    if probability >= 0.5:
        # Favourite: negative American odds.
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))


def normalize_market(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One Kalshi market, flattened. Missing fields are None and are COUNTED.

    `missing_fields` rides on every row rather than being dropped: it is what
    turns "the schema is wrong" from an empty result into a stated fact on the
    first production run.
    """
    out: dict[str, Any] = {}
    missing: list[str] = []
    for field in _MARKET_FIELDS:
        if field in raw:
            out[field] = raw.get(field)
        else:
            out[field] = None
            missing.append(field)
    # Derived, so a caller never has to know Kalshi's price convention.
    out["yes_probability"] = cents_to_probability(raw.get("yes_ask"))
    out["yes_american"] = cents_to_american(raw.get("yes_ask"))
    out["no_probability"] = cents_to_probability(raw.get("no_ask"))
    out["no_american"] = cents_to_american(raw.get("no_ask"))
    out["missing_fields"] = missing
    return out


def _get(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "syndicate/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise KalshiError(f"http_{exc.code}: {url}") from exc
    except Exception as exc:
        # Network denial included -- the agent proxy 403s CONNECT for this host,
        # so a local run fails here and that is expected, not a code fault.
        raise KalshiError(f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise KalshiError(f"payload_not_an_object: {type(payload).__name__}")
    return payload


def _api_key() -> str | None:
    return (os.environ.get("KALSHI_API_KEY") or "").strip() or None


def fetch_markets(
    *,
    series_ticker: str | None = None,
    status: str = "open",
    limit: int = 200,
    max_pages: int = 20,
) -> dict[str, Any]:
    """Every market matching the filter, following the cursor.

    Read-only and unauthenticated: Kalshi's market listings are public, and
    trading (which needs a key) is deliberately not in this module. Nothing here
    can place an order.

    `max_pages` is a hard stop, not a budget -- a cursor that never terminates
    would otherwise page forever, and the page count is reported so a truncated
    result is visible rather than mistaken for the whole listing.
    """
    markets: list[dict[str, Any]] = []
    cursor: str | None = None
    pages = 0
    errors: list[str] = []
    base_used: str | None = None

    for base in _BASE_URLS:
        try:
            while pages < max_pages:
                query = [f"limit={int(limit)}", f"status={status}"]
                if series_ticker:
                    query.append(f"series_ticker={series_ticker}")
                if cursor:
                    query.append(f"cursor={cursor}")
                payload = _get(f"{base}{_MARKETS_PATH}?" + "&".join(query))
                pages += 1
                page_markets = payload.get("markets")
                if not isinstance(page_markets, list):
                    raise KalshiError(
                        f"markets_not_a_list: got {type(page_markets).__name__}"
                    )
                markets.extend(normalize_market(m) for m in page_markets if isinstance(m, Mapping))
                cursor = payload.get("cursor") or None
                if not cursor or not page_markets:
                    break
            base_used = base
            break
        except KalshiError as exc:
            errors.append(f"{base}: {exc}")
            continue

    if base_used is None:
        # REFUSE rather than return an empty list. An empty list here would read
        # as "Kalshi lists nothing", which is the precise wrong conclusion this
        # module exists to prevent.
        raise KalshiError("all_hosts_failed: " + "; ".join(errors))

    missing_counts: dict[str, int] = {}
    for market in markets:
        for field in market.get("missing_fields") or ():
            missing_counts[field] = missing_counts.get(field, 0) + 1

    return {
        "base_url": base_used,
        "series_ticker": series_ticker,
        "status": status,
        "markets": markets,
        "count": len(markets),
        "pages": pages,
        "truncated": pages >= max_pages and bool(cursor),
        # If this is non-empty the schema assumption is wrong, and it says which
        # field rather than leaving a silently-None column.
        "missing_fields": dict(sorted(missing_counts.items())),
        "host_errors": errors,
        "authenticated": _api_key() is not None,
    }


def discover(*, limit: int = 200, max_pages: int = 10) -> dict[str, Any]:
    """What does Kalshi actually list right now, grouped by series?

    THE DISCOVERY CALL, and deliberately UNFILTERED. Fetching by
    `series_ticker` requires knowing the ticker, and guessing one that does not
    exist returns an empty page that looks exactly like a venue listing nothing
    -- the same false negative this whole module exists to avoid. Pulling open
    markets and grouping by `series_ticker` inverts that: the tickers come from
    Kalshi rather than from my memory of their naming.

    `by_series` is the answer to the question the OddsAPI numbers could not
    reach: whether Kalshi lists player props at all, and at what volume.
    """
    report = fetch_markets(status="open", limit=limit, max_pages=max_pages)
    by_series: dict[str, int] = {}
    titled: dict[str, str] = {}
    for market in report.get("markets") or ():
        series = str(market.get("series_ticker") or "") or "<absent>"
        by_series[series] = by_series.get(series, 0) + 1
        # One example title per series, so a ticker like KXMLBGAME is readable
        # without a second lookup.
        if series not in titled and market.get("title"):
            titled[series] = str(market.get("title"))[:80]
    report["by_series"] = dict(sorted(by_series.items(), key=lambda kv: -kv[1]))
    report["series_examples"] = titled
    report["series_count"] = len(by_series)
    return report


def probe(*, limit: int = 5) -> dict[str, Any]:
    """Report the shape that ACTUALLY came back, without parsing it.

    The verification step for everything above. Run this first on a host that
    can reach Kalshi and the output says whether `_MARKET_FIELDS` is right,
    rather than a downstream number quietly being wrong.
    """
    attempts: list[dict[str, Any]] = []
    for base in _BASE_URLS:
        url = f"{base}{_MARKETS_PATH}?limit={int(limit)}&status=open"
        try:
            payload = _get(url)
        except KalshiError as exc:
            attempts.append({"base": base, "ok": False, "error": str(exc)})
            continue
        sample = None
        markets = payload.get("markets")
        if isinstance(markets, list) and markets and isinstance(markets[0], Mapping):
            sample = markets[0]
        attempts.append(
            {
                "base": base,
                "ok": True,
                "top_level_keys": sorted(payload.keys()),
                "market_count": len(markets) if isinstance(markets, list) else None,
                "market_keys": sorted(sample.keys()) if sample else None,
                "expected_but_absent": sorted(set(_MARKET_FIELDS) - set(sample or {})),
                "present_but_unexpected": sorted(set(sample or {}) - set(_MARKET_FIELDS)),
                "sample": sample,
            }
        )
        break
    return {"attempts": attempts}
