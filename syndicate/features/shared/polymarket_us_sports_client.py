"""Polymarket US's dedicated Sports API -- events by league or sport.

--------------------------------------------------------------------------
WHY THIS IS A SEPARATE MODULE FROM `polymarket_client.py` AND NOT JUST A
NEW FUNCTION ON `polymarket_us_orders.py`
--------------------------------------------------------------------------

`polymarket_client.py` talks to the GLOBAL, on-chain venue
(`gamma-api.polymarket.com`) -- its `/markets` listing is a general catalogue
with no sport scoping, and the one real production pull measured so far
(`.syndicate/deploys.md` 2026-08-24) came back `sporting=0` of the top 100:
politics and crypto-forecasting markets, no sports at all in that page.

`polymarket_us_auth.py`/`polymarket_us_orders.py` talk to the US venue
(`api.polymarket.us`) -- a DIFFERENT exchange, different auth (Ed25519,
already confirmed working: `POLYMARKET_US_AUTH ok=True`,
`.syndicate/deploys.md` 2026-08-24T19:29:14Z), different money. That module
is the ORDER path (`order_body`, `submit_order`) for whichever markets it is
pointed at; it has no sport-scoped discovery of its own.

This module is that discovery, for the specific Sports API the user supplied
verbatim (session transcript, 2026-08-24) -- `GET /v2/leagues/{slug}/events`
and `GET /v2/sports/{slug}/events`, plus the legacy `/v1/sports*` family. It
reuses `polymarket_us_auth.signed_request` (which signs from the URL's own
path, so a v2 path signs exactly like a v1 one -- nothing in that module
needed to change) rather than duplicating credential handling, and imports
nothing from `polymarket_us_orders.py` -- discovery must never gain the
ability to place an order by accident of a shared import.

--------------------------------------------------------------------------
THE ENDPOINT SHAPE IS DOCUMENTED THIS TIME -- THE ROW SCHEMA IS NOT
--------------------------------------------------------------------------

The user pasted Polymarket's own Sports API and Sports (Legacy) API reference
pages directly, so `_LEAGUE_EVENTS_PATH`/`_SPORT_EVENTS_PATH`/the legacy paths
and their query parameters are DOCUMENTED, not guessed -- unlike
`polymarket_client._MARKET_FIELDS`, which was written from third-party
research and got 2 of 18 fields wrong on its first live call.

But the docs describe the ENDPOINTS, not one example event row -- no field
list for what `/v2/leagues/{slug}/events` actually returns. So `probe_*`
below reports the SHAPE that comes back, unparsed, before anything here
trusts a field name -- the same discipline that caught Kalshi's ten wrong
fields and Polymarket global's two.

--------------------------------------------------------------------------
LEAGUE SLUGS: DOCUMENTED EXAMPLES ONLY FOR THREE, THE REST ARE A GUESS
--------------------------------------------------------------------------

The docs give `nfl`, `nba`, `mlb` as example league slugs and nothing more.
`_SYNDICATE_TO_POLYMARKET_LEAGUE` maps Syndicate's own sport keys to a slug
guess for the rest (wnba, nhl, ncaaf, ncaab, soccer) using the same
lowercase-abbreviation pattern the three confirmed examples share. THESE ARE
UNVERIFIED and marked as such in the mapping's own comment -- `probe_league`
against each is what turns a guess into a fact, not further pattern-matching.
A 404/empty response for a guessed slug is a normal, expected outcome to
report, not a bug in this module.

--------------------------------------------------------------------------
READ-ONLY, AND STRUCTURALLY SO
--------------------------------------------------------------------------

Every function here is a GET. Nothing imports `polymarket_us_orders`, and
nothing here builds a request body. Discovery and order placement stay two
separate modules on purpose, matching this file's own header reasoning above.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "PolymarketUSSportsError",
    "syndicate_sport_to_polymarket_league",
    "fetch_league_events",
    "fetch_sport_events",
    "probe_league",
    "probe_all_leagues",
]

# Verbatim from the user-supplied Sports API reference, 2026-08-24.
_LEAGUE_EVENTS_PATH = "/v2/leagues/{slug}/events"
_SPORT_EVENTS_PATH = "/v2/sports/{slug}/events"

# Syndicate sport key -> Polymarket league slug. `nfl`/`nba`/`mlb` are the
# docs' own documented examples; everything else is an UNVERIFIED guess at
# the same naming pattern (see module header) and needs `probe_league` to
# confirm before anything treats it as real.
_SYNDICATE_TO_POLYMARKET_LEAGUE: dict[str, str] = {
    "nfl": "nfl",          # documented example
    "nba": "nba",          # documented example
    "mlb": "mlb",          # documented example
    "wnba": "wnba",        # UNVERIFIED guess
    "nhl": "nhl",          # UNVERIFIED guess
    "ncaaf": "ncaaf",       # UNVERIFIED guess
    "ncaab": "ncaab",       # UNVERIFIED guess
    # Soccer has no single Syndicate league key (multiple competitions) and no
    # documented slug at all -- deliberately absent rather than guessed twice
    # over. A real probe of `/v2/sports/football/events` (soccer is a SPORT,
    # not a league, on most sports data providers' vocabulary) may be the
    # right shape instead; add it once that is confirmed, not before.
}


class PolymarketUSSportsError(RuntimeError):
    """Raised only where continuing would report a result that was never
    actually confirmed against the venue."""


def syndicate_sport_to_polymarket_league(sport: str) -> str | None:
    """`None` for a sport with no known-or-guessed slug -- never invents one
    at call time. See the mapping's own comment for which entries are
    documented versus guessed."""
    return _SYNDICATE_TO_POLYMARKET_LEAGUE.get(str(sport or "").strip().lower())


def _events_url(path_template: str, slug: str, *, limit=None, offset=None, type_=None, section=None) -> str:
    import urllib.parse

    from syndicate.features.shared.polymarket_us_auth import BASE_URL
    import os

    base = (os.environ.get("POLYMARKET_US_API_BASE") or "").strip() or BASE_URL
    path = path_template.format(slug=urllib.parse.quote(str(slug), safe=""))
    query: dict[str, str] = {}
    if limit is not None:
        query["limit"] = str(int(limit))
    if offset is not None:
        query["offset"] = str(int(offset))
    if type_ is not None:
        # Documented values: "sport" (default) or "futures".
        query["type"] = str(type_)
    if section is not None:
        # Documented values: "general" (default) or "trending".
        query["section"] = str(section)
    url = f"{base.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    return url


def _get_events(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """One signed GET, returning the decoded payload or a named error --
    never raising past this function, matching every other venue probe in
    this lane (a venue being unreachable must degrade to a named refusal)."""
    from syndicate.features.shared.polymarket_us_auth import (
        PolymarketUSAuthError,
        credentials_present,
        signed_request,
    )

    if not credentials_present():
        return {"status": "error", "reason": "credentials_absent", "url": url}
    try:
        payload = signed_request("GET", url, timeout=timeout)
    except PolymarketUSAuthError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    except Exception as exc:  # noqa: BLE001 -- named, never crashes the caller
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", "url": url}
    return {"status": "ok", "payload": payload, "url": url}


def fetch_league_events(
    slug: str, *, limit: int | None = None, offset: int | None = None,
    type_: str | None = None, section: str | None = None,
) -> dict[str, Any]:
    """`GET /v2/leagues/{slug}/events`. `slug` is a Polymarket league slug
    (e.g. `"nfl"`) -- pass the result of `syndicate_sport_to_polymarket_league`
    for a Syndicate sport key, not the Syndicate key itself."""
    url = _events_url(_LEAGUE_EVENTS_PATH, slug, limit=limit, offset=offset, type_=type_, section=section)
    return _get_events(url)


def fetch_sport_events(
    slug: str, *, limit: int | None = None, offset: int | None = None,
    type_: str | None = None, section: str | None = None,
) -> dict[str, Any]:
    """`GET /v2/sports/{slug}/events` -- every league under one sport
    (e.g. `"football"`), per the docs' own example."""
    url = _events_url(_SPORT_EVENTS_PATH, slug, limit=limit, offset=offset, type_=type_, section=section)
    return _get_events(url)


