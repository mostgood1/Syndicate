from __future__ import annotations

import csv
from contextlib import ExitStack
import sys
import types
import unittest
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import syndicate.features.shared.basketball_props_predictions as predictions_module
import syndicate.features.shared.basketball_props_smart_sim as smart_sim_module
from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local


class BasketballPropsPredictionsTests(unittest.TestCase):
    class _FakeSeries:
        def __init__(self, values: list[object]) -> None:
            self.values = values

        def clip(self, lower: float | None = None, upper: float | None = None):
            clipped: list[object] = []
            for value in self.values:
                if value is None:
                    clipped.append(value)
                    continue
                current = float(value)
                if lower is not None and current < lower:
                    current = lower
                if upper is not None and current > upper:
                    current = upper
                clipped.append(current)
            return BasketballPropsPredictionsTests._FakeSeries(clipped)

        def fillna(self, default: float):
            return BasketballPropsPredictionsTests._FakeSeries([
                default if value is None else value for value in self.values
            ])

        def notna(self):
            return BasketballPropsPredictionsTests._FakeSeries([value is not None for value in self.values])

        def astype(self, dtype):
            if dtype in (str, "str"):
                return BasketballPropsPredictionsTests._FakeSeries([
                    "" if value is None else str(value) for value in self.values
                ])
            return self

        def __add__(self, other):
            if isinstance(other, BasketballPropsPredictionsTests._FakeSeries):
                return BasketballPropsPredictionsTests._FakeSeries([
                    (0.0 if left is None else float(left)) + (0.0 if right is None else float(right))
                    for left, right in zip(self.values, other.values)
                ])
            return BasketballPropsPredictionsTests._FakeSeries([
                (0.0 if value is None else float(value)) + float(other) for value in self.values
            ])

    class _FakeFrame:
        def __init__(self, rows: list[dict[str, object]]) -> None:
            self.rows = rows

        @property
        def columns(self) -> list[str]:
            return list(self.rows[0].keys()) if self.rows else []

        @property
        def empty(self) -> bool:
            return len(self.rows) == 0

        @property
        def index(self) -> range:
            return range(len(self.rows))

        def copy(self):
            return BasketballPropsPredictionsTests._FakeFrame([dict(row) for row in self.rows])

        def __getitem__(self, key: str):
            return BasketballPropsPredictionsTests._FakeSeries([row.get(key) for row in self.rows])

        def __setitem__(self, key: str, value):
            if isinstance(value, BasketballPropsPredictionsTests._FakeSeries):
                values = value.values
            else:
                values = [value for _ in self.rows]
            for row, item in zip(self.rows, values):
                row[key] = item

        def to_csv(self, path: Path, index: bool = False) -> None:
            fieldnames = list(self.rows[0].keys()) if self.rows else []
            with Path(path).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in self.rows:
                    writer.writerow(row)

    class _FakePandasModule:
        NA = None

        def __init__(self, frame):
            self._frame = frame
            self.DataFrame = BasketballPropsPredictionsTests._FakeFrame

        def read_csv(self, path):
            return self._frame.copy()

        def to_numeric(self, values, errors="coerce"):
            if isinstance(values, BasketballPropsPredictionsTests._FakeSeries):
                converted: list[object] = []
                for value in values.values:
                    try:
                        converted.append(float(value) if value not in (None, "") else None)
                    except Exception:
                        converted.append(None)
                return BasketballPropsPredictionsTests._FakeSeries(converted)
            return values

        def isna(self, value) -> bool:
            return value is None

    class _BranchFakeFrame:
        def __init__(self, rows: list[dict[str, object]]) -> None:
            self.rows = rows

        @property
        def columns(self) -> list[str]:
            return list(self.rows[0].keys()) if self.rows else []

        @property
        def empty(self) -> bool:
            return len(self.rows) == 0

        @property
        def index(self) -> range:
            return range(len(self.rows))

        def copy(self):
            return BasketballPropsPredictionsTests._BranchFakeFrame([dict(row) for row in self.rows])

        def __getitem__(self, key: str):
            return BasketballPropsPredictionsTests._FakeSeries([row.get(key) for row in self.rows])

        def __setitem__(self, key: str, value) -> None:
            values = value.values if isinstance(value, BasketballPropsPredictionsTests._FakeSeries) else [value for _ in self.rows]
            for row, item in zip(self.rows, values):
                row[key] = item

        def to_csv(self, path: Path, index: bool = False) -> None:
            fieldnames = list(self.rows[0].keys()) if self.rows else []
            with Path(path).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in self.rows:
                    writer.writerow(row)

    def test_local_to_tricode_normalizes_aliases(self) -> None:
        self.assertEqual(predictions_module._to_tricode("Boston Celtics"), "BOS")
        self.assertEqual(predictions_module._to_tricode("boston"), "BOS")
        self.assertEqual(predictions_module._to_tricode("nyk"), "NYK")

    def test_team_players_from_props_local_uses_home_away_roster_matching(self) -> None:
        import pandas as pd

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            processed_root = root / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            (processed_root / "rosters_2025-26.csv").write_text(
                "PLAYER,TEAM_ABBREVIATION,PLAYER_ID\n"
                "Shai Gilgeous-Alexander,OKC,1\n"
                "Chet Holmgren,OKC,2\n"
                "Victor Wembanyama,SAS,3\n",
                encoding="utf-8",
            )
            props_df = pd.DataFrame(
                [
                    {"home_team": "Oklahoma City Thunder", "away_team": "San Antonio Spurs", "player_name": "Shai Gilgeous-Alexander"},
                    {"home_team": "Oklahoma City Thunder", "away_team": "San Antonio Spurs", "player_name": "Chet Holmgren"},
                    {"home_team": "Oklahoma City Thunder", "away_team": "San Antonio Spurs", "player_name": "Victor Wembanyama"},
                ]
            )

            home_rows = smart_sim_module._team_players_from_props_local(
                props_df=props_df,
                team_tri="OKC",
                opp_tri="SAS",
                processed_root=processed_root,
                date_str="2026-05-30",
            )
            away_rows = smart_sim_module._team_players_from_props_local(
                props_df=props_df,
                team_tri="SAS",
                opp_tri="OKC",
                processed_root=processed_root,
                date_str="2026-05-30",
            )

            self.assertEqual(sorted(home_rows["player_name"].tolist()), ["Chet Holmgren", "Shai Gilgeous-Alexander"])
            self.assertEqual(sorted(away_rows["player_name"].tolist()), ["Victor Wembanyama"])

    def test_team_players_from_props_local_normalizes_team_opponent_values(self) -> None:
        import pandas as pd

        props_df = pd.DataFrame(
            [
                {"team": "Oklahoma City Thunder", "opponent": "San Antonio Spurs", "player_name": "Shai Gilgeous-Alexander"},
                {"team": "Oklahoma City Thunder", "opponent": "San Antonio Spurs", "player_name": "Chet Holmgren"},
                {"team": "San Antonio Spurs", "opponent": "Oklahoma City Thunder", "player_name": "Victor Wembanyama"},
            ]
        )

        home_rows = smart_sim_module._team_players_from_props_local(
            props_df=props_df,
            team_tri="OKC",
            opp_tri="SAS",
        )
        away_rows = smart_sim_module._team_players_from_props_local(
            props_df=props_df,
            team_tri="SAS",
            opp_tri="OKC",
        )

        self.assertEqual(sorted(home_rows["player_name"].tolist()), ["Chet Holmgren", "Shai Gilgeous-Alexander"])
        self.assertEqual(sorted(away_rows["player_name"].tolist()), ["Victor Wembanyama"])

    def test_export_props_predictions_local_invokes_local_smart_sim_helper(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            (source_root / "src").mkdir(parents=True, exist_ok=True)
            out_path = root / "props_predictions_2026-05-22.csv"
            log_path = root / "refresh.log"
            helper_calls: list[dict[str, object]] = []
            heartbeat_ticks: list[str] = []
            previous_cwd = Path.cwd()

            def _fake_smart_sim_helper(**kwargs):
                helper_calls.append(dict(kwargs))
                Path(kwargs["out_path"]).write_text("player\nA\n", encoding="utf-8")
                return 1, kwargs["out_path"]

            with patch.object(
                predictions_module.basketball_props_smart_sim,
                "export_props_predictions_with_smart_sim_local",
                side_effect=_fake_smart_sim_helper,
            ), patch.object(
                predictions_module,
                "finalize_props_predictions_local",
                return_value=(1, out_path),
            ) as finalize_mock:
                rows, written_path = export_props_predictions_local(
                    source_root=source_root,
                    date_str="2026-05-22",
                    out_path=out_path,
                    calib_window=7,
                    calibrate_player=True,
                    player_calib_window=30,
                    player_min_pairs=6,
                    player_shrink_k=8,
                    use_smart_sim=True,
                    smart_sim_n_sims=150,
                    smart_sim_pbp=True,
                    smart_sim_workers=1,
                    log_file=log_path,
                    heartbeat_cb=lambda: heartbeat_ticks.append("tick"),
                    heartbeat_every_s=0.01,
                )

            self.assertEqual(rows, 1)
            self.assertEqual(written_path, out_path)
            self.assertEqual(len(helper_calls), 1)
            self.assertEqual(helper_calls[0]["date_str"], "2026-05-22")
            self.assertEqual(helper_calls[0]["smart_sim_n_sims"], 150)
            self.assertTrue(bool(helper_calls[0]["smart_sim_pbp"]))
            self.assertEqual(helper_calls[0]["smart_sim_workers"], 1)
            self.assertEqual(finalize_mock.call_count, 1)
            self.assertEqual(Path.cwd(), previous_cwd)
            self.assertTrue(log_path.exists())

    def test_export_props_predictions_local_passes_finalize_args(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            (source_root / "src").mkdir(parents=True, exist_ok=True)
            out_path = root / "props_predictions_2026-05-22.csv"
            finalize_calls: list[dict[str, object]] = []

            def _fake_smart_sim_helper(**kwargs):
                Path(kwargs["out_path"]).write_text("player\nA\n", encoding="utf-8")
                return 1, kwargs["out_path"]

            def _fake_finalize(**kwargs):
                finalize_calls.append(dict(kwargs))
                return 1, kwargs["out_path"]

            with patch.object(
                predictions_module.basketball_props_smart_sim,
                "export_props_predictions_with_smart_sim_local",
                side_effect=_fake_smart_sim_helper,
            ), patch.object(
                predictions_module,
                "finalize_props_predictions_local",
                side_effect=_fake_finalize,
            ):
                rows, written_path = export_props_predictions_local(
                    source_root=source_root,
                    date_str="2026-05-22",
                    out_path=out_path,
                    calib_window=7,
                    calibrate_player=True,
                    player_calib_window=30,
                    player_min_pairs=6,
                    player_shrink_k=8,
                    use_smart_sim=True,
                    smart_sim_n_sims=150,
                    smart_sim_pbp=True,
                    smart_sim_workers=1,
                )

            self.assertEqual(rows, 1)
            self.assertEqual(written_path, out_path)
            self.assertEqual(len(finalize_calls), 1)
            self.assertTrue(bool(finalize_calls[0]["calibrate"]))
            self.assertTrue(bool(finalize_calls[0]["calibrate_player"]))
            self.assertEqual(finalize_calls[0]["player_calib_window"], 30)
            self.assertEqual(finalize_calls[0]["player_min_pairs"], 6)
            self.assertEqual(finalize_calls[0]["player_shrink_k"], 8)

    def test_quarter_splits_for_team_local_uses_passed_league(self) -> None:
        fake_league = SimpleNamespace(code="wnba")

        with patch.object(smart_sim_module, "_load_quarters_calibration_local", return_value={}), patch.object(
            smart_sim_module,
            "_quarter_splits_local",
            return_value=[0.25, 0.25, 0.25, 0.25],
        ) as quarter_splits_mock:
            splits = smart_sim_module._quarter_splits_for_team_local(
                processed_root=Path("C:/tmp"),
                team_tri="NYL",
                is_home=True,
                league=fake_league,
            )

        self.assertEqual(splits, [0.25, 0.25, 0.25, 0.25])
        self.assertEqual(quarter_splits_mock.call_count, 1)
        self.assertIs(quarter_splits_mock.call_args.kwargs["league"], fake_league)

    def test_local_event_wrappers_route_usage_helper(self) -> None:
        usage_calls: list[dict[str, object]] = []
        entrypoint_calls: list[tuple[str, object]] = []
        fake_events_module = SimpleNamespace()

        def _original_usage(*args, **kwargs):
            raise AssertionError("expected local usage helper to be patched in")

        def _fake_simulate_pbp_game_boxscore(**kwargs):
            entrypoint_calls.append(("pbp", fake_events_module._player_usage_weights("players", "_prior_fga_pm", [1, 2, 3])))
            return {"mode": "pbp", "kwargs": dict(kwargs)}

        def _fake_simulate_event_level_boxscore(**kwargs):
            entrypoint_calls.append(("event", fake_events_module._player_usage_weights("players", "_prior_tov_pm", [4, 5])))
            return {"mode": "event", "kwargs": dict(kwargs)}

        fake_events_module._player_usage_weights = _original_usage
        fake_events_module.simulate_pbp_game_boxscore = _fake_simulate_pbp_game_boxscore
        fake_events_module.simulate_event_level_boxscore = _fake_simulate_event_level_boxscore

        with patch.object(smart_sim_module, "_LOCAL_EVENTS_MODULE", fake_events_module), patch.object(
            smart_sim_module,
            "_player_usage_weights_local",
            side_effect=lambda **kwargs: usage_calls.append(dict(kwargs)) or {"local_usage": kwargs["col_pm"]},
        ):
            pbp_out = smart_sim_module._simulate_pbp_game_boxscore_local(mode="pbp")
            event_out = smart_sim_module._simulate_event_level_boxscore_local(mode="event")

        self.assertEqual(pbp_out["mode"], "pbp")
        self.assertEqual(event_out["mode"], "event")
        self.assertEqual(entrypoint_calls, [("pbp", {"local_usage": "_prior_fga_pm"}), ("event", {"local_usage": "_prior_tov_pm"})])
        self.assertEqual(
            usage_calls,
            [
                {"players": "players", "col_pm": "_prior_fga_pm", "lineup_idx": [1, 2, 3]},
                {"players": "players", "col_pm": "_prior_tov_pm", "lineup_idx": [4, 5]},
            ],
        )
        self.assertIs(fake_events_module._player_usage_weights, _original_usage)

    def test_export_props_predictions_local_uses_local_branch_without_smart_sim(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            (source_root / "src").mkdir(parents=True, exist_ok=True)
            out_path = root / "props_predictions_2026-05-22.csv"
            fake_frame = self._BranchFakeFrame([
                {"player_id": 1, "pred_pts": 20.0}
            ])
            fake_pandas = self._FakePandasModule(fake_frame)
            feature_calls: list[str] = []
            predictor_calls: list[object] = []

            def _fake_import(name: str):
                if name == "nba_betting.cli":
                    raise AssertionError("source callback should not be used when SmartSim is disabled")
                raise AssertionError(f"unexpected import: {name}")

            with patch.dict(sys.modules, {"pandas": fake_pandas}), patch.object(
                predictions_module.importlib,
                "import_module",
                side_effect=_fake_import,
            ), patch.object(
                predictions_module.basketball_props_features,
                "build_features_for_date_local",
                side_effect=lambda **kwargs: feature_calls.append(kwargs["date"]) or fake_frame,
            ), patch.object(
                predictions_module.basketball_props_onnx,
                "predict_props_pure_onnx_local",
                side_effect=lambda **kwargs: predictor_calls.append(kwargs["features_df"]) or fake_frame,
            ), patch.object(
                predictions_module,
                "finalize_props_predictions_local",
                return_value=(1, out_path),
            ) as finalize_mock:
                rows, written_path = export_props_predictions_local(
                    source_root=source_root,
                    date_str="2026-05-22",
                    out_path=out_path,
                    calib_window=7,
                    calibrate_player=True,
                    player_calib_window=30,
                    player_min_pairs=6,
                    player_shrink_k=8,
                    use_smart_sim=False,
                    smart_sim_n_sims=150,
                    smart_sim_pbp=True,
                    smart_sim_workers=1,
                )

            self.assertEqual(rows, 1)
            self.assertEqual(written_path, out_path)
            self.assertEqual(feature_calls, ["2026-05-22"])
            self.assertEqual(len(predictor_calls), 1)
            self.assertEqual(finalize_mock.call_count, 1)

    def test_smart_sim_helper_does_not_import_source_cli(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            out_path = processed_root / "props_predictions_2026-05-22.csv"
            out_path.write_text("player_id,team,player_name\n1,ATL,Player A\n", encoding="utf-8")
            (processed_root / "predictions_2026-05-22.csv").write_text("home_team,visitor_team,total,home_spread,totals,spread_margin\nATL,CHI,160,-3,160,6\n", encoding="utf-8")
            (processed_root / "game_odds_2026-05-22.csv").write_text("home_team,visitor_team,total,home_spread\nATL,CHI,160,-3\n", encoding="utf-8")
            fake_frame = self._BranchFakeFrame([{"player_id": 1, "team": "ATL", "player_name": "Player A"}])
            fake_pandas = self._FakePandasModule(fake_frame)
            smart_sim_calls: list[dict[str, object]] = []

            fake_teams = types.SimpleNamespace(
                to_tricode=lambda value: str(value or "").strip().upper()[:3],
                normalize_team=lambda value: str(value or "").strip().upper(),
            )
            fake_schedule = types.SimpleNamespace(compute_rest_for_matchups=lambda m, h: None)
            fake_league = types.SimpleNamespace(LEAGUE=types.SimpleNamespace(baseline_pace=98.0, baseline_def_rating=112.0, baseline_off_rating=112.0))
            fake_player_names = types.SimpleNamespace(normalize_player_name_key=lambda value, case="upper": str(value or "").strip().upper())

            def _fake_import(name: str):
                if name == "nba_betting.cli":
                    raise AssertionError("smart sim helper should not import source cli")
                if name == "nba_betting.teams":
                    return fake_teams
                if name == "nba_betting.schedule":
                    return fake_schedule
                if name == "nba_betting.league":
                    return fake_league
                if name == "nba_betting.player_names":
                    return fake_player_names
                if name == "nba_betting.scrapers":
                    raise AssertionError("scrapers should not be needed for this focused test")
                raise AssertionError(f"unexpected import: {name}")

            with patch.object(
                predictions_module,
                "_export_props_predictions_without_smart_sim_local",
                return_value=(1, out_path),
            ), patch.dict(sys.modules, {"pandas": fake_pandas}), patch.object(
                smart_sim_module.importlib,
                "import_module",
                side_effect=_fake_import,
            ), patch.object(
                smart_sim_module,
                "_smart_sim_run_date_local",
                side_effect=lambda **kwargs: smart_sim_calls.append(dict(kwargs)) or {"wrote": 1, "failures": 0},
            ), patch.object(
                smart_sim_module,
                "_load_sim_df",
                return_value=None,
            ), patch.object(
                smart_sim_module,
                "_merge_smart_sim_into_preds",
                side_effect=lambda preds, sim_df: preds,
            ):
                rows, written_path = smart_sim_module.export_props_predictions_with_smart_sim_local(
                    source_root=source_root,
                    date_str="2026-05-22",
                    out_path=out_path,
                    smart_sim_n_sims=150,
                    smart_sim_pbp=True,
                    smart_sim_workers=1,
                )

            self.assertEqual(rows, 1)
            self.assertEqual(written_path, out_path)
            self.assertEqual(len(smart_sim_calls), 1)
            self.assertEqual(smart_sim_calls[0]["date_str"], "2026-05-22")

    def test_smart_sim_worker_uses_local_small_helpers(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            processed_root = root / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            out_path = processed_root / "smart_sim_2026-05-22_ATL_CHI.json"
            fake_numpy = SimpleNamespace(isfinite=lambda value: value is not None, mean=lambda values: sum(values) / len(values))
            fake_pandas = SimpleNamespace(to_numeric=lambda value, errors="coerce": value)
            period_line_calls: list[dict[str, object]] = []
            market_line_calls: list[dict[str, object]] = []
            total_cal_calls: list[dict[str, object]] = []
            team_players_calls: list[dict[str, object]] = []
            priors_calls: list[dict[str, object]] = []
            team_adv_calls: list[dict[str, object]] = []
            intervals_band_calls: list[dict[str, object]] = []
            intervals_time_calls: list[dict[str, object]] = []
            player_stat_cal_calls: list[dict[str, object]] = []
            coalesce_calls: list[tuple[object, ...]] = []
            infer_game_id_calls: list[dict[str, object]] = []
            processed_box_calls: list[dict[str, object]] = []
            processed_roster_calls: list[dict[str, object]] = []
            roster_filter_calls: list[dict[str, object]] = []
            espn_box_calls: list[dict[str, object]] = []
            espn_name_map_calls: list[dict[str, object]] = []
            pregame_minutes_calls: list[dict[str, object]] = []
            prune_pool_calls: list[dict[str, object]] = []
            market_names_calls: list[dict[str, object]] = []
            rotation_history_calls: list[dict[str, object]] = []
            split_rate_calls: list[dict[str, object]] = []
            career_opp_calls: list[dict[str, object]] = []
            pos_ctx_calls: list[dict[str, object]] = []
            pbp_sim_calls: list[dict[str, object]] = []
            event_sim_calls: list[dict[str, object]] = []
            rotation_minutes_calls: list[dict[str, object]] = []
            apply_priors_calls: list[dict[str, object]] = []
            quarter_calls: list[object] = []
            smart_game_calls: list[dict[str, object]] = []
            helper_route_checks: list[tuple[object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object, object]] = []

            fake_smart_sim_module = SimpleNamespace()

            def _fake_simulate_smart_game(**kwargs):
                helper_route_checks.append(
                    (
                        getattr(fake_smart_sim_module, "_period_lines_from_processed")("2026-05-22", "ATL", "CHI"),
                        getattr(fake_smart_sim_module, "_market_lines_from_processed_odds")("2026-05-22", "ATL", "CHI"),
                        getattr(fake_smart_sim_module, "_load_smartsim_total_calibration")(),
                        getattr(fake_smart_sim_module, "_team_players_from_props")(None, "ATL", "CHI"),
                        getattr(fake_smart_sim_module, "_coalesce_team_player_frames")({"a": 1}),
                        getattr(fake_smart_sim_module, "_infer_game_id")("2026-05-22", "ATL", "CHI"),
                        getattr(fake_smart_sim_module, "_team_players_from_processed_boxscores")("2026-05-22", "ATL", "CHI", "ATL", "100"),
                        getattr(fake_smart_sim_module, "_team_players_from_processed_rosters")("2026-05-22", "ATL", "CHI", "ATL"),
                        getattr(fake_smart_sim_module, "_filter_team_players_against_processed_roster")({"team": "ATL"}, "2026-05-22", "ATL", "CHI", "ATL"),
                        getattr(fake_smart_sim_module, "_team_players_from_espn_boxscore")("2026-05-22", "ATL", "CHI", "ATL", "evt"),
                        getattr(fake_smart_sim_module, "_espn_name_to_id_map_for_game")("2026-05-22", "ATL", "CHI", "evt"),
                        getattr(fake_smart_sim_module, "_merge_pregame_expected_minutes_for_team")({"team": "ATL"}, "2026-05-22", "ATL"),
                        getattr(fake_smart_sim_module, "_prune_pregame_rotation_pool")({"team": "ATL"}, "ATL", 8, None, {"A"}),
                        getattr(fake_smart_sim_module, "_market_player_names_for_matchup")(None, "2026-05-22", "ATL", "CHI"),
                        getattr(fake_smart_sim_module, "_rotation_sim_minutes_from_history")({"team": "ATL"}, "2026-05-22", "ATL", "CHI", "ATL", 28),
                        getattr(fake_smart_sim_module, "_player_split_rate_context")("2026-05-22", "ATL", 120),
                        getattr(fake_smart_sim_module, "_player_career_opponent_rate_context")("2026-05-22", 720),
                        getattr(fake_smart_sim_module, "_opponent_position_rate_context")("2026-05-22", 120),
                        getattr(fake_smart_sim_module, "simulate_pbp_game_boxscore")(mode="pbp"),
                        getattr(fake_smart_sim_module, "simulate_event_level_boxscore")(mode="event"),
                        getattr(fake_smart_sim_module, "_rotation_sim_minutes_for_team")({"team": "ATL"}, "2026-05-22", "ATL", "CHI", "ATL", "home", "100"),
                        getattr(fake_smart_sim_module, "_apply_player_priors")({"team": "ATL"}, {"priors": True}, "ATL", "sim_min", "2026-05-22"),
                        getattr(fake_smart_sim_module, "_compute_player_priors_cached")("2026-05-21", 21),
                        getattr(fake_smart_sim_module, "_team_adj_from_advanced_stats")("2026-05-22", "ATL", "CHI"),
                        getattr(fake_smart_sim_module, "_load_intervals_band_calibration")(),
                        getattr(fake_smart_sim_module, "_load_intervals_time_profile")(),
                        getattr(fake_smart_sim_module, "_load_player_stat_calibration")(),
                    )
                )
                smart_game_calls.append(dict(kwargs))
                return {"players": {"home": [], "away": []}}

            fake_smart_sim_module.simulate_smart_game = _fake_simulate_smart_game

            original_state = smart_sim_module._SMARTSIM_WORKER_STATE
            smart_sim_module._SMARTSIM_WORKER_STATE = {
                "date_str": "2026-05-22",
                "n_sims": 150,
                "seed": 7,
                "pbp": True,
                "roster_mode": "pregame",
                "props_df": None,
                "excluded_map": {},
                "game_id_map": {},
                "name_to_id": {},
                "team_name_to_id": {},
            }
            try:
                with ExitStack() as stack:
                    stack.enter_context(patch.dict(sys.modules, {"pandas": fake_pandas, "numpy": fake_numpy}))
                    stack.enter_context(patch.object(smart_sim_module, "_build_local_smart_sim_module", side_effect=lambda **kwargs: fake_smart_sim_module))
                    stack.enter_context(patch.object(smart_sim_module, "_period_lines_from_processed_local", side_effect=lambda **kwargs: period_line_calls.append(dict(kwargs)) or {"period": "ok"}))
                    stack.enter_context(patch.object(smart_sim_module, "_market_lines_from_processed_odds_local", side_effect=lambda **kwargs: market_line_calls.append(dict(kwargs)) or (160.0, -3.0)))
                    stack.enter_context(patch.object(smart_sim_module, "_load_smartsim_total_calibration_local", side_effect=lambda **kwargs: total_cal_calls.append(dict(kwargs)) or {"points_mult": 1.0}))
                    stack.enter_context(patch.object(smart_sim_module, "_team_players_from_props_local", side_effect=lambda **kwargs: team_players_calls.append(dict(kwargs)) or {"team": kwargs["team_tri"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_coalesce_team_player_frames_local", side_effect=lambda *args: coalesce_calls.append(args) or {"coalesced": True}))
                    stack.enter_context(patch.object(smart_sim_module, "_infer_game_id_local", side_effect=lambda **kwargs: infer_game_id_calls.append(dict(kwargs)) or "100"))
                    stack.enter_context(patch.object(smart_sim_module, "_team_players_from_processed_boxscores_local", side_effect=lambda **kwargs: processed_box_calls.append(dict(kwargs)) or {"processed_box": kwargs["team_tri"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_team_players_from_processed_rosters_local", side_effect=lambda **kwargs: processed_roster_calls.append(dict(kwargs)) or {"processed_roster": kwargs["team_tri"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_filter_team_players_against_processed_roster_local", side_effect=lambda **kwargs: roster_filter_calls.append(dict(kwargs)) or {"filtered": kwargs["team_tri"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_team_players_from_espn_boxscore_local", side_effect=lambda **kwargs: espn_box_calls.append(dict(kwargs)) or {"espn_box": kwargs["team_tri"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_espn_name_to_id_map_for_game_local", side_effect=lambda **kwargs: espn_name_map_calls.append(dict(kwargs)) or {("ATL", "A"): "1"}))
                    stack.enter_context(patch.object(smart_sim_module, "_merge_pregame_expected_minutes_for_team_local", side_effect=lambda **kwargs: pregame_minutes_calls.append(dict(kwargs)) or ({"merged": kwargs["team_tri"]}, {"diag": "pem"})))
                    stack.enter_context(patch.object(smart_sim_module, "_prune_pregame_rotation_pool_local", side_effect=lambda **kwargs: prune_pool_calls.append(dict(kwargs)) or ({"pruned": kwargs["team_tri"]}, {"diag": "prune"})))
                    stack.enter_context(patch.object(smart_sim_module, "_market_player_names_for_matchup_local", side_effect=lambda **kwargs: market_names_calls.append(dict(kwargs)) or {"ATL": {"A"}}))
                    stack.enter_context(patch.object(smart_sim_module, "_rotation_sim_minutes_from_history_local", side_effect=lambda **kwargs: rotation_history_calls.append(dict(kwargs)) or ("hist_min", "hist_lineups", "hist_weights", {"diag": "history"})))
                    stack.enter_context(patch.object(smart_sim_module, "_player_split_rate_context_local", side_effect=lambda **kwargs: split_rate_calls.append(dict(kwargs)) or {"split": kwargs["team_tri"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_player_career_opponent_rate_context_local", side_effect=lambda **kwargs: career_opp_calls.append(dict(kwargs)) or {"career_opp": kwargs["date_str"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_opponent_position_rate_context_local", side_effect=lambda **kwargs: pos_ctx_calls.append(dict(kwargs)) or {"pos_ctx": kwargs["date_str"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_simulate_pbp_game_boxscore_local", side_effect=lambda **kwargs: pbp_sim_calls.append(dict(kwargs)) or {"pbp": kwargs.get("mode")}))
                    stack.enter_context(patch.object(smart_sim_module, "_simulate_event_level_boxscore_local", side_effect=lambda **kwargs: event_sim_calls.append(dict(kwargs)) or {"event": kwargs.get("mode")}))
                    stack.enter_context(patch.object(smart_sim_module, "_rotation_sim_minutes_for_team_local", side_effect=lambda **kwargs: rotation_minutes_calls.append(dict(kwargs)) or ("sim_min", "lineups", "weights", {"diag": "rotation"})))
                    stack.enter_context(patch.object(smart_sim_module, "_apply_player_priors_local", side_effect=lambda **kwargs: apply_priors_calls.append(dict(kwargs)) or {"applied_priors": kwargs["team_tri"]}))
                    stack.enter_context(patch.object(smart_sim_module, "_compute_player_priors_cached_local", side_effect=lambda **kwargs: priors_calls.append(dict(kwargs)) or {"priors": "ok"}))
                    stack.enter_context(patch.object(smart_sim_module, "_team_adj_from_advanced_stats_local", side_effect=lambda **kwargs: team_adv_calls.append(dict(kwargs)) or ({"home": "adj"}, {"away": "adj"}, 1.0, {"diag": "ok"})))
                    stack.enter_context(patch.object(smart_sim_module, "_load_intervals_band_calibration_local", side_effect=lambda **kwargs: intervals_band_calls.append(dict(kwargs)) or {"bands": "ok"}))
                    stack.enter_context(patch.object(smart_sim_module, "_load_intervals_time_profile_local", side_effect=lambda **kwargs: intervals_time_calls.append(dict(kwargs)) or {"time": "ok"}))
                    stack.enter_context(patch.object(smart_sim_module, "_load_player_stat_calibration_local", side_effect=lambda **kwargs: player_stat_cal_calls.append(dict(kwargs)) or {"players": "ok"}))
                    stack.enter_context(patch.object(smart_sim_module, "_simulate_quarters_local", side_effect=lambda **kwargs: quarter_calls.append(kwargs["inp"]) or SimpleNamespace(quarters=[{"q": 1}])))
                    result = smart_sim_module._smart_sim_worker_run_local(
                        {
                            "date_str": "2026-05-22",
                            "home_tri": "ATL",
                            "away_tri": "CHI",
                            "out_path": str(out_path),
                            "home_pace": 98.0,
                            "away_pace": 99.0,
                            "matchup_pace": 98.5,
                            "home_def_rtg": 111.0,
                            "away_def_rtg": 113.0,
                            "home_off_rtg": 114.0,
                            "away_off_rtg": 110.0,
                            "home_outs": 0,
                            "away_outs": 1,
                        }
                    )
            finally:
                smart_sim_module._SMARTSIM_WORKER_STATE = original_state

            self.assertEqual(result["status"], "wrote")
            self.assertEqual(len(period_line_calls), 2)
            self.assertEqual(period_line_calls[0]["processed_root"], processed_root)
            self.assertEqual(len(quarter_calls), 1)
            self.assertIsNone(quarter_calls[0].market_total)
            self.assertEqual(quarter_calls[0].home.team, "ATL")
            self.assertEqual(len(smart_game_calls), 1)
            self.assertEqual(helper_route_checks, [({"period": "ok"}, (160.0, -3.0), {"points_mult": 1.0}, {"team": "ATL"}, {"coalesced": True}, "100", {"processed_box": "ATL"}, {"processed_roster": "ATL"}, {"filtered": "ATL"}, {"espn_box": "ATL"}, {("ATL", "A"): "1"}, ({"merged": "ATL"}, {"diag": "pem"}), ({"pruned": "ATL"}, {"diag": "prune"}), {"ATL": {"A"}}, ("hist_min", "hist_lineups", "hist_weights", {"diag": "history"}), {"split": "ATL"}, {"career_opp": "2026-05-22"}, {"pos_ctx": "2026-05-22"}, {"pbp": "pbp"}, {"event": "event"}, ("sim_min", "lineups", "weights", {"diag": "rotation"}), {"applied_priors": "ATL"}, {"priors": "ok"}, ({"home": "adj"}, {"away": "adj"}, 1.0, {"diag": "ok"}), {"bands": "ok"}, {"time": "ok"}, {"players": "ok"})])
            self.assertEqual(len(period_line_calls), 2)
            self.assertEqual(len(market_line_calls), 1)
            self.assertEqual(len(total_cal_calls), 1)
            self.assertEqual(len(team_players_calls), 1)
            self.assertEqual(len(coalesce_calls), 1)
            self.assertEqual(len(infer_game_id_calls), 1)
            self.assertEqual(len(processed_box_calls), 1)
            self.assertEqual(len(processed_roster_calls), 1)
            self.assertEqual(len(roster_filter_calls), 1)
            self.assertEqual(len(espn_box_calls), 1)
            self.assertEqual(len(espn_name_map_calls), 1)
            self.assertEqual(len(pregame_minutes_calls), 1)
            self.assertEqual(len(prune_pool_calls), 1)
            self.assertEqual(len(market_names_calls), 1)
            self.assertEqual(len(rotation_history_calls), 1)
            self.assertEqual(len(split_rate_calls), 1)
            self.assertEqual(len(career_opp_calls), 1)
            self.assertEqual(len(pos_ctx_calls), 1)
            self.assertEqual(len(pbp_sim_calls), 1)
            self.assertEqual(len(event_sim_calls), 1)
            self.assertEqual(len(rotation_minutes_calls), 1)
            self.assertEqual(len(apply_priors_calls), 1)
            self.assertEqual(len(priors_calls), 1)
            self.assertEqual(len(team_adv_calls), 1)
            self.assertEqual(len(intervals_band_calls), 1)
            self.assertEqual(len(intervals_time_calls), 1)
            self.assertEqual(len(player_stat_cal_calls), 1)
            self.assertEqual(smart_game_calls[0]["cfg"].roster_mode, "pregame")
            self.assertIsInstance(smart_game_calls[0]["cfg"].event_cfg, smart_sim_module.EventSimConfigLocal)

    def test_finalize_props_predictions_local_uses_local_calibration_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            processed_root = source_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            out_path = processed_root / "props_predictions_2026-05-22.csv"
            out_path.write_text("player_id\n1\n", encoding="utf-8")
            fake_preds = self._FakeFrame([{"player_id": 1}])
            fake_pandas = self._FakePandasModule(fake_preds)
            local_calls: list[tuple[str, dict[str, object]]] = []

            with patch.dict(sys.modules, {"pandas": fake_pandas}), patch.object(
                predictions_module.basketball_props_calibration,
                "compute_biases",
                side_effect=lambda **kwargs: local_calls.append(("compute_biases", dict(kwargs))) or {"pts": 1.5},
            ), patch.object(
                predictions_module.basketball_props_calibration,
                "apply_biases",
                side_effect=lambda **kwargs: local_calls.append(("apply_biases", dict(kwargs))) or fake_preds.copy(),
            ), patch.object(
                predictions_module.basketball_props_calibration,
                "save_calibration",
                side_effect=lambda **kwargs: local_calls.append(("save_calibration", dict(kwargs))) or (processed_root / "props_calibration_2026-05-22.json"),
            ), patch.object(
                predictions_module.importlib,
                "import_module",
                side_effect=AssertionError("source calibration import should not be used"),
            ):
                rows, written_path = predictions_module.finalize_props_predictions_local(
                    source_root=source_root,
                    date_str="2026-05-22",
                    out_path=out_path,
                    calib_window=7,
                    calibrate=True,
                    calibrate_player=False,
                    player_calib_window=30,
                    player_min_pairs=1,
                    player_shrink_k=8,
                )

            self.assertEqual(rows, 1)
            self.assertEqual(written_path, out_path)
            self.assertEqual([name for name, _ in local_calls], ["compute_biases", "apply_biases", "save_calibration"])
            self.assertEqual(local_calls[0][1]["processed_root"], processed_root)

    def test_finalize_props_predictions_local_uses_local_player_calibration_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            processed_root = source_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            out_path = processed_root / "props_predictions_2026-05-22.csv"
            out_path.write_text("player_id\n1\n", encoding="utf-8")
            fake_preds = self._FakeFrame([{"player_id": 1}])
            fake_pandas = self._FakePandasModule(fake_preds)
            player_biases = self._FakeFrame([{"player_id": 1, "stat": "pts", "adj": 2.0}])
            local_calls: list[tuple[str, dict[str, object]]] = []

            with patch.dict(sys.modules, {"pandas": fake_pandas}), patch.object(
                predictions_module.basketball_props_calibration,
                "compute_player_biases",
                side_effect=lambda **kwargs: local_calls.append(("compute_player_biases", dict(kwargs))) or player_biases,
            ), patch.object(
                predictions_module.basketball_props_calibration,
                "apply_player_biases",
                side_effect=lambda **kwargs: local_calls.append(("apply_player_biases", dict(kwargs))) or fake_preds.copy(),
            ), patch.object(
                predictions_module.basketball_props_calibration,
                "save_player_calibration",
                side_effect=lambda **kwargs: local_calls.append(("save_player_calibration", dict(kwargs))) or (processed_root / "props_player_calibration_2026-05-22.csv"),
            ), patch.object(
                predictions_module.importlib,
                "import_module",
                side_effect=AssertionError("source calibration import should not be used"),
            ):
                rows, written_path = predictions_module.finalize_props_predictions_local(
                    source_root=source_root,
                    date_str="2026-05-22",
                    out_path=out_path,
                    calib_window=7,
                    calibrate=False,
                    calibrate_player=True,
                    player_calib_window=30,
                    player_min_pairs=1,
                    player_shrink_k=1,
                )

            self.assertEqual(rows, 1)
            self.assertEqual(written_path, out_path)
            self.assertEqual(
                [name for name, _ in local_calls],
                ["compute_player_biases", "apply_player_biases", "save_player_calibration"],
            )
            self.assertEqual(local_calls[0][1]["processed_root"], processed_root)
            used_meta = processed_root / "props_player_calibration_used_2026-05-22.json"
            self.assertTrue(used_meta.exists())

    def test_league_quarter_lengths_differ_between_nba_and_wnba(self) -> None:
        nba = smart_sim_module._NBA_LEAGUE_LOCAL
        wnba = smart_sim_module._WNBA_LEAGUE_LOCAL

        self.assertEqual(float(nba.quarter_minutes), 12.0)
        self.assertEqual(float(wnba.quarter_minutes), 10.0)
        self.assertGreater(float(nba.regulation_team_minutes), float(wnba.regulation_team_minutes))
        self.assertEqual(smart_sim_module._quarter_splits_local(league=nba), [0.245, 0.245, 0.255, 0.255])
        self.assertEqual(smart_sim_module._quarter_splits_local(league=wnba), [0.2425, 0.2475, 0.2525, 0.2575])
        self.assertLess(
            float(smart_sim_module._quarter_duration_scale_local(league=wnba)),
            float(smart_sim_module._quarter_duration_scale_local(league=nba)),
        )


if __name__ == "__main__":
    unittest.main()