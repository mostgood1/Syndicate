from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


class MlbRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_mlb_oddsapi.py"
        spec = importlib.util.spec_from_file_location("test_refresh_mlb_oddsapi", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_calls_source_modules_directly(self) -> None:
        module = self._load_module()

        class _FakeOddsModule:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def fetch_and_write_live_odds_for_date(self, date_str: str, *, out_dir, overwrite: bool, regions: str):
                self.calls.append(
                    {
                        "date": date_str,
                        "out_dir": str(out_dir),
                        "overwrite": overwrite,
                        "regions": regions,
                    }
                )
                return {}

        odds_module = _FakeOddsModule()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            (source_root / "data").mkdir(parents=True)
            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(Path(tmp_dir) / "bundle"),
                "--regions",
                "us,eu",
            ]
            with patch.object(module, "_load_local_fetcher", return_value=odds_module), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(odds_module.calls), 1)
        self.assertEqual(odds_module.calls[0]["date"], "2026-05-22")
        self.assertEqual(odds_module.calls[0]["regions"], "us,eu")

    def test_cards_page_context_defaults_to_auto_expand(self) -> None:
        from syndicate.features.mlb.cards import build_cards_page_context

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "daily_artifact_2026-06-03.json"
            live_lens_path = temp_root / "live_lens_report_2026-06-03.json"
            summary_path.write_text(json.dumps({"date": "2026-06-03", "outputs": []}), encoding="utf-8")
            live_lens_path.write_text(json.dumps({"games": []}), encoding="utf-8")

            with patch("syndicate.features.mlb.cards.available_daily_summary_dates", return_value=["2026-06-03"]), patch(
                "syndicate.features.mlb.cards.daily_artifact_path",
                return_value=summary_path,
            ), patch(
                "syndicate.features.mlb.cards.live_lens_report_path",
                return_value=live_lens_path,
            ), patch(
                "syndicate.features.mlb.cards._cards_recommendation_payload_by_game",
                return_value={},
            ), patch(
                "syndicate.features.mlb.cards._daily_sim_by_game",
                return_value={},
            ), patch(
                "syndicate.features.mlb.cards._daily_actual_by_game",
                return_value={},
            ), patch(
                "syndicate.features.mlb.cards._rfi_targets_signal_index",
                return_value={},
            ), patch(
                "syndicate.features.mlb.cards._hr_targets_shelf",
                return_value=None,
            ), patch(
                "syndicate.features.mlb.cards.build_module_links",
                return_value=[],
            ):
                context = build_cards_page_context("2026-06-03")

        self.assertTrue(context["auto_expand_cards"])

    def test_same_doc_considers_retrieved_at_freshness(self) -> None:
        module = self._load_module()

        existing = {
            "date": "2026-07-01",
            "mode": "live",
            "retrieved_at": "2026-07-01T07:42:15Z",
            "games": [{"event_id": "1", "markets": {"h2h": {"home": 1.0, "away": 2.0}}}],
        }
        candidate = {
            "date": "2026-07-01",
            "mode": "live",
            "retrieved_at": "2026-07-01T08:15:00Z",
            "games": [{"event_id": "1", "markets": {"h2h": {"home": 1.0, "away": 2.0}}}],
        }

        self.assertFalse(module._same_doc(existing, candidate))

    def test_main_warns_when_live_lens_artifacts_are_missing(self) -> None:
        module = self._load_module()

        class _FakeOddsModule:
            pass

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            artifact_root = Path(tmp_dir) / "bundle"
            source_root.mkdir(parents=True)
            artifact_root.mkdir(parents=True)
            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--regions",
                "us",
            ]
            stdout = io.StringIO()
            with (
                patch.object(module, "_load_local_fetcher", return_value=_FakeOddsModule()),
                patch.object(module, "_refresh_source_artifacts", return_value={"market_refresh": {"ok": True}, "live_lens": {"ok": True}}),
                patch.object(module, "_materialize_artifact_bundle", return_value={"files": [str(artifact_root / "dummy.json")]}),
                patch.object(module, "_required_live_lens_relative_paths", return_value=[Path("data/live_lens/required.json")]),
                patch("sys.argv", argv),
                redirect_stdout(stdout),
            ):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertIn("live-lens artifacts were not fully present after refresh", stdout.getvalue())

    def test_main_treats_quota_failure_as_warning(self) -> None:
        module = self._load_module()

        class _FakeOddsModule:
            pass

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            artifact_root = Path(tmp_dir) / "bundle"
            source_root.mkdir(parents=True)
            artifact_root.mkdir(parents=True)
            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--regions",
                "us",
            ]
            stdout = io.StringIO()
            with (
                patch.object(module, "_load_local_fetcher", return_value=_FakeOddsModule()),
                patch.object(module, "_refresh_source_artifacts", side_effect=RuntimeError("OddsAPI live odds request failed: Usage quota has been reached. See usage plans at https://the-odds-api.com")),
                patch("sys.argv", argv),
                redirect_stdout(stdout),
            ):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertIn("Usage quota has been reached", stdout.getvalue())

    def test_materialize_artifact_bundle_allows_same_source_and_artifact_root(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle_root = Path(tmp_dir)
            live_lens_file = bundle_root / "data" / "live_lens" / "live_lens_2026_07_01.jsonl"
            live_lens_file.parent.mkdir(parents=True, exist_ok=True)
            live_lens_file.write_text("{}\n", encoding="utf-8")

            copied = module._materialize_artifact_bundle(
                source_root=bundle_root,
                artifact_root=bundle_root,
                date_str="2026-07-01",
            )

            self.assertIn(str(live_lens_file), copied.get("files", []))
            self.assertEqual(live_lens_file.read_text(encoding="utf-8"), "{}\n")

    def test_reconcile_module_resolves_daily_sims_directory(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "reconcile_daily_sim_artifacts.py"
        spec = importlib.util.spec_from_file_location("test_mlb_reconcile_daily_sim_artifacts", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            spec.loader.exec_module(module)

            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                expected = root / "data" / "daily" / "sims" / "2026-06-21"
                expected.mkdir(parents=True, exist_ok=True)

                module._ROOT = root

                resolved = module._resolve_sim_dir("", "2026-06-21")

            self.assertEqual(resolved, expected.resolve())
        finally:
            sys.modules.pop(spec.name, None)

    def test_reconcile_module_missing_sim_dir_writes_empty_report(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "reconcile_daily_sim_artifacts.py"
        spec = importlib.util.spec_from_file_location("test_mlb_reconcile_daily_sim_artifacts_missing_dir", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            spec.loader.exec_module(module)

            with tempfile.TemporaryDirectory() as tmp_dir:
                out_path = Path(tmp_dir) / "sim_vs_actual.json"
                argv = [
                    "reconcile_daily_sim_artifacts.py",
                    "--date",
                    "2026-06-21",
                    "--season",
                    "2026",
                    "--sim-dir",
                    str(Path(tmp_dir) / "missing" / "data" / "daily" / "sims" / "2026-06-21"),
                    "--out",
                    str(out_path),
                ]

                with patch.object(sys, "argv", argv):
                    rc = module.main()

                payload = json.loads(out_path.read_text(encoding="utf-8"))

            self.assertEqual(rc, 0)
            self.assertEqual(payload["aggregate"]["full"]["games"], 0)
            self.assertIn("sim_dir_missing", payload["meta"]["warnings"][0])
        finally:
            sys.modules.pop(spec.name, None)

    def test_live_lens_report_refresh_default_is_thirty_seconds(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)

            self.assertEqual(module._live_lens_report_refresh_interval_seconds(), 60)
        finally:
            sys.modules.pop(spec.name, None)

    def test_live_lens_data_dir_prefers_render_disk_when_only_syndicate_root_is_set(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_data_dir", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        with tempfile.TemporaryDirectory() as tmp_dir:
            syndicate_root = Path(tmp_dir)
            expected_root = syndicate_root / "mlb_source" / "source_artifacts" / "data"
            expected_root.mkdir(parents=True, exist_ok=True)

            try:
                with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(syndicate_root)}, clear=True):
                    spec.loader.exec_module(module)

                self.assertEqual(module._DATA_DIR, expected_root.resolve())
                self.assertEqual(module._LIVE_LENS_DIR, (expected_root / "live_lens").resolve())
            finally:
                sys.modules.pop(spec.name, None)

    def test_live_lens_reports_payload_overrides_stale_report_metadata(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_reports", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                module._DATA_DIR = runtime_root
                module._LIVE_LENS_DIR = runtime_root / "live_lens"
                expected_data_root = module._relative_path_str(runtime_root)
                expected_live_lens_dir = module._relative_path_str(runtime_root / "live_lens")
                module._local_timestamp_text = lambda: "2026-06-01T21:00:00-05:00"
                module._load_json_file = lambda path: {
                    "generatedAt": "1999-01-01T00:00:00-05:00",
                    "dataRoot": "C:/stale/data",
                    "liveLensDir": "C:/stale/data/live_lens",
                    "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                }
                module._live_prop_registry_summary = lambda d: {}
                module._load_live_prop_first_observation_archive = lambda d: []
                module._live_lens_optimization_regime = lambda d: "baseline"
                module._live_lens_log_path = lambda d: runtime_root / f"live_lens_{d}.jsonl"
                module._live_prop_observation_log_path = lambda d: runtime_root / "prop_registry" / f"live_prop_observations_{d}.jsonl"
                module._live_prop_registry_path = lambda d: runtime_root / "prop_registry" / f"live_prop_registry_{d}.json"
                module._live_prop_registry_log_path = lambda d: runtime_root / "prop_registry" / f"live_prop_registry_{d}.jsonl"
                module._live_lens_daily_recap_path = lambda d: runtime_root / "recaps" / f"live_lens_daily_recap_{d}.json"

                payload = module._live_lens_reports_payload("2026-06-01")

            self.assertEqual(payload["latestReport"]["generatedAt"], "2026-06-01T21:00:00-05:00")
            self.assertEqual(payload["latestReport"]["dataRoot"], expected_data_root)
            self.assertEqual(payload["latestReport"]["liveLensDir"], expected_live_lens_dir)
        finally:
            sys.modules.pop(spec.name, None)

    def test_api_live_lens_overrides_stale_report_metadata_on_read_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_api_live_lens", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_root.mkdir(parents=True, exist_ok=True)
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_01.json"
                report_path.write_text("{}\n", encoding="utf-8")
                module._DATA_DIR = runtime_root
                module._LIVE_LENS_DIR = runtime_live_lens_dir
                module._is_live_lens_loop_enabled = lambda: False
                module._local_timestamp_text = lambda: "2026-06-01T21:00:00-05:00"
                module._live_lens_report_path = lambda d: report_path
                module._load_json_file = lambda path: {
                    "generatedAt": "1999-01-01T00:00:00-05:00",
                    "dataRoot": "C:/stale/data",
                    "liveLensDir": "C:/stale/data/live_lens",
                    "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                }

                with module.app.test_client() as client:
                    response = client.get("/api/live-lens?date=2026-06-01")

                self.assertEqual(response.status_code, 200)
                payload = response.get_json()

            self.assertIsInstance(payload, dict)
            self.assertEqual(payload["generatedAt"], "2026-06-01T21:00:00-05:00")
            self.assertEqual(payload["dataRoot"], module._relative_path_str(runtime_root))
            self.assertEqual(payload["liveLensDir"], module._relative_path_str(runtime_live_lens_dir))
        finally:
            sys.modules.pop(spec.name, None)

    def test_api_live_lens_does_not_auto_persist_for_current_date(self) -> None:
        from syndicate.blueprints import mlb as mlb_blueprint
        from syndicate.app import app as syndicate_app

        captured: dict[str, object] = {}

        def fake_read_latest_live_lens_api_payload(selected_date: str, *, season: int | None = None):
            captured["selected_date"] = selected_date
            captured["season"] = season
            return {"date": selected_date, "games": [], "counts": {}, "generatedAt": "2026-06-03T20:15:00-05:00"}

        with patch.object(mlb_blueprint, "read_latest_live_lens_api_payload", side_effect=fake_read_latest_live_lens_api_payload) as mocked_payload:
            with syndicate_app.test_client() as client:
                response = client.get("/mlb/api/live-lens?date=2026-06-03")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["selected_date"], "2026-06-03")
        self.assertIsNone(captured["season"])
        mocked_payload.assert_called_once()

    def test_live_lens_api_rebuilds_empty_today_snapshot(self) -> None:
        from syndicate.features.mlb import live_lens as live_lens_module

        today = datetime.now().astimezone().date().isoformat()
        rebuilt_snapshot = {
            "games": [{"gamePk": 123, "status": {"abstract": "Live", "detailed": "In Progress"}, "props": [1]}],
            "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 1, "archivedLiveProps": 0},
            "source_title": "MLB live-lens report artifact",
            "generatedAt": "2026-06-27T15:10:00-05:00",
        }

        with patch.object(live_lens_module, "read_latest_live_lens_snapshot", return_value={}) as mocked_snapshot:
            with patch.object(live_lens_module, "build_live_lens_snapshot_internal", return_value=rebuilt_snapshot) as mocked_build:
                payload = live_lens_module.read_latest_live_lens_api_payload(today)

        self.assertEqual(payload["counts"]["games"], 1)
        self.assertEqual(payload["games"][0]["gamePk"], 123)
        mocked_snapshot.assert_called_once()
        mocked_build.assert_called_once_with(today, season=None, persist=False)

    def test_build_live_lens_snapshot_internal_reads_report_without_feed_refresh(self) -> None:
        from syndicate.features.mlb import live_lens as live_lens_module

        report = {
            "games": [
                {
                    "gamePk": 822727,
                    "status": {"abstract": "Preview", "detailed": "Scheduled"},
                    "matchup": {"score": {"away": 0, "home": 0}},
                    "detail": "Scheduled",
                }
            ]
        }

        live_feed = {
            "gameData": {"status": {"abstractGameState": "Final", "detailedState": "Final"}},
            "liveData": {"linescore": {"teams": {"away": {"runs": 5}, "home": {"runs": 3}}}},
        }

        fresh_report = {
            "games": [
                {
                    "gamePk": 822727,
                    "status": {"abstract": "Final", "detailed": "Final"},
                    "matchup": {"score": {"away": 5, "home": 3}},
                    "detail": "Final",
                }
            ],
            "counts": {"games": 1, "live": 0, "final": 1, "pregame": 0, "props": 0, "archivedLiveProps": 0},
            "source_title": "MLB Game Cards",
        }

        with patch.object(live_lens_module, "load_json_file", return_value=report), patch.object(
            live_lens_module,
            "build_cards_page_context",
            return_value={"games": []},
        ), patch.object(live_lens_module, "_persist_live_lens_report", return_value=fresh_report), patch.object(
            live_lens_module,
            "live_lens_report_path",
            return_value=Path("report.json"),
        ):
            context = live_lens_module.build_live_lens_snapshot_internal("2026-06-03", persist=False)

        self.assertEqual(context["counts"]["pregame"], 1)
        self.assertEqual(context["games"][0]["status"]["abstract"], "Preview")
        self.assertEqual(context["games"][0]["detail"], "2026-06-03")
        self.assertEqual(context["games"][0]["matchup"]["score"], {"away": 0, "home": 0})

    def test_cards_backed_live_lens_report_calls_real_build_cards_page_context_signature(self) -> None:
        # #128 regression: _cards_backed_live_lens_report/_merge_cards_context_into_report
        # called build_cards_page_context(selected_date, allow_request_daily_ladders_refresh=True)
        # for a long time, but the real function only ever accepted
        # `selected_date` -- every call silently raised TypeError, caught by
        # the bare except Exception, so this fallback path never actually
        # worked in production. Every other test in this file mocks
        # build_cards_page_context with a signature that accepted the bogus
        # kwarg, which is exactly how this stayed hidden -- this test uses
        # inspect on the REAL function instead of a hand-written mock.
        import inspect

        from syndicate.features.mlb import cards as cards_module
        from syndicate.features.mlb import live_lens as live_lens_module

        signature = inspect.signature(cards_module.build_cards_page_context)
        self.assertNotIn(
            "allow_request_daily_ladders_refresh",
            signature.parameters,
            "build_cards_page_context's real signature changed -- if it now accepts this "
            "kwarg, this regression test (and its comment) are stale and should be updated.",
        )

        called: dict[str, object] = {}

        def real_shaped_build_cards_page_context(selected_date: str) -> dict[str, object]:
            called["selected_date"] = selected_date
            return {"games": [{"gamePk": 824755, "status": {"abstract": "Live", "detailed": "In Progress"}, "markets": {}}], "source_title": "MLB Game Cards"}

        with patch.object(live_lens_module, "build_cards_page_context", side_effect=real_shaped_build_cards_page_context):
            report = live_lens_module._cards_backed_live_lens_report("2026-06-03")

        self.assertEqual(called.get("selected_date"), "2026-06-03")
        self.assertIsNotNone(report)
        self.assertEqual(len(report.get("games") or []), 1)

    def test_live_lens_page_context_opts_into_today_ladder_refresh(self) -> None:
        from syndicate.features.mlb import live_lens as live_lens_module

        captured: dict[str, object] = {}

        def fake_build_cards_page_context(selected_date: str):
            captured["selected_date"] = selected_date
            return {"games": [], "source_title": "MLB Game Cards", "using_sample_data": False}

        empty_report = {"games": [], "counts": {"games": 0, "live": 0, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0}, "source_title": "MLB Game Cards"}

        with patch.object(live_lens_module, "build_cards_page_context", side_effect=fake_build_cards_page_context), patch.object(
            live_lens_module,
            "_persist_live_lens_report",
            return_value=empty_report,
        ), patch.object(live_lens_module, "live_lens_report_path", return_value=Path("report.json")):
            context = live_lens_module.build_live_lens_snapshot_internal("2026-06-03", persist=False)

        self.assertEqual(captured["selected_date"], "2026-06-03")
        self.assertEqual(context["counts"]["games"], 0)

    def test_live_lens_page_context_prefers_persisted_live_report_over_cards_merge(self) -> None:
        from syndicate.features.mlb import live_lens as live_lens_module

        fresh_report = {
            "games": [
                {
                    "gamePk": 824755,
                    "status": {"abstract": "Live", "detailed": "In Progress"},
                    "gameLens": [{"key": "live", "label": "Top 9"}],
                    "props": [{"id": "live-prop"}],
                    "liveProps": [{"id": "live-prop"}],
                    "trackedProps": [{"id": "live-prop"}],
                }
            ],
            "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 1, "archivedLiveProps": 0},
            "source_title": "MLB Live Lens",
            "generatedAt": "2026-06-03T12:00:00-05:00",
        }

        def fake_persist_live_lens_report(selected_date: str):
            self.assertEqual(selected_date, "2026-06-03")
            return fresh_report

        def fake_build_cards_page_context(selected_date: str):
            self.assertEqual(selected_date, "2026-06-03")
            return {
                "games": [
                    {
                        "gamePk": 824755,
                        "status": {"abstract": "Preview", "detailed": "Scheduled"},
                        "gameLens": [{"key": "first1", "label": "F1"}],
                        "props": [],
                    }
                ],
                "source_title": "MLB Game Cards",
                "using_sample_data": False,
            }

        with patch.object(live_lens_module, "build_cards_page_context", side_effect=fake_build_cards_page_context), patch.object(
            live_lens_module,
            "_persist_live_lens_report",
            side_effect=fake_persist_live_lens_report,
        ), patch.object(live_lens_module, "_refresh_current_date_live_statuses", return_value=None), patch.object(
            live_lens_module,
            "live_lens_report_path",
            return_value=Path("report.json"),
        ):
            context = live_lens_module.build_live_lens_snapshot_internal("2026-06-03", persist=True)

        self.assertEqual(context["games"][0]["status"]["abstract"], "Live")
        self.assertEqual(context["games"][0]["gameLens"][0]["key"], "live")
        self.assertEqual(context["games"][0]["props"][0]["id"], "live-prop")

    def test_live_lens_payload_refreshes_card_before_game_lens(self) -> None:
        from vendor.mlb_bettingv2.tools.web import flask_frontend as mlb_frontend

        captured: dict[str, object] = {}

        def fake_supplement(card: dict[str, object], d: str, *, feed=None) -> None:
            card["status"] = {"abstract": "Live", "detailed": "In Progress"}

        def fake_build_game_lens(card, snapshot, sim_context, market_row, *, date_str=None):
            captured["status"] = dict(card.get("status") or {})
            captured["date_str"] = date_str
            return []

        with patch.object(mlb_frontend, "_load_cards_artifacts", return_value={}), patch.object(
            mlb_frontend,
            "_load_cards_archive_context",
            return_value={},
        ), patch.object(mlb_frontend, "_should_load_cards_archive_context", return_value=False), patch.object(
            mlb_frontend,
            "_schedule_games_for_date",
            return_value=[{"gamePk": 824755}],
        ), patch.object(mlb_frontend, "_load_live_lens_cards", return_value=[{"gamePk": 824755, "status": {"abstract": "Preview", "detailed": "Scheduled"}, "markets": {}, "away": {}, "home": {}}]), patch.object(
            mlb_frontend,
            "_load_game_line_market_index",
            return_value={},
        ), patch.object(mlb_frontend, "_load_live_lens_snapshot", return_value={"status": {"abstractGameState": "Preview", "detailedState": "Scheduled"}, "teams": {"away": {"totals": {}}, "home": {"totals": {}}}}), patch.object(
            mlb_frontend,
            "_load_sim_context_for_game",
            return_value={"found": True},
        ), patch.object(mlb_frontend, "_current_live_prop_rows", return_value=[]), patch.object(
            mlb_frontend,
            "_normalize_live_lens_live_prop_row",
            side_effect=lambda row, snapshot, card: row,
        ), patch.object(mlb_frontend, "_supplement_card_status_from_live_feed", side_effect=fake_supplement), patch.object(
            mlb_frontend,
            "_build_game_lens",
            side_effect=fake_build_game_lens,
        ):
            payload = mlb_frontend._live_lens_payload("2026-06-03", persist=False)

        self.assertEqual(captured["status"].get("abstract"), "Live")
        self.assertEqual(captured["status"].get("detailed"), "In Progress")
        self.assertEqual(captured["date_str"], "2026-06-03")
        self.assertEqual((payload.get("counts") or {}).get("games"), 1)

    def test_api_live_lens_persist_bypasses_cache_and_rewrites_report(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_api_live_lens_persist", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_01.json"
                counter = {"value": 0}

                def fake_live_lens_payload(date_str: str, *, persist: bool = False, refresh_markets: bool = False):
                    counter["value"] += 1
                    payload = {
                        "date": date_str,
                        "generatedAt": f"2026-06-01T21:00:0{counter['value']}-05:00",
                        "dataRoot": module._relative_path_str(runtime_root),
                        "liveLensDir": module._relative_path_str(runtime_live_lens_dir),
                        "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                        "performance": {"marketsRefreshed": bool(refresh_markets), "persistMs": 0.0},
                        "games": [],
                    }
                    report_path.write_text(json.dumps(payload), encoding="utf-8")
                    return payload

                module._DATA_DIR = runtime_root
                module._LIVE_LENS_DIR = runtime_live_lens_dir
                module._is_live_lens_loop_enabled = lambda: False
                module._is_historical_date = lambda d: False
                module._live_lens_report_path = lambda d: report_path
                module._payload_cache_get_or_build = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache should be bypassed for persist=on"))
                module._live_lens_payload = fake_live_lens_payload

                with module.app.test_client() as client:
                    first_response = client.get("/api/live-lens?date=2026-06-01&persist=on")
                    second_response = client.get("/api/live-lens?date=2026-06-01&persist=on")

                first_payload = first_response.get_json()
                second_payload = second_response.get_json()
                report_payload = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(first_response.status_code, 200)
            self.assertEqual(second_response.status_code, 200)
            self.assertEqual(counter["value"], 2)
            self.assertEqual(first_payload["generatedAt"], "2026-06-01T21:00:01-05:00")
            self.assertEqual(second_payload["generatedAt"], "2026-06-01T21:00:02-05:00")
            self.assertEqual(report_payload["generatedAt"], "2026-06-01T21:00:02-05:00")
        finally:
            sys.modules.pop(spec.name, None)

    def test_live_lens_payload_normalizes_in_progress_status_as_live(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_live_status", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                spec.loader.exec_module(module)
                module._DATA_DIR = Path(tmp_dir) / "data"
                module._LIVE_LENS_DIR = module._DATA_DIR / "live_lens"

                module._load_cards_artifacts = lambda d: {}
                module._load_cards_archive_context = lambda d: {}
                module._should_load_cards_archive_context = lambda d, artifacts=None: False
                module._schedule_games_for_date = lambda d: []
                module._load_live_lens_cards = lambda d, artifacts=None, archive=None, schedule_games=None: [
                    {
                        "gamePk": 123,
                        "status": {"abstract": "Preview", "detailed": "Pre-Game"},
                        "startTime": "7:10 PM",
                        "away": {"abbr": "AAA", "name": "Away A"},
                        "home": {"abbr": "BBB", "name": "Home B"},
                        "markets": {"totals": {}, "ml": {}, "pitcherProps": [], "hitterProps": []},
                        "predictions": {},
                        "probable": {},
                        "gameLens": [],
                        "liveProps": [],
                        "trackedProps": [],
                    }
                ]
                module._load_game_line_market_index = lambda d: {}
                module._load_live_lens_feed = lambda game_pk, d: None
                module._load_live_lens_snapshot = lambda game_pk, d, feed=None: {
                    "status": {"abstractGameState": "In Progress", "detailedState": "In Progress"},
                    "teams": {
                        "away": {"totals": {"R": 1}},
                        "home": {"totals": {"R": 2}},
                    },
                }
                module._load_sim_context_for_game = lambda *args, **kwargs: {"found": True}
                module._prop_lens_rows = lambda card, snapshot, sim_context: []
                module._normalize_live_lens_live_prop_row = lambda row, snapshot, card: dict(row)
                module._build_game_lens = lambda *args, **kwargs: []
                module._live_matchup_text = lambda snapshot: "Live state text"

                def fake_current_live_prop_rows(card, snapshot, sim_context, d, **kwargs):
                    self.assertEqual(card.get("status", {}).get("abstract"), "Live")
                    return [
                        {
                            "playerName": "Player A",
                            "selection": "Over",
                            "marketLabel": "Hits",
                            "line": 0.5,
                            "odds": -110,
                            "rankingScore": 0.9,
                            "estimatedWinProb": 0.9,
                            "edge": 0.1,
                        }
                    ]

                module._current_live_prop_rows = fake_current_live_prop_rows

                payload = module._live_lens_payload("2026-06-03", persist=False, refresh_markets=False)

            self.assertEqual(payload["counts"]["live"], 1)
            self.assertEqual(payload["games"][0]["status"]["abstract"], "Live")
            self.assertEqual(payload["games"][0]["status"]["detailed"], "In Progress")
            self.assertEqual(len(payload["games"][0]["liveProps"]), 1)
        finally:
            sys.modules.pop(spec.name, None)

    def test_build_live_lens_snapshot_internal_persist_rewrites_report(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_01.json"
                report_path.write_text(
                    json.dumps(
                        {
                            "generatedAt": "1999-01-01T00:00:00-05:00",
                            "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                            "games": [],
                            "dataRoot": "stale",
                            "liveLensDir": "stale",
                        }
                    ),
                    encoding="utf-8",
                )

                counter = {"value": 0}

                def fake_persist(selected_date: str):
                    counter["value"] += 1
                    payload = {
                        "generatedAt": f"2026-06-01T21:00:0{counter['value']}-05:00",
                        "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                        "games": [
                            {
                                "gamePk": 123,
                                "matchup": {
                                    "away": {"abbr": "AAA", "name": "Away A"},
                                    "home": {"abbr": "BBB", "name": "Home B"},
                                    "score": {"away": 0, "home": 0},
                                    "liveText": "Persisted live lens row",
                                },
                                "status": {"abstract": "Final", "detailed": "Final"},
                                "startTime": "7:10 PM",
                                "gameMarkets": {},
                                "gameLens": [],
                                "props": [],
                                "liveProps": [],
                                "archivedLiveProps": [],
                                "trackedProps": [],
                                "simContextAvailable": False,
                                "snapshotAvailable": False,
                            }
                        ],
                        "dataRoot": module.live_lens_report_path(selected_date).parent.parent.as_posix(),
                        "liveLensDir": module.live_lens_report_path(selected_date).parent.as_posix(),
                        "optimizationRegime": None,
                    }
                    report_path.write_text(json.dumps(payload), encoding="utf-8")
                    return payload

                module.live_lens_report_path = lambda d: report_path
                module.load_json_file = lambda path: json.loads(report_path.read_text(encoding="utf-8"))
                module._persist_live_lens_report = fake_persist

                first_context = module.build_live_lens_snapshot_internal("2026-06-01", persist=True)
                second_context = module.build_live_lens_snapshot_internal("2026-06-01", persist=True)
                persisted_report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(counter["value"], 2)
            self.assertEqual(first_context["generatedAt"], "2026-06-01T21:00:01-05:00")
            self.assertEqual(second_context["generatedAt"], "2026-06-01T21:00:02-05:00")
            self.assertEqual(persisted_report["generatedAt"], "2026-06-01T21:00:02-05:00")
        finally:
            sys.modules.pop(spec.name, None)

    def test_persist_live_lens_report_appends_snapshot_log(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature_log", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_01.json"
                log_path = runtime_live_lens_dir / "live_lens_2026_06_01.jsonl"

                payload = {
                    "generatedAt": "2026-06-01T21:00:01-05:00",
                    "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 2, "archivedLiveProps": 0},
                    "performance": {"marketsRefreshed": True, "persistMs": 12.3},
                    "games": [
                        {
                            "gamePk": 123,
                            "matchup": {
                                "away": {"abbr": "AAA", "name": "Away A"},
                                "home": {"abbr": "BBB", "name": "Home B"},
                                "score": {"away": 3, "home": 1},
                                "liveText": "Live snapshot",
                            },
                            "status": {"abstract": "Live", "detailed": "In Progress"},
                            "liveProps": [
                                {"playerName": "Player One", "selection": "Over", "marketLabel": "Hits", "line": 0.5, "odds": -115},
                                {"playerName": "Player Two", "selection": "Under", "marketLabel": "Ks", "line": 4.5, "odds": 105},
                            ],
                            "props": [],
                            "trackedProps": [],
                        }
                    ],
                }

                import vendor.mlb_bettingv2.tools.web.flask_frontend as vendor_frontend

                module.live_lens_report_path = lambda d: report_path
                module.live_lens_log_path = lambda d: log_path
                module.build_cards_page_context = lambda selected_date, **kwargs: {"source_title": "MLB Game Cards", "using_sample_data": False, "games": []}
                vendor_frontend._live_lens_payload = lambda date_str, *, persist=False, refresh_markets=False: dict(payload)

                result = module._persist_live_lens_report("2026-06-01")
                log_lines = log_path.read_text(encoding="utf-8").splitlines()

                self.assertIsNotNone(result)
                self.assertTrue(report_path.exists())
                self.assertTrue(log_path.exists())
                self.assertEqual(len(log_lines), 1)
                snapshot = json.loads(log_lines[0])
                self.assertEqual(snapshot["date"], "2026-06-01")
                self.assertEqual(snapshot["counts"]["live"], 1)
                self.assertEqual(snapshot["games"][0]["score"], {"away": 3, "home": 1})
                self.assertEqual(snapshot["games"][0]["propCount"], 2)
                self.assertEqual(len(snapshot["games"][0]["topProps"]), 2)
        finally:
            sys.modules.pop(spec.name, None)

    def test_build_live_lens_snapshot_internal_refreshes_stale_current_day_report(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature_stale_refresh", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                today = datetime.now().astimezone().date().isoformat()
                report_path = runtime_live_lens_dir / f"live_lens_report_{today.replace('-', '_')}.json"
                report_path.write_text(
                    json.dumps(
                        {
                            "generatedAt": "1999-01-01T00:00:00-05:00",
                            "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                            "games": [
                                {
                                    "gamePk": 123,
                                    "status": {"abstract": "Live", "detailed": "In Progress"},
                                    "startTime": "7:10 PM",
                                    "matchup": {
                                        "away": {"abbr": "AAA", "name": "Away A"},
                                        "home": {"abbr": "BBB", "name": "Home B"},
                                        "score": {"away": 0, "home": 0},
                                        "liveText": "Stale live lens row",
                                    },
                                    "gameMarkets": {},
                                    "gameLens": [],
                                    "props": [],
                                    "liveProps": [],
                                    "trackedProps": [],
                                    "archivedLiveProps": [],
                                    "simContextAvailable": False,
                                    "snapshotAvailable": False,
                                }
                            ],
                            "source_title": "MLB live-lens report artifact",
                        }
                    ),
                    encoding="utf-8",
                )

                refresh_calls = {"count": 0}

                def fake_persist(selected_date: str):
                    refresh_calls["count"] += 1
                    payload = {
                        "generatedAt": "2026-07-02T12:00:01-05:00",
                        "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                        "games": [
                            {
                                "gamePk": 123,
                                "matchup": {
                                    "away": {"abbr": "AAA", "name": "Away A"},
                                    "home": {"abbr": "BBB", "name": "Home B"},
                                    "score": {"away": 2, "home": 1},
                                    "liveText": "Fresh live lens row",
                                },
                                "status": {"abstract": "Live", "detailed": "In Progress"},
                                "startTime": "7:10 PM",
                                "gameMarkets": {},
                                "gameLens": [],
                                "props": [],
                                "liveProps": [],
                                "trackedProps": [],
                                "archivedLiveProps": [],
                                "simContextAvailable": False,
                                "snapshotAvailable": False,
                            }
                        ],
                        "dataRoot": module.live_lens_report_path(selected_date).parent.parent.as_posix(),
                        "liveLensDir": module.live_lens_report_path(selected_date).parent.as_posix(),
                        "optimizationRegime": None,
                    }
                    report_path.write_text(json.dumps(payload), encoding="utf-8")
                    return payload

                module.live_lens_report_path = lambda d: report_path
                module._path_age_seconds = lambda path: 999.0
                module._persist_live_lens_report = fake_persist

                snapshot = module.build_live_lens_snapshot_internal(today, persist=False)
                persisted_report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(refresh_calls["count"], 1)
            self.assertEqual(snapshot["generatedAt"], "2026-07-02T12:00:01-05:00")
            self.assertEqual(snapshot["games"][0]["matchup"]["score"], {"away": 2, "home": 1})
            self.assertEqual(persisted_report["generatedAt"], "2026-07-02T12:00:01-05:00")
        finally:
            sys.modules.pop(spec.name, None)

    def test_build_live_lens_snapshot_internal_falls_back_to_cards_when_vendor_report_is_empty(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature_cards_fallback", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                spec.loader.exec_module(module)
                import vendor.mlb_bettingv2.tools.web.flask_frontend as vendor_frontend
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_02.json"
                report_path.write_text(json.dumps({"generatedAt": "1999-01-01T00:00:00-05:00", "counts": {"games": 0, "live": 0, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0}, "games": []}), encoding="utf-8")

                module.live_lens_report_path = lambda d: report_path
                module.load_json_file = lambda path: json.loads(report_path.read_text(encoding="utf-8"))
                module._persist_live_lens_report = lambda selected_date: None
                module.build_cards_page_context = lambda selected_date, **kwargs: {
                    "source_title": "MLB Game Cards",
                    "using_sample_data": False,
                    "games": [
                        {
                            "gamePk": 123,
                            "away": {"abbr": "AAA", "name": "Away A"},
                            "home": {"abbr": "BBB", "name": "Home B"},
                            "status": {"abstract": "Final", "detailed": "Final"},
                            "detail": "7:10 PM",
                            "startTime": "7:10 PM",
                            "summary": "Fallback slate",
                            "markets": {},
                            "props": [],
                            "trackedProps": [],
                        }
                    ],
                }

                context = module.build_live_lens_snapshot_internal("2026-06-02", persist=True)
                persisted_report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(context["counts"]["games"], 1)
            self.assertEqual(context["games"][0]["away"]["abbr"], "AAA")
            self.assertEqual(context["games"][0]["home"]["abbr"], "BBB")
            self.assertEqual(persisted_report["counts"]["games"], 1)
        finally:
            sys.modules.pop(spec.name, None)

    def test_build_live_lens_snapshot_internal_merges_cards_detail_into_vendor_report(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature_cards_merge", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_02.json"
                report_path.write_text(
                    json.dumps(
                        {
                            "generatedAt": "1999-01-01T00:00:00-05:00",
                            "counts": {"games": 1, "live": 0, "final": 1, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                            "games": [
                                {
                                    "gamePk": 123,
                                    "status": {"abstract": "Final", "detailed": "Final"},
                                    "startTime": "7:10 PM",
                                    "matchup": {
                                        "away": {"abbr": "AAA", "name": "Away A"},
                                        "home": {"abbr": "BBB", "name": "Home B"},
                                        "score": {"away": 0, "home": 0},
                                        "liveText": "Vendor row",
                                    },
                                    "gameMarkets": {},
                                    "gameLens": [],
                                    "props": [],
                                    "liveProps": [],
                                    "trackedProps": [],
                                    "archivedLiveProps": [],
                                    "simContextAvailable": False,
                                    "snapshotAvailable": False,
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

                module.live_lens_report_path = lambda d: report_path
                module.load_json_file = lambda path: json.loads(report_path.read_text(encoding="utf-8"))
                import vendor.mlb_bettingv2.tools.web.flask_frontend as vendor_frontend
                vendor_frontend._live_lens_payload = lambda *args, **kwargs: {}
                vendor_frontend._live_lens_reports_payload = lambda d, include_archive=False: json.loads(report_path.read_text(encoding="utf-8"))
                module.build_cards_page_context = lambda selected_date, **kwargs: {
                    "source_title": "MLB Game Cards",
                    "using_sample_data": False,
                    "games": [
                        {
                            "gamePk": 123,
                            "away": {"abbr": "AAA", "name": "Away A"},
                            "home": {"abbr": "BBB", "name": "Home B"},
                            "status": {"abstract": "Final", "detailed": "Final"},
                            "detail": "7:10 PM",
                            "startTime": "7:10 PM",
                            "summary": "Fallback slate",
                            "segment_overview_cards": [
                                {"label": "F1", "subtitle": "AAA 0.42 - BBB 0.58 | Total 1.00", "reason": "first segment", "score": "AAA 0 - BBB 0", "main": "No surfaced bet", "best_edge": "0.17", "home_win": "58.0%"}
                            ],
                            "probability_rows": [{"label": "First 1", "summary": "AAA 18.1% | BBB 24.4% | Tie 57.5%"}],
                            "markets": {
                                "extraHitterProps": [{"playerName": "Player A", "selection": "Over", "marketLabel": "Hits", "line": 0.5, "rankingScore": 0.8}],
                                "extraPitcherProps": [],
                                "hitterProps": [],
                                "pitcherProps": [],
                            },
                        }
                    ],
                }

                context = module.build_live_lens_snapshot_internal("2026-06-02", persist=True)
                persisted_report = json.loads(report_path.read_text(encoding="utf-8"))

            target_game = next((game for game in context["games"] if game.get("gamePk") == 123), None)
            persisted_target_game = next((game for game in persisted_report["games"] if game.get("gamePk") == 123), None)

            self.assertIsNotNone(target_game)
            self.assertIsNotNone(persisted_target_game)
            self.assertGreaterEqual(context["counts"]["games"], 1)
            self.assertGreaterEqual(context["counts"]["props"], 1)
            self.assertGreater(len(target_game["gameLens"]), 0)
            self.assertGreater(len(target_game["liveProps"]), 0)
            self.assertEqual(target_game["gameLens"][0]["key"], "first1")
            self.assertEqual(target_game["liveProps"][0]["playerName"], "Player A")
            self.assertGreater(len(persisted_target_game["gameLens"]), 0)
        finally:
            sys.modules.pop(spec.name, None)

    def test_card_to_live_lens_row_uses_segment_overview_when_game_lens_is_thin(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature_card_row", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            spec.loader.exec_module(module)
            card = {
                "gamePk": 123,
                "away": {"abbr": "AAA", "name": "Away A"},
                "home": {"abbr": "BBB", "name": "Home B"},
                "status": {"abstract": "Live", "detailed": "Top 3rd"},
                "summary": "Fallback slate",
                "gameLens": [
                    {
                        "key": "live",
                        "label": "Live",
                        "projection": {"away": None, "home": None, "total": None, "homeMargin": None},
                        "modelHomeWinProb": None,
                        "markets": {"moneyline": {}, "spread": {}, "total": {}},
                    }
                ],
                "segment_overview_cards": [
                    {"label": "Live", "subtitle": "AAA 2.9 - BBB 3.6 | Total 6.5", "reason": "live segment", "score": "AAA 1 - BBB 2", "main": "Over 6.5", "best_edge": "0.7", "home_win": "61.0%"}
                ],
                "probability_rows": [],
            }

            row = module._card_to_live_lens_row(card, report_date="2026-06-02")

            self.assertEqual(row["gameLens"][0]["key"], "live")
            self.assertEqual(row["gameLens"][0]["projection"]["total"], 6.5)
            self.assertEqual(row["gameLens"][0]["projection"]["homeMargin"], 0.7)
        finally:
            sys.modules.pop(spec.name, None)

    def test_merge_cards_context_into_live_row_replaces_thin_live_game_lens(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature_merge_row", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            spec.loader.exec_module(module)
            row = {
                "gamePk": 123,
                "status": {"abstract": "Live", "detailed": "Top 3rd"},
                "gameLens": [
                    {
                        "key": "live",
                        "label": "Live",
                        "projection": {"away": None, "home": None, "total": None, "homeMargin": None},
                        "modelHomeWinProb": None,
                        "markets": {"moneyline": {}, "spread": {}, "total": {}},
                    }
                ],
            }
            card = {
                "gamePk": 123,
                "away": {"abbr": "AAA", "name": "Away A"},
                "home": {"abbr": "BBB", "name": "Home B"},
                "status": {"abstract": "Live", "detailed": "Top 3rd"},
                "summary": "Fallback slate",
                "segment_overview_cards": [
                    {"label": "Live", "subtitle": "AAA 2.9 - BBB 3.6 | Total 6.5", "reason": "live segment", "score": "AAA 1 - BBB 2", "main": "Over 6.5", "best_edge": "0.7", "home_win": "61.0%"}
                ],
                "probability_rows": [],
            }

            merged = module._merge_cards_context_into_live_row(row, card)

            self.assertEqual(merged["gameLens"][0]["key"], "live")
            self.assertEqual(merged["gameLens"][0]["projection"]["total"], 6.5)
            self.assertEqual(merged["gameLens"][0]["projection"]["homeMargin"], 0.7)
        finally:
            sys.modules.pop(spec.name, None)

    def test_build_live_lens_snapshot_internal_synthesizes_props_and_score_from_cards(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature_cards_props", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_03.json"
                report_path.write_text(
                    json.dumps(
                        {
                            "generatedAt": "1999-01-01T00:00:00-05:00",
                            "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                            "games": [
                                {
                                    "gamePk": 123,
                                    "status": {"abstract": "In Progress", "detailed": "In Progress"},
                                    "startTime": "7:10 PM",
                                    "matchup": {
                                        "away": {"abbr": "AAA", "name": "Away A"},
                                        "home": {"abbr": "BBB", "name": "Home B"},
                                        "score": {"away": None, "home": None},
                                        "liveText": "Vendor row",
                                    },
                                    "gameMarkets": {},
                                    "gameLens": [],
                                    "props": [],
                                    "liveProps": [],
                                    "trackedProps": [],
                                    "archivedLiveProps": [],
                                    "simContextAvailable": False,
                                    "snapshotAvailable": False,
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

                module.live_lens_report_path = lambda d: report_path
                module.load_json_file = lambda path: json.loads(report_path.read_text(encoding="utf-8"))
                module._persist_live_lens_report = lambda selected_date: None
                module.build_cards_page_context = lambda selected_date, **kwargs: {
                    "source_title": "MLB Game Cards",
                    "using_sample_data": False,
                    "games": [
                        {
                            "gamePk": 123,
                            "away": {"abbr": "AAA", "name": "Away A"},
                            "home": {"abbr": "BBB", "name": "Home B"},
                            "status": {"abstract": "In Progress", "detailed": "In Progress"},
                            "detail": "7:10 PM",
                            "startTime": "7:10 PM",
                            "summary": "Fallback slate",
                            "prop_groups": [
                                {
                                    "variant": "official",
                                    "sections": [
                                        {
                                            "title": "Pitcher props",
                                            "items": [
                                                {"title": "Player A over 0.5 Hits", "detail": "+105"},
                                            ],
                                        }
                                    ],
                                }
                            ],
                            "actual_box_panel": {
                                "actual_box": {
                                    "totals": [
                                        {"team": "away", "totals": {"R": 3}},
                                        {"team": "home", "totals": {"R": 1}},
                                    ]
                                }
                            },
                            "markets": {},
                        }
                    ],
                }

                context = module.build_live_lens_snapshot_internal("2026-06-03", persist=True)
                persisted_report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(context["counts"]["live"], 1)
            self.assertEqual(context["counts"]["props"], 1)
            self.assertEqual(context["games"][0]["matchup"]["score"], {"away": 3, "home": 1})
            self.assertEqual(len(context["games"][0]["liveProps"]), 1)
            self.assertEqual(len(context["games"][0]["trackedProps"]), 1)
            self.assertEqual(context["games"][0]["liveProps"][0]["playerName"], "Player A")
            self.assertEqual(persisted_report["counts"]["props"], 1)
            self.assertEqual(persisted_report["games"][0]["matchup"]["score"], {"away": 3, "home": 1})
        finally:
            sys.modules.pop(spec.name, None)

    def test_main_prefers_existing_source_artifacts_when_overwrite_off(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            ready_paths = (
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json",
                source_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json",
                source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z" / "refresh_meta.json",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json",
                source_root / "sim_engine" / "live_prop_ranking.py",
            )
            for path in ready_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--overwrite",
                "off",
            ]
            with patch.object(module, "_load_local_fetcher", side_effect=AssertionError("local fetcher should not load")), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "daily" / f"daily_summary_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json").exists())

    def test_main_refreshes_live_lens_when_overwrite_off(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            ready_paths = (
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json",
                source_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json",
                source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z" / "refresh_meta.json",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json",
                source_root / "sim_engine" / "live_prop_ranking.py",
            )
            for path in ready_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            payload = {
                "generatedAt": "2026-05-22T19:15:00-05:00",
                "counts": {"games": 1, "live": 1, "pregame": 0, "final": 0, "props": 0, "archivedLiveProps": 0},
                "games": [{"gamePk": 1}],
            }
            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--overwrite",
                "off",
            ]
            with patch.object(module, "_load_local_fetcher", side_effect=AssertionError("local fetcher should not load")), \
                patch.object(module, "_fetch_live_lens_reports_payload", return_value=payload), \
                patch.dict("os.environ", {"MLB_BETTING_BASE_URL": "https://example.com", "MLB_BETTING_CRON_TOKEN": "token"}, clear=False), \
                patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            report_path = source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json"
            self.assertTrue(report_path.exists())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["counts"]["live"], 1)
            self.assertEqual(
                json.loads((artifact_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json").read_text(encoding="utf-8"))["counts"]["live"],
                1,
            )

    def test_main_builds_live_lens_locally_when_http_refresh_is_unavailable(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            ready_paths = (
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json",
                source_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json",
                source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z" / "refresh_meta.json",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json",
                source_root / "sim_engine" / "live_prop_ranking.py",
            )
            for path in ready_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            payload = {
                "generatedAt": "2026-05-22T19:15:00-05:00",
                "counts": {"games": 2, "live": 1, "pregame": 1, "final": 0, "props": 3, "archivedLiveProps": 0},
                "games": [{"gamePk": 1}, {"gamePk": 2}],
            }
            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--overwrite",
                "off",
            ]
            with patch.object(module, "_load_local_fetcher", side_effect=AssertionError("local fetcher should not load")), \
                patch.object(module, "_build_local_live_lens_reports_payload", return_value=payload) as local_builder, \
                patch.dict("os.environ", {"MLB_BETTING_BASE_URL": "", "MLB_BETTING_CRON_TOKEN": ""}, clear=False), \
                patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertEqual(local_builder.call_count, 1)
            self.assertEqual(local_builder.call_args.kwargs["source_root"].resolve(), source_root.resolve())
            self.assertEqual(local_builder.call_args.kwargs["date_str"], date_str)
            report_path = source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json"
            self.assertTrue(report_path.exists())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["counts"]["props"], 3)

    def test_main_materializes_mlb_artifacts_into_bundle_root(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            required_files = {
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / f"live_lens_{date_slug}.jsonl": "{}\n",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_observations_{date_slug}.jsonl": "{}\n",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json": "{}\n",
                source_root / "sim_engine" / "live_prop_ranking.py": "def rank():\n    return []\n",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json": "{}\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            snapshot_dir = source_root / "data" / "daily" / "snapshots" / date_str
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / f"oddsapi_game_lines_{date_slug}.json").write_text("{}\n", encoding="utf-8")

            refresh_history_dir = source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z"
            refresh_history_dir.mkdir(parents=True, exist_ok=True)
            (refresh_history_dir / "refresh_meta.json").write_text("{}\n", encoding="utf-8")

            class _FakeOddsModule:
                def fetch_and_write_live_odds_for_date(self, date_str: str, *, out_dir, overwrite: bool, regions: str):
                    out_dir = Path(out_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    game = out_dir / f"oddsapi_game_lines_{date_slug}.json"
                    pitcher = out_dir / f"oddsapi_pitcher_props_{date_slug}.json"
                    hitter = out_dir / f"oddsapi_hitter_props_{date_slug}.json"
                    game.write_text("{}\n", encoding="utf-8")
                    pitcher.write_text("{}\n", encoding="utf-8")
                    hitter.write_text("{}\n", encoding="utf-8")
                    return {
                        "game_lines_path": str(game),
                        "pitcher_props_path": str(pitcher),
                        "hitter_props_path": str(hitter),
                    }

            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_load_local_fetcher", return_value=_FakeOddsModule()), patch.object(module, "_local_now", return_value=datetime(2026, 5, 22, 12, 0, 0).astimezone()), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "daily" / f"daily_summary_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / f"live_lens_{date_slug}.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z" / "refresh_meta.json").exists())
            self.assertTrue((artifact_root / "sim_engine" / "live_prop_ranking.py").exists())
            self.assertTrue((artifact_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json").exists())

    def test_main_overwrites_existing_bundle_tree_without_deleting_root_first(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            required_files = {
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / f"live_lens_{date_slug}.jsonl": "{}\n",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_observations_{date_slug}.jsonl": "{}\n",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json": "{}\n",
                source_root / "sim_engine" / "live_prop_ranking.py": "def rank():\n    return []\n",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json": "{}\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            snapshot_dir = source_root / "data" / "daily" / "snapshots" / date_str
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / f"oddsapi_game_lines_{date_slug}.json").write_text("{\"fresh\": true}\n", encoding="utf-8")

            refresh_history_dir = source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z"
            refresh_history_dir.mkdir(parents=True, exist_ok=True)
            (refresh_history_dir / "refresh_meta.json").write_text("{}\n", encoding="utf-8")

            existing_snapshot_dir = artifact_root / "data" / "daily" / "snapshots" / date_str
            existing_snapshot_dir.mkdir(parents=True, exist_ok=True)
            (existing_snapshot_dir / "stale.json").write_text("{}\n", encoding="utf-8")

            class _FakeOddsModule:
                def fetch_and_write_live_odds_for_date(self, date_str: str, *, out_dir, overwrite: bool, regions: str):
                    out_dir = Path(out_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    game = out_dir / f"oddsapi_game_lines_{date_slug}.json"
                    pitcher = out_dir / f"oddsapi_pitcher_props_{date_slug}.json"
                    hitter = out_dir / f"oddsapi_hitter_props_{date_slug}.json"
                    game.write_text("{}\n", encoding="utf-8")
                    pitcher.write_text("{}\n", encoding="utf-8")
                    hitter.write_text("{}\n", encoding="utf-8")
                    return {
                        "game_lines_path": str(game),
                        "pitcher_props_path": str(pitcher),
                        "hitter_props_path": str(hitter),
                    }

            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_load_local_fetcher", return_value=_FakeOddsModule()), patch.object(module, "_local_now", return_value=datetime(2026, 5, 22, 12, 0, 0).astimezone()), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json").exists())

    def test_render_live_lens_refresh_requests_live_lens_and_cache_only(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "render_live_lens_refresh.py"
        spec = importlib.util.spec_from_file_location("test_render_live_lens_refresh", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        calls: list[dict[str, object]] = []

        def _fake_request(session, method, url, *, token, timeout, params=None):
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "token": token,
                    "timeout": timeout,
                    "params": dict(params or {}),
                }
            )
            return {"ok": True, "url": url}

        with patch.dict(
            module.os.environ,
            {
                "MLB_CRON_TOKEN": "token",
                "MLB_WEB_INTERNAL_BASE_URL": "http://example.test",
                "MLB_LIVE_LENS_MARKET_REFRESH_INTERVAL_MINUTES": "999",
            },
            clear=False,
        ), patch.object(module, "_request", side_effect=_fake_request):
            rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual([call["url"] for call in calls], [
            "http://example.test/api/cron/live-lens-tick",
            "http://example.test/api/cron/warm-cards-cache",
        ])
        self.assertEqual(calls[0]["params"], {"refreshMarkets": "off"})