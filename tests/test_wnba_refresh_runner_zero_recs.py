from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class WnbaRefreshRunnerZeroRecsTests(unittest.TestCase):
    @staticmethod
    def _load_module(repo_root: Path):
        script_path = repo_root / "scripts" / "refresh_wnba_oddsapi_props.py"
        spec = importlib.util.spec_from_file_location("test_refresh_wnba_oddsapi_props_zero_recs", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_main_does_not_fail_when_recommendations_rows_are_zero(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            source_root.mkdir(parents=True, exist_ok=True)
            artifact_root.mkdir(parents=True, exist_ok=True)

            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                "2026-06-22",
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
                "--mode",
                "fast",
            ]
            fake_state = {
                "date": "2026-06-22",
                "started_at": "2026-06-23T02:00:00Z",
                "ended_at": "2026-06-23T02:00:05Z",
                "phase": "done",
                "phase_started_at": "2026-06-23T02:00:05Z",
                "heartbeat_at": "2026-06-23T02:00:05Z",
                "rc_snapshot": 0,
                "rc_edges": 0,
                "rc_export": 0,
                "snapshot_rows": 12,
                "predictions_rows": 8,
                "edges_rows": 6,
                "recs_rows": 0,
                "game_cards_rows": 2,
                "snapshot_path": str(source_root / "data" / "raw" / "odds_wnba_player_props_2026-06-22.csv"),
                "predictions_path": str(artifact_root / "data" / "processed" / "props_predictions_2026-06-22.csv"),
                "edges_path": str(artifact_root / "data" / "processed" / "props_edges_2026-06-22.csv"),
                "recs_path": str(artifact_root / "data" / "processed" / "props_recommendations_2026-06-22.csv"),
                "snapshot_alias_path": str(artifact_root / "data" / "processed" / "oddsapi_player_props_2026-06-22.csv"),
                "snapshot_alias_rows": 12,
                "duration_s": 5.0,
                "error": None,
                "mode": "fast",
            }

            with patch.object(module, "_existing_refresh_state", return_value=None), patch.object(module, "_existing_artifact_bundle_state", return_value=None), patch.object(module, "_run_refresh_via_cli", return_value=fake_state), patch.object(module, "_run_playoff_transition_if_needed", return_value={"status": "unavailable"}), patch.object(sys, "argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
