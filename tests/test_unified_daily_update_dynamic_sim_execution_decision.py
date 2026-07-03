from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateDynamicSimExecutionDecisionTests(unittest.TestCase):
    def test_first_run_decision_runs_when_state_is_missing(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Get-SimExecutionDecision", content)
        self.assertIn("if (-not (Test-Path -LiteralPath $LatestManifestPath)) {", content)
        self.assertIn("$null -eq $latestManifest.runState", content)
        self.assertIn("return $true", content)
        self.assertIn("function Get-OddsHistoryTriggerDecision", content)

    def test_existing_artifacts_decision_skips_when_markers_exist(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("Get-OddsHistoryTriggerDecision -RepoRoot $RepoRoot -DateValue $DateValue -Sport $sport -Workflow $workflow", content)
        self.assertIn("$oddsHistoryDecisions = @()", content)
        self.assertIn("return $null", content)
        self.assertIn("Get-BasketballScheduledGamesCheck -Sport $sport -DateValue $DateValue", content)
        self.assertIn("trigger = 'skip_heavy_computation'", content)
        self.assertIn("trigger = 'scheduled_slate'", content)
        self.assertIn("return $true", content)
        self.assertIn("return $false", content)