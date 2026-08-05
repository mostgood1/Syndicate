"""Coverage for syndicate/features/nfl/preseason_cards.py -- real
preseason card-building path. Fixture preseason projection CSV under a
tempdir-patched source root, same pattern as the regular-season cards
fallback tests. Explicit regression guard for the exact top-level
away/home logo_url omission bug already hit once this session in NCAAF's
equivalent card-building function.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.nfl import cards as nfl_cards
from syndicate.features.nfl import injury_adjustment as inj
from syndicate.features.nfl import preseason_cards as pc
from syndicate.features.nfl import preseason_projection as pp
from syndicate.features.nfl import sources as nfl_sources


class PreseasonCardsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        # inj (injury_adjustment.py) is patched too -- preseason_depth.py's
        # likely_snap_leaders()/likely_starters_sitting() read the real
        # depth chart via injury_adjustment._depth_chart_rows(), which
        # resolves its own default_nfl_source_root() independently; without
        # this, these tests would silently read real production depth data
        # instead of this fixture's controlled (empty) tempdir.
        for target in (pc, nfl_sources, inj):
            patcher = patch.object(target, "default_nfl_source_root", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        nfl_cards._team_branding_index.cache_clear()
        self.addCleanup(nfl_cards._team_branding_index.cache_clear)

    def _write_projection(self, season: int, week: int, rows: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"smartsim2_preseason_projections_{season}_wk{week}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(pp.PRESEASON_PROJECTION_CSV_COLUMNS))
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in pp.PRESEASON_PROJECTION_CSV_COLUMNS}
                full.update(row)
                writer.writerow(full)

    def _projection_row(self, *, game_id="g1", home_team="ARI", away_team="CAR", week=1, share=0.92):
        return {
            "game_id": game_id, "season": "2026", "week": str(week),
            "home_team": home_team, "away_team": away_team,
            "home_score_mean": "24.3", "away_score_mean": "20.9",
            "margin_mean": "3.4", "total_mean": "45.2",
            "margin_stdev": "27.9", "total_stdev": "23.3",
            "home_win_rate": "0.59", "seeds_used": "100",
            "profile_name": "nfl_preseason_v1",
            "rating_source": "nflverse_pbp_epa_prior_season_shrunk[prior_season_fallback/prior_season_fallback]",
            "generated_at": "2026-08-05T00:00:00Z",
            "nonstarter_participation_share": str(share),
            "shrinkage_applied": str(share),
            "uncertainty_note": f"Preseason projection -- shrunk toward league-neutral by {share:.0%}.",
        }


    def _write_odds(self, season: int, rows: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fieldnames = ["game_id", "season", "week", "home_team", "away_team", "home_moneyline", "away_moneyline", "spread_home", "total_line", "book", "fetched_at"]
        path = self.root / f"preseason_odds_{season}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in fieldnames}
                full.update(row)
                writer.writerow(full)


class LoadPreseasonOddsTests(PreseasonCardsTestCase):
    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(pc._load_preseason_odds(2026), {})

    def test_real_row_keyed_by_away_home_pair(self) -> None:
        self._write_odds(2026, [{"game_id": "g1", "season": "2026", "week": "1", "home_team": "ARI", "away_team": "CAR", "home_moneyline": "105", "away_moneyline": "-125", "spread_home": "1.5", "total_line": "35.5", "book": "draftkings"}])
        odds = pc._load_preseason_odds(2026)
        self.assertIn(("CAR", "ARI"), odds)
        self.assertEqual(odds[("CAR", "ARI")]["book"], "draftkings")


class MarketPanelTests(unittest.TestCase):
    def test_none_market_returns_none(self) -> None:
        self.assertIsNone(pc._market_panel(None, away_name="Carolina Panthers", home_name="Arizona Cardinals"))

    def test_real_moneylines_formatted_for_both_teams(self) -> None:
        panel = pc._market_panel(
            {"home_moneyline": "105", "away_moneyline": "-125", "spread_home": "1.5", "total_line": "35.5", "book": "draftkings"},
            away_name="Carolina Panthers", home_name="Arizona Cardinals",
        )
        self.assertIn("Carolina Panthers", panel["items"][0])
        self.assertIn("Arizona Cardinals", panel["items"][0])
        self.assertIn("draftkings".title(), panel["eyebrow"])

    def test_positive_spread_home_means_away_team_favored(self) -> None:
        panel = pc._market_panel(
            {"home_moneyline": "105", "away_moneyline": "-125", "spread_home": "1.5", "total_line": "35.5", "book": "draftkings"},
            away_name="Carolina Panthers", home_name="Arizona Cardinals",
        )
        self.assertIn("Carolina Panthers favored", panel["items"][1])

    def test_negative_spread_home_means_home_team_favored(self) -> None:
        panel = pc._market_panel(
            {"home_moneyline": "-140", "away_moneyline": "120", "spread_home": "-2.5", "total_line": "42.0", "book": "fanduel"},
            away_name="Away Team", home_name="Home Team",
        )
        self.assertIn("Home Team favored", panel["items"][1])

    def test_body_discloses_reference_only(self) -> None:
        panel = pc._market_panel(
            {"home_moneyline": "105", "away_moneyline": "-125", "spread_home": "1.5", "total_line": "35.5", "book": "draftkings"},
            away_name="Away", home_name="Home",
        )
        self.assertIn("not blended into the model projection", panel["body"])


class GameFromPreseasonProjectionTests(PreseasonCardsTestCase):
    def test_top_level_away_home_have_logo_and_color_fields(self) -> None:
        # Regression guard for the exact bug class hit once this session:
        # a similarly-shaped NCAAF card-building function omitted
        # logo_url/primary_color/secondary_color at the top level and
        # silently broke every team logo in production.
        self._write_projection(2026, 1, [self._projection_row()])
        projections = pp.read_preseason_projection_artifact(season=2026, week=1, data_root=self.root)
        game = pc._game_from_preseason_projection(projections[0], 2026, 1)
        self.assertIn("logo_url", game["away"])
        self.assertIn("primary_color", game["away"])
        self.assertIn("secondary_color", game["away"])
        self.assertIn("logo_url", game["home"])
        self.assertIn("primary_color", game["home"])
        self.assertIn("secondary_color", game["home"])

    def test_summary_contains_uncertainty_disclosure(self) -> None:
        self._write_projection(2026, 1, [self._projection_row()])
        projections = pp.read_preseason_projection_artifact(season=2026, week=1, data_root=self.root)
        game = pc._game_from_preseason_projection(projections[0], 2026, 1)
        self.assertIn("shrunk toward league-neutral", game["summary"])
        self.assertIn("much lower confidence", game["summary"])

    def test_panel_body_contains_uncertainty_note(self) -> None:
        self._write_projection(2026, 1, [self._projection_row()])
        projections = pp.read_preseason_projection_artifact(season=2026, week=1, data_root=self.root)
        game = pc._game_from_preseason_projection(projections[0], 2026, 1)
        panel_bodies = [panel["body"] for panel in game["panels"]]
        self.assertTrue(any("shrunk toward league-neutral" in body for body in panel_bodies))

    def test_depth_chart_panels_present_for_both_teams(self) -> None:
        self._write_projection(2026, 1, [self._projection_row()])
        projections = pp.read_preseason_projection_artifact(season=2026, week=1, data_root=self.root)
        game = pc._game_from_preseason_projection(projections[0], 2026, 1)
        depth_panels = [panel for panel in game["panels"] if panel["eyebrow"] == "Real depth chart"]
        self.assertEqual(len(depth_panels), 2)

    def test_status_shows_real_week_label(self) -> None:
        self._write_projection(2026, 3, [self._projection_row(week=3)])
        projections = pp.read_preseason_projection_artifact(season=2026, week=3, data_root=self.root)
        game = pc._game_from_preseason_projection(projections[0], 2026, 3)
        self.assertEqual(game["status"], "Preseason Week 2 (dress rehearsal)")


class BuildPreseasonCardsPageContextTests(PreseasonCardsTestCase):
    def test_renders_real_games_for_week(self) -> None:
        self._write_projection(2026, 1, [self._projection_row()])
        ctx = pc.build_preseason_cards_page_context(1, season=2026)
        self.assertEqual(len(ctx["games"]), 1)
        self.assertIn("Hall of Fame Weekend", ctx["date"])
        self.assertIsNone(ctx["empty_state"])

    def test_empty_week_shows_empty_state(self) -> None:
        ctx = pc.build_preseason_cards_page_context(1, season=2026)
        self.assertEqual(ctx["games"], [])
        self.assertIsNotNone(ctx["empty_state"])

    def test_route_path_is_preseason_scoped(self) -> None:
        ctx = pc.build_preseason_cards_page_context(1, season=2026)
        self.assertEqual(ctx["route_path"], "/nfl/preseason/cards")

    def test_default_week_prefers_real_calendar_target_over_latest(self) -> None:
        self._write_projection(2026, 1, [self._projection_row(week=1)])
        self._write_projection(2026, 3, [self._projection_row(game_id="g2", week=3, share=0.55)])
        schedule_fieldnames = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team", "away_score", "home_score", "status", "venue"]
        with (self.root / "schedule_preseason_2026.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=schedule_fieldnames)
            writer.writeheader()
            writer.writerow({**{k: "" for k in schedule_fieldnames}, "game_id": "g1", "week": "1", "home_team": "ARI", "away_team": "CAR", "home_score": "", "away_score": ""})
            writer.writerow({**{k: "" for k in schedule_fieldnames}, "game_id": "g2", "week": "3", "home_team": "ARI", "away_team": "CAR", "home_score": "", "away_score": ""})
        ctx = pc.build_preseason_cards_page_context(0, season=2026)
        self.assertIn("Hall of Fame Weekend", ctx["date"])


class BuildNflPreseasonMarketBoardTests(PreseasonCardsTestCase):
    """Coverage for pc.build_nfl_preseason_market_board -- mirrors the
    regular-season builder's tests in tests/test_nfl_market_board.py, but
    reads preseason's own artifacts (smartsim2_preseason_projections_*.csv /
    preseason_odds_{season}.csv) via a tempdir-patched source root instead
    of mocking read_projection_artifact/_nfl_real_lines_for_matchup."""

    def test_builds_joined_game_market_rows(self) -> None:
        self._write_projection(2026, 1, [self._projection_row()])
        self._write_odds(
            2026,
            [
                {
                    "game_id": "g1",
                    "season": "2026",
                    "week": "1",
                    "home_team": "ARI",
                    "away_team": "CAR",
                    "home_moneyline": "-125",
                    "away_moneyline": "105",
                    "spread_home": "-1.5",
                    "total_line": "35.5",
                    "book": "draftkings",
                }
            ],
        )

        board = pc.build_nfl_preseason_market_board(2026, 1)

        self.assertEqual(board["season"], 2026)
        self.assertEqual(board["week"], 1)
        self.assertEqual(board["route_path"], "/nfl/preseason/market-board")
        self.assertFalse(board["using_sample_data"])
        self.assertEqual(len(board["games"]), 1)

        game = board["games"][0]
        self.assertEqual(game["matchup"], "CAR @ ARI")
        self.assertEqual(game["away_abbr"], "CAR")
        self.assertEqual(game["home_abbr"], "ARI")
        self.assertEqual(game["game_state"], "pregame")
        self.assertIn("away_logo", game)
        self.assertIn("home_logo", game)

        markets = sorted({row["market"] for row in game["rows"]})
        self.assertEqual(markets, ["Moneyline", "Spread", "Total"])
        self.assertFalse(any(row["market_type"] == "prop" for row in game["rows"]))

        moneyline_home = next(row for row in game["rows"] if row["market"] == "Moneyline" and row["side"] == "home")
        self.assertEqual(moneyline_home["odds"], -125.0)
        self.assertIsNotNone(moneyline_home["sim_projection"])

        self.assertIn("shrunk toward league-neutral", board["uncertainty_note"])

    def test_no_odds_file_still_returns_game_with_no_market_rows(self) -> None:
        self._write_projection(2026, 1, [self._projection_row()])

        board = pc.build_nfl_preseason_market_board(2026, 1)

        self.assertEqual(len(board["games"]), 1)
        self.assertEqual(board["games"][0]["rows"], [])

    def test_empty_week_returns_default_uncertainty_note(self) -> None:
        board = pc.build_nfl_preseason_market_board(2026, 1)

        self.assertEqual(board["games"], [])
        self.assertIn("shrunk toward league-neutral", board["uncertainty_note"])


if __name__ == "__main__":
    unittest.main()
