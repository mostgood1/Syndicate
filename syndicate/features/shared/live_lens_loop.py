from __future__ import annotations

import atexit
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from syndicate.features.shared.artifact_publisher import publish_changed_hot_artifacts
from syndicate.features.shared.artifact_publisher import pull_hot_artifacts
from syndicate.features.mlb.live_lens import build_live_lens_snapshot_internal as _mlb_build
from syndicate.features.mlb.live_lens import live_lens_snapshot_path as _mlb_snapshot_path
from syndicate.features.mlb.live_lens import validate_live_lens_snapshot as _mlb_validate
from syndicate.features.nba.live_lens import build_live_lens_snapshot as _nba_build
from syndicate.features.nba.live_lens import live_lens_snapshot_path as _nba_snapshot_path
from syndicate.features.nba.live_lens import validate_live_lens_snapshot as _nba_validate
from syndicate.features.shared.memory_observability import log_all_process_memory
from syndicate.features.shared.memory_observability import memory_headroom_snapshot
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.wnba.live_lens import build_live_lens_snapshot as _wnba_build
from syndicate.features.wnba.live_lens import live_lens_snapshot_path as _wnba_snapshot_path
from syndicate.features.wnba.live_lens import validate_live_lens_snapshot as _wnba_validate

try:
	import fcntl  # type: ignore
except Exception:
	fcntl = None

try:
	import msvcrt  # type: ignore
except Exception:
	msvcrt = None


_LIVE_LENS_LOOP_THREAD: threading.Thread | None = None
_LIVE_LENS_LOOP_LOCK = threading.Lock()
_LIVE_LENS_LOOP_STOP = threading.Event()
_LIVE_LENS_PROCESS_LOCK_HANDLE: Any | None = None


def _mlb_build_wrapper(date_str: str) -> dict[str, Any]:
	return _mlb_build(date_str)


def _nba_build_wrapper(date_str: str) -> dict[str, Any]:
	return _nba_build(date_str, limit=50)


def _wnba_build_wrapper(date_str: str) -> dict[str, Any]:
	return _wnba_build(date_str, limit=50)


_LIVE_LENS_SPORTS: tuple[str, ...] = ("mlb", "nba", "wnba")

_LIVE_LENS_BUILDERS: dict[str, Callable[[str], dict[str, Any]]] = {
	"mlb": _mlb_build_wrapper,
	"nba": _nba_build_wrapper,
	"wnba": _wnba_build_wrapper,
}

_LIVE_LENS_VALIDATORS: dict[str, Callable[[Any], bool]] = {
	"mlb": _mlb_validate,
	"nba": _nba_validate,
	"wnba": _wnba_validate,
}

_LIVE_LENS_SNAPSHOT_PATHS: dict[str, Callable[[], Path]] = {
	"mlb": _mlb_snapshot_path,
	"nba": _nba_snapshot_path,
	"wnba": _wnba_snapshot_path,
}


def _utc_now() -> str:
	return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_bool(name: str, *, default: bool = False) -> bool:
	raw = str(os.environ.get(name) or "").strip().lower()
	if not raw:
		return bool(default)
	return raw in {"1", "true", "yes", "on"}


def _meta_dir() -> Path:
	path = reports_root() / "live_lens_loop"
	path.mkdir(parents=True, exist_ok=True)
	return path


def _process_lock_path() -> Path:
	return _meta_dir() / "live_lens_background_loop.lock"


def _release_process_lock() -> None:
	global _LIVE_LENS_PROCESS_LOCK_HANDLE
	handle = _LIVE_LENS_PROCESS_LOCK_HANDLE
	if handle is None:
		return
	_LIVE_LENS_PROCESS_LOCK_HANDLE = None
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
	global _LIVE_LENS_PROCESS_LOCK_HANDLE
	if _LIVE_LENS_PROCESS_LOCK_HANDLE is not None:
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
		_LIVE_LENS_PROCESS_LOCK_HANDLE = handle
		return True
	except Exception:
		try:
			handle.close()
		except Exception:
			pass
		return False


def _is_live_lens_loop_enabled() -> bool:
	return _env_bool("SYNDICATE_ENABLE_LIVE_LENS_LOOP", default=False)


def _live_lens_loop_interval_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_LIVE_LENS_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw or 60)
	except Exception:
		value = 60
	return max(5, int(value))


