"""The market catalogue for `api.polymarket.us` -- the venue we can actually trade.

--------------------------------------------------------------------------
WHY THIS EXISTS AT ALL, WHEN A POLYMARKET CATALOGUE ALREADY DID
--------------------------------------------------------------------------

`pipeline/polymarket_odds_refresh.py` pulls its catalogue through
`polymarket_client.fetch_markets()`, which talks to `gamma-api.polymarket.com`
-- the GLOBAL, on-chain exchange. The funded account and the working credential
are on `api.polymarket.us`. Those are different exchanges with different order
books and different money (see `polymarket_us_auth`'s header).

So pricing an edge off the global book and filling it on the US venue is the
same "different money" error the auth module was split in two to prevent, moved
from the order layer to the ODDS layer, where it is much harder to see: it does
not fail. It produces plausible edges against prices that do not exist where the
order lands.

Two facts make this concrete rather than theoretical:

  1. MEASURED 2026-08-24, live-odds-worker: the global catalogue pull returned
     `count=100 sporting=0` on every cycle -- 100 rows, none of them sport. It
     is unfiltered and takes whatever the default ordering gives, which is
     high-liquidity politics. There has never been anything there to join.

  2. `orderPriceMinTickSize` and `minimumTradeQty` are per-market fields on the
     US venue and are REQUIRED ARGUMENTS to `polymarket_us_orders.order_body`
     -- deliberately, because the docs say "Do not infer price tick size or
     minimum quantity from product type, symbol, or slug." The global catalogue
     does not carry them. So the global path could never have fed an order even
     with a perfect join; it was missing two inputs the order refuses to guess.

Fact 1 hid fact 2. While `sporting=0`, no join is attempted, so nobody
discovers the prices are from the wrong exchange.

--------------------------------------------------------------------------
WHAT IS KNOWN AND WHAT IS NOT
--------------------------------------------------------------------------

Known, because a signed read returned it (`POLYMARKET_US_AUTH ok=True`):

    payload key   `markets`
    row keys      active archived category closed comboEnabled createdAt
                  description endDate ep3Status ep3SyncedAt feeCoefficient
                  gameStartTime hidden id manualActivation marketSides
                  marketType minimumTradeQty orderPriceMinTickSize
                  outcomePrices outcomes question slug sportsMarketType
                  sportsMarketTypeV2 startDate status tags updatedAt

NOT known, and therefore NOT guessed:

  * The PAGINATION mechanism ON `/v1/markets`. The `limit=1` probe returned
    `['markets']` and nothing else -- no cursor, no `next`, no total. So this
    module does not invent one for that route: it asks for a large page and
    reports `truncated=True` when the venue returns exactly what was asked
    for, which is the honest reading of "there may be more and we cannot tell"
    rather than a silent cap.

    The SPORTS routes are different -- `limit`/`offset` are documented there,
    so `fetch_league_events` pages properly instead of guessing.

  * The VALUE VOCABULARY of `sportsMarketTypeV2`. The probe returned one row
    and it was not a sports row, so no value has ever been observed. Filtering
    on a guessed constant would silently return zero and look exactly like a
    venue with no sports markets -- which is the failure this module is being
    written to correct, repeated one layer down. So the sporting test is
    STRUCTURAL (does the row carry sports fields at all) and the distinct
    values seen are REPORTED, so the next run designs the mapping from data.

That is the same discipline that caught Kalshi's ten wrong field names and its
100x price error before either reached an order: report the shape, do not parse
it, and let the first live run correct the guesses cheaply.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

__all__ = [
    "fetch_markets",
    "is_settled_row",
    "MARKET_STATUS_OPEN",
    "fetch_league_slate",
    "fetch_teams",
    "probe_v1_sports_routes",
    "probe_market_query_params",
    "probe_offset_landscape",
    "team_alias_index",
    "is_sporting_row",
    "is_game_market_row",
    "sports_market_type",
    "trimmed_row",
    "league_slug_for_sport",
    "SPORTS_FIELDS",
    "ORDER_REQUIRED_FIELDS",
    "DOCUMENTED_LEAGUE_SLUGS",
]

# A large page, because the pagination mechanism is unknown and one round trip
# that reports its own truncation beats a loop built on a guessed cursor.
_DEFAULT_LIMIT = 500

# The fields whose PRESENCE marks a row as a sporting market. Structural rather
# than a value match, for the reason in the header: no value of
# `sportsMarketTypeV2` has ever been observed, and a guessed constant returns
# zero rows indistinguishably from a venue that lists no sport.
SPORTS_FIELDS = ("sportsMarketTypeV2", "sportsMarketType", "gameStartTime")

# The two the order builder REFUSES to infer. A row missing either cannot be
# ordered against, so the catalogue records that per row rather than letting it
# surface as a TypeError at submit time.
ORDER_REQUIRED_FIELDS = ("orderPriceMinTickSize", "minimumTradeQty")

# What the artifact keeps. The Novig lane hit `refresh_state_store`'s ~8MB
# keyvalue ceiling on a full catalogue the same day (#60), so the trim is here
# from the start rather than after an outage -- and every field kept is one the
# join or the order actually reads, which is a better rule than a size budget.
_KEEP = (
    "id", "slug", "question", "category", "tags",
    "marketType", "marketSides", "sportsMarketType", "sportsMarketTypeV2",
    "outcomes", "outcomePrices",
    "orderPriceMinTickSize", "minimumTradeQty", "feeCoefficient",
    "gameStartTime", "startDate", "endDate", "status", "active", "closed",
)


# MEASURED 2026-08-24T21:07:04Z, the first run through `closed=false`:
#
#   sporting=2000 types=['SPORTS_MARKET_TYPE_FUTURE',
#                        'SPORTS_MARKET_TYPE_UNSPECIFIED']
#   categories=['crypto','culture','finance','geopolitics','macro',
#               'politics','sports','technology']
#
# `sporting=2000` was WRONG, and wrong the same way `sporting=500` was. The
# presence test counted crypto, politics and macro markets as sporting,
# because they carry `sportsMarketTypeV2` with the value
# `SPORTS_MARKET_TYPE_UNSPECIFIED` -- a field that is PRESENT and means "not a
# sports market". Presence was the right test while no value had been
# observed; now that the vocabulary is known, it is the wrong one.
_NON_SPORT_TYPE_MARKERS = ("UNSPECIFIED", "UNKNOWN")

# The category vocabulary, observed in that same response. `sports` is the one
# that matters; the rest are listed so a future reader can see this was read
# off the venue rather than guessed.
SPORTS_CATEGORY = "sports"

# Game-level vs season-level. Both are genuinely sports and they are NOT
# interchangeable: a future ("World Series Champion", `outcomes: ["Yes","No"]`)
# has no game to join a board row to, while a moneyline
# (`outcomes: ["Titans","Chargers"]`) does.
GAME_MARKET_TYPE = "SPORTS_MARKET_TYPE_MONEYLINE"
FUTURES_MARKET_TYPE = "SPORTS_MARKET_TYPE_FUTURE"


def sports_market_type(row: Mapping[str, Any]) -> str:
    return str(row.get("sportsMarketTypeV2") or "").strip().upper()


def is_sporting_row(row: Mapping[str, Any]) -> bool:
    """Is this a sports market at all?

    Was a PRESENCE test, because no value of `sportsMarketTypeV2` had ever been
    observed and matching a guessed constant would have returned zero rows
    indistinguishably from a venue with no sport. Both facts are now measured,
    so the test uses them: a type of `*_UNSPECIFIED` is present and means NOT
    sport, and `category` carries a real `sports` value.
    """
    category = str(row.get("category") or "").strip().lower()
    if category:
        return category == SPORTS_CATEGORY

    market_type = sports_market_type(row)
    if market_type:
        return not any(marker in market_type for marker in _NON_SPORT_TYPE_MARKERS)

    # No category and no type: fall back to the original structural signal. A
    # market tied to a specific game start is a game market whatever else is
    # missing.
    return bool(str(row.get("gameStartTime") or "").strip())


def is_game_market_row(row: Mapping[str, Any]) -> bool:
    """A GAME market -- the only kind a board row can join to.

    A future is a sports market and cannot be joined: "World Series Champion"
    with `outcomes: ["Yes","No"]` has no game. A moneyline carries the two
    teams (`["Titans","Chargers"]`) and a `gameStartTime` that identifies one.
    Counting them together is how `sporting=2000` looked like a usable slate
    while containing no joinable row at all.
    """
    return is_sporting_row(row) and sports_market_type(row) == GAME_MARKET_TYPE


def trimmed_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """The subset the join and the order read, plus an explicit orderability flag.

    `orderable` is computed HERE, once, rather than at submit time: a row that
    cannot be priced is a row the join should never offer, and discovering that
    at the venue is the expensive place to discover it.
    """
    kept = {key: row[key] for key in _KEEP if key in row}
    kept["orderable"] = all(
        row.get(field) not in (None, "") for field in ORDER_REQUIRED_FIELDS
    )
    return kept


def _distinct(rows: Iterable[Mapping[str, Any]], field: str) -> list[str]:
    seen = {str(r.get(field)) for r in rows if r.get(field) not in (None, "")}
    return sorted(seen)[:20]


# Observed 2026-08-24T20:46:21Z: every one of 2,000 rows carried
# `MARKET_STATUS_RESOLVED`. That is the only value seen so far, so the test
# below asks whether the status says RESOLVED rather than pattern-matching a
# vocabulary nobody has seen the rest of -- an unknown status must not be read
# as "settled", because that direction silently discards tradeable markets.
_RESOLVED_STATUS_MARKERS = ("RESOLVED", "SETTLED", "CLOSED", "CANCELED", "CANCELLED")


def is_settled_row(row: Mapping[str, Any]) -> bool:
    """Is this market already resolved? STATUS first, price only as a fallback.

    MEASURED 2026-08-24T20:28:07Z: the first 500 rows of
    `/v1/markets?active=true&limit=500` were ALL NFL games from `2025-11-02`
    with `outcomePrices` of `["1","0"]` -- settled games from last season,
    priced at certainty, returned under `active=true`. So `active` does not
    mean unresolved on this venue.

    The first version of this inferred resolution from the PRICE, because the
    `status` vocabulary had never been observed. MEASURED 2026-08-24T20:46:21Z,
    it now has been: `statuses=['MARKET_STATUS_RESOLVED']` across 2,000 rows --
    **including the 2 rows the price test called live**, which are priced
    `["0.5","0.5"]`. A resolved market that never traded sits at 0.5 forever,
    and no price test can tell that from a genuine coin-flip.

    So status is authoritative where present and price is the fallback for a
    row that omits it. Two false "live" rows out of 2,000 is a 0.1% error rate
    that would have put real orders on games that finished months ago.
    """
    status = str(row.get("status") or "").strip().upper()
    if status:
        return any(marker in status for marker in _RESOLVED_STATUS_MARKERS)

    prices = row.get("outcomePrices")
    if isinstance(prices, str):
        try:
            import json

            prices = json.loads(prices)
        except Exception:
            return False
    if not isinstance(prices, list) or not prices:
        return False
    values: list[float] = []
    for price in prices:
        try:
            values.append(float(price))
        except (TypeError, ValueError):
            return False
    return any(v <= 0.0 or v >= 1.0 for v in values)


def _game_start(row: Mapping[str, Any]) -> str:
    return str(row.get("gameStartTime") or "")


# MEASURED 2026-08-24T20:56:41Z. `closed=false` is the filter that reaches the
# CURRENT slate: one request returned row id 7898 with
# `gameStartTime=2026-09-07` and `status=MARKET_STATUS_OPEN`, where the
# unfiltered query was still in 2025-11 two thousand rows deep.
#
# `active` is NOT that filter and is actively misleading here. `active=true` is
# the server default (it returned the identical signature to no param at all)
# and yields MARKET_STATUS_RESOLVED rows; `active=false` yields resolved rows
# from a different window. So on this venue `active` does not mean "tradeable"
# and `closed` is the field that does -- which is why 500 settled games came
# back under `active=true` and looked like a healthy slate.
_LIVE_FILTER = "closed=false"

# The open-status value, finally observed in that same response. Recorded
# because `status=` as a QUERY PARAM is not honoured (see
# `probe_market_query_params`), so this is useful for reading rows, not for
# filtering them.
MARKET_STATUS_OPEN = "MARKET_STATUS_OPEN"


def fetch_markets(
    *,
    limit: int = _DEFAULT_LIMIT,
    open_only: bool = True,
    active: bool | None = None,
    offset: int = 0,
    max_pages: int = 1,
    drop_settled: bool = False,
) -> dict[str, Any]:
    """One or more signed reads of the US catalogue, reported by shape.

    --------------------------------------------------------------------------
    THE COUNT THAT LOOKS RIGHT AND IS NOT
    --------------------------------------------------------------------------

    The first production run of this function returned
    `sporting=500 of=500 orderable=500 truncated=True` -- which reads as a full,
    healthy slate and was 500 games that finished nine months earlier. A join
    built on it would price today's board against settled results, and every
    counter on the log line would look correct.

    So the report now separates three different things that were one number:

        sporting     rows that are sports markets at all
        settled      of those, already resolved (see `is_settled_row`)
        live         sporting and NOT settled -- the only usable count

    `drop_settled` filters them out; it is OFF by default so a caller that has
    not thought about it gets the full picture rather than a silently narrowed
    one, and the `settled` count is always reported either way. It is now a
    SECOND line of defence rather than the primary one: `open_only` sends
    `closed=false`, which is the filter the venue actually honours.

    --------------------------------------------------------------------------
    `closed`, NOT `active`
    --------------------------------------------------------------------------

    `open_only=True` sends `closed=false`. Measured 2026-08-24T20:56:41Z, that
    is the parameter that reaches the current slate, and `active` is not:
    `active=true` is the server default and returns MARKET_STATUS_RESOLVED
    rows. That is why the first version of this function pulled 500 settled
    NFL games under `active=true` and reported them as a healthy slate.

    --------------------------------------------------------------------------
    PAGING, WHICH IS STILL A GUESS ON THIS ROUTE
    --------------------------------------------------------------------------

    `payload_keys=['markets']` -- no cursor, no total. `offset` is used because
    the venue's own Sports API documents `limit`/`offset`, so it is the house
    convention rather than an invention. IT IS UNVERIFIED HERE. If the venue
    ignores it, every page returns the same rows, so `duplicate_ids` counts
    repeats across pages: a non-zero value means offset did nothing and the
    pagination is wrong, which is otherwise invisible.

    Never raises for a venue problem -- this runs inside a refresh loop, and a
    venue being unreachable must degrade to a NAMED refusal rather than take
    the loop down.
    """
    from syndicate.features.shared import polymarket_us_auth as auth

    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent", "markets": []}

    rows: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_ids = 0
    pages = 0
    truncated = False
    payload_keys: list[str] = []

    for page in range(max(1, int(max_pages))):
        page_offset = int(offset) + page * int(limit)
        url = f"{auth.BASE_URL}/v1/markets?limit={int(limit)}&offset={page_offset}"
        if open_only:
            url += f"&{_LIVE_FILTER}"
        if active is not None:
            url += f"&active={'true' if active else 'false'}"
        try:
            payload = auth.signed_request("GET", url)
        except Exception as exc:
            reason = (
                str(exc) if isinstance(exc, auth.PolymarketUSAuthError)
                else f"{type(exc).__name__}: {exc}"
            )
            if not rows:
                return {"status": "error", "reason": reason, "markets": []}
            truncated = True
            break

        batch = payload.get("markets")
        if not isinstance(batch, list):
            # The one key the probe confirmed. If it is gone, say so by name
            # rather than returning an empty catalogue, which reads as "no
            # markets".
            if not rows:
                return {
                    "status": "error",
                    "reason": f"markets_key_absent: payload_keys={sorted(payload.keys())}",
                    "markets": [],
                }
            truncated = True
            break

        payload_keys = sorted(payload.keys())
        pages += 1
        for row in batch:
            if not isinstance(row, Mapping):
                continue
            row_id = str(row.get("id") or "")
            if row_id and row_id in seen_ids:
                duplicate_ids += 1
                continue
            if row_id:
                seen_ids.add(row_id)
            rows.append(row)
        if len(batch) < int(limit):
            break
    else:
        truncated = True

    sporting = [r for r in rows if is_sporting_row(r)]
    games = [r for r in sporting if is_game_market_row(r)]
    settled = [r for r in sporting if is_settled_row(r)]
    live = [r for r in sporting if not is_settled_row(r)]
    chosen = live if drop_settled else sporting
    trimmed = [trimmed_row(r) for r in chosen]
    starts = sorted(_game_start(r) for r in sporting if _game_start(r))
    live_starts = sorted(_game_start(r) for r in live if _game_start(r))
    return {
        "status": "ok",
        "markets": trimmed,
        "count": len(trimmed),
        "total_rows": len(rows),
        "sporting": len(sporting),
        # GAME markets only -- the joinable ones. A slate of futures is a
        # sports catalogue with nothing a board row can be priced against.
        "games": len(games),
        "futures": sum(1 for r in sporting if sports_market_type(r) == FUTURES_MARKET_TYPE),
        # THE THREE NUMBERS THAT WERE ONE. `live` is the only usable count.
        "settled": len(settled),
        "live": len(live),
        "pages": pages,
        "truncated": truncated,
        # Non-zero means `offset` did nothing and paging is wrong -- otherwise
        # invisible, because every page would simply look full.
        "duplicate_ids": duplicate_ids,
        "orderable": sum(1 for r in trimmed if r.get("orderable")),
        # The window actually covered, which is what makes "these are last
        # season's games" legible at a glance instead of needing a sample.
        "game_start_min": starts[0] if starts else None,
        "game_start_max": starts[-1] if starts else None,
        "live_start_min": live_starts[0] if live_starts else None,
        "live_start_max": live_starts[-1] if live_starts else None,
        "sports_market_types": _distinct(sporting, "sportsMarketTypeV2"),
        "market_types": _distinct(sporting, "marketType"),
        "categories": _distinct(sporting, "category"),
        # Never observed. Reported so the next run can filter on `status`
        # directly instead of inferring resolution from the price.
        "statuses": _distinct(sporting, "status"),
        "payload_keys": payload_keys,
        "row_keys": sorted(rows[0].keys()) if rows else None,
    }


# --------------------------------------------------------------------------
# THE SPORTS API -- 404 ON THIS HOST. MEASURED 2026-08-24T20:18:37Z.
# --------------------------------------------------------------------------
#
# READ THIS BEFORE BUILDING ANYTHING ON `fetch_league_slate`. FOUR of the
# user-supplied Sports API routes return HTTP 404 from `api.polymarket.us`.
# One boot, one credential, 0.6 seconds end to end (live-odds-worker `hvpj6`):
#
#     .602  GET /v1/markets                 ok=True, 29 row keys
#     .752  GET /v2/leagues/mlb/events      http_404  {"code":5}  NOT_FOUND
#     .901  GET /v2/leagues/wnba/events     http_404
#   38.100  GET /v2/leagues/nfl/events      http_404
#   38.240  GET /v1/sports/teams/provider   http_404
#
# Two things that rules out, which is why it is worth stating at this length:
#
#   * NOT the slug. `nfl`/`nba`/`mlb` are the docs' OWN examples and they 404
#     identically to the four guessed ones. The route is absent, not the league.
#   * NOT the credential, the clock, or the signature. A signed read of
#     `/v1/markets` succeeded in the SAME SECOND, on the same instance, through
#     the same `signed_request`. gRPC code 5 is NOT_FOUND, not UNAUTHENTICATED.
#
# WHAT IT DOES *NOT* RULE OUT, and an earlier draft of this comment wrongly
# claimed it did: the rest of the LEGACY `/v1` sports routes. Four routes were
# tested, not the doc set. `/v1/sports/teams/provider` is the `provider`
# VARIANT, and these are untried:
#
#     GET /v1/sports                    all sports + their series ids
#     GET /v1/sports/teams              teams, with no provider argument
#     GET /v1/sports/{seriesId}/events  events for a series
#
# They matter because they share the `/v1` prefix that demonstrably works on
# this host, while everything confirmed dead is either `/v2` or carries the
# `provider` sub-path. A 404 on `/v1/sports/teams/provider` is as consistent
# with "that variant needs different arguments" as with "no sports data here",
# and those have opposite consequences. `probe_v1_sports_routes` below asks.
#
# The code below is KEPT rather than deleted -- it is correct against the
# documented contract, and the moment the right host is found it works by
# pointing `POLYMARKET_US_API_BASE` at it. What must not happen is a future
# session rediscovering this 404 from scratch, or worse, reading an empty slate
# as "the venue lists no sport".
#
# USE `fetch_markets` INSTEAD. `/v1/markets` works and carries
# `sportsMarketTypeV2`, `gameStartTime`, `orderPriceMinTickSize` and
# `minimumTradeQty` -- every field the join and the order need.
#
# --------------------------------------------------------------------------
# (original design notes, still accurate about the CONTRACT)
#
# `GET /v2/leagues/{slug}/events` returns one league's events directly, which
# is strictly better than pulling `/v1/markets` and filtering: it cannot be
# swamped by politics the way the global pull was (`count=100 sporting=0` every
# cycle), and `limit`/`offset` are DOCUMENTED here, so paging is a mechanism
# rather than the guess `/v1/markets` still requires.
#
# THE ROUTE ITSELF LIVES IN `polymarket_us_sports_client`, which a parallel
# session built from the same user-supplied docs. That module owns URL
# construction, the Syndicate-sport -> league-slug mapping, and the single-page
# signed GET; it also covers `/v2/sports/{slug}/events`, which this file does
# not need. Reimplementing any of that here would give the codebase two
# `fetch_league_events` with DIFFERENT argument meanings -- theirs takes a
# Polymarket slug, a pager takes a Syndicate sport key -- which is a footgun
# for exactly the reason the two Polymarket AUTH modules are kept apart.
#
# So this adds only what that module does not have and this file's callers
# need: paging to exhaustion, extraction of the markets hanging off each
# event, and the orderability check. Named `fetch_league_slate` rather than
# `fetch_league_events` so the two are never confused at a call site.
#
# `fetch_markets` above is kept regardless. It is the only route whose response
# shape has actually been observed, and it carries `orderPriceMinTickSize` and
# `minimumTradeQty` -- so if an event's nested markets turn out not to carry
# those, the catalogue is where they come from.

# The docs' own examples: "League slug (e.g., nfl, nba, mlb)". Everything else
# in the sibling module's mapping is a guess at the same convention. Kept as a
# set here because an empty slate means completely different things either way:
# for a documented slug it is "no games today", for a guessed one it is most
# likely "the slug is wrong". Collapsing them would make a typo look like an
# off day, which is the absence/failure confusion this layer exists to prevent.
DOCUMENTED_LEAGUE_SLUGS = frozenset({"nfl", "nba", "mlb"})


def league_slug_for_sport(sport: Any) -> tuple[str | None, bool]:
    """`(slug, documented)`. An unknown sport returns `(None, False)`.

    The mapping itself belongs to `polymarket_us_sports_client` -- one source
    of truth for which slug a sport uses. This only adds whether that slug is
    documented or guessed.
    """
    from syndicate.features.shared.polymarket_us_sports_client import (
        syndicate_sport_to_polymarket_league,
    )

    slug = syndicate_sport_to_polymarket_league(str(sport or ""))
    return slug, bool(slug in DOCUMENTED_LEAGUE_SLUGS)


def _event_markets(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The markets hanging off an event, wherever the venue puts them.

    The response shape of the events route has NOT been observed -- the docs
    describe its parameters and not its body, and the sibling module's live
    probe ran on refresh-worker, where the credential is absent, so it returned
    `credentials_absent` for all seven leagues and learned nothing about the
    body. Rather than assume one key, this looks in the plausible places and
    COUNTS the misses, so the first run with a working credential corrects it
    from data instead of returning a slate with no prices and no explanation.
    """
    for key in ("markets", "Markets", "marketList"):
        value = event.get(key)
        if isinstance(value, list):
            return [m for m in value if isinstance(m, Mapping)]
    return []


