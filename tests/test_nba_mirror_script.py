from __future__ import annotations

import unittest
from pathlib import Path


class MlbMirrorScriptTests(unittest.TestCase):
    def test_refresh_mlb_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_mlb_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("[string]$SourceArtifactRoot", content)
        self.assertIn("SYNDICATE_ARTIFACT_ROOT_MLB", content)
        self.assertIn("data\\mlb_source", content)
        self.assertIn("SYNDICATE_DATA_ROOT", content)
        self.assertIn("SYNDICATE_MLB_SOURCE_ROOT", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)
        self.assertIn("usedArtifactBundle", content)
        self.assertIn("tracking", content)


class NbaMirrorScriptTests(unittest.TestCase):
    def test_refresh_nba_mirror_script_has_no_source_app_bootstrap(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nba_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertNotIn("function Ensure-LiveStateSnapshot", content)
        self.assertNotIn("app.app.test_client()", content)
        self.assertNotIn("/api/live_state", content)
        self.assertNotIn("syndicate_emit_nba_live_state_", content)

    def test_refresh_nba_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nba_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("[string]$SourceArtifactRoot", content)
        self.assertIn("SYNDICATE_ARTIFACT_ROOT_NBA", content)
        self.assertIn("SYNDICATE_DATA_ROOT", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)
        self.assertIn("usedArtifactBundle", content)
        self.assertIn("props_movement_signals_", content)
        self.assertIn("odds_nba_player_props_opening_", content)
        self.assertIn("odds_nba_player_props_history_", content)


class NhlMirrorScriptTests(unittest.TestCase):
    def test_refresh_nhl_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nhl_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("[string]$SourceArtifactRoot", content)
        self.assertIn("SYNDICATE_ARTIFACT_ROOT_NHL", content)
        self.assertIn("SYNDICATE_DATA_ROOT", content)
        self.assertIn("SYNDICATE_NHL_SOURCE_ROOT", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)
        self.assertIn("usedArtifactBundle", content)
        self.assertIn("tracking", content)


class NflMirrorScriptTests(unittest.TestCase):
    def test_refresh_nfl_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nfl_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("[string]$SourceArtifactRoot", content)
        self.assertIn("SYNDICATE_ARTIFACT_ROOT_NFL", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)
        self.assertIn("usedArtifactBundle", content)
        self.assertIn("tracking", content)


class NcaafMirrorScriptTests(unittest.TestCase):
    def test_refresh_ncaaf_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_ncaaf_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("[string]$SourceArtifactRoot", content)
        self.assertIn("SYNDICATE_ARTIFACT_ROOT_NCAAF", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)
        self.assertIn("usedArtifactBundle", content)
        self.assertIn("college_football_betting_lines_2025.csv", content)
        self.assertIn("college_football_schedule_2025_predicted_totals_enhanced*.csv", content)
        self.assertIn("tracking", content)


class WnbaMirrorScriptTests(unittest.TestCase):
    def test_refresh_wnba_mirror_script_supports_existing_artifact_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_wnba_source_mirror.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[switch]$UseExistingMirrorArtifacts", content)
        self.assertIn("[string]$SourceArtifactRoot", content)
        self.assertIn("SYNDICATE_ARTIFACT_ROOT_WNBA", content)
        self.assertIn("SYNDICATE_DATA_ROOT", content)
        self.assertIn("SYNDICATE_WNBA_SOURCE_ROOT", content)
        self.assertIn("or use -UseExistingMirrorArtifacts", content)
        self.assertIn("usedExistingMirrorArtifacts", content)
        self.assertIn("usedArtifactBundle", content)
        self.assertIn("props_movement_signals_", content)
        self.assertIn("odds_wnba_player_props_opening_", content)
        self.assertIn("odds_wnba_player_props_history_", content)


class UnifiedDailyUpdatePublishTests(unittest.TestCase):
    def test_basketball_force_publish_paths_include_tracking_artifacts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("props_movement_signals_${DateValue}.csv", content)
        self.assertIn("odds_${SportName}_player_props_opening_${DateValue}.csv", content)
        self.assertIn("odds_${SportName}_player_props_history_${DateValue}.csv", content)

    def test_nba_advanced_gate_includes_live_lens_fallback_artifacts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("live_lens_projections_${DateValue}.jsonl", content)
        self.assertIn("live_snapshots/live_lines_${DateValue}.jsonl", content)
        self.assertIn("live_snapshots/live_player_lens_${DateValue}.jsonl", content)
        self.assertIn("missing live_lens projections artifacts", content)

    def test_non_basketball_force_publish_paths_include_tracking_roots(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("data/mlb_source/tracking", content)
        self.assertIn("data/nhl_source/tracking", content)
        self.assertIn("data/nfl_source/tracking", content)
        self.assertIn("data/ncaaf_source/tracking", content)
        self.assertIn("data/ncaab_source/tracking", content)
