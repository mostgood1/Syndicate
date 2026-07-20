"""SoccerSim league calibration profiles.

One profile per league, all built exclusively from profile-level parameters
on the shared ``CalibrationProfile`` seam (``calibration_profile.py``). No
engine, control-flow, or situational-model code is forked per league --
every value below is consumed by the same ``event_simulator.py`` /
``possession_simulator.py`` functions the generic profile runs through,
just with different numbers. This mirrors how the Football Core carries
NFL and NCAAF on one engine.

These are v0 / Provisional profiles: values encode broadly documented
league signatures (relative scoring environment, tempo, transition
character, penalty frequency, home advantage) as modest deltas around the
generic baseline. They are starting points for each league's
historical-truth calibration loop -- the process the NCAAF profile went
through (truth report -> baseline audit -> iterative parameter sweeps) --
not its endpoint. Treat every number as replaceable by measurement.
"""

from __future__ import annotations

from dataclasses import replace

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE

# England: high tempo, above-average scoring, strong pressing, relatively
# few penalties, moderate home advantage.
EPL_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="epl",
    # First calibration pass vs football-data.co.uk truth (2023-24..2025-26,
    # 1,140 matches; see soccersim_epl_truth_baseline_report.md): shots
    # 26.2/match, totals 2.99, corners 10.4, H/D/A 43.2/24.5/32.4.
    shot_frequency_multiplier=1.10,
    goal_conversion_multiplier=0.895,
    fast_break_multiplier=1.05,
    turnover_multiplier=1.05,
    possession_tempo_multiplier=0.97,
    corner_frequency_multiplier=0.85,
    penalty_award_probability=0.11,
    home_advantage_attack_boost=0.065,
    # Second calibration pass (Phase 10) vs real shot-location truth --
    # 8,824 shots from ESPN's commentary feed across the full 2025-26
    # season, classified by ESPN's own location text (box/outside-box) and
    # corner-phase flag (see espn_shot_events.py). Measured P(goal|shot):
    # box 0.135, outside_box 0.045, from-corner 0.204 vs non-corner 0.094
    # (corner deliveries convert at ~2.2x a regular shot -- goalmouth
    # scrambles/unmarked headers). The box-vs-outside-box RATIO the
    # match-level-only pass had locked in (0.14/0.032 = 4.4x) was still off
    # from the real ratio (0.135/0.045 = 3.0x) even though aggregate totals
    # were already well-calibrated: match-level truth alone under-
    # constrains location-conditioned shot quality, since shot-volume mix
    # and conversion rate can trade off and still net out to the right
    # total. Base values set to the measured rates directly;
    # goal_conversion_multiplier is the lever that keeps aggregate totals
    # anchored (re-verified after this correction: see below).
    box_shot_conversion_base=0.135,
    outside_box_conversion_base=0.045,
    corner_shot_conversion_base=0.204,
)

# Spain: slower circulation, slightly below-average scoring, more penalties,
# more pronounced time management with a lead.
# Calibrated vs football-data.co.uk truth (2023-24..2025-26, 1,140 matches;
# see soccersim_la_liga_truth_baseline_report.md): shots 24.4/match, totals
# 2.65, corners 9.52, H/D/A 45.8/26.1/28.2, half split 1.17/1.49.
LA_LIGA_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="la_liga",
    shot_frequency_multiplier=1.06,
    goal_conversion_multiplier=0.904,
    possession_tempo_multiplier=1.06,
    corner_frequency_multiplier=0.84,
    penalty_award_probability=0.14,
    protect_lead_defensiveness=1.10,
    second_half_stoppage_base_seconds=330.0,
    second_half_shot_multiplier=1.32,
    home_advantage_attack_boost=0.085,
    # Shot-location calibration (Phase 12) vs real truth -- 8,897 shots from
    # ESPN's commentary feed, full 2025-26 season (see espn_shot_events.py).
    # Measured P(goal|shot): box 0.131, outside_box 0.046, from-corner 0.141
    # vs non-corner 0.097. Close to the pre-existing v0 box/outside-box
    # values already; corner conversion was the mismatch (engine 0.085 vs
    # measured 0.141).
    box_shot_conversion_base=0.131,
    outside_box_conversion_base=0.046,
    corner_shot_conversion_base=0.141,
)

