from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class WnbaRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_wnba_oddsapi_props.py"
        spec = importlib.util.spec_from_file_location("test_refresh_wnba_oddsapi_props", script_path)
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
                "refresh_wnba_oddsapi_props.py",
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

    def test_ensure_source_game_inputs_fetches_with_periods_enabled(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            (processed_root / f"game_odds_{date_str}.csv").write_text(
                "game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "1,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus\n",
                encoding="utf-8",
            )

            calls: list[list[str]] = []

            def fake_cli(*, source_root, package_name, command_parts, log_file, heartbeat_cb, timeout_s):
                calls.append(list(command_parts))
                if command_parts and command_parts[0] == "export-game-cards":
                    out_path = source_root / "data" / "processed" / f"game_cards_{date_str}.csv"
                    out_path.write_text(
                        "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                        "2026-05-22,1,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                        encoding="utf-8",
                    )
                return 0

            module._run_source_subprocess_cli_command = fake_cli
            module._seed_game_odds_from_props_snapshot = lambda **kwargs: None
            module._seed_game_odds_from_raw_history = lambda **kwargs: None

            module._ensure_source_game_inputs(
                source_root=source_root,
                package_name="wnba_betting",
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
                heartbeat_cb=None,
            )

        self.assertIn(["fetch", "--years", "10"], calls)

    def test_build_local_game_recommendations_artifact_uses_game_cards_and_smart_sim(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            date_str = "2026-05-22"
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,1,Home Team,Away Team,2026-05-22T19:00:00Z,-130,110,-4.5,4.5,219.5,oddsapi_consensus,HTM,ATM\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_HTM_ATM.json").write_text(
                json.dumps(
                    {
                        "date": date_str,
                        "home": "HTM",
                        "away": "ATM",
                        "quarters": [
                            {"home_pts_mu": 28.0, "away_pts_mu": 24.0},
                            {"home_pts_mu": 27.0, "away_pts_mu": 25.0},
                            {"home_pts_mu": 26.0, "away_pts_mu": 24.0},
                            {"home_pts_mu": 25.0, "away_pts_mu": 23.0},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_recommendations_artifact(processed_root=processed_root, date_str=date_str)

            self.assertEqual(rows, 2)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual([row.get("market") for row in written], ["ATS", "TOTAL"])
        self.assertEqual(written[0].get("side"), "Home Team")
        self.assertEqual(written[1].get("side"), "Under")

    def test_build_local_game_cards_artifact_uses_raw_team_odds_snapshot(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            (raw_root / f"odds_wnba_current_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Chicago Sky,,,-140,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Minnesota Lynx,,,120,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Chicago Sky,,-4.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Minnesota Lynx,,4.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Over,,164.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Under,,164.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n",
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 1)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].get("home_team"), "Chicago Sky")
        self.assertEqual(written[0].get("visitor_team"), "Minnesota Lynx")
        self.assertEqual(written[0].get("home_tri"), "CHI")
        self.assertEqual(written[0].get("away_tri"), "MIN")
        self.assertEqual(written[0].get("bookmaker"), "oddsapi_consensus")

    def test_build_local_game_cards_artifact_uses_raw_player_props_snapshot_fallback(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-06-17"
            (raw_root / f"odds_wnba_player_props_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-06-17T13:55:26Z,401,2026-06-17T23:00:00Z,draftkings,DraftKings,player_points,Over,Sonia Citron,16.5,-113,2026-06-17T13:55:01Z,Connecticut Sun,Washington Mystics\n"
                "2026-06-17T13:55:26Z,401,2026-06-17T23:00:00Z,draftkings,DraftKings,player_points,Under,Sonia Citron,16.5,-117,2026-06-17T13:55:01Z,Connecticut Sun,Washington Mystics\n",
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 1)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].get("home_team"), "Connecticut Sun")
        self.assertEqual(written[0].get("visitor_team"), "Washington Mystics")
        self.assertEqual(written[0].get("home_tri"), "CON")
        self.assertEqual(written[0].get("away_tri"), "WSH")
        self.assertEqual(written[0].get("bookmaker"), "oddsapi_consensus")

    def test_repair_predictions_slate_rebuilds_when_predictions_missing(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            date_str = "2026-06-05"
            (processed_root / f"game_odds_{date_str}.csv").write_text(
                "date,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "2026-06-05,Chicago Sky,Minnesota Lynx,2026-06-05T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus\n",
                encoding="utf-8",
            )
            (processed_root / f"oddsapi_player_props_{date_str}.csv").write_text(
                "home_team,away_team,commence_time\n"
                "Chicago Sky,Minnesota Lynx,2026-06-05T23:00:00Z\n",
                encoding="utf-8",
            )

            repaired = module._repair_predictions_slate_from_game_odds_if_needed(
                processed_root=processed_root,
                date_str=date_str,
                log_file=processed_root / "refresh.log",
            )

            self.assertTrue(repaired)
            pred_path = processed_root / f"predictions_{date_str}.csv"
            self.assertTrue(pred_path.exists())
            with pred_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].get("date"), date_str)
        self.assertEqual(written[0].get("home_team"), "Chicago Sky")
        self.assertEqual(written[0].get("visitor_team"), "Minnesota Lynx")

    def test_main_returns_error_when_refresh_runner_returns_none(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                "2026-05-22",
                "--regions",
                "us",
                "--source-root",
                tmp_dir,
                "--log-file",
                str(Path(tmp_dir) / "refresh.log"),
            ]
            with patch.object(module, "_run_refresh_via_cli", return_value=None), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 1)

    def test_local_basketball_json_exports_use_owned_inputs(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            with (processed_root / f"recommendations_{date_str}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "market",
                        "side",
                        "home",
                        "away",
                        "date",
                        "ev",
                        "price",
                        "implied_prob",
                        "edge",
                        "line",
                        "pred_margin",
                        "market_home_margin",
                        "pred_total",
                        "tier",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "market": "ATS",
                        "side": "Chicago Sky",
                        "home": "Chicago Sky",
                        "away": "Minnesota Lynx",
                        "date": date_str,
                        "ev": 0.07,
                        "price": -110,
                        "implied_prob": 0.5238,
                        "edge": 1.7,
                        "line": 4.5,
                        "pred_margin": 6.0,
                        "market_home_margin": -4.5,
                        "pred_total": "",
                        "tier": "Medium",
                    }
                )
            prop_columns = [
                "player",
                "team",
                "plays",
                "ladders",
                "sim_ladders",
                "model",
                "_plays_list",
                "top_play",
                "top_play_explain",
                "top_play_baseline",
                "top_play_reasons",
                "top_play_consensus",
                "top_play_line_adv",
                "last5_average",
                "last10_average",
                "last_game_value",
                "projected_minutes",
                "last10_workload",
            ]
            with (processed_root / f"props_recommendations_{date_str}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=prop_columns)
                writer.writeheader()
                writer.writerow(
                    {
                        "player": "Angel Reese",
                        "team": "CHI",
                        "plays": str([{"market": "reb", "side": "OVER", "line": 10.5, "price": -110, "edge": 1.4, "ev": 0.08, "ev_pct": 8.0, "book": "fanduel"}]),
                        "ladders": "[]",
                        "sim_ladders": "[]",
                        "model": str({"reb": 11.3, "pts": 15.1}),
                        "_plays_list": str([{"market": "reb", "side": "OVER", "line": 10.5, "price": -110, "edge": 1.4, "ev": 0.08, "ev_pct": 8.0, "book": "fanduel"}]),
                        "top_play": str({"market": "reb", "side": "OVER", "line": 10.5, "price": -110, "edge": 1.4, "ev": 0.08, "ev_pct": 8.0, "book": "fanduel"}),
                        "top_play_explain": "model 11.3 vs line 10.5 (+0.8)",
                        "top_play_baseline": "11.3",
                        "top_play_reasons": str(["EV 8.0%", "Regular price range (-150 to +150)"]),
                        "top_play_consensus": "0.5",
                        "top_play_line_adv": "1.0",
                        "last5_average": "12.4",
                        "last10_average": "11.7",
                        "last_game_value": "13.0",
                        "projected_minutes": "34.5",
                        "last10_workload": "32.0",
                    }
                )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                slate_path = module._export_recommendations_slate_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)
                props_path = module._export_cards_props_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)
                top_path = module._export_top_by_game_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)

            self.assertIsNotNone(slate_path)
            self.assertIsNotNone(props_path)
            self.assertIsNotNone(top_path)
            slate_payload = json.loads((processed_root / f"recommendations_slate_{date_str}.json").read_text(encoding="utf-8"))
            props_payload = json.loads((processed_root / f"cards_props_snapshot_{date_str}.json").read_text(encoding="utf-8"))
            top_payload = json.loads((processed_root / f"props_recommendations_top_by_game_{date_str}.json").read_text(encoding="utf-8"))

        self.assertEqual(slate_payload["counts"]["games"], 1)
        self.assertEqual(slate_payload["per_game"][0]["home"], "CHI")
        self.assertTrue(any(float(pick.get("last5_average") or 0.0) == 12.4 for pick in (slate_payload["per_game"][0]["picks"] or []) if isinstance(pick, dict)))
        self.assertEqual(props_payload["games"][0]["prop_recommendations"]["home"][0]["player"], "Angel Reese")
        self.assertEqual(props_payload["games"][0]["prop_recommendations"]["home"][0]["last10_workload"], 32.0)
        self.assertEqual(top_payload["data"][0]["team_tricode"], "CHI")
        self.assertEqual(top_payload["data"][0]["top_play"]["market"], "reb")
        self.assertEqual(top_payload["data"][0]["top_play"]["projected_minutes"], 34.5)

    def test_recon_games_export_uses_local_boxscores_and_game_cards(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-29"
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-29,9876543210,Chicago Sky,Minnesota Lynx,2026-05-29T19:00:00Z,120,-140,3.5,-3.5,162.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"boxscores_{date_str}.csv").write_text(
                "GAME_ID,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,PTS\n"
                "9876543210,CHI,1,Angel Reese,19\n"
                "9876543210,CHI,2,Kamilla Cardoso,14\n"
                "9876543210,MIN,3,Napheesa Collier,26\n"
                "9876543210,MIN,4,Kayla McBride,17\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                out = module._export_recon_games_artifact(source_root=source_root, date_str=date_str, processed_root=processed_root)

            self.assertEqual(out, str(processed_root / f"recon_games_{date_str}.csv"))
            with (processed_root / f"recon_games_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_team"], "Chicago Sky")
        self.assertEqual(rows[0]["visitor_team"], "Minnesota Lynx")
        self.assertEqual(rows[0]["home_pts"], "33")
        self.assertEqual(rows[0]["visitor_pts"], "43")
        self.assertEqual(rows[0]["total_actual"], "76")

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
        self.assertIn("wnba", commands[0][0])
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
                "2026-05-21,NYL,1,Test Player,30,20,5,6,3\n",
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

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)):
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

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)):
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
            (raw_root / "odds_wnba_current_2026-05-22.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Chicago Sky,,,-140,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Minnesota Lynx,,,120,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Chicago Sky,,-4.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Minnesota Lynx,,4.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Over,,164.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Under,,164.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n",
                encoding="utf-8",
            )
            (processed_root / "smart_sim_2026-05-22_CHI_MIN.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "home": "CHI",
                        "away": "MIN",
                        "quarters": [
                            {"home_pts_mu": 21.0, "away_pts_mu": 19.0},
                            {"home_pts_mu": 22.0, "away_pts_mu": 20.0},
                            {"home_pts_mu": 21.0, "away_pts_mu": 19.0},
                            {"home_pts_mu": 20.0, "away_pts_mu": 18.0}
                        ],
                    }
                ),
                encoding="utf-8",
            )
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

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "export_props_recommendations_local", side_effect=_fake_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_source_game_inputs", return_value={"schedule": 1, "fetch": 0, "build_features": 0, "predict_date": 0}):
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

    def test_run_refresh_via_cli_treats_written_export_artifacts_as_success(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

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
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_edges_export(**kwargs):
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("market\nPTS\n", encoding="utf-8")
                return 1, out_path

            def _fake_game_cards_artifact(*, source_root, processed_root, date_str, log_file):
                game_cards_path = processed_root / f"game_cards_{date_str}.csv"
                recs_path = processed_root / f"props_recommendations_{date_str}.csv"
                game_cards_path.write_text(
                    "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                    "2026-05-22,401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                    encoding="utf-8",
                )
                recs_path.write_text("market\nATS\n", encoding="utf-8")
                raise RuntimeError("simulated export helper failure after writing artifacts")

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_source_game_inputs", return_value={"schedule": 1, "fetch": 0, "build_features": 0, "predict_date": 0}), patch.object(module, "_build_local_game_cards_artifact", side_effect=_fake_game_cards_artifact):
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

        self.assertEqual(int(state["rc_export"]), 0)
        self.assertIsNone(state["error"])
        self.assertGreater(int(state["game_cards_rows"]), 0)
        self.assertGreater(int(state["recs_rows"]), 0)

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

    def test_live_lens_tuning_export_uses_local_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            date_str = "2026-05-22"
            processed_source.mkdir(parents=True, exist_ok=True)
            (processed_source / f"live_lens_signals_{date_str}.jsonl").write_text('{"kind":"signal"}\n', encoding="utf-8")
            (processed_source / f"live_lens_projections_{date_str}.jsonl").write_text('{"kind":"projection"}\n', encoding="utf-8")

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )

            self.assertEqual(copied["live_lens_tuning_override_path"], str(processed_root / "live_lens_tuning_override.json"))
            self.assertEqual(copied["live_lens_tuning_override_live_lens_path"], str(live_lens_root / "live_lens_tuning_override.json"))
            payload = json.loads((processed_root / "live_lens_tuning_override.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["markets"]["player_prop"]["bet"], 4.0)

    def test_live_lens_signals_export_uses_local_smart_sim_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            date_str = "2026-05-22"
            processed_source.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            live_lens_root.mkdir(parents=True, exist_ok=True)

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_CHI_MIN.json").write_text(
                json.dumps(
                    {
                        "date": date_str,
                        "home": "CHI",
                        "away": "MIN",
                        "periods": {
                            "q1": {"home_mean": 22.0, "away_mean": 20.0},
                            "q2": {"home_mean": 21.0, "away_mean": 21.0},
                            "q3": {"home_mean": 23.0, "away_mean": 20.0},
                            "q4": {"home_mean": 22.0, "away_mean": 21.0},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (processed_source / f"live_lens_projections_{date_str}.jsonl").write_text(
                json.dumps({"market": "player_prop", "player": "Angel Reese"}) + "\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )

            self.assertEqual(copied["live_lens_signals_path"], str(processed_root / f"live_lens_signals_{date_str}.jsonl"))
            rows = [
                json.loads(line)
                for line in (processed_root / f"live_lens_signals_{date_str}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market"], "total")
        self.assertEqual(rows[0]["klass"], "WATCH")
        self.assertEqual(rows[0]["side"], "OVER")
        self.assertEqual(rows[0]["live_line"], 164.5)
        self.assertEqual(rows[0]["pred"], 170.0)
        self.assertEqual(rows[0]["remaining"], 40)

    def test_live_lens_signals_export_prefers_existing_source_artifact(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            date_str = "2026-05-22"
            processed_source.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            live_lens_root.mkdir(parents=True, exist_ok=True)

            source_rows = [
                {
                    "market": "quarter_total",
                    "klass": "BET",
                    "game_id": "0401",
                    "home": "CHI",
                    "away": "MIN",
                    "side": "OVER",
                    "live_line": 40.5,
                    "pred": 45.0,
                    "edge": 4.5,
                    "edge_adj": 4.5,
                    "horizon": "q1",
                }
            ]
            (processed_source / f"live_lens_signals_{date_str}.jsonl").write_text(
                "\n".join(json.dumps(row) for row in source_rows) + "\n",
                encoding="utf-8",
            )
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_CHI_MIN.json").write_text(
                json.dumps(
                    {
                        "date": date_str,
                        "home": "CHI",
                        "away": "MIN",
                        "periods": {
                            "q1": {"home_mean": 22.0, "away_mean": 20.0},
                            "q2": {"home_mean": 21.0, "away_mean": 21.0},
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )

            self.assertEqual(copied["live_lens_signals_path"], str(processed_root / f"live_lens_signals_{date_str}.jsonl"))
            rows = [
                json.loads(line)
                for line in (processed_root / f"live_lens_signals_{date_str}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(rows, source_rows)

    def test_flat_props_rows_still_build_top_by_game_snapshot(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            date_str = "2026-06-17"
            processed_source.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-06-17,0401,Chicago Sky,Minnesota Lynx,2026-06-17T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"props_recommendations_{date_str}.csv").write_text(
                "date,team,player,market,side,line,price,ev,ev_pct,book,top_play_explain,top_play_reasons\n"
                "2026-06-17,CHI,Angel Reese,reb,OVER,10.5,-110,0.08,8.0,fanduel,model 11.3 vs line 10.5 (+0.8),['EV 8.0%','Regular price range (-150 to +150)']\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                props_path = module._export_cards_props_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)
                top_path = module._export_top_by_game_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)

            self.assertIsNotNone(props_path)
            self.assertIsNotNone(top_path)
            props_payload = json.loads((processed_root / f"cards_props_snapshot_{date_str}.json").read_text(encoding="utf-8"))
            top_payload = json.loads((processed_root / f"props_recommendations_top_by_game_{date_str}.json").read_text(encoding="utf-8"))

        self.assertEqual(props_payload["games"][0]["prop_recommendations"]["home"][0]["player"], "Angel Reese")
        self.assertEqual(top_payload["data"][0]["team_tricode"], "CHI")
        self.assertEqual(top_payload["data"][0]["top_play"]["market"], "reb")
        self.assertEqual(top_payload["data"][0]["top_play"]["side"], "OVER")

    def test_generate_offline_live_lens_signals_emits_period_totals(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "vendor" / "wnba_betting_repo" / "tools" / "generate_offline_live_lens_signals.py"
        spec = importlib.util.spec_from_file_location("test_generate_offline_live_lens_signals", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            date_str = "2026-05-22"
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,halves_h1_total,quarters_q1_total,quarters_q2_total,quarters_q3_total,quarters_q4_total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,82.0,40.5,41.5,39.5,42.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"_predictions_backup_{date_str}.csv").write_text(
                "home_team,visitor_team,totals,pred_h1_total,pred_q1_total,pred_q2_total,pred_q3_total,pred_q4_total\n"
                "Chicago Sky,Minnesota Lynx,170.0,86.0,45.0,39.5,41.0,43.0\n",
                encoding="utf-8",
            )

            out_path = processed_root / f"live_lens_signals_{date_str}.jsonl"
            argv = ["generate_offline_live_lens_signals.py", "--date", date_str, "--out", str(out_path), "--min-left", "40"]
            with patch.object(module, "PROCESSED", processed_root), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            rows = [
                json.loads(line)
                for line in out_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(rows), 6)
        markets = {(row["market"], row.get("horizon")) for row in rows}
        self.assertIn(("total", "game"), markets)
        self.assertIn(("half_total", "h1"), markets)
        self.assertIn(("quarter_total", "q1"), markets)
        self.assertIn(("quarter_total", "q2"), markets)
        self.assertIn(("quarter_total", "q3"), markets)
        self.assertIn(("quarter_total", "q4"), markets)

    def test_live_lens_projections_export_uses_local_predictions_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            processed_source.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            live_lens_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"props_predictions_{date_str}.csv").write_text(
                "player_name,team,opponent,home,pred_pts,mean_pts,pred_reb,mean_reb\n"
                "Angel Reese,CHI,MIN,1,15.8,15.1,10.9,10.4\n",
                encoding="utf-8",
            )
            (processed_root / f"props_edges_{date_str}.csv").write_text(
                "player_name,team,stat,line\n"
                "Angel Reese,CHI,reb,10.5\n",
                encoding="utf-8",
            )
            (processed_source / f"live_lens_signals_{date_str}.jsonl").write_text(
                json.dumps({"market": "total", "game_id": "0401"}) + "\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )

            self.assertEqual(copied["live_lens_projections_path"], str(processed_root / f"live_lens_projections_{date_str}.jsonl"))
            rows = [
                json.loads(line)
                for line in (processed_root / f"live_lens_projections_{date_str}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(rows), 2)
        reb_row = next(row for row in rows if row["stat"] == "reb")
        self.assertEqual(reb_row["market"], "player_prop")
        self.assertEqual(reb_row["game_id"], "0401")
        self.assertEqual(reb_row["home"], "CHI")
        self.assertEqual(reb_row["away"], "MIN")
        self.assertEqual(reb_row["proj"], 10.9)
        self.assertEqual(reb_row["sim_mu"], 10.4)
        self.assertEqual(reb_row["line"], 10.5)

    def test_recon_props_export_uses_local_boxscores_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"boxscores_{date_str}.csv").write_text(
                "date,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,PTS,REB,AST,FG3M,STL,BLK,TOV\n"
                "2026-05-22,CHI,5,Angel Reese,24,11,4,0,1,2,3\n",
                encoding="utf-8",
            )

            out = module._export_recon_props_artifact(
                source_root=source_root,
                date_str=date_str,
                processed_root=processed_root,
            )

            self.assertEqual(out, str(processed_root / f"recon_props_{date_str}.csv"))
            with (processed_root / f"recon_props_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_id"], "0401")
        self.assertEqual(rows[0]["player_name"], "Angel Reese")
        self.assertEqual(rows[0]["team_abbr"], "CHI")
        self.assertEqual(rows[0]["blk"], "2")
        self.assertEqual(rows[0]["pr"], "35")
        self.assertEqual(rows[0]["pa"], "28")
        self.assertEqual(rows[0]["ra"], "15")
        self.assertEqual(rows[0]["pra"], "39")

    def test_cards_sim_detail_export_preserves_quarter_summary(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True)
            (processed_root / "smart_sim_2026-05-29_POR_ATL.json").write_text(
                json.dumps(
                    {
                        "home": "POR",
                        "away": "ATL",
                        "periods": {"q1": {"away_mean": 21.4, "home_mean": 19.8, "total_mean": 41.2, "margin_mean": -1.6, "p_home_win": 0.41}},
                        "players_summary": {"home": 1, "away": 1},
                        "players": {"home": [{"player_name": "Home Player"}], "away": [{"player_name": "Away Player"}]},
                        "missing_prop_players": {"home": [], "away": []},
                        "injuries": {"home": [], "away": []},
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(module, "_copy_existing_processed_artifact", return_value=None), patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                out = module._export_cards_sim_detail_snapshot(source_root=source_root, date_str="2026-05-29", processed_root=processed_root)

            self.assertEqual(out, str(processed_root / "cards_sim_detail_2026-05-29.json"))
            payload = json.loads((processed_root / "cards_sim_detail_2026-05-29.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["games"][0]["sim"]["quarters"][0]["away_pts_mu"], 21.4)

    def test_optional_tool_exports_prefer_existing_processed_files(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_source.mkdir(parents=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            date_str = "2026-05-22"

            (processed_source / f"recon_players_{date_str}.csv").write_text("player\nA\n", encoding="utf-8")
            (processed_source / f"live_player_lens_tuning_{date_str}.csv").write_text("player\nA\n", encoding="utf-8")

            with patch.object(module, "_load_module_from_path", side_effect=AssertionError("tool module should not load")):
                copied = module._build_optional_player_recon_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                )
                self.assertEqual(copied["recon_players_path"], str(processed_root / f"recon_players_{date_str}.csv"))
                self.assertEqual(copied["live_player_lens_tuning_path"], str(processed_root / f"live_player_lens_tuning_{date_str}.csv"))

    def test_optional_tool_exports_use_local_vendored_builders(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_CHI_MIN.json").write_text(
                json.dumps(
                    {
                        "game_id": "0401",
                        "home": "CHI",
                        "away": "MIN",
                        "players": {
                            "home": [
                                {
                                    "player_id": 5,
                                    "player_name": "Angel Reese",
                                    "min_mean": 34.0,
                                    "pts_mean": 18.0,
                                    "reb_mean": 11.0,
                                    "ast_mean": 4.0,
                                    "threes_mean": 0.0,
                                    "pra_mean": 33.0,
                                    "stl_mean": 1.0,
                                    "blk_mean": 2.0,
                                    "tov_mean": 3.0,
                                }
                            ],
                            "away": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (processed_root / f"boxscores_{date_str}.csv").write_text(
                "GAME_ID,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,FG3M,FG3A,FGM,FGA,FTM,FTA,STL,BLK,TOV,PF,OREB,DREB,PLUS_MINUS\n"
                "0401,CHI,5,Angel Reese,35:00,20,12,3,0,0,9,16,2,4,1,2,3,3,5,7,9\n",
                encoding="utf-8",
            )
            (processed_root / f"props_predictions_{date_str}.csv").write_text(
                "player_id,player_name,team,opponent,roll10_min,mean_pts,mean_reb,mean_ast,mean_threes,mean_pra\n"
                "5,Angel Reese,CHI,MIN,34.0,18.0,11.0,4.0,0.0,33.0\n",
                encoding="utf-8",
            )
            (processed_root / f"props_edges_{date_str}.csv").write_text(
                "team,player_name,stat,line\n"
                "CHI,Angel Reese,reb,10.5\n"
                "CHI,Angel Reese,pra,31.5\n",
                encoding="utf-8",
            )

            copied = module._build_optional_player_recon_artifacts(
                source_root=source_root,
                date_str=date_str,
                processed_root=processed_root,
            )

            self.assertEqual(copied["recon_players_path"], str(processed_root / f"recon_players_{date_str}.csv"))
            self.assertEqual(copied["live_player_lens_tuning_path"], str(processed_root / f"live_player_lens_tuning_{date_str}.csv"))
            with (processed_root / f"recon_players_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                recon_rows = list(csv.DictReader(handle))
            with (processed_root / f"live_player_lens_tuning_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                tuning_rows = list(csv.DictReader(handle))

        self.assertEqual(len(recon_rows), 1)
        self.assertEqual(recon_rows[0]["player_name"], "Angel Reese")
        self.assertEqual(recon_rows[0]["actual_reb"], "12.0")
        reb_row = next(row for row in tuning_rows if row["stat"] == "reb")
        self.assertEqual(reb_row["player_name"], "Angel Reese")
        self.assertEqual(reb_row["game_id"], "0401")
        self.assertEqual(reb_row["actual"], "12.0")
        self.assertEqual(reb_row["line"], "10.5")

    def test_export_live_snapshot_artifacts_overwrites_empty_lens_snapshot_with_local_build(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            source_snapshots = source_root / "data" / "processed" / "live_snapshots"
            source_snapshots.mkdir(parents=True, exist_ok=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            module._write_live_snapshot_payload(
                source_snapshots / "live_state_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "status": "Scheduled"}]},
            )
            module._write_live_snapshot_payload(
                source_snapshots / "live_player_lens_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "rows": []}]},
            )

            def _fake_local_payload(*, kind: str, date_str: str, event_ids: list[str]):
                if kind == "live_player_lens":
                    return {"ok": True, "games": [{"event_id": "401856963", "rows": [{"player": "Aneesah Morrow"}]}]}
                return None

            with patch.object(module, "_source_app_fallback_enabled", return_value=False), patch.object(
                module,
                "_build_local_live_snapshot_payload",
                side_effect=_fake_local_payload,
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_player_lens_path", copied)
            payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_player_lens_2026-06-05.jsonl")
            self.assertEqual((((payload or {}).get("games") or [{}])[0].get("rows") or [{}])[0].get("player"), "Aneesah Morrow")

    def test_export_live_snapshot_artifacts_skips_empty_shells_without_replacement(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            source_snapshots = source_root / "data" / "processed" / "live_snapshots"
            source_snapshots.mkdir(parents=True, exist_ok=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            module._write_live_snapshot_payload(
                source_snapshots / "live_state_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "status": "Live"}]},
            )
            module._write_live_snapshot_payload(
                source_snapshots / "live_lines_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "found": False, "lines": {}}]},
            )
            module._write_live_snapshot_payload(
                source_snapshots / "live_player_lens_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "rows": []}]},
            )

            with patch.object(module, "_source_app_fallback_enabled", return_value=False), patch.object(
                module,
                "_build_local_live_snapshot_payload",
                return_value=None,
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_state_path", copied)
            self.assertNotIn("live_lines_path", copied)
            self.assertNotIn("live_player_lens_path", copied)
            self.assertFalse((processed_root / "live_snapshots" / "live_lines_2026-06-05.jsonl").exists())
            self.assertFalse((processed_root / "live_snapshots" / "live_player_lens_2026-06-05.jsonl").exists())

    def test_export_live_snapshot_artifacts_builds_from_bundle_live_lens_artifacts(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            source_snapshots = source_root / "data" / "processed" / "live_snapshots"
            source_snapshots.mkdir(parents=True, exist_ok=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            module._write_live_snapshot_payload(
                source_snapshots / "live_state_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "home": "LAS", "away": "NYL", "status": "Live"}]},
            )
            (processed_root / "game_cards_2026-06-05.csv").write_text(
                "date,game_id,event_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-06-05,0401,401856963,Las Vegas Aces,New York Liberty,2026-06-05T23:00:00Z,-140,120,-4.5,4.5,163.5,oddsapi_consensus,LAS,NYL\n",
                encoding="utf-8",
            )
            (processed_root / "live_lens_signals_2026-06-05.jsonl").write_text(
                json.dumps({"market": "total", "game_id": "0401", "home": "LAS", "away": "NYL", "live_line": 163.5}) + "\n",
                encoding="utf-8",
            )
            (processed_root / "live_lens_projections_2026-06-05.jsonl").write_text(
                json.dumps({"market": "player_prop", "game_id": "0401", "home": "LAS", "away": "NYL", "player": "Breanna Stewart", "team": "NYL", "opponent": "LAS", "stat": "pts", "line": 17.5, "proj": 23.0, "sim_mu": 21.0, "klass": "BET"}) + "\n",
                encoding="utf-8",
            )

            with patch.object(module, "_source_app_fallback_enabled", return_value=False), patch(
                "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
                return_value={"games": [{"event_id": "401856963", "players": []}]},
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_lines_path", copied)
            self.assertIn("live_player_lens_path", copied)
            lines_payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_lines_2026-06-05.jsonl")
            lens_payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_player_lens_2026-06-05.jsonl")

        self.assertIsNotNone(((((lines_payload or {}).get("games") or [{}])[0].get("lines") or {}).get("total")))
        self.assertEqual((((lens_payload or {}).get("games") or [{}])[0].get("rows") or [{}])[0].get("player"), "Breanna Stewart")
        self.assertEqual((((lens_payload or {}).get("games") or [{}])[0].get("rows") or [{}])[0].get("line_source"), "live_lens_projection_artifact")

    def test_export_live_snapshot_artifacts_prefers_richer_local_live_lines(self) -> None:
        module = self._load_module()

        class _FakeResponse:
            def __init__(self, payload):
                self.status_code = 200
                self._payload = payload

            def get_json(self):
                return self._payload

        class _FakeClient:
            def get(self, query):
                if query.startswith("/api/live_state"):
                    return _FakeResponse({"ok": True, "games": [{"event_id": "401856963", "status": "Live"}]})
                if query.startswith("/api/live_lines"):
                    return _FakeResponse(
                        {
                            "ok": True,
                            "games": [{"event_id": "401856963", "found": True, "lines": {"total": 163.5, "period_totals": {}, "period_spreads": {}}}],
                        }
                    )
                return _FakeResponse({"ok": True, "games": []})

        class _FakeSourceApp:
            class app:
                @staticmethod
                def test_client():
                    return _FakeClient()

        def _fake_local_payload(*, kind, date_str, event_ids):
            if kind != "live_lines":
                return None
            return {
                "ok": True,
                "games": [
                    {
                        "event_id": "401856963",
                        "found": True,
                        "lines": {
                            "total": 162.5,
                            "period_totals": {"q1": 40.5},
                            "period_spreads": {"q1": -2.5},
                        },
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            with patch.object(module, "_source_app_fallback_enabled", return_value=True), patch.object(
                module,
                "_load_source_app",
                return_value=_FakeSourceApp(),
            ), patch.object(
                module,
                "_build_local_live_snapshot_payload",
                side_effect=_fake_local_payload,
            ), patch.object(
                module,
                "_build_bundle_local_live_snapshot_payload",
                return_value=None,
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_lines_path", copied)
            lines_payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_lines_2026-06-05.jsonl")

        lines = ((((lines_payload or {}).get("games") or [{}])[0].get("lines") or {}))
        self.assertEqual((lines.get("period_totals") or {}).get("q1"), 40.5)
        self.assertEqual((lines.get("period_spreads") or {}).get("q1"), -2.5)

    def test_export_live_snapshot_artifacts_builds_live_lines_from_processed_game_odds(self) -> None:
        module = self._load_module()

        class _FakeSourceApp:
            @staticmethod
            def _live_oddsapi_period_totals_for_game(date_str, home_tri, away_tri):
                return {}

        def _fake_local_payload(*, kind, date_str, event_ids):
            if kind == "live_state":
                return {
                    "ok": True,
                    "games": [
                        {
                            "event_id": "401856963",
                            "game_id": "0401",
                            "home": "LAS",
                            "away": "NYL",
                            "in_progress": False,
                            "final": True,
                            "status": "Final",
                        }
                    ],
                }
            if kind == "live_lines":
                return {"ok": True, "games": [{"event_id": "401856963", "found": True, "lines": {"period_totals": None, "period_spreads": None}}]}
            return None

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            (source_root / "data" / "processed").mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            (source_root / "data" / "processed" / "game_odds_2026-06-05.csv").write_text(
                "date,commence_time,home_team,visitor_team,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "2026-06-05,2026-06-05T23:00:00Z,Las Vegas Aces,New York Liberty,-140,120,-4.5,4.5,163.5,oddsapi_consensus\n",
                encoding="utf-8",
            )

            with patch.object(module, "_source_app_fallback_enabled", return_value=False), patch.object(
                module,
                "_load_source_app",
                return_value=_FakeSourceApp(),
            ), patch.object(
                module,
                "_build_local_live_snapshot_payload",
                side_effect=_fake_local_payload,
            ), patch.object(
                module,
                "_build_bundle_local_live_snapshot_payload",
                return_value=None,
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_lines_path", copied)
            lines_payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_lines_2026-06-05.jsonl")

        game = ((lines_payload or {}).get("games") or [{}])[0]
        lines = game.get("lines") or {}
        self.assertEqual(lines.get("total"), 163.5)
        self.assertEqual(lines.get("home_spread"), -4.5)
        self.assertEqual(lines.get("away_spread"), 4.5)
        self.assertEqual(game.get("home"), "LVA")
        self.assertEqual(game.get("away"), "NYL")

    def test_materialize_artifact_bundle_exports_live_snapshots_when_outputs_already_in_bundle(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            artifact_root = tmp_root / "bundle"
            processed_root = artifact_root / "data" / "processed"
            raw_root = artifact_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            source_root = tmp_root / "source"
            source_root.mkdir(parents=True, exist_ok=True)

            state = {
                "date": "2026-06-06",
                "snapshot_alias_path": str(processed_root / "oddsapi_player_props_2026-06-06.csv"),
                "predictions_path": str(processed_root / "props_predictions_2026-06-06.csv"),
                "edges_path": str(processed_root / "props_edges_2026-06-06.csv"),
                "recs_path": str(processed_root / "props_recommendations_2026-06-06.csv"),
                "snapshot_path": str(raw_root / "odds_wnba_player_props_2026-06-06.csv"),
            }
            for path_text in state.values():
                if isinstance(path_text, str) and path_text.endswith((".csv", ".jsonl", ".json")):
                    Path(path_text).parent.mkdir(parents=True, exist_ok=True)
                    Path(path_text).write_text("id\n1\n", encoding="utf-8")

            with patch.object(module, "_export_live_snapshot_artifacts", return_value={"live_lines_path": "written"}) as export_snapshots, patch.object(
                module,
                "_build_optional_player_recon_artifacts",
                return_value={},
            ):
                copied = module._materialize_artifact_bundle(
                    state=state,
                    artifact_root=artifact_root,
                    source_root=source_root,
                )

        export_snapshots.assert_called_once_with(source_root=artifact_root, date_str="2026-06-06", processed_root=processed_root)
        self.assertEqual(copied.get("live_lines_path"), "written")

    def test_materialize_artifact_bundle_builds_game_cards_when_bundle_lacks_export(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            artifact_root = tmp_root / "bundle"
            processed_root = artifact_root / "data" / "processed"
            raw_root = artifact_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            source_root = tmp_root / "source"
            source_root.mkdir(parents=True, exist_ok=True)

            date_str = "2026-06-27"
            (processed_root / f"game_odds_{date_str}.csv").write_text(
                "date,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "2026-06-27,Chicago Sky,Minnesota Lynx,2026-06-27T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus\n",
                encoding="utf-8",
            )
            (raw_root / f"odds_wnba_player_props_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,h2h,Chicago Sky,,,-140,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,h2h,Minnesota Lynx,,,120,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,spreads,Chicago Sky,,-4.5,-110,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,spreads,Minnesota Lynx,,4.5,-110,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,totals,Over,,164.5,-110,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,totals,Under,,164.5,-110,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n",
                encoding="utf-8",
            )

            state = {
                "date": date_str,
                "snapshot_alias_path": str(processed_root / f"oddsapi_player_props_{date_str}.csv"),
                "predictions_path": str(processed_root / f"props_predictions_{date_str}.csv"),
                "edges_path": str(processed_root / f"props_edges_{date_str}.csv"),
                "recs_path": str(processed_root / f"props_recommendations_{date_str}.csv"),
                "snapshot_path": str(raw_root / f"odds_wnba_player_props_{date_str}.csv"),
            }
            (processed_root / f"oddsapi_player_props_{date_str}.csv").write_text("id\n1\n", encoding="utf-8")

            with patch.object(module, "_export_recon_games_artifact", return_value=None), patch.object(module, "_export_recon_quarters_artifact", return_value=None), patch.object(module, "_export_boxscores_artifact", return_value=None), patch.object(module, "_export_recommendations_artifact", return_value=None), patch.object(module, "_export_recommendations_slate_snapshot", return_value=None), patch.object(module, "_export_cards_props_snapshot", return_value=None), patch.object(module, "_export_cards_sim_detail_snapshot", return_value=None), patch.object(module, "_export_top_by_game_snapshot", return_value=None), patch.object(module, "_export_live_lens_artifacts", return_value={}), patch.object(module, "_build_optional_player_recon_artifacts", return_value={}), patch.object(module, "_export_live_snapshot_artifacts", return_value={}):
                copied = module._materialize_artifact_bundle(
                    state=state,
                    artifact_root=artifact_root,
                    source_root=source_root,
                )

            game_cards_path = processed_root / f"game_cards_{date_str}.csv"
            self.assertTrue(game_cards_path.exists())
            self.assertIn("game_cards_path", copied)
            written = game_cards_path.read_text(encoding="utf-8")
            self.assertIn("Chicago Sky", written)
            self.assertIn("Minnesota Lynx", written)

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
                    "snapshot_path": kwargs["log_file"].parent / "odds_wnba_player_props_2026-05-22.csv",
                    "snapshot_alias_path": kwargs["log_file"].parent / "oddsapi_player_props_2026-05-22.csv",
                    "predictions_path": kwargs["log_file"].parent / "props_predictions_2026-05-22.csv",
                    "edges_path": kwargs["log_file"].parent / "props_edges_2026-05-22.csv",
                    "recs_path": kwargs["log_file"].parent / "props_recommendations_2026-05-22.csv",
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            for name in [
                "odds_wnba_player_props_2026-05-22.csv",
                "oddsapi_player_props_2026-05-22.csv",
                "props_predictions_2026-05-22.csv",
                "props_edges_2026-05-22.csv",
                "props_recommendations_2026-05-22.csv",
                "smart_sim_2026-05-22_ATL_DAL.json",
                "smart_sim_2026-05-22_IND_GSV.json",
            ]:
                (tmp_root / name).write_text("id\n1\n", encoding="utf-8")
            source_root = tmp_root / "source"
            source_root.mkdir()
            artifact_root = tmp_root / "bundle"
            argv = [
                "refresh_wnba_oddsapi_props.py",
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
                                    return {"games": [{"home_tri": "ATL", "away_tri": "DAL"}]}
                                if "/api/cards" in query:
                                    return {
                                        "games": [
                                            {
                                                "home_tri": "ATL",
                                                "away_tri": "DAL",
                                                "prop_recommendations": {
                                                    "home": [{"player": "Home WNBA Prop"}],
                                                    "away": [{"player": "Away WNBA Prop"}],
                                                },
                                                "sim": {
                                                    "players": {
                                                        "home": [{"player": "Home WNBA Sim"}],
                                                        "away": [{"player": "Away WNBA Sim"}],
                                                    },
                                                    "missing_prop_players": {
                                                        "home": [{"player": "Missing Home WNBA"}],
                                                        "away": [{"player": "Missing Away WNBA"}],
                                                    },
                                                    "injuries": {
                                                        "home": [{"player": "Injured Home WNBA"}],
                                                        "away": [{"player": "Injured Away WNBA"}],
                                                    },
                                                },
                                            }
                                        ]
                                    }
                                return {"data": [{"player": "Test WNBA Player"}]}

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
                recon_path.write_text("player\nTest WNBA Player\n", encoding="utf-8")
                tuning_path.write_text("player\nTest WNBA Player\n", encoding="utf-8")
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

            def _fake_recon_games_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recon_games_{date_str}.csv"
                out_path.write_text("game_id\n123\n", encoding="utf-8")
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

            def _fake_cards_sim_detail_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"cards_sim_detail_{date_str}.json"
                out_path.write_text('{"games": []}\n', encoding="utf-8")
                return str(out_path)

            def _fake_recommendations_slate_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recommendations_slate_{date_str}.json"
                out_path.write_text('{"counts": {"games": 1, "picks": 1}, "per_game": []}\n', encoding="utf-8")
                return str(out_path)

            def _fake_cards_props_snapshot_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"cards_props_snapshot_{date_str}.json"
                out_path.write_text('{"games": []}\n', encoding="utf-8")
                return str(out_path)

            def _fake_top_by_game_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"props_recommendations_top_by_game_{date_str}.json"
                out_path.write_text('{"data": []}\n', encoding="utf-8")
                return str(out_path)

            def _fake_live_lens_artifacts(*, source_root, date_str, processed_root, live_lens_root):
                processed_root.mkdir(parents=True, exist_ok=True)
                live_lens_root.mkdir(parents=True, exist_ok=True)
                signals_processed = processed_root / f"live_lens_signals_{date_str}.jsonl"
                projections_processed = processed_root / f"live_lens_projections_{date_str}.jsonl"
                tuning_processed = processed_root / "live_lens_tuning_override.json"
                signals_live_lens = live_lens_root / f"live_lens_signals_{date_str}.jsonl"
                projections_live_lens = live_lens_root / f"live_lens_projections_{date_str}.jsonl"
                tuning_live_lens = live_lens_root / "live_lens_tuning_override.json"
                for path, content in (
                    (signals_processed, '{"kind":"signal"}\n'),
                    (projections_processed, '{"kind":"projection"}\n'),
                    (tuning_processed, '{"alpha":1.25}\n'),
                    (signals_live_lens, '{"kind":"signal"}\n'),
                    (projections_live_lens, '{"kind":"projection"}\n'),
                    (tuning_live_lens, '{"alpha":1.25}\n'),
                ):
                    path.write_text(content, encoding="utf-8")
                return {
                    "live_lens_signals_path": str(signals_processed),
                    "live_lens_projections_path": str(projections_processed),
                    "live_lens_tuning_override_path": str(tuning_processed),
                    "live_lens_signals_live_lens_path": str(signals_live_lens),
                    "live_lens_projections_live_lens_path": str(projections_live_lens),
                    "live_lens_tuning_override_live_lens_path": str(tuning_live_lens),
                }

            with patch.object(module, "_run_refresh_via_cli", return_value=_FakeSourceModule().run_refresh_oddsapi_props_job(log_file=tmp_root / "refresh.log")), patch.object(module, "_load_source_app", return_value=_FakeSourceApp()), patch.object(module, "_build_optional_player_recon_artifacts", side_effect=_fake_optional_artifacts), patch.object(module, "_export_recon_games_artifact", side_effect=_fake_recon_games_artifact), patch.object(module, "_export_game_cards_artifact", side_effect=_fake_game_cards_artifact), patch.object(module, "_export_boxscores_artifact", side_effect=_fake_boxscores_artifact), patch.object(module, "_export_recommendations_artifact", side_effect=_fake_recommendations_artifact), patch.object(module, "_export_recommendations_slate_snapshot", side_effect=_fake_recommendations_slate_artifact), patch.object(module, "_export_cards_props_snapshot", side_effect=_fake_cards_props_snapshot_artifact), patch.object(module, "_export_cards_sim_detail_snapshot", side_effect=_fake_cards_sim_detail_artifact), patch.object(module, "_export_top_by_game_snapshot", side_effect=_fake_top_by_game_artifact), patch.object(module, "_export_live_lens_artifacts", side_effect=_fake_live_lens_artifacts), patch.object(module, "_export_recon_quarters_artifact", side_effect=_fake_recon_quarters_artifact), patch.object(module, "_export_recon_props_artifact", side_effect=_fake_recon_props_artifact), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "raw" / "odds_wnba_player_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "oddsapi_player_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_predictions_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_edges_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_recommendations_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_ATL_DAL.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_IND_GSV.json").exists())
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
                raw_root / f"odds_wnba_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"oddsapi_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"props_predictions_{date_str}.csv": "player\nA\n",
                processed_root / f"props_edges_{date_str}.csv": "player\nA\n",
                processed_root / f"props_recommendations_{date_str}.csv": "player\nA\n",
                processed_root / f"game_cards_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_slate_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_props_snapshot_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_sim_detail_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"props_recommendations_top_by_game_{date_str}.json": "{\"ok\": true}\n",
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
            (processed_root / "smart_sim_2026-05-22_ATL_DAL.json").write_text('{"ok": true}\n', encoding="utf-8")

            argv = [
                "refresh_wnba_oddsapi_props.py",
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
            self.assertTrue((artifact_root / "data" / "raw" / f"odds_wnba_player_props_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_predictions_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_edges_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_recommendations_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"game_cards_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "boxscores_history.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_ATL_DAL.json").exists())
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
                raw_root / f"odds_wnba_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"oddsapi_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"props_predictions_{date_str}.csv": "player\nA\n",
                processed_root / f"props_edges_{date_str}.csv": "player\nA\n",
                processed_root / f"props_recommendations_{date_str}.csv": "player\nA\n",
                processed_root / f"game_cards_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_slate_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_props_snapshot_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_sim_detail_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"props_recommendations_top_by_game_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"smart_sim_{date_str}_ATL_DAL.json": "{\"ok\": true}\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            argv = [
                "refresh_wnba_oddsapi_props.py",
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
