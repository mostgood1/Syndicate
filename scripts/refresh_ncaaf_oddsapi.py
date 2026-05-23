from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

ROOT_FILES = (
    "recommendations_latest.json",
    "recommendations_2025.csv",
    "college_football_betting_lines_2025.csv",
)

DIRECTORIES = (
    "recommendations_summary",
)


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _copy_tree_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_dir():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return True


def _load_source_module(source_root: Path):
    module_path = source_root / "fetch_2025_lines.py"
    spec = importlib.util.spec_from_file_location("ncaaf_fetch_2025_lines", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load source module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    previous = sys.argv[:]
    sys.argv = args
    try:
        yield
    finally:
        sys.argv = previous


def _materialize_artifact_bundle(*, source_root: Path, artifact_root: Path) -> dict[str, object]:
    source_data_root = source_root / "data"
    copied: dict[str, object] = {}

    for name in ROOT_FILES:
        source = source_data_root / name
        destination = artifact_root / name
        if _copy_if_exists(source, destination):
            copied.setdefault("files", []).append(str(destination))

    for name in DIRECTORIES:
        source = source_data_root / name
        destination = artifact_root / name
        if _copy_tree_if_exists(source, destination):
            copied.setdefault("directories", []).append(str(destination))

    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NCAAF OddsAPI lines through a Syndicate-owned runner.")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--artifact-root", required=False, default=str(REPO_ROOT / "data" / "ncaaf_source" / "source_artifacts"))
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    artifact_root = Path(args.artifact_root).resolve()
    source_module = _load_source_module(source_root)

    runner_argv = ["fetch_2025_lines.py"]
    if args.week is not None:
        runner_argv.extend(["--week", str(args.week)])
    if args.debug:
        runner_argv.append("--debug")

    try:
        with _pushd(source_root), _argv(runner_argv):
            rc = source_module.main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    if rc not in (None, 0):
        print(json.dumps({"ok": False, "return_code": int(rc)}))
        return int(rc)

    copied = _materialize_artifact_bundle(source_root=source_root, artifact_root=artifact_root)
    print(
        json.dumps(
            {
                "ok": True,
                "week": args.week,
                "artifact_bundle_root": str(artifact_root),
                "artifact_bundle_files": copied,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())