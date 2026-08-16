"""Tests for `shared/game_shape.py` (lane `game-shape-capture`).

Each test below is written to FAIL under a specific plausible wrong
implementation, not merely to pass under the right one. The wrong
implementation each one guards against is named in its docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from syndicate.features.shared.game_shape import (
    SHAPE_VERSION,
    bucket_distribution,
    mlb_game_shape,
    mlb_margin_band,
    mlb_phase,
    mlb_shape_bucket,
)


class _BaseStateLike(str, Enum):
    """Reproduces the vendor enum's exact declaration (`str, Enum`)."""

    EMPTY = "---"
    FIRST = "1--"
    FIRST_THIRD = "1-3"
    LOADED = "123"


@dataclass
class _SituationLike:
    """Mirrors `LiveSituation`'s field names without importing the vendor tree."""

    inning: int = 1
    top: bool = True
    outs: int = 0
    bases: Any = _BaseStateLike.EMPTY
    away_score: int = 0
    home_score: int = 0
    away_pitcher_id: int | None = None
    home_pitcher_id: int | None = None
    balls: int = 0
    strikes: int = 0
    current_pa_pitch_count: int = 0
    pitcher_pitch_count: dict = field(default_factory=dict)
    pitcher_batters_faced: dict = field(default_factory=dict)
    pitcher_entered_mid_inning: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# The enum trap
# --------------------------------------------------------------------------


def test_base_state_enum_member_is_read_by_value_not_str():
    """Guards against `str(bases)`.

    `class X(str, Enum)` is NOT `StrEnum`: `str(member)` returns
    `"_BaseStateLike.FIRST_THIRD"`. An implementation using `str()` would store
    that repr, fail the occupancy whitelist, and mark every record invalid.
    """
    assert str(_BaseStateLike.FIRST_THIRD) != "1-3", (
        "the trap this test guards has disappeared; re-check the reader"
    )
    shape = mlb_game_shape(_SituationLike(bases=_BaseStateLike.FIRST_THIRD))
    assert shape["valid"] is True
    assert shape["bases"] == "1-3"
    assert shape["runners_on"] == 2
    assert shape["in_scoring_position"] is True


def test_plain_string_base_state_also_accepted():
    """A JSON round-trip yields the bare string, not the enum."""
    shape = mlb_game_shape(_SituationLike(bases="12-"))
    assert shape["bases"] == "12-"
    assert shape["runners_on"] == 2


def test_unrecognised_base_state_is_invalid_not_guessed():
    shape = mlb_game_shape(_SituationLike(bases="banana"))
    assert shape["valid"] is False
    assert shape["reason"] == "base_state_unrecognised"


# --------------------------------------------------------------------------
# Progress arithmetic
# --------------------------------------------------------------------------


def test_outs_recorded_counts_the_completed_top_half():
    """Guards against `(inning-1)*6 + outs`, which ignores the half.

    Bottom of the 1st with 1 out is 4 outs recorded, not 1 -- the top half's
    three are already in the book.
    """
    top = mlb_game_shape(_SituationLike(inning=1, top=True, outs=1))
    bottom = mlb_game_shape(_SituationLike(inning=1, top=False, outs=1))
    assert top["outs_recorded"] == 1
    assert bottom["outs_recorded"] == 4


def test_outs_recorded_mid_game():
    """Top of the 5th, 2 out -> 4 completed innings (24) + 2."""
    shape = mlb_game_shape(_SituationLike(inning=5, top=True, outs=2))
    assert shape["outs_recorded"] == 26
    assert shape["outs_remaining_regulation"] == 28
    assert shape["extra_innings"] is False


def test_extra_innings_flagged_and_progress_capped():
    """Guards against an uncapped ratio: the 10th must not read 1.06 complete."""
    shape = mlb_game_shape(_SituationLike(inning=10, top=True, outs=0))
    assert shape["outs_recorded"] == 54
    assert shape["extra_innings"] is True
    assert shape["game_pct_complete"] == 1.0
    assert shape["outs_remaining_regulation"] == 0


