from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from typing import Sequence
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALLOWED_AUDIT_FINDINGS = (
    {
        "category": "source_shell_route",
        "path": "syndicate/blueprints/mlb.py",
        "line": 291,
    },
    {
        "category": "source_shell_route",
        "path": "syndicate/blueprints/nba.py",
        "line": 140,
    },
    {
        "category": "source_shell_route",
        "path": "syndicate/blueprints/nhl.py",
        "line": 234,
    },
    {
        "category": "source_shell_route",
        "path": "syndicate/blueprints/wnba.py",
        "line": 243,
    },
)

ALLOWED_RUNTIME_DEPENDENCY_FINDINGS = (
)

PROTECTED_RUNTIME_CONTRACTS = (
    {
        "slug": "mlb",
        "dependency_tier": "owned_local",
        "ownership_goal": "full_local",
        "ownership_score_min": 100,
        "fallback_surfaces": (),
        "parity_gap_count": 0,
    },
    {
        "slug": "nba",
        "dependency_tier": "artifact_backed",
        "ownership_goal": "mirror_first",
        "ownership_score_min": 85,
        "fallback_surfaces": (),
        "parity_gap_count": 0,
    },
    {
        "slug": "nhl",
        "dependency_tier": "artifact_backed",
        "ownership_goal": "mirror_first",
        "ownership_score_min": 85,
        "fallback_surfaces": (),
        "parity_gap_count": 0,
    },
    {
        "slug": "nfl",
        "dependency_tier": "artifact_backed",
        "ownership_goal": "artifact_backed",
        "ownership_score_min": 85,
        "fallback_surfaces": (),
        "parity_gap_count": 0,
    },
    {
        "slug": "wnba",
        "dependency_tier": "artifact_backed",
        "ownership_goal": "mirror_first",
        "ownership_score_min": 85,
        "fallback_surfaces": (),
        "parity_gap_count": 0,
    },
    {
        "slug": "ncaaf",
        "dependency_tier": "artifact_backed",
        "ownership_goal": "artifact_backed",
        "ownership_score_min": 85,
        "fallback_surfaces": (),
        "parity_gap_count": 0,
    },
    {
        "slug": "ncaab",
        "dependency_tier": "artifact_backed",
        "ownership_goal": "mirror_first",
        "ownership_score_min": 85,
        "fallback_surfaces": (),
        "parity_gap_count": 0,
    },
)

PROTECTED_MIRROR_ASSETS = (
    {
        "slug": "mlb",
        "description": "live prop ranking config",
        "path": "data/mlb_source/data/tuning/live_prop_ranking/default.json",
    },
    {
        "slug": "mlb",
        "description": "live prop ranking predictor",
        "path": "data/mlb_source/sim_engine/live_prop_ranking.py",
    },
    {
        "slug": "mlb",
        "description": "daily mirror manifest breadth",
        "path": "data/mlb_source/manifests/mirror_refresh_latest.json",
        "required_artifact_prefixes": (
            "daily\\daily_summary_",
            "daily\\ladders\\daily_ladders_",
            "daily\\top_props\\daily_top_props_",
            "daily\\ops\\daily_ops_",
            "daily\\snapshots\\",
            "daily\\sims\\",
            "eval\\seasons\\",
        ),
    },
    {
        "slug": "nba",
        "description": "live analytics and betting-card mirror breadth",
        "path": "data/nba_source/manifests/mirror_refresh_latest.json",
        "required_artifact_prefixes": (
            "live_lens_projections_",
            "live_lens_signals_",
            "live_snapshots\\live_state_",
            "recon_games_",
            "recon_props_",
            "season_betting_card_manifest_",
            "season_betting_card_day_",
        ),
    },
)

PROTECTED_LOCAL_RESOLVER_CHECKS = (
    {"slug": "mlb", "description": "daily artifact path stays on local mirror"},
    {"slug": "mlb", "description": "daily summary dates ignore sibling artifacts"},
    {"slug": "mlb", "description": "raw feed path stays on local mirror"},
    {"slug": "wnba", "description": "processed_path stays on local mirror"},
    {"slug": "wnba", "description": "live snapshot path stays on local mirror"},
    {"slug": "wnba", "description": "available_dates ignore sibling artifacts"},
    {"slug": "ncaaf", "description": "data_path stays on local mirror"},
    {"slug": "ncaab", "description": "mirror_path stays on local mirror"},
    {"slug": "nfl", "description": "data_path stays on local mirror"},
    {"slug": "nfl", "description": "week_summaries ignore sibling snapshots"},
    {"slug": "nba", "description": "processed_path stays on local mirror"},
    {"slug": "nba", "description": "available_dates ignore sibling artifacts"},
    {"slug": "nhl", "description": "processed_path stays on local mirror"},
    {"slug": "nhl", "description": "scoreboard snapshot stays on local mirror"},
    {"slug": "nhl", "description": "slate summaries ignore sibling artifacts"},
)

