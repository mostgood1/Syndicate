"""The NCAAB in-play odds lane: NBA's 240 s live lane, for college basketball.

User 2026-11-02: "Live betting NCAAB is the most important part of its usage"
and, given the cost estimate, "Build it now". Before this NCAAB had no in-play
capture of its own: it rode the shared live sweep (no live checker, so it went
into whichever sweep launched), and measured right after the 15:55Z restart
that was 3 NCAAB snapshots in ~55 min.

WHAT A PULL COSTS. `refresh_ncaab_odds_history.py --in-play-only`: one bulk
`/odds` call (3 credits: h2h/spreads/totals for EVERY event, live included) plus
the half markets per STARTED game (~4 credits before halftime, ~2 after). At a
40-game evening peak that is ~123 credits a pull, ~15 pulls an hour = ~1,850
credits/h (the estimate the user approved); an afternoon with 3 games live is
~200/h. Nothing launches while no NCAAB game is live.

LAUNCHED BY the live-odds-worker's in-play capture thread, beside NBA's
(`_launch_inplay_capture_autoruns`), and shaped exactly like
`_launch_autorun_nba_live_refresh`: forced live-phase run on its own lane, so it
never queues behind the shared sweep; `refresh_odds_sources._in_play_only_scope`
turns that run into `--in-play-only`.

DEFAULT ON, the NBA lane's precedent: the local fleet derives role env only at
`up`, so a default-off switch could not be turned on without restarting every
role. SYNDICATE_ENABLE_NCAAB_LIVE_REFRESH_AUTORUN=0 turns it off.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.refresh_state_store import read_json_file, reports_root, write_json_file
from syndicate.features.shared.timezone import central_today_iso

# A game that tipped this long ago and is still not final on the slate is
# treated as live: the slate is refreshed by the refresh-worker, so it can trail
# the real clock by a few minutes in either direction.
_LIVE_AFTER_TIP_SECONDS = 3 * 3600


# BOTH COLLEGE LEAGUES (lane wncaab-module, 2026-11-02): every switch, lane name, status file and log tag
# is keyed by league -- `ncaab` keeps exactly the names it shipped with; women's college basketball gets
# SYNDICATE_ENABLE_WNCAAB_LIVE_REFRESH_AUTORUN, lane `live-odds-worker-wncaab-live`, WNCAAB_LIVE_AUTORUN_*.
def ncaab_live_refresh_enabled(league: str = "ncaab") -> bool:
    raw = str(os.environ.get(f"SYNDICATE_ENABLE_{league.upper()}_LIVE_REFRESH_AUTORUN") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def ncaab_live_refresh_interval_seconds(league: str = "ncaab") -> int:
    raw = str(os.environ.get(f"SYNDICATE_{league.upper()}_LIVE_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw or 240)
    except ValueError:
        value = 240
    return max(60, value)


def ncaab_live_refresh_lane(league: str = "ncaab") -> str:
    return str(os.environ.get(f"SYNDICATE_{league.upper()}_LIVE_REFRESH_LANE") or "").strip() or f"live-odds-worker-{league}-live"


def _status_path(league: str = "ncaab") -> Path:
    return reports_root() / "refresh_status" / "latest" / f"{league}_live_autorun_status.json"


def ncaab_live_game_count(date_iso: str, *, now: datetime | None = None, league: str = "ncaab") -> int:
    """D1 games in progress on the slate, or tipped < 3 h ago and not final."""
    from syndicate.features.ncaab.slate import read_slate

    moment = now or datetime.now(timezone.utc)
    count = 0
    for game in (read_slate(date_iso, league) or {}).get("games") or []:
        live = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
        if live.get("final"):
            continue
        if live.get("in_progress"):
            count += 1
            continue
        try:
            start = datetime.fromisoformat(str(game.get("start_time_utc") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if 0 <= (moment - start).total_seconds() <= _LIVE_AFTER_TIP_SECONDS:
            count += 1
    return count


def _is_contention(exc: Exception) -> bool:
    """`launch_refresh_run`'s "a run is already active" refusal: nothing was attempted."""
    try:
        from syndicate.features.shared.ops_refresh import RefreshRunRefused

        if isinstance(exc, RefreshRunRefused):
            return True
    except ImportError:
        pass
    return isinstance(exc, ValueError) and "already active" in str(exc)


# PREGAME SIMS (lane wncaab-module, Phase 3, user 2026-11-02 "Straight to the boards"). Launched from THIS
# worker so the child inherits the live tier's engine switches (HALF_SPLIT / EXACT_TARGET / mechanisms): the
# board's pregame numbers come from the same engine configuration as its live ones. One child at a time, at
# low priority, each bounded by a budget so a deploy preflight is never held for long; the producer re-sims
# only games whose inputs changed (`college_basketball/pregame_sim.py`). SYNDICATE_COLLEGE_PREGAME_SIM=0 is off.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_pregame_child: Any = None
_pregame_last_launch = 0.0


def pregame_sim_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_COLLEGE_PREGAME_SIM") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _env_seconds(name: str, default: int, floor: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return max(floor, int(raw)) if raw else default
    except ValueError:
        return default


def _pregame_dates() -> list[str]:
    today = central_today_iso()
    return [today, (date.fromisoformat(today) + timedelta(days=1)).isoformat()]


def _pregame_game_count(dates: list[str], league: str) -> int:
    from syndicate.features.college_basketball.pregame_sim import is_pregame
    from syndicate.features.ncaab.slate import read_slate

    moment = datetime.now(timezone.utc)
    return sum(1 for d in dates for g in (read_slate(d, league) or {}).get("games") or [] if is_pregame(g, moment))


