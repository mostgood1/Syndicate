"""The US catalogue, and the wrong-exchange error it exists to correct.

Nothing here has run against the venue -- the sandbox proxy denies CONNECT to
every venue host. So the fetch is tested through a stubbed `signed_request`,
which is what let `kalshi_orders` survive its contract changing underneath it.
"""

from __future__ import annotations

from typing import Any

import pytest

from syndicate.features.shared import polymarket_us_markets as mod


def _row(**kw):
    row = {
        "id": "m-1",
        "slug": "yankees-vs-red-sox-yankees-win",
        "question": "Will the Yankees beat the Red Sox?",
        "sportsMarketTypeV2": "MONEYLINE",
        "gameStartTime": "2026-08-24T23:05:00Z",
        "orderPriceMinTickSize": "0.01",
        "minimumTradeQty": "1",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.55", "0.45"],
        "marketType": "BINARY",
        "category": "sports",
        "createdAt": "2026-08-01T00:00:00Z",
        "ep3SyncedAt": "2026-08-24T19:00:00Z",
    }
    row.update(kw)
    return row


def _stub(monkeypatch, payload, *, present=True):
    monkeypatch.setattr(mod, "polymarket_us_markets", mod, raising=False)
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: present)
    monkeypatch.setattr(auth, "signed_request", lambda *a, **k: payload)


# --------------------------------------------------------------------------
# THE WRONG-EXCHANGE ERROR. This is why the module exists.
# --------------------------------------------------------------------------


def test_the_catalogue_is_read_from_the_US_venue_and_not_the_global_one(monkeypatch):
    """MEASURED 2026-08-24: the odds pipeline priced Polymarket off
    `gamma-api.polymarket.com` -- the global, on-chain exchange -- while the
    funded account and the working credential are on `api.polymarket.us`.
    Different books, different money. Pricing an edge on one and filling it on
    the other does not fail; it produces plausible edges against prices that do
    not exist where the order lands."""
    seen: list[str] = []

    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def capture(_method, url, **_kw):
        seen.append(url)
        return {"markets": []}

    monkeypatch.setattr(auth, "signed_request", capture)
    mod.fetch_markets()
    assert seen and seen[0].startswith("https://api.polymarket.us/")
    assert "gamma-api" not in seen[0] and "clob.polymarket" not in seen[0]


def test_this_module_never_imports_the_global_client():
    """Behaviour, not prose -- the docstring necessarily NAMES the global hosts
    to explain the distinction, so a source grep would fail on itself."""
    import ast
    import inspect

    imported: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(mod))):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("polymarket_client" in name for name in imported), imported


# --------------------------------------------------------------------------
# The sporting test is STRUCTURAL, because no value has ever been observed
# --------------------------------------------------------------------------


def test_a_sporting_row_is_recognised_by_the_OBSERVED_vocabulary():
    """This was a PRESENCE test while no value of `sportsMarketTypeV2` had ever
    been observed -- a guessed constant would have returned zero rows
    indistinguishably from a venue with no sport. Both facts are measured now,
    so the test uses them."""
    row = _row(category=None, sportsMarketTypeV2="SPORTS_MARKET_TYPE_MONEYLINE")
    assert mod.is_sporting_row(row)
    # `gameStartTime` alone still carries it when nothing else is present.
    bare = _row(category=None, sportsMarketTypeV2=None, sportsMarketType=None)
    assert mod.is_sporting_row(bare)


def test_a_non_sporting_row_is_excluded():
    politics = {"id": "p-1", "question": "Xi Jinping out before 2027?", "category": "politics"}
    assert mod.is_sporting_row(politics) is False


def test_empty_sports_fields_do_not_count_as_present():
    """`""` and `[]` are absence wearing a value's clothes."""
    assert mod.is_sporting_row(
        {"sportsMarketTypeV2": "", "sportsMarketType": None, "gameStartTime": ""}
    ) is False


def test_the_observed_type_values_are_REPORTED_so_the_mapping_comes_from_data(monkeypatch):
    """The whole point of the first live run: design the sport/market mapping
    from what is really there rather than from a guess."""
    _stub(monkeypatch, {"markets": [
        _row(sportsMarketTypeV2="MONEYLINE"),
        _row(id="m-2", sportsMarketTypeV2="SPREAD"),
        _row(id="m-3", sportsMarketTypeV2="MONEYLINE"),
    ]})
    result = mod.fetch_markets()
    assert result["sports_market_types"] == ["MONEYLINE", "SPREAD"]


# --------------------------------------------------------------------------
# Tick size and minimum quantity: the two the order REFUSES to infer
# --------------------------------------------------------------------------


def test_a_row_missing_tick_size_is_marked_unorderable(monkeypatch):
    """`order_body` takes these as REQUIRED arguments -- deliberately, because
    the docs say not to infer them. A row that cannot supply them cannot be
    ordered against, and the catalogue is a much cheaper place to find that out
    than a submit."""
    _stub(monkeypatch, {"markets": [
        _row(),
        _row(id="m-2", orderPriceMinTickSize=None),
        _row(id="m-3", minimumTradeQty=""),
    ]})
    result = mod.fetch_markets()
    assert result["count"] == 3
    assert result["orderable"] == 1
    by_id = {r["id"]: r for r in result["markets"]}
    assert by_id["m-1"]["orderable"] is True
    assert by_id["m-2"]["orderable"] is False
    assert by_id["m-3"]["orderable"] is False


def test_the_trim_keeps_every_field_an_order_or_a_join_reads():
    kept = mod.trimmed_row(_row())
    for field in ("slug", "question", "outcomes", "outcomePrices", "gameStartTime",
                  "orderPriceMinTickSize", "minimumTradeQty", "feeCoefficient",
                  "sportsMarketTypeV2"):
        assert field in kept or field == "feeCoefficient", field
    # And drops the bookkeeping nobody downstream reads. The Novig lane hit the
    # ~8MB keyvalue ceiling on a full catalogue the same day (#60), so the trim
    # is here from the start rather than after an outage.
    assert "ep3SyncedAt" not in kept
    assert "createdAt" not in kept


