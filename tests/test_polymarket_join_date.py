"""The join's date comes from the caller when the board row has none.

MEASURED 2026-08-25T01:23:04Z, the first production build in which game-line
rows reached the pairing loop at all:

  POLYMARKET_BOARD_JOIN board_rows=10 matched=0
    refusals={'board_market_not_a_game_line': 6,
              'no_polymarket_market_for_league_date_market': 4, ...}

All four game-line rows refused for want of a candidate at
`(league, date, market)`. Shortlist rows carry neither `selected_date` nor
`date` -- `_board_rows_for_join` returns them verbatim from
`read_layer2_shortlist` and nothing stamps one on -- so the board side of the
key was always "" and could never equal a slug's real date.

Same shape as `apply_venue_quotes` reading a key board rows do not carry and
reporting a confident `stamped=0` earlier the same evening. A join keyed on a
field one side never populates fails silently and looks like absent inventory.
"""

from __future__ import annotations

from syndicate.features.shared.polymarket_board_join import join_polymarket_to_board


def _market(slug, market_type="SPORTS_MARKET_TYPE_MONEYLINE"):
    return {
        "slug": slug,
        "sportsMarketTypeV2": market_type,
        "outcomes": '["Chicago Cubs","Arizona Diamondbacks"]',
        "outcomePrices": '["0.55","0.45"]',
        "orderPriceMinTickSize": "0.001",
        "minimumTradeQty": "1",
        "orderable": True,
    }


def _row(**over):
    row = {
        "sport": "mlb",
        "market": "h2h",
        "side": "home",
        "home_team": "Arizona Diamondbacks",
        "away_team": "Chicago Cubs",
    }
    row.update(over)
    return row


def test_a_row_with_NO_date_uses_the_callers_date():
    """The regression, stated directly: this is the production shape."""
    markets = [_market("aec-mlb-chc-ari-2026-08-24")]

    joined = join_polymarket_to_board(markets, [_row()], selected_date="2026-08-24")

    assert joined["matched"] == 1, joined["refusals"]


def test_without_a_callers_date_the_same_row_REFUSES_by_name():
    """Proves the fix is what changed the outcome, not the fixture."""
    markets = [_market("aec-mlb-chc-ari-2026-08-24")]

    joined = join_polymarket_to_board(markets, [_row()])

    assert joined["matched"] == 0
    assert joined["refusals"].get("no_polymarket_market_for_league_date_market") == 1


def test_the_ROWS_own_date_wins_over_the_callers():
    """A multi-date board must not be collapsed onto one caller's date."""
    markets = [
        _market("aec-mlb-chc-ari-2026-08-24"),
        _market("aec-mlb-chc-ari-2026-08-25"),
    ]

    joined = join_polymarket_to_board(
        markets, [_row(selected_date="2026-08-25")], selected_date="2026-08-24"
    )

    assert joined["matched"] == 1, joined["refusals"]
    assert joined["matches"][0]["polymarket_slug"].endswith("2026-08-25")
    # And the SIDE resolved to the row's own home club, not positionally:
    # outcomes are [Cubs 0.55, Diamondbacks 0.45] and home_team is the latter.
    assert joined["matches"][0]["polymarket_probability"] == 0.45


def test_a_row_on_a_date_the_venue_does_not_quote_still_refuses():
    """The fallback must not paper over a genuinely absent market."""
    markets = [_market("aec-mlb-chc-ari-2026-08-24")]

    joined = join_polymarket_to_board(markets, [_row()], selected_date="2026-08-26")

    assert joined["matched"] == 0
    assert joined["refusals"].get("no_polymarket_market_for_league_date_market") == 1


# ---------------------------------------------------------------------------
# The side, once the date fix let rows reach it at all.
# ---------------------------------------------------------------------------


def test_the_board_ROLE_resolves_to_the_rows_own_club():
    """`home`/`away` is a ROLE; this venue names the CLUB.

    Once the date fix let game-line rows reach `_probability_for_side`, every
    one of them refused `side_not_an_outcome_of_this_market` -- "home" is not a
    club, so neither the literal compare nor `teams_match` could bridge it.
    """
    markets = [_market("aec-mlb-chc-ari-2026-08-24")]

    home = join_polymarket_to_board(markets, [_row(side="home")], selected_date="2026-08-24")
    away = join_polymarket_to_board(markets, [_row(side="away")], selected_date="2026-08-24")

    # outcomes are [Chicago Cubs 0.55, Arizona Diamondbacks 0.45];
    # home_team is Arizona, away_team is Chicago.
    assert home["matches"][0]["polymarket_probability"] == 0.45
    assert away["matches"][0]["polymarket_probability"] == 0.55


def test_the_two_sides_get_DIFFERENT_prices():
    """The cheapest possible guard against a resolver that returns one price
    for both sides -- which would look entirely reasonable in a log."""
    markets = [_market("aec-mlb-chc-ari-2026-08-24")]

    home = join_polymarket_to_board(markets, [_row(side="home")], selected_date="2026-08-24")
    away = join_polymarket_to_board(markets, [_row(side="away")], selected_date="2026-08-24")

    assert home["matches"][0]["polymarket_probability"] != away["matches"][0]["polymarket_probability"]


def test_a_role_the_row_cannot_name_REFUSES_rather_than_picking_positionally():
    """An unresolvable role must not fall through to array order.

    The refusal lands as `no_matching_polymarket_market`, not
    `side_not_an_outcome_of_this_market`: a row with no `home_team` also fails
    the earlier `_teams_match` gate, so it never reaches the side resolver.
    Asserted as measured rather than as first guessed -- the property under
    test is that it REFUSES and does not pick positionally, and which gate
    catches it first is a detail this pins rather than dictates.
    """
    markets = [_market("aec-mlb-chc-ari-2026-08-24")]
    row = _row(side="home")
    row.pop("home_team")

    joined = join_polymarket_to_board(markets, [row], selected_date="2026-08-24")

    assert joined["matched"] == 0
    assert joined["refusals"] == {"no_matching_polymarket_market": 1}


def test_the_side_resolver_itself_refuses_an_unnameable_role():
    """The side gate in isolation, since the join's earlier gate masks it."""
    from syndicate.features.shared.polymarket_board_join import _probability_for_side

    candidate = {"outcomes": [("Chicago Cubs", 0.55), ("Arizona Diamondbacks", 0.45)]}

    assert _probability_for_side("home", candidate, "mlb", {}) is None
    assert _probability_for_side("home", candidate, "mlb", {"home_team": ""}) is None
    assert _probability_for_side(
        "home", candidate, "mlb", {"home_team": "Arizona Diamondbacks"}
    ) == 0.45