def _mlb_live_lens_memory_gate_enabled() -> bool:
	return _env_bool("SYNDICATE_LIVE_LENS_MEMORY_GATE_ENABLED", default=True)


def _mlb_live_lens_min_headroom_bytes() -> int:
	# #124 root cause (2026-07-30): this used to default to 1800, copy-pasted
	# from live_refresh_loop.py's _odds_refresh_min_headroom_bytes(), which is
	# deliberately calibrated to the worst WNBA-refresh-leg RSS spike measured
	# in production (~1528MB) -- a much heavier operation than this gate
	# guards. 1800MB required headroom on a 2048MB container left only 248MB
	# of the whole container "allowed" to be in use at any time, which
	# live-odds-worker's steady-state baseline (~700-900MB) never satisfied --
	# hence the ~80%+ tick-failure rate, all of it reason=low_headroom (33/33
	# sampled failures over 40h, zero exceptions/invalid_snapshot). Paired 100
	# real before/after-build memory snapshots the same day: estimate_live's
	# actual per-tick cost was 0-13MB. 300MB keeps the same "worst measured +
	# margin" calibration philosophy, just applied to what this gate actually
	# guards instead of a different, heavier operation's number.
	raw = str(os.environ.get("SYNDICATE_LIVE_LENS_MIN_HEADROOM_MB") or "").strip()
	try:
		value = int(raw or 300)
	except Exception:
		value = 300
	return max(0, value) * 1024 * 1024


def _mlb_live_lens_headroom_snapshot() -> dict[str, Any] | None:
	# Guards the MLB builder only: it's the one sport whose build reaches
	# estimate_live (a real Monte Carlo resim, 120 sims per live game,
	# in-process, no batching) via _persist_live_lens_report. NBA/WNBA builders
	# don't run a comparable heavy resim, so gating them too would just add
	# unnecessary staleness risk without a matching memory benefit -- the same
	# over-scoping mistake already made (and reverted) for the WNBA
	# odds-refresh mutex.
	#
	# Phase 4 (2026-07-30): WNBA's builder now also computes a real live
	# win-probability (_build_wnba_game_lens/_wnba_live_margin_win_prob in
	# wnba/live_lens.py), but deliberately still isn't gated here -- that
	# computation is a clock parse + one logistic call + one blend, not a
	# sampling loop, so its cost is expected to be negligible like NBA's. If
	# real measurement ever shows otherwise, calibrate a WNBA-specific gate
	# from that measurement -- never copy this function's number (that's
	# the exact #124 mistake this file's own history already made once).
	if not _mlb_live_lens_memory_gate_enabled():
		return None
	return memory_headroom_snapshot(_mlb_live_lens_min_headroom_bytes())


def _tally_mlb_live_mc_sources(snapshot: Any) -> dict[str, int]:
	# estimate_live's own failures are swallowed by a bare except in the
	# vendor code with zero logging -- the "source" field on each gameLens
	# lane (live_mc / live_projection / segment_projection) is the only signal
	# that survives. Tallying it here, once per tick, makes the real
	# success/fallback rate observable through the existing tick-status
	# plumbing instead of requiring a live API probe to find out.
	tally: dict[str, int] = {}
	games = snapshot.get("games") if isinstance(snapshot, dict) else None
	if not isinstance(games, list):
		return tally
	for game in games:
		if not isinstance(game, dict):
			continue
		lanes = game.get("gameLens")
		if not isinstance(lanes, list):
			continue
		for lane in lanes:
			if not isinstance(lane, dict):
				continue
			source = str(lane.get("source") or "unknown")
			tally[source] = tally.get(source, 0) + 1
	return tally


