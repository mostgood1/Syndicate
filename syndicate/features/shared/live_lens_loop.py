from __future__ import annotations

import atexit
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from syndicate.features.shared.artifact_publisher import sweep_changed_hot_artifacts
from syndicate.features.shared.artifact_publisher import pull_hot_artifacts
from syndicate.features.mlb.live_lens import build_live_lens_snapshot_internal as _mlb_build
from syndicate.features.mlb.live_lens import live_lens_snapshot_path as _mlb_snapshot_path
from syndicate.features.mlb.live_lens import validate_live_lens_snapshot as _mlb_validate
from syndicate.features.nba.live_lens import build_live_lens_snapshot as _nba_build
from syndicate.features.nba.live_lens import live_lens_snapshot_path as _nba_snapshot_path
from syndicate.features.nba.live_lens import validate_live_lens_snapshot as _nba_validate
from syndicate.features.nfl.live_lens import build_live_lens_snapshot as _nfl_build
from syndicate.features.nfl.live_lens import live_lens_snapshot_path as _nfl_snapshot_path
from syndicate.features.nfl.live_lens import validate_live_lens_snapshot as _nfl_validate
from syndicate.features.nfl.sources import default_week as _nfl_default_week
from syndicate.features.nfl.sources import latest_season as _nfl_latest_season
from syndicate.features.nfl.sources import preseason_target_week as _nfl_preseason_target_week
# #327: log_and_persist, not log_all_process_memory. These three call sites were
# the THIRD emitter -- after the two identically-named `_diag_log_all_process_memory`
# helpers were unified, these still wrote stderr only, so `live_lens_tick_*`
# stayed invisible to the ring buffer and read as zero however long anyone
# watched. `append_to_ring=False` keeps their ~6.6/min out of the time series
# (which would rotate it below the 11-42 min excursion gap) while still
# recording each stage's high-water mark.
from syndicate.features.shared.memory_observability import log_and_persist_process_memory
from syndicate.features.shared.memory_observability import memory_headroom_snapshot
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.soccer.live_lens import live_lens_snapshot_path as _soccer_snapshot_path
from syndicate.features.soccer.live_lens import validate_live_lens_snapshot as _soccer_validate
from syndicate.features.wnba.live_lens import build_live_lens_snapshot as _wnba_build
from syndicate.features.wnba.live_lens import live_lens_snapshot_path as _wnba_snapshot_path
from syndicate.features.wnba.live_lens import validate_live_lens_snapshot as _wnba_validate

# Deliberate exception to this codebase's usual scripts-depend-on-syndicate
# direction: soccer's live-tick Monte Carlo orchestration (poll_league,
# _load_player_rows/_load_team_ratings reuse) already lives in
# scripts/poll_soccer_live_state.py, sharing helpers with
# scripts/build_soccer_artifacts.py -- duplicating that into syndicate/ would
# cost more (two copies of the sim-input-building logic to keep in sync)
# than importing the one entrypoint function back. Safe at runtime: every
# process that loads this module (run_refresh_worker.py / the live-odds-worker
# equivalent) already inserts REPO_ROOT onto sys.path at its own startCommand
# entrypoint, so `scripts` resolves as an importable package by the time this
# import executes.
from scripts.poll_soccer_live_state import poll_active_leagues_for_tick as _soccer_poll_active_leagues

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


def _nfl_build_wrapper(date_str: str) -> dict[str, Any]:
	# NFL's live-lens snapshot is week-scoped, not date-scoped like every
	# other sport this loop drives -- date_str (central_today_iso(), passed
	# uniformly to every sport's builder by _run_live_lens_tick) isn't
	# actually usable to pick a week, so resolve the currently tracked
	# season/week the same way the route's own default resolution does
	# (nfl/sources.py's latest_season()/default_week()) instead of ignoring
	# the date_str parameter silently.
	#
	# preseason_target_week() is checked FIRST -- the same real "which phase
	# is actually current" signal _build_sport_overview (home.py) and
	# _NFLDataProvider.games() already use, both fixed earlier this session.
	# default_week()/nfl_target_week() both still say "week 1" as soon as the
	# regular season is next up, even while genuinely still in preseason (no
	# regular-season game has been played yet either way) -- week number
	# alone can't tell the two phases apart. Without this, the loop would
	# resolve week=1/regular-season every single tick during preseason and
	# build_live_lens_snapshot would never see a real preseason week, even
	# though it independently re-derives the same signal itself as a second
	# line of defense.
	season = _nfl_latest_season()
	preseason_week = _nfl_preseason_target_week(season)
	week = preseason_week if preseason_week is not None else _nfl_default_week(season)
	return _nfl_build(week, season)