def maybe_launch_pregame_sims(league: str = "ncaab", *, popen: Callable[..., Any] = subprocess.Popen,
                              clock: Callable[[], float] = time.monotonic) -> dict[str, Any] | None:
    """Start `scripts/build_college_pregame_sims.py` when the last child has exited, the interval has passed and
    the slate shows a pregame game today or tomorrow. Returns what it launched, or None."""
    global _pregame_child, _pregame_last_launch
    if not pregame_sim_enabled():
        return None
    if _pregame_child is not None:
        code = _pregame_child.poll()
        if code is None:
            return None
        print(f"[live_odds_worker] COLLEGE_PREGAME_SIM_EXITED league={league} rc={code}", flush=True)
        _pregame_child = None
    interval = _env_seconds("SYNDICATE_COLLEGE_PREGAME_INTERVAL_SECONDS", 900, 300)
    if _pregame_last_launch and clock() - _pregame_last_launch < interval:
        return None
    dates = _pregame_dates()
    pregame = _pregame_game_count(dates, league)
    if pregame <= 0:
        return None
    budget = _env_seconds("SYNDICATE_COLLEGE_PREGAME_BUDGET_SECONDS", 600, 60)
    command = [sys.executable, str(_REPO_ROOT / "scripts" / "build_college_pregame_sims.py"), "--league", league,
               "--dates", ",".join(dates), "--budget-seconds", str(budget)]
    nice = shutil.which("nice")
    if nice:
        command = [nice, "-n", "15", *command]
    _pregame_child = popen(command, cwd=str(_REPO_ROOT))
    _pregame_last_launch = clock()
    print(f"[live_odds_worker] COLLEGE_PREGAME_SIM_LAUNCHED league={league} dates={','.join(dates)} pregame_games={pregame} "
          f"budget_s={budget} interval_s={interval} pid={getattr(_pregame_child, 'pid', None)}", flush=True)
    return {"league": league, "dates": dates, "pregame_games": pregame, "budget_s": budget}


def launch_autorun_ncaab_live_refresh(league: str = "ncaab") -> dict[str, Any] | None:
    """One tick of the lane for `league` (`ncaab` / `wncaab`). Returns what it launched, or None."""
    tag = league.upper()
    if league == "ncaab":
        try:
            maybe_launch_pregame_sims("ncaab")
        except Exception as exc:  # noqa: BLE001 -- the pregame sim must never cost the odds lane
            print(f"[live_odds_worker] COLLEGE_PREGAME_SIM_LAUNCH_FAILED {type(exc).__name__}: {exc}", flush=True)
    if not ncaab_live_refresh_enabled(league):
        return None
    selected_date = central_today_iso()
    live_games = ncaab_live_game_count(selected_date, league=league)
    if live_games <= 0:
        return None
    # The rail's live line (run + bonus) for both college leagues: one capture thread per process,
    # started the first time either league has a live game (`college_basketball/momentum_capture.py`).
    try:
        from syndicate.features.college_basketball.momentum_capture import ensure_capture_thread

        ensure_capture_thread()
    except Exception as exc:  # noqa: BLE001 -- the run line must never cost the odds lane
        print(f"[live_odds_worker] COLLEGE_MOMENTUM_START_FAILED {type(exc).__name__}: {exc}", flush=True)
    status_path = _status_path(league)
    last_status = read_json_file(status_path) or {}
    if last_status and not last_status.get("reported"):
        err = last_status.get("error")
        print(f"[live_odds_worker] {tag}_LIVE_AUTORUN_PREV date={last_status.get('date')} "
              + (f"FAILED {err}" if err else f"launched=ok runStamp={last_status.get('runStamp')}"), flush=True)
        try:
            write_json_file(status_path, {**last_status, "reported": True})
        except Exception:  # noqa: BLE001
            pass
    last_epoch = float(last_status.get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(ncaab_live_refresh_interval_seconds(league)):
        return None
    try:
        result = launch_refresh_run(
            date=selected_date,
            sports=league,
            phase="live",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode="fast",
            launch_mode="web_process",
            force_refresh=True,
            force_refresh_sports=league,
            lane=ncaab_live_refresh_lane(league),
        )
    except Exception as exc:  # noqa: BLE001
        if _is_contention(exc):
            # Keep the old epoch: the next tick retries instead of waiting a full interval.
            write_json_file(status_path, {**last_status, "sports": league, "date": selected_date,
                                          "error": f"{type(exc).__name__}: {exc}", "reported": False})
        else:
            write_json_file(status_path, {"epoch": time.time(), "sports": league, "date": selected_date,
                                          "error": f"{type(exc).__name__}: {exc}"})
        print(f"[live_odds_worker] {tag}_LIVE_AUTORUN_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None
    run_stamp = (result or {}).get("runStamp") or (result or {}).get("run_stamp")
    write_json_file(status_path, {"epoch": time.time(), "sports": league, "date": selected_date,
                                  "runStamp": run_stamp, "live_games": live_games, "reported": False})
    print(f"[live_odds_worker] {tag}_LIVE_AUTORUN_LAUNCHED date={selected_date} phase=live mode=fast force={league} "
          f"live_games={live_games} lane={ncaab_live_refresh_lane(league)} interval_s={ncaab_live_refresh_interval_seconds(league)}", flush=True)
    return {"date": selected_date, "live_games": live_games, "runStamp": run_stamp}


def launch_autorun_wncaab_live_refresh() -> dict[str, Any] | None:
    """Women's college basketball's in-play lane (lane wncaab-module): quarter + half lines for live games."""
    return launch_autorun_ncaab_live_refresh("wncaab")
