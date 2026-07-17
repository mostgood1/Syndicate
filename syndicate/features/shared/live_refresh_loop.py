from __future__ import annotations

import atexit
import csv
import hashlib
import json
import os
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.artifact_publisher import publish_changed_hot_artifacts
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.schedule_adapter import events_starting_within
from syndicate.features.shared.schedule_adapter import fetch_schedule_for_date
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
		value = int(raw or 900)
	except Exception:
		value = 900
	return max(60, int(value))


def _live_refresh_loop_adaptive_enabled() -> bool:
	return _env_bool("SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE", default=True)


def _mlb_has_live_game_via_report(date_str: str) -> bool:
	path = data_root() / "mlb_source" / "source_artifacts" / "data" / "live_lens" / f"live_lens_report_{date_str.replace('-', '_')}.json"
	payload = read_json_file(path)
	counts = payload.get("counts") if isinstance(payload, dict) else None
	if not isinstance(counts, dict):
		return False
	try:
		return int(counts.get("live") or 0) > 0
	except (TypeError, ValueError):
		return False


def _mlb_has_live_game_via_schedule(date_str: str, *, timeout_s: float = 15.0) -> bool:
	helper = REPO_ROOT / "scripts" / "fetch_mlb_live_game_pks_for_date.py"
	if not helper.exists():
		return False
	python_exe = sys.executable if (sys.executable and Path(sys.executable).exists()) else "python"
	try:
		result = subprocess.run(
			[python_exe, str(helper), "--date", date_str],
			cwd=str(REPO_ROOT),
			capture_output=True,
			text=True,
			timeout=timeout_s,
		)
		if result.returncode != 0:
			return False
		payload = json.loads(result.stdout or "{}")
		live_game_pks = payload.get("live_game_pks") if isinstance(payload, dict) else None
		return isinstance(live_game_pks, list) and len(live_game_pks) > 0
	except Exception:
		return False


def _mlb_has_live_game(date_str: str) -> bool:
	# live_lens_report_<date>.json's own generation cadence/timing can lag
	# actual game state (its rebuild is a separate step from this adaptive
	# phase check), which left the odds-refresh loop stuck reporting
	# anyLive=false -- and therefore never switching to live-phase odds
	# refresh -- through an entire live game on 2026-07-17 despite the report
	# itself showing counts.live>0 moments earlier. The schedule-status check
	# is authoritative and decoupled from that report's own timing, so either
	# source saying "live" is enough.
	if _mlb_has_live_game_via_report(date_str):
		return True
	return _mlb_has_live_game_via_schedule(date_str)


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


def _nba_has_live_game(date_str: str) -> bool:
	path = data_root() / "nba_source" / "source_artifacts" / "data" / "processed" / "live_snapshots" / f"live_state_{date_str}.jsonl"
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


def _nhl_has_live_game(date_str: str) -> bool:
	path = data_root() / "nhl_source" / "source_artifacts" / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv"
	if not path.exists():
		return False
	try:
		with path.open("r", encoding="utf-8", newline="") as handle:
			rows = list(csv.DictReader(handle))
	except Exception:
		return False
	return any(str(row.get("gameState") or "").strip().upper() in {"LIVE", "CRIT"} for row in rows)


_LIVE_STATUS_CHECKERS = {
	"mlb": _mlb_has_live_game,
	"wnba": _wnba_has_live_game,
	"nba": _nba_has_live_game,
	"nhl": _nhl_has_live_game,
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


def _lineup_check_interval_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_LINEUP_CHECK_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw or 1800)
	except Exception:
		value = 1800
	return max(300, int(value))


def _last_lineup_check_path() -> Path:
	return _meta_dir() / "last_lineup_check.json"


def _read_last_lineup_check() -> dict[str, Any]:
	payload = read_json_file(_last_lineup_check_path())
	return payload if isinstance(payload, dict) else {}


def _record_lineup_check(epoch: float, date_str: str, fingerprints: dict[str, str | None]) -> None:
	write_json_file(
		_last_lineup_check_path(),
		{"epoch": epoch, "date": date_str, "fingerprints": fingerprints, "recordedAt": _utc_now()},
	)


def _vendor_source_root(sport: str) -> Path:
	return REPO_ROOT / "vendor" / f"{sport}_betting_repo"


