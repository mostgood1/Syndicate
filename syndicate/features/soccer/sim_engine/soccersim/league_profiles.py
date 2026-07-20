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
    goal_conversion_multiplier=0.90,
    fast_break_multiplier=1.20,
    turnover_multiplier=1.08,
    possession_tempo_multiplier=0.95,
    corner_frequency_multiplier=0.82,
    # Shot-location calibration (Phase 16) vs real truth -- 7,536 shots from
    # ESPN's commentary feed, full 2025-26 season. Measured P(goal|shot): box
    # 0.155, outside_box 0.042, from-corner 0.195 vs non-corner 0.109 --
    # Bundesliga's corner conversion measured more than double the v0
    # default (0.085), needing goal_conversion_multiplier re-anchored well
    # below its pre-existing value (1.06 -> 0.90, found via a wide single-
    # pass scan against the documented truth total of 3.20 goals/match,
    # verified on an independent 500-simulation batch: 3.36 goals/match).
    box_shot_conversion_base=0.155,
    outside_box_conversion_base=0.042,
    corner_shot_conversion_base=0.195,
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
    goal_conversion_multiplier=0.90,
    final_third_stiffening=0.78,
    box_entry_stiffening=0.66,
    corner_frequency_multiplier=0.78,
    penalty_award_probability=0.15,
    protect_lead_defensiveness=1.12,
    # Shot-location calibration (Phase 17) vs real truth -- 8,726 shots from
    # ESPN's commentary feed, full 2025-26 season. Measured P(goal|shot):
    # box 0.124, outside_box 0.040, from-corner 0.151 vs non-corner 0.088.
    # multiplier re-anchor 0.85 -> 0.90 was the tightest of any league
    # calibrated this pass (scan gap 0.010; verified 2.544 vs truth 2.53 on
    # an independent batch).
    box_shot_conversion_base=0.124,
    outside_box_conversion_base=0.04,
    corner_shot_conversion_base=0.151,
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
    goal_conversion_multiplier=0.90,
    fast_break_multiplier=1.08,
    corner_frequency_multiplier=0.80,
    home_advantage_attack_boost=0.045,
    # Shot-location calibration (Phase 17) vs real truth -- 7,093 shots from
    # ESPN's commentary feed, full 2025-26 season. Measured P(goal|shot):
    # box 0.143, outside_box 0.043, from-corner 0.138 vs non-corner 0.104 --
    # the closest of any calibrated league to its own pre-existing v0
    # defaults. multiplier re-anchor 1.00 -> 0.90 (verified 2.778 vs truth
    # 2.83 on an independent batch).
    box_shot_conversion_base=0.143,
    outside_box_conversion_base=0.043,
    corner_shot_conversion_base=0.138,
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
    goal_conversion_multiplier=1.00,
    fast_break_multiplier=1.12,
    turnover_multiplier=1.10,
    home_advantage_attack_boost=0.098,
    # Shot-location calibration (Phase 16) vs real truth -- 12,924 shots from
    # ESPN's commentary feed, full 2025-26 MLS season. Measured P(goal|shot):
    # box 0.150, outside_box 0.043, from-corner 0.153 vs non-corner 0.109.
    # goal_conversion_multiplier re-anchored 1.09 -> 1.00 via a wide scan
    # against the documented truth total of 3.30 goals/match (gap 0.008 at
    # the chosen multiplier, verified on an independent 500-sim batch: 3.42).
    box_shot_conversion_base=0.15,
    outside_box_conversion_base=0.043,
    corner_shot_conversion_base=0.153,
)

# Next-tier leagues. Calibrated vs football-data.co.uk truth (2023-24..
# 2025-26; see soccersim_{league}_truth_baseline_report.md for each).

# Netherlands: high-scoring, attacking league. Truth (918 matches): shots
# 27.54/match, totals 3.14, corners 10.31, half split 1.36/1.77.
NETHERLANDS_ERE_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="eredivisie",
    shot_frequency_multiplier=1.16,
    goal_conversion_multiplier=0.80,
    corner_frequency_multiplier=0.88,
    second_half_shot_multiplier=1.34,
    # Shot-location calibration (Phase 16) vs real truth -- 8,150 shots from
    # ESPN's commentary feed, full 2025-26 season (1,298 of 8,150 shots had
    # unparseable location text and are excluded from these rates, not
    # counted as "outside box"). Measured P(goal|shot): box 0.167,
    # outside_box 0.060, from-corner 0.172 vs non-corner 0.105 -- notably
    # higher across the board than the big-five leagues, consistent with
    # Eredivisie's known attacking/high-scoring profile. Best achievable
    # multiplier-scan gap (0.084 at multiplier=0.80) sits just outside this
    # script's 0.08 tolerance -- treat 0.80 as a starting point verified to
    # the nearest 0.1, not tuned to the last decimal; a follow-up pass with
    # a larger simulation budget would sharpen it.
    box_shot_conversion_base=0.167,
    outside_box_conversion_base=0.06,
    corner_shot_conversion_base=0.172,
)