def _events_from_payload(payload: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    for key in ("events", "data", "results"):
        if isinstance(payload.get(key), list):
            return [e for e in payload[key] if isinstance(e, Mapping)]
    return None


def fetch_league_slate(
    sport: Any,
    *,
    limit: int = 100,
    max_pages: int = 10,
    event_type: str = "sport",
) -> dict[str, Any]:
    """One league's slate, paged by the documented `limit`/`offset`.

    `event_type` defaults to `sport` (the documented default) rather than
    `futures`: a futures market has no game to join a board row to.
    """
    from syndicate.features.shared import polymarket_us_sports_client as sports

    slug, documented = league_slug_for_sport(sport)
    if slug is None:
        return {"status": "skipped", "reason": f"no_league_slug_for_sport: {sport}", "events": []}

    events: list[Mapping[str, Any]] = []
    pages = 0
    truncated = False
    payload_keys: list[str] = []

    for page in range(int(max_pages)):
        result = sports.fetch_league_events(
            slug, limit=int(limit), offset=page * int(limit), type_=event_type
        )
        if result.get("status") != "ok":
            reason = str(result.get("reason") or "unknown")
            # A failure on page 0 is a failure. A failure on page 3 still has
            # three real pages in hand, so it degrades to a partial result that
            # SAYS it is partial rather than throwing away what was fetched.
            if not events:
                return {
                    "status": "error", "reason": reason, "events": [],
                    "league_slug": slug, "slug_documented": documented,
                }
            truncated = True
            break

        payload = result.get("payload")
        if not isinstance(payload, Mapping):
            return {
                "status": "error", "reason": f"payload_not_an_object: {type(payload).__name__}",
                "events": [], "league_slug": slug, "slug_documented": documented,
            }
        payload_keys = sorted(payload.keys())
        batch = _events_from_payload(payload)
        if batch is None:
            return {
                "status": "error",
                "reason": f"events_key_absent: payload_keys={payload_keys}",
                "events": [], "league_slug": slug, "slug_documented": documented,
            }
        pages += 1
        events.extend(batch)
        if len(batch) < int(limit):
            break
    else:
        # Ran the full page budget without a short page: there may be more.
        truncated = True

    markets = [m for e in events for m in _event_markets(e)]
    trimmed = [trimmed_row(m) for m in markets]
    return {
        "status": "ok",
        "league_slug": slug,
        # See DOCUMENTED_LEAGUE_SLUGS: an empty slate reads differently for a
        # guessed slug than for a documented one.
        "slug_documented": documented,
        "events": events,
        "event_count": len(events),
        "pages": pages,
        "truncated": truncated,
        "markets": trimmed,
        "market_count": len(trimmed),
        "orderable": sum(1 for m in trimmed if m.get("orderable")),
        # If this is nonzero while `market_count` is 0, the events route nests
        # its markets somewhere `_event_markets` does not look -- a named,
        # visible gap rather than a silently priceless slate.
        "events_without_markets": sum(1 for e in events if not _event_markets(e)),
        "payload_keys": payload_keys,
        "event_keys": sorted(events[0].keys()) if events else None,
        "sports_market_types": _distinct(markets, "sportsMarketTypeV2"),
    }


# --------------------------------------------------------------------------
# TEAMS -- the join's hardest part, handed over by the venue
# --------------------------------------------------------------------------
#
# The game-line join's measured failure mode was `side_not_a_team_in_this_game:
# 77` -- our board's team naming against a venue's. `/v1/sports/teams/provider`
# returns `name`, `abbreviation`, `displayAbbreviation`, `alias` and `safeName`
# per team, which is an ALIAS TABLE from the venue itself. Matching against
# that is a different kind of operation from fuzzy string similarity: it can be
# exact, and an unmatched name is then a real fact rather than a threshold.


_TEAMS_PROVIDER_PATH = "/v1/sports/teams/provider"

# Two documented providers. Which of them is actually populated for a given
# league has not been observed, so it is overridable without a deploy -- the
# same escape hatch `POLYMARKET_US_ORDER_PATH` exists for, and for the same
# reason: Kalshi's route moved and cost an http_410 to discover.
DEFAULT_TEAM_PROVIDER = "PROVIDER_SPORTRADAR"

_TEAM_NAME_FIELDS = ("name", "abbreviation", "displayAbbreviation", "alias", "safeName")


def fetch_teams(league: Any, *, provider: str | None = None) -> dict[str, Any]:
    """The venue's own team table for one league."""
    import os

    from syndicate.features.shared import polymarket_us_auth as auth

    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent", "teams": []}

    slug, _documented = league_slug_for_sport(league)
    league_param = (slug or str(league or "")).upper()
    chosen = provider or os.environ.get("POLYMARKET_US_TEAM_PROVIDER") or DEFAULT_TEAM_PROVIDER
    url = f"{auth.BASE_URL}{_TEAMS_PROVIDER_PATH}?provider={chosen}&league={league_param}"
    try:
        payload = auth.signed_request("GET", url)
    except Exception as exc:
        reason = (
            str(exc) if isinstance(exc, auth.PolymarketUSAuthError)
            else f"{type(exc).__name__}: {exc}"
        )
        return {"status": "error", "reason": reason, "teams": [], "provider": chosen}

    rows = None
    for key in ("teams", "data", "results"):
        if isinstance(payload.get(key), list):
            rows = payload[key]
            break
    if rows is None:
        return {
            "status": "error",
            "reason": f"teams_key_absent: payload_keys={sorted(payload.keys())}",
            "teams": [], "provider": chosen,
        }

    teams = [r for r in rows if isinstance(r, Mapping)]
    return {
        "status": "ok",
        "provider": chosen,
        "league": league_param,
        "teams": teams,
        "count": len(teams),
        "payload_keys": sorted(payload.keys()),
        "row_keys": sorted(teams[0].keys()) if teams else None,
    }


# --------------------------------------------------------------------------
# WHICH QUERY PARAMETERS DOES `/v1/markets` ACTUALLY HONOUR?
# --------------------------------------------------------------------------
#
# The blocker measured 2026-08-24T20:46:21Z: 2,000 rows deep the window is
# still `2025-10-31..2026-01-13`, ascending, `truncated=True`, while today is
# 2026-08-24. Today's slate is roughly 6,000-8,000 rows in. Paging blindly to
# ~16 pages on every boot is the brute-force fallback; a filter or a sort would
# make it one request.
#
# TWO DESIGN CHOICES MAKE THIS PROBE WORTH RUNNING, and without them it would
# produce a table of results that cannot be interpreted:
#
#   1. A NEGATIVE CONTROL. `zzz_not_a_real_param` is sent deliberately. If the
#      API REJECTS it, then "this param was ignored" is real evidence the param
#      is unsupported. If the API silently IGNORES it, then every "ignored"
#      result below is uninformative -- it means only that this API discards
#      unknown query params, which is the normal grpc-gateway behaviour and
#      would make the whole table meaningless. Interpreting the results without
#      knowing which world we are in is exactly the mistake that produced the
#      `sporting=500` reading.
#
#   2. KNOWN-VALID VALUES WHERE POSSIBLE. `status=MARKET_STATUS_RESOLVED` and
#      `sportsMarketTypeV2=SPORTS_MARKET_TYPE_MONEYLINE` are values the venue
#      itself returned. Sending those separates "the PARAM is unsupported" from
#      "the VALUE was wrong", which guessing both at once cannot do. If
#      `status=` is honoured with the resolved value, then status filtering
#      works and only the name of the OPEN value is missing -- a much smaller
#      question.

# `(label, query fragment)`. Grouped by hypothesis so a result table reads as
# an argument rather than a list.
_MARKET_PARAM_CANDIDATES: tuple[tuple[str, str], ...] = (
    # NEGATIVE CONTROL -- read this row first, see (1) above.
    ("control_bogus_param", "zzz_not_a_real_param=1"),
    # Does filtering work AT ALL? Known-valid values, see (2) above.
    ("status_resolved_known", "status=MARKET_STATUS_RESOLVED"),
    ("type_moneyline_known", "sportsMarketTypeV2=SPORTS_MARKET_TYPE_MONEYLINE"),
    ("category_sports_known", "category=sports"),
    # Guesses at the value that means "not resolved".
    ("status_open", "status=MARKET_STATUS_OPEN"),
    ("status_active", "status=MARKET_STATUS_ACTIVE"),
    ("status_unspecified", "status=MARKET_STATUS_UNSPECIFIED"),
    # Boolean ROW FIELDS. These are real keys on every row
    # (active/archived/closed/hidden), and a gateway commonly exposes row
    # fields as filters -- a better-than-random guess.
    ("closed_false", "closed=false"),
    ("closed_true", "closed=true"),
    ("archived_false", "archived=false"),
    ("hidden_false", "hidden=false"),
    ("active_true", "active=true"),
    ("active_false", "active=false"),
    # Ordering. Any of these reaching today's slate makes paging unnecessary.
    ("order_desc", "order=desc"),
    ("sort_desc", "sort=desc"),
    ("sort_by_start", "sortBy=gameStartTime"),
    ("sort_direction_desc", "sortDirection=desc"),
    ("descending_true", "descending=true"),
    ("reverse_true", "reverse=true"),
    # Time bounds, in the naming styles this API has already shown.
    ("game_start_min", "gameStartTimeMin=2026-08-01T00:00:00Z"),
    ("min_game_start", "minGameStartTime=2026-08-01T00:00:00Z"),
    ("start_date", "startDate=2026-08-01T00:00:00Z"),
    ("start_after", "gameStartTimeAfter=2026-08-01T00:00:00Z"),
)


def _query_signature(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """What a response looked like, compactly enough to compare two of them."""
    starts = sorted(str(r.get("gameStartTime") or "") for r in rows if r.get("gameStartTime"))
    return {
        "count": len(rows),
        # The first id is the sharpest single tell: a different first row means
        # a different ordering or a different filter, even at equal counts.
        "first_id": str(rows[0].get("id")) if rows else None,
        "start_min": starts[0] if starts else None,
        "start_max": starts[-1] if starts else None,
        "statuses": sorted({str(r.get("status")) for r in rows if r.get("status")})[:5],
    }


def probe_market_query_params(*, limit: int = 5) -> dict[str, Any]:
    """Send each candidate parameter and report which CHANGE the response.

    Three outcomes, kept distinct because they imply different next steps:

        rejected   the call failed -- the param is understood and disallowed,
                   or the value is malformed
        ignored    identical signature to the baseline
        honoured   different signature -- the param did something

    `ignored` is only meaningful if `control_bogus_param` is REJECTED. If the
    control is also ignored, this API discards unknown query params and no
    `ignored` row below carries information. That verdict is computed here
    rather than left to a reader.
    """
    from syndicate.features.shared import polymarket_us_auth as auth

    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent"}

    def _fetch(extra: str | None) -> dict[str, Any]:
        url = f"{auth.BASE_URL}/v1/markets?limit={int(limit)}"
        if extra:
            url += f"&{extra}"
        try:
            payload = auth.signed_request("GET", url)
        except Exception as exc:
            reason = (
                str(exc) if isinstance(exc, auth.PolymarketUSAuthError)
                else f"{type(exc).__name__}: {exc}"
            )
            return {"outcome": "rejected", "reason": reason[:200]}
        rows = payload.get("markets")
        if not isinstance(rows, list):
            return {"outcome": "rejected", "reason": f"markets_key_absent: {sorted(payload.keys())}"}
        return {"outcome": "ok", "signature": _query_signature(
            [r for r in rows if isinstance(r, Mapping)])}

    baseline = _fetch(None)
    if baseline.get("outcome") != "ok":
        # No baseline means nothing below can be compared to anything.
        return {"status": "error", "reason": f"baseline_failed: {baseline.get('reason')}"}

    results: dict[str, Any] = {}
    for label, fragment in _MARKET_PARAM_CANDIDATES:
        probe = _fetch(fragment)
        if probe.get("outcome") == "rejected":
            results[label] = {"outcome": "rejected", "reason": probe.get("reason"), "query": fragment}
            continue
        signature = probe.get("signature") or {}
        changed = signature != baseline.get("signature")
        results[label] = {
            "outcome": "honoured" if changed else "ignored",
            "query": fragment,
            "signature": signature if changed else None,
        }

    control = results.get("control_bogus_param", {}).get("outcome")
    return {
        "status": "ok",
        "baseline": baseline.get("signature"),
        # THE VERDICT, computed rather than left to the reader. See (1).
        "control_outcome": control,
        "ignored_is_meaningful": control == "rejected",
        "honoured": sorted(k for k, v in results.items() if v.get("outcome") == "honoured"),
        "rejected": sorted(k for k, v in results.items() if v.get("outcome") == "rejected"),
        "results": results,
    }


def probe_offset_landscape(
    *, offsets: tuple[int, ...] = (0, 1000, 2000, 4000, 8000, 16000, 32000, 64000),
    limit: int = 5,
) -> dict[str, Any]:
    """WHERE in the `closed=false` ordering do game markets live?

    MEASURED 2026-08-24T21:18:53Z: `games=0 futures=1644` across the first
    2,000 rows. Moneylines are known to EXIST on this venue -- the unfiltered
    query returned them for 2025-11 games -- so they are either deeper in this
    ordering or absent from the open set. Those have completely different
    consequences and a linear sweep is the expensive way to tell them apart.

    So this SAMPLES the ordering instead: ~8 requests of 5 rows each, spread
    across the offset range, reporting what type of market lives at each depth.
    That locates the moneylines (or establishes their absence) for a fraction
    of the cost of paging to them, and the shape of the result also says
    whether the ordering is by id, by date, or by type.

    An offset past the end returns an empty page, which is itself the answer to
    "how big is this collection" -- reported rather than treated as a failure.
    """
    from syndicate.features.shared import polymarket_us_auth as auth

    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent"}

    samples: dict[str, Any] = {}
    first_game_offset: int | None = None
    for offset in offsets:
        url = f"{auth.BASE_URL}/v1/markets?limit={int(limit)}&offset={int(offset)}&{_LIVE_FILTER}"
        try:
            payload = auth.signed_request("GET", url)
        except Exception as exc:
            reason = (
                str(exc) if isinstance(exc, auth.PolymarketUSAuthError)
                else f"{type(exc).__name__}: {exc}"
            )
            samples[str(offset)] = {"status": "error", "reason": reason[:200]}
            continue
        rows = [r for r in (payload.get("markets") or []) if isinstance(r, Mapping)]
        if not rows:
            # PAST THE END, which is a real answer about the collection's size
            # rather than a failure to report.
            samples[str(offset)] = {"status": "empty", "note": "past_end_of_collection"}
            continue
        games = [r for r in rows if is_game_market_row(r)]
        if games and first_game_offset is None:
            first_game_offset = offset
        samples[str(offset)] = {
            "status": "ok",
            "count": len(rows),
            "games": len(games),
            "types": sorted({sports_market_type(r) for r in rows if sports_market_type(r)}),
            "categories": sorted({str(r.get("category")) for r in rows if r.get("category")}),
            "first_id": str(rows[0].get("id")),
            "first_slug": str(rows[0].get("slug"))[:60],
            "start_min": min((str(r.get("gameStartTime") or "") for r in rows if r.get("gameStartTime")), default=None),
        }
    return {
        "status": "ok",
        # The number that decides the next step: an offset to page from, or
        # None meaning the open set genuinely contains no game markets.
        "first_game_offset": first_game_offset,
        "samples": samples,
    }


def probe_v1_sports_routes() -> dict[str, Any]:
    """Ask the LEGACY `/v1` sports routes what they return, by shape.

    Exists because concluding "the Sports API is not on this host" from four
    tested routes was an overreach. `/v1/sports` and `/v1/sports/teams` share
    the prefix that works for `/v1/markets`; everything confirmed 404 is either
    `/v2` or the `provider` sub-path. Those are different claims with opposite
    consequences, so this asks rather than assumes.

    READ-ONLY. Reports status and keys, never parses.
    """
    from syndicate.features.shared import polymarket_us_auth as auth

    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent"}

    out: dict[str, Any] = {}
    for name, path in (
        ("sports", "/v1/sports"),
        ("teams", "/v1/sports/teams"),
        ("teams_provider_no_league", "/v1/sports/teams/provider?provider=PROVIDER_SPORTRADAR"),
    ):
        url = f"{auth.BASE_URL}{path}"
        try:
            payload = auth.signed_request("GET", url)
        except Exception as exc:
            reason = (
                str(exc) if isinstance(exc, auth.PolymarketUSAuthError)
                else f"{type(exc).__name__}: {exc}"
            )
            out[name] = {"status": "error", "reason": reason[:300], "url": url}
            continue
        rows = None
        for key in ("sports", "teams", "data", "results"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
        sample = rows[0] if rows else None
        out[name] = {
            "status": "ok",
            "url": url,
            "payload_keys": sorted(payload.keys()),
            "count": len(rows) if rows is not None else None,
            "row_keys": sorted(sample.keys()) if isinstance(sample, Mapping) else None,
        }
    return {"status": "ok", "routes": out}


def team_alias_index(teams: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """`normalised alias -> team row`, for an EXACT lookup.

    Every name the venue publishes for a team points at that team. Building the
    index from the venue's own aliases is what makes the lookup exact; the
    alternative is a similarity threshold, where a miss and a wrong match are
    the same event at different scores.

    A collision -- two teams claiming one alias -- is DROPPED rather than
    resolved by insertion order. An ambiguous alias that silently picks one
    team is a bet on the wrong side of a game, and there is no cheaper place to
    catch it than here.
    """
    index: dict[str, Any] = {}
    collisions: set[str] = set()
    for team in teams:
        for field in _TEAM_NAME_FIELDS:
            alias = _normalise_team(team.get(field))
            if not alias:
                continue
            existing = index.get(alias)
            if existing is not None and existing.get("id") != team.get("id"):
                collisions.add(alias)
                continue
            index[alias] = team
    for alias in collisions:
        index.pop(alias, None)
    return index


def _normalise_team(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum())