def _vendor_worker_env(source_root: Path) -> dict[str, str]:
	env = dict(os.environ)
	src_dir = str(source_root / "src")
	existing = str(env.get("PYTHONPATH") or "").strip()
	env["PYTHONPATH"] = src_dir if not existing else f"{src_dir}{os.pathsep}{existing}"
	env.setdefault("PYTHONUNBUFFERED", "1")
	return env


def _fetch_injuries(sport: str, date_str: str, *, package_name: str, timeout_s: float = 90.0) -> bool:
	source_root = _vendor_source_root(sport)
	if not source_root.exists():
		return False
	python_exe = sys.executable if (sys.executable and Path(sys.executable).exists()) else "python"
	try:
		result = subprocess.run(
			[python_exe, "-m", f"{package_name}.cli", "fetch-injuries", "--date", date_str],
			cwd=str(source_root),
			env=_vendor_worker_env(source_root),
			capture_output=True,
			text=True,
			timeout=timeout_s,
		)
		return result.returncode == 0
	except Exception:
		return False


def _hash_file_bytes(path: Path) -> str | None:
	try:
		if not path.exists() or not path.is_file():
			return None
		digest = hashlib.sha256()
		with path.open("rb") as handle:
			for chunk in iter(lambda: handle.read(65536), b""):
				digest.update(chunk)
		return digest.hexdigest()
	except Exception:
		return None


def _basketball_lineup_injury_fingerprint(sport: str, date_str: str) -> str | None:
	# The vendored CLI writes through <sport>_BETTING_DATA_ROOT
	# (= data_root()/<sport>_source/data on Render), while older bootstrap
	# artifacts live under the source_artifacts-nested variant. Hash both so
	# the change-detection actually sees the files fetch-injuries just wrote
	# -- fingerprinting only the source_artifacts path meant a fresh injury
	# report never changed the fingerprint and never forced a resim.
	base = data_root() / f"{sport}_source"
	parts = [
		_hash_file_bytes(base / "data" / "raw" / "injuries.csv"),
		_hash_file_bytes(base / "data" / "processed" / f"league_status_{date_str}.csv"),
		_hash_file_bytes(base / "source_artifacts" / "data" / "raw" / "injuries.csv"),
		_hash_file_bytes(base / "source_artifacts" / "data" / "processed" / f"league_status_{date_str}.csv"),
	]
	if all(part is None for part in parts):
		return None
	return "|".join(part or "" for part in parts)


def _nba_lineup_injury_fingerprint(date_str: str) -> str | None:
	return _basketball_lineup_injury_fingerprint("nba", date_str)


def _wnba_lineup_injury_fingerprint(date_str: str) -> str | None:
	return _basketball_lineup_injury_fingerprint("wnba", date_str)


_LINEUP_INJURY_FETCH_PACKAGES = {
	"nba": "nba_betting",
	"wnba": "wnba_betting",
}


def _event_sim_force_window_minutes() -> int:
	raw = str(os.environ.get("SYNDICATE_EVENT_SIM_FORCE_WINDOW_MINUTES") or "").strip()
	try:
		value = int(raw or 30)
	except Exception:
		value = 30
	return max(0, value)


def _any_gated_sport_event_within_force_window(date_str: str, *, now_epoch: float) -> bool:
	# Schedule-aware replacement for the retired GHA pipeline's per-event
	# "forceWithinMinutes" policy: near a scheduled tip-off, re-check the
	# lineup/injury fingerprint on every tick instead of waiting out the
	# normal interval, so a late scratch isn't missed for up to 30 minutes.
	# This only tightens *how often we check* -- it doesn't force a resim by
	# itself; _should_force_sim_rerun still only returns True when the
	# fingerprint (or date) actually changed.
	window_minutes = _event_sim_force_window_minutes()
	if window_minutes <= 0:
		return False
	for sport in _LINEUP_INJURY_FETCH_PACKAGES:
		try:
			events = fetch_schedule_for_date(sport, date_str)
			if events_starting_within(events, now_epoch=now_epoch, window_minutes=window_minutes):
				return True
		except Exception:
			continue
	return False


