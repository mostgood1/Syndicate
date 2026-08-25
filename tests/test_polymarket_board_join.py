"""Board row -> Polymarket's own price.

Fixes the gap `portfolio_commit.py:170` left: every venue but Kalshi got
`(None, None)`, so `paper:polymarket` was the aggregator's prices wearing a
venue label.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import polymarket_board_join as mod


def _market(slug="aec-mlb-pit-sd-2026-08-24", kind="SPORTS_MARKET_TYPE_MONEYLINE",
            outcomes=("Pirates", "Padres"), prices=("0.45", "0.55"), **kw):
    row = {
        "slug": slug,
        "sportsMarketTypeV2": kind,
        "outcomes": json.dumps(list(outcomes)),
        "outcomePrices": json.dumps(list(prices)),
        "orderPriceMinTickSize": 0.01,
        "minimumTradeQty": 1,
    }
    row.update(kw)
    return row


def _board(market="h2h", side="Padres", line=None, home="San Diego Padres",
           away="Pittsburgh Pirates", date="2026-08-24", sport="mlb", **kw):
    row = {"market": market, "side": side, "line": line, "home": home,
           "away": away, "selected_date": date, "sport": sport}
    row.update(kw)
    return row


# ==========================================================================
# THE SLUG IS A STRUCTURED KEY -- the join is exact, not a similarity score
# ==========================================================================


def test_the_slug_parses_into_league_teams_and_date():
    parsed = mod.parse_slug("aec-nfl-lac-ten-2025-11-02")
    assert parsed["league"] == "nfl"
    assert parsed["away"] == "lac"
    assert parsed["home"] == "ten"
    assert parsed["date"] == "2025-11-02"
    assert parsed["modifiers"] == []


def test_modifiers_are_kept_for_spread_and_total_slugs():
    assert mod.parse_slug("asc-nfl-nyg-nyj-2026-08-28-pos-14pt5")["modifiers"] == ["pos", "14pt5"]
    assert mod.parse_slug("tsc-nfl-tb-jax-2026-08-28-1q-17pt5")["modifiers"] == ["1q", "17pt5"]


def test_an_unparseable_slug_is_None_rather_than_a_guess():
    """A slug we cannot parse is a market we cannot place. Inventing a parse is
    how a row gets joined to the wrong game."""
    for bad in ("", None, "not-a-slug", "aec-nfl-lac-ten-notadate"):
        assert mod.parse_slug(bad) is None


def test_pt_is_a_DECIMAL_POINT_not_a_digit():
    """`14pt5` is +14.5. Reading it as an integer prices a +14.5 spread at
    +145."""
    body = mod.join_polymarket_to_board(
        [_market(slug="asc-mlb-pit-sd-2026-08-24-pos-14pt5",
                 kind="SPORTS_MARKET_TYPE_SPREAD", outcomes=("Padres", "Pirates"))],
        [_board(market="spreads", side="Padres", line=14.5)],
    )
    assert body["matched"] == 1


def test_the_LAST_number_is_the_line_not_the_first():
    """`tsc-nfl-tb-jax-2026-08-28-1q-17pt5` carries a SEGMENT (1q) and a line
    (17.5). Taking the first would price a full-game total at the first
    quarter's number."""
    assert mod._line_from_modifiers(["1q", "17pt5"]) == 17.5
    assert mod._line_from_modifiers(["pos", "14pt5"]) == 14.5
    assert mod._line_from_modifiers(["neg", "3pt5"]) == -3.5


# ==========================================================================
# What is refused, and why each refusal is its own counter
# ==========================================================================


def test_a_segment_market_is_refused_not_priced_as_a_full_game():
    """The board's `totals` means the FULL GAME. Pricing it from a
    first-quarter market is a different bet at a confident-looking number."""
    result = mod.join_polymarket_to_board(
        [_market(slug="tsc-mlb-pit-sd-2026-08-24-1q-17pt5",
                 kind="SPORTS_MARKET_TYPE_TOTAL", outcomes=("Over", "Under"))],
        [_board(market="totals", side="Over", line=17.5)],
    )
    assert result["matched"] == 0
    assert result["refusals"]["segment_market_not_full_game"] == 1