# --------------------------------------------------------------------------
# Pace and pitcher workload
# --------------------------------------------------------------------------


def test_pitches_per_out_is_work_per_out_across_all_pitchers():
    """Guards against dividing by innings, or by the current pitcher only."""
    shape = mlb_game_shape(
        _SituationLike(
            inning=5,
            top=True,
            outs=1,
            pitcher_pitch_count={101: 80, 102: 20},
        )
    )
    assert shape["outs_recorded"] == 25
    assert shape["pitches_thrown"] == 100
    assert shape["pitches_per_out"] == 4.0
    assert shape["pitchers_used"] == 2


def test_times_through_order_boundaries():
    """Batters 1-9 are TTO 1; the 10th batter faced starts TTO 2.

    Guards against `//9` without the `+1` (which yields 0 for a fresh starter)
    and against an off-by-one at the boundary.
    """
    def tto(batters_faced: int) -> int | None:
        shape = mlb_game_shape(
            _SituationLike(
                inning=4,
                top=True,
                home_pitcher_id=7,
                pitcher_batters_faced={7: batters_faced},
            )
        )
        return shape["times_through_order"]

    assert tto(0) == 1
    assert tto(8) == 1
    assert tto(9) == 2
    assert tto(17) == 2
    assert tto(18) == 3


def test_current_pitcher_is_the_fielding_side():
    """Guards against reading the batting team's pitcher.

    Top half -> the AWAY team bats -> the HOME pitcher is on the mound.
    """
    top = mlb_game_shape(
        _SituationLike(
            inning=3,
            top=True,
            home_pitcher_id=7,
            away_pitcher_id=9,
            pitcher_pitch_count={7: 45, 9: 60},
        )
    )
    bottom = mlb_game_shape(
        _SituationLike(
            inning=3,
            top=False,
            home_pitcher_id=7,
            away_pitcher_id=9,
            pitcher_pitch_count={7: 45, 9: 60},
        )
    )
    assert top["current_pitcher_pitch_count"] == 45
    assert bottom["current_pitcher_pitch_count"] == 60


def test_pitcher_maps_survive_a_json_round_trip():
    """Guards against int-only key lookup.

    After JSON, `{7: 45}` becomes `{"7": 45}`. Checking only the int key would
    report 0 pitches -- a plausible number, not an obvious miss.
    """
    shape = mlb_game_shape(
        {
            "inning": 3,
            "top": True,
            "outs": 0,
            "bases": "---",
            "away_score": 0,
            "home_score": 0,
            "home_pitcher_id": 7,
            "pitcher_pitch_count": {"7": 45},
            "pitcher_batters_faced": {"7": 12},
        }
    )
    assert shape["current_pitcher_pitch_count"] == 45
    assert shape["times_through_order"] == 2


def test_unidentified_pitcher_yields_none_not_a_fresh_starter():
    """`None` must not collapse to TTO 1, which would assert a fact."""
    shape = mlb_game_shape(_SituationLike(inning=6, top=True))
    assert shape["current_pitcher_pitch_count"] is None
    assert shape["times_through_order"] is None


# --------------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------------


def test_home_margin_is_signed_from_the_home_side():
    """Must match `model_home_win_prob`'s orientation, or every join inverts."""
    shape = mlb_game_shape(_SituationLike(home_score=2, away_score=5))
    assert shape["home_margin"] == -3
    assert shape["bucket"].endswith("moderate")


# --------------------------------------------------------------------------
# Bucketing
# --------------------------------------------------------------------------


def test_phase_boundaries():
    def phase_at(inning: int, top: bool, outs: int) -> str:
        return mlb_phase(mlb_game_shape(_SituationLike(inning=inning, top=top, outs=outs)))

    assert phase_at(1, True, 0) == "early"       # 0 outs
    assert phase_at(3, False, 2) == "early"      # 17 outs -- still early by one
    assert phase_at(4, True, 0) == "middle"      # 18 exactly -> middle, not early
    assert phase_at(6, False, 2) == "middle"     # 35 outs -- still middle by one
    assert phase_at(7, True, 0) == "late"        # 36 exactly -> late, not middle
    assert phase_at(10, True, 0) == "extras"     # 54 exactly -> extras