def _shape_of(result: dict[str, Any], *, sample_limit: int = 1) -> dict[str, Any]:
    """The SHAPE a fetch actually returned -- keys and a small sample, never
    a full dump. Same role every other `probe()` in this lane plays: report
    what came back before anything trusts a field name."""
    if result.get("status") != "ok":
        return result
    payload = result.get("payload")
    events: Any = None
    if isinstance(payload, dict):
        for key in ("events", "data", "results"):
            if isinstance(payload.get(key), list):
                events = payload[key]
                break
    elif isinstance(payload, list):
        events = payload
    return {
        "status": "ok",
        "url": result.get("url"),
        "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else None,
        "event_count": len(events) if isinstance(events, list) else None,
        "event_keys": sorted(events[0].keys()) if isinstance(events, list) and events and isinstance(events[0], dict) else None,
        "sample": events[:sample_limit] if isinstance(events, list) else None,
    }


def probe_league(slug: str, *, limit: int = 3) -> dict[str, Any]:
    """Report the SHAPE `/v2/leagues/{slug}/events` returns for one league,
    unparsed. Run this against every candidate slug (documented and guessed
    alike) before any join code trusts a field name off it."""
    return _shape_of(fetch_league_events(slug, limit=limit))


def probe_all_leagues(*, limit: int = 3) -> dict[str, Any]:
    """`probe_league` for every Syndicate-mapped slug, documented and guessed
    alike -- the one call that turns the whole mapping's guesses into either
    confirmed facts or named failures, in one pass."""
    results: dict[str, Any] = {}
    for sport, slug in _SYNDICATE_TO_POLYMARKET_LEAGUE.items():
        results[sport] = probe_league(slug)
    return results