def test_player_props_are_refused_by_name_rather_than_half_matched():
    """Props are REAL on this venue. Resolving `jakman` to a roster name is a
    different problem, and a prop priced by a guessed player is a real order on
    the wrong person."""
    result = mod.join_polymarket_to_board(
        [_market(slug="astatc-mlb-pit-sd-2026-08-24-hits-jakman-gte2",
                 kind="SPORTS_MARKET_TYPE_PROP", outcomes=("Yes", "No"))],
        [],
    )
    assert result["refusals"]["market_type_not_a_game_line"] == 1


def test_an_unseen_market_type_is_refused_not_mapped_to_a_neighbour():
    result = mod.join_polymarket_to_board(
        [_market(kind="SPORTS_MARKET_TYPE_SOMETHING_NEW")], [],
    )
    assert result["refusals"]["market_type_not_a_game_line"] == 1


def test_a_wrong_line_does_not_match():
    result = mod.join_polymarket_to_board(
        [_market(slug="asc-mlb-pit-sd-2026-08-24-pos-1pt5",
                 kind="SPORTS_MARKET_TYPE_SPREAD", outcomes=("Padres", "Pirates"))],
        [_board(market="spreads", side="Padres", line=2.5)],
    )
    assert result["matched"] == 0
    assert result["refusals"]["no_matching_polymarket_market"] == 1


def test_BOTH_clubs_must_match_not_one():
    """Matching on one club pairs a row with that team's OTHER fixture -- a
    real risk on a doubleheader."""
    result = mod.join_polymarket_to_board(
        [_market(slug="aec-mlb-pit-lad-2026-08-24", outcomes=("Pirates", "Dodgers"))],
        [_board(side="Padres", home="San Diego Padres", away="Pittsburgh Pirates")],
    )
    assert result["matched"] == 0


def test_a_side_that_is_not_an_outcome_is_its_own_counter():
    """The game-line join's measured failure was
    `side_not_a_team_in_this_game: 77`. The market matched; the SIDE could not
    be placed. That is a different fix from "no market", so it is a different
    counter."""
    result = mod.join_polymarket_to_board(
        [_market(outcomes=("Pirates", "Padres"))],
        [_board(side="Mariners")],
    )
    assert result["matched"] == 0
    assert result["refusals"]["side_not_an_outcome_of_this_market"] == 1


def test_every_drop_is_counted_so_matched_zero_is_diagnosable():
    """`matched=0` is the same number whether slugs failed to parse, the date
    was wrong, or the venue does not quote the sport. Only the refusal
    breakdown separates them."""
    result = mod.join_polymarket_to_board(
        [_market(slug="garbage"), _market(kind="SPORTS_MARKET_TYPE_PROP")],
        [_board(date="2099-01-01")],
    )
    assert result["matched"] == 0
    assert result["refusals"]["slug_unparseable"] == 1
    assert result["refusals"]["market_type_not_a_game_line"] == 1
    assert result["refusals"]["no_polymarket_market_for_league_date_market"] == 1


# ==========================================================================
# Matching and pricing
# ==========================================================================


def test_a_moneyline_matches_and_prices_from_POLYMARKET(monkeypatch):
    result = mod.join_polymarket_to_board([_market()], [_board(side="Padres")])
    assert result["matched"] == 1
    match = result["matches"][0]
    assert match["polymarket_probability"] == pytest.approx(0.55)
    # 0.55 -> -122 American. Priced from the venue, not the aggregator.
    assert match["polymarket_american"] == -122
    assert match["polymarket_slug"] == "aec-mlb-pit-sd-2026-08-24"


