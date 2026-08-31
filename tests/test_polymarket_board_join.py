"""Board row -> Polymarket's own price.

Fixes the gap `portfolio_commit.py:170` left: every venue but Kalshi got
`(None, None)`, so `paper:polymarket` was the aggregator's prices wearing a
venue label.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import polymarket_board_join as mod


# ---------------------------------------------------------------------------
# THE PER-LEAGUE SOCCER ROSTERS, AND THE ONE PREDICATE EVERY TEST THAT NEEDS
# THEM SHARES.
# ---------------------------------------------------------------------------
#
# `soccer_fixture_clubs` -> `_soccer_alias_by_league` -> `soccer.sources
# .all_teams` -> `rosters_path(league, season)` -> a `rosters_<season>.csv`
# under `data/soccer_source/`. Without `data/` the per-league map is EMPTY --
# not missing one club, empty -- so EVERY test that reaches the pair resolver
# fails.
#
# `scripts/session_worktree.py` excludes `data/` BY DEFAULT (34,689 of 37,745
# tracked files) and CLAUDE.md tells every session to work that way, so a
# protocol-standard worktree fails all of them. A red that also means "you
# followed the worktree instructions" is a red people learn to ignore.
#
# ONE PREDICATE, ONE REASON, APPLIED AT EVERY SITE. The first fix gated a single
# test and left eight more red -- fixing one instance of a shared cause, which
# is how a defect comes back under a different name.
def _soccer_rosters_present() -> bool:
    try:
        from syndicate.features.soccer.sources import rosters_path
    except Exception:  # noqa: BLE001
        return False
    for league in ("epl", "la_liga", "serie_a"):
        for season in (2026, 2025):
            try:
                if rosters_path(league, season).exists():
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


needs_soccer_rosters = pytest.mark.skipif(
    not _soccer_rosters_present(),
    reason=(
        "per-league soccer rosters absent from this tree -- "
        "`scripts/session_worktree.py` excludes `data/` BY DEFAULT and CLAUDE.md "
        "tells every session to work that way, so the pair resolver has no map "
        "to answer from. SKIPPED rather than RED: a red that also means 'you "
        "followed the worktree instructions' is a red people learn to ignore. "
        "Mechanism coverage that does NOT need the mirror lives in "
        "`test_the_pair_resolver_MECHANISM_with_an_injected_roster`."
    ),
)




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


@needs_soccer_rosters
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


@needs_soccer_rosters
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


@needs_soccer_rosters
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


@needs_soccer_rosters
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


@needs_soccer_rosters
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
        # Clubs NO token can name by prefix, initials or elimination -- the row
        # must stay unmatched to reach the flip counter this asserts. `elc`
        # against "elche" now pairs for real via fixture matching, which is
        # correct behaviour and made the old fixture untestable.
        lambda sport, a, b: {("zz1", "alpha"), ("zz2", "beta")}.__contains__(
            (str(a).lower(), str(b).lower())
        ),
    )
    markets = [{
        # `<away>-<home>` = away:rrc home:elc -- the INVERTED shape production
        # showed. Written `elc-rrc` first, which pairs NORMALLY and made this
        # test assert against a correct implementation. League token `soccer`
        # rather than `lal` so the row is bucketed without depending on
        # `soccer_competition_tokens` resolving a real competition here.
        "slug": "tsc-soccer-zz1-zz2-2026-08-28-2pt5",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
        "outcomes": '["Over","Under"]',
        "outcomePrices": '["0.50","0.50"]',
    }]
    board = [{
        "market": "totals", "side": "under", "line": 2.5, "sport": "soccer",
        "selected_date": "2026-08-28", "home_team": "alpha", "away_team": "beta",
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

    # `zzz`/`qqq` name no club, so fixture-consistency matching cannot pair
    # them -- these tests need the row to stay UNMATCHED to reach the
    # eligibility classifier at all.
    canon = {"zzz": "crystal palace", "qqq": "manchester city",
             "Crystal Palace": "crystal palace", "Manchester City": "manchester city"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)

    markets = [_soccer_market("atc-soccer-zzz-qqq-2026-08-28-zzz")]
    board = [_soccer_board("Crystal Palace", "Manchester City")]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")

    assert out["orientation_fixture_listed"].get("soccer|h2h") == 1
    assert out["orientation_fixture_not_listed"] == {}


def test_a_fixture_the_venue_DOES_NOT_LIST_is_coverage_not_a_join_defect(monkeypatch):
    """The 96. No join change recovers these, and they must not inflate the
    denominator that judges orientation."""
    import syndicate.features.shared.team_aliases as aliases

    canon = {"zzz": "crystal palace", "qqq": "manchester city",
             "Everton": "everton", "Arsenal": "arsenal"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)

    markets = [_soccer_market("atc-soccer-zzz-qqq-2026-08-28-zzz")]
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

    # `zz1`/`zz2` name neither club, so fixture-consistency cannot pair them
    # and the row reaches the flip test -- which is what this asserts.
    markets = [_soccer_market("atc-soccer-zz1-zz2-2026-08-28-zz1")]
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

    # `zzz`/`qqq` name no club, so fixture-consistency matching cannot pair
    # them -- these tests need the row to stay UNMATCHED to reach the
    # eligibility classifier at all.
    canon = {"zzz": "crystal palace", "qqq": "manchester city",
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
        [_soccer_market("atc-soccer-zzz-qqq-2026-08-28-zzz")], board,
        selected_date="2026-08-28")
    reverse = mod.join_polymarket_to_board(
        [_soccer_market("atc-soccer-zzz-qqq-2026-08-28-zzz-r")], board,
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
    # unchanged: the venue tokens deliberately do NOT canonicalise here
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    # Pairs only when flipped.
    monkeypatch.setattr(
        aliases, "teams_match",
        lambda sport, a, b: (str(a), str(b)) in {
            ("zz1", "Real Racing Club de Santander"), ("zz2", "Elche CF")},
    )

    # `<away>-<home>` = away:rrc home:elc, so FLIPPED gives home=rrc, which is
    # the board's home. Written `elc-rrc` first, which flips to home=elc and
    # pairs with nothing -- the same slug-order slip this lane has now made
    # three times, and the reason the field is no longer called
    # `slug_away_home`.
    # `zz1`/`zz2` name neither club, so fixture-consistency cannot pair them
    # and the row reaches the flip test -- which is what this asserts.
    markets = [_soccer_market("atc-soccer-zz1-zz2-2026-08-28-zz1")]
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

    canon = {"zzz": "crystal palace", "qqq": "manchester city",
             "Everton": "everton", "Arsenal": "arsenal"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)

    markets = [
        _soccer_market("atc-soccer-zzz-qqq-2026-08-28-zzz"),   # readable
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

    canon = {"zzz": "crystal palace", "qqq": "manchester city",
             "Everton": "everton", "Arsenal": "arsenal"}
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: canon.get(str(n)))
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)

    markets = [_soccer_market("atc-soccer-zzz-qqq-2026-08-28-zzz")]
    board = [_soccer_board("Everton", "Arsenal")]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")

    assert out["orientation_fixture_not_listed"].get("soccer|h2h") == 1
    assert out["orientation_invariant_ok"] is True


@needs_soccer_rosters
def test_a_venue_tri_code_resolves_only_inside_its_own_competition():
    """`(competition, code)`, never code alone — and this is the whole design.

    A flat table would reintroduce the bug `_soccer_alias_to_name` drops keys to
    avoid. Our own maps carry `mil` as BOTH `serie_a: ac milan` and
    `championship: millwall`; evidence for the Polymarket code covers Serie A
    only, so it must say nothing about the Championship.
    """
    assert mod._venue_club({"league": "sea"}, "mil") == "ac milan"
    assert mod._venue_club({"league": "eflch"}, "mil") is None, (
        "evidence for one competition must not leak into another"
    )
    assert mod._venue_club({"league": "bun"}, "fcb") == "bayern munich"
    assert mod._venue_club({"league": "lal"}, "fcb") is None, (
        "`fcb` is Bayern in the Bundesliga and Barcelona in La Liga -- the "
        "canonical ambiguous token this module's history records"
    )


@needs_soccer_rosters
def test_every_tri_code_entry_resolves_through_canonical_team():
    """An entry naming a club the alias map cannot canonicalise is dead weight
    that reads as a working mapping. Cheap to assert, and it catches a typo in
    the club name — the most likely way one of these silently stops working."""
    from syndicate.features.shared.team_aliases import canonical_team

    unresolved = [
        (league, code, name)
        for (league, code), name in mod._VENUE_TRI_CODES.items()
        if not canonical_team("soccer", name)
    ]
    assert unresolved == [], f"tri-code entries naming an unknown club: {unresolved}"


def test_the_tri_code_table_is_additive_and_cannot_remove_a_pairing(monkeypatch):
    """Reached only after `alias_match` declines both clubs, so it can add a
    match and never take one away."""
    import syndicate.features.shared.team_aliases as aliases

    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    parsed = {"league": "bun", "home": "fcb", "away": "stu"}
    board = {"home_team": "anything", "away_team": "anything else"}
    assert mod._teams_match(board, parsed, "soccer") is True


def _align(fair, venue_p):
    counts, samples = {}, []
    mod._classify_alignment(
        {"quote": {"fair_probability": fair}, "side": "home",
         "home_team": "H", "away_team": "A"},
        venue_p, "soccer|h2h", counts, samples)
    return counts, samples


def test_a_price_matching_the_books_own_fair_reads_ALIGNED():
    counts, _ = _align(0.75, 0.73)
    assert counts == {"soccer|h2h|aligned": 1}


def test_a_price_sitting_on_the_COMPLEMENT_reads_INVERTED():
    """The signature of handing a side the other side's price: the number lands
    near `1 - fair`, which on a lopsided market is tens of cents away."""
    counts, samples = _align(0.75, 0.26)
    assert counts == {"soccer|h2h|inverted": 1}
    assert samples and samples[0]["complement"] == 0.25


def test_a_NEAR_COINFLIP_market_is_refused_not_scored():
    """`fair` and `1 - fair` converge at 0.5, so the test cannot separate the
    hypotheses there. Scoring it anyway is exactly how the spread-sign audit
    manufactured a rate out of a comparison with no discriminating power — and
    how a ONE-CENT gap came to look like evidence in `#595` step 1.
    """
    counts, _ = _align(0.505, 0.50)
    assert counts == {"soccer|h2h|too_close": 1}


def test_a_NORMAL_BETTING_EDGE_cannot_masquerade_as_an_inversion():
    """The confound that would make this instrument lie.

    We bet Polymarket precisely when it disagrees with the books, so a few
    points of disagreement is the signal, not an error. The thresholds put the
    two hypotheses >= 0.20 apart so an ordinary edge cannot cross over.
    """
    counts, _ = _align(0.70, 0.62)          # an 8-point edge, still clearly aligned
    assert counts == {"soccer|h2h|aligned": 1}


def test_a_row_with_no_book_reference_is_counted_not_silently_dropped():
    counts, _ = _align(None, 0.60)
    assert counts == {"soccer|h2h|no_reference": 1}


def _listing_split(monkeypatch, *, canonical_hits, flip_hits):
    """One unmatched soccer h2h row; control whether canonical and/or flip find it."""
    import syndicate.features.shared.team_aliases as aliases
    # `zzz`/`qqq` name no club, so fixture-consistency matching cannot pair
    # them -- these tests need the row to stay UNMATCHED to reach the
    # eligibility classifier at all.
    canon = {"zzz": "crystal palace", "qqq": "manchester city",
             "Crystal Palace": "crystal palace", "Manchester City": "manchester city"}
    monkeypatch.setattr(
        aliases, "canonical_team",
        (lambda sport, n: canon.get(str(n))) if canonical_hits else (lambda sport, n: None))
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(
        aliases, "teams_match",
        # Pairs only when flipped. Slug `zzz-qqq` parses to away=zzz, home=qqq,
        # so the NORMAL test asks (qqq, board_home) and fails; flipping asks
        # (zzz, board_home) and succeeds. Getting this pair the wrong way round
        # makes the row match normally and never reach the flip -- the same
        # slug-order slip this lane has now made four times.
        (lambda sport, a, b: (str(a), str(b)) in {
            ("zzz", "Crystal Palace"), ("qqq", "Manchester City")})
        if flip_hits else (lambda sport, a, b: False))
    markets = [_soccer_market("atc-soccer-zzz-qqq-2026-08-28-zzz")]
    board = [_soccer_board("Crystal Palace", "Manchester City")]
    return mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")


def test_a_listing_found_ONLY_by_the_flip_is_not_independent_evidence(monkeypatch):
    """The tautology this split exists to expose.

    `flipped / listed` = 1.0 by construction when every listing was established
    BY the flip. Two production readings returned listed and flipped identical
    (5/5, then 24/24) and were indistinguishable from a working measurement.
    """
    out = _listing_split(monkeypatch, canonical_hits=False, flip_hits=True)
    assert out["orientation_flip_counts"].get("soccer|h2h") == 1
    assert out["orientation_fixture_listed"].get("soccer|h2h") == 1
    assert out["orientation_listed_by_flip_only"].get("soccer|h2h") == 1
    assert out["orientation_listed_by_canonical"] == {}, (
        "a flip-established listing must not count as independent evidence"
    )


def test_a_listing_found_by_CANONICAL_pair_is_independent_evidence(monkeypatch):
    """The denominator that cannot be circular: the fixture was identified by
    comparing canonical club pairs, without consulting the orientation matcher."""
    out = _listing_split(monkeypatch, canonical_hits=True, flip_hits=True)
    assert out["orientation_listed_by_canonical"].get("soccer|h2h") == 1
    assert out["orientation_listed_by_flip_only"] == {}


def test_the_two_listing_buckets_partition_listed(monkeypatch):
    """They must sum to `listed` exactly, or the split hides rows instead of
    explaining them — the failure mode of every counter fixed in this lane."""
    for canon in (True, False):
        out = _listing_split(monkeypatch, canonical_hits=canon, flip_hits=True)
        total = sum(out["orientation_fixture_listed"].values())
        parts = (sum(out["orientation_listed_by_canonical"].values())
                 + sum(out["orientation_listed_by_flip_only"].values()))
        assert total == parts, f"listed={total} but split sums to {parts}"


def test_the_slugs_two_tokens_identify_the_BOARDS_own_matchup(monkeypatch):
    """The Villarreal @ Alaves row that sat unplaceable in tonight's plan.

    Polymarket LISTS the fixture (`atc-lal-ala-vil-2026-08-28`); the board has
    it; nothing paired them, so `venue_scope` fell back to the aggregator and
    committed a row with `venue_ticker: None` that the placer refused with
    `no_venue_ticker`. No alias map is needed to pair it -- the board row
    already names the fixture.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(
        aliases, "canonical_team",
        lambda sport, n: {"Alaves": "alaves", "Villarreal": "villarreal"}.get(str(n)))

    parsed = {"league": "lal", "home": "vil", "away": "ala"}
    board = {"home_team": "Alaves", "away_team": "Villarreal"}
    assert mod._teams_match(board, parsed, "soccer") is True


