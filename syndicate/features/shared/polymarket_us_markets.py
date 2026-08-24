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
    "fetch_league_events",
    "fetch_teams",
    "team_alias_index",
    "is_sporting_row",
    "trimmed_row",
    "league_slug_for_sport",
    "SPORTS_FIELDS",
    "ORDER_REQUIRED_FIELDS",
    "LEAGUE_SLUGS",
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


def is_sporting_row(row: Mapping[str, Any]) -> bool:
    """Does this row carry sports structure at all?

    Presence, not value. `gameStartTime` alone is enough: a market tied to a
    specific game start is a game market whatever the venue calls its type.
    """
    for field in SPORTS_FIELDS:
        value = row.get(field)
        if value not in (None, "", [], {}):
            return True
    return False


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


def fetch_markets(*, limit: int = _DEFAULT_LIMIT, active: bool = True) -> dict[str, Any]:
    """One signed read of the US catalogue, reported by shape.

    Never raises for a venue problem -- this runs inside a refresh loop, and a
    venue being unreachable must degrade to a NAMED refusal rather than take
    the loop down. `credentials_absent` and a failed call are separate reasons
    because they need completely different responses.
    """
    from syndicate.features.shared import polymarket_us_auth as auth

    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent", "markets": []}

    url = f"{auth.BASE_URL}/v1/markets?limit={int(limit)}"
    if active:
        url += "&active=true"
    try:
        payload = auth.signed_request("GET", url)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, auth.PolymarketUSAuthError) else f"{type(exc).__name__}: {exc}"
        return {"status": "error", "reason": reason, "markets": []}

    rows = payload.get("markets")
    if not isinstance(rows, list):
        # The one key the probe confirmed. If it is gone, say so by name rather
        # than returning an empty catalogue, which reads as "no markets".
        return {
            "status": "error",
            "reason": f"markets_key_absent: payload_keys={sorted(payload.keys())}",
            "markets": [],
        }

    sporting = [r for r in rows if isinstance(r, Mapping) and is_sporting_row(r)]
    trimmed = [trimmed_row(r) for r in sporting]
    return {
        "status": "ok",
        "markets": trimmed,
        "count": len(trimmed),
        "total_rows": len(rows),
        # Exactly the page we asked for means we cannot tell whether there is
        # more. Reported rather than silently accepted as the whole catalogue.
        "truncated": len(rows) >= int(limit),
        "orderable": sum(1 for r in trimmed if r.get("orderable")),
        # THE POINT OF THE FIRST RUN. No value of these has ever been observed,
        # so the next pass designs the sport/market mapping from what is really
        # there instead of from a guess that would return zero.
        "sports_market_types": _distinct(sporting, "sportsMarketTypeV2"),
        "market_types": _distinct(sporting, "marketType"),
        "categories": _distinct(sporting, "category"),
        "payload_keys": sorted(payload.keys()),
        "row_keys": sorted(rows[0].keys()) if rows and isinstance(rows[0], Mapping) else None,
    }


# --------------------------------------------------------------------------
# THE SPORTS API -- a league-scoped slate instead of a filtered catalogue
# --------------------------------------------------------------------------
#
# `GET /v2/leagues/{slug}/events` returns one league's events directly, which
# is strictly better than pulling `/v1/markets` and filtering: it cannot be
# swamped by politics the way the global pull was (`count=100 sporting=0` every
# cycle), and `limit`/`offset` are DOCUMENTED here, so paging is a mechanism
# rather than the guess `/v1/markets` still requires.
#
# `fetch_markets` above is kept regardless. It is the only route whose response
# shape has actually been observed, and it carries `orderPriceMinTickSize` and
# `minimumTradeQty` -- so if an event's nested markets turn out not to carry
# those, the catalogue is where they come from.

_LEAGUE_EVENTS_PATH = "/v2/leagues/{slug}/events"
_TEAMS_PROVIDER_PATH = "/v1/sports/teams/provider"

