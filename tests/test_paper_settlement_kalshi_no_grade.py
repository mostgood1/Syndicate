"""Kalshi YES/NO game moneylines in the venue-vs-game grade check (lane kalshi-no-grade-check, 2026-11-21).

The in-game entries record the CONTRACT side (`side "no"`), and `_check_venue_grade` used to hand it to
the sport resolver as a club. `canonical_team("nba", "no")` is New Orleans, so NO on
`KXNBAGAME-26NOV20NOPOKC-NOP` (backing Oklahoma City) was graded as New Orleans to win and raised a
false conflict; every other game refused `side_not_a_team_in_this_game`.
"""

from __future__ import annotations

from syndicate.features.shared import paper_settlement as ps
from syndicate.features.shared.game_line_bet import (
    REASON_KALSHI_TICKER_DISAGREES,
    REASON_KALSHI_TICKER_UNREADABLE,
    REASON_SIDE_NOT_A_TEAM,
    game_line_view,
    kalshi_contract_named_side,
)


def _named(ticker, sport="nba", home=None, away=None, market="h2h"):
    return kalshi_contract_named_side(sport=sport, market=market, venue_ticker=ticker, home_team=home, away_team=away)


# ---- the club the ticker names ----------------------------------------------------------------


def test_us_sports_list_away_then_home():
    assert _named("KXNBAGAME-26NOV20NOPOKC-NOP", home="Oklahoma City Thunder", away="New Orleans Pelicans") == ("away", None)
    assert _named("KXNBAGAME-26NOV20NOPOKC-OKC") == ("home", None)
    assert _named("KXNFLGAME-26NOV08CLENO-NO", sport="nfl", home="New Orleans Saints", away="Cleveland Browns") == ("home", None)
    assert _named("KXNHLGAME-26NOV03VGKPIT-PIT", sport="nhl") == ("home", None)


def test_mlb_start_time_after_the_date_is_skipped():
    assert _named("KXMLBGAME-26OCT232000TBMIL-MIL", sport="mlb") == ("home", None)
    assert _named("KXMLBGAME-26OCT232000TBMIL-TB", sport="mlb") == ("away", None)


def test_soccer_lists_home_then_away():
    assert _named("KXSERIEAGAME-26NOV07PARBFC-PAR", sport="soccer") == ("home", None)
    assert _named("KXSERIEAGAME-26NOV07PARBFC-BFC", sport="soccer") == ("away", None)


def test_ticker_contradicting_the_order_names_refuses():
    # The suffix resolves to OKC, which the order lists as AWAY, but the code order puts it home.
    assert _named("KXNBAGAME-26NOV20NOPOKC-OKC", home="New Orleans Pelicans", away="Oklahoma City Thunder") == (
        None, REASON_KALSHI_TICKER_DISAGREES,
    )


def test_unreadable_tickers_refuse():
    assert _named("KXNBAGAME-26NOV20NOPOKC")[1] == REASON_KALSHI_TICKER_UNREADABLE
    assert _named("KXNBAGAME-26NOV20NOPOKC-BOS")[1] == REASON_KALSHI_TICKER_UNREADABLE  # neither code
    assert _named("KXEPLGAME-26NOV21ARSCHE-TIE", sport="soccer")[1] == REASON_KALSHI_TICKER_UNREADABLE
    assert _named("KXNBAGAME-NOTADATE-NOP")[1] == REASON_KALSHI_TICKER_UNREADABLE


def test_contract_sides_are_never_clubs():
    # `canonical_team("nba", "no")` is New Orleans: the root cause of the NOP@OKC inversion.
    for side in ("no", "yes", "NO"):
        view = game_line_view(
            sport="nba", market="h2h", side=side, line=None,
            home_team="Oklahoma City Thunder", away_team="New Orleans Pelicans",
            home_score=106, away_score=100, draw_possible=False,
        )
        assert view == {"unavailable_reason": REASON_SIDE_NOT_A_TEAM}


