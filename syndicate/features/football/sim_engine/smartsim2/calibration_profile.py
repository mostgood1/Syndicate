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

from syndicate.features.shared.calibration_profile_paths import calibration_profile_path
from syndicate.features.shared.calibration_profile_store import load_versioned_profile


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

    # Red-zone-specific scoring distribution: these two isolate red-zone
    # behavior from the general touchdown_weight_multiplier/gain formulas
    # above, so a league can raise red-zone efficiency (more trips ending in
    # touchdowns instead of stalling into a field-goal attempt or
    # turnover-on-downs) without moving the overall (all-field-position)
    # touchdown rate or ordinary drive yardage.
    # Additive bonus to the touchdown outcome weight while play_state.red_zone
    # is true (play_simulator._play_outcome_weights); replaces the literal
    # `red_zone * 0.33` term.
    red_zone_touchdown_weight_bonus: float = 0.33
    # Multiplies the ordinary-GAIN outcome weight while play_state.field_goal_range
    # is true (play_simulator._play_outcome_weights); replaces the literal
    # `gain *= 0.80` scoring-zone stiffening. Lower values stall more drives
    # into field-goal attempts/turnovers-on-downs; higher values (closer to
    # 1.0) keep more red-zone possessions alive long enough to score a
    # touchdown instead.
    red_zone_gain_stiffening: float = 0.80

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
            "red_zone_touchdown_weight_bonus": self.red_zone_touchdown_weight_bonus,
            "red_zone_gain_stiffening": self.red_zone_gain_stiffening,
        }


# Extracted, not invented: every value here is the literal that used to be
# hardcoded in play_simulator.py/drive_simulator.py before this profile seam
# existed. Passing this profile (or no profile at all, since call sites
# default to it) reproduces the frozen NFL Production Candidate exactly.
NFL_CALIBRATION_PROFILE_DEFAULT = CalibrationProfile(name="nfl")

# `#440` Part 4 Phase 5 -- the versioned-profile seam. See the soccer engine's
# copy of this comment for the full reasoning; the short version:
#
# RESOLVED AT IMPORT because every consumer takes this constant as a DEFAULT
# ARGUMENT (`simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)` in the
# four generate/backtest scripts, and the engine's own defaults), and Python
# evaluates those once at import. Resolving the CONSTANT reaches every call site
# with no churn; a separate `resolve_...()` helper would have required editing
# each one, and any site missed keeps reading the frozen default -- which is
# exactly how `load_versioned_profile` came to be "complete and unreachable".
#
# NO-OP WHILE NO ARTIFACT EXISTS: the loader returns `default_profile` ITSELF
# when the file is absent, invalid or unreadable, and never raises. The comment
# above still holds verbatim -- passing this profile, or none, reproduces the
# frozen NFL Production Candidate exactly.
#
# NOTE FOR PHASE 8: this profile is currently ALL 1.0 MULTIPLIERS, i.e. NFL has
# never had a real calibration. That is what makes it the cheapest Phase 8
# target, and this seam is what lets it ship as a file rather than a code change.
NFL_CALIBRATION_PROFILE, NFL_CALIBRATION_PROFILE_METADATA = load_versioned_profile(
    default_profile=NFL_CALIBRATION_PROFILE_DEFAULT,
    artifact_path=calibration_profile_path("nfl"),
)

__all__ = [
    "CalibrationProfile",
    "NFL_CALIBRATION_PROFILE",
    "NFL_CALIBRATION_PROFILE_DEFAULT",
    "NFL_CALIBRATION_PROFILE_METADATA",
]
