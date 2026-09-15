"""Every non-shootout ESPN scoring play counts, for the team ESPN tags.

MEASURED 2026-09-15 (lane soccer-live-scoreboard-range-stale) over every finished
match in the ten tracked leagues on 09-12/13/14, n=95:

- scoring keyEvent types: `goal` 226, `goal---header` 34, `penalty---scored` 23,
  `own-goal` 7, `goal---volley` 2, `goal---free-kick` 1.
- the live score counted `type.startswith("goal")` per tagged team, which drops
  EVERY penalty and EVERY own goal: it reproduced ESPN's final score on 68 of 95.
- "count every non-shootout `scoringPlay` for the team ESPN tags" reproduced 95 of 95.
- ESPN tags an own goal with the team it COUNTS FOR (6 of 7 finals matched that
  rule, 0 of 7 the other; the 7th only failed because its penalty was also dropped).

Seen live the same evening: Real Madrid at Elche read 1-0 on the Layer 2 chip while
ESPN had 2-0 -- a 25' own goal was missing. The live projection, goal-window
probabilities and live props all resume from this score.

The fixtures below use those real type keys and the real field names.
"""

from __future__ import annotations

import unittest

from syndicate.features.soccer.ingestion.espn_live_state import build_live_state
from syndicate.features.soccer.ingestion.espn_match_box import extract_goals
from syndicate.features.soccer.ingestion.espn_match_events import extract_key_events
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events

HOME = "Home FC"
AWAY = "Away FC"
HOME_STRIKER = ("1", "Home Striker")
HOME_DEFENDER = ("2", "Home Defender")
AWAY_STRIKER = ("3", "Away Striker")


def _minute(clock: float) -> str:
    return f"{int(clock // 60)}'"


def _key_event(type_key, text, clock, team, athlete, *, scoring, shootout=False, period=None):
    return {
        "type": {"text": text, "type": type_key},
        "period": {"number": period if period is not None else (1 if clock <= 2700 else 2)},
        "clock": {"value": clock, "displayValue": _minute(clock)},
        "team": {"displayName": team},
        "participants": [{"athlete": {"id": athlete[0], "displayName": athlete[1]}}] if athlete else [],
        "scoringPlay": scoring,
        "shootout": shootout,
    }


def _commentary(type_key, text_type, text, clock, team, athlete):
    return {
        "play": {
            "type": {"text": text_type, "type": type_key},
            "period": {"number": 1 if clock <= 2700 else 2},
            "clock": {"value": clock, "displayValue": _minute(clock)},
            "team": {"displayName": team},
            "participants": [{"athlete": {"id": athlete[0], "displayName": athlete[1]}}],
            "text": text,
        }
    }


def _summary() -> dict:
    return {
        "rosters": [
            {
                "homeAway": "home",
                "team": {"displayName": HOME},
                "roster": [
                    {"starter": True, "athlete": {"id": "1", "displayName": "Home Striker"}, "position": {"name": "Forward"}},
                    {"starter": True, "athlete": {"id": "2", "displayName": "Home Defender"}, "position": {"name": "Defender"}},
                ],
            },
            {
                "homeAway": "away",
                "team": {"displayName": AWAY},
                "roster": [
                    {"starter": True, "athlete": {"id": "3", "displayName": "Away Striker"}, "position": {"name": "Forward"}},
                ],
            },
        ],
        "keyEvents": [
            _key_event("kickoff", "Kickoff", 0.0, "", None, scoring=False),
            _key_event("goal", "Goal", 600.0, HOME, HOME_STRIKER, scoring=True),
            # Scored by a HOME player into his own net, tagged with AWAY -- the
            # team it counts for, which is how ESPN writes it.
            _key_event("own-goal", "Own Goal", 1500.0, AWAY, HOME_DEFENDER, scoring=True),
            _key_event("yellow-card", "Yellow Card", 2000.0, HOME, HOME_DEFENDER, scoring=False),
            _key_event("penalty---scored", "Penalty - Scored", 3000.0, HOME, HOME_STRIKER, scoring=True),
            _key_event("goal---header", "Goal - Header", 5000.0, AWAY, AWAY_STRIKER, scoring=True),
            # A shootout kick is a scoring play in ESPN's feed and must NOT move the score.
            _key_event("penalty---scored", "Penalty - Scored", 5400.0, HOME, HOME_STRIKER, scoring=True, shootout=True, period=5),
        ],
        "commentary": [
            _commentary("goal", "Goal", "Goal! Home FC 1, Away FC 0. Home Striker right footed shot from the centre of the box.", 600.0, HOME, HOME_STRIKER),
            _commentary("own-goal", "Own Goal", "Own Goal by Home Defender, Home FC. Home FC 1, Away FC 1.", 1500.0, AWAY, HOME_DEFENDER),
            _commentary("penalty---scored", "Penalty - Scored", "Goal! Home FC 2, Away FC 1. Home Striker converts the penalty with a right footed shot to the bottom left corner.", 3000.0, HOME, HOME_STRIKER),
            _commentary("goal---header", "Goal - Header", "Goal! Home FC 2, Away FC 2. Away Striker header from the centre of the box.", 5000.0, AWAY, AWAY_STRIKER),
        ],
    }


