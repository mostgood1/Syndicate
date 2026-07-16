"""SmartSim 2.0 Football Core calibration profile.

A calibration profile is the Football Core's parameterization seam for
league-specific behavior: explosive-play frequency/magnitude, ordinary
drive-yardage magnitude, field-goal success, fourth-down aggressiveness,
and touchdown-vs-field-goal scoring mix. No decision logic, control flow,
or situational/urgency model lives here -- that stays exactly as coded in
``play_simulator.py`` / ``drive_simulator.py`` / ``situation_model.py``. A
profile only rescales the numeric constants those modules already expose
as tunable seams (the constants a league's calibration report would tune).

``NFL_CALIBRATION_PROFILE`` reproduces today's hardcoded constants exactly
(multipliers of 1.0, additive bases matching the literals that used to be
hardcoded directly in play_simulator.py/drive_simulator.py). Every call
site that does not pass ``profile=`` explicitly still resolves to this
default, so the NFL calibration profile stays frozen -- byte-for-byte
identical simulated behavior -- while the Core becomes profile-aware.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationProfile:
    name: str

    # Explosive-play frequency: multiplies the EXPLOSIVE_GAIN outcome-selection
    # weight in play_simulator._play_outcome_weights.
    explosive_play_multiplier: float = 1.0
    # Explosive-play yardage magnitude: multiplies the EXPLOSIVE_GAIN yardage
    # base in play_simulator.simulate_play.
    explosive_yardage_multiplier: float = 1.0
    # Ordinary-gain yardage magnitude ("drive-yardage generation"): multiplies
    # the GAIN outcome's yardage base in play_simulator.simulate_play.
    drive_yardage_multiplier: float = 1.0

    # Field-goal success profile: make_probability = clamp(base - max(0, kick_distance - 25) * distance_penalty, floor, ceiling).
    field_goal_make_base: float = 0.98
    field_goal_make_distance_penalty: float = 0.012
    field_goal_make_floor: float = 0.30
    field_goal_make_ceiling: float = 0.97

    # Fourth-down aggressiveness -- field-goal attempt-probability curve
    # (drive_simulator._field_goal_decision).
    field_goal_attempt_fringe_probability: float = 0.50
    field_goal_attempt_base_probability: float = 0.88
    field_goal_attempt_distance_scale: float = 0.02

    # Fourth-down aggressiveness -- punt-probability by field-position/distance
    # band (drive_simulator._punt_decision). Lower values are more aggressive
    # (more likely to go for it instead of punting).
    fourth_down_short_distance_punt_probability: float = 0.30
    fourth_down_mid_distance_punt_probability: float = 0.60
    fourth_down_midfield_punt_probability: float = 0.97
    fourth_down_range_approach_punt_base: float = 0.86
    fourth_down_range_approach_punt_scale: float = 0.08
    fourth_down_in_range_punt_base: float = 0.18
    fourth_down_in_range_punt_scale: float = 0.30

    # Fourth-down conversion success: multiplies the existing distance-scaled
    # conversion-probability clamp in drive_simulator.simulate_drive.
    fourth_down_conversion_multiplier: float = 1.0

    # Scoring distribution: touchdown vs field-goal outcome-weight balance
    # in play_simulator._play_outcome_weights.
    touchdown_weight_multiplier: float = 1.0
    field_goal_weight_multiplier: float = 1.0

    def to_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "explosive_play_multiplier": self.explosive_play_multiplier,
            "explosive_yardage_multiplier": self.explosive_yardage_multiplier,
            "drive_yardage_multiplier": self.drive_yardage_multiplier,
            "field_goal_make_base": self.field_goal_make_base,
            "field_goal_make_distance_penalty": self.field_goal_make_distance_penalty,
            "field_goal_make_floor": self.field_goal_make_floor,
            "field_goal_make_ceiling": self.field_goal_make_ceiling,
            "field_goal_attempt_fringe_probability": self.field_goal_attempt_fringe_probability,
            "field_goal_attempt_base_probability": self.field_goal_attempt_base_probability,
            "field_goal_attempt_distance_scale": self.field_goal_attempt_distance_scale,
            "fourth_down_short_distance_punt_probability": self.fourth_down_short_distance_punt_probability,
            "fourth_down_mid_distance_punt_probability": self.fourth_down_mid_distance_punt_probability,
            "fourth_down_midfield_punt_probability": self.fourth_down_midfield_punt_probability,
            "fourth_down_range_approach_punt_base": self.fourth_down_range_approach_punt_base,
            "fourth_down_range_approach_punt_scale": self.fourth_down_range_approach_punt_scale,
            "fourth_down_in_range_punt_base": self.fourth_down_in_range_punt_base,
            "fourth_down_in_range_punt_scale": self.fourth_down_in_range_punt_scale,
            "fourth_down_conversion_multiplier": self.fourth_down_conversion_multiplier,
            "touchdown_weight_multiplier": self.touchdown_weight_multiplier,
            "field_goal_weight_multiplier": self.field_goal_weight_multiplier,
        }


# Extracted, not invented: every value here is the literal that used to be
# hardcoded in play_simulator.py/drive_simulator.py before this profile seam
# existed. Passing this profile (or no profile at all, since call sites
# default to it) reproduces the frozen NFL Production Candidate exactly.
NFL_CALIBRATION_PROFILE = CalibrationProfile(name="nfl")

__all__ = ["CalibrationProfile", "NFL_CALIBRATION_PROFILE"]
