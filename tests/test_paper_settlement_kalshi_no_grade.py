"""Kalshi YES/NO game moneylines in the venue-vs-game grade check (lane kalshi-no-grade-check, 2026-11-21).

The in-game entries record the CONTRACT side (`side "no"`), and `_check_venue_grade` used to hand it to
the sport resolver as a club. `canonical_team("nba", "no")` is New Orleans, so NO on
`KXNBAGAME-26NOV20NOPOKC-NOP` (backing Oklahoma City) was graded as New Orleans to win and raised a
false conflict; every other game refused `side_not_a_team_in_this_game`.
"""

from __future__ import annotations

from syndicate.features.shared import paper_settlement as ps
from syndicate.features.shared.game_line_bet import (
    REASON_KALSHI_NO_THREE_WAY,
    REASON_KALSHI_TICKER_DISAGREES,
    REASON_KALSHI_TICKER_UNREADABLE,
    game_line_view,
    kalshi_contract_backed_side,
)


def _side(ticker, contract="no", sport="nba", home=None, away=None, market="h2h", draw=False):
    return kalshi_contract_backed_side(
        sport=sport, market=market, contract_side=contract, venue_ticker=ticker,
        home_team=home, away_team=away, draw_possible=draw,
    )


# ---- the pure translation -------------------------------------------------------------------


def test_no_on_away_club_backs_home():
    # NOPOKC: New Orleans away, Oklahoma City home. NO on NOP = OKC.
    assert _side("KXNBAGAME-26NOV20NOPOKC-NOP", home="Oklahoma City Thunder", away="New Orleans Pelicans") == ("home", None)


def test_no_on_home_club_backs_away():
    assert _side("KXNFLGAME-26NOV08CLENO-NO", sport="nfl", home="New Orleans Saints", away="Cleveland Browns") == ("away", None)


def test_yes_backs_the_named_club():
    assert _side("KXNBAGAME-26NOV20NOPOKC-OKC", contract="yes") == ("home", None)
    assert _side("KXNBAGAME-26NOV20NOPOKC-NOP", contract="yes") == ("away", None)


def test_positional_reading_works_without_names():
    assert _side("KXNHLGAME-26NOV03VGKPIT-PIT", sport="nhl") == ("away", None)


def test_ticker_contradicting_the_order_names_refuses():
    # The suffix resolves to OKC, which the order lists as AWAY, but the segment puts it last (home).
    assert _side("KXNBAGAME-26NOV20NOPOKC-OKC", home="New Orleans Pelicans", away="Oklahoma City Thunder") == (
        None, REASON_KALSHI_TICKER_DISAGREES,
    )


def test_no_on_a_three_way_market_refuses():
    assert _side("KXEPLGAME-26NOV21ARSCHE-ARS", sport="soccer", draw=True) == (None, REASON_KALSHI_NO_THREE_WAY)


def test_unreadable_tickers_refuse():
    assert _side("KXNBAGAME-26NOV20NOPOKC")[1] == REASON_KALSHI_TICKER_UNREADABLE
    assert _side("KXNBAGAME-26NOV20NOPOKC-BOS")[1] == REASON_KALSHI_TICKER_UNREADABLE
    assert _side("KXEPLGAME-26NOV21ARSCHE-TIE", sport="soccer", contract="yes")[1] == REASON_KALSHI_TICKER_UNREADABLE


# ---- through _check_venue_grade ---------------------------------------------------------------


def _resolver(home_score, away_score):
    """A final game; grades the ORDER's side through the real translator, as the sport resolvers do."""

    def resolve(order):
        view = game_line_view(
            sport=order.get("sport"), market=order.get("market"), side=order.get("side"), line=order.get("line"),
            home_team=order.get("home_team"), away_team=order.get("away_team"),
            home_score=home_score, away_score=away_score, draw_possible=False,
        )
        if view.get("unavailable_reason"):
            return view
        return {**view, "is_final": True, "started": True}

    return resolve


def _nop_okc_order(**over):
    # The 11-21 ledger row, trimmed to what the check reads.
    order = {
        "venue": "kalshi", "sport": "nba", "market": "h2h", "side": "no", "held_side": "no", "line": None,
        "position_key": "ingame:KXNBAGAME-26NOV20NOPOKC-NOP:no", "venue_ticker": "KXNBAGAME-26NOV20NOPOKC-NOP",
        "home_team": "Oklahoma City Thunder", "away_team": "New Orleans Pelicans",
        "status": "filled", "fill_price": 0.65, "fill_stake_dollars": 2.6, "contracts": 4,
        "outcome": "won", "pnl_dollars": 1.3363, "settled_by": "venue",
    }
    order.update(over)
    return order


def test_the_inverted_nop_okc_row_now_agrees():
    order = _nop_okc_order()
    assert ps._check_venue_grade(order, _resolver(home_score=106, away_score=100)) == "agrees"
    gc = order["grade_check"]
    assert gc["agrees"] is True and gc["our_outcome"] == "won" and gc["side_from_ticker"] == "home"
    # The order keeps what was bet; money fields untouched.
    assert order["side"] == "no" and order["outcome"] == "won" and order["pnl_dollars"] == 1.3363


def test_a_real_wrong_side_fill_still_conflicts():
    # The venue paid a win on NO-NOP, but New Orleans won: the venue and the game describe different positions.
    order = _nop_okc_order()
    assert ps._check_venue_grade(order, _resolver(home_score=100, away_score=106)) == "conflict"
    assert order["grade_check"]["our_outcome"] == "lost"


def test_ticker_read_from_position_key_when_venue_ticker_absent():
    order = _nop_okc_order(venue_ticker=None)
    assert ps._check_venue_grade(order, _resolver(home_score=106, away_score=100)) == "agrees"


def test_unreadable_ticker_is_a_named_refusal_not_a_conflict():
    order = _nop_okc_order(venue_ticker="garbage", position_key="ingame:garbage:no")
    assert ps._check_venue_grade(order, _resolver(106, 100)) == REASON_KALSHI_TICKER_UNREADABLE
    assert order["grade_check"]["agrees"] is None


def test_team_side_rows_are_untouched():
    # The YES rows record home/away: no ticker reading, no side_from_ticker stamp.
    order = _nop_okc_order(side="home", held_side="yes", position_key="ingame:KXNBAGAME-26NOV20NOPOKC-OKC:yes",
                           venue_ticker="KXNBAGAME-26NOV20NOPOKC-OKC")
    assert ps._check_venue_grade(order, _resolver(106, 100)) == "agrees"
    assert "side_from_ticker" not in order["grade_check"]


def test_non_kalshi_and_spreads_are_untouched():
    assert ps._kalshi_contract_side_order(_nop_okc_order(venue="polymarket")) == (None, "")
    assert ps._kalshi_contract_side_order(_nop_okc_order(market="spreads")) == (None, "")
