from __future__ import annotations

import importlib.util
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import basketball_props_features


class NbaRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nba_oddsapi_props.py"
        spec = importlib.util.spec_from_file_location("test_refresh_nba_oddsapi_props", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_calls_syndicate_cli_refresh_path(self) -> None:
        module = self._load_module()

        calls = []

        def _fake_refresh(**kwargs):
            calls.append(kwargs)
            return {
                "snapshot_rows": 12,
                "snapshot_alias_rows": 12,
                "edges_rows": 5,
                "recs_rows": 3,
                "error": None,
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            argv = [
                "refresh_nba_oddsapi_props.py",
                "--date",
                "2026-05-22",
                "--regions",
                "us",
                "--source-root",
                tmp_dir,
                "--log-file",
                str(Path(tmp_dir) / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            with patch.object(module, "_run_refresh_via_cli", side_effect=_fake_refresh), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["date_str"], "2026-05-22")
        self.assertTrue(calls[0]["do_edges"])
        self.assertTrue(calls[0]["do_export"])

    def test_run_refresh_via_cli_uses_local_snapshot_fetcher(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            (source_root / "data" / "raw").mkdir(parents=True, exist_ok=True)
            commands = []

            def _fake_run(args, log_file, **kwargs):
                commands.append((list(args), kwargs.get("cwd")))
                out_idx = args.index("--out") + 1
                out_path = Path(args[out_idx])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                return 0

            with patch.object(module, "_run_to_file", side_effect=_fake_run):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="fanduel,draftkings",
                    markets="player_points,player_rebounds",
                    do_edges=False,
                    do_export=False,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(len(commands), 1)
        self.assertEqual(Path(commands[0][0][1]).name, "fetch_basketball_oddsapi_props_local.py")
        self.assertIn("--league", commands[0][0])
        self.assertIn("nba", commands[0][0])
        self.assertEqual(commands[0][1], module.REPO_ROOT)
        self.assertEqual(int(state["rc_snapshot"]), 0)
        self.assertEqual(int(state["snapshot_rows"]), 1)

    def test_player_logs_preflight_accepts_local_boxscores(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            (processed_root / "boxscores_2026-05-22.csv").write_text(
                "date,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,FG3M\n"
                "2026-05-21,BOS,1,Test Player,30,20,5,6,3\n",
                encoding="utf-8",
            )

            ready, reason = module._ensure_player_logs_for_props_refresh(
                source_root=source_root,
                date_str="2026-05-22",
                log_file=Path(tmp_dir) / "refresh.log",
                heartbeat_cb=lambda *_args, **_kwargs: None,
            )

        self.assertTrue(ready)
        self.assertIsNone(reason)

    def test_player_logs_preflight_bootstraps_local_history_when_missing(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            (source_root / "data" / "processed").mkdir(parents=True, exist_ok=True)

            with patch.object(module, "_bootstrap_local_boxscores_history_for_props", return_value=(True, None)):
                ready, reason = module._ensure_player_logs_for_props_refresh(
                    source_root=source_root,
                    date_str="2026-05-22",
                    log_file=Path(tmp_dir) / "refresh.log",
                    heartbeat_cb=lambda *_args, **_kwargs: None,
                )

        self.assertTrue(ready)
        self.assertIsNone(reason)

    def test_load_player_logs_local_falls_back_to_boxscores_files(self) -> None:
        class _FakeDataFrame:
            def __init__(self):
                self.empty = False

        fake_logs = _FakeDataFrame()
        fake_pd = types.SimpleNamespace(DataFrame=_FakeDataFrame)

        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict("sys.modules", {"pandas": fake_pd}):
            processed_root = Path(tmp_dir)
            with patch.object(basketball_props_features, "_load_boxscores_as_player_logs", return_value=fake_logs):
                logs = basketball_props_features.load_player_logs_local(processed_root=processed_root)

        self.assertIs(logs, fake_logs)

    def test_run_refresh_via_cli_uses_inprocess_predict_props(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            predict_calls = []
            run_calls = []

            def _fake_run(args, log_file, **kwargs):
                run_calls.append(list(args))
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                elif "props-edges" in args:
                    edges_path = processed_root / "props_edges_2026-05-22.csv"
                    edges_path.parent.mkdir(parents=True, exist_ok=True)
                    edges_path.write_text("market\nPTS\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                predict_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=False,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(len(run_calls), 1)
        self.assertEqual(Path(run_calls[0][1]).name, "fetch_basketball_oddsapi_props_local.py")
        self.assertEqual(len(predict_calls), 1)
        self.assertEqual(predict_calls[0]["date_str"], "2026-05-22")
        self.assertTrue(predict_calls[0]["use_smart_sim"])
        self.assertEqual(int(state["predictions_rows"]), 1)

    def test_run_refresh_via_cli_uses_inprocess_props_edges(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            predict_calls = []
            edges_calls = []

            def _fake_run(args, log_file, **kwargs):
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                predict_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_edges_export(**kwargs):
                edges_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.write_text("market\nPTS\n", encoding="utf-8")
                return 1, out_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=True,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(len(predict_calls), 1)
        self.assertEqual(len(edges_calls), 1)
        self.assertEqual(edges_calls[0]["bookmakers"], "")
        self.assertEqual(int(state["rc_edges"]), 0)
        self.assertEqual(int(state["edges_rows"]), 1)

    def test_run_refresh_via_cli_uses_inprocess_export_props_recommendations(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            predict_calls = []
            edges_calls = []
            export_calls = []

            def _fake_run(args, log_file, **kwargs):
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                elif "props-edges" in args:
                    (processed_root / "props_edges_2026-05-22.csv").write_text("market\nPTS\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                predict_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_edges_export(**kwargs):
                edges_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.write_text("market\nPTS\n", encoding="utf-8")
                return 1, out_path

            def _fake_export(*, processed_root, date_str, max_plus_odds=125.0):
                export_calls.append({"processed_root": processed_root, "date_str": date_str, "max_plus_odds": max_plus_odds})
                out_path = processed_root / f"props_recommendations_{date_str}.csv"
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "export_props_recommendations_local", side_effect=_fake_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=True,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(len(predict_calls), 1)
        self.assertEqual(len(edges_calls), 1)
        self.assertEqual(len(export_calls), 1)
        self.assertEqual(int(state["rc_export"]), 0)
        self.assertEqual(int(state["recs_rows"]), 1)

    def test_cli_backed_exports_prefer_existing_processed_files(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_source.mkdir(parents=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            date_str = "2026-05-22"

            expected = {
                f"recon_quarters_{date_str}.csv": module._export_recon_quarters_artifact,
                f"recon_props_{date_str}.csv": module._export_recon_props_artifact,
                f"game_cards_{date_str}.csv": module._export_game_cards_artifact,
                f"boxscores_{date_str}.csv": module._export_boxscores_artifact,
                f"recommendations_{date_str}.csv": module._export_recommendations_artifact,
            }
            for name in expected:
                (processed_source / name).write_text("id\n1\n", encoding="utf-8")

            with patch.object(module, "_load_source_cli", side_effect=AssertionError("source CLI should not load")):
                for name, exporter in expected.items():
                    out = exporter(source_root=source_root, date_str=date_str, processed_root=processed_root)
                    self.assertEqual(out, str(processed_root / name))
                    self.assertTrue((processed_root / name).exists())

    def test_app_backed_exports_prefer_existing_processed_files(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_source.mkdir(parents=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            date_str = "2026-05-22"

            expected = {
                f"recon_games_{date_str}.csv": module._export_recon_games_artifact,
                f"recommendations_slate_{date_str}.json": module._export_recommendations_slate_snapshot,
                f"cards_props_snapshot_{date_str}.json": module._export_cards_props_snapshot,
                f"cards_sim_detail_{date_str}.json": module._export_cards_sim_detail_snapshot,
                f"props_recommendations_top_by_game_{date_str}.json": module._export_top_by_game_snapshot,
            }
            for name in expected:
                (processed_source / name).write_text('{"ok": true}\n', encoding="utf-8")
            (processed_source / f"live_lens_signals_{date_str}.jsonl").write_text('{"kind":"signal"}\n', encoding="utf-8")
            (processed_source / f"live_lens_projections_{date_str}.jsonl").write_text('{"kind":"projection"}\n', encoding="utf-8")
            (processed_source / "live_lens_tuning_override.json").write_text('{"alpha":1.25}\n', encoding="utf-8")

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                for name, exporter in expected.items():
                    out = exporter(source_root=source_root, date_str=date_str, processed_root=processed_root)
                    self.assertEqual(out, str(processed_root / name))
                    self.assertTrue((processed_root / name).exists())
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )
                self.assertEqual(copied["live_lens_signals_path"], str(processed_root / f"live_lens_signals_{date_str}.jsonl"))
                self.assertEqual(copied["live_lens_projections_path"], str(processed_root / f"live_lens_projections_{date_str}.jsonl"))
                self.assertEqual(copied["live_lens_tuning_override_path"], str(processed_root / "live_lens_tuning_override.json"))
                self.assertEqual(copied["live_lens_tuning_override_live_lens_path"], str(live_lens_root / "live_lens_tuning_override.json"))

    def test_optional_tool_and_season_exports_prefer_existing_processed_files(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_source.mkdir(parents=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            date_str = "2026-05-22"
            season = module._resolve_nba_season_year(date_str)

            (processed_source / f"recon_players_{date_str}.csv").write_text("player\nA\n", encoding="utf-8")
            (processed_source / f"live_player_lens_tuning_{date_str}.csv").write_text("player\nA\n", encoding="utf-8")
            (processed_source / f"season_betting_card_manifest_{season}_retuned_{date_str}.json").write_text('{"ok": true}\n', encoding="utf-8")
            (processed_source / f"season_betting_card_day_{season}_retuned_{date_str}.json").write_text('{"ok": true}\n', encoding="utf-8")
            (processed_source / f"season_betting_card_day_{season}_retuned_{date_str}_insights.json").write_text('{"ok": true}\n', encoding="utf-8")

            with patch.object(module, "_load_module_from_path", side_effect=AssertionError("tool module should not load")):
                copied = module._build_optional_player_recon_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                )
                self.assertEqual(copied["recon_players_path"], str(processed_root / f"recon_players_{date_str}.csv"))
                self.assertEqual(copied["live_player_lens_tuning_path"], str(processed_root / f"live_player_lens_tuning_{date_str}.csv"))

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_season_betting_card_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                )
                self.assertEqual(copied["season_betting_card_manifest_path"], str(processed_root / f"season_betting_card_manifest_{season}_retuned_{date_str}.json"))
                self.assertEqual(copied["season_betting_card_manifest_generic_path"], str(processed_root / f"season_betting_card_manifest_{season}_retuned.json"))

    def test_main_materializes_core_artifacts_into_bundle_root(self) -> None:
        module = self._load_module()

        class _FakeSourceModule:
            def run_refresh_oddsapi_props_job(self, **kwargs):
                return {
                    "date": "2026-05-22",
                    "snapshot_rows": 12,
                    "snapshot_alias_rows": 12,
                    "edges_rows": 5,
                    "recs_rows": 3,
                    "error": None,
                    "snapshot_path": kwargs["log_file"].parent / "odds_nba_player_props_2026-05-22.csv",
                    "snapshot_alias_path": kwargs["log_file"].parent / "oddsapi_player_props_2026-05-22.csv",
                    "predictions_path": kwargs["log_file"].parent / "props_predictions_2026-05-22.csv",
                    "edges_path": kwargs["log_file"].parent / "props_edges_2026-05-22.csv",
                    "recs_path": kwargs["log_file"].parent / "props_recommendations_2026-05-22.csv",
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            for name in [
                "odds_nba_player_props_2026-05-22.csv",
                "oddsapi_player_props_2026-05-22.csv",
                "props_predictions_2026-05-22.csv",
                "props_edges_2026-05-22.csv",
                "props_recommendations_2026-05-22.csv",
                "smart_sim_2026-05-22_BOS_NYK.json",
                "smart_sim_2026-05-22_LAL_GSW.json",
            ]:
                (tmp_root / name).write_text("id\n1\n", encoding="utf-8")
            source_root = tmp_root / "source"
            source_root.mkdir()
            artifact_root = tmp_root / "bundle"
            argv = [
                "refresh_nba_oddsapi_props.py",
                "--date",
                "2026-05-22",
                "--regions",
                "us",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            class _FakeSourceApp:
                class _Client:
                    @staticmethod
                    def get(query):
                        class _Response:
                            @staticmethod
                            def get_json():
                                if "cron/reconcile-games" in query:
                                    recon_source = tmp_root / "recon_games_2026-05-22.csv"
                                    recon_source.write_text("game_id\n123\n", encoding="utf-8")
                                    return {"output": str(recon_source), "rows": 1}
                                if "view=slate" in query:
                                    return {"games": [{"home_tri": "BOS", "away_tri": "NYK"}]}
                                if "/api/season/" in query:
                                    if "include_prop_insights=1" in query:
                                        return {"date": "2026-05-22", "insights": [{"label": "Prop Insight"}]}
                                    if "/day/" in query:
                                        return {"date": "2026-05-22", "rows": [{"home_tri": "BOS", "away_tri": "NYK"}]}
                                    return {"season": 2025, "days": [{"date": "2026-05-22"}]}
                                if "/api/cards" in query:
                                    return {
                                        "games": [
                                            {
                                                "home_tri": "BOS",
                                                "away_tri": "NYK",
                                                "prop_recommendations": {
                                                    "home": [{"player": "Home NBA Prop"}],
                                                    "away": [{"player": "Away NBA Prop"}],
                                                },
                                                "sim": {
                                                    "players": {
                                                        "home": [{"player": "Home NBA Sim"}],
                                                        "away": [{"player": "Away NBA Sim"}],
                                                    },
                                                    "missing_prop_players": {
                                                        "home": [{"player": "Missing Home NBA"}],
                                                        "away": [{"player": "Missing Away NBA"}],
                                                    },
                                                    "injuries": {
                                                        "home": [{"player": "Injured Home NBA"}],
                                                        "away": [{"player": "Injured Away NBA"}],
                                                    },
                                                },
                                            }
                                        ]
                                    }
                                return {"data": [{"player": "Test NBA Player"}]}

                            @staticmethod
                            def get_data():
                                if "download_live_lens_signals" in query:
                                    return b'{"kind":"signal"}\n'
                                if "download_live_lens_projections" in query:
                                    return b'{"kind":"projection"}\n'
                                if "download_live_lens_tuning" in query:
                                    return b'{"alpha": 1.25}\n'
                                return b""

                            status_code = 200

                        return _Response()

                app = type("_App", (), {"test_client": staticmethod(lambda: _FakeSourceApp._Client())})()

            def _fake_optional_artifacts(*, source_root, date_str, processed_root):
                recon_path = processed_root / f"recon_players_{date_str}.csv"
                tuning_path = processed_root / f"live_player_lens_tuning_{date_str}.csv"
                recon_path.write_text("player\nTest NBA Player\n", encoding="utf-8")
                tuning_path.write_text("player\nTest NBA Player\n", encoding="utf-8")
                return {
                    "recon_players_path": str(recon_path),
                    "live_player_lens_tuning_path": str(tuning_path),
                }

            def _fake_recon_quarters_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recon_quarters_{date_str}.csv"
                out_path.write_text("game_id\nquarter-123\n", encoding="utf-8")
                return str(out_path)

            def _fake_recon_props_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recon_props_{date_str}.csv"
                out_path.write_text("player_id\n42\n", encoding="utf-8")
                return str(out_path)

            def _fake_game_cards_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"game_cards_{date_str}.csv"
                out_path.write_text("game_id\ncard-123\n", encoding="utf-8")
                return str(out_path)

            def _fake_boxscores_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"boxscores_{date_str}.csv"
                out_path.write_text("gameId\nbox-123\n", encoding="utf-8")
                return str(out_path)

            def _fake_recommendations_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recommendations_{date_str}.csv"
                out_path.write_text("market\nATS\n", encoding="utf-8")
                return str(out_path)

            with patch.object(module, "_run_refresh_via_cli", return_value=_FakeSourceModule().run_refresh_oddsapi_props_job(log_file=tmp_root / "refresh.log")), patch.object(module, "_load_source_app", return_value=_FakeSourceApp()), patch.object(module, "_build_optional_player_recon_artifacts", side_effect=_fake_optional_artifacts), patch.object(module, "_export_game_cards_artifact", side_effect=_fake_game_cards_artifact), patch.object(module, "_export_boxscores_artifact", side_effect=_fake_boxscores_artifact), patch.object(module, "_export_recommendations_artifact", side_effect=_fake_recommendations_artifact), patch.object(module, "_export_recon_quarters_artifact", side_effect=_fake_recon_quarters_artifact), patch.object(module, "_export_recon_props_artifact", side_effect=_fake_recon_props_artifact), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "raw" / "odds_nba_player_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "oddsapi_player_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_predictions_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_edges_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_recommendations_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_BOS_NYK.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_LAL_GSW.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recon_games_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "game_cards_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "boxscores_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recommendations_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recon_quarters_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recon_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recommendations_slate_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "cards_props_snapshot_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "cards_sim_detail_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_recommendations_top_by_game_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "season_betting_card_manifest_2025_retuned_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "season_betting_card_manifest_2025_retuned.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "season_betting_card_day_2025_retuned_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "season_betting_card_day_2025_retuned_2026-05-22_insights.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_lens_signals_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_lens_projections_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_lens_tuning_override.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recon_players_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_player_lens_tuning_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "live_lens_signals_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "live_lens_projections_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "live_lens_tuning_override.json").exists())

    def test_main_prefers_existing_refresh_outputs_before_source_job(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            required_files = {
                raw_root / f"odds_nba_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"oddsapi_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"props_predictions_{date_str}.csv": "player\nA\n",
                processed_root / f"props_edges_{date_str}.csv": "player\nA\n",
                processed_root / f"props_recommendations_{date_str}.csv": "player\nA\n",
                processed_root / f"game_cards_{date_str}.csv": "game_id\n1\n",
                processed_root / f"boxscores_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_{date_str}.csv": "market\nATS\n",
                processed_root / f"recon_quarters_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recon_props_{date_str}.csv": "player_id\n1\n",
                processed_root / f"recon_games_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_slate_{date_str}.json": '{"ok": true}\n',
                processed_root / f"cards_props_snapshot_{date_str}.json": '{"ok": true}\n',
                processed_root / f"cards_sim_detail_{date_str}.json": '{"ok": true}\n',
                processed_root / f"props_recommendations_top_by_game_{date_str}.json": '{"ok": true}\n',
                processed_root / f"live_lens_signals_{date_str}.jsonl": '{"kind":"signal"}\n',
                processed_root / f"live_lens_projections_{date_str}.jsonl": '{"kind":"projection"}\n',
                processed_root / "live_lens_tuning_override.json": '{"alpha":1.25}\n',
                processed_root / f"recon_players_{date_str}.csv": "player\nA\n",
                processed_root / f"live_player_lens_tuning_{date_str}.csv": "player\nA\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            (processed_root / "boxscores_2026-05-21.csv").write_text("game_id,player_id\nold-game,11\n", encoding="utf-8")

            season = module._resolve_nba_season_year(date_str)
            for name in (
                f"season_betting_card_manifest_{season}_retuned_{date_str}.json",
                f"season_betting_card_day_{season}_retuned_{date_str}.json",
                f"season_betting_card_day_{season}_retuned_{date_str}_insights.json",
            ):
                (processed_root / name).write_text('{"ok": true}\n', encoding="utf-8")
            (processed_root / "smart_sim_2026-05-22_BOS_NYK.json").write_text('{"ok": true}\n', encoding="utf-8")

            argv = [
                "refresh_nba_oddsapi_props.py",
                "--date",
                date_str,
                "--regions",
                "us",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            with patch.object(module, "_run_refresh_via_cli", side_effect=AssertionError("cli refresh path should not load")), patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")), patch.object(module, "_load_source_cli", side_effect=AssertionError("source cli should not load")), patch.object(module, "_load_module_from_path", side_effect=AssertionError("source tools should not load")), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "raw" / f"odds_nba_player_props_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_predictions_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_edges_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_recommendations_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"game_cards_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "boxscores_history.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_BOS_NYK.json").exists())
            history_text = (artifact_root / "data" / "processed" / "boxscores_history.csv").read_text(encoding="utf-8")
            self.assertIn("old-game", history_text)
            self.assertIn("game_id", history_text)

    def test_main_prefers_existing_artifact_bundle_before_source_job(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "missing-source"
            artifact_root = tmp_root / "bundle"
            raw_root = artifact_root / "data" / "raw"
            processed_root = artifact_root / "data" / "processed"
            date_str = "2026-05-22"

            required_files = {
                raw_root / f"odds_nba_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"oddsapi_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"props_predictions_{date_str}.csv": "player\nA\n",
                processed_root / f"props_edges_{date_str}.csv": "player\nA\n",
                processed_root / f"props_recommendations_{date_str}.csv": "player\nA\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            argv = [
                "refresh_nba_oddsapi_props.py",
                "--date",
                date_str,
                "--regions",
                "us",
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            with patch.object(module, "_run_refresh_via_cli", side_effect=AssertionError("cli refresh path should not load")), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