def _run_live_lens_tick_for_sport(sport: str, date_str: str) -> dict[str, Any]:
	meta: dict[str, Any] = {"sport": sport, "date": date_str, "startedAt": _utc_now()}
	# This loop runs independently of live_refresh_loop.py's own tick, on its own
	# interval, in the same process (live-odds-worker) -- and had no memory
	# instrumentation of its own. Confirmed elsewhere that the main tick's RSS
	# stays flat (~100-110MB) at every checkpoint while the container still
	# restarts roughly once per cycle with nothing visible in between; this is
	# the leading remaining candidate for where that gap is going.
	try:
		log_all_process_memory(f"live_lens_tick_before_{sport}", sport=sport, date=date_str)
		if sport == "mlb":
			headroom_snapshot = _mlb_live_lens_headroom_snapshot()
			if headroom_snapshot is not None and not headroom_snapshot["sufficient"]:
				meta["ok"] = False
				meta["skipped"] = True
				meta["reason"] = "low_headroom"
				meta["memoryHeadroom"] = headroom_snapshot
				# TEMPORARY diagnostic (todo.md #124 follow-up) -- the third
				# ok=False path, missed by the first pass of this diagnostic
				# (which only covered the exception and invalid_snapshot
				# branches, neither of which fired even once across 12
				# measured failing ticks). print, not logger.info. Remove
				# once the actual failure mode is confirmed.
				print(f"[LIVE_LENS_TICK_DIAG] sport={sport} ok=False reason=low_headroom headroom={headroom_snapshot}", flush=True)
				return meta
		builder = _LIVE_LENS_BUILDERS[sport]
		validator = _LIVE_LENS_VALIDATORS[sport]
		path_fn = _LIVE_LENS_SNAPSHOT_PATHS[sport]
		snapshot = builder(date_str)
		log_all_process_memory(f"live_lens_tick_after_build_{sport}", sport=sport, date=date_str)
		if not validator(snapshot):
			meta["ok"] = False
			meta["skipped"] = True
			meta["reason"] = "invalid_snapshot"
			# TEMPORARY diagnostic (todo.md #124 follow-up) -- MLB's tick
			# fails ~80% of the time (2/11 succeeded in one measured window)
			# while NBA/WNBA never fail, and meta["error"]/meta["reason"]
			# were only ever written to latest_live_lens_tick.json (itself
			# keyvalue-routed, unreadable without the admin token). print,
			# not logger.info -- see other #124 diagnostics for why. Remove
			# once the actual failure mode is confirmed.
			if sport == "mlb":
				games = snapshot.get("games") if isinstance(snapshot, dict) else None
				print(
					f"[LIVE_LENS_TICK_DIAG] sport={sport} ok=False reason=invalid_snapshot "
					f"is_dict={isinstance(snapshot, dict)} games_type={type(games).__name__} "
					f"games_len={len(games) if isinstance(games, list) else None}",
					flush=True,
				)
			return meta
		if sport == "mlb":
			meta["liveMcSources"] = _tally_mlb_live_mc_sources(snapshot)
		write_json_file(path_fn(), snapshot)
		meta["ok"] = True
		meta["path"] = str(path_fn())
	except Exception as exc:
		meta["ok"] = False
		meta["error"] = f"{type(exc).__name__}: {exc}"
		if sport == "mlb":
			import traceback

			print(
				f"[LIVE_LENS_TICK_DIAG] sport={sport} ok=False error={type(exc).__name__}: {exc}\n{traceback.format_exc()}",
				flush=True,
			)
	finally:
		meta["finishedAt"] = _utc_now()
		log_all_process_memory(f"live_lens_tick_after_{sport}", sport=sport, date=date_str, ok=bool(meta.get("ok")))
	return meta


def _run_live_lens_tick() -> dict[str, Any]:
	date_str = central_today_iso()
	results = {sport: _run_live_lens_tick_for_sport(sport, date_str) for sport in _LIVE_LENS_SPORTS}
	meta = {
		"startedAt": _utc_now(),
		"date": date_str,
		"results": results,
		"ok": all(bool(result.get("ok")) for result in results.values()),
	}
	meta["finishedAt"] = _utc_now()
	write_json_file(_meta_dir() / "latest_live_lens_tick.json", meta)
	return meta


def _live_lens_publish_enabled() -> bool:
	return _env_bool("SYNDICATE_LIVE_LENS_LOOP_PUBLISH_ARTIFACTS", default=True)