def test_the_order_fields_ride_along_with_the_match():
    """`order_body` REFUSES to infer tick size and minimum quantity, so a
    caller holding the ticker holds everything the order needs."""
    match = mod.join_polymarket_to_board([_market()], [_board(side="Padres")])["matches"][0]
    assert match["tick_size"] == 0.01
    assert match["minimum_trade_qty"] == 1


def test_a_board_side_naming_the_full_club_matches_the_venue_nickname():
    """The board writes "San Diego Padres", the venue writes "Padres"."""
    result = mod.join_polymarket_to_board([_market()], [_board(side="San Diego Padres")])
    assert result["matched"] == 1


def test_an_AMBIGUOUS_match_is_refused_rather_than_taken_in_order():
    """Two venue markets claiming one board row, resolved by iteration order,
    is a bet on whichever came first -- confident and wrong half the time."""
    duplicate = [_market(), _market(slug="aec-mlb-pit-sd-2026-08-24-dup")]
    result = mod.join_polymarket_to_board(duplicate, [_board(side="Padres")])
    assert result["matched"] == 0
    assert result["refusals"]["ambiguous_polymarket_match"] == 1


# ==========================================================================
# The resolvers -- keyed exactly as the join matched
# ==========================================================================


def test_the_price_resolver_returns_polymarkets_american_price():
    matches = mod.join_polymarket_to_board([_market()], [_board(side="Padres")])["matches"]
    resolve = mod.polymarket_price_resolver(matches)
    assert resolve(_board(side="Padres")) == -122
    assert resolve.market_count == 1


def test_the_resolver_is_not_LOOSER_than_the_join():
    """A lookup looser than the join would silently reintroduce exactly the
    mismatches the join refuses."""
    matches = mod.join_polymarket_to_board(
        [_market(slug="asc-mlb-pit-sd-2026-08-24-pos-1pt5",
                 kind="SPORTS_MARKET_TYPE_SPREAD", outcomes=("Padres", "Pirates"))],
        [_board(market="spreads", side="Padres", line=1.5)],
    )["matches"]
    resolve = mod.polymarket_price_resolver(matches)
    assert resolve(_board(market="spreads", side="Padres", line=1.5)) is not None
    # Different line, different bet.
    assert resolve(_board(market="spreads", side="Padres", line=2.5)) is None
    # Different side, different bet.
    assert resolve(_board(market="spreads", side="Pirates", line=1.5)) is None


def test_the_ticker_resolver_is_SEPARATE_from_the_price_resolver():
    """A function returning either a float or a dict is one every caller must
    shape-test, and the caller that forgets places an order priced by a dict."""
    matches = mod.join_polymarket_to_board([_market()], [_board(side="Padres")])["matches"]
    ticker = mod.polymarket_ticker_resolver(matches)
    resolved = ticker(_board(side="Padres"))
    assert resolved["slug"] == "aec-mlb-pit-sd-2026-08-24"
    assert resolved["tick_size"] == 0.01
    assert resolved["minimum_trade_qty"] == 1
    assert ticker(_board(side="Pirates")) is None


def test_an_unmatched_row_resolves_to_None_not_a_default_price():
    resolve = mod.polymarket_price_resolver([])
    assert resolve(_board()) is None
    assert resolve.market_count == 0


def test_the_SIGN_is_its_own_token_and_flips_the_bet():
    """`asc-nfl-nyg-nyj-2026-08-28-pos-14pt5` puts the sign in a separate
    token. A regex handling only `neg14pt5` reads -14.5 as +14.5 -- the
    opposite side of the same spread, at a price that looks reasonable."""
    assert mod._line_from_modifiers(["neg", "14pt5"]) == -14.5
    assert mod._line_from_modifiers(["pos", "14pt5"]) == 14.5
    # And a segment before the sign does not confuse it.
    assert mod._line_from_modifiers(["1h", "neg", "3pt5"]) == -3.5


