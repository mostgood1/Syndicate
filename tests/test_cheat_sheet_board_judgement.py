"""Cheat-sheet rules v4: the sheet's pick, fee and model number are the Layer 2 board's (todo #861 step 1c, lane
surface-consistency-oversight, user "Yes, do 1c" 2026-11-24).

Measured 2026-11-24 20:11Z on 1,081 pregame board rows: the sheet's fair and net EV were already the board's, but its
own "value" label sat on 12 rows the board refused to suggest (6 stale quotes, 6 one-book fairs).
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared.layer2_row_context import ONE_MODEL_NUMBER_ENV


@pytest.fixture(autouse=True)
def _switch_off(monkeypatch):
    monkeypatch.delenv(ONE_MODEL_NUMBER_ENV, raising=False)


def _prop(**over):
    """An NBA over at bovada +155 on a 0.4048 fair: net EV +3.22%, the board's own number."""
    row = {"kind": "prop", "sport": "nba", "event_id": "e1", "market": "player_rebounds", "segment": "full",
           "side": "over", "line": 9.5, "player_name": "A Player", "game_state": "pregame",
           "quote": {"price": 155, "bookmaker": "bovada", "fair_probability": 0.4048, "fair_method": "shin",
                     "books_quoting": 6, "book_prices": {"bovada": 155, "fanduel": 140}},
           "projection": {"side": "over", "model_prob_over": 0.4410, "projected": 10.6},
           "ev_pct": 3.22, "score_v2": {"ev_net_pct": 3.22, "fee_basis": "none", "fee_per_contract": 0.0},
           "suggested": True, "suggested_reasons": [],
           "model_probability_cal": 0.4500, "model_edge_pct": 4.52, "calibration_method": "identity"}
    row.update(over)
    return row


def _game(**over):
    row = {"kind": "game", "sport": "ncaab", "event_id": "g1", "market": "spreads", "segment": "full", "side": "home",
           "line": -6.5, "game_state": "pregame", "home_team": "Home U", "away_team": "Away St",
           "quote": {"price": 107, "bookmaker": "betrivers", "fair_probability": 0.4977, "fair_method": "shin",
                     "books_quoting": 5, "book_prices": {"betrivers": 107, "fanduel": -105}},
           "projection": {"side": "home", "model_prob_over": 0.5300},
           "ev_pct": 3.03, "score_v2": {"ev_net_pct": 3.03, "fee_basis": "none", "fee_per_contract": 0.0},
           "suggested": True, "suggested_reasons": [],
           "model_probability_cal": 0.5600, "model_edge_pct": 6.23, "calibration_method": "identity"}
    row.update(over)
    return row


def test_rules_version_carries_v4():
    assert cs.SECTION_RULES >= 4    # v4's board verdict holds in every later version (v5 2026-11-27)


# ---------------------------------------------------------------- the pick is the board's


def test_a_suggested_row_is_value():
    check = cs.price_check(_prop(), None)
    assert check.verdict == "value"
    assert check.ev_market == pytest.approx(3.22, abs=0.01)


def test_a_one_book_fair_the_board_refused_is_not_value_and_says_why():
    """Before v4 this row read "value" at +3.22%: 6 of the 12 measured rows."""
    row = _prop(suggested=False, suggested_reasons=["single_book_fair"])
    check = cs.price_check(row, None)
    assert check.verdict == "neutral"
    assert check.ev_market == pytest.approx(3.22, abs=0.01)    # the EV itself does not move
    assert any("the board does not suggest it: its fair price comes from one book only" in r for r in check.reasons)


def test_a_stale_quote_the_board_refused_reads_check_price():
    """The other 6 of the 12."""
    row = _prop(suggested=False, suggested_reasons=["suspect_stale_quote"])
    check = cs.price_check(row, None)
    assert check.verdict == "suspect_price"
    assert any("the board flags the quote as stale" in r for r in check.reasons)


def test_the_board_suggesting_the_other_side_is_not_value_here():
    row = _prop(suggested=False, suggested_reasons=["other_side_suggested"])
    assert cs.price_check(row, None).verdict == "neutral"


def test_a_refused_row_with_a_streak_still_reads_its_streak():
    row = _prop(suggested=False, suggested_reasons=["single_book_fair"])
    check = cs.price_check(row, [12, 11, 10, 13, 12, 8, 9, 10, 11, 12])
    assert check.verdict in ("streak_with_room", "streak_priced_in")
    assert any("the board does not suggest it" in r for r in check.reasons)


def test_a_row_the_board_never_judged_keeps_the_price_rule():
    """`build_cheat_sheets.quote_rows` rebuilds started games from the quote logs: no board judgement, no projection."""
    row = _prop(rebuilt=True, projection={}, score_v2=None)
    row.pop("suggested")
    row.pop("suggested_reasons")
    check = cs.price_check(row, None)
    assert check.verdict == "value"
    assert check.p_model is None


