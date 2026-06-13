from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateReplayContextScaffoldTests(unittest.TestCase):
    def test_manifest_includes_replay_context_scaffold(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("$latestCheckpoint = $null", content)
        self.assertIn("if (Test-Path -LiteralPath $latestCheckpointPath) {", content)
        self.assertIn("replayContext = [ordered]@{", content)
        self.assertIn("latestCheckpointLoaded = [bool]($null -ne $latestCheckpoint)", content)
        self.assertIn("resumeEligible = [bool]($null -ne $latestCheckpoint", content)
        self.assertIn("resumedFromCheckpoint = [bool]($null -ne $latestCheckpoint -and $null -eq $latestManifest)", content)
        self.assertIn("replayContext = $Manifest.replayContext", content)
        self.assertIn("$runManifest.replayContext.latestCheckpointLoaded -and", content)
        self.assertIn("$sourceUpdateAlreadyCompleted = [bool](", content)
        self.assertIn("[string]$runManifest.runState.currentStage -ne 'source_update'", content)
        self.assertIn("Replay checkpoint: source_update already completed; continuing at the next stage.", content)
