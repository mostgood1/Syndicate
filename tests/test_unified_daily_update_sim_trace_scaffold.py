from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateSimTraceScaffoldTests(unittest.TestCase):
    def test_manifest_includes_run_trace_scaffold(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Get-RunTraceSnapshot", content)
        self.assertIn("$Manifest.runTrace = Get-RunTraceSnapshot -Manifest $Manifest", content)
        self.assertIn("eventSimExecutionCount = $eventSimExecutionRecords.Count", content)
        self.assertIn("artifactUpdateCount = $artifactUpdateRecords.Count", content)
        self.assertIn("inputFingerprintCount = $inputFingerprints.Count", content)
        self.assertIn("artifactPathCount = $artifactPaths.Count", content)
        self.assertIn("trace = $Manifest.runTrace", content)
        self.assertIn("function Write-RunTraceArtifact", content)
        self.assertIn("$runTracePath = Join-Path $runDir 'unified_daily_update_run_trace.json'", content)
        self.assertIn("$latestRunTracePath = Join-Path $latestDir 'unified_daily_update_latest_run_trace.json'", content)
