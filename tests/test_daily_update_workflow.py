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
