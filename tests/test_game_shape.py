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
