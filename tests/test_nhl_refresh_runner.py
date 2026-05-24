from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NhlRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nhl_oddsapi.py"
        spec = importlib.util.spec_from_file_location("test_refresh_nhl_oddsapi", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

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
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch("sys.argv", argv):
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
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch("sys.argv", argv):
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
            with patch.object(module, "_collect_owned_nhl_artifacts", side_effect=_fake_collect_owned_nhl_artifacts), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "odds" / "games" / "date=2026-05-22" / "scoreboard.csv").exists())