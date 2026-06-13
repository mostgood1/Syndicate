from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateSimNoOpDetectionTests(unittest.TestCase):
    def test_no_events_need_simulation_skips_stage(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Get-SimExecutionNoOpDecision", content)
        self.assertIn("[string]$LatestCheckpointPath", content)
        self.assertIn("$hasLatestCheckpoint = -not [string]::IsNullOrWhiteSpace($LatestCheckpointPath)", content)
        self.assertIn("Get-OddsHistoryTriggerDecision -RepoRoot $RepoRoot -DateValue $DateValue -Sport $sport -Workflow $workflow", content)
        self.assertIn("skip_heavy_computation", content)
        self.assertIn("$shouldRunSimExecution = $false", content)
        self.assertIn("if ($simExecutionNoOpDecision -eq $false) {", content)

    def test_at_least_one_event_needs_simulation_runs_stage_normally(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if (@($oddsHistoryDecisions | Where-Object { [bool]$_.runSimulation -or [bool]$_.priorityScoring }).Count -gt 0) {", content)
        self.assertIn("return $true", content)
        self.assertIn("if ($shouldRunSimExecution) {", content)
