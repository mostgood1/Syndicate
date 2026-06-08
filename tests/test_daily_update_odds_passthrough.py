from __future__ import annotations

import unittest
from pathlib import Path


class DailyUpdateOddsPassthroughTests(unittest.TestCase):
    def test_top_level_in_season_wrapper_exposes_refresh_odds_args(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "daily_update_in_season.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$RefreshOdds", content)
        self.assertIn("[string]$OddsPhase = 'all'", content)
        self.assertIn("[string]$OddsSports = 'all'", content)
        self.assertIn("[string]$OddsRegions = 'us'", content)

    def test_daily_update_wrapper_passes_refresh_odds_args(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if ($RefreshOdds) { $unifiedArgs += '-RefreshOdds' }", content)
        self.assertIn("if ($OddsPhase) { $unifiedArgs += @('-OddsPhase', $OddsPhase) }", content)
        self.assertIn("if ($OddsSports) { $unifiedArgs += @('-OddsSports', $OddsSports) }", content)
        self.assertIn("if ($OddsRegions) { $unifiedArgs += @('-OddsRegions', $OddsRegions) }", content)

    def test_unified_daily_update_passes_refresh_odds_to_refresh_gate(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("if ($RefreshOdds) { $refreshArgs += '-RefreshOdds' }", content)
        self.assertIn("if ($OddsPhase) { $refreshArgs += @('-OddsPhase', $OddsPhase) }", content)
        self.assertIn("if ($OddsSports) { $refreshArgs += @('-OddsSports', $OddsSports) }", content)
        self.assertIn("if ($OddsRegions) { $refreshArgs += @('-OddsRegions', $OddsRegions) }", content)