PROTECTED_SOURCE_SHELL_CHECKS = (
    {
        "slug": "mlb",
        "description": "source cards route keeps standalone Syndicate shell",
        "path": "/mlb/cards?date=2026-05-20&client=source",
        "required_substrings": ("mlb/cards_source.js", "<title>MLB Game Cards — 2026-05-20</title>"),
        "forbidden_substrings": ("Syndicate app navigation", "Module navigation"),
    },
    {
        "slug": "nba",
        "description": "source cards route uses local versioned Syndicate assets",
        "path": "/nba/cards?date=2026-05-14",
        "required_substrings": ("/static/nba/cards_source.css?v=", "/static/nba/cards_source.js?v="),
        "forbidden_substrings": (),
    },
    {
        "slug": "nhl",
        "description": "source cards route keeps local date-scoped Syndicate links",
        "path": "/nhl/cards?date=2026-05-14",
        "required_substrings": ("/nhl/reconciliation?date=", "setDateScopedHref('bettingRecapLink', bettingRecapBasePath, d);"),
        "forbidden_substrings": (),
    },
    {
        "slug": "wnba",
        "description": "source cards alias preserves explicit local parity shell",
        "path": "/wnba/cards/source?date=2026-05-21",
        "required_substrings": ("/wnba/cards-parity.js", "WNBA Game Cards"),
        "forbidden_substrings": (),
        "follow_redirects": True,
    },
)


@dataclass
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Syndicate migration gate: audit, regression tests, and browser parity smoke.",
    )
    parser.add_argument(
        "--base-url",
        help="Reuse an already-running Syndicate server for the browser smoke step.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip the unittest regression step.",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip the browser smoke step.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the final gate report as JSON.",
    )
    parser.add_argument(
        "--write-dir",
        type=Path,
        help="Optional output directory for persisted migration gate reports.",
    )
    return parser.parse_args(argv)


