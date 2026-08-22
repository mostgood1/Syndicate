"""`shared/basketball_momentum.py` -- taxonomy, orientation, and the clock.

NOTHING HERE VALIDATES THAT MOMENTUM PREDICTS ANYTHING. These are construction
tests: the events we claim to extract are extracted, signed to the right side,
and placed at the right instant. Whether the resulting series LEADS scoring is
Phase C's question (`scripts/basketball_momentum_leadlag.py`, not yet written),
and no test in this file may be cited as evidence about it.
"""

from __future__ import annotations

from typing import Any

import pytest

from syndicate.features.shared.basketball_momentum import DEFAULT_HALF_LIFE_SECONDS
from syndicate.features.shared.basketball_momentum import _LEAGUE_PERIODS
from syndicate.features.shared.basketball_momentum import _normalize_clock
from syndicate.features.shared.basketball_momentum import basketball_pressure_events
from syndicate.features.shared.basketball_momentum import basketball_scoring_events
from syndicate.features.shared.basketball_momentum import elapsed_seconds
from syndicate.features.shared.game_shape import _BASKETBALL_RULES
from syndicate.features.shared.game_shape import basketball_elapsed_minutes
from syndicate.features.shared.momentum_core import momentum_at
from syndicate.features.shared.momentum_core import momentum_series

HOME_ID, HOME_TRI = "16", "PHX"
AWAY_ID, AWAY_TRI = "20", "LVA"


def _play(
    *,
    period: int,
    clock: str,
    team_id: str,
    type_text: str = "",
    text: str = "",
    shooting: bool = False,
    attempted: int | None = None,
    score_value: int = 0,
) -> dict[str, Any]:
    play: dict[str, Any] = {
        "period": {"number": period},
        "clock": {"displayValue": clock},
        "team": {"id": team_id},
        "type": {"text": type_text},
        "text": text,
        "shootingPlay": shooting,
        "scoreValue": score_value,
    }
    if attempted is not None:
        play["pointsAttempted"] = attempted
    return play


def _summary(plays: list[dict[str, Any]], *, home_first: bool = True) -> dict[str, Any]:
    competitors = [
        {"homeAway": "home", "team": {"id": HOME_ID, "abbreviation": HOME_TRI}},
        {"homeAway": "away", "team": {"id": AWAY_ID, "abbreviation": AWAY_TRI}},
    ]
    if not home_first:
        competitors.reverse()
    return {"header": {"competitions": [{"competitors": competitors}]}, "plays": plays}


# --------------------------------------------------------------------------
# THE DRIFT GUARD
# --------------------------------------------------------------------------

@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_league_periods_agree_with_game_shape_rules(league: str) -> None:
    """`_LEAGUE_PERIODS` duplicates `game_shape._BASKETBALL_RULES` for the two
    leagues that appear in both. Duplicated because that table is private and
    carries no NCAA rows -- so this test is what makes the duplication safe.
    A quarter length that drifts here is a silently wrong elapsed clock for a
    whole sport, with no error anywhere."""
    mine = _LEAGUE_PERIODS[league]
    theirs = _BASKETBALL_RULES[league]
    assert mine["quarter_minutes"] == theirs["quarter_minutes"]
    assert mine["ot_minutes"] == theirs["ot_minutes"]
    assert mine["regulation_periods"] == theirs["regulation_periods"]


def test_ncaa_rows_are_present_and_distinct_from_the_pro_leagues() -> None:
    """Men play two 20-minute halves, women four 10-minute quarters.
    UNVERIFIED against a real feed -- no NCAAB summary has been captured and
    the season starts November 2026. Asserted so the intent is legible."""
    assert _LEAGUE_PERIODS["ncaab"]["regulation_periods"] == 2.0
    assert _LEAGUE_PERIODS["ncaab"]["quarter_minutes"] == 20.0
    assert _LEAGUE_PERIODS["ncaabw"]["regulation_periods"] == 4.0


