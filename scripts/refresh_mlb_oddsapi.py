from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

FILE_TEMPLATES = (
    ("data/daily/daily_summary_{date_slug}.json", "data/daily/daily_summary_{date_slug}.json"),
    ("data/daily/daily_summary_{date_slug}_profile_bundle.json", "data/daily/daily_summary_{date_slug}_profile_bundle.json"),
    ("data/daily/daily_summary_{date_slug}_locked_policy.json", "data/daily/daily_summary_{date_slug}_locked_policy.json"),
    ("data/daily/daily_summary_{date_slug}_hr_targets.json", "data/daily/daily_summary_{date_slug}_hr_targets.json"),
    ("data/daily/daily_summary_{date_slug}_rfi_targets.json", "data/daily/daily_summary_{date_slug}_rfi_targets.json"),
    ("data/daily/ladders/daily_ladders_{date_slug}.json", "data/daily/ladders/daily_ladders_{date_slug}.json"),
    ("data/daily/top_props/daily_top_props_{date_slug}.json", "data/daily/top_props/daily_top_props_{date_slug}.json"),
    ("data/daily/ops/daily_ops_{date_slug}.json", "data/daily/ops/daily_ops_{date_slug}.json"),
    ("data/daily/season_frontend/season_betting_day_{date_slug}.json", "data/daily/season_frontend/season_betting_day_{date_slug}.json"),
    ("data/live_lens/live_lens_{date_slug}.jsonl", "data/live_lens/live_lens_{date_slug}.jsonl"),
    ("data/live_lens/live_lens_report_{date_slug}.json", "data/live_lens/live_lens_report_{date_slug}.json"),
    ("data/live_lens/prop_registry/live_prop_registry_{date_slug}.json", "data/live_lens/prop_registry/live_prop_registry_{date_slug}.json"),
    ("data/live_lens/prop_registry/live_prop_registry_{date_slug}.jsonl", "data/live_lens/prop_registry/live_prop_registry_{date_slug}.jsonl"),
    ("data/live_lens/prop_registry/live_prop_observations_{date_slug}.jsonl", "data/live_lens/prop_registry/live_prop_observations_{date_slug}.jsonl"),
    ("data/tuning/live_prop_ranking/default.json", "data/tuning/live_prop_ranking/default.json"),
    ("sim_engine/live_prop_ranking.py", "sim_engine/live_prop_ranking.py"),
)

DIRECTORY_TEMPLATES = (
    ("data/daily/snapshots/{date_str}", "data/daily/snapshots/{date_str}"),
    ("data/daily/sims/{date_str}", "data/daily/sims/{date_str}"),
    ("data/market/oddsapi/refresh_history/{date_slug}", "data/market/oddsapi/refresh_history/{date_slug}"),
    ("data/raw/statsapi/feed_live/{season}/{date_str}", "data/raw/statsapi/feed_live/{season}/{date_str}"),
)

SEASON_MANIFEST_FILES = (
    "season_betting_cards_retuned_manifest.json",
    "season_betting_cards_retuned_hrr_manifest.json",
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
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return True


def _source_artifacts_ready(*, source_root: Path, date_str: str) -> bool:
    date_slug = str(date_str).replace("-", "_")
    season = str(date_str).split("-", 1)[0]
    required_paths = (
        source_root / "data" / "daily" / f"daily_summary_{date_slug}.json",
        source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json",
        source_root / "data" / "daily" / "snapshots" / date_str,
        source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug,
        source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json",
    )
    return all(path.exists() for path in required_paths)


def _load_local_fetcher():
    scripts_root = (REPO_ROOT / "scripts").resolve()
    if str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))
    importlib.invalidate_caches()
    return importlib.import_module("fetch_mlb_oddsapi_local")


@contextmanager
def _pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _date_slug(date_str: str) -> str:
    return str(date_str).replace("-", "_")


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _local_timestamp_text(value: datetime | None = None) -> str:
    stamp = value.astimezone() if isinstance(value, datetime) else _local_now()
    return stamp.isoformat(timespec="seconds")


