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
           away="Pittsburgh Pirates", date="2026-08-24", sport="mlb",
           event_id="evt-pit-sd", **kw):
    # `event_id` IS PART OF A BOARD ROW AND PART OF THE RESOLVER KEY.
    #
    # It was absent from this fixture, which is how the wrong-game defect lived
    # here undisturbed: every fixture row was the same nameless game, so a key
    # that omitted the game looked like an identity. Published board rows always
    # carry one (`layer2_board.py:1825`).
    row = {"market": market, "side": side, "line": line, "home": home,
           "away": away, "selected_date": date, "sport": sport,
           "event_id": event_id}
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
    mismatches the join refuses.

    THIS TEST NAMED THE RIGHT PROPERTY AND TESTED A WEAKER ONE. It varies the
    LINE and the SIDE within a single game, and both of those were in the old
    key -- so it passed while the resolver was looser than the join in the one
    dimension the key omitted: the GAME. Production bought that gap on
    2026-08-25 (a BAL@STL slug stamped on a CIN@SF row).

    The missing case now lives in `test_polymarket_resolver_wrong_game.py`,
    which varies the game and holds everything else fixed. Kept here as-is
    because the line/side dimensions are still worth pinning."""
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


# --------------------------------------------------------------------------
# What we fetch and discard, characterised rather than assumed
# --------------------------------------------------------------------------


def _prop_row(slug, question, market_type="SPORTS_MARKET_TYPE_PROP"):
    return {
        "slug": slug,
        "sportsMarketTypeV2": market_type,
        "question": question,
        "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.5","0.5"]',
        "orderPriceMinTickSize": "0.01",
        "minimumTradeQty": "1",
    }


def test_out_of_scope_markets_are_counted_by_type_and_league():
    """6,838 `market_type_not_a_game_line` are fetched and discarded every
    cycle and had never been characterised. A count keyed by (type, league)
    turns "out of scope" from a standing assumption into a revisitable one."""
    markets = [
        _prop_row("astatc-lol-bam-gng-2026-08-20-game1", "Will Baam win Game 1?"),
        _prop_row("astatc-lol-doc-fsk-2026-08-20-game1", "Will Doc win Game 1?"),
        _prop_row("astatc-nfl-lar-lac-2026-08-27-x", "Will someone score a TD?"),
    ]
    report = mod.join_polymarket_to_board(markets, [], selected_date="2026-08-20")
    counts = report["out_of_scope_counts"]
    assert counts["SPORTS_MARKET_TYPE_PROP|lol"] == 2
    assert counts["SPORTS_MARKET_TYPE_PROP|nfl"] == 1


def test_the_out_of_scope_sample_carries_the_QUESTION():
    """The slug says which game; only the question says what the bet IS.

    Measured 2026-08-25T17:05:02Z: `astatc-lol-bam-gng-2026-08-20-game1` with
    type `SPORTS_MARKET_TYPE_PROP` is a League of Legends MAP WINNER, not a
    player prop. The type alone cannot name the family, so a parser written
    from the type would be written for the wrong thing.
    """
    markets = [_prop_row("astatc-lol-bam-gng-2026-08-20-game1",
                         "Will Baam Esports win Game 1 vs GnG Amazigh?")]
    report = mod.join_polymarket_to_board(markets, [], selected_date="2026-08-20")
    sample = report["out_of_scope_samples"][0]
    assert sample["question"] == "Will Baam Esports win Game 1 vs GnG Amazigh?"
    assert sample["key"] == "SPORTS_MARKET_TYPE_PROP|lol"


def test_the_sample_is_one_per_type_and_league_but_the_count_is_complete():
    """Same argument as the Kalshi title sample: the sample teaches the
    grammar, the count answers "is this family here at all"."""
    markets = [
        _prop_row(f"astatc-lol-t{n}-o{n}-2026-08-20-game1", f"Q{n}") for n in range(9)
    ]
    report = mod.join_polymarket_to_board(markets, [], selected_date="2026-08-20")
    assert report["out_of_scope_counts"]["SPORTS_MARKET_TYPE_PROP|lol"] == 9
    assert len(report["out_of_scope_samples"]) == 1


def test_segment_markets_are_sampled_separately_from_type_refusals():
    """A quarter total is a market we CAN parse and choose not to join; a prop
    is one we cannot yet name. Sharing a sample key would hide both."""
    markets = [{
        "slug": "tsc-nfl-tb-jax-2026-08-28-1q-17pt5",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
        "question": "1Q total over 17.5?",
        "outcomes": '["Over","Under"]',
        "outcomePrices": '["0.5","0.5"]',
        "orderPriceMinTickSize": "0.01",
        "minimumTradeQty": "1",
    }]
    report = mod.join_polymarket_to_board(markets, [], selected_date="2026-08-28")
    assert "SPORTS_MARKET_TYPE_TOTAL|SEGMENT|nfl" in report["out_of_scope_counts"]


# --------------------------------------------------------------------------
# A board row the venue could not be paired with: both sides, not a count
# --------------------------------------------------------------------------


def _total_market(slug, line_prices=("0.5", "0.5")):
    import json as _json
    return {
        "slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
        "outcomes": _json.dumps(["Over", "Under"]),
        "outcomePrices": _json.dumps(list(line_prices)),
        "orderPriceMinTickSize": "0.01", "minimumTradeQty": "1",
    }


def test_a_game_the_venue_never_listed_reports_an_EMPTY_offered_list():
    """"The venue does not list this game" and "it lists it under a name we do
    not recognise" need opposite responses, and shared a counter
    (`no_matching_polymarket_market: 54`). An empty `offered` is the first."""
    report = mod.join_polymarket_to_board(
        [],
        [{"sport": "mlb", "market": "totals", "side": "under", "line": 10.5,
          "away_team": "Minnesota Twins", "home_team": "Athletics",
          "date": "2026-08-25", "event_id": "e1"}],
        selected_date="2026-08-25",
    )
    sample = report["unmatched_samples"][0]
    assert sample["kind"] == "no_candidates"
    assert sample["offered"] == []
    assert "Athletics" in sample["board"]


def test_a_game_the_venue_DID_list_shows_what_it_offered():
    """The other half. A populated `offered` beside a failed match means the
    game IS there and the PAIRING failed -- a club-code or line question, not
    a coverage one.

    `Athletics` is the live example: the club moved, so `ath` / `oak` / `sac`
    are all plausible venue spellings and our club map carries only `ATH`.
    """
    report = mod.join_polymarket_to_board(
        [_total_market("tsc-mlb-min-sac-2026-08-25-10pt5")],
        [{"sport": "mlb", "market": "totals", "side": "under", "line": 10.5,
          "away_team": "Minnesota Twins", "home_team": "Athletics",
          "date": "2026-08-25", "event_id": "e1"}],
        selected_date="2026-08-25",
    )
    sample = report["unmatched_samples"][0]
    assert sample["kind"] == "no_match"
    assert sample["offered"] == ["min-sac@10.5"], sample
    assert sample["want"] == "totals|under|10.5"


def test_the_unmatched_count_is_complete_while_the_sample_is_bounded():
    """Same shape as every other work list added today: the sample teaches the
    pattern, the count says how much of the board it costs."""
    rows = [
        {"sport": "mlb", "market": "totals", "side": "under", "line": 10.5,
         "away_team": f"Team {n}", "home_team": "Athletics",
         "date": "2026-08-25", "event_id": f"e{n}"}
        for n in range(7)
    ]
    report = mod.join_polymarket_to_board([], rows, selected_date="2026-08-25")
    assert report["unmatched_counts"]["no_candidates|mlb|totals"] == 7
    assert len(report["unmatched_samples"]) == 1


def test_a_matched_row_is_not_sampled_as_unmatched():
    """The control -- a work list that fills with successes is noise."""
    report = mod.join_polymarket_to_board(
        [_total_market("tsc-mlb-min-ath-2026-08-25-10pt5")],
        [{"sport": "mlb", "market": "totals", "side": "under", "line": 10.5,
          "away_team": "Minnesota Twins", "home_team": "Athletics",
          "date": "2026-08-25", "event_id": "e1"}],
        selected_date="2026-08-25",
    )
    assert report["matched"] == 1
    assert report["unmatched_samples"] == []


# --------------------------------------------------------------------------
# A club-code coincidence must not reclassify a sport out of itself
# --------------------------------------------------------------------------


def test_an_mlb_slug_is_not_reclassified_as_soccer_by_colliding_tri_codes():
    """MEASURED 2026-08-25T18:49:14Z, in production, as a LOST POSITION.

    `_effective_league` asked only whether BOTH clubs resolve as soccer clubs.
    MLB tri-codes collide with soccer clubs:

        min -> Minnesota United FC (MLS)   | Minnesota Twins
        ath -> Athletic Club (Bilbao)      | Athletics
        sd  -> San Diego FC                | San Diego Padres

    So `tsc-mlb-min-ath-...` was indexed under league `soccer` while its MLB
    board row looked up `mlb`, and the two could never meet. A `totals under
    10.5` on Minnesota Twins @ Athletics reached the placer with
    `venue_ticker=None`.

    Tampa Bay @ Detroit filled minutes earlier from the same code path, because
    `tb` and `det` happen not to collide -- which is why this read as
    intermittent coverage rather than as a rule.
    """
    assert mod._effective_league(mod.parse_slug("tsc-mlb-min-ath-2026-08-25-10pt5")) == "mlb"
    assert mod._effective_league(mod.parse_slug("aec-mlb-sd-pit-2026-08-25")) == "mlb"


def test_the_colliding_game_now_joins_end_to_end():
    """The failure the user reported, as a join test."""
    report = mod.join_polymarket_to_board(
        [_total_market("tsc-mlb-min-ath-2026-08-25-10pt5")],
        [{"sport": "mlb", "market": "totals", "side": "under", "line": 10.5,
          "away_team": "Minnesota Twins", "home_team": "Athletics",
          "date": "2026-08-25", "event_id": "e1"}],
        selected_date="2026-08-25",
    )
    assert report["matched"] == 1, report["refusals"]


def test_a_real_soccer_competition_token_still_resolves_to_soccer():
    """The behaviour `e27812117` added is preserved and is the reason for an
    ALLOWLIST rather than a soccer denylist: Polymarket names soccer per
    COMPETITION (`eflc`), Syndicate stamps every soccer row `sport="soccer"`,
    and a competition token we have never seen must still be able to reach the
    soccer test."""
    parsed = mod.parse_slug("tsc-eflc-lee-bur-2026-08-25-2pt5")
    assert mod._effective_league(parsed) == "soccer"


def test_every_sport_syndicate_models_is_protected():
    """A club-code coincidence in ANY modelled sport must not move it. NBA and
    WNBA share tri-codes with each other and with soccer clubs."""
    for token in ("mlb", "nba", "wnba", "nfl", "nhl", "ncaaf", "ncaab"):
        parsed = mod.parse_slug(f"tsc-{token}-min-ath-2026-08-25-10pt5")
        assert mod._effective_league(parsed) == token, token


def test_a_slug_yields_the_browsable_game_page():
    """CONFIRMED BY THE USER 2026-08-25, one example, verbatim:

        slug  tsc-mlb-cin-sf-2026-08-25-7pt5
        url   https://polymarket.us/sports/mlb/mlb-cin-sf-2026-08-25

    The slug's PREFIX and MODIFIERS are both dropped. Until this, the repo had
    never seen a browsable Polymarket address -- the coverage audit refused to
    construct one, correctly, and that left its gap table unactionable.
    """
    from syndicate.features.shared.polymarket_board_join import market_web_url

    assert (
        market_web_url("tsc-mlb-cin-sf-2026-08-25-7pt5")
        == "https://polymarket.us/sports/mlb/mlb-cin-sf-2026-08-25"
    )
    # A moneyline slug carries no modifiers and lands on the same page.
    assert (
        market_web_url("aec-mlb-cin-sf-2026-08-25")
        == "https://polymarket.us/sports/mlb/mlb-cin-sf-2026-08-25"
    )


def test_the_url_speaks_POLYMARKETS_league_vocabulary_not_ours():
    """THE SECOND CONFIRMED EXAMPLE, and the one that mattered. User-supplied
    2026-08-25:

        astatc-epl-cry-mnc-2026-08-28 -> https://polymarket.us/sports/epl/epl-cry-mnc-2026-08-28

    Syndicate calls that sport `soccer`; Polymarket calls the competition
    `epl`. The open question was whose vocabulary the web form speaks, and it
    is theirs -- unchanged from the slug. So every soccer row in the coverage
    gap is checkable with a link built from what we already store, including
    the league codes we do not yet map (`lal`, `lg1`, `sea`, `bun`).
    """
    from syndicate.features.shared.polymarket_board_join import market_web_url

    assert (
        market_web_url("astatc-epl-cry-mnc-2026-08-28-btts")
        == "https://polymarket.us/sports/epl/epl-cry-mnc-2026-08-28"
    )
    # An unmapped soccer code builds by the same rule.
    assert (
        market_web_url("astatc-lal-ala-vil-2026-08-28-btts")
        == "https://polymarket.us/sports/lal/lal-ala-vil-2026-08-28"
    )


def test_every_market_on_one_game_collapses_to_ONE_url():
    """It addresses the GAME, not the MARKET, and the report must not imply
    otherwise. The modifiers that distinguish a 7.5 total from a spread ladder
    rung are exactly what the web form discards, so pointing someone at this
    URL for a specific market would send them looking for something the page
    does not single out."""
    from syndicate.features.shared.polymarket_board_join import market_web_url

    urls = {
        market_web_url(slug)
        for slug in (
            "tsc-mlb-cin-sf-2026-08-25-7pt5",
            "tsc-mlb-cin-sf-2026-08-25-8pt5",
            "asc-mlb-cin-sf-2026-08-25-pos-1pt5",
            "astatc-mlb-cin-sf-2026-08-25-hits-jakman-gte2",
        )
    }
    assert urls == {"https://polymarket.us/sports/mlb/mlb-cin-sf-2026-08-25"}


def test_an_unparseable_slug_yields_no_url_rather_than_a_broken_one():
    from syndicate.features.shared.polymarket_board_join import market_web_url

    assert market_web_url("garbage") is None
    assert market_web_url("") is None
    assert market_web_url(None) is None


# --------------------------------------------------------------------------
# LANE `venue-join-refusal-visibility` (2026-08-28)
#
# Production trace behind these: `POLYMARKET_UNMATCHED counts=
# {'no_match|soccer|h2h': 104, ...}` -- EVERY soccer h2h row on the board --
# while `/api/ops/polymarket/slate` reported `mls|h2h 30` sitting under a
# league token no board row can ever look up.
# --------------------------------------------------------------------------


def _slate(*slugs):
    return [{"slug": s, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE"} for s in slugs]


def test_a_competition_is_proven_by_the_PAIR_test_when_the_flat_one_declines(monkeypatch):
    """MLS was invisible for exactly this reason.

    `canonical_team` is the flat cross-league map and drops a club token that
    names two clubs in different leagues. `soccer_fixture_clubs` asks the same
    question as a PAIR -- both codes inside ONE league -- and `_teams_match`
    has trusted it as an additive fallback since 2026-08-27. It was never
    applied to proving a COMPETITION, so a token whose every fixture has one
    ambiguous code could never enter the soccer bucket.

    MEASURED on the live slate 2026-08-28: of 9 MLS fixtures, the flat test
    proved 0 and the pair test proved `tor-nyc`.
    """
    monkeypatch.setattr(mod, "parse_slug", mod.parse_slug)
    import syndicate.features.shared.team_aliases as aliases

    # Neither club resolves flat -- the real MLS condition.
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, name: None)
    monkeypatch.setattr(
        aliases,
        "soccer_fixture_clubs",
        # ARGUMENT ORDER IS (home, away) AND THE SLUG IS <away>-<home>.
        # `atc-mls-tor-nyc-...` parses to away=tor, home=nyc, so the call is
        # ("nyc", "tor"). Writing it the other way round made this test fail
        # against a correct implementation -- the same reversal, in a test,
        # that `_polymarket_sides` refuses to make in production.
        lambda home, away: ("toronto fc", "new york city fc")
        if (home, away) == ("nyc", "tor")
        else None,
    )
    proven = mod.soccer_competition_tokens(_slate("atc-mls-tor-nyc-2026-08-29-tor"))
    assert "mls" in proven, "the pair test must be able to prove a competition on its own"


def test_the_pair_test_is_ADDITIVE_and_cannot_unprove_a_token(monkeypatch):
    """Union, not replacement, and this is the measurement that forced it.

    On the same 2026-08-28 sample `elv-lev` passes the FLAT test and returns
    None as a pair. Swapping one test for the other would have bought MLS and
    silently sold a Bundesliga fixture -- a strictly worse trade that every
    aggregate number would have reported as an improvement.
    """
    import syndicate.features.shared.team_aliases as aliases

    monkeypatch.setattr(aliases, "canonical_team", lambda sport, name: f"club-{name}")
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda home, away: None)
    proven = mod.soccer_competition_tokens(_slate("atc-bun-elv-lev-2026-08-29-elv"))
    assert "bun" in proven, "a token the flat test proves must stay proven"


def test_a_sport_we_model_can_never_be_folded_into_soccer_by_the_pair_test(monkeypatch):
    """The MLB tri-code collision (`min`->Minnesota United, `ath`->Athletic
    Club) cost a real position on 2026-08-25. `_NON_SOCCER_LEAGUE_TOKENS`
    short-circuits FIRST and the new test must not reach around it."""
    import syndicate.features.shared.team_aliases as aliases

    monkeypatch.setattr(aliases, "canonical_team", lambda sport, name: None)
    monkeypatch.setattr(
        aliases, "soccer_fixture_clubs", lambda home, away: ("minnesota united", "athletic club")
    )
    proven = mod.soccer_competition_tokens(_slate("tsc-mlb-min-ath-2026-08-25-10pt5"))
    assert "mlb" not in proven


def test_a_competition_no_board_row_can_reach_is_COUNTED_with_its_club_codes():
    """`unproven_league_tokens` is the work list that replaces a guess.

    The codes matter, not the count: Polymarket's tri-codes are its own
    vocabulary, and each code here is one confirmable club -- the only basis on
    which a vendor alias may be added. Guessing them from the name is how a bet
    reaches the wrong team.
    """
    markets = [
        {
            "slug": "atc-nas-abc-xyz-2026-08-29-abc",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.40","0.60"]',
        }
    ]
    out = mod.join_polymarket_to_board(markets, [], selected_date="2026-08-29")
    assert "nas" in out["unproven_league_tokens"]
    assert set(out["unproven_league_tokens"]["nas"]) == {"abc", "xyz"}


def test_a_row_that_would_pair_only_when_flipped_is_counted_and_STILL_REFUSED(monkeypatch):
    """The measurement, and the guarantee that it stays a measurement.

    Production 2026-08-28: the board wanted `Elche CF @ Real Racing Club de
    Santander` at `totals under 2.5` and the venue offered `rrc-elc@2.5` --
    same two clubs, same line, refused. `parse_slug` reads `<away>-<home>`, so
    the slug gives home=rrc/away=elc against a board carrying the reverse.

    Two assertions, and the second is the important one: the row must be
    COUNTED and must still REFUSE. Applying a plausible orientation without
    ground truth is the `pos`/`neg` trap in a new costume -- a confident bet on
    the wrong team.
    """
    import syndicate.features.shared.team_aliases as aliases

    monkeypatch.setattr(
        aliases,
        "teams_match",
        lambda sport, a, b: {("rrc", "racing"), ("elc", "elche")}.__contains__(
            (str(a).lower(), str(b).lower())
        ),
    )
    markets = [{
        # `<away>-<home>` = away:rrc home:elc -- the INVERTED shape production
        # showed. Written `elc-rrc` first, which pairs NORMALLY and made this
        # test assert against a correct implementation. League token `soccer`
        # rather than `lal` so the row is bucketed without depending on
        # `soccer_competition_tokens` resolving a real competition here.
        "slug": "tsc-soccer-rrc-elc-2026-08-28-2pt5",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
        "outcomes": '["Over","Under"]',
        "outcomePrices": '["0.50","0.50"]',
    }]
    board = [{
        "market": "totals", "side": "under", "line": 2.5, "sport": "soccer",
        "selected_date": "2026-08-28", "home_team": "racing", "away_team": "elche",
        "event_id": "e1",
    }]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")
    assert out["orientation_flip_counts"].get("soccer|totals") == 1
    assert out["matched"] == 0, "counting the flip must never apply it"
    assert out["refusals"].get("no_matching_polymarket_market") == 1


def test_a_row_that_pairs_normally_is_NOT_counted_as_an_orientation_miss(monkeypatch):
    """The control has to be able to read zero.

    MLB and NFL pair correctly today. If this counter fired on rows that match
    the normal way, every sport would look equally broken and the per-sport cut
    -- the only thing that can distinguish "the slug order differs by sport"
    from "my orientation reading is wrong" -- would carry no information.
    """
    import syndicate.features.shared.team_aliases as aliases

    monkeypatch.setattr(
        aliases,
        "teams_match",
        lambda sport, a, b: {("lad", "dodgers"), ("det", "tigers")}.__contains__(
            (str(a).lower(), str(b).lower())
        ),
    )
    markets = [{
        "slug": "tsc-mlb-lad-det-2026-08-28-7pt5",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
        "outcomes": '["Over","Under"]',
        "outcomePrices": '["0.50","0.50"]',
    }]
    board = [{
        "market": "totals", "side": "under", "line": 7.5, "sport": "mlb",
        "selected_date": "2026-08-28", "home_team": "tigers", "away_team": "dodgers",
        "event_id": "e1",
    }]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")
    assert out["matched"] == 1
    assert out["orientation_flip_counts"] == {}


def test_the_control_carries_its_DENOMINATOR_not_just_its_zero(monkeypatch):
    """An absent rescue key must not be readable as a clean control.

    Caught by a second reader before the first production run. The rescue
    counter only increments when a flip SUCCEEDS, so a sport's absence meant
    either "tried on every unmatched row and never matched" (the hypothesis) or
    "never attempted here" (an untested branch reading as a pass).

    And the control was selected for the property that hollows it out: mlb/nfl
    are the control BECAUSE they pair correctly, which is exactly what leaves
    them almost no unmatched rows to try.

    So a row the flip was tried on and did NOT rescue must still move `tried`.
    """
    import syndicate.features.shared.team_aliases as aliases

    # Nothing matches, in either orientation.
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    markets = [{
        "slug": "tsc-mlb-lad-det-2026-08-28-7pt5",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
        "outcomes": '["Over","Under"]',
        "outcomePrices": '["0.50","0.50"]',
    }]
    board = [{
        "market": "totals", "side": "under", "line": 7.5, "sport": "mlb",
        "selected_date": "2026-08-28", "home_team": "tigers", "away_team": "dodgers",
        "event_id": "e1",
    }]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")
    assert out["orientation_flip_counts"] == {}, "nothing was rescued"
    assert out["orientation_flip_attempts"].get("mlb|totals") == 1, (
        "a zero with no denominator cannot be told from an untested branch"
    )


def test_a_row_with_no_line_compatible_candidate_is_NOT_counted_as_tried():
    """`tried` has to be able to read zero too, or it is not a denominator.

    A board row the venue quotes at no comparable line was never a test of
    orientation. Counting it would inflate the denominator and make a genuinely
    untested sport look exercised — the same failure this counter exists to
    prevent, one level down.
    """
    markets = [{
        "slug": "tsc-mlb-lad-det-2026-08-28-99pt5",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
        "outcomes": '["Over","Under"]',
        "outcomePrices": '["0.50","0.50"]',
    }]
    board = [{
        "market": "totals", "side": "under", "line": 7.5, "sport": "mlb",
        "selected_date": "2026-08-28", "home_team": "tigers", "away_team": "dodgers",
        "event_id": "e1",
    }]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")
    assert out["orientation_flip_attempts"] == {}


def _soccer_market(slug, mtype="SPORTS_MARKET_TYPE_MONEYLINE"):
    return {"slug": slug, "sportsMarketTypeV2": mtype,
            "outcomes": '["Yes","No"]', "outcomePrices": '["0.40","0.60"]'}


def _soccer_board(home, away, market="h2h", **over):
    row = {"market": market, "side": "home", "sport": "soccer",
           "selected_date": "2026-08-28", "home_team": home, "away_team": away,
           "event_id": "e1"}
    row.update(over)
    return row


def test_a_fixture_the_venue_LISTS_but_could_not_pair_is_the_real_denominator(monkeypatch):
    """`flipped / tried` is not a rate; `flipped / listed` is.

    A board row whose fixture the venue never listed sits in `tried` and can
    never reach the numerator. Production reported `soccer|h2h` 10 of 106 tried
    — and 106 included fixtures Polymarket does not carry at all.
    """
    import syndicate.features.shared.team_aliases as aliases

    canon = {"cry": "crystal palace", "mnc": "manchester city",
             "Crystal Palace": "crystal palace", "Manchester City": "manchester city"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)

    markets = [_soccer_market("atc-soccer-cry-mnc-2026-08-28-cry")]
    board = [_soccer_board("Crystal Palace", "Manchester City")]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")

    assert out["orientation_fixture_listed"].get("soccer|h2h") == 1
    assert out["orientation_fixture_not_listed"] == {}


def test_a_fixture_the_venue_DOES_NOT_LIST_is_coverage_not_a_join_defect(monkeypatch):
    """The 96. No join change recovers these, and they must not inflate the
    denominator that judges orientation."""
    import syndicate.features.shared.team_aliases as aliases

    canon = {"cry": "crystal palace", "mnc": "manchester city",
             "Everton": "everton", "Arsenal": "arsenal"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)

    markets = [_soccer_market("atc-soccer-cry-mnc-2026-08-28-cry")]
    board = [_soccer_board("Everton", "Arsenal")]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")

    assert out["orientation_fixture_not_listed"].get("soccer|h2h") == 1
    assert out["orientation_fixture_listed"] == {}


def test_an_UNREADABLE_club_token_is_its_own_bucket_not_counted_as_absent(monkeypatch):
    """"Listed but we cannot read it" and "not listed" are different facts.

    `canonical_team('soccer','rrc')` is None while
    `teams_match('soccer','rrc','Real Racing Club de Santander')` is True — so a
    fixture can be present and still fail to canonicalise. Folding that into
    `not_listed` would be the same conflation `no_match` already makes.
    """
    import syndicate.features.shared.team_aliases as aliases

    canon = {"Elche CF": "elche", "Real Racing Club de Santander": "racing santander"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)

    markets = [_soccer_market("atc-soccer-rrc-elc-2026-08-28-rrc")]
    board = [_soccer_board("Real Racing Club de Santander", "Elche CF")]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")

    assert out["orientation_fixture_unreadable"].get("soccer|h2h") == 1
    assert out["orientation_fixture_not_listed"] == {}
    assert out["orientation_fixture_listed"] == {}


def test_eligibility_is_ORDER_INDEPENDENT_or_it_answers_its_own_question(monkeypatch):
    """The load-bearing property.

    Eligibility must NOT be decided by the orientation-sensitive matcher — that
    is what the flip test already does, and defining the denominator that way
    would make the rate 100% by construction. Comparing canonical clubs as a
    SET is what keeps the two independent, so a listed fixture reads as listed
    whichever way round the slug puts it.
    """
    import syndicate.features.shared.team_aliases as aliases

    canon = {"cry": "crystal palace", "mnc": "manchester city",
             "Crystal Palace": "crystal palace", "Manchester City": "manchester city"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    # `_teams_match` falls back to `soccer_fixture_clubs` for soccer, and the
    # REAL one reads the club artifacts. Left unstubbed it paired one of the two
    # orientations for real, so that row never reached the unmatched branch and
    # the test compared a bookkeeping counter against a row that had matched.
    # Both rows must be unmatched for this comparison to mean anything.
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)

    board = [_soccer_board("Crystal Palace", "Manchester City")]
    forward = mod.join_polymarket_to_board(
        [_soccer_market("atc-soccer-cry-mnc-2026-08-28-cry")], board,
        selected_date="2026-08-28")
    reverse = mod.join_polymarket_to_board(
        [_soccer_market("atc-soccer-mnc-cry-2026-08-28-mnc")], board,
        selected_date="2026-08-28")

    assert forward["orientation_fixture_listed"] == reverse["orientation_fixture_listed"] == {"soccer|h2h": 1}


def test_a_FLIP_MATCH_counts_as_proof_the_fixture_is_listed(monkeypatch):
    """The invariant, and the defect that produced it.

    Production 18:55:16Z: `flipped={'soccer|h2h': 9}` against
    `listed={'soccer|h2h': 4}` — nine rows paired with a fixture the classifier
    had called absent. A flip-match is direct evidence of listing, and the
    first version could not use it because it classified BEFORE the flip loop.
    """
    import syndicate.features.shared.team_aliases as aliases

    # Board resolves; the venue tri-codes do NOT canonicalise -- the `rrc` case.
    canon = {"Real Racing Club de Santander": "racing santander", "Elche CF": "elche"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    # Pairs only when flipped.
    monkeypatch.setattr(
        aliases, "teams_match",
        lambda sport, a, b: (str(a), str(b)) in {
            ("rrc", "Real Racing Club de Santander"), ("elc", "Elche CF")},
    )

    # `<away>-<home>` = away:rrc home:elc, so FLIPPED gives home=rrc, which is
    # the board's home. Written `elc-rrc` first, which flips to home=elc and
    # pairs with nothing -- the same slug-order slip this lane has now made
    # three times, and the reason the field is no longer called
    # `slug_away_home`.
    markets = [_soccer_market("atc-soccer-rrc-elc-2026-08-28-rrc")]
    board = [_soccer_board("Real Racing Club de Santander", "Elche CF")]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")

    assert out["orientation_flip_counts"].get("soccer|h2h") == 1
    assert out["orientation_fixture_listed"].get("soccer|h2h") == 1, (
        "a flip-match proves the fixture is listed"
    )
    assert out["orientation_fixture_not_listed"] == {}
    assert out["orientation_invariant_ok"] is True


def test_absence_is_claimed_ONLY_when_every_candidate_canonicalised(monkeypatch):
    """The `elif readable` bug.

    Some candidates canonicalising says nothing about OURS. If any candidate in
    the bucket is unreadable, our fixture may be that one, so eligibility is
    unknown — not absent.
    """
    import syndicate.features.shared.team_aliases as aliases

    canon = {"cry": "crystal palace", "mnc": "manchester city",
             "Everton": "everton", "Arsenal": "arsenal"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)

    markets = [
        _soccer_market("atc-soccer-cry-mnc-2026-08-28-cry"),   # readable
        _soccer_market("atc-soccer-rrc-elc-2026-08-28-rrc"),   # NOT readable
    ]
    board = [_soccer_board("Everton", "Arsenal")]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")

    assert out["orientation_fixture_unreadable"].get("soccer|h2h") == 1
    assert out["orientation_fixture_not_listed"] == {}, (
        "one unreadable candidate makes absence unprovable"
    )


def test_absence_IS_claimed_when_the_whole_bucket_reads(monkeypatch):
    """The counter must still be able to say 'not listed', or `not_listed`
    becomes unreachable and the coverage half goes silent."""
    import syndicate.features.shared.team_aliases as aliases

    canon = {"cry": "crystal palace", "mnc": "manchester city",
             "Everton": "everton", "Arsenal": "arsenal"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)

    markets = [_soccer_market("atc-soccer-cry-mnc-2026-08-28-cry")]
    board = [_soccer_board("Everton", "Arsenal")]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")

    assert out["orientation_fixture_not_listed"].get("soccer|h2h") == 1
    assert out["orientation_invariant_ok"] is True
