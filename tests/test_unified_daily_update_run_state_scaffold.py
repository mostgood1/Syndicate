from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateRunStateScaffoldTests(unittest.TestCase):
    def test_manifest_includes_run_state_scaffold(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("runState = [ordered]@{", content)
        self.assertIn("currentStage = 'queued'", content)
        self.assertIn("completedStages = @()", content)
        self.assertIn("failedStage = $null", content)
        self.assertIn("lastUpdatedAt = $null", content)
        self.assertIn("function Sync-RunStateArtifacts", content)
        self.assertIn("function Update-RunStateStage", content)
        self.assertIn("function Set-RunFailureState", content)
        self.assertIn("Sync-RunStateArtifacts -Manifest $Manifest", content)
        self.assertIn("Update-RunStateStage -Manifest $runManifest -Stage 'source_update' -Status 'started'", content)
        self.assertIn("Update-RunStateStage -Manifest $runManifest -Stage 'refresh_gate' -Status 'completed'", content)
        self.assertIn("Set-RunFailureState -Manifest $runManifest -Stage 'source_update' -Message $_.Exception.Message", content)