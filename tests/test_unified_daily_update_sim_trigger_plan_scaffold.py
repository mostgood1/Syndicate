from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateSimTriggerPlanScaffoldTests(unittest.TestCase):
    def test_manifest_includes_sim_trigger_plan_scaffold(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("oddsHistoryTriggerPlan = @(", content)
        self.assertIn("simTriggerPlan = @(", content)
        self.assertIn("trigger = $_.trigger", content)
        self.assertIn("priorityScoring = $_.priorityScoring", content)
        self.assertIn("maxDeltaDetected = $_.maxDeltaDetected", content)