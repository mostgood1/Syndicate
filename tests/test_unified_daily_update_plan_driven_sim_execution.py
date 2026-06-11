from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdatePlanDrivenSimExecutionTests(unittest.TestCase):
    def test_sim_execution_uses_run_plan_with_skip_flag_fallback(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("Get-SimExecutionDecision", content)
        self.assertIn("simExecution = $simExecutionDecision", content)
        self.assertIn("stage = 'sim_execution'", content)
        self.assertIn("oddsHistoryTriggerPlan = @(", content)
        self.assertIn("$shouldRunSimExecution = Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'simExecution' -Fallback ([bool](-not $SkipSourceUpdates))", content)
        self.assertIn("if ($shouldRunSimExecution) {", content)