from __future__ import annotations

import atexit
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.artifact_publisher import sweep_changed_hot_artifacts
from syndicate.features.shared.ops_refresh import _active_sports_for_date
from syndicate.features.shared.ops_refresh import is_refresh_run_active
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.schedule_adapter import events_starting_within
from syndicate.features.shared.schedule_adapter import fetch_schedule_for_date
from syndicate.features.shared.schedule_adapter import ScheduleEvent
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import read_json_file_result
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.refresh_state_store import write_text_file
from syndicate.features.shared.source_roots import repo_root_from
from syndicate.features.shared.timezone import central_datetime_from_epoch
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
# Captured once at import time -- i.e. "when this container/process started."
# refresh-worker runs as a single instance (no horizontal scaling in
# render.yaml), so a shared active-run pointer whose started_at predates this
# process's own start can only have been written by a previous, now-dead
# container. That's a strictly more certain signal than PID+cmdline
# comparison for the cross-container-restart case specifically -- confirmed
# in production 2026-07-21: a container only 14 seconds past its own deploy
# already reported "previous_run_still_active" from a pointer that had to
# predate it, suggesting the PID/cmdline check alone wasn't reliably
# detecting staleness across a full container restart.
_PROCESS_STARTED_AT = datetime.now(timezone.utc)


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


def _espn_has_live_game(sport: str, date_str: str, *, timeout_s: float = 12.0) -> bool:
	# Independent, authoritative fallback for the same class of bug fixed for
	# MLB above: each sport's _has_live_game check below trusts a locally
	# written artifact from a decoupled process (its own live-state/odds
	# tick), and if that process's rebuild cadence lags actual game state,
	# the adaptive phase decision silently starves live games of live odds
	# with no error surfaced anywhere. ESPN's public scoreboard API is
	# already used for exactly this purpose elsewhere in this repo (see
	# syndicate/features/wnba/cards.py's _public_scoreboard_live_state_payload).
	helper = REPO_ROOT / "scripts" / "fetch_espn_live_status_for_date.py"
	if not helper.exists():
		return False
	python_exe = sys.executable if (sys.executable and Path(sys.executable).exists()) else "python"
	try:
		result = subprocess.run(
			[python_exe, str(helper), "--sport", sport, "--date", date_str],
			cwd=str(REPO_ROOT),
			capture_output=True,
			text=True,
			timeout=timeout_s,
		)
		if result.returncode != 0:
			return False
		payload = json.loads(result.stdout or "{}")
		live_event_ids = payload.get("live_event_ids") if isinstance(payload, dict) else None
		return isinstance(live_event_ids, list) and len(live_event_ids) > 0
	except Exception:
		return False


def _wnba_has_live_game_via_artifact(date_str: str) -> bool:
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


def _wnba_has_live_game(date_str: str) -> bool:
	if _wnba_has_live_game_via_artifact(date_str):
		return True
	return _espn_has_live_game("wnba", date_str)


def _nba_has_live_game_via_artifact(date_str: str) -> bool:
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


def _nba_has_live_game(date_str: str) -> bool:
	if _nba_has_live_game_via_artifact(date_str):
		return True
	return _espn_has_live_game("nba", date_str)


def _nhl_has_live_game_via_artifact(date_str: str) -> bool:
	path = data_root() / "nhl_source" / "source_artifacts" / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv"
	if not path.exists():
		return False
	try:
		with path.open("r", encoding="utf-8", newline="") as handle:
			rows = list(csv.DictReader(handle))
	except Exception:
		return False
	return any(str(row.get("gameState") or "").strip().upper() in {"LIVE", "CRIT"} for row in rows)


def _nhl_has_live_game(date_str: str) -> bool:
	if _nhl_has_live_game_via_artifact(date_str):
		return True
	return _espn_has_live_game("nhl", date_str)


def _nfl_has_live_game(date_str: str) -> bool:
	# No local live-state artifact of their own (unlike WNBA/NBA/NHL/soccer
	# above) -- NFL/NCAAF's own refresh steps aren't date-scoped so they've
	# never needed one. ESPN's scoreboard is the only signal, same as it is
	# for every sport above as a fallback.
	return _espn_has_live_game("nfl", date_str)


def _ncaaf_has_live_game(date_str: str) -> bool:
	return _espn_has_live_game("ncaaf", date_str)


def _soccer_has_live_game_via_artifact(league: str, date_str: str) -> bool:
	# poll_soccer_live_state.py writes {"count": len(games), ...} per
	# league/date -- same fast local-artifact-first shape as the WNBA/NBA
	# checks above, before falling back to ESPN's scoreboard.
	path = data_root() / "soccer_source" / league / "api" / "live_state" / f"live_state_{date_str}.json"
	payload = read_json_file(path)
	if not isinstance(payload, dict):
		return False
	try:
		return int(payload.get("count") or 0) > 0
	except (TypeError, ValueError):
		return False


def _soccer_has_live_game(date_str: str) -> bool:
	# Soccer is 10 independently-scheduled leagues, not one competition --
	# only check leagues currently in season (see
	# syndicate/features/soccer/sources.py's active_leagues_for_date), same
	# scoping _build_soccer_steps() in refresh_odds_sources.py already uses.
	try:
		from syndicate.features.soccer.sources import active_leagues_for_date
		leagues = active_leagues_for_date(date_str)
	except Exception:
		leagues = []
	for league in leagues:
		if _soccer_has_live_game_via_artifact(league, date_str):
			return True
		if _espn_has_live_game(league, date_str):
			return True
	return False


