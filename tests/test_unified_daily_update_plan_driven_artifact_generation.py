from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdatePlanDrivenArtifactGenerationTests(unittest.TestCase):
    def test_artifact_generation_uses_run_plan_with_skip_flag_fallback(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("artifactGeneration = [bool](-not $SkipGitPush)", content)
        self.assertIn("stage = 'artifact_generation'", content)
        self.assertIn("$shouldRunArtifactGeneration = Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'artifactGeneration' -Fallback ([bool](-not $SkipGitPush))", content)
        self.assertIn("if ($shouldRunArtifactGeneration) {", content)