from __future__ import annotations

import importlib.util
import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "bootstrap_data_root.py"
    spec = importlib.util.spec_from_file_location("bootstrap_data_root", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load bootstrap_data_root module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BootstrapDataRootTests(unittest.TestCase):
    def test_sync_tree_copies_missing_files(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
            src_root = Path(src_dir)
            dst_root = Path(dst_dir)
            (src_root / "nba_source" / "data" / "processed").mkdir(parents=True, exist_ok=True)
            expected_path = src_root / "nba_source" / "data" / "processed" / "game_cards_2026-05-28.csv"
            expected_path.write_text("header\nvalue\n", encoding="utf-8")

            module._sync_tree(src_root, dst_root, {}, "nba_source")

            copied_path = dst_root / "nba_source" / "data" / "processed" / "game_cards_2026-05-28.csv"
            self.assertTrue(copied_path.exists())
            self.assertEqual(copied_path.read_text(encoding="utf-8"), "header\nvalue\n")

    def test_sync_tree_updates_stale_files(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
            src_root = Path(src_dir)
            dst_root = Path(dst_dir)
            relative_path = Path("mlb_source") / "data" / "daily" / "daily_summary_2026_05_28.json"
            source_file = src_root / relative_path
            dest_file = dst_root / relative_path
            source_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text('{"games": 12}\n', encoding="utf-8")
            dest_file.write_text('{"games": 0}\n', encoding="utf-8")

            module._sync_tree(src_root, dst_root, {}, "mlb_source")

            self.assertEqual(dest_file.read_text(encoding="utf-8"), '{"games": 12}\n')

    def test_sync_tree_overwrites_same_size_stale_files(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
            src_root = Path(src_dir)
            dst_root = Path(dst_dir)
            relative_path = Path("nhl_source") / "data" / "processed" / "predictions_2026-06-02.csv"
            source_file = src_root / relative_path
            dest_file = dst_root / relative_path
            source_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text("aaaa\n", encoding="utf-8")
            dest_file.write_text("bbbb\n", encoding="utf-8")
            stamp = 1_725_000_000.0
            os.utime(source_file, (stamp, stamp))
            os.utime(dest_file, (stamp, stamp))

            module._sync_tree(src_root, dst_root, {}, "nhl_source")

            self.assertEqual(dest_file.read_text(encoding="utf-8"), "aaaa\n")

    def test_sync_tree_skips_unchanged_files(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
            src_root = Path(src_dir)
            dst_root = Path(dst_dir)
            relative_path = Path("wnba_source") / "data" / "processed" / "props_recommendations_top_by_game_2026-06-18.json"
            source_file = src_root / relative_path
            dest_file = dst_root / relative_path
            source_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text("{\"ok\": true}\n", encoding="utf-8")
            dest_file.write_text("{\"ok\": true}\n", encoding="utf-8")

            with patch.object(module.filecmp, "cmp", return_value=True):
                with patch.object(module.shutil, "copy2") as copy_mock:
                    module._sync_tree(src_root, dst_root, {}, "wnba_source")

            self.assertEqual(dest_file.read_text(encoding="utf-8"), '{"ok": true}\n')
            copy_mock.assert_not_called()

    def test_sync_bootstrap_roots_isolates_a_failing_root_from_later_ones(self) -> None:
        # Confirmed live 2026-08-01: main() has no try/except around this
        # loop, and app.py's caller wraps the whole call in a bare `except
        # Exception: pass` -- so one root throwing used to silently abort
        # every root listed after it in BOOTSTRAP_ROOTS, with zero error
        # surfaced anywhere. soccer_source (last among the per-sport roots)
        # never reached web's disk as a result, degrading MLS player-prop
        # generation to zero rows. Each root must sync independently.
        module = _load_module()
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
            src_root = Path(src_dir)
            dst_root = Path(dst_dir)
            (src_root / "mlb_source").mkdir(parents=True, exist_ok=True)
            (src_root / "soccer_source" / "mls" / "players").mkdir(parents=True, exist_ok=True)
            players_file = src_root / "soccer_source" / "mls" / "players" / "players_2026.csv"
            players_file.write_text("player_id,name\n1,Real Player\n", encoding="utf-8")

            real_sync_tree = module._sync_tree

            def _flaky_sync_tree(source, destination, counters, key):
                if key == "mlb_source":
                    raise OSError("simulated disk failure syncing mlb_source")
                return real_sync_tree(source, destination, counters, key)

            with patch.object(
                module,
                "_bootstrap_root_pairs",
                return_value=[
                    (src_root / "mlb_source", dst_root / "mlb_source", "mlb_source"),
                    (src_root / "soccer_source", dst_root / "soccer_source", "soccer_source"),
                ],
            ), patch.object(module, "_sync_tree", side_effect=_flaky_sync_tree):
                counters = module._sync_bootstrap_roots(src_root, dst_root)

            copied_players_file = dst_root / "soccer_source" / "mls" / "players" / "players_2026.csv"
            self.assertTrue(copied_players_file.exists(), "soccer_source must still sync after mlb_source fails")
            self.assertEqual(copied_players_file.read_text(encoding="utf-8"), "player_id,name\n1,Real Player\n")
            self.assertNotIn("mlb_source", counters)
            self.assertEqual(counters.get("soccer_source"), 1)

    def test_bootstrap_roots_include_render_critical_paths(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            data_root = Path(temp_dir) / "data-root"

            pairs = module._bootstrap_root_pairs(repo_root, data_root)
            relative_sources = [source.relative_to(repo_root).as_posix() for source, _, _ in pairs]

            self.assertEqual(
                relative_sources,
                [
                    "data/mlb_source/source_artifacts",
                    "data/mlb_source/manifests",
                    "data/nba_source/source_artifacts",
                    "data/nba_source/manifests",
                    "data/nhl_source/source_artifacts",
                    "data/nhl_source/manifests",
                    "data/nfl_source/source_artifacts",
                    "data/nfl_source/manifests",
                    "data/ncaaf_source/source_artifacts",
                    "data/ncaaf_source/manifests",
                    "data/ncaab_source/source_artifacts",
                    "data/ncaab_source/manifests",
                    "data/wnba_source/source_artifacts",
                    "data/wnba_source/manifests",
                    "data/soccer_source",
                    "reports/odds_control_plane",
                    "reports/daily_update/latest",
                    "reports/refresh_status/latest",
                    "vendor/wnba_betting_repo/src",
                    "reports/intelligence/board_snapshot.json",
                    "reports/intelligence/intelligence_state.json",
                    "reports/intelligence/intelligence_state_history.jsonl",
                    "reports/intelligence/status_response_cache.json",
                    "reports/intelligence/query_state_cache.json",
                    "reports/intelligence/query_response_cache.json",
                    "reports/intelligence/query_response_version.json",
                    "reports/intelligence/performance_summary.json",
                ],
            )

    def test_bootstrap_roots_include_daily_intelligence_artifacts(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            data_root = Path(temp_dir) / "data-root"
            daily_snapshot = repo_root / "reports" / "intelligence" / "board_snapshot_2026_06_18.json"
            daily_snapshot.parent.mkdir(parents=True, exist_ok=True)
            daily_snapshot.write_text("{}\n", encoding="utf-8")

            pairs = module._bootstrap_root_pairs(repo_root, data_root)
            relative_sources = [source.relative_to(repo_root).as_posix() for source, _, _ in pairs]

            self.assertIn("reports/intelligence/board_snapshot_2026_06_18.json", relative_sources)

    def test_bootstrap_wnba_today_artifacts_runs_when_missing(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data-root"
            with patch.dict(os.environ, {"SYNDICATE_BOOTSTRAP_ON_START": "1", "SYNDICATE_BOOTSTRAP_WNBA_TODAY": "1"}, clear=False):
                with patch.object(module.subprocess, "Popen") as popen_mock:
                    did_run = module._bootstrap_wnba_today_artifacts(Path(__file__).resolve().parents[1], data_root)

            self.assertTrue(did_run)
            popen_mock.assert_called_once()
            called_command = popen_mock.call_args.args[0]
            self.assertIn("--sports", called_command)
            self.assertIn("wnba", called_command)
            self.assertIn("--execution-mode", called_command)
            self.assertIn("source", called_command)
            self.assertNotIn("--source-root", called_command)
            called_env = popen_mock.call_args.kwargs.get("env") or {}
            self.assertEqual(
                called_env.get("SYNDICATE_SOURCE_ROOT_WNBA"),
                str(Path(__file__).resolve().parents[1] / "vendor" / "wnba_betting_repo"),
            )

    def test_bootstrap_wnba_today_artifacts_skips_when_present(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data-root"
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            for sentinel in [module._wnba_today_props_path(data_root, today), *module._wnba_today_bundle_paths(data_root, today)]:
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text("{}\n", encoding="utf-8")

            with patch.dict(os.environ, {"SYNDICATE_BOOTSTRAP_ON_START": "1"}, clear=False):
                with patch.object(module.subprocess, "run") as run_mock:
                    did_run = module._bootstrap_wnba_today_artifacts(Path(__file__).resolve().parents[1], data_root)

            self.assertFalse(did_run)
            run_mock.assert_not_called()

    def test_bootstrap_wnba_today_artifacts_runs_when_cards_missing(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data-root"
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            sentinel = module._wnba_today_props_path(data_root, today)
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("{}\n", encoding="utf-8")

            with patch.dict(os.environ, {"SYNDICATE_BOOTSTRAP_ON_START": "1", "SYNDICATE_BOOTSTRAP_WNBA_TODAY": "1"}, clear=False):
                with patch.object(module.subprocess, "Popen") as popen_mock:
                    did_run = module._bootstrap_wnba_today_artifacts(Path(__file__).resolve().parents[1], data_root)

            self.assertTrue(did_run)
            popen_mock.assert_called_once()

    def test_main_triggers_wnba_artifact_bootstrap(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data-root"
            with patch.dict(os.environ, {"SYNDICATE_BOOTSTRAP_ON_START": "1", "SYNDICATE_BOOTSTRAP_WNBA_TODAY": "1", "SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                with patch.object(module, "_sync_bootstrap_roots", return_value={}) as sync_mock:
                    with patch.object(module, "_bootstrap_wnba_today_artifacts", return_value=True) as bootstrap_mock:
                        exit_code = module.main()

        self.assertEqual(exit_code, 0)
        sync_mock.assert_called_once()
        bootstrap_mock.assert_called_once()

    def test_main_still_bootstraps_when_intelligence_state_exists(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data-root"
            sentinel = module._intelligence_latest_state_path(data_root)
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("{}\n", encoding="utf-8")

            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                with patch.object(module, "_sync_bootstrap_roots") as sync_mock:
                    with patch.object(module, "_bootstrap_wnba_today_artifacts") as wnba_mock:
                        exit_code = module.main()

        self.assertEqual(exit_code, 0)
        sync_mock.assert_called_once()
        wnba_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
