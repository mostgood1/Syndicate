from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


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

            module._sync_tree(src_root, dst_root)

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

            module._sync_tree(src_root, dst_root)

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

            module._sync_tree(src_root, dst_root)

            self.assertEqual(dest_file.read_text(encoding="utf-8"), "aaaa\n")

    def test_bootstrap_roots_include_render_critical_paths(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            data_root = Path(temp_dir) / "data-root"

            pairs = module._bootstrap_root_pairs(repo_root, data_root)
            relative_sources = [source.relative_to(repo_root).as_posix() for source, _ in pairs]

            self.assertEqual(
                relative_sources,
                [
                    "data/mlb_source/source_artifacts",
                    "data/mlb_source/manifests",
                    "data/nhl_source/source_artifacts",
                    "data/nhl_source/manifests",
                    "reports/intelligence",
                    "reports/daily_update/latest",
                    "reports/refresh_status/latest",
                ],
            )


if __name__ == "__main__":
    unittest.main()
