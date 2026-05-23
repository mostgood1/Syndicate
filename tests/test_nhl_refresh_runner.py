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

        class _FakeSourceCli:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, str]] = []

            def team_odds_collect(self, *, date: str, markets: str) -> None:
                self.calls.append(("team", date, markets))

            def props_collect(self, *, date: str, source: str) -> None:
                self.calls.append(("props", date, source))

        fake_cli = _FakeSourceCli()

        with tempfile.TemporaryDirectory() as tmp_dir:
            argv = [
                "refresh_nhl_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                tmp_dir,
                "--artifact-root",
                str(Path(tmp_dir) / "bundle"),
            ]
            with patch.object(module, "_load_source_cli", return_value=fake_cli), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(fake_cli.calls, [("team", "2026-05-22", "h2h,spreads,totals"), ("props", "2026-05-22", "oddsapi")])

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

            class _FakeSourceCli:
                def team_odds_collect(self, *, date: str, markets: str) -> None:
                    team_root = source_root / "data" / "odds" / "team" / f"date={date}"
                    team_root.mkdir(parents=True, exist_ok=True)
                    (team_root / "oddsapi.csv").write_text("game_id\nteam-1\n", encoding="utf-8")
                    (team_root / "oddsapi.parquet").write_text("parquet", encoding="utf-8")

                def props_collect(self, *, date: str, source: str) -> None:
                    props_root = source_root / "data" / "props" / "player_props_lines" / f"date={date}"
                    props_root.mkdir(parents=True, exist_ok=True)
                    (props_root / "oddsapi.csv").write_text("player\nProp Skater\n", encoding="utf-8")
                    (props_root / "oddsapi.parquet").write_text("parquet", encoding="utf-8")

            argv = [
                "refresh_nhl_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_load_source_cli", return_value=_FakeSourceCli()), patch("sys.argv", argv):
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