def test_a_negative_and_positive_spread_are_DIFFERENT_bets():
    result = mod.join_polymarket_to_board(
        [_market(slug="asc-mlb-pit-sd-2026-08-24-neg-1pt5",
                 kind="SPORTS_MARKET_TYPE_SPREAD", outcomes=("Padres", "Pirates"))],
        [_board(market="spreads", side="Padres", line=1.5)],
    )
    assert result["matched"] == 0, "a -1.5 market must not price a +1.5 row"


def test_the_venue_ABBREVIATION_matches_the_boards_full_club_name():
    """`sd` is not a substring of `sandiegopadres`. A containment test matched
    nothing here and looked exactly like "the venue does not quote this" --
    the failure mode this repo keeps paying for."""
    result = mod.join_polymarket_to_board(
        [_market(slug="aec-mlb-pit-sd-2026-08-24", outcomes=("Pirates", "Padres"))],
        [_board(side="Padres", home="San Diego Padres", away="Pittsburgh Pirates")],
    )
    assert result["matched"] == 1


# ==========================================================================
# The 132: four different things wearing one counter
# ==========================================================================


def test_a_ONE_SIDED_quote_is_its_own_reason_not_generic_unreadable():
    """MEASURED 2026-08-24: `outcomes_unreadable: 132` (1.7% of 7,940). A
    market quoted on ONE SIDE ONLY is a real tradeable market being discarded,
    not a broken row -- opposite responses, so they cannot share a counter. A
    logged row carried outcomes=["Yes","No"] against prices=["0.0010"], and a
    parallel lane measured 88% of soccer live prop quotes as one-sided."""
    result = mod.join_polymarket_to_board(
        [_market(outcomes=("Yes", "No"), prices=("0.0010",))], [],
    )
    assert result["refusals"]["outcomes_count_mismatch"] == 1
    assert "outcomes_unreadable" not in result["refusals"]


def test_a_one_sided_quote_is_still_REFUSED_for_now():
    """Deliberately. Pairing positionally assumes prices[0] belongs to
    names[0] -- plausible, unverified, and on a two-outcome market a wrong
    assumption is a real order on the opposite team."""
    result = mod.join_polymarket_to_board(
        [_market(outcomes=("Padres", "Pirates"), prices=("0.55",))],
        [_board(side="Padres")],
    )
    assert result["matched"] == 0


@pytest.mark.parametrize("row,expected", [
    ({"outcomes": None, "outcomePrices": '["0.5"]'}, "outcomes_field_missing"),
    ({"outcomes": "not json", "outcomePrices": '["0.5"]'}, "outcomes_not_a_json_list"),
    ({"outcomes": "[]", "outcomePrices": "[]"}, "outcomes_empty"),
    ({"outcomes": '["A","B"]', "outcomePrices": '["0.5","x"]'}, "price_not_numeric"),
])
def test_each_parse_failure_gets_its_own_name(row, expected):
    market = _market()
    market.update(row)
    result = mod.join_polymarket_to_board([market], [])
    assert result["refusals"][expected] == 1


def test_the_SHAPE_is_sampled_so_a_count_can_be_explained():
    """A count says how many; only a sample says WHAT. Every unexplained
    refusal this week needed the sample to resolve."""
    result = mod.join_polymarket_to_board(
        [_market(slug="asc-mlb-pit-sd-2026-08-24-pos-1pt5",
                 kind="SPORTS_MARKET_TYPE_SPREAD",
                 outcomes=("Yes", "No"), prices=("0.0010",))], [],
    )
    shape = result["unreadable_shapes"][0]
    assert shape["reason"] == "outcomes_count_mismatch"
    assert shape["type"] == "SPORTS_MARKET_TYPE_SPREAD"
    assert '"Yes"' in shape["outcomes"]
    assert "0.0010" in shape["prices"]


def test_the_sample_is_BOUNDED_so_the_log_line_stays_a_log_line():
    markets = [_market(slug=f"aec-mlb-pit-sd-2026-08-2{i%9}", outcomes=("Y", "N"), prices=("0.5",))
               for i in range(40)]
    result = mod.join_polymarket_to_board(markets, [])
    assert result["refusals"]["outcomes_count_mismatch"] == 40
    assert len(result["unreadable_shapes"]) == 6