def test_matching_is_ORDER_INDEPENDENT_so_no_per_sport_ordering_rule_is_needed():
    """Soccer slugs are home-first and MLB's are away-first, both measured. A
    matcher comparing the two clubs as an unordered pair does not care, which
    is why this replaced the per-sport swap rather than sitting beside it."""
    f = mod._fixture_tokens_name_matchup
    assert f("ala", "vil", "Alaves", "Villarreal") is True
    assert f("vil", "ala", "Alaves", "Villarreal") is True


def test_a_token_naming_BOTH_clubs_refuses_rather_than_pairing():
    """One token matching both sides would pair almost anything. Both clubs
    must be named, and by DIFFERENT tokens."""
    assert mod._fixture_tokens_name_matchup("man", "man", "Manchester City",
                                            "Manchester United") is False


def test_an_INITIALS_token_resolves_but_a_LOOSER_shape_still_refuses():
    """`psg`/`whu`/`rrc` are initials, distinctive and safe. `mnc` is neither a
    prefix nor initials of Manchester City ("mc"); it stays refused because the
    looser rule that would catch it also lets it name Manchester United."""
    f = mod._fixture_tokens_name_matchup
    assert f("lil", "psg", "Lille", "Paris Saint Germain") is True
    assert f("wat", "whu", "Watford", "West Ham United") is True
    assert f("cry", "mnc", "Crystal Palace", "Manchester City") is False


