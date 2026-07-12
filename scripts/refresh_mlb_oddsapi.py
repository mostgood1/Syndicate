from __future__ import annotations

import argparse
import errno
import importlib
import importlib.util
import hashlib
import json
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib.error import HTTPError
from urllib.error import URLError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.refresh_state_store import build_input_hash
from syndicate.features.shared.refresh_state_store import path_fingerprint
from syndicate.features.shared.refresh_state_store import record_refresh_state
from syndicate.features.shared.refresh_state_store import should_recompute

FILE_TEMPLATES = (
    ("data/daily/lineups_last_known_by_team.json", "data/daily/lineups_last_known_by_team.json"),
    ("data/daily/daily_summary_{date_slug}.json", "data/daily/daily_summary_{date_slug}.json"),
    ("data/daily/daily_summary_{date_slug}_profile_bundle.json", "data/daily/daily_summary_{date_slug}_profile_bundle.json"),
    ("data/daily/daily_summary_{date_slug}_locked_policy.json", "data/daily/daily_summary_{date_slug}_locked_policy.json"),
    ("data/daily/daily_summary_{date_slug}_hr_targets.json", "data/daily/daily_summary_{date_slug}_hr_targets.json"),
    ("data/daily/daily_summary_{date_slug}_rfi_targets.json", "data/daily/daily_summary_{date_slug}_rfi_targets.json"),
    ("data/manager/manager_tendencies.json", "data/manager/manager_tendencies.json"),
    ("data/manager/probable_pitcher_overrides.json", "data/manager/probable_pitcher_overrides.json"),
    ("data/park/park_factors.json", "data/park/park_factors.json"),
    ("data/umpire/umpire_factors.json", "data/umpire/umpire_factors.json"),
    ("data/umpire/umpire_factors_report_2025-07-01_2025-09-30.json", "data/umpire/umpire_factors_report_2025-07-01_2025-09-30.json"),
    ("data/daily/ladders/daily_ladders_{date_slug}.json", "data/daily/ladders/daily_ladders_{date_slug}.json"),
    ("data/daily/top_props/daily_top_props_{date_slug}.json", "data/daily/top_props/daily_top_props_{date_slug}.json"),
    ("data/daily/ops/daily_ops_{date_slug}.json", "data/daily/ops/daily_ops_{date_slug}.json"),
    ("data/market/oddsapi/oddsapi_game_lines_{date_slug}.json", "data/daily/snapshots/{date_str}/oddsapi_game_lines_{date_slug}.json"),
    ("data/market/oddsapi/oddsapi_pitcher_props_{date_slug}.json", "data/daily/snapshots/{date_str}/oddsapi_pitcher_props_{date_slug}.json"),
    ("data/market/oddsapi/oddsapi_hitter_props_{date_slug}.json", "data/daily/snapshots/{date_str}/oddsapi_hitter_props_{date_slug}.json"),
    ("data/live_lens/live_lens_{date_slug}.jsonl", "data/live_lens/live_lens_{date_slug}.jsonl"),
    ("data/live_lens/live_lens_report_{date_slug}.json", "data/live_lens/live_lens_report_{date_slug}.json"),
    ("data/live_lens/render_sync/live_lens_reports_{date_slug}.json", "data/live_lens/render_sync/live_lens_reports_{date_slug}.json"),
    ("data/live_lens/prop_registry/live_prop_registry_{date_slug}.json", "data/live_lens/prop_registry/live_prop_registry_{date_slug}.json"),
    ("data/live_lens/prop_registry/live_prop_registry_{date_slug}.jsonl", "data/live_lens/prop_registry/live_prop_registry_{date_slug}.jsonl"),
    ("data/live_lens/prop_registry/live_prop_observations_{date_slug}.jsonl", "data/live_lens/prop_registry/live_prop_observations_{date_slug}.jsonl"),
    ("data/tuning/live_prop_ranking/default.json", "data/tuning/live_prop_ranking/default.json"),
    ("sim_engine/live_prop_ranking.py", "sim_engine/live_prop_ranking.py"),
)