def test_unknown_league_raises_rather_than_defaulting() -> None:
    """A silent fallback to NBA geometry would misplace every WNBA event by up
    to two minutes per quarter and never say so."""
    with pytest.raises(ValueError):
        basketball_pressure_events(_summary([]), league_code="nhl")
    with pytest.raises(ValueError):
        basketball_scoring_events(_summary([]), league_code="")


# --------------------------------------------------------------------------
# THE CLOCK -- quarter boundary, OT, and the last minute
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "league,period,clock,expected_seconds",
    [
        ("nba", 1, "12:00", 0.0),
        ("nba", 1, "0:30", 690.0),
        ("nba", 2, "11:30", 750.0),      # 60s later than the row above
        ("nba", 2, "0:00", 1440.0),
        ("nba", 5, "5:00", 2880.0),      # OT1 tip: 4 x 12
        ("nba", 5, "0:00", 3180.0),      # OT1 end: 48 + 5
        ("nba", 6, "0:00", 3480.0),      # OT2 end: 48 + 10
        ("wnba", 2, "10:00", 600.0),
        ("wnba", 5, "0:00", 2700.0),     # 4 x 10 + 5
        ("ncaab", 2, "20:00", 1200.0),   # halves, not quarters
    ],
)
def test_elapsed_seconds_across_period_boundaries_and_overtime(
    league: str, period: int, clock: str, expected_seconds: float
) -> None:
    """The lane's verification (c). Decay is meaningless against a clock that
    resets every period and runs backwards."""
    play = _play(period=period, clock=clock, team_id=HOME_ID)
    assert elapsed_seconds(play, league_code=league) == pytest.approx(expected_seconds)


def test_a_quarter_boundary_is_sixty_seconds_wide_not_twelve_minutes() -> None:
    """The specific bug a period-relative clock would cause, asserted directly:
    two events 60 real seconds apart across the Q1/Q2 line."""
    end_q1 = elapsed_seconds(_play(period=1, clock="0:30", team_id=HOME_ID), league_code="nba")
    start_q2 = elapsed_seconds(_play(period=2, clock="11:30", team_id=HOME_ID), league_code="nba")
    assert start_q2 - end_q1 == pytest.approx(60.0)


def test_the_last_minute_of_a_period_is_not_silently_dropped() -> None:
    """**THE FINDING THIS MODULE'S `_normalize_clock` EXISTS FOR.**

    ESPN switches to a tenths format under 1:00 (`"48.6"`, no colon).
    `basketball_elapsed_minutes` requires exactly two colon-separated parts, so
    every event inside the final minute would be dropped -- the stretch where
    pressure matters most, lost silently: fewer events, a plausible series, no
    error. Both halves are asserted: that the raw form IS rejected downstream,
    and that we survive it by normalising on the way in."""
    assert basketball_elapsed_minutes(1, "48.6", quarter_minutes=12.0) is None
    assert _normalize_clock("48.6") == "0:48"
    assert elapsed_seconds(
        _play(period=1, clock="48.6", team_id=HOME_ID), league_code="nba"
    ) == pytest.approx(672.0)


def test_sub_minute_clock_truncates_rather_than_rounds() -> None:
    """59.7 must not become 1:00 and push the event into the previous period."""
    assert _normalize_clock("59.7") == "0:59"
    assert _normalize_clock("0.4") == "0:00"
    assert _normalize_clock("60.0") is None
    assert _normalize_clock("-1") is None
    assert _normalize_clock("") is None
    assert _normalize_clock(None) is None


# --------------------------------------------------------------------------
# THE TAXONOMY -- what is pressure, and whose
# --------------------------------------------------------------------------

def test_points_are_absent_from_the_pressure_series() -> None:
    """The whole design. A series that counts the thing it predicts correlates
    with it by construction. A made three contributes its ATTEMPT (weight 1.0),
    never its three points."""
    made_three = _play(
        period=1, clock="10:00", team_id=HOME_ID,
        shooting=True, attempted=3, score_value=3, type_text="Three Point Jump Shot",
    )
    rows = basketball_pressure_events(_summary([made_three]), league_code="nba")
    assert len(rows) == 1
    assert rows[0]["type"] == "shot_attempt_3"
    assert rows[0]["weight"] == 1.0
    assert all(row["weight"] != 3.0 for row in rows)