# --------------------------------------------------------------------------
# Absence, failure, and truncation must never share a rendering
# --------------------------------------------------------------------------


def test_absent_credentials_are_named_rather_than_returning_an_empty_catalogue(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: False)
    result = mod.fetch_markets()
    assert result["status"] == "skipped"
    assert result["reason"] == "credentials_absent"


def test_a_failed_call_is_an_error_not_an_empty_catalogue(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def boom(*_a, **_k):
        raise auth.PolymarketUSAuthError("http_401: ... clock skew ...")

    monkeypatch.setattr(auth, "signed_request", boom)
    result = mod.fetch_markets()
    assert result["status"] == "error"
    assert "http_401" in result["reason"]
    assert result["markets"] == []


def test_a_missing_markets_key_is_named_rather_than_read_as_no_markets(monkeypatch):
    """The one key the probe confirmed. If the contract moves, that must be
    loud -- an empty list would read as "the venue lists nothing"."""
    _stub(monkeypatch, {"data": []})
    result = mod.fetch_markets()
    assert result["status"] == "error"
    assert "markets_key_absent" in result["reason"]


def test_a_full_page_reports_truncated_because_pagination_is_UNKNOWN(monkeypatch):
    """The `limit=1` probe returned `['markets']` and nothing else -- no
    cursor, no total. Rather than invent a pagination scheme, a page that comes
    back exactly full says so, which is the honest reading of "there may be
    more and we cannot tell"."""
    _stub(monkeypatch, {"markets": [_row(id=f"m-{i}") for i in range(5)]})
    assert mod.fetch_markets(limit=5)["truncated"] is True
    assert mod.fetch_markets(limit=50)["truncated"] is False


def test_the_politics_only_catalogue_is_visible_as_zero_sporting_of_many(monkeypatch):
    """MEASURED 2026-08-24: the global pull returned `count=100 sporting=0` on
    every cycle and nobody could tell whether that was a filter problem or a
    venue with no sport. `total_rows` alongside `count` makes the difference
    readable at a glance."""
    _stub(monkeypatch, {"markets": [
        {"id": f"p-{i}", "question": "politics", "category": "politics"} for i in range(30)
    ]})
    result = mod.fetch_markets()
    assert result["count"] == 0
    assert result["total_rows"] == 30


# ==========================================================================
# THE SPORTS API -- a league slate instead of a filtered catalogue
# ==========================================================================


def _arm(monkeypatch, responder):
    """Stub the SIBLING module's single-page fetch.

    `fetch_league_slate` is a pager over `polymarket_us_sports_client`, which
    owns URL construction and the slug mapping. Stubbing there rather than at
    `signed_request` keeps this file testing the paging and extraction it
    actually adds, instead of re-testing their URL builder.
    """
    from syndicate.features.shared import polymarket_us_auth as auth
    from syndicate.features.shared import polymarket_us_sports_client as sports

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def one_page(slug, *, limit=None, offset=None, type_=None, section=None):
        url = f"https://api.polymarket.us/v2/leagues/{slug}/events?limit={limit}&offset={offset}&type={type_}"
        payload = responder("GET", url)
        return {"status": "ok", "payload": payload, "url": url}

    monkeypatch.setattr(sports, "fetch_league_events", one_page)


def test_the_slate_is_requested_per_league_rather_than_filtered_from_everything(monkeypatch):
    """The global pull returned `count=100 sporting=0` on every cycle because it
    took the default ordering, which is high-liquidity politics. A league-scoped
    route cannot be swamped that way."""
    seen: list[str] = []

    def responder(_m, url, **_k):
        seen.append(url)
        return {"events": []}

    _arm(monkeypatch, responder)
    mod.fetch_league_slate("mlb")
    assert "/v2/leagues/mlb/events" in seen[0]
    assert seen[0].startswith("https://api.polymarket.us/")


def test_the_route_is_NOT_reimplemented_here(monkeypatch):
    """A parallel session already owns `/v2/leagues/{slug}/events`, its URL
    builder, and the sport -> slug mapping. Two `fetch_league_events` with
    different argument meanings -- theirs a Polymarket slug, a pager a
    Syndicate sport key -- is a footgun for the same reason the two Polymarket
    AUTH modules are kept apart. So this module pages over theirs and is named
    differently."""
    from syndicate.features.shared import polymarket_us_sports_client as sports

    assert not hasattr(mod, "fetch_league_events")
    calls: list[Any] = []

    def one_page(slug, **kw):
        calls.append((slug, kw))
        return {"status": "ok", "payload": {"events": []}, "url": "u"}

    monkeypatch.setattr(sports, "fetch_league_events", one_page)
    mod.fetch_league_slate("mlb", limit=7)
    assert calls and calls[0][0] == "mlb"
    assert calls[0][1]["limit"] == 7


def test_the_slug_mapping_has_one_source_of_truth():
    """The mapping lives in the sibling module. This only adds whether the slug
    is documented or guessed, which that module records as a comment rather
    than a value."""
    assert mod.league_slug_for_sport("mlb") == ("mlb", True)
    assert mod.league_slug_for_sport("nhl") == ("nhl", False)
    assert mod.league_slug_for_sport("kabaddi") == (None, False)


def test_the_default_event_type_is_sport_not_futures(monkeypatch):
    seen: list[str] = []

    def responder(_m, url, **_k):
        seen.append(url)
        return {"events": []}

    _arm(monkeypatch, responder)
    mod.fetch_league_slate("mlb")
    assert "type=sport" in seen[0]


def test_pagination_uses_the_documented_limit_and_offset(monkeypatch):
    """Documented on this route, unlike `/v1/markets` -- so it is a mechanism
    here rather than the guess that route still requires."""
    seen: list[str] = []

    def responder(_m, url, **_k):
        seen.append(url)
        offset = int(url.split("offset=")[1].split("&")[0])
        # Two full pages then a short one.
        if offset >= 4:
            return {"events": [{"id": "e-short"}]}
        return {"events": [{"id": f"e-{offset}-{i}"} for i in range(2)]}

    _arm(monkeypatch, responder)
    result = mod.fetch_league_slate("mlb", limit=2)
    assert [u.split("?")[1] for u in seen] == [
        "limit=2&offset=0&type=sport",
        "limit=2&offset=2&type=sport",
        "limit=2&offset=4&type=sport",
    ]
    assert result["event_count"] == 5
    assert result["pages"] == 3
    # A short page means the end was reached, so nothing is being hidden.
    assert result["truncated"] is False


def test_exhausting_the_page_budget_reports_truncated_rather_than_looking_complete(monkeypatch):
    _arm(monkeypatch, lambda _m, _u, **_k: {"events": [{"id": "e"}, {"id": "e2"}]})
    result = mod.fetch_league_slate("mlb", limit=2, max_pages=3)
    assert result["pages"] == 3
    assert result["truncated"] is True


def _arm_pages(monkeypatch, pages):
    """`pages` is a list of sibling-module results, one per requested page."""
    from syndicate.features.shared import polymarket_us_sports_client as sports

    calls = {"n": 0}

    def one_page(_slug, **_kw):
        index = calls["n"]
        calls["n"] += 1
        return pages[index] if index < len(pages) else pages[-1]

    monkeypatch.setattr(sports, "fetch_league_events", one_page)


def _ok(*ids):
    return {"status": "ok", "payload": {"events": [{"id": i} for i in ids]}, "url": "u"}


def test_a_failure_partway_through_keeps_the_pages_already_fetched(monkeypatch):
    """Two real pages in hand is not the same as a failed fetch, and throwing
    them away to report a clean error loses real data."""
    _arm_pages(monkeypatch, [
        _ok("e1", "f1"),
        _ok("e2", "f2"),
        {"status": "error", "reason": "connection reset", "url": "u"},
    ])
    result = mod.fetch_league_slate("mlb", limit=2)
    assert result["status"] == "ok"
    assert result["event_count"] == 4
    assert result["truncated"] is True


def test_a_failure_on_the_first_page_is_an_error(monkeypatch):
    _arm_pages(monkeypatch, [{"status": "error", "reason": "connection reset", "url": "u"}])
    result = mod.fetch_league_slate("mlb")
    assert result["status"] == "error"
    assert "connection reset" in result["reason"]


def test_credentials_absent_arrives_through_the_sibling_module(monkeypatch):
    """That module returns `credentials_absent` as a named error rather than
    raising -- measured on refresh-worker, where the credential is not set and
    all seven leagues reported exactly that."""
    _arm_pages(monkeypatch, [{"status": "error", "reason": "credentials_absent", "url": "u"}])
    result = mod.fetch_league_slate("mlb")
    assert result["status"] == "error"
    assert result["reason"] == "credentials_absent"


def test_an_assumed_league_slug_is_flagged_as_assumed(monkeypatch):
    """An empty slate means opposite things for a documented slug and a guessed
    one: "no games today" versus "the slug is wrong". Collapsing them makes a
    typo look like an off day."""
    _arm(monkeypatch, lambda *_a, **_k: {"events": []})
    assert mod.fetch_league_slate("mlb")["slug_documented"] is True
    assert mod.fetch_league_slate("nba")["slug_documented"] is True
    assert mod.fetch_league_slate("nhl")["slug_documented"] is False
    assert mod.fetch_league_slate("wnba")["slug_documented"] is False


def test_an_unknown_sport_is_a_named_refusal_not_a_guessed_slug(monkeypatch):
    _arm(monkeypatch, lambda *_a, **_k: {"events": []})
    result = mod.fetch_league_slate("kabaddi")
    assert result["status"] == "skipped"
    assert "no_league_slug_for_sport" in result["reason"]


def test_events_whose_markets_are_nested_elsewhere_are_COUNTED_not_silently_priceless(monkeypatch):
    """The events route's response body is not documented -- only its
    parameters. If the markets are somewhere this does not look, that must be a
    visible number rather than a slate with no prices and no explanation."""
    _arm(monkeypatch, lambda *_a, **_k: {"events": [
        {"id": "e-1", "markets": [_row()]},
        {"id": "e-2", "somethingElse": [_row(id="m-9")]},
    ]})
    result = mod.fetch_league_slate("mlb")
    assert result["market_count"] == 1
    assert result["events_without_markets"] == 1


def test_a_missing_events_key_is_named(monkeypatch):
    _arm(monkeypatch, lambda *_a, **_k: {"unexpected": []})
    result = mod.fetch_league_slate("mlb")
    assert result["status"] == "error"
    assert "events_key_absent" in result["reason"]


# --------------------------------------------------------------------------
# Teams: an alias table from the venue beats a similarity threshold
# --------------------------------------------------------------------------


def _team(**kw):
    team = {"id": 1, "name": "New York Yankees", "abbreviation": "NYY",
            "displayAbbreviation": "NYY", "alias": "Yankees", "safeName": "new-york-yankees",
            "league": "MLB"}
    team.update(kw)
    return team


def test_every_name_the_venue_publishes_points_at_the_team():
    """The game-line join's measured failure was `side_not_a_team_in_this_game:
    77` -- our board's naming against a venue's. An alias table from the venue
    makes the lookup exact, so an unmatched name becomes a real fact rather
    than a threshold."""
    index = mod.team_alias_index([_team()])
    for alias in ("New York Yankees", "NYY", "Yankees", "new-york-yankees", "  yankees  "):
        assert mod.team_alias_index([_team()])[
            "".join(c for c in alias.strip().lower() if c.isalnum())
        ]["id"] == 1
    assert "newyorkyankees" in index


def test_an_ambiguous_alias_is_DROPPED_rather_than_resolved_by_insertion_order():
    """Two teams claiming one alias, picked by whichever was inserted last, is a
    bet on the wrong side of a game. There is no cheaper place to catch it."""
    index = mod.team_alias_index([
        _team(id=1, name="New York Yankees", alias="NY", abbreviation="NYY",
              displayAbbreviation="NYY", safeName="ny-yankees"),
        _team(id=2, name="New York Mets", alias="NY", abbreviation="NYM",
              displayAbbreviation="NYM", safeName="ny-mets"),
    ])
    assert "ny" not in index
    # The unambiguous names still resolve.
    assert index["nyy"]["id"] == 1
    assert index["nym"]["id"] == 2


def test_the_same_team_listed_twice_is_not_a_collision():
    index = mod.team_alias_index([_team(), _team()])
    assert index["nyy"]["id"] == 1


def test_the_team_provider_is_overridable_without_a_deploy(monkeypatch):
    """Two providers are documented and which one is populated per league has
    not been observed."""
    seen: list[str] = []

    def responder(_m, url, **_k):
        seen.append(url)
        return {"teams": []}

    # The teams route calls `signed_request` directly -- it is not a paged
    # events route, so it does not go through the sibling module.
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(auth, "signed_request", responder)
    mod.fetch_teams("mlb")
    assert "provider=PROVIDER_SPORTRADAR" in seen[0]
    assert "league=MLB" in seen[0]

    monkeypatch.setenv("POLYMARKET_US_TEAM_PROVIDER", "PROVIDER_SPORTSDATAIO")
    mod.fetch_teams("mlb")
    assert "provider=PROVIDER_SPORTSDATAIO" in seen[1]


def test_absent_credentials_skip_the_teams_route(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: False)
    assert mod.fetch_teams("mlb")["reason"] == "credentials_absent"


# --------------------------------------------------------------------------
# The legacy /v1 sports routes -- NOT covered by the measured 404
# --------------------------------------------------------------------------


def test_the_v1_probe_asks_the_routes_the_404_did_not_cover(monkeypatch):
    """Concluding "the Sports API is not on this host" from four tested routes
    was an overreach. `/v1/sports/teams/provider` is the PROVIDER VARIANT;
    `/v1/sports` and `/v1/sports/teams` were never tried and share the prefix
    that demonstrably works for `/v1/markets`."""
    seen: list[str] = []

    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        seen.append(url)
        return {"sports": [{"sport": "baseball", "series": "12"}]}

    monkeypatch.setattr(auth, "signed_request", responder)
    result = mod.probe_v1_sports_routes()
    assert any(u.endswith("/v1/sports") for u in seen)
    assert any(u.endswith("/v1/sports/teams") for u in seen)
    assert result["routes"]["sports"]["row_keys"] == ["series", "sport"]
    assert result["routes"]["sports"]["count"] == 1


def test_one_route_404ing_does_not_stop_the_others(monkeypatch):
    """The whole point is comparing them. A route that dies must not take the
    comparison with it."""
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        if url.endswith("/v1/sports"):
            raise auth.PolymarketUSAuthError("http_404: not found")
        return {"teams": [{"id": 1, "name": "New York Yankees"}]}

    monkeypatch.setattr(auth, "signed_request", responder)
    routes = mod.probe_v1_sports_routes()["routes"]
    assert routes["sports"]["status"] == "error"
    assert "http_404" in routes["sports"]["reason"]
    assert routes["teams"]["status"] == "ok"
    assert routes["teams"]["count"] == 1


def test_the_v1_probe_names_absent_credentials(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: False)
    assert mod.probe_v1_sports_routes()["reason"] == "credentials_absent"


# ==========================================================================
# SETTLED vs LIVE -- the count that looked right and was not
# ==========================================================================


def _settled_row(**kw):
    row = _row(outcomePrices=["1", "0"], gameStartTime="2025-11-02T18:00:00Z",
               status="MARKET_STATUS_RESOLVED")
    row.update(kw)
    return row


def _no_status(**kw):
    """A row with no `status`, to exercise the PRICE fallback specifically."""
    row = _row(**kw)
    row.pop("status", None)
    return row


def test_a_market_priced_at_certainty_is_settled():
    """MEASURED 2026-08-24: the first 500 rows of
    /v1/markets?active=true&limit=500 were ALL NFL games from 2025-11-02 priced
    ["1","0"] -- settled games from last season, returned under active=true. So
    `active` does not mean unresolved on this venue, and a price at exactly 0
    or 1 is the reliable tell: a live market cannot be certain."""
    assert mod.is_settled_row(_settled_row()) is True
    assert mod.is_settled_row(_no_status(outcomePrices=["0", "1"])) is True
    assert mod.is_settled_row(_no_status(outcomePrices=["0.55", "0.45"])) is False


def test_prices_arrive_as_a_JSON_STRING_not_a_list():
    """The venue sends `outcomePrices` as `'["1","0"]'`. Treating that string as
    a list would make every row unparseable and therefore never settled --
    which fails toward "everything is live", the wrong direction."""
    assert mod.is_settled_row(_no_status(outcomePrices='["1","0"]')) is True
    assert mod.is_settled_row(_no_status(outcomePrices='["0.55","0.45"]')) is False


def test_an_unparseable_price_is_not_claimed_to_be_settled():
    for prices in (None, "", "not-json", [], ["abc"]):
        assert mod.is_settled_row(_no_status(outcomePrices=prices)) is False


def test_settled_and_live_are_reported_SEPARATELY_from_sporting(monkeypatch):
    """`sporting=500 of=500 orderable=500` read as a full healthy slate and was
    500 games that finished nine months earlier. Three different things were
    one number; `live` is the only usable one."""
    _stub(monkeypatch, {"markets": [
        _settled_row(id="s-1"), _settled_row(id="s-2"),
        _no_status(id="l-1", outcomePrices=["0.55", "0.45"],
                   gameStartTime="2026-08-24T23:05:00Z"),
    ]})
    result = mod.fetch_markets()
    assert result["sporting"] == 3
    assert result["settled"] == 2
    assert result["live"] == 1


def test_settled_rows_are_kept_by_default_and_dropped_only_on_request(monkeypatch):
    """Off by default: a caller who has not thought about it should get the
    full picture rather than a silently narrowed one."""
    rows = [_settled_row(id="s-1"),
            _no_status(id="l-1", outcomePrices=["0.55", "0.45"])]
    _stub(monkeypatch, {"markets": rows})
    assert mod.fetch_markets()["count"] == 2
    _stub(monkeypatch, {"markets": rows})
    assert mod.fetch_markets(drop_settled=True)["count"] == 1


def test_the_game_start_window_is_reported_so_stale_data_is_legible(monkeypatch):
    """"These are last season's games" should be readable off the log line
    without needing a sample row."""
    _stub(monkeypatch, {"markets": [
        _settled_row(id="s-1", gameStartTime="2025-11-02T18:00:00Z"),
        _no_status(id="l-1", outcomePrices=["0.5", "0.5"],
                   gameStartTime="2026-08-24T23:05:00Z"),
    ]})
    result = mod.fetch_markets()
    assert result["game_start_min"] == "2025-11-02T18:00:00Z"
    assert result["game_start_max"] == "2026-08-24T23:05:00Z"
    # And the LIVE window separately -- the one that says whether today is there.
    assert result["live_start_min"] == "2026-08-24T23:05:00Z"


# --------------------------------------------------------------------------
# Paging, which is a guess on this route
# --------------------------------------------------------------------------


def test_offset_advances_across_pages(monkeypatch):
    seen: list[str] = []

    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        seen.append(url)
        off = int(url.split("offset=")[1].split("&")[0])
        return {"markets": [_row(id=f"m-{off}-{i}") for i in range(2)]}

    monkeypatch.setattr(auth, "signed_request", responder)
    mod.fetch_markets(limit=2, max_pages=3)
    assert [int(u.split("offset=")[1].split("&")[0]) for u in seen] == [0, 2, 4]


def test_a_venue_that_IGNORES_offset_is_caught_by_duplicate_ids(monkeypatch):
    """`offset` is the house convention from the venue's own Sports API docs,
    but it is UNVERIFIED on this route. If the venue ignores it every page
    returns the same rows, and every page looks full -- invisible without
    this counter."""
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(
        auth, "signed_request",
        lambda *_a, **_k: {"markets": [_row(id="same-1"), _row(id="same-2")]},
    )
    result = mod.fetch_markets(limit=2, max_pages=3)
    assert result["duplicate_ids"] == 4
    assert result["total_rows"] == 2


def test_a_short_page_ends_paging_without_claiming_truncation(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(auth, "signed_request", lambda *_a, **_k: {"markets": [_row()]})
    result = mod.fetch_markets(limit=50, max_pages=5)
    assert result["pages"] == 1
    assert result["truncated"] is False


def test_a_failure_after_real_pages_keeps_them(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    calls = {"n": 0}
    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(*_a, **_k):
        calls["n"] += 1
        if calls["n"] > 1:
            raise auth.PolymarketUSAuthError("http_500")
        return {"markets": [_row(id="a"), _row(id="b")]}

    monkeypatch.setattr(auth, "signed_request", responder)
    result = mod.fetch_markets(limit=2, max_pages=3)
    assert result["status"] == "ok"
    assert result["total_rows"] == 2
    assert result["truncated"] is True


def test_the_status_vocabulary_is_reported_since_it_has_never_been_observed(monkeypatch):
    """Resolution is currently inferred from the PRICE. If `status` turns out to
    say it directly, that is better -- but nothing may depend on a guessed
    value before one is seen."""
    _stub(monkeypatch, {"markets": [_row(status="STATUS_OPEN"), _row(id="m-2", status="STATUS_RESOLVED")]})
    assert mod.fetch_markets()["statuses"] == ["STATUS_OPEN", "STATUS_RESOLVED"]


def test_STATUS_beats_price_because_a_resolved_market_can_sit_at_a_coin_flip():
    """MEASURED 2026-08-24T20:46:21Z: all 2,000 rows carried
    MARKET_STATUS_RESOLVED -- INCLUDING the 2 the price test called live, which
    are priced ["0.5","0.5"]. A resolved market that never traded sits at 0.5
    forever, and no price test can tell that from a genuine coin-flip. Two
    false live rows in 2,000 is a 0.1% error rate that would have put real
    orders on games finished months ago."""
    coin_flip_but_resolved = _row(
        outcomePrices=["0.5", "0.5"], status="MARKET_STATUS_RESOLVED",
        gameStartTime="2025-12-21T23:00:00Z",
    )
    assert mod.is_settled_row(coin_flip_but_resolved) is True


def test_an_UNKNOWN_status_is_not_read_as_settled():
    """Only one status value has ever been seen. An unknown one must fail
    toward tradeable, because the other direction silently discards live
    markets -- and a discarded market is invisible, while a bad order is not."""
    assert mod.is_settled_row(_row(status="MARKET_STATUS_SOMETHING_NEW")) is False
    assert mod.is_settled_row(_row(status="MARKET_STATUS_OPEN")) is False


def test_the_price_fallback_still_applies_when_status_is_absent():
    """Status is authoritative WHERE PRESENT. A row that omits it still gets
    the price test rather than being assumed live."""
    assert mod.is_settled_row(_no_status(outcomePrices=["1", "0"])) is True


@pytest.mark.parametrize("status", [
    "MARKET_STATUS_RESOLVED", "market_status_resolved", "SETTLED", "CLOSED", "CANCELED",
])
def test_the_resolved_markers_are_matched_case_insensitively(status):
    assert mod.is_settled_row(_row(status=status)) is True


# ==========================================================================
# WHICH QUERY PARAMS DOES /v1/markets HONOUR?
# ==========================================================================


def _sig_rows(first_id="m-1", start="2025-10-31T00:15:00Z", n=2):
    return [_row(id=f"{first_id}" if i == 0 else f"other-{i}", gameStartTime=start)
            for i in range(n)]


def test_the_negative_control_decides_whether_IGNORED_means_anything(monkeypatch):
    """If the API silently discards unknown query params -- normal
    grpc-gateway behaviour -- then every "ignored" row is uninformative, and a
    table read without knowing that is worse than no table. The verdict is
    COMPUTED here rather than left to a reader."""
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    # Everything returns the same rows -- including the bogus param.
    monkeypatch.setattr(auth, "signed_request", lambda *_a, **_k: {"markets": _sig_rows()})
    result = mod.probe_market_query_params()
    assert result["control_outcome"] == "ignored"
    assert result["ignored_is_meaningful"] is False


def test_a_rejected_control_makes_ignored_informative(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        if "zzz_not_a_real_param" in url:
            raise auth.PolymarketUSAuthError("http_400: unknown field")
        return {"markets": _sig_rows()}

    monkeypatch.setattr(auth, "signed_request", responder)
    result = mod.probe_market_query_params()
    assert result["control_outcome"] == "rejected"
    assert result["ignored_is_meaningful"] is True


def test_a_param_that_changes_the_response_is_reported_as_honoured(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        if "order=desc" in url:
            # A different first row is the sharpest tell of a real change.
            return {"markets": _sig_rows(first_id="newest", start="2026-08-24T23:05:00Z")}
        return {"markets": _sig_rows()}

    monkeypatch.setattr(auth, "signed_request", responder)
    result = mod.probe_market_query_params()
    assert "order_desc" in result["honoured"]
    assert result["results"]["order_desc"]["signature"]["first_id"] == "newest"
    # And an unchanged one is not claimed as a win.
    assert result["results"]["sort_desc"]["outcome"] == "ignored"


def test_known_valid_values_separate_a_bad_PARAM_from_a_bad_VALUE(monkeypatch):
    """`status=MARKET_STATUS_RESOLVED` uses a value the venue itself returned.
    If that is honoured, status filtering works and only the name of the OPEN
    value is missing -- a far smaller question than guessing both at once."""
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        if "status=MARKET_STATUS_RESOLVED" in url:
            return {"markets": _sig_rows(first_id="resolved-only", n=1)}
        if "status=MARKET_STATUS_OPEN" in url:
            return {"markets": []}
        return {"markets": _sig_rows()}

    monkeypatch.setattr(auth, "signed_request", responder)
    result = mod.probe_market_query_params()
    assert "status_resolved_known" in result["honoured"]
    # An empty result is a CHANGE, not a failure -- it is the answer "that
    # value matches nothing", which is exactly what we want to learn.
    assert result["results"]["status_open"]["outcome"] == "honoured"
    assert result["results"]["status_open"]["signature"]["count"] == 0


def test_a_failed_baseline_refuses_rather_than_comparing_to_nothing(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def boom(*_a, **_k):
        raise auth.PolymarketUSAuthError("http_500")

    monkeypatch.setattr(auth, "signed_request", boom)
    result = mod.probe_market_query_params()
    assert result["status"] == "error"
    assert "baseline_failed" in result["reason"]


def test_absent_credentials_are_named(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: False)
    assert mod.probe_market_query_params()["reason"] == "credentials_absent"


# ==========================================================================
# `closed=false`, NOT `active=true` -- the filter that reaches today
# ==========================================================================


def test_the_live_filter_is_closed_false(monkeypatch):
    """MEASURED 2026-08-24T20:56:41Z: `closed=false` returned row id 7898 with
    gameStartTime 2026-09-07 and status MARKET_STATUS_OPEN in ONE request,
    where the unfiltered query was still in 2025-11 two thousand rows deep."""
    seen: list[str] = []

    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        seen.append(url)
        return {"markets": []}

    monkeypatch.setattr(auth, "signed_request", responder)
    mod.fetch_markets()
    assert "closed=false" in seen[0]
    # And `active` is NOT sent by default: it is the server default anyway and
    # returns RESOLVED rows, which is what made 500 settled games look healthy.
    assert "active=" not in seen[0]


def test_active_is_only_sent_when_explicitly_asked_for(monkeypatch):
    """`active` stays reachable for diagnostics -- it is a real parameter, just
    not the one that means "tradeable" on this venue."""
    seen: list[str] = []

    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(auth, "signed_request",
                        lambda _m, url, **_k: seen.append(url) or {"markets": []})
    mod.fetch_markets(active=False)
    assert "active=false" in seen[0]
    seen.clear()
    mod.fetch_markets(active=True)
    assert "active=true" in seen[0]


def test_the_live_filter_can_be_turned_off_to_see_everything(monkeypatch):
    seen: list[str] = []

    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(auth, "signed_request",
                        lambda _m, url, **_k: seen.append(url) or {"markets": []})
    mod.fetch_markets(open_only=False)
    assert "closed=" not in seen[0]


def test_the_open_status_value_is_recorded():
    """Observed in the same response. Useful for READING rows -- `status=` as a
    query param is not honoured, so it cannot filter."""
    assert mod.MARKET_STATUS_OPEN == "MARKET_STATUS_OPEN"
    assert mod.is_settled_row(_row(status=mod.MARKET_STATUS_OPEN)) is False


# ==========================================================================
# UNSPECIFIED is present and means NOT SPORT; futures are not joinable
# ==========================================================================


def test_an_UNSPECIFIED_type_is_not_a_sports_market(monkeypatch):
    """MEASURED 2026-08-24T21:07:04Z: `sporting=2000` with
    categories=['crypto','culture','finance','geopolitics','macro','politics',
    'sports','technology']. The presence test counted crypto and politics as
    sporting because they carry `sportsMarketTypeV2` with the value
    SPORTS_MARKET_TYPE_UNSPECIFIED -- a field that is PRESENT and means "not a
    sports market". Same failure as `sporting=500`, one layer along."""
    crypto = _row(category="crypto", sportsMarketTypeV2="SPORTS_MARKET_TYPE_UNSPECIFIED")
    assert mod.is_sporting_row(crypto) is False
    no_category = _row(category=None, sportsMarketTypeV2="SPORTS_MARKET_TYPE_UNSPECIFIED")
    assert mod.is_sporting_row(no_category) is False


def test_the_category_decides_when_it_is_present():
    """`category` carries a real `sports` value, observed alongside seven
    non-sport categories."""
    assert mod.is_sporting_row(_row(category="sports")) is True
    for other in ("politics", "crypto", "macro", "geopolitics", "finance"):
        assert mod.is_sporting_row(_row(category=other)) is False, other


def test_a_FUTURE_is_a_sports_market_but_NOT_a_joinable_game():
    """"World Series Champion" with outcomes ["Yes","No"] has no game to join a
    board row to. A moneyline carries the two teams and a gameStartTime that
    identifies one. Counting them together is how sporting=2000 looked like a
    usable slate while containing no joinable row."""
    future = _row(category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_FUTURE",
                  outcomes=["Yes", "No"], question="World Series Champion")
    assert mod.is_sporting_row(future) is True
    assert mod.is_game_market_row(future) is False

    game = _row(category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_MONEYLINE",
                outcomes=["Titans", "Chargers"])
    assert mod.is_game_market_row(game) is True


def test_games_and_futures_are_counted_SEPARATELY(monkeypatch):
    _stub(monkeypatch, {"markets": [
        _row(id="f-1", category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_FUTURE"),
        _row(id="f-2", category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_FUTURE"),
        _row(id="g-1", category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_MONEYLINE"),
        _row(id="x-1", category="politics", sportsMarketTypeV2="SPORTS_MARKET_TYPE_UNSPECIFIED"),
    ]})
    result = mod.fetch_markets()
    assert result["sporting"] == 3
    assert result["futures"] == 2
    # The only number that means "a board row could be priced against this".
    assert result["games"] == 1


# ==========================================================================
# WHERE do game markets live in the closed=false ordering?
# ==========================================================================


def test_the_offset_landscape_locates_the_first_game_market(monkeypatch):
    """MEASURED 2026-08-24T21:18:53Z: games=0 futures=1644 across the first
    2,000 rows, while moneylines are known to exist here. Deeper or absent are
    completely different answers, and a linear sweep is the expensive way to
    tell them apart -- this samples ~8 offsets at 5 rows each."""
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        offset = int(url.split("offset=")[1].split("&")[0])
        kind = ("SPORTS_MARKET_TYPE_MONEYLINE" if offset >= 8000
                else "SPORTS_MARKET_TYPE_FUTURE")
        return {"markets": [_row(id=f"m-{offset}", category="sports",
                                 sportsMarketTypeV2=kind)]}

    monkeypatch.setattr(auth, "signed_request", responder)
    result = mod.probe_offset_landscape()
    assert result["first_game_offset"] == 8000
    assert result["samples"]["0"]["games"] == 0
    assert result["samples"]["8000"]["games"] == 1


def test_no_game_markets_anywhere_reports_None_rather_than_a_number(monkeypatch):
    """`None` is the answer "the open set contains no game markets", which is a
    completely different next step from "they start at offset N"."""
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(auth, "signed_request", lambda *_a, **_k: {"markets": [
        _row(category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_FUTURE")]})
    assert mod.probe_offset_landscape()["first_game_offset"] is None


def test_an_offset_past_the_end_is_reported_as_empty_not_failed(monkeypatch):
    """How big the collection is, which is worth knowing."""
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        offset = int(url.split("offset=")[1].split("&")[0])
        return {"markets": [] if offset >= 4000 else [_row()]}

    monkeypatch.setattr(auth, "signed_request", responder)
    samples = mod.probe_offset_landscape()["samples"]
    assert samples["4000"]["status"] == "empty"
    assert samples["4000"]["note"] == "past_end_of_collection"


def test_one_offset_failing_does_not_stop_the_rest(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        if "offset=2000" in url:
            raise auth.PolymarketUSAuthError("http_500")
        return {"markets": [_row(category="sports",
                                 sportsMarketTypeV2="SPORTS_MARKET_TYPE_MONEYLINE")]}

    monkeypatch.setattr(auth, "signed_request", responder)
    result = mod.probe_offset_landscape()
    assert result["samples"]["2000"]["status"] == "error"
    assert result["first_game_offset"] == 0


def test_a_SPREAD_is_a_game_market_even_though_only_MONEYLINE_was_known():
    """MEASURED 2026-08-24T21:26:36Z at offset 16000:
    types=['SPORTS_MARKET_TYPE_SPREAD'], slug
    'asc-nfl-nyg-nyj-2026-08-28-pos-1pt5' -- Giants at Jets, four days out.

    The allowlist version knew only MONEYLINE and reported games=0 on a page
    full of real NFL spreads. That is the "guessed constant returns zero
    indistinguishably from absence" failure, hit at a third layer."""
    spread = _row(category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_SPREAD",
                  gameStartTime="2026-08-28T23:30:00Z")
    assert mod.is_game_market_row(spread) is True


def test_an_UNSEEN_game_market_type_is_included_not_excluded():
    """Exclusion, not an allowlist. An over-count is visible in the sample rows;
    an under-count reads as "the venue does not offer this"."""
    for unseen in ("SPORTS_MARKET_TYPE_TOTAL", "SPORTS_MARKET_TYPE_PLAYER_PROP",
                   "SPORTS_MARKET_TYPE_SOMETHING_NEW"):
        row = _row(category="sports", sportsMarketTypeV2=unseen,
                   gameStartTime="2026-08-28T23:30:00Z")
        assert mod.is_game_market_row(row) is True, unseen


def test_season_level_types_are_still_excluded():
    for season in ("SPORTS_MARKET_TYPE_FUTURE", "SPORTS_MARKET_TYPE_CHAMPION",
                   "SPORTS_MARKET_TYPE_AWARD", "SPORTS_MARKET_TYPE_SEASON_WINS"):
        row = _row(category="sports", sportsMarketTypeV2=season,
                   gameStartTime="2026-09-07T00:00:00Z")
        assert mod.is_game_market_row(row) is False, season


def test_a_row_with_no_game_start_is_not_a_game_market():
    """A season-level market with no type would otherwise pass on category."""
    row = _row(category="sports", sportsMarketTypeV2=None, gameStartTime=None)
    assert mod.is_game_market_row(row) is False


def test_the_game_type_vocabulary_is_reported(monkeypatch):
    _stub(monkeypatch, {"markets": [
        _row(id="g-1", category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_MONEYLINE",
             gameStartTime="2026-08-28T23:30:00Z"),
        _row(id="g-2", category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_SPREAD",
             gameStartTime="2026-08-28T23:30:00Z"),
        _row(id="f-1", category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_FUTURE",
             gameStartTime="2026-09-07T00:00:00Z"),
    ]})
    result = mod.fetch_markets()
    assert result["games"] == 2
    assert result["futures"] == 1
    assert result["game_types"] == ["SPORTS_MARKET_TYPE_MONEYLINE", "SPORTS_MARKET_TYPE_SPREAD"]


# ==========================================================================
# Locating the game block without hardcoding where it starts
# ==========================================================================


def _partitioned(monkeypatch, boundary):
    """Season-level below `boundary`, game markets from it up to an end."""
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def responder(_m, url, **_k):
        offset = int(url.split("offset=")[1].split("&")[0])
        if offset >= 27000:
            return {"markets": []}
        kind = ("SPORTS_MARKET_TYPE_SPREAD" if offset >= boundary
                else "SPORTS_MARKET_TYPE_FUTURE")
        return {"markets": [_row(id=f"m-{offset}", category="sports",
                                 sportsMarketTypeV2=kind,
                                 gameStartTime="2026-08-28T23:30:00Z")]}

    monkeypatch.setattr(auth, "signed_request", responder)


def test_the_boundary_is_FOUND_rather_than_hardcoded(monkeypatch):
    """MEASURED 2026-08-24T21:36:46Z: games begin at 16000. Ids grow as the
    venue lists markets, so that boundary moves every day -- a stale constant
    starts the scan inside the futures block, or past the first games and
    silently misses part of the slate."""
    _partitioned(monkeypatch, 16000)
    result = mod.find_first_game_offset()
    assert result["first_game_offset"] == 16000
    # And it costs a handful of probes, not a linear sweep.
    assert result["probes"] <= 20


def test_a_moved_boundary_is_found_too(monkeypatch):
    """The point of searching: tomorrow it is somewhere else."""
    _partitioned(monkeypatch, 9000)
    assert mod.find_first_game_offset()["first_game_offset"] == 9000


def test_the_partition_assumption_is_CHECKED_not_trusted(monkeypatch):
    """Binary search is only valid if the collection is partitioned. If games
    appear below the discovered boundary it is not, and the answer cannot be
    trusted -- so that is reported rather than assumed away."""
    _partitioned(monkeypatch, 16000)
    result = mod.find_first_game_offset()
    assert result["monotonic"] is True


def test_a_collection_with_no_games_reports_no_offset(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(auth, "signed_request", lambda *_a, **_k: {"markets": [
        _row(category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_FUTURE")]})
    assert mod.find_first_game_offset()["first_game_offset"] is None


def test_fetch_game_markets_starts_at_the_located_boundary(monkeypatch):
    _partitioned(monkeypatch, 16000)
    result = mod.fetch_game_markets(limit=500, max_pages=2)
    assert result["status"] == "ok"
    assert result["start_offset"] == 16000
    # And it returns only joinable rows -- the function's whole purpose.
    assert result["markets"]
    assert all("FUTURE" not in str(m.get("sportsMarketTypeV2")) for m in result["markets"])


def test_fetch_game_markets_refuses_when_no_boundary_exists(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(auth, "signed_request", lambda *_a, **_k: {"markets": [
        _row(category="sports", sportsMarketTypeV2="SPORTS_MARKET_TYPE_FUTURE")]})
    result = mod.fetch_game_markets()
    assert result["status"] == "error"
    assert "no_game_offset" in result["reason"]


# ==========================================================================
# Persisting the slate so the fan-in can read an artifact, not the API
# ==========================================================================


def test_the_slate_is_written_with_its_own_fetched_at(monkeypatch, tmp_path):
    """An artifact republished unchanged gets a fresh mtime while its contents
    are hours old -- PUBLISH_SKIPPED_UNCHANGED and the artifact-pull sweep both
    touch files that way. Trusting mtime would launder stale odds as fresh."""
    written = {}

    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "reports_root", lambda: tmp_path)
    monkeypatch.setattr(refresh_state_store, "write_json_file",
                        lambda path, payload: written.update({"path": path, "payload": payload}))
    monkeypatch.setattr(mod, "fetch_game_markets",
                        lambda **_k: {"status": "ok", "markets": [_row()], "truncated": False,
                                      "game_types": ["SPORTS_MARKET_TYPE_MONEYLINE"]})
    result = mod.persist_game_slate()
    assert result["status"] == "ok" and result["written"] is True
    assert written["payload"]["fetched_at"] > 0
    assert written["payload"]["count"] == 1
    assert str(written["path"]).endswith("polymarket_us_games.json")


def test_a_failed_fetch_KEEPS_the_previous_slate(monkeypatch):
    """Clearing it would turn "we could not reach Polymarket" into "Polymarket
    lists nothing", and those need opposite responses."""
    monkeypatch.setattr(mod, "fetch_game_markets",
                        lambda **_k: {"status": "error", "reason": "http_500"})
    result = mod.persist_game_slate()
    assert result["status"] == "error"
    assert result["kept_previous"] is True
    assert result["written"] is False


def test_a_failed_WRITE_is_distinct_from_a_failed_fetch(monkeypatch, tmp_path):
    """The fetch succeeded and the caller can still use the result; only the
    cache is missing. Same shape as Novig's 8MB keyvalue ceiling failure."""
    from syndicate.features.shared import refresh_state_store

    def boom(*_a, **_k):
        raise RuntimeError("exceeds 8388608")

    monkeypatch.setattr(refresh_state_store, "reports_root", lambda: tmp_path)
    monkeypatch.setattr(refresh_state_store, "write_json_file", boom)
    monkeypatch.setattr(mod, "fetch_game_markets",
                        lambda **_k: {"status": "ok", "markets": [_row()]})
    result = mod.persist_game_slate()
    assert result["status"] == "fetched_not_written"
    assert result["count"] == 1
    assert "8388608" in result["reason"]