def _soccer_live_lens_tick_simulations() -> int:
	# Soccer's live tick (poll_league -> project_live_match + 2x
	# goal_in_window_probability + project_live_player_props, 4 separate
	# Monte Carlo passes per in-progress match) is architecturally the
	# soccer analog of MLB's 120-sim live resim, not WNBA/NBA's cheap
	# deterministic blend -- see _soccer_live_lens_headroom_snapshot below.
	# The standalone script's own --simulations CLI default (300, for a
	# manual/dedicated one-off run) stays unchanged; this is a separate,
	# lower default specifically for the frequent 60s-cadence tick, to keep
	# per-tick cost bounded when multiple leagues/matches are live at once.
	raw = str(os.environ.get("SYNDICATE_SOCCER_LIVE_LENS_TICK_SIMULATIONS") or "").strip()
	try:
		value = int(raw or 80)
	except Exception:
		value = 80
	return max(20, value)


def _soccer_source_root() -> Path:
	roots = preferred_source_roots(__file__, env_var="SYNDICATE_SOCCER_SOURCE_ROOT", local_dir_name="soccer_source")
	return roots[0]


def _soccer_build_wrapper(date_str: str) -> dict[str, Any]:
	root = _soccer_source_root()
	return _soccer_poll_active_leagues(
		date_str, source_root=root, out_root=root, simulations=_soccer_live_lens_tick_simulations()
	)


_LIVE_LENS_SPORTS: tuple[str, ...] = ("mlb", "nba", "wnba", "soccer", "nfl")

_LIVE_LENS_BUILDERS: dict[str, Callable[[str], dict[str, Any]]] = {
	"mlb": _mlb_build_wrapper,
	"nba": _nba_build_wrapper,
	"wnba": _wnba_build_wrapper,
	"soccer": _soccer_build_wrapper,
	"nfl": _nfl_build_wrapper,
}

_LIVE_LENS_VALIDATORS: dict[str, Callable[[Any], bool]] = {
	"mlb": _mlb_validate,
	"nba": _nba_validate,
	"wnba": _wnba_validate,
	"soccer": _soccer_validate,
	"nfl": _nfl_validate,
}

