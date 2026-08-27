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
PRICES ARE DOLLARS OF PROBABILITY, NOT CENTS AND NOT ODDS
--------------------------------------------------------------------------

VERIFIED 2026-08-23T03:11:22Z by the boot probe, and it corrected me: the
fields are `yes_ask_dollars` / `no_ask_dollars`, not `yes_ask` in cents. A
Kalshi contract settles at $1, so a price in DOLLARS *is* the probability
directly -- 0.62 means the market says 62%, with no division.

**This was a 100x error caught before it shipped.** The first version divided by
100 on the assumption of cents; fed 0.62 it would have returned 0.0062 and
rendered a 62% market as 0.6%, then handed that to a comparison layer that would
have accepted it silently. That is precisely why `probe()` reports the shape
instead of parsing it -- the parser would have "worked".

The value is still not an American price and must never be compared to one
directly: the board speaks American odds, and 0.62 read as odds is meaningless.
Both conversions are exact arithmetic and unit-tested, because they are the part
that does not depend on the endpoint.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "dollars_to_probability",
    "dollars_to_american",
    "probability_to_american",
    "series_from_ticker",
    "is_combinatorial_series",
    "fetch_series",
    "cents_to_probability",
    "cents_to_american",
    "normalize_market",
    "fetch_markets",
    "discover",
    "discover_series",
    "series_matching",
    "probe",
    "KalshiError",
]

# Hosts to try in order. `external-api` is the one the owner supplied from
# Kalshi's own docs and is CORRECT; the other two are hosts I guessed before
# asking, kept only as fallbacks so a future move does not read as an outage.
# The guessed ones going first is exactly the kind of thing that turns "wrong
# base URL" into "venue lists nothing", so the verified host leads.
_BASE_URLS = (
    "https://external-api.kalshi.com/trade-api/v2",
    "https://api.elections.kalshi.com/trade-api/v2",
    "https://trading-api.kalshi.com/trade-api/v2",
)
_MARKETS_PATH = "/markets"
# The CATALOGUE endpoint. Listing markets to learn which series exist is the
# wrong instrument: the first 40,000 open markets were 99.5% parlay
# combinations and TRUNCATED before reaching most single markets, so a sport
# Kalshi genuinely lists can be invisible in it. UNVERIFIED, like everything
# else here was before its first live run -- `discover_series` reports what came
# back rather than assuming, and falls back to the market listing when this path
# is not there.
_SERIES_PATH = "/series"

# The fields this module reads. Named here so the whole schema assumption is one
# object, and so `probe()` can diff it against what actually arrives.
# VERIFIED against the live API 2026-08-23. The previous list was written from
# memory and got 10 of 17 names wrong, including the price fields.
_MARKET_FIELDS = (
    "ticker",
    "event_ticker",
    "market_type",
    "title",
    "yes_sub_title",
    "no_sub_title",
    "status",
    "yes_bid_dollars",
    "yes_ask_dollars",
    "no_bid_dollars",
    "no_ask_dollars",
    "last_price_dollars",
    "previous_price_dollars",
    "volume_fp",
    "volume_24h_fp",
    "open_interest_fp",
    "liquidity_dollars",
    "open_time",
    "close_time",
    "expiration_time",
    "strike_type",
    "custom_strike",
    "result",
    "rules_primary",
    # THE EXCHANGE SHARD THIS MARKET LIVES ON, and the field that explains two
    # days of failed MLB orders. Public, no credential needed -- and it was
    # being DROPPED here, so `SUBMIT_FAILED_MARKET` printed `exchange_index=None`
    # for a market whose raw payload carried `3`.
    #
    # `normalize_market` is an allowlist, which is right: it is why a venue
    # rename shows up as a missing field instead of a silent None. The cost is
    # that a field nobody listed is invisible even when the raw response has it,
    # and the whole diagnosis had to come from a session with unproxied network
    # access reading the payload directly.
    "exchange_index",
)


class KalshiError(RuntimeError):
    """Raised when the fetch cannot be trusted -- never swallowed into an empty list."""


def dollars_to_probability(dollars: Any) -> float | None:
    """A Kalshi price in DOLLARS is the implied probability directly. 0.62 -> 0.62.

    No division: the contract settles at $1, so the price and the probability
    are the same number in different clothes. The earlier cents assumption
    divided by 100 here and would have rendered every market at 1% of its true
    probability.

    Returns None outside (0, 1): 0 and 1 are not tradeable prices, they are a
    settled or absent market, and treating either as a probability produces an
    infinite or zero-payout bet downstream.
    """
    try:
        value = float(dollars)
    except (TypeError, ValueError):
        return None
    if value != value or not (0.0 < value < 1.0):
        return None
    return value


