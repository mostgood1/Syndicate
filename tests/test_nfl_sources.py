from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.nfl import sources


class NflTargetWeekTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.nfl_root = os.path.join(self._tmp.name, "nfl_source")
        os.makedirs(self.nfl_root, exist_ok=True)
        self._root_patch = patch.object(sources, "default_nfl_source_root", return_value=Path(self.nfl_root))
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)

    def _write_schedule(self, season: int, rows: list[dict]) -> None:
        fieldnames = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team", "away_score", "home_score", "spread_line", "total_line", "away_moneyline", "home_moneyline", "stadium"]
        path = os.path.join(self.nfl_root, f"schedule_{season}.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in fieldnames}
                full.update(row)
                writer.writerow(full)

    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(sources.nfl_target_week(2099))

    def test_all_games_unplayed_returns_lowest_week(self) -> None:
        self._write_schedule(2026, [
            {"week": "1", "home_score": "", "away_score": ""},
            {"week": "2", "home_score": "", "away_score": ""},
        ])
        self.assertEqual(sources.nfl_target_week(2026), 1)

    def test_completed_weeks_are_skipped(self) -> None:
        self._write_schedule(2026, [
            {"week": "1", "home_score": "24", "away_score": "17"},
            {"week": "2", "home_score": "", "away_score": ""},
        ])
        self.assertEqual(sources.nfl_target_week(2026), 2)

    def test_all_games_played_returns_none(self) -> None:
        self._write_schedule(2026, [
            {"week": "1", "home_score": "24", "away_score": "17"},
        ])
        self.assertIsNone(sources.nfl_target_week(2026))


class BuildModuleLinksTests(unittest.TestCase):
    """Coverage for the two orphaned-nav-link additions to
    build_module_links (regular season)."""

    def test_props_link_present(self) -> None:
        links = sources.build_module_links(3, "Cards", season=2026)
        props_link = next((link for link in links if link["label"] == "Props"), None)
        self.assertIsNotNone(props_link)
        self.assertEqual(props_link["href"], "/nfl/props?season=2026&week=3")

    def test_market_board_link_present(self) -> None:
        links = sources.build_module_links(3, "Cards", season=2026)
        market_board_link = next((link for link in links if link["label"] == "Market Board"), None)
        self.assertIsNotNone(market_board_link)
        self.assertEqual(market_board_link["href"], "/nfl/market-board?season=2026&week=3")

    def test_active_label_still_marks_the_right_link_active(self) -> None:
        links = sources.build_module_links(3, "Props", season=2026)
        active_labels = [link["label"] for link in links if link["active"]]
        self.assertEqual(active_labels, ["Props"])


class BuildPreseasonModuleLinksTests(unittest.TestCase):
    """build_preseason_module_links already carried its own "Preseason
    Market Board" link before this session's fixes -- this just guards
    that it stays present and that no "Props" link is ever added here
    (preseason has no real prop-odds source, see nfl/props.py's
    docstring)."""

    def test_market_board_link_present(self) -> None:
        links = sources.build_preseason_module_links(1, "Preseason Cards", season=2026)
        labels = [link["label"] for link in links]
        self.assertIn("Preseason Market Board", labels)
        market_board_link = next(link for link in links if link["label"] == "Preseason Market Board")
        self.assertEqual(market_board_link["href"], "/nfl/preseason/market-board?season=2026&week=1")

    def test_no_props_link(self) -> None:
        links = sources.build_preseason_module_links(1, "Preseason Cards", season=2026)
        labels = [link["label"] for link in links]
        self.assertNotIn("Props", labels)


if __name__ == "__main__":
    unittest.main()
