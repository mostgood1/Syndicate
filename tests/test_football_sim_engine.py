from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.football.adapters import FootballSimulationAdapter
from syndicate.features.football.contracts import FootballGameFeatures
from syndicate.features.football.contracts import FootballPlayerFeatures
from syndicate.features.football.contracts import FootballEvaluationRecord
from syndicate.features.football.contracts import FootballSimulationInput
from syndicate.features.football.contracts import FootballTeamFeatures
from syndicate.features.football.features.advanced_metrics import build_advanced_metrics
from syndicate.features.football.features.loaders import build_football_simulation_input
from syndicate.features.football.features.player_usage import build_player_usage
from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.football.features.team_identity import canonical_team_metadata
from syndicate.features.football.features.team_metrics import to_football_game_features
from syndicate.features.football.season_validation import run_football_season_validation
from syndicate.features.football.season_validation import write_football_season_review
from syndicate.features.football.sim_engine.football_core import build_football_simulation_adapter
from syndicate.features.football.sim_engine.ncaaf_adapter import NcaafAdapter
from syndicate.features.football.sim_engine.nfl_adapter import NflAdapter


class FootballSimEngineTests(unittest.TestCase):
    def test_shared_adapter_supports_game_and_artifact_workflow(self) -> None:
        adapter = build_football_simulation_adapter("nfl")
        self.assertIsInstance(adapter, FootballSimulationAdapter)

        game_features = FootballGameFeatures(
            sport="nfl",
            date="2026-07-12",
            game_id="game-1",
            home_team="PHI",
            away_team="DAL",
        )
        simulation_input = FootballSimulationInput(sport="nfl", date="2026-07-12", games=(game_features,))
        simulation_output = adapter.simulate_games(simulation_input)
        artifacts = adapter.build_artifacts(simulation_output)
        evaluation = adapter.evaluate(simulation_output)

        self.assertEqual(simulation_output.sport, "nfl")
        self.assertEqual(simulation_output.date, "2026-07-12")
        self.assertIn("daily_summary", artifacts)
        self.assertIn("calibration", evaluation)

    def test_combined_player_usage_index_responds_to_each_usage_family(self) -> None:
        adapter = build_football_simulation_adapter("nfl")
        game_features = FootballGameFeatures(
            sport="nfl",
            date="2026-07-12",
            game_id="game-1",
            home_team="PHI",
            away_team="DAL",
        )
        player = FootballPlayerFeatures(
            sport="nfl",
            date="2026-07-12",
            player_id="player-1",
            player_name="Test Receiver",
            team="PHI",
            position="WR",
            usage_metrics={
                "snap_share": 0.20,
                "target_share": 0.25,
                "route_participation": 0.30,
                "air_yard_share": 0.15,
            },
        )
        simulation_input = FootballSimulationInput(sport="nfl", date="2026-07-12", games=(game_features,), players=(player,))

        base_output = adapter.simulate_games(simulation_input)
        base_player = base_output.player_outputs[0]

        def bumped_output(metric: str) -> dict[str, object]:
            bumped_metrics = dict(player.usage_metrics)
            bumped_metrics[metric] = float(bumped_metrics[metric]) * 1.1
            bumped_player = FootballPlayerFeatures(
                sport=player.sport,
                date=player.date,
                player_id=player.player_id,
                player_name=player.player_name,
                team=player.team,
                position=player.position,
                usage_metrics=bumped_metrics,
            )
            bumped_input = FootballSimulationInput(sport="nfl", date="2026-07-12", games=(game_features,), players=(bumped_player,))
            return adapter.simulate_games(bumped_input).player_outputs[0]

        for metric in ("route_participation", "target_share", "snap_share", "air_yard_share"):
            bumped_player = bumped_output(metric)
            self.assertGreater(
                bumped_player["projection"]["projection_mean"],
                base_player["projection"]["projection_mean"],
                msg=f"Expected {metric} to increase projection_mean",
            )
            self.assertGreaterEqual(bumped_player["usage_confidence"], base_player["usage_confidence"])

    def test_thin_sport_adapters_point_to_shared_football_core(self) -> None:
        self.assertEqual(NflAdapter().build().sport, "nfl")
        self.assertEqual(NcaafAdapter().build().sport, "ncaaf")

    def test_nfl_loader_falls_back_to_latest_available_season(self) -> None:
        adapter = NflAdapter().build()

        simulation_input = adapter.load_features(date="2026-07-12", selection=12, season=2026)

        self.assertEqual(simulation_input.sport, "nfl")
        self.assertGreaterEqual(len(simulation_input.games), 0)
        self.assertEqual(simulation_input.metadata.get("season") if isinstance(simulation_input.metadata, dict) else None, 2025)

    def test_feature_builder_normalizes_game_payload(self) -> None:
        game = {
            "gamePk": "g-1",
            "home": {"abbr": "PHI"},
            "away": {"abbr": "DAL"},
            "team_metrics": {"epa_play": 0.12},
            "defensive_metrics": {"epa_allowed": 0.18},
            "advanced_metrics": {"proe": 0.07},
        }

        features = to_football_game_features(game, sport="nfl", date="2026-07-12")

        self.assertEqual(features.game_id, "g-1")
        self.assertEqual(features.home_team, "PHI")
        self.assertEqual(features.away_team, "DAL")
        self.assertEqual(features.team_metrics["epa_play"], 0.12)
        self.assertEqual(features.team_metrics["proe"], 0.07)
        self.assertIsInstance(features.home_team_features, FootballTeamFeatures)
        self.assertEqual(features.home_team_features.adapter_metadata["side"], "home")

    def test_feature_builder_surfaces_home_and_away_advanced_aliases(self) -> None:
        game = {
            "gamePk": "g-2",
            "home": {"abbr": "PHI"},
            "away": {"abbr": "DAL"},
            "advanced_metrics": {
                "home_off_epa": 0.41,
                "away_off_epa": 0.32,
                "home_def_epa": 0.22,
                "away_def_epa": 0.29,
                "home_success_rate": 0.53,
                "away_success_rate": 0.48,
                "home_success_rate_allowed": 0.47,
                "away_success_rate_allowed": 0.52,
                "home_rzd_off_eff": 0.73,
                "away_rzd_off_eff": 0.68,
                "home_explosive_pass_rate": 0.19,
                "away_explosive_pass_rate": 0.16,
                "home_pace_secs_play": 27.1,
                "away_pace_secs_play": 28.3,
                "home_pass_rate": 0.58,
                "away_pass_rate": 0.42,
            },
        }

        features = to_football_game_features(game, sport="nfl", date="2026-07-12")

        self.assertEqual(features.team_metrics["home_offensive_epa"], 0.41)
        self.assertEqual(features.team_metrics["away_offensive_epa"], 0.32)
        self.assertEqual(features.team_metrics["home_success_rate"], 0.53)
        self.assertEqual(features.team_metrics["away_success_rate"], 0.48)
        self.assertEqual(features.team_metrics["home_pace_secs_play"], 27.1)
        self.assertEqual(features.team_metrics["away_pace_secs_play"], 28.3)
        self.assertEqual(features.epa_per_play, 0.41)
        self.assertEqual(features.success_rate_value, 0.53)
        self.assertEqual(features.proe_value, 0.58)
        self.assertEqual(features.red_zone_efficiency_value, 0.73)
        self.assertEqual(features.explosive_play_rate_value, 0.19)

    def test_build_advanced_metrics_normalizes_weekly_schema_aliases(self) -> None:
        metrics = build_advanced_metrics(
            {
                "game_id": "401857062",
                "season": "2026",
                "week": "12",
                "home_team": "CHI",
                "away_team": "DAL",
                "home_off_epa": "0.123",
                "home_def_epa": "0.456",
                "away_off_epa": "0.234",
                "away_def_epa": "0.567",
                "home_success_rate": "0.51",
                "away_success_rate": "0.47",
                "home_success_rate_allowed": "0.49",
                "away_success_rate_allowed": "0.53",
                "home_pass_rate": "0.61",
                "away_pass_rate": "0.39",
                "home_rzd_off_eff": "0.72",
                "away_rzd_off_eff": "0.68",
                "home_explosive_pass_rate": "0.18",
                "away_explosive_pass_rate": "0.22",
                "home_pace_secs_play": "27.4",
                "away_pace_secs_play": "28.1",
                "off_epa_diff": "0.11",
                "def_epa_diff": "-0.08",
                "pass_rate_diff": "0.04",
            }
        )

        self.assertEqual(metrics["home_offensive_epa"], 0.123)
        self.assertEqual(metrics["home_defensive_epa"], 0.456)
        self.assertEqual(metrics["away_offensive_epa"], 0.234)
        self.assertEqual(metrics["away_defensive_epa"], 0.567)
        self.assertEqual(metrics["home_success_rate"], 0.51)
        self.assertEqual(metrics["home_red_zone_efficiency"], 0.72)
        self.assertEqual(metrics["home_pace_secs_play"], 27.4)
        self.assertEqual(metrics["off_epa_diff"], 0.11)

    def test_loader_applies_advanced_metrics_from_manifest_rows(self) -> None:
        manifest_rows = [
            {
                "game_id": "401857062",
                "home_team": "CHI",
                "away_team": "DAL",
                "season": "2026",
                "week": "12",
                "home_off_epa": "0.123",
                "home_def_epa": "0.456",
                "home_success_rate": "0.51",
                "home_success_rate_allowed": "0.49",
                "pass_rate_diff": "0.04",
                "home_rzd_off_eff": "0.72",
                "home_explosive_pass_rate": "0.18",
                "home_pace_secs_play": "27.4",
            }
        ]

        game = {
            "gamePk": "401857062",
            "home": {"abbr": "CHI"},
            "away": {"abbr": "DAL"},
            "team_metrics": {},
            "defensive_metrics": {},
            "matchup_metrics": {},
            "pace_features": {},
            "market_features": {},
        }

        with patch("syndicate.features.football.features.loaders._manifest_games", return_value=manifest_rows):
            simulation_input = build_football_simulation_input(
                sport="nfl",
                date="2026-07-12",
                games=[game],
                season=2026,
                selection=12,
            )

        built_game = simulation_input.games[0]
        self.assertEqual(built_game.advanced_metrics["home_offensive_epa"], 0.123)
        self.assertEqual(built_game.advanced_metrics["home_success_rate"], 0.51)
        self.assertEqual(built_game.team_metrics["offensive_epa"], 0.123)
        self.assertEqual(built_game.team_metrics["success_rate"], 0.51)
        self.assertEqual(built_game.pace_features["pace"], 27.4)

    def test_loader_prefers_nflverse_derived_metrics_when_available(self) -> None:
        nflverse_rows = [
            {
                "season": 2026,
                "week": 12,
                "home_team": "PHI",
                "away_team": "DAL",
                "posteam": "PHI",
                "epa": 0.31,
                "success": 1,
                "play_type": "pass",
                "proe": 0.09,
                "defteam": "DAL",
            },
            {
                "season": 2026,
                "week": 12,
                "home_team": "PHI",
                "away_team": "DAL",
                "posteam": "DAL",
                "epa": -0.14,
                "success": 0,
                "play_type": "rush",
                "proe": 0.02,
                "defteam": "PHI",
            },
        ]

        game = {
            "gamePk": "401857062",
            "home": {"abbr": "PHI"},
            "away": {"abbr": "DAL"},
            "team_metrics": {},
            "defensive_metrics": {},
            "matchup_metrics": {},
            "pace_features": {},
            "market_features": {},
        }

        with patch("syndicate.features.football.features.loaders.build_nflverse_game_metrics", return_value={
            "source": "nflverse_play_by_play",
            "row_count": 2,
            "epa_per_play": 0.31,
            "success_rate": 1.0,
            "proe": 0.09,
            "home_offensive_epa": 0.31,
            "away_offensive_epa": -0.14,
            "home_defensive_epa": -0.14,
            "away_defensive_epa": 0.31,
            "home_success_rate": 1.0,
            "away_success_rate": 0.0,
            "home_pass_rate": 1.0,
            "away_pass_rate": 0.0,
            "home_rush_rate": 0.0,
            "away_rush_rate": 1.0,
        }):
            simulation_input = build_football_simulation_input(
                sport="nfl",
                date="2026-07-13",
                games=[game],
                season=2026,
                selection=12,
            )

        built_game = simulation_input.games[0]
        self.assertEqual(built_game.advanced_metrics["source"], "nflverse_play_by_play")
        self.assertEqual(built_game.team_metrics["epa_play"], 0.31)
        self.assertEqual(built_game.team_metrics["proe"], 0.09)
        self.assertEqual(built_game.team_metrics["home_offensive_epa"], 0.31)

    def test_loader_applies_rbsdm_derived_team_metrics_when_available(self) -> None:
        game = {
            "gamePk": "401857063",
            "home": {"abbr": "PHI"},
            "away": {"abbr": "DAL"},
            "team_metrics": {},
            "defensive_metrics": {},
            "matchup_metrics": {},
            "pace_features": {},
            "market_features": {},
        }

        with patch("syndicate.features.football.features.loaders.build_nflverse_game_metrics", return_value={}):
            with patch("syndicate.features.football.features.loaders.build_rbsdm_game_metrics", return_value={
                "source": "rbsdm_team_efficiency",
                "epa_per_play": 0.27,
                "success_rate": 0.54,
                "proe": 0.08,
                "home_offensive_epa": 0.27,
                "away_offensive_epa": -0.11,
                "home_defensive_epa": -0.11,
                "away_defensive_epa": 0.27,
                "home_success_rate": 0.54,
                "away_success_rate": 0.46,
                "home_success_rate_allowed": 0.42,
                "away_success_rate_allowed": 0.58,
                "home_pass_rate": 0.62,
                "away_pass_rate": 0.38,
                "home_red_zone_efficiency": 0.71,
                "away_red_zone_efficiency": 0.66,
                "home_explosive_play_rate": 0.17,
                "away_explosive_play_rate": 0.14,
                "home_pace_secs_play": 28.0,
                "away_pace_secs_play": 29.2,
            }):
                simulation_input = build_football_simulation_input(
                    sport="nfl",
                    date="2026-07-13",
                    games=[game],
                    season=2026,
                    selection=12,
                )

        built_game = simulation_input.games[0]
        self.assertEqual(built_game.advanced_metrics["source"], "rbsdm_team_efficiency")
        self.assertEqual(built_game.team_metrics["epa_play"], 0.27)
        self.assertEqual(built_game.team_metrics["proe"], 0.08)
        self.assertEqual(built_game.team_metrics["home_success_rate"], 0.54)
        self.assertEqual(built_game.team_metrics["home_red_zone_efficiency"], 0.71)

    def test_team_identity_canonicalizes_aliases_and_metadata(self) -> None:
        cases = [
            ("Philadelphia Eagles", "PHI", "NFC", "NFC East"),
            ("Los Angeles Rams", "LA", "NFC", "NFC West"),
            ("Washington Redskins", "WAS", "NFC", "NFC East"),
        ]

        for raw_value, expected_abbr, expected_conference, expected_division in cases:
            metadata = canonical_team_metadata(raw_value)
            self.assertEqual(canonical_team_abbr(raw_value), expected_abbr)
            self.assertEqual(metadata["team_abbr"], expected_abbr)
            self.assertEqual(metadata["conference"], expected_conference)
            self.assertEqual(metadata["division"], expected_division)

    def test_loader_canonicalizes_home_away_and_player_teams(self) -> None:
        game = {
            "gamePk": "401857064",
            "home": {"abbr": "Philadelphia Eagles"},
            "away": {"abbr": "Dallas Cowboys"},
            "home_team": "Philadelphia Eagles",
            "away_team": "Dallas Cowboys",
            "team_metrics": {},
            "defensive_metrics": {},
            "matchup_metrics": {},
            "pace_features": {},
            "market_features": {},
            "adapter_metadata": {
                "source": "real_betting_lines",
                "source_path": "c:/Users/tempadmin/OneDrive/Coding/Syndicate/data/nfl_source/real_betting_lines_2024_09_08.json",
                "schedule_source": "real_betting_lines",
            },
        }

        simulation_input = build_football_simulation_input(
            sport="nfl",
            date="2024-09-08",
            games=[game],
            season=2024,
            selection=1,
        )

        built_game = simulation_input.games[0]
        self.assertEqual(built_game.home_team, "PHI")
        self.assertEqual(built_game.away_team, "DAL")
        self.assertEqual(built_game.adapter_metadata["home_team_metadata"]["team_name"], "Philadelphia Eagles")
        self.assertEqual(built_game.adapter_metadata["away_team_metadata"]["division"], "NFC East")
        self.assertEqual(simulation_input.adapter_metadata["home_team_metadata"]["team_abbr"], "PHI")
        self.assertEqual(simulation_input.adapter_metadata["away_team_metadata"]["team_abbr"], "DAL")

    def test_2026_betting_line_schedule_source_flows_into_game_metadata(self) -> None:
        game = {
            "game_id": "2026-07-09-NE-SEA",
            "home_team": "SEA",
            "away_team": "NE",
            "game_date": "2026-07-09",
            "season": "2026",
            "week": "1",
            "team_metrics": {},
            "defensive_metrics": {},
            "matchup_metrics": {},
            "pace_features": {},
            "market_features": {
                "total": {"line": 44.5},
                "spread": {"home_line": -3.5},
                "moneyline": {"home": -192, "away": 160},
            },
            "adapter_metadata": {
                "source": "real_betting_lines",
                "source_path": "c:/Users/tempadmin/OneDrive/Coding/Syndicate/data/nfl_source/real_betting_lines_2026_07_09.json",
                "schedule_source": "real_betting_lines",
            },
        }

        simulation_input = build_football_simulation_input(
            sport="nfl",
            date="2026-07-09",
            games=[game],
            season=2026,
            selection=1,
        )

        built_game = simulation_input.games[0]
        self.assertEqual(built_game.adapter_metadata["schedule_source"], "real_betting_lines")
        self.assertIn("real_betting_lines_2026_07_09.json", built_game.adapter_metadata["schedule_source_path"])
        self.assertEqual(simulation_input.adapter_metadata["schedule_source"], "real_betting_lines")
        self.assertEqual(simulation_input.metadata["season"], 2026)

    def test_player_usage_builder_surfaces_explicit_aliases(self) -> None:
        usage = build_player_usage(
            {
                "player_id": "p-1",
                "player_name": "Test Player",
                "team": "PHI",
                "position": "WR",
                "usage_metrics": {
                    "snap_pct": 0.81,
                    "target_pct": 0.27,
                    "route_pct": 0.74,
                    "rush_pct": 0.08,
                    "goal_line_pct": 0.11,
                    "red_zone_pct": 0.22,
                    "air_yards_pct": 0.35,
                },
            },
            sport="nfl",
            date="2026-07-12",
        )

        self.assertEqual(usage["snap_pct"], 0.81)
        self.assertEqual(usage["target_pct"], 0.27)
        self.assertEqual(usage["route_pct"], 0.74)
        self.assertEqual(usage["rush_pct"], 0.08)
        self.assertEqual(usage["goal_line_pct"], 0.11)
        self.assertEqual(usage["red_zone_pct"], 0.22)
        self.assertEqual(usage["air_yards_pct"], 0.35)

    def test_player_usage_builder_applies_ftn_charting_rows_when_available(self) -> None:
        player = {
            "player_id": "p-2",
            "player_name": "Charted Player",
            "team": "PHI",
            "position": "WR",
            "usage_metrics": {},
        }

        charting_rows = (
            {
                "player_id": "p-2",
                "player_name": "Charted Player",
                "team": "PHI",
                "season": 2026,
                "week": 12,
                "snap_pct": 0.84,
                "target_pct": 0.29,
                "route_pct": 0.76,
                "carry_share": 0.04,
                "goal_line_pct": 0.07,
                "red_zone_pct": 0.24,
                "air_yards_pct": 0.39,
            },
            {
                "player_id": "p-2",
                "player_name": "Charted Player",
                "team": "PHI",
                "season": 2026,
                "week": 12,
                "snap_pct": 0.86,
                "target_pct": 0.31,
                "route_pct": 0.78,
                "carry_share": 0.05,
                "goal_line_pct": 0.08,
                "red_zone_pct": 0.26,
                "air_yards_pct": 0.41,
            },
        )

        with patch("syndicate.features.football.ingestion.ftn_charting_ingestion.load_ftn_charting_rows", return_value=charting_rows):
            usage = build_player_usage(player, sport="nfl", date="2026-07-12", season=2026, week=12)

        self.assertEqual(usage["source"], "ftn_charting")
        self.assertEqual(usage["snap_share"], 0.85)
        self.assertEqual(usage["target_share"], 0.3)
        self.assertEqual(usage["route_participation"], 0.77)
        self.assertEqual(usage["air_yard_share"], 0.4)
        self.assertEqual(usage["usage_metrics"]["snap_share"], 0.85)

    def test_shared_contracts_expose_end_state_evaluation_shape(self) -> None:
        record = FootballEvaluationRecord(
            sport="nfl",
            season=2026,
            date="2026-07-12",
            simulation_kind="game",
            calibration={"win_probability": {"brier": 0.11}},
            adapter_metadata={"source": "unit_test"},
        )

        self.assertEqual(record.sport, "nfl")
        self.assertEqual(record.calibration["win_probability"]["brier"], 0.11)
        self.assertEqual(record.adapter_metadata["source"], "unit_test")

    def test_persist_evaluation_writes_season_manifest_path(self) -> None:
        adapter = build_football_simulation_adapter("nfl")
        game_features = FootballGameFeatures(
            sport="nfl",
            date="2026-07-12",
            game_id="game-1",
            home_team="PHI",
            away_team="DAL",
        )
        simulation_input = FootballSimulationInput(sport="nfl", date="2026-07-12", games=(game_features,), adapter_metadata={"season": 2026})
        simulation_output = adapter.simulate_games(simulation_input)
        persisted = adapter.persist_evaluation(simulation_output, season=2026)

        self.assertIn("calibration_summary", persisted)
        self.assertIn("calibration_report", persisted)
        self.assertIn("backtest_manifest", persisted)

    def test_run_football_season_validation_builds_season_payload(self) -> None:
        payload = run_football_season_validation(sport="nfl", season=2026, dates=["2026-07-12"], selection=1)

        self.assertEqual(payload["sport"], "nfl")
        self.assertEqual(payload["season"], 2026)
        self.assertEqual(payload["run_count"], 1)
        self.assertIn("backtest_manifest", payload)
        self.assertEqual(len(payload["date_outputs"]), 1)

    def test_write_football_season_review_writes_markdown(self) -> None:
        payload = run_football_season_validation(sport="nfl", season=2026, dates=["2026-07-12"], selection=1)

        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "football_season_review.md"
            written_path = write_football_season_review(payload["review"], out_path)

            self.assertEqual(str(out_path), written_path)
            self.assertTrue(out_path.exists())
            content = out_path.read_text(encoding="utf-8")
            self.assertIn("# Football Season Review", content)
            self.assertIn("## Calibration", content)


if __name__ == "__main__":
    unittest.main()