def _should_force_sim_rerun(*, now_epoch: float, date_str: str) -> bool:
	interval = _lineup_check_interval_seconds()
	last = _read_last_lineup_check()
	last_epoch = float(last.get("epoch") or 0.0)
	last_date = str(last.get("date") or "")
	within_tip_off_window = _any_gated_sport_event_within_force_window(date_str, now_epoch=now_epoch)
	if not within_tip_off_window and last_epoch > 0.0 and last_date == date_str and (now_epoch - last_epoch) < interval:
		return False
	for sport, package_name in _LINEUP_INJURY_FETCH_PACKAGES.items():
		_fetch_injuries(sport, date_str, package_name=package_name)
	current_fingerprints = {
		"nba": _nba_lineup_injury_fingerprint(date_str),
		"wnba": _wnba_lineup_injury_fingerprint(date_str),
	}
	stored_fingerprints = last.get("fingerprints") if isinstance(last.get("fingerprints"), dict) else {}
	changed = last_date != date_str or any(
		current_fingerprints.get(sport) != stored_fingerprints.get(sport)
		for sport in current_fingerprints
	)
	_record_lineup_check(now_epoch, date_str, current_fingerprints)
	return changed


# ---------------------------------------------------------------------------
# MLB daily sim: the one piece of the retired GHA daily-update pipeline that
# has no equivalent on the always-on worker path today (NBA/WNBA prediction
# generation already runs here; MLB's vendored Monte Carlo sim did not).
# Gated behind SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER (default off) for a
# dark-launch/shadow rollout alongside the still-running GHA pipeline.
# ---------------------------------------------------------------------------

def _mlb_daily_sim_enabled() -> bool:
	return _env_bool("SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER", default=False)


def _mlb_sim_check_interval_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_SIM_CHECK_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw or 600)
	except Exception:
		value = 600
	return max(60, value)


def _mlb_sim_timeout_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_SIM_TIMEOUT_SECONDS") or "").strip()
	try:
		value = int(raw or 2700)
	except Exception:
		value = 2700
	return max(60, value)


def _mlb_sim_count() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_SIM_COUNT") or "").strip()
	try:
		value = int(raw or 1000)
	except Exception:
		value = 1000
	return max(1, value)


def _mlb_sim_workers() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_SIM_WORKERS") or "").strip()
	try:
		value = int(raw or 2)
	except Exception:
		value = 2
	return max(1, value)


def _last_mlb_sim_check_path() -> Path:
	return _meta_dir() / "last_mlb_sim_check.json"


def _read_last_mlb_sim_check() -> dict[str, Any]:
	payload = read_json_file(_last_mlb_sim_check_path())
	return payload if isinstance(payload, dict) else {}


def _record_mlb_sim_check(epoch: float, date_str: str, fingerprint: str | None, *, launched: bool) -> None:
	write_json_file(
		_last_mlb_sim_check_path(),
		{"epoch": epoch, "date": date_str, "fingerprint": fingerprint, "launched": bool(launched), "recordedAt": _utc_now()},
	)


def _mlb_daily_summary_path(date_str: str) -> Path:
	date_slug = date_str.replace("-", "_")
	return data_root() / "mlb_source" / "source_artifacts" / "data" / "daily" / f"daily_summary_{date_slug}.json"


def _mlb_sim_input_fingerprint(date_str: str) -> str | None:
	root = data_root() / "mlb_source" / "source_artifacts" / "data"
	date_slug = date_str.replace("-", "_")
	parts = [
		_hash_file_bytes(root / "daily" / "lineups_last_known_by_team.json"),
		_hash_file_bytes(root / "market" / "oddsapi" / f"oddsapi_game_lines_{date_slug}.json"),
		_hash_file_bytes(root / "manager" / "probable_pitcher_overrides.json"),
	]
	if all(part is None for part in parts):
		return None
	return "|".join(part or "" for part in parts)


