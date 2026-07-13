from __future__ import annotations

import atexit
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.artifact_publisher import publish_changed_hot_artifacts
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import repo_root_from
from syndicate.features.shared.timezone import central_today_iso

try:
	import fcntl  # type: ignore
except Exception:
	fcntl = None

try:
	import msvcrt  # type: ignore
except Exception:
	msvcrt = None


REPO_ROOT = repo_root_from(__file__)
_LIVE_REFRESH_LOOP_THREAD: threading.Thread | None = None
_LIVE_REFRESH_LOOP_LOCK = threading.Lock()
_LIVE_REFRESH_LOOP_STOP = threading.Event()
_LIVE_REFRESH_PROCESS_LOCK_HANDLE: Any | None = None


def _utc_now() -> str:
	return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_bool(name: str, *, default: bool = False) -> bool:
	raw = str(os.environ.get(name) or "").strip().lower()
	if not raw:
		return bool(default)
	return raw in {"1", "true", "yes", "on"}


def _reports_root() -> Path:
	return reports_root()


def _meta_dir() -> Path:
	path = _reports_root() / "live_refresh_loop"
	path.mkdir(parents=True, exist_ok=True)
	return path


def _process_lock_path() -> Path:
	return _meta_dir() / "live_refresh_background_loop.lock"


def _release_process_lock() -> None:
	global _LIVE_REFRESH_PROCESS_LOCK_HANDLE
	handle = _LIVE_REFRESH_PROCESS_LOCK_HANDLE
	if handle is None:
		return
	_LIVE_REFRESH_PROCESS_LOCK_HANDLE = None
	try:
		if fcntl is not None:
			fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
		elif msvcrt is not None:
			handle.seek(0)
			try:
				msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
			except Exception:
				pass
	except Exception:
		pass
	try:
		handle.close()
	except Exception:
		pass


def _acquire_process_lock() -> bool:
	global _LIVE_REFRESH_PROCESS_LOCK_HANDLE
	if _LIVE_REFRESH_PROCESS_LOCK_HANDLE is not None:
		return True
	lock_path = _process_lock_path()
	try:
		handle = open(lock_path, "a+", encoding="utf-8")
	except Exception:
		return False
	try:
		handle.seek(0)
		handle.write(f"pid={os.getpid()}\n")
		handle.truncate()
		handle.flush()
	except Exception:
		pass
	try:
		if fcntl is not None:
			fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
		elif msvcrt is not None:
			handle.seek(0)
			msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
		_LIVE_REFRESH_PROCESS_LOCK_HANDLE = handle
		return True
	except Exception:
		try:
			handle.close()
		except Exception:
			pass
		return False


def _is_live_refresh_loop_enabled() -> bool:
	return _env_bool("SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP", default=False)


def _live_refresh_loop_interval_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw or 60)
	except Exception:
		value = 60
	return max(5, int(value))


def _live_refresh_loop_idle_interval_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_IDLE_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw or 1800)
	except Exception:
		value = 1800
	return max(60, int(value))


def _live_refresh_loop_adaptive_enabled() -> bool:
	return _env_bool("SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE", default=True)


def _mlb_has_live_game(date_str: str) -> bool:
	path = data_root() / "mlb_source" / "source_artifacts" / "data" / "live_lens" / f"live_lens_report_{date_str.replace('-', '_')}.json"
	payload = read_json_file(path)
	counts = payload.get("counts") if isinstance(payload, dict) else None
	if not isinstance(counts, dict):
		return False
	try:
		return int(counts.get("live") or 0) > 0
	except (TypeError, ValueError):
		return False


def _wnba_has_live_game(date_str: str) -> bool:
	path = data_root() / "wnba_source" / "source_artifacts" / "data" / "processed" / "live_snapshots" / f"live_state_{date_str}.jsonl"
	try:
		if not path.exists():
			return False
		last_line: str | None = None
		with path.open("r", encoding="utf-8") as handle:
			for raw_line in handle:
				stripped = raw_line.strip()
				if stripped:
					last_line = stripped
		if not last_line:
			return False
		record = json.loads(last_line)
	except Exception:
		return False
	payload = record.get("payload") if isinstance(record, dict) else None
	games = payload.get("games") if isinstance(payload, dict) else None
	if not isinstance(games, list):
		return False
	return any(bool(game.get("in_progress")) for game in games if isinstance(game, dict))