_LIVE_LENS_SNAPSHOT_PATHS: dict[str, Callable[[], Path]] = {
	"mlb": _mlb_snapshot_path,
	"nba": _nba_snapshot_path,
	"wnba": _wnba_snapshot_path,
	"soccer": _soccer_snapshot_path,
	"nfl": _nfl_snapshot_path,
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


def _soccer_live_lens_memory_gate_enabled() -> bool:
	return _env_bool("SYNDICATE_SOCCER_LIVE_LENS_MEMORY_GATE_ENABLED", default=True)


def _soccer_live_lens_min_headroom_bytes() -> int:
	# Soccer's tick (poll_active_leagues_for_tick -> poll_league per active
	# league) runs up to 4 separate Monte Carlo passes per in-progress match
	# (project_live_match, 2x goal_in_window_probability,
	# project_live_player_props), same class of per-tick cost as MLB's real
	# resim -- unlike WNBA/NBA's cheap logistic blend, which stays ungated.
	# 300MB starts from the same calibration philosophy #124 already
	# established for MLB (worst-measured-cost + margin), but this specific
	# number is NOT yet backed by a real production measurement of soccer's
	# per-tick RSS delta the way MLB's is -- there was no live match in
	# progress to measure against when this was built. Revisit with a real
	# measurement (log_all_process_memory before/after a live soccer tick)
	# once matches are actually running through this path in production;
	# do not let this number silently drift into being treated as measured.
	raw = str(os.environ.get("SYNDICATE_SOCCER_LIVE_LENS_MIN_HEADROOM_MB") or "").strip()
	try:
		value = int(raw or 300)
	except Exception:
		value = 300
	return max(0, value) * 1024 * 1024


def _soccer_live_lens_headroom_snapshot() -> dict[str, Any] | None:
	if not _soccer_live_lens_memory_gate_enabled():
		return None
	return memory_headroom_snapshot(_soccer_live_lens_min_headroom_bytes())


def _wnba_live_lens_memory_gate_enabled() -> bool:
	return _env_bool("SYNDICATE_WNBA_LIVE_LENS_MEMORY_GATE_ENABLED", default=True)


def _wnba_live_lens_min_headroom_bytes() -> int:
	"""CALIBRATED FROM A REAL PRODUCTION MEASUREMENT, as this file already
	instructed -- see `_mlb_live_lens_headroom_snapshot`'s own comment:

	    "WNBA's builder now also computes a real live win-probability ... but
	     deliberately still isn't gated here -- that computation is a clock
	     parse + one logistic call + one blend, not a sampling loop, so its cost
	     is expected to be negligible like NBA's. If real measurement ever shows
	     otherwise, calibrate a WNBA-specific gate from that measurement --
	     never copy this function's number."

	Real measurement now shows otherwise. live-odds-worker (2Gi), 2026-08-08:

	    03:03:54   581.5MB   live_lens_tick_after_build_nba
	    03:04:01  1644.1MB   live_lens_tick_after_build_wnba   <- +1,062MB

	One step, the single largest allocation on that service, and the ONLY
	ungated builder in the tick. It OOM-killed the container repeatedly and
	then crash-looped: boots at 03:07:56, 03:09:09, 03:10:31, 03:12:07.

	1200MB was the measured 1,062MB plus ~13% margin.

	RE-CALIBRATED 2026-08-08 to 300MB, and the reason is the one this file keeps
	learning: THE STAGE IT GUARDS CHANGED EIGHT MINUTES AFTER THE NUMBER WAS SET.
	`44008605` landed at 22:24 CDT and removed the `build_cards_page_context`
	call that the 1,062MB was a measurement OF; `56d67061` set 1200MB at 22:16
	against a builder that no longer exists in that form. A threshold calibrated
	to a deleted cost is the #124 defect wearing new clothes.

	What the guarded step costs NOW, measured on refresh-worker (4096MB) across
	all 7 WNBA ticks 2026-08-08 18:00-21:45Z (before -> after_build, container):

	    595.3 ->  748.8   (+153.5)      793.7 ->  863.3   (+69.6)
	    703.9 ->  792.5   ( +88.7)      765.4 ->  857.8   (+92.4)
	    708.0 ->  797.2   ( +89.3)     1051.0 -> 1122.9   (+71.9)
	                                   1105.8 -> 1179.0   (+73.2)

	Worst 153.5MB, mean ~91MB. 300MB is worst-measured + ~95% margin -- the same
	"worst measured + margin" philosophy #124 established, applied to what this
	gate actually guards. It now matches MLB's number by CONVERGENCE, not by
	copying: two different builders were separately measured into the same
	neighbourhood.

	It did not fire once in that window (0 of 7 skipped, headroom 2.9-3.5GB), so
	this is not the cause of the WNBA live-lens regression -- see
	`load_published_cards_page_context` for what was. It is still worth fixing:
	refresh-worker also holds the MLB daily sim, and a 1200MB bar on a service
	that has been measured past 1.4GB resident would silently skip a ~90MB step
	at exactly the moment a live slate is running.
	"""
	raw = str(os.environ.get("SYNDICATE_WNBA_LIVE_LENS_MIN_HEADROOM_BYTES") or "").strip()
	try:
		return max(0, int(raw)) if raw else 300 * 1024 * 1024
	except ValueError:
		return 300 * 1024 * 1024


def _wnba_live_lens_headroom_snapshot() -> dict[str, Any] | None:
	if not _wnba_live_lens_memory_gate_enabled():
		return None
	return memory_headroom_snapshot(_wnba_live_lens_min_headroom_bytes())


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
		log_and_persist_process_memory(f"live_lens_tick_before_{sport}", append_to_ring=False, sport=sport, date=date_str)
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
		if sport == "soccer":
			headroom_snapshot = _soccer_live_lens_headroom_snapshot()
			if headroom_snapshot is not None and not headroom_snapshot["sufficient"]:
				meta["ok"] = False
				meta["skipped"] = True
				meta["reason"] = "low_headroom"
				meta["memoryHeadroom"] = headroom_snapshot
				return meta
		if sport == "wnba":
			# The LAST ungated builder, and measurement showed it is the most
			# expensive one on this service by a wide margin: +1,062MB in a
			# single step (581.5 -> 1644.1MB, 2026-08-08), which OOM-killed a
			# 2Gi container and then crash-looped it.
			#
			# The two sports that already had gates are the cheap ones here
			# (MLB +97MB, soccer negligible on the same tick). The gates were
			# placed by reasoning about which builder LOOKED heavy -- a resim
			# loop -- and WNBA's was exempted for looking like "a clock parse
			# plus one logistic call". Printed, like MLB's, because a gate that
			# fires silently cannot be told from a builder that never ran.
			headroom_snapshot = _wnba_live_lens_headroom_snapshot()
			if headroom_snapshot is not None and not headroom_snapshot["sufficient"]:
				meta["ok"] = False
				meta["skipped"] = True
				meta["reason"] = "low_headroom"
				meta["memoryHeadroom"] = headroom_snapshot
				print(f"[LIVE_LENS_TICK_DIAG] sport=wnba ok=False reason=low_headroom headroom={headroom_snapshot}", flush=True)
				return meta
		builder = _LIVE_LENS_BUILDERS[sport]
		validator = _LIVE_LENS_VALIDATORS[sport]
		path_fn = _LIVE_LENS_SNAPSHOT_PATHS[sport]
		snapshot = builder(date_str)
		log_and_persist_process_memory(f"live_lens_tick_after_build_{sport}", append_to_ring=False, sport=sport, date=date_str)
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
		log_and_persist_process_memory(f"live_lens_tick_after_{sport}", append_to_ring=False, sport=sport, date=date_str, ok=bool(meta.get("ok")))
	return meta


def _live_lens_active_sports() -> tuple[str, ...]:
	"""Which of the REGISTERED sports this service should actually tick.

	`_LIVE_LENS_SPORTS` is the registry -- what has a builder, a validator and a
	snapshot path. It is not, and was being used as, the answer to "what should
	this service work on". Measured 2026-08-08: refresh-worker's
	`SYNDICATE_ACTIVE_SPORTS` is `mlb,wnba,soccer,nfl`, yet the loop built NBA
	every cycle at 1.6-42s and up to +321MB for a sport with no August slate --
	roughly 10% of the long cycles. Nothing reconciled the two lists, and
	`SYNDICATE_ACTIVE_SPORTS` was read in only two places, both web navigation
	(`syndicate/app.py`, `blueprints/home.py`).

	TWO DELIBERATE REFUSALS TO LET CONFIG SILENCE THE LOOP, because a background
	stage that stops for a config reason and says nothing is the defect this
	module keeps shipping:

	  * UNSET means tick everything registered. It does NOT mean fall back to
	    `home.py`'s `"mlb,wnba"` default, which would silently drop soccer, nfl
	    and nba from the tick on any service that forgot the variable.
	  * A value that matches NOTHING (a typo, a renamed sport) also ticks
	    everything, rather than ticking nothing. An empty intersection is far
	    more likely to be a mistake than an intention.

	Either way the skipped set is reported on every tick -- see `_run_live_lens_tick`.
	"""
	raw = str(os.environ.get("SYNDICATE_ACTIVE_SPORTS") or "").strip()
	if not raw:
		return _LIVE_LENS_SPORTS
	configured = {part.strip().lower() for part in raw.split(",") if part.strip()}
	active = tuple(sport for sport in _LIVE_LENS_SPORTS if sport in configured)
	return active or _LIVE_LENS_SPORTS


def _run_live_lens_tick() -> dict[str, Any]:
	date_str = central_today_iso()
	active_sports = _live_lens_active_sports()
	skipped_sports = [sport for sport in _LIVE_LENS_SPORTS if sport not in active_sports]
	results = {sport: _run_live_lens_tick_for_sport(sport, date_str) for sport in active_sports}
	meta = {
		"startedAt": _utc_now(),
		"date": date_str,
		"activeSports": list(active_sports),
		# Named, not merely absent. A sport missing from `results` is
		# indistinguishable from a sport whose tick never got that far, and
		# "not configured for this service" and "failed" must not share a
		# spelling.
		"skippedSports": skipped_sports,
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
	#
	# THE WATERMARK MUST BE STAMPED AT THE PUBLISH, NOT AT THE CYCLE START, and
	# for four months it was stamped at the cycle start. Every file the tick
	# writes has an mtime in [cycle_start, publish_start], which is strictly
	# GREATER than a watermark set to cycle_start -- so the next cycle matched
	# all of them again and re-sent everything the previous cycle had just sent.
	# Each artifact went over the wire at least twice.
	#
	# Measured on refresh-worker 2026-08-08 21:31-22:05Z (n=8, deploy-free):
	# publish was 48-74s per cycle at 73-103 artifacts, on a 246s median cycle
	# whose configured interval is 60s -- so this was ~20-30% of the loop's wall
	# clock with roughly half of it a resend, on the tick's own thread, ahead of
	# every subsequent build.
	#
	# Stamping at publish_start (not after the publish returns) is deliberate:
	# anything written DURING the sweep is then picked up next cycle rather than
	# skipped. The bias stays on the safe side -- at worst one extra send, never
	# a dropped file. There is no threshold here and nothing to tune; a guessed
	# interval on this call is exactly the kind of number that silently disables
	# the stage it guards.
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
			publish_started_epoch = time.time()
			try:
				# sweep_changed_hot_artifacts, NOT the publish_changed_hot_artifacts
				# wrapper. `publish_hot_artifact` NEVER RAISES -- a network blip or
				# an unreachable web service returns False and is logged -- so
				# "did not throw" is not "everything went through", and this call
				# site was advancing its watermark on the weaker of the two.
				# `HotArtifactSweepResult.all_succeeded` exists for exactly this
				# and its own docstring names the failure: "a caller that advances
				# a persisted watermark on any non-raising return would
				# permanently skip a file that failed for a transient reason".
				# That was still true here after the watermark fix above.
				sweep = sweep_changed_hot_artifacts(last_publish_epoch)
				if sweep.published_count or sweep.failed_paths:
					print(
						f"[live_lens_loop] published_hot_artifacts count={sweep.published_count} "
						f"failed={len(sweep.failed_paths)} "
						f"window_seconds={round(publish_started_epoch - last_publish_epoch, 1)} "
						f"elapsed_seconds={round(time.time() - publish_started_epoch, 1)}",
						flush=True,
					)
				# Advance ONLY past a window every candidate in which is confirmed
				# published. A failure then retries next cycle instead of vanishing
				# -- the same reasoning pull_hot_artifacts already applies to its
				# own persisted watermark.
				if sweep.all_succeeded:
					last_publish_epoch = publish_started_epoch
			except Exception as exc:
				print(f"[live_lens_loop] publish_hot_artifacts_failed error={type(exc).__name__}: {exc}", flush=True)
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
		print(
			f"[live_lens_loop] TICK_COMPLETE results={summary} "
			f"skipped={meta.get('skippedSports') or []} "
			f"nextIntervalSeconds={interval_seconds}",
			flush=True,
		)
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
