from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer import archive


def _simulated_game(gid: str) -> dict:
    return {"gamePk": gid, "away": {"name": "Away FC"}, "home": {"name": "Home FC"}, "panels": [{"eyebrow": "Match projection"}]}


def _unsimulated_game(gid: str) -> dict:
    return {"gamePk": gid, "away": {"name": "Away FC"}, "home": {"name": "Home FC"}, "panels": [{"eyebrow": "Not yet simulated"}]}


class WeekCardTests(unittest.TestCase):
    def test_counts_simulated_vs_total_matches(self) -> None:
        games = [_simulated_game("1"), _unsimulated_game("2"), _unsimulated_game("3")]
        with patch.object(archive, "week_games", return_value=games), \
             patch.object(archive, "week_label", return_value="Week 1 (2026-08-01 to 2026-08-07)"):
            card = archive._week_card("epl", 2026, 1)
        metrics = {m["label"]: m["value"] for m in card["metrics"]}
        self.assertEqual(metrics["Matches"], "3")
        self.assertEqual(metrics["Simulated"], "1")
        self.assertEqual(card["href"], "/soccer/epl/cards?week=1&season=2026")

    def test_empty_week_reports_no_fixtures(self) -> None:
        with patch.object(archive, "week_games", return_value=[]), \
             patch.object(archive, "week_label", return_value="Week 1"):
            card = archive._week_card("epl", 2026, 1)
        self.assertEqual(card["list_items"], ["No fixtures on the schedule for this week."])


class BuildArchivePageContextTests(unittest.TestCase):
    def test_windows_around_the_selected_week_and_sorts_it_first(self) -> None:
        with patch.object(archive, "available_weeks", return_value=list(range(1, 21))), \
             patch.object(archive, "default_week", return_value=10), \
             patch.object(archive, "week_games", return_value=[]):
            context = archive.build_archive_page_context("epl", week=10, season=2026)
        cards = context["rank_cards"]
        self.assertEqual(cards[0]["title"], "10")
        self.assertLessEqual(len(cards), archive._WINDOW)

    def test_no_stored_weeks_sets_empty_state(self) -> None:
        with patch.object(archive, "available_weeks", return_value=[]), \
             patch.object(archive, "default_week", return_value=1), \
             patch.object(archive, "week_games", return_value=[]):
            context = archive.build_archive_page_context("epl", season=2026)
        self.assertEqual(context["rank_cards"], [])
        self.assertIsNotNone(context["empty_state"])


if __name__ == "__main__":
    unittest.main()
