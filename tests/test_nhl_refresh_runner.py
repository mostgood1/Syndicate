from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from syndicate import local_nhl_odds as nhl_odds


class NhlRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nhl_oddsapi.py"
        spec = importlib.util.spec_from_file_location("test_refresh_nhl_oddsapi", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_script_bootstraps_repo_root_before_syndicate_imports(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nhl_oddsapi.py"
        content = script_path.read_text(encoding="utf-8")

        self.assertLess(content.index("sys.path.insert(0, str(REPO_ROOT))"), content.index("from syndicate.features.shared.refresh_state_store import build_input_hash"))

    def test_main_calls_source_cli_functions_directly(self) -> None:
        module = self._load_module()
        calls: list[tuple[str, str, str]] = []

        def _fake_collect_owned_nhl_artifacts(*, artifact_root, date_str, team_markets, props_source):
            calls.append((date_str, team_markets, props_source))
            out_dir = artifact_root / "data" / "odds" / "team" / f"date={date_str}"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "oddsapi.csv").write_text("game_id\nteam-1\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp_dir:
            argv = [
                "refresh_nhl_oddsapi.py",
                "--date",
                "2026-05-22",
                "--artifact-root",
                str(Path(tmp_dir) / "bundle"),
            ]
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch.object(module, "_run_source_generation_multi", return_value=None), patch.object(module, "_missing_required_artifacts", return_value=[]), patch.object(module, "_lineup_quality_issues", return_value=[]), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(calls, [("2026-05-22", "h2h,spreads,totals", "oddsapi")])

    def test_main_materializes_nhl_artifacts_into_bundle_root(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            (source_root / "data" / "processed").mkdir(parents=True)
            (source_root / "data" / "live_lens").mkdir(parents=True)
            (source_root / "data" / "odds" / "games" / "date=2026-05-22").mkdir(parents=True)
            (source_root / "data" / "odds" / "team" / "date=2026-05-22").mkdir(parents=True)
            (source_root / "data" / "props" / "player_props_lines" / "date=2026-05-22").mkdir(parents=True)

            (source_root / "data" / "processed" / "recommendations_2026-05-22.csv").write_text("market\nML\n", encoding="utf-8")
            (source_root / "data" / "processed" / "props_recommendations_2026-05-22.csv").write_text("player\nSkater\n", encoding="utf-8")
            (source_root / "data" / "live_lens" / "live_lens_signals_2026-05-22.jsonl").write_text('{"kind":"signal"}\n', encoding="utf-8")
            (source_root / "data" / "live_lens" / "live_lens_tuning_override.json").write_text('{"alpha":1.1}\n', encoding="utf-8")
            (source_root / "data" / "odds" / "games" / "date=2026-05-22" / "scoreboard.csv").write_text("game_id\n1\n", encoding="utf-8")

            def _fake_collect_owned_nhl_artifacts(*, artifact_root, date_str, team_markets, props_source):
                (artifact_root / "data" / "odds" / "games" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv").write_text("game_id\n1\n", encoding="utf-8")
                (artifact_root / "data" / "odds" / "team" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "odds" / "team" / f"date={date_str}" / "oddsapi.csv").write_text("game_id\nteam-1\n", encoding="utf-8")
                (artifact_root / "data" / "odds" / "team" / f"date={date_str}" / "oddsapi.parquet").write_text("parquet", encoding="utf-8")
                (artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv").write_text("player\nProp Skater\n", encoding="utf-8")
                (artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.parquet").write_text("parquet", encoding="utf-8")

            argv = [
                "refresh_nhl_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch.object(module, "_run_source_generation_multi", return_value=None), patch.object(module, "_missing_required_artifacts", return_value=[]), patch.object(module, "_lineup_quality_issues", return_value=[]), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "processed" / "recommendations_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_recommendations_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_lens_signals_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_lens_tuning_override.json").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "live_lens_signals_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "live_lens_tuning_override.json").exists())
            self.assertTrue((artifact_root / "data" / "odds" / "games" / "date=2026-05-22" / "scoreboard.csv").exists())
            self.assertTrue((artifact_root / "data" / "odds" / "team" / "date=2026-05-22" / "oddsapi.csv").exists())
            self.assertTrue((artifact_root / "data" / "odds" / "team" / "date=2026-05-22" / "oddsapi.parquet").exists())
            self.assertTrue((artifact_root / "data" / "props" / "player_props_lines" / "date=2026-05-22" / "oddsapi.csv").exists())
            self.assertTrue((artifact_root / "data" / "props" / "player_props_lines" / "date=2026-05-22" / "oddsapi.parquet").exists())

    def test_main_generates_source_backed_nhl_sim_files_into_bundle(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"

            def _fake_collect_owned_nhl_artifacts(*, artifact_root, date_str, team_markets, props_source):
                (artifact_root / "data" / "odds" / "games" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv").write_text("game_id\n1\n", encoding="utf-8")
                (artifact_root / "data" / "odds" / "team" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "odds" / "team" / f"date={date_str}" / "oddsapi.csv").write_text("game_id\nteam-1\n", encoding="utf-8")
                (artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv").write_text("player\nProp Skater\n", encoding="utf-8")

            def _fake_run_source_generation(*, source_root, artifact_root, date_str, props_boxscore_n_sims, days_ahead):
                processed_root = artifact_root / "data" / "processed"
                processed_root.mkdir(parents=True, exist_ok=True)
                (processed_root / f"props_boxscores_sim_{date_str}.csv").write_text("player\nSkater\n", encoding="utf-8")
                (processed_root / f"props_boxscores_sim_hist_{date_str}.csv").write_text("player\nSkater\n", encoding="utf-8")
                (processed_root / f"predictions_sim_{date_str}.csv").write_text("game_id\n1\n", encoding="utf-8")
                (processed_root / f"recommendations_sim_{date_str}.csv").write_text("game_id\n1\n", encoding="utf-8")

            argv = [
                "refresh_nhl_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch.object(module, "_run_source_generation_multi", side_effect=_fake_run_source_generation), patch.object(module, "_missing_required_artifacts", return_value=[]), patch.object(module, "_lineup_quality_issues", return_value=[]), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "processed" / "props_boxscores_sim_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_boxscores_sim_hist_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "predictions_sim_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recommendations_sim_2026-05-22.csv").exists())

    def test_main_uses_local_artifact_root_when_source_root_omitted(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir) / "bundle"

            def _fake_collect_owned_nhl_artifacts(*, artifact_root, date_str, team_markets, props_source):
                (artifact_root / "data" / "odds" / "games" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv").write_text("game_id\n1\n", encoding="utf-8")

            argv = [
                "refresh_nhl_oddsapi.py",
                "--date",
                "2026-05-22",
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch.object(module, "_run_source_generation_multi", return_value=None), patch.object(module, "_missing_required_artifacts", return_value=[]), patch.object(module, "_lineup_quality_issues", return_value=[]), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "odds" / "games" / "date=2026-05-22" / "scoreboard.csv").exists())

    def test_fast_mode_uses_collected_artifacts_only(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir) / "bundle"
            calls: list[str] = []

            def _fake_collect_owned_nhl_artifacts(*, artifact_root, date_str, team_markets, props_source):
                calls.append("collect")
                (artifact_root / "data" / "odds" / "games" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv").write_text("game_id\n1\n", encoding="utf-8")
                (artifact_root / "data" / "odds" / "team" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "odds" / "team" / f"date={date_str}" / "oddsapi.csv").write_text("market_id\nNHL:2026-05-22:AWAY@HOME:moneyline:TEAM:-120\n", encoding="utf-8")
                (artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}").mkdir(parents=True, exist_ok=True)
                (artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv").write_text("market_id\nNHL:2026-05-22:AWAY@HOME:player_points:nathan_mackinnon:3.5\n", encoding="utf-8")

            argv = [
                "refresh_nhl_oddsapi.py",
                "--date",
                "2026-05-22",
                "--artifact-root",
                str(artifact_root),
                "--mode",
                "fast",
            ]
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch.object(module, "_run_source_generation_multi", side_effect=AssertionError("source generation should not run in fast mode")), patch.object(module, "_materialize_artifact_bundle", side_effect=AssertionError("full bundle materialization should not run in fast mode")), patch.object(module, "_missing_required_artifacts", return_value=[]), patch.object(module, "_lineup_quality_issues", return_value=[]), patch.object(module, "_write_smart_sim_bundle", side_effect=AssertionError("smart sim bundle should not run in fast mode")), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertEqual(calls, ["collect"])

    def test_main_treats_missing_required_artifacts_as_no_data_warning(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir) / "bundle"
            source_root = Path(tmp_dir) / "source"

            def _fake_collect_owned_nhl_artifacts(*, artifact_root, date_str, team_markets, props_source):
                return None

            argv = [
                "refresh_nhl_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch.object(module, "_run_source_generation_multi", return_value=None), patch.object(module, "_missing_required_artifacts", return_value=["data/processed/props_predictions_2026-05-22.csv"]), patch.object(module, "_lineup_quality_issues", return_value=[]), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)


class NhlMarketIdTests(unittest.TestCase):
    def test_nhl_market_id_helpers_cover_team_props_and_scoreboard_rows(self) -> None:
        team_rows = nhl_odds._flatten_team_odds(
            {"id": "game-1", "home_team": "Colorado Avalanche", "away_team": "Toronto Maple Leafs", "commence_time": "2026-05-22T00:00:00Z"},
            {"key": "fanduel", "title": "FanDuel", "last_update": "2026-05-22T00:10:00Z"},
            {"key": "h2h", "outcomes": [{"name": "Toronto Maple Leafs", "price": 120}, {"name": "Colorado Avalanche", "price": -135}]},
        )
        self.assertTrue(all(str(row.get("market_id") or "").startswith("NHL:2026-05-22:TOR@COL:moneyline") for row in team_rows))

        props_input = pd.DataFrame([
            {
                "date": "2026-05-22",
                "player": "Nathan MacKinnon",
                "team": "COL",
                "home_team": "Colorado Avalanche",
                "away_team": "Toronto Maple Leafs",
                "market": "POINTS",
                "line": 3.5,
                "odds": -115,
                "side": "OVER",
                "book": "fanduel",
                "collected_at": "2026-05-22T00:10:00Z",
            }
        ])
        props_output = nhl_odds.combine_over_under(props_input)
        self.assertEqual(len(props_output), 1)
        self.assertEqual(props_output.iloc[0]["market_id"], "NHL:2026-05-22:TOR@COL:points:nathan_mackinnon:3.5")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            class _FakeClient:
                def scoreboard_day(self, date: str):
                    return [{"gamePk": 1, "home": "Colorado Avalanche", "away": "Toronto Maple Leafs", "home_goals": 3, "away_goals": 2, "gameState": "LIVE"}]

            with patch.object(nhl_odds, "NhlWebClient", return_value=_FakeClient()):
                scoreboard_path = nhl_odds.write_scoreboard_snapshot(artifact_root=root, date="2026-05-22")

            scoreboard_frame = pd.read_csv(scoreboard_path)
            self.assertEqual(scoreboard_frame.loc[0, "market_id"], "NHL:2026-05-22:TOR@COL:scoreboard:game:5")