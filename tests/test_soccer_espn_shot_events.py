from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer.ingestion.espn_shot_events import aggregate_season_shot_events
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events


def _play(type_key: str, type_text: str, text: str, *, team: str = "Home FC", shooter_id: str = "p1") -> dict:
    return {
        "type": {"text": type_text, "type": type_key},
        "period": {"number": 1},
        "clock": {"value": 1000.0, "displayValue": "17'"},
        "team": {"displayName": team},
        "participants": [{"athlete": {"id": shooter_id, "displayName": "Shooter"}}],
        "text": text,
    }


class ExtractShotEventsTests(unittest.TestCase):
    def test_extracts_only_shot_type_events(self) -> None:
        summary = {
            "commentary": [
                {"play": _play("shot-on-target", "Shot On Target", "shot from the centre of the box is saved.")},
                {"play": _play("foul", "Foul", "Foul by Someone.")},
                {"play": _play("corner-awarded", "Corner Awarded", "Corner, Home FC.")},
            ]
        }
        rows = extract_shot_events(summary, event_id="e1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "saved")

    def test_classifies_box_vs_outside_box_vs_six_yard(self) -> None:
        cases = [
            ("shot from outside the box is high and wide.", "outside_box"),
            ("shot from the centre of the box is close.", "box"),
            ("shot from the left side of the six yard box is saved.", "six_yard_box"),
            ("shot from more than 35 yards misses to the right.", "outside_box"),
            ("shot from a difficult angle is saved.", "outside_box"),
        ]
        for text, expected in cases:
            summary = {"commentary": [{"play": _play("shot-off-target", "Shot Off Target", text)}]}
            rows = extract_shot_events(summary, event_id="e1")
            self.assertEqual(rows[0]["location"], expected, msg=text)

    def test_unrecognized_location_text_is_unknown(self) -> None:
        summary = {"commentary": [{"play": _play("shot-off-target", "Shot Off Target", "a wild swing at nothing")}]}
        rows = extract_shot_events(summary, event_id="e1")
        self.assertEqual(rows[0]["location"], "unknown")

    def test_from_corner_flag(self) -> None:
        summary = {
            "commentary": [
                {"play": _play("goal", "Goal", "Goal! Header from the centre of the box following a corner.")}
            ]
        }
        rows = extract_shot_events(summary, event_id="e1")
        self.assertTrue(rows[0]["from_corner"])
        self.assertEqual(rows[0]["outcome"], "goal")

    def test_goal_variant_types_are_all_classified_as_goal(self) -> None:
        # ESPN keys goal variants distinctly ("goal", "goal---volley",
        # "goal---header", ...); every one must count as a goal or the
        # conversion-rate denominator quietly drops real goals.
        for type_key in ("goal", "goal---volley", "goal---header", "goal---penalty"):
            summary = {"commentary": [{"play": _play(type_key, "Goal", "shot from the box")}]}
            rows = extract_shot_events(summary, event_id="e1")
            self.assertEqual(len(rows), 1, msg=type_key)
            self.assertEqual(rows[0]["outcome"], "goal", msg=type_key)

    def test_own_goal_is_not_classified_as_a_shot(self) -> None:
        summary = {"commentary": [{"play": _play("own-goal", "Own Goal", "own goal")}]}
        rows = extract_shot_events(summary, event_id="e1")
        self.assertEqual(rows, [])

    def test_outcome_classification_for_all_types(self) -> None:
        cases = [("goal", "goal"), ("shot-on-target", "saved"), ("shot-off-target", "off_target"), ("shot-blocked", "blocked")]
        for type_key, expected in cases:
            summary = {"commentary": [{"play": _play(type_key, "x", "shot from the box")}]}
            rows = extract_shot_events(summary, event_id="e1")
            self.assertEqual(rows[0]["outcome"], expected)

    def test_missing_commentary_returns_empty(self) -> None:
        self.assertEqual(extract_shot_events({}, event_id="e1"), [])


class AggregateSeasonShotEventsTests(unittest.TestCase):
    def test_aggregates_across_matches_and_skips_fetch_failures(self) -> None:
        events = [{"event_id": "e1"}, {"event_id": "e2"}]
        summaries = {
            "e1": {"commentary": [{"play": _play("goal", "Goal", "shot from the box")}]},
        }

        def _fetch(league: str, event_id: str) -> dict:
            if event_id not in summaries:
                raise RuntimeError("boom")
            return summaries[event_id]

        with patch(
            "syndicate.features.soccer.ingestion.espn_shot_events.fetch_completed_events", return_value=events
        ), patch("syndicate.features.soccer.ingestion.espn_shot_events.fetch_match_summary", side_effect=_fetch):
            rows = aggregate_season_shot_events("epl", date_windows=["20250101-20250107"])
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
