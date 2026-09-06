"""Novig market data -- one PUBLIC path, one CREDENTIAL-GATED path, and one
path this module deliberately does NOT implement.

WHY THIS EXISTS. Same lane as `polymarket_client.py` and
`.syndicate/scope_2026-08-24_exchange_markets_api_integration.md`: pull
markets/odds for six venues ahead of the order-automation phase another
session is building for Kalshi.

--------------------------------------------------------------------------
THREE TIERS OF ACCESS, RESEARCHED (not called -- see below), AND KEPT DISTINCT
--------------------------------------------------------------------------

Research (WebSearch/WebFetch, triangulated across ~15 independent third-party
repos that reference `docs.novig.com` -- the agent proxy 403s CONNECT to both
`docs.novig.com` and `api.novig.us`, same denial `kalshi_client.py`'s header
records for Kalshi) found Novig exposes THREE structurally different things,
and conflating any two of them would misrepresent what this module can
actually do:

1. **`data.novig.com` -- public, no-auth, CDN-served daily CSV mirror**
   (`trades.csv`, `markets.csv`). **RESOLVED 2026-08-24, twice over.** The
   first live call from refresh-worker got `http_403` on a flat
   `{base}/markets.csv` -- a path this module invented from a paraphrase
   ("two anonymized files for every trading day"), not read from real docs.
   The user then supplied the actual documented structure directly:
   **files are DATED and INDEXED, not flat.**

       GET /reporting/trade-data/index.json                -- which dates exist
       GET /reporting/trade-data/{date}/trades.csv          -- one trading day
       GET /reporting/trade-data/{date}/markets.csv         -- one trading day

   The flat path was never going to exist; the 403 was CDN default-deny on a
   missing key, not an auth problem or a wrong header, confirming the
   `diagnose_daily_csv_403` hypothesis that never got to run. That diagnostic
   is RETIRED (deleted, not merely superseded) now that the real shape is
   known rather than guessed at -- keeping it would have meant maintaining
   dead speculative code alongside a definitive fix.

   **THIS IS END-OF-DAY DATA, NOT LIVE ODDS.** Each day "publishes shortly
   after midnight Eastern" for the PRIOR trading day -- a closing-line /
   historical feed. `fetch_latest_markets_snapshot()` exists to populate
   Syndicate's odds from this, and its docstring repeats this warning because
   presenting yesterday's close as a current price is the exact "stale data
   read as fresh" failure this repo's own `CLAUDE.md` names as a standing
   trap (`Render is the source of truth` section).
2. **The official "NBX API"** (`docs.novig.com`, REST under
   `api.novig.us/nbx/v1|v2`, OAuth2 client-credentials) -- Novig's own
   documented, versioned, supported API. Confirmed by multiple independent
   sources to be **founder-gated**: credentials are requested directly from
   Novig, not self-serve. `fetch_open_markets()` implements THIS tier and
   REFUSES BY NAME (`no_credential`) without `NOVIG_CLIENT_ID` /
   `NOVIG_CLIENT_SECRET` -- it does not fall back to anything else.
3. **An undocumented, unauthenticated Hasura GraphQL backend**
   (`api.novig.us/v1/graphql`) that several independent third-party scrapers
   use by reverse-engineering Novig's own consumer app. **Deliberately NOT
   implemented here.** It is not published, not supported, can change without
   notice, and its terms-of-service status for third-party read access is
   explicitly unclear in every source that mentions it. Building durable
   Syndicate infrastructure on an app-internal endpoint we were not given is a
   different kind of risk than an unverified-but-documented schema, and this
   module does not take it. If Novig ever documents or grants access to this
   surface, it belongs in tier 2, not smuggled in as tier 1.

--------------------------------------------------------------------------
PRICES ARE PROBABILITY, NOT AMERICAN ODDS -- NOW CONFIRMED ON THE WRITE SIDE TOO
--------------------------------------------------------------------------

Two independent third-party sources originally described Novig's outcome
`last` / `available` READ fields as de-vigged probabilities (over + under =~
1.0). **CORRECTED FROM "corroborated-but-unread" 2026-08-24**: real
`docs.novig.com` content for the ORDER-PLACEMENT contract documents `price`
explicitly as "decimal probability, up to 3 decimal places" -- the same
convention, now confirmed independently on the write side rather than only
inferred from the read side. That is what `probability_to_american` below
assumes. `probe()` still exists to check the READ fields' exact names
against a live response -- the unit convention is settled, the field names
are not.

--------------------------------------------------------------------------
ORDER SIZE IS `qty` -- MINIMAL CURRENCY UNITS, NOT DOLLARS AND NOT CONTRACTS
--------------------------------------------------------------------------

CONFIRMED from the same real content: `POST /emm/orders/place` takes
`outcomeId` (UUID), `price` (decimal probability), `qty` (positive integer,
MINIMAL CURRENCY UNITS -- for `currency: "CASH"`, 1 unit = $0.01, so a $5.00
order sends `qty: 500`; for `currency: "COIN"`, 1 unit = 1 Novig Coin, a
SEPARATE, non-real-money denomination), `currency` (`"CASH"` or `"COIN"`,
required), `tif` (`GTC`/`GTT`/`IOC`/`FOK`), and optionally `ttl` (milliseconds,
`GTT` only) and `flags` (an 8-char metadata string). Bearer-token auth, same
credential as the read side.

**THIS IS A DIFFERENT SIZING MODEL FROM KALSHI'S, and the difference matters
for whoever builds `novig_orders.py`.** Kalshi buys N *contracts* at a price,
floored from a dollar stake (`kalshi_orders.contracts_for_stake`). Novig's
`qty` is a currency amount directly -- there is no floor-to-a-whole-contract
step, and `qty` does not depend on `price` at all. **UNRESOLVED**: whether
`qty` represents the amount RISKED or the amount to WIN is not stated in
anything read so far -- on a P2P exchange this is usually the risked stake
(mirroring how a market order's `count` works on Kalshi), but that is an
assumption carried into `novig_orders.py`'s design, not a confirmed fact,
and it is the one thing a future live call or a direct question to Novig
should settle before real money moves.

**RATE LIMITS AND THEIR UNIT TRAP** are documented in `_MARKET_BY_ID_PATH`'s
neighbouring comment block below -- `Retry-After` and `X-RateLimit-Reset` on
a 429 are MILLISECONDS, not seconds, which is exactly the class of error
(`kalshi_client`'s 100x price bug, `kalshi_auth`'s timestamp-unit assumption)
this repo has already paid for twice.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

__all__ = [
    "probability_to_american",
    "cents_to_probability",
    "cents_to_american",
    "normalize_market",
    "normalize_trade_row",
    "normalize_market_row",
    "load_credentials",
    "fetch_open_markets",
    "fetch_market",
    "fetch_trade_data_index",
    "latest_market_date",
    "fetch_daily_csv",
    "fetch_latest_markets_snapshot",
    "probe",
    "NovigError",
]

# Tier 2: the official, documented, OAuth-gated REST API.
# PROD/QA hosts CONFIRMED verbatim from real docs.novig.com content
# 2026-08-24 -- `_API_BASE` already had the right value from earlier
# research; `_QA_API_BASE` is new and lets a future credential be tested
# against QA before anything touches PROD, the same caution Kalshi's demo
# host exists for.
_API_BASE = "https://api.novig.us/nbx/v2"
_QA_API_BASE = "https://api-qa.novig.us/nbx/v2"
_TOKEN_URL = "https://api.novig.us/nbx/v1/auth/emm-token"
# UNCONFIRMED -- the real docs content obtained 2026-08-24 documented
# `GET /emm/markets/{marketId}` (single market, see `fetch_market`) and
# `POST /emm/orders/place`, but no "list open markets" endpoint. This path
# is the original research-only guess, kept because refusing to page at all
# would be a worse default than a possibly-wrong path that `fetch_open_markets`
# already reports failures from by name.
_MARKETS_PATH = "/emm/markets/open"
_MARKET_BY_ID_PATH = "/emm/markets"  # CONFIRMED: {base}/emm/markets/{marketId}, GET, rate limit 128/s
_ORDER_PLACE_PATH = "/emm/orders/place"  # CONFIRMED, see order_body() below
_ORDER_CANCEL_PATH = "/emm/orders"  # CONFIRMED path prefix ({base}/emm/orders/{orderId}); HTTP method NOT
# stated in the rate-limit table's row name ("Order cancellation") -- DELETE
# is the REST convention and is what this module assumes, but it is an
# assumption, not a read fact, unlike the path itself.

# Rate limits, CONFIRMED verbatim from real docs.novig.com content 2026-08-24.
# Not enforced by this module (no client-side throttle here) -- recorded so a
# future novig_orders.py submitter can rate-limit itself rather than
# discover these the way Kalshi discovered its http_429s.
#
#   emm/orders/place (single)         1s / 64   (the endpoint's own page says
#                                                 "32 requests per second" --
#                                                 BOTH numbers appear in the
#                                                 source content and disagree;
#                                                 note both, trust neither
#                                                 alone, and rate-limit to the
#                                                 lower one, 32/s, until a live
#                                                 429 settles which is real)
#   emm/orders/batch                  1s / 64
#   emm/orders/{orderId} (cancel)     1s / 512
#   emm/kill (Novig's OWN kill switch -- a venue-side panic button, distinct
#             from this repo's execution_guard.kill_switch_engaged(); not
#             wired to anything here yet)                       30s / 1
#   emm/fills/all, emm/orders/all, emm/transactions              32 burst,
#                                                                 512/60s sustained
#   everything else                    1s / 256
#
# 429 RESPONSES CARRY `Retry-After` AND `X-RateLimit-Reset` IN MILLISECONDS,
# NOT SECONDS. A value of 73 means wait 73ms. Feeding either header straight
# into a helper that assumes HTTP's usual seconds convention is the exact
# shape of Kalshi's 100x price error and `kalshi_auth`'s millisecond-vs-second
# timestamp assumption -- both already burned this repo once. Any future
# backoff logic in `novig_orders.py` must divide by 1000, explicitly, with a
# test pinning it.
_RATE_LIMIT_HEADERS_ARE_MILLISECONDS = True

# Tier 1: the genuinely public, no-auth CSV mirror. Historical/EOD, not live.
# CONFIRMED structure 2026-08-24 (real docs.novig.com content, supplied
# directly): dated files under a fixed reporting root, indexed by a manifest
# that tracks trades' and markets' available dates SEPARATELY -- the two
# publish independently, so a date can have a markets snapshot with no trades
# file (a day that failed trade validation is withheld; its market census is
# not).
_TRADE_DATA_BASE = "https://data.novig.com/reporting/trade-data"
_INDEX_PATH = "/index.json"

# markets.csv `status` values that accept new orders right now, per the
# documented enum (active/closed/determined/finalized). Used to filter a
# snapshot down to markets actually worth pricing -- a closed/determined/
# finalized market has a real close price but nothing to quote.
_MARKET_STATUS_TRADEABLE = frozenset({"active"})

# The fields a `GET /emm/markets/{marketId}` row carries. CORRECTED
# 2026-08-24 against real `docs.novig.com` page content supplied directly
# (not search-engine paraphrase) -- the previous list (`market_type`,
# `is_consensus`, `scheduled_start`) was RESEARCHED, not read, and none of
# those three names exist in the real schema. The real flat fields:
# `id`, `description`, `status` (OPEN/CLOSED/SETTLED), `type` (MONEY/SPREAD/
# TOTAL/RUSHING_ATTEMPTS/etc -- confirming Novig lists PLAYER PROPS, not just
# game lines), `league`, `volume`, `eventId`, `strike` (nullable), `settledAt`
# (nullable). `outcomeIds`, `outcomes`, `event`, `player`, `playerId`,
# `competitor` are nested/array shapes handled separately, not flattened here.
_MARKET_FIELDS = (
    "id",
    "description",
    "status",
    "type",
    "league",
    "volume",
    "eventId",
    "strike",
    "settledAt",
)
# Still UNVERIFIED against a live response, still `_OUTCOME_FIELDS`'
# original research-only guess -- the pasted docs described the market object
# and the order-placement contract, not one outcome row's own field names.
_OUTCOME_FIELDS = ("type", "last", "available")


class NovigError(RuntimeError):
    """Raised when a fetch cannot be trusted -- never swallowed into an empty list."""


def probability_to_american(probability: float | None) -> int | None:
    """De-vigged probability -> American odds. See module header for the
    convention this assumes and how confident that assumption is."""
    if probability is None:
        return None
    # COERCE BEFORE COMPARING `[2026-09-05]`. `0.0 < probability < 1.0` raises
    # TypeError on `""` instead of refusing, so a caller handing this a string
    # got an exception where every sibling returns None. Boundary only: a valid
    # float takes the identical path and returns the identical value.
    try:
        probability = float(probability)
    except (TypeError, ValueError):
        return None
    if not (0.0 < probability < 1.0):
        return None
    if probability >= 0.5:
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))


def _as_probability(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or not (0.0 < parsed < 1.0):
        return None
    return parsed


def cents_to_probability(cents: Any) -> float | None:
    """A `markets.csv` OHLC price -- CENTS, 0.0-100.0, one decimal -- to a
    probability. **A DIFFERENT CONVENTION from `probability_to_american`'s
    input**, which is the REST tier's already-0-1 decimal probability. The
    docs' own example: "a close of 47.5 is a probability of 0.475." Mixing
    the two conventions -- handing a CSV cents value to something expecting
    0-1 already, or vice versa -- is a 100x error of exactly the shape
    `kalshi_client`'s dollars-vs-cents bug was, which is why this is a
    separate, named function rather than a shared `_as_probability` reused
    across both tiers.

    Empty string (the documented value for "no trades that day") and values
    outside (0, 100) return None -- 0 and 100 are a resolved-or-impossible
    price the same way 0/1 are for the REST tier's convention.
    """
    if cents is None or cents == "":
        return None
    try:
        parsed = float(cents)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or not (0.0 < parsed < 100.0):
        return None
    return parsed / 100.0


def cents_to_american(cents: Any) -> int | None:
    """A `markets.csv` OHLC price straight to American odds."""
    return probability_to_american(cents_to_probability(cents))


def _decimal_or_none(value: Any) -> Any:
    """A CSV numeric field, parsed via `Decimal(str(...))` rather than
    `float()` -- `cost`/`qty`/`openInterest`/`dailyVolume` are documented as
    carrying FULL NUMERIC PRECISION, and a raw float parse is exactly the
    class of error `novig_orders.cash_units_for_stake` was fixed for in this
    same lane (`12.345` misrepresented in binary float). Returns `None` for
    an empty string or an unparseable value -- never `Decimal("0")`, which
    would claim a real zero where the field was simply absent.
    """
    from decimal import Decimal, InvalidOperation

    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def normalize_trade_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """One `trades.csv` row (one SIDE of a trade -- see module header:
    every trade appears as one TAKER row plus one MAKER row per
    counterparty), typed and with the documented derived fields computed.

    `price` = `cost / qty` -- "the price one side paid, a probability
    between 0 and 1" per the docs' own words, computed here rather than left
    for every caller to derive and possibly get backwards (e.g. `qty / cost`,
    which is NOT a probability and would not even be bounded).
    """
    cost = _decimal_or_none(row.get("cost"))
    qty = _decimal_or_none(row.get("qty"))
    price = None
    if cost is not None and qty is not None and qty != 0:
        price = float(cost / qty)
    return {
        "timestamp": row.get("timestamp"),
        "outcome_id": row.get("outcomeId"),
        "market_id": row.get("marketId"),
        "contract_series": row.get("contractSeries"),
        "league": row.get("league") or None,  # documented empty for a COMBO
        "market_type": row.get("marketType") or None,  # documented empty for a COMBO
        "trade_type": row.get("tradeType"),  # STRAIGHT | COMBO
        "legs": int(row["legs"]) if str(row.get("legs") or "").strip().isdigit() else None,
        "cost": cost,
        "qty": qty,
        "side": row.get("side"),  # TAKER | MAKER
        "price_probability": price,
        "price_american": probability_to_american(price) if price is not None else None,
    }


def normalize_market_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """One `markets.csv` row -- a market's daily census, whether or not it
    traded. OHLC fields are CENTS (`cents_to_probability`), not the REST
    tier's 0-1 decimal -- see that function's docstring for why the
    distinction is load-bearing. Empty OHLC strings (documented: "no trades
    that day") become `None` throughout, never a silent 0.0 that would read
    as a real price.
    """
    close_probability = cents_to_probability(row.get("close"))
    return {
        "date": row.get("date"),
        "market_id": row.get("marketId"),
        "report_ticker": row.get("reportTicker"),
        "open_interest": _decimal_or_none(row.get("openInterest")),
        "daily_volume": _decimal_or_none(row.get("dailyVolume")),
        "open_probability": cents_to_probability(row.get("open")),
        "high_probability": cents_to_probability(row.get("high")),
        "low_probability": cents_to_probability(row.get("low")),
        "close_probability": close_probability,
        "close_american": probability_to_american(close_probability) if close_probability is not None else None,
        "status": row.get("status"),  # active | closed | determined | finalized
        "traded_today": row.get("open") not in (None, ""),
    }


def fetch_latest_markets_snapshot(
    *, status_filter: frozenset[str] | None = _MARKET_STATUS_TRADEABLE, timeout: float = 20.0
) -> dict[str, Any]:
    """THE ENTRY POINT for "populate our odds from the public CSV mirror."

    Resolves the latest published `markets.csv` date from the index, fetches
    it, and normalizes every row. **THIS IS THE PRIOR TRADING DAY'S CLOSE,
    NOT A LIVE PRICE** -- see module header. A caller building a live or
    pregame board from this is mis-using it; a caller building closing-line
    history, CLV comparisons, or a slow-moving reference price is using it
    correctly. The returned `date` and `is_stale_by_days` (calendar days
    between the snapshot date and today, UTC) exist so a consuming board can
    refuse to render this as current rather than silently doing so.

    `status_filter=None` returns every market regardless of status (useful
    for historical/closed-market analysis); the default keeps only `active`
    markets, i.e. ones that could still be quoted.
    """
    from datetime import date as _date, datetime, timezone

    index = fetch_trade_data_index(timeout=timeout)
    if index.get("status") != "ok":
        return {"status": "error", "reason": index.get("reason", "index_fetch_failed")}

    resolved_date = latest_market_date(index)
    if resolved_date.get("status") != "ok":
        return {"status": "error", "reason": resolved_date.get("reason")}
    target_date = resolved_date["date"]

    csv_result = fetch_daily_csv("markets", target_date, timeout=timeout)
    if csv_result.get("status") != "ok":
        return {"status": "error", "reason": csv_result.get("reason"), "date": target_date}

    rows = [normalize_market_row(r) for r in csv_result.get("rows") or []]
    if status_filter is not None:
        rows = [r for r in rows if r.get("status") in status_filter]

    try:
        snapshot_date = _date.fromisoformat(target_date)
        is_stale_by_days = (datetime.now(timezone.utc).date() - snapshot_date).days
    except ValueError:
        is_stale_by_days = None

    return {
        "status": "ok",
        "date": target_date,
        "is_stale_by_days": is_stale_by_days,
        "status_filter": sorted(status_filter) if status_filter is not None else None,
        "markets": rows,
        "count": len(rows),
        "available_market_dates": index.get("market_dates"),
    }


def normalize_market(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One market row, flattened, outcomes normalized. Missing fields are None
    and COUNTED -- same contract as `kalshi_client.normalize_market`."""
    out: dict[str, Any] = {}
    missing: list[str] = []
    for field in _MARKET_FIELDS:
        if field in raw:
            out[field] = raw.get(field)
        else:
            out[field] = None
            missing.append(field)

    outcomes_raw = raw.get("outcomes")
    outcomes: list[dict[str, Any]] = []
    if isinstance(outcomes_raw, list):
        for row in outcomes_raw:
            if not isinstance(row, Mapping):
                continue
            probability = _as_probability(row.get("last") if row.get("last") is not None else row.get("available"))
            entry: dict[str, Any] = {}
            outcome_missing: list[str] = []
            for field in _OUTCOME_FIELDS:
                if field in row:
                    entry[field] = row.get(field)
                else:
                    entry[field] = None
                    outcome_missing.append(field)
            entry["probability"] = probability
            entry["american"] = probability_to_american(probability)
            entry["missing_fields"] = outcome_missing
            outcomes.append(entry)
    else:
        missing.append("outcomes")

    out["outcomes"] = outcomes
    out["missing_fields"] = missing
    return out


def load_credentials() -> dict[str, Any]:
    """The OAuth client-credentials pair, or a NAMED reason there isn't one.

    Founder-gated per every source that describes tier 2 -- there is no
    self-serve signup, so an absent credential here is the EXPECTED state
    until Novig issues one, not a misconfiguration.
    """
    client_id = (os.environ.get("NOVIG_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("NOVIG_CLIENT_SECRET") or "").strip()
    if not client_id:
        return {"status": "unavailable", "reason": "no_client_id"}
    if not client_secret:
        return {"status": "unavailable", "reason": "no_client_secret"}
    return {"status": "ok", "client_id": client_id, "client_secret": client_secret}


def _get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> Any:
    request_headers = {"Accept": "application/json", "User-Agent": "syndicate/1.0"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise NovigError(f"http_{exc.code}: {url}") from exc
    except Exception as exc:
        raise NovigError(f"{type(exc).__name__}: {exc}") from exc
    return body


def _fetch_token(creds: dict[str, Any], *, timeout: float = 20.0) -> str:
    """OAuth2 client-credentials exchange. Tokens expire every ~30 min per
    documentation research -- never cached across calls in this module; the
    caller decides caching policy."""
    body = json.dumps(
        {
            "grant_type": "client_credentials",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "syndicate/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise NovigError(f"token_http_{exc.code}") from exc
    except Exception as exc:
        raise NovigError(f"token_{type(exc).__name__}: {exc}") from exc
    token = payload.get("access_token") if isinstance(payload, Mapping) else None
    if not token:
        raise NovigError("token_response_missing_access_token")
    return str(token)


def fetch_open_markets(*, league: str | None = None, market_type: str = "MONEY") -> dict[str, Any]:
    """Tier 2: the official, credential-gated REST listing.

    Refuses by name (`no_client_id` / `no_client_secret`) rather than
    returning an empty list -- an empty list here would be indistinguishable
    from "Novig lists nothing", and the actual, much more common reason is
    that this lane has no partner credential yet.
    """
    creds = load_credentials()
    if creds.get("status") != "ok":
        return {"status": "unavailable", "reason": creds.get("reason")}

    try:
        token = _fetch_token(creds)
    except NovigError as exc:
        return {"status": "error", "reason": str(exc)}

    query = f"marketType={market_type}"
    if league:
        query += f"&league={league}"
    url = f"{_API_BASE}{_MARKETS_PATH}?{query}"
    try:
        raw_body = _get(url, headers={"Authorization": f"Bearer {token}"})
        payload = json.loads(raw_body.decode("utf-8"))
    except NovigError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    except (ValueError, UnicodeDecodeError) as exc:
        return {"status": "error", "reason": f"undecodable_response: {exc}", "url": url}

    rows = payload.get("markets") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return {
            "status": "error",
            "reason": f"unexpected_shape: got {type(payload).__name__}",
            "url": url,
        }

    markets = [normalize_market(m) for m in rows if isinstance(m, Mapping)]
    missing_counts: dict[str, int] = {}
    for market in markets:
        for field in market.get("missing_fields") or ():
            missing_counts[field] = missing_counts.get(field, 0) + 1

    return {
        "status": "ok",
        "url": url,
        "league": league,
        "market_type": market_type,
        "markets": markets,
        "count": len(markets),
        "missing_fields": dict(sorted(missing_counts.items())),
    }


def fetch_market(market_id: str) -> dict[str, Any]:
    """ONE market, by id. CONFIRMED endpoint (`GET /emm/markets/{marketId}`,
    real docs.novig.com content 2026-08-24) -- unlike `fetch_open_markets`'s
    listing path, this one's existence is not a guess. Still requires the
    same credential; still refuses by name without one.
    """
    creds = load_credentials()
    if creds.get("status") != "ok":
        return {"status": "unavailable", "reason": creds.get("reason")}

    key = str(market_id or "").strip()
    if not key:
        return {"status": "error", "reason": "no_market_id"}

    try:
        token = _fetch_token(creds)
    except NovigError as exc:
        return {"status": "error", "reason": str(exc)}

    url = f"{_API_BASE}{_MARKET_BY_ID_PATH}/{key}"
    try:
        raw_body = _get(url, headers={"Authorization": f"Bearer {token}"})
        payload = json.loads(raw_body.decode("utf-8"))
    except NovigError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    except (ValueError, UnicodeDecodeError) as exc:
        return {"status": "error", "reason": f"undecodable_response: {exc}", "url": url}

    if not isinstance(payload, Mapping):
        return {"status": "error", "reason": f"unexpected_shape: got {type(payload).__name__}", "url": url}

    market = normalize_market(payload)
    return {"status": "ok", "url": url, "market": market}


def fetch_trade_data_index(*, timeout: float = 20.0) -> dict[str, Any]:
    """The manifest: which dates have a `trades.csv`, which have a
    `markets.csv`. The two are tracked SEPARATELY (`dates` vs `marketDates`)
    because they publish independently -- a day whose trades failed
    validation is withheld while its market census still ships.

    `marketDates` is absent on manifests predating that field -- read as an
    empty list, per the documented behaviour, not as a fetch failure.
    """
    url = f"{_TRADE_DATA_BASE}{_INDEX_PATH}"
    try:
        raw_body = _get(url, headers={"Accept": "application/json"}, timeout=timeout)
        payload = json.loads(raw_body.decode("utf-8"))
    except NovigError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    except (ValueError, UnicodeDecodeError) as exc:
        return {"status": "error", "reason": f"undecodable_response: {exc}", "url": url}
    if not isinstance(payload, Mapping):
        return {"status": "error", "reason": f"unexpected_shape: got {type(payload).__name__}", "url": url}

    dates = payload.get("dates")
    market_dates = payload.get("marketDates")
    if not isinstance(dates, list):
        return {"status": "error", "reason": "no_dates_array", "url": url}

    return {
        "status": "ok",
        "url": url,
        "dates": sorted(str(d) for d in dates),
        # Documented absence-means-empty, not a missing-field refusal --
        # this key genuinely may not exist yet on an older manifest.
        "market_dates": sorted(str(d) for d in market_dates) if isinstance(market_dates, list) else [],
    }


def latest_market_date(index: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The most recent date `markets.csv` is published for, or a NAMED
    reason there isn't one. Fetches the index itself when not given one, so
    a caller doing one thing can call this alone."""
    manifest = index if index is not None else fetch_trade_data_index()
    if manifest.get("status") != "ok":
        return {"status": "error", "reason": manifest.get("reason", "index_fetch_failed")}
    dates = manifest.get("market_dates") or []
    if not dates:
        return {"status": "error", "reason": "no_market_dates_published"}
    return {"status": "ok", "date": dates[-1]}


def _daily_csv_url(name: str, date: str) -> str:
    return f"{_TRADE_DATA_BASE}/{date}/{name}.csv"


def fetch_daily_csv(name: str, date: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Tier 1: the genuinely public, no-auth daily CSV mirror -- ONE
    dated file. `name` is `"trades"` or `"markets"`; `date` is `YYYY-MM-DD`
    and must come from `fetch_trade_data_index()` (or `latest_market_date()`)
    rather than guessed -- an unpublished date 403s the same way the old
    flat-path guess did, for the same underlying reason (CDN default-deny on
    a missing key).

    Rows are returned as RAW STRINGS from the CSV, not type-converted --
    `normalize_trade_row` / `normalize_market_row` do that, deliberately
    separate, so a parsing assumption can be wrong without this function
    needing to change.
    """
    key = str(name or "").strip().lower()
    if key not in ("trades", "markets"):
        return {"status": "error", "reason": "invalid_name", "name": name}
    day = str(date or "").strip()
    if not day:
        return {"status": "error", "reason": "no_date"}
    url = _daily_csv_url(key, day)
    try:
        raw_body = _get(url, headers={"Accept": "text/csv"}, timeout=timeout)
    except NovigError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"status": "error", "reason": f"undecodable_response: {exc}", "url": url}
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return {
        "status": "ok",
        "url": url,
        "name": key,
        "date": day,
        "count": len(rows),
        "columns": reader.fieldnames or [],
        "rows": rows,
    }


def probe(*, league: str | None = None) -> dict[str, Any]:
    """Report the shape that ACTUALLY comes back for both tiers, unparsed.

    Tier 2 reports `credential_unavailable` rather than attempting a call when
    no credential is configured -- there is no point probing a schema behind
    an auth wall this lane cannot open yet. Tier 1 always attempts a call: it
    needs no credential and is the one thing this module can verify today.
    """
    result: dict[str, Any] = {"checked_at": time.time()}

    creds = load_credentials()
    if creds.get("status") != "ok":
        result["tier2_official_rest"] = {"status": "credential_unavailable", "reason": creds.get("reason")}
    else:
        try:
            token = _fetch_token(creds)
            query = f"marketType=MONEY" + (f"&league={league}" if league else "")
            url = f"{_API_BASE}{_MARKETS_PATH}?{query}"
            raw_body = _get(url, headers={"Authorization": f"Bearer {token}"})
            payload = json.loads(raw_body.decode("utf-8"))
            rows = payload.get("markets") if isinstance(payload, Mapping) else payload
            sample = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], Mapping) else None
            result["tier2_official_rest"] = {
                "status": "ok",
                "url": url,
                "top_level_keys": sorted(payload.keys()) if isinstance(payload, Mapping) else None,
                "market_keys": sorted(sample.keys()) if sample else None,
                "expected_but_absent": sorted(set(_MARKET_FIELDS) - set(sample or {})),
                "present_but_unexpected": sorted(set(sample or {}) - set(_MARKET_FIELDS)),
                "sample": sample,
            }
        except Exception as exc:  # noqa: BLE001 -- a probe must never crash the caller
            result["tier2_official_rest"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    index_result = fetch_trade_data_index()
    if index_result.get("status") != "ok":
        result["tier1_daily_csv"] = {"status": "error", "stage": "index", **index_result}
        return result

    resolved = latest_market_date(index_result)
    if resolved.get("status") != "ok":
        result["tier1_daily_csv"] = {"status": "error", "stage": "latest_market_date", **resolved}
        return result

    csv_result = fetch_daily_csv("markets", resolved["date"])
    if csv_result.get("status") == "ok":
        result["tier1_daily_csv"] = {
            "status": "ok",
            "date": resolved["date"],
            "url": csv_result.get("url"),
            "columns": csv_result.get("columns"),
            "count": csv_result.get("count"),
            "sample_row": csv_result.get("rows", [None])[0],
            "sample_normalized": (
                normalize_market_row(csv_result["rows"][0]) if csv_result.get("rows") else None
            ),
        }
    else:
        result["tier1_daily_csv"] = {"stage": "markets_csv", **csv_result}

    return result