def cents_to_probability(cents: Any) -> float | None:
    """Kept for the cents-denominated fields, if any turn out to exist.

    NOT the main path any more -- the live API returns `*_dollars`. Retained
    rather than deleted because a second price convention appearing later should
    meet an existing tested function instead of a fresh guess.
    """
    try:
        value = float(cents)
    except (TypeError, ValueError):
        return None
    if value != value or not (0.0 < value < 100.0):
        return None
    return value / 100.0


def probability_to_american(probability: float | None) -> int | None:
    """Implied probability -> American odds, so the board's layer can read it.

    THE CONVERSION THE REST OF THIS SYSTEM DEPENDS ON. A raw Kalshi price handed
    to a consumer expecting American odds is meaningless -- 0.62 is not +0.62 of
    anything. Exact arithmetic, and tested.
    """
    if probability is None:
        return None
    if probability >= 0.5:
        # Favourite: negative American odds.
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))


def dollars_to_american(dollars: Any) -> int | None:
    """Kalshi's dollar price straight to American odds."""
    return probability_to_american(dollars_to_probability(dollars))


def cents_to_american(cents: Any) -> int | None:
    """Back-compat for the cents path. See `cents_to_probability`."""
    return probability_to_american(cents_to_probability(cents))


def series_from_ticker(ticker: Any) -> str | None:
    """Kalshi markets carry NO `series_ticker` -- the probe proved that, 2000 of
    2000 absent. The series is the prefix of the ticker before the first dash
    (`KXMLBGAME-25AUG22NYYBOS-NYY` -> `KXMLBGAME`), which is what makes grouping
    possible at all."""
    text = str(ticker or "").strip()
    if not text:
        return None
    head = text.split("-", 1)[0].strip()
    return head or None


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
    out["yes_probability"] = dollars_to_probability(raw.get("yes_ask_dollars"))
    out["yes_american"] = dollars_to_american(raw.get("yes_ask_dollars"))
    out["no_probability"] = dollars_to_probability(raw.get("no_ask_dollars"))
    out["no_american"] = dollars_to_american(raw.get("no_ask_dollars"))
    # Derived, because the API does not supply it -- see `series_from_ticker`.
    out["series"] = series_from_ticker(raw.get("ticker"))
    out["missing_fields"] = missing
    return out


def _signed_headers_or_none(url: str) -> dict[str, str] | None:
    """Auth headers when a credential is configured, else None.

    WHY SIGN A PUBLIC READ. Measured 2026-08-23T22:53Z: both unauthenticated
    hosts returned `http_429` for `/series` and `/markets` while an
    AUTHENTICATED `/portfolio/balance` succeeded in the same minute, from the
    same process. Anonymous reads are on a tighter quota than signed ones, so
    signing a read we are entitled to make is the difference between a catalogue
    we can enumerate and one we cannot.

    Returns None rather than raising when there is no credential: these
    endpoints are genuinely public and must keep working unauthenticated.
    """
    try:
        from syndicate.features.shared.kalshi_auth import auth_headers, load_credentials

        creds = load_credentials()
        if creds.get("status") != "ok":
            return None
        return auth_headers("GET", url, credentials=creds)
    except Exception:
        # A signing failure must never cost us the unauthenticated read that
        # worked before this function existed.
        return None


def _get(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "syndicate/1.0"}
    signed = _signed_headers_or_none(url)
    if signed:
        headers.update(signed)
    request = urllib.request.Request(url, headers=headers)
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


# Multi-leg parlay combinations. MEASURED 2026-08-23: 39,793 of the first
# 40,000 open markets (99.5%) sit in these series, and they TRUNCATED the
# listing -- real single markets are pushed past the page cap by combinatorial
# noise. The board does not bet parlays, so counting them as catalogue would
# both overstate Kalshi's size and hide the markets that matter.
_COMBINATORIAL_SERIES_PREFIXES = ("KXMVECROSSCATEGORY",)


