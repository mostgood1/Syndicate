from __future__ import annotations

import unittest
from pathlib import Path


class DailyUpdateRootLauncherTests(unittest.TestCase):
    def test_root_wrapper_delegates_to_in_season_controller(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "daily_update_in_season.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("Join-Path $PSScriptRoot 'scripts\\daily_update_in_season.ps1'", content)
        self.assertIn("& $target @PSBoundParameters", content)

    def test_root_wrapper_preserves_force_switch_surface(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "daily_update_in_season.ps1"
        content = script_path.read_text(encoding="utf-8")

        for switch_name in (
            "ForceMLB",
            "ForceNBA",
            "ForceNHL",
            "ForceWNBA",
            "ForceNFL",
            "ForceNCAAF",
            "ForceNCAAB",
        ):
            self.assertIn(f"[switch]${switch_name}", content)

    def test_root_wrapper_preserves_event_sim_force_window(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "daily_update_in_season.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[int]$EventSimForceWindowMinutes = 30", content)

    def test_in_season_wrapper_syncs_source_artifacts_for_active_sports(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "daily_update_in_season.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function Sync-SportSourceArtifacts", content)
        self.assertIn("data\\{0}_source\\source_artifacts\\data", content)
        self.assertIn("@('mlb', 'nba', 'wnba', 'nhl', 'nfl', 'ncaaf', 'ncaab')", content)