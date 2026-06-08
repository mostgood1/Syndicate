from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdatePolicyPerformanceTests(unittest.TestCase):
    def test_evaluation_records_include_policy_metadata(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("policyId = [string]$effectivePolicy.policyId", content)
        self.assertIn("policySource = [string]$effectivePolicy.policySource", content)
        self.assertIn("policyKeyParameters = $effectivePolicy.keyParameters", content)
        self.assertIn("selectionMode = 'default'", content)

    def test_aggregation_groups_correctly_by_policy(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Get-PolicyPerformance", content)
        self.assertIn("sampleSize = [int]$groupRecords.Count", content)
        self.assertIn("Group-Object -Property policyId", content)
        self.assertIn("withinWindowCount", content)
        self.assertIn("roi = if ($roiSamples.Count -gt 0)", content)
        self.assertIn("averageTimeToStartMinutes", content)
        self.assertIn("$Manifest.policyPerformance = $policyPerformance", content)
        self.assertIn("Sync-RunManifestPolicyPerformance -Manifest $runManifest", content)

    def test_incremental_evaluation_still_works(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("Sync-RunManifestEventRecords -Manifest $runManifest -EventRecords $stepEventDecisions", content)
        self.assertIn("Update-ManifestEventRecordCollection -ExistingRecords @($Manifest.eventSimExecution) -NewRecords $EventRecords", content)
        self.assertIn("Sync-RunManifestPolicyPerformance -Manifest $runManifest", content)


if __name__ == "__main__":
    unittest.main()