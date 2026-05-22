from __future__ import annotations

import unittest
from pathlib import Path


class NbaMirrorScriptTests(unittest.TestCase):
    def test_refresh_nba_mirror_script_has_no_source_app_bootstrap(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nba_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertNotIn("function Ensure-LiveStateSnapshot", content)
        self.assertNotIn("app.app.test_client()", content)
        self.assertNotIn("/api/live_state", content)
        self.assertNotIn("syndicate_emit_nba_live_state_", content)

    def test_refresh_nba_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nba_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)


class NhlMirrorScriptTests(unittest.TestCase):
    def test_refresh_nhl_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nhl_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)


class WnbaMirrorScriptTests(unittest.TestCase):
    def test_refresh_wnba_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_wnba_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)
