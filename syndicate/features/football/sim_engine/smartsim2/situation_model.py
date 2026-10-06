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


def classify_urgency(*, quarter: int, seconds_remaining: int, score_differential: int, yardline: int) -> str:
    """Classify the offense's urgency state from game context.

    Preservation states (kneel/run-out) take precedence, then hurry-up states,
    then the leading four-minute grind, then neutral offense.
    """
    if quarter >= 4 and seconds_remaining <= 150 and score_differential > 0:
        return URGENCY_END_GAME_PRESERVATION
    if quarter == 2 and seconds_remaining <= 60 and score_differential >= 0 and yardline < 50:
        return URGENCY_HALFTIME_PRESERVATION
    if quarter in {2, 4} or quarter >= 5:
        if seconds_remaining <= 120 and score_differential <= 7:
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
