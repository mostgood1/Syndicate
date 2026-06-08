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