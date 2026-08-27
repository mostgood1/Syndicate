"""Polymarket market data, fetched DIRECTLY -- fully public, no credential.

WHY THIS EXISTS. This lane pulls markets/odds for six venues ahead of the
order-automation phase another session is building for Kalshi
(`kalshi_client.py`, `kalshi_auth.py`, `kalshi_board.py`). Of the six,
Polymarket is the one with a genuinely public, well-documented,
no-authentication read API -- confirmed against Polymarket's own GitHub org
(`Polymarket/agent-skills`, `Polymarket/agents`'s `gamma.py`), not merely
inferred from third-party write-ups the way most of this lane's other modules
had to be. See `.syndicate/scope_2026-08-24_exchange_markets_api_integration.md`
for the per-venue research this module and its siblings are built from.

--------------------------------------------------------------------------
THE SCHEMA BELOW WAS RESEARCHED, NOT CALLED -- SAME DISCIPLINE AS KALSHI
--------------------------------------------------------------------------

The agent proxy denies every venue host in this lane, `gamma-api.polymarket.com`
and `clob.polymarket.com` included (`connect_rejected`, 403 to CONNECT), exactly
as `kalshi_client.py`'s header records for Kalshi. So this was written from
research (WebSearch/WebFetch over Polymarket's own GitHub source and docs
index) rather than a live call, and `kalshi_client`'s first live run corrected
10 of 17 field names and a 100x price error against material written the same
way. So: every assumption is in ONE place (`_MARKET_FIELDS`, `_BASE_URL_GAMMA`,
`_BASE_URL_CLOB`), nothing is read positionally, and `probe()` reports the
SHAPE that actually comes back rather than parsing it.

--------------------------------------------------------------------------
PRICES ARE 0-1 DECIMALS -- PROBABILITY DIRECTLY, LIKE KALSHI'S DOLLARS
--------------------------------------------------------------------------

`outcomePrices` (Gamma) and `/price`, `/midpoint` (CLOB) are decimal strings in
(0, 1): the dollar price of a $1-payout share, which IS the implied probability
with no conversion. Same convention Kalshi's `*_dollars` fields use, unlike
Novig's de-vigged-but-differently-shaped fields or ProphetX's raw American odds
-- each venue in this lane gets its OWN conversion functions rather than a
shared one, because assuming they agree is exactly the kind of cross-venue
contamination `venue_scope.py`'s header warns about for prices.

--------------------------------------------------------------------------
`outcomes` / `outcomePrices` / `clobTokenIds` ARE JSON-ENCODED STRINGS
--------------------------------------------------------------------------

Per the official `Polymarket/agents` `gamma.py` client, these three fields on a
Gamma market object are NOT native JSON arrays -- they are strings containing a
JSON array, index-matched to each other (`outcomes[i]` <-> `outcomePrices[i]`
<-> `clobTokenIds[i]`). `normalize_market` decodes them and reports a decode
failure by name rather than leaving a silently-empty outcome list.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "probability_to_american",
    "outcome_price_to_american",
    "decode_outcomes",
    "normalize_market",
    "fetch_markets",
    "fetch_price",
    "probe",
    "PolymarketError",
]

# Base hosts. Confirmed identically across Polymarket's own `agent-skills` and
# `agents` GitHub repos and the docs-index page titles -- the one fact every
# research source agreed on verbatim for this venue.
_BASE_URL_GAMMA = "https://gamma-api.polymarket.com"
_BASE_URL_CLOB = "https://clob.polymarket.com"

_MARKETS_PATH = "/markets"

# The fields this module reads off a Gamma `/markets` row. Named here so the
# whole schema assumption is one object and `probe()` can diff it against what
# actually arrives -- same discipline `kalshi_client._MARKET_FIELDS` uses, and
# for the same reason: this list was originally RESEARCHED, not called, and
# the Kalshi module's first live run got 10 of 17 field names wrong against
# material written the identical way.
#
# VERIFIED against a live response 2026-08-24T17:24:49Z (refresh-worker boot
# probe, `.syndicate/deploys.md` same date): 16 of 18 fields matched exactly.
# The two that did not are fixed here -- `minimum_tick_size` was actually
# `orderPriceMinTickSize`, `neg_risk` was actually `negRisk`. Every field this
# module's `normalize_market`/`decode_outcomes` actually price off of
# (`outcomes`, `outcomePrices`, `clobTokenIds`, `question`, `conditionId`,
# `active`, `closed`, `volume`, `liquidity`, `endDate`) was already right.
_MARKET_FIELDS = (
    "id",
    "conditionId",
    "questionID",
    "question",
    "slug",
    "outcomes",
    "outcomePrices",
    "clobTokenIds",
    "volume",
    "volume24hr",
    "liquidity",
    "active",
    "closed",
    "archived",
    "endDate",
    "enableOrderBook",
    "orderPriceMinTickSize",
    "negRisk",
)


class PolymarketError(RuntimeError):
    """Raised when the fetch cannot be trusted -- never swallowed into an empty list."""


def probability_to_american(probability: float | None) -> int | None:
    """Implied probability -> American odds, so the board's layer can read it.

    Identical arithmetic to `kalshi_client.probability_to_american` by
    necessity -- this is just what American-odds conversion IS -- but kept as
    its own function rather than imported, matching `kalshi_client`'s own
    choice not to import from `opportunity_signals`: a leaf module usable from
    a bare probe script should not have to pull in the rest of the tree.

    Guards its own range rather than trusting the caller to have validated
    first (unlike `kalshi_client`'s version, which relies on
    `dollars_to_probability` always running first in its own call chain) --
    this function is exported in `__all__` and callable directly, and 0/1
    would otherwise divide by zero instead of refusing.
    """
    if probability is None:
        return None
    if not (0.0 < probability < 1.0):
        return None
    if probability >= 0.5:
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))


def _as_probability(value: Any) -> float | None:
    """A Polymarket outcome price, decoded and range-checked.

    Outside (0, 1): 0 and 1 are a resolved-or-impossible outcome, not a
    tradeable price, and treating either as a probability produces an infinite
    or zero-payout position downstream -- same refusal Kalshi's
    `dollars_to_probability` makes for the same reason.
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or not (0.0 < parsed < 1.0):
        return None
    return parsed


