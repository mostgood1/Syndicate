from __future__ import annotations

import argparse
import atexit
import gc
import random
import signal
import sys
import time
import json
from pathlib import Path

import os

try:
    import psutil
except Exception:
    psutil = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.live_refresh_loop import _live_refresh_loop_interval_seconds
from syndicate.features.shared.live_refresh_loop import _live_refresh_loop_interval_for_meta
from syndicate.features.shared.live_refresh_loop import _run_live_refresh_tick
from syndicate.features.shared.live_refresh_loop import _acquire_process_lock
from syndicate.features.shared.live_refresh_loop import _release_process_lock
from syndicate.features.shared.live_refresh_loop import _LIVE_REFRESH_LOOP_STOP
from syndicate.features.shared.live_refresh_loop import _wnba_has_live_game
from syndicate.features.shared.live_lens_loop import start_live_lens_loop
from syndicate.features.shared.refresh_state_store import assert_refresh_state_backend_ready
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.memory_observability import log_all_process_memory
from syndicate.features.shared.memory_observability import log_runtime_memory
from syndicate.features.shared.ops_refresh import _active_sports_for_date
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.timezone import central_today_iso
from vendor.mlb_bettingv2.tools.web.flask_frontend import start_live_lens_background_loop


# #148. Soccer's pregame steps (schedule/odds/props/picks --
# scripts/refresh_odds_sources.py's _build_soccer_steps, phases=("pregame",))
# depend on _run_live_refresh_tick's shared adaptive phase ever actually
# resolving to "pregame" -- but that phase is a single GLOBAL decision across
# ALL active sports (effective_phase = "live" the instant ANY sport anywhere
# has a live game), not per-sport. With MLB/WNBA/NBA running live games most
# evenings, soccer's own per-sport pregame-cadence window
# (_apply_pregame_sport_cadence, 8h) and the tick's global phase being
# genuinely "pregame" rarely coincide in practice -- confirmed live
# 2026-07-30: MLB's live game made effective_phase="live" while soccer was
# independently "due" for its own sweep, so soccer's pregame steps still got
# filtered out of that tick's launch entirely. That's why #137/#146's own
# workaround put a dedicated, unconditional autorun on refresh-worker instead
# (phase="all", bundling odds+props+schedule with the sim) -- but that made
# refresh-worker a second direct OddsAPI caller for soccer, the same
# violation class fixed for MLB in #139/#144.
#
# This is the real fix: an independent, soccer-scoped pregame trigger that
# never depends on the shared tick's cross-sport phase at all -- runs on its
# own cadence, calls launch_refresh_run(phase="pregame") directly, only ever
# covering schedule/odds/props/picks (odds ownership stays on
# live-odds-worker, where it belongs). refresh-worker's own autorun now
# requests phase="live" only, keeping just the sim (soccer_{league}_artifacts,
# phases=("pregame","live")) and live_state polling.
def _is_refresh_run_contention_error(exc: Exception) -> bool:
    """True when `exc` is `launch_refresh_run`'s "already active" mutex
    ValueError specifically -- i.e. NOTHING was actually attempted here,
    some OTHER job (often a protected in-flight sim) legitimately holds the
    shared "one refresh run active" slot right now.

    `#472`: both `_launch_autorun_soccer_pregame_refresh` and
    `_launch_autorun_wnba_pregame_refresh` used to write a fresh, full-
    interval-resetting epoch on EVERY exception here, contention included --
    conflating "we tried and it's genuinely too soon to try again" (a real
    completed attempt) with "we didn't get a turn" (contention says nothing
    about whether it's too soon). One lost race therefore cost the FULL
    cadence interval (4h default) instead of a short retry. Confirmed live
    2026-08-19: WNBA's autorun succeeded cleanly at ~4h intervals all day
    (01:24/05:24/09:29/13:35Z), then went 5+ hours dark the first time it
    collided with a chain of back-to-back MLB resims (`fingerprint_change`-
    triggered; the sim's own pid was observed switching mid-investigation,
    3311 -> 111, confirming it was genuinely still running, not a stuck
    zombie state). Distinguishing this class is what lets the caller skip
    the epoch-reset for contention only, so the very next tick (the
    worker's own short poll cadence, not this function's interval) retries
    again -- succeeding the moment the slot frees up rather than being
    locked out for up to a full cadence window over one race.
    """
    return isinstance(exc, ValueError) and "already active" in str(exc)


def _soccer_pregame_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("SYNDICATE_ENABLE_SOCCER_PREGAME_REFRESH_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _soccer_pregame_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("SYNDICATE_SOCCER_PREGAME_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 14400)  # 4h -- matches refresh-worker's old cadence for this same work.
    except ValueError:
        value = 14400
    return max(1, value)


def _soccer_pregame_autorun_status_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "soccer_pregame_autorun_status.json"


def _soccer_active_for_date(date_str: str) -> bool:
    active = {item.strip().lower() for item in _active_sports_for_date(date_str).split(",") if item.strip()}
    return "soccer" in active


def _report_previous_soccer_pregame_run(last_status: dict) -> None:
    """Print the PREVIOUS run's per-step outcome to THIS worker's stdout (`#433`).

    WHY THIS EXISTS, and it is not a nice-to-have. Soccer game odds stopped
    being captured on 2026-08-10 and nobody saw an error for four days. Not
    because nothing was logged -- because of WHERE it was logged:

      * `launch_refresh_run` spawns the refresh detached with
        `stdout=DEVNULL, stderr=DEVNULL` (`ops_refresh.py`). Its comment says
        the child's output is "already captured to
        odds_refresh.json/odds_refresh.stderr.txt ... so there's no diagnostic
        value in inheriting them here." That is TRUE and, on this deployment,
        misleading: those files land on **live-odds-worker's own disk**, and
        Render gives the web service a DIFFERENT disk. So
        `/api/ops/odds-refresh/logs` returns `exists=False` from web forever --
        which reads as "no logs" and is really "wrong machine".
      * Render's log collector only captures a service's OWN stdout.

    The worker CAN read its own disk. So rather than inheriting the child's
    stdout -- which would push a full 50-step refresh, thousands of lines, into
    the log collector every 4 hours -- this reads the run artifact the child
    already wrote and emits ONE compact line per step plus a summary.

    Deliberately reports the PREVIOUS run, on the next tick. The launch is
    fire-and-forget by design (`ops_refresh.py` documents that making it
    blocking stalled this worker's tick loop and contributed to an OOM), so
    there is no point at which this function could wait for a result. Reading
    last tick's artifact costs nothing and cannot stall anything.

    Never raises: an observability side-effect must not be able to break the
    autorun it is describing -- the same rule `_append_soccer_book_quotes`
    follows, and the reason a failing shard append stayed silent.
    """
    try:
        artifacts_dir = str((last_status or {}).get("artifactsDir") or "").strip()
        stamp = str((last_status or {}).get("runStamp") or "").strip()
        if not artifacts_dir or (last_status or {}).get("reported"):
            return
        result_path = Path(artifacts_dir) / "odds_refresh.json"
        if not result_path.exists():
            # A launched run with no artifact is itself the finding: the child
            # died before writing anything. Say so -- silence here is what the
            # four-day outage looked like from outside.
            print(
                f"[live_odds_worker] SOCCER_PREGAME_RUN_NO_ARTIFACT stamp={stamp} "
                f"path={result_path} (child wrote nothing)",
                flush=True,
            )
            return
        payload = json.loads(result_path.read_text(encoding="utf-8", errors="replace"))
        results = payload.get("results") or []
        steps = []
        for entry in results if isinstance(results, list) else []:
            generation = (entry or {}).get("generation") or {}
            for step in generation.get("steps") or []:
                steps.append(step)
        ok_count = sum(1 for s in steps if s.get("ok") or s.get("return_code") == 0)
        failed = [s for s in steps if not (s.get("ok") or s.get("return_code") == 0)]
        print(
            f"[live_odds_worker] SOCCER_PREGAME_RUN_SUMMARY stamp={stamp} "
            f"steps={len(steps)} ok={ok_count} failed={len(failed)}",
            flush=True,
        )
        # Only the odds steps by name, plus every failure. The full 50-step list
        # every 4 hours is noise; the odds steps are the ones this outage was
        # about, and a failure anywhere is always worth a line.
        for step in steps:
            name = str(step.get("name") or "")
            is_odds = name.endswith("_odds")
            ok = bool(step.get("ok") or step.get("return_code") == 0)
            if is_odds or not ok:
                print(
                    f"[live_odds_worker] SOCCER_PREGAME_STEP name={name} ok={ok} "
                    f"rc={step.get('return_code')} skipped={step.get('skipped')}",
                    flush=True,
                )
    except Exception as exc:  # noqa: BLE001
        print(f"[live_odds_worker] SOCCER_PREGAME_RUN_SUMMARY_FAILED {type(exc).__name__}: {exc}", flush=True)


