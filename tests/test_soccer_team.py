from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer import team


class PositionRankTests(unittest.TestCase):
    def test_goalkeeper_sorts_before_outfield_positions(self) -> None:
        self.assertLess(team._position_rank("Goalkeeper"), team._position_rank("Defender"))
        self.assertLess(team._position_rank("Defender"), team._position_rank("Midfielder"))
        self.assertLess(team._position_rank("Midfielder"), team._position_rank("Forward"))

    def test_attacker_and_forward_rank_together(self) -> None:
        self.assertEqual(team._position_rank("Forward"), team._position_rank("Attacker"))

    def test_unknown_position_sorts_last(self) -> None:
        self.assertGreater(team._position_rank("Utility"), team._position_rank("Forward"))
        self.assertGreater(team._position_rank(""), team._position_rank("Goalkeeper"))


class PlayerRankCardTests(unittest.TestCase):
    def test_builds_card_with_headshot_and_metrics(self) -> None:
        row = {
            "player_name": "Bukayo Saka",
            "position": "Forward",
            "jersey": "7",
            "age": "23",
            "height": "70",
            "weight": "150",
            "headshot_url": "https://example.com/saka.png",
        }
        card = team._player_rank_card(row, league="epl", team_name="Arsenal")
        self.assertEqual(card["title"], "Bukayo Saka")
        self.assertEqual(card["badge"], "#7")
        self.assertEqual(card["headshot_url"], "https://example.com/saka.png")
        metrics = {m["label"]: m["value"] for m in card["metrics"]}
        self.assertEqual(metrics["Jersey"], "7")

    def test_missing_jersey_falls_back_to_dash_badge(self) -> None:
        row = {"player_name": "Reserve Player", "position": "Defender"}
        card = team._player_rank_card(row, league="epl", team_name="Arsenal")
        self.assertEqual(card["badge"], "-")
        self.assertIsNone(card["headshot_url"])


class FixtureRankCardTests(unittest.TestCase):
    def test_home_fixture_labeled_vs_opponent(self) -> None:
        row = {
            "home_team": "Arsenal", "away_team": "Chelsea", "week": 3,
            "status_state": "pre", "date": "2026-08-21T15:00Z", "event_id": "1",
        }
        card = team._fixture_rank_card(row, league="epl", team_name="Arsenal", season=2026)
        self.assertEqual(card["title"], "vs Chelsea")
        self.assertIn("/soccer/epl/game/1?week=3&season=2026", card["href"])

    def test_away_fixture_labeled_at_opponent(self) -> None:
        row = {
            "home_team": "Chelsea", "away_team": "Arsenal", "week": 3,
            "status_state": "pre", "date": "2026-08-21T15:00Z", "event_id": "1",
        }
        card = team._fixture_rank_card(row, league="epl", team_name="Arsenal", season=2026)
        self.assertEqual(card["title"], "@ Chelsea")

    def test_completed_fixture_shows_score(self) -> None:
        row = {
            "home_team": "Arsenal", "away_team": "Chelsea", "week": 3,
            "status_state": "post", "home_score": "2", "away_score": "1",
            "date": "2026-08-21T15:00Z", "event_id": "1",
        }
        card = team._fixture_rank_card(row, league="epl", team_name="Arsenal", season=2026)
        self.assertEqual(card["badge"], "1-2")

    def test_fixture_without_week_has_no_href(self) -> None:
        row = {"home_team": "Arsenal", "away_team": "Chelsea", "week": None, "status_state": "pre", "date": "", "event_id": "1"}
        card = team._fixture_rank_card(row, league="epl", team_name="Arsenal", season=2026)
        self.assertIsNone(card["href"])


class TeamSelectControlTests(unittest.TestCase):
    def test_lists_every_team_sorted_by_name(self) -> None:
        teams = [{"team_id": "2", "name": "Zebra FC"}, {"team_id": "1", "name": "Alpha FC"}]
        with patch.object(team, "all_teams", return_value=teams):
            control = team.team_select_control("epl", "1", page_suffix="roster", query_suffix="?season=2026")
        self.assertEqual([opt["label"] for opt in control["options"]], ["Alpha FC", "Zebra FC"])
        self.assertEqual(control["value"], "1")
        self.assertIn("/roster?season=2026", control["onchange"])


if __name__ == "__main__":
    unittest.main()