_LIVE_STATUS_CHECKERS = {
	"mlb": _mlb_has_live_game,
	"wnba": _wnba_has_live_game,
	"nba": _nba_has_live_game,
	"nhl": _nhl_has_live_game,
	"soccer": _soccer_has_live_game,
	"nfl": _nfl_has_live_game,
	"ncaaf": _ncaaf_has_live_game,
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


def _read_csv_rows_lenient(path: Path) -> list[dict[str, str]]:
	try:
		if not path.exists() or not path.is_file():
			return []
		with path.open("r", encoding="utf-8", newline="") as handle:
			return list(csv.DictReader(handle))
	except Exception:
		return []


def _row_team_tricode(row: dict[str, str]) -> str:
	# injuries.csv uses "team" or "team_tri"; league_status_{date}.csv uses
	# "team" (confirmed against the real column names both files' own
	# readers expect -- basketball_props_smart_sim.py's
	# _smart_sim_injuries_excluded_map_for_date_local, lines ~4056/4140/4172).
	# Neither is guaranteed to already be a 3-letter tricode (league_status's
	# reader explicitly normalizes it), so route through the same
	# to_tricode helper the sim engine uses rather than assume the raw value.
	from syndicate.features.shared.basketball_props_smart_sim import _to_tricode_local

	raw = str(row.get("team_tri") or row.get("team") or "").strip()
	if not raw:
		return ""
	return str(_to_tricode_local(raw) or "").strip().upper()


def _wnba_lineup_injury_fingerprint_by_game(date_str: str) -> dict[tuple[str, str], str]:
	# Per-matchup analog of _wnba_lineup_injury_fingerprint above -- that one
	# hashes the WHOLE injuries.csv + league_status_{date}.csv as one
	# sport-wide blob (told you THAT something changed, never WHICH game,
	# same limitation _mlb_sim_input_fingerprint_by_game replaced for MLB).
	# Slices both sources down to one matchup's rows by team tricode --
	# each WNBA team plays at most one game/day, so (home, away) is a
	# sufficient key with zero ScheduleEvent schema changes (unlike MLB,
	# which needed home_team_id/away_team_id added for its numeric-team_id-
	# keyed lineups file).
	try:
		events = fetch_schedule_for_date("wnba", date_str)
	except Exception:
		events = []
	matchups = {
		(str(event.home or "").strip().upper(), str(event.away or "").strip().upper())
		for event in events
		if str(event.home or "").strip() and str(event.away or "").strip()
	}
	if not matchups:
		return {}

	base = data_root() / "wnba_source"
	injuries_rows = _read_csv_rows_lenient(base / "data" / "raw" / "injuries.csv") + _read_csv_rows_lenient(
		base / "source_artifacts" / "data" / "raw" / "injuries.csv"
	)
	status_rows = _read_csv_rows_lenient(base / "data" / "processed" / f"league_status_{date_str}.csv") + _read_csv_rows_lenient(
		base / "source_artifacts" / "data" / "processed" / f"league_status_{date_str}.csv"
	)

	fingerprints: dict[tuple[str, str], str] = {}
	for home, away in matchups:
		team_set = {home, away}
		injuries_slice = [row for row in injuries_rows if _row_team_tricode(row) in team_set]
		status_slice = [row for row in status_rows if _row_team_tricode(row) in team_set]
		fingerprints[(home, away)] = _hash_json_value({"injuries": injuries_slice, "status": status_slice})
	return fingerprints


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


# Side channel for _run_live_refresh_tick to learn WHICH sport(s) actually
# changed on the most recent _should_force_sim_rerun call, without changing
# that function's plain-bool contract -- ~18 existing tests mock it directly
# with return_value=True/False and must keep working unchanged. Populated as
# a side effect; a caller that only cares about the bool never needs this.
_LAST_LINEUP_INJURY_CHANGED_SPORTS: set[str] = set()

# WNBA-only per-matchup counterpart, isolated from the sport-level channel
# above deliberately -- generalizing this to also cover NBA would be a
# bigger, riskier diff than an isolated side channel a WNBA-blind code path
# can't be affected by, and this file already caused two incidents tonight
# (an OOM crash and a WNBA-candidates-zeroed bug). None means "unscoped" --
# no prior per-matchup record to diff against, the diff failed, or wnba
# didn't change at all this tick -- which correctly means "resim the whole
# slate," matching the fails-open posture used throughout.
_LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS: set[tuple[str, str]] | None = None


def _last_wnba_lineup_injury_changed_matchups() -> set[tuple[str, str]] | None:
	return set(_LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS) if _LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS is not None else None


def _last_wnba_matchup_lineup_check_path() -> Path:
	return _meta_dir() / "last_wnba_matchup_lineup_check.json"


def _read_last_wnba_matchup_lineup_check() -> dict[str, Any]:
	payload = read_json_file(_last_wnba_matchup_lineup_check_path())
	return payload if isinstance(payload, dict) else {}


def _record_wnba_matchup_lineup_check(epoch: float, date_str: str, fingerprints: dict[tuple[str, str], str]) -> None:
	# Tuple keys serialized as "HOME-AWAY" strings -- same hyphen convention
	# as the --only-matchups/--wnba-only-matchups CLI flags (Phase 1), and
	# JSON can't hold tuple keys anyway.
	write_json_file(
		_last_wnba_matchup_lineup_check_path(),
		{
			"epoch": epoch,
			"date": date_str,
			"fingerprints": {f"{home}-{away}": value for (home, away), value in fingerprints.items()},
			"recordedAt": _utc_now(),
		},
	)


def _should_force_sim_rerun(*, now_epoch: float, date_str: str) -> bool:
	global _LAST_LINEUP_INJURY_CHANGED_SPORTS
	global _LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS
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
	is_new_date = last_date != date_str
	changed_sports = {
		sport
		for sport in current_fingerprints
		if is_new_date or current_fingerprints.get(sport) != stored_fingerprints.get(sport)
	}
	# A new date marks every sport "changed" above so the resim-forcing
	# behavior (changed_sports/the return value) correctly rechecks
	# everything on day rollover -- but that's not a real injury/lineup news
	# event, so it must not feed the board-callout signal below, or every
	# sport would get falsely tagged "news-driven" once per day regardless
	# of whether anything actually happened.
	genuinely_changed_sports = {
		sport
		for sport in current_fingerprints
		if not is_new_date and current_fingerprints.get(sport) != stored_fingerprints.get(sport)
	}
	_LAST_LINEUP_INJURY_CHANGED_SPORTS = changed_sports

	# WNBA per-matchup narrowing: only worth computing when the sport-level
	# hash above actually moved (also naturally skips this on every
	# unchanged tick, keeping the added cost near-zero). Exception-swallowed
	# so a failure here can never break the plain-bool contract this
	# function has always had.
	_LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS = None
	if "wnba" in changed_sports:
		try:
			current_matchup_fp = _wnba_lineup_injury_fingerprint_by_game(date_str)
			last_matchup_record = _read_last_wnba_matchup_lineup_check()
			stored_matchup_fp_raw = (
				last_matchup_record.get("fingerprints") if str(last_matchup_record.get("date") or "") == date_str else None
			)
			if not isinstance(stored_matchup_fp_raw, dict):
				# No prior per-matchup record for today (first time seen,
				# date rollover, or pre-migration gap) -- don't know WHICH
				# game(s) changed, so stay unscoped (whole-slate resim),
				# same posture MLB's _mlb_daily_sim_decision takes when
				# stored_fingerprints isn't a dict.
				_LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS = None
			else:
				stored_matchup_fp = {
					tuple(key.split("-", 1)): value for key, value in stored_matchup_fp_raw.items() if "-" in key
				}
				_LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS = {
					matchup
					for matchup, current_hash in current_matchup_fp.items()
					if stored_matchup_fp.get(matchup) != current_hash
				}
			_record_wnba_matchup_lineup_check(now_epoch, date_str, current_matchup_fp)
			# Staged rollout (see the WNBA single-game sim scoping plan): this
			# is observation-only for now -- logged so production behavior
			# can be watched over a real slate before _run_live_refresh_tick
			# is wired to actually pass this through to launch_refresh_run.
			print(
				f"[live_refresh_loop] WNBA_MATCHUP_FINGERPRINT_DIFF "
				f"changed={sorted(_LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS) if _LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS is not None else None} "
				f"total_matchups={len(current_matchup_fp)}",
				flush=True,
			)
		except Exception:
			_LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS = None

	_record_lineup_check(now_epoch, date_str, current_fingerprints)
	if genuinely_changed_sports:
		_record_lineup_injury_change_epochs(genuinely_changed_sports, now_epoch=now_epoch)
	return bool(changed_sports)


def _last_lineup_injury_changed_sports() -> set[str]:
	return set(_LAST_LINEUP_INJURY_CHANGED_SPORTS)


def _lineup_injury_change_epochs_path() -> Path:
	return _meta_dir() / "last_lineup_injury_change_epochs.json"


def _read_lineup_injury_change_epochs() -> dict[str, float]:
	payload = read_json_file(_lineup_injury_change_epochs_path())
	changed_at_epoch = payload.get("changed_at_epoch") if isinstance(payload, dict) else None
	if not isinstance(changed_at_epoch, dict):
		return {}
	result: dict[str, float] = {}
	for sport, epoch in changed_at_epoch.items():
		if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
			result[str(sport)] = float(epoch)
	return result


def _record_lineup_injury_change_epochs(changed_sports: set[str], *, now_epoch: float) -> None:
	if not changed_sports:
		return
	existing = _read_lineup_injury_change_epochs()
	existing.update({sport: now_epoch for sport in changed_sports})
	write_json_file(_lineup_injury_change_epochs_path(), {"changed_at_epoch": existing, "recordedAt": _utc_now()})


def _news_triggered_window_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_INTELLIGENCE_NEWS_TRIGGERED_WINDOW_SECONDS") or "").strip()
	try:
		value = int(raw or 3600)
	except Exception:
		value = 3600
	return max(60, value)


def sports_with_recent_lineup_injury_change(*, now_epoch: float | None = None, within_seconds: int | None = None) -> set[str]:
	# Cross-process read of plan item 1F0's deferred board callout signal:
	# which sport(s) had a detected injury/lineup fingerprint change recently
	# enough that a candidate whose line/projection just moved should say so
	# distinctly ("news-driven"), instead of looking like an ordinary
	# market-driven move. _LAST_LINEUP_INJURY_CHANGED_SPORTS above is an
	# in-memory, single-tick, single-process signal (live-odds-worker); this
	# persists the epoch of each sport's last detected change to disk so the
	# board-building/scoring code (a different process/container) can ask
	# "was this recent enough to still matter" independently of exactly when
	# the tick that detected it ran.
	resolved_now = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
	resolved_window = within_seconds if within_seconds is not None else _news_triggered_window_seconds()
	epochs = _read_lineup_injury_change_epochs()
	return {sport for sport, changed_epoch in epochs.items() if 0.0 <= (resolved_now - changed_epoch) <= resolved_window}


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


# SYNDICATE_MLB_SIM_TIMEOUT_SECONDS is read where it is actually enforced --
# scripts/run_mlb_daily_sim_job.py's _timeout_seconds(), which passes it to
# subprocess.run() and kills a hung sim. A duplicate reader used to live here
# and was never called by anything, which made the var look wired up when
# nothing enforced it; the only real ceiling was the stale-pointer
# _MLB_SIM_MAX_RUNTIME_SECONDS below, and that is a different concept (when to
# stop trusting a "running" record, not when to kill the child).


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


def _record_mlb_sim_check(epoch: float, date_str: str, fingerprints: dict[str, str], *, launched: bool) -> None:
	# Schema note: this used to store a single "fingerprint" string (one hash
	# for the whole slate). Now stores "fingerprints", a {game_pk: hash} dict,
	# so a per-game diff is possible. See _mlb_daily_sim_decision's migration
	# handling for reading old-schema records left over from before this.
	write_json_file(
		_last_mlb_sim_check_path(),
		{"epoch": epoch, "date": date_str, "fingerprints": dict(fingerprints), "launched": bool(launched), "recordedAt": _utc_now()},
	)


def _mlb_daily_summary_path(date_str: str) -> Path:
	date_slug = date_str.replace("-", "_")
	return data_root() / "mlb_source" / "source_artifacts" / "data" / "daily" / f"daily_summary_{date_slug}.json"


# ---------------------------------------------------------------------------
# Cold-start batching. tip_off_window/fingerprint_change/join_mismatch already
# scope their runs to the affected game(s) via --only-game-pks; the remaining
# full-slate paths (first_appearance, and the one-time "no stored
# fingerprints" case) deliberately passed no game_pks, meaning one process
# simulated the entire ~15-game slate at _mlb_sim_count() sims each. That is
# the run that OOM-killed the 2GB worker on 2026-07-25. Rather than introduce
# a second mechanism, this splits the cold start into successive batches fed
# through the SAME --only-game-pks path the scoped triggers already use.
# ---------------------------------------------------------------------------

# DEFAULT 0 = OFF, deliberately. The batching below is correct and tested, but
# it cannot be turned on until vendor/mlb_bettingv2/tools/daily_update.py stops
# truncating the daily summary on a scoped run: non-targeted games hit
# `continue` at daily_update.py:6814 BEFORE `outputs.append(record)` (:7756),
# so summary["outputs"] (:7787) ends up containing only the targeted games.
# syndicate/features/mlb/cards.py:4629 builds the whole board from that key,
# so every scoped resim currently drops the rest of the slate off the board --
# which also looks like the real mechanism behind the long-standing
# "board count swings 184 -> 10" flakiness. Batching the cold start would fire
# that bug on every batch. Flip this to 4 (or set
# SYNDICATE_MLB_SIM_MAX_GAMES_PER_RUN) only after preserved_non_targeted_games
# is merged back into summary["outputs"].
_MLB_SIM_MAX_GAMES_PER_RUN_DEFAULT = 0


def _mlb_sim_max_games_per_run() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_SIM_MAX_GAMES_PER_RUN") or "").strip()
	try:
		if raw:
			# 0 (or negative) restores the old unscoped whole-slate behavior,
			# kept as an escape hatch for a bigger container.
			return max(0, int(raw))
	except Exception:
		pass
	return _MLB_SIM_MAX_GAMES_PER_RUN_DEFAULT


def _mlb_sim_coldstart_progress_path() -> Path:
	return _meta_dir() / "mlb_sim_coldstart_progress.json"


def _read_mlb_sim_coldstart_progress(date_str: str) -> list[str]:
	payload = read_json_file(_mlb_sim_coldstart_progress_path())
	if not isinstance(payload, dict) or str(payload.get("date") or "") != date_str:
		return []
	attempted = payload.get("attempted_game_pks")
	if not isinstance(attempted, list):
		return []
	return [str(item).strip() for item in attempted if str(item or "").strip()]


def _record_mlb_sim_coldstart_batch(date_str: str, attempted_game_pks: list[str]) -> None:
	write_json_file(
		_mlb_sim_coldstart_progress_path(),
		{"date": date_str, "attempted_game_pks": sorted(set(attempted_game_pks)), "updatedAt": _utc_now()},
	)


def _next_mlb_sim_coldstart_batch(date_str: str, events: list[ScheduleEvent]) -> list[str]:
	"""Next slice of the slate to cold-start sim, or [] to mean "whole slate"
	when batching is disabled.

	Tracks only what has been ATTEMPTED, never what succeeded -- the summary
	artifact is written once at the end of a full run, so there is no
	per-batch success signal to read here. A batch that dies mid-run is
	therefore not retried immediately; once every game has been attempted the
	progress resets and the next pass picks them up again. That keeps a
	genuinely broken slate from spinning at full speed while still converging,
	and the existing _mlb_recent_sim_attempt_within_backoff cooldown paces the
	batches apart.
	"""
	batch_size = _mlb_sim_max_games_per_run()
	if batch_size <= 0:
		return []
	all_game_pks = sorted({str(event.event_id).strip() for event in events if str(event.event_id or "").strip()})
	if not all_game_pks or len(all_game_pks) <= batch_size:
		return []
	attempted = set(_read_mlb_sim_coldstart_progress(date_str))
	remaining = [game_pk for game_pk in all_game_pks if game_pk not in attempted]
	if not remaining:
		# Full pass finished without producing a summary -- start over rather
		# than wedging on a slate we can never mark complete.
		attempted = set()
		remaining = all_game_pks
	batch = remaining[:batch_size]
	_record_mlb_sim_coldstart_batch(date_str, sorted(attempted | set(batch)))
	return batch


_MLB_SIM_ATTEMPT_BACKOFF_SECONDS = 180

# Confirmed live 2026-07-25: re-enabling SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER
# on a container already sitting at ~1.1GB of its 2GB limit OOM-killed the
# worker within ~40s of boot, three times in a row. The backoff above only
# spaces the retries out; it does nothing to make the run fit. This is the
# missing half: refuse to launch at all unless there is genuinely enough
# headroom for the sim subprocess, measured from cgroups rather than assumed.
# Same helper the intelligence-state pipeline and the odds-refresh gate use.
_MLB_SIM_MIN_MEMORY_HEADROOM_BYTES_DEFAULT = 900 * 1024 * 1024


def _mlb_sim_min_memory_headroom_bytes() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_SIM_MIN_MEMORY_HEADROOM_MB") or "").strip()
	try:
		if raw:
			return max(0, int(raw)) * 1024 * 1024
	except Exception:
		pass
	return _MLB_SIM_MIN_MEMORY_HEADROOM_BYTES_DEFAULT


def _mlb_sim_memory_headroom_snapshot() -> dict[str, Any] | None:
	try:
		from syndicate.features.shared.memory_observability import memory_headroom_snapshot

		return memory_headroom_snapshot(_mlb_sim_min_memory_headroom_bytes())
	except Exception:
		return None


def _mlb_recent_sim_attempt_within_backoff(date_str: str) -> bool:
	# _mlb_daily_sim_decision's "first_appearance" branch only checks whether
	# the summary artifact exists -- that file is written when a sim run
	# *finishes*, not when it starts. If the container gets OOM-killed (or
	# otherwise dies) mid-run, the summary never gets written, so every
	# restart sees the same missing-summary state and immediately relaunches
	# the same full, unscoped (all games) 1000-sim job -- which can itself
	# take long enough to contribute to another OOM before finishing. That's
	# a self-reinforcing crash loop with zero cooldown between attempts.
	# This reads a marker dedicated to backoff tracking, NOT the active-run
	# pointer (_mlb_sim_active_pointer_path): _mlb_daily_sim_process_still_running
	# runs before this check on every call and clears that pointer to {} the
	# moment it confirms the previous process is dead (correct for its own
	# purpose -- don't let a stale pointer block future runs forever) -- but
	# that means by the time a crashed run reaches this branch, the active
	# pointer has *already* been wiped by the very liveness check that ran
	# moments earlier, making a backoff read of it always empty in exactly
	# the crash-loop case this function exists to catch. The last-attempt
	# marker is written at the same moment as the active pointer but nothing
	# else ever clears it, so it survives that liveness check intact.
	try:
		meta = read_json_file(_mlb_sim_last_attempt_marker_path())
	except Exception:
		return False
	if not isinstance(meta, dict) or not meta:
		return False
	if str(meta.get("date") or "") != date_str:
		return False
	started_at = str(meta.get("started_at") or "")
	try:
		started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00")) if started_at else None
	except Exception:
		started_dt = None
	if started_dt is None:
		return False
	age_seconds = (datetime.now(timezone.utc) - started_dt).total_seconds()
	return 0.0 <= age_seconds < _MLB_SIM_ATTEMPT_BACKOFF_SECONDS


def _read_json_file_lenient(path: Path) -> Any | None:
	try:
		if not path.exists() or not path.is_file():
			return None
		return json.loads(path.read_text(encoding="utf-8"))
	except Exception:
		return None


def _hash_json_value(value: Any) -> str:
	try:
		encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
	except Exception:
		encoded = repr(value).encode("utf-8", errors="replace")
	return hashlib.sha256(encoded).hexdigest()


def _mlb_sim_fingerprint_includes_odds_prices() -> bool:
	# Escape hatch to restore the pre-#48 behaviour if some artifact turns out
	# to bake prices at sim time after all.
	return _env_bool("SYNDICATE_MLB_SIM_FINGERPRINT_INCLUDE_ODDS_PRICES", default=False)


def _mlb_sim_odds_fingerprint_slice(rows: list[dict[str, Any]]) -> list[Any]:
	"""Reduce a game's odds rows to what a RESIM should react to.

	#48. The gate hashed these rows verbatim and so fired on essentially every
	odds refresh -- measured triggering roughly every 10 minutes all day on
	2026-07-24, exactly matching _mlb_sim_check_interval_seconds, which is the
	signature of "the hash flips every time we look".

	The key question is what a simulation's inputs actually ARE, and the
	answer is in daily_update.py's own summary row: game_pk, teams,
	starter_names, per-segment win probabilities, run distributions, HR and
	prop likelihoods. No odds. No prices. No edges. Prices are joined to sim
	output at READ time by the market board (join_odds_to_sim), so a price
	move is already reflected on the board without re-running anything.

	So a price move cannot change a single value the sim produces, and three
	things are excluded here, none of them a simulation input:

	- prices (*_odds). Removed outright rather than rounded. Bucketing was
	  tried first and is only probabilistic -- a -125 -> -128 tick still
	  crosses a bucket boundary -- which treats a design question as a tuning
	  knob. Exclusion makes the behaviour deterministic and testable.
	- bookmaker identity. _best_bookmaker_game_lines picks a book by market
	  coverage, so the winner rotates as books post and pull markets. A book
	  swap quoting the same lines is not news to the sim.
	- row ordering. Rows came off the artifact in file order, which is not
	  guaranteed stable, so an identical set of odds in a different order
	  flipped the hash by itself.

	LINE values (spread/total points) are KEPT and exact. A total moving
	8.5 -> 9 changes what is being bet and legitimately warrants a resim, and
	it is also what the prop/target artifacts key off.
	"""
	include_prices = _mlb_sim_fingerprint_includes_odds_prices()
	reduced: list[Any] = []
	for row in rows:
		if not isinstance(row, dict):
			continue
		markets = row.get("markets") if isinstance(row.get("markets"), dict) else {}
		markets_slice: dict[str, Any] = {}
		for market_name, market in sorted(markets.items()):
			if not isinstance(market, dict):
				continue
			entry: dict[str, Any] = {}
			for field, value in sorted(market.items()):
				if field.endswith("_odds") and not include_prices:
					continue
				entry[field] = value
			markets_slice[str(market_name)] = entry
		reduced.append(markets_slice)
	# Deterministic order so an unchanged set of odds always hashes the same.
	reduced.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
	return reduced


def _mlb_sim_input_fingerprint_by_game(date_str: str, events: list[ScheduleEvent]) -> dict[str, str]:
	# Was a single whole-file-hash blob covering all 3 sources at once (see
	# git history) -- told you THAT something changed, never WHICH game, so
	# every fingerprint_change trigger resimmed the entire day's slate. This
	# slices each source down to one game's inputs so only the actually-
	# changed game(s) need resimming.
	root = data_root() / "mlb_source" / "source_artifacts" / "data"
	date_slug = date_str.replace("-", "_")
	lineups_doc = _read_json_file_lenient(root / "daily" / "lineups_last_known_by_team.json")
	if not isinstance(lineups_doc, dict):
		lineups_doc = {}
	odds_doc = _read_json_file_lenient(root / "market" / "oddsapi" / f"oddsapi_game_lines_{date_slug}.json")
	odds_games = odds_doc.get("games") if isinstance(odds_doc, dict) and isinstance(odds_doc.get("games"), list) else []
	overrides_doc = _read_json_file_lenient(root / "manager" / "probable_pitcher_overrides.json")
	overrides_for_date = overrides_doc.get(date_str) if isinstance(overrides_doc, dict) else None
	if not isinstance(overrides_for_date, dict):
		overrides_for_date = {}

	odds_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
	for row in odds_games:
		if isinstance(row, dict):
			key = (str(row.get("home_team") or "").strip(), str(row.get("away_team") or "").strip())
			odds_by_pair.setdefault(key, []).append(row)

	fingerprints: dict[str, str] = {}
	for event in events:
		game_pk = str(event.event_id or "").strip()
		if not game_pk:
			continue
		if event.home_team_id is not None and event.away_team_id is not None:
			lineup_slice: Any = {
				"home": lineups_doc.get(str(event.home_team_id)),
				"away": lineups_doc.get(str(event.away_team_id)),
			}
		else:
			# Degraded fallback (team ids not resolvable, e.g. a schedule
			# fetch that predates this deploy still cached): fall back to the
			# WHOLE lineups file for just this game -- over-inclusive (may
			# flag this game "changed" when a different team's lineup moved)
			# but never under-inclusive, and still scoped to one game rather
			# than today's whole-slate behavior.
			lineup_slice = {"__whole_file__": lineups_doc}
		# Reduced rather than verbatim (#48): see
		# _mlb_sim_odds_fingerprint_slice for why hashing raw odds rows made
		# this fire on nearly every refresh.
		odds_slice = _mlb_sim_odds_fingerprint_slice(odds_by_pair.get((event.home, event.away), []))
		override_slice = overrides_for_date.get(game_pk, {})
		fingerprints[game_pk] = _hash_json_value({"lineups": lineup_slice, "odds": odds_slice, "overrides": override_slice})
	return fingerprints


def _mlb_join_mismatch_game_pks(date_str: str) -> list[str]:
	# Phase 4 of the Layer 1 plan: the market board's odds<->sim join
	# (market_inventory.join_odds_to_sim) already detects a needs-resim
	# mismatch directly from the current odds/sim data itself -- a probable
	# pitcher swap the fingerprint diff below might not catch if the
	# lineups/overrides artifacts lag behind the odds feed. This is purely
	# additive on top of that existing mechanism, so any failure here must
	# never break the fingerprint-based trigger that already works.
	try:
		from syndicate.features.mlb.cards import mlb_needs_resim_game_pks

		return mlb_needs_resim_game_pks(date_str)
	except Exception:
		return []


def _intelligence_pipeline_busy() -> bool:
	# #55, sim side. The pipeline yielding to a resident sim is only half the
	# bound: at boot the pipeline starts FIRST and this gate fires ~5s later,
	# so the pipeline never sees a sim and both run. Confirmed in production
	# 2026-07-25 -- the worker OOM-looped with pipeline_defers=0.
	#
	# Imported lazily: pipeline.intelligence_state imports this module (also
	# lazily) for the mirror-image check, so a module-level import either way
	# would be a cycle.
	if not _env_bool("SYNDICATE_MLB_SIM_DEFER_TO_INTELLIGENCE", default=True):
		return False
	try:
		from pipeline.intelligence_state import intelligence_pipeline_busy

		return bool(intelligence_pipeline_busy())
	except Exception:
		# Never let this check be the reason a slate goes unsimmed.
		return False


def _max_consecutive_pipeline_defers() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_SIM_MAX_PIPELINE_DEFERS") or "").strip()
	try:
		value = int(raw or 5)
	except ValueError:
		value = 5
	return max(1, value)


def _last_pipeline_defer_state_path() -> Path:
	return _meta_dir() / "last_mlb_sim_pipeline_defer.json"


def _sim_pipeline_deferral_reason(*, now_epoch: float, date_str: str) -> str | None:
	"""Should the sim yield to the board build right now, or has it waited
	long enough that yielding has become starvation?

	The original #55 comment claimed this "costs at most one tick: the
	pipeline's run is finite". That was wrong in production and it is worth
	being precise about why, because the same mistake was made twice today in
	mirror image. An individual board build IS finite (~4 minutes, measured
	01:23:21 -> 01:27:23). Its DUTY CYCLE is not: it re-queues on a 60s
	interval, so it is busy far more often than it is idle. Finite-per-run
	does not imply finite-in-aggregate, and an unbounded wait on a
	near-continuous producer is equivalent to being switched off -- measured
	as 30 of 30 consecutive gate decisions returning intelligence_pipeline_busy
	with no sim launching at all.

	So the wait is bounded exactly as the board build's wait on the odds
	refresh is. Past the bound the question stops being "is the pipeline busy"
	and becomes the one that matters: is there memory for both. At 4GB there
	usually is -- sim ~1674MB plus board ~1479MB is ~3.2GB -- which is
	precisely the headroom the upgrade bought.

	Persisted rather than in-memory: this decision runs on the tick path and
	the counter has to survive across ticks, and across the restarts that
	deploys cause.
	"""
	if not _intelligence_pipeline_busy():
		if _read_pipeline_defer_count(date_str) > 0:
			_write_pipeline_defer_count(date_str, 0, now_epoch)
		return None

	defers = _read_pipeline_defer_count(date_str)
	if defers < _max_consecutive_pipeline_defers():
		_write_pipeline_defer_count(date_str, defers + 1, now_epoch)
		return "intelligence_pipeline_busy"

	headroom = _mlb_sim_memory_headroom_snapshot()
	if headroom is not None and headroom.get("sufficient"):
		print(
			f"[live_refresh_loop] SIM_PROCEEDING_DESPITE_BUSY_PIPELINE defers={defers} "
			f"{json.dumps(headroom, sort_keys=True)}",
			flush=True,
		)
		_write_pipeline_defer_count(date_str, 0, now_epoch)
		return None
	# Genuinely no room. Keep deferring, but say so distinctly -- "waiting
	# politely" and "cannot fit" are different problems and should not share
	# one reason string.
	return "intelligence_pipeline_busy_and_no_headroom"


def _read_pipeline_defer_count(date_str: str) -> int:
	payload = read_json_file(_last_pipeline_defer_state_path())
	if not isinstance(payload, dict) or str(payload.get("date") or "") != date_str:
		return 0
	try:
		return max(0, int(payload.get("count") or 0))
	except (TypeError, ValueError):
		return 0


def _write_pipeline_defer_count(date_str: str, count: int, now_epoch: float) -> None:
	try:
		write_json_file(
			_last_pipeline_defer_state_path(),
			{"date": date_str, "count": int(count), "epoch": float(now_epoch), "recordedAt": _utc_now()},
		)
	except Exception:
		pass


def _mlb_daily_sim_decision(*, now_epoch: float, date_str: str) -> dict[str, Any]:
	if not _mlb_daily_sim_enabled():
		return {"force": False, "reason": "disabled"}
	pipeline_deferral = _sim_pipeline_deferral_reason(now_epoch=now_epoch, date_str=date_str)
	if pipeline_deferral is not None:
		return {"force": False, "reason": pipeline_deferral}
	if _mlb_daily_sim_process_still_running():
		# A previously launched sim subprocess is still alive. Every other
		# branch below (first_appearance, tip_off_window, fingerprint_change)
		# would just relaunch and immediately bounce off daily_update.py's own
		# run lock -- harmless, but on a slate with lineups posting throughout
		# pregame this fired on nearly every tick, each one spawning a doomed
		# subprocess purely to print "already holds the lock" and exit.
		return {"force": False, "reason": "previous_run_still_active"}
	try:
		if is_refresh_run_active():
			# Don't stack the sim's 1000-game Monte Carlo run + multi-profile
			# target generation on top of an in-flight odds refresh (which can
			# itself spawn WNBA SmartSim) -- confirmed OOM signature was two
			# independent heavy pipelines peaking concurrently in the same
			# container. One extra tick of delay here is cheap; a container
			# restart mid-sim is not.
			return {"force": False, "reason": "odds_refresh_active"}
	except Exception:
		pass
	# Memory gate: every branch below can return force=True and spawn the sim
	# subprocess, so check once here rather than at each return. A None
	# snapshot means headroom couldn't be measured (e.g. local dev without
	# cgroups) -- memory_headroom_snapshot's own contract says callers should
	# treat that as "not sufficient", but doing so here would make the sim
	# never run outside a container, so this only blocks on a measured
	# shortfall and leaves unmeasurable environments alone.
	headroom = _mlb_sim_memory_headroom_snapshot()
	if headroom is not None and not headroom.get("sufficient", True):
		print(f"[live_refresh_loop] MLB_DAILY_SIM_DEFERRED_LOW_MEMORY {json.dumps(headroom, sort_keys=True)}", flush=True)
		return {"force": False, "reason": "insufficient_memory_headroom", "memory": headroom}
	try:
		events = fetch_schedule_for_date("mlb", date_str)
	except Exception:
		events = []
	if not events:
		return {"force": False, "reason": "no_games_scheduled"}

	if not _mlb_daily_summary_path(date_str).exists():
		if _mlb_recent_sim_attempt_within_backoff(date_str):
			return {"force": False, "reason": "recent_attempt_backoff"}
		coldstart_batch = _next_mlb_sim_coldstart_batch(date_str, events)
		if coldstart_batch:
			return {"force": True, "reason": "first_appearance", "game_pks": coldstart_batch, "coldstart_batch": True}
		return {"force": True, "reason": "first_appearance"}

	window_minutes = _event_sim_force_window_minutes()
	if window_minutes > 0:
		starting_soon = events_starting_within(events, now_epoch=now_epoch, window_minutes=window_minutes)
		if starting_soon:
			tip_off_game_pks = sorted({str(event.event_id).strip() for event in starting_soon if str(event.event_id or "").strip()})
			return {"force": True, "reason": "tip_off_window", "game_pks": tip_off_game_pks}

	last = _read_last_mlb_sim_check()
	last_epoch = float(last.get("epoch") or 0.0)
	last_date = str(last.get("date") or "")
	interval = _mlb_sim_check_interval_seconds()
	if last_epoch > 0.0 and last_date == date_str and (now_epoch - last_epoch) < interval:
		return {"force": False, "reason": "within_check_interval"}

	current_fingerprints = _mlb_sim_input_fingerprint_by_game(date_str, events)
	stored_fingerprints = last.get("fingerprints") if last_date == date_str else None
	if not isinstance(stored_fingerprints, dict):
		# Covers three cases uniformly: no prior record at all, a prior record
		# for a different date, and a pre-migration record still holding the
		# old singular "fingerprint" string key (reading .get("fingerprints")
		# on that shape returns None for free). In all three we don't know
		# WHICH game(s) changed, so conservatively resim the whole slate this
		# one time -- the next check onward stores the new per-game shape and
		# scoping applies from then on.
		changed_game_pks = sorted(current_fingerprints.keys())
	else:
		changed_game_pks = sorted(game_pk for game_pk, current_hash in current_fingerprints.items() if stored_fingerprints.get(game_pk) != current_hash)

	# _mlb_join_mismatch_game_pks -> mlb_needs_resim_game_pks ->
	# build_mlb_market_board is a FULL market board build. Confirmed live
	# 2026-07-25: with the trigger enabled this ran on the worker's main loop
	# every sim tick, concurrently with the intelligence pipeline's own
	# _build_candidate_pool in its background thread, and OOM-killed the 2GB
	# container in ~14 seconds -- 355MB to dead, with the sim subprocess never
	# even launching. Two guards, cheapest first:
	#
	# 1. Short-circuit. If the fingerprint diff already found work, we are
	#    simming this tick regardless; the join-mismatch signal can only add
	#    games to a set we are already going to process. Deferring it to a
	#    later tick costs at most one interval of latency on a secondary
	#    trigger, and skips the expensive build entirely on exactly the ticks
	#    where the container is about to get busy.
	# 2. Memory gate. On a quiet slate (no fingerprint change) this still runs
	#    every tick, so gate the build itself on real headroom rather than
	#    only gating the sim launch further up -- that earlier gate measured
	#    ~1.7GB free and passed, because the blowup is here, after it.
	# NOTE: this is a PARTIAL mitigation, not the fix. Skipping the build when
	# headroom is already low helps only when the container is visibly close
	# to the limit; it cannot stop the failure actually observed, where the
	# build itself allocated from 355MB to past 2048MB in ~14 seconds -- any
	# pre-flight measurement passes comfortably right before that. The real
	# fix is to stop doing a full market board build on the main loop at all
	# (cache it, or derive the join-mismatch signal from an artifact the board
	# build already persists). Tracked in #23; deliberately not attempted here
	# because the obvious short-circuit (skip when changed_game_pks is already
	# non-empty) silently drops join-mismatch games from the merged set, which
	# test_mlb_daily_sim_decision_merges_fingerprint_and_join_mismatch_game_pks
	# exists to prevent.
	join_mismatch_game_pks = []
	join_headroom = _mlb_sim_memory_headroom_snapshot()
	if join_headroom is not None and not join_headroom.get("sufficient", True):
		print(
			f"[live_refresh_loop] MLB_JOIN_MISMATCH_CHECK_SKIPPED reason=insufficient_memory_headroom {json.dumps(join_headroom, sort_keys=True)}",
			flush=True,
		)
	else:
		join_mismatch_game_pks = _mlb_join_mismatch_game_pks(date_str)

	if changed_game_pks or join_mismatch_game_pks:
		_record_mlb_sim_check(now_epoch, date_str, current_fingerprints, launched=True)
		merged_game_pks = sorted(set(changed_game_pks) | set(join_mismatch_game_pks))
		reason = "fingerprint_change" if changed_game_pks else "join_mismatch_needs_resim"
		result: dict[str, Any] = {"force": True, "reason": reason, "game_pks": merged_game_pks}
		if join_mismatch_game_pks:
			result["join_mismatch_game_pks"] = join_mismatch_game_pks
		return result

	_record_mlb_sim_check(now_epoch, date_str, current_fingerprints, launched=False)
	return {"force": False, "reason": "no_change"}


def _process_exists(pid: Any) -> bool:
	# Cross-platform PID-liveness probe, mirrored from
	# vendor/mlb_bettingv2/tools/daily_update.py's _acquire_daily_update_run_lock
	# guard (same proven fix applied there for live-odds-worker's stale-lock
	# crash loop earlier this session). Needed here because with
	# WEB_CONCURRENCY>1, the module-level _MLB_SIM_PROCESS handle below is
	# only visible to the gunicorn worker that launched it -- other workers
	# (and any worker after a container restart) have no in-memory signal at
	# all and must verify against the actual OS process table instead.
	try:
		pid_i = int(pid or 0)
	except Exception:
		return False
	if pid_i <= 0:
		return False
	if sys.platform.startswith("win") or os.name == "nt":
		try:
			import ctypes

			PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
			SYNCHRONIZE = 0x00100000
			WAIT_TIMEOUT = 0x00000102
			WAIT_OBJECT_0 = 0x00000000

			kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
			handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid_i)
			if not handle:
				err = ctypes.get_last_error()
				if err == 5:
					return True
				return False
			try:
				wait_code = kernel32.WaitForSingleObject(handle, 0)
				if wait_code == WAIT_TIMEOUT:
					return True
				if wait_code == WAIT_OBJECT_0:
					return False
				return True
			finally:
				kernel32.CloseHandle(handle)
		except Exception:
			return False
	try:
		os.kill(pid_i, 0)
	except PermissionError:
		return True
	except (OSError, SystemError, ValueError):
		return False
	return True


