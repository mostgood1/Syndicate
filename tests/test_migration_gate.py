from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.migration_gate import evaluate_active_sport_advanced_readiness
from scripts.migration_gate import evaluate_protected_mirror_assets
from scripts.migration_gate import evaluate_protected_runtime_contracts
from scripts.migration_gate import evaluate_protected_local_resolvers
from scripts.migration_gate import evaluate_runtime_dependency_findings
from scripts.migration_gate import evaluate_protected_source_shell_routes
from scripts.migration_gate import normalize_runtime_dependency_findings
from scripts.migration_gate import render_text_report
from scripts.migration_gate import run_command
from scripts.module_tracker_snapshot import module_snapshot
from syndicate.features.shared.source_roots import preferred_source_roots


class MigrationGateRuntimeDependencyTests(unittest.TestCase):
    def test_run_command_marks_timeout_as_failure_with_message(self) -> None:
        with patch("scripts.migration_gate.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=1)):
            result = run_command("timeout_test", ["python", "-c", "pass"], timeout_sec=1)

        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 124)
        self.assertTrue(result.timed_out)
        self.assertIn("timed out", result.stderr.lower())

    def test_preferred_source_roots_returns_local_mirror_without_sibling_fallback(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            file_path = repo_root / "syndicate" / "features" / "nba" / "sources.py"
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with patch.dict(os.environ, {}, clear=False):
                roots = preferred_source_roots(
                    file_path,
                    env_var="TEST_SOURCE_ROOT",
                    local_dir_name="nba_source",
                )

        self.assertEqual(roots, [(repo_root / "data" / "nba_source").resolve()])

    def test_normalize_runtime_dependency_findings_reads_tracker_summary(self) -> None:
        payload = {
            "gap_summary": {
                "modules_ranked_by_ownership": [
                    {
                        "slug": "ncaab",
                        "dependency_tier": "source_backed",
                        "ownership_score": 30,
                        "fallback_surfaces": ["cards", "game"],
                    },
                    {
                        "slug": "ncaaf",
                        "dependency_tier": "artifact_backed",
                        "ownership_score": 85,
                        "fallback_surfaces": [],
                    },
                ]
            }
        }

        findings = normalize_runtime_dependency_findings(payload)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["slug"], "ncaab")
        self.assertEqual(findings[0]["fallback_surfaces"], ("cards", "game"))

    def test_runtime_dependency_allowlist_flags_unexpected_changes(self) -> None:
        findings = [
            {
                "slug": "nba",
                "dependency_tier": "mixed_local_and_source",
                "fallback_surfaces": ("cards", "props"),
            },
            {
                "slug": "nhl",
                "dependency_tier": "mixed_local_and_source",
                "fallback_surfaces": ("cards", "live-lens", "props"),
            },
            {
                "slug": "ncaab",
                "dependency_tier": "source_backed",
                "fallback_surfaces": ("cards", "game"),
            },
        ]

        unexpected, missing = evaluate_runtime_dependency_findings(findings)

        self.assertEqual({item["slug"] for item in unexpected}, {"nba", "nhl", "ncaab"})
        self.assertEqual(missing, [])

    def test_render_text_report_includes_runtime_dependency_section(self) -> None:
        report = {
            "ok": True,
            "audit": {
                "ok": True,
                "allowed_count": 4,
                "actual_count": 4,
                "unexpected_findings": [],
                "missing_allowed_findings": [],
            },
            "runtime_dependency": {
                "ok": True,
                "allowed_count": 4,
                "actual_count": 4,
                "unexpected_findings": [],
                "missing_allowed_findings": [],
                "protected_mirror_asset_violations": [],
                "lowest_ownership_modules": [
                    {"slug": "nba", "ownership_score": 53, "dependency_tier": "mixed_local_and_source"}
                ],
            },
            "commands": [],
        }

        rendered = render_text_report(report)

        self.assertIn("Runtime dependency: PASS", rendered)
        self.assertIn("Lowest ownership modules:", rendered)
        self.assertIn("nba: score=53; tier=mixed_local_and_source", rendered)

    def test_evaluate_active_sport_advanced_readiness_skips_out_of_season_and_no_games(self) -> None:
        sports = [
            {
                "slug": "ncaab",
                "name": "NCAAB",
                "active_today": True,
                "advanced_ready": False,
                "readiness_gate": {"state": "ready"},
                "advanced_gate": {
                    "required_total": 3,
                    "exists_count": 0,
                    "tracked_count": 0,
                    "missing_inputs": [{"label": "Recommendations mirror"}],
                    "publish_missing_inputs": [],
                },
            },
            {
                "slug": "nhl",
                "name": "NHL",
                "active_today": True,
                "advanced_ready": False,
                "readiness_gate": {"state": "ready"},
                "advanced_gate": {
                    "required_total": 3,
                    "exists_count": 1,
                    "tracked_count": 0,
                    "missing_inputs": [{"label": "Recommendations"}],
                    "publish_missing_inputs": [{"label": "Scoreboard snapshot"}],
                },
            },
            {
                "slug": "wnba",
                "name": "WNBA",
                "active_today": True,
                "advanced_ready": True,
                "readiness_gate": {"state": "ready"},
                "advanced_gate": {
                    "required_total": 3,
                    "exists_count": 3,
                    "tracked_count": 3,
                    "missing_inputs": [],
                    "publish_missing_inputs": [],
                },
            },
        ]

        with patch("scripts.migration_gate._load_intelligence_status_for_migration_gate", return_value=("2026-06-05", {"sports": sports}, None)), \
             patch("scripts.migration_gate._scheduled_game_count", side_effect=[(True, 0), (True, 2)]):
            result = evaluate_active_sport_advanced_readiness()

        self.assertTrue(result["ok"])
        self.assertEqual(result["active_sport_count"], 1)
        self.assertEqual([item["slug"] for item in result["active_sports"]], ["wnba"])
        self.assertEqual(result["violations"], [])

    def test_evaluate_protected_mirror_assets_flags_missing_mlb_live_prop_assets(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            cfg_path = repo_root / "data" / "mlb_source" / "data" / "tuning" / "live_prop_ranking" / "default.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text("{}\n", encoding="utf-8")

            violations = evaluate_protected_mirror_assets(repo_root)

        mlb_violations = [item for item in violations if item["slug"] == "mlb"]
        self.assertEqual(len(mlb_violations), 2)
        self.assertEqual({item["description"] for item in mlb_violations}, {"live prop ranking predictor", "daily mirror manifest breadth"})

    def test_evaluate_protected_mirror_assets_flags_missing_mlb_manifest_artifact_families(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            cfg_path = repo_root / "data" / "mlb_source" / "data" / "tuning" / "live_prop_ranking" / "default.json"
            predictor_path = repo_root / "data" / "mlb_source" / "sim_engine" / "live_prop_ranking.py"
            manifest_path = repo_root / "data" / "mlb_source" / "manifests" / "mirror_refresh_latest.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            predictor_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text("{}\n", encoding="utf-8")
            predictor_path.write_text("# stub\n", encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "copiedArtifacts": [
                            "daily\\daily_summary_2026_05_21.json",
                            "daily\\ladders\\daily_ladders_2026_05_21.json",
                            "eval\\seasons\\2026\\season_eval_manifest.json",
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            violations = evaluate_protected_mirror_assets(repo_root)

        mlb_violations = [item for item in violations if item["slug"] == "mlb" and item.get("issue") == "missing_manifest_artifacts"]
        self.assertEqual(len(mlb_violations), 1)
        self.assertEqual(
            mlb_violations[0]["missing_prefixes"],
            [
                "daily\\top_props\\daily_top_props_",
                "daily\\ops\\daily_ops_",
                "daily\\snapshots\\",
                "daily\\sims\\",
            ],
        )

    def test_evaluate_protected_mirror_assets_flags_missing_nba_manifest_artifact_families(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            manifest_path = repo_root / "data" / "nba_source" / "manifests" / "mirror_refresh_latest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "copiedArtifacts": [
                            "live_lens_projections_2026-05-09.jsonl",
                            "live_snapshots\\live_state_2026-05-19.jsonl",
                            "recon_games_2026-05-19.csv",
                            "season_betting_card_manifest_2026_retuned.json",
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            violations = evaluate_protected_mirror_assets(repo_root)

        nba_violations = [item for item in violations if item["slug"] == "nba"]
        self.assertEqual(len(nba_violations), 1)
        self.assertEqual(nba_violations[0]["issue"], "missing_manifest_artifacts")
        self.assertEqual(
            nba_violations[0]["missing_prefixes"],
            ["live_lens_signals_", "recon_props_", "season_betting_card_day_"],
        )

    def test_evaluate_protected_runtime_contracts_passes_current_snapshot(self) -> None:
        violations = evaluate_protected_runtime_contracts(module_snapshot())

        self.assertEqual(violations, [])

    def test_evaluate_protected_local_resolvers_passes_current_contracts(self) -> None:
        violations = evaluate_protected_local_resolvers()

        self.assertEqual(violations, [])

    def test_evaluate_protected_source_shell_routes_passes_current_contracts(self) -> None:
        violations = evaluate_protected_source_shell_routes()

        self.assertEqual(violations, [])

    def test_render_text_report_includes_protected_mirror_asset_violations(self) -> None:
        report = {
            "ok": False,
            "audit": {
                "ok": True,
                "allowed_count": 4,
                "actual_count": 4,
                "unexpected_findings": [],
                "missing_allowed_findings": [],
            },
            "runtime_dependency": {
                "ok": False,
                "allowed_count": 4,
                "actual_count": 4,
                "unexpected_findings": [],
                "missing_allowed_findings": [],
                "protected_mirror_asset_violations": [
                    {
                        "slug": "mlb",
                        "description": "live prop ranking predictor",
                        "path": "data/mlb_source/sim_engine/live_prop_ranking.py",
                    },
                    {
                        "slug": "mlb",
                        "description": "daily mirror manifest breadth",
                        "path": "data/mlb_source/manifests/mirror_refresh_latest.json",
                        "missing_prefixes": [
                            "daily\\top_props\\daily_top_props_",
                            "daily\\ops\\daily_ops_",
                            "daily\\snapshots\\",
                            "daily\\sims\\",
                        ],
                    },
                    {
                        "slug": "nba",
                        "description": "live analytics and betting-card mirror breadth",
                        "path": "data/nba_source/manifests/mirror_refresh_latest.json",
                        "missing_prefixes": ["live_lens_signals_", "recon_props_", "season_betting_card_day_"],
                    }
                ],
                "protected_local_resolver_violations": [],
                "protected_source_shell_violations": [],
                "lowest_ownership_modules": [],
            },
            "commands": [],
        }

        rendered = render_text_report(report)

        self.assertIn("Protected mirror asset violations:", rendered)
        self.assertIn("mlb: live prop ranking predictor; path=data/mlb_source/sim_engine/live_prop_ranking.py", rendered)
        self.assertIn(
            "mlb: daily mirror manifest breadth; path=data/mlb_source/manifests/mirror_refresh_latest.json; missing_prefixes=daily\\top_props\\daily_top_props_, daily\\ops\\daily_ops_, daily\\snapshots\\, daily\\sims\\",
            rendered,
        )
        self.assertIn(
            "nba: live analytics and betting-card mirror breadth; path=data/nba_source/manifests/mirror_refresh_latest.json; missing_prefixes=live_lens_signals_, recon_props_, season_betting_card_day_",
            rendered,
        )

    def test_render_text_report_includes_protected_local_resolver_violations(self) -> None:
        report = {
            "ok": False,
            "audit": {
                "ok": True,
                "allowed_count": 5,
                "actual_count": 5,
                "unexpected_findings": [],
                "missing_allowed_findings": [],
            },
            "runtime_dependency": {
                "ok": False,
                "allowed_count": 0,
                "actual_count": 0,
                "unexpected_findings": [],
                "missing_allowed_findings": [],
                "protected_mirror_asset_violations": [],
                "protected_local_resolver_violations": [
                    {
                        "slug": "nfl",
                        "description": "week_summaries ignore sibling snapshots",
                        "issue": "unexpected_result",
                        "expected": [],
                        "actual": [{"season": 2025, "week": 7}],
                    }
                ],
                "protected_source_shell_violations": [],
                "lowest_ownership_modules": [],
            },
            "commands": [],
        }

        rendered = render_text_report(report)

        self.assertIn("Protected local resolver violations:", rendered)
        self.assertIn(
            "nfl: week_summaries ignore sibling snapshots; issue=unexpected_result; expected=[]; actual=[{'season': 2025, 'week': 7}]",
            rendered,
        )

    def test_render_text_report_includes_protected_source_shell_violations(self) -> None:
        report = {
            "ok": False,
            "audit": {
                "ok": True,
                "allowed_count": 5,
                "actual_count": 5,
                "unexpected_findings": [],
                "missing_allowed_findings": [],
            },
            "runtime_dependency": {
                "ok": False,
                "allowed_count": 0,
                "actual_count": 0,
                "unexpected_findings": [],
                "missing_allowed_findings": [],
                "protected_mirror_asset_violations": [],
                "protected_local_resolver_violations": [],
                "protected_source_shell_violations": [
                    {
                        "slug": "mlb",
                        "description": "source cards route keeps standalone Syndicate shell",
                        "path": "/mlb/cards?date=2026-05-20&client=source",
                        "issue": "found_forbidden_substring",
                        "expected": "not present: Syndicate app navigation",
                        "actual": "Syndicate app navigation",
                    }
                ],
                "lowest_ownership_modules": [],
            },
            "commands": [],
        }

        rendered = render_text_report(report)

        self.assertIn("Protected source shell violations:", rendered)
        self.assertIn(
            "mlb: source cards route keeps standalone Syndicate shell; path=/mlb/cards?date=2026-05-20&client=source; issue=found_forbidden_substring; expected=not present: Syndicate app navigation; actual=Syndicate app navigation",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()