def test_margin_band_is_sign_free():
    home_up = mlb_game_shape(_SituationLike(home_score=3, away_score=0))
    away_up = mlb_game_shape(_SituationLike(home_score=0, away_score=3))
    assert mlb_margin_band(home_up) == mlb_margin_band(away_up) == "moderate"


def test_bucket_space_stays_coarse_over_the_whole_state_space():
    """The precision-floor guarantee, asserted rather than asserted-in-prose.

    Guards against a future edit that folds a fine field (base-out state, TTO)
    into the published bucket -- which is exactly the change that would make
    every cell noise at 120 sims.
    """
    labels = set()
    for inning in range(1, 13):
        for top in (True, False):
            for outs in range(3):
                for margin in range(-9, 10):
                    shape = mlb_game_shape(
                        _SituationLike(
                            inning=inning,
                            top=top,
                            outs=outs,
                            home_score=max(0, margin),
                            away_score=max(0, -margin),
                        )
                    )
                    labels.add(shape["bucket"])
    assert len(labels) <= 17, f"bucket space grew to {len(labels)}: {sorted(labels)}"
    assert "unknown" not in labels, "a valid situation must never bucket to unknown"


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


def test_invalid_shape_never_buckets_to_a_real_label():
    """Unknown must not default onto a permissive branch."""
    for bad in (None, {}, {"inning": None}, _SituationLike(outs=7), _SituationLike(inning=0)):
        shape = mlb_game_shape(bad)
        assert shape["valid"] is False
        assert shape["bucket"] == "unknown"
        assert mlb_shape_bucket(shape) == "unknown"


def test_missing_score_is_invalid_rather_than_zero_zero():
    """Guards against `or 0`, which files an unknown score as a tie."""
    shape = mlb_game_shape(
        {"inning": 3, "top": True, "outs": 1, "bases": "---", "away_score": None, "home_score": 2}
    )
    assert shape["valid"] is False
    assert shape["reason"] == "score_absent"


def test_never_raises_on_hostile_input():
    for bad in ("", 0, [], object(), {"inning": "banana"}):
        shape = mlb_game_shape(bad)
        assert shape["valid"] is False
        assert shape["shape_version"] == SHAPE_VERSION


# --------------------------------------------------------------------------
# Distribution
# --------------------------------------------------------------------------


def test_bucket_distribution_counts_failures_rather_than_dropping_them():
    """A coverage table that omits its failures reads as full coverage."""
    shapes = [
        mlb_game_shape(_SituationLike(inning=1, top=True)),
        mlb_game_shape(_SituationLike(inning=1, top=True)),
        mlb_game_shape(_SituationLike(inning=8, top=True, home_score=7)),
        mlb_game_shape(None),
    ]
    counts = bucket_distribution(shapes)
    assert counts["early|tied"] == 2
    assert counts["late|blowout"] == 1
    assert counts["unknown"] == 1
    assert sum(counts.values()) == len(shapes)


# ==========================================================================
# BASKETBALL (WNBA / NBA)
# ==========================================================================

from syndicate.features.shared.game_shape import (  # noqa: E402
    basketball_elapsed_minutes,
    basketball_game_shape,
    basketball_margin_band,
    basketball_phase,
    wnba_game_shape,
)


def _live_state(**kw: Any) -> dict:
    """Mirrors the measured `live_state` block, 2026-06-05 DAL @ LAS."""
    base = {
        "period": 4,
        "clock": "7:43",
        "home_pts": 84.0,
        "away_pts": 83.0,
        "in_progress": True,
        "final": False,
        "periods": [
            {"period": 1, "away": 24.0, "home": 28.0},
            {"period": 2, "away": 30.0, "home": 27.0},
            {"period": 3, "away": 23.0, "home": 23.0},
            {"period": 4, "away": 6.0, "home": 6.0},
        ],
    }
    base.update(kw)
    return base