def _write_json_file(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _daily_snapshot_dir(*, source_root: Path, date_str: str) -> Path:
    return source_root / "data" / "daily" / "snapshots" / str(date_str)


def _cron_meta_dir(*, source_root: Path) -> Path:
    return _ensure_dir(source_root / "data" / "live_lens" / "cron_meta")


def _live_lens_log_path(*, source_root: Path, date_str: str) -> Path:
    return source_root / "data" / "live_lens" / f"live_lens_{_date_slug(date_str)}.jsonl"


def _live_lens_report_path(*, source_root: Path, date_str: str) -> Path:
    return source_root / "data" / "live_lens" / f"live_lens_report_{_date_slug(date_str)}.json"


def _live_prop_observation_log_path(*, source_root: Path, date_str: str) -> Path:
    return _ensure_dir(source_root / "data" / "live_lens" / "prop_registry") / f"live_prop_observations_{_date_slug(date_str)}.jsonl"


def _live_prop_registry_path(*, source_root: Path, date_str: str) -> Path:
    return _ensure_dir(source_root / "data" / "live_lens" / "prop_registry") / f"live_prop_registry_{_date_slug(date_str)}.json"


def _live_prop_registry_log_path(*, source_root: Path, date_str: str) -> Path:
    return _ensure_dir(source_root / "data" / "live_lens" / "prop_registry") / f"live_prop_registry_{_date_slug(date_str)}.jsonl"


def _write_jsonl_line(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
        handle.write("\n")


def _build_degraded_live_lens_payload(*, source_root: Path, date_str: str) -> dict[str, object]:
    return {
        "date": str(date_str),
        "generatedAt": _local_timestamp_text(),
        "dataRoot": "data",
        "liveLensDir": "data/live_lens",
        "optimizationRegime": None,
        "counts": {
            "games": 0,
            "live": 0,
            "final": 0,
            "pregame": 0,
            "props": 0,
            "archivedLiveProps": 0,
        },
        "performance": {
            "marketsRefreshed": False,
            "marketRefreshMs": 0.0,
            "totalMs": 0.0,
            "snapshotLoadMs": 0.0,
            "simContextLoadMs": 0.0,
            "propEvalMs": 0.0,
            "gameLensMs": 0.0,
            "gameCount": 0,
            "liveGameCount": 0,
            "feedFetchCount": 0,
            "degraded": True,
        },
        "games": [],
        "found": False,
        "error": "live_lens_unavailable",
        "detail": f"Generated locally in Syndicate for {source_root}",
    }


def _bootstrap_live_lens_artifacts(*, source_root: Path, date_str: str, trigger: str) -> dict[str, object]:
    report_payload = _build_degraded_live_lens_payload(source_root=source_root, date_str=date_str)
    report_path = _live_lens_report_path(source_root=source_root, date_str=date_str)
    log_path = _live_lens_log_path(source_root=source_root, date_str=date_str)
    observation_path = _live_prop_observation_log_path(source_root=source_root, date_str=date_str)
    registry_path = _live_prop_registry_path(source_root=source_root, date_str=date_str)
    registry_log_path = _live_prop_registry_log_path(source_root=source_root, date_str=date_str)
    _write_json_file(report_path, report_payload)
    if log_path.exists():
        log_path.unlink()
    _write_jsonl_line(
        log_path,
        {
            "recordedAt": report_payload.get("generatedAt"),
            "date": str(date_str),
            "counts": report_payload.get("counts"),
            "performance": report_payload.get("performance"),
            "games": [],
            "degraded": True,
        },
    )
    _write_json_file(
        registry_path,
        {
            "date": str(date_str),
            "updatedAt": report_payload.get("generatedAt"),
            "entries": {},
        },
    )
    registry_log_path.parent.mkdir(parents=True, exist_ok=True)
    registry_log_path.write_text("", encoding="utf-8")
    observation_path.parent.mkdir(parents=True, exist_ok=True)
    observation_path.write_text("", encoding="utf-8")
    meta = {
        "recordedAt": _local_timestamp_text(),
        "date": str(date_str),
        "counts": report_payload.get("counts"),
        "marketsRefreshed": False,
        "reportPath": str(report_path),
        "logPath": str(log_path),
        "propObservationLogPath": str(observation_path),
        "trigger": str(trigger),
        "reused": False,
        "degraded": True,
    }
    _write_json_file(_cron_meta_dir(source_root=source_root) / "latest_live_lens_tick.json", meta)
    return {
        "ok": True,
        "date": str(date_str),
        "counts": report_payload.get("counts"),
        "report": meta,
    }


def _reuse_existing_live_lens_tick(*, source_root: Path, date_str: str, trigger: str) -> dict[str, object] | None:
    report_path = _live_lens_report_path(source_root=source_root, date_str=date_str)
    log_path = _live_lens_log_path(source_root=source_root, date_str=date_str)
    observation_path = _live_prop_observation_log_path(source_root=source_root, date_str=date_str)
    if not report_path.exists() or not report_path.is_file():
        return None
    if not log_path.exists() and not observation_path.exists():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    counts = payload.get("counts") if isinstance(payload, dict) and isinstance(payload.get("counts"), dict) else None
    meta = {
        "recordedAt": _local_timestamp_text(),
        "date": str(date_str),
        "counts": counts,
        "marketsRefreshed": False,
        "reportPath": str(report_path),
        "logPath": str(log_path),
        "propObservationLogPath": str(observation_path),
        "trigger": str(trigger),
        "reused": True,
    }
    _write_json_file(_cron_meta_dir(source_root=source_root) / "latest_live_lens_tick.json", meta)
    return {"ok": True, "date": str(date_str), "counts": counts, "report": meta}


def _archive_oddsapi_refresh_outputs(*, source_root: Path, date_str: str, result: dict[str, object], recorded_at: datetime) -> dict[str, object]:
    archive_dir = _ensure_dir(
        source_root / "data" / "market" / "oddsapi" / "refresh_history" / _date_slug(date_str) / recorded_at.strftime("%Y%m%dT%H%M%S_%fZ")
    )
    copied: dict[str, str] = {}
    files: dict[str, str] = {}
    for key in ("game_lines_path", "pitcher_props_path", "hitter_props_path"):
        raw_source_path = result.get(key)
        source_path = Path(str(raw_source_path)).resolve() if raw_source_path else None
        if not source_path or not source_path.exists() or not source_path.is_file():
            continue
        destination = archive_dir / source_path.name
        shutil.copy2(source_path, destination)
        copied[source_path.name] = str(destination)
        files[key] = str(destination)
    archive_meta = {
        "recordedAt": _local_timestamp_text(recorded_at),
        "date": str(date_str),
        "archiveDir": str(archive_dir),
        "result": result,
        "files": files,
    }
    _write_json_file(archive_dir / "refresh_meta.json", archive_meta)
    return {
        "archiveDir": str(archive_dir),
        "files": files,
        "copied": copied,
    }


def _freeze_oddsapi_pregame_markets(*, source_root: Path, date_str: str) -> dict[str, str]:
    snapshot_dir = _daily_snapshot_dir(source_root=source_root, date_str=date_str)
    market_dir = source_root / "data" / "market" / "oddsapi"
    slug = _date_slug(date_str)
    _ensure_dir(snapshot_dir)
    copied: dict[str, str] = {}
    for prefix in ("oddsapi_game_lines", "oddsapi_pitcher_props", "oddsapi_hitter_props"):
        source_path = market_dir / f"{prefix}_{slug}.json"
        if not source_path.exists() or not source_path.is_file():
            continue
        try:
            source_doc = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception:
            source_doc = {}
        if str((source_doc or {}).get("mode") or "").strip().lower() == "live":
            continue
        frozen_name = f"{prefix}_{slug}_pregame.json"
        for destination in (market_dir / frozen_name, snapshot_dir / frozen_name):
            shutil.copy2(source_path, destination)
            copied[destination.name] = str(destination)
    return copied


def _refresh_source_artifacts(*, odds_module, source_root: Path, date_str: str, regions: str, overwrite: bool) -> dict[str, object]:
    recorded_at = _local_now()
    frozen_pregame = _freeze_oddsapi_pregame_markets(source_root=source_root, date_str=date_str)
    result = odds_module.fetch_and_write_live_odds_for_date(
        date_str,
        out_dir=source_root / "data" / "market" / "oddsapi",
        overwrite=overwrite,
        regions=regions,
    )

    snapshot_dir = _daily_snapshot_dir(source_root=source_root, date_str=date_str)
    copied: dict[str, str] = {}
    _ensure_dir(snapshot_dir)
    for key in ("game_lines_path", "pitcher_props_path", "hitter_props_path"):
        raw_source_path = result.get(key)
        source_path = Path(str(raw_source_path)).resolve() if raw_source_path else None
        if not source_path or not source_path.exists() or not source_path.is_file():
            continue
        destination = snapshot_dir / source_path.name
        shutil.copy2(source_path, destination)
        copied[source_path.name] = str(destination)

    archived = _archive_oddsapi_refresh_outputs(source_root=source_root, date_str=date_str, result=result, recorded_at=recorded_at)
    meta = {
        "recordedAt": _local_timestamp_text(recorded_at),
        "date": str(date_str),
        "overwrite": bool(overwrite),
        "frozenPregame": frozen_pregame,
        "result": result,
        "copied": copied,
        "archived": archived,
    }
    _write_json_file(_cron_meta_dir(source_root=source_root) / "latest_refresh_oddsapi.json", meta)
    live_lens = _reuse_existing_live_lens_tick(source_root=source_root, date_str=date_str, trigger="syndicate_refresh")
    if live_lens is None:
        live_lens = _bootstrap_live_lens_artifacts(source_root=source_root, date_str=date_str, trigger="syndicate_refresh")
    return {
        "market_refresh": {
            "ok": True,
            "date": str(date_str),
            "result": result,
            "copied": copied,
            "archived": archived,
        },
        "live_lens": live_lens,
    }


def _materialize_artifact_bundle(*, source_root: Path, artifact_root: Path, date_str: str) -> dict[str, object]:
    date_slug = str(date_str).replace("-", "_")
    season = str(date_str).split("-", 1)[0]
    season_payload_slug = date_slug
    prefix = f"{season}_"
    if season_payload_slug.startswith(prefix):
        season_payload_slug = season_payload_slug[len(prefix) :]

    copied: dict[str, object] = {}
    format_values = {
        "date_str": date_str,
        "date_slug": date_slug,
        "season": season,
        "season_payload_slug": season_payload_slug,
    }

    for source_template, destination_template in FILE_TEMPLATES:
        source = source_root / Path(source_template.format(**format_values))
        destination = artifact_root / Path(destination_template.format(**format_values))
        if _copy_if_exists(source, destination):
            copied.setdefault("files", []).append(str(destination))

    for source_template, destination_template in DIRECTORY_TEMPLATES:
        source = source_root / Path(source_template.format(**format_values))
        destination = artifact_root / Path(destination_template.format(**format_values))
        if _copy_tree_if_exists(source, destination):
            copied.setdefault("directories", []).append(str(destination))

    season_eval_root = source_root / "data" / "eval" / "seasons" / season
    season_manifest = season_eval_root / "season_eval_manifest.json"
    if _copy_if_exists(season_manifest, artifact_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json"):
        copied.setdefault("files", []).append(str(artifact_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json"))

    for name in SEASON_MANIFEST_FILES:
        source = season_eval_root / name
        destination = artifact_root / "data" / "eval" / "seasons" / season / name
        if _copy_if_exists(source, destination):
            copied.setdefault("files", []).append(str(destination))

    for parent in season_eval_root.glob("betting_day_payloads*"):
        if not parent.is_dir():
            continue
        pattern = f"season_betting_day_{season}_{season_payload_slug}*.json"
        for source in parent.glob(pattern):
            destination = artifact_root / "data" / "eval" / "seasons" / season / parent.name / source.name
            if _copy_if_exists(source, destination):
                copied.setdefault("files", []).append(str(destination))

    for parent in season_eval_root.glob("betting_day_recaps*"):
        if not parent.is_dir():
            continue
        pattern = f"season_betting_day_{season}_{season_payload_slug}*.json"
        for source in parent.glob(pattern):
            destination = artifact_root / "data" / "eval" / "seasons" / season / parent.name / source.name
            if _copy_if_exists(source, destination):
                copied.setdefault("files", []).append(str(destination))

    live_lens_recap = source_root / "data" / "live_lens" / "recaps" / f"live_lens_daily_recap_{date_slug}.json"
    recap_destination = artifact_root / "data" / "live_lens" / "recaps" / f"live_lens_daily_recap_{date_slug}.json"
    if _copy_if_exists(live_lens_recap, recap_destination):
        copied.setdefault("files", []).append(str(recap_destination))

    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh MLB OddsAPI snapshots through a Syndicate-owned runner.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--artifact-root", required=False, default=str(REPO_ROOT / "data" / "mlb_source" / "source_artifacts"))
    parser.add_argument("--regions", default="us")
    parser.add_argument("--overwrite", choices=("on", "off"), default="on")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    artifact_root = Path(args.artifact_root).resolve()

    try:
        if str(args.overwrite) == "off" and _source_artifacts_ready(source_root=source_root, date_str=str(args.date)):
            refresh_payload = {
                "market_refresh": {
                    "ok": True,
                    "date": str(args.date),
                    "skipped": True,
                    "reason": "existing_source_artifacts",
                }
            }
        else:
            odds_module = _load_local_fetcher()
            with _pushd(source_root):
                refresh_payload = _refresh_source_artifacts(
                    odds_module=odds_module,
                    source_root=source_root,
                    date_str=str(args.date),
                    regions=str(args.regions or "us"),
                    overwrite=str(args.overwrite) == "on",
                )
    except Exception as exc:
        print(json.dumps({"ok": False, "date": args.date, "error": str(exc)}))
        return 1

    copied = _materialize_artifact_bundle(source_root=source_root, artifact_root=artifact_root, date_str=str(args.date))
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "artifact_bundle_root": str(artifact_root),
                "refresh": refresh_payload,
                "artifact_bundle_files": copied,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())