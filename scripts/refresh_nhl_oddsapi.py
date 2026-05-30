from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import sys
import subprocess
import pandas as pd
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROCESSED_FILES = (
    "predictions_{date}.csv",
    "predictions_sim_{date}.csv",
    "recommendations_{date}.csv",
    "recommendations_sim_{date}.csv",
    "reconciliations_log.csv",
    "props_reconciliations_log.csv",
    "recon_games_{date}.csv",
    "recon_props_{date}.csv",
    "props_projections_all_{date}.csv",
    "props_boxscores_sim_{date}.csv",
    "props_boxscores_sim_hist_{date}.csv",
    "props_boxscores_sim_samples_{date}.csv",
    "props_recommendations_{date}.csv",
    "roster_snapshot_{date}.csv",
    "injuries_{date}.csv",
    "lineups_{date}.csv",
    "lineups_co_toi_{date}.csv",
    "shifts_{date}.csv",
    "co_toi_shifts_{date}.csv",
    "starting_goalies_{date}.csv",
)

LIVE_LENS_FILES = (
    "live_lens_projections_{date}.jsonl",
    "live_lens_signals_{date}.jsonl",
    "live_lens_tuning_override.json",
)


REQUIRED_ARTIFACTS = (
    "data/processed/predictions_sim_{date}.csv",
    "data/processed/recommendations_sim_{date}.csv",
    "data/processed/props_projections_all_{date}.csv",
    "data/processed/props_boxscores_sim_{date}.csv",
    "data/processed/props_boxscores_sim_hist_{date}.csv",
    "data/processed/props_recommendations_{date}.csv",
    "data/processed/roster_snapshot_{date}.csv",
    "data/processed/lineups_{date}.csv",
    "data/odds/games/date={date}/scoreboard.csv",
    "data/odds/team/date={date}/oddsapi.csv",
    "data/props/player_props_lines/date={date}/oddsapi.csv",
)


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    try:
        if source.resolve() == destination.resolve():
            return True
    except Exception:
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_file_with_fallback(source, destination)
    return True


def _copy_file_with_fallback(source: Path, destination: Path) -> None:
    try:
        shutil.copy2(source, destination)
        return
    except OSError as exc:
        if exc.errno != errno.EINVAL:
            raise
    source_fd = os.open(str(source), os.O_RDONLY)
    try:
        destination_fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        try:
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                os.write(destination_fd, chunk)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)
    try:
        shutil.copystat(source, destination)
    except OSError:
        pass


def _copy_first_existing(*, sources: list[Path], destination: Path) -> bool:
    for source in sources:
        if _copy_if_exists(source, destination):
            return True
    return False


def _collect_owned_nhl_artifacts(*, artifact_root: Path, date_str: str, team_markets: str, props_source: str) -> dict[str, object]:
    from syndicate.local_nhl_odds import collect_and_write_player_props, collect_and_write_team_odds, write_scoreboard_snapshot

    copied: dict[str, object] = {}
    scoreboard_path = write_scoreboard_snapshot(artifact_root=artifact_root, date=date_str)
    copied["scoreboard_path"] = str(scoreboard_path)
    team_result = collect_and_write_team_odds(artifact_root=artifact_root, date=date_str, markets=team_markets)
    copied["team_odds_paths"] = [path for path in [team_result.get("csv_path"), team_result.get("parquet_path")] if path]
    props_result = collect_and_write_player_props(artifact_root=artifact_root, date=date_str, source=props_source)
    props_output = str(props_result.get("output_path") or "").strip()
    if props_output:
        csv_path = str(Path(props_output).with_suffix(".csv"))
        parquet_path = str(Path(props_output).with_suffix(".parquet"))
        copied["props_line_paths"] = [path for path in [csv_path, parquet_path] if Path(path).exists()]
    return copied


