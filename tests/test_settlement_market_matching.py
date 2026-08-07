"""#247: settlement could never agree with the board on what market a bet was in.

Production, 2026-08-06: 4,560 of 8,276 ledger records were `no_key_match`. The
cause was not the identity keys -- those overlapped fine -- it was the market
gate. The ledger carries the board's display label ("pitcher outs"); the graded
row carries the sport's stat label ("outs"); `_market_family` keyword-sniffed
both and got "props" and "outs". Never equal, so the gate that exists to prevent
WRONG matches blocked every RIGHT one.
"""

from __future__ import annotations

from syndicate.features.shared.evaluation_settlement import _markets_compatible, match_graded_row
from syndicate.features.shared.market_keys import canonical_market_key


def test_role_prefixed_display_labels_canonicalise_like_the_bare_stat():
    # The board says "Hitter Hits"; the grader and the odds feed say
    # "batter_hits". Before #247 the first returned None, so the two sides of
    # settlement could not agree a market existed at all.
    assert canonical_market_key("mlb", "Hitter Hits") == canonical_market_key("mlb", "batter_hits")
    assert canonical_market_key("mlb", "Hitter Total Bases") == canonical_market_key("mlb", "batter_total_bases")
    assert canonical_market_key("mlb", "Pitcher Outs") == canonical_market_key("mlb", "outs")


def test_role_strip_does_not_break_the_keys_that_already_worked():
    assert canonical_market_key("mlb", "batter_home_runs") == "batter_home_runs"
    assert canonical_market_key("mlb", "batter_hits_runs_rbis") == "batter_hits_runs_rbis"
    assert canonical_market_key("mlb", "pitcher_strikeouts") == "strikeouts"
    assert canonical_market_key("mlb", "moneyline") == canonical_market_key("mlb", "h2h")


def test_the_exact_production_pair_now_matches():
    # From the live unmatched sample: record market "pitcher outs" against a
    # graded row whose market is "outs".
    assert _markets_compatible("pitcher outs", "outs", "mlb") is True


def test_a_player_prop_still_cannot_match_a_game_total():
    # The dangerous half of the old behaviour: _market_family mapped
    # "batter_total_bases" to "totals", the same family as a game total, so an
    # overlapping key set would have matched a prop to the wrong market.
    assert _markets_compatible("Hitter Total Bases", "total", "mlb") is False
    assert _markets_compatible("batter_total_bases", "moneyline", "mlb") is False


def test_different_props_do_not_match_each_other():
    assert _markets_compatible("pitcher outs", "strikeouts", "mlb") is False
    assert _markets_compatible("Hitter Hits", "batter_rbis", "mlb") is False


def test_unknown_markets_do_not_veto_an_otherwise_good_row():
    # An unrecognised label must not silently block a row every other signal
    # says is right -- that failure mode is what this whole item is about.
    assert _markets_compatible("", "", "mlb") is True
    assert _markets_compatible("some_new_market_we_have_no_label_for", "", "mlb") is True


def test_match_graded_row_finds_the_prop_it_previously_skipped():
    """End to end, using the shape of the real unmatched sample."""
    record = {
        "sport": "mlb",
        "recommendation": {
            "sport": "mlb",
            "market": "pitcher outs",
            "selection": "over drew anderson",
            "player": "Drew Anderson",
            "team": "DET",
            "game_id": "823106",
            "line": 8.5,
        },
    }
    rows = [
        {"sport": "mlb", "market": "moneyline", "selection": "DET", "home": "DET", "away": "CLE", "result": "win"},
        {"sport": "mlb", "market": "outs", "selection": "over", "player": "Drew Anderson",
         "team": "DET", "line": 8.5, "actual": 9, "result": "win"},
    ]
    matched = match_graded_row(record, rows)
    assert matched is not None
    assert matched["market"] == "outs"
    assert matched["result"] == "win"


def test_match_graded_row_still_respects_the_line():
    record = {
        "sport": "mlb",
        "recommendation": {
            "sport": "mlb", "market": "pitcher outs", "player": "Drew Anderson", "line": 8.5,
        },
    }
    rows = [{"sport": "mlb", "market": "outs", "selection": "over", "player": "Drew Anderson",
             "line": 5.5, "actual": 9, "result": "win"}]
    assert match_graded_row(record, rows) is None