def fetch_market(ticker: str) -> dict[str, Any]:
    """ONE market, live, at the moment of asking. Never the artifact.

    THE ARTIFACT IS NOT A PRICE, it is a price from up to ~26 minutes ago:
    155 series refresh 12 per tick, so the per-series clock never drains.
    Measured 2026-08-24 -- an order was sent at $0.54 because that was the ask
    when the artifact was last written, while the live ask was $0.56. It rested
    unfilled, which is the good outcome; the bad one is filling at a price the
    edge was never computed against.

    So the SUBMIT path reads the venue directly. This costs one request per
    order actually placed -- at most ten a day under the caps -- which is a
    different budget entirely from refreshing every series every cycle.

    Returns `{"status": "ok", "market": {...}}` or a NAMED failure. Absent is
    not zero: a caller must refuse rather than price off nothing.
    """
    key = str(ticker or "").strip()
    if not key:
        return {"status": "error", "reason": "no_ticker"}

    errors: list[str] = []
    for base in _BASE_URLS:
        url = f"{base}{_MARKETS_PATH}/{key}"
        try:
            payload = _get(url)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        raw = payload.get("market") or payload
        if not isinstance(raw, Mapping) or not raw.get("ticker"):
            errors.append(f"unexpected_shape:{sorted(payload)[:6]}")
            continue
        return {"status": "ok", "market": normalize_market(raw), "base": base}
    return {"status": "error", "reason": "; ".join(errors) or "no_base_responded"}


def fetch_event_markets(event_ticker: str) -> dict[str, Any]:
    """The market tickers KALSHI ITSELF lists under one event.

    THE ONE QUESTION LEFT ON `market_not_found`. Measured 2026-08-26T01:18:47Z:
    `GET /markets/KXMLBTOTAL-26AUG251907KCTOR-8` returns 200 with live quotes,
    and `POST /portfolio/events/orders` with that exact ticker, on the SAME
    host, in the same second, returns `market_not_found`. Four hypotheses have
    been measured and killed -- side, market shape, event field, and host.

    What has never been checked is whether the ticker the MARKET endpoint
    answers to is the ticker the ORDER endpoint expects. A market listing can
    resolve an alias; an order book cannot. If this returns tickers that differ
    from ours, that is the whole bug, and it is not a guess -- it is the
    venue's own spelling of its own markets.

    Read-only and unauthenticated, like every other fetch here. Returns a NAMED
    failure rather than raising: this runs inside an exception handler and must
    never replace the real error with its own.
    """
    key = str(event_ticker or "").strip()
    if not key:
        return {"status": "error", "reason": "no_event_ticker"}

    errors: list[str] = []
    for base in _BASE_URLS:
        url = f"{base}/events/{key}?with_nested_markets=true"
        try:
            payload = _get(url)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        event = payload.get("event")
        markets = payload.get("markets")
        if not isinstance(markets, list) and isinstance(event, Mapping):
            markets = event.get("markets")
        if not isinstance(markets, list):
            errors.append(f"unexpected_shape:{sorted(payload)[:6]}")
            continue
        if not markets:
            # AN EMPTY LIST IS NOT AN ANSWER, and accepting one as `status=ok`
            # is what made this probe useless on the run it was built for.
            #
            # Measured 2026-08-26T09:34-11:44Z: `count=0 ours_listed=False` on
            # EIGHT different events whose markets we had just fetched prices
            # for. Read as data, that says Kalshi lists nothing. It actually
            # said the query was wrong -- the same "a null from a query you got
            # wrong is indistinguishable from a null from a quiet system"
            # failure this repo logged hours earlier.
            #
            # So an empty result now REFUSES and carries the payload's own keys
            # and the URL, which is what a reader needs to fix the query rather
            # than mis-trust the venue.
            errors.append(f"empty_markets url={url} keys={sorted(payload)[:8]}")
            continue
        return {
            "status": "ok",
            "base": base,
            "tickers": [
                str(m.get("ticker") or "")
                for m in markets
                if isinstance(m, Mapping)
            ],
        }
    return {"status": "error", "reason": "; ".join(errors) or "no_base_responded"}


def is_combinatorial_series(series: Any) -> bool:
    text = str(series or "").strip().upper()
    return any(text.startswith(prefix) for prefix in _COMBINATORIAL_SERIES_PREFIXES)


def fetch_series(series_ticker: str, *, limit: int = 1000, max_pages: int = 10) -> dict[str, Any]:
    """One series, asked for by name.

    Necessary because the unfiltered listing is 99.5% parlay combinations: the
    single markets this board could actually bet are past the page cap, so
    counting them from `discover()` measures the cap rather than the catalogue.
    Asking per series is the only way to get a true count.
    """
    return fetch_markets(series_ticker=series_ticker, limit=limit, max_pages=max_pages)