def test_a_make_and_a_miss_carry_identical_pressure() -> None:
    """Dropping makes would be perverse -- pressure would FALL at the moment a
    team converted."""
    make = _play(period=1, clock="10:00", team_id=HOME_ID, shooting=True, attempted=2, score_value=2)
    miss = _play(period=1, clock="9:00", team_id=HOME_ID, shooting=True, attempted=2, score_value=0)
    rows = basketball_pressure_events(_summary([make, miss]), league_code="nba")
    assert [row["weight"] for row in rows] == [1.0, 1.0]


def test_the_scoring_series_carries_points_and_only_points() -> None:
    plays = [
        _play(period=1, clock="10:00", team_id=HOME_ID, shooting=True, attempted=3, score_value=3),
        _play(period=1, clock="9:00", team_id=AWAY_ID, shooting=True, attempted=2, score_value=0),
        _play(period=1, clock="8:00", team_id=AWAY_ID, shooting=True, attempted=2, score_value=2),
    ]
    rows = basketball_scoring_events(_summary(plays), league_code="nba")
    assert [(row["team"], row["weight"], row["sign"]) for row in rows] == [
        (HOME_TRI, 3.0, 1.0),
        (AWAY_TRI, 2.0, -1.0),
    ]


def test_a_turnover_is_credited_to_the_side_that_did_not_commit_it() -> None:
    """The one place a play's team and its sign deliberately disagree. ESPN
    attributes a turnover to the committing team; the pressure is the other
    side's."""
    plays = [_play(period=1, clock="10:00", team_id=AWAY_ID, type_text="Turnover")]
    rows = basketball_pressure_events(_summary(plays), league_code="nba")
    assert len(rows) == 1
    assert rows[0]["type"] == "turnover"
    assert rows[0]["team"] == HOME_TRI
    assert rows[0]["committed_by"] == AWAY_TRI
    assert rows[0]["sign"] == 1.0


def test_free_throws_are_weighted_per_attempt_so_a_two_shot_trip_is_one_unit() -> None:
    plays = [
        _play(period=1, clock="10:00", team_id=HOME_ID, shooting=True, attempted=1, score_value=1,
              type_text="Free Throw"),
        _play(period=1, clock="10:00", team_id=HOME_ID, shooting=True, attempted=1, score_value=1,
              type_text="Free Throw"),
    ]
    rows = basketball_pressure_events(_summary(plays), league_code="nba")
    assert [row["type"] for row in rows] == ["free_throw", "free_throw"]
    assert sum(row["weight"] for row in rows) == pytest.approx(0.8)


def test_non_shooting_fouls_and_defensive_rebounds_carry_no_pressure() -> None:
    """Both deliberately absent, for stated reasons: a foul's beneficiary
    depends on context the feed does not carry, and a defensive board is the
    DEFAULT outcome of a miss already counted as the opponent's attempt."""
    plays = [
        _play(period=1, clock="10:00", team_id=HOME_ID, type_text="Personal Foul"),
        _play(period=1, clock="9:00", team_id=HOME_ID, type_text="Defensive Rebound"),
        _play(period=1, clock="8:00", team_id=HOME_ID, type_text="Substitution"),
        _play(period=1, clock="7:00", team_id=HOME_ID, type_text="Full Timeout"),
    ]
    assert basketball_pressure_events(_summary(plays), league_code="nba") == []


def test_offensive_rebounds_steals_and_blocks_are_counted() -> None:
    plays = [
        _play(period=1, clock="10:00", team_id=HOME_ID, type_text="Offensive Rebound"),
        _play(period=1, clock="9:00", team_id=HOME_ID, type_text="Steal"),
        _play(period=1, clock="8:00", team_id=HOME_ID, type_text="Blocked Shot"),
    ]
    rows = basketball_pressure_events(_summary(plays), league_code="nba")
    assert [row["type"] for row in rows] == ["offensive_rebound", "steal", "block"]
    assert [row["weight"] for row in rows] == [1.0, 1.0, 0.75]


