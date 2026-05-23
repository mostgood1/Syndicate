from __future__ import annotations

import argparse
import importlib
import importlib.util
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


def _load_module_from_path(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_source_app(source_root: Path):
    app_path = source_root / "app.py"
    return _load_module_from_path("syndicate_nba_source_app", app_path)


def _build_optional_player_recon_artifacts(*, source_root: Path, date_str: str, processed_root: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    tool_specs = (
        (
            source_root / "tools" / "build_recon_players.py",
            "syndicate_nba_build_recon_players",
            "build_recon_players",
            processed_root / f"recon_players_{date_str}.csv",
            "recon_players_path",
        ),
        (
            source_root / "tools" / "build_live_player_lens_tuning.py",
            "syndicate_nba_build_live_player_lens_tuning",
            "build_live_player_lens_tuning",
            processed_root / f"live_player_lens_tuning_{date_str}.csv",
            "live_player_lens_tuning_path",
        ),
    )
    for module_path, module_name, function_name, out_path, copied_key in tool_specs:
        try:
            module = _load_module_from_path(module_name, module_path)
            builder = getattr(module, function_name, None)
            if builder is None:
                continue
            df = builder(date_str)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out_path, index=False)
            copied[copied_key] = str(out_path)
        except Exception:
            continue
    return copied


def _export_top_by_game_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    source_app = _load_source_app(source_root)
    out_path = processed_root / f"props_recommendations_top_by_game_{date_str}.json"
    query = (
        f"/api/props/recommendations?date={date_str}&compact=1&portfolio_only=1"
        "&use_snapshot=0&limit=25&per_game_limit=3&per_market=1&slate_per_market_limit=4"
        "&markets=pts,reb,ast,threes,blk,stl,pra,pr,pa,ra,dd,td"
    )
    client = source_app.app.test_client()
    response = client.get(query)
    try:
        payload = response.get_json() if response is not None else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {"error": "no_json", "status": int(getattr(response, "status_code", 0) or 0)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out_path)


def _export_recon_games_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    source_app = _load_source_app(source_root)
    if hasattr(source_app, "_cron_auth_ok"):
        try:
            source_app._cron_auth_ok = lambda _request: True
        except Exception:
            pass
    client = source_app.app.test_client()
    response = client.get(f"/api/cron/reconcile-games?date={date_str}")
    try:
        payload = response.get_json() if response is not None else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return None
    output_path = str(payload.get("output") or "").strip()
    if not output_path:
        return None
    source = Path(output_path)
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _export_live_lens_artifacts(*, source_root: Path, date_str: str, processed_root: Path, live_lens_root: Path) -> dict[str, str]:
    source_app = _load_source_app(source_root)
    client = source_app.app.test_client()
    exports = (
        (
            f"/api/download_live_lens_signals?date={date_str}",
            (
                (processed_root / f"live_lens_signals_{date_str}.jsonl", "live_lens_signals_path"),
                (live_lens_root / f"live_lens_signals_{date_str}.jsonl", None),
            ),
        ),
        (
            f"/api/download_live_lens_projections?date={date_str}",
            (
                (processed_root / f"live_lens_projections_{date_str}.jsonl", "live_lens_projections_path"),
                (live_lens_root / f"live_lens_projections_{date_str}.jsonl", None),
            ),
        ),
        (
            "/api/download_live_lens_tuning",
            (
                (processed_root / "live_lens_tuning_override.json", "live_lens_tuning_override_path"),
                (live_lens_root / "live_lens_tuning_override.json", "live_lens_tuning_override_live_lens_path"),
            ),
        ),
    )
    copied: dict[str, str] = {}
    for query, destinations in exports:
        try:
            response = client.get(query)
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code != 200:
                continue
            raw = b""
            get_data = getattr(response, "get_data", None)
            if callable(get_data):
                raw = get_data()
            elif hasattr(response, "data"):
                raw = getattr(response, "data") or b""
            if not isinstance(raw, (bytes, bytearray)) or not raw:
                continue
            for out_path, copied_key in destinations:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(bytes(raw))
                if copied_key:
                    copied[copied_key] = str(out_path)
        except Exception:
            continue
    return copied


def _materialize_artifact_bundle(*, state: dict[str, object], artifact_root: Path, source_root: Path) -> dict[str, object]:
    processed_root = artifact_root / "data" / "processed"
    raw_root = artifact_root / "data" / "raw"
    live_lens_root = artifact_root / "data" / "live_lens"
    copied: dict[str, object] = {}
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
        recon_games_path = _export_recon_games_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recon_games_path:
            copied["recon_games_path"] = recon_games_path
        recon_quarters_path = _export_recon_quarters_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recon_quarters_path:
            copied["recon_quarters_path"] = recon_quarters_path
        top_by_game_path = _export_top_by_game_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if top_by_game_path:
            copied["top_by_game_path"] = top_by_game_path
        copied.update(_export_live_lens_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root, live_lens_root=live_lens_root))
        copied.update(_build_optional_player_recon_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root))
    return copied


def _load_source_module(source_root: Path):
    src_root = source_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    return importlib.import_module("nba_betting.refresh_oddsapi_props_job")


def _load_source_cli(source_root: Path):
    src_root = source_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    return importlib.import_module("nba_betting.cli")


def _export_recon_quarters_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    try:
        cli_module = _load_source_cli(source_root)
        cli_module.cli.main(["reconcile-quarters", "--date", date_str], standalone_mode=False)  # type: ignore[attr-defined]
    except SystemExit:
        pass
    except Exception:
        return None
    source = source_root / "data" / "processed" / f"recon_quarters_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


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
        copied = _materialize_artifact_bundle(
            state=state,
            artifact_root=Path(artifact_root).resolve(),
            source_root=source_root,
        )
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