def test_a_DIFFERENT_fixture_is_not_paired():
    """The wrong-game guard. Same competition and date, different clubs."""
    assert mod._fixture_tokens_name_matchup("ala", "vil", "Everton", "Arsenal") is False


def _no_aliases(monkeypatch):
    """Every alias resolver dark. Fixture matching must not need any of them."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: None)


_EPL_SLATE = [("Crystal Palace", "Manchester City"),
              ("Everton", "Arsenal"),
              ("Chelsea", "Fulham")]


def test_with_EVERY_RESOLVER_DARK_mnc_is_no_longer_carried(monkeypatch):
    """`mnc` COVERAGE, KEPT -- but carried by the pair resolver, not elimination.

    This test has flipped twice in one day and the history is the point.

    `mnc` is neither a prefix nor the initials of "Manchester City", so no token
    rule reaches it. Elimination used to accept it: `cry` named exactly one
    fixture, and `mnc` naming NOTHING was read as "does not contradict".

    That same permissiveness, on a token collision, cost a real order:

        board row   Nice @ Paris FC          (Ligue 1)
        slug        tsc-sea-juv-par-...-2pt5 (Serie A, Juventus-Parma)
        filled      $5.20 on "Over 2.5 total goals -- Juventus FC vs Parma"

    `par` prefixes BOTH "Paris FC" and "Parma"; `juv` matched neither Nice nor
    Paris FC and was waved through. The opponent token must now POSITIVELY name
    the other side.

    The first fix removed the permissive branch and TRADED THIS AWAY, on the
    reasoning that coverage is cheaper to lose than a wrong-game fill. That was
    the right call with the information available.

    The trade turned out to be unnecessary. `soccer_fixture_clubs('cry','mnc')`
    resolves to ('crystal palace', 'manchester city') -- the pair resolver knew
    this fixture all along, and it requires BOTH codes inside ONE league, so it
    also answers the competition question that let the wrong-game bet through.
    Running it FIRST and treating it as authoritative refuses `sea-juv-par`
    against a Ligue 1 row AND carries `mnc`.

    SO THE TRADE IS NARROWER THAN "LOST", AND NARROWER THAN "RESTORED":

      - alias table AVAILABLE (production): `mnc` is carried by the pair
        resolver. Proven by the test below, which uses the REAL resolver.
      - EVERY resolver dark (this test): `mnc` is NOT carried. Elimination alone
        can no longer rescue a token that names nothing, and that is the cost.

    This test pins the dark case because that is the half that actually changed.
    Kept rather than deleted so nobody re-adds the permissive branch.
    """
    _no_aliases(monkeypatch)
    assert mod._teams_match(
        {"home_team": "Crystal Palace", "away_team": "Manchester City"},
        {"league": "epl", "home": "mnc", "away": "cry", "date": "2026-08-28"},
        "soccer", _EPL_SLATE) is False


def test_ELIMINATION_refuses_when_the_token_names_TWO_fixtures(monkeypatch):
    """Exactly-one is the guard. A token naming two fixtures discriminates
    nothing — the same rule `_soccer_alias_to_name` applies when it drops a
    code that names two clubs."""
    _no_aliases(monkeypatch)
    assert mod._teams_match(
        {"home_team": "Chelsea", "away_team": "Fulham"},
        {"league": "epl", "home": "xxx", "away": "ch", "date": "2026-08-28"},
        "soccer", [("Chelsea", "Fulham"), ("Charlton", "Luton")]) is False


def test_ELIMINATION_does_not_pair_a_DIFFERENT_fixture(monkeypatch):
    """The wrong-game guard, with the slate present."""
    _no_aliases(monkeypatch)
    assert mod._teams_match(
        {"home_team": "Everton", "away_team": "Arsenal"},
        {"league": "epl", "home": "mnc", "away": "cry", "date": "2026-08-28"},
        "soccer", _EPL_SLATE) is False


def test_fixture_matching_works_with_EVERY_alias_resolver_DARK(monkeypatch):
    """The reason this sits ABOVE the canonicalisation guard.

    It compares raw board names and never calls `canonical_team`. Placed below
    that guard it was unreachable for every row whose club the alias map cannot
    name — 76 of 80 unmatched `soccer|h2h` rows measured tonight, i.e. exactly
    the population it exists to serve.
    """
    _no_aliases(monkeypatch)
    assert mod._teams_match(
        {"home_team": "Alaves", "away_team": "Villarreal"},
        {"league": "lal", "home": "vil", "away": "ala", "date": "2026-08-28"},
        "soccer", None) is True


def test_polymarket_BTTS_is_admitted_from_its_slug_modifier(monkeypatch):
    """Polymarket types BTTS as PROP, so it was refused with the other 8,029
    while the board carried 36 `btts` rows it could never reach.

    MEASURED 2026-08-28 -- three on fixtures this lane chased all day:
        astatc-lg1-lil-psg-2026-08-28-btts
        astatc-sea-mil-ven-2026-08-28-btts
        astatc-lal-ala-vil-2026-08-28-btts
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: None)

    markets = [{
        "slug": "astatc-soccer-ala-vil-2026-08-28-btts",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
        "outcomes": '["Yes","No"]', "outcomePrices": '["0.55","0.45"]',
    }]
    board = [{
        "market": "btts", "side": "yes", "line": None, "sport": "soccer",
        "selected_date": "2026-08-28",
        "home_team": "Alaves", "away_team": "Villarreal", "event_id": "e1",
    }]
    out = mod.join_polymarket_to_board(markets, board, selected_date="2026-08-28")
    assert out["refusals"].get("market_type_not_a_game_line") is None, out["refusals"]
    assert out["matched"] == 1, out


def test_the_OTHER_prop_families_still_refuse(monkeypatch):
    """PROP is admitted one NAMED family at a time, never as a class.

    `exact-score-0-0` is not a board row and `winner-1h-was` is a segment. Both
    sit in the same bucket as BTTS and must keep refusing -- opening PROP
    wholesale would have admitted them too.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")

    for slug in ("atc-soccer-ala-vil-2026-08-28-exact-score-0-0",
                 "atc-soccer-ala-vil-2026-08-28-winner-1h-ala"):
        out = mod.join_polymarket_to_board(
            [{"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
              "outcomes": '["Yes","No"]', "outcomePrices": '["0.5","0.5"]'}],
            [], selected_date="2026-08-28")
        assert out["refusals"].get("market_type_not_a_game_line") == 1, (slug, out)


def _soccer_unpaired(monkeypatch):
    """Force the alias resolvers to admit nothing, so a match can only come
    from the code under test rather than from a lucky alias hit."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: None)


def _corners_board_row(side="over", line=9.5):
    return {
        "market": "alternate_totals_corners", "side": side, "line": line,
        "sport": "soccer", "selected_date": "2026-08-28",
        "home_team": "Alaves", "away_team": "Villarreal", "event_id": "e1",
    }


def _prop(slug, outcomes='["Over","Under"]', prices='["0.52","0.48"]'):
    return {
        "slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
        "outcomes": outcomes, "outcomePrices": prices,
    }


