from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent


@dataclass(frozen=True)
class RefreshStep:
    name: str
    phases: tuple[str, ...]
    cwd: Path
    command: tuple[str, ...]
    env_updates: dict[str, str] | None = None
    description: str | None = None


@dataclass(frozen=True)
class SportSpec:
    slug: str
    source_repo_name: str
    mirror_script_name: str
    step_builder: Callable[[argparse.Namespace], list[RefreshStep]]
    ingest_contract_kind: str
    ingest_contract_notes: str = ""
    notes: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _source_root_env_var(slug: str) -> str:
    return f"SYNDICATE_SOURCE_ROOT_{slug.upper()}"


def _source_repo_root(slug: str, source_repo_name: str) -> Path:
    override = str(os.environ.get(_source_root_env_var(slug)) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (WORKSPACE_ROOT / source_repo_name).resolve()


def _venv_python(source_root: Path) -> str:
    candidate = source_root / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable or "python"


def _powershell() -> str:
    return "powershell.exe"


def _merge_pythonpath(existing: str | None, extra: str) -> str:
    if existing:
        return extra + os.pathsep + existing
    return extra


def _json_payload(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"))


def _infer_nfl_context(source_root: Path, season: int | None, week: int | None) -> tuple[int, int]:
    if season is not None and week is not None:
        return int(season), int(week)
    current_week_path = source_root / "nfl_compare" / "data" / "current_week.json"
    payload: dict[str, Any] = {}
    if current_week_path.exists():
        try:
            payload = json.loads(current_week_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    resolved_season = int(season if season is not None else payload.get("season") or datetime.now().year)
    resolved_week = int(week if week is not None else payload.get("week") or 1)
    return resolved_season, resolved_week


def _build_mlb_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _source_repo_root("mlb", "MLB-BettingV2")
    python_exe = _venv_python(source_root)
    return [
        RefreshStep(
            name="mlb_oddsapi_markets",
            phases=("pregame", "live"),
            cwd=source_root,
            command=(
                python_exe,
                "-m",
                "tools.oddsapi.fetch_daily_oddsapi_markets",
                "--date",
                args.date,
                "--regions",
                args.regions,
                "--overwrite",
                "on",
            ),
            description="Refresh MLB current-day game lines and props from OddsAPI.",
        ),
        RefreshStep(
            name="mlb_live_lens_report",
            phases=("live",),
            cwd=source_root,
            command=(
                python_exe,
                "-c",
                (
                    "import json; "
                    "from tools.web.flask_frontend import _persist_live_lens_tick; "
                    f"print(json.dumps(_persist_live_lens_tick({args.date!r}, trigger='syndicate_refresh', refresh_markets=False)))"
                ),
            ),
            description="Rebuild the MLB live-lens report after live OddsAPI refresh so mirrored live artifacts stay current.",
        ),
    ]


def _build_nba_payload(args: argparse.Namespace, *, env_key: str) -> dict[str, str]:
    log_dir = _source_repo_root(
        "nba" if env_key == "NBA_BETTING_ODDSAPI_PROPS_JOB" else "wnba",
        "NBA-Betting" if env_key == "NBA_BETTING_ODDSAPI_PROPS_JOB" else "WNBA-Betting",
    ) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"syndicate_refresh_oddsapi_props_{args.date}.log"
    payload = {
        "date_str": args.date,
        "regions": args.regions,
        "bookmakers": str(args.bookmakers or ""),
        "markets": str(args.markets or ""),
        "do_edges": True,
        "do_export": True,
        "do_push": False,
        "started_at": _utc_now(),
        "log_file": str(log_file),
    }
    return {env_key: _json_payload(payload)}


def _build_nba_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _source_repo_root("nba", "NBA-Betting")
    python_exe = _venv_python(source_root)
    env_updates = _build_nba_payload(args, env_key="NBA_BETTING_ODDSAPI_PROPS_JOB")
    env_updates["PYTHONPATH"] = _merge_pythonpath(os.environ.get("PYTHONPATH"), str(source_root / "src"))
    return [
        RefreshStep(
            name="nba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=source_root,
            command=(python_exe, "-m", "nba_betting.refresh_oddsapi_props_job"),
            env_updates=env_updates,
            description="Refresh NBA OddsAPI props snapshot, edges, and recommendations.",
        )
    ]


def _build_wnba_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _source_repo_root("wnba", "WNBA-Betting")
    python_exe = _venv_python(source_root)
    env_updates = _build_nba_payload(args, env_key="WNBA_BETTING_ODDSAPI_PROPS_JOB")
    env_updates["PYTHONPATH"] = _merge_pythonpath(os.environ.get("PYTHONPATH"), str(source_root / "src"))
    return [
        RefreshStep(
            name="wnba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=source_root,
            command=(python_exe, "-m", "wnba_betting.refresh_oddsapi_props_job"),
            env_updates=env_updates,
            description="Refresh WNBA OddsAPI props snapshot, edges, and recommendations.",
        )
    ]


def _build_nhl_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _source_repo_root("nhl", "NHL-Betting")
    python_exe = _venv_python(source_root)
    return [
        RefreshStep(
            name="nhl_team_odds_collect",
            phases=("pregame", "live"),
            cwd=source_root,
            command=(python_exe, "-m", "nhl_betting.cli", "team-odds-collect", "--date", args.date),
            description="Refresh NHL team odds for the selected date.",
        ),
        RefreshStep(
            name="nhl_props_collect",
            phases=("pregame", "live"),
            cwd=source_root,
            command=(python_exe, "-m", "nhl_betting.cli", "props-collect", "--date", args.date, "--source", "oddsapi"),
            description="Refresh NHL player props lines from OddsAPI.",
        ),
    ]


def _build_nfl_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _source_repo_root("nfl", "NFL-Betting")
    season, week = _infer_nfl_context(source_root, args.season, args.week)
    python_exe = _venv_python(source_root)
    out_path = source_root / "nfl_compare" / "data" / f"oddsapi_player_props_{season}_wk{week}.csv"
    return [
        RefreshStep(
            name="nfl_team_odds_snapshot",
            phases=("pregame", "live"),
            cwd=source_root / "nfl_compare",
            command=(python_exe, "-m", "src.odds_api_client"),
            description="Refresh NFL team odds snapshot from OddsAPI.",
        ),
        RefreshStep(
            name="nfl_player_props_snapshot",
            phases=("pregame", "live"),
            cwd=source_root,
            command=(
                python_exe,
                "scripts/fetch_oddsapi_props.py",
                "--season",
                str(season),
                "--week",
                str(week),
                "--out",
                str(out_path),
            ),
            description="Refresh NFL player props snapshot from OddsAPI.",
        ),
    ]


def _build_ncaab_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _source_repo_root("ncaab", "NCAAB")
    python_exe = _venv_python(source_root)
    env_updates = {
        "PYTHONPATH": _merge_pythonpath(os.environ.get("PYTHONPATH"), str(source_root / "src"))
    }
    return [
        RefreshStep(
            name="ncaab_odds_history_snapshot",
            phases=("pregame", "live"),
            cwd=source_root,
            command=(
                python_exe,
                "-m",
                "ncaab_model.cli",
                "fetch-odds-history",
                "--start",
                args.date,
                "--end",
                args.date,
                "--region",
                args.regions,
                "--out-dir",
                str(source_root / "outputs" / "odds_history"),
                "--mode",
                "current",
            ),
            env_updates=env_updates,
            description="Refresh NCAAB current-day odds snapshot with full-game and derivative markets.",
        )
    ]


def _build_ncaaf_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _source_repo_root("ncaaf", "NCAAFCompare")
    python_exe = _venv_python(source_root)
    command = [python_exe, "fetch_2025_lines.py"]
    if args.week is not None:
        command.extend(["--week", str(args.week)])
    return [
        RefreshStep(
            name="ncaaf_lines_snapshot",
            phases=("pregame", "live"),
            cwd=source_root,
            command=tuple(command),
            description="Refresh NCAAF lines snapshot using the existing 2025 lines fetcher.",
        )
    ]


REGISTRY: dict[str, SportSpec] = {
    "mlb": SportSpec(
        slug="mlb",
        source_repo_name="MLB-BettingV2",
        mirror_script_name="refresh_mlb_source_mirror.ps1",
        step_builder=_build_mlb_steps,
        ingest_contract_kind="artifact_bundle_or_existing_mirror",
        ingest_contract_notes="Hosted-safe ingest can rebuild from existing files under data/mlb_source or from a published MLB artifact bundle root via SYNDICATE_ARTIFACT_ROOT_MLB.",
        notes="Uses the canonical current-day OddsAPI market refresh script that writes game lines plus hitter/pitcher props.",
    ),
    "nba": SportSpec(
        slug="nba",
        source_repo_name="NBA-Betting",
        mirror_script_name="refresh_nba_source_mirror.ps1",
        step_builder=_build_nba_steps,
        ingest_contract_kind="existing_mirror_artifacts",
        ingest_contract_notes="Hosted-safe ingest can rebuild the mirror manifest from existing files under data/nba_source.",
        notes="Runs the existing OddsAPI props refresh job with the same env-payload contract the source app and workflows already use.",
    ),
    "nhl": SportSpec(
        slug="nhl",
        source_repo_name="NHL-Betting",
        mirror_script_name="refresh_nhl_source_mirror.ps1",
        step_builder=_build_nhl_steps,
        ingest_contract_kind="artifact_bundle_or_existing_mirror",
        ingest_contract_notes="Hosted-safe ingest can rebuild from existing files under data/nhl_source or from a published NHL artifact bundle root via SYNDICATE_ARTIFACT_ROOT_NHL.",
        notes="Refreshes both team odds and player props using the source CLI instead of a new Syndicate fetcher.",
    ),
    "nfl": SportSpec(
        slug="nfl",
        source_repo_name="NFL-Betting",
        mirror_script_name="refresh_nfl_source_mirror.ps1",
        step_builder=_build_nfl_steps,
        ingest_contract_kind="source_repo_artifacts",
        ingest_contract_notes="Mirror import still expects source-generated weekly artifacts from the sibling NFL repo layout.",
        notes="Uses the source team's JSON odds snapshot plus weekly player-props CSV flow.",
    ),
    "wnba": SportSpec(
        slug="wnba",
        source_repo_name="WNBA-Betting",
        mirror_script_name="refresh_wnba_source_mirror.ps1",
        step_builder=_build_wnba_steps,
        ingest_contract_kind="existing_mirror_artifacts",
        ingest_contract_notes="Hosted-safe ingest can rebuild the mirror manifest from existing files under data/wnba_source.",
        notes="Reuses the WNBA repo's existing OddsAPI props job rather than duplicating the shared NBA logic.",
    ),
    "ncaab": SportSpec(
        slug="ncaab",
        source_repo_name="NCAAB",
        mirror_script_name="refresh_ncaab_source_mirror.ps1",
        step_builder=_build_ncaab_steps,
        ingest_contract_kind="existing_raw_outputs",
        ingest_contract_notes="Hosted-safe ingest can rebuild the local API bundle from the mirrored raw bundle under data/ncaab_source/raw_outputs.",
        notes="Uses the existing TheOddsAPI adapter through the source CLI so period markets keep the same event-level fetch behavior.",
    ),
    "ncaaf": SportSpec(
        slug="ncaaf",
        source_repo_name="NCAAFCompare",
        mirror_script_name="refresh_ncaaf_source_mirror.ps1",
        step_builder=_build_ncaaf_steps,
        ingest_contract_kind="source_repo_artifacts",
        ingest_contract_notes="Mirror import still expects source-generated artifacts from the sibling NCAAF repo layout.",
        notes="Uses the existing NCAAF lines fetcher that merges provider lines into the source CSV used by the app.",
    ),
}


def _ingest_is_hosted_safe(spec: SportSpec) -> bool:
    return spec.ingest_contract_kind in {"existing_mirror_artifacts", "existing_raw_outputs", "artifact_bundle_or_existing_mirror"}


def _generation_payload(spec: SportSpec, *, execution_mode: str, source_root: Path) -> dict[str, Any]:
    return {
        "kind": "source_repo" if execution_mode == "source" else "none",
        "source_dependency": "source_repo" if execution_mode == "source" else "none",
        "hosted_safe": execution_mode != "source",
        "source_repo": str(source_root),
        "steps": [],
    }


def _ingestion_payload(spec: SportSpec, *, skip_mirror: bool, execution_mode: str) -> dict[str, Any] | None:
    if skip_mirror:
        return None
    return {
        "kind": "mirror_script",
        "source_dependency": "local_artifacts" if execution_mode == "ingest" and _ingest_is_hosted_safe(spec) else "source_repo_artifacts",
        "hosted_safe": execution_mode == "ingest" and _ingest_is_hosted_safe(spec),
        "contract": {
            "kind": spec.ingest_contract_kind,
            "notes": spec.ingest_contract_notes,
        },
        "step": None,
    }


def _parse_sports(raw: str) -> list[str]:
    cleaned = [part.strip().lower() for part in str(raw or "all").split(",") if part.strip()]
    if not cleaned or cleaned == ["all"]:
        return list(REGISTRY.keys())
    unknown = [sport for sport in cleaned if sport not in REGISTRY]
    if unknown:
        raise ValueError(f"Unknown sport(s): {', '.join(sorted(unknown))}")
    return cleaned


def _resolve_execution_mode(raw: str | None, *, mirror_only: bool = False) -> str:
    if mirror_only:
        return "ingest"
    value = str(raw or "source").strip().lower()
    if value in {"source", "ingest"}:
        return value
    raise ValueError("execution_mode must be 'source' or 'ingest'.")


def _run_command(step: RefreshStep, *, dry_run: bool = False) -> dict[str, Any]:
    env = os.environ.copy()
    if step.env_updates:
        env.update({key: value for key, value in step.env_updates.items() if value is not None})
    started = _utc_now()
    if dry_run:
        return {
            "name": step.name,
            "description": step.description,
            "cwd": str(step.cwd),
            "command": list(step.command),
            "return_code": 0,
            "started_at": started,
            "finished_at": started,
            "stdout": "",
            "stderr": "",
            "ok": True,
            "dry_run": True,
        }
    result = subprocess.run(
        list(step.command),
        cwd=str(step.cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    finished = _utc_now()
    return {
        "name": step.name,
        "description": step.description,
        "cwd": str(step.cwd),
        "command": list(step.command),
        "return_code": int(result.returncode),
        "started_at": started,
        "finished_at": finished,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ok": result.returncode == 0,
        "dry_run": False,
    }


def _validate_source_root(spec: SportSpec) -> str | None:
    source_root = _source_repo_root(spec.slug, spec.source_repo_name)
    if source_root.exists():
        return None
    env_var = _source_root_env_var(spec.slug)
    return (
        f"Source repo root not found for {spec.slug}: {source_root}. "
        f"Set {env_var} to an absolute path for this sport or use --execution-mode ingest / --mirror-only."
    )


def _mirror_command(script_name: str, *, date: str, sport: str | None = None, mirror_only: bool = False) -> RefreshStep:
    command = [_powershell(), "-ExecutionPolicy", "Bypass", "-File", str(REPO_ROOT / "scripts" / script_name)]
    if script_name not in {"refresh_nfl_source_mirror.ps1", "refresh_ncaaf_source_mirror.ps1"}:
        command.extend(["-Date", date])
    if sport == "mlb":
        artifact_root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_MLB") or "").strip()
        if artifact_root:
            command.extend(["-SourceArtifactRoot", artifact_root])
    if sport == "nhl":
        artifact_root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
        if artifact_root:
            command.extend(["-SourceArtifactRoot", artifact_root])
    if mirror_only and sport == "ncaab":
        command.append("-UseExistingRawOutputs")
    if mirror_only and sport == "mlb":
        command.append("-UseExistingMirrorArtifacts")
    if mirror_only and sport == "nba":
        command.append("-UseExistingMirrorArtifacts")
    if mirror_only and sport == "nhl":
        command.append("-UseExistingMirrorArtifacts")
    if mirror_only and sport == "wnba":
        command.append("-UseExistingMirrorArtifacts")
    return RefreshStep(
        name=script_name.replace(".ps1", ""),
        phases=("pregame", "live", "all"),
        cwd=REPO_ROOT,
        command=tuple(command),
        description="Mirror refreshed source artifacts into Syndicate.",
    )


def _filter_steps(steps: Sequence[RefreshStep], phase: str) -> list[RefreshStep]:
    if phase == "all":
        return list(steps)
    return [step for step in steps if phase in step.phases]


def _build_summary(args: argparse.Namespace) -> dict[str, Any]:
    selected = _parse_sports(args.sports)
    execution_mode = _resolve_execution_mode(getattr(args, "execution_mode", None), mirror_only=bool(args.mirror_only))
    summary: dict[str, Any] = {
        "date": args.date,
        "phase": args.phase,
        "sports": selected,
        "skip_mirror": bool(args.skip_mirror),
        "mirror_only": execution_mode == "ingest",
        "execution_mode": execution_mode,
        "dry_run": bool(args.dry_run),
        "results": [],
        "started_at": _utc_now(),
    }

    any_failure = False
    for sport in selected:
        spec = REGISTRY[sport]
        source_root = _source_repo_root(spec.slug, spec.source_repo_name)
        sport_result: dict[str, Any] = {
            "sport": sport,
            "source_repo": str(source_root),
            "source_root_env_var": _source_root_env_var(spec.slug),
            "notes": spec.notes,
            "generation_mode": "source_repo" if execution_mode == "source" else "none",
            "ingestion_mode": None if args.skip_mirror else "mirror_script",
            "generation": _generation_payload(spec, execution_mode=execution_mode, source_root=source_root),
            "ingestion": _ingestion_payload(spec, skip_mirror=bool(args.skip_mirror), execution_mode=execution_mode),
            "refresh_steps": [],
            "mirror": None,
            "ok": True,
        }

        refresh_steps = [] if execution_mode == "ingest" else _filter_steps(spec.step_builder(args), args.phase)
        if refresh_steps:
            source_error = _validate_source_root(spec)
            if source_error is not None:
                any_failure = True
                sport_result["ok"] = False
                sport_result["error"] = source_error
                summary["results"].append(sport_result)
                if not args.continue_on_error:
                    summary["finished_at"] = _utc_now()
                    summary["ok"] = False
                    return summary
                continue

        for step in refresh_steps:
            step_result = _run_command(step, dry_run=bool(args.dry_run))
            sport_result["refresh_steps"].append(step_result)
            sport_result["generation"]["steps"].append(step_result)
            if not step_result["ok"]:
                any_failure = True
                sport_result["ok"] = False
                if not args.continue_on_error:
                    summary["results"].append(sport_result)
                    summary["finished_at"] = _utc_now()
                    summary["ok"] = False
                    return summary

        if not args.skip_mirror and (execution_mode == "ingest" or sport_result["ok"]):
            mirror_result = _run_command(
                _mirror_command(
                    spec.mirror_script_name,
                    date=args.date,
                    sport=spec.slug,
                    mirror_only=execution_mode == "ingest",
                ),
                dry_run=bool(args.dry_run),
            )
            sport_result["mirror"] = mirror_result
            if isinstance(sport_result.get("ingestion"), dict):
                sport_result["ingestion"]["step"] = mirror_result
            if not mirror_result["ok"]:
                any_failure = True
                sport_result["ok"] = False
                if not args.continue_on_error:
                    summary["results"].append(sport_result)
                    summary["finished_at"] = _utc_now()
                    summary["ok"] = False
                    return summary

        summary["results"].append(sport_result)

    summary["finished_at"] = _utc_now()
    summary["ok"] = not any_failure
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh pregame/live odds in the source sport repos, then optionally mirror the refreshed artifacts into Syndicate.",
    )
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Target date (YYYY-MM-DD) for date-based sports.")
    parser.add_argument("--sports", default="all", help="Comma-separated sport slugs or 'all'.")
    parser.add_argument("--phase", choices=("pregame", "live", "all"), default="all")
    parser.add_argument("--regions", default="us", help="Odds regions forwarded to source refresh commands where supported.")
    parser.add_argument("--bookmakers", default="", help="Optional bookmaker filter forwarded to source refresh commands where supported.")
    parser.add_argument("--markets", default="", help="Optional market filter forwarded to source refresh commands where supported.")
    parser.add_argument("--season", type=int, default=None, help="Optional season override for weekly sports like NFL.")
    parser.add_argument("--week", type=int, default=None, help="Optional week override for weekly sports like NFL/NCAAF.")
    parser.add_argument("--skip-mirror", action="store_true", help="Refresh source repos only; do not run the Syndicate mirror scripts.")
    parser.add_argument("--execution-mode", choices=("source", "ingest"), default="source", help="Choose whether to run source-owned refresh generation or ingest-only mirror/import steps.")
    parser.add_argument("--mirror-only", action="store_true", help="Skip source refresh and only run the Syndicate mirror scripts.")
    parser.add_argument("--continue-on-error", action="store_true", default=True, help="Continue across sports even when one refresh fails.")
    parser.add_argument("--no-continue-on-error", action="store_false", dest="continue_on_error")
    parser.add_argument("--dry-run", action="store_true", help="Resolve commands and source roots without executing refresh or mirror steps.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    parser.add_argument("--list", action="store_true", help="List supported sports and exit.")
    args = parser.parse_args()

    if args.list:
        payload = {
            "sports": [
                {
                    "sport": spec.slug,
                    "source_repo": spec.source_repo_name,
                    "source_root_env_var": _source_root_env_var(spec.slug),
                    "mirror_script": spec.mirror_script_name,
                    "notes": spec.notes,
                }
                for spec in REGISTRY.values()
            ]
        }
        print(json.dumps(payload, indent=2))
        return 0

    try:
        summary = _build_summary(args)
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(payload, indent=2))
        return 1

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for sport_result in summary.get("results", []):
            sport = sport_result["sport"]
            status = "ok" if sport_result.get("ok") else "failed"
            print(f"[{sport}] {status}")
            if sport_result.get("error"):
                print(f"  - error: {sport_result['error']}")
            for step_result in sport_result.get("refresh_steps", []):
                marker = "dry-run" if step_result.get("dry_run") else ("ok" if step_result.get("ok") else "failed")
                print(f"  - refresh {step_result['name']}: {marker}")
            mirror = sport_result.get("mirror")
            if isinstance(mirror, dict):
                marker = "dry-run" if mirror.get("dry_run") else ("ok" if mirror.get("ok") else "failed")
                print(f"  - mirror: {marker}")

    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())