# PHASE 2 of the migration off the daily-update GHA cron. Phase 1 moved
# NFL/NCAAF/NCAAB to refresh-worker's weekly autorun (`render.yaml`); WNBA was
# never re-homed, so NOTHING called `refresh_wnba_oddsapi_props.main()` on any
# cadence. Measured 2026-08-17: `MAIN_ENTRY` 0 hits over 8h on BOTH workers, and
# `GAME_CARDS_CENSUS` 0 over ~2 days with the emitter confirmed present in both
# deployed SHAs. The GHA cron cannot cover it either -- it reads
# `RUN_FULL_PIPELINE` from `github.event.inputs`, which is empty on the
# `schedule` trigger, so full regeneration is manual-dispatch only.
#
# `phase="pregame"` IS LOAD-BEARING, NOT COPIED FROM SOCCER. This worker is 2GB
# and already carries WNBA SmartSim + live-lens load; `render.yaml` records sim
# workers cut to 1 and the WNBA sim count cut 500 -> 250 -> 100 fighting for that
# memory, against a WNBA refresh leg measured at ~1.3-1.5GB RSS. Pregame covers
# schedule/odds/props/picks and EXCLUDES the sim leg. A full-phase autorun here
# would OOM the service.
def _wnba_pregame_refresh_enabled() -> bool:
    # DEFAULT OFF. New periodic worker work is never free (`#241` caused a
    # production restart loop), and enabling it is a `render.yaml` change, which
    # is a deploy and therefore coordinator-owned.
    raw_value = str(os.environ.get("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _wnba_pregame_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("SYNDICATE_WNBA_PREGAME_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 14400)  # 4h, matching soccer's cadence for the same work.
    except ValueError:
        value = 14400
    return max(1, value)


def _wnba_pregame_autorun_status_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "wnba_pregame_autorun_status.json"


def _wnba_active_for_date(date_str: str) -> bool:
    active = {item.strip().lower() for item in _active_sports_for_date(date_str).split(",") if item.strip()}
    return "wnba" in active


def _report_previous_wnba_pregame_run(last_status: dict) -> None:
    """Print the PREVIOUS run's outcome to THIS worker's stdout.

    Same reason as `_report_previous_soccer_pregame_run` (`#433`): soccer odds
    stopped for FOUR DAYS with no visible error because `launch_refresh_run`
    spawns the child detached with stdout/stderr to DEVNULL, so the launch is
    otherwise the last thing anyone hears about the run. A silent WNBA autorun
    would reproduce exactly the invisibility this whole lane exists to fix.
    """
    if not last_status:
        return
    err = last_status.get("error")
    if err:
        print(f"[live_odds_worker] WNBA_PREGAME_AUTORUN_PREV date={last_status.get('date')} FAILED {err}", flush=True)
        return
    print(
        f"[live_odds_worker] WNBA_PREGAME_AUTORUN_PREV date={last_status.get('date')} "
        f"launched=ok runStamp={last_status.get('runStamp')} artifactsDir={last_status.get('artifactsDir')}",
        flush=True,
    )


def _launch_autorun_wnba_pregame_refresh() -> None:
    if not _wnba_pregame_refresh_enabled():
        return
    selected_date = central_today_iso()
    if not _wnba_active_for_date(selected_date):
        return
    status_path = _wnba_pregame_autorun_status_path()
    last_status = read_json_file(status_path) or {}
    # BEFORE the cadence gate, for the same reason soccer does it: the gate
    # returns on most ticks, so reporting after it would surface the previous
    # run's outcome up to 4 hours late -- most of the way back to silence.
    _report_previous_wnba_pregame_run(last_status)
    if last_status and not last_status.get("reported"):
        try:
            write_json_file(status_path, {**last_status, "reported": True})
        except Exception:  # noqa: BLE001
            pass
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_wnba_pregame_refresh_interval_seconds()):
        return
    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="wnba",
            phase="pregame",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode=str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "full"),
            launch_mode="web_process",
        )
    except Exception as exc:
        if _is_refresh_run_contention_error(exc):
            # Same fix as soccer's identical except-block, #472: preserve the
            # ORIGINAL epoch on contention instead of stamping a new one, so
            # one lost mutex race doesn't cost a full cadence window.
            write_json_file(status_path, {**last_status, "sports": "wnba", "date": selected_date, "error": f"{type(exc).__name__}: {exc}", "reported": False})
        else:
            write_json_file(status_path, {"epoch": time.time(), "sports": "wnba", "date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
        print(f"[live_odds_worker] WNBA_PREGAME_AUTORUN_FAILED {type(exc).__name__}: {exc}", flush=True)
        return
    write_json_file(
        status_path,
        {
            "epoch": time.time(),
            "sports": "wnba",
            "date": selected_date,
            "artifactsDir": (result or {}).get("artifactsDir"),
            "runStamp": (result or {}).get("runStamp"),
            "reported": False,
        },
    )
    print(f"[live_odds_worker] WNBA_PREGAME_AUTORUN_LAUNCHED date={selected_date} phase=pregame", flush=True)


# `wnba-live-odds-capture-gap`, 2026-08-20. The pregame autorun above keeps
# WNBA's odds fresh before tip-off; nothing kept them fresh AFTER it, and that
# gap is what this fixes.
#
# ROOT CAUSE, confirmed live, not inferred. The general combined `phase=live`
# sweep (`live_refresh_loop.py`) launches `sports=mlb,wnba,soccer` together,
# once per tick (`SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS`, default 60s).
# That combined run genuinely takes several minutes end to end (soccer alone
# runs `build_soccer_artifacts.py` sims), so almost every subsequent tick's
# `launch_refresh_run` collides with its OWN still-running prior launch and
# raises `ValueError: A refresh run is already active` -- confirmed directly
# in production logs, repeating every ~65-70s for 16+ minutes straight against
# a single service's own lane (`live-odds-worker`, pid 100 then pid 833).
# `_assert_no_active_refresh_run` is doing exactly its job; the tick cadence
# is just far shorter than the combined run's real duration, so the run that
# eventually DOES land almost never includes a completed WNBA leg -- WNBA's
# own fetch, when isolated (no mlb/soccer sharing the run), completes in
# under 400s every time it was tested.
#
# THE FIX IS ISOLATION, NOT A FASTER COMBINED RUN. An independent WNBA-only
# live trigger, same shape as the soccer/WNBA pregame autorons above:
#   - Its OWN cadence, long enough that a single WNBA-only run reliably
#     finishes before the next tick (measured mode=full WNBA-only duration:
#     ~368s; this uses a distinct, explicit refresh LANE so it can never
#     collide with the general combined sweep's lane even if both fire in
#     the same window -- `SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES` is on in
#     production, so an explicit `lane=` string is honored directly).
#   - `mode="fast"`, not `"full"`. `refresh_wnba_oddsapi_props.py` runs its
#     OddsAPI snapshot fetch (the thing that actually writes book_quotes)
#     UNCONDITIONALLY; `mode="full"` additionally runs the SmartSim
#     prediction/edges/export pipeline (`if refresh_mode == "full": ...`),
#     which is real weight this needs to pay for repeatedly and does not.
#     `test_wnba_pregame_autorun.py`'s own warning -- "a full-phase autorun
#     here would OOM the service", against a refresh leg measured at
#     ~1.3-1.5GB RSS -- is exactly the risk `mode="fast"` avoids by never
#     entering that branch, which matters more here than for the pregame
#     autorun because this one is meant to repeat every few minutes for as
#     long as a game is live, not once per ~4h.
#   - Gated on `_wnba_has_live_game`, not merely "WNBA active today" (the
#     pregame gate's own check) -- there is nothing to refresh live-side
#     when nothing is live, and firing anyway would be pure waste.
def _wnba_live_refresh_enabled() -> bool:
    # DEFAULT OFF, same convention as every other autorun in this file --
    # new periodic worker work is never free (`#241`).
    raw_value = str(os.environ.get("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _wnba_live_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("SYNDICATE_WNBA_LIVE_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        # 240s: comfortable margin over the measured mode=full standalone
        # duration (~368s is the UPPER bound this was measured against;
        # mode=fast skips the heaviest stage, so this is conservative, not
        # tight). Tunable without a code change once more data exists.
        value = int(raw_value or 240)
    except ValueError:
        value = 240
    return max(1, value)


def _wnba_live_refresh_lane() -> str:
    # Explicit and distinct from anything else, deliberately: this is what
    # keeps this launch from ever contending with the general combined
    # `phase=live` sweep's own (already self-colliding) lane. Overridable for
    # tests / multi-instance setups; the default is namespaced with the
    # service name it always runs on so a future reader does not need this
    # comment to know it is not shared.
    raw_value = str(os.environ.get("SYNDICATE_WNBA_LIVE_REFRESH_LANE") or "").strip()
    return raw_value or "live-odds-worker-wnba-live"


def _wnba_live_autorun_status_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "wnba_live_autorun_status.json"


def _report_previous_wnba_live_run(last_status: dict) -> None:
    """Same reason as `_report_previous_wnba_pregame_run` (`#433`): a launch
    that is fire-and-forget by design must still be OBSERVABLE, or a real
    failure here reproduces the exact silence this whole lane exists to fix.
    """
    if not last_status:
        return
    err = last_status.get("error")
    if err:
        print(f"[live_odds_worker] WNBA_LIVE_AUTORUN_PREV date={last_status.get('date')} FAILED {err}", flush=True)
        return
    print(
        f"[live_odds_worker] WNBA_LIVE_AUTORUN_PREV date={last_status.get('date')} "
        f"launched=ok runStamp={last_status.get('runStamp')} artifactsDir={last_status.get('artifactsDir')}",
        flush=True,
    )


def _launch_autorun_wnba_live_refresh() -> None:
    if not _wnba_live_refresh_enabled():
        return
    selected_date = central_today_iso()
    if not _wnba_has_live_game(selected_date):
        return
    status_path = _wnba_live_autorun_status_path()
    last_status = read_json_file(status_path) or {}
    # BEFORE the cadence gate, same reason as every other autorun here:
    # reporting after it would surface the previous run's outcome up to a
    # full interval late.
    _report_previous_wnba_live_run(last_status)
    if last_status and not last_status.get("reported"):
        try:
            write_json_file(status_path, {**last_status, "reported": True})
        except Exception:  # noqa: BLE001
            pass
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_wnba_live_refresh_interval_seconds()):
        return
    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="wnba",
            phase="live",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode="fast",
            launch_mode="web_process",
            lane=_wnba_live_refresh_lane(),
        )
    except Exception as exc:
        if _is_refresh_run_contention_error(exc):
            # `#472`'s fix, same shape: preserve the ORIGINAL epoch on
            # contention so one lost mutex race costs a short retry, not a
            # full interval.
            write_json_file(status_path, {**last_status, "sports": "wnba", "date": selected_date, "error": f"{type(exc).__name__}: {exc}", "reported": False})
        else:
            write_json_file(status_path, {"epoch": time.time(), "sports": "wnba", "date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
        print(f"[live_odds_worker] WNBA_LIVE_AUTORUN_FAILED {type(exc).__name__}: {exc}", flush=True)
        return
    write_json_file(
        status_path,
        {
            "epoch": time.time(),
            "sports": "wnba",
            "date": selected_date,
            "artifactsDir": (result or {}).get("artifactsDir"),
            "runStamp": (result or {}).get("runStamp"),
            "reported": False,
        },
    )
    print(f"[live_odds_worker] WNBA_LIVE_AUTORUN_LAUNCHED date={selected_date} phase=live mode=fast", flush=True)


def _launch_autorun_soccer_pregame_refresh() -> None:
    if not _soccer_pregame_refresh_enabled():
        return
    selected_date = central_today_iso()
    if not _soccer_active_for_date(selected_date):
        return
    status_path = _soccer_pregame_autorun_status_path()
    last_status = read_json_file(status_path) or {}
    # BEFORE the cadence gate, deliberately. The gate returns on most ticks, so
    # reporting after it would emit the previous run's outcome only on the tick
    # that launches the NEXT one -- i.e. up to 4 hours late, which is most of
    # the way back to the silence this is fixing.
    _report_previous_soccer_pregame_run(last_status)
    if last_status and not last_status.get("reported"):
        # Mark reported so the summary is emitted once, not on every tick for
        # four hours. Written back with the rest of the record intact.
        try:
            write_json_file(status_path, {**last_status, "reported": True})
        except Exception:  # noqa: BLE001
            pass
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_soccer_pregame_refresh_interval_seconds()):
        return
    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="soccer",
            phase="pregame",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode=str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "full"),
            launch_mode="web_process",
        )
    except Exception as exc:
        if _is_refresh_run_contention_error(exc):
            # Preserve the ORIGINAL epoch (from the last real success) rather
            # than stamping a new one -- see _is_refresh_run_contention_error.
            # Once that original interval elapses, every subsequent tick
            # retries again immediately instead of waiting out a second full
            # window earned by pure bad luck.
            write_json_file(status_path, {**last_status, "sports": "soccer", "date": selected_date, "error": f"{type(exc).__name__}: {exc}", "reported": False})
        else:
            write_json_file(status_path, {"epoch": time.time(), "sports": "soccer", "date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
        print(f"[live_odds_worker] SOCCER_PREGAME_AUTORUN_FAILED {type(exc).__name__}: {exc}", flush=True)
        return
    # `artifactsDir` and `runStamp` are what make the NEXT tick able to report
    # this run's outcome. Without them the summary has no artifact to read and
    # the launch is once again the last thing anyone hears about the run.
    write_json_file(
        status_path,
        {
            "epoch": time.time(),
            "sports": "soccer",
            "date": selected_date,
            "runStamp": result.get("run_stamp"),
            "artifactsDir": result.get("artifacts_dir"),
            "pid": result.get("pid"),
            "reported": False,
        },
    )
    print(
        f"[live_odds_worker] SOCCER_PREGAME_AUTORUN_LAUNCHED date={selected_date} "
        f"pid={result.get('pid')} stamp={result.get('run_stamp')}",
        flush=True,
    )


def _memory_trace_enabled() -> bool:
    return str(__import__("os").environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE") or "").strip().lower() in {"1", "true", "yes", "on"}


def _rss_bytes() -> int | None:
    if psutil is None:
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            process = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, os.getpid())
            if not process:
                return None
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                return int(counters.WorkingSetSize)
        except Exception:
            try:
                with open("/proc/self/status", encoding="utf-8", errors="ignore") as handle:
                    for line in handle:
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return int(parts[1]) * 1024
            except Exception:
                pass
            return None
        return None
    try:
        return int(psutil.Process().memory_info().rss)
    except Exception:
        try:
            with open("/proc/self/status", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
        except Exception:
            pass
        return None


def _largest_gc_object_summary() -> dict[str, object] | None:
    largest_size = -1
    largest_obj: object = None
    try:
        for obj in gc.get_objects():
            try:
                size = sys.getsizeof(obj)
            except Exception:
                continue
            if size <= largest_size:
                continue
            largest_size = size
            largest_obj = obj
    except Exception:
        return None
    if largest_size < 0:
        return None
    largest_type = type(largest_obj).__name__
    try:
        largest_len = len(largest_obj) if hasattr(largest_obj, "__len__") else None
    except Exception:
        largest_len = None
    payload: dict[str, object] = {"type": largest_type, "size_bytes": largest_size}
    if largest_len is not None:
        payload["len"] = largest_len
    # A container this big is a memory-spike smoking gun on its own, but "type
    # + len" alone isn't enough to trace it back to a call site. Sample its
    # shape so a future spike is identifiable straight from the log line
    # instead of needing another guess-and-deploy round to add this after
    # the fact.
    if largest_len and largest_len > 1000:
        try:
            if isinstance(largest_obj, (list, tuple)):
                sample = largest_obj[0]
                if isinstance(sample, dict):
                    payload["sample_keys"] = sorted(str(key) for key in sample.keys())[:20]
                else:
                    payload["sample_repr"] = repr(sample)[:200]
            elif isinstance(largest_obj, dict):
                keys = list(largest_obj.keys())
                payload["sample_keys"] = [str(key) for key in keys[:20]]
        except Exception:
            pass
    return payload


def _phase_memory_snapshot() -> dict[str, object]:
    return {
        "rss_bytes": _rss_bytes(),
        "largest_gc_object": _largest_gc_object_summary(),
    }


def _log_worker_memory(stage: str, **extra: object) -> None:
    if not _memory_trace_enabled():
        return
    payload: dict[str, object] = {
        "stage": stage,
        **extra,
    }
    payload.update(_phase_memory_snapshot())
    print(f"LIVE_ODDS_WORKER_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", flush=True)


def _handle_stop(_signum: int, _frame: object) -> None:
    _LIVE_REFRESH_LOOP_STOP.set()


def _max_uptime_seconds() -> float | None:
    # Long-lived worker processes doing routine multi-sport file I/O every
    # tick accumulate page cache over hours of uptime that never gets
    # credited back (observed climbing from ~416MB to ~989MB container
    # memory in production with no single repeated expensive call to blame --
    # see docs/fix_notes_log.md). Render restarts the process on exit
    # regardless of exit code, so a periodic clean self-exit resets the
    # container's page cache to baseline instead of letting it climb
    # indefinitely toward another OOM kill. 0 or unset disables the restart.
    raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_WORKER_MAX_UPTIME_SECONDS") or "21600").strip()
    try:
        value = float(raw)
    except Exception:
        value = 21600.0
    if value <= 0:
        return None
    # +/-10% jitter so the restart doesn't land at the same wall-clock offset
    # every single day (which could otherwise coincide with a live game).
    jitter = value * random.uniform(-0.1, 0.1)
    return max(300.0, value + jitter)


def _run_tick() -> dict[str, object] | None:
    # #148: independent of the shared adaptive tick below (same relationship
    # as run_refresh_worker.py's own MLB sim tick, called every cycle
    # regardless of the queued-contract handling) -- its own interval gate
    # makes this a no-op on every call except when soccer's pregame refresh
    # is actually due, so calling it unconditionally here is cheap.
    try:
        _launch_autorun_soccer_pregame_refresh()
    except Exception as exc:
        print(f"[live_odds_worker] SOCCER_PREGAME_AUTORUN_ERROR {type(exc).__name__}: {exc}", flush=True)
    # Phase 2 (WNBA). Same shape and the same independence as soccer above: its
    # own interval gate makes this a no-op on every call except when due, and its
    # own try/except means a WNBA failure can never take down the soccer autorun
    # or the tick that follows.
    try:
        _launch_autorun_wnba_pregame_refresh()
    except Exception as exc:
        print(f"[live_odds_worker] WNBA_PREGAME_AUTORUN_ERROR {type(exc).__name__}: {exc}", flush=True)
    # `wnba-live-odds-capture-gap`. Same independence as the two autoruns
    # above: its own interval AND liveness gate make this a no-op except
    # when a WNBA game is actually live and due, and its own try/except
    # means a WNBA failure here can never take down the general tick.
    try:
        _launch_autorun_wnba_live_refresh()
    except Exception as exc:
        print(f"[live_odds_worker] WNBA_LIVE_AUTORUN_ERROR {type(exc).__name__}: {exc}", flush=True)
    try:
        _log_worker_memory("tick_start")
        meta = _run_live_refresh_tick()
        _log_worker_memory("tick_end", ok=bool(meta.get("ok", False)), skipped=bool(meta.get("skipped")), error=meta.get("error"))
        print(f"LIVE ODDS REFRESH TICK: {meta.get('ok', False)}")
        if meta.get("skipped") or meta.get("error"):
            print(f"LIVE ODDS REFRESH SKIP/ERROR DETAIL: {meta.get('error')}", flush=True)
        return meta
    except Exception as exc:
        _log_worker_memory("tick_error", error=f"{type(exc).__name__}: {exc}")
        print(f"LIVE ODDS REFRESH ERROR: {exc}")
        return None


def _ncaaf_oddsapi_report_at_boot() -> None:
    """One-shot, OPT-IN: does the NCAAF team resolver survive contact with the
    REAL OddsAPI event list?

    `todo.md` `#558`. `scripts/fetch_ncaaf_oddsapi_game_lines.py` was built and
    proven entirely against a captured fixture -- the sandbox it was written in
    answers 403 to CONNECT for `api.the-odds-api.com`, so not one live call had
    ever been made. This service does reach OddsAPI (it fetches MLB and soccer
    lines every tick), which is why the check belongs here rather than in a
    checkout, and it is the same role `probe_exchange_markets.py` plays for the
    exchange clients.

    `--report` FETCHES BUT DOES NOT WRITE. One credit, no quote rows, so this
    can run before `SYNDICATE_ACTIVE_SPORTS` carries `ncaaf` and cannot leave a
    half-populated quote log behind if the resolver is wrong.

    THE READING IS `UNRESOLVED_TEAMS`, not the exit code. A school the resolver
    cannot place is a game whose card shows an empty market block -- which is
    indistinguishable on the board from "no book quoted it". This log line is
    the only place that difference is visible, which is the entire reason to
    spend a boot on it.

    **OFF BY DEFAULT, and meant to be turned off again.** Set
    `SYNDICATE_NCAAF_ODDSAPI_REPORT_ON_BOOT=1`, deploy, read the
    `[ncaaf_odds]` lines, then clear the flag. Nothing here raises past its own
    try/except: a diagnostic must never be able to stop this worker booting.
    """
    raw = str(os.environ.get("SYNDICATE_NCAAF_ODDSAPI_REPORT_ON_BOOT") or "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        # Says so out loud rather than returning in silence: when this runs the
        # question being asked is "did the flag reach this service", and a
        # silent no-op answers it identically to a probe that crashed.
        print("[live_odds_worker] NCAAF_ODDSAPI_REPORT_SKIPPED flag=off", flush=True)
        return
    try:
        from scripts.fetch_ncaaf_oddsapi_game_lines import main as _ncaaf_report_main

        code = _ncaaf_report_main(["--report"])
        print(f"[live_odds_worker] NCAAF_ODDSAPI_REPORT_DONE exit={code}", flush=True)
    except Exception as exc:
        print(
            f"[live_odds_worker] NCAAF_ODDSAPI_REPORT_ERROR {type(exc).__name__}: {exc}",
            flush=True,
        )


def _kalshi_auth_probe_at_boot() -> None:
    """Can THIS service sign? Asked here because the answer is per-service.

    `refresh-worker` proving its credentials work says nothing about this
    worker: different service, different env block. And this is the one that
    places orders, so "can it sign" has to be answered before it is armed
    rather than discovered on the first submit -- where a 401 does not tell you
    whether the ORDER or the AUTH was rejected.

    Read-only: `probe_auth` asks for the balance. Nothing here can trade.
    """
    try:
        from syndicate.features.shared.kalshi_auth import probe_auth

        result = probe_auth()
        print(
            "[live_odds_worker] KALSHI_AUTH_PROBE"
            f" status={result.get('status')}"
            f" reason={result.get('reason')}"
            f" detail={result.get('detail')}"
            f" key_shape={result.get('key_shape')}"
            # Keys, never values.
            f" keys={result.get('keys')}"
            f" balance_present={result.get('balance_present')}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[live_odds_worker] KALSHI_AUTH_PROBE_ERROR {type(exc).__name__}: {exc}",
            flush=True,
        )


def _polymarket_us_auth_probe_at_boot() -> None:
    """Does the Polymarket US credential work, and what shape does a read take?

    A DIFFERENT EXCHANGE from `_polymarket_catalogue_at_boot` below, which pulls
    the global on-chain venue's public catalogue. This one is `api.polymarket.us`
    -- different host, different auth, and different MONEY. They are separate
    functions for that reason.

    Read-only: it asks for one market. Nothing here can place an order, and the
    probe reports the SHAPE that came back rather than parsing it -- the choice
    that caught Kalshi's ten wrong field names and its 100x price error before
    either reached an order.
    """
    try:
        from syndicate.features.shared.polymarket_us_auth import credentials_present, probe_auth

        if not credentials_present():
            # ABSENCE, NAMED. Distinct from a credential that exists and fails;
            # they need completely different responses and must never share a
            # line. Not an error -- the venue is simply not configured here.
            print(
                "[live_odds_worker] POLYMARKET_US_AUTH status=credentials_absent",
                flush=True,
            )
            return
        report = probe_auth()
        print(
            f"[live_odds_worker] POLYMARKET_US_AUTH ok={report.get('ok')}"
            f" base={report.get('base_url')}"
            f" payload_keys={report.get('payload_keys')}"
            f" row_keys={report.get('row_keys')}"
            f" count={report.get('count')}"
            f" reason={report.get('reason')}",
            flush=True,
        )
    except Exception as exc:
        # Type only, never the exception's full text -- a credential failure is
        # the one place a stack string can carry key material.
        print(
            f"[live_odds_worker] POLYMARKET_US_AUTH_FAILED {type(exc).__name__}",
            flush=True,
        )


def _print_param_probe(pm) -> None:
    """Which `/v1/markets` query params the venue honours. DIAGNOSTIC.

    Behind `SYNDICATE_POLYMARKET_US_PARAM_PROBE=1` because it costs ~25 signed
    calls and it has already answered its question: `closed=false` is the
    filter that reaches the current slate. Kept because the same technique
    settles the next unknown parameter cheaply.

    Read `control=` FIRST. Measured 2026-08-24T20:56:41Z it came back
    `ignored`, meaning this API silently discards unknown query params -- so
    every `ignored` verdict is uninformative and only `honoured` rows carry
    information. That is why the control exists.
    """
    params = pm.probe_market_query_params()
    print(
        f"[live_odds_worker] POLYMARKET_US_PARAMS status={params.get('status')}"
        f" control={params.get('control_outcome')}"
        f" ignored_is_meaningful={params.get('ignored_is_meaningful')}"
        f" honoured={params.get('honoured')}"
        f" rejected={params.get('rejected')}"
        f" baseline={params.get('baseline')}"
        f" reason={params.get('reason')}",
        flush=True,
    )
    for label, row in (params.get("results") or {}).items():
        if row.get("outcome") == "honoured":
            print(
                f"[live_odds_worker] POLYMARKET_US_PARAM_HIT {label}"
                f" query={row.get('query')!r} signature={row.get('signature')}",
                flush=True,
            )


def _polymarket_daily_book() -> None:
    """Write Polymarket's venue-native daily odds files. Never fatal.

    Reads the slate artifact that `persist_game_slate` just wrote, so this adds
    no venue traffic at all -- it is a second CONSUMER of one fetch, never a
    second caller.
    """
    try:
        from syndicate.features.shared.polymarket_us_markets import GAME_SLATE_ARTIFACT
        from syndicate.features.shared.refresh_state_store import read_json_file, reports_root
        from syndicate.features.shared.venue_daily_odds import (
            polymarket_daily_rows,
            record_venue_book,
        )

        payload = read_json_file(reports_root().joinpath(*GAME_SLATE_ARTIFACT)) or {}
        markets = payload.get("markets")
        if not isinstance(markets, list) or not markets:
            print("[live_odds_worker] POLYMARKET_DAILY_BOOK status=no_slate", flush=True)
            return
        report = record_venue_book("polymarket", polymarket_daily_rows(markets))
    except Exception as exc:  # noqa: BLE001
        print(
            f"[live_odds_worker] POLYMARKET_DAILY_BOOK_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )
        return
    print(
        "[live_odds_worker] POLYMARKET_DAILY_BOOK"
        f" status={report.get('status')}"
        f" files={report.get('files')}"
        f" errors={report.get('file_errors')}"
        f" listed={report.get('listed')}"
        f" parsed={report.get('parsed')}"
        f" opened={report.get('opened')}"
        f" appended={report.get('appended')}"
        f" undated={report.get('undated')}"
        # Sports we do not model, counted by name. Polymarket's soccer league
        # codes surface here -- real markets in a sport we DO model, under
        # names we have not yet read.
        f" skipped={report.get('skipped_total')}"
        f" skipped_by_sport={report.get('skipped_by_sport')}"
        # BY FAMILY -- this is the number that says what a parser is still
        # owed, and `SPORTS_MARKET_TYPE_PROP` is a mixed bucket, so the family
        # is the venue's own type rather than anything inferred from it.
        f" unparsed={report.get('unparsed_by_family')}"
        f" detail={report.get('detail')}",
        flush=True,
    )


def _polymarket_us_slate_refresh_tick() -> None:
    """Persist the Polymarket US game slate on a cadence, like Kalshi's.

    WHY A WRITER AT ALL. `venue_quote_adapters` reads ARTIFACTS, never venue
    APIs -- a second independent caller for one venue is a documented incident
    class here (`#139/#144` MLB, `#148` soccer). Kalshi already writes
    `intelligence/kalshi_markets.json` with its own `fetched_at`; OddsAPI
    writes `odds_history` shards. Polymarket had no equivalent, so its adapter
    refused by name on every cycle. This is that missing writer.

    Cadence is deliberate, not free: the slate costs ~33 signed calls (a
    binary-searched boundary plus ~18 pages). At the default 900s that is ~130
    calls an hour, against a venue whose rate limits nobody here has measured.

    THE ARTIFACT GOES OVER THE SHARED KEYVALUE BACKEND, not the HTTP
    allowlist. `write_json_file` under `reports/` is how `kalshi_markets.json`
    already crosses services (`artifact_publisher.py:35`'s own comment says so
    for `intelligence_state.json`), which is why this needs no
    HOT_ARTIFACT_PATTERNS entry -- and why the ~8MB ceiling applies instead.
    """
    import os

    if (os.environ.get("SYNDICATE_POLYMARKET_US_SLATE_REFRESH_ENABLED") or "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    # LOWERED FROM 900s. THESE CALLS ARE FREE.
    #
    # Polymarket US is a direct API; unlike OddsAPI there is no per-call cost
    # to ration, so a 15-minute cadence was rationing a resource that is not
    # scarce. Exchange prices are also the freshest thing on the board -- they
    # move in-game, which is exactly when a 15-minute-old quote is worth least
    # and most likely to size a bet against a price nobody is showing.
    #
    # One cycle is ~37 requests (6-7 offset probes plus up to 30 pages), so
    # 180s is ~12 requests/minute sustained. That is comfortably inside what
    # this venue has tolerated and an order of magnitude below the burst that
    # drew Kalshi's http_429s.
    #
    # The floor drops to 60s so the override can go further when a slate is
    # worth watching closely; it stays a floor because the write is ~2.1MB and
    # an unbounded value here would put that on the keyvalue store in a loop.
    from syndicate.features.shared.polymarket_us_markets import SLATE_INTERVAL_SECONDS

    interval = SLATE_INTERVAL_SECONDS
    raw = str(os.environ.get("SYNDICATE_POLYMARKET_US_SLATE_INTERVAL_SECONDS") or "").strip()
    if raw:
        try:
            interval = max(60, int(raw))
        except ValueError:
            pass

    global _POLYMARKET_SLATE_LAST_RUN
    now = time.time()
    if _POLYMARKET_SLATE_LAST_RUN and (now - _POLYMARKET_SLATE_LAST_RUN) < interval:
        return
    _POLYMARKET_SLATE_LAST_RUN = now

    try:
        from syndicate.features.shared import polymarket_us_markets as pm
        from syndicate.features.shared.polymarket_us_auth import credentials_present

        if not credentials_present():
            print("[live_odds_worker] POLYMARKET_US_SLATE_WRITE status=credentials_absent", flush=True)
            return
        result = pm.persist_game_slate()
        print(
            f"[live_odds_worker] POLYMARKET_US_SLATE_WRITE status={result.get('status')}"
            f" written={result.get('written')} count={result.get('count')}"
            f" bytes={result.get('bytes')} headroom={result.get('headroom_bytes')}"
            f" truncated={result.get('truncated')}"
            # WHAT WE CHOSE NOT TO STORE, by date. Distinct from `truncated`,
            # which is what the VENUE had beyond our page budget. A slate that
            # dropped its far end silently makes the next
            # `market_unresolved_for_position` indistinguishable from the venue
            # not listing the market -- which is what happened on
            # `tsc-mlb-cin-sf-2026-08-25-7pt5` at 3:55 PM Central.
            f" fetched={result.get('fetched_count')}"
            f" dropped_for_size={result.get('dropped_for_size')}"
            f" dropped_by_date={result.get('dropped_by_date')}"
            f" kept_through={result.get('kept_through')}"
            f" game_types={result.get('game_types')}"
            f" reason={result.get('reason')}",
            flush=True,
        )
        # THE DAILY BOOK, from the SAME fetch. Capture-first: this records
        # every market the venue listed, including the 6,838
        # `market_type_not_a_game_line` and 1,064 segment rows the board join
        # refuses. They are already fetched and paid for; today they are
        # discarded without record, so an unparsed family is invisible rather
        # than counted.
        #
        # Reads the persisted slate rather than re-fetching -- becoming a
        # second independent caller of this venue is a documented incident
        # class in `venue_quote_adapters.py`.
        _polymarket_daily_book()
    except Exception as exc:  # noqa: BLE001 -- never fatal to the loop
        print(
            f"[live_odds_worker] POLYMARKET_US_SLATE_WRITE_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )


_POLYMARKET_SLATE_LAST_RUN: float = 0.0


def _polymarket_us_slate_probe_at_boot() -> None:
    """What the US venue actually lists for sport, by SHAPE.

    WHY THIS IS NOT `_polymarket_catalogue_at_boot`. That one pulls
    `gamma-api.polymarket.com` -- the GLOBAL, on-chain exchange. The funded
    account and the working credential are on `api.polymarket.us`. Pricing an
    edge on one book and filling it on the other is the "different money" error
    the auth modules were split in two to prevent, and at the odds layer it does
    not fail loudly: it produces plausible edges against prices that do not
    exist where the order lands.

    It stayed invisible because the global pull returned `count=100 sporting=0`
    on every cycle -- so no join was ever attempted, so nobody discovered the
    prices were from the wrong exchange.

    --------------------------------------------------------------------------
    THE SPORTS API ROUTES 404 ON THIS HOST. MEASURED, NOT ASSUMED.
    --------------------------------------------------------------------------

    2026-08-24T20:18:37Z, live-odds-worker `hvpj6`, ONE BOOT, ONE CREDENTIAL,
    0.6 seconds end to end:

        .602  GET /v1/markets                      ok=True, 29 row keys
        .752  GET /v2/leagues/mlb/events           http_404  code 5 NOT_FOUND
        .901  GET /v2/leagues/wnba/events          http_404
       38.100 GET /v2/leagues/nfl/events           http_404
       38.240 GET /v1/sports/teams/provider        http_404

    The three DOCUMENTED league slugs (`nfl`/`nba`/`mlb`) 404 identically to
    the four guessed ones, which rules out a bad slug: the ROUTE is absent. And
    a signed read of `/v1/markets` succeeding in the same second rules out the
    credential, the clock and the signature. The user-supplied Sports API docs
    describe a different host from the trading API.

    So this probe asks the route that EXISTS. `/v1/markets` carries
    `sportsMarketTypeV2`, `gameStartTime`, `orderPriceMinTickSize` and
    `minimumTradeQty` -- every field the join and the order need -- so the
    sporting slate is reachable by filtering it structurally, which is what
    `fetch_markets` does.

    The 404'd routes stay behind `SYNDICATE_POLYMARKET_US_SPORTS_PROBE=1`:
    diagnostic, not a standing feature. Re-probing a confirmed 404 on every
    boot is noise that would bury the line that matters, but deleting the call
    would lose the ability to re-check cheaply if the host is found.

    READ-ONLY, and it reports shapes rather than parsing them: the value
    vocabulary of `sportsMarketTypeV2` has still never been observed, and a
    guessed constant would return zero rows indistinguishably from a venue that
    lists no sport.
    """
    import os

    try:
        from syndicate.features.shared import polymarket_us_markets as pm
        from syndicate.features.shared.polymarket_us_auth import credentials_present

        if not credentials_present():
            print("[live_odds_worker] POLYMARKET_US_SLATE status=credentials_absent", flush=True)
            return

        # THE ROUTE THAT WORKS -- paged, and reporting SETTLED separately.
        #
        # The first run of this printed `sporting=500 of=500 orderable=500`,
        # which reads as a full healthy slate and was 500 NFL games that
        # finished nine months earlier, priced at certainty under
        # `active=true`. `live` is the only usable count; `duplicate_ids`
        # catches a venue that ignores `offset`, which is otherwise invisible
        # because every page simply looks full.
        catalogue = pm.fetch_markets(limit=500, max_pages=4)
        print(
            f"[live_odds_worker] POLYMARKET_US_CATALOGUE status={catalogue.get('status')}"
            f" sporting={catalogue.get('sporting')}"
            f" games={catalogue.get('games')} futures={catalogue.get('futures')}"
            f" game_types={catalogue.get('game_types')}"
            f" settled={catalogue.get('settled')} live={catalogue.get('live')}"
            f" rows={catalogue.get('total_rows')} pages={catalogue.get('pages')}"
            f" duplicate_ids={catalogue.get('duplicate_ids')}"
            f" orderable={catalogue.get('orderable')}"
            f" truncated={catalogue.get('truncated')}"
            f" window={catalogue.get('game_start_min')}..{catalogue.get('game_start_max')}"
            f" live_window={catalogue.get('live_start_min')}..{catalogue.get('live_start_max')}"
            f" types={catalogue.get('sports_market_types')}"
            f" market_types={catalogue.get('market_types')}"
            f" categories={catalogue.get('categories')}"
            f" statuses={catalogue.get('statuses')}"
            f" reason={catalogue.get('reason')}",
            flush=True,
        )
        # A SAMPLE OF THE LIVE ROWS, not the first rows -- the first rows are
        # exactly the settled ones that made the last run look healthy.
        live_sample = pm.fetch_markets(limit=500, max_pages=4, drop_settled=True)
        for row in (live_sample.get("markets") or [])[:5]:
            print(
                f"[live_odds_worker] POLYMARKET_US_MARKET"
                f" slug={row.get('slug')!r} type={row.get('sportsMarketTypeV2')!r}"
                f" start={row.get('gameStartTime')!r} outcomes={row.get('outcomes')!r}"
                f" prices={row.get('outcomePrices')!r}"
                f" tick={row.get('orderPriceMinTickSize')!r}"
                f" min_qty={row.get('minimumTradeQty')!r}"
                f" orderable={row.get('orderable')}"
                f" question={str(row.get('question'))[:90]!r}",
                flush=True,
            )

        # THE JOINABLE SLATE. Boundary located rather than hardcoded: ids grow
        # as the venue lists markets, so it moves daily.
        slate = pm.fetch_game_markets(limit=500, max_pages=30)
        print(
            f"[live_odds_worker] POLYMARKET_US_GAMES status={slate.get('status')}"
            f" start_offset={slate.get('start_offset')}"
            f" boundary_probes={slate.get('boundary_probes')}"
            f" monotonic={slate.get('boundary_monotonic')}"
            f" games={slate.get('games')} futures={slate.get('futures')}"
            f" rows={slate.get('total_rows')} pages={slate.get('pages')}"
            f" duplicate_ids={slate.get('duplicate_ids')}"
            f" truncated={slate.get('truncated')}"
            f" orderable={slate.get('orderable')}"
            f" game_types={slate.get('game_types')}"
            f" window={slate.get('game_start_min')}..{slate.get('game_start_max')}"
            f" reason={slate.get('reason')}",
            flush=True,
        )
        for row in (slate.get("markets") or [])[:6]:
            print(
                f"[live_odds_worker] POLYMARKET_US_GAME slug={row.get('slug')!r}"
                f" type={row.get('sportsMarketTypeV2')!r}"
                f" start={row.get('gameStartTime')!r}"
                f" outcomes={row.get('outcomes')!r} prices={row.get('outcomePrices')!r}"
                f" tick={row.get('orderPriceMinTickSize')!r}"
                f" question={str(row.get('question'))[:70]!r}",
                flush=True,
            )

        # WHERE do game markets live in the `closed=false` ordering?
        # games=0 across the first 2,000 rows, and moneylines are known to
        # exist here (the unfiltered query returns them). Deeper, or absent?
        # Samples ~8 offsets at 5 rows each rather than sweeping linearly.
        landscape = pm.probe_offset_landscape(
            # MEASURED 2026-08-24T21:26:36Z: game markets start around 16000
            # and the collection ends between 16000 and 32000. Sampling near
            # that boundary is worth more than another look at offset 0.
            offsets=(0, 8000, 12000, 16000, 18000, 20000, 24000, 28000),
        )
        print(
            f"[live_odds_worker] POLYMARKET_US_OFFSETS status={landscape.get('status')}"
            f" first_game_offset={landscape.get('first_game_offset')}"
            f" reason={landscape.get('reason')}",
            flush=True,
        )
        for offset, sample in (landscape.get("samples") or {}).items():
            print(
                f"[live_odds_worker] POLYMARKET_US_OFFSET at={offset} {sample}",
                flush=True,
            )

        # WHICH QUERY PARAMS DOES `/v1/markets` HONOUR?
        # ANSWERED 2026-08-24T20:56:41Z: `closed=false`. `fetch_markets` sends
        # it now, so this is behind a flag rather than ~25 signed calls a boot.
        if (os.environ.get("SYNDICATE_POLYMARKET_US_PARAM_PROBE") or "").strip() == "1":
            _print_param_probe(pm)

        # THE LEGACY `/v1` SPORTS ROUTES, which are NOT covered by the 404
        # above. Only `/v1/sports/teams/provider` was tested -- the `provider`
        # VARIANT -- and `/v1/sports` and `/v1/sports/teams` share the prefix
        # that works for `/v1/markets`. "That variant needs different
        # arguments" and "no sports data on this host" are different claims
        # with opposite consequences, so this asks rather than assuming.
        v1 = pm.probe_v1_sports_routes()
        for name, route in (v1.get("routes") or {}).items():
            print(
                f"[live_odds_worker] POLYMARKET_US_V1 route={name}"
                f" status={route.get('status')} count={route.get('count')}"
                f" payload_keys={route.get('payload_keys')}"
                f" row_keys={route.get('row_keys')}"
                f" reason={route.get('reason')}",
                flush=True,
            )

        if not (os.environ.get("SYNDICATE_POLYMARKET_US_SPORTS_PROBE") or "").strip() == "1":
            # See the docstring: confirmed 404, re-checkable on demand.
            print(
                "[live_odds_worker] POLYMARKET_US_SLATE status=skipped"
                " reason=sports_routes_404_on_this_host_measured_2026-08-24T20:18:37Z"
                " (set SYNDICATE_POLYMARKET_US_SPORTS_PROBE=1 to re-check)",
                flush=True,
            )
            return

        for sport in ("mlb", "wnba", "nfl"):
            slate = pm.fetch_league_slate(sport, limit=100, max_pages=3)
            print(
                f"[live_odds_worker] POLYMARKET_US_SLATE sport={sport}"
                f" status={slate.get('status')}"
                f" slug={slate.get('league_slug')} documented={slate.get('slug_documented')}"
                f" events={slate.get('event_count')} markets={slate.get('market_count')}"
                f" orderable={slate.get('orderable')}"
                f" no_markets={slate.get('events_without_markets')}"
                f" types={slate.get('sports_market_types')}"
                f" payload_keys={slate.get('payload_keys')}"
                f" event_keys={slate.get('event_keys')}"
                f" reason={slate.get('reason')}",
                flush=True,
            )
        teams = pm.fetch_teams("mlb")
        index = pm.team_alias_index(teams.get("teams") or [])
        print(
            f"[live_odds_worker] POLYMARKET_US_TEAMS status={teams.get('status')}"
            f" provider={teams.get('provider')} count={teams.get('count')}"
            f" aliases={len(index)} reason={teams.get('reason')}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[live_odds_worker] POLYMARKET_US_SLATE_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )


def _polymarket_spread_sign_audit_at_boot() -> None:
    """Which team does a Polymarket spread's sign belong to? Read-only, opt-in.

    Spreads are refused on every sport by name -- `execute_portfolio`'s
    `spread_side_needs_verified_team_mapping` and `venue_quote_adapters`'
    matching refusal -- because a spread's outcomes are signed numbers
    (`["-1.50","+1.50"]`) and name no team. That cost 1,519 quotes per cycle on
    2026-08-25.

    Two of the three facts needed to lift it are confirmed from production
    (the slug's `pos`/`neg` token labels `outcomes[0]`, 5 rows of 5; each
    fixture's ladder is symmetric about zero). The third -- home or away -- is
    not readable from any log line this worker emits, which is why this exists.

    Wrapped whole: a diagnostic that can stop the loop it is diagnosing is
    worse than no diagnostic.
    """
    try:
        from scripts.audit_polymarket_coverage import run_spread_audit_if_enabled

        run_spread_audit_if_enabled()
    except Exception as exc:  # noqa: BLE001
        print(
            f"[live_odds_worker] POLYMARKET_SPREAD_SIGN_AUDIT_FAILED"
            f" {type(exc).__name__}: {exc}",
            flush=True,
        )


def _game_line_grade_audit_at_boot() -> None:
    """Print the raw facts behind each game-line verdict, once, for eyeballing.

    Game lines returned -16.4% on 79 bets at a 35.44% win rate while totals
    returned +24.03% -- and game lines are the ones this session's own code
    started grading hours earlier. A consistent sign inversion looks exactly
    like that, and passes every guard already in place.

    Boot-time and one-shot: this is a question being asked, not a monitor.
    """
    try:
        from datetime import date, timedelta

        from syndicate.features.shared.paper_settlement import audit_game_line_grades

        # Yesterday's slate is the one with settled game lines on it; today's
        # are mostly still in progress.
        for offset in (1, 0):
            audit_game_line_grades((date.today() - timedelta(days=offset)).isoformat())
    except Exception as exc:
        print(
            f"[live_odds_worker] GRADE_AUDIT_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )


def _polymarket_catalogue_at_boot() -> None:
    """What does Polymarket actually list, and can any of it be joined?

    HERE RATHER THAN BESIDE THE KALSHI REFRESH, and that is a compromise worth
    stating. The natural home is `intelligence_state`'s refresh block, next to
    `run_kalshi_odds_refresh` -- but that file is claimed by an open lane
    (`layer2-sim-view-and-live-projection`) and the lane guard refused the
    edit, correctly. This worker is this lane's own, so the pull lands here and
    the move can happen when that lane closes.

    THE POINT IS THE SAMPLE. `paper:polymarket` reports +21.41% on 14 settled
    bets priced from the ODDS FEED's view of the venue -- roughly 1.5% of a
    slate -- so that edge is claimed at a price nothing has checked against
    Polymarket's own book. Fixing it needs a join, and Polymarket has no
    tickers at all: free-text questions against ERC-1155 token ids. The
    QUESTION lines this prints are what that join gets written from.

    Kalshi is the argument for doing it this way round. Its grammar was
    guessed twice -- "Will the X win by over N runs?" against a real "Texas
    wins by over 3.5 runs?", and `close_time` against a game date encoded in
    the event ticker -- and cost a day of `unreadable_title: 302` and
    `matched=0` before anyone read a real one.

    Read-only: Gamma and the CLOB price endpoint need no key, no wallet and no
    signature. Nothing reachable from here can place an order.
    """
    try:
        from pipeline.polymarket_odds_refresh import run_polymarket_odds_refresh

        result = run_polymarket_odds_refresh(force=True)
        print(
            f"[live_odds_worker] POLYMARKET_CATALOGUE status={result.get('status')}"
            f" count={result.get('count')} sporting={result.get('sporting')}"
            f" truncated={result.get('truncated')} reason={result.get('reason')}",
            flush=True,
        )
    except Exception as exc:
        # Named and contained, like every other optional boot diagnostic in
        # this file. A venue we cannot reach must not stop the worker booting.
        print(
            f"[live_odds_worker] POLYMARKET_CATALOGUE_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )


def _kalshi_series_catalogue_at_boot() -> None:
    """Which series does Kalshi list -- now asked with a SIGNED read.

    The unauthenticated catalogue call returned `http_429` from both public
    hosts while an authenticated call succeeded in the same minute. `_get` now
    signs when a credential is present, so this is the same question asked from
    a quota we are actually entitled to.
    """
    try:
        from syndicate.features.shared.kalshi_client import discover_series, series_matching

        # Imported HERE, not inside the auto-registration `try` below. A name
        # bound inside a try is unbound on the except path, and that is exactly
        # how `BET_STATUS_FAILED` shipped a block that had never once executed.
        from syndicate.features.shared.kalshi_catalogue import sport_for_series

        report = discover_series()
        tickers = report.get("tickers") or []
        print(
            "[live_odds_worker] KALSHI_SERIES_CATALOGUE"
            f" status={report.get('status')}"
            f" count={report.get('count')}"
            f" container={report.get('container_key')}"
            f" payload_keys={report.get('payload_keys')}"
            f" row_keys={report.get('row_keys')}"
            f" errors={report.get('errors')}",
            flush=True,
        )
        if report.get("status") != "ok":
            # No per-sport lines on a failed catalogue: `n=0` would read as
            # "Kalshi does not list it" when the truth is "we could not ask".
            print(
                "[live_odds_worker] KALSHI_SPORT_UNKNOWN reason=catalogue_unavailable",
                flush=True,
            )
            return
        # TITLES, not just tickers. `KXWNBATEAMTOTAL` is legible; most are not,
        # and the question tonight is which of the 91 is a PLAYER PROP -- the
        # only shape that can be joined on (player, market, line) and graded
        # without an event mapping that does not exist. A ticker list cannot
        # answer that and a title list can.
        titled = report.get("titles") or {}
        # AUTO-REGISTER the player-prop series Kalshi lists. Four were
        # hand-written; the catalogue has 13,389, and every sport added by hand
        # is a sport somebody has to remember. Registered only when the TITLE
        # says "Player <stat>" AND `market_keys` resolves that stat for that
        # sport -- either alone is a guess.
        try:
            from syndicate.features.shared.kalshi_catalogue import (
                auto_series_from_catalogue,
                register_discovered,
            )

            discovered = auto_series_from_catalogue(titled)
            result = register_discovered(discovered)
            print(
                "[live_odds_worker] KALSHI_AUTO_SERIES"
                f" added={result.get('added')}"
                f" total_discovered={result.get('total_discovered')}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[live_odds_worker] KALSHI_AUTO_SERIES_ERROR {type(exc).__name__}: {exc}",
                flush=True,
            )

        # THE PROP CANDIDATES, MAPPED OR NOT. This is what tells us which
        # series to add for a new sport, and it prints the ones we CANNOT price
        # as well as the ones we can -- a list of only what already works
        # cannot distinguish "Kalshi does not list it" from "we have no
        # vocabulary for it", which is exactly how 317 NFL series sat behind
        # `classified_n=0`. Soccer can only surface here: Kalshi names those
        # series by COMPETITION, so there is no sport token to add until the
        # real prefixes have been seen.
        try:
            from syndicate.features.shared.kalshi_catalogue import prop_candidates

            candidates = prop_candidates(titled)
            unmapped = [c for c in candidates if not c.get("market")]
            print(
                f"[live_odds_worker] KALSHI_PROP_CANDIDATES n={len(candidates)}"
                f" mapped={len(candidates) - len(unmapped)} unmapped={len(unmapped)}",
                flush=True,
            )
            for cand in unmapped[:60]:
                print(
                    f"[live_odds_worker] KALSHI_PROP_UNMAPPED sport={cand.get('sport')}"
                    f" stat={cand.get('stat')!r} ticker={cand.get('ticker')}"
                    f" title={cand.get('title')!r}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[live_odds_worker] KALSHI_PROP_CANDIDATES_ERROR {type(exc).__name__}: {exc}",
                flush=True,
            )

        # GAME-LINE SERIES, registered so they can be COUNTED. Registering is
        # not agreeing to bet them: `kalshi_board_join` keeps game lines behind
        # `SYNDICATE_KALSHI_GAME_LINES` and refuses an unresolved event by name.
        # This only makes totals, spreads, moneylines and their quarter/half and
        # alternate forms legible enough to measure.
        try:
            from syndicate.features.shared.kalshi_catalogue import (
                auto_game_series_from_catalogue,
                register_discovered,
            )

            game_found = auto_game_series_from_catalogue(titled)
            game_result = register_discovered(game_found)
            by_sport: dict[str, int] = {}
            for sport in game_found.values():
                by_sport[sport] = by_sport.get(sport, 0) + 1
            print(
                f"[live_odds_worker] KALSHI_GAME_SERIES found={len(game_found)}"
                f" added={len(game_result.get('added') or {})} by_sport={by_sport}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[live_odds_worker] KALSHI_GAME_SERIES_ERROR {type(exc).__name__}: {exc}",
                flush=True,
            )

        for token in ("WNBA",):
            found = series_matching([token], tickers)
            print(
                f"[live_odds_worker] KALSHI_SPORT {token} n={len(found)}",
                flush=True,
            )
            for ticker in found:
                print(
                    f"[live_odds_worker] KALSHI_SERIES {ticker} :: {str(titled.get(ticker) or '')[:70]}",
                    flush=True,
                )
        for token in ("NBA", "MLB", "NFL", "NHL"):
            # SUBSTRING MATCH, and the line says so. `KXWNBAPTS` contains
            # "NBA", so it appears under NBA here -- which read, in a log, as
            # the classifier having made exactly the mistake `_SPORT_TOKENS`
            # exists to prevent, and cost a diagnostic detour to disprove. The
            # classifier is `sport_for_series`; this is a catalogue census. A
            # diagnostic that cannot be told apart from the bug it is near is
            # worse than no diagnostic.
            found = series_matching([token], tickers)
            classified = [t for t in found if sport_for_series(t) == token.lower()]
            print(
                f"[live_odds_worker] KALSHI_SPORT {token}"
                f" ticker_substring_n={len(found)}"
                f" classified_n={len(classified)}"
                f" classified={classified[:12]}",
                flush=True,
            )
    except Exception as exc:
        print(
            f"[live_odds_worker] KALSHI_SERIES_CATALOGUE_ERROR {type(exc).__name__}: {exc}",
            flush=True,
        )


def _cancel_stale_enabled() -> bool:
    """Default ON. A stale resting order is not a neutral thing to leave: it
    cannot fill, and it blocks its own replacement. `off`/`0`/`false` disables."""
    raw = str(os.environ.get("SYNDICATE_EXECUTION_CANCEL_STALE") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _live_ledger_at_boot() -> None:
    """Print every LIVE order the ledger holds, with the venue's own error.

    A BOOT DUMP RATHER THAN AN ENDPOINT, because the endpoint is not always
    reachable and a real position is not something to be unable to look at.
    Added 2026-08-24 after the first real order this system sent failed and the
    reason -- written to the ledger by `place_order` -- had no reader anywhere
    in the logs. Read-only, and bounded: live orders are capped per day by
    `execution_guard`, so this cannot become the 4.9GB log the shadow ledger
    once was.
    """
    try:
        from syndicate.features.shared.execution_ledger import LIVE, _load

        orders = [
            o
            for o in (_load().get("orders") or [])
            if str(o.get("mode") or "") == LIVE
        ]
    except Exception as exc:
        # An unreadable ledger is NOT "no live orders" and must never print as
        # one -- that is the same absence/failure confusion the live page
        # exists to keep apart.
        print(
            f"[live_odds_worker] LIVE_LEDGER_UNREADABLE {type(exc).__name__}: {exc}",
            flush=True,
        )
        return

    # CORRECT BEFORE REPORTING. Rows written before adapters declared
    # `venue_contacted` carry `failed` for orders that never left the process,
    # and `failed` charges the daily budget and can block the next live run.
    # Idempotent, so this is a no-op on every boot after the first.
    try:
        from syndicate.features.shared.execution_ledger import reclassify_presend_failures

        fixed = reclassify_presend_failures()
        if fixed.get("reclassified"):
            print(
                f"[live_odds_worker] LEDGER_RECLASSIFIED n={fixed.get('reclassified')}"
                f" orders={fixed.get('orders')}",
                flush=True,
            )
    except Exception as exc:
        print(
            f"[live_odds_worker] LEDGER_RECLASSIFY_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )

    # THEN ASK KALSHI WHAT IT ACTUALLY HOLDS. Reclassification above corrects
    # rows from what we KNOW happened locally; this corrects them from what the
    # VENUE says, which is the only account that can see a resting order fill
    # after we stopped watching it. Runs on this worker because this is where
    # the Kalshi credentials live and where the ledger is already being read.
    try:
        from syndicate.features.shared.execution_ledger import reconcile_live_orders

        reconciled = reconcile_live_orders()

        # THEN PULL THE DEAD ONES OFF THE BOOK. Separate call, separate log,
        # because this is the only VENUE WRITE outside order placement -- a
        # read pass that quietly cancelled things would be the wrong shape to
        # run anywhere.
        #
        # Gated, and defaulting ON only because a resting order that has aged
        # out at a price the market has left behind cannot fill and holds its
        # own idempotency key hostage. `off` restores the old behaviour.
        if _cancel_stale_enabled() and reconciled.get("resting"):
            from syndicate.features.shared.execution_ledger import (
                cancel_stale_resting_orders,
            )

            cancel_stale_resting_orders(reconciled["resting"])

        if reconciled.get("changed"):
            # Re-read: the rows printed below are now stale by exactly the
            # corrections we just made, and a report of the pre-correction
            # state is worse than no report.
            orders = [
                o
                for o in (_load().get("orders") or [])
                if str(o.get("mode") or "") == LIVE
            ]
    except Exception as exc:
        print(
            f"[live_odds_worker] LEDGER_RECONCILE_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )

    print(f"[live_odds_worker] LIVE_LEDGER n={len(orders)}", flush=True)
    for order in orders[-25:]:
        print(
            f"[live_odds_worker] LIVE_LEDGER_ROW date={order.get('selected_date')}"
            f" status={order.get('status')} venue={order.get('venue')}"
            f" ticker={order.get('venue_ticker')}"
            f" sport={order.get('sport')} market={order.get('market')}"
            f" player={order.get('player_name')!r}"
            f" side={order.get('side')} line={order.get('line')}"
            f" price={order.get('requested_price')}"
            f" stake={order.get('requested_stake_dollars')}"
            f" fill_price={order.get('fill_price')}"
            f" outcome={order.get('outcome')}"
            f" error={order.get('error')!r}",
            flush=True,
        )


def _execution_interval_seconds() -> int:
    """How often to place, at most. Five minutes unless told otherwise.

    NOT the loop interval. This worker ticks as fast as 60s once a game is live,
    and a placer on that cadence would re-examine a plan far more often than the
    plan changes. The ledger refuses duplicates by key, so a faster cadence
    would cost nothing but noise -- but noise in the one log a person reads
    while money is moving is not free.
    """
    raw = os.environ.get("SYNDICATE_EXECUTION_INTERVAL_SECONDS")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return 300
    return parsed if parsed > 0 else 300


_LAST_EXECUTION_AT: float | None = None


def _run_execution_tick() -> None:
    """Place today's committed plan, on this worker, on its own clock.

    WHY HERE. `execute_portfolio`'s own contract says live placement must never
    run inside `refresh-worker`: that service has 110 OOM kills on record and
    restarts mid-job, and a restart between submit and record is exactly what
    the ledger's write-ahead exists to survive rather than to invite. This
    worker is the other long-lived process, so this is where a live placer
    belongs.

    NOT `inline=True`. That flag makes `run_execution` refuse live mode
    structurally, which is correct on refresh-worker and would make this
    function silently pointless here.

    DARK BY DEFAULT and gated four separate ways before anything is sent:
    `SYNDICATE_EXECUTION_ENABLED`, then `SYNDICATE_EXECUTION_MODE=live`, then
    `SYNDICATE_EXECUTION_LIVE_ARMED`, then the caps and the kill switch inside
    `run_execution` itself. Absent any of them this is a no-op that costs one
    dict lookup, the same relationship as the disk-maintenance call above.
    """
    global _LAST_EXECUTION_AT

    try:
        from pipeline.execute_portfolio import execution_enabled

        if not execution_enabled():
            return

        now = time.monotonic()
        interval = _execution_interval_seconds()
        if _LAST_EXECUTION_AT is not None and (now - _LAST_EXECUTION_AT) < interval:
            return
        _LAST_EXECUTION_AT = now

        from pipeline.execute_portfolio import run_execution
        from syndicate.features.shared.timezone import central_today_iso

        # STAMP THE SWITCHES WHERE WEB CAN SEE THEM. They are env vars on THIS
        # process; the web service has none of them and reading its own env
        # reports `mode=paper armed=no` on a live, armed book. Written every
        # tick so `recorded_at` doubles as a heartbeat.
        try:
            from syndicate.features.shared.execution_ledger import record_execution_state

            record_execution_state(recorded_by="live-odds-worker")
        except Exception as exc:
            print(
                f"[live_odds_worker] EXECUTION_STATE_STAMP_FAILED {type(exc).__name__}: {exc}",
                flush=True,
            )

        # THE VENUE-RESTRICTED PLAN, named explicitly. Without this the call
        # read the unrestricted plan and tried to place a soccer total and an
        # MLB spread on Kalshi (2026-08-24T00:34Z) -- positions priced at other
        # books, carrying no Kalshi ticker, that only the order builder stopped.
        # `run_execution` now refuses live mode without a scope, so this is the
        # explicit half of a guard that fails closed on both sides.
        #
        # A LIST, NOT ONE VENUE. This was read as a single string, so exactly
        # one venue could ever place -- Kalshi held the slot, and Polymarket US
        # could not transact no matter how complete its order path was. Comma
        # separated now, and one venue is still a list of one, so nothing
        # already configured changes meaning.
        #
        # RUN IN TURN, NOT POOLED. Each venue reads its OWN venue-restricted
        # plan (`read_portfolio_plan_for_venue`), because a position in
        # kalshi's plan is a claim that KALSHI quotes that market -- exactly
        # the category error `LIVE_WITHOUT_VENUE_SCOPE` refuses. One call per
        # venue is the only shape that keeps that true.
        #
        # ORDER IS THE CONFIGURED ORDER, and it is load-bearing whenever the
        # account-wide cap binds: the first venue listed gets first call on the
        # shared daily budget. Stated because it is a real allocation decision
        # hiding inside a string.
        venues = [
            part.strip().lower()
            for part in str(os.environ.get("SYNDICATE_EXECUTION_VENUE") or "").split(",")
            if part.strip()
        ]
        # `[None]` preserves the previous unscoped call exactly: live mode
        # refuses without a scope, and paper mode wants the unrestricted plan.
        # WHAT WOULD BUILD, BEFORE ANYTHING IS PLACED. Never submits -- see
        # `verify_order_paths`. Reported every cycle because the alternative
        # was learning the order path's state one slate at a time: six
        # sequential defects on 2026-08-25, each hidden behind the one before
        # it, each costing a real position we intended to hold. A per-market
        # verdict turns that into one reading.
        try:
            from pipeline.execute_portfolio import verify_order_paths

            checked = verify_order_paths(
                central_today_iso(), venues=tuple(venues) or ("kalshi", "polymarket")
            )
            for venue_name, detail in (checked.get("venues") or {}).items():
                print(
                    f"[live_odds_worker] ORDER_PATH venue={venue_name}"
                    f" status={detail.get('status')}"
                    f" positions={detail.get('positions')}"
                    f" markets={detail.get('markets')}"
                    f" examples={detail.get('examples')}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001 -- a diagnostic must never block a placer
            print(
                f"[live_odds_worker] ORDER_PATH_FAILED {type(exc).__name__}: {exc}",
                flush=True,
            )

        for venue in venues or [None]:
            result = run_execution(central_today_iso(), venue_scope=venue)
            print(
                "[live_odds_worker] EXECUTION"
                f" status={result.get('status')}"
                f" reason={result.get('reason')}"
                f" mode={result.get('mode')}"
                f" venue={result.get('venue')}"
                # The venue ASKED FOR, beside the venue the ledger recorded.
                # They differ when a venue has no plan, and "placed nothing
                # because there was no plan" must not read the same as "placed
                # nothing because the caps said no".
                f" scope={venue}"
                f" placed={result.get('placed')}"
                f" duplicates={result.get('duplicates')}"
                # Named refusals, so a cap that stopped a good slate and a plan
                # with nothing bettable never share a number.
                f" refused={result.get('refused')}"
                f" spent={result.get('spent')}"
                f" limits={result.get('limits')}",
                flush=True,
            )
    except Exception as exc:
        # A placer that raises must not take down the odds refresh this worker
        # exists for. Named, because a silent absence and a crashed placer are
        # different faults.
        print(
            f"[live_odds_worker] EXECUTION_ERROR {type(exc).__name__}: {exc}",
            flush=True,
        )


def _start_live_lens_reports() -> None:
    try:
        _log_worker_memory("start_live_lens_reports_before")
        start_live_lens_background_loop()
        _log_worker_memory("start_live_lens_reports_after")
    except Exception:
        _log_worker_memory("start_live_lens_reports_error")
        pass
    try:
        _log_worker_memory("start_live_lens_loop_before")
        start_live_lens_loop()
        _log_worker_memory("start_live_lens_loop_after")
    except Exception:
        _log_worker_memory("start_live_lens_loop_error")
        pass


def main() -> int:
    _log_worker_memory("startup", argv=list(sys.argv), pid=os.getpid())
    log_all_process_memory("startup", worker="run_live_odds_refresh_worker", pid=os.getpid(), argv=list(sys.argv))
    log_runtime_memory("startup", worker="run_live_odds_refresh_worker", pid=os.getpid(), argv=list(sys.argv))
    assert_refresh_state_backend_ready(process_name="live-odds-worker")

    # THIS SERVICE BUILDS THE SOCCER ARTIFACTS, SO IT NEEDS SOCCER'S SEED FILES.
    #
    # `#145`/`#170`/`#361` fixed exactly this three times in
    # `scripts/run_refresh_worker.py`, and it came back a fourth time here
    # because the soccer sim moved to a service whose entrypoint never ran any
    # bootstrap. Measured 2026-08-15: `_launch_autorun_soccer_pregame_refresh`
    # below spawns `scripts/build_soccer_artifacts.py` on THIS worker (its PID
    # is in our own ALL_PROCESS_MEMORY payload at 02:25:48Z, matching the
    # `generated_at` on all four published recommendations files), and
    # `_load_player_rows` reads `players_*.csv` off THIS disk -- which is not
    # refresh-worker's, and which nothing seeded. Every published file carried
    # `player_props: 0`, so all 107 player-prop rows on the soccer board had no
    # projection while the committed CSVs sat correct and unread in git.
    #
    # Must run AFTER assert_refresh_state_backend_ready: it resolves the
    # destination through `refresh_state_store.data_root()`.
    #
    # Never fatal. Missing seeds degrade the sim; a seeder that can stop this
    # worker booting is strictly worse than the bug it fixes.
    try:
        from syndicate.features.soccer.seed_bootstrap import bootstrap_soccer_seed_files

        bootstrap_soccer_seed_files(log_prefix="live_odds_worker")
    except Exception as exc:
        print(
            f"[live_odds_worker] SOCCER_SEED_BOOTSTRAP_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )

    # #57: the intelligence board build can now be hosted here instead of on
    # refresh-worker, where it no longer fits alongside the MLB sim in 2GB.
    # This service runs neither the sim nor the intelligence pipeline today,
    # which is why it is the candidate.
    #
    # Gated by the same env var refresh-worker uses, so exactly one service
    # owns the loop -- two owners would recompute the same state concurrently
    # and put the collision back, just on a different box.
    #
    # The risk here is different from refresh-worker's: this service's own
    # odds refresh can spawn WNBA SmartSim and is documented spiking to
    # ~1.3-1.5GB. The pipeline defers to an in-flight refresh for that reason
    # (see _odds_refresh_in_flight in pipeline/intelligence_state.py).
    if str(os.environ.get("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP") or "").strip().lower() in {"1", "true", "yes", "on"}:
        print("[live_odds_worker] INTELLIGENCE_LOOP_ENABLED calling start_intelligence_state_background_loop()", flush=True)
        try:
            from pipeline.intelligence_state import start_intelligence_state_background_loop

            loop_started = start_intelligence_state_background_loop()
            print(f"[live_odds_worker] INTELLIGENCE_LOOP_START_RESULT started={loop_started}", flush=True)
        except Exception as exc:
            # Must not stop this worker doing its actual job.
            print(f"[live_odds_worker] INTELLIGENCE_LOOP_START_FAILED {type(exc).__name__}: {exc}", flush=True)
    else:
        print("[live_odds_worker] INTELLIGENCE_LOOP_DISABLED", flush=True)
    parser = argparse.ArgumentParser(description="Run the Syndicate live odds refresh worker loop.")
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()

    def _emit_exit_memory() -> None:
        log_all_process_memory("before_exit", worker="run_live_odds_refresh_worker", pid=os.getpid())
        log_runtime_memory("before_exit", worker="run_live_odds_refresh_worker", pid=os.getpid())

    atexit.register(_emit_exit_memory)

    try:
        signal.signal(signal.SIGTERM, _handle_stop)
        signal.signal(signal.SIGINT, _handle_stop)
    except Exception:
        pass

    if not _acquire_process_lock():
        _log_worker_memory("lock_unavailable")
        print("LIVE ODDS REFRESH WORKER SKIPPED: lock_unavailable")
        return 0

    _start_live_lens_reports()

    try:
        interval_seconds = max(5, int(_live_refresh_loop_interval_seconds()))
    except Exception:
        interval_seconds = 60

    if args.run_once:
        try:
            _log_worker_memory("run_once_start", interval_seconds=interval_seconds)
            _run_tick()
            return 0
        finally:
            _log_worker_memory("run_once_finally")
            _release_process_lock()

    loop_started_at = time.monotonic()
    max_uptime_seconds = _max_uptime_seconds()
    recycled_for_uptime = False

    try:
        # FIRST, deliberately. Every comment below this block is about a
        # probe that never ran because something above it returned early;
        # nothing can be above this one.
        _ncaaf_oddsapi_report_at_boot()
        _kalshi_auth_probe_at_boot()
        _kalshi_series_catalogue_at_boot()
        # BEFORE the catalogue's early returns could ever swallow it -- placing
        # a probe after another probe's `return` is how the auth check went
        # three restarts without running.
        _live_ledger_at_boot()
        # Same reasoning, one line later: this sits AFTER the calls that own
        # early returns, so nothing above it can prevent it running. The whole
        # value is the QUESTION sample, and a diagnostic that silently never
        # executes is the failure mode this file has already had twice.
        _polymarket_catalogue_at_boot()
        _polymarket_us_auth_probe_at_boot()
        _polymarket_us_slate_probe_at_boot()
        # The WRITER, not the probe: the probe reports shape once at boot, this
        # keeps the artifact fresh for the fan-in to read.
        _polymarket_us_slate_refresh_tick()
        # AFTER the writer, deliberately: the audit reads the slate artifact,
        # so running it before the refresh tick would measure the previous
        # cycle's book. Inert unless SYNDICATE_POLYMARKET_SPREAD_AUDIT_ON_BOOT
        # is set -- absent means off -- and it only reads, so a boot with the
        # flag on costs one artifact read and one printed line. Unset the flag
        # again once the reading is taken, same as the two probe hooks on the
        # sibling worker. Full reasoning:
        # `docs/ai_context/polymarket_oddsapi_coverage_audit.md` SS5.4.
        _polymarket_spread_sign_audit_at_boot()
        _game_line_grade_audit_at_boot()
        _log_worker_memory("loop_start", interval_seconds=interval_seconds, max_uptime_seconds=max_uptime_seconds)
        while not _LIVE_REFRESH_LOOP_STOP.is_set():
            _log_worker_memory("loop_tick_begin", interval_seconds=interval_seconds)
            meta = _run_tick()
            # Disk maintenance: compaction + retention, once per day, AFTER the
            # tick rather than during it. Its own interval gate and its own
            # enable flag make this a no-op on every call but one per day, and a
            # no-op entirely until SYNDICATE_DISK_MAINTENANCE_ENABLED is set --
            # so calling it unconditionally here is cheap, the same relationship
            # as the soccer pregame autorun above. See `#241` for why periodic
            # work on this worker is never free.
            try:
                from syndicate.features.shared.disk_maintenance import run_disk_maintenance

                run_disk_maintenance()
            except Exception as exc:
                print(f"[live_odds_worker] DISK_MAINTENANCE_ERROR {type(exc).__name__}: {exc}", flush=True)
            # THE SLATE WRITER BELONGS IN THE LOOP, and was called only at boot.
            #
            # MEASURED 2026-08-25: POLYMARKET_US_SLATE_WRITE at 22:33:57Z
            # (instance c2727), then nothing until 00:13:15Z -- on a NEW
            # instance. 99 minutes on a 900s cadence should be ~6 writes; it
            # was one. Every write in the record is a fresh-boot write, because
            # `_POLYMARKET_SLATE_LAST_RUN` is per-process and resets to 0.0.
            #
            # The interval gate inside the function was never wrong; it simply
            # never got a second chance to run, so the artifact went as stale as
            # the worker was long-lived. That reads as a cadence in the log
            # (writes DO appear, with plausible gaps) which is why it survived.
            #
            # THIS IS NOW A MONEY PATH. `execute_portfolio._polymarket_resolve_
            # market` prices real orders off this artifact and, by its own
            # docstring, logs staleness rather than bounding it. A boot-only
            # writer means an order priced off a slate of unbounded age.
            #
            # Called BEFORE the execution tick so an order placed this pass is
            # priced from the freshest slate this pass can get.
            _polymarket_us_slate_refresh_tick()
            _run_execution_tick()
            # Use the adaptive interval (900s idle/pregame, 60s once a game is
            # actually live -- see _live_refresh_loop_interval_for_meta) rather
            # than the fixed base interval. Sleeping a fixed 60s regardless of
            # phase meant every pregame tick relaunched the full predict-date +
            # SmartSim pipeline before the previous attempt could possibly
            # finish (confirmed taking 20-30+ minutes cold), so the cold-start
            # WNBA/MLB slate could never complete -- each attempt got cut off
            # ~60-70s in as the next tick's launch collided with it.
            try:
                sleep_seconds = _live_refresh_loop_interval_for_meta(meta) if meta is not None else interval_seconds
            except Exception:
                sleep_seconds = interval_seconds
            uptime_seconds = time.monotonic() - loop_started_at
            if max_uptime_seconds is not None and uptime_seconds >= max_uptime_seconds:
                recycled_for_uptime = True
                _log_worker_memory("loop_recycle_for_uptime", uptime_seconds=uptime_seconds, max_uptime_seconds=max_uptime_seconds)
                print(f"LIVE ODDS REFRESH WORKER RECYCLING after {uptime_seconds:.0f}s uptime to reset accumulated page cache", flush=True)
                break
            _log_worker_memory("loop_sleep", interval_seconds=sleep_seconds)
            time.sleep(sleep_seconds)
    finally:
        _log_worker_memory("loop_finally", recycled_for_uptime=recycled_for_uptime)
        _release_process_lock()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Redeploy trigger, 2026-08-20 13:2xZ: SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN
# was set on the live service dashboard; a restart alone does not re-inject env
# vars on Render, so this comment-only change exists to produce a genuinely new,
# non-redundant commit for the redeploy that actually picks it up.