def test_polymarket_CORNERS_is_admitted_from_its_cor_all_slug_modifier(monkeypatch):
    """`cor-all` is the corners family, and it is 434 rows -- not absent.

    The previous route keyed on `row["question"]`, which is the empty string in
    every persisted slate row, so it could never fire. It was kept as a named
    gap with an explicit instruction to DELETE it if the census found no
    corners family -- 19 sampled PROP slugs had shown only ftts/exact-score/
    btts.

    `prop_modifier_census`, read 2026-08-29T04:14:58Z, found the opposite:

        exact-score 930 | fh-exact-score 496 | cor-all 434 | btts 62 | ...

    Deleting on that 19-slug sample would have removed the route to a market
    the venue lists 434 times. THROUGH THE JOIN, not the helper: every corners
    test before this one called a helper the classifier never reached.
    """
    _soccer_unpaired(monkeypatch)
    out = mod.join_polymarket_to_board(
        [_prop("atc-soccer-ala-vil-2026-08-28-cor-all-9pt5")],
        [_corners_board_row()], selected_date="2026-08-28")
    assert out["refusals"].get("market_type_not_a_game_line") is None, out["refusals"]
    assert out["refusals"].get("board_market_not_a_game_line") is None, out["refusals"]
    assert out["matched"] == 1, out


def test_corners_reaches_the_join_only_when_it_is_KEYED_correctly(monkeypatch):
    """`off != on`. The same fixture with the OLD hook present and the new one
    absent must NOT match -- otherwise the test above passes on a row that
    would have matched anyway, which is how the inert route survived review."""
    _soccer_unpaired(monkeypatch)
    row = _prop("atc-soccer-ala-vil-2026-08-28-9pt5")
    row["question"] = "Total Corners Taken (Reg. Time)"
    out = mod.join_polymarket_to_board(
        [row], [_corners_board_row()], selected_date="2026-08-28")
    assert out["matched"] == 0, out
    assert out["refusals"].get("market_type_not_a_game_line") == 1, out["refusals"]


def test_a_SEGMENT_corners_slug_still_refuses(monkeypatch):
    """A first-half corners market is a different contract on the same fixture.
    It must refuse as a SEGMENT, not be priced as the full 90."""
    _soccer_unpaired(monkeypatch)
    out = mod.join_polymarket_to_board(
        [_prop("atc-soccer-ala-vil-2026-08-28-fh-cor-all-9pt5")],
        [_corners_board_row()], selected_date="2026-08-28")
    assert out["matched"] == 0, out
    assert out["refusals"].get("segment_market_not_full_game") == 1, out["refusals"]


def test_bare_cor_without_all_is_not_admitted(monkeypatch):
    """`all` is the full-match qualifier and is REQUIRED. There is no bare
    `cor` shape in the census, so an unrecognised corners variant must refuse
    rather than be priced as the full game."""
    _soccer_unpaired(monkeypatch)
    out = mod.join_polymarket_to_board(
        [_prop("atc-soccer-ala-vil-2026-08-28-cor-9pt5")],
        [_corners_board_row()], selected_date="2026-08-28")
    assert out["matched"] == 0, out
    assert out["refusals"].get("market_type_not_a_game_line") == 1, out["refusals"]


def test_HALF_btts_is_screened_as_a_segment(monkeypatch):
    """REGRESSION, and it was live in production.

    `_has_segment` matched only a DIGIT-led half (`1h`, `2h`), so the venue's
    soccer tokens `fh`/`sh` fell straight through. The screen runs AFTER the
    market is assigned, and the BTTS branch keys on `"btts" in modifiers` --
    true of `btts`, `fh-btts` and `sh-btts` alike. The census counted 62 of
    each half shape, so 124 half contracts were being admitted as full-game
    BTTS: a segment priced as the full game, which is the $7.08 MLB error.
    """
    _soccer_unpaired(monkeypatch)
    for slug in ("astatc-soccer-ala-vil-2026-08-28-fh-btts",
                 "astatc-soccer-ala-vil-2026-08-28-sh-btts"):
        out = mod.join_polymarket_to_board(
            [_prop(slug, '["Yes","No"]', '["0.55","0.45"]')],
            [{"market": "btts", "side": "yes", "line": None, "sport": "soccer",
              "selected_date": "2026-08-28", "home_team": "Alaves",
              "away_team": "Villarreal", "event_id": "e1"}],
            selected_date="2026-08-28")
        assert out["matched"] == 0, (slug, out)
        assert out["refusals"].get("segment_market_not_full_game") == 1, (slug, out["refusals"])


def test_FULL_GAME_btts_still_matches(monkeypatch):
    """The segment screen must not take the full-game family with it -- the
    control for the test above."""
    _soccer_unpaired(monkeypatch)
    out = mod.join_polymarket_to_board(
        [_prop("astatc-soccer-ala-vil-2026-08-28-btts", '["Yes","No"]', '["0.55","0.45"]')],
        [{"market": "btts", "side": "yes", "line": None, "sport": "soccer",
          "selected_date": "2026-08-28", "home_team": "Alaves",
          "away_team": "Villarreal", "event_id": "e1"}],
        selected_date="2026-08-28")
    assert out["matched"] == 1, out


def test_soccer_board_row_reaches_a_FORWARD_dated_fixture(monkeypatch):
    """The board dates by SLATE, the venue dates by FIXTURE.

    A shortlist row carries no date of its own, so it inherits `selected_date`
    -- today. Polymarket files each slug under the day the fixture is PLAYED,
    and `#545` widened the soccer card build to two matchdays, so most soccer
    rows describe a future fixture.

    Measured 2026-08-29T04:14:58Z: the venue carried 2,038 soccer rows and NONE
    of them on 2026-08-28, while all 118 soccer h2h board rows refused for want
    of a candidate.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [{"slug": "atc-soccer-liv-not-2026-08-29-liv",
          "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
          "outcomes": '["Liverpool","Nottingham Forest"]',
          "outcomePrices": '["0.60","0.40"]'}],
        [{"market": "h2h", "side": "home", "line": None, "sport": "soccer",
          "selected_date": "2026-08-28", "home_team": "Liverpool",
          "away_team": "Nottingham Forest", "event_id": "e1"}],
        selected_date="2026-08-28")
    assert out["matched"] == 1, out
    assert out["forward_date_widened"] == {"soccer|h2h": 1}, out["forward_date_widened"]


def test_MLB_is_NOT_widened_across_dates(monkeypatch):
    """THE SAFETY GATE, and the reason the widening is soccer-only.

    MLB plays the SAME club pair on consecutive days -- a three-game series is
    one fixture on three dates. Widening by date there could price tonight's
    game off tomorrow's market, which is worse than the bug being fixed.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [{"slug": "atc-mlb-az-sf-2026-08-29-az",
          "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
          "outcomes": '["Diamondbacks","Giants"]',
          "outcomePrices": '["0.55","0.45"]'}],
        [{"market": "h2h", "side": "away", "line": None, "sport": "mlb",
          "selected_date": "2026-08-28", "home_team": "San Francisco Giants",
          "away_team": "Arizona Diamondbacks", "event_id": "e1"}],
        selected_date="2026-08-28")
    assert out["matched"] == 0, out
    assert out["forward_date_widened"] == {}, out["forward_date_widened"]


def test_a_SETTLED_past_fixture_is_never_reached(monkeypatch):
    """Forward only. The slate still carries 2026-08-16 rows; matching one
    would price a live board row off a contract that resolved at 0.99."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [{"slug": "atc-soccer-bra-gil-2026-08-16-bra",
          "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
          "outcomes": '["Braga","Gil Vicente"]',
          "outcomePrices": '["0.99","0.01"]'}],
        [{"market": "h2h", "side": "home", "line": None, "sport": "soccer",
          "selected_date": "2026-08-28", "home_team": "Braga",
          "away_team": "Gil Vicente", "event_id": "e1"}],
        selected_date="2026-08-28")
    assert out["matched"] == 0, out
    assert out["forward_date_widened"] == {}, out["forward_date_widened"]


def test_a_fixture_beyond_the_horizon_is_not_reached(monkeypatch):
    """Bounded, because the slate holds futures dated months out."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [{"slug": "atc-soccer-liv-not-2026-11-30-liv",
          "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
          "outcomes": '["Liverpool","Nottingham Forest"]',
          "outcomePrices": '["0.60","0.40"]'}],
        [{"market": "h2h", "side": "home", "line": None, "sport": "soccer",
          "selected_date": "2026-08-28", "home_team": "Liverpool",
          "away_team": "Nottingham Forest", "event_id": "e1"}],
        selected_date="2026-08-28")
    assert out["matched"] == 0, out