DIRECTORY_TEMPLATES = (
    ("data/cache", "data/cache"),
    ("data/daily_hitter_props", "data/daily_hitter_props"),
    ("data/daily_pitcher_props", "data/daily_pitcher_props"),
    ("data/daily/snapshots/{date_str}", "data/daily/snapshots/{date_str}"),
    ("data/daily/sims/{date_str}", "data/daily/sims/{date_str}"),
    ("data/manager", "data/manager"),
    ("data/park", "data/park"),
    ("data/market/oddsapi/refresh_history/{date_slug}", "data/market/oddsapi/refresh_history/{date_slug}"),
    ("data/raw/statcast/pitches", "data/raw/statcast/pitches"),
    ("data/raw/statsapi/feed_live", "data/raw/statsapi/feed_live"),
    ("data/roster_registry", "data/roster_registry"),
    ("data/runtime", "data/runtime"),
    ("data/statcast", "data/statcast"),
    ("data/umpire", "data/umpire"),
    ("data/raw/statsapi/feed_live/{season}/{date_str}", "data/raw/statsapi/feed_live/{season}/{date_str}"),
)

SEASON_MANIFEST_FILES = (
    "season_betting_cards_retuned_manifest.json",
    "season_betting_cards_retuned_hrr_manifest.json",
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


def _copy_tree_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_dir():
        return False
    try:
        if source.resolve() == destination.resolve():
            return True
    except Exception:
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree_with_fallback(source, destination)
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


def _copy_tree_with_fallback(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for root, _dirs, files in os.walk(source):
        root_path = Path(root)
        relative_root = root_path.relative_to(source)
        target_root = destination / relative_root
        target_root.mkdir(parents=True, exist_ok=True)
        for file_name in files:
            _copy_file_with_fallback(root_path / file_name, target_root / file_name)


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


def _env_first(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _load_module_from_path(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _temporary_env(overrides: dict[str, str | None]):
    original: dict[str, str | None] = {}
    for key, value in overrides.items():
        original[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _normalize_render_base_url(value: str) -> str:
    base_url = str(value or "").strip()
    if not base_url:
        return ""
    if "://" not in base_url:
        return f"https://{base_url}"
    return base_url


def _fetch_live_lens_reports_payload(*, base_url: str, token: str, date_str: str, timeout_seconds: int) -> dict[str, object]:
    query = urllib_parse.urlencode({"date": str(date_str), "slim": "on"})
    url = f"{str(base_url).rstrip('/')}/api/cron/live-lens-reports?{query}"
    request = urllib_request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib_request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("live-lens reports response was not a JSON object")
    return payload


def _build_local_live_lens_reports_payload(*, source_root: Path, date_str: str) -> dict[str, object]:
    module_path = (REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py").resolve()
    if not module_path.exists() or not module_path.is_file():
        raise RuntimeError(f"Vendored MLB live-lens source app not found at {module_path}")
    data_root = (source_root / "data").resolve()
    module_name = f"syndicate_mlb_live_lens_source_{abs(hash((str(module_path), str(data_root))))}"
    with _temporary_env(
        {
            "MLB_BETTING_DATA_ROOT": str(data_root),
            "MLB_LIVE_LENS_DIR": str((data_root / "live_lens").resolve()),
        }
    ):
        source_app = _load_module_from_path(module_name, module_path)
        builder = getattr(source_app, "_live_lens_reports_payload", None)
        if not callable(builder):
            raise RuntimeError("Vendored MLB live-lens payload builder is unavailable")
        payload = builder(str(date_str), include_archive=False, slim=True)
    if not isinstance(payload, dict):
        raise RuntimeError("Vendored MLB live-lens payload builder did not return a JSON object")
    return payload


def _write_live_lens_reports_payload(*, source_root: Path, date_str: str, payload: dict[str, object], trigger: str) -> dict[str, object]:
    report_payload = payload.get("latestReport") if isinstance(payload.get("latestReport"), dict) else payload
    if not isinstance(report_payload, dict):
        report_payload = {}
    counts_payload = report_payload.get("counts") if isinstance(report_payload.get("counts"), dict) else payload.get("counts")
    performance_payload = report_payload.get("performance") if isinstance(report_payload.get("performance"), dict) else payload.get("performance")
    games_payload = report_payload.get("games") if isinstance(report_payload.get("games"), list) else payload.get("games")

    report_path = _live_lens_report_path(source_root=source_root, date_str=date_str)
    sync_path = source_root / "data" / "live_lens" / "render_sync" / f"live_lens_reports_{_date_slug(date_str)}.json"
    log_path = _live_lens_log_path(source_root=source_root, date_str=date_str)
    registry_path = _live_prop_registry_path(source_root=source_root, date_str=date_str)
    registry_log_path = _live_prop_registry_log_path(source_root=source_root, date_str=date_str)
    observation_path = _live_prop_observation_log_path(source_root=source_root, date_str=date_str)
    _write_json_file(report_path, report_payload)
    _write_json_file(sync_path, payload)

    latest_entry = payload.get("latestEntry") if isinstance(payload.get("latestEntry"), dict) else {}
    if latest_entry:
        _write_jsonl_line(log_path, latest_entry)
    elif not log_path.exists():
        _write_jsonl_line(
            log_path,
            {
                "recordedAt": _local_timestamp_text(),
                "date": str(date_str),
                "counts": counts_payload if isinstance(counts_payload, dict) else None,
                "performance": performance_payload if isinstance(performance_payload, dict) else None,
                "games": games_payload if isinstance(games_payload, list) else [],
                "degraded": bool(payload.get("error") or report_payload.get("error")),
            },
        )

    if not registry_path.exists():
        _write_json_file(
            registry_path,
            {
                "date": str(date_str),
                "updatedAt": report_payload.get("generatedAt") or _local_timestamp_text(),
                "entries": {},
            },
        )
    registry_log_path.parent.mkdir(parents=True, exist_ok=True)
    if not registry_log_path.exists():
        registry_log_path.write_text("", encoding="utf-8")
    observation_path.parent.mkdir(parents=True, exist_ok=True)
    if not observation_path.exists():
        observation_path.write_text("", encoding="utf-8")
    meta = {
        "recordedAt": _local_timestamp_text(),
        "date": str(date_str),
        "counts": counts_payload if isinstance(counts_payload, dict) else None,
        "marketsRefreshed": bool(games_payload if isinstance(games_payload, list) else []),
        "reportPath": str(report_path),
        "syncPath": str(sync_path),
        "logPath": str(log_path),
        "propObservationLogPath": str(observation_path),
        "trigger": str(trigger),
        "reused": False,
        "synced": True,
    }
    _write_json_file(_cron_meta_dir(source_root=source_root) / "latest_live_lens_tick.json", meta)
    return {
        "ok": True,
        "date": str(date_str),
        "counts": counts_payload if isinstance(counts_payload, dict) else None,
        "report": meta,
    }


def _live_lens_input_hash(*, source_root: Path, date_str: str) -> str:
    date_slug = _date_slug(date_str)
    snapshot_root = source_root / "data" / "daily" / "snapshots" / str(date_str)
    return build_input_hash(
        {
            "step": "mlb_live_lens",
            "date": date_str,
            "inputs": [
                path_fingerprint(snapshot_root / f"oddsapi_game_lines_{date_slug}.json"),
                path_fingerprint(snapshot_root / f"oddsapi_pitcher_props_{date_slug}.json"),
                path_fingerprint(snapshot_root / f"oddsapi_hitter_props_{date_slug}.json"),
            ],
        }
    )


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


def _read_json_if_exists(path: Path) -> dict[str, object] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _stable_doc_hash(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _same_doc(existing: dict[str, object] | None, candidate: dict[str, object] | None) -> bool:
    if not isinstance(existing, dict) or not isinstance(candidate, dict):
        return False
    return _stable_doc_hash(existing) == _stable_doc_hash(candidate)


def _market_entry_hash(entry: dict[str, object]) -> str:
    return _stable_doc_hash(entry)


def _daily_snapshot_dir(*, source_root: Path, date_str: str) -> Path:
    return source_root / "data" / "daily" / "snapshots" / str(date_str)


def _cron_meta_dir(*, source_root: Path) -> Path:
    return _ensure_dir(source_root / "data" / "live_lens" / "cron_meta")


def _live_lens_log_path(*, source_root: Path, date_str: str) -> Path:
    return source_root / "data" / "live_lens" / f"live_lens_{_date_slug(date_str)}.jsonl"


def _live_lens_report_path(*, source_root: Path, date_str: str) -> Path:
    return source_root / "data" / "live_lens" / f"live_lens_report_{_date_slug(date_str)}.json"


def _required_live_lens_relative_paths(*, date_str: str) -> tuple[Path, ...]:
    date_slug = _date_slug(date_str)
    return (
        Path("data") / "live_lens" / f"live_lens_{date_slug}.jsonl",
        Path("data") / "live_lens" / f"live_lens_report_{date_slug}.json",
        Path("data") / "live_lens" / "render_sync" / f"live_lens_reports_{date_slug}.json",
        Path("data") / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json",
    )


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
    return _write_live_lens_reports_payload(source_root=source_root, date_str=date_str, payload=report_payload, trigger=trigger)


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
    if isinstance(payload, dict) and not payload.get("games"):
        return None
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


def fetch_live_odds_incremental(*, odds_module, source_root: Path, date_str: str, regions: str, bookmakers: str | None, hitter_markets: list[str] | None) -> dict[str, object]:
    api_key = (
        os.environ.get("ODDS_API_KEY")
        or os.environ.get("ODDSAPI_KEY")
        or os.environ.get("THEODDS_API_KEY")
        or os.environ.get("THEODDSAPI_KEY")
        or os.environ.get("NCAAB_THEODDS_API_KEY")
    )
    if not api_key:
        raise RuntimeError("ODDS_API_KEY not set")

    target_dir = source_root / "data" / "market" / "oddsapi"
    _ensure_dir(target_dir)
    token = _date_slug(date_str)
    game_lines_path = target_dir / f"oddsapi_game_lines_{token}.json"
    pitcher_props_path = target_dir / f"oddsapi_pitcher_props_{token}.json"
    hitter_props_path = target_dir / f"oddsapi_hitter_props_{token}.json"

    existing_game_lines_doc = _read_json_if_exists(game_lines_path)
    existing_pitcher_props_doc = _read_json_if_exists(pitcher_props_path)
    existing_hitter_props_doc = _read_json_if_exists(hitter_props_path)

    print("[mlb_fetch_start]", flush=True)
    live_events = list(odds_module._fetch_live_events_for_date(api_key, date_str))
    print(f"[mlb_fetch_events] events_count={len(live_events) if live_events else 0}", flush=True)
    game_market_keys = [
        "h2h",
        "spreads",
        "totals",
        "h2h_1st_1_innings",
        "h2h_3_way_1st_1_innings",
        "spreads_1st_1_innings",
        "alternate_spreads_1st_1_innings",
        "totals_1st_1_innings",
        "alternate_totals_1st_1_innings",
        "h2h_1st_3_innings",
        "h2h_3_way_1st_3_innings",
        "spreads_1st_3_innings",
        "alternate_spreads_1st_3_innings",
        "totals_1st_3_innings",
        "alternate_totals_1st_3_innings",
        "h2h_1st_5_innings",
        "h2h_3_way_1st_5_innings",
        "spreads_1st_5_innings",
        "alternate_spreads_1st_5_innings",
        "totals_1st_5_innings",
        "alternate_totals_1st_5_innings",
        "h2h_1st_7_innings",
        "h2h_3_way_1st_7_innings",
        "spreads_1st_7_innings",
        "alternate_spreads_1st_7_innings",
        "totals_1st_7_innings",
        "alternate_totals_1st_7_innings",
    ]
    pitcher_market_keys = list(getattr(odds_module, "PITCHER_MARKET_KEY_MAP", {}).keys())
    if hitter_markets:
        desired_hitter_markets = [str(m).strip().lower() for m in hitter_markets if str(m).strip()]
    else:
        desired_hitter_markets = [str(m).strip().lower() for m in getattr(odds_module, "DEFAULT_HITTER_MARKETS", []) if str(m).strip()]
    combined_markets = []
    for market_name in game_market_keys + pitcher_market_keys + desired_hitter_markets:
        market_name = str(market_name).strip().lower()
        if market_name and market_name not in combined_markets:
            combined_markets.append(market_name)

    pitch_key_map = dict(getattr(odds_module, "PITCHER_MARKET_KEY_MAP", {}))
    hitter_key_map = {market_name: market_name for market_name in desired_hitter_markets}
    existing_game_rows = {
        str(row.get("event_id") or "").strip(): row
        for row in ((existing_game_lines_doc or {}).get("games") or [])
        if isinstance(row, dict) and str(row.get("event_id") or "").strip()
    }
    game_rows: list[dict[str, object]] = []
    pitcher_props: dict[str, dict[str, dict[str, object]]] = {}
    hitter_props: dict[str, dict[str, dict[str, object]]] = {}
    changed_game_rows = 0
    reused_game_rows = 0

    for event in live_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        try:
            payload = odds_module._fetch_live_event_odds(
                api_key,
                event_id,
                markets_csv=",".join(combined_markets),
                regions=regions,
                bookmakers=bookmakers,
            )
        except getattr(odds_module, "OddsApiLiveFetchError", RuntimeError):
            raise
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        home_team = str(event.get("home_team") or payload.get("home_team") or "")
        away_team = str(event.get("away_team") or payload.get("away_team") or "")
        best_lines, bookmaker_key = odds_module._best_bookmaker_game_lines(payload, home_team=home_team, away_team=away_team)
        if isinstance(best_lines, dict):
            game_entry = {
                "event_id": event_id,
                "commence_time": event.get("commence_time") or payload.get("commence_time"),
                "home_team": home_team,
                "away_team": away_team,
                "bookmaker": bookmaker_key,
                "markets": best_lines,
            }
            existing_game_entry = existing_game_rows.get(event_id)
            if _same_doc(existing_game_entry, game_entry):
                game_rows.append(existing_game_entry or game_entry)
                reused_game_rows += 1
            else:
                game_rows.append(game_entry)
                changed_game_rows += 1

        for bookmaker in (payload.get("bookmakers") or []):
            if not isinstance(bookmaker, dict):
                continue
            extracted_pitcher = odds_module._extract_player_props(bookmaker.get("markets"), key_map=pitch_key_map)
            for name, market_rows in extracted_pitcher.items():
                dst = pitcher_props.setdefault(name, {})
                for market_name, row in market_rows.items():
                    dst[market_name] = odds_module._merge_prop_market_rows(dst.get(market_name, {}), row)
            extracted_hitter = odds_module._extract_player_props(bookmaker.get("markets"), key_map=hitter_key_map)
            for name, market_rows in extracted_hitter.items():
                dst = hitter_props.setdefault(name, {})
                for market_name, row in market_rows.items():
                    dst[market_name] = odds_module._merge_prop_market_rows(dst.get(market_name, {}), row)

    finalized_pitcher_props = odds_module._finalize_prop_market_map(pitcher_props)
    finalized_hitter_props = odds_module._finalize_prop_market_map(hitter_props)

    game_counts = {
        "events_matched": int(len(live_events)),
        "games": int(len(game_rows)),
        "h2h_games": int(sum(1 for row in game_rows if isinstance((row.get("markets") or {}).get("h2h"), dict))),
        "totals_games": int(sum(1 for row in game_rows if isinstance((row.get("markets") or {}).get("totals"), dict))),
        "spreads_games": int(sum(1 for row in game_rows if isinstance((row.get("markets") or {}).get("spreads"), dict))),
    }
    print(f"[mlb_counts] events_matched={game_counts['events_matched']} games={game_counts['games']}", flush=True)
    pitcher_counts = dict(odds_module._prop_market_counts(finalized_pitcher_props))
    pitcher_counts["events_matched"] = int(len(live_events))
    hitter_counts = dict(odds_module._prop_market_counts(finalized_hitter_props))
    hitter_counts["events_matched"] = int(len(live_events))

    retrieved_at = datetime.utcnow().isoformat()
    game_lines_doc = {
        "date": str(date_str),
        "mode": "live",
        "retrieved_at": retrieved_at,
        "games": game_rows,
        "meta": {
            "markets": game_market_keys,
            "regions": str(regions or "us"),
            "bookmakers": (str(bookmakers).split(",") if bookmakers else None),
            "counts": game_counts,
        },
    }
    pitcher_props_doc = {
        "date": str(date_str),
        "mode": "live",
        "retrieved_at": retrieved_at,
        "pitcher_props": finalized_pitcher_props,
        "meta": {
            "markets": pitcher_market_keys,
            "regions": str(regions or "us"),
            "bookmakers": (str(bookmakers).split(",") if bookmakers else None),
            "counts": pitcher_counts,
        },
    }
    hitter_props_doc = {
        "date": str(date_str),
        "mode": "live",
        "retrieved_at": retrieved_at,
        "hitter_props": finalized_hitter_props,
        "meta": {
            "markets": desired_hitter_markets,
            "regions": str(regions or "us"),
            "bookmakers": (str(bookmakers).split(",") if bookmakers else None),
            "counts": hitter_counts,
        },
    }

    wrote_files: list[str] = []
    if not _same_doc(existing_game_lines_doc, game_lines_doc):
        _write_json_file(game_lines_path, game_lines_doc)
        wrote_files.append(str(game_lines_path))
    if not _same_doc(existing_pitcher_props_doc, pitcher_props_doc):
        _write_json_file(pitcher_props_path, pitcher_props_doc)
        wrote_files.append(str(pitcher_props_path))
    if not _same_doc(existing_hitter_props_doc, hitter_props_doc):
        _write_json_file(hitter_props_path, hitter_props_doc)
        wrote_files.append(str(hitter_props_path))

    result = {
        "status": "ok" if wrote_files else "skipped",
        "date": str(date_str),
        "mode": "live",
        "incremental": True,
        "out_dir": str(target_dir),
        "game_lines_path": str(game_lines_path),
        "pitcher_props_path": str(pitcher_props_path),
        "hitter_props_path": str(hitter_props_path),
        "updated_games": int(changed_game_rows),
        "reused_games": int(reused_game_rows),
        "written_files": wrote_files,
        "counts": {
            "game_lines": dict(game_counts),
            "pitcher_props": dict(pitcher_counts),
            "hitter_props": dict(hitter_counts),
        },
    }
    if reused_game_rows and not changed_game_rows:
        result["warnings"] = [f"reused {reused_game_rows} unchanged game rows for {date_str}"]
    return result


def _refresh_source_artifacts(*, odds_module, source_root: Path, date_str: str, regions: str, overwrite: bool, fast_mode: bool) -> dict[str, object]:
    recorded_at = _local_now()
    frozen_pregame = _freeze_oddsapi_pregame_markets(source_root=source_root, date_str=date_str)
    if fast_mode:
        result = fetch_live_odds_incremental(
            odds_module=odds_module,
            source_root=source_root,
            date_str=date_str,
            regions=regions,
            bookmakers=None,
            hitter_markets=None,
        )
    else:
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

    if fast_mode:
        live_lens = _reuse_existing_live_lens_tick(source_root=source_root, date_str=date_str, trigger="syndicate_refresh")
        if live_lens is None:
            live_lens = {
                "ok": True,
                "date": str(date_str),
                "skipped": True,
                "reason": "live_lens_artifacts_missing",
            }
    else:
        live_lens = _refresh_live_lens_artifacts(source_root=source_root, date_str=date_str, trigger="syndicate_refresh")

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


def _refresh_live_lens_artifacts(*, source_root: Path, date_str: str, trigger: str) -> dict[str, object]:
    def _coerce_report_payload(payload: dict[str, object] | None) -> dict[str, object]:
        if not isinstance(payload, dict):
            return {}
        latest_report = payload.get("latestReport")
        if isinstance(latest_report, dict):
            return latest_report
        return payload

    def _payload_is_usable(payload: dict[str, object] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        report_payload = _coerce_report_payload(payload)
        if payload.get("error") or report_payload.get("error"):
            return False
        performance = report_payload.get("performance")
        if isinstance(performance, dict) and performance.get("degraded"):
            return False
        return True

    live_lens = None
    errors: list[str] = []
    input_hash = _live_lens_input_hash(source_root=source_root, date_str=date_str)
    if not should_recompute(f"mlb_live_lens:{date_str}", input_hash):
        reused = _reuse_existing_live_lens_tick(source_root=source_root, date_str=date_str, trigger=trigger)
        if reused is not None:
            return reused
    base_url = _normalize_render_base_url(_env_first("MLB_BETTING_BASE_URL", "BASE_URL", "RENDER_URL", "RENDER_EXTERNAL_URL"))
    token = _env_first("MLB_BETTING_CRON_TOKEN", "MLB_CRON_TOKEN", "CRON_TOKEN")
    if base_url and token:
        try:
            live_lens_payload = _fetch_live_lens_reports_payload(base_url=base_url, token=token, date_str=date_str, timeout_seconds=45)
            if _payload_is_usable(live_lens_payload):
                live_lens = _write_live_lens_reports_payload(source_root=source_root, date_str=date_str, payload=live_lens_payload, trigger=trigger)
            else:
                errors.append("remote live-lens payload was degraded or empty")
        except (HTTPError, URLError, OSError, ValueError, RuntimeError) as exc:
            errors.append(f"remote live-lens fetch failed: {exc}")
    if live_lens is None:
        try:
            live_lens_payload = _build_local_live_lens_reports_payload(source_root=source_root, date_str=date_str)
            if _payload_is_usable(live_lens_payload):
                live_lens = _write_live_lens_reports_payload(source_root=source_root, date_str=date_str, payload=live_lens_payload, trigger=trigger)
            else:
                errors.append("local live-lens payload was degraded or empty")
        except Exception as exc:
            errors.append(f"local live-lens build failed: {exc}")
    if live_lens is None:
        detail = "; ".join(errors) if errors else "unknown live-lens failure"
        raise RuntimeError(f"MLB live-lens refresh failed without fallback: {detail}")
    record_refresh_state(
        f"mlb_live_lens:{date_str}",
        input_hash,
        metadata={"date": date_str, "trigger": trigger, "source_root": str(source_root)},
        outputs=[
            str(_live_lens_report_path(source_root=source_root, date_str=date_str)),
            str(_live_lens_log_path(source_root=source_root, date_str=date_str)),
            str(_live_prop_registry_path(source_root=source_root, date_str=date_str)),
        ],
    )
    return live_lens


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

    season_frontend_root = source_root / "data" / "daily" / "season_frontend"
    if season_frontend_root.exists() and season_frontend_root.is_dir():
        season_frontend_patterns = (
            f"season_manifest_{season}_{date_slug}.json",
            f"season_day_{season}_{date_slug}_*.json",
            f"season_betting_day_{season}_{date_slug}_*.json",
            f"season_official_betting_day_{season}_{date_slug}_*.json",
        )
        for pattern in season_frontend_patterns:
            for source in season_frontend_root.glob(pattern):
                destination = artifact_root / "data" / "daily" / "season_frontend" / source.name
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
    print("=== MLB RUNNER HIT ===", flush=True)
    parser = argparse.ArgumentParser(description="Refresh MLB OddsAPI snapshots through a Syndicate-owned runner.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--artifact-root", required=False, default=str(REPO_ROOT / "data" / "mlb_source" / "source_artifacts"))
    parser.add_argument("--regions", default="us")
    parser.add_argument("--overwrite", choices=("on", "off"), default="on")
    parser.add_argument("--mode", choices=("fast", "full"), default="full")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    artifact_root = Path(args.artifact_root).resolve()
    fast_mode = str(args.mode or "full").strip().lower() == "fast"

    try:
        if fast_mode:
            odds_module = _load_local_fetcher()
            with _pushd(source_root):
                refresh_payload = _refresh_source_artifacts(
                    odds_module=odds_module,
                    source_root=source_root,
                    date_str=str(args.date),
                    regions=str(args.regions or "us"),
                    overwrite=False,
                    fast_mode=True,
                )
            refresh_payload["mode"] = "fast"
        elif str(args.overwrite) == "off" and _source_artifacts_ready(source_root=source_root, date_str=str(args.date)):
            refresh_payload = {
                "market_refresh": {
                    "ok": True,
                    "date": str(args.date),
                    "skipped": True,
                    "reason": "existing_source_artifacts",
                },
                "live_lens": _refresh_live_lens_artifacts(source_root=source_root, date_str=str(args.date), trigger="syndicate_refresh"),
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
                    fast_mode=False,
                )
    except Exception as exc:
        message = str(exc)
        if "Usage quota has been reached" in message:
            print(json.dumps({"ok": True, "date": args.date, "warning": message}))
            return 0
        print(json.dumps({"ok": False, "date": args.date, "error": message}))
        return 1

    copied = _materialize_artifact_bundle(source_root=source_root, artifact_root=artifact_root, date_str=str(args.date)) if str(args.mode or "full").strip().lower() == "full" else {}
    required_live_lens_paths = _required_live_lens_relative_paths(date_str=str(args.date))
    missing_source_live_lens = [str(path) for path in required_live_lens_paths if not (source_root / path).exists()]
    missing_artifact_live_lens = [str(path) for path in required_live_lens_paths if not (artifact_root / path).exists()]
    if missing_source_live_lens or missing_artifact_live_lens:
        refresh_payload["warnings"] = list(refresh_payload.get("warnings") or []) + [
            "fast mode skipped live-lens rebuild; existing live-lens artifacts were not fully present"
            if fast_mode
            else "live-lens artifacts were not fully present after refresh",
        ]

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