def _source_python_executable(source_root: Path) -> str:
    override = str(os.environ.get("SYNDICATE_PYTHON_EXE") or "").strip()
    if override and Path(override).exists() and "windowsapps" not in override.lower():
        return override
    if sys.executable and Path(sys.executable).exists() and "windowsapps" not in str(sys.executable).lower():
        return sys.executable
    for installed in (
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311-arm64" / "python.exe",
    ):
        if installed.exists():
            return str(installed)
    candidate = source_root / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _default_source_root() -> Path | None:
    candidate = REPO_ROOT / "vendor" / "nhl_betting_repo"
    cli_path = candidate / "nhl_betting" / "cli.py"
    if cli_path.exists() and cli_path.is_file():
        return candidate
    return None


def _source_data_root(source_root: Path) -> Path:
    return source_root / "data"


def _run_source_cli(*, source_root: Path, artifact_root: Path, command_args: list[str]) -> None:
    env = os.environ.copy()
    data_dir = _source_data_root(source_root)
    data_dir.mkdir(parents=True, exist_ok=True)
    env["NHL_DATA_DIR"] = str(data_dir)
    env["DATA_DIR"] = str(data_dir)
    print(json.dumps({"phase": "source_cli", "command": command_args}))
    completed = subprocess.run(
        [_source_python_executable(source_root), "-m", "nhl_betting.cli", *command_args],
        cwd=str(source_root),
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Source NHL CLI failed for {' '.join(command_args)} with exit code {completed.returncode}: {completed.stderr.strip() or completed.stdout.strip()}"
        )


def _run_source_generation(*, source_root: Path, artifact_root: Path, date_str: str, props_boxscore_n_sims: int) -> None:
    _run_source_generation_multi(source_root=source_root, artifact_root=artifact_root, date_str=date_str, props_boxscore_n_sims=props_boxscore_n_sims, days_ahead=0)


def _date_window(*, date_str: str, days_ahead: int) -> list[str]:
    parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
    return [(parsed + timedelta(days=offset)).isoformat() for offset in range(0, max(0, int(days_ahead)) + 1)]


def _run_source_generation_multi(*, source_root: Path, artifact_root: Path, date_str: str, props_boxscore_n_sims: int, days_ahead: int) -> None:
    target_dates = _date_window(date_str=date_str, days_ahead=days_ahead)
    for index, target_date in enumerate(target_dates):
        pregame_batches = [
            ["roster-update", "--date", target_date],
            ["lineup-update", "--date", target_date, "--prefer-source", "none"],
            ["team-odds-collect", "--date", target_date],
            ["props-collect", "--date", target_date],
            ["props-project-all", "--date", target_date],
        ]
        if index == 0:
            pregame_batches.insert(2, ["shifts-update", "--date", target_date])
            pregame_batches.insert(3, ["injury-update", "--date", target_date])
        for command_args in pregame_batches:
            _run_source_cli(source_root=source_root, artifact_root=artifact_root, command_args=command_args)
        if index == 0:
            for command_args in (
                ["props-simulate-boxscores", "--date", target_date, "--n-sims", str(int(props_boxscore_n_sims))],
                ["props-recommendations-boxscores", "--date", target_date],
                ["props-recommendations", "--date", target_date, "--min-ev", "0.0", "--top", "200"],
                ["game-recommendations-sim", "--date", target_date],
            ):
                _run_source_cli(source_root=source_root, artifact_root=artifact_root, command_args=command_args)


