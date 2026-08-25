"""Soccer bets could never settle. These pin the resolver that fixes that.

MEASURED 2026-08-25 14:03:02Z, all-time:

    SETTLED date=2026-08-25 orders=2 graded=0 ungraded={'no_resolver_for_soccer': 2}
    PNL_CUT all_time by_sport=[('mlb', 181, ...), ('soccer', 0, ...), ('wnba', 0, ...)]

Zero soccer bets graded, ever, on a board that was ~97% soccer by row count.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import bet_status_soccer as soccer


def _order(**over):
    base = {
        "sport": "soccer",
        "market": "h2h",
        "side": "home",
        "line": None,
        "home_team": "Chelsea",
        "away_team": "Fulham",
        "event_id": "oddsapi-hash-not-espns",
    }
    base.update(over)
    return base


def _patch_matches(monkeypatch, records):
    monkeypatch.setattr(soccer, "_load_matches", lambda _date: records)


def test_a_finished_match_grades_the_moneyline(monkeypatch):
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 2, "away_score": 1, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order())

    assert verdict["is_final"] is True
    # Home margin +1 against a 0.5 line: `game_line_view` frames a three-way
    # moneyline as over/under a half-goal margin so a level score LOSES rather
    # than pushing, which is what a soccer h2h with a draw leg actually does.
    assert verdict["current_value"] == 1
    assert verdict["side"] == "over"
    assert verdict["line"] == 0.5


def test_a_level_score_is_not_a_home_win(monkeypatch):
    """The draw leg is the whole reason soccer needed its own resolver rather
    than reusing MLB's two-way framing."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 1, "away_score": 1, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order())
    # margin 0 < 0.5 -> the over (home win) is NOT satisfied.
    assert verdict["current_value"] == 0
    assert verdict["line"] == 0.5


def test_the_draw_side_grades_as_its_own_outcome(monkeypatch):
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 1, "away_score": 1, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order(side="draw"))
    # |margin| under 0.5 is true for a level score and nothing else.
    assert verdict["current_value"] == 0
    assert verdict["side"] == "under"
    assert verdict["line"] == 0.5


def test_an_in_play_match_reports_a_value_but_NOT_final(monkeypatch):
    """A 2-0 at half time is a real current value and not a result. `is_final`
    is asserted by the artifact, never inferred from a clock -- stoppage time is
    real and routinely decides totals."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 2, "away_score": 0, "final": False},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order())
    assert verdict["current_value"] == 2
    assert verdict["is_final"] is False


def test_the_join_is_on_TEAMS_because_event_id_is_a_different_namespace(monkeypatch):
    """The MLB trap, avoided by construction.

    The order's `event_id` is OddsAPI's hash; the live-state artifact is keyed
    by ESPN's id. `bet_status_wnba` records that this exact mismatch "cost a
    day" on MLB. The record here carries NO event_id at all and must still
    grade.
    """
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 3, "away_score": 0, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(event_id="totally-unrelated")
    )
    assert verdict["current_value"] == 3


def test_an_order_with_no_matchup_refuses_by_name(monkeypatch):
    """There is no id fallback that would be anything but a guess."""
    _patch_matches(monkeypatch, [])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order(home_team=None))
    assert verdict["unavailable_reason"] == soccer.REASON_NO_MATCHUP


def test_an_unreadable_live_state_is_NOT_the_same_as_no_matches(monkeypatch):
    """None means we could not read; [] means we read and the match is absent.
    Two different jobs, and the ungraded counts must keep them apart."""
    _patch_matches(monkeypatch, None)
    assert soccer.soccer_status_resolver("2026-08-25")(_order())[
        "unavailable_reason"
    ] == soccer.REASON_NO_LIVE_STATE

    _patch_matches(monkeypatch, [])
    assert soccer.soccer_status_resolver("2026-08-25")(_order())[
        "unavailable_reason"
    ] == soccer.REASON_MATCH_NOT_FOUND


def test_a_player_prop_refuses_with_the_CAP_named_not_as_an_unknown_market(monkeypatch):
    """`poll_soccer_live_state` keeps `sorted(...)[:12]` players per match, so a
    player outside the cap is ABSENT rather than at zero. Grading that as "0
    shots, the under is fine" is the worst available wrong answer and the cap
    makes it systematic. The reason names the capture, because that is where the
    fix is."""
    _patch_matches(monkeypatch, [
        {"home_team": "Chelsea", "away_team": "Fulham",
         "home_score": 1, "away_score": 0, "final": True},
    ])
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", side="over", line=2.5, player_name="Cole Palmer")
    )
    assert verdict["unavailable_reason"] == soccer.REASON_PROPS


def test_the_market_check_runs_BEFORE_the_artifact_read(monkeypatch):
    """`bet_status_wnba`'s rule, paid for on the MLB grader: a permanent
    "we cannot grade this market" must not be hidden behind a transient
    "the artifact is not captured yet"."""
    def explode(_date):
        raise AssertionError("the artifact was read for an ungradeable market")

    monkeypatch.setattr(soccer, "_load_matches", explode)
    verdict = soccer.soccer_status_resolver("2026-08-25")(
        _order(market="player_shots", player_name="Cole Palmer")
    )
    assert verdict["unavailable_reason"] == soccer.REASON_PROPS


def test_a_non_soccer_order_is_not_reported_as_a_soccer_failure(monkeypatch):
    _patch_matches(monkeypatch, [])
    verdict = soccer.soccer_status_resolver("2026-08-25")(_order(sport="mlb"))
    assert verdict["unavailable_reason"] == soccer.REASON_NOT_SOCCER


def test_the_artifact_is_read_ONCE_for_a_whole_slate(monkeypatch):
    calls = {"n": 0}

    def counted(_date):
        calls["n"] += 1
        return [{"home_team": "Chelsea", "away_team": "Fulham",
                 "home_score": 1, "away_score": 0, "final": True}]

    monkeypatch.setattr(soccer, "_load_matches", counted)
    resolve = soccer.soccer_status_resolver("2026-08-25")
    for _ in range(5):
        resolve(_order())
    assert calls["n"] == 1