def _process_cmdline(pid: Any) -> list[str] | None:
	try:
		pid_i = int(pid or 0)
	except Exception:
		return None
	if pid_i <= 0:
		return None
	if sys.platform.startswith("win") or os.name == "nt":
		return None
	try:
		raw = Path(f"/proc/{pid_i}/cmdline").read_bytes()
	except Exception:
		return None
	parts = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]
	return parts or None


def _process_matches_lock(pid: Any, expected_command: Any) -> bool:
	"""Guard against PID reuse: a dead sim's PID can be reassigned to an
	unrelated process within minutes on Render's low-PID-churn containers,
	which would make a stale pointer look perpetually "held" via
	_process_exists (a pure liveness probe, no identity check) alone.
	"""
	current = _process_cmdline(pid)
	if current is None:
		# Can't verify (Windows, /proc unavailable, process just exited) --
		# fall back to trusting the existing PID-liveness check alone.
		return True
	expected = expected_command if isinstance(expected_command, list) else []
	if not expected:
		return True
	return [str(part) for part in current] == [str(part) for part in expected]


# Hard ceiling on how long a "running" pointer is trusted regardless of PID
# checks. A real sim run (even a full slate at high sim counts) should
# finish well inside this; anything older is treated as an orphaned/stuck
# record so a fresh launch isn't blocked forever by a hang.
_MLB_SIM_MAX_RUNTIME_SECONDS = 90 * 60