def discover_series(*, category: str | None = None) -> dict[str, Any]:
    """What series does Kalshi list, asked DIRECTLY rather than inferred.

    ANSWERS "does Kalshi carry sport X" without paging through parlays. The
    market listing cannot answer it: 39,793 of the first 40,000 open markets
    were multi-leg combinations and the page cap hit before most single markets
    appeared, so a sport that IS listed can be absent from it entirely. Reading
    that absence as "Kalshi does not carry it" is the false negative this whole
    module exists to prevent, and it would be a confident wrong answer.

    The endpoint is UNVERIFIED. So this reports the SHAPE that came back --
    status, keys, count -- rather than parsing it into a confident empty list,
    and a failure is named rather than returned as "no series". Same discipline
    as `probe()`, which is what caught the 100x price error.
    """
    errors: list[str] = []
    for base in _BASE_URLS:
        url = f"{base}{_SERIES_PATH}"
        if category:
            url = f"{url}?category={urllib.parse.quote(str(category))}"
        try:
            payload = _get(url)
        except KalshiError as exc:
            errors.append(f"{base}: {exc}")
            continue

        # The container key is a guess; report which one was found rather than
        # defaulting to an empty list under any of them.
        container = None
        for key in ("series", "series_list", "data"):
            if isinstance(payload.get(key), list):
                container = key
                break
        rows = payload.get(container) if container else []
        tickers = [
            str(row.get("ticker") or row.get("series_ticker") or "").strip()
            for row in rows
            if isinstance(row, Mapping)
        ]
        return {
            "status": "ok",
            "base_url": base,
            "category": category,
            "container_key": container,
            # Top-level keys, so a wrong container guess is visible immediately
            # rather than showing up as a venue that lists nothing.
            "payload_keys": sorted(payload.keys()),
            "count": len(rows),
            "tickers": [t for t in tickers if t],
            # One row's keys, to check the field names before anything parses
            # them. `kalshi_client`'s first live run got 10 of 17 wrong.
            "row_keys": sorted(rows[0].keys()) if rows and isinstance(rows[0], Mapping) else [],
            # ticker -> title. A ticker says what a series is CALLED; the title
            # says what it IS, and "player prop" versus "game line" is the
            # difference between a bet we can grade and one we must refuse.
            "titles": {
                str(row.get("ticker") or row.get("series_ticker") or "").strip(): str(row.get("title") or "")
                for row in rows
                if isinstance(row, Mapping)
            },
        }

    return {"status": "error", "category": category, "errors": errors}


def series_matching(tokens: Sequence[str], tickers: Sequence[str]) -> list[str]:
    """Series whose ticker contains any of `tokens`, upper-cased.

    A SEARCH over tickers Kalshi gave us, never a guess at one. `KXWNBA` typed
    from memory and fetched is an empty page that reads as "not listed"; the
    same string matched against a real catalogue is an answer either way.
    """
    wanted = [str(t).strip().upper() for t in tokens if str(t).strip()]
    return [
        ticker
        for ticker in tickers
        if any(token in str(ticker).strip().upper() for token in wanted)
    ]


def discover(*, limit: int = 1000, max_pages: int = 40) -> dict[str, Any]:
    """What does Kalshi actually list right now, grouped by series?

    THE DISCOVERY CALL, and deliberately UNFILTERED. Fetching by
    `series_ticker` requires knowing the ticker, and guessing one that does not
    exist returns an empty page that looks exactly like a venue listing nothing
    -- the same false negative this whole module exists to avoid. Pulling open
    markets and grouping by `series_ticker` inverts that: the tickers come from
    Kalshi rather than from my memory of their naming.

    `by_series` is the answer to the question the OddsAPI numbers could not
    reach: whether Kalshi lists player props at all, and at what volume.

    The caps were raised after the first live run returned `markets=2000
    pages=10 truncated=True` -- the catalogue is bigger than the page limit, and
    a truncated listing read as the whole thing would understate Kalshi exactly
    the way OddsAPI's feed did.
    """
    report = fetch_markets(status="open", limit=limit, max_pages=max_pages)
    by_series: dict[str, int] = {}
    titled: dict[str, str] = {}
    for market in report.get("markets") or ():
        series = market.get("series") or "<absent>"
        by_series[series] = by_series.get(series, 0) + 1
        # One example title per series, so a ticker like KXMLBGAME is readable
        # without a second lookup.
        if series not in titled and market.get("title"):
            titled[series] = str(market.get("title"))[:80]
    report["by_series"] = dict(sorted(by_series.items(), key=lambda kv: -kv[1]))
    # The catalogue WITHOUT parlay combinations -- what is actually bettable as
    # a single market, which is the only part this board could ever use.
    report["by_series_singles"] = {
        series: count
        for series, count in report["by_series"].items()
        if not is_combinatorial_series(series)
    }
    report["combinatorial_markets"] = sum(
        count for series, count in by_series.items() if is_combinatorial_series(series)
    )
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