def _mlb_daily_sim_decision(*, now_epoch: float, date_str: str) -> dict[str, Any]:
	if not _mlb_daily_sim_enabled():
		return {"force": False, "reason": "disabled"}
	try:
		events = fetch_schedule_for_date("mlb", date_str)
	except Exception:
		events = []
	if not events:
		return {"force": False, "reason": "no_games_scheduled"}

	if not _mlb_daily_summary_path(date_str).exists():
		return {"force": True, "reason": "first_appearance"}

	window_minutes = _event_sim_force_window_minutes()
	if window_minutes > 0 and events_starting_within(events, now_epoch=now_epoch, window_minutes=window_minutes):
		return {"force": True, "reason": "tip_off_window"}

	last = _read_last_mlb_sim_check()
	last_epoch = float(last.get("epoch") or 0.0)
	last_date = str(last.get("date") or "")
	interval = _mlb_sim_check_interval_seconds()
	if last_epoch > 0.0 and last_date == date_str and (now_epoch - last_epoch) < interval:
		return {"force": False, "reason": "within_check_interval"}

	current_fingerprint = _mlb_sim_input_fingerprint(date_str)
	stored_fingerprint = last.get("fingerprint") if last_date == date_str else None
	if current_fingerprint != stored_fingerprint:
		_record_mlb_sim_check(now_epoch, date_str, current_fingerprint, launched=True)
		return {"force": True, "reason": "fingerprint_change"}

	_record_mlb_sim_check(now_epoch, date_str, current_fingerprint, launched=False)
	return {"force": False, "reason": "no_change"}


def _launch_mlb_daily_sim(date_str: str, decision: dict[str, Any]) -> dict[str, Any]:
	command = [
		sys.executable if (sys.executable and Path(sys.executable).exists()) else "python",
		str(REPO_ROOT / "scripts" / "run_mlb_daily_sim_job.py"),
		"--date", date_str,
		"--season", str(int(date_str[:4])),
		"--sims", str(_mlb_sim_count()),
		"--workers", str(_mlb_sim_workers()),
		"--reason", str(decision.get("reason") or ""),
	]
	popen_kwargs: dict[str, Any] = {"cwd": str(REPO_ROOT)}
	if os.name == "nt":
		popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
	else:
		popen_kwargs["start_new_session"] = True
	try:
		process = subprocess.Popen(command, **popen_kwargs)
		print(f"[live_refresh_loop] MLB_DAILY_SIM_TRIGGERED date={date_str} reason={decision.get('reason')} pid={process.pid}", flush=True)
		return {"ok": True, "pid": process.pid, "command": command, "reason": decision.get("reason")}
	except Exception as exc:
		return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "reason": decision.get("reason")}


# ---------------------------------------------------------------------------
# Look-ahead: proactively warm tomorrow's slate during idle ticks instead of
# only reacting once central_today_iso() rolls over to a new date. Reuses the
# same schedule_adapter helpers as the MLB tip-off-window check above (they
# already accept an arbitrary date_str), and the same single-active-refresh
# guard launch_refresh_run already enforces, so a look-ahead launch that
# collides with the day's own tick just skips gracefully like any other tick.
# ---------------------------------------------------------------------------

def _look_ahead_enabled() -> bool:
	# Defaults off, matching _mlb_daily_sim_enabled()'s dark-launch posture for
	# the same class of feature (replacing a piece of the GHA daily-update
	# cron): flip SYNDICATE_LOOK_AHEAD_ENABLED on once logs confirm it behaves
	# as expected.
	return _env_bool("SYNDICATE_LOOK_AHEAD_ENABLED", default=False)


def _look_ahead_interval_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_LOOK_AHEAD_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw or 3600)
	except Exception:
		value = 3600
	return max(300, value)


def _last_look_ahead_check_path() -> Path:
	return _meta_dir() / "last_look_ahead_check.json"


def _read_last_look_ahead_check() -> dict[str, Any]:
	payload = read_json_file(_last_look_ahead_check_path())
	return payload if isinstance(payload, dict) else {}


def _record_look_ahead_check(epoch: float, date_str: str, *, launched: bool) -> None:
	write_json_file(
		_last_look_ahead_check_path(),
		{"epoch": epoch, "date": date_str, "launched": bool(launched), "recordedAt": _utc_now()},
	)


def _look_ahead_target_date(selected_date: str) -> str:
	return (date.fromisoformat(selected_date) + timedelta(days=1)).isoformat()


