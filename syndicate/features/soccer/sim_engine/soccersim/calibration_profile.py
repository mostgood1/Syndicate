"""SoccerSim Core calibration profile.

A calibration profile is the Soccer Core's parameterization seam for
league-specific behavior: shot frequency and quality, set-piece and penalty
rates, possession tempo, transition (counter-attack) character, home
advantage, and stoppage-time norms. No decision logic, control flow, or
situational/urgency model lives here -- that stays exactly as coded in
``event_simulator.py`` / ``possession_simulator.py`` / ``situation_model.py``.
A profile only rescales the numeric constants those modules expose as
tunable seams (the constants a league's calibration report would tune).

``SOCCER_CALIBRATION_PROFILE`` is the generic top-flight baseline the Core
defaults to (roughly a 2.6-2.8 goals-per-match European league shape).
League profiles in ``league_profiles.py`` are built on this same seam, so
every league runs through identical engine code with different numbers --
the same pattern the Football Core uses for NFL vs NCAAF.
"""

from __future__ import annotations

from dataclasses import dataclass

from syndicate.features.shared.calibration_profile_paths import calibration_profile_path
from syndicate.features.shared.calibration_profile_store import load_versioned_profile


@dataclass(frozen=True)
class CalibrationProfile:
    name: str

    # Attacking output: multiplies the SHOT outcome-selection weight in
    # event_simulator._event_outcome_weights.
    shot_frequency_multiplier: float = 1.0
    # Multiplies the on-target share of resolved shots in
    # event_simulator._resolve_shot.
    shot_on_target_multiplier: float = 1.0
    # Multiplies the goal probability of resolved shots in
    # event_simulator._resolve_shot.
    goal_conversion_multiplier: float = 1.0
    # Multiplies the FAST_BREAK outcome weight (transition character).
    fast_break_multiplier: float = 1.0

    # Location-based shot quality: goal probability bases by shot origin
    # before team-strength adjustment (event_simulator._goal_probability).
    box_shot_conversion_base: float = 0.140
    outside_box_conversion_base: float = 0.032
    corner_shot_conversion_base: float = 0.085

    # Set pieces: additive SHOT-weight bonus while in a dangerous set-piece
    # phase, the corner goal-quality multiplier, and the corner-award
    # frequency multiplier (scales the CORNER_WON outcome weight).
    set_piece_shot_bonus: float = 0.35
    corner_goal_multiplier: float = 1.0
    corner_frequency_multiplier: float = 1.0
    # Penalty probability per foul won inside the penalty box, and the
    # conversion probability of the resulting spot kick.
    penalty_award_probability: float = 0.12
    penalty_conversion: float = 0.78

    # Possession flow: multiplies the per-event clock consumption (higher is
    # slower, fewer possessions), the TURNOVER outcome weight (pressing
    # leagues run higher), and the ADVANCE weight in the final third / into
    # the penalty box (defensive stiffening near goal).
    possession_tempo_multiplier: float = 1.0
    turnover_multiplier: float = 1.0
    final_third_stiffening: float = 0.82
    box_entry_stiffening: float = 0.70

    # Home advantage: added to the home side's attack index in
    # possession_priors.build_possession_priors.
    home_advantage_attack_boost: float = 0.070

    # Game-state behavior: scales the retain/time-wasting boost while
    # protecting a lead and the shot/advance boost while chasing.
    protect_lead_defensiveness: float = 1.0
    trailing_push_aggression: float = 1.0
    # Second-half attacking lift: real matches score ~55-56% of goals after
    # the break (fatigue, substitutions, game-state chasing). Multiplies the
    # SHOT outcome weight from the second half on.
    second_half_shot_multiplier: float = 1.22

    # Stoppage time norms per half (seconds), drawn once per half in
    # match_simulator.simulate_match.
    first_half_stoppage_base_seconds: float = 150.0
    second_half_stoppage_base_seconds: float = 300.0
    stoppage_seconds_sigma: float = 60.0

    def to_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "shot_frequency_multiplier": self.shot_frequency_multiplier,
            "shot_on_target_multiplier": self.shot_on_target_multiplier,
            "goal_conversion_multiplier": self.goal_conversion_multiplier,
            "fast_break_multiplier": self.fast_break_multiplier,
            "box_shot_conversion_base": self.box_shot_conversion_base,
            "outside_box_conversion_base": self.outside_box_conversion_base,
            "corner_shot_conversion_base": self.corner_shot_conversion_base,
            "set_piece_shot_bonus": self.set_piece_shot_bonus,
            "corner_goal_multiplier": self.corner_goal_multiplier,
            "corner_frequency_multiplier": self.corner_frequency_multiplier,
            "penalty_award_probability": self.penalty_award_probability,
            "penalty_conversion": self.penalty_conversion,
            "possession_tempo_multiplier": self.possession_tempo_multiplier,
            "turnover_multiplier": self.turnover_multiplier,
            "final_third_stiffening": self.final_third_stiffening,
            "box_entry_stiffening": self.box_entry_stiffening,
            "home_advantage_attack_boost": self.home_advantage_attack_boost,
            "protect_lead_defensiveness": self.protect_lead_defensiveness,
            "trailing_push_aggression": self.trailing_push_aggression,
            "second_half_shot_multiplier": self.second_half_shot_multiplier,
            "first_half_stoppage_base_seconds": self.first_half_stoppage_base_seconds,
            "second_half_stoppage_base_seconds": self.second_half_stoppage_base_seconds,
            "stoppage_seconds_sigma": self.stoppage_seconds_sigma,
        }


# Generic top-flight baseline. Every call site that does not pass
# ``profile=`` explicitly resolves to this default, exactly as the Football
# Core defaults to its NFL profile.
SOCCER_CALIBRATION_PROFILE_DEFAULT = CalibrationProfile(name="soccer")

# `#440` Part 4 Phase 5 -- the versioned-profile seam.
#
# RESOLVED AT IMPORT, AND ON PURPOSE. Every consumer takes this constant as a
# DEFAULT ARGUMENT (`profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE` in
# match_simulator, possession_simulator, possession_priors, league_profiles), and
# Python evaluates default arguments once at import. Resolving the CONSTANT
# therefore reaches every existing call site with no call-site churn. Adding a
# `resolve_...()` helper instead would have required finding and changing each
# site, and any site missed would keep reading the frozen default -- which is
# precisely how `load_versioned_profile` came to be "complete and unreachable".
#
# NO-OP WHILE NO ARTIFACT EXISTS: `load_versioned_profile` returns
# `default_profile` ITSELF (not a copy) when the file is absent, invalid, or
# unreadable, and never raises. So with no artifact this line is exactly
# equivalent to the old assignment.
#
# The cost is one `Path.exists()` (plus a small JSON read if present) at import.
# Accepted deliberately: the profile must be stable for the life of a sim run,
# and re-reading per call would let an artifact change mid-slate.
SOCCER_CALIBRATION_PROFILE, SOCCER_CALIBRATION_PROFILE_METADATA = load_versioned_profile(
    default_profile=SOCCER_CALIBRATION_PROFILE_DEFAULT,
    artifact_path=calibration_profile_path("soccer"),
)

__all__ = [
    "CalibrationProfile",
    "SOCCER_CALIBRATION_PROFILE",
    "SOCCER_CALIBRATION_PROFILE_DEFAULT",
    "SOCCER_CALIBRATION_PROFILE_METADATA",
]