@contextmanager
def _pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _materialize_artifact_bundle(*, source_root: Path | None, artifact_root: Path, date_str: str) -> dict[str, object]:
    processed_root = artifact_root / "data" / "processed"
    live_lens_root = artifact_root / "data" / "live_lens"
    odds_games_root = artifact_root / "data" / "odds" / "games" / f"date={date_str}"
    odds_team_root = artifact_root / "data" / "odds" / "team" / f"date={date_str}"
    props_root = artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}"

    copied: dict[str, object] = {}

    scoreboard_destination = odds_games_root / "scoreboard.csv"
    if scoreboard_destination.exists() and scoreboard_destination.is_file():
        copied["scoreboard_path"] = str(scoreboard_destination)

    team_paths = [str(path) for path in (odds_team_root / "oddsapi.csv", odds_team_root / "oddsapi.parquet") if path.exists()]
    if team_paths:
        copied["team_odds_paths"] = team_paths

    props_paths = [str(path) for path in (props_root / "oddsapi.csv", props_root / "oddsapi.parquet") if path.exists()]
    if props_paths:
        copied["props_line_paths"] = props_paths

    source_roots = [artifact_root]
    if source_root is not None:
        source_roots.append(source_root)

    for template in PROCESSED_FILES:
        filename = template.format(date=date_str)
        destination = processed_root / filename
        for candidate_root in source_roots:
            source = candidate_root / "data" / "processed" / filename
            if _copy_if_exists(source, destination):
                copied.setdefault("processed_files", []).append(str(destination))
                break

    for template in LIVE_LENS_FILES:
        filename = template.format(date=date_str)
        processed_destination = processed_root / filename
        live_lens_destination = live_lens_root / filename
        for candidate_root in source_roots:
            sources = [
                candidate_root / "data" / "processed" / filename,
                candidate_root / "data" / "processed" / "live_lens" / filename,
                candidate_root / "data" / "live_lens" / filename,
            ]
            if _copy_first_existing(sources=sources, destination=processed_destination):
                copied.setdefault("live_lens_processed_files", []).append(str(processed_destination))
                break
        for candidate_root in source_roots:
            sources = [
                candidate_root / "data" / "processed" / filename,
                candidate_root / "data" / "processed" / "live_lens" / filename,
                candidate_root / "data" / "live_lens" / filename,
            ]
            if _copy_first_existing(sources=sources, destination=live_lens_destination):
                copied.setdefault("live_lens_files", []).append(str(live_lens_destination))
                break

    for name in ("oddsapi.csv", "oddsapi.parquet"):
        team_destination = odds_team_root / name
        for candidate_root in source_roots:
            team_source = candidate_root / "data" / "odds" / "team" / f"date={date_str}" / name
            if _copy_if_exists(team_source, team_destination):
                copied["team_odds_paths"] = [str(path) for path in (odds_team_root / "oddsapi.csv", odds_team_root / "oddsapi.parquet") if path.exists()]
                break

        props_destination = props_root / name
        for candidate_root in source_roots:
            props_source = candidate_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / name
            if _copy_if_exists(props_source, props_destination):
                copied["props_line_paths"] = [str(path) for path in (props_root / "oddsapi.csv", props_root / "oddsapi.parquet") if path.exists()]
                break

    return copied


def _missing_required_artifacts(*, artifact_root: Path, date_str: str) -> list[str]:
    missing: list[str] = []
    for template in REQUIRED_ARTIFACTS:
        rel_path = template.format(date=date_str)
        full_path = artifact_root / rel_path
        if not full_path.exists():
            missing.append(rel_path)
    return missing


def _required_artifacts_by_date(*, artifact_root: Path, date_values: list[str]) -> dict[str, list[str]]:
    missing_by_date: dict[str, list[str]] = {}
    for date_value in date_values:
        missing = _missing_required_artifacts(artifact_root=artifact_root, date_str=date_value)
        if missing:
            missing_by_date[str(date_value)] = list(missing)
    return missing_by_date


def _lineup_quality_issues(*, artifact_root: Path, date_str: str) -> list[str]:
    lineups_path = artifact_root / "data" / "processed" / f"lineups_{date_str}.csv"
    if not lineups_path.exists() or not lineups_path.is_file():
        return [f"missing lineup snapshot: {lineups_path}"]
    try:
        df = pd.read_csv(lineups_path)
    except Exception as exc:
        return [f"unable to read lineup snapshot {lineups_path}: {exc}"]
    if df is None or df.empty:
        return [f"empty lineup snapshot: {lineups_path}"]
    if "proj_toi" not in df.columns:
        return [f"lineup snapshot missing proj_toi: {lineups_path}"]

    issues: list[str] = []
    skaters = df.copy()
    if "position" in skaters.columns:
        skaters = skaters[~skaters["position"].astype(str).str.upper().str.startswith("G")].copy()
    toi = pd.to_numeric(skaters["proj_toi"], errors="coerce") if not skaters.empty else pd.Series(dtype=float)
    confidence = pd.to_numeric(skaters["confidence"], errors="coerce") if "confidence" in skaters.columns and not skaters.empty else pd.Series(dtype=float)
    if not skaters.empty:
        uniform_placeholder_toi = toi.notna().all() and toi.nunique(dropna=True) == 1 and abs(float(toi.iloc[0]) - 15.0) < 1e-9
        uniform_placeholder_confidence = confidence.notna().all() and confidence.nunique(dropna=True) == 1 and abs(float(confidence.iloc[0]) - 0.5) < 1e-9
        if uniform_placeholder_toi and uniform_placeholder_confidence:
            issues.append(f"placeholder skater TOI detected in {lineups_path}")
    return issues


