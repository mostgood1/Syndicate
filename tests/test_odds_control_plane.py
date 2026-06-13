from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.odds_control_plane import build_odds_control_plane_snapshot
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_paths_for_sport
from syndicate.features.shared.odds_control_plane import write_odds_control_plane_snapshot


class OddsControlPlaneTests(unittest.TestCase):
    def test_odds_history_prefers_artifact_history_over_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            artifact_path = repo_root / "data" / "nba_source" / "artifacts" / "nba" / "odds_history.json"
            tracking_path = repo_root / "data" / "nba_source" / "tracking" / "odds_history.json"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            tracking_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text('{"source":"artifact"}', encoding="utf-8")
            tracking_path.write_text('{"source":"tracking"}', encoding="utf-8")

            with patch("syndicate.features.shared.odds_control_plane.REPO_ROOT", repo_root):
                self.assertEqual(odds_history_paths_for_sport("nba"), [artifact_path, tracking_path])
                self.assertEqual(load_odds_history_payload_for_sport("nba"), {"source": "artifact"})

    def test_control_plane_snapshot_writes_central_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            report_root = repo_root / "reports"
            control_plane_path = report_root / "odds_control_plane" / "latest.json"
            with patch("syndicate.features.shared.odds_control_plane.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.odds_control_plane.reports_root",
                return_value=report_root,
            ):
                snapshot = build_odds_control_plane_snapshot(
                    {
                        "date": "2026-06-12",
                        "phase": "all",
                        "execution_mode": "source",
                        "dry_run": False,
                        "ok": True,
                        "results": [
                            {
                                "sport": "nba",
                                "ok": True,
                                "generation_mode": "local_artifact_bundle",
                                "ingestion_mode": "mirror_script",
                                "source_repo": str(repo_root / "nba_betting_repo"),
                                "source_root_env_var": "SYNDICATE_SOURCE_ROOT_NBA",
                                "artifact_paths": ["one", "two"],
                                "sport_manifest": {"payload": {"metadata": {"post_refresh_ok": True, "mirror_ok": True}}},
                            }
                        ],
                    }
                )
                written = write_odds_control_plane_snapshot(
                    {
                        "date": "2026-06-12",
                        "phase": "all",
                        "execution_mode": "source",
                        "dry_run": False,
                        "ok": True,
                        "results": snapshot["sports"],
                    }
                )

            self.assertEqual(Path(written["path"]), control_plane_path)
            self.assertTrue(control_plane_path.exists())
            self.assertEqual(snapshot["source_precedence"], ["artifact_history", "tracking_history"])
            self.assertEqual(snapshot["sports"][0]["sport"], "nba")
            self.assertEqual(snapshot["sports"][0]["odds_history"]["source_precedence"], ["artifact_history", "tracking_history"])


if __name__ == "__main__":
    unittest.main()