def test_a_repeated_club_pair_across_dates_refuses_as_AMBIGUOUS(monkeypatch):
    """A two-legged tie repeats the club pair. The widened rows go through the
    same ambiguity refusal, so it declines rather than guessing a leg."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    markets = [
        {"slug": f"atc-soccer-liv-not-2026-08-{d}-liv",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
         "outcomes": '["Liverpool","Nottingham Forest"]',
         "outcomePrices": '["0.60","0.40"]'}
        for d in ("29", "30")
    ]
    out = mod.join_polymarket_to_board(
        markets,
        [{"market": "h2h", "side": "home", "line": None, "sport": "soccer",
          "selected_date": "2026-08-28", "home_team": "Liverpool",
          "away_team": "Nottingham Forest", "event_id": "e1"}],
        selected_date="2026-08-28")
    assert out["matched"] == 0, out
    assert out["refusals"].get("ambiguous_polymarket_match") == 1, out["refusals"]


def _threeway(subject, price="0.55"):
    """One leg of a soccer 3-way: a Yes/No binary with the subject in the slug.
    Away is `liv`, home is `not` -- `parse_slug` reads `<away>-<home>`."""
    return {"slug": f"atc-epl-liv-not-2026-08-29-{subject}",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME",
            "outcomes": '["Yes","No"]',
            "outcomePrices": f'["{price}","{round(1-float(price),2)}"]'}


def _threeway_board(side):
    return [{"market": "h2h", "side": side, "line": None, "sport": "soccer",
             "selected_date": "2026-08-29", "home_team": "Nottingham Forest",
             "away_team": "Liverpool", "event_id": "e1"}]


def test_soccer_THREE_WAY_picks_the_right_leg(monkeypatch):
    """The production failure, verbatim.

    Polymarket splits a 3-way into three binaries. All three carry the same
    fixture and `line=None`, so all three matched one board row and the
    ambiguity guard refused every one -- `ambiguous_polymarket_match: 186` at
    2026-08-29T05:16:29Z, sample `offered: ['liv-not@None'] x3`.

    Each side must now select exactly one leg and take its YES price.

    USES A DISCRIMINATING RESOLVER, deliberately. This test used to pin
    `teams_match` to always-True and still passed, because the leg was chosen
    POSITIONALLY from `parse_slug` -- the code path that bought Getafe on a bet
    for CA Osasuna on 2026-08-31 and lost $5.96. A resolver that matches every
    team must no longer yield a confident leg, which is pinned separately in
    `test_a_PERMISSIVE_resolver_now_REFUSES_instead_of_picking_positionally`.

    So the stub here answers the way the real resolver does -- `liv` is
    Liverpool and nothing else, `not` is Nottingham Forest and nothing else
    (both verified against the real `teams_match`). The leg selection is then
    testing team identity, which is what actually decides it now.
    """
    import syndicate.features.shared.team_aliases as aliases
    _pairs = {("liv", "liverpool"), ("not", "nottingham forest")}
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: (
        str(a or "").strip().lower(), str(b or "").strip().lower()) in _pairs)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    markets = [_threeway("liv", "0.60"), _threeway("draw", "0.25"),
               _threeway("not", "0.15")]
    for side, expected in (("away", 0.60), ("draw", 0.25), ("home", 0.15)):
        out = mod.join_polymarket_to_board(
            markets, _threeway_board(side), selected_date="2026-08-29")
        assert out["refusals"].get("ambiguous_polymarket_match") is None, (side, out["refusals"])
        assert out["matched"] == 1, (side, out)
        row = out["rows"][0] if out.get("rows") else None
        if row is not None and row.get("venue_probability") is not None:
            assert abs(float(row["venue_probability"]) - expected) < 1e-6, (side, row)


def test_the_draw_leg_is_never_given_to_a_TEAM_side(monkeypatch):
    """A draw contract can only be the draw leg. Handing it to home or away
    would price 'nobody wins' as 'this team wins'."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    for side in ("home", "away"):
        out = mod.join_polymarket_to_board(
            [_threeway("draw")], _threeway_board(side), selected_date="2026-08-29")
        assert out["matched"] == 0, (side, out)


def test_an_UNREADABLE_subject_refuses_rather_than_guessing(monkeypatch):
    """No positional fallback. A leg we cannot name must cost a match, never
    price the wrong team."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: None)
    out = mod.join_polymarket_to_board(
        [_threeway("zzz")], _threeway_board("home"), selected_date="2026-08-29")
    assert out["matched"] == 0, out


def test_BTTS_yes_no_is_NOT_routed_through_the_subject_test(monkeypatch):
    """`btts` is also a Yes/No contract, but its board side NAMES the outcome.
    Routing it through the subject test would break a working family."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [{"slug": "astatc-soccer-ala-vil-2026-08-29-btts",
          "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
          "outcomes": '["Yes","No"]', "outcomePrices": '["0.55","0.45"]'}],
        [{"market": "btts", "side": "yes", "line": None, "sport": "soccer",
          "selected_date": "2026-08-29", "home_team": "Alaves",
          "away_team": "Villarreal", "event_id": "e1"}],
        selected_date="2026-08-29")
    assert out["matched"] == 1, out


def test_CORNERS_rungs_no_longer_refuse_each_other_as_ambiguous(monkeypatch):
    """`alternate_totals_corners` was absent from the line-bearing set, so every
    rung on a fixture matched the same board row and they cancelled out."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    markets = [
        {"slug": f"atc-soccer-ala-vil-2026-08-29-cor-all-{tok}",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
         "outcomes": '["Over","Under"]', "outcomePrices": '["0.52","0.48"]'}
        for tok in ("8pt5", "9pt5", "10pt5")
    ]
    out = mod.join_polymarket_to_board(
        markets,
        [{"market": "alternate_totals_corners", "side": "over", "line": 9.5,
          "sport": "soccer", "selected_date": "2026-08-29",
          "home_team": "Alaves", "away_team": "Villarreal", "event_id": "e1"}],
        selected_date="2026-08-29")
    assert out["refusals"].get("ambiguous_polymarket_match") is None, out["refusals"]
    assert out["matched"] == 1, out


def test_NCAAF_board_row_reaches_a_cfb_slug(monkeypatch):
    """The venue files college football under `cfb`; the board stamps `ncaaf`.

    PROVEN 2026-08-29 against the production slate, not inferred from a
    truncated diagnostic list:

        cfb    h2h 180 | spreads 1265 | totals 749 = 2,194 rows
        ncaaf  nothing, under any market
        tsc-cfb-sacst-emich-2026-08-29-total-52pt5

    That slug is Sacramento State @ Eastern Michigan -- the exact fixture in the
    production refusal sample, same date, filed under `cfb`.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [{"slug": "tsc-cfb-sacst-emich-2026-08-29-total-52pt5",
          "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
          "outcomes": '["Over","Under"]', "outcomePrices": '["0.52","0.48"]'}],
        [{"market": "totals", "side": "over", "line": 52.5, "sport": "ncaaf",
          "selected_date": "2026-08-29", "home_team": "Eastern Michigan Eagles",
          "away_team": "Sacramento State Hornets", "event_id": "e1"}],
        selected_date="2026-08-29")
    assert out["refusals"].get("no_polymarket_market_for_league_date_market") is None, out["refusals"]
    assert out["matched"] == 1, out


def test_an_UNALIASED_league_token_is_still_returned_verbatim(monkeypatch):
    """Only `cfb` is mapped. A token we have not proven must not be bent onto
    some sport because it looks close -- `nba`/`nhl`/`ncaab` read as zero rows
    today because it is AUGUST, not because they are aliased."""
    monkeypatch.setattr(mod, "_VENUE_LEAGUE_ALIASES", {"cfb": "ncaaf"})
    assert mod._effective_league({"league": "cfb"}, None) == "ncaaf"
    for token in ("nfl", "mlb", "wnba", "nba", "nhl"):
        assert mod._effective_league({"league": token}, None) == token