def _look_ahead_has_scheduled_games(date_str: str, *, sports: str | None) -> bool:
	configured = [item.strip().lower() for item in (sports or "").split(",") if item.strip()] if sports else list(_LIVE_STATUS_CHECKERS.keys())
	for sport in configured:
		try:
			if fetch_schedule_for_date(sport, date_str):
				return True
		except Exception:
			continue
	return False


def _look_ahead_decision(*, now_epoch: float, selected_date: str, any_live: bool | None) -> dict[str, Any]:
	if not _look_ahead_enabled():
		return {"launch": False, "reason": "disabled"}
	if any_live:
		# Never compete with a live tick for the container's resources.
		return {"launch": False, "reason": "sport_currently_live"}
	target_date = _look_ahead_target_date(selected_date)
	last = _read_last_look_ahead_check()
	last_epoch = float(last.get("epoch") or 0.0)
	last_date = str(last.get("date") or "")
	interval = _look_ahead_interval_seconds()
	if last_epoch > 0.0 and last_date == target_date and (now_epoch - last_epoch) < interval:
		return {"launch": False, "reason": "within_check_interval", "date": target_date}
	if not _look_ahead_has_scheduled_games(target_date, sports=_live_refresh_loop_sports()):
		_record_look_ahead_check(now_epoch, target_date, launched=False)
		return {"launch": False, "reason": "no_games_scheduled", "date": target_date}
	_record_look_ahead_check(now_epoch, target_date, launched=True)
	return {"launch": True, "reason": "warm_next_day_slate", "date": target_date}


def _launch_look_ahead_refresh(decision: dict[str, Any]) -> dict[str, Any]:
	target_date = str(decision.get("date") or "")
	try:
		result = launch_refresh_run(
			date=target_date,
			sports=_live_refresh_loop_sports(),
			phase="pregame",
			regions=_live_refresh_loop_regions(),
			mode=_live_refresh_loop_mode(),
			execution_mode=_live_refresh_loop_execution_mode(),
			launch_mode=_live_refresh_loop_launch_mode(),
			skip_mirror=bool(_live_refresh_loop_skip_mirror()),
			mirror_only=False,
			dry_run=False,
			force_refresh=False,
		)
		print(f"[live_refresh_loop] LOOK_AHEAD_TRIGGERED date={target_date} reason={decision.get('reason')}", flush=True)
		return {"ok": True, "launched": True, "date": target_date, "result": result, "reason": decision.get("reason")}
	except ValueError as exc:
		# Same single-active-refresh guard the main tick already respects --
		# skip gracefully and retry next interval rather than erroring.
		return {"ok": False, "launched": False, "skipped": True, "date": target_date, "error": str(exc)}
	except Exception as exc:
		return {"ok": False, "launched": False, "date": target_date, "error": f"{type(exc).__name__}: {exc}"}


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


# Pregame relaunch cooldown: defense-in-depth against the retry-storm
# confirmed in production on 2026-07-16 -- the outer worker loop's fixed 60s
# sleep (now fixed separately, see run_live_odds_refresh_worker.py) let every
# tick relaunch the full predict-date + SmartSim pipeline before the previous
# cold-start attempt (20-30+ minutes) could finish, so a cold WNBA/MLB slate
# never completed. This cooldown applies independently of that fix and of
# _assert_no_active_refresh_run's own PID-based guard, so a pregame relaunch
# is blocked for a fixed window after the last attempt regardless of whether
# that guard correctly detects an in-flight detached subprocess.
def _pregame_relaunch_cooldown_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_PREGAME_RELAUNCH_COOLDOWN_SECONDS") or "").strip()
	try:
		value = int(raw or 1800)
	except Exception:
		value = 1800
	return max(0, value)


def _last_pregame_launch_path() -> Path:
	return _meta_dir() / "last_pregame_refresh_launch.json"


def _read_last_pregame_launch() -> dict[str, Any]:
	payload = read_json_file(_last_pregame_launch_path())
	return payload if isinstance(payload, dict) else {}


def _record_pregame_launch(epoch: float, date_str: str) -> None:
	write_json_file(_last_pregame_launch_path(), {"epoch": epoch, "date": date_str, "recordedAt": _utc_now()})


