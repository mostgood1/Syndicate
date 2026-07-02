from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateIncrementalArtifactGenerationTests(unittest.TestCase):
    def test_single_event_changed_updates_only_the_incremental_artifact_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("artifactUpdates = @()", content)
        self.assertIn("Sync-RunManifestEventRecords -Manifest $runManifest -EventRecords $stepEventDecisions", content)
        self.assertIn("artifactUpdatePaths = @($runManifest.artifactUpdates | ForEach-Object { [string]$_.artifactPath }", content)
        self.assertIn("Artifact stage incremental: publishing {0} updated event artifact(s).", content)
        self.assertIn("-ForceIncludePaths $artifactUpdatePaths", content)

    def test_incremental_publish_force_adds_ignored_artifact_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("git check-ignore -q -- $relativePath", content)
        self.assertIn("git add -f -- $relativePath", content)
        self.assertIn("git add -- $relativePath", content)

    def test_no_events_changed_skips_artifact_stage(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("Artifact stage no-op: no event-level artifact updates were scheduled; skipping artifact publish.", content)
        self.assertIn("$stageDecision.decision = 'skipped'", content)
        self.assertIn("$stageDecision.status = if ($DryRun) { 'dry_run' } else { 'skipped' }", content)

    def test_fallback_still_runs_full_publish(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("$artifactGenerationFallbackToFullPublish = $true", content)
        self.assertIn("if ($artifactGenerationFallbackToFullPublish) {", content)
        self.assertIn("-ForceIncludePaths (& $resolveForcedPublishArtifactPaths)", content)
