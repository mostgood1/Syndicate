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

    def test_refresh_and_gate_points_all_supported_sports_at_source_artifacts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_and_gate.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("$localMlbArtifactRoot = Join-Path $repoRoot 'data\\mlb_source\\source_artifacts'", content)
        self.assertIn("$localNbaArtifactRoot = Join-Path $repoRoot 'data\\nba_source\\source_artifacts'", content)
        self.assertIn("$localNhlArtifactRoot = Join-Path $repoRoot 'data\\nhl_source\\source_artifacts'", content)
        self.assertIn("$localWnbaArtifactRoot = Join-Path $repoRoot 'data\\wnba_source\\source_artifacts'", content)
        self.assertIn("$localNflArtifactRoot = Join-Path $repoRoot 'data\\nfl_source\\source_artifacts'", content)
        self.assertIn("$localNcaafArtifactRoot = Join-Path $repoRoot 'data\\ncaaf_source\\source_artifacts'", content)

    def test_unified_daily_update_force_publishes_mlb_source_artifacts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("foreach ($rootRelative in @('data/mlb_source/data', 'data/mlb_source/source_artifacts/data'))", content)
        self.assertIn('"$rootRelative/daily/daily_summary_${dateSlug}.json"', content)
        self.assertIn('"$rootRelative/live_lens/live_lens_report_${dateSlug}.json"', content)
        self.assertIn('"$rootRelative/daily/snapshots/${DateValue}/oddsapi_game_lines_${dateSlug}.json"', content)
        self.assertIn("Add-PathsUnderRoot -RelativeRoot 'data/mlb_source/manifests'", content)
        self.assertIn("Add-PathsUnderRoot -RelativeRoot 'data/mlb_source/source_artifacts/manifests'", content)

    def test_world_class_plan_explicitly_requires_unified_standardization(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "docs" / "syndicate_world_class_implementation_plan.md"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("## Unified platform standardization", content)
        self.assertIn("one unified logic engine", content)
        self.assertIn("MLB, NBA, and WNBA should be treated as the maturity anchors", content)