def test_an_aliased_token_can_never_become_a_SOCCER_competition(monkeypatch):
    """`cfb` is not in `_NON_SOCCER_LEAGUE_TOKENS`, so without the alias guard a
    college tri-code that happened to resolve as a club could have proven `cfb`
    a soccer competition."""
    monkeypatch.setattr(
        "syndicate.features.shared.team_aliases.canonical_team",
        lambda sport, n: "club",
    )
    tokens = mod.soccer_competition_tokens(
        [{"slug": "tsc-cfb-sacst-emich-2026-08-29-total-52pt5"}]
    )
    assert "cfb" not in tokens, tokens


def _corners_row(slug, line_field=None, prices='["0.52","0.48"]'):
    row = {"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
           "outcomes": '["Over","Under"]', "outcomePrices": prices}
    if line_field is not None:
        row["line"] = line_field
    return row


def _corners_want(line=13.5):
    return [{"market": "alternate_totals_corners", "side": "over", "line": line,
             "sport": "soccer", "selected_date": "2026-08-29",
             "home_team": "Barcelona", "away_team": "Rayo Vallecano",
             "event_id": "e1"}]


def test_corners_line_comes_from_the_ROW_FIELD_when_the_slug_has_none(monkeypatch):
    """`no_match|soccer|alternate_totals_corners: 37`, measured 16:11:39Z:

        offered ['lev-bet@None', 'lev-bet@None', ...]

    `@None` is the candidate's own line. Corners is line-bearing, so a candidate
    with no line is skipped and every rung was discarded before comparison. The
    slate row keeps a `line` field and this join only ever read the slug.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [_corners_row("atc-soccer-ray-bar-2026-08-29-cor-all", line_field=13.5)],
        _corners_want(13.5), selected_date="2026-08-29")
    assert out["matched"] == 1, out
    assert out["line_source"].get("alternate_totals_corners|row_field") == 1, out["line_source"]


def test_off_is_not_on_for_the_line_fallback(monkeypatch):
    """Same fixture, same slug, NO row line field -- must still refuse. Without
    this the test above would pass on a row that matched for another reason."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [_corners_row("atc-soccer-ray-bar-2026-08-29-cor-all")],
        _corners_want(13.5), selected_date="2026-08-29")
    assert out["matched"] == 0, out
    assert out["line_source"].get("alternate_totals_corners|none") == 1, out["line_source"]
    assert out["line_gap_samples"], "the slug shape must be reported when no line exists"
    assert out["line_gap_samples"][0]["slug"].endswith("cor-all")


def test_the_SLUG_still_wins_when_both_carry_a_line(monkeypatch):
    """Every match working today is slug-derived. The fallback may only ADD
    rows, never re-price an existing one."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [_corners_row("atc-soccer-ray-bar-2026-08-29-cor-all-13pt5", line_field=99.5)],
        _corners_want(13.5), selected_date="2026-08-29")
    assert out["matched"] == 1, out
    assert out["line_source"].get("alternate_totals_corners|slug") == 1, out["line_source"]
    assert out["line_source"].get("alternate_totals_corners|DISAGREE") == 1, out["line_source"]


def test_a_wrong_row_line_still_refuses(monkeypatch):
    """The fallback supplies a line; it does not relax the comparison."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [_corners_row("atc-soccer-ray-bar-2026-08-29-cor-all", line_field=8.5)],
        _corners_want(13.5), selected_date="2026-08-29")
    assert out["matched"] == 0, out


def test_a_side_that_cannot_be_placed_reports_the_OUTCOME_NAMES(monkeypatch):
    """`side_not_an_outcome_of_this_market` went 30 -> 93 the moment the corners
    line fix let 454 rungs reach it. The count alone cannot be acted on: it
    reads identically for "the venue names its outcomes Yes/No" and "we picked
    the wrong market".

    The sample carries the outcome NAMES and PRICES beside the wanted side, so
    the polarity is readable from data rather than guessed from the words.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [{"slug": "atc-soccer-ray-bar-2026-08-29-cor-all",
          "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
          "line": 13.5,
          "outcomes": '["Yes","No"]', "outcomePrices": '["0.52","0.48"]'}],
        [{"market": "alternate_totals_corners", "side": "over", "line": 13.5,
          "sport": "soccer", "selected_date": "2026-08-29",
          "home_team": "Barcelona", "away_team": "Rayo Vallecano",
          "event_id": "e1"}],
        selected_date="2026-08-29")
    assert out["matched"] == 0, out
    assert out["refusals"].get("side_not_an_outcome_of_this_market") == 1, out["refusals"]
    gaps = out["side_gap_samples"]
    assert gaps, "a side that cannot be placed must report what the venue offered"
    g = gaps[0]
    assert g["wanted_side"] == "over"
    assert g["board_line"] == 13.5
    assert [n for n, _ in g["outcomes"]] == ["Yes", "No"], g


def test_an_over_under_market_still_places_its_side(monkeypatch):
    """The control: a market that DOES name over/under must keep matching, so
    the census above is reporting a real gap rather than a broken path."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [{"slug": "atc-soccer-ray-bar-2026-08-29-cor-all",
          "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
          "line": 13.5,
          "outcomes": '["Over","Under"]', "outcomePrices": '["0.52","0.48"]'}],
        [{"market": "alternate_totals_corners", "side": "over", "line": 13.5,
          "sport": "soccer", "selected_date": "2026-08-29",
          "home_team": "Barcelona", "away_team": "Rayo Vallecano",
          "event_id": "e1"}],
        selected_date="2026-08-29")
    assert out["matched"] == 1, out
    assert not out["side_gap_samples"], out["side_gap_samples"]


def _gt_corners(line_tok, line_field, prices='["0.41","0.67"]'):
    return {"slug": f"astatc-mls-sdg-lag-2026-08-29-cor-all-{line_tok}",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
            "line": line_field,
            "outcomes": '["Yes","No"]', "outcomePrices": prices}


def _gt_board(side, line):
    return [{"market": "alternate_totals_corners", "side": side, "line": line,
             "sport": "soccer", "selected_date": "2026-08-29",
             "home_team": "LA Galaxy", "away_team": "San Diego FC", "event_id": "e1"}]


def test_gt_yes_is_OVER_and_no_is_UNDER(monkeypatch):
    """`cor-all-gt10pt5` is "more than 10.5". Yes = over, No = under.

    MEASURED 2026-08-29T18:33:49Z, confirmed two independent ways:
      TOKEN  `gt10pt5` states the direction in the slug.
      PRICE  Yes on the 7.5 line was 0.76 -- over 7.5 corners is the likely side
             of a ~10-corner match; under would be ~0.24.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    for side, expected in (("over", 0.41), ("under", 0.67)):
        out = mod.join_polymarket_to_board(
            [_gt_corners("gt10pt5", 10.5)], _gt_board(side, 10.5),
            selected_date="2026-08-29")
        assert out["matched"] == 1, (side, out)
        assert not out["side_gap_samples"], (side, out["side_gap_samples"])


def test_a_yes_no_market_with_NO_gt_token_still_refuses(monkeypatch):
    """THE GATE IS THE EVIDENCE. A Yes/No contract that does not state its
    direction gets no polarity, so a family that never declared one can never be
    silently assigned the wrong side."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [_gt_corners("", 10.5)], _gt_board("over", 10.5), selected_date="2026-08-29")
    assert out["matched"] == 0, out
    assert out["refusals"].get("side_not_an_outcome_of_this_market") == 1, out["refusals"]


