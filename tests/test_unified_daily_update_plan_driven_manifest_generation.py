from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdatePlanDrivenManifestGenerationTests(unittest.TestCase):
    def test_manifest_generation_uses_run_plan_with_default_fallback(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("manifestGeneration = $true", content)
        self.assertIn("stage = 'manifest_generation'", content)
        self.assertIn("$shouldRunManifestGeneration = Get-RunPlanDecisionValue -Plan $runManifest.runPlan -Key 'manifestGeneration' -Fallback $true", content)
        self.assertIn("if ($shouldRunManifestGeneration) {", content)