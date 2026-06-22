from __future__ import annotations

import unittest
from pathlib import Path


class DailyUpdateSimulationContractScaffoldTests(unittest.TestCase):
    def test_unified_daily_update_emits_simulation_contract_artifact(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("$runSimulationContractPath = Join-Path $runDir 'unified_daily_update_simulation_contract.json'", content)
        self.assertIn("$latestSimulationContractPath = Join-Path $latestDir 'unified_daily_update_latest_simulation_contract.json'", content)
        self.assertIn("function Write-SimulationContractArtifact", content)
        self.assertIn("--run-output $runSimulationContractPath", content)
        self.assertIn("--latest-output $latestSimulationContractPath", content)
        self.assertIn("build_daily_update_simulation_contract.py", content)

    def test_helper_script_uses_shared_simulation_adapter(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "build_daily_update_simulation_contract.py"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("build_unified_simulation_adapter", content)
        self.assertIn("nfl_default_week", content)
        self.assertIn("ncaaf_default_week", content)
        self.assertIn('"source_modes": {contract["sport"]: contract.get("source_mode") for contract in sport_contracts}', content)
        self.assertIn('"freshness": {contract["sport"]: contract.get("freshness") for contract in sport_contracts}', content)
        self.assertIn('"source_paths": {contract["sport"]: contract.get("source_paths") for contract in sport_contracts}', content)
        self.assertIn('"advanced_by_sport": advanced_by_sport', content)

    def test_workflow_docs_mark_simulation_contract_as_reference(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow_doc = repo_root / "docs" / "daily_update_workflow.md"
        control_plane_doc = repo_root / "docs" / "daily_update_control_plane.md"

        workflow_content = workflow_doc.read_text(encoding="utf-8")
        control_plane_content = control_plane_doc.read_text(encoding="utf-8")

        self.assertIn("canonical cross-sport simulation reference", workflow_content)
        self.assertIn("unified_daily_update_latest_simulation_contract.json", workflow_content)
        self.assertIn("canonical cross-sport reference for daily-update debugging", control_plane_content)