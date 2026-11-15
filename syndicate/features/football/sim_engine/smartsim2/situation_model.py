from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syndicate.features.football.sim_engine.smartsim2.play_state import PlayState


# True field-goal range: kick distance = 17 + (100 - yardline). Yardline >= 65 keeps the
# attempt at 52 yards or shorter, which is the realistic NFL attempt envelope.
TRUE_FIELD_GOAL_RANGE_YARDLINE = 65

# Explicit urgency states for late-half and late-game football behavior.
URGENCY_NEUTRAL = "neutral_offense"
URGENCY_TWO_MINUTE = "two_minute_drill"
URGENCY_FOUR_MINUTE = "four_minute_offense"
URGENCY_TRAILING = "trailing_urgency"
URGENCY_HALFTIME_PRESERVATION = "halftime_preservation"
URGENCY_END_GAME_PRESERVATION = "end_game_preservation"

URGENCY_STATES = (
    URGENCY_NEUTRAL,
    URGENCY_TWO_MINUTE,
    URGENCY_FOUR_MINUTE,
    URGENCY_TRAILING,
    URGENCY_HALFTIME_PRESERVATION,
    URGENCY_END_GAME_PRESERVATION,
)


def classify_urgency(
    *,
    quarter: int,
    seconds_remaining: int,
    score_differential: int,
    yardline: int,
    q2_ignores_score: bool = False,
) -> str:
    """Classify the offense's urgency state from game context.

    Preservation states (kneel/run-out) take precedence, then hurry-up states,
    then the leading four-minute grind, then neutral offense.

    `q2_ignores_score` (todo #808, `CalibrationProfile.q2_urgency_ignores_score`):
    in Q2 the two-minute drill fires at any score, as the league's end-of-half
    behaviour does; the `diff <= 7` gate is a Q4 rule. Default False is the
    original function exactly.
    """
    if quarter >= 4 and seconds_remaining <= 150 and score_differential > 0:
        return URGENCY_END_GAME_PRESERVATION
    if quarter == 2 and seconds_remaining <= 60 and score_differential >= 0 and yardline < 50:
        return URGENCY_HALFTIME_PRESERVATION
    if quarter in {2, 4} or quarter >= 5:
        if seconds_remaining <= 120 and (score_differential <= 7 or (q2_ignores_score and quarter == 2)):
            return URGENCY_TWO_MINUTE
    if quarter >= 4 and seconds_remaining <= 360 and score_differential < 0:
        return URGENCY_TRAILING
    if quarter >= 4 and 120 < seconds_remaining <= 240 and score_differential > 0:
        return URGENCY_FOUR_MINUTE
    return URGENCY_NEUTRAL


@dataclass(frozen=True)
class SituationContext:
    label: str
    red_zone: bool
    goal_to_go: bool
    backed_up_territory: bool
    field_goal_range: bool
    four_minute_offense: bool
    two_minute_drill: bool
    long_yardage: bool
    urgency_state: str = URGENCY_NEUTRAL

    def to_dict(self) -> dict[str, bool | str]:
        return {
            "label": self.label,
            "red_zone": self.red_zone,
            "goal_to_go": self.goal_to_go,
            "backed_up_territory": self.backed_up_territory,
            "field_goal_range": self.field_goal_range,
            "four_minute_offense": self.four_minute_offense,
            "two_minute_drill": self.two_minute_drill,
            "long_yardage": self.long_yardage,
            "urgency_state": self.urgency_state,
        }


