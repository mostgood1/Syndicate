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
#
# v2 (pre-registered `9affd0cba`, Amendment 4 `fe98d1b87`; v1's table is commit
# `79dbfb23c`): every mode-dependent cell is keyed by QUARTER as well ("<q>_<mode>",
# "<q>_run_<mode>", "<q>_to_off" ...), because v1's pooled preserve cells mixed Q2's
# halftime leaders (still throwing, 0.21-0.27 incomplete) with Q4's run-out (~0.01).
# A cell with < 30 observations takes its pooled-over-quarters value ("P"). New:
# `p_sack` / `p_turnover` shares (applied like `p_incomplete`; kneels are not in
# their denominators), `p_to_off_need` ("<q>_<zone>", hurry, by field position),
# `p_spike` ("<q>_<zone>", last 60 s, out of timeouts), `to_spike` / `spike` /
# "<q>_kneel" deltas, and `kneel_live` (the spike delta; Amendment 4).
# ---------------------------------------------------------------------------
END_OF_HALF_WINDOW_SECONDS = 120

END_OF_HALF_CLOCK_TABLES = {
    "nfl": {
        "two_minute_warning": True,
        "first_down_stop": False,
        "live_seconds": 4.87,  # an incompletion: the live play alone
        "kneel_live": 1.0,  # v2 Amendment 4: a snap-and-down play = the spike delta
        "delta": {  # POOLED (mean, sd) seconds from this snap to the next snap of the quarter
            "fg_good": (6.33, 3.27),  # n=256, censored 0.432
            "fg_miss": (4.61, 1.36),  # n=61, censored 0.413
            "incomplete": (4.87, 1.65),  # n=1885, censored 0.018
            "oob": (6.45, 3.3),  # n=929, censored 0.007
            "penalty": (3.65, 3.54),  # n=658, censored 0.016
            "punt": (9.14, 2.31),  # n=395, censored 0.025
            "safety": (5.0, 0.71),  # n=4, censored 0.2
            "td": (7.37, 3.59),  # n=355, censored 0.03
            "to_spike": (14.84, 3.16),  # n=99, censored 0.0
            "tod": (5.46, 1.72),  # n=145, censored 0.116
            "turnover": (7.92, 3.24),  # n=180, censored 0.1
            "spike": (1.0, 0.0),  # n=146, censored 0.0
            "2_kneel": (33.43, 10.28),  # n=271, censored 0.645, pooled over quarters
            "4_kneel": (33.53, 10.26),  # n=269, censored 0.543
        },
        "delta_by_bucket": {  # [0-30 s, 30-60, 60-90, 90-120] (mean, sd); "<-b" borrowed, "P" pooled over quarters
            "2_run_hurry": [(12.41, 8.87), (12.41, 8.87), (19.93, 11.64), (25.43, 13.55)],
            # n=183 cens 0.187 <-1; n=375 cens 0.008; n=511 cens 0.0; n=652 cens 0.0
            "4_run_hurry": [(17.04, 9.56), (17.04, 9.56), (21.39, 11.39), (24.1, 11.02)],
            # n=58 cens 0.528 <-1; n=173 cens 0.094; n=276 cens 0.0; n=389 cens 0.0
            "2_run_preserve": [(13.16, 8.43), (13.16, 8.43), (30.72, 18.63), (23.87, 20.08)],
            # n=56 cens 0.434 <-1; n=130 cens 0.023; n=58 cens 0.0 P; n=186 cens 0.0 P
            "4_run_preserve": [(13.28, 9.66), (13.28, 9.66), (30.72, 18.63), (23.87, 20.08)],
            # n=59 cens 0.438 <-1 P; n=147 cens 0.039 P; n=58 cens 0.0; n=186 cens 0.0
            "2_to_off": [(9.1, 4.93), (12.79, 7.51), (20.55, 12.82), (25.14, 16.52)],
            # n=124 cens 0.095; n=109 cens 0.027; n=31 cens 0.0; n=22 cens 0.0 P
            "4_to_off": [(9.46, 5.21), (17.11, 13.28), (25.19, 14.94), (25.14, 16.52)],
            # n=146 cens 0.099 P; n=37 cens 0.075; n=53 cens 0.0 P; n=22 cens 0.0 P
            "2_to_def": [(12.21, 11.1), (12.21, 11.1), (16.0, 13.48), (15.55, 14.71)],
            # n=34 cens 0.261 <-1; n=47 cens 0.078; n=68 cens 0.0; n=85 cens 0.0
            "4_to_def": [(11.29, 11.52), (11.29, 11.52), (14.93, 15.43), (20.18, 18.97)],
            # n=54 cens 0.26 <-1 P; n=41 cens 0.047; n=59 cens 0.0; n=156 cens 0.0
        },
        "p_incomplete": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.3668, 0.2507, 0.2387, 0.1794],  # n=[1047, 1013, 1039, 1176]
            "2_preserve": [0.2634, 0.2748, 0.0094, 0.0625],  # n=[262, 302, '0->pooled 106', '0->pooled 352']
            "4_hurry": [0.3313, 0.268, 0.2191, 0.2398],  # n=[495, 597, 607, 788]
            "4_preserve": [0.25, 0.02, 0.0094, 0.0625],  # n=['14->pooled 276', 50, 106, 352]
        },
        "p_sack": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.0525, 0.0632, 0.0433, 0.0451],  # n=[1047, 1013, 1039, 1176]
            "2_preserve": [0.0573, 0.053, 0.0, 0.0227],  # n=[262, 302, '0->pooled 106', '0->pooled 352']
            "4_hurry": [0.0606, 0.0419, 0.0527, 0.0571],  # n=[495, 597, 607, 788]
            "4_preserve": [0.058, 0.0, 0.0, 0.0227],  # n=['14->pooled 276', 50, 106, 352]
        },
        "p_turnover": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.0201, 0.0247, 0.0164, 0.0213],  # n=[1047, 1013, 1039, 1176]
            "2_preserve": [0.0191, 0.0397, 0.0, 0.0028],  # n=[262, 302, '0->pooled 106', '0->pooled 352']
            "4_hurry": [0.0566, 0.0352, 0.028, 0.0203],  # n=[495, 597, 607, 788]
            "4_preserve": [0.0181, 0.0, 0.0, 0.0028],  # n=['14->pooled 276', 50, 106, 352]
        },
        "p_oob": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.2804, 0.2255, 0.1758, 0.1643],  # n=[485, 612, 694, 834]
            "2_preserve": [0.2281, 0.2708, 0.0316, 0.0229],  # n=[171, 192, '0->pooled 95', '0->pooled 306']
            "4_hurry": [0.1972, 0.27, 0.2104, 0.1587],  # n=[218, 337, 385, 479]
            "4_preserve": [0.2167, 0.0, 0.0316, 0.0229],  # n=['9->pooled 180', 47, 95, 306]
        },
        "p_to_off": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.212, 0.1918, 0.0497, 0.0123],  # n=[382, 490, 584, 734]
            "2_preserve": [0.1124, 0.0414, 0.0465, 0.0138],  # n=[178, 145, '0->pooled 215', '0->pooled 362']
            "4_hurry": [0.1525, 0.1304, 0.0323, 0.0139],  # n=[118, 184, 248, 359]
            "4_preserve": [0.0242, 0.0284, 0.0465, 0.0138],  # n=[124, 282, 215, 362]
        },
        "p_to_off_need": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_mid": [0.3857, 0.1733, 0.0763, 0.027],  # n=[70, 150, 118, 111]
            "2_own": [0.1075, 0.1511, 0.0453, 0.0026],  # n=[186, 139, 287, 380]
            "2_range": [0.2698, 0.2338, 0.0391, 0.0206],  # n=[126, 201, 179, 243]
            "4_mid": [0.3548, 0.087, 0.0204, 0.0299],  # n=['23->pooled 93', 46, 49, 67]
            "4_own": [0.025, 0.1404, 0.0192, 0.0059],  # n=[40, 57, 104, 170]
            "4_range": [0.2, 0.1481, 0.0526, 0.0164],  # n=[55, 81, 95, 122]
        },
        "p_to_def": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_lead": [0.0746, 0.0695, 0.1137, 0.0926],  # n=[228, 259, 299, 367]
            "2_trail": [0.0815, 0.0846, 0.1085, 0.1215],  # n=[233, 272, 258, 354]
            "4_lead": [0.0909, 0.0588, 0.0695, 0.0678],  # n=[121, 170, 259, 369]
            "4_trail": [0.1139, 0.2099, 0.1973, 0.2867],  # n=[79, 162, 147, 286]
        },
        "p_spike": {  # last 60 s, hurry, out of timeouts, after a clock-running play
            "2_own": 0.4839,  # n=31
            "2_mid": 0.325,  # n=13->pooled 40
            "2_range": 0.4348,  # n=18->pooled 46
            "4_own": 0.3559,  # n=59
            "4_mid": 0.325,  # n=27->pooled 40
            "4_range": 0.4348,  # n=28->pooled 46
        },
        "league_window_snaps": {"q2": 10.634, "q4": 7.382},  # 544 games; reference only
    },
    "ncaaf": {
        "two_minute_warning": False,
        "first_down_stop": True,
        "live_seconds": 6.83,  # an incompletion: the live play alone
        "kneel_live": 4.12,  # v2 Amendment 4: a snap-and-down play = the spike delta
        "delta": {  # POOLED (mean, sd) seconds from this snap to the next snap of the quarter
            "fg_good": (7.25, 7.24),  # n=465, censored 0.36, dropped 0.007
            "fg_miss": (5.87, 5.55),  # n=156, censored 0.46, dropped 0.02
            "first_down": (12.06, 10.43),  # n=4498, censored 0.047, dropped 0.01
            "incomplete": (6.83, 6.82),  # n=4727, censored 0.023, dropped 0.009
            "oob": (6.28, 5.49),  # n=534, censored 0.022, dropped 0.004
            "penalty": (8.57, 8.85),  # n=1677, censored 0.025, dropped 0.013
            "punt": (7.12, 6.33),  # n=1037, censored 0.038, dropped 0.027
            "safety": (7.33, 5.31),  # n=12, censored 0.2, dropped 0.0
            "td": (7.5, 7.73),  # n=1113, censored 0.036, dropped 0.012
            "to_spike": (6.88, 4.9),  # n=16, censored 0.0, dropped 0.0
            "tod": (6.89, 8.02),  # n=491, censored 0.096, dropped 0.03
            "turnover": (8.17, 7.49),  # n=499, censored 0.128, dropped 0.009
            "spike": (4.12, 3.47),  # n=64, censored 0.0, dropped 0.015
            "2_kneel": (30.55, 14.59),  # n=344, censored 0.662, dropped 0.038, pooled over quarters
            "4_kneel": (30.74, 14.52),  # n=340, censored 0.582, dropped 0.045
        },
        "delta_by_bucket": {  # [0-30 s, 30-60, 60-90, 90-120] (mean, sd); "<-b" borrowed, "P" pooled over quarters
            "2_run_hurry": [(13.7, 11.4), (13.7, 11.4), (17.37, 13.42), (16.44, 14.61)],
            # n=408 cens 0.456 <-1; n=572 cens 0.04; n=895 cens 0.002; n=1257 cens 0.002
            "4_run_hurry": [(16.14, 13.18), (16.14, 13.18), (17.26, 12.73), (16.39, 14.4)],
            # n=206 cens 0.451 <-1; n=360 cens 0.037; n=443 cens 0.004; n=680 cens 0.007
            "2_run_preserve": [(14.2, 12.73), (14.2, 12.73), (30.29, 16.42), (24.62, 19.7)],
            # n=76 cens 0.738 <-1; n=231 cens 0.094; n=195 cens 0.022 P; n=482 cens 0.014 P
            "4_run_preserve": [(30.29, 16.42), (30.29, 16.42), (30.29, 16.42), (24.62, 19.7)],
            # n=30 cens 0.921 <-2; n=179 cens 0.215 <-2; n=195 cens 0.022; n=482 cens 0.014
            "2_to_off": [(7.14, 4.78), (12.95, 11.76), (17.19, 15.48), (16.45, 16.66)],
            # n=470 cens 0.015; n=381 cens 0.003; n=159 cens 0.0; n=177 cens 0.0
            "4_to_off": [(7.13, 5.17), (16.57, 15.18), (23.66, 18.49), (19.99, 19.24)],
            # n=97 cens 0.02; n=102 cens 0.0; n=114 cens 0.0; n=237 cens 0.004
            "2_to_def": [(8.13, 6.07), (11.13, 10.22), (9.27, 8.16), (11.16, 10.79)],
            # n=197 cens 0.02; n=256 cens 0.0; n=244 cens 0.004; n=421 cens 0.0
            "4_to_def": [(7.45, 5.67), (9.97, 9.0), (9.3, 9.21), (9.44, 10.41)],
            # n=66 cens 0.043; n=90 cens 0.011; n=189 cens 0.0; n=396 cens 0.003
        },
        "p_incomplete": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.2742, 0.2593, 0.2205, 0.1854],  # n=[3169, 2549, 2984, 3857]
            "2_preserve": [0.1553, 0.1957, 0.0077, 0.0252],  # n=[747, 833, '0->pooled 649', '0->pooled 1310']
            "4_hurry": [0.2896, 0.2628, 0.2346, 0.2297],  # n=[1526, 1389, 1458, 2194]
            "4_preserve": [0.0129, 0.0123, 0.0077, 0.0252],  # n=[543, 406, 649, 1310]
        },
        "p_sack": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.0483, 0.0455, 0.0379, 0.0342],  # n=[3169, 2549, 2984, 3857]
            "2_preserve": [0.0482, 0.03, 0.0, 0.0061],  # n=[747, 833, '0->pooled 649', '0->pooled 1310']
            "4_hurry": [0.0433, 0.0374, 0.0508, 0.0438],  # n=[1526, 1389, 1458, 2194]
            "4_preserve": [0.0074, 0.0, 0.0, 0.0061],  # n=[543, 406, 649, 1310]
        },
        "p_turnover": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.0297, 0.0243, 0.0231, 0.0158],  # n=[3169, 2549, 2984, 3857]
            "2_preserve": [0.0268, 0.0132, 0.0139, 0.0061],  # n=[747, 833, '0->pooled 649', '0->pooled 1310']
            "4_hurry": [0.0564, 0.0403, 0.0309, 0.0237],  # n=[1526, 1389, 1458, 2194]
            "4_preserve": [0.0037, 0.0074, 0.0139, 0.0061],  # n=[543, 406, 649, 1310]
        },
        "p_oob": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.0532, 0.0474, 0.0405, 0.0337],  # n=[1692, 1518, 1977, 2727]
            "2_preserve": [0.0378, 0.0499, 0.0018, 0.0078],  # n=[556, 621, '0->pooled 561', '0->pooled 1153']
            "4_hurry": [0.0476, 0.0376, 0.0451, 0.0311],  # n=[778, 797, 864, 1381]
            "4_preserve": [0.0022, 0.0059, 0.0018, 0.0078],  # n=[455, 339, 561, 1153]
        },
        "p_to_off": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_hurry": [0.2395, 0.2063, 0.0793, 0.0672],  # n=[1236, 1139, 1525, 2218]
            "2_preserve": [0.1403, 0.1075, 0.078, 0.1135],  # n=[449, 428, '0->pooled 577', '0->pooled 925']
            "4_hurry": [0.1602, 0.1258, 0.0923, 0.0773],  # n=[462, 477, 596, 983]
            "4_preserve": [0.0123, 0.0434, 0.078, 0.1135],  # n=[569, 461, 577, 925]
        },
        "p_to_off_need": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_mid": [0.3151, 0.2119, 0.1003, 0.0573],  # n=[238, 269, 289, 384]
            "2_own": [0.1111, 0.1189, 0.0602, 0.0598],  # n=[603, 387, 847, 1237]
            "2_range": [0.3899, 0.2733, 0.1054, 0.0888],  # n=[395, 483, 389, 597]
            "4_mid": [0.1594, 0.0933, 0.084, 0.0632],  # n=[69, 75, 119, 174]
            "4_own": [0.1283, 0.1033, 0.0753, 0.0642],  # n=[265, 242, 279, 514]
            "4_range": [0.2266, 0.175, 0.1212, 0.1085],  # n=[128, 160, 198, 295]
        },
        "p_to_def": {  # by bucket [0-30 s, 30-60, 60-90, 90-120]
            "2_lead": [0.1083, 0.1363, 0.1375, 0.1891],  # n=[683, 587, 691, 1005]
            "2_trail": [0.1085, 0.1314, 0.1285, 0.1592],  # n=[691, 784, 747, 1131]
            "4_lead": [0.0623, 0.0592, 0.0427, 0.0616],  # n=[401, 473, 539, 941]
            "4_trail": [0.0379, 0.1085, 0.252, 0.2872],  # n=[554, 387, 508, 888]
        },
        "p_spike": {  # last 60 s, hurry, out of timeouts, after a clock-running play
            "2_own": 0.0,  # n=77
            "2_mid": 0.0638,  # n=47
            "2_range": 0.039,  # n=77
            "4_own": 0.0515,  # n=97
            "4_mid": 0.0526,  # n=29->pooled 76
            "4_range": 0.0,  # n=34
        },
        "league_window_snaps": {"q2": 10.594, "q4": 7.254},  # 1514 games; reference only
    },
}


def end_of_half_clock_table(profile_name: str) -> dict:
    """The sport's clock table for a profile name (`ncaaf...` -> NCAAF, anything else -> NFL)."""
    return END_OF_HALF_CLOCK_TABLES["ncaaf" if str(profile_name).lower().startswith("ncaaf") else "nfl"]


def end_of_half_zone(yardline: int) -> str:
    """todo #808 v2 need key: own half / 50-64 / scoring range (>= TRUE_FIELD_GOAL_RANGE_YARDLINE)."""
    y = int(yardline)
    return "own" if y < 50 else "mid" if y < TRUE_FIELD_GOAL_RANGE_YARDLINE else "range"


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