def test_one_sided_and_suspect_still_win_over_the_board():
    one = _prop(quote={**_prop()["quote"], "fair_method": "book_margin_model"})
    assert cs.price_check(one, None).verdict == "one_sided_fair"
    big = _prop(quote={**_prop()["quote"], "price": 300})       # EV far above SUSPECT_EV_PCT
    assert cs.price_check(big, None).verdict == "suspect_price"


# ---------------------------------------------------------------- the fee is the board's


def test_the_fee_is_the_boards_not_a_second_lookup(monkeypatch):
    def _no_lookup(*a, **k):
        raise AssertionError("the sheet looked the fee up itself")

    monkeypatch.setattr(cs, "taker_fee", _no_lookup)
    row = _prop(quote={**_prop()["quote"], "bookmaker": "kalshi", "price": -144, "fair_probability": 0.6100},
                score_v2={"ev_net_pct": 2.07, "fee_basis": "kalshi_assumed_full_rate", "fee_per_contract": 0.014115})
    check = cs.price_check(row, None)
    q = 1 / cs.decimal_odds(-144)
    assert check.ev_market == pytest.approx(round(100 * (0.61 - q - 0.014115) / (q + 0.014115), 2))
    assert any("kalshi fee (1.4c a contract)" in r for r in check.reasons)


def test_a_row_without_the_boards_fee_falls_back_to_the_lookup(monkeypatch):
    calls = []
    monkeypatch.setattr(cs, "taker_fee", lambda row, book, price: calls.append(book) or 0.0)
    cs.price_check(_prop(score_v2=None), None)
    assert calls == ["bovada"]


# ---------------------------------------------------------------- the model number is the card's


def test_prop_model_number_is_the_cards_and_follows_the_one_number_switch(monkeypatch):
    off = cs.price_check(_prop(), None).p_model
    assert off == pytest.approx(0.4410)                         # the card's Win% today: the served projection
    monkeypatch.setenv(ONE_MODEL_NUMBER_ENV, "on")
    on = cs.price_check(_prop(), None).p_model
    assert on == pytest.approx(0.4500) and on != off            # reachability: the sheet moves with the card


def test_game_line_model_number_is_the_cards_not_the_calibrated_field(monkeypatch):
    """Before v4 the sheet showed `model_probability_cal` (0.56) beside a card showing 0.53."""
    assert cs.game_line_check(_game())["p_model"] == pytest.approx(0.5300)
    monkeypatch.setenv(ONE_MODEL_NUMBER_ENV, "on")
    assert cs.game_line_check(_game())["p_model"] == pytest.approx(0.5600)


def test_a_blank_card_keeps_the_projections_own_number():
    """Measured 11-24: the card shows no Win% on 104 one-sided "yes" props (NFL anytime TD, soccer scorers) because
    `_model_prob_for_side` cannot place "yes" against a projection framed "over". The sheet keeps its number there."""
    row = _prop(market="Anytime TD", side="yes", line=None,
                projection={"side": "over", "model_prob_over": 0.2313, "basis": "nfl_prop_model_probability"},
                quote={**_prop()["quote"], "fair_method": "book_margin_model"})
    assert cs.board_model_number(row) is None
    assert cs.price_check(row, None).p_model == pytest.approx(0.2313)


def test_a_game_line_with_a_blank_card_keeps_its_calibrated_number():
    row = _game(projection={"projected": 4.1, "side": "Home U"})       # no model_prob_over: the card is blank
    assert cs.board_model_number(row) is None
    assert cs.game_line_check(row)["p_model"] == pytest.approx(0.5600)


# ---------------------------------------------------------------- game lines


def test_game_line_pick_is_the_boards():
    assert cs.game_line_check(_game())["verdict"] == "value"
    refused = cs.game_line_check(_game(suggested=False, suggested_reasons=["single_book_fair"]))
    assert refused["verdict"] == "neutral"
    assert any("its fair price comes from one book only" in r for r in refused["reasons"])
    stale = cs.game_line_check(_game(suggested=False, suggested_reasons=["suspect_stale_quote"]))
    assert stale["verdict"] == "suspect_price"


def test_game_line_sections_feature_only_the_boards_picks():
    lines = [{"market": "spreads", "side": "home", "check": cs.game_line_check(_game())},
             {"market": "spreads", "side": "away",
              "check": cs.game_line_check(_game(side="away", suggested=False, suggested_reasons=["single_book_fair"]))}]
    assert cs.game_line_sections(lines)["value"] == [0]


def test_prop_value_section_features_only_the_boards_picks():
    picked = {**_prop(), "check": cs.price_check(_prop(), None).as_dict(), "projected": 10.6, "player": "A Player"}
    refused_row = _prop(player_name="B Player", suggested=False, suggested_reasons=["single_book_fair"])
    refused = {**refused_row, "check": cs.price_check(refused_row, None).as_dict(), "projected": 10.6,
               "player": "B Player"}
    secs = cs.sections([picked, refused], rules=cs.SECTION_RULES)
    assert secs["value"] == [0]