def _mlb_sim_active_pointer_path() -> Path:
	return _mlb_sim_runs_state_dir() / "_active.json"


def _mlb_sim_last_attempt_marker_path() -> Path:
	# Deliberately separate from _mlb_sim_active_pointer_path -- see the
	# comment in _mlb_recent_sim_attempt_within_backoff for why the active
	# pointer can't be reused for this.
	return _mlb_sim_runs_state_dir() / "_last_attempt.json"


def _write_last_attempt_marker(meta: dict[str, Any]) -> None:
	try:
		write_json_file(_mlb_sim_last_attempt_marker_path(), meta)
	except Exception:
		pass


def _write_active_pointer(meta: dict[str, Any]) -> None:
	try:
		write_json_file(_mlb_sim_active_pointer_path(), meta)
	except Exception:
		pass


def _clear_active_pointer(expected_pid: Any = None) -> None:
	try:
		current = read_json_file(_mlb_sim_active_pointer_path())
		if isinstance(current, dict) and expected_pid is not None and int(current.get("pid") or 0) != int(expected_pid or 0):
			# Someone else's run is now the active pointer; don't clobber it.
			return
		write_json_file(_mlb_sim_active_pointer_path(), {})
	except Exception:
		pass


def _shared_mlb_sim_still_running() -> bool:
	"""Cross-worker, restart-safe check: is there a genuinely live sim
	process behind the shared active-run pointer? Falls back to False (safe
	to launch) on any ambiguity -- daily_update.py's own run-lock is the
	backstop against a genuine double-launch race, so a false negative here
	just costs a doomed extra subprocess, not a correctness problem; a false
	positive would silently block every future sim run.
	"""
	try:
		meta = read_json_file(_mlb_sim_active_pointer_path())
	except Exception:
		return False
	if not isinstance(meta, dict) or not meta:
		return False
	pid = meta.get("pid")
	started_at = str(meta.get("started_at") or "")
	try:
		started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00")) if started_at else None
	except Exception:
		started_dt = None
	if started_dt is not None:
		age_seconds = (datetime.now(timezone.utc) - started_dt).total_seconds()
		if age_seconds > _MLB_SIM_MAX_RUNTIME_SECONDS:
			_clear_active_pointer(expected_pid=pid)
			return False
		# A pointer recorded before this very process started can only belong
		# to a previous, now-dead container (single-instance service -- see
		# _PROCESS_STARTED_AT above) -- a definitive signal, unlike PID
		# liveness/cmdline matching, which can false-positive on a reused PID
		# whose /proc/<pid>/cmdline happens to be unreadable during the new
		# container's own early boot.
		if started_dt < _PROCESS_STARTED_AT:
			_clear_active_pointer(expected_pid=pid)
			return False
	if not _process_exists(pid):
		_clear_active_pointer(expected_pid=pid)
		return False
	if not _process_matches_lock(pid, meta.get("command")):
		_clear_active_pointer(expected_pid=pid)
		return False
	return True


_MLB_SIM_PROCESS: subprocess.Popen | None = None
_MLB_SIM_LOG_HANDLE: Any = None
_MLB_SIM_LOG_PATH: Path | None = None
_MLB_SIM_RUN_META: dict[str, Any] | None = None


def _mlb_sim_log_dir() -> Path:
	override = str(os.environ.get("SYNDICATE_MLB_SIM_LOG_DIR") or "").strip()
	path = Path(override) if override else Path(tempfile.gettempdir()) / "syndicate_mlb_sim_logs"
	path.mkdir(parents=True, exist_ok=True)
	return path


def _mlb_sim_runs_state_dir() -> Path:
	return reports_root() / "live_refresh_loop" / "mlb_sim_runs"


def _persist_finished_mlb_sim_run(*, state: str = "finished") -> None:
	# The worker's own stdout/stderr is the only place a sim subprocess's
	# traceback lives, and the web service has no way to see it directly (no
	# shared disk, no Render log API). _launch_mlb_daily_sim captures the
	# subprocess's output to a local file; this copies it into the shared
	# (Redis-backed) state store the moment we notice the process has exited,
	# so /api/ops/live-refresh/state?sim_date=&sim_run= can surface it remotely.
	global _MLB_SIM_LOG_HANDLE, _MLB_SIM_LOG_PATH, _MLB_SIM_RUN_META, _MLB_SIM_PROCESS
	meta = _MLB_SIM_RUN_META
	if meta is None:
		return
	try:
		if _MLB_SIM_LOG_HANDLE is not None:
			try:
				_MLB_SIM_LOG_HANDLE.close()
			except Exception:
				pass
		log_text = ""
		if _MLB_SIM_LOG_PATH is not None and _MLB_SIM_LOG_PATH.exists():
			try:
				log_text = _MLB_SIM_LOG_PATH.read_text(encoding="utf-8", errors="replace")
			except Exception:
				log_text = ""
		date_str = str(meta.get("date") or "")
		run_stamp = str(meta.get("run_stamp") or "")
		sim_base = _mlb_sim_runs_state_dir()
		if log_text:
			write_text_file(sim_base / f"{date_str}_{run_stamp}.log", log_text[-40000:])
		returncode = _MLB_SIM_PROCESS.returncode if _MLB_SIM_PROCESS is not None else None
		status_payload = dict(meta)
		status_payload["state"] = state
		status_payload["exit_code"] = returncode
		status_payload["finished_at"] = _utc_now()
		write_json_file(sim_base / f"{date_str}_{run_stamp}_status.json", status_payload)
		_clear_active_pointer(expected_pid=meta.get("pid"))
	except Exception:
		pass
	finally:
		_MLB_SIM_LOG_HANDLE = None
		_MLB_SIM_LOG_PATH = None
		_MLB_SIM_RUN_META = None


def _mlb_local_sim_run_is_stale() -> bool:
	# Mirrors the age check _shared_mlb_sim_still_running already applies to
	# the cross-container pointer -- confirmed missing here in production
	# 2026-07-24/25: a worker-launched sim that hangs without exiting keeps
	# .poll() returning None forever, so mlbDailySim reported
	# "previous_run_still_active" on every tick for 27+ minutes straight with
	# zero sim-job log output, permanently blocking that date's sim.
	meta = _MLB_SIM_RUN_META
	if not isinstance(meta, dict):
		return False
	started_at = str(meta.get("started_at") or "")
	try:
		started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00")) if started_at else None
	except Exception:
		started_dt = None
	if started_dt is None:
		return False
	age_seconds = (datetime.now(timezone.utc) - started_dt).total_seconds()
	return age_seconds > _MLB_SIM_MAX_RUNTIME_SECONDS


def _kill_stale_mlb_sim_process() -> None:
	global _MLB_SIM_PROCESS
	process = _MLB_SIM_PROCESS
	meta = _MLB_SIM_RUN_META
	if process is not None:
		try:
			process.kill()
			process.wait(timeout=5)
		except Exception:
			pass
	if isinstance(meta, dict):
		print(
			f"[live_refresh_loop] MLB_DAILY_SIM_TIMEOUT date={meta.get('date')} pid={meta.get('pid')} "
			f"run_stamp={meta.get('run_stamp')} max_runtime_seconds={_MLB_SIM_MAX_RUNTIME_SECONDS}",
			flush=True,
		)
	_persist_finished_mlb_sim_run(state="timed_out")
	_MLB_SIM_PROCESS = None


def _mlb_daily_sim_process_still_running() -> bool:
	global _MLB_SIM_PROCESS
	if _MLB_SIM_PROCESS is not None:
		# Fast path: this worker holds the actual Popen handle for a sim it
		# launched itself, so its own .poll() is the most direct signal.
		try:
			still_running = _MLB_SIM_PROCESS.poll() is None
		except Exception:
			still_running = False
		if not still_running:
			_persist_finished_mlb_sim_run()
			_MLB_SIM_PROCESS = None
			return False
		# A live .poll() only proves the process hasn't exited -- it says
		# nothing about whether it's still making progress. Apply the same
		# _MLB_SIM_MAX_RUNTIME_SECONDS ceiling the shared-pointer fallback
		# below already enforces, so a hung subprocess this worker launched
		# itself can't block every future daily-sim tick forever.
		if _mlb_local_sim_run_is_stale():
			_kill_stale_mlb_sim_process()
			return False
		return True
	# No local handle -- either this worker never launched a sim, or a
	# container restart wiped the in-memory state. Either way, fall back to
	# the shared, PID-verified pointer so a sim launched by a different
	# gunicorn worker (or by this same worker before a restart) is still
	# correctly detected, instead of silently allowing a second sim to stack
	# on top of it.
	return _shared_mlb_sim_still_running()


def _launch_mlb_daily_sim(date_str: str, decision: dict[str, Any]) -> dict[str, Any]:
	global _MLB_SIM_PROCESS, _MLB_SIM_LOG_HANDLE, _MLB_SIM_LOG_PATH, _MLB_SIM_RUN_META
	run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
	command = [
		sys.executable if (sys.executable and Path(sys.executable).exists()) else "python",
		str(REPO_ROOT / "scripts" / "run_mlb_daily_sim_job.py"),
		"--date", date_str,
		"--season", str(int(date_str[:4])),
		"--sims", str(_mlb_sim_count()),
		"--workers", str(_mlb_sim_workers()),
		"--reason", str(decision.get("reason") or ""),
	]
	game_pks = decision.get("game_pks")
	if isinstance(game_pks, (list, tuple, set)) and game_pks:
		# Present for tip_off_window/fingerprint_change/join_mismatch so only
		# the actually-impacted game(s) get resimmed, and (since 2026-07-25)
		# for first_appearance too, where _next_mlb_sim_coldstart_batch feeds
		# the slate through here a batch at a time instead of as one process
		# covering every game -- that unscoped run is what OOM-killed the 2GB
		# worker. Still absent for evening-next-day, and for first_appearance
		# on a slate small enough to fit in one batch.
		normalized_game_pks = sorted({str(game_pk).strip() for game_pk in game_pks if str(game_pk or "").strip()})
		if normalized_game_pks:
			command.extend(["--only-game-pks", ",".join(normalized_game_pks)])
	popen_kwargs: dict[str, Any] = {"cwd": str(REPO_ROOT)}
	if os.name == "nt":
		popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
	else:
		popen_kwargs["start_new_session"] = True
	log_path = _mlb_sim_log_dir() / f"{date_str}_{run_stamp}.log"
	log_handle: Any = None
	try:
		log_handle = open(log_path, "wb")
		popen_kwargs["stdout"] = log_handle
		popen_kwargs["stderr"] = subprocess.STDOUT
	except Exception:
		log_handle = None
	try:
		process = subprocess.Popen(command, **popen_kwargs)
		_MLB_SIM_PROCESS = process
		_MLB_SIM_LOG_HANDLE = log_handle
		_MLB_SIM_LOG_PATH = log_path if log_handle is not None else None
		_MLB_SIM_RUN_META = {
			"date": date_str,
			"run_stamp": run_stamp,
			"pid": process.pid,
			"reason": decision.get("reason"),
			"command": command,
			"started_at": _utc_now(),
		}
		try:
			write_json_file(_mlb_sim_runs_state_dir() / f"{date_str}_{run_stamp}_status.json", {**_MLB_SIM_RUN_META, "state": "running"})
		except Exception:
			pass
		_write_active_pointer(dict(_MLB_SIM_RUN_META))
		_write_last_attempt_marker(dict(_MLB_SIM_RUN_META))
		print(f"[live_refresh_loop] MLB_DAILY_SIM_TRIGGERED date={date_str} reason={decision.get('reason')} pid={process.pid} run_stamp={run_stamp}", flush=True)
		return {"ok": True, "pid": process.pid, "command": command, "reason": decision.get("reason"), "run_stamp": run_stamp}
	except Exception as exc:
		if log_handle is not None:
			try:
				log_handle.close()
			except Exception:
				pass
		return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "reason": decision.get("reason")}


# ---------------------------------------------------------------------------
# Evening next-day sim: with the GHA daily-update cron reduced to backup-only,
# nothing simmed tomorrow's slate until the date-rollover first_appearance
# gate fired after midnight Central -- fine for correctness, but it meant
# tomorrow's board never populated the evening before the way the old cron's
# --build-next-day step used to. This reuses the exact same sim launch path
# as the regular daily-sim gate (_launch_mlb_daily_sim / the shared
# _MLB_SIM_PROCESS tracking), just pointed at tomorrow's date and gated to a
# configurable evening window instead of firing all day.
# ---------------------------------------------------------------------------

def _mlb_evening_next_day_sim_enabled() -> bool:
	# Dark-launch default off, same posture as every other piece of the
	# worker-centric replacement for the GHA cron in this file.
	return _env_bool("SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_ENABLED", default=False)


def _mlb_evening_next_day_sim_start_hour() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_START_HOUR") or "").strip()
	try:
		value = int(raw or 18)
	except Exception:
		value = 18
	return max(0, min(23, value))


def _mlb_evening_next_day_sim_decision(*, now_epoch: float, selected_date: str, any_live: bool | None) -> dict[str, Any]:
	if not _mlb_evening_next_day_sim_enabled():
		return {"force": False, "reason": "disabled"}
	if any_live:
		# Same posture as look-ahead: never compete with a live tick for the
		# container's resources.
		return {"force": False, "reason": "sport_currently_live"}
	local_hour = central_datetime_from_epoch(now_epoch).hour
	if local_hour < _mlb_evening_next_day_sim_start_hour():
		return {"force": False, "reason": "before_evening_window"}
	if _mlb_daily_sim_process_still_running():
		# Covers both "today's sim is still running" and "we already launched
		# tomorrow's sim earlier this evening and it's still going" -- either
		# way, don't stack a second sim job on the same box.
		return {"force": False, "reason": "previous_run_still_active"}
	try:
		if is_refresh_run_active():
			return {"force": False, "reason": "odds_refresh_active"}
	except Exception:
		pass
	target_date = _look_ahead_target_date(selected_date)
	if _mlb_daily_summary_path(target_date).exists():
		return {"force": False, "reason": "already_simmed"}
	try:
		events = fetch_schedule_for_date("mlb", target_date)
	except Exception:
		events = []
	if not events:
		return {"force": False, "reason": "no_games_scheduled"}
	return {"force": True, "reason": "evening_next_day_sim", "date": target_date}


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


