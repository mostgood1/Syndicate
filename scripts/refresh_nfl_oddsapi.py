from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"

STATIC_FILES = (
    "current_week.json",
    "calibration_active.json",
    "prob_calibration.json",
    "sigma_calibration.json",
    "totals_calibration.json",
)

GLOB_PATTERNS = (
    "upcoming_recs_*.csv",
    "real_betting_lines_*.json",
    "oddsapi_player_props_*.csv",
)

DIRECTORIES = (
    "manifests",
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_local_fetchers():
    scripts_root_text = str(SCRIPTS_ROOT.resolve())
    if scripts_root_text not in sys.path:
        sys.path.insert(0, scripts_root_text)
    importlib.invalidate_caches()
    odds_module = importlib.import_module("fetch_nfl_team_odds_local")
    props_module = importlib.import_module("fetch_nfl_oddsapi_props_local")
    return odds_module, props_module


def _copy_if_exists(*, source: Path, destination: Path, recurse: bool = False) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.resolve() == destination.resolve():
            return True
    except Exception:
        pass
    if recurse:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return True

@contextmanager
def _pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextmanager
def _argv(args: list[str]):
    previous = list(sys.argv)
    sys.argv = args
    try:
        yield
    finally:
        sys.argv = previous


def _materialize_artifact_bundle(*, source_data_root: Path, artifact_root: Path) -> dict[str, object]:
    copied: dict[str, object] = {}

    for name in STATIC_FILES:
        source = source_data_root / name
        destination = artifact_root / name
        if _copy_if_exists(source=source, destination=destination):
            copied.setdefault("static_files", []).append(str(destination))

    for pattern in GLOB_PATTERNS:
        for source in sorted(source_data_root.glob(pattern)):
            destination = artifact_root / source.name
            if _copy_if_exists(source=source, destination=destination):
                copied.setdefault("globbed_files", []).append(str(destination))

    for name in DIRECTORIES:
        source = source_data_root / name
        destination = artifact_root / name
        if _copy_if_exists(source=source, destination=destination, recurse=True):
            copied.setdefault("directories", []).append(str(destination))

    return copied


def _resolve_source_data_root(*, source_root: str | None, artifact_root: Path) -> Path:
    if source_root:
        return Path(source_root).resolve() / "nfl_compare" / "data"
    return artifact_root


def _resolve_context(*, source_data_root: Path, season: int | None, week: int | None) -> tuple[int, int]:
    from datetime import datetime

    current_week_path = source_data_root / "current_week.json"
    payload: dict[str, object] = {}
    if current_week_path.exists():
        try:
            payload = json.loads(current_week_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    resolved_season = int(season if season is not None else payload.get("season") or payload.get("current_season") or datetime.now().year)
    resolved_week = int(week if week is not None else payload.get("week") or payload.get("current_week") or 1)
    return resolved_season, resolved_week


def _ensure_current_week_file(*, source_data_root: Path, season: int, week: int) -> None:
    _write_json(
        source_data_root / "current_week.json",
        {
            "season": int(season),
            "week": int(week),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NFL OddsAPI artifacts through a Syndicate-owned runner.")
    parser.add_argument("--source-root", required=False)
    parser.add_argument("--artifact-root", default=str(REPO_ROOT / "data" / "nfl_source" / "source_artifacts"))
    parser.add_argument("--season", type=int, required=False)
    parser.add_argument("--week", type=int, required=False)
    args = parser.parse_args()

    artifact_root = Path(args.artifact_root).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    source_data_root = _resolve_source_data_root(source_root=args.source_root, artifact_root=artifact_root)
    source_data_root.mkdir(parents=True, exist_ok=True)
    season, week = _resolve_context(source_data_root=source_data_root, season=args.season, week=args.week)
    _ensure_current_week_file(source_data_root=source_data_root, season=season, week=week)
    props_out = source_data_root / f"oddsapi_player_props_{int(season)}_wk{int(week)}.csv"

    try:
        odds_module, props_module = _load_local_fetchers()
        odds_module.main(data_dir=source_data_root)
        props_argv = [
            "--season",
            str(int(season)),
            "--week",
            str(int(week)),
            "--out",
            str(props_out),
        ]
        if args.source_root:
            with _pushd(Path(args.source_root).resolve()):
                props_rc = props_module.main(props_argv)
        else:
            props_rc = props_module.main(props_argv)
        if int(props_rc or 0) != 0:
            print(json.dumps({"ok": False, "error": f"fetch_oddsapi_props exited with {props_rc}"}, indent=2))
            return int(props_rc or 1)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    copied = _materialize_artifact_bundle(source_data_root=source_data_root, artifact_root=artifact_root)
    print(json.dumps({"ok": True, "season": int(season), "week": int(week), "artifact_bundle_root": str(artifact_root), "artifact_bundle_files": copied}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())