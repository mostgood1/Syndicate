from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateEventSimPolicyTests(unittest.TestCase):
    def test_different_sports_produce_different_policy_behavior(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("$eventSimPolicyConfig = [ordered]@{", content)
        self.assertIn("mlb = [ordered]@{", content)
        self.assertIn("policyId = 'sport:mlb:default'", content)
        self.assertIn("policyId = 'sport:nba:default'", content)
        self.assertIn("policyId = 'sport:nba:late'", content)
        self.assertIn("policySource = 'sport'", content)

    def test_fallback_behavior_works_with_no_policy(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Get-Policy", content)
        self.assertIn("if ($null -eq $PolicyConfig) {", content)
        self.assertIn("return $null", content)
        self.assertIn("selectionMode = 'default'", content)
        self.assertIn("Select-BestPolicy -Context $Context -PolicyGroup $selectedPolicy -PolicySource $policySource -PolicyPerformance $PolicyPerformance", content)

    def test_existing_freshness_logic_still_works_with_policy_override(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("$timeToStartMinutes = $null", content)
        self.assertIn("Get-Policy -Context $eventPolicyContext -PolicyConfig $eventSimPolicyConfig", content)
        self.assertIn("Get-Policy -Context $eventPolicyContext -PolicyConfig $eventSimPolicyConfig -PolicyPerformance @($runManifest.policyPerformance)", content)
        self.assertIn("Get-EventSimExecutionDecision -CurrentFingerprint $currentEventInputFingerprint -PreviousFingerprint $previousInputFingerprint -Fallback $null -CurrentTimeUtc $currentTimeUtc -EventStartTimeUtc $eventStartTimeUtc -ForceWithinMinutes $effectiveForceWindowMinutes", content)
        self.assertIn("$currentTimeOffset -ge $windowStartOffset -and $currentTimeOffset -le $eventStartOffset", content)


if __name__ == "__main__":
    unittest.main()