# Germany: highest-scoring of the big five, fast transitions, high pressing.
# Calibrated vs truth (918 matches; soccersim_bundesliga_truth_baseline_report.md):
# shots 26.5/match, totals 3.20, corners 9.75, H/D/A 42.0/25.4/32.6 (already
# close pre-calibration -- only the corner rate needed correcting).
BUNDESLIGA_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="bundesliga",
    shot_frequency_multiplier=1.10,
    goal_conversion_multiplier=1.06,
    fast_break_multiplier=1.20,
    turnover_multiplier=1.08,
    possession_tempo_multiplier=0.95,
    corner_frequency_multiplier=0.82,
)

# Italy: structured defending, scoring near league-average with a high
# penalty rate and strong late-game management.
# Calibrated vs truth (1,140 matches; soccersim_serie_a_truth_baseline_report.md):
# shots 24.75/match, totals 2.53, corners 9.25, H/D/A 40.2/28.0/31.8. The v0
# profile overshot totals and both-teams-scored substantially (+0.27 goals,
# +12pts BTTS) -- goal_conversion_multiplier pulled down hard to compensate.
SERIE_A_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="serie_a",
    shot_frequency_multiplier=1.04,
    goal_conversion_multiplier=0.85,
    final_third_stiffening=0.78,
    box_entry_stiffening=0.66,
    corner_frequency_multiplier=0.78,
    penalty_award_probability=0.15,
    protect_lead_defensiveness=1.12,
)

# France: near-baseline scoring, transition-friendly midtable field.
# Calibrated vs truth (918 matches; soccersim_ligue_1_truth_baseline_report.md):
# shots 25.02/match, totals 2.83, corners 9.45, H/D/A 44.0/23.7/32.2. Draw
# rate ran high and away win rate low pre-calibration -- home advantage
# trimmed below the shared default to compensate.
LIGUE_1_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="ligue_1",
    shot_frequency_multiplier=1.05,
    goal_conversion_multiplier=1.00,
    fast_break_multiplier=1.08,
    corner_frequency_multiplier=0.80,
    home_advantage_attack_boost=0.045,
)

# United States: high-variance, high-scoring, transition-heavy league with
# outsized home advantage (travel distance, surfaces, altitude).
# Calibrated vs American Soccer Analysis 2026 season-to-date (223 games;
# see soccersim_mls_truth_baseline_report.md): shots 25.74/match (team-season
# average proxy, not per-game -- ASA's free tier has no per-game shot count),
# totals 3.30, H/D/A 48.0/22.0/30.0. Corners/SOT/half-split are not available
# from this source and stay out of MLS's benchmark scope.
MLS_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="mls",
    shot_frequency_multiplier=1.11,
    goal_conversion_multiplier=1.09,
    fast_break_multiplier=1.12,
    turnover_multiplier=1.10,
    home_advantage_attack_boost=0.098,
)

# Next-tier leagues. Calibrated vs football-data.co.uk truth (2023-24..
# 2025-26; see soccersim_{league}_truth_baseline_report.md for each).

# Netherlands: high-scoring, attacking league. Truth (918 matches): shots
# 27.54/match, totals 3.14, corners 10.31, half split 1.36/1.77.
NETHERLANDS_ERE_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="eredivisie",
    shot_frequency_multiplier=1.16,
    goal_conversion_multiplier=1.06,
    corner_frequency_multiplier=0.88,
    second_half_shot_multiplier=1.34,
)