def test_basketball_elapsed_minutes_agrees_with_the_wnba_implementation():
    """Pins this parser to `wnba/cards.py:_wnba_elapsed_minutes`.

    That function's own comment says it was relocated once so two copies would
    not drift apart. This module cannot import it (shared/ must not depend on a
    sport module), so agreement is asserted instead -- across the valid grid AND
    the rejection cases. Being more permissive here would itself BE the drift,
    and would surface downstream as a population difference rather than an error.
    """
    from syndicate.features.wnba.cards import _wnba_elapsed_minutes

    clocks = ["10:00", "9:59", "7:43", "5:00", "0:01", "0:00",
              "", "banana", "7:60", "-1:00", "7", "7:43:00", None]
    checked = 0
    for period in [None, 0, 1, 2, 3, 4, 5, 6, 9, "4", "banana"]:
        for clock in clocks:
            mine = basketball_elapsed_minutes(period, clock)
            theirs = _wnba_elapsed_minutes(period, clock)
            assert mine == theirs, f"drift at period={period!r} clock={clock!r}: {mine} vs {theirs}"
            checked += 1
    assert checked == 143, f"grid shrank to {checked}; the guard is weaker than it reads"
    # Non-vacuity: the grid must contain BOTH accepted and rejected inputs, or
    # "they agree" could just mean "both return None everywhere".
    assert basketball_elapsed_minutes(4, "7:43") is not None
    assert basketball_elapsed_minutes(4, "banana") is None


def test_nba_quarters_are_twelve_minutes_not_wnba_ten():
    """Guards against hardcoding one league's quarter length in a shared fn."""
    assert basketball_elapsed_minutes(2, "0:00", quarter_minutes=10.0) == 20.0
    assert basketball_elapsed_minutes(2, "0:00", quarter_minutes=12.0) == 24.0
    wnba = wnba_game_shape(_live_state(period=2, clock="0:00"))
    nba = basketball_game_shape(_live_state(period=2, clock="0:00"), sport="nba")
    assert wnba["elapsed_minutes"] == 20.0
    assert nba["elapsed_minutes"] == 24.0
    assert wnba["game_pct_complete"] == nba["game_pct_complete"] == 0.5


def test_overtime_periods_are_five_minutes():
    assert basketball_elapsed_minutes(5, "0:00", quarter_minutes=10.0) == 45.0
    assert basketball_elapsed_minutes(6, "2:30", quarter_minutes=10.0) == 47.5
    shape = wnba_game_shape(_live_state(period=5, clock="2:00"))
    assert shape["overtime"] is True
    assert shape["elapsed_minutes"] == 43.0
    assert shape["minutes_remaining_regulation"] == 0.0
    assert shape["game_pct_complete"] == 1.0


def test_the_measured_live_record_parses_end_to_end():
    """The real 2026-06-05 DAL @ LAS state: period 4, 7:43 left, 84-83."""
    shape = wnba_game_shape(_live_state())
    assert shape["valid"] is True
    assert shape["sport"] == "wnba"
    assert shape["period"] == 4
    assert shape["home_margin"] == 1.0
    assert shape["total_points"] == 167.0
    assert round(shape["elapsed_minutes"], 2) == 32.28
    assert shape["overtime"] is False
    assert shape["bucket"] == "fourth_quarter|close"


def test_points_per_minute_is_scoring_pace_and_says_so():
    """Guards against anyone renaming this to `pace`.

    Possessions need FGA/TOV/OREB/FTA, none of which appear in any live
    basketball artifact. A reader joining this to a possession-pace prior would
    be silently wrong, so the record states the gap explicitly.
    """
    shape = wnba_game_shape(_live_state())
    assert shape["points_per_minute"] == round(167.0 / (32 + 17 / 60), 3)
    assert shape["possession_pace_available"] is False
    assert "pace" not in shape, "a bare `pace` key implies possessions"


