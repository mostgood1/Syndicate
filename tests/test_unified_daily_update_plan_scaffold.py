from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdatePlanScaffoldTests(unittest.TestCase):
    def test_manifest_includes_run_mode_and_run_plan_scaffold(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("runMode = if ($DryRun) { 'dry_run' } else { 'standard' }", content)
        self.assertIn("runPlan = [ordered]@{", content)
        self.assertIn("simExecution = $simExecutionDecision", content)
        self.assertIn("sourceUpdates = [bool](-not $SkipSourceUpdates)", content)
        self.assertIn("refreshGate = [bool](-not $SkipRefreshGate)", content)
        self.assertIn("publish = [bool](-not $SkipGitPush)", content)