# Portugal: "big three" dominance, moderate scoring, high BTTS gap in the
# v0 baseline. Truth (918 matches): shots 23.68/match, totals 2.71,
# corners 9.71, H/D/A 42.6/25.8/31.6, BTTS 50.1%.
PORTUGAL_PRIMEIRA_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="primeira_liga",
    goal_conversion_multiplier=0.97,
    corner_frequency_multiplier=0.83,
    home_advantage_attack_boost=0.045,
    second_half_shot_multiplier=1.36,
)

# England 2nd tier: known for parity/competitiveness -- moderate scoring,
# more draws. Truth (1,656 matches): shots 24.66/match, totals 2.58,
# corners 10.40, H/D/A 44.0/26.0/30.0.
CHAMPIONSHIP_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="championship",
    shot_frequency_multiplier=1.04,
    goal_conversion_multiplier=0.92,
    corner_frequency_multiplier=0.88,
    home_advantage_attack_boost=0.055,
)

# Belgium: technical, moderate-high scoring. Truth (935 matches): shots
# 26.26/match, totals 2.75, corners 10.01, H/D/A 43.0/26.7/30.3.
BELGIAN_PRO_LEAGUE_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="belgian_pro_league",
    shot_frequency_multiplier=1.10,
    goal_conversion_multiplier=0.90,
    corner_frequency_multiplier=0.85,
    home_advantage_attack_boost=0.055,
)

LEAGUE_CALIBRATION_PROFILES: dict[str, CalibrationProfile] = {
    profile.name: profile
    for profile in (
        SOCCER_CALIBRATION_PROFILE,
        EPL_CALIBRATION_PROFILE,
        LA_LIGA_CALIBRATION_PROFILE,
        BUNDESLIGA_CALIBRATION_PROFILE,
        SERIE_A_CALIBRATION_PROFILE,
        LIGUE_1_CALIBRATION_PROFILE,
        MLS_CALIBRATION_PROFILE,
        NETHERLANDS_ERE_CALIBRATION_PROFILE,
        PORTUGAL_PRIMEIRA_CALIBRATION_PROFILE,
        CHAMPIONSHIP_CALIBRATION_PROFILE,
        BELGIAN_PRO_LEAGUE_CALIBRATION_PROFILE,
    )
}

_LEAGUE_ALIASES = {
    "premier_league": "epl",
    "premier-league": "epl",
    "england": "epl",
    "laliga": "la_liga",
    "spain": "la_liga",
    "germany": "bundesliga",
    "seriea": "serie_a",
    "italy": "serie_a",
    "ligue1": "ligue_1",
    "france": "ligue_1",
    "major_league_soccer": "mls",
    "netherlands": "eredivisie",
    "eredevisie": "eredivisie",
    "portugal": "primeira_liga",
    "primeiraliga": "primeira_liga",
    "efl_championship": "championship",
    "english_championship": "championship",
    "belgium": "belgian_pro_league",
    "jupiler_pro_league": "belgian_pro_league",
}


def get_league_profile(league: str | None) -> CalibrationProfile:
    key = str(league or "").strip().lower().replace(" ", "_")
    key = _LEAGUE_ALIASES.get(key, key)
    return LEAGUE_CALIBRATION_PROFILES.get(key, SOCCER_CALIBRATION_PROFILE)


__all__ = [
    "BELGIAN_PRO_LEAGUE_CALIBRATION_PROFILE",
    "BUNDESLIGA_CALIBRATION_PROFILE",
    "CHAMPIONSHIP_CALIBRATION_PROFILE",
    "EPL_CALIBRATION_PROFILE",
    "LA_LIGA_CALIBRATION_PROFILE",
    "LEAGUE_CALIBRATION_PROFILES",
    "LIGUE_1_CALIBRATION_PROFILE",
    "MLS_CALIBRATION_PROFILE",
    "NETHERLANDS_ERE_CALIBRATION_PROFILE",
    "PORTUGAL_PRIMEIRA_CALIBRATION_PROFILE",
    "SERIE_A_CALIBRATION_PROFILE",
    "get_league_profile",
]