def test_a_gt_threshold_on_a_DIFFERENT_line_refuses(monkeypatch):
    """`gt10pt5` against a board row on 9.5 is a different contract. The rung
    must agree or it is the mismatch this file refuses everywhere else."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [_gt_corners("gt10pt5", 9.5)], _gt_board("over", 9.5), selected_date="2026-08-29")
    assert out["matched"] == 0, out


def test_the_prop_census_covers_EVERY_sport_not_just_soccer(monkeypatch):
    """The census was gated to soccer, so the venue's LARGEST discarded family
    was invisible.

    MEASURED 2026-08-29T19:08:56Z: `SPORTS_MARKET_TYPE_PROP|mlb 5000` discarded
    every cycle, plus ufc 1039 / cfb 556 / nfl 119, and `_note_out_of_scope`
    caps at 14 keys and never reached MLB. A COUNT WITH NO SHAPE -- the exact
    state corners were in while 221 refusals read as "the venue does not list
    them" and it listed 434.

    Keyed by league because the answer differs per sport: soccer props are
    team-level, MLB's are most likely player lines, and one merged vocabulary
    would hide that.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: None)
    markets = [
        {"slug": "astatc-mlb-col-atl-2026-08-29-ks-5pt5",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
         "outcomes": '["Yes","No"]', "outcomePrices": '["0.5","0.5"]'},
        {"slug": "astatc-nfl-chi-ten-2026-08-29-anytime-td",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
         "outcomes": '["Yes","No"]', "outcomePrices": '["0.5","0.5"]'},
        {"slug": "astatc-soccer-ala-vil-2026-08-29-ftts-ala",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
         "outcomes": '["Yes","No"]', "outcomePrices": '["0.5","0.5"]'},
    ]
    out = mod.join_polymarket_to_board(markets, [], selected_date="2026-08-29")
    census = out["prop_modifier_census"]
    assert census.get("mlb|ks") == 1, census
    assert census.get("nfl|anytime-td") == 1, census
    assert census.get("soccer|ftts-ala") == 1, census


def _aligned_board(side, fair):
    return [{"market": "h2h", "side": side, "line": None, "sport": "mlb",
             "selected_date": "2026-08-29", "home_team": "Los Angeles Angels",
             "away_team": "Philadelphia Phillies", "event_id": "e1",
             "quote": {"fair_probability": fair}}]


def _ml(prices):
    return [{"slug": "atc-mlb-phi-laa-2026-08-29-laa",
             "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
             "outcomes": '["Los Angeles Angels","Philadelphia Phillies"]',
             "outcomePrices": prices}]


def test_an_INVERTED_venue_price_is_REFUSED_not_traded(monkeypatch):
    """The user-reported defect: orders going through at non-market prices.

    MEASURED 2026-08-29T19:38:25Z: `soccer|h2h|inverted 13` vs `aligned 10`, and
    'San Jose Earthquakes@Houston Dynamo' side=draw priced at venue_p 0.79
    against book_fair 0.2285 -- a DRAW at 0.79. `venue_p` tracks the complement,
    so the order pays the opposite outcome's price.

    `_classify_alignment` detected this and its docstring said "Never decides".
    It now decides.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    # book says home wins 32%; venue would hand us 0.685 -- the complement.
    out = mod.join_polymarket_to_board(
        _ml('["0.685","0.30"]'), _aligned_board("home", 0.3218),
        selected_date="2026-08-29")
    assert out["matched"] == 0, out
    assert out["refusals"].get("venue_price_inverted_vs_book") == 1, out["refusals"]


def test_an_ALIGNED_price_still_trades(monkeypatch):
    """The control. Refusing inversions must not refuse correct prices."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        _ml('["0.33","0.66"]'), _aligned_board("home", 0.3218),
        selected_date="2026-08-29")
    assert out["matched"] == 1, out
    assert out["refusals"].get("venue_price_inverted_vs_book") is None, out["refusals"]


def test_a_TOO_CLOSE_row_is_not_refused(monkeypatch):
    """A near-coin-flip market cannot separate `fair` from `1 - fair`. Refusing
    on an unreadable signal would silently drop half the slate."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        _ml('["0.52","0.47"]'), _aligned_board("home", 0.49),
        selected_date="2026-08-29")
    assert out["matched"] == 1, out
    assert out["refusals"].get("venue_price_inverted_vs_book") is None, out["refusals"]


def test_a_slug_from_ANOTHER_COMPETITION_cannot_pair_by_elimination(monkeypatch):
    """THE WRONG-GAME BET. User-reported 2026-08-29, order filled $5.20.

        board row   Nice @ Paris FC          (Ligue 1)
        slug        tsc-sea-juv-par-...-2pt5 (Serie A, Juventus-Parma)
        ledger      "totals over 2.5 · Nice @ Paris FC"
        Polymarket  "Over 2.5 total goals -- Juventus FC vs Parma Calcio"

    `par` is a prefix of BOTH "Paris FC" and "Parma", so it named exactly one
    fixture on our board and looked decisive. `juv` then matched neither Nice
    nor Paris FC -- and the elimination branch read "names nothing" as "does not
    contradict". Unknown defaulting permissive, on real money.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: None)
    assert mod._teams_match(
        {"home_team": "Paris FC", "away_team": "Nice"},
        {"league": "sea", "home": "par", "away": "juv", "date": "2026-08-29"},
        "soccer", [("Paris FC", "Nice")],
    ) is False


def test_the_real_fixture_still_pairs(monkeypatch):
    """The control. Refusing the collision must not refuse the true match --
    otherwise the fix is just a coverage cut wearing a safety label."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: False)
    monkeypatch.setattr(aliases, "soccer_fixture_clubs", lambda h, a: None)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: None)
    assert mod._teams_match(
        {"home_team": "Parma", "away_team": "Juventus"},
        {"league": "sea", "home": "par", "away": "juv", "date": "2026-08-29"},
        "soccer", [("Parma", "Juventus")],
    ) is True


def test_the_pair_resolver_MECHANISM_with_an_injected_roster(monkeypatch):
    """The resolver itself, with a MINIMAL roster fed in -- runs in ANY tree.

    This is the half that must never depend on the mirror. It proves the rule
    the wrong-game fix rests on: a pair that resolves inside ONE league is
    authoritative, so a slug naming a different fixture refuses.
    """
    from syndicate.features.shared import team_aliases as ta

    roster = {
        "epl": {"cry": "crystal palace", "mnc": "manchester city"},
        "serie_a": {"juv": "juventus", "par": "parma"},
    }
    monkeypatch.setattr(ta, "_soccer_alias_by_league", lambda: roster)
    ta._soccer_alias_by_league.cache_clear() if hasattr(
        ta._soccer_alias_by_league, "cache_clear") else None

    assert ta.soccer_fixture_clubs("cry", "mnc") == ("crystal palace", "manchester city")
    assert ta.soccer_fixture_clubs("juv", "par") == ("juventus", "parma")
    # A pair spanning two leagues names no single competition.
    assert ta.soccer_fixture_clubs("cry", "juv") is None


@needs_soccer_rosters
def test_mnc_IS_carried_by_the_REAL_pair_resolver():
    """The production half of the trade above -- NO monkeypatching.

    `soccer_fixture_clubs` requires both codes inside ONE league and exactly one
    league to qualify, so when it answers it has named the COMPETITION too. That
    is what refuses `sea-juv-par` against a Ligue 1 board row, and the same call
    is what carries `mnc`:

        soccer_fixture_clubs('cry','mnc') -> ('crystal palace', 'manchester city')
        soccer_fixture_clubs('juv','par') -> ('juventus', 'parma')

    One rule, both outcomes. If this test ever fails, the alias table stopped
    naming the fixture and the coverage claim above is void.
    """
    assert mod._teams_match(
        {"home_team": "Crystal Palace", "away_team": "Manchester City"},
        {"league": "epl", "home": "mnc", "away": "cry", "date": "2026-08-28"},
        "soccer", _EPL_SLATE) is True


def test_the_pair_resolver_REFUSES_a_different_competition():
    """The wrong-game bet, through the real resolver rather than a fixture."""
    assert mod._teams_match(
        {"home_team": "Paris FC", "away_team": "Nice"},
        {"league": "sea", "home": "par", "away": "juv", "date": "2026-08-29"},
        "soccer", [("Paris FC", "Nice")]) is False


def _tot(slug_line_tok, line, prices):
    return {"slug": f"tsc-mls-col-rsl-2026-08-29-{slug_line_tok}",
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
            "outcomes": '["Over","Under"]', "outcomePrices": prices}


def _tot_board(line):
    return {"market": "totals", "side": "over", "line": line, "sport": "soccer",
            "selected_date": "2026-08-29", "home_team": "Real Salt Lake",
            "away_team": "Colorado Rapids", "event_id": "fixture-1"}


def test_a_NON_MONOTONIC_ladder_is_dropped_entirely(monkeypatch):
    """P(over) must not RISE as the line rises: over 3.5 cannot be likelier
    than over 2.5 in the same match. Arithmetic, not a model opinion.

    WHY THIS EXISTS, measured 2026-08-29: soccer totals ran 7:1 OVER while MLB
    stayed balanced, on a day down $42.80. `_classify_alignment` votes only when
    the book is lopsided by >=0.20 from a coin flip, and a 2.5-goal total sits
    ON the coin flip -- every soccer total classified `too_close`, zero aligned,
    zero inverted. A systematic side error had nowhere to show up.

    THE WHOLE LADDER GOES. If two rungs contradict each other the pairing is
    untrustworthy at any rung, and choosing which one is "right" would be the
    guess this file refuses everywhere else.
    """
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    markets = [_tot("2pt5", 2.5, '["0.42","0.58"]'), _tot("3pt5", 3.5, '["0.61","0.39"]')]
    out = mod.join_polymarket_to_board(
        markets, [_tot_board(2.5), _tot_board(3.5)], selected_date="2026-08-29")
    assert out["matched"] == 0, out
    assert out["refusals"].get("ladder_not_monotonic") == 2, out["refusals"]
    assert out["ladder_samples"], out
    assert out["ladder_samples"][0]["side"] == "over"


def test_a_MONOTONIC_ladder_is_kept(monkeypatch):
    """The control. A well-ordered ladder must survive, or the check is just a
    coverage cut wearing a safety label."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    markets = [_tot("2pt5", 2.5, '["0.58","0.42"]'), _tot("3pt5", 3.5, '["0.36","0.64"]')]
    out = mod.join_polymarket_to_board(
        markets, [_tot_board(2.5), _tot_board(3.5)], selected_date="2026-08-29")
    assert out["matched"] == 2, out
    assert out["refusals"].get("ladder_not_monotonic") is None, out["refusals"]
    assert out["ladder_counts"].get("totals|over|monotonic") == 1, out["ladder_counts"]


