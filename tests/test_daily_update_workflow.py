from __future__ import annotations

import unittest
from pathlib import Path


class DailyUpdateWorkflowTests(unittest.TestCase):
    def test_commit_step_checks_staged_outputs_not_head_commit(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow_path = repo_root / ".github" / "workflows" / "daily-update.yml"
        content = workflow_path.read_text(encoding="utf-8")

        self.assertIn("git diff --cached --name-only --relative", content)
        self.assertIn("artifacts not found in staged pipeline outputs", content)
        self.assertNotIn("artifacts not found in HEAD commit", content)
        self.assertNotIn("(Join-Path $sourceRoot.FullName 'source_artifacts')", content)
        self.assertIn("(Join-Path $sourceRoot.FullName 'manifests')", content)
        self.assertIn("(Join-Path $sourceRoot.FullName 'source_artifacts\\data\\daily')", content)
        self.assertIn("(Join-Path $sourceRoot.FullName 'source_artifacts\\data\\processed')", content)
        self.assertIn("(Join-Path $sourceRoot.FullName 'source_artifacts\\data\\live_lens')", content)

    def test_workflow_runs_daily_update_contract_regressions(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow_path = repo_root / ".github" / "workflows" / "daily-update.yml"
        content = workflow_path.read_text(encoding="utf-8")

        self.assertIn("Run daily update contract regressions", content)
        self.assertIn("tests.test_unified_daily_update_plan_driven_artifact_generation", content)
        self.assertIn("tests.test_daily_update_simulation_contract", content)
        self.assertIn("tests.test_daily_update_simulation_contract_scaffold", content)
        self.assertIn("tests.test_wnba_cards_merge_aliases", content)
        self.assertIn("tests.test_game_board_simulation_contract", content)

    def test_workflow_forces_today_rebuild_on_retries(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow_path = repo_root / ".github" / "workflows" / "daily-update.yml"
        content = workflow_path.read_text(encoding="utf-8")

        self.assertIn("DAILY_UPDATE_FORCE_REBUILD_TODAY", content)
        self.assertIn("-ForceRebuildToday", content)