# --------------------------------------------------------------------------
# ORIENTATION -- which way is up
# --------------------------------------------------------------------------

def test_home_orientation_comes_from_the_feeds_own_homeaway_field() -> None:
    """Not from competitor order. Asserted with the order reversed, because
    reading `competitors[0]` as home is the obvious wrong implementation and
    would pass every other test in this file."""
    play = _play(period=1, clock="10:00", team_id=HOME_ID, shooting=True, attempted=2)
    for home_first in (True, False):
        rows = basketball_pressure_events(_summary([play], home_first=home_first), league_code="nba")
        assert rows[0]["sign"] == 1.0, f"home_first={home_first} flipped the chart"


def test_an_explicit_home_tri_overrides_the_header() -> None:
    play = _play(period=1, clock="10:00", team_id=HOME_ID, shooting=True, attempted=2)
    rows = basketball_pressure_events(_summary([play]), league_code="nba", home_tri=AWAY_TRI)
    assert rows[0]["sign"] == -1.0


def test_an_unresolvable_home_side_yields_no_events_rather_than_a_mirrored_chart() -> None:
    """A tricode that is not in the game must not silently sign everything
    away-negative -- that produces a chart which is confidently backwards."""
    play = _play(period=1, clock="10:00", team_id=HOME_ID, shooting=True, attempted=2)
    assert basketball_pressure_events(_summary([play]), league_code="nba", home_tri="XXX") == []
    assert basketball_pressure_events({"plays": [play]}, league_code="nba") == []
    assert basketball_pressure_events({"header": {}}, league_code="nba") == []


def test_a_play_from_an_unknown_team_id_is_skipped() -> None:
    plays = [_play(period=1, clock="10:00", team_id="999", shooting=True, attempted=2)]
    assert basketball_pressure_events(_summary(plays), league_code="nba") == []


def test_rows_are_sorted_by_elapsed_time() -> None:
    plays = [
        _play(period=2, clock="1:00", team_id=HOME_ID, shooting=True, attempted=2),
        _play(period=1, clock="1:00", team_id=AWAY_ID, shooting=True, attempted=2),
        _play(period=3, clock="1:00", team_id=HOME_ID, shooting=True, attempted=3),
    ]
    rows = basketball_pressure_events(_summary(plays), league_code="nba")
    assert [row["clock_seconds"] for row in rows] == sorted(row["clock_seconds"] for row in rows)


# --------------------------------------------------------------------------
# INTEGRATION with the shared core
# --------------------------------------------------------------------------

def test_pressure_rows_are_the_shape_momentum_core_reads() -> None:
    """The contract between the two modules: clock_seconds / sign / weight."""
    plays = [
        _play(period=1, clock="11:00", team_id=HOME_ID, shooting=True, attempted=3),
        _play(period=1, clock="10:00", team_id=HOME_ID, type_text="Offensive Rebound"),
        _play(period=1, clock="9:00", team_id=AWAY_ID, type_text="Steal"),
        _play(period=2, clock="11:00", team_id=AWAY_ID, shooting=True, attempted=2),
    ]
    rows = basketball_pressure_events(_summary(plays), league_code="nba")
    assert len(rows) == 4
    series = momentum_series(
        rows, until_seconds=900.0, half_life_seconds=DEFAULT_HALF_LIFE_SECONDS
    )
    assert series and all(isinstance(v, float) for _, v in series)
    # Home built pressure early, away answered later: the sign must reverse.
    assert momentum_at(rows, 180.0, half_life_seconds=DEFAULT_HALF_LIFE_SECONDS) > 0.0
    assert momentum_at(rows, 780.0, half_life_seconds=DEFAULT_HALF_LIFE_SECONDS) < 0.0


def test_the_half_life_is_declared_and_is_not_soccers() -> None:
    """Soccer's 300s is ~12 possessions per side in basketball. Asserted so a
    later edit to the shared core cannot quietly reintroduce it."""
    assert DEFAULT_HALF_LIFE_SECONDS == 120.0