def outcome_price_to_american(value: Any) -> int | None:
    """A raw `outcomePrices[i]` string straight to American odds."""
    return probability_to_american(_as_probability(value))


def decode_outcomes(raw: Mapping[str, Any]) -> dict[str, Any]:
    """`outcomes` / `outcomePrices` / `clobTokenIds`, JSON-decoded and zipped.

    Returns `{"outcomes": [...], "decode_error": None}` or, on a malformed or
    absent field, `{"outcomes": [], "decode_error": "<field>: <reason>"}` --
    NEVER a silent empty list standing in for "the market has no outcomes",
    which is a different and much rarer fact than "the string did not parse".
    """
    names_raw = raw.get("outcomes")
    prices_raw = raw.get("outcomePrices")
    tokens_raw = raw.get("clobTokenIds")

    def _decode(field: str, value: Any) -> tuple[list[Any] | None, str | None]:
        if value is None:
            return None, f"{field}: absent"
        if isinstance(value, list):
            return value, None
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            return None, f"{field}: {type(exc).__name__}"
        if not isinstance(decoded, list):
            return None, f"{field}: decoded_not_a_list ({type(decoded).__name__})"
        return decoded, None

    names, names_err = _decode("outcomes", names_raw)
    prices, prices_err = _decode("outcomePrices", prices_raw)
    tokens, tokens_err = _decode("clobTokenIds", tokens_raw)

    error = names_err or prices_err or tokens_err
    if error:
        return {"outcomes": [], "decode_error": error}

    names = names or []
    prices = prices or []
    tokens = tokens or []
    if not (len(names) == len(prices) == len(tokens)):
        return {
            "outcomes": [],
            "decode_error": (
                f"length_mismatch: outcomes={len(names)} prices={len(prices)} tokens={len(tokens)}"
            ),
        }

    rows = []
    for name, price, token in zip(names, prices, tokens):
        probability = _as_probability(price)
        rows.append(
            {
                "name": name,
                "token_id": token,
                "price": price,
                "probability": probability,
                "american": probability_to_american(probability),
            }
        )
    return {"outcomes": rows, "decode_error": None}