def _read_last_look_ahead_check() -> tuple[dict[str, Any], bool]:
	# Returns (payload, read_ok). Must use read_json_file_result (not plain
	# read_json_file) so a transient keyvalue-backend read failure is
	# distinguishable from "never checked before" -- confirmed in production
	# 2026-07-24: the plain-read version let this interval gate get silently
	# defeated, producing 8 look-ahead relaunches for the same target date in
	# 5 hours (several only 6-30 minutes apart, well under the configured
	# 3600s interval), which stacked overlapping refresh_odds_sources.py runs
	# for that date and left it with zero completed sim/odds rows all day.
	# Mirrors _assert_refresh_manifest_read_ok's existing fail-closed pattern
	# for the same class of bug in the sibling concurrency guard.
	payload, ok = read_json_file_result(_last_look_ahead_check_path())
	return (payload if isinstance(payload, dict) else {}), ok


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
	last, read_ok = _read_last_look_ahead_check()
	if not read_ok:
		# Fail closed: a keyvalue-store read failure must never be treated as
		# "never checked before" -- see _read_last_look_ahead_check's comment.
		return {"launch": False, "reason": "state_read_failed", "date": target_date}
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


# Second day of the look-ahead window (selected_date + 2), extending warm-up
# coverage to a full 48 hours as requested -- e.g. a WNBA slate starting
# tomorrow evening previously wasn't warmed until the day itself rolled
# over. Kept as fully separate functions/state file from the day-1 ones
# above (rather than adding a days_ahead parameter to them) so the existing
# day-1 tests' exact call-signature assertions can't be broken by this.

def _look_ahead_window_enabled() -> bool:
	return _env_bool("SYNDICATE_LOOK_AHEAD_48H_ENABLED", default=True)


def _look_ahead_target_date_day2(selected_date: str) -> str:
	return (date.fromisoformat(selected_date) + timedelta(days=2)).isoformat()


def _last_look_ahead_check_day2_path() -> Path:
	return _meta_dir() / "last_look_ahead_check_day2.json"


def _read_last_look_ahead_check_day2() -> tuple[dict[str, Any], bool]:
	# See _read_last_look_ahead_check's comment -- same fail-closed fix.
	payload, ok = read_json_file_result(_last_look_ahead_check_day2_path())
	return (payload if isinstance(payload, dict) else {}), ok


def _record_look_ahead_check_day2(epoch: float, date_str: str, *, launched: bool) -> None:
	write_json_file(
		_last_look_ahead_check_day2_path(),
		{"epoch": epoch, "date": date_str, "launched": bool(launched), "recordedAt": _utc_now()},
	)


def _look_ahead_decision_day2(*, now_epoch: float, selected_date: str, any_live: bool | None) -> dict[str, Any]:
	if not _look_ahead_enabled() or not _look_ahead_window_enabled():
		return {"launch": False, "reason": "disabled"}
	if any_live:
		return {"launch": False, "reason": "sport_currently_live"}
	target_date = _look_ahead_target_date_day2(selected_date)
	last, read_ok = _read_last_look_ahead_check_day2()
	if not read_ok:
		return {"launch": False, "reason": "state_read_failed", "date": target_date}
	last_epoch = float(last.get("epoch") or 0.0)
	last_date = str(last.get("date") or "")
	interval = _look_ahead_interval_seconds()
	if last_epoch > 0.0 and last_date == target_date and (now_epoch - last_epoch) < interval:
		return {"launch": False, "reason": "within_check_interval", "date": target_date}
	if not _look_ahead_has_scheduled_games(target_date, sports=_live_refresh_loop_sports()):
		_record_look_ahead_check_day2(now_epoch, target_date, launched=False)
		return {"launch": False, "reason": "no_games_scheduled", "date": target_date}
	_record_look_ahead_check_day2(now_epoch, target_date, launched=True)
	return {"launch": True, "reason": "warm_day_after_next_slate", "date": target_date}


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


def _live_refresh_loop_effective_sports(selected_date: str) -> list[str]:
	# Mirrors launch_refresh_run's own sports resolution (configured override,
	# else season-active-for-date) so the WNBA-exclusion split below sees
	# exactly the same sport set the unscoped call would have covered.
	configured = _live_refresh_loop_sports()
	resolved = configured if configured else _active_sports_for_date(selected_date)
	return [piece.strip().lower() for piece in resolved.split(",") if piece.strip()]


def _live_refresh_loop_sports_excluding_wnba(selected_date: str) -> str | None:
	# 2026-07-19 incident: the sim-vs-refresh mutex is a blanket gate over the
	# whole combined sports call, but the actual measured OOM risk (WNBA's
	# refresh leg spiking ~1.3-1.5GB RSS) is specific to WNBA. On a live MLB
	# slate with staggered tip-offs, an MLB sim can stay resident almost
	# continuously for hours, and gating everything on it starved MLB's own
	# (much cheaper) odds refresh for 3+ hours straight even though nothing
	# about refreshing MLB itself risks the OOM the mutex exists to prevent.
	# Used only when the mutex would otherwise block the whole tick -- the
	# normal (no sim contention) path still launches the full combined set
	# unchanged.
	sports = [sport for sport in _live_refresh_loop_effective_sports(selected_date) if sport != "wnba"]
	return ",".join(sports) if sports else None


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


def _last_odds_refresh_launch_path() -> Path:
	return _meta_dir() / "last_odds_refresh_launch.json"


def _read_last_odds_refresh_launch() -> dict[str, Any]:
	payload = read_json_file(_last_odds_refresh_launch_path())
	return payload if isinstance(payload, dict) else {}


def _record_odds_refresh_launch(epoch: float) -> None:
	write_json_file(_last_odds_refresh_launch_path(), {"epoch": epoch, "recordedAt": _utc_now()})


def _odds_refresh_starvation_override_enabled() -> bool:
	# Off by default -- reverted 2026-07-18 after confirming in production
	# that "force through past N minutes" reintroduces the exact
	# stack-two-heavy-pipelines OOM the sim-mutex gate exists to prevent,
	# every time it fires, not just occasionally: WNBA's refresh leg alone
	# has been measured spiking to ~1.3-1.5GB RSS in this 2048MB container,
	# and a live MLB sim's process tree resident alongside it (~300-400MB)
	# plus worker/wrapper overhead (~400-450MB) leaves no safe headroom for
	# that spike at ANY ceiling length while a sim is genuinely still
	# running -- and sims chain back-to-back for hours on a live slate, so
	# "genuinely still running" is true almost continuously. A stale board
	# is the safer failure mode than an OOM crash-loop; this flag exists so
	# the override can be re-enabled deliberately once paired with an
	# actual memory-headroom check (or once WNBA's own spike is fixed)
	# rather than a blind timer.
	return _env_bool("SYNDICATE_LIVE_ODDS_REFRESH_STARVATION_OVERRIDE_ENABLED", default=False)


def _odds_refresh_starvation_ceiling_seconds() -> int:
	# The sim-vs-refresh mutual-exclusion gate (see the "MLB daily sim is still
	# running" check below) was added to stop two heavy pipelines stacking in
	# the same container. It didn't account for MLB sims relaunching
	# back-to-back on fingerprint changes (lineup/odds movement) throughout a
	# live slate -- confirmed in production 2026-07-18: sims chained for 90+
	# minutes straight, deferring every single odds-refresh tick in that
	# window, so WNBA/live odds/intelligence data went stale and the board
	# emptied out. This bounds the worst case: however long the sim mutex has
	# been blocking, force the refresh through after this many seconds of
	# staleness rather than deferring indefinitely -- a stale board is worse
	# than an occasional OOM-restart, which Render recovers from
	# automatically anyway.
	raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_STARVATION_CEILING_SECONDS") or "").strip()
	try:
		value = int(raw or 900)
	except Exception:
		value = 900
	return max(0, value)


def _odds_refresh_starved(*, now_epoch: float) -> bool:
	ceiling = _odds_refresh_starvation_ceiling_seconds()
	if ceiling <= 0:
		return True
	last = _read_last_odds_refresh_launch()
	last_epoch = float(last.get("epoch") or 0.0)
	if last_epoch <= 0.0:
		# No prior successful refresh recorded. This is the very first time
		# this check has ever run on this worker's data disk (the record file
		# is new), most commonly right at a cold worker start where the first
		# tick's "first_appearance"/"tip_off_window" sim launch and the
		# odds-refresh gate land in the same tick -- exactly the
		# stack-two-heavy-pipelines-at-once case the gate exists to prevent,
		# not the chained-relaunch staleness case the ceiling exists to
		# bound. So: not starved *yet* -- but seed the record with now_epoch
		# so the ceiling has a real anchor to count from. Production incident
		# 2026-07-18: without this seed, a worker that redeploys while sims
		# are ALREADY chaining back-to-back never got a first successful
		# refresh to record, so last_epoch stayed 0 forever and this branch
		# returned False on every single tick -- the ceiling could never
		# fire. Seeding here means "count from when we first started
		# watching," not "count from a success that may never happen."
		_record_odds_refresh_launch(now_epoch)
		return False
	return (now_epoch - last_epoch) >= ceiling


def _last_wnba_odds_refresh_launch_path() -> Path:
	return _meta_dir() / "last_wnba_odds_refresh_launch.json"


def _read_last_wnba_odds_refresh_launch() -> dict[str, Any]:
	payload = read_json_file(_last_wnba_odds_refresh_launch_path())
	return payload if isinstance(payload, dict) else {}


def _record_wnba_odds_refresh_launch(epoch: float) -> None:
	write_json_file(_last_wnba_odds_refresh_launch_path(), {"epoch": epoch, "recordedAt": _utc_now()})


def _wnba_odds_refresh_skip_seconds(*, now_epoch: float) -> float | None:
	# 2026-07-19: the "scope the sim-vs-refresh mutex to WNBA only" fix
	# (launch every other configured sport, defer only WNBA while a sim is
	# resident) fixed MLB's starvation by shifting the exact same risk onto
	# WNBA -- and the only escape hatch that existed at the time
	# (_odds_refresh_starved) tracks a GLOBAL last-launch timestamp that
	# keeps getting refreshed by the non-WNBA sports launching successfully,
	# so it could never detect "WNBA specifically has been skipped for
	# hours" even if enabled. This is a WNBA-specific equivalent. Returns
	# None if WNBA has never been recorded as launched (nothing to measure
	# a gap against yet) or launched too recently to matter.
	last = _read_last_wnba_odds_refresh_launch()
	last_epoch = float(last.get("epoch") or 0.0)
	if last_epoch <= 0.0:
		_record_wnba_odds_refresh_launch(now_epoch)
		return None
	return max(0.0, now_epoch - last_epoch)


def _wnba_odds_refresh_starvation_override_enabled() -> bool:
	# Off by default, deliberately: forcing WNBA's refresh through on a blind
	# timer while an MLB sim is resident is the exact mechanism
	# _odds_refresh_starvation_override_enabled() above already tried and
	# reverted for the whole-tick case, after confirming it reliably
	# reproduced the OOM it exists to prevent. Real production evidence from
	# 2026-07-19 (the same day the per-game MLB sim scoping and
	# memory-headroom checks landed) still measured only 900-1550MB of real
	# headroom on a busy 16-game slate -- under the 1800MB bar
	# _odds_refresh_memory_headroom_snapshot() requires -- so the
	# improvements help but don't make a blind timer safe on the busiest
	# days. This is a separate, explicit opt-in specifically for accepting
	# that residual risk in exchange for bounding how stale WNBA can get,
	# for whoever has visibility into current container memory to enable
	# deliberately (e.g. via Render's dashboard) rather than something this
	# code silently assumes is now safe.
	return _env_bool("SYNDICATE_WNBA_ODDS_REFRESH_STARVATION_OVERRIDE_ENABLED", default=False)


def _wnba_odds_refresh_starvation_ceiling_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_WNBA_ODDS_REFRESH_STARVATION_CEILING_SECONDS") or "").strip()
	try:
		value = int(raw or 2700)  # 45 minutes -- deliberately much longer than
		# the general 900s ceiling, since firing here means "force through
		# despite insufficient measured memory headroom," not just "despite
		# a resident sim."
	except Exception:
		value = 2700
	return max(0, value)


def _wnba_odds_refresh_starved(*, now_epoch: float) -> bool:
	if not _wnba_odds_refresh_starvation_override_enabled():
		return False
	skip_seconds = _wnba_odds_refresh_skip_seconds(now_epoch=now_epoch)
	if skip_seconds is None:
		return False
	return skip_seconds >= _wnba_odds_refresh_starvation_ceiling_seconds()


def _odds_refresh_memory_overlap_enabled() -> bool:
	return _env_bool("SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_OVERLAP_ENABLED", default=True)


def _odds_refresh_min_headroom_bytes() -> int:
	# Default matches the worst WNBA-refresh-leg RSS spike measured in
	# production (~1528MB) plus a margin for the rest of the odds-refresh
	# process tree (~185MB) and slack -- i.e. this is deliberately set so the
	# gate only opens when there's real proof the WNBA-sized spike (the
	# thing that actually caused the 2026-07-18 OOM) would still fit,
	# not just "some headroom exists."
	raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MIN_HEADROOM_MB") or "").strip()
	try:
		value = int(raw or 1800)
	except Exception:
		value = 1800
	return max(0, value) * 1024 * 1024


def _soccer_resim_trigger_enabled() -> bool:
	# Default OFF, same posture SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER takes.
	# This puts a market-board build on the tick path, which is exactly the
	# shape of call that OOM-killed the 2GB refresh-worker on 2026-07-25 --
	# so it ships dark and gets turned on deliberately, per service.
	return _env_bool("SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER", default=False)


def _soccer_resim_tick_owner_here() -> bool:
	# Which service owns this decision. Mirrors _mlb_sim_tick_owner_here /
	# _mlb_refresh_tick_owner_here. Defaults true so a service with no
	# explicit opinion keeps whatever the enable flag says; set false on
	# refresh-worker so this lands on live-odds-worker instead -- refresh-
	# worker already carries the MLB sim AND the intelligence pipeline,
	# while live-odds-worker runs neither.
	raw = str(os.environ.get("SYNDICATE_SOCCER_RESIM_TICK_OWNER") or "").strip().lower()
	if not raw:
		return True
	return raw in ("1", "true", "yes", "y", "on")


def _soccer_resim_check_interval_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_SOCCER_RESIM_CHECK_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw or 900)
	except Exception:
		value = 900
	return max(120, value)


def _last_soccer_resim_check_path() -> Path:
	return _meta_dir() / "last_soccer_resim_check.json"