def test_period_scores_give_run_detection():
    """Largest completed-quarter swing is shape a scoreline cannot show."""
    shape = wnba_game_shape(_live_state())
    assert shape["periods_completed"] == 3           # Q4 is in progress, not completed
    assert shape["largest_completed_period_swing"] == 4.0   # Q1 28-24; Q2 3; Q3 0
    assert shape["current_period_points"] == 12.0


def test_tip_off_is_zero_elapsed_and_pace_is_none_not_zero():
    shape = wnba_game_shape(
        _live_state(period=1, clock="10:00", home_pts=0.0, away_pts=0.0, periods=[])
    )
    assert shape["valid"] is True
    assert shape["elapsed_minutes"] == 0.0
    assert shape["points_per_minute"] is None    # not 0.0, and not a ZeroDivisionError
    assert shape["periods_completed"] == 0


def test_period_and_clock_fall_back_to_the_status_block():
    """The measured 2026-07-30 case: a live_state carrying no period/clock.

    `wnba/cards.py:1048-1049` records that reading either source alone loses
    real live games. Guards against dropping the fallback.
    """
    thin = {"home_pts": 51.0, "away_pts": 58.0, "in_progress": True, "final": False}
    status = {"period": 3, "clock": "4:00", "in_progress": True}
    shape = wnba_game_shape(thin, status=status)
    assert shape["valid"] is True
    assert shape["period"] == 3
    assert shape["elapsed_minutes"] == 26.0
    assert shape["bucket"] == "third_quarter|moderate"


def test_missing_clock_degrades_pace_only_and_keeps_the_record():
    shape = wnba_game_shape(_live_state(clock=None))
    assert shape["valid"] is True
    assert shape["clock_parsed"] is False
    assert shape["elapsed_minutes"] is None
    assert shape["points_per_minute"] is None
    assert shape["home_margin"] == 1.0
    assert shape["bucket"] == "fourth_quarter|close"


def test_absent_score_is_invalid_rather_than_zero_zero():
    shape = wnba_game_shape(_live_state(home_pts=None))
    assert shape["valid"] is False
    assert shape["reason"] == "score_absent"
    assert shape["bucket"] == "unknown"


def test_unsupported_sport_is_refused_not_defaulted_to_wnba():
    """Guards against a silent `.get(sport, WNBA_RULES)` default."""
    shape = basketball_game_shape(_live_state(), sport="ncaab")
    assert shape["valid"] is False
    assert shape["reason"] == "sport_not_supported"


def test_basketball_never_raises_on_hostile_input():
    for bad in (None, {}, "", 0, [], object(), {"period": "banana"}):
        shape = wnba_game_shape(bad)
        assert shape["valid"] is False
        assert shape["bucket"] == "unknown"


def test_basketball_margin_bands_are_not_baseball_bands():
    """3 points is `close` in basketball; the MLB scale would call it `blowout`."""
    def band(h, a):
        return basketball_margin_band(wnba_game_shape(_live_state(home_pts=h, away_pts=a)))

    assert band(84.0, 81.0) == "close"
    assert band(90.0, 81.0) == "moderate"
    assert band(99.0, 81.0) == "comfortable"
    assert band(105.0, 81.0) == "blowout"
    assert mlb_margin_band(mlb_game_shape(_SituationLike(home_score=3, away_score=0))) == "moderate"


def test_basketball_phase_boundaries():
    def phase_at(period: int) -> str:
        return basketball_phase(wnba_game_shape(_live_state(period=period, clock="5:00")))

    assert phase_at(1) == "first_half"
    assert phase_at(2) == "first_half"
    assert phase_at(3) == "third_quarter"
    assert phase_at(4) == "fourth_quarter"
    assert phase_at(5) == "overtime"


def test_basketball_bucket_space_stays_coarse():
    labels = set()
    for period in range(1, 8):
        for margin in range(-30, 31, 3):
            shape = wnba_game_shape(
                _live_state(period=period, home_pts=80.0 + margin, away_pts=80.0)
            )
            labels.add(shape["bucket"])
    assert len(labels) <= 17, f"bucket space grew to {len(labels)}: {sorted(labels)}"
    assert "unknown" not in labels
