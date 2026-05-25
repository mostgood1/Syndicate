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


def _load_local_fetchers():
    odds_module = importlib.import_module("scripts.fetch_nfl_team_odds_local")
    props_module = importlib.import_module("scripts.fetch_nfl_oddsapi_props_local")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NFL OddsAPI artifacts through a Syndicate-owned runner.")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--artifact-root", default=str(REPO_ROOT / "data" / "nfl_source" / "source_artifacts"))
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    artifact_root = Path(args.artifact_root).resolve()
    source_data_root = source_root / "nfl_compare" / "data"
    props_out = source_data_root / f"oddsapi_player_props_{int(args.season)}_wk{int(args.week)}.csv"

    try:
        odds_module, props_module = _load_local_fetchers()
        odds_module.main(data_dir=source_data_root)
        with _pushd(source_root):
            props_rc = props_module.main([
                "--season",
                str(int(args.season)),
                "--week",
                str(int(args.week)),
                "--out",
                str(props_out),
            ])
        if int(props_rc or 0) != 0:
            print(json.dumps({"ok": False, "error": f"fetch_oddsapi_props exited with {props_rc}"}, indent=2))
            return int(props_rc or 1)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    copied = _materialize_artifact_bundle(source_data_root=source_data_root, artifact_root=artifact_root)
    print(json.dumps({"ok": True, "season": int(args.season), "week": int(args.week), "artifact_bundle_root": str(artifact_root), "artifact_bundle_files": copied}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())