def classify_situation(play_state: PlayState) -> SituationContext:
    red_zone = play_state.yardline >= 80
    goal_to_go = play_state.yardline >= 90 and play_state.yards_to_goal <= play_state.distance
    backed_up_territory = play_state.yardline <= 20
    field_goal_range = play_state.yardline >= TRUE_FIELD_GOAL_RANGE_YARDLINE
    urgency_state = classify_urgency(
        quarter=play_state.quarter,
        seconds_remaining=play_state.seconds_remaining,
        score_differential=play_state.score_differential,
        yardline=play_state.yardline,
        q2_ignores_score=bool(getattr(play_state, "q2_urgency_ignores_score", False)),
    )
    four_minute_offense = urgency_state == URGENCY_FOUR_MINUTE
    two_minute_drill = urgency_state == URGENCY_TWO_MINUTE
    long_yardage = play_state.distance >= 8

    if goal_to_go and play_state.yards_to_goal <= 5:
        label = "Goal Line"
    elif two_minute_drill:
        label = "Two Minute Drill"
    elif four_minute_offense:
        label = "Four Minute Offense"
    elif red_zone:
        label = "Red Zone"
    elif long_yardage:
        label = "Long Yardage"
    else:
        label = "Neutral"

    return SituationContext(
        label=label,
        red_zone=red_zone,
        goal_to_go=goal_to_go,
        backed_up_territory=backed_up_territory,
        field_goal_range=field_goal_range,
        four_minute_offense=four_minute_offense,
        two_minute_drill=two_minute_drill,
        long_yardage=long_yardage,
        urgency_state=urgency_state,
    )


__all__ = [
    "SituationContext",
    "TRUE_FIELD_GOAL_RANGE_YARDLINE",
    "URGENCY_NEUTRAL",
    "URGENCY_TWO_MINUTE",
    "URGENCY_FOUR_MINUTE",
    "URGENCY_TRAILING",
    "URGENCY_HALFTIME_PRESERVATION",
    "URGENCY_END_GAME_PRESERVATION",
    "URGENCY_STATES",
    "classify_situation",
    "classify_urgency",
]


# ---------------------------------------------------------------------------
# MEASURED FOURTH-DOWN DECISIONS -- lane `football-scenario-calibration` H2
# (pre-registered in .syndicate/findings_2026-10-06_football_scenario_calibration.md
# before measuring). Read by `drive_simulator` ONLY when
# `CalibrationProfile.fourth_down_decision_model` is ON.
#
# Source: `scripts/football_scenario_rates.py fourth` -- NFL nflverse 2023-24 REG
# (7,261 fourth downs), NCAAF CFBD 2024 FBS-vs-FBS REG (10,707). EXCLUDED: the
# states the engine already decides by its own rules (Q4 <= 300 s trailing -> the
# late go-for-it; Q2/Q4 <= 90 s, field position >= 65, diff -9..+2 -> urgency FG).
# Key (field-position bucket, to-go bucket) -> (P(go), P(fg), P(punt)); each cell is
# its counts + 10 x its field-position row's pooled proportions, so a thin cell leans
# on its row (n is the raw count). Conversion: P(first down or TD | go, to-go bucket).
# FIT seasons only -- 2025 is the held-out season and was not read.
# ---------------------------------------------------------------------------
FOURTH_DOWN_FP_EDGES = (40, 50, 60, 70, 80, 90)  # yards from own goal: <40 .. 90+
FOURTH_DOWN_TOGO_EDGES = (2, 3, 5, 8, 11)  # to-go: 1 | 2 | 3-4 | 5-7 | 8-10 | 11+

