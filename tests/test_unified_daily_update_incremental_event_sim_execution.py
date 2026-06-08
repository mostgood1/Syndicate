from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateIncrementalEventSimExecutionTests(unittest.TestCase):
    def test_first_run_without_fingerprint_falls_back_to_full_sim_execution(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Get-EventInputFingerprint", content)
        self.assertIn("if ([string]::IsNullOrWhiteSpace($currentFingerprintText)) {", content)
        self.assertIn("return $Fallback", content)
        self.assertIn("if ([string]::IsNullOrWhiteSpace($previousFingerprintText)) {", content)
        self.assertIn("return $true", content)

    def test_unchanged_inputs_skip_event_execution(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("$currentFingerprintText -eq $previousFingerprintText", content)
        self.assertIn("return $false", content)
        self.assertIn("previousInputFingerprint = $previousInputFingerprint", content)

    def test_changed_inputs_force_event_execution(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("$currentEventInputFingerprint = Get-EventInputFingerprint", content)
        self.assertIn("Get-EventSimExecutionDecision -CurrentFingerprint $currentEventInputFingerprint -PreviousFingerprint $previousInputFingerprint -Fallback $null", content)
        self.assertIn("inputFingerprint = [string]$currentEventInputFingerprint", content)
        self.assertIn("if ($eventDecision) {", content)
        self.assertIn("decision = 'planned'", content)