def write_reports(report: dict[str, object], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "migration_gate_report.json"
    text_path = output_dir / "migration_gate_report.txt"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    text_path.write_text(render_text_report(report), encoding="utf-8")
    return {
        "json": str(json_path.relative_to(ROOT)),
        "text": str(text_path.relative_to(ROOT)),
    }


def run_command(name: str, command: list[str]) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return CommandResult(
        name=name,
        command=command,
        returncode=int(completed.returncode),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def normalize_audit_findings(payload: object) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        findings.append(
            {
                "category": item.get("category"),
                "path": item.get("path"),
                "line": item.get("line"),
                "summary": item.get("summary"),
            }
        )
    return findings


def normalize_runtime_dependency_findings(payload: object) -> list[dict[str, object]]:
    gap_summary = payload.get("gap_summary") if isinstance(payload, dict) else {}
    findings: list[dict[str, object]] = []
    for item in gap_summary.get("modules_ranked_by_ownership") if isinstance(gap_summary, dict) else []:
        if not isinstance(item, dict):
            continue
        fallback_surfaces = tuple(str(value).strip() for value in (item.get("fallback_surfaces") or []) if str(value).strip())
        if not fallback_surfaces:
            continue
        findings.append(
            {
                "slug": str(item.get("slug") or "").strip(),
                "dependency_tier": str(item.get("dependency_tier") or "").strip(),
                "fallback_surfaces": fallback_surfaces,
                "ownership_score": item.get("ownership_score"),
            }
        )
    return findings


def summarize_command_output(output: str, limit: int = 600) -> str:
    text = "\n".join(line.rstrip() for line in output.strip().splitlines() if line.strip())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def audit_finding_identity(item: dict[str, object]) -> tuple[object, ...]:
    category = str(item.get("category") or "").strip()
    path = str(item.get("path") or "").strip()
    if category == "source_shell_route":
        return (category, path)
    return (category, path, item.get("line"))


def evaluate_runtime_dependency_findings(findings: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    allowed_set = {
        (
            str(item["slug"]),
            str(item["dependency_tier"]),
            tuple(str(value) for value in item["fallback_surfaces"]),
        )
        for item in ALLOWED_RUNTIME_DEPENDENCY_FINDINGS
    }
    actual_set = {
        (
            str(item.get("slug") or ""),
            str(item.get("dependency_tier") or ""),
            tuple(str(value) for value in (item.get("fallback_surfaces") or ())),
        )
        for item in findings
    }
    unexpected_findings = [
        item
        for item in findings
        if (
            str(item.get("slug") or ""),
            str(item.get("dependency_tier") or ""),
            tuple(str(value) for value in (item.get("fallback_surfaces") or ())),
        )
        not in allowed_set
    ]
    missing_allowed_findings = [
        item
        for item in ALLOWED_RUNTIME_DEPENDENCY_FINDINGS
        if (
            str(item["slug"]),
            str(item["dependency_tier"]),
            tuple(str(value) for value in item["fallback_surfaces"]),
        )
        not in actual_set
    ]
    return unexpected_findings, missing_allowed_findings


def evaluate_protected_runtime_contracts(payload: object) -> list[dict[str, object]]:
    modules = payload.get("modules") if isinstance(payload, dict) else []
    module_map = {
        str(item.get("slug") or "").strip(): item
        for item in modules
        if isinstance(item, dict) and str(item.get("slug") or "").strip()
    }
    violations: list[dict[str, object]] = []
    for expected in PROTECTED_RUNTIME_CONTRACTS:
        slug = str(expected["slug"])
        module = module_map.get(slug)
        if not isinstance(module, dict):
            violations.append({
                "slug": slug,
                "issue": "missing_module",
                "expected": dict(expected),
            })
            continue
        runtime_contract = module.get("runtime_contract") if isinstance(module.get("runtime_contract"), dict) else {}
        contract_alignment = module.get("contract_alignment") if isinstance(module.get("contract_alignment"), dict) else {}
        fallback_surfaces = tuple(str(value).strip() for value in (runtime_contract.get("fallback_surfaces") or []) if str(value).strip())
        actual = {
            "dependency_tier": str(runtime_contract.get("dependency_tier") or "").strip(),
            "ownership_goal": str(runtime_contract.get("ownership_goal") or "").strip(),
            "ownership_score": int(runtime_contract.get("ownership_score") or 0),
            "fallback_surfaces": fallback_surfaces,
            "parity_gap_count": int(contract_alignment.get("parity_gap_count") or 0),
        }
        if actual["dependency_tier"] != str(expected["dependency_tier"]):
            violations.append({"slug": slug, "field": "dependency_tier", "expected": expected["dependency_tier"], "actual": actual["dependency_tier"]})
        if actual["ownership_goal"] != str(expected["ownership_goal"]):
            violations.append({"slug": slug, "field": "ownership_goal", "expected": expected["ownership_goal"], "actual": actual["ownership_goal"]})
        if actual["ownership_score"] < int(expected["ownership_score_min"]):
            violations.append({"slug": slug, "field": "ownership_score", "expected_min": expected["ownership_score_min"], "actual": actual["ownership_score"]})
        if actual["fallback_surfaces"] != tuple(str(value) for value in expected["fallback_surfaces"]):
            violations.append({"slug": slug, "field": "fallback_surfaces", "expected": tuple(str(value) for value in expected["fallback_surfaces"]), "actual": actual["fallback_surfaces"]})
        if actual["parity_gap_count"] != int(expected["parity_gap_count"]):
            violations.append({"slug": slug, "field": "parity_gap_count", "expected": expected["parity_gap_count"], "actual": actual["parity_gap_count"]})
    return violations


def evaluate_protected_mirror_assets(root: Path | None = None) -> list[dict[str, object]]:
    repo_root = (root or ROOT).resolve()
    violations: list[dict[str, object]] = []
    for expected in PROTECTED_MIRROR_ASSETS:
        relative_path = Path(str(expected["path"]))
        asset_path = repo_root / relative_path
        if not asset_path.exists() or not asset_path.is_file():
            violations.append(
                {
                    "slug": str(expected["slug"]),
                    "description": str(expected["description"]),
                    "path": relative_path.as_posix(),
                    "issue": "missing_asset",
                }
            )
            continue

        required_prefixes = tuple(str(value).strip() for value in (expected.get("required_artifact_prefixes") or ()) if str(value).strip())
        if not required_prefixes:
            continue

        try:
            manifest_payload = json.loads(asset_path.read_text(encoding="utf-8-sig"))
        except Exception:
            violations.append(
                {
                    "slug": str(expected["slug"]),
                    "description": str(expected["description"]),
                    "path": relative_path.as_posix(),
                    "issue": "invalid_manifest",
                }
            )
            continue

        copied_artifacts = manifest_payload.get("copiedArtifacts") if isinstance(manifest_payload, dict) else []
        copied_artifacts = [str(value).strip() for value in copied_artifacts if str(value).strip()]
        missing_prefixes = [
            prefix
            for prefix in required_prefixes
            if not any(artifact.startswith(prefix) for artifact in copied_artifacts)
        ]
        if missing_prefixes:
            violations.append(
                {
                    "slug": str(expected["slug"]),
                    "description": str(expected["description"]),
                    "path": relative_path.as_posix(),
                    "issue": "missing_manifest_artifacts",
                    "missing_prefixes": missing_prefixes,
                }
            )
    return violations


def evaluate_protected_local_resolvers() -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []

    def _append_violation(slug: str, description: str, *, expected: object, actual: object, issue: str = "unexpected_result") -> None:
        violations.append(
            {
                "slug": slug,
                "description": description,
                "issue": issue,
                "expected": expected,
                "actual": actual,
            }
        )

    try:
        from syndicate.features.mlb.sources import available_daily_summary_dates as mlb_available_daily_summary_dates
        from syndicate.features.mlb.sources import daily_artifact_path as mlb_daily_artifact_path
        from syndicate.features.mlb.sources import raw_feed_live_path as mlb_raw_feed_live_path

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "mlb_source"
            sibling_root = root / "MLB-BettingV2"
            sibling_daily = sibling_root / "data" / "daily" / "daily_summary_2026_05_17.json"
            sibling_feed = sibling_root / "data" / "raw" / "statsapi" / "feed_live" / "2026" / "2026-05-17" / "123.json"
            sibling_daily.parent.mkdir(parents=True, exist_ok=True)
            sibling_feed.parent.mkdir(parents=True, exist_ok=True)
            sibling_daily.write_text("{}", encoding="utf-8")
            sibling_feed.write_text("{}", encoding="utf-8")
            expected_daily = local_root / "data" / "daily" / "daily_summary_2026_05_17.json"
            with patch("syndicate.features.mlb.sources._source_roots", return_value=[local_root, sibling_root]):
                actual_daily = mlb_daily_artifact_path("2026-05-17")
                actual_dates = mlb_available_daily_summary_dates()
                actual_feed = mlb_raw_feed_live_path("2026-05-17", 123)
            if Path(actual_daily) != expected_daily:
                _append_violation("mlb", "daily artifact path stays on local mirror", expected=str(expected_daily), actual=str(actual_daily))
            if actual_dates != []:
                _append_violation("mlb", "daily summary dates ignore sibling artifacts", expected=[], actual=actual_dates)
            if actual_feed is not None:
                _append_violation("mlb", "raw feed path stays on local mirror", expected=None, actual=str(actual_feed))
    except Exception as error:
        _append_violation("mlb", "local resolver contracts", expected="no exceptions", actual=repr(error), issue="exception")

    try:
        from syndicate.features.wnba.sources import available_dates as wnba_available_dates
        from syndicate.features.wnba.sources import live_snapshot_path as wnba_live_snapshot_path
        from syndicate.features.wnba.sources import processed_path as wnba_processed_path

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "wnba_source"
            sibling_root = root / "WNBA-Betting"
            sibling_processed = sibling_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            sibling_snapshot = sibling_root / "data" / "processed" / "live_snapshots" / "live_state_2026-05-17.json"
            sibling_processed.parent.mkdir(parents=True, exist_ok=True)
            sibling_snapshot.parent.mkdir(parents=True, exist_ok=True)
            sibling_processed.write_text("x", encoding="utf-8")
            sibling_snapshot.write_text("x", encoding="utf-8")
            expected_processed = local_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            expected_snapshot = local_root / "data" / "processed" / "live_snapshots" / "live_state_2026-05-17.json"
            with patch("syndicate.features.wnba.sources._source_roots", return_value=[local_root, sibling_root]):
                actual_processed = wnba_processed_path("game_cards_2026-05-17.csv")
                actual_snapshot = wnba_live_snapshot_path("live_state_2026-05-17.json")
                actual_dates = wnba_available_dates()
            if Path(actual_processed) != expected_processed:
                _append_violation("wnba", "processed_path stays on local mirror", expected=str(expected_processed), actual=str(actual_processed))
            if Path(actual_snapshot) != expected_snapshot:
                _append_violation("wnba", "live snapshot path stays on local mirror", expected=str(expected_snapshot), actual=str(actual_snapshot))
            if actual_dates != []:
                _append_violation("wnba", "available_dates ignore sibling artifacts", expected=[], actual=actual_dates)
    except Exception as error:
        _append_violation("wnba", "local resolver contracts", expected="no exceptions", actual=repr(error), issue="exception")

    try:
        from syndicate.features.ncaaf.sources import data_path as ncaaf_data_path

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "ncaaf_source"
            sibling_root = root / "NCAAFCompare"
            sibling_file = sibling_root / "data" / "recommendations_summary" / "index.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")
            expected = local_root / "data" / "recommendations_summary" / "index.json"
            with patch("syndicate.features.ncaaf.sources._source_roots", return_value=[local_root, sibling_root]):
                actual = ncaaf_data_path("recommendations_summary", "index.json")
            if Path(actual) != expected:
                _append_violation("ncaaf", "data_path stays on local mirror", expected=str(expected), actual=str(actual))
    except Exception as error:
        _append_violation("ncaaf", "data_path stays on local mirror", expected="local mirror path", actual=repr(error), issue="exception")

    try:
        from syndicate.features.ncaab.sources import _mirror_path as ncaab_mirror_path

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "ncaab_source"
            sibling_root = root / "NCAAB"
            sibling_file = sibling_root / "api" / "display_prediction_dates.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")
            expected = local_root / "api" / "display_prediction_dates.json"
            with patch("syndicate.features.ncaab.sources._source_roots", return_value=[local_root, sibling_root]):
                actual = ncaab_mirror_path("display_prediction_dates.json")
            if Path(actual) != expected:
                _append_violation("ncaab", "mirror_path stays on local mirror", expected=str(expected), actual=str(actual))
    except Exception as error:
        _append_violation("ncaab", "mirror_path stays on local mirror", expected="local mirror path", actual=repr(error), issue="exception")

    try:
        from syndicate.features.nfl.sources import data_path as nfl_data_path
        from syndicate.features.nfl.sources import week_summaries as nfl_week_summaries

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nfl_source"
            sibling_root = root / "NFL-Betting" / "nfl_compare" / "data"
            sibling_file = sibling_root / "current_week.json"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("{}", encoding="utf-8")
            expected = local_root / "current_week.json"
            with patch("syndicate.features.nfl.sources._source_roots", return_value=[local_root, sibling_root]):
                actual = nfl_data_path("current_week.json")
            if Path(actual) != expected:
                _append_violation("nfl", "data_path stays on local mirror", expected=str(expected), actual=str(actual))

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nfl_source"
            sibling_root = root / "NFL-Betting" / "nfl_compare" / "data"
            sibling_file = sibling_root / "upcoming_recs_2025_wk7.csv"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("col\nvalue\n", encoding="utf-8")
            with patch("syndicate.features.nfl.sources._source_roots", return_value=[local_root, sibling_root]):
                actual = nfl_week_summaries()
            if actual != []:
                _append_violation("nfl", "week_summaries ignore sibling snapshots", expected=[], actual=actual)
    except Exception as error:
        _append_violation("nfl", "local resolver contracts", expected="no exceptions", actual=repr(error), issue="exception")

    try:
        from syndicate.features.nba.sources import available_dates as nba_available_dates
        from syndicate.features.nba.sources import processed_path as nba_processed_path

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nba_source"
            sibling_root = root / "NBA-Betting"
            sibling_file = sibling_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            sibling_file.parent.mkdir(parents=True, exist_ok=True)
            sibling_file.write_text("x", encoding="utf-8")
            expected = local_root / "data" / "processed" / "game_cards_2026-05-17.csv"
            with patch("syndicate.features.nba.sources.preferred_source_roots", return_value=[local_root, sibling_root]):
                actual_path = nba_processed_path("game_cards_2026-05-17.csv")
                actual_dates = nba_available_dates()
            if Path(actual_path) != expected:
                _append_violation("nba", "processed_path stays on local mirror", expected=str(expected), actual=str(actual_path))
            if actual_dates != []:
                _append_violation("nba", "available_dates ignore sibling artifacts", expected=[], actual=actual_dates)
    except Exception as error:
        _append_violation("nba", "local resolver contracts", expected="no exceptions", actual=repr(error), issue="exception")

    try:
        from syndicate.features.nhl.sources import processed_path as nhl_processed_path
        from syndicate.features.nhl.sources import scoreboard_snapshot_path as nhl_scoreboard_snapshot_path
        from syndicate.features.nhl.sources import slate_summaries as nhl_slate_summaries

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_root = root / "data" / "nhl_source"
            sibling_root = root / "NHL-Betting"
            sibling_processed = sibling_root / "data" / "processed" / "recommendations_2026-05-17.csv"
            sibling_scoreboard = sibling_root / "data" / "odds" / "games" / "date=2026-05-17" / "scoreboard.csv"
            sibling_processed.parent.mkdir(parents=True, exist_ok=True)
            sibling_scoreboard.parent.mkdir(parents=True, exist_ok=True)
            sibling_processed.write_text("x", encoding="utf-8")
            sibling_scoreboard.write_text("x", encoding="utf-8")
            expected_processed = local_root / "data" / "processed" / "recommendations_2026-05-17.csv"
            expected_scoreboard = local_root / "data" / "odds" / "games" / "date=2026-05-17" / "scoreboard.csv"
            with patch("syndicate.features.nhl.sources._source_roots", return_value=[local_root, sibling_root]):
                actual_processed = nhl_processed_path("recommendations_2026-05-17.csv")
                actual_scoreboard = nhl_scoreboard_snapshot_path("2026-05-17")
                actual_slates = nhl_slate_summaries()
            if Path(actual_processed) != expected_processed:
                _append_violation("nhl", "processed_path stays on local mirror", expected=str(expected_processed), actual=str(actual_processed))
            if Path(actual_scoreboard) != expected_scoreboard:
                _append_violation("nhl", "scoreboard snapshot stays on local mirror", expected=str(expected_scoreboard), actual=str(actual_scoreboard))
            if actual_slates != []:
                _append_violation("nhl", "slate summaries ignore sibling artifacts", expected=[], actual=actual_slates)
    except Exception as error:
        _append_violation("nhl", "local resolver contracts", expected="no exceptions", actual=repr(error), issue="exception")

    return violations


def evaluate_protected_source_shell_routes() -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []

    try:
        from syndicate.app import create_app
    except Exception as error:
        return [
            {
                "slug": "source_shell",
                "description": "load Syndicate app for source shell checks",
                "issue": "exception",
                "expected": "import syndicate.app.create_app",
                "actual": repr(error),
            }
        ]

    app = create_app()
    client = app.test_client()
    for expected in PROTECTED_SOURCE_SHELL_CHECKS:
        path = str(expected["path"])
        response = client.get(path, follow_redirects=bool(expected.get("follow_redirects")))
        body = response.get_data(as_text=True)
        if response.status_code != 200:
            violations.append(
                {
                    "slug": str(expected["slug"]),
                    "description": str(expected["description"]),
                    "path": path,
                    "issue": "unexpected_status",
                    "expected": 200,
                    "actual": response.status_code,
                }
            )
            continue
        for required in expected.get("required_substrings") or ():
            if str(required) not in body:
                violations.append(
                    {
                        "slug": str(expected["slug"]),
                        "description": str(expected["description"]),
                        "path": path,
                        "issue": "missing_required_substring",
                        "expected": str(required),
                        "actual": "absent",
                    }
                )
        for forbidden in expected.get("forbidden_substrings") or ():
            if str(forbidden) in body:
                violations.append(
                    {
                        "slug": str(expected["slug"]),
                        "description": str(expected["description"]),
                        "path": path,
                        "issue": "found_forbidden_substring",
                        "expected": f"not present: {forbidden}",
                        "actual": str(forbidden),
                    }
                )
    return violations


def render_text_report(report: dict[str, object]) -> str:
    lines: list[str] = []
    overall = "PASS" if report.get("ok") else "FAIL"
    lines.append(f"Migration gate: {overall}")
    lines.append("")

    audit = report.get("audit") or {}
    audit_status = "PASS" if audit.get("ok") else "FAIL"
    lines.append(f"Audit: {audit_status}")
    lines.append(f"  Allowed findings: {audit.get('allowed_count', 0)}")
    lines.append(f"  Actual findings: {audit.get('actual_count', 0)}")
    if audit.get("unexpected_findings"):
        lines.append("  Unexpected findings:")
        for finding in audit.get("unexpected_findings") or []:
            path = finding.get("path") or "<unknown>"
            line = finding.get("line")
            category = finding.get("category") or "unknown"
            suffix = f":{line}" if line else ""
            lines.append(f"    - {category} {path}{suffix}")
    if audit.get("missing_allowed_findings"):
        lines.append("  Missing previously-allowed findings:")
        for finding in audit.get("missing_allowed_findings") or []:
            path = finding.get("path") or "<unknown>"
            line = finding.get("line")
            category = finding.get("category") or "unknown"
            suffix = f":{line}" if line else ""
            lines.append(f"    - {category} {path}{suffix}")
    lines.append("")

    runtime_dependency = report.get("runtime_dependency") or {}
    runtime_status = "PASS" if runtime_dependency.get("ok") else "FAIL"
    lines.append(f"Runtime dependency: {runtime_status}")
    lines.append(f"  Allowed findings: {runtime_dependency.get('allowed_count', 0)}")
    lines.append(f"  Actual findings: {runtime_dependency.get('actual_count', 0)}")
    if runtime_dependency.get("unexpected_findings"):
        lines.append("  Unexpected findings:")
        for finding in runtime_dependency.get("unexpected_findings") or []:
            slug = finding.get("slug") or "<unknown>"
            tier = finding.get("dependency_tier") or "unknown"
            surfaces = ", ".join(finding.get("fallback_surfaces") or []) or "none"
            lines.append(f"    - {slug} ({tier}) -> {surfaces}")
    if runtime_dependency.get("missing_allowed_findings"):
        lines.append("  Missing previously-allowed findings:")
        for finding in runtime_dependency.get("missing_allowed_findings") or []:
            slug = finding.get("slug") or "<unknown>"
            tier = finding.get("dependency_tier") or "unknown"
            surfaces = ", ".join(finding.get("fallback_surfaces") or []) or "none"
            lines.append(f"    - {slug} ({tier}) -> {surfaces}")
    if runtime_dependency.get("protected_contract_violations"):
        lines.append("  Protected contract violations:")
        for violation in runtime_dependency.get("protected_contract_violations") or []:
            slug = violation.get("slug") or "<unknown>"
            field = violation.get("field") or violation.get("issue") or "unknown"
            expected = violation.get("expected", violation.get("expected_min", "-"))
            actual = violation.get("actual", "-")
            lines.append(f"    - {slug}: {field}; expected={expected}; actual={actual}")
    if runtime_dependency.get("protected_mirror_asset_violations"):
        lines.append("  Protected mirror asset violations:")
        for violation in runtime_dependency.get("protected_mirror_asset_violations") or []:
            slug = violation.get("slug") or "<unknown>"
            description = violation.get("description") or "unknown asset"
            path = violation.get("path") or "<unknown>"
            detail = f"{slug}: {description}; path={path}"
            missing_prefixes = violation.get("missing_prefixes") or []
            if missing_prefixes:
                detail += f"; missing_prefixes={', '.join(str(value) for value in missing_prefixes)}"
            lines.append(f"    - {detail}")
    if runtime_dependency.get("protected_local_resolver_violations"):
        lines.append("  Protected local resolver violations:")
        for violation in runtime_dependency.get("protected_local_resolver_violations") or []:
            slug = violation.get("slug") or "<unknown>"
            description = violation.get("description") or "unknown resolver"
            issue = violation.get("issue") or "unexpected_result"
            expected = violation.get("expected", "-")
            actual = violation.get("actual", "-")
            lines.append(f"    - {slug}: {description}; issue={issue}; expected={expected}; actual={actual}")
    if runtime_dependency.get("protected_source_shell_violations"):
        lines.append("  Protected source shell violations:")
        for violation in runtime_dependency.get("protected_source_shell_violations") or []:
            slug = violation.get("slug") or "<unknown>"
            description = violation.get("description") or "unknown source shell"
            path = violation.get("path") or "<unknown>"
            issue = violation.get("issue") or "unexpected_result"
            expected = violation.get("expected", "-")
            actual = violation.get("actual", "-")
            lines.append(f"    - {slug}: {description}; path={path}; issue={issue}; expected={expected}; actual={actual}")
    lowest = runtime_dependency.get("lowest_ownership_modules") or []
    if lowest:
        lines.append("  Lowest ownership modules:")
        for item in lowest:
            slug = item.get("slug") or "<unknown>"
            score = item.get("ownership_score")
            tier = item.get("dependency_tier") or "unknown"
            lines.append(f"    - {slug}: score={score}; tier={tier}")
    lines.append("")

    for command in report.get("commands") or []:
        status = "PASS" if command.get("ok") else "FAIL"
        lines.append(f"{command.get('name')}: {status}")
        lines.append(f"  Command: {' '.join(command.get('command') or [])}")
        snippet = command.get("stdout_excerpt") or command.get("stderr_excerpt")
        if snippet:
            lines.append(f"  Output: {snippet}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    command_results: list[CommandResult] = []
    audit_result = run_command("audit", [sys.executable, "scripts/audit_migration.py", "--format", "json"])
    command_results.append(audit_result)

    findings_payload: object = []
    audit_parse_error: str | None = None
    if audit_result.ok:
        try:
            findings_payload = json.loads(audit_result.stdout)
        except json.JSONDecodeError as error:
            audit_parse_error = str(error)
    else:
        audit_parse_error = "audit command failed"

    normalized_findings = normalize_audit_findings(findings_payload)
    allowed_set = {audit_finding_identity(item) for item in ALLOWED_AUDIT_FINDINGS}
    actual_set = {audit_finding_identity(item) for item in normalized_findings}
    unexpected_findings = [
        item for item in normalized_findings if audit_finding_identity(item) not in allowed_set
    ]
    missing_allowed_findings = [
        item for item in ALLOWED_AUDIT_FINDINGS if audit_finding_identity(item) not in actual_set
    ]
    audit_ok = bool(audit_result.ok and audit_parse_error is None and not unexpected_findings and not missing_allowed_findings)

    module_tracker_result = run_command("module_tracker", [sys.executable, "scripts/module_tracker_snapshot.py", "--json"])
    command_results.append(module_tracker_result)

    module_tracker_payload: object = {}
    module_tracker_parse_error: str | None = None
    if module_tracker_result.ok:
        try:
            module_tracker_payload = json.loads(module_tracker_result.stdout)
        except json.JSONDecodeError as error:
            module_tracker_parse_error = str(error)
    else:
        module_tracker_parse_error = "module tracker command failed"

    runtime_dependency_findings = normalize_runtime_dependency_findings(module_tracker_payload)
    runtime_unexpected_findings, runtime_missing_allowed_findings = evaluate_runtime_dependency_findings(runtime_dependency_findings)
    protected_contract_violations = evaluate_protected_runtime_contracts(module_tracker_payload)
    protected_mirror_asset_violations = evaluate_protected_mirror_assets()
    protected_local_resolver_violations = evaluate_protected_local_resolvers()
    protected_source_shell_violations = evaluate_protected_source_shell_routes()
    runtime_dependency_summary = (
        module_tracker_payload.get("gap_summary") if isinstance(module_tracker_payload, dict) else {}
    )
    runtime_dependency_ok = bool(
        module_tracker_result.ok
        and module_tracker_parse_error is None
        and not runtime_unexpected_findings
        and not runtime_missing_allowed_findings
        and not protected_contract_violations
        and not protected_mirror_asset_violations
        and not protected_local_resolver_violations
        and not protected_source_shell_violations
    )

    if not args.skip_tests:
        command_results.append(run_command("tests", [sys.executable, "-m", "unittest", "tests.test_archives"]))

    if not args.skip_smoke:
        smoke_command = [sys.executable, "scripts/browser_parity_smoke.py"]
        if args.base_url:
            smoke_command.extend(["--base-url", args.base_url])
        command_results.append(run_command("browser_smoke", smoke_command))

    report = {
        "ok": audit_ok and runtime_dependency_ok and all(result.ok for result in command_results if result.name not in {"audit", "module_tracker"}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit": {
            "ok": audit_ok,
            "parse_error": audit_parse_error,
            "allowed_count": len(ALLOWED_AUDIT_FINDINGS),
            "actual_count": len(normalized_findings),
            "unexpected_findings": unexpected_findings,
            "missing_allowed_findings": missing_allowed_findings,
        },
        "runtime_dependency": {
            "ok": runtime_dependency_ok,
            "parse_error": module_tracker_parse_error,
            "allowed_count": len(ALLOWED_RUNTIME_DEPENDENCY_FINDINGS),
            "actual_count": len(runtime_dependency_findings),
            "unexpected_findings": runtime_unexpected_findings,
            "missing_allowed_findings": runtime_missing_allowed_findings,
            "protected_contract_count": len(PROTECTED_RUNTIME_CONTRACTS),
            "protected_contract_violations": protected_contract_violations,
            "protected_mirror_asset_count": len(PROTECTED_MIRROR_ASSETS),
            "protected_mirror_asset_violations": protected_mirror_asset_violations,
            "protected_local_resolver_count": len(PROTECTED_LOCAL_RESOLVER_CHECKS),
            "protected_local_resolver_violations": protected_local_resolver_violations,
            "protected_source_shell_count": len(PROTECTED_SOURCE_SHELL_CHECKS),
            "protected_source_shell_violations": protected_source_shell_violations,
            "lowest_ownership_modules": runtime_dependency_summary.get("lowest_ownership_modules") or [],
        },
        "commands": [
            {
                "name": result.name,
                "command": result.command,
                "ok": result.ok,
                "returncode": result.returncode,
                "stdout_excerpt": summarize_command_output(result.stdout),
                "stderr_excerpt": summarize_command_output(result.stderr),
            }
            for result in command_results
        ],
    }

    if args.write_dir:
        output_dir = args.write_dir if args.write_dir.is_absolute() else ROOT / args.write_dir
        report["written_reports"] = write_reports(report, output_dir)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text_report(report), end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())