# Portugal: "big three" dominance, moderate scoring, high BTTS gap in the
# v0 baseline. Truth (918 matches): shots 23.68/match, totals 2.71,
# corners 9.71, H/D/A 42.6/25.8/31.6, BTTS 50.1%.
PORTUGAL_PRIMEIRA_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="primeira_liga",
    goal_conversion_multiplier=0.70,
    corner_frequency_multiplier=0.83,
    home_advantage_attack_boost=0.045,
    second_half_shot_multiplier=1.36,
    # Shot-location calibration (Phase 17) vs real truth -- 6,649 shots from
    # ESPN's commentary feed, full 2025-26 season (1,175 unparseable-location
    # shots excluded from the rates, not miscounted). Measured P(goal|shot):
    # box 0.175, outside_box 0.040, from-corner 0.176 vs non-corner 0.096 --
    # the highest box-conversion rate of any calibrated league, needing the
    # largest multiplier cut of the batch (0.97 -> 0.70) to hold the
    # documented truth total of 2.71 (verified 2.60 on an independent batch).
    box_shot_conversion_base=0.175,
    outside_box_conversion_base=0.04,
    corner_shot_conversion_base=0.176,
)

# England 2nd tier: known for parity/competitiveness -- moderate scoring,
# more draws. Truth (1,656 matches): shots 24.66/match, totals 2.58,
# corners 10.40, H/D/A 44.0/26.0/30.0.
CHAMPIONSHIP_CALIBRATION_PROFILE = replace(
    SOCCER_CALIBRATION_PROFILE,
    name="championship",
    shot_frequency_multiplier=1.04,
    goal_conversion_multiplier=0.80,
    corner_frequency_multiplier=0.88,
    home_advantage_attack_boost=0.055,
    # Shot-location calibration (Phase 17) vs real truth -- 13,292 shots
    # from ESPN's commentary feed, full 2025-26 season (the largest single
    # sample of any league calibrated, matching Championship's own larger
    # 46-team, 1,656-match season). Measured P(goal|shot): box 0.130,
    # outside_box 0.043, from-corner 0.160 vs non-corner 0.094. Best
    # achievable multiplier-scan gap (0.124 at multiplier=0.80) sits
    # outside this script's 0.08 tolerance and the independent verification
    # batch came back softer still (2.43 vs. truth 2.58) -- documented as a
    # starting point verified to roughly +/-0.15 goals/match, not tuned
    # tighter; a follow-up pass with a larger simulation budget is the
    # right next step here, same open item as Eredivisie.
    box_shot_conversion_base=0.13,
    outside_box_conversion_base=0.043,
    corner_shot_conversion_base=0.16,
)

# Belgium: technical, moderate-high scoring. Truth (935 matches): shots
# 26.26/match, totals 2.75, corners 10.01, H/D/A 43.0/26.7/30.3.
#
# Shot-location calibration attempted (Phase 16) and NOT applied: all 711
# shots pulled from ESPN's commentary feed classified as "unknown" location
# (0 in box/outside-box/six-yard-box). Checked the raw text directly rather
# than assuming a classifier bug -- it's not one: ESPN's own commentary for
# this league is simply much sparser than the other nine leagues (e.g.
# "Kerim Mrabti (KV Mechelen) Goal at 7'", with no shot-location phrase at
# all for espn_shot_events.py's `_classify_location` to read), not a
# language or phrasing mismatch a classifier fix could close. Applying
# box/outside-box/corner bases measured from an n=0 sample would be worse
# than leaving the v0 shot-location values in place, so this profile's
# box_shot_conversion_base/outside_box_conversion_base/
# corner_shot_conversion_base are untouched. A real, likely-permanent data
# ceiling for this league via ESPN's commentary feed, not a to-do item.
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