def normalize_market(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One Gamma market row, flattened. Missing fields are None and COUNTED.

    `missing_fields` rides on every row so a wrong field-name guess is a
    stated fact on the first production run rather than a silently-None
    column -- same contract `kalshi_client.normalize_market` makes.
    """
    out: dict[str, Any] = {}
    missing: list[str] = []
    for field in _MARKET_FIELDS:
        if field in raw:
            out[field] = raw.get(field)
        else:
            out[field] = None
            missing.append(field)
    out.update(decode_outcomes(raw))
    out["missing_fields"] = missing
    return out


def _get(url: str, *, timeout: float = 20.0) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "syndicate/1.0"}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise PolymarketError(f"http_{exc.code}: {url}") from exc
    except Exception as exc:
        # Network denial included -- the agent proxy 403s CONNECT for this
        # host, so a local run fails here and that is expected, not a fault.
        raise PolymarketError(f"{type(exc).__name__}: {exc}") from exc
    return payload


def fetch_markets(
    *,
    active: bool = True,
    closed: bool = False,
    limit: int = 200,
    max_pages: int = 20,
) -> dict[str, Any]:
    """Every market matching the filter, offset-paginated.

    Read-only and unauthenticated -- Polymarket's own docs describe market
    discovery and price reads as requiring no API key, wallet, or token.
    Nothing here can place an order.

    `max_pages` is a hard stop, not a budget: an API that never signals "no
    more pages" would otherwise page forever, and the page count rides on the
    result so a truncated listing is visible rather than mistaken for the
    whole catalogue.

    DO NOT RAISE `max_pages` EXPECTING MORE. Offset paging has a hard ceiling
    on this API, measured 2026-08-27: offset 1000 and 2000 return 100 rows each,
    offset 3000+ returns HTTP 200 carrying
    `{"type": "validation error", "error": "offset too large, use
    /markets/keyset for deeper pagination"}`. The server caps page size at 100
    (see the loop), so 20 pages reaches offset 2000 and stops just inside the
    ceiling. Going deeper is a DIFFERENT ENDPOINT (`/markets/keyset`), not a
    bigger number here -- and this function now raises `gamma_refused` naming
    that message rather than failing as an unexplained shape error.
    """
    markets: list[dict[str, Any]] = []
    offset = 0
    pages = 0
    truncated = False

    while pages < max_pages:
        query = f"limit={int(limit)}&offset={offset}&active={'true' if active else 'false'}&closed={'true' if closed else 'false'}"
        payload = _get(f"{_BASE_URL_GAMMA}{_MARKETS_PATH}?{query}")
        pages += 1
        # Gamma answers a refused query with 200 + `{"type": ..., "error": ...}`,
        # not an HTTP error. Named here so the reason reaches the caller instead
        # of being flattened into `unexpected_shape: got dict`, which says
        # nothing about WHY. The one that matters is the offset ceiling; see the
        # measurement below.
        if isinstance(payload, dict) and payload.get("error"):
            raise PolymarketError(
                f"gamma_refused: {payload.get('error')} at offset={offset}"
            )
        if isinstance(payload, dict):
            page_rows = payload.get("data") if isinstance(payload.get("data"), list) else None
        else:
            page_rows = payload if isinstance(payload, list) else None
        if page_rows is None:
            raise PolymarketError(
                f"unexpected_shape: got {type(payload).__name__} at offset={offset}"
            )
        # END OF CATALOGUE IS AN EMPTY PAGE, NOT A SHORT ONE.
        #
        # This used to `break` on `len(page_rows) < limit` and advance `offset`
        # by `limit`. Both halves were wrong, because THE SERVER CAPS PAGE SIZE
        # AND IGNORES A LARGER `limit`. Measured against the live API
        # 2026-08-27:
        #     asked limit=100 -> 100 rows
        #     asked limit=200 -> 100 rows
        #     asked limit=500 -> 100 rows
        # The default `limit` is 200, so `len(page_rows) < limit` was true on
        # EVERY page and the loop always stopped after the first one. `truncated`
        # is set only when `max_pages` is exhausted, so the result reported
        # `truncated=False` -- A 100-ROW SLICE PRESENTED AS THE WHOLE CATALOGUE.
        # Production: `POLYMARKET_CATALOGUE count=100 truncated=False` on all ten
        # live-odds-worker boots in 17h.
        #
        # Fixing only the break condition would have been WORSE than the bug:
        # advancing `offset` by `limit` (200) while the server returns 100 skips
        # rows 100-199 of every page. The stride must be what we RECEIVED.
        if not page_rows:
            break
        markets.extend(normalize_market(m) for m in page_rows if isinstance(m, Mapping))
        offset += len(page_rows)
    else:
        truncated = True

    missing_counts: dict[str, int] = {}
    decode_errors = 0
    for market in markets:
        for field in market.get("missing_fields") or ():
            missing_counts[field] = missing_counts.get(field, 0) + 1
        if market.get("decode_error"):
            decode_errors += 1

    return {
        "base_url": _BASE_URL_GAMMA,
        "active": active,
        "closed": closed,
        "markets": markets,
        "count": len(markets),
        "pages": pages,
        "truncated": truncated,
        "missing_fields": dict(sorted(missing_counts.items())),
        "decode_errors": decode_errors,
    }


def fetch_price(token_id: str, *, side: str = "BUY") -> dict[str, Any]:
    """ONE outcome token's live CLOB price. Never the cached listing.

    `side="BUY"` reads the best ask, `side="SELL"` the best bid, per the
    endpoint's own documented semantics -- UNVERIFIED against a live call
    (see module header), so this is deliberately named after the venue's
    documented parameter rather than pre-resolved to "ask"/"bid" on our side,
    to keep the one place that could be wrong visible.
    """
    key = str(token_id or "").strip()
    if not key:
        return {"status": "error", "reason": "no_token_id"}
    side_norm = str(side or "").strip().upper()
    if side_norm not in ("BUY", "SELL"):
        return {"status": "error", "reason": "invalid_side"}
    url = f"{_BASE_URL_CLOB}/price?token_id={key}&side={side_norm}"
    try:
        payload = _get(url)
    except PolymarketError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    if not isinstance(payload, Mapping) or "price" not in payload:
        return {"status": "error", "reason": f"unexpected_shape:{sorted(payload) if isinstance(payload, Mapping) else type(payload).__name__}"}
    probability = _as_probability(payload.get("price"))
    return {
        "status": "ok",
        "token_id": key,
        "side": side_norm,
        "price": payload.get("price"),
        "probability": probability,
        "american": probability_to_american(probability),
        "url": url,
    }


def probe(*, limit: int = 5) -> dict[str, Any]:
    """Report the shape that ACTUALLY comes back, without parsing it.

    Run this first, from a host that can reach Polymarket, before trusting
    `_MARKET_FIELDS`. Same role `kalshi_client.probe()` plays, which is what
    caught the 100x price error and the ten wrong field names before either
    shipped.
    """
    url = f"{_BASE_URL_GAMMA}{_MARKETS_PATH}?limit={int(limit)}&active=true"
    try:
        payload = _get(url)
    except PolymarketError as exc:
        return {"base_url": _BASE_URL_GAMMA, "ok": False, "error": str(exc)}
    rows = payload.get("data") if isinstance(payload, Mapping) else payload
    sample = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], Mapping) else None
    return {
        "base_url": _BASE_URL_GAMMA,
        "ok": True,
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, Mapping) else None,
        "market_count": len(rows) if isinstance(rows, list) else None,
        "market_keys": sorted(sample.keys()) if sample else None,
        "expected_but_absent": sorted(set(_MARKET_FIELDS) - set(sample or {})),
        "present_but_unexpected": sorted(set(sample or {}) - set(_MARKET_FIELDS)),
        "sample": sample,
    }
