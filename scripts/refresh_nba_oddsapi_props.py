from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _json_ready(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _copy_if_exists(source_path: str | None, destination_path: Path) -> bool:
    source_text = str(source_path or "").strip()
    if not source_text:
        return False
    source = Path(source_text)
    if not source.exists() or not source.is_file():
        return False
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination_path)
    return True


def _copy_matching_files(*, source_directory: Path, pattern: str, destination_directory: Path) -> list[str]:
    if not source_directory.exists() or not source_directory.is_dir():
        return []
    copied: list[str] = []
    for source in sorted(source_directory.glob(pattern)):
        if not source.is_file():
            continue
        destination = destination_directory / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(str(destination))
    return copied


def _processed_source_directory(state: dict[str, object]) -> Path | None:
    for key in ("snapshot_alias_path", "predictions_path", "edges_path", "recs_path"):
        source_text = str(state.get(key) or "").strip()
        if not source_text:
            continue
        source = Path(source_text)
        if source.exists():
            return source.resolve().parent
    return None


def _materialize_artifact_bundle(*, state: dict[str, object], artifact_root: Path) -> dict[str, str]:
    processed_root = artifact_root / "data" / "processed"
    raw_root = artifact_root / "data" / "raw"
    copied: dict[str, str] = {}
    artifact_map = {
        "snapshot_alias_path": processed_root / Path(str(state.get("snapshot_alias_path") or "")).name,
        "predictions_path": processed_root / Path(str(state.get("predictions_path") or "")).name,
        "edges_path": processed_root / Path(str(state.get("edges_path") or "")).name,
        "recs_path": processed_root / Path(str(state.get("recs_path") or "")).name,
        "snapshot_path": raw_root / Path(str(state.get("snapshot_path") or "")).name,
    }
    for key, destination in artifact_map.items():
        if _copy_if_exists(str(state.get(key) or ""), destination):
            copied[key] = str(destination)
    date_text = str(state.get("date") or "").strip()
    source_directory = _processed_source_directory(state)
    if date_text and source_directory is not None:
        smart_sim_files = _copy_matching_files(
            source_directory=source_directory,
            pattern=f"smart_sim_{date_text}_*.json",
            destination_directory=processed_root,
        )
        if smart_sim_files:
            copied["smart_sim_paths"] = smart_sim_files
    return copied


def _load_source_module(source_root: Path):
    src_root = source_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    return importlib.import_module("nba_betting.refresh_oddsapi_props_job")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NBA OddsAPI props refresh job through a Syndicate-owned entrypoint.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--regions", default="us")
    parser.add_argument("--bookmakers", default="")
    parser.add_argument("--markets", default="")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--artifact-root")
    parser.add_argument("--do-edges", action="store_true")
    parser.add_argument("--do-export", action="store_true")
    parser.add_argument("--do-push", action="store_true")
    parser.add_argument("--started-at")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    source_module = _load_source_module(source_root)
    state = source_module.run_refresh_oddsapi_props_job(
        date_str=args.date,
        regions=args.regions,
        bookmakers=args.bookmakers,
        markets=args.markets,
        do_edges=bool(args.do_edges),
        do_export=bool(args.do_export),
        do_push=bool(args.do_push),
        log_file=Path(args.log_file).resolve(),
        started_at=args.started_at or None,
    )
    artifact_root = str(args.artifact_root or "").strip()
    if artifact_root:
        copied = _materialize_artifact_bundle(state=state, artifact_root=Path(artifact_root).resolve())
        if copied:
            state["artifact_bundle_root"] = str(Path(artifact_root).resolve())
            state["artifact_bundle_files"] = copied
    print(json.dumps(_json_ready(state), indent=2, sort_keys=True))

    snapshot_rows = int(state.get("snapshot_rows") or 0)
    alias_rows = int(state.get("snapshot_alias_rows") or 0)
    edges_rows = int(state.get("edges_rows") or 0)
    recs_rows = int(state.get("recs_rows") or 0)
    if state.get("error"):
        return 1
    if snapshot_rows > 0 and alias_rows <= 0:
        return 1
    if bool(args.do_edges) and snapshot_rows > 0 and edges_rows <= 0:
        return 1
    if bool(args.do_export) and snapshot_rows > 0 and recs_rows <= 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())