class KeyEventScoringFlagTests(unittest.TestCase):
    def test_key_events_carry_espn_scoring_and_shootout_flags(self) -> None:
        events = extract_key_events(_summary())
        by_clock = {(e["clock_seconds"], e["type"]): e for e in events}
        self.assertIs(by_clock[(3000.0, "penalty---scored")]["scoring_play"], True)
        self.assertIs(by_clock[(3000.0, "penalty---scored")]["shootout"], False)
        self.assertIs(by_clock[(5400.0, "penalty---scored")]["shootout"], True)
        self.assertIs(by_clock[(1500.0, "own-goal")]["scoring_play"], True)
        self.assertIs(by_clock[(0.0, "kickoff")]["scoring_play"], False)


class LiveScoreTests(unittest.TestCase):
    def test_penalties_and_own_goals_count_for_the_tagged_team(self) -> None:
        state = build_live_state(_summary(), event_id="e1")
        # HOME: open-play goal + penalty. AWAY: own goal + header. The shootout kick is excluded.
        self.assertEqual((state["score_home"], state["score_away"]), (2, 2))

    def test_every_scoring_type_respects_the_live_cutoff(self) -> None:
        self.assertEqual(
            _score(build_live_state(_summary(), event_id="e1", as_of_seconds=2000.0)), (1, 1)
        )  # goal 600s + own goal 1500s
        self.assertEqual(
            _score(build_live_state(_summary(), event_id="e1", as_of_seconds=3100.0)), (2, 1)
        )  # + penalty 3000s

    def test_converted_penalty_reaches_the_takers_live_goals(self) -> None:
        striker = build_live_state(_summary(), event_id="e1")["player_stats"]["1"]
        self.assertEqual(striker["goals_so_far"], 2)
        self.assertEqual(striker["shots_so_far"], 2)


class MatchBoxGoalListTests(unittest.TestCase):
    def test_goal_list_carries_penalties_and_own_goals_but_not_shootout_kicks(self) -> None:
        goals = extract_goals(_summary())
        self.assertEqual([g["clock_seconds"] for g in goals], [600.0, 1500.0, 3000.0, 5000.0])
        self.assertEqual([g["team"] for g in goals], [HOME, AWAY, HOME, AWAY])
        self.assertEqual([g["own_goal"] for g in goals], [False, True, False, False])
        self.assertEqual([g["penalty"] for g in goals], [False, False, True, False])


class ShotEventTests(unittest.TestCase):
    def test_converted_penalty_is_the_takers_goal_and_an_own_goal_is_no_ones_shot(self) -> None:
        rows = extract_shot_events(_summary(), event_id="e1")
        by_clock = {r["clock_seconds"]: r for r in rows}
        self.assertIn(3000.0, by_clock)
        self.assertEqual(by_clock[3000.0]["outcome"], "goal")
        self.assertEqual(by_clock[3000.0]["player_id"], "1")
        self.assertNotIn(1500.0, by_clock)
        self.assertEqual(sorted(by_clock), [600.0, 3000.0, 5000.0])


def _score(state: dict) -> tuple[int, int]:
    return state["score_home"], state["score_away"]


if __name__ == "__main__":
    unittest.main()