FOURTH_DOWN_TABLES = {
    "nfl": {
        "decision": {
            (0, 0): (0.3051, 0.0, 0.6949),  # n=244
            (0, 1): (0.1021, 0.0, 0.8979),  # n=181
            (0, 2): (0.0563, 0.0, 0.9437),  # n=372
            (0, 3): (0.0224, 0.0, 0.9776),  # n=592
            (0, 4): (0.0176, 0.0, 0.9824),  # n=586
            (0, 5): (0.0057, 0.0, 0.9943),  # n=961
            (1, 0): (0.5962, 0.0, 0.4038),  # n=98
            (1, 1): (0.2656, 0.0, 0.7344),  # n=63
            (1, 2): (0.1183, 0.0, 0.8817),  # n=137
            (1, 3): (0.0828, 0.0, 0.9172),  # n=212
            (1, 4): (0.0396, 0.0, 0.9604),  # n=202
            (1, 5): (0.0477, 0.0, 0.9523),  # n=229
            (2, 0): (0.8419, 0.0017, 0.1563),  # n=99
            (2, 1): (0.5461, 0.0167, 0.4372),  # n=61
            (2, 2): (0.395, 0.0094, 0.5956),  # n=116
            (2, 3): (0.1779, 0.0011, 0.8211),  # n=163
            (2, 4): (0.0958, 0.0239, 0.8802),  # n=165
            (2, 5): (0.0597, 0.0429, 0.8974),  # n=204
            (3, 0): (0.8644, 0.1185, 0.0171),  # n=106
            (3, 1): (0.5732, 0.4131, 0.0137),  # n=62
            (3, 2): (0.4502, 0.4879, 0.062),  # n=135
            (3, 3): (0.2126, 0.7152, 0.0721),  # n=170
            (3, 4): (0.0734, 0.791, 0.1356),  # n=130
            (3, 5): (0.079, 0.7008, 0.2202),  # n=158
            (4, 0): (0.7154, 0.2845, 0.0002),  # n=77
            (4, 1): (0.4817, 0.5181, 0.0002),  # n=59
            (4, 2): (0.2639, 0.7266, 0.0095),  # n=97
            (4, 3): (0.137, 0.8629, 0.0001),  # n=145
            (4, 4): (0.0463, 0.9535, 0.0001),  # n=103
            (4, 5): (0.0319, 0.968, 0.0001),  # n=154
            (5, 0): (0.7081, 0.2919, 0.0),  # n=80
            (5, 1): (0.3673, 0.6327, 0.0),  # n=41
            (5, 2): (0.178, 0.822, 0.0),  # n=84
            (5, 3): (0.048, 0.952, 0.0),  # n=151
            (5, 4): (0.0444, 0.9556, 0.0),  # n=119
            (5, 5): (0.036, 0.964, 0.0),  # n=149
            (6, 0): (0.8169, 0.1831, 0.0),  # n=103
            (6, 1): (0.549, 0.451, 0.0),  # n=78
            (6, 2): (0.2457, 0.7543, 0.0),  # n=150
            (6, 3): (0.0901, 0.9099, 0.0),  # n=160
            (6, 4): (0.0708, 0.9292, 0.0),  # n=65
            (6, 5): (0.3309, 0.6691, 0.0),  # n=0
        },
        "conversion": {
            0: 0.7076,  # n=537
            1: 0.5735,  # n=204
            2: 0.5247,  # n=223
            3: 0.4462,  # n=130
            4: 0.2979,  # n=47
            5: 0.2143,  # n=42
        },
        "n_rows": 7261,
    },
    "ncaaf": {
        "decision": {
            (0, 0): (0.4089, 0.0, 0.5911),  # n=361
            (0, 1): (0.1148, 0.0, 0.8852),  # n=240
            (0, 2): (0.0584, 0.0, 0.9416),  # n=584
            (0, 3): (0.0386, 0.0, 0.9614),  # n=888
            (0, 4): (0.036, 0.0, 0.964),  # n=899
            (0, 5): (0.0171, 0.0, 0.9829),  # n=1319
            (1, 0): (0.7145, 0.0, 0.2855),  # n=187
            (1, 1): (0.3515, 0.0, 0.6485),  # n=123
            (1, 2): (0.1331, 0.0, 0.8669),  # n=221
            (1, 3): (0.0802, 0.0, 0.9198),  # n=361
            (1, 4): (0.0546, 0.0, 0.9454),  # n=297
            (1, 5): (0.037, 0.0, 0.963),  # n=335
            (2, 0): (0.8771, 0.0003, 0.1226),  # n=151
            (2, 1): (0.7029, 0.0005, 0.2966),  # n=97
            (2, 2): (0.4614, 0.0003, 0.5383),  # n=179
            (2, 3): (0.2036, 0.0037, 0.7927),  # n=271
            (2, 4): (0.1182, 0.004, 0.8778),  # n=254
            (2, 5): (0.0798, 0.0139, 0.9063),  # n=281
            (3, 0): (0.96, 0.0242, 0.0158),  # n=152
            (3, 1): (0.8388, 0.1241, 0.037),  # n=86
            (3, 2): (0.7776, 0.1729, 0.0495),  # n=163
            (3, 3): (0.577, 0.2711, 0.1518),  # n=211
            (3, 4): (0.3169, 0.4522, 0.2308),  # n=222
            (3, 5): (0.1589, 0.5162, 0.3249),  # n=201
            (4, 0): (0.8794, 0.1206, 0.0),  # n=136
            (4, 1): (0.6633, 0.3367, 0.0),  # n=72
            (4, 2): (0.4116, 0.5884, 0.0),  # n=161
            (4, 3): (0.1895, 0.8105, 0.0),  # n=219
            (4, 4): (0.2019, 0.7981, 0.0),  # n=195
            (4, 5): (0.0938, 0.9062, 0.0),  # n=218
            (5, 0): (0.8058, 0.1942, 0.0),  # n=126
            (5, 1): (0.492, 0.508, 0.0),  # n=42
            (5, 2): (0.2562, 0.7438, 0.0),  # n=125
            (5, 3): (0.1113, 0.8887, 0.0),  # n=184
            (5, 4): (0.1201, 0.8799, 0.0),  # n=153
            (5, 5): (0.0457, 0.9543, 0.0),  # n=156
            (6, 0): (0.8774, 0.1173, 0.0053),  # n=186
            (6, 1): (0.6117, 0.388, 0.0003),  # n=124
            (6, 2): (0.3057, 0.6942, 0.0002),  # n=196
            (6, 3): (0.1003, 0.8954, 0.0043),  # n=229
            (6, 4): (0.0979, 0.8928, 0.0092),  # n=102
            (6, 5): (0.3967, 0.5998, 0.0036),  # n=0
        },
        "conversion": {
            0: 0.7198,  # n=978
            1: 0.5887,  # n=372
            2: 0.4954,  # n=434
            3: 0.4038,  # n=317
            4: 0.3854,  # n=205
            5: 0.1827,  # n=104
        },
        "n_rows": 10707,
    },
}


