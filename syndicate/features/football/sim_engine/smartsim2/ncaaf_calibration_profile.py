"""SmartSim 2.0 NCAAF Calibration Profile v1.

Defines the second Football Core calibration profile, built exclusively
from profile-level parameters on the shared ``CalibrationProfile`` seam
(``calibration_profile.py``). No engine, control-flow, or situational-model
code is forked for NCAAF -- every value below is consumed by the same
``play_simulator.py`` / ``drive_simulator.py`` functions the NFL profile
already runs through, just with different numbers.

Values are derived from the measured deltas in ``ncaaf_historical_truth_report.md``
(53,548 real NCAAF drives vs 17,677 real NFL drives, 2023-2025):

- yards/play +42.4% (7.36 vs 5.17) -> drive_yardage_multiplier, explosive_yardage_multiplier, explosive_play_multiplier
- touchdown_rate +20.0% (26.4% vs 22.0%), field_goal_rate(made) -36.3% (10.0% vs 15.7%) -> touchdown_weight_multiplier, field_goal_make_base/distance_penalty/floor/ceiling
- turnover_on_downs_rate +25.9% (7.3% vs 5.8%) -> fourth_down_conversion_multiplier (the field-goal-attempt-probability curve was tried and reverted to NFL defaults -- it moved punt_rate, a sport-invariant metric, without moving the made-FG-rate target)
- punt_rate, turnover_rate, seconds/drive, plays/drive, red_zone_conversion measured within 3% of NFL truth -> left at or near NFL defaults (sport-invariant Football Core behaviors, not NCAAF-specific levers)

This is a v1 / Experimental profile: parameters were set directly from the
measured truth deltas and one measurement pass (see
``ncaaf_calibration_profile_report.md`` and ``ncaaf_profile_validation_report.md``),
not from an iterative multi-pass calibration loop like the NFL profile's
seven iterations. Treat these values as the starting point for that process,
not its endpoint.
"""

from __future__ import annotations

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import CalibrationProfile

NCAAF_CALIBRATION_PROFILE = CalibrationProfile(
    name="ncaaf",
    # Yards/play is the largest measured divergence (+42.4% relative). Split
    # across three levers: more frequent explosive plays, bigger explosive
    # plays, and bigger ordinary gains -- matching the spread/tempo-offense,
    # wider-talent-mismatch signature documented in the truth report.
    explosive_play_multiplier=1.45,
    explosive_yardage_multiplier=1.35,
    drive_yardage_multiplier=1.15,
    # Field-goal success profile: college kickers are trusted over a shorter
    # effective range -- steeper distance penalty, lower ceiling.
    field_goal_make_base=0.90,
    field_goal_make_distance_penalty=0.022,
    field_goal_make_floor=0.25,
    field_goal_make_ceiling=0.82,
    # Fourth-down aggressiveness: attempt-probability curve left at NFL
    # defaults -- measurement showed the made-FG-rate gap is carried entirely
    # by the make-probability curve above; changing attempt probability only
    # perturbed punt_rate (a measured sport-invariant metric) without moving
    # the made-FG rate, so it is not a useful lever for this target.
    field_goal_attempt_fringe_probability=0.50,
    field_goal_attempt_base_probability=0.88,
    field_goal_attempt_distance_scale=0.02,
    # Punt-decision thresholds left at NFL defaults: punt_rate measured within
    # 0.1% of NFL truth, so this lever is a Football Core constant, not a
    # league-specific one.
    fourth_down_short_distance_punt_probability=0.30,
    fourth_down_mid_distance_punt_probability=0.60,
    fourth_down_midfield_punt_probability=0.97,
    fourth_down_range_approach_punt_base=0.86,
    fourth_down_range_approach_punt_scale=0.08,
    fourth_down_in_range_punt_base=0.18,
    fourth_down_in_range_punt_scale=0.30,
    # Fourth-down conversion success is lower, not higher, consistent with
    # college teams going for it more out of kicker distrust/aggression
    # rather than superior short-yardage execution -- this is the primary
    # turnover-on-downs lever.
    fourth_down_conversion_multiplier=0.55,
    # Scoring distribution: touchdown_weight_multiplier is the effective lever
    # here. The yardage multipliers above already raise touchdown frequency
    # indirectly (bigger gains reach/hold the red zone more often, and
    # red-zone presence itself raises touchdown weight), so this only needs
    # to correct, not drive, the TD/FG split -- measurement showed it
    # overshoots quickly, hence the value below 1.0.
    # field_goal_weight_multiplier is defined for symmetry/documentation of
    # the seam but is currently a no-op in practice: drive_simulator.py's 4th
    # -down handling always intercepts down==4 with its own explicit
    # _field_goal_decision/_punt_decision branch before simulate_play ever
    # runs, so play_simulator's down>=4-gated FIELD_GOAL_ATTEMPT weight is
    # unreachable. The real field-goal levers are field_goal_make_* (make
    # probability, used above) and field_goal_attempt_* (attempt probability).
    touchdown_weight_multiplier=0.66,
    field_goal_weight_multiplier=1.0,
)

__all__ = ["NCAAF_CALIBRATION_PROFILE"]
