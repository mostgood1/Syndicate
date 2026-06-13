from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateReplayApplyScaffoldTests(unittest.TestCase):
    def test_manifest_applies_replay_context_into_run_state(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Apply-RunReplayContext", content)
        self.assertIn("if (-not [bool]$ReplayContext.resumeEligible) {", content)
        self.assertIn("$Manifest.runState.currentStage = $currentStage", content)
        self.assertIn("$Manifest.runState.completedStages = @($ReplayContext.latestCheckpointCompletedStages)", content)
        self.assertIn("$Manifest.overallStatus = 'resumed'", content)
        self.assertIn("decision = 'resumed'", content)
        self.assertIn("status = if ($DryRun) { 'dry_run' } else { 'resumed' }", content)
        self.assertIn("Apply-RunReplayContext -Manifest $runManifest -ReplayContext $runManifest.replayContext", content)
        self.assertIn("latestCheckpointCompletedStages = if ($null -ne $latestCheckpoint) { @($latestCheckpoint.completedStages) } else { @() }", content)
