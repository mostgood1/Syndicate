from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateIncrementalManifestUpdatesTests(unittest.TestCase):
    def test_single_event_changed_updates_only_that_manifest_entry(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Update-ManifestEventRecordCollection", content)
        self.assertIn("function Sync-RunManifestEventRecords", content)
        self.assertIn("Sync-RunManifestEventRecords -Manifest $runManifest -EventRecords $stepEventDecisions", content)
        self.assertIn("Update-ManifestEventRecordCollection -ExistingRecords @($Manifest.eventSimExecution) -NewRecords $EventRecords", content)

    def test_no_changes_preserves_existing_manifest_entries(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if ($null -ne $latestManifest) {", content)
        self.assertIn("$runManifest.eventSimExecution = @($latestManifest.eventSimExecution)", content)
        self.assertIn("$runManifest.artifactUpdates = @($latestManifest.artifactUpdates)", content)
        self.assertIn("if ($stepEventDecisions.Count -gt 0) {", content)

    def test_fallback_path_rebuilds_manifest_from_current_run(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if (($stepEventPlans.Count -eq 0) -and ($null -eq $latestManifest)", content)
        self.assertIn("$fullEventRecords = @()", content)
        self.assertIn("Sync-RunManifestEventRecords -Manifest $runManifest -EventRecords $fullEventRecords -ArtifactUpdateRecords $fullEventRecords", content)