def _source_cli_generation_enabled() -> bool:
    value = str(os.environ.get("SYNDICATE_NHL_SOURCE_CLI_GENERATION") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NHL OddsAPI snapshots through a Syndicate-owned runner.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-root")
    parser.add_argument("--artifact-root", required=False, default=str(REPO_ROOT / "data" / "nhl_source" / "source_artifacts"))
    parser.add_argument("--team-markets", default="h2h,spreads,totals")
    parser.add_argument("--props-source", default="oddsapi")
    parser.add_argument("--props-boxscore-n-sims", type=int, default=1000)
    parser.add_argument("--days-ahead", type=int, default=0)
    args = parser.parse_args()

    default_source_root = _default_source_root()
    source_root = Path(args.source_root).resolve() if args.source_root else default_source_root
    artifact_root = Path(args.artifact_root).resolve()
    target_dates = _date_window(date_str=args.date, days_ahead=int(args.days_ahead or 0))
    warnings: list[str] = []

    try:
        for target_date in target_dates:
            _collect_owned_nhl_artifacts(
                artifact_root=artifact_root,
                date_str=target_date,
                team_markets=str(args.team_markets or "h2h,spreads,totals"),
                props_source=str(args.props_source or "oddsapi"),
            )
        if source_root is not None and _source_cli_generation_enabled():
            try:
                _run_source_generation_multi(
                    source_root=source_root,
                    artifact_root=artifact_root,
                    date_str=args.date,
                    props_boxscore_n_sims=int(args.props_boxscore_n_sims),
                    days_ahead=int(args.days_ahead or 0),
                )
            except Exception as exc:
                missing_by_date = _required_artifacts_by_date(artifact_root=artifact_root, date_values=target_dates)
                if missing_by_date:
                    raise
                warnings.append(f"source generation skipped: {exc}")
        elif source_root is not None:
            warnings.append("source generation disabled by default (set SYNDICATE_NHL_SOURCE_CLI_GENERATION=1 to enable)")
    except Exception as exc:
        print(json.dumps({"ok": False, "date": args.date, "error": str(exc)}))
        return 1

    copied = _materialize_artifact_bundle(source_root=source_root, artifact_root=artifact_root, date_str=args.date)
    missing_required = _missing_required_artifacts(artifact_root=artifact_root, date_str=args.date)
    if missing_required:
        print(
            json.dumps(
                {
                    "ok": False,
                    "date": args.date,
                    "artifact_bundle_root": str(artifact_root),
                    "error": "missing_required_artifacts",
                    "missing_required_artifacts": missing_required,
                },
                indent=2,
            )
        )
        return 1
    lineup_quality_issues = _lineup_quality_issues(artifact_root=artifact_root, date_str=args.date)
    if lineup_quality_issues:
        print(
            json.dumps(
                {
                    "ok": False,
                    "date": args.date,
                    "artifact_bundle_root": str(artifact_root),
                    "error": "placeholder_lineup_artifacts",
                    "lineup_quality_issues": lineup_quality_issues,
                },
                indent=2,
            )
        )
        return 1
    lookahead_runs = []
    for target_date in _date_window(date_str=args.date, days_ahead=int(args.days_ahead or 0))[1:]:
        lookahead_runs.append(
            {
                "date": target_date,
                "artifact_bundle_files": _materialize_artifact_bundle(source_root=source_root, artifact_root=artifact_root, date_str=target_date),
            }
        )
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "artifact_bundle_root": str(artifact_root),
                "artifact_bundle_files": copied,
                "lookahead_runs": lookahead_runs,
                "required_artifacts": [template.format(date=args.date) for template in REQUIRED_ARTIFACTS],
                "warnings": warnings,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())