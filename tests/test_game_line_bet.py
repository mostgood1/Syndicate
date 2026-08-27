"""Game lines, translated into the vocabulary the grader already speaks.

The defect these exist for, measured 2026-08-24 and printed every cycle:

    UNMAPPED_MARKETS date=2026-08-23
      {'spreads': 41, 'h2h': 31, 'h2h_3_way': 6, 'spreads_alt': 2}

80 of 171 orders on one slate, permanently ungradeable.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.bet_status import (
    STATUS_LOST,
    STATUS_LIVE_TIED,
    STATUS_WON,
    resolve_bet_status,
)
from syndicate.features.shared.game_line_bet import (
    REASON_NO_SCORES,
    REASON_NO_SPREAD_LINE,
    REASON_SIDE_NOT_A_TEAM,
    REASON_HOME_AWAY_DISAGREE,
    REASON_UNKNOWN_GAME_MARKET,
    game_line_view,
    is_game_line_market,
)

# A real MLB matchup, so the alias resolution is exercised rather than mocked.
HOME = "Miami Marlins"
AWAY = "Boston Red Sox"


def _view(**overrides):
    kwargs = {
        "sport": "mlb", "market": "h2h", "side": HOME, "line": None,
        "home_team": HOME, "away_team": AWAY,
        "home_score": 5, "away_score": 3, "draw_possible": False,
    }
    kwargs.update(overrides)
    return game_line_view(**kwargs)


def _grade(view, *, is_final=True):
    """Run a translated view through the REAL grader, never a reimplementation.

    Every assertion below is about the end-to-end verdict for that reason: a
    translation that is self-consistent and disagrees with the grader is the
    failure mode worth catching, and testing the view's fields alone would
    miss it entirely.
    """
    return resolve_bet_status(
        market="spreads",  # non-monotone: nothing decides before final
        side=view["side"],
        line=view["line"],
        current_value=view["current_value"],
        is_final=is_final,
    )


# --------------------------------------------------------------------------
# The sign convention. Inverting it grades every favourite as an underdog,
# silently, with plausible numbers.
# --------------------------------------------------------------------------


def test_a_favourite_covering_its_spread_wins():
    """Miami -1.5, Miami win by 2. Covered."""
    view = _view(market="spreads", side=HOME, line=-1.5, home_score=5, away_score=3)
    assert view["line"] == 1.5
    assert view["current_value"] == 2
    assert _grade(view)["status"] == STATUS_WON


def test_a_favourite_winning_by_less_than_its_spread_loses():
    """Miami -1.5, Miami win by 1. Won the game, lost the bet -- the case that
    makes a spread different from a moneyline, and the one an inverted sign
    would report backwards while looking entirely reasonable."""
    view = _view(market="spreads", side=HOME, line=-1.5, home_score=4, away_score=3)
    assert _grade(view)["status"] == STATUS_LOST


def test_an_underdog_losing_by_less_than_its_spread_wins():
    """Boston +1.5, Boston lose by 1. The mirror image, and the reason both
    directions are asserted: a sign error passes one of these on its own."""
    view = _view(market="spreads", side=AWAY, line=1.5, home_score=4, away_score=3)
    assert view["line"] == -1.5
    assert view["current_value"] == -1
    assert _grade(view)["status"] == STATUS_WON


def test_an_underdog_losing_by_more_than_its_spread_loses():
    view = _view(market="spreads", side=AWAY, line=1.5, home_score=6, away_score=3)
    assert _grade(view)["status"] == STATUS_LOST


def test_a_whole_number_spread_landing_exactly_is_a_PUSH():
    """Miami -2, Miami win by 2. The stake comes back, and this is the one
    place the grader's equality branch is REACHABLE and correct."""
    view = _view(market="spreads", side=HOME, line=-2.0, home_score=5, away_score=3)
    graded = _grade(view)
    assert graded["decided"] is True
    assert graded["status"] == STATUS_LIVE_TIED


def test_spreads_alt_is_the_same_market_by_another_name():
    view = _view(market="spreads_alt", side=HOME, line=-1.5, home_score=5, away_score=3)
    assert _grade(view)["status"] == STATUS_WON


# --------------------------------------------------------------------------
# Moneylines
# --------------------------------------------------------------------------


def test_a_two_way_moneyline_grades_off_the_winner():
    assert _grade(_view(side=HOME, home_score=5, away_score=3))["status"] == STATUS_WON
    assert _grade(_view(side=AWAY, home_score=5, away_score=3))["status"] == STATUS_LOST


def test_a_moneyline_needs_no_line_on_the_order():
    """`line=None` is CORRECT for a moneyline and used to refuse with
    `no_line`. That refusal was the grader being asked a question in the wrong
    language, not the order being incomplete."""
    view = _view(side=HOME, line=None)
    assert view.get("unavailable_reason") is None
    assert view["line"] == 0.0