def _soccer_join_mismatch_leagues(*, now_epoch: float, date_str: str) -> list[str]:
	"""Soccer leagues whose market board has at least one odds<->sim
	needs-resim mismatch, i.e. the book is quoting an entity SoccerSim did
	not project for that market.

	Returns [] for every "don't act" case (disabled, not this service's
	lane, inside the check interval, insufficient memory, or any error) --
	this runs on the main loop, so it must never be the reason a tick dies.
	"""
	if not _soccer_resim_trigger_enabled() or not _soccer_resim_tick_owner_here():
		return []
	last = read_json_file(_last_soccer_resim_check_path())
	last = last if isinstance(last, dict) else {}
	last_epoch = float(last.get("epoch") or 0.0)
	last_date = str(last.get("date") or "")
	if last_epoch > 0.0 and last_date == date_str and (now_epoch - last_epoch) < _soccer_resim_check_interval_seconds():
		return []

	# build_soccer_market_board is cached (60s TTL + artifact signature), but
	# a cold key still assembles a full board per league, so gate on real
	# measured headroom exactly as the MLB join-mismatch check does. None
	# means "couldn't measure" and is treated as insufficient.
	headroom = _mlb_sim_memory_headroom_snapshot()
	if headroom is None or not headroom.get("sufficient", False):
		print(
			f"[live_refresh_loop] SOCCER_JOIN_MISMATCH_CHECK_SKIPPED reason=insufficient_memory_headroom "
			f"{json.dumps(headroom, sort_keys=True) if headroom else '{}'}",
			flush=True,
		)
		return []

	try:
		from syndicate.features.soccer.market_board import soccer_needs_resim_event_ids
		from syndicate.features.soccer.sources import active_leagues_for_date

		leagues_with_mismatch: list[str] = []
		for league in active_leagues_for_date(date_str):
			try:
				if soccer_needs_resim_event_ids(league, date_str):
					leagues_with_mismatch.append(str(league))
			except Exception as exc:
				print(
					f"[live_refresh_loop] SOCCER_JOIN_MISMATCH_LEAGUE_ERROR league={league} "
					f"error={type(exc).__name__}: {exc}",
					flush=True,
				)
	except Exception as exc:
		print(f"[live_refresh_loop] SOCCER_JOIN_MISMATCH_CHECK_ERROR error={type(exc).__name__}: {exc}", flush=True)
		return []

	write_json_file(
		_last_soccer_resim_check_path(),
		{"epoch": now_epoch, "date": date_str, "leagues": sorted(leagues_with_mismatch), "recordedAt": _utc_now()},
	)
	return sorted(leagues_with_mismatch)


def _odds_refresh_memory_headroom_snapshot() -> dict[str, Any] | None:
	# Unlike the time-based starvation override above (reverted 2026-07-18
	# after it forced refreshes into an actually-resident sim and OOMed the
	# container regardless of how long it waited), this checks REAL,
	# currently-measured memory headroom rather than guessing from elapsed
	# time or trigger type. A "--only-game-pks"-scoped sim CAN have a much
	# smaller footprint than the old whole-slate sim -- but not always: a
	# profile with no same-day baseline yet silently falls back to
	# simulating everything (see docs/fix_notes_log.md / commit bc614d77),
	# so scope alone can't prove it's safe. Measuring the container's actual
	# cgroup headroom at decision time can. Returns None when headroom can't
	# be measured at all (e.g. local dev without cgroups) -- callers treat
	# that the same as "not sufficient," preserving the original safe
	# defer-while-sim-running behavior rather than guessing.
	if not _odds_refresh_memory_overlap_enabled():
		return None
	try:
		from syndicate.features.shared.memory_observability import memory_headroom_snapshot
	except Exception:
		return None
	return memory_headroom_snapshot(_odds_refresh_min_headroom_bytes())




def _last_pregame_launch_path() -> Path:
	return _meta_dir() / "last_pregame_refresh_launch.json"


def _read_last_pregame_launch() -> dict[str, Any]:
	payload = read_json_file(_last_pregame_launch_path())
	return payload if isinstance(payload, dict) else {}


def _record_pregame_launch(epoch: float, date_str: str) -> None:
	write_json_file(_last_pregame_launch_path(), {"epoch": epoch, "date": date_str, "recordedAt": _utc_now()})


def _off_hours_max_staleness_seconds() -> int:
	# How stale the odds may get while NO tracked game is live. 3600 bounds
	# worst-case pregame staleness at one hour -- the moment any game goes
	# live, full cadence resumes on the next tick regardless of this. 0
	# disables the gate entirely.
	raw = str(os.environ.get("SYNDICATE_ODDS_OFF_HOURS_MAX_STALENESS_SECONDS") or "").strip()
	try:
		value = int(raw or 3600)
	except Exception:
		value = 3600
	return max(0, value)


def _off_hours_gate_blocks_launch(*, now_epoch: float, any_live: bool | None) -> bool:
	"""#15. True when nothing is live and a sweep ran recently enough.

	Only a definite any_live=False can block: None means adaptive is off or
	the liveness signal was unreadable, and a sweep that cannot establish
	liveness must run, not starve (same fail-open rule as the empty-board
	guard). A missing/unreadable launch marker also fails open -- the sweep
	that then runs writes the marker, so the gate self-heals.
	"""
	if any_live is not False:
		return False
	ceiling = _off_hours_max_staleness_seconds()
	if ceiling <= 0:
		return False
	try:
		last = _read_last_odds_refresh_launch()
		last_epoch = float(last.get("epoch") or 0.0)
	except Exception:
		return False
	if last_epoch <= 0.0:
		return False
	return (now_epoch - last_epoch) < ceiling


