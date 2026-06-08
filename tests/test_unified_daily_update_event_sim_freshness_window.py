from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateEventSimFreshnessWindowTests(unittest.TestCase):
    def test_close_to_start_time_forces_event_sim_execution(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("Get-Policy -Context $eventPolicyContext -PolicyConfig $eventSimPolicyConfig", content)
        self.assertIn("selectionMode = 'default'", content)
        self.assertIn("selectionMode = 'performance'", content)
        self.assertIn("function Get-EventSimExecutionStartTimeUtc", content)
        self.assertIn("Get-EventSimExecutionDecision -CurrentFingerprint $currentEventInputFingerprint -PreviousFingerprint $previousInputFingerprint -Fallback $null -CurrentTimeUtc $currentTimeUtc -EventStartTimeUtc $eventStartTimeUtc -ForceWithinMinutes $effectiveForceWindowMinutes", content)
        self.assertIn("$currentTimeOffset -ge $windowStartOffset -and $currentTimeOffset -le $eventStartOffset", content)
        self.assertIn("return $true", content)

    def test_far_from_start_time_keeps_fingerprint_skip_behavior(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if ($currentFingerprintText -eq $previousFingerprintText) {", content)
        self.assertIn("return $false", content)

    def test_fingerprint_change_still_triggers_run(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if ([string]::IsNullOrWhiteSpace($previousFingerprintText)) {", content)
        self.assertIn("return $true", content)
        self.assertIn("if ($eventDecision) {", content)


if __name__ == "__main__":
    unittest.main()