def test_a_level_score_is_a_push_only_where_a_draw_cannot_HAPPEN():
    """Two-way: a tie returns the stake. Baseball does not draw, so this is a
    safety property rather than a live case -- and the safe direction is
    returning the stake, not silently awarding it to the favourite."""
    graded = _grade(_view(side=HOME, home_score=3, away_score=3))
    assert graded["status"] == STATUS_LIVE_TIED


# --------------------------------------------------------------------------
# Three-way, and the half-point that makes it work
# --------------------------------------------------------------------------


def test_a_draw_LOSES_a_three_way_team_bet_rather_than_pushing():
    """The whole reason for the half-point. On a three-way market a level score
    is a LOSS for both teams; grading it as a push would return a stake that
    was lost, on every drawn match, forever."""
    view = _view(market="h2h", side=HOME, home_score=1, away_score=1,
                 draw_possible=True)
    assert view["line"] == 0.5
    graded = _grade(view)
    assert graded["decided"] is True
    assert graded["status"] == STATUS_LOST


def test_a_draw_bet_wins_on_a_level_score_and_nothing_else():
    view = _view(market="h2h", side="Draw", home_score=1, away_score=1,
                 draw_possible=True)
    assert view["current_value"] == 0
    assert view["side"] == "under" and view["line"] == 0.5
    assert _grade(view)["status"] == STATUS_WON

    lost = _view(market="h2h", side="Draw", home_score=2, away_score=1,
                 draw_possible=True)
    assert _grade(lost)["status"] == STATUS_LOST


def test_the_push_branch_is_unreachable_on_a_three_way_market():
    """Scores are whole numbers and the line is a half, so equality cannot
    arise. The impossible case is impossible by construction rather than
    merely unhandled."""
    for home in range(0, 6):
        for away in range(0, 6):
            for side in (HOME, AWAY, "Draw"):
                view = _view(market="h2h", side=side, home_score=home,
                             away_score=away, draw_possible=True)
                assert _grade(view)["status"] in {STATUS_WON, STATUS_LOST}


def test_h2h_3_way_is_three_way_even_where_the_sport_cannot_draw():
    """The market name can only ADD three-way-ness, never remove it."""
    view = _view(market="h2h_3_way", side=HOME, home_score=1, away_score=1,
                 draw_possible=False)
    assert view["line"] == 0.5
    assert _grade(view)["status"] == STATUS_LOST


def test_h2h_is_three_way_in_a_sport_that_draws():
    """PRODUCTION SAYS SO. Soccer's own odds history carries
    `market=h2h|side=Draw` (Levante v Real Betis, fanduel) -- so `h2h` is
    three-way in soccer and two-way in baseball, and keying the behaviour on
    the market NAME would return a lost stake on every drawn match."""
    two_way = _view(market="h2h", side=HOME, home_score=1, away_score=1,
                    draw_possible=False)
    three_way = _view(market="h2h", side=HOME, home_score=1, away_score=1,
                      draw_possible=True)
    assert _grade(two_way)["status"] == STATUS_LIVE_TIED
    assert _grade(three_way)["status"] == STATUS_LOST


def test_a_draw_side_on_a_sport_that_cannot_draw_is_refused():
    view = _view(market="h2h", side="Draw", draw_possible=False)
    assert view["unavailable_reason"] == REASON_SIDE_NOT_A_TEAM


# --------------------------------------------------------------------------
# Refusals -- each one names a different next step
# --------------------------------------------------------------------------


def test_a_side_naming_a_team_not_in_this_game_is_refused():
    """Refused rather than defaulted to either team: picking one produces a
    confident verdict on the wrong bet."""
    view = _view(side="New York Yankees")
    assert view["unavailable_reason"] == REASON_SIDE_NOT_A_TEAM


def test_an_unreadable_side_is_refused():
    assert _view(side="")["unavailable_reason"] == REASON_SIDE_NOT_A_TEAM


def test_a_half_known_score_is_not_a_score():
    """A missing away total read as zero is a shutout that did not happen."""
    assert _view(away_score=None)["unavailable_reason"] == REASON_NO_SCORES
    assert _view(home_score=None)["unavailable_reason"] == REASON_NO_SCORES


def test_a_spread_with_no_number_is_named_separately_from_a_moneyline():
    """A moneyline correctly has no line; a spread without one is broken.
    They need opposite responses, so they are counted apart."""
    assert _view(market="spreads", line=None)["unavailable_reason"] == REASON_NO_SPREAD_LINE
    assert _view(market="h2h", line=None).get("unavailable_reason") is None


def test_a_player_prop_is_not_a_game_line():
    assert not is_game_line_market("mlb", "batter_hits")
    assert not is_game_line_market("mlb", "strikeouts")
    # `totals` is a scoreboard bet but needs no team resolution at all, so it
    # stays with each sport's own resolver rather than coming through here.
    assert not is_game_line_market("mlb", "totals")
    assert _view(market="batter_hits")["unavailable_reason"] == REASON_UNKNOWN_GAME_MARKET