# ---- through _check_venue_grade ---------------------------------------------------------------


def _resolver(home_score, away_score, draw_possible=False):
    """A final game; grades the ORDER's side through the real translator, as the sport resolvers do."""

    def resolve(order):
        view = game_line_view(
            sport=order.get("sport"), market=order.get("market"), side=order.get("side"), line=order.get("line"),
            home_team=order.get("home_team"), away_team=order.get("away_team"),
            home_score=home_score, away_score=away_score, draw_possible=draw_possible,
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
    assert gc["agrees"] is True and gc["our_outcome"] == "won" and gc["named_club"] == "away"
    assert gc["settled_value"] == -6.0  # New Orleans' margin
    # The order keeps what was bet; money fields untouched.
    assert order["side"] == "no" and order["outcome"] == "won" and order["pnl_dollars"] == 1.3363


def test_a_real_wrong_side_fill_still_conflicts():
    # The venue paid a win on NO-NOP, but New Orleans won: the venue and the game describe different positions.
    order = _nop_okc_order()
    assert ps._check_venue_grade(order, _resolver(home_score=100, away_score=106)) == "conflict"
    assert order["grade_check"]["our_outcome"] == "lost"


def test_yes_contract_side_grades_the_named_club():
    order = _nop_okc_order(side="yes", held_side="yes", outcome="lost")
    assert ps._check_venue_grade(order, _resolver(home_score=106, away_score=100)) == "agrees"


def test_nfl_tie_resolves_no_and_against_yes():
    base = dict(sport="nfl", venue_ticker="KXNFLGAME-26NOV08CLENO-CLE", position_key="ingame:KXNFLGAME-26NOV08CLENO-CLE:no",
                home_team="New Orleans Saints", away_team="Cleveland Browns")
    no = _nop_okc_order(**base, outcome="won")
    assert ps._check_venue_grade(no, _resolver(20, 20)) == "agrees"
    yes = _nop_okc_order(**base, side="yes", held_side="yes", outcome="lost")
    assert ps._check_venue_grade(yes, _resolver(20, 20)) == "agrees"


def test_soccer_draw_resolves_no():
    order = _nop_okc_order(sport="soccer", venue_ticker="KXSERIEAGAME-26NOV07PARBFC-PAR",
                           position_key="ingame:KXSERIEAGAME-26NOV07PARBFC-PAR:no",
                           home_team="Parma", away_team="Bologna", outcome="won")
    assert ps._check_venue_grade(order, _resolver(1, 1, draw_possible=True)) == "agrees"
    assert order["grade_check"]["named_club"] == "home"


def test_ticker_read_from_position_key_when_venue_ticker_absent():
    order = _nop_okc_order(venue_ticker=None)
    assert ps._check_venue_grade(order, _resolver(home_score=106, away_score=100)) == "agrees"


def test_unreadable_ticker_is_a_named_refusal_not_a_conflict():
    order = _nop_okc_order(venue_ticker="garbage", position_key="ingame:garbage:no")
    assert ps._check_venue_grade(order, _resolver(106, 100)) == REASON_KALSHI_TICKER_UNREADABLE
    assert order["grade_check"]["agrees"] is None


def test_team_side_rows_are_untouched():
    # The YES rows record home/away: no ticker reading, no named_club stamp.
    order = _nop_okc_order(side="home", held_side="yes", position_key="ingame:KXNBAGAME-26NOV20NOPOKC-OKC:yes",
                           venue_ticker="KXNBAGAME-26NOV20NOPOKC-OKC")
    assert ps._check_venue_grade(order, _resolver(106, 100)) == "agrees"
    assert "named_club" not in order["grade_check"]


def test_non_kalshi_and_spreads_are_untouched():
    assert ps._kalshi_contract_side_order(_nop_okc_order(venue="polymarket")) == (None, "")
    assert ps._kalshi_contract_side_order(_nop_okc_order(market="spreads")) == (None, "")
