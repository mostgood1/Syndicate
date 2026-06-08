from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedDailyUpdateStageDecisionScaffoldTests(unittest.TestCase):
    def test_manifest_includes_stage_decision_scaffold(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("stageDecisions = @(", content)
        self.assertIn("stage = 'source_update'", content)
        self.assertIn("decision = 'planned'", content)
        self.assertIn("stage = 'refresh_gate'", content)
        self.assertIn("stage = 'git_publish'", content)