def test_the_markets_production_actually_refused_are_all_covered():
    """The four names off `UNMAPPED_MARKETS`, checked as a set rather than
    individually -- the point is coverage of the measured list, not that any
    one of them parses."""
    for market in ("spreads", "h2h", "h2h_3_way", "spreads_alt"):
        assert is_game_line_market("mlb", market), market


# --------------------------------------------------------------------------
# Nothing decides before the final whistle
# --------------------------------------------------------------------------


def test_a_lead_decides_nothing_before_the_game_ends():
    """Game lines are non-monotone: the value swings. A four-run lead in the
    second inning is not a won bet, and `resolve_bet_status` already refuses to
    call one -- this asserts the translation does not accidentally make a game
    line look monotone."""
    view = _view(market="spreads", side=HOME, line=-1.5, home_score=8, away_score=0)
    graded = _grade(view, is_final=False)
    assert graded["decided"] is False
    assert graded["status"] not in {STATUS_WON, STATUS_LOST}


@pytest.mark.parametrize("market", ["spreads", "spreads_alt", "h2h", "h2h_3_way"])
def test_no_game_line_market_is_monotone(market):
    from syndicate.features.shared.bet_status import is_monotone_market

    assert not is_monotone_market(market)


# --------------------------------------------------------------------------
# Positional sides -- the vocabulary the board actually writes
# --------------------------------------------------------------------------
#
# MEASURED 2026-08-24T16:36Z, one tick after game-line grading shipped:
#
#   before  ungraded={'unmapped_market': 80, ...}
#   after   ungraded={'side_not_a_team_in_this_game': 77, ...}
#
# The markets reached the translator and it could not read their sides. It had
# been written from the SOCCER odds history (`side=Levante`, `side=Draw`), and
# the board writes `home -1.5` -- `clv_opening_ledger` documents the key that
# way, and `layer2_board` and `basketball_market_board` both emit it.


def test_a_positional_side_resolves():
    """`home`/`away`, not a club name. 77 of 80 orders on the first live slate."""
    view = _view(market="spreads", side="home", line=-1.5, home_score=5, away_score=3)
    assert view.get("unavailable_reason") is None
    assert view["current_value"] == 2
    assert _grade(view)["status"] == STATUS_WON

    away = _view(market="spreads", side="away", line=1.5, home_score=5, away_score=3)
    assert away["current_value"] == -2
    assert _grade(away)["status"] == STATUS_LOST


def test_a_positional_moneyline_resolves():
    assert _grade(_view(side="home", home_score=5, away_score=3))["status"] == STATUS_WON
    assert _grade(_view(side="away", home_score=5, away_score=3))["status"] == STATUS_LOST


def test_both_vocabularies_agree_on_the_same_bet():
    """The whole point: `home` and the home club's NAME are the same wager, and
    must grade identically. If these ever diverge, one of the two paths is
    reading a different team."""
    by_name = _view(market="spreads", side=HOME, line=-1.5, home_score=5, away_score=3)
    by_slot = _view(market="spreads", side="home", line=-1.5, home_score=5, away_score=3)
    assert by_name["current_value"] == by_slot["current_value"]
    assert _grade(by_name)["status"] == _grade(by_slot)["status"]


def test_a_positional_side_is_refused_when_the_sources_disagree():
    """`home` means the ODDS PROVIDER's home team; the scores come from the
    sport's own feed. They agree in practice -- which side is at home is a
    scheduled fact, not a naming judgement -- but an inverted game line is a
    confident wrong verdict on every bet in the game, so the disagreement is
    named rather than resolved by trusting either source."""
    view = game_line_view(
        sport="mlb", market="spreads", side="home", line=-1.5,
        # The FEED has Boston at home...
        home_team=AWAY, away_team=HOME, home_score=5, away_score=3,
        draw_possible=False,
        # ...the ORDER says Miami is.
        expect_home=HOME, expect_away=AWAY,
    )
    assert view["unavailable_reason"] == REASON_HOME_AWAY_DISAGREE


def test_a_positional_side_is_accepted_when_the_sources_agree():
    view = game_line_view(
        sport="mlb", market="spreads", side="home", line=-1.5,
        home_team=HOME, away_team=AWAY, home_score=5, away_score=3,
        draw_possible=False, expect_home=HOME, expect_away=AWAY,
    )
    assert view["current_value"] == 2


def test_a_positional_side_still_works_with_no_names_to_check():
    """Orders written before `home_team` joined the ledger's lean fields carry
    none. Refusing those would ground every positional bet rather than catch
    anything -- the feed's assignment is the only one available."""
    view = game_line_view(
        sport="mlb", market="h2h", side="home", line=None,
        home_team=HOME, away_team=AWAY, home_score=5, away_score=3,
        draw_possible=False, expect_home=None, expect_away=None,
    )
    assert view["current_value"] == 2


def test_a_positional_draw_is_still_a_draw():
    view = _view(market="h2h", side="draw", home_score=1, away_score=1,
                 draw_possible=True)
    assert _grade(view)["status"] == STATUS_WON
