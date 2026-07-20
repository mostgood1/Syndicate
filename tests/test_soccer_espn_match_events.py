from __future__ import annotations

import unittest

from syndicate.features.soccer.ingestion.espn_match_events import compute_minutes_played
from syndicate.features.soccer.ingestion.espn_match_events import extract_key_events


def _sub_event(*, clock_seconds: float, in_id: str, out_id: str, period: int = 2) -> dict:
    # Normalized shape (the output of extract_key_events, not raw ESPN JSON) --
    # compute_minutes_played consumes this shape directly.
    return {
        "type": "substitution",
        "type_text": "Substitution",
        "period": period,
        "clock_seconds": clock_seconds,
        "clock_display": "",
        "team": "Home FC",
        "participants": [
            {"athlete_id": in_id, "athlete_name": f"Player {in_id}"},
            {"athlete_id": out_id, "athlete_name": f"Player {out_id}"},
        ],
    }


def _red_card_event(*, clock_seconds: float, player_id: str, period: int = 2) -> dict:
    return {
        "type": "red-card",
        "type_text": "Red Card",
        "period": period,
        "clock_seconds": clock_seconds,
        "clock_display": "",
        "team": "Home FC",
        "participants": [{"athlete_id": player_id, "athlete_name": f"Player {player_id}"}],
    }


def _roster(player_ids: dict[str, bool]) -> list[dict]:
    return [{"player_id": pid, "starter": is_starter} for pid, is_starter in player_ids.items()]


class ExtractKeyEventsTests(unittest.TestCase):
    def test_normalizes_raw_espn_events(self) -> None:
        summary = {
            "keyEvents": [
                {
                    "type": {"text": "Substitution", "type": "substitution"},
                    "period": {"number": 2},
                    "clock": {"value": 3600.0, "displayValue": "60'"},
                    "team": {"displayName": "Home FC"},
                    "participants": [
                        {"athlete": {"id": "10", "displayName": "Sub In"}},
                        {"athlete": {"id": "20", "displayName": "Sub Out"}},
                    ],
                }
            ]
        }
        events = extract_key_events(summary)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["type"], "substitution")
        self.assertEqual(event["clock_seconds"], 3600.0)
        self.assertEqual(event["participants"][0]["athlete_id"], "10")
        self.assertEqual(event["participants"][1]["athlete_id"], "20")

    def test_missing_key_events_returns_empty_list(self) -> None:
        self.assertEqual(extract_key_events({}), [])


class ComputeMinutesPlayedTests(unittest.TestCase):
    def test_starter_never_subbed_plays_full_match(self) -> None:
        roster = _roster({"1": True})
        minutes = compute_minutes_played([], roster)
        self.assertEqual(minutes["1"], 90.0)

    def test_starter_subbed_off_gets_partial_minutes(self) -> None:
        roster = _roster({"1": True, "2": False})
        events = [_sub_event(clock_seconds=3600.0, in_id="2", out_id="1")]  # 60'
        minutes = compute_minutes_played(events, roster)
        self.assertAlmostEqual(minutes["1"], 60.0)
        self.assertAlmostEqual(minutes["2"], 30.0)  # 90 - 60

    def test_unused_substitute_is_absent_not_zero(self) -> None:
        roster = _roster({"1": True, "2": False})
        minutes = compute_minutes_played([], roster)
        self.assertNotIn("2", minutes)

    def test_double_substitution_in_one_event_handles_both(self) -> None:
        roster = _roster({"1": True, "2": True, "3": False, "4": False})
        events = [
            _sub_event(clock_seconds=2700.0, in_id="3", out_id="1"),  # halftime sub
            _sub_event(clock_seconds=4500.0, in_id="4", out_id="2"),  # 75'
        ]
        minutes = compute_minutes_played(events, roster)
        self.assertAlmostEqual(minutes["1"], 45.0)
        self.assertAlmostEqual(minutes["3"], 45.0)
        self.assertAlmostEqual(minutes["2"], 75.0)
        self.assertAlmostEqual(minutes["4"], 15.0)

    def test_red_card_ends_playing_time_early(self) -> None:
        roster = _roster({"1": True})
        events = [_red_card_event(clock_seconds=3960.0, player_id="1")]  # 66'
        minutes = compute_minutes_played(events, roster)
        self.assertAlmostEqual(minutes["1"], 66.0)

    def test_substitute_who_enters_never_removed_plays_to_match_end(self) -> None:
        roster = _roster({"1": True, "2": False})
        events = [_sub_event(clock_seconds=4500.0, in_id="2", out_id="1")]  # 75'
        minutes = compute_minutes_played(events, roster)
        self.assertAlmostEqual(minutes["2"], 15.0)  # 90 - 75

    def test_custom_match_end_seconds_for_extra_time(self) -> None:
        roster = _roster({"1": True})
        minutes = compute_minutes_played([], roster, match_end_seconds=6600.0)  # 110 minutes
        self.assertAlmostEqual(minutes["1"], 110.0)


if __name__ == "__main__":
    unittest.main()