def fourth_down_buckets(field_position: int, distance: int) -> tuple[int, int]:
    fp_bucket = sum(1 for edge in FOURTH_DOWN_FP_EDGES if field_position >= edge)
    togo_bucket = sum(1 for edge in FOURTH_DOWN_TOGO_EDGES if distance >= edge)
    return fp_bucket, togo_bucket


def fourth_down_table(profile_name: str) -> dict:
    """The sport's table for a profile name (`ncaaf...` -> NCAAF, anything else -> NFL)."""
    return FOURTH_DOWN_TABLES["ncaaf" if str(profile_name).lower().startswith("ncaaf") else "nfl"]


# ---------------------------------------------------------------------------
# MEASURED NON-OFFENSIVE SCORING -- lane `football-scenario-calibration` H3
# (pre-registered before measuring). Read by `drive_simulator` ONLY when
# `CalibrationProfile.non_offensive_scoring` is ON. Source:
# `scripts/football_scenario_rates.py nonoff`, FIT seasons only (NFL nflverse
# 2023-24 REG, NCAAF CFBD 2024 FBS-vs-FBS REG); 2025 not read.
# ---------------------------------------------------------------------------
NON_OFFENSIVE_RATES = {
    "nfl": {
        "def_td": 0.08036,  # 106/1319 turnovers
        "punt_ret_td": 0.00325,  # 14/4309 punts
        "ko_ret_td": 0.002,  # 11/5501 kickoffs
        "safety_1_5": 0.0301,  # 18/598 snaps from own 1-5
        "safety_6_10": 0.00241,  # 3/1245 snaps from own 6-10
        "free_kick_start": 37,  # mean of n=25
    },
    "ncaaf": {
        "def_td": 0.08947,  # 153/1710 turnovers
        "punt_ret_td": 0.00267,  # 17/6356 punts
        "ko_ret_td": 0.00356,  # 29/8135 kickoffs
        "safety_1_5": 0.02991,  # 28/936 snaps from own 1-5
        "safety_6_10": 0.00296,  # 5/1691 snaps from own 6-10
        "free_kick_start": 36,  # mean of n=43
    },
}


def non_offensive_rates(profile_name: str) -> dict:
    """The sport's rates for a profile name (`ncaaf...` -> NCAAF, anything else -> NFL)."""
    return NON_OFFENSIVE_RATES["ncaaf" if str(profile_name).lower().startswith("ncaaf") else "nfl"]


