"""The US catalogue, and the wrong-exchange error it exists to correct.

Nothing here has run against the venue -- the sandbox proxy denies CONNECT to
every venue host. So the fetch is tested through a stubbed `signed_request`,
which is what let `kalshi_orders` survive its contract changing underneath it.
"""

from __future__ import annotations

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


def test_a_sporting_row_is_recognised_by_STRUCTURE_not_by_a_guessed_constant():
    """No value of `sportsMarketTypeV2` has ever come back from the venue --
    the probe returned one row and it was politics. Matching a guessed constant
    would return zero rows indistinguishably from a venue that lists no sport,
    which is exactly the failure this module corrects, one layer down."""
    assert mod.is_sporting_row(_row(sportsMarketTypeV2="ANYTHING_AT_ALL"))
    assert mod.is_sporting_row(_row(sportsMarketTypeV2="A_VALUE_NOBODY_PREDICTED"))
    # `gameStartTime` alone is enough: a market tied to a specific game start
    # is a game market whatever the venue calls its type.
    row = _row(sportsMarketTypeV2=None, sportsMarketType=None)
    assert mod.is_sporting_row(row)


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
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)
    monkeypatch.setattr(auth, "signed_request", responder)


def test_the_slate_is_requested_per_league_rather_than_filtered_from_everything(monkeypatch):
    """The global pull returned `count=100 sporting=0` on every cycle because it
    took the default ordering, which is high-liquidity politics. A league-scoped
    route cannot be swamped that way."""
    seen: list[str] = []

    def responder(_m, url, **_k):
        seen.append(url)
        return {"events": []}

    _arm(monkeypatch, responder)
    mod.fetch_league_events("mlb")
    assert "/v2/leagues/mlb/events" in seen[0]
    assert seen[0].startswith("https://api.polymarket.us/")


def test_the_default_event_type_is_sport_not_futures(monkeypatch):
    seen: list[str] = []

    def responder(_m, url, **_k):
        seen.append(url)
        return {"events": []}

    _arm(monkeypatch, responder)
    mod.fetch_league_events("mlb")
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
    result = mod.fetch_league_events("mlb", limit=2)
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
    result = mod.fetch_league_events("mlb", limit=2, max_pages=3)
    assert result["pages"] == 3
    assert result["truncated"] is True


def test_a_failure_partway_through_keeps_the_pages_already_fetched(monkeypatch):
    """Three real pages in hand is not the same as a failed fetch, and throwing
    them away to report a clean error loses real data."""
    calls = {"n": 0}

    def responder(_m, _url, **_k):
        calls["n"] += 1
        if calls["n"] > 2:
            raise RuntimeError("connection reset")
        return {"events": [{"id": f"e{calls['n']}"}, {"id": f"f{calls['n']}"}]}

    _arm(monkeypatch, responder)
    result = mod.fetch_league_events("mlb", limit=2)
    assert result["status"] == "ok"
    assert result["event_count"] == 4
    assert result["truncated"] is True


def test_a_failure_on_the_first_page_is_an_error(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("connection reset")

    _arm(monkeypatch, boom)
    result = mod.fetch_league_events("mlb")
    assert result["status"] == "error"
    assert "connection reset" in result["reason"]


def test_an_assumed_league_slug_is_flagged_as_assumed(monkeypatch):
    """An empty slate means opposite things for a documented slug and a guessed
    one: "no games today" versus "the slug is wrong". Collapsing them makes a
    typo look like an off day."""
    _arm(monkeypatch, lambda *_a, **_k: {"events": []})
    assert mod.fetch_league_events("mlb")["slug_documented"] is True
    assert mod.fetch_league_events("nba")["slug_documented"] is True
    assert mod.fetch_league_events("nhl")["slug_documented"] is False
    assert mod.fetch_league_events("wnba")["slug_documented"] is False


def test_an_unknown_sport_is_a_named_refusal_not_a_guessed_slug(monkeypatch):
    _arm(monkeypatch, lambda *_a, **_k: {"events": []})
    result = mod.fetch_league_events("kabaddi")
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
    result = mod.fetch_league_events("mlb")
    assert result["market_count"] == 1
    assert result["events_without_markets"] == 1


def test_a_missing_events_key_is_named(monkeypatch):
    _arm(monkeypatch, lambda *_a, **_k: {"unexpected": []})
    result = mod.fetch_league_events("mlb")
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

    _arm(monkeypatch, responder)
    mod.fetch_teams("mlb")
    assert "provider=PROVIDER_SPORTRADAR" in seen[0]
    assert "league=MLB" in seen[0]

    monkeypatch.setenv("POLYMARKET_US_TEAM_PROVIDER", "PROVIDER_SPORTSDATAIO")
    mod.fetch_teams("mlb")
    assert "provider=PROVIDER_SPORTSDATAIO" in seen[1]


def test_absent_credentials_skip_both_sports_routes(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: False)
    assert mod.fetch_league_events("mlb")["reason"] == "credentials_absent"
    assert mod.fetch_teams("mlb")["reason"] == "credentials_absent"