def _weather_fetch_interval_seconds() -> int:
	raw = str(os.environ.get("SYNDICATE_MLB_WEATHER_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw or 3600)
	except Exception:
		value = 3600
	return max(0, value)


def _maybe_launch_weather_fetch(*, now_epoch: float, date_str: str) -> dict[str, Any] | None:
	"""#84. At most one NWS park-weather fetch per interval (default hourly).

	Detached like the other subprocess jobs so a slow NWS response cannot
	stall the tick. Gated on MLB being an effective sport for the date; 0
	disables. Fail-open on marker problems means at worst an extra hourly
	fetch against a free, keyless API.
	"""
	interval = _weather_fetch_interval_seconds()
	if interval <= 0:
		return None
	try:
		if "mlb" not in _live_refresh_loop_effective_sports(date_str):
			return None
	except Exception:
		return None
	marker_path = _meta_dir() / "last_weather_fetch.json"
	try:
		payload = read_json_file(marker_path)
		last_epoch = float(payload.get("epoch") or 0.0) if isinstance(payload, dict) else 0.0
	except Exception:
		last_epoch = 0.0
	if last_epoch > 0.0 and (now_epoch - last_epoch) < interval:
		return None
	try:
		write_json_file(marker_path, {"epoch": now_epoch, "date": date_str})
	except Exception:
		pass
	log_path = _meta_dir() / "weather_fetch.log"
	try:
		with open(log_path, "ab") as log_handle:
			process = subprocess.Popen(
				[sys.executable, str(REPO_ROOT / "scripts" / "fetch_mlb_weather.py"), "--date", date_str],
				stdout=log_handle,
				stderr=subprocess.STDOUT,
				cwd=str(REPO_ROOT),
			)
		print(f"[live_refresh_loop] WEATHER_FETCH_LAUNCHED date={date_str} pid={process.pid}", flush=True)
		return {"launched": True, "pid": process.pid}
	except Exception as exc:
		print(f"[live_refresh_loop] WEATHER_FETCH_LAUNCH_FAILED error={type(exc).__name__}: {exc}", flush=True)
		return {"launched": False, "error": f"{type(exc).__name__}: {exc}"}


# #82 Phase 3: per-game T-window sweeps. CLV's closing line is the last
# pregame price, and a slate-wide cadence structurally misses it for the
# first game of a day and for one-game slates (WNBA's normal case) -- nothing
# is live yet, so the drift cadence is all there is, and a 2h drift point can
# miss the close by an hour. These windows guarantee a full sweep at ~T-75m
# (post-lineup market) and ~T-10m (the close) per game, fired ONLY while the
# sport is not already live: once any of the sport's games is live, the 60s
# live cadence sweeps the whole slate -- including its still-pregame events --
# and the windows would add nothing but cost.
_T_WINDOW_RAMP_SECONDS = 75 * 60
_T_WINDOW_CLOSING_SECONDS = 10 * 60
_COMMENCE_TIMES_CACHE: dict[tuple[str, str], tuple[float, list[tuple[str, float]]]] = {}
_COMMENCE_TIMES_CACHE_TTL_SECONDS = 600.0


def _parse_commence_epoch(value: Any) -> float | None:
	try:
		stamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
	except (TypeError, ValueError):
		return None
	if stamp.tzinfo is None:
		return None
	return stamp.timestamp()


def _mlb_commence_times(date_str: str) -> list[tuple[str, float]]:
	token = date_str.replace("-", "_")
	candidates = (
		data_root() / "mlb_source" / "source_artifacts" / "data" / "daily" / "snapshots" / date_str / "oddsapi_game_lines.json",
		data_root() / "mlb_source" / "source_artifacts" / "data" / "market" / "oddsapi" / f"oddsapi_game_lines_{token}.json",
	)
	for path in candidates:
		payload = read_json_file(path)
		games = payload.get("games") if isinstance(payload, dict) else None
		if not isinstance(games, list) or not games:
			continue
		out: list[tuple[str, float]] = []
		for row in games:
			if not isinstance(row, dict):
				continue
			epoch = _parse_commence_epoch(row.get("commence_time"))
			event_id = str(row.get("event_id") or "").strip()
			if epoch is not None and event_id:
				out.append((event_id, epoch))
		if out:
			return out
	return []


def _wnba_commence_times(date_str: str) -> list[tuple[str, float]]:
	payload = read_json_file(REPO_ROOT / "vendor" / "wnba_betting_repo" / "data" / "processed" / "schedule_2026.json")
	rows = payload if isinstance(payload, list) else (payload.get("games") if isinstance(payload, dict) else None)
	if not isinstance(rows, list):
		return []
	out: list[tuple[str, float]] = []
	for row in rows:
		if not isinstance(row, dict):
			continue
		if str(row.get("date_est") or "").strip()[:10] != date_str:
			continue
		epoch = _parse_commence_epoch(row.get("datetime_utc"))
		game_id = str(row.get("game_id") or "").strip()
		if epoch is not None and game_id:
			out.append((game_id, epoch))
	return out


_T_WINDOW_COMMENCE_PROVIDERS = {
	"mlb": _mlb_commence_times,
	"wnba": _wnba_commence_times,
}


def _commence_times_cached(sport: str, date_str: str, *, now_epoch: float) -> list[tuple[str, float]]:
	key = (sport, date_str)
	cached = _COMMENCE_TIMES_CACHE.get(key)
	if cached is not None and (now_epoch - cached[0]) < _COMMENCE_TIMES_CACHE_TTL_SECONDS:
		return cached[1]
	provider = _T_WINDOW_COMMENCE_PROVIDERS.get(sport)
	times: list[tuple[str, float]] = []
	if provider is not None:
		try:
			times = provider(date_str)
		except Exception:
			times = []
	_COMMENCE_TIMES_CACHE[key] = (now_epoch, times)
	if len(_COMMENCE_TIMES_CACHE) > 16:
		_COMMENCE_TIMES_CACHE.clear()
	return times


def _t_window_markers_path() -> Path:
	return _meta_dir() / "t_window_sweeps.json"


def _read_t_window_markers(date_str: str) -> dict[str, float]:
	payload = read_json_file(_t_window_markers_path())
	if not isinstance(payload, dict) or str(payload.get("date") or "") != date_str:
		return {}
	markers = payload.get("markers")
	out: dict[str, float] = {}
	if isinstance(markers, dict):
		for key, epoch in markers.items():
			try:
				out[str(key)] = float(epoch)
			except (TypeError, ValueError):
				continue
	return out


def _record_t_window_markers(date_str: str, new_markers: dict[str, float]) -> None:
	try:
		markers = _read_t_window_markers(date_str)
		markers.update(new_markers)
		write_json_file(_t_window_markers_path(), {"date": date_str, "markers": markers})
	except Exception as exc:
		print(f"[live_refresh_loop] T_WINDOW_MARKER_WRITE_FAILED error={type(exc).__name__}: {exc}", flush=True)


def _t_window_due_sports(*, now_epoch: float, date_str: str) -> dict[str, dict[str, float]]:
	"""{sport: {marker: epoch}} for T-windows due RIGHT NOW.

	A window is due when a game starts within it and no sweep has been
	credited to that (game, window) yet. Live sports are skipped entirely --
	their slate-wide live cadence already covers every event, pregame ones
	included. Everything fails open to "nothing due": a missing schedule
	artifact costs precision, never a sweep storm.
	"""
	due: dict[str, dict[str, float]] = {}
	for sport in _T_WINDOW_COMMENCE_PROVIDERS:
		checker = _LIVE_STATUS_CHECKERS.get(sport)
		try:
			if checker is not None and checker(date_str):
				continue
		except Exception:
			continue
		times = _commence_times_cached(sport, date_str, now_epoch=now_epoch)
		if not times:
			continue
		markers = _read_t_window_markers(date_str)
		sport_due: dict[str, float] = {}
		for event_id, start_epoch in times:
			seconds_to_start = start_epoch - now_epoch
			if seconds_to_start <= 0:
				continue
			if seconds_to_start <= _T_WINDOW_CLOSING_SECONDS:
				# Inside T-10 only the closing window may fire. A plain elif
				# let a game whose closing sweep had already run fall through
				# and arm a spurious ramp sweep -- caught by test.
				if f"{sport}:closing:{event_id}" not in markers:
					sport_due[f"{sport}:closing:{event_id}"] = now_epoch
			elif seconds_to_start <= _T_WINDOW_RAMP_SECONDS and f"{sport}:ramp:{event_id}" not in markers:
				sport_due[f"{sport}:ramp:{event_id}"] = now_epoch
		if sport_due:
			due[sport] = sport_due
	return due


# #107. _launch_market_tier (whole-tick, "lines_props" only when NOTHING
# on the whole slate is live) used to compute a tier passed to
# launch_refresh_run's market_tier kwarg, which flowed all the way down to
# refresh_mlb_oddsapi.py's --market-tier flag -- consumed only by
# fetch_live_odds_incremental, itself only reachable when fast_mode is
# true, which requires refresh_mlb_oddsapi.py's own --mode flag to be
# "fast". render.yaml pins SYNDICATE_LIVE_ODDS_REFRESH_MODE=full on all
# three services, and the actual caller (refresh_odds_sources.py's
# _build_mlb_steps) never even passed --mode to that script at all, so
# args.mode there could only ever be its own "full" default regardless of
# any env var. Confirmed dead end to end; removed along with
# fetch_live_odds_incremental itself. Superseded by event scoping
# (fetch_mlb_oddsapi_local.py's per-game hot/cold decision, not a single
# whole-slate flag) and the props cadence cache on top of it.


# #15 Phase 1: per-sport pregame sweep intervals. Defaults encode the
# per-sport rules agreed 2026-07-27: daily sports drift-sample every 2h
# pregame (full sweeps, so the midday PROP samples ride along); soccer is a
# weekly sport whose pre-matchday drift is worth 2-3 points a day, so 8h.
# On matchday soccer's games go live and the live cadence takes over; the
# proper matchday ramp (T-75/T-10 per game) is Phase 3.
_PREGAME_SWEEP_INTERVAL_DEFAULTS = {"soccer": 8 * 3600}
_PREGAME_SWEEP_INTERVAL_FALLBACK = 2 * 3600


def _pregame_sweep_interval_seconds(sport: str) -> int:
	sport = str(sport or "").strip().lower()
	raw = str(os.environ.get(f"SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_{sport.upper()}") or "").strip()
	if not raw:
		raw = str(os.environ.get("SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS") or "").strip()
	try:
		value = int(raw) if raw else int(_PREGAME_SWEEP_INTERVAL_DEFAULTS.get(sport, _PREGAME_SWEEP_INTERVAL_FALLBACK))
	except Exception:
		value = int(_PREGAME_SWEEP_INTERVAL_DEFAULTS.get(sport, _PREGAME_SWEEP_INTERVAL_FALLBACK))
	return max(0, value)


def _pregame_sport_sweep_epochs_path() -> Path:
	return _meta_dir() / "last_pregame_sweep_by_sport.json"


def _read_pregame_sport_sweep_epochs() -> dict[str, float]:
	payload = read_json_file(_pregame_sport_sweep_epochs_path())
	out: dict[str, float] = {}
	if isinstance(payload, dict):
		for sport, epoch in payload.items():
			try:
				out[str(sport).strip().lower()] = float(epoch)
			except (TypeError, ValueError):
				continue
	return out


def _record_pregame_sport_sweep_epochs(epoch: float, sports: list[str]) -> None:
	try:
		existing = _read_pregame_sport_sweep_epochs()
		for sport in sports:
			existing[str(sport).strip().lower()] = float(epoch)
		write_json_file(_pregame_sport_sweep_epochs_path(), existing)
	except Exception as exc:
		# A missing marker only ever fails open to an extra sweep.
		print(f"[live_refresh_loop] PREGAME_SWEEP_MARKER_WRITE_FAILED error={type(exc).__name__}: {exc}", flush=True)


def _apply_pregame_sport_cadence(
	sports: list[str],
	*,
	now_epoch: float,
	force_sports: set[str],
) -> tuple[list[str], list[str]]:
	"""(kept, skipped): drop sports mid-interval whose own games are not live.

	Per-SPORT, not per-phase, deliberately: the loop's phase is global, so
	before this filter a sport with no live game rode whatever cadence any
	OTHER sport's live window set -- WNBA re-swept every 60s for the whole of
	an MLB slate. A sport's own liveness is the only cadence signal that
	belongs to it.

	Fail-open rules, in order: an event-triggered sport (force_sports --
	lineup/injury change, join-mismatch resim) always sweeps; a sport whose
	liveness cannot be established sweeps; a sport with no checker sweeps; a
	sport with no marker sweeps. Only "definitively not live AND swept within
	its own interval" is dropped.
	"""
	date_str = central_today_iso()
	markers = _read_pregame_sport_sweep_epochs()
	kept: list[str] = []
	skipped: list[str] = []
	for sport in sports:
		normalized = str(sport).strip().lower()
		if not normalized:
			continue
		if normalized in force_sports:
			kept.append(normalized)
			continue
		interval = _pregame_sweep_interval_seconds(normalized)
		if interval <= 0:
			kept.append(normalized)
			continue
		checker = _LIVE_STATUS_CHECKERS.get(normalized)
		if checker is None:
			kept.append(normalized)
			continue
		try:
			sport_live = bool(checker(date_str))
		except Exception:
			kept.append(normalized)
			continue
		if sport_live:
			kept.append(normalized)
			continue
		last_epoch = markers.get(normalized, 0.0)
		if last_epoch <= 0.0 or (now_epoch - last_epoch) >= interval:
			kept.append(normalized)
			continue
		skipped.append(normalized)
	return kept, skipped


def _pregame_relaunch_blocked(*, now_epoch: float, date_str: str) -> bool:
	cooldown = _pregame_relaunch_cooldown_seconds()
	if cooldown <= 0:
		return False
	last = _read_last_pregame_launch()
	last_epoch = float(last.get("epoch") or 0.0)
	last_date = str(last.get("date") or "")
	return last_epoch > 0.0 and last_date == date_str and (now_epoch - last_epoch) < cooldown


def _hot_artifact_publish_watermark_path() -> Path:
	return _meta_dir() / "last_hot_artifact_publish_epoch.json"


def _hot_artifact_publish_since_epoch(*, tick_started_epoch: float) -> float:
	# Refreshes launch as detached (non-blocking) subprocesses that can take
	# several minutes to finish writing output -- almost always longer than
	# the launching tick's own brief synchronous execution. Using EACH tick's
	# own start time as the publish "since" cutoff (the previous behavior)
	# means a file's fixed mtime is compared against a monotonically
	# increasing sequence of cutoffs: too early for the launching tick (the
	# file doesn't exist yet) and, once any later tick's start time passes
	# the file's mtime, too late for every tick after that -- the file can
	# permanently never satisfy `mtime >= since_epoch_seconds` again.
	# Confirmed live: recommendations_2026-07-18.csv/game_cards_2026-07-18.csv
	# existed on the worker's disk from a clean, completed refresh run but
	# never reached the web service. A persisted watermark (floor = the end
	# of the last successful sweep) instead of each tick's own start time
	# fixes this: any file written since the last sweep gets caught by the
	# next one, regardless of how long the async refresh took or how many
	# tick intervals passed in between.
	payload = read_json_file(_hot_artifact_publish_watermark_path())
	try:
		stored = float(payload.get("epoch")) if isinstance(payload, dict) and payload.get("epoch") is not None else None
	except (TypeError, ValueError):
		stored = None
	if stored is None or stored <= 0.0:
		# No prior watermark (fresh deploy/backend): start tracking from now
		# rather than sweeping the full artifact history on the first tick.
		return tick_started_epoch
	return stored


def _record_hot_artifact_publish_watermark(epoch: float) -> None:
	write_json_file(_hot_artifact_publish_watermark_path(), {"epoch": epoch, "recordedAt": _utc_now()})


def _mlb_sim_tick_owner_here() -> bool:
	# Whether THIS service's tick should attempt to launch the MLB daily
	# sim / look-ahead / evening-next-day sim at all, vs. just observing
	# whether one is running (via the shared PID-verified pointer) to gate
	# its own odds-refresh launch. Defaults true so a service with no
	# explicit opinion keeps today's behavior; set false on any service
	# where sim-launch ownership has been relocated elsewhere (e.g.
	# live-odds-worker once refresh-worker owns it) to avoid two services
	# both attempting the same decision every tick -- harmless either way
	# since _launch_mlb_daily_sim's own decision functions and the shared
	# pointer prevent an actual double-launch, but wasteful and noisy.
	raw = str(os.environ.get("SYNDICATE_MLB_SIM_TICK_OWNER") or "").strip().lower()
	if not raw:
		return True
	return raw in ("1", "true", "yes", "y", "on")


def _mlb_refresh_tick_owner_here() -> bool:
	# Whether THIS service's tick should include "mlb" among the sports it
	# launches live-phase odds refreshes for, vs. leaving that entirely to
	# refresh-worker's own purpose-built MLB autorun
	# (_launch_autorun_mlb_refresh in run_refresh_worker.py, which reacts to
	# the live-lens report's actual staleness rather than a generic tick
	# interval). Both were confirmed independently deciding "MLB needs a
	# refresh" in the same window when both are enabled -- the cross-service
	# refresh-run lock (see _refresh_run_still_active in ops_refresh.py)
	# already makes that safe, but this removes the redundant decision-making
	# at the source instead of just tolerating the collision. Defaults true
	# so a service with no explicit opinion keeps today's behavior. Mirrors
	# _mlb_sim_tick_owner_here's existing pattern (2026-07-20 sim-ownership
	# move from live-odds-worker to refresh-worker).
	raw = str(os.environ.get("SYNDICATE_MLB_REFRESH_TICK_OWNER") or "").strip().lower()
	if not raw:
		return True
	return raw in ("1", "true", "yes", "y", "on")


_WEEKLY_SPORTS_TICK_EXCLUDABLE = ("nfl", "ncaaf", "ncaab")


def _weekly_sports_refresh_tick_owner_here() -> bool:
	# Mirrors _mlb_refresh_tick_owner_here's pattern exactly, for the same
	# reason: without this split, this tick's own launch and refresh-worker's
	# weekly-sports autorun (_launch_autorun_weekly_sports_refresh in
	# run_refresh_worker.py) would both target the identical in-season
	# nfl/ncaaf/ncaab artifacts -- including at least one file that isn't even
	# date-partitioned -- the moment those sports are back in season. Unlike
	# MLB (where only a redundant decision was at stake, made safe by the
	# refresh-run lock), this is a REAL write race once football season
	# starts, not just wasted duplicate work. Defaults true so a service with
	# no explicit opinion keeps today's behavior.
	raw = str(os.environ.get("WEEKLY_SPORTS_REFRESH_TICK_OWNER") or "").strip().lower()
	if not raw:
		return True
	return raw in ("1", "true", "yes", "y", "on")


def _run_mlb_sim_tick() -> dict[str, Any]:
	"""Self-contained MLB sim/look-ahead/evening-sim decision+launch pass.

	Split out of _run_live_refresh_tick() so it can be called independently
	from a different service's loop (see scripts/run_refresh_worker.py) --
	the launch decisions (_mlb_daily_sim_enabled, _look_ahead_enabled,
	_mlb_evening_next_day_sim_enabled) already read their own env-var gates,
	so relocating ownership is just flipping those three flags between
	services, not new gating logic here. Computes its own now_epoch/date/
	any_live rather than accepting them as params so it's safe to call from
	any context.
	"""
	meta: dict[str, Any] = {}
	if not _mlb_sim_tick_owner_here():
		return meta
	if not (_mlb_daily_sim_enabled() or _look_ahead_enabled() or _mlb_evening_next_day_sim_enabled()):
		# None of the three sub-features are on -- skip _any_tracked_sport_game_live()
		# entirely rather than paying for its real per-sport live-status
		# subprocess checks for nothing.
		return meta
	tick_started_epoch = datetime.now(timezone.utc).timestamp()
	adaptive_enabled = _live_refresh_loop_adaptive_enabled()
	any_live = _any_tracked_sport_game_live() if adaptive_enabled else None
	selected_date = central_today_iso()

	# MLB daily sim is dispatched independently of the odds-refresh call
	# below: its cadence/gate differs from NBA/WNBA's, and the vendor
	# script's own PID lock (not ops_refresh's single-active-refresh
	# assertion) is the correct concurrency guard for it. The launched
	# wrapper publishes its own results synchronously on completion (see
	# run_mlb_daily_sim_job.py), so the tick's publish sweep doesn't need to
	# account for it.
	try:
		mlb_decision = _mlb_daily_sim_decision(now_epoch=tick_started_epoch, date_str=selected_date)
		if mlb_decision.get("force"):
			meta["mlbDailySim"] = _launch_mlb_daily_sim(selected_date, mlb_decision)
		else:
			meta["mlbDailySim"] = {"launched": False, "reason": mlb_decision.get("reason")}
	except Exception as exc:
		meta["mlbDailySim"] = {"launched": False, "error": f"{type(exc).__name__}: {exc}"}

	# Look-ahead: while idle, proactively warm tomorrow's slate instead of
	# only reacting once central_today_iso() rolls over. Independent of the
	# day's own odds-refresh launch -- a collision with it is handled by
	# launch_refresh_run's existing single-active-refresh guard.
	try:
		look_ahead_decision = _look_ahead_decision(now_epoch=tick_started_epoch, selected_date=selected_date, any_live=any_live)
		if look_ahead_decision.get("launch"):
			meta["lookAhead"] = _launch_look_ahead_refresh(look_ahead_decision)
		else:
			meta["lookAhead"] = {"ok": False, "launched": False, "reason": look_ahead_decision.get("reason")}
	except Exception as exc:
		meta["lookAhead"] = {"ok": False, "launched": False, "error": f"{type(exc).__name__}: {exc}"}

	# Second day of the look-ahead window (selected_date + 2). Skipped
	# whenever day 1 just launched this same tick -- don't stack two heavy
	# refresh launches back to back on Render's tight memory headroom; the
	# next idle tick picks day 2 up instead.
	if meta.get("lookAhead", {}).get("launched"):
		meta["lookAheadDay2"] = {"ok": True, "launched": False, "reason": "day1_launched_this_tick"}
	else:
		try:
			look_ahead_day2_decision = _look_ahead_decision_day2(now_epoch=tick_started_epoch, selected_date=selected_date, any_live=any_live)
			if look_ahead_day2_decision.get("launch"):
				meta["lookAheadDay2"] = _launch_look_ahead_refresh(look_ahead_day2_decision)
			else:
				meta["lookAheadDay2"] = {"ok": False, "launched": False, "reason": look_ahead_day2_decision.get("reason")}
		except Exception as exc:
			meta["lookAheadDay2"] = {"ok": False, "launched": False, "error": f"{type(exc).__name__}: {exc}"}

	try:
		evening_sim_decision = _mlb_evening_next_day_sim_decision(now_epoch=tick_started_epoch, selected_date=selected_date, any_live=any_live)
		if evening_sim_decision.get("force"):
			meta["mlbEveningNextDaySim"] = _launch_mlb_daily_sim(str(evening_sim_decision.get("date")), evening_sim_decision)
		else:
			meta["mlbEveningNextDaySim"] = {"launched": False, "reason": evening_sim_decision.get("reason")}
	except Exception as exc:
		meta["mlbEveningNextDaySim"] = {"launched": False, "error": f"{type(exc).__name__}: {exc}"}

	return meta


def _run_live_refresh_tick() -> dict[str, Any]:
	tick_started_epoch = datetime.now(timezone.utc).timestamp()
	adaptive_enabled = _live_refresh_loop_adaptive_enabled()
	any_live = _any_tracked_sport_game_live() if adaptive_enabled else None
	effective_phase = ("live" if any_live else "pregame") if adaptive_enabled else _live_refresh_loop_phase()
	selected_date = central_today_iso()
	force_sim_rerun = _should_force_sim_rerun(now_epoch=tick_started_epoch, date_str=selected_date)
	# An NBA-only lineup/injury change was forcing WNBA's refresh script to
	# bypass its cache too (and vice versa), since force_refresh applied to
	# the whole combined launch rather than just the sport that changed.
	# Falls back to forcing both when the changed-sport detail isn't
	# available (e.g. a test mocks _should_force_sim_rerun directly) --
	# same behavior as before this fix, just not narrowed.
	force_refresh_sports = (
		",".join(sorted(_last_lineup_injury_changed_sports())) if force_sim_rerun else None
	) or (",".join(sorted(_LINEUP_INJURY_FETCH_PACKAGES)) if force_sim_rerun else None)
	# Soccer's join-mismatch resim. Deliberately expressed as "add soccer to
	# the sports whose refresh bypasses its cache" rather than as a new
	# subprocess launcher like _launch_mlb_daily_sim: soccer's sim rebuild is
	# ALREADY a step inside the odds refresh (build_soccer_artifacts.py, via
	# refresh_odds_sources.py's "Refresh {league}'s current-week simulation,
	# props, and recommendation artifacts"), so forcing that refresh is
	# sufficient to resim, and reusing this proven path avoids adding a
	# second set of active pointers, status files, timeouts and backoff on a
	# worker that has already been OOM-killed twice this month.
	soccer_resim_leagues = _soccer_join_mismatch_leagues(now_epoch=tick_started_epoch, date_str=selected_date)
	if soccer_resim_leagues:
		force_sim_rerun = True
		existing_sports = [piece for piece in str(force_refresh_sports or "").split(",") if piece]
		force_refresh_sports = ",".join(sorted(set(existing_sports) | {"soccer"}))
		print(
			f"[live_refresh_loop] SOCCER_JOIN_MISMATCH_RESIM_TRIGGERED date={selected_date} "
			f"leagues={','.join(soccer_resim_leagues)}",
			flush=True,
		)
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

	meta.update(_run_mlb_sim_tick())
	weather_launch = _maybe_launch_weather_fetch(now_epoch=tick_started_epoch, date_str=selected_date)
	if weather_launch is not None:
		meta["weatherFetch"] = weather_launch
	sim_process_running = _mlb_daily_sim_process_still_running()
	memory_headroom_snapshot = _odds_refresh_memory_headroom_snapshot() if sim_process_running else None
	if memory_headroom_snapshot is not None:
		meta["oddsRefreshMemoryHeadroom"] = memory_headroom_snapshot
		print(f"[live_refresh_loop] ODDS_REFRESH_MEMORY_HEADROOM_CHECK {json.dumps(memory_headroom_snapshot, sort_keys=True)}", flush=True)
	memory_headroom_sufficient = bool(memory_headroom_snapshot and memory_headroom_snapshot["sufficient"])
	sim_blocks_refresh = sim_process_running and not (
		(_odds_refresh_starvation_override_enabled() and _odds_refresh_starved(now_epoch=tick_started_epoch))
		or memory_headroom_sufficient
	)
	# Mirror of the mlbDailySim gate above (is_refresh_run_active): that gate
	# only stops a NEW sim from launching on top of an in-flight odds refresh,
	# but does nothing once a sim IS running -- the live-phase tick still
	# fired every ~60s regardless, relaunching the full odds-refresh pipeline
	# (which can itself spike WNBA to 1.3-1.5GB RSS) on top of the resident
	# sim process tree for its whole ~45-55min run. Confirmed via production
	# ALL_PROCESS_MEMORY snapshots: container hit 2048/2048MB (100%) with both
	# pipelines resident at once. Skipping here is symmetric with the existing
	# one-directional gate and equally conservative -- a delayed odds tick is
	# cheap, a container OOM-kill is not.
	#
	# Two independent, opt-outable exceptions can let the FULL combined refresh
	# proceed anyway: _odds_refresh_starved() (a blind elapsed-time ceiling,
	# disabled by default -- reverted 2026-07-18 after it forced refreshes into
	# an actually-resident sim and OOMed regardless of wait length) and
	# _odds_refresh_memory_headroom_snapshot() (measures REAL cgroup headroom
	# right now; a --only-game-pks-scoped sim CAN have a much smaller
	# footprint than the old whole-slate one, but proving it from measured
	# memory beats guessing from scope or elapsed time).
	#
	# 2026-07-19: neither exception fired reliably on a genuinely busy 16-game
	# slate (headroom hovered 900MB-1550MB, never the required 1800MB), so the
	# mutex deferred EVERY live-phase tick for 3+ hours straight -- even
	# sports whose refresh leg poses none of the OOM risk the mutex exists to
	# prevent. Only WNBA's refresh leg has ever been measured causing that
	# spike, so when the mutex would otherwise block the whole tick, launch
	# every other configured sport anyway and defer only WNBA specifically.
	skip_launch = False
	launch_sports = _live_refresh_loop_sports()
	mlb_owned_elsewhere = not _mlb_refresh_tick_owner_here()
	weekly_sports_owned_elsewhere = not _weekly_sports_refresh_tick_owner_here()
	if launch_sports is None and (mlb_owned_elsewhere or weekly_sports_owned_elsewhere):
		# No explicit sports override configured -- launch_refresh_run would
		# otherwise resolve the full active-season set itself (including
		# "mlb" and/or nfl/ncaaf/ncaab), duplicating refresh-worker's own
		# purpose-built autoruns for whichever of those it owns.
		excluded_sports = set()
		if mlb_owned_elsewhere:
			excluded_sports.add("mlb")
		if weekly_sports_owned_elsewhere:
			excluded_sports.update(_WEEKLY_SPORTS_TICK_EXCLUDABLE)
		launch_sports = ",".join(sport for sport in _live_refresh_loop_effective_sports(selected_date) if sport not in excluded_sports)
	wnba_forced_through = False
	if sim_blocks_refresh:
		effective_sports = _live_refresh_loop_effective_sports(selected_date)
		if "wnba" in effective_sports:
			wnba_skip_seconds = _wnba_odds_refresh_skip_seconds(now_epoch=tick_started_epoch)
			wnba_starved = _wnba_odds_refresh_starved(now_epoch=tick_started_epoch)
			meta["oddsRefreshWnbaSkipped"] = {
				"reason": "mlb_daily_sim_still_running",
				"headroom": memory_headroom_snapshot,
				"skippedForSeconds": wnba_skip_seconds,
				"starvationOverrideEnabled": _wnba_odds_refresh_starvation_override_enabled(),
				"forcedThrough": wnba_starved,
			}
			if wnba_starved:
				# Opt-in only (see _wnba_odds_refresh_starvation_override_enabled) --
				# accepting the same OOM risk the whole-tick override was reverted
				# for, deliberately, because this only fires after WNBA has been
				# skipped for _wnba_odds_refresh_starvation_ceiling_seconds()
				# straight, not on every resident-sim tick.
				print(f"[live_refresh_loop] WNBA_ODDS_REFRESH_FORCED_THROUGH skipped_for_seconds={wnba_skip_seconds}", flush=True)
				wnba_forced_through = True
		sports_to_launch = [
			sport
			for sport in effective_sports
			if (sport != "wnba" or wnba_forced_through)
			and (sport != "mlb" or _mlb_refresh_tick_owner_here())
			and (sport not in _WEEKLY_SPORTS_TICK_EXCLUDABLE or _weekly_sports_refresh_tick_owner_here())
		]
		if sports_to_launch:
			launch_sports = ",".join(sports_to_launch)
		else:
			meta["ok"] = False
			meta["skipped"] = True
			meta["error"] = "odds refresh deferred: MLB daily sim is still running (avoid stacking two heavy pipelines in the same container)"
			skip_launch = True
	if not skip_launch and effective_phase == "pregame" and _pregame_relaunch_blocked(now_epoch=tick_started_epoch, date_str=selected_date):
		meta["ok"] = False
		meta["skipped"] = True
		meta["error"] = "pregame refresh relaunch blocked by cooldown (previous attempt still within cooldown window)"
		# #107. Unlike the off-hours gate two blocks down (which prints
		# ODDS_REFRESH_OFF_HOURS_SKIPPED every time it fires), this cooldown
		# had no log line at all -- only meta["error"], readable solely by
		# catching the exact tick that hit it via /api/ops/live-refresh/state
		# before the next tick overwrites it. Confirmed live 2026-07-28: this
		# made the cooldown's actual observed cadence impossible to verify
		# from logs, the reason #107 stayed open. Printing it closes that gap
		# the same way the off-hours gate already does.
		print(
			f"[live_refresh_loop] PREGAME_RELAUNCH_COOLDOWN_SKIPPED cooldown_s={_pregame_relaunch_cooldown_seconds()}",
			flush=True,
		)
		skip_launch = True
	if not skip_launch and _off_hours_gate_blocks_launch(now_epoch=tick_started_epoch, any_live=any_live):
		# #15 off-hours gate. When NOTHING is live, every sweep prices a
		# board nobody's odds are moving for. The idle interval (900s) and
		# pregame cooldown (1800s) already throttled off-hours to ~2
		# sweeps/hour; this halves that again by default and makes the
		# ceiling explicit and tunable rather than an accident of two
		# unrelated settings. Fail-open by construction: adaptive off or an
		# unreadable liveness signal means any_live is None, not False, and
		# the gate only ever fires on a definite False -- an odds refresh
		# that cannot establish liveness must sweep, not starve.
		meta["ok"] = False
		meta["skipped"] = True
		meta["offHoursSkipped"] = True
		meta["error"] = "off-hours: no tracked game live; next sweep when the staleness ceiling expires or a game goes live"
		print(
			f"[live_refresh_loop] ODDS_REFRESH_OFF_HOURS_SKIPPED max_staleness_s={_off_hours_max_staleness_seconds()}",
			flush=True,
		)
		skip_launch = True
	if not skip_launch:
		# #15 Phase 1: per-sport pregame cadence. A sport whose OWN games are
		# not live doesn't need the tick cadence -- its lines drift, they
		# don't move -- and before this filter every non-live sport rode
		# whatever cadence the loop was on, including MLB's 60s LIVE cadence
		# for the whole of a 14h slate. Each sport now sweeps pregame at most
		# once per its configured interval (default 2h; soccer 8h, i.e. the
		# 2-3/day a weekly sport's drift actually shows), full cadence
		# resuming the moment that sport itself is live.
		#
		# Deliberately full sweeps, not lines-only: the 2h drift points are
		# also the midday PROP samples the movement/CLV surfaces need
		# (decided 2026-07-27). Market tiering is Phase 2; per-game
		# T-75/T-10 ramp-and-close capture is Phase 3 and outranks it.
		#
		# Event triggers bypass the interval by design: a lineup or injury
		# change IS the movement worth sampling, so force_refresh_sports
		# sweeps regardless of how recent the last drift point was.
		try:
			resolved_launch_sports = (
				[piece for piece in str(launch_sports).split(",") if piece]
				if launch_sports
				else list(_live_refresh_loop_effective_sports(selected_date))
			)
			force_sports = {piece for piece in str(force_refresh_sports or "").split(",") if piece}
			# #82 Phase 3. T-window sweeps bypass the cadence filter the same
			# way lineup changes do: an imminent start IS the reason to sweep.
			# Markers are recorded before the launch (the #25 fail-closed
			# rule: a launch that dies costs one missed window, never a
			# duplicate storm), and only for sports actually in this launch --
			# a sport excluded by owner rules keeps its window armed for the
			# service that owns it.
			t_window_due = _t_window_due_sports(now_epoch=tick_started_epoch, date_str=selected_date)
			t_window_sports = {sport for sport in t_window_due if sport in resolved_launch_sports}
			if t_window_sports:
				meta["tWindowSweeps"] = {sport: sorted(t_window_due[sport]) for sport in t_window_sports}
				print(
					f"[live_refresh_loop] T_WINDOW_SWEEP_DUE {json.dumps(meta['tWindowSweeps'], sort_keys=True)}",
					flush=True,
				)
				for sport in t_window_sports:
					_record_t_window_markers(selected_date, t_window_due[sport])
				force_sports |= t_window_sports
			kept_sports, cadence_skipped = _apply_pregame_sport_cadence(
				resolved_launch_sports,
				now_epoch=tick_started_epoch,
				force_sports=force_sports,
			)
			if cadence_skipped:
				meta["pregameCadenceSkipped"] = cadence_skipped
				print(
					f"[live_refresh_loop] PREGAME_CADENCE_SKIPPED sports={','.join(sorted(cadence_skipped))}",
					flush=True,
				)
				if not kept_sports:
					meta["ok"] = False
					meta["skipped"] = True
					meta["error"] = "pregame cadence: every sport swept within its own interval; nothing due"
					skip_launch = True
				else:
					launch_sports = ",".join(kept_sports)
			# Nothing dropped: leave launch_sports EXACTLY as it was --
			# None means launch_refresh_run resolves the active set itself,
			# and that contract must survive this filter untouched.
		except Exception as exc:
			# The filter must never be the reason odds stop refreshing --
			# fail open to the unfiltered launch.
			print(f"[live_refresh_loop] PREGAME_CADENCE_FILTER_FAILED error={type(exc).__name__}: {exc}", flush=True)
	if not skip_launch:
		if effective_phase == "pregame":
			_record_pregame_launch(tick_started_epoch, selected_date)
		# Fail-closed (#25): record the ATTEMPT before launching, not the
		# success after. These markers are what the interval gates read to
		# decide "did we already refresh recently", and they used to be
		# written inside the try below, after launch_refresh_run returned.
		#
		# launch_refresh_run spawns a detached subprocess and then does more
		# work (state writes, manifest bookkeeping). If it raises AFTER the
		# spawn -- or the container is killed in that window -- the sweep is
		# genuinely running but no marker exists, so the next tick sees "no
		# recent launch" and starts a SECOND one. That is two concurrent
		# OddsAPI sweeps (#20) burning credits against a budget already over
		# target, and it is the same shape as the look-ahead firing at ~28min
		# instead of 60 (#24).
		#
		# Recording first inverts the failure: a launch that dies costs one
		# skipped interval instead of a duplicate sweep. A missed refresh is
		# self-correcting on the next tick; a duplicate is not -- it burns
		# credits and can stack two heavy pipelines in a 2GB container.
		# _record_pregame_launch above already had it right.
		_record_odds_refresh_launch(tick_started_epoch)
		try:
			# launch_sports is None when unconfigured (launch_refresh_run then
			# resolves the full season-active-for-date set itself) -- resolve
			# the same way here rather than assuming an unset launch_sports
			# means WNBA wasn't included.
			launched_sports = launch_sports.split(",") if launch_sports else _live_refresh_loop_effective_sports(selected_date)
			if "wnba" in launched_sports:
				_record_wnba_odds_refresh_launch(tick_started_epoch)
			# #15 Phase 1: per-sport sweep markers, recorded for every sport
			# in the launch (live included -- the filter only consults a
			# marker when the sport is NOT live, and a marker refreshed
			# during live play just means the first post-slate pregame sweep
			# waits one interval, with the slate-end data still fresh).
			_record_pregame_sport_sweep_epochs(tick_started_epoch, list(launched_sports))
		except Exception as exc:
			# Resolving the sport list must never be the reason a refresh
			# doesn't launch; the WNBA marker is only a gate input.
			print(f"[live_refresh_loop] WNBA_LAUNCH_MARKER_SKIPPED error={type(exc).__name__}: {exc}", flush=True)
		try:
			result = launch_refresh_run(
				date=meta["date"],
				sports=launch_sports,
				phase=str(meta["phase"]),
				regions=str(meta["regions"]),
				mode=str(meta["mode"]),
				execution_mode=str(meta["executionMode"]),
				launch_mode=_live_refresh_loop_launch_mode(),
				skip_mirror=bool(meta["skipMirror"]),
				mirror_only=False,
				dry_run=False,
				force_refresh=force_sim_rerun,
				force_refresh_sports=force_refresh_sports,
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

	meta["finishedAt"] = _utc_now()
	write_json_file(_meta_dir() / "latest_live_refresh_tick.json", meta)
	try:
		publish_since_epoch = _hot_artifact_publish_since_epoch(tick_started_epoch=tick_started_epoch)
		sweep_result = sweep_changed_hot_artifacts(publish_since_epoch)
		meta["publishedArtifacts"] = sweep_result.published_count
		if sweep_result.all_succeeded:
			# Only advance the watermark once every candidate in this window
			# is confirmed published -- publish_hot_artifact never raises on
			# a transient failure (network blip, web service momentarily
			# unreachable), so advancing unconditionally would silently and
			# permanently skip a file that failed for a reason that would
			# have succeeded on retry. Leaving the watermark in place makes
			# the next tick re-sweep this same window, including any file
			# that failed here (re-publishing an already-succeeded file is
			# a harmless duplicate POST).
			_record_hot_artifact_publish_watermark(tick_started_epoch)
		else:
			meta["publishFailedCount"] = len(sweep_result.failed_paths)
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