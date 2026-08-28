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

from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "fetch_markets",
    "is_settled_row",
    "MARKET_STATUS_OPEN",
    "fetch_league_slate",
    "fetch_teams",
    "probe_v1_sports_routes",
    "probe_market_query_params",
    "probe_offset_landscape",
    "find_first_game_offset",
    "fetch_game_markets",
    "persist_game_slate",
    "GAME_SLATE_ARTIFACT",
    "team_alias_index",
    "is_sporting_row",
    "is_game_market_row",
    "MONEYLINE_MARKET_TYPE",
    "SPREAD_MARKET_TYPE",
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
MONEYLINE_MARKET_TYPE = "SPORTS_MARKET_TYPE_MONEYLINE"
SPREAD_MARKET_TYPE = "SPORTS_MARKET_TYPE_SPREAD"
FUTURES_MARKET_TYPE = "SPORTS_MARKET_TYPE_FUTURE"

# MEASURED 2026-08-24T21:26:36Z, offset 16000 of the `closed=false` ordering:
#
#   types=['SPORTS_MARKET_TYPE_SPREAD'] categories=['sports']
#   first_slug='asc-nfl-nyg-nyj-2026-08-28-pos-1pt5'
#   start_min='2026-08-28T23:30:00Z'
#
# A real game market -- NFL, Giants at Jets, four days out, spread +1.5 -- and
# a market TYPE never seen before. The previous definition allowlisted
# MONEYLINE alone, from the only value observed at the time, so it counted this
# as `games=0`: the exact "guessed constant returns zero indistinguishably from
# absence" failure this module has hit at three different layers now.
#
# So the test is now an EXCLUSION. A game market is a sports market that is not
# season-level and is tied to a specific start time. That admits SPREAD, an
# unseen TOTAL, and anything else the venue adds, and it fails toward
# INCLUSION -- which for a counter is the safe direction, because an
# over-count is visible in the sample rows while an under-count reads as "the
# venue does not offer this".
_SEASON_LEVEL_TYPE_MARKERS = ("FUTURE", "CHAMPION", "AWARD", "SEASON")


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
    with `outcomes: ["Yes","No"]` has no game. A moneyline or a spread carries
    a `gameStartTime` that identifies one. Counting them together is how
    `sporting=1644` looked like a usable slate while containing no joinable row.

    Defined by EXCLUSION rather than an allowlist. See
    `_SEASON_LEVEL_TYPE_MARKERS`: the allowlist version knew only MONEYLINE and
    reported `games=0` on a page full of real NFL spreads.
    """
    if not is_sporting_row(row):
        return False
    market_type = sports_market_type(row)
    if market_type and any(m in market_type for m in _SEASON_LEVEL_TYPE_MARKERS):
        return False
    if market_type and any(m in market_type for m in _NON_SPORT_TYPE_MARKERS):
        return False
    # Tied to a specific game. A season-level market with no type would
    # otherwise slip through on category alone.
    return bool(str(row.get("gameStartTime") or "").strip())


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
        "futures": sum(1 for r in sporting if not is_game_market_row(r)),
        "game_types": _distinct(games, "sportsMarketTypeV2"),
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


def find_first_game_offset(
    *, ceiling: int = 40000, probe_limit: int = 5, max_probes: int = 20,
) -> dict[str, Any]:
    """Binary-search the offset where game markets begin.

    MEASURED 2026-08-24T21:36:46Z, the `closed=false` ordering is PARTITIONED:

        0..12000   season-level -- sports futures, then politics, then culture
        16000      SPORTS_MARKET_TYPE_SPREAD   asc-nfl-nyg-nyj-2026-08-28...
        18000      SPORTS_MARKET_TYPE_PROP     astatc-nfl-lar-lac-2026-08-27...
        20000      SPORTS_MARKET_TYPE_TOTAL    tsc-nfl-tb-jax-2026-08-28-1q...
        24000      PROP + TOTAL                astatc-mlb-pit-sd-2026-08-24...
        28000      empty -- past the end

    So the game slate is a contiguous block at the HIGH end, consistent with
    ids being assigned as markets are created.

    HARDCODING 16000 WOULD BREAK QUIETLY. Ids grow as the venue lists markets,
    so that boundary moves every day, and a stale constant would start the
    scan inside the futures block (wasted pages) or past the first games
    (silently missing part of the slate). Six or seven probes of five rows
    find it every time instead.

    The search assumes the partition above holds. That assumption is CHECKED,
    not trusted: `monotonic` is False if a probe finds games below the
    discovered boundary, which is the one way this could return a wrong answer
    confidently.
    """
    from syndicate.features.shared import polymarket_us_auth as auth

    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent"}

    probes = 0
    seen: dict[int, str] = {}

    # THREE PAGE STATES, NOT TWO, and conflating them is what broke this.
    #
    # The layout is [futures][games][empty]. The old probe returned a BOOL, so
    # a futures page and a past-the-end empty page were both `False` -- and
    # `False` sends the search UP (`low = mid + 1`). Its own comment claimed
    # "the search should move DOWN, which False achieves correctly", which is
    # the opposite of what the line below it did.
    #
    # Consequences, measured 2026-08-25 from 3:32 PM Central onward, on every
    # cycle and across two instances:
    #
    #     POLYMARKET_US_SLATE_WRITE status=error reason=no_game_offset: ok
    #
    # -- a reason string that contradicts itself, because `status` was "ok"
    # while `first_game_offset` was None. The slate artifact stopped
    # refreshing (2,903s stale in the 3:48 PM reprice) and Polymarket could
    # place nothing.
    #
    # An EMPTY page means the block is BELOW us; a FUTURES page means it is
    # ABOVE us. Told apart, the search is correct wherever the block sits.
    _GAMES, _FUTURES, _EMPTY = "games", "futures", "empty"

    def _page(offset: int) -> str | None:
        nonlocal probes
        if offset in seen:
            return seen[offset]
        if probes >= max_probes:
            return None
        probes += 1
        url = (f"{auth.BASE_URL}/v1/markets?limit={int(probe_limit)}"
               f"&offset={int(offset)}&{_LIVE_FILTER}")
        try:
            payload = auth.signed_request("GET", url)
        except Exception:
            return None
        rows = [r for r in (payload.get("markets") or []) if isinstance(r, Mapping)]
        if not rows:
            state = _EMPTY
        elif any(is_game_market_row(r) for r in rows):
            state = _GAMES
        else:
            state = _FUTURES
        seen[offset] = state
        return state

    # THE CEILING IS DERIVED, NOT TRUSTED. This function's own docstring says
    # hardcoding 16000 "would break quietly" because ids grow as the venue
    # lists markets -- and then hardcoded 40000 one line down. A ceiling that
    # still shows FUTURES is a ceiling below the block, so it doubles until it
    # reaches empty-or-games. Bounded by `max_probes` like every other probe.
    top = int(ceiling)
    for _ in range(6):
        state = _page(top)
        if state is None:
            return {
                "status": "error",
                "reason": f"probe_failed_at_ceiling_{top}",
                "probes": probes,
                "sampled": dict(sorted(seen.items())),
            }
        if state != _FUTURES:
            break
        top *= 2
    else:
        # Still futures after six doublings: the partition assumption does not
        # hold, or the catalogue is far larger than this search is shaped for.
        # NAMED, never returned as a quiet None.
        return {
            "status": "error",
            "reason": f"ceiling_below_game_block: futures at offset {top}",
            "probes": probes,
            "ceiling": top,
            "sampled": dict(sorted(seen.items())),
        }

    low, high = 0, top
    while low < high:
        mid = (low + high) // 2
        state = _page(mid)
        if state is None:
            return {
                "status": "error",
                "reason": f"probe_failed_at_offset_{mid}",
                "probes": probes,
                "sampled": dict(sorted(seen.items())),
            }
        if state == _FUTURES:
            low = mid + 1          # the block is above us
        else:
            high = mid             # games here, or past the end -- look lower

    boundary = low if _page(low) == _GAMES else None
    if boundary is None:
        # THE FAILURE IS AN ERROR, NOT AN "ok" WITH A NULL. A status that says
        # fine beside a result that says nothing is what produced
        # `no_game_offset: ok` and told nobody anything. The sampled map goes
        # with it so the next reading says WHICH shape was seen where.
        return {
            "status": "error",
            "reason": "no_game_page_found",
            "probes": probes,
            "ceiling": top,
            "sampled": dict(sorted(seen.items())),
        }
    # THE ASSUMPTION, CHECKED. If any offset BELOW the boundary had games, the
    # collection is not partitioned and this answer is not trustworthy.
    monotonic = not any(
        state == _GAMES for off, state in seen.items() if off < boundary
    )
    return {
        "status": "ok",
        "first_game_offset": boundary,
        "probes": probes,
        "monotonic": monotonic,
        "ceiling": top,
        "sampled": dict(sorted(seen.items())),
    }


# Pages per `fetch_markets` call while sweeping. The sweep keeps only game
# rows, so peak memory is one chunk of raw rows rather than the whole
# collection -- ~5,000 instead of ~23,000.
_SCAN_CHUNK_PAGES = 10


def fetch_game_markets(
    *, limit: int = 500, max_pages: int = 200, start_offset: int | None = None,
) -> dict[str, Any]:
    """Every game market in the open catalogue. THERE IS NO BOUNDARY TO FIND.

    --------------------------------------------------------------------------
    WHY THIS NO LONGER BINARY-SEARCHES, AND WHY THAT WAS NEVER GOING TO WORK
    --------------------------------------------------------------------------

    This used to call `find_first_game_offset` and page from what it returned,
    on the premise that the `closed=false` ordering is `[futures][games][empty]`.
    **Probed directly 2026-08-25T22:54:25Z, that premise is false:**

        12,578   GAMES 5/5 SPREAD   asc-nfl-ne-cle-2026-08-27-pos-1pt5
        16,771   GAMES 5/5 TOTAL    tsc-nfl-pit-buf-2026-08-27-1q-5pt5
        18,867   GAMES 5/5 TOTAL    tsc-nfl-cin-phi-2026-08-28-4q-17pt5
        19,915   futures (golf)     tec-dpwt-britmast-2026-08-27-r1l-jorlof
        20,754   futures (LPGA)     tec-lpga-fmcham-2026-08-27-r3l-hyecho
        20,964   BOUNDARY           tec-f1-pigp-2026-09-06-cons-alpine
        22,964   GAMES 5/5 PROP     astatc-mlb-lad-atl-2026-08-25-xi

    A band of golf/F1 futures sits ABOVE a large block of game markets. Ids are
    assigned by creation time and the venue creates futures and game markets
    continuously, so the collection is interleaved and **no single boundary
    exists**. The search converged into that upper futures band and everything
    below it -- ~8,400 rows, including NFL full-game spreads two days before
    week 1 -- was never fetched. `games` read 7,936 against 13,255 hours
    earlier, on a scan reporting `truncated=False`.

    Nothing caught it because `monotonic` only checks offsets the search itself
    probed, so a boundary inside a futures band above the block satisfies it.
    **A guard whose true value carries no information is not a guard**, and it
    was the only check on the premise. Full working: `todo.md` `#559`,
    `deploys.md` 2026-08-25T22:54:25Z.

    So this SWEEPS. Correct by construction: a market is kept because it IS a
    game market, never because of where it sits. The cost is ~46 pages instead
    of ~17 on a free API, and the byte consequence is already handled one
    function down by `_slate_within_budget`, which orders by game date and has
    5.99MB of headroom it has never touched.

    CHUNKED, so peak memory is one chunk of raw rows rather than the whole
    collection. `fetch_markets` accumulates every row it reads before filtering;
    sweeping 23,000 rows through it in one call would triple this worker's
    retained set for no reason, on a service that has been OOM-killed before.

    `start_offset` is kept for callers that genuinely want a partial sweep, and
    is REPORTED so a partial read can never be mistaken for a complete one. The
    default is 0 -- the whole collection.
    """
    swept_from = 0 if start_offset is None else int(start_offset)
    offset = swept_from
    kept: list[Mapping[str, Any]] = []
    pages = scanned = futures_skipped = duplicate_ids = 0
    game_types: set[str] = set()
    starts: list[str] = []
    reached_end = False
    payload_keys: list[str] | None = None

    while pages < int(max_pages):
        chunk = fetch_markets(
            limit=limit,
            max_pages=min(_SCAN_CHUNK_PAGES, int(max_pages) - pages),
            offset=offset,
        )
        if chunk.get("status") != "ok":
            if not kept:
                return chunk
            # A failure PART WAY THROUGH is a partial sweep, not a slate. Say so
            # by name rather than returning what we happened to reach, which
            # would read as a complete catalogue one row short.
            return {
                "status": "partial",
                "reason": f"sweep_failed_at_offset_{offset}: {chunk.get('reason')}",
                "markets": list(kept),
                "count": len(kept),
                "swept_from": swept_from,
                "scanned_rows": scanned,
                "pages": pages,
                "truncated": True,
            }

        chunk_pages = int(chunk.get("pages") or 0)
        scanned += int(chunk.get("total_rows") or 0)
        duplicate_ids += int(chunk.get("duplicate_ids") or 0)
        payload_keys = chunk.get("payload_keys") or payload_keys

        # `fetch_markets` returns rows already trimmed and filtered to sporting.
        for row in chunk.get("markets") or []:
            if is_game_market_row(row):
                kept.append(row)
                market_type = sports_market_type(row)
                if market_type:
                    game_types.add(market_type)
                start = _game_start(row)
                if start:
                    starts.append(start)
            else:
                futures_skipped += 1

        pages += chunk_pages
        offset += chunk_pages * int(limit)
        if not chunk.get("truncated"):
            # A short page: the end of the collection, which is the ONLY
            # condition that makes this sweep complete.
            reached_end = True
            break
        if chunk_pages == 0:
            break

    starts.sort()
    return {
        "status": "ok",
        "markets": list(kept),
        "count": len(kept),
        "games": len(kept),
        "futures": futures_skipped,
        "game_types": sorted(game_types),
        "total_rows": scanned,
        "scanned_rows": scanned,
        "pages": pages,
        # TRUE means the sweep hit its page budget before the end of the
        # collection -- i.e. there is more and we did not read it. False means
        # a short page ended it, which is the only complete read.
        "truncated": not reached_end,
        "duplicate_ids": duplicate_ids,
        "orderable": sum(1 for r in kept if r.get("orderable")),
        "game_start_min": starts[0] if starts else None,
        "game_start_max": starts[-1] if starts else None,
        # Where the sweep began. 0 unless a caller asked for a partial read --
        # reported so a partial can never read as a complete one.
        "swept_from": swept_from,
        "start_offset": swept_from,
        # The boundary search is GONE from this path. Kept as explicit nulls so
        # the worker's log line renders, and so anyone grepping for the old
        # fields finds them saying "not applicable" rather than nothing.
        "boundary_probes": None,
        "boundary_monotonic": None,
        "payload_keys": payload_keys,
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


# --------------------------------------------------------------------------
# PERSISTENCE -- so the fan-in reads an ARTIFACT, not this venue's API
# --------------------------------------------------------------------------
#
# `venue_quote_adapters` deliberately never calls a venue API: a second
# independent caller for one venue is a documented incident class here
# (`#139/#144` for MLB, `#148` for soccer). So the slate has to land somewhere
# a reader can find it, with a timestamp it can defend.

GAME_SLATE_ARTIFACT = ("intelligence", "polymarket_us_games.json")

# How often the slate writer runs, in seconds.
#
# NAMED HERE SO THE FRESHNESS CEILING CAN BE DERIVED FROM IT rather than
# restated. `execute_portfolio._polymarket_max_price_age_seconds` is documented
# as a MULTIPLE of this cadence -- and it drifted: the ceiling stayed at 1800s
# (twice a 900s writer) when the writer dropped to 180s, which quietly made it
# ten times the cadence. A guard that tolerates nine missed writes is still
# present, still logged, and no longer guarding anything.
#
# One constant, two readers, so the relationship the docstrings claim is the
# one the code has.
SLATE_INTERVAL_SECONDS = 180

# `refresh_state_store`'s keyvalue backend refuses a write past this.
_KEYVALUE_CEILING_BYTES = 8 * 1024 * 1024

# EXACTLY what the fan-in adapter and the order builder read, and nothing else.
# Measured 2026-08-24: the full trimmed row is 4.9MB across 7,585 markets --
# under the ceiling but with thin headroom on a slate that grows toward a
# matchday. These fields are 2.1MB, 43% of that.
#
#   outcomes/outcomePrices/sportsMarketTypeV2/line   the quote
#   slug/gameStartTime                               the join key
#   orderPriceMinTickSize/minimumTradeQty            what order_body REFUSES
#                                                    to infer
_SLATE_STORAGE_FIELDS = (
    "slug", "sportsMarketTypeV2", "outcomes", "outcomePrices", "line",
    "gameStartTime", "orderPriceMinTickSize", "minimumTradeQty", "orderable",
)


def _slate_row_for_storage(row: Mapping[str, Any]) -> dict[str, Any]:
    """The persisted row. Drops `question`, `description`, `tags`, `category`
    and the rest -- readable from the venue on demand, and none of them is read
    by anything downstream of this artifact."""
    return {key: row[key] for key in _SLATE_STORAGE_FIELDS if key in row}


# How much of the ceiling the slate may use. The remainder is margin: the
# envelope keys, and the fact that a row's size is estimated per-row and summed
# rather than re-serialised at every step.
_SLATE_BYTE_BUDGET = int(_KEYVALUE_CEILING_BYTES * 0.90)


def _slate_date(row: Mapping[str, Any]) -> str:
    """The row's game DATE, or "" when it carries none.

    Empty sorts FIRST deliberately. A game row with no `gameStartTime` cannot
    be ranked, and dropping what we cannot rank is how a real market disappears
    without appearing in any count.
    """
    text = str(row.get("gameStartTime") or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _slate_within_budget(
    markets: Sequence[Mapping[str, Any]], *, budget: int = _SLATE_BYTE_BUDGET
) -> dict[str, Any]:
    """Keep the NEAREST games and drop the furthest-out ones, by name.

    THE OLD TRUNCATION CUT BY OFFSET, WHICH IS ARBITRARY WITH RESPECT TO DATE.
    `fetch_markets` stopped after `max_pages` and set `truncated=True`, so
    whatever happened to sit past 30 pages was gone -- and the venue orders by
    id, not by kickoff. Measured 2026-08-25 2:59:40 PM Central:

        POLYMARKET_US_SLATE_WRITE status=ok count=13243 bytes=3920483
          truncated=True

    That is a slate we cannot resolve orders against and cannot tell which part
    is missing. `market_unresolved_for_position` on
    `tsc-mlb-cin-sf-2026-08-25-7pt5` at 3:55 PM is exactly the symptom: a real
    market on tonight's game, absent from our copy for no reason connected to
    the game.

    Ordering by date makes the cut MEAN something. Tonight's slate is what we
    trade; a market eight days out is what we can afford to lose. And the
    dropped dates are REPORTED, so "we chose not to store this" never reads as
    "the venue does not list it" -- the distinction this whole integration
    keeps paying for.

    Rows are measured individually and summed rather than re-serialised per
    step: an exact check on the finished payload still runs in
    `persist_game_slate`, and this only has to get the ORDER and the rough size
    right.
    """
    import json as _json

    ordered = sorted(markets, key=_slate_date)
    kept: list[Mapping[str, Any]] = []
    used = 0
    dropped_by_date: dict[str, int] = {}
    for row in ordered:
        size = len(_json.dumps(row)) + 1
        if used + size > budget and kept:
            dropped_by_date[_slate_date(row) or "<undated>"] = (
                dropped_by_date.get(_slate_date(row) or "<undated>", 0) + 1
            )
            continue
        kept.append(row)
        used += size
    return {
        "markets": kept,
        "dropped": sum(dropped_by_date.values()),
        "dropped_by_date": dict(sorted(dropped_by_date.items())),
        "kept_through": _slate_date(kept[-1]) if kept else None,
        "estimated_bytes": used,
    }


def persist_game_slate(*, limit: int = 500, max_pages: int = 200) -> dict[str, Any]:
    """Fetch the joinable slate and write it for the fan-in to read.

    Writes `fetched_at` INTO the payload rather than relying on the file's
    mtime. An artifact republished unchanged gets a fresh mtime while its
    contents are hours old -- `PUBLISH_SKIPPED_UNCHANGED` and the artifact-pull
    sweep both touch files that way -- and trusting mtime there would launder
    stale odds as fresh, which is the exact failure the fan-in exists to catch.

    A failed fetch LEAVES THE PREVIOUS SLATE IN PLACE. Clearing it would turn
    "we could not reach Polymarket" into "Polymarket lists nothing", and those
    need opposite responses.
    """
    import time as _time

    from syndicate.features.shared.refresh_state_store import reports_root, write_json_file

    slate = fetch_game_markets(limit=limit, max_pages=max_pages)
    if slate.get("status") != "ok":
        return {"status": "error", "reason": slate.get("reason"), "written": False, "kept_previous": True}

    # PAGE TO EXHAUSTION, THEN CHOOSE WHAT TO DROP -- in that order.
    #
    # `max_pages` defaulted to 30, so at limit=500 the fetch stopped after
    # 15,000 rows whether or not the venue had more, and it did:
    # `count=13243 truncated=True` on 2026-08-25 at 2:59:40 PM Central. The
    # repo measured `games=7585, truncated=False` on 2026-08-24, so the
    # catalogue outgrew the constant in a day -- the same failure as
    # `find_first_game_offset`'s hardcoded ceiling, one function over.
    #
    # `fetch_markets` already stops on a short page, so a high bound costs
    # nothing on a small slate and only binds on a genuinely huge one.
    # ------------------------------------------------------------------
    # WHICH OUTCOME DOES THE YES TOKEN PAY? NOBODY HAS EVER LOOKED.
    # ------------------------------------------------------------------
    #
    # `marketSides` and `question` have been in `_KEEP` since this module was
    # written and are read by nothing; `_slate_row_for_storage` drops both on
    # the next line. Only their KEY NAMES have ever reached a log
    # (`POLYMARKET_US_AUTH ... row_keys=[...]`), never their values.
    #
    # That gap is what makes `polymarket_us_orders._resolve_outcome_side` refuse
    # a team side as of 2026-08-28: the YES leg is measurably NOT `outcomes[0]`
    # (3 of 8 settled moneylines bought the wrong team) and no stored field
    # names it, so the sound rule cannot be written. One of these two fields
    # very likely does name it -- a `question` reading "Will the Tigers beat the
    # Dodgers?" settles it outright -- and one log line is the whole cost of
    # finding out.
    #
    # ONE MONEYLINE ROW PER WRITE, not per market: this is a shape report in the
    # pattern `fetch_polymarket_resolutions` and `kalshi_client` already use,
    # and the thing being reported is a schema, not a slate. Truncated, because
    # `description` sits beside these and is prose.
    _shape = next(
        (
            m for m in (slate.get("markets") or [])
            if sports_market_type(m) == MONEYLINE_MARKET_TYPE
            and (m.get("marketSides") is not None or m.get("question"))
        ),
        None,
    )
    if _shape is not None:
        print(
            "[polymarket_us_markets] MONEYLINE_YES_LEG_SHAPE"
            f" slug={_shape.get('slug')!r}"
            f" outcomes={_shape.get('outcomes')!r}"
            f" outcomePrices={_shape.get('outcomePrices')!r}"
            f" marketSides={str(_shape.get('marketSides'))[:400]!r}"
            f" question={str(_shape.get('question') or '')[:200]!r}"
            " -- WHICH OUTCOME IS YES? see polymarket_us_orders"
            "._resolve_outcome_side",
            flush=True,
        )
    else:
        # A named zero. "No moneyline in the slate" and "the fields are absent
        # from every moneyline" are different findings and must not both render
        # as silence -- that is the same rule this module already applies to
        # `sporting=0`.
        print(
            "[polymarket_us_markets] MONEYLINE_YES_LEG_SHAPE none"
            f" moneylines={sum(1 for m in (slate.get('markets') or []) if sports_market_type(m) == MONEYLINE_MARKET_TYPE)}"
            " -- no moneyline row carried marketSides or question",
            flush=True,
        )

    fetched = [_slate_row_for_storage(m) for m in (slate.get("markets") or [])]
    budgeted = _slate_within_budget(fetched)
    markets = budgeted["markets"]
    payload = {
        "fetched_at": _time.time(),
        "markets": markets,
        "count": len(markets),
        "start_offset": slate.get("start_offset"),
        # THE FETCH's truncation, which should now be False. Kept distinct from
        # the budget drop below: "the venue had more than we asked for" and "we
        # chose not to store the far end" are different facts and only one of
        # them is a bug.
        "truncated": slate.get("truncated"),
        "fetched_count": len(fetched),
        "dropped_for_size": budgeted["dropped"],
        "dropped_by_date": budgeted["dropped_by_date"],
        "kept_through": budgeted["kept_through"],
        "game_types": slate.get("game_types"),
        "game_start_min": slate.get("game_start_min"),
        "game_start_max": slate.get("game_start_max"),
    }
    # SIZE IS CHECKED BEFORE THE WRITE, not discovered by its failure.
    # `refresh_state_store`'s keyvalue backend refuses past ~8MB, and #60's
    # rule is "shrink the payload rather than raise the ceiling" -- Novig hit
    # exactly this at 9,128,668 bytes on 2026-08-24 and had to trim after the
    # outage. Measured here: the full trimmed row is 4.9MB at 7,585 markets and
    # GROWS toward a matchday, so the lean row (2.1MB, 43%) is what persists.
    import json as _json

    size_bytes = len(_json.dumps(payload))
    if size_bytes > _KEYVALUE_CEILING_BYTES:
        return {
            "status": "too_large_to_persist",
            "reason": f"{size_bytes} bytes exceeds {_KEYVALUE_CEILING_BYTES}",
            "count": len(markets), "bytes": size_bytes, "written": False,
        }

    path = reports_root().joinpath(*GAME_SLATE_ARTIFACT)
    try:
        write_json_file(path, payload)
    except Exception as exc:  # noqa: BLE001 -- reported, never raised into the loop
        # Same shape as Novig's 8MB keyvalue ceiling failure: the fetch
        # succeeded and the caller can still use the result; only the cache is
        # missing, and saying which is what makes it diagnosable.
        return {
            "status": "fetched_not_written",
            "reason": f"{type(exc).__name__}: {exc}",
            "count": len(markets),
            "written": False,
        }
    return {
        "status": "ok",
        "written": True,
        "count": len(markets),
        # Reported every run so growth toward the ceiling is visible BEFORE it
        # becomes a write failure, which is how Novig's was found.
        "bytes": size_bytes,
        "headroom_bytes": _KEYVALUE_CEILING_BYTES - size_bytes,
        "truncated": slate.get("truncated"),
        # NEVER SILENT. A slate that dropped its far end must say so and say
        # which dates, or the next `market_unresolved_for_position` is
        # indistinguishable from the venue not listing the market.
        "fetched_count": len(fetched),
        "dropped_for_size": budgeted["dropped"],
        "dropped_by_date": budgeted["dropped_by_date"],
        "kept_through": budgeted["kept_through"],
        "game_types": slate.get("game_types"),
    }