def _live_lens_pull_enabled() -> bool:
	# #128: live-odds-worker never calls pull_hot_artifacts anywhere else --
	# that only runs inside the intelligence-state background loop, which
	# this service deliberately does NOT own (SYNDICATE_ENABLE_INTELLIGENCE_
	# STATE_BACKGROUND_LOOP is false here, true on refresh-worker, "so
	# exactly one service owns the loop"). Confirmed live: MLB's
	# build_cards_page_context ran fine on this service (schedule/status/
	# matchup all correct) but its own source_title came back "MLB cards
	# unavailable" -- daily_summary_<date>_locked_policy.json (the file
	# _live_props_from_card ultimately depends on, see #124 item 3) was
	# never on this service's disk because nothing here had ever asked web
	# for it. pull_hot_artifacts is watermark-incremental plus a repair pass
	# for exactly this "permanently missing, not merely stale" case, and
	# never raises -- safe to call every tick.
	return _env_bool("SYNDICATE_LIVE_LENS_LOOP_PULL_ARTIFACTS", default=True)


def _live_lens_background_loop() -> None:
	status_path = _meta_dir() / "live_lens_loop_status.json"
	interval_seconds = _live_lens_loop_interval_seconds()
	# live_lens_loop runs on live-odds-worker, which has its own disk separate
	# from the web service's (Render gives each service its own mount even at
	# the same path) -- writing live_lens_projections_*.jsonl/live_lens_signals_
	# *.jsonl here does nothing for web's read side without an explicit publish.
	# Bounded to files changed since the previous tick so a slow cycle doesn't
	# repeatedly re-scan/re-publish the same unchanged files.
	last_publish_epoch = time.time()
	while not _LIVE_LENS_LOOP_STOP.is_set():
		started_at = _utc_now()
		started_epoch = time.time()
		if _live_lens_pull_enabled():
			try:
				pulled_count = pull_hot_artifacts(date_str=central_today_iso())
				if pulled_count:
					print(f"[live_lens_loop] pulled_hot_artifacts count={pulled_count}", flush=True)
			except Exception as exc:
				print(f"[live_lens_loop] pull_hot_artifacts_failed error={type(exc).__name__}: {exc}", flush=True)
		meta = _run_live_lens_tick()
		if _live_lens_publish_enabled():
			try:
				published_count = publish_changed_hot_artifacts(last_publish_epoch)
				if published_count:
					print(f"[live_lens_loop] published_hot_artifacts count={published_count}", flush=True)
			except Exception as exc:
				print(f"[live_lens_loop] publish_hot_artifacts_failed error={type(exc).__name__}: {exc}", flush=True)
		last_publish_epoch = started_epoch
		write_json_file(
			status_path,
			{
				"state": "running",
				"startedAt": started_at,
				"lastTickAt": meta.get("finishedAt"),
				"intervalSeconds": int(interval_seconds),
				"threadAlive": True,
				"lastTickOk": bool(meta.get("ok")),
				"results": meta.get("results"),
			},
		)
		summary = {sport: result.get("ok") for sport, result in (meta.get("results") or {}).items()}
		print(f"[live_lens_loop] TICK_COMPLETE results={summary} nextIntervalSeconds={interval_seconds}", flush=True)
		_LIVE_LENS_LOOP_STOP.wait(interval_seconds)


def start_live_lens_loop() -> bool:
	global _LIVE_LENS_LOOP_THREAD
	if not _is_live_lens_loop_enabled():
		return False
	with _LIVE_LENS_LOOP_LOCK:
		if _LIVE_LENS_LOOP_THREAD is not None and _LIVE_LENS_LOOP_THREAD.is_alive():
			return False
		if not _acquire_process_lock():
			return False
		_LIVE_LENS_LOOP_STOP.clear()
		_LIVE_LENS_LOOP_THREAD = threading.Thread(
			target=_live_lens_background_loop,
			name="syndicate-live-lens-loop",
			daemon=True,
		)
		_LIVE_LENS_LOOP_THREAD.start()
		return True


def live_lens_loop_status_payload() -> dict[str, Any]:
	status_path = _meta_dir() / "live_lens_loop_status.json"
	latest_tick_path = _meta_dir() / "latest_live_lens_tick.json"
	return {
		"enabled": _is_live_lens_loop_enabled(),
		"intervalSeconds": int(_live_lens_loop_interval_seconds()),
		"threadAlive": bool(_LIVE_LENS_LOOP_THREAD is not None and _LIVE_LENS_LOOP_THREAD.is_alive()),
		"latestStatus": read_json_file(status_path) or {},
		"latestTick": read_json_file(latest_tick_path) or {},
	}


atexit.register(_release_process_lock)