# ==========================================================================
# DRAWABLE_OUTCOME (soccer's 3-way h2h) and the soccer league key -- 2026-08-25
# ==========================================================================


def test_drawable_outcome_is_a_mapped_game_line_not_a_refusal():
    """Was refused as `market_type_not_a_game_line` alongside PROP -- the
    largest refusal bucket measured (5,810-6,612 of ~12,200-12,900 markets
    every cycle). Confirmed live in `POLYMARKET_US_GAMES` catalogue logs as a
    real game-market type. Slug is `<away>-<home>` -- `ars` away, `che` home."""
    assert mod.MARKET_TYPE_TO_BOARD["SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME"] == "h2h"
    result = mod.join_polymarket_to_board(
        [_market(slug="aec-eflc-ars-che-2026-08-25",
                 kind="SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME",
                 outcomes=("Arsenal", "Chelsea"))],
        [_board(side="Arsenal", home="Chelsea", away="Arsenal",
                date="2026-08-25", sport="soccer")],
    )
    assert result["matched"] == 1


def test_a_draw_outcome_with_no_board_side_is_dropped_not_an_error():
    """A third "Draw" outcome resolves to no club and no board `h2h` side asks
    for it today -- it must simply not match anything, not raise or refuse
    the whole row."""
    result = mod.join_polymarket_to_board(
        [_market(slug="aec-eflc-ars-che-2026-08-25",
                 kind="SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME",
                 outcomes=("Arsenal", "Chelsea", "Draw"),
                 prices=("0.45", "0.30", "0.25"))],
        [_board(side="Arsenal", home="Chelsea", away="Arsenal",
                date="2026-08-25", sport="soccer")],
    )
    assert result["matched"] == 1
    assert result["matches"][0]["polymarket_probability"] == pytest.approx(0.45)


def test_soccer_effective_league_overrides_a_non_soccer_literal_token():
    """Polymarket lists soccer per COMPETITION (`eflc` observed live for EFL
    Championship); Syndicate stamps every soccer board row `sport="soccer"`
    uniformly. A literal `parsed["league"] == "soccer"` compare can never
    match, so `_effective_league` recognises the row by its CLUBS instead."""
    parsed = mod.parse_slug("aec-eflc-ars-che-2026-08-25")
    assert parsed["league"] == "eflc"
    assert mod._effective_league(parsed) == "soccer"


def test_effective_league_leaves_non_soccer_leagues_untouched():
    """mlb/nfl/nba/wnba already match on the literal token -- this must not
    change behaviour for any of them."""
    for slug in ("aec-mlb-pit-sd-2026-08-24", "aec-nfl-lac-ten-2025-11-02"):
        parsed = mod.parse_slug(slug)
        assert mod._effective_league(parsed) == parsed["league"]


def test_effective_league_does_not_relabel_an_unresolvable_pair():
    """Both clubs must resolve as soccer clubs before the row is relabelled --
    an unknown pair keeps its literal (probably wrong, but not GUESSED)
    league token."""
    parsed = mod.parse_slug("aec-xyz-zzznotaclub-alsonotaclub-2026-08-25")
    assert mod._effective_league(parsed) == "xyz"


def test_a_soccer_row_matches_the_board_across_a_non_soccer_league_token():
    """End to end: the board asks for `sport="soccer"`, the venue's slug
    carries the competition token `eflc`, and the row still matches -- the
    fix this test guards against regressing."""
    result = mod.join_polymarket_to_board(
        [_market(slug="aec-eflc-ars-che-2026-08-25", outcomes=("Arsenal", "Chelsea"))],
        [_board(side="Arsenal", home="Chelsea", away="Arsenal",
                date="2026-08-25", sport="soccer")],
    )
    assert result["matched"] == 1