# Two documented providers. Which of them is actually populated for a given
# league has not been observed, so it is overridable without a deploy -- the
# same escape hatch `POLYMARKET_US_ORDER_PATH` exists for, and for the same
# reason: Kalshi's route moved and cost an http_410 to discover.
DEFAULT_TEAM_PROVIDER = "PROVIDER_SPORTRADAR"

# Syndicate sport -> Polymarket league slug, and whether that slug is
# DOCUMENTED or merely assumed from the same convention. The distinction is
# kept because an empty slate means completely different things either way: for
# a documented slug it is "no games today", for an assumed one it is most
# likely "the slug is wrong". Collapsing them would make a typo look like an
# off day, which is the absence/failure confusion this layer exists to prevent.
LEAGUE_SLUGS: dict[str, tuple[str, bool]] = {
    # Documented verbatim: "League slug (e.g., nfl, nba, mlb)".
    "mlb": ("mlb", True),
    "nba": ("nba", True),
    "nfl": ("nfl", True),
    # Assumed from the same convention. Never confirmed against the venue.
    "nhl": ("nhl", False),
    "wnba": ("wnba", False),
    "ncaaf": ("ncaaf", False),
    "ncaab": ("ncaab", False),
}


def league_slug_for_sport(sport: Any) -> tuple[str | None, bool]:
    """`(slug, documented)`. An unknown sport returns `(None, False)`."""
    return LEAGUE_SLUGS.get(str(sport or "").strip().lower(), (None, False))


def _event_markets(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The markets hanging off an event, wherever the venue puts them.

    The response shape of the events route has NOT been observed -- the docs
    describe its parameters and not its body. Rather than assume one key, this
    looks in the plausible places and reports finding none, so the first live
    run corrects it from data instead of returning a slate with no prices and
    no explanation.
    """
    for key in ("markets", "Markets", "marketList"):
        value = event.get(key)
        if isinstance(value, list):
            return [m for m in value if isinstance(m, Mapping)]
    return []


def fetch_league_events(
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
    from syndicate.features.shared import polymarket_us_auth as auth

    slug, documented = league_slug_for_sport(sport)
    if slug is None:
        return {"status": "skipped", "reason": f"no_league_slug_for_sport: {sport}", "events": []}
    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent", "events": []}

    path = _LEAGUE_EVENTS_PATH.format(slug=slug)
    events: list[Mapping[str, Any]] = []
    pages = 0
    truncated = False
    payload_keys: list[str] = []

    for page in range(int(max_pages)):
        offset = page * int(limit)
        url = f"{auth.BASE_URL}{path}?limit={int(limit)}&offset={offset}&type={event_type}"
        try:
            payload = auth.signed_request("GET", url)
        except Exception as exc:
            reason = (
                str(exc) if isinstance(exc, auth.PolymarketUSAuthError)
                else f"{type(exc).__name__}: {exc}"
            )
            # A failure on page 0 is a failure. A failure on page 3 still has
            # three real pages in hand, so it degrades to a partial result that
            # SAYS it is partial rather than throwing away what was fetched.
            if not events:
                return {
                    "status": "error", "reason": reason, "events": [],
                    "league_slug": slug, "slug_documented": documented,
                }
            truncated = True
            payload_keys = payload_keys or []
            break

        pages += 1
        payload_keys = sorted(payload.keys())
        batch = None
        for key in ("events", "data", "results"):
            if isinstance(payload.get(key), list):
                batch = payload[key]
                break
        if batch is None:
            return {
                "status": "error",
                "reason": f"events_key_absent: payload_keys={payload_keys}",
                "events": [], "league_slug": slug, "slug_documented": documented,
            }
        events.extend(e for e in batch if isinstance(e, Mapping))
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
        # See LEAGUE_SLUGS: an empty slate reads differently for an assumed slug.
        "slug_documented": documented,
        "events": events,
        "event_count": len(events),
        "pages": pages,
        "truncated": truncated,
        "markets": trimmed,
        "market_count": len(trimmed),
        "orderable": sum(1 for m in trimmed if m.get("orderable")),
        # If this is 0 while `event_count` is not, the events route nests its
        # markets somewhere `_event_markets` does not look -- a named, visible
        # gap rather than a silently priceless slate.
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