_LIVE_STATUS_CHECKERS = {
	"mlb": _mlb_has_live_game,
	"wnba": _wnba_has_live_game,
}


def _any_tracked_sport_game_live() -> bool:
	date_str = central_today_iso()
	configured = _live_refresh_loop_sports()
	sports = [item.strip().lower() for item in configured.split(",") if item.strip()] if configured else list(_LIVE_STATUS_CHECKERS.keys())
	for sport in sports:
		checker = _LIVE_STATUS_CHECKERS.get(sport)
		if checker is not None and checker(date_str):
			return True
	return False


def _live_refresh_loop_phase() -> str:
	phase = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_PHASE") or "live").strip().lower()
	return phase if phase in {"live", "pregame", "all"} else "live"


def _live_refresh_loop_regions() -> str:
	return str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_REGIONS") or "us").strip() or "us"


def _live_refresh_loop_execution_mode() -> str:
	mode = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_EXECUTION_MODE") or "source").strip().lower()
	return mode if mode in {"source", "ingest"} else "source"


def _live_refresh_loop_mode() -> str:
	raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or os.environ.get("SYNDICATE_REFRESH_MODE") or "fast").strip().lower()
	return raw if raw in {"fast", "full"} else "fast"


def _live_refresh_loop_launch_mode() -> str:
	raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_LAUNCH_MODE") or "").strip().lower()
	if raw in {"detached_subprocess", "manifest_only", "external_runner"}:
		return raw
	fallback = str(os.environ.get("SYNDICATE_REFRESH_LAUNCH_MODE") or "").strip().lower()
	if fallback in {"detached_subprocess", "manifest_only", "external_runner"}:
		return fallback
	return "detached_subprocess"


def _live_refresh_loop_skip_mirror() -> bool:
	return _env_bool("SYNDICATE_LIVE_ODDS_REFRESH_SKIP_MIRROR", default=True)


def _live_refresh_loop_sports() -> str | None:
	raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_SPORTS") or "").strip()
	return raw or None


def _status_payload() -> dict[str, Any]:
	status_path = _meta_dir() / "live_refresh_loop_status.json"
	latest_tick_path = _meta_dir() / "latest_live_refresh_tick.json"
	latest_status = read_json_file(status_path) or {}
	latest_tick = read_json_file(latest_tick_path) or {}
	return {
		"enabled": _is_live_refresh_loop_enabled(),
		"intervalSeconds": int(_live_refresh_loop_interval_seconds()),
		"phase": _live_refresh_loop_phase(),
		"regions": _live_refresh_loop_regions(),
		"executionMode": _live_refresh_loop_execution_mode(),
		"mode": _live_refresh_loop_mode(),
		"launchMode": _live_refresh_loop_launch_mode(),
		"skipMirror": bool(_live_refresh_loop_skip_mirror()),
		"sports": _live_refresh_loop_sports() or "active",
		"threadAlive": bool(_LIVE_REFRESH_LOOP_THREAD is not None and _LIVE_REFRESH_LOOP_THREAD.is_alive()),
		"latestStatus": latest_status,
		"latestTick": latest_tick,
	}


