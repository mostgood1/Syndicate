from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateStatusArtifactScaffoldTests(unittest.TestCase):
    def test_manifest_includes_status_artifact_scaffold(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("statusArtifact = [ordered]@{", content)
        self.assertIn("scope = 'daily_update'", content)
        self.assertIn("runManifestPath = $runManifestPath", content)
        self.assertIn("latestManifestPath = $latestManifestPath", content)
        self.assertIn("runCheckpointPath = $runCheckpointPath", content)
        self.assertIn("latestCheckpointPath = $latestCheckpointPath", content)
        self.assertIn("function Write-RunStateArtifact", content)
        self.assertIn("$runStatePath = Join-Path $runDir 'unified_daily_update_run_state.json'", content)
        self.assertIn("$latestRunStatePath = Join-Path $latestDir 'unified_daily_update_latest_run_state.json'", content)
        self.assertIn("currentStage = 'queued'", content)
        self.assertIn("replayContext = $null", content)
        self.assertIn("$Manifest.statusArtifact.state.replayContext = $Manifest.replayContext", content)
        self.assertIn("function Write-RunCheckpoint", content)