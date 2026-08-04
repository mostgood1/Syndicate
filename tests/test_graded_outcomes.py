"""Tests for syndicate.features.shared.graded_outcomes -- the shared
GradedOutcome contract/registry that evaluation_settlement.py now delegates
to instead of hardcoding a per-sport grader inline."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import graded_outcomes as go


class RegistryTests(unittest.TestCase):
    def test_every_sport_has_a_registered_grader(self) -> None:
        for sport in ("mlb", "wnba", "nba", "nhl", "nfl", "ncaaf", "soccer", "ncaab"):
            self.assertIn(sport, go.GRADED_OUTCOME_GRADERS)

    def test_unknown_sport_returns_empty_not_an_error(self) -> None:
        self.assertEqual(go.graded_rows_for_date("esports", "2026-08-02"), [])

    def test_not_yet_available_sports_return_empty(self) -> None:
        for sport in ("soccer", "ncaab", "ncaaf"):
            self.assertEqual(go.graded_rows_for_date(sport, "2026-08-02"), [])


class LocalMarketAccuracyDelegationTests(unittest.TestCase):
    def test_mlb_filters_to_requested_date_and_graded_results_only(self) -> None:
        fake_payload = {
            "days": [
                {
                    "date": "2026-08-02",
                    "rows": {
                        "official": [
                            {"market": "moneyline", "selection": "KC", "player_name": None, "team": "KC", "title": "KC @ NYY", "line": None, "actual": None, "odds": -120, "result": "win", "profit_u": 0.83},
                            {"market": "moneyline", "selection": "BOS", "team": "BOS", "title": "BOS @ TB", "result": "pending"},
                        ]
                    },
                },
                {"date": "2026-08-03", "rows": {"official": [{"market": "moneyline", "result": "win"}]}},
            ]
        }
        with patch("syndicate.features.mlb.market_accuracy.build_market_accuracy_payload", return_value=fake_payload):
            rows = go.graded_rows_for_date("mlb", "2026-08-02")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sport"], "mlb")
        self.assertEqual(rows[0]["selection"], "KC")
        self.assertEqual(rows[0]["result"], "win")
        self.assertEqual(rows[0]["pnl"], 0.83)

    def test_mlb_exception_returns_empty(self) -> None:
        with patch("syndicate.features.mlb.market_accuracy.build_market_accuracy_payload", side_effect=RuntimeError("boom")):
            self.assertEqual(go.graded_rows_for_date("mlb", "2026-08-02"), [])

    def test_wnba_games_and_props_both_extracted(self) -> None:
        fake_payload = {
            "days": [
                {
                    "date": "2026-08-02",
                    "games": {"rows": [{"market": "moneyline", "side": "home", "home": "LV", "away": "NY", "line": None, "actual": None, "price": -150, "result": "loss"}]},
                    "props": {"rows": [{"market": "points", "side": "over", "player": "A. Wilson", "team": "LV", "line": 21.5, "actual": 24, "price": -110, "result": "win"}]},
                }
            ]
        }
        with patch("syndicate.features.shared.live_lens_local.build_local_market_accuracy_payload", return_value=fake_payload), \
             patch("syndicate.features.wnba.sources.processed_root", return_value=Path(".")):
            rows = go.graded_rows_for_date("wnba", "2026-08-02")
        self.assertEqual(len(rows), 2)
        markets = {row["market"] for row in rows}
        self.assertEqual(markets, {"moneyline", "points"})


class NflGraderTests(unittest.TestCase):
    def _write_schedule(self, root: Path, rows: list[dict]) -> None:
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        fieldnames = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team", "away_score", "home_score", "spread_line", "total_line", "away_moneyline", "home_moneyline", "stadium"]
        with (data_dir / "schedule_2026.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_home_favorite_covers_and_away_does_not(self) -> None:
        # Home favored by 10.5 (spread_line=-10.5), wins by 14 -> home covers, away doesn't.
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_schedule(
                root,
                [
                    {
                        "game_id": "2026_01_NE_SEA", "season": 2026, "game_type": "REG", "week": 1,
                        "gameday": "2026-09-09", "gametime": "20:20", "away_team": "NE", "home_team": "SEA",
                        "away_score": 10, "home_score": 24, "spread_line": -10.5, "total_line": 44.5,
                        "away_moneyline": 160, "home_moneyline": -192, "stadium": "Lumen Field",
                    }
                ],
            )
            with patch("syndicate.features.nfl.sources.default_nfl_source_root", return_value=root):
                rows = go.graded_rows_for_date("nfl", "2026-09-09")

        by_market_selection = {(r["market"], r["selection"]): r for r in rows}
        self.assertEqual(by_market_selection[("moneyline", "SEA")]["result"], "win")
        self.assertEqual(by_market_selection[("moneyline", "NE")]["result"], "loss")
        self.assertEqual(by_market_selection[("spread", "SEA")]["result"], "win")
        self.assertEqual(by_market_selection[("spread", "NE")]["result"], "loss")
        # actual_total = 34, line = 44.5 -> under wins
        self.assertEqual(by_market_selection[("total", "under")]["result"], "win")
        self.assertEqual(by_market_selection[("total", "over")]["result"], "loss")
        self.assertEqual(by_market_selection[("moneyline", "SEA")]["odds"], -192.0)

    def test_favorite_fails_to_cover_is_a_loss_not_a_win(self) -> None:
        # Home favored by 10.5 but only wins by 3 -> home fails to cover.
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_schedule(
                root,
                [
                    {
                        "game_id": "g1", "season": 2026, "game_type": "REG", "week": 1,
                        "gameday": "2026-09-09", "gametime": "20:20", "away_team": "NE", "home_team": "SEA",
                        "away_score": 20, "home_score": 23, "spread_line": -10.5, "total_line": 44.5,
                        "away_moneyline": 160, "home_moneyline": -192, "stadium": "",
                    }
                ],
            )
            with patch("syndicate.features.nfl.sources.default_nfl_source_root", return_value=root):
                rows = go.graded_rows_for_date("nfl", "2026-09-09")
        by_market_selection = {(r["market"], r["selection"]): r for r in rows}
        self.assertEqual(by_market_selection[("moneyline", "SEA")]["result"], "win")
        self.assertEqual(by_market_selection[("spread", "SEA")]["result"], "loss")
        self.assertEqual(by_market_selection[("spread", "NE")]["result"], "win")

    def test_push_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_schedule(
                root,
                [
                    {
                        "game_id": "g2", "season": 2026, "game_type": "REG", "week": 1,
                        "gameday": "2026-09-09", "gametime": "20:20", "away_team": "NE", "home_team": "SEA",
                        "away_score": 13, "home_score": 20, "spread_line": -7, "total_line": 33, "away_moneyline": 160, "home_moneyline": -192, "stadium": "",
                    }
                ],
            )
            with patch("syndicate.features.nfl.sources.default_nfl_source_root", return_value=root):
                rows = go.graded_rows_for_date("nfl", "2026-09-09")
        by_market_selection = {(r["market"], r["selection"]): r for r in rows}
        self.assertEqual(by_market_selection[("spread", "SEA")]["result"], "push")
        self.assertEqual(by_market_selection[("spread", "NE")]["result"], "push")
        self.assertEqual(by_market_selection[("total", "over")]["result"], "push")
        self.assertEqual(by_market_selection[("total", "under")]["result"], "push")

    def test_unplayed_games_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_schedule(
                root,
                [
                    {
                        "game_id": "g3", "season": 2026, "game_type": "REG", "week": 2,
                        "gameday": "2026-09-16", "gametime": "13:00", "away_team": "KC", "home_team": "LAC",
                        "away_score": "", "home_score": "", "spread_line": -3, "total_line": 45, "away_moneyline": 120, "home_moneyline": -140, "stadium": "",
                    }
                ],
            )
            with patch("syndicate.features.nfl.sources.default_nfl_source_root", return_value=root):
                rows = go.graded_rows_for_date("nfl", "2026-09-16")
        self.assertEqual(rows, [])

    def test_no_schedule_files_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("syndicate.features.nfl.sources.default_nfl_source_root", return_value=Path(tmp_dir)):
                self.assertEqual(go.graded_rows_for_date("nfl", "2026-09-09"), [])


if __name__ == "__main__":
    unittest.main()
