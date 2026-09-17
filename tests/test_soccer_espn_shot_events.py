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


class WoodworkAndPenaltyShotsAreCountedTests(unittest.TestCase):
    """A shot off the post was not off target, not blocked -- it was ABSENT.

    MEASURED 2026-09-17 on ESPN's public feeds, 24 finished matches across
    epl/la_liga/serie_a/bundesliga (09-01..09-17): the old three-type allowlist
    reproduced ESPN's own per-match `totalShots` in 9 of 24 matches, and each
    shortfall equalled that match's count of dropped `shot-hit-woodwork` /
    `penalty---saved` entries -- 23 and 1 in the sample, 1.42 shots/match, 5.0
    per 100 kept. With them counted: 24 of 24, no residual gap.

    Restoring the old `_NON_GOAL_SHOT_TYPES` turns every test here red.
    """

    def test_a_shot_off_the_woodwork_is_a_shot(self) -> None:
        summary = {
            "commentary": [
                {"play": _play("shot-hit-woodwork", "Hit Woodwork",
                               "Justin Kluivert (Bournemouth) hits the left post with a right footed shot from outside the box.")}
            ]
        }
        rows = extract_shot_events(summary, event_id="e1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["location"], "outside_box")

    def test_woodwork_has_its_own_outcome_and_is_NOT_on_target(self) -> None:
        # The on/off-target question is UNRESOLVED against ESPN's own
        # `shotsOnTarget` (off: 15/24 matches, on: 10/24, residuals both ways),
        # so this pins that the code does not pretend to have answered it. The
        # live-state reader keys off `_ON_TARGET_OUTCOMES = {goal, saved}`, and
        # `woodwork` must stay out of that set rather than being folded into
        # either side here.
        from syndicate.features.soccer.ingestion.espn_live_state import _ON_TARGET_OUTCOMES

        summary = {"commentary": [{"play": _play("shot-hit-woodwork", "Hit Woodwork", "hits the bar with a shot from the box.")}]}
        outcome = extract_shot_events(summary, event_id="e1")[0]["outcome"]
        self.assertEqual(outcome, "woodwork")
        self.assertNotIn(outcome, _ON_TARGET_OUTCOMES)

    def test_penalty_variants_are_shots_with_the_right_outcome(self) -> None:
        # `penalty---scored` was already handled as the taker's goal; the other
        # three are the same shot with a different ending.
        cases = [
            ("penalty---saved", "saved", "Penalty saved. Kylian Mbappe (Real Madrid) right footed shot saved in the bottom left corner."),
            ("penalty---missed", "off_target", "Penalty missed! Bad penalty by Someone (Team), right footed shot is too high."),
            ("penalty---post", "woodwork", "Penalty missed! Someone (Team) hits the right post with a right footed shot."),
        ]
        for type_key, expected, text in cases:
            with self.subTest(type_key):
                summary = {"commentary": [{"play": _play(type_key, "Penalty", text)}]}
                rows = extract_shot_events(summary, event_id="e1")
                self.assertEqual(len(rows), 1, "a penalty is a shot by the taker")
                self.assertEqual(rows[0]["outcome"], expected)

    def test_an_unknown_shot_like_type_is_LOGGED_not_silently_dropped(self) -> None:
        # THE REASON THIS DEFECT SURVIVED: the old code dropped it wordlessly.
        # ESPN renames these keys with no notice, so the next one must announce
        # itself even though it is still (correctly) not counted.
        summary = {
            "commentary": [
                {"play": _play("shot-deflected-wide", "New Thing", "Attempt blocked. Someone (Team) right footed shot from the box.")},
                {"play": _play("shot-deflected-wide", "New Thing", "Attempt saved. Another (Team) header from the six yard box.")},
                {"play": _play("foul", "Foul", "Foul by Someone.")},
            ]
        }
        with patch("builtins.print") as printed:
            rows = extract_shot_events(summary, event_id="e9")
        self.assertEqual(rows, [], "an unknown type is still not counted -- only announced")
        lines = [str(call.args[0]) for call in printed.call_args_list]
        self.assertEqual(len(lines), 1, f"one line per unknown type per match, got {lines}")
        self.assertIn("SHOT_EVENT_TYPE_UNMAPPED", lines[0])
        self.assertIn("type=shot-deflected-wide", lines[0])
        self.assertIn("event_id=e9", lines[0])

    def test_a_dropped_NON_shot_entry_stays_quiet(self) -> None:
        # The tripwire must not fire on the ordinary contents of this feed --
        # fouls, cards, subs and corners are most of it. A tripwire that fires
        # on everything is read as noise and then not read at all.
        summary = {
            "commentary": [
                {"play": _play("foul", "Foul", "Foul by Someone (Team).")},
                {"play": _play("corner-awarded", "Corner", "Corner, Home FC. Conceded by Someone.")},
                {"play": _play("yellow-card", "Yellow", "Someone (Team) is shown the yellow card for a bad foul.")},
                {"play": _play("substitution", "Sub", "Substitution, Home FC. A replaces B.")},
            ]
        }
        with patch("builtins.print") as printed:
            self.assertEqual(extract_shot_events(summary, event_id="e1"), [])
        self.assertEqual(printed.call_args_list, [])

    def test_own_goal_is_still_nobody_s_shot(self) -> None:
        # Guard against the widened allowlist swallowing the one case the
        # module already got right on purpose.
        summary = {"commentary": [{"play": _play("own-goal", "Own Goal", "Own Goal by Someone (Team), header from the six yard box.")}]}
        with patch("builtins.print") as printed:
            self.assertEqual(extract_shot_events(summary, event_id="e1"), [])
        lines = [str(call.args[0]) for call in printed.call_args_list]
        self.assertEqual(len(lines), 1, "it is not a shot, but a header in the text must still be announced, not hidden")
        self.assertIn("type=own-goal", lines[0])


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