def _pregame_relaunch_blocked(*, now_epoch: float, date_str: str) -> bool:
	cooldown = _pregame_relaunch_cooldown_seconds()
	if cooldown <= 0:
		return False
	last = _read_last_pregame_launch()
	last_epoch = float(last.get("epoch") or 0.0)
	last_date = str(last.get("date") or "")
	return last_epoch > 0.0 and last_date == date_str and (now_epoch - last_epoch) < cooldown


def _run_live_refresh_tick() -> dict[str, Any]:
	tick_started_epoch = datetime.now(timezone.utc).timestamp()
	adaptive_enabled = _live_refresh_loop_adaptive_enabled()
	any_live = _any_tracked_sport_game_live() if adaptive_enabled else None
	effective_phase = ("live" if any_live else "pregame") if adaptive_enabled else _live_refresh_loop_phase()
	selected_date = central_today_iso()
	force_sim_rerun = _should_force_sim_rerun(now_epoch=tick_started_epoch, date_str=selected_date)
	effective_mode = "full" if force_sim_rerun else _live_refresh_loop_mode()
	meta = {
		"startedAt": _utc_now(),
		"date": selected_date,
		"phase": effective_phase,
		"adaptive": adaptive_enabled,
		"anyLive": bool(any_live) if adaptive_enabled else None,
		"regions": _live_refresh_loop_regions(),
		"executionMode": _live_refresh_loop_execution_mode(),
		"mode": effective_mode,
		"simRerunTriggered": force_sim_rerun,
		"skipMirror": bool(_live_refresh_loop_skip_mirror()),
		"sports": _live_refresh_loop_sports() or "active",
	}

	# MLB daily sim is dispatched independently of the odds-refresh call below:
	# its cadence/gate differs from NBA/WNBA's, and the vendor script's own
	# PID lock (not ops_refresh's single-active-refresh assertion) is the
	# correct concurrency guard for it. The launched wrapper publishes its own
	# results synchronously on completion (see run_mlb_daily_sim_job.py), so
	# this tick's publish sweep below doesn't need to account for it.
	try:
		mlb_decision = _mlb_daily_sim_decision(now_epoch=tick_started_epoch, date_str=selected_date)
		if mlb_decision.get("force"):
			meta["mlbDailySim"] = _launch_mlb_daily_sim(selected_date, mlb_decision)
		else:
			meta["mlbDailySim"] = {"launched": False, "reason": mlb_decision.get("reason")}
	except Exception as exc:
		meta["mlbDailySim"] = {"launched": False, "error": f"{type(exc).__name__}: {exc}"}
	if effective_phase == "pregame" and _pregame_relaunch_blocked(now_epoch=tick_started_epoch, date_str=selected_date):
		meta["ok"] = False
		meta["skipped"] = True
		meta["error"] = "pregame refresh relaunch blocked by cooldown (previous attempt still within cooldown window)"
	else:
		if effective_phase == "pregame":
			_record_pregame_launch(tick_started_epoch, selected_date)
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
				force_refresh=force_sim_rerun,
			)
			meta["ok"] = True
			meta["result"] = result
			if force_sim_rerun:
				print(f"[live_refresh_loop] LINEUP_INJURY_CHANGE_RESIM_TRIGGERED date={meta['date']} phase={meta['phase']}", flush=True)
		except ValueError as exc:
			meta["ok"] = False
			meta["skipped"] = True
			meta["error"] = str(exc)
		except Exception as exc:
			meta["ok"] = False
			meta["error"] = f"{type(exc).__name__}: {exc}"

	# Look-ahead: while idle, proactively warm tomorrow's slate instead of only
	# reacting once central_today_iso() rolls over. Independent of the above
	# today-scoped launch -- a collision with it (or with the day's own tick)
	# is handled by launch_refresh_run's existing single-active-refresh guard.
	try:
		look_ahead_decision = _look_ahead_decision(now_epoch=tick_started_epoch, selected_date=selected_date, any_live=any_live)
		if look_ahead_decision.get("launch"):
			meta["lookAhead"] = _launch_look_ahead_refresh(look_ahead_decision)
		else:
			meta["lookAhead"] = {"ok": False, "launched": False, "reason": look_ahead_decision.get("reason")}
	except Exception as exc:
		meta["lookAhead"] = {"ok": False, "launched": False, "error": f"{type(exc).__name__}: {exc}"}

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