def test_a_SINGLE_RUNG_fixture_is_not_judged(monkeypatch):
    """One rung has no ordering to violate. Judging it would refuse on no
    evidence."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    out = mod.join_polymarket_to_board(
        [_tot("2pt5", 2.5, '["0.42","0.58"]')], [_tot_board(2.5)],
        selected_date="2026-08-29")
    assert out["matched"] == 1, out
    assert not out["ladder_counts"], out["ladder_counts"]


# ---------------------------------------------------------------------------
# THE WRONG-SIDE LOSS, 2026-08-31. Two live orders bought the opposite team.
# ---------------------------------------------------------------------------

import pytest as _pytest


@_pytest.mark.parametrize("slug,home,away,subject,side,expected,why", [
    # atc-lal-osa-get-2026-08-31-get -- board says "Getafe @ CA Osasuna", we bet
    # HOME (Osasuna). The subject is Getafe, so this contract is NOT ours.
    # SHIPPED BEHAVIOUR WAS True: parse_slug reads <away>-<home>, so it called
    # `get` the home code and matched. Osasuna WON and the bet LOST. -$5.96.
    ("atc-lal-osa-get-2026-08-31-get", "CA Osasuna", "Getafe", "get", "home", False,
     "subject is the AWAY team; betting home must refuse"),
    ("atc-lal-osa-get-2026-08-31-get", "CA Osasuna", "Getafe", "get", "away", True,
     "subject IS the away team; betting away is exactly this contract"),
    # atc-sea-ata-bol-2026-08-31-bol -- "Bologna @ Atalanta BC", we bet HOME.
    ("atc-sea-ata-bol-2026-08-31-bol", "Atalanta BC", "Bologna", "bol", "home", False,
     "subject is Bologna, the away team; betting home must refuse"),
    ("atc-sea-ata-bol-2026-08-31-bol", "Atalanta BC", "Bologna", "bol", "away", True,
     "subject IS Bologna; betting away is this contract"),
])
def test_the_subject_leg_is_decided_by_TEAM_NAMES_not_slug_position(
    slug, home, away, subject, side, expected, why
):
    """Soccer slugs are `<home>-<away>`; MLB's are `<away>-<home>`.

    `parse_slug` documents one shape and applies it to every sport, so the
    positional check answered these backwards and the alias fallback -- which
    gets all four legs right -- never ran. The "definitive NO" guard could not
    catch it either: it reads the SAME inverted parse, so it confirmed the wrong
    answer instead of contradicting it.

    These cases are the two real orders, with the board's own home/away."""
    from syndicate.features.shared.polymarket_board_join import _subject_is_side, parse_slug
    candidate = {"parsed": parse_slug(slug) or {}}
    row = {"home_team": home, "away_team": away}
    assert _subject_is_side(candidate, row, side, "soccer") is expected, why


def test_an_UNRESOLVABLE_subject_refuses_rather_than_falling_back_to_position():
    """No team names on the row means the alias resolver cannot answer, and the
    positional parse is a known-broken input for this sport. Refuse."""
    from syndicate.features.shared.polymarket_board_join import _subject_is_side, parse_slug
    candidate = {"parsed": parse_slug("atc-lal-osa-get-2026-08-31-get") or {}}
    assert _subject_is_side(candidate, {}, "home", "soccer") is False
    assert _subject_is_side(candidate, {"home_team": ""}, "home", "soccer") is False


def test_a_subject_matching_BOTH_teams_refuses():
    """A resolver that cannot separate the two teams has not identified a leg."""
    from syndicate.features.shared.polymarket_board_join import _subject_is_side, parse_slug
    candidate = {"parsed": parse_slug("atc-lal-osa-get-2026-08-31-get") or {}}
    row = {"home_team": "Getafe", "away_team": "Getafe"}
    assert _subject_is_side(candidate, row, "home", "soccer") is False


def test_the_DRAW_leg_still_resolves_in_both_directions():
    """Unchanged by the fix, and it has no team to match on."""
    from syndicate.features.shared.polymarket_board_join import _subject_is_side, parse_slug
    candidate = {"parsed": parse_slug("atc-lal-osa-get-2026-08-31-draw") or {}}
    row = {"home_team": "CA Osasuna", "away_team": "Getafe"}
    assert _subject_is_side(candidate, row, "draw", "soccer") is True
    assert _subject_is_side(candidate, row, "home", "soccer") is False


def test_a_PERMISSIVE_resolver_now_REFUSES_instead_of_picking_positionally(monkeypatch):
    """THE INVERTED REQUIREMENT, and the reason the loss was possible.

    `test_soccer_THREE_WAY_picks_the_right_leg` used to assert that a
    maximally permissive `teams_match` STILL picked the right leg -- which was
    true, and true only because `parse_slug`'s positional `<away>-<home>` made
    the choice. That convention is sport-dependent: MLB really is away-first
    (`aec-mlb-bal-col` reports away_index=1 = Baltimore, and `bal` leads), while
    the two live soccer orders on 2026-08-31 were home-first, and the parser has
    one rule for both.

    A resolver that matches every team has not identified anything. It must now
    cost the match rather than hand back a leg chosen by position."""
    import syndicate.features.shared.team_aliases as aliases
    monkeypatch.setattr(aliases, "teams_match", lambda sport, a, b: True)
    monkeypatch.setattr(aliases, "canonical_team", lambda sport, n: "x")
    for side in ("home", "away"):
        out = mod.join_polymarket_to_board(
            [_threeway("liv", "0.60"), _threeway("not", "0.15")],
            _threeway_board(side), selected_date="2026-08-29")
        assert out["matched"] == 0, (side, out)
