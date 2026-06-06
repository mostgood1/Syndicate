from __future__ import annotations

import csv
import importlib.util
import json
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
            (raw_root / f"odds_nba_current_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Boston Celtics,,,-140,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,New York Knicks,,,120,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Boston Celtics,,-4.5,-110,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,New York Knicks,,4.5,-110,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Over,,218.5,-110,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Under,,218.5,-110,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n",
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
        self.assertEqual(written[0].get("home_team"), "Boston Celtics")
        self.assertEqual(written[0].get("visitor_team"), "New York Knicks")
        self.assertEqual(written[0].get("home_tri"), "BOS")
        self.assertEqual(written[0].get("away_tri"), "NYK")
        self.assertEqual(written[0].get("bookmaker"), "oddsapi_consensus")

    def test_ensure_source_game_cards_export_invokes_source_cli(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            game_cards_path = processed_root / f"game_cards_{date_str}.csv"
            calls: list[list[str]] = []

            def fake_cli(*, source_root, package_name, command_parts, log_file, heartbeat_cb, timeout_s):
                calls.append(list(command_parts))
                game_cards_path.write_text(
                    "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                    "2026-05-22,1,Boston Celtics,New York Knicks,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,218.5,oddsapi_consensus,BOS,NYK\n",
                    encoding="utf-8",
                )
                return 0

            module._run_source_subprocess_cli_command = fake_cli
            module._build_local_game_cards_artifact = lambda **kwargs: (1, game_cards_path)

            rows, out_path = module._ensure_source_game_cards_export(
                source_root=source_root,
                package_name="nba_betting",
                date_str=date_str,
                processed_root=processed_root,
                log_file=Path(tmp_dir) / "refresh.log",
                heartbeat_cb=None,
            )

            self.assertIn(["export-game-cards", "--date", date_str], calls)
            self.assertEqual(rows, 1)
            self.assertEqual(out_path, game_cards_path)
            self.assertTrue(game_cards_path.exists())

    def test_export_cards_sim_detail_snapshot_uses_source_cards_api_fallback(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"

            class FakeResponse:
                status_code = 200

                def get_json(self):
                    return {
                        "games": [
                            {
                                "home_tri": "BOS",
                                "away_tri": "NYK",
                                "sim": {
                                    "players_summary": {"home": 1, "away": 1},
                                    "players": {"home": [{"player_name": "A"}], "away": [{"player_name": "B"}]},
                                    "missing_prop_players": {"home": [], "away": []},
                                    "injuries": {"home": [], "away": []},
                                },
                            }
                        ]
                    }

            class FakeClient:
                def get(self, query):
                    self.query = query
                    return FakeResponse()

            class FakeApp:
                def test_client(self):
                    return FakeClient()

            module._source_app_fallback_enabled = lambda: True
            module._load_source_app = lambda source_root: types.SimpleNamespace(app=FakeApp())

            out_path = module._export_cards_sim_detail_snapshot(
                source_root=source_root,
                date_str=date_str,
                processed_root=processed_root,
            )

            self.assertIsNotNone(out_path)
            assert out_path is not None
            self.assertTrue(Path(out_path).exists())
            payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["date"], date_str)
            self.assertEqual(len(payload["games"]), 1)
            self.assertEqual(payload["games"][0]["home_tri"], "BOS")

    def test_ensure_source_game_inputs_exports_game_cards_when_missing(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            (processed_root / "game_odds_2026-05-22.csv").write_text(
                "game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "1,Boston Celtics,New York Knicks,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,218.5,oddsapi_consensus\n",
                encoding="utf-8",
            )

            calls: list[list[str]] = []

            def fake_cli(*, source_root, package_name, command_parts, log_file, heartbeat_cb, timeout_s):
                calls.append(list(command_parts))
                if command_parts and command_parts[0] == "export-game-cards":
                    out_path = source_root / "data" / "processed" / f"game_cards_{date_str}.csv"
                    out_path.write_text(
                        "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                        "2026-05-22,1,Boston Celtics,New York Knicks,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,218.5,oddsapi_consensus,BOS,NYK\n",
                        encoding="utf-8",
                    )
                return 0

            module._run_source_subprocess_cli_command = fake_cli
            module._seed_game_odds_from_props_snapshot = lambda **kwargs: None
            module._seed_game_odds_from_raw_history = lambda **kwargs: None

            result = module._ensure_source_game_inputs(
                source_root=source_root,
                package_name="nba_betting",
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
                heartbeat_cb=None,
            )

            game_cards_path = processed_root / f"game_cards_{date_str}.csv"

            self.assertIn(["export-game-cards", "--date", date_str], calls)
            self.assertTrue(game_cards_path.exists())
            with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))
            self.assertGreater(len(written), 0)

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
                "2026-05-22,0401,Boston Celtics,New York Knicks,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,218.5,oddsapi_consensus,BOS,NYK\n",
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
                        "side": "Boston Celtics",
                        "home": "Boston Celtics",
                        "away": "New York Knicks",
                        "date": date_str,
                        "ev": 0.08,
                        "price": -110,
                        "implied_prob": 0.5238,
                        "edge": 2.0,
                        "line": 4.5,
                        "pred_margin": 6.5,
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
            ]
            with (processed_root / f"props_recommendations_{date_str}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=prop_columns)
                writer.writeheader()
                writer.writerow(
                    {
                        "player": "Jayson Tatum",
                        "team": "BOS",
                        "plays": str([{"market": "pts", "side": "OVER", "line": 27.5, "price": -110, "edge": 1.8, "ev": 0.09, "ev_pct": 9.0, "book": "fanduel"}]),
                        "ladders": "[]",
                        "sim_ladders": "[]",
                        "model": str({"pts": 29.2, "reb": 8.1}),
                        "_plays_list": str([{"market": "pts", "side": "OVER", "line": 27.5, "price": -110, "edge": 1.8, "ev": 0.09, "ev_pct": 9.0, "book": "fanduel"}]),
                        "top_play": str({"market": "pts", "side": "OVER", "line": 27.5, "price": -110, "edge": 1.8, "ev": 0.09, "ev_pct": 9.0, "book": "fanduel"}),
                        "top_play_explain": "model 29.2 vs line 27.5 (+1.7)",
                        "top_play_baseline": "29.2",
                        "top_play_reasons": str(["EV 9.0%", "Regular price range (-150 to +150)"]),
                        "top_play_consensus": "0.5",
                        "top_play_line_adv": "1.0",
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
        self.assertEqual(slate_payload["per_game"][0]["home"], "BOS")
        self.assertEqual(props_payload["games"][0]["prop_recommendations"]["home"][0]["player"], "Jayson Tatum")
        self.assertEqual(top_payload["data"][0]["team_tricode"], "BOS")
        self.assertEqual(top_payload["data"][0]["top_play"]["market"], "pts")

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
                "2026-05-29,1234567890,Boston Celtics,New York Knicks,2026-05-29T19:00:00Z,-130,110,-4.5,4.5,219.5,oddsapi_consensus,BOS,NYK\n",
                encoding="utf-8",
            )
            (processed_root / f"boxscores_{date_str}.csv").write_text(
                "GAME_ID,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,PTS\n"
                "1234567890,BOS,1,Jayson Tatum,30\n"
                "1234567890,BOS,2,Jaylen Brown,25\n"
                "1234567890,NYK,3,Jalen Brunson,28\n"
                "1234567890,NYK,4,Karl-Anthony Towns,20\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                out = module._export_recon_games_artifact(source_root=source_root, date_str=date_str, processed_root=processed_root)

            self.assertEqual(out, str(processed_root / f"recon_games_{date_str}.csv"))
            with (processed_root / f"recon_games_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_team"], "Boston Celtics")
        self.assertEqual(rows[0]["visitor_team"], "New York Knicks")
        self.assertEqual(rows[0]["home_pts"], "55")
        self.assertEqual(rows[0]["visitor_pts"], "48")
        self.assertEqual(rows[0]["total_actual"], "103")

    def test_cards_sim_detail_export_uses_local_smart_sim(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True)
            (processed_root / "smart_sim_2026-05-29_BOS_NYK.json").write_text(
                json.dumps(
                    {
                        "home": "BOS",
                        "away": "NYK",
                        "periods": {"q1": {"away_mean": 26.1, "home_mean": 28.4, "total_mean": 54.5, "margin_mean": 2.3, "p_home_win": 0.61}},
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
            self.assertEqual(payload["games"][0]["sim"]["quarters"][0]["away_pts_mu"], 26.1)

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
            (raw_root / "odds_nba_current_2026-05-22.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Boston Celtics,,,-140,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,New York Knicks,,,120,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Boston Celtics,,-4.5,-110,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,New York Knicks,,4.5,-110,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Over,,218.5,-110,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Under,,218.5,-110,2026-05-22T12:00:00Z,Boston Celtics,New York Knicks\n",
                encoding="utf-8",
            )
            (processed_root / "smart_sim_2026-05-22_BOS_NYK.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "home": "BOS",
                        "away": "NYK",
                        "quarters": [
                            {"home_pts_mu": 27.0, "away_pts_mu": 24.0},
                            {"home_pts_mu": 27.0, "away_pts_mu": 25.0},
                            {"home_pts_mu": 26.0, "away_pts_mu": 24.0},
                            {"home_pts_mu": 26.0, "away_pts_mu": 23.0}
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
                "2026-05-22,0401,Boston Celtics,New York Knicks,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,218.5,oddsapi_consensus,BOS,NYK\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_BOS_NYK.json").write_text(
                json.dumps(
                    {
                        "date": date_str,
                        "home": "BOS",
                        "away": "NYK",
                        "quarters": [
                            {"home_pts_mu": 30.0, "away_pts_mu": 27.0},
                            {"home_pts_mu": 29.0, "away_pts_mu": 28.0},
                            {"home_pts_mu": 30.0, "away_pts_mu": 27.0},
                            {"home_pts_mu": 29.0, "away_pts_mu": 28.0},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (processed_source / f"live_lens_projections_{date_str}.jsonl").write_text(
                json.dumps({"market": "player_prop", "player": "Jayson Tatum"}) + "\n",
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
        self.assertEqual(rows[0]["klass"], "BET")
        self.assertEqual(rows[0]["side"], "OVER")
        self.assertEqual(rows[0]["live_line"], 218.5)
        self.assertEqual(rows[0]["pred"], 228.0)
        self.assertEqual(rows[0]["remaining"], 48)

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
                "2026-05-22,0401,Boston Celtics,New York Knicks,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,218.5,oddsapi_consensus,BOS,NYK\n",
                encoding="utf-8",
            )
            (processed_root / f"props_predictions_{date_str}.csv").write_text(
                "player_name,team,opponent,home,pred_pts,mean_pts,pred_reb,mean_reb\n"
                "Jayson Tatum,BOS,NYK,1,29.2,28.7,8.4,8.1\n",
                encoding="utf-8",
            )
            (processed_root / f"props_edges_{date_str}.csv").write_text(
                "player_name,team,stat,line\n"
                "Jayson Tatum,BOS,pts,27.5\n",
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
        pts_row = next(row for row in rows if row["stat"] == "pts")
        self.assertEqual(pts_row["market"], "player_prop")
        self.assertEqual(pts_row["game_id"], "0401")
        self.assertEqual(pts_row["home"], "BOS")
        self.assertEqual(pts_row["away"], "NYK")
        self.assertEqual(pts_row["proj"], 29.2)
        self.assertEqual(pts_row["sim_mu"], 28.7)
        self.assertEqual(pts_row["line"], 27.5)

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
                "2026-05-22,0401,Boston Celtics,New York Knicks,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,218.5,oddsapi_consensus,BOS,NYK\n",
                encoding="utf-8",
            )
            (processed_root / f"boxscores_{date_str}.csv").write_text(
                "date,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,PTS,REB,AST,FG3M,STL,BLK,TOV\n"
                "2026-05-22,BOS,0,Jayson Tatum,31,8,5,4,2,1,3\n",
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
        self.assertEqual(rows[0]["player_name"], "Jayson Tatum")
        self.assertEqual(rows[0]["team_abbr"], "BOS")
        self.assertEqual(rows[0]["threes"], "4")
        self.assertEqual(rows[0]["pr"], "39")
        self.assertEqual(rows[0]["pa"], "36")
        self.assertEqual(rows[0]["ra"], "13")
        self.assertEqual(rows[0]["pra"], "44")


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
                "2026-05-22,0401,Boston Celtics,New York Knicks,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,218.5,oddsapi_consensus,BOS,NYK\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_BOS_NYK.json").write_text(
                json.dumps(
                    {
                        "game_id": "0401",
                        "home": "BOS",
                        "away": "NYK",
                        "players": {
                            "home": [
                                {
                                    "player_id": 7,
                                    "player_name": "Jayson Tatum",
                                    "min_mean": 35.0,
                                    "pts_mean": 30.0,
                                    "reb_mean": 8.0,
                                    "ast_mean": 5.0,
                                    "threes_mean": 3.0,
                                    "pra_mean": 43.0,
                                    "stl_mean": 2.0,
                                    "blk_mean": 1.0,
                                    "tov_mean": 4.0,
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
                "0401,BOS,7,Jayson Tatum,36:00,28,9,6,4,8,10,20,4,5,2,1,3,2,3,6,11\n",
                encoding="utf-8",
            )
            (processed_root / f"props_predictions_{date_str}.csv").write_text(
                "player_id,player_name,team,opponent,roll10_min,mean_pts,mean_reb,mean_ast,mean_threes,mean_pra\n"
                "7,Jayson Tatum,BOS,NYK,35.0,30.0,8.0,5.0,3.0,43.0\n",
                encoding="utf-8",
            )
            (processed_root / f"props_edges_{date_str}.csv").write_text(
                "team,player_name,stat,line\n"
                "BOS,Jayson Tatum,pts,27.5\n"
                "BOS,Jayson Tatum,pra,41.5\n",
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
        self.assertEqual(recon_rows[0]["player_name"], "Jayson Tatum")
        self.assertEqual(recon_rows[0]["actual_pts"], "28.0")
        pts_row = next(row for row in tuning_rows if row["stat"] == "pts")
        self.assertEqual(pts_row["player_name"], "Jayson Tatum")
        self.assertEqual(pts_row["game_id"], "0401")
        self.assertEqual(pts_row["actual"], "28.0")
        self.assertEqual(pts_row["line"], "27.5")

    def test_export_live_snapshot_artifacts_builds_local_snapshots_without_source_app(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            def _fake_local_payload(*, kind: str, date_str: str, event_ids: list[str]):
                if kind == "live_state":
                    return {"ok": True, "games": [{"event_id": "401859964", "status": "Live"}]}
                if kind == "live_player_lens":
                    return {"ok": True, "games": [{"event_id": "401859964", "rows": [{"player": "Test Player"}]}]}
                return {"ok": True, "games": [{"event_id": "401859964"}]}

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
            snapshot_path = processed_root / "live_snapshots" / "live_player_lens_2026-06-05.jsonl"
            payload = module._read_live_snapshot_payload(snapshot_path)
            self.assertEqual((((payload or {}).get("games") or [{}])[0].get("rows") or [{}])[0].get("player"), "Test Player")

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
                {"ok": True, "games": [{"event_id": "401859964", "status": "Live"}]},
            )
            module._write_live_snapshot_payload(
                source_snapshots / "live_lines_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401859964", "found": False, "lines": {}}]},
            )
            module._write_live_snapshot_payload(
                source_snapshots / "live_player_lens_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401859964", "rows": []}]},
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

    def test_season_betting_card_export_uses_local_manifest_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            date_str = "2026-05-22"
            season = module._resolve_nba_season_year(date_str)
            processed_source.mkdir(parents=True, exist_ok=True)
            (processed_source / f"season_betting_card_manifest_{season}_retuned.json").write_text(
                '{"ok": true, "cards_url": "/?date=2026-05-22", "date": "2026-05-22"}\n',
                encoding="utf-8",
            )
            (processed_source / f"season_betting_card_day_{season}_retuned_{date_str}.json").write_text(
                '{"ok": true, "cards_url": "/?date=2026-05-22"}\n',
                encoding="utf-8",
            )
            (processed_source / f"season_betting_card_day_{season}_retuned_{date_str}_insights.json").write_text(
                '{"ok": true, "cards_url": "/?date=2026-05-22", "insights": [{"label": "Prop Insight"}]}\n',
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_season_betting_card_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                )

            self.assertEqual(copied["season_betting_card_manifest_path"], str(processed_root / f"season_betting_card_manifest_{season}_retuned_{date_str}.json"))
            self.assertEqual(copied["season_betting_card_manifest_generic_path"], str(processed_root / f"season_betting_card_manifest_{season}_retuned.json"))
            payload = json.loads((processed_root / f"season_betting_card_manifest_{season}_retuned_{date_str}.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["cards_url"], "/nba/cards?date=2026-05-22")
            day_payload = json.loads((processed_root / f"season_betting_card_day_{season}_retuned_{date_str}.json").read_text(encoding="utf-8"))
            self.assertEqual(day_payload["cards_url"], "/nba/cards?date=2026-05-22")

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

            with patch.object(module, "_run_refresh_via_cli", return_value=_FakeSourceModule().run_refresh_oddsapi_props_job(log_file=tmp_root / "refresh.log")), patch.object(module, "_load_source_app", return_value=_FakeSourceApp()), patch.object(module, "_build_optional_player_recon_artifacts", side_effect=_fake_optional_artifacts), patch.object(module, "_export_game_cards_artifact", side_effect=_fake_game_cards_artifact), patch.object(module, "_export_boxscores_artifact", side_effect=_fake_boxscores_artifact), patch.object(module, "_export_recommendations_artifact", side_effect=_fake_recommendations_artifact), patch.object(module, "_export_recommendations_slate_snapshot", side_effect=_fake_recommendations_slate_artifact), patch.object(module, "_export_cards_props_snapshot", side_effect=_fake_cards_props_snapshot_artifact), patch.object(module, "_export_cards_sim_detail_snapshot", side_effect=_fake_cards_sim_detail_artifact), patch.object(module, "_export_top_by_game_snapshot", side_effect=_fake_top_by_game_artifact), patch.object(module, "_export_recon_quarters_artifact", side_effect=_fake_recon_quarters_artifact), patch.object(module, "_export_recon_props_artifact", side_effect=_fake_recon_props_artifact), patch("sys.argv", argv):
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
