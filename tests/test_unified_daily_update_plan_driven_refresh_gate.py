from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdatePlanDrivenRefreshGateTests(unittest.TestCase):
    def test_refresh_gate_uses_run_plan_with_skip_flag_fallback(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Get-RunPlanDecisionValue", content)
        self.assertIn("$shouldRunRefreshGate = Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'refreshGate' -Fallback ([bool](-not $SkipRefreshGate))", content)
        self.assertIn("if ($shouldRunRefreshGate) {", content)