# ---------------------------------------------------------------------------
# MEASURED END-OF-HALF CLOCK -- todo #808, lane `football-end-of-half-fix`
# (pre-registered in .syndicate/findings_2026-11-15_football_end_of_half_fix.md
# before measuring). Read by `drive_simulator` ONLY when
# `CalibrationProfile.end_of_half_clock` is ON, for snaps in regulation Q2 / Q4.
#
# Source: `scripts/football_end_of_half_clock_rates.py` -- NFL nflverse pbp 2024-25
# REG (544 games), NCAAF CFBD plays 2024-25 FBS-vs-FBS REG (1,514 games). WINDOW =
# a snap with <= 120 s left in the quarter.
#
# `delta` is (mean, sd) seconds from a snap to the next snap of the quarter, by what
# the snap did: the clock stopped (`incomplete`, `oob`, NCAAF `first_down`), a
# timeout followed (`to_off` / `to_def` -- the live play plus whatever ran before the
# call), the clock ran (`run_<mode>`, mode from `classify_urgency` with the Q2
# score-blind rule), a no-play `penalty`, or the drive ended (`td`, `fg_good`,
# `fg_miss`, `punt`, `turnover`, `tod`, `safety` -- to the NEXT team's first snap, so
# the kickoff or return is inside it). `censored` is the share with no next snap in
# the quarter.
#
# CLOCK BUCKETS (Amendment 2, before any FIT read): the running-clock and timeout
# deltas (`delta_by_bucket`) and EVERY probability are keyed on the time left at the
# snap, [0-30 s, 30-60, 60-90, 90-120] (`end_of_half_bucket`) -- the league's
# running clock falls from 24.9 s to 9.0 s across the window and its incompletion
# share rises from 0.20 to 0.33, which a pooled cell cannot carry. A bucket censored
# above 0.15 takes the nearest bucket with more time left ("<-b" in the comments);
# in the sim a draw longer than the clock left ends the half, which is how the real
# censoring arises. Drive-ending cells, `incomplete`, `oob`, `penalty` (and NCAAF
# `first_down`) are flat across buckets and stay pooled in `delta`.
#
# `p_incomplete[mode]` (Amendment 1, written before any FIT read): the incompletion
# share of the window's offensive plays (runs, passes, sacks, kneels, turnovers; not
# spikes, kicks or no-play penalties). `play_simulator` sets the INCOMPLETE_PASS
# weight to it in the window -- a smoke run showed the clock times right and the
# play mix wrong (1.20 incompletions a game in Q2's window against the league's 2.30).
# `p_oob[mode]`: out of bounds among runs and completions (not TD / turnover / kneel
# / spike). `p_to_off["<q>_<mode>"]`: offense timeout right after a clock-running
# play, given it has one. `p_to_def["<q>_trail|lead"]`: defense timeout after one,
# given no offense timeout and it has one; `trail` = the defense is behind or tied.
#
# NCAAF CAVEATS: CFBD's `clock` is the clock at the END of each play, and some rows
# sit out of order; deltas outside 0..60 s were dropped (`dropped`). Its "out of
# bounds" comes from play text and is likely undercounted (0.04 vs the NFL's 0.20).
# NCAAF has no two-minute warning, and a first down stops the clock in the last two
# minutes (the 2023 rule) -- `first_down` is its own cell.
#
# Values are FIT-season measurements, not fitted dials: nothing here was tuned to a
# target (findings: "No fitted dial in the clock").
# ---------------------------------------------------------------------------
END_OF_HALF_WINDOW_SECONDS = 120

END_OF_HALF_CLOCK_TABLES = {
    "nfl": {
        "two_minute_warning": True,
        "first_down_stop": False,
        "live_seconds": 4.87,  # an incompletion: the live play alone
        "delta": {  # POOLED (mean, sd) seconds from this snap to the next snap of the quarter
            "fg_good": (6.33, 3.27),  # n=256, censored 0.432
            "fg_miss": (4.61, 1.36),  # n=61, censored 0.413
            "incomplete": (4.87, 1.65),  # n=1885, censored 0.018
            "oob": (6.45, 3.3),  # n=929, censored 0.007
            "penalty": (3.65, 3.54),  # n=658, censored 0.016
            "punt": (9.14, 2.31),  # n=395, censored 0.025
            "safety": (5.0, 0.71),  # n=4, censored 0.2
            "td": (7.37, 3.59),  # n=355, censored 0.03
            "tod": (5.4, 1.74),  # n=149, censored 0.118
            "turnover": (7.92, 3.24),  # n=180, censored 0.1
        },
        "delta_by_bucket": {  # Amendment 2: [0-30 s, 30-60, 60-90, 90-120] (mean, sd); "<-b" = borrowed
            "run_hurry": [(14.01, 9.23), (14.01, 9.23), (20.43, 11.54), (24.92, 12.68)],
            # n=298 cens 0.409 <-1; n=573 cens 0.037; n=798 cens 0.0; n=1045 cens 0.0
            "run_preserve": [(34.69, 11.48), (34.69, 11.48), (34.69, 11.48), (28.45, 18.91)],
            # n=71 cens 0.785 <-2; n=208 cens 0.471 <-2; n=192 cens 0.0; n=252 cens 0.0
            "to_off": [(9.48, 5.19), (14.23, 9.91), (25.66, 14.69), (25.14, 16.52)],
            # n=147 cens 0.114; n=150 cens 0.038; n=56 cens 0.0; n=22 cens 0.0
            "to_def": [(14.13, 12.85), (14.13, 12.85), (16.51, 15.0), (19.06, 17.87)],
            # n=58 cens 0.318 <-1; n=110 cens 0.098; n=134 cens 0.0; n=250 cens 0.0
        },
        "p_incomplete": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "hurry": [0.3311, 0.2546, 0.2308, 0.2034],  # n=[1655, 1626, 1651, 1967]
            "preserve": [0.1383, 0.137, 0.004, 0.0518],  # n=[499, 613, 247, 425]
        },
        "p_oob": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "hurry": [0.2546, 0.2413, 0.1881, 0.1622],  # n=[703, 949, 1079, 1313]
            "preserve": [0.2167, 0.2176, 0.0316, 0.0229],  # n=[180, 239, 95, 306]
        },
        "p_to_off": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.212, 0.1918, 0.0497, 0.0123],  # n=[382, 490, 584, 734]
            "2_preserve": [0.1124, 0.0414, 0.0, 0.0],  # n=[178, 145, 0, 0]
            "4_hurry": [0.1525, 0.1304, 0.0323, 0.0139],  # n=[118, 184, 248, 359]
            "4_preserve": [0.0242, 0.0284, 0.0465, 0.0138],  # n=[124, 282, 215, 362]
        },
        "p_to_def": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_lead": [0.0746, 0.0695, 0.1137, 0.0926],  # n=[228, 259, 299, 367]
            "2_trail": [0.0815, 0.0846, 0.1085, 0.1215],  # n=[233, 272, 258, 354]
            "4_lead": [0.0909, 0.0588, 0.0695, 0.0678],  # n=[121, 170, 259, 369]
            "4_trail": [0.1139, 0.2099, 0.1973, 0.2867],  # n=[79, 162, 147, 286]
        },
        "league_window_snaps": {"q2": 10.634, "q4": 7.382},  # 544 games; reference only
    },
    "ncaaf": {
        "two_minute_warning": False,
        "first_down_stop": True,
        "live_seconds": 6.83,  # an incompletion: the live play alone
        "delta": {  # POOLED (mean, sd) seconds from this snap to the next snap of the quarter
            "fg_good": (7.25, 7.24),  # n=465, censored 0.36, dropped 0.007
            "fg_miss": (5.87, 5.55),  # n=156, censored 0.46, dropped 0.02
            "first_down": (12.06, 10.44),  # n=4499, censored 0.047, dropped 0.01
            "incomplete": (6.83, 6.82),  # n=4727, censored 0.023, dropped 0.009
            "oob": (6.28, 5.49),  # n=534, censored 0.022, dropped 0.004
            "penalty": (8.57, 8.85),  # n=1680, censored 0.026, dropped 0.013
            "punt": (7.12, 6.33),  # n=1037, censored 0.038, dropped 0.027
            "safety": (7.33, 5.31),  # n=12, censored 0.2, dropped 0.0
            "td": (7.5, 7.73),  # n=1113, censored 0.036, dropped 0.012
            "tod": (6.88, 8.0),  # n=496, censored 0.103, dropped 0.03
            "turnover": (8.17, 7.49),  # n=499, censored 0.128, dropped 0.009
        },
        "delta_by_bucket": {  # Amendment 2: [0-30 s, 30-60, 60-90, 90-120] (mean, sd); "<-b" = borrowed
            "run_hurry": [(14.64, 12.17), (14.64, 12.17), (17.34, 13.2), (16.41, 14.53)],
            # n=631 cens 0.497 <-1; n=934 cens 0.043; n=1338 cens 0.003; n=1938 cens 0.004
            "run_preserve": [(31.62, 14.73), (31.62, 14.73), (31.62, 14.73), (25.69, 19.63)],
            # n=122 cens 0.893 <-2; n=532 cens 0.301 <-2; n=332 cens 0.031; n=547 cens 0.02
            "to_off": [(7.14, 4.84), (13.67, 12.65), (20.16, 17.14), (18.49, 18.24)],
            # n=569 cens 0.016; n=485 cens 0.004; n=277 cens 0.0; n=417 cens 0.002
            "to_def": [(7.93, 6.07), (10.96, 10.29), (9.19, 8.59), (10.37, 10.67)],
            # n=269 cens 0.025; n=357 cens 0.006; n=441 cens 0.004; n=819 cens 0.001
        },
        "p_incomplete": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "hurry": [0.2723, 0.2601, 0.2251, 0.2015],  # n=[4815, 3945, 4442, 6051]
            "preserve": [0.0687, 0.1096, 0.0059, 0.0236],  # n=[1790, 1533, 841, 1397]
        },
        "p_oob": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "hurry": [0.0514, 0.0441, 0.0419, 0.0329],  # n=[2470, 2315, 2841, 4108]
            "preserve": [0.0218, 0.0344, 0.0018, 0.0078],  # n=[1011, 960, 561, 1153]
        },
        "p_to_off": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.2395, 0.2063, 0.0793, 0.0672],  # n=[1236, 1139, 1525, 2218]
            "2_preserve": [0.1403, 0.1075, 0.0, 0.0],  # n=[449, 428, 0, 0]
            "4_hurry": [0.1602, 0.1258, 0.0923, 0.0773],  # n=[462, 477, 596, 983]
            "4_preserve": [0.0123, 0.0434, 0.078, 0.1135],  # n=[569, 461, 577, 925]
        },
        "p_to_def": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_lead": [0.1083, 0.1363, 0.1375, 0.1891],  # n=[683, 587, 691, 1005]
            "2_trail": [0.1085, 0.1314, 0.1285, 0.1592],  # n=[691, 784, 747, 1131]
            "4_lead": [0.0623, 0.0592, 0.0427, 0.0616],  # n=[401, 473, 539, 941]
            "4_trail": [0.0379, 0.1085, 0.252, 0.2872],  # n=[554, 387, 508, 888]
        },
        "league_window_snaps": {"q2": 10.594, "q4": 7.254},  # 1514 games; reference only
    },
}


def end_of_half_clock_table(profile_name: str) -> dict:
    """The sport's clock table for a profile name (`ncaaf...` -> NCAAF, anything else -> NFL)."""
    return END_OF_HALF_CLOCK_TABLES["ncaaf" if str(profile_name).lower().startswith("ncaaf") else "nfl"]


def end_of_half_bucket(seconds_remaining: int) -> int:
    """The clock table's bucket: 0 = <= 30 s left, 1 = <= 60, 2 = <= 90, 3 = <= 120."""
    s = int(seconds_remaining)
    return 3 if s > 90 else 2 if s > 60 else 1 if s > 30 else 0


def end_of_half_mode(urgency_state: str) -> str:
    """`classify_urgency`'s state -> the clock table's mode. `neutral` cannot occur in
    the window when `q2_urgency_ignores_score` is ON (Q2 is hurry or the halftime
    kneel; Q4 is hurry or the end-game run-out); with it OFF a Q2 leader by 8+ is
    neutral, and the table reads it as `hurry`, the only other measured mode."""
    if urgency_state in (URGENCY_HALFTIME_PRESERVATION, URGENCY_END_GAME_PRESERVATION):
        return "preserve"
    return "hurry"