def _run_live_refresh_tick() -> dict[str, Any]:
	tick_started_epoch = datetime.now(timezone.utc).timestamp()
	adaptive_enabled = _live_refresh_loop_adaptive_enabled()
	any_live = _any_tracked_sport_game_live() if adaptive_enabled else None
	effective_phase = ("live" if any_live else "pregame") if adaptive_enabled else _live_refresh_loop_phase()
	meta = {
		"startedAt": _utc_now(),
		"date": central_today_iso(),
		"phase": effective_phase,
		"adaptive": adaptive_enabled,
		"anyLive": bool(any_live) if adaptive_enabled else None,
		"regions": _live_refresh_loop_regions(),
		"executionMode": _live_refresh_loop_execution_mode(),
		"mode": _live_refresh_loop_mode(),
		"skipMirror": bool(_live_refresh_loop_skip_mirror()),
		"sports": _live_refresh_loop_sports() or "active",
	}
	try:
		result = launch_refresh_run(
			date=meta["date"],
			sports=_live_refresh_loop_sports(),
			phase=str(meta["phase"]),
			regions=str(meta["regions"]),
			mode=str(meta["mode"]),
			execution_mode=str(meta["executionMode"]),
			launch_mode=_live_refresh_loop_launch_mode(),
			skip_mirror=bool(meta["skipMirror"]),
			mirror_only=False,
			dry_run=False,
		)
		meta["ok"] = True
		meta["result"] = result
	except ValueError as exc:
		meta["ok"] = False
		meta["skipped"] = True
		meta["error"] = str(exc)
	except Exception as exc:
		meta["ok"] = False
		meta["error"] = f"{type(exc).__name__}: {exc}"
	meta["finishedAt"] = _utc_now()
	write_json_file(_meta_dir() / "latest_live_refresh_tick.json", meta)
	try:
		meta["publishedArtifacts"] = publish_changed_hot_artifacts(tick_started_epoch)
	except Exception:
		meta["publishedArtifacts"] = 0
	return meta


def _live_refresh_loop_interval_for_meta(meta: dict[str, Any]) -> int:
	if bool(meta.get("adaptive")) and meta.get("anyLive") is not None:
		return _live_refresh_loop_interval_seconds() if meta.get("anyLive") else _live_refresh_loop_idle_interval_seconds()
	return _live_refresh_loop_interval_seconds()


def _live_refresh_background_loop() -> None:
	status_path = _meta_dir() / "live_refresh_loop_status.json"
	while not _LIVE_REFRESH_LOOP_STOP.is_set():
		started_at = _utc_now()
		write_json_file(
			status_path,
			{
				"state": "running",
				"startedAt": started_at,
				"threadAlive": True,
			},
		)
		meta = _run_live_refresh_tick()
		interval_seconds = _live_refresh_loop_interval_for_meta(meta)
		write_json_file(
			status_path,
			{
				"state": "running",
				"startedAt": started_at,
				"lastTickAt": meta.get("finishedAt"),
				"intervalSeconds": int(interval_seconds),
				"threadAlive": True,
				"lastTickOk": bool(meta.get("ok")),
				"lastTickSkipped": bool(meta.get("skipped")),
				"lastError": meta.get("error"),
				"anyLive": meta.get("anyLive"),
				"phase": meta.get("phase"),
			},
		)
		print(f"[live_refresh_loop] TICK_COMPLETE phase={meta.get('phase')} anyLive={meta.get('anyLive')} nextIntervalSeconds={interval_seconds} ok={meta.get('ok')}", flush=True)
		_LIVE_REFRESH_LOOP_STOP.wait(interval_seconds)


def start_live_refresh_background_loop() -> bool:
	global _LIVE_REFRESH_LOOP_THREAD
	if not _is_live_refresh_loop_enabled():
		return False
	werkzeug_run_main = str(os.environ.get("WERKZEUG_RUN_MAIN") or "").strip().lower()
	if werkzeug_run_main == "false" and _env_bool("FLASK_DEBUG", default=False):
		return False
	with _LIVE_REFRESH_LOOP_LOCK:
		if _LIVE_REFRESH_LOOP_THREAD is not None and _LIVE_REFRESH_LOOP_THREAD.is_alive():
			return False
		if not _acquire_process_lock():
			return False
		_LIVE_REFRESH_LOOP_STOP.clear()
		_LIVE_REFRESH_LOOP_THREAD = threading.Thread(
			target=_live_refresh_background_loop,
			name="syndicate-live-refresh-loop",
			daemon=True,
		)
		_LIVE_REFRESH_LOOP_THREAD.start()
		return True


def live_refresh_loop_status_payload() -> dict[str, Any]:
	return _status_payload()


atexit.register(_release_process_lock)