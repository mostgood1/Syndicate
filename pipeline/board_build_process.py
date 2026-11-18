"""The Layer 2 board loop in its OWN PROCESS, behind a switch (lane `layer2-board-process-split`).

WHY. refresh-worker runs the board build on one thread (`syndicate-intelligence-state-loop`) and the book-grid /
in-play overlay tick on its main thread, with the chip publisher and the venue odds loop beside them -- one
interpreter lock for all of it. Measured on the fleet (per-thread `/proc` jiffies, `.syndicate/findings_2026-11-17_
layer2_board_process_split.md`): over 24 evening builds on 11-16 the board thread got a median 0.58 of a core
(0.36 in the overview stage, 0.38-0.53 in the early-evening builds that ran 345-942 s), the main thread 0.31, and the
process sat at 1.01 cores -- the lock, not the host, capped it. A process has its own lock. `live_resim_workers.py`
made the same move for the college re-sims (todo #762) and measured x2.17 as a thread vs x0.92 as a process.

THE SWITCH: `SYNDICATE_BOARD_BUILD_PROCESS`. Absent, empty or anything but 1/true/yes/on: refresh-worker starts the
board loop IN-THREAD exactly as before (`start_intelligence_state_background_loop()`, nothing else runs). On: the
parent keeps the venue odds loop and the game-chip publisher, and runs the board loop -- and only it -- in a
supervised child, `python -m pipeline.board_build_process --serve` (fresh interpreter, same env, same role log).
POSIX only: without `fcntl` the switch logs `BOARD_PROCESS_MODE mode=thread reason=no_fcntl` and stays in-thread.

WHAT CROSSES BETWEEN THE TWO, AND HOW
- Board outputs: unchanged. The loop already publishes through the keyvalue store and the data disk (web, which
  never runs the loop, reads them there); the parent's readers (venue loop, Kalshi arb scan) read the store too.
- "Board busy" for the parent's MLB-sim gate (`live_refresh_loop._sim_pipeline_deferral_reason` ->
  `intelligence_state.intelligence_pipeline_busy()` -> `_execution_guard.locked()`): the CHILD's guard is wrapped so it
  holds an `flock` on `BUSY_LOCK` while held; the PARENT's guard is replaced by a probe whose `locked()` reads that
  flock. Without this the gate would always read "idle" in the parent (the sim and the board would stack again, the
  2026-07-25 OOM). An unreadable probe reads BUSY: the gate's own defer bound (`SYNDICATE_MLB_SIM_MAX_PIPELINE_DEFERS`)
  keeps that from starving a sim.
- The ROLE's boot time, not the child's: `deploy_drain._PROCESS_BOOTED_AT` (a drain requested before the child
  (re)started must still hold it) and `live_refresh_loop._PROCESS_STARTED_AT` (else every MLB sim the parent started
  before the child reads `killed_by_restart` and its shared pointer is CLEARED). Passed in the env, set at child boot.
- `SYNDICATE_MLB_SIM_TICK_OWNER=false` in the child: it observes the sim pointer, never writes a death certificate.
- `SYNDICATE_LOCAL_MEMORY_ROOT_PID` = the parent: the child's headroom gates measure the whole role tree, as today.
- `SYNDICATE_GAME_CHIP_PUBLISH_ENABLED=0` in the child: the loop's `ensure_publisher_thread()` is a no-op there; the
  parent starts the publisher itself (its own 120 s clock; it depends on none of the board's work).
- Logs: the child inherits fd 1/2 -> the same role log, stamped by the same `sitecustomize`, so
  `check_deploy_safety`'s line-order board-build check (BUILD_SPAN_ENTER / LOOP_ITERATION) reads it unchanged.
  `check_deploy_safety.SERVICE_CHILD_CMDLINE_MARKERS` names the child, so it is not an in-flight JOB forever.

LIFETIME -- WHAT RESTARTS
- A refresh-worker restart restarts both: the child is in the role's process group (the supervisor's killpg reaches
  it), and its stdin is a pipe from the parent -- EOF (parent gone, however it died) makes the child SIGTERM itself,
  so its shutdown recorder names a board build it kills. A `getppid()` poll backs that up.
- A child exit restarts only the child: the parent's supervisor thread respawns it, 5 s backoff doubling to 300 s,
  reset after 10 min up. So `kill -TERM <child>` loads new board code without touching the parent's sims/odds jobs.
- ONE BUILDER: the child holds `LOCK_EX` on `BUILDER_LOCK` for its whole life and waits for it before starting the
  loop, so a second child can never build beside a first that has not exited yet.
- Recycle: heavy-build refusals are counted where the build runs (`worker_recycle`, in the child). The child runs
  `maybe_recycle` on its OWN uptime and exits rc 75; the parent respawns it. Under the switch a refusal streak restarts
  the board process, not the whole worker -- the parent's own refusal count stays 0, so it never recycles for them.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

try:  # POSIX only; the switch refuses without it
    import fcntl
except ImportError:  # pragma: no cover - Windows dev box
    fcntl = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]

SWITCH_ENV = "SYNDICATE_BOARD_BUILD_PROCESS"
CHILD_MARKER_ENV = "SYNDICATE_BOARD_BUILD_PROCESS_CHILD"
PARENT_PID_ENV = "SYNDICATE_BOARD_PROCESS_PARENT_PID"
PARENT_BOOTED_AT_ENV = "SYNDICATE_BOARD_PROCESS_PARENT_BOOTED_AT"
DRY_RUN_ENV = "SYNDICATE_BOARD_PROCESS_DRY_RUN"
CHILD_MODULE = "pipeline.board_build_process"
# `check_deploy_safety.SERVICE_CHILD_CMDLINE_MARKERS` carries this exact string.
CHILD_CMDLINE_MARKER = f"{CHILD_MODULE} --serve"
RECYCLE_EXIT_CODE = 75
LOOP_DIED_EXIT_CODE = 70

_BACKOFF_FIRST_S = 5.0
_BACKOFF_MAX_S = 300.0
_BACKOFF_RESET_AFTER_UP_S = 600.0

_TRUE = {"1", "true", "yes", "on"}

# This module's own import time; the parent stamps it into the child's env as the ROLE's boot time when deploy_drain
# has not been imported yet (it normally has: run_refresh_worker's main loop imports it).
_MODULE_LOADED_AT = time.time()


def _log(message: str) -> None:
    print(f"[board_process] {message}", flush=True)


def board_build_process_enabled(env: Mapping[str, str] | None = None) -> bool:
    raw = str((os.environ if env is None else env).get(SWITCH_ENV) or "").strip().lower()
    return raw in _TRUE


def _posix_ready() -> tuple[bool, str]:
    if fcntl is None:
        return False, "no_fcntl"
    if os.name != "posix":
        return False, f"os_{os.name}"
    return True, "ok"


def lock_dir() -> Path:
    """Where the two flock files live: the role's reports root (shared data disk, one per fleet home)."""
    from syndicate.features.shared.refresh_state_store import reports_root

    path = Path(reports_root()) / "board_process"
    path.mkdir(parents=True, exist_ok=True)
    return path


def busy_lock_path() -> Path:
    return lock_dir() / "board_build_busy.lock"


def builder_lock_path() -> Path:
    return lock_dir() / "board_builder.lock"


def _role_booted_at() -> float:
    try:
        from syndicate.features.shared.deploy_drain import _PROCESS_BOOTED_AT

        return float(_PROCESS_BOOTED_AT)
    except Exception:
        return _MODULE_LOADED_AT


def child_env(
    base: Mapping[str, str] | None = None,
    *,
    parent_pid: int | None = None,
    parent_booted_at: float | None = None,
) -> dict[str, str]:
    """The child's environment: the parent's, plus the five keys the design above names. Pure."""
    from syndicate.features.shared.memory_observability import LOCAL_MEMORY_ROOT_PID_ENV

    env = dict(os.environ if base is None else base)
    pid = int(parent_pid if parent_pid is not None else os.getpid())
    env[CHILD_MARKER_ENV] = "1"
    env[PARENT_PID_ENV] = str(pid)
    env[PARENT_BOOTED_AT_ENV] = repr(float(parent_booted_at if parent_booted_at is not None else _role_booted_at()))
    env["SYNDICATE_GAME_CHIP_PUBLISH_ENABLED"] = "0"
    env["SYNDICATE_MLB_SIM_TICK_OWNER"] = "false"
    env[LOCAL_MEMORY_ROOT_PID_ENV] = str(pid)
    return env


def child_command(python: str | None = None) -> list[str]:
    return [python or sys.executable, "-m", CHILD_MODULE, "--serve"]


# --------------------------------------------------------------------------------------- the busy signal, both sides


class CrossProcessGuard:
    """CHILD side. Wraps the service's `threading.Lock`; while it is held, also holds `LOCK_EX` on `path`.

    The inner lock stays the authority inside the child (the loop, the today cadence, the carry-over and the canonical
    drain all `acquire(blocking=False)` it). The flock is only the signal the parent reads. It is taken BLOCKING after
    the inner lock succeeds: the parent's probe holds its shared lock for microseconds, and a build must never be
    refused because the parent happened to be looking. A failure to signal never fails the build.
    """

    def __init__(self, inner: Any, path: Path) -> None:
        self._inner = inner
        self._path = Path(path)
        self._handle: Any = None

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        got = self._inner.acquire(blocking, timeout) if timeout != -1 else self._inner.acquire(blocking)
        if got:
            try:
                handle = open(self._path, "a+", encoding="utf-8")
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                self._handle = handle
            except Exception as exc:  # noqa: BLE001 - the signal must never cost the build
                _log(f"BUSY_SIGNAL_FAILED op=acquire {type(exc).__name__}: {exc}")
        return got

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:  # noqa: BLE001
                pass
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass
        self._inner.release()

    def locked(self) -> bool:
        return bool(self._inner.locked())

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc: Any) -> None:
        self.release()


def child_board_busy(path: Path | None = None) -> bool:
    """PARENT side. True while the board child holds the busy flock.

    No file yet = no child has ever built = idle. Any other failure to read = BUSY (unknown must not read as idle; the
    MLB-sim gate that reads this has its own defer bound, so BUSY cannot starve it).
    """
    try:
        target = Path(path) if path is not None else busy_lock_path()
        if not target.exists():
            return False
        if fcntl is None:
            return True
        with open(target, "r", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
    except Exception:  # noqa: BLE001
        return True


class ParentGuardProbe:
    """PARENT side. Stands in for the service's `_execution_guard`, which no parent thread computes under any more.

    `locked()` is what `intelligence_pipeline_busy()` reads: the parent's own lock OR the child's busy flock.
    `acquire` / `release` keep working on a real lock in case anything in the parent ever takes it.
    """

    def __init__(self, inner: Any | None = None, path: Path | None = None) -> None:
        self._inner = inner if inner is not None else threading.Lock()
        self._path = path

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        return self._inner.acquire(blocking, timeout) if timeout != -1 else self._inner.acquire(blocking)

    def release(self) -> None:
        self._inner.release()

    def locked(self) -> bool:
        return bool(self._inner.locked()) or child_board_busy(self._path)

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc: Any) -> None:
        self.release()


# ------------------------------------------------------------------------------------------------- the parent side


class BoardProcessSupervisor:
    """Spawns the child, waits on it (no lock held), respawns it with backoff. One per parent."""

    def __init__(
        self,
        *,
        python: str | None = None,
        env: Mapping[str, str] | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.python = python or sys.executable
        self.env = dict(env) if env is not None else None
        self._popen = popen
        self._clock = clock
        self._stop = threading.Event()
        self._sleep = sleep or (lambda seconds: self._stop.wait(seconds))
        self._thread: Optional[threading.Thread] = None
        self._proc: Any = None
        self.spawned: list[int] = []
        self.exits: list[tuple[int, Any, float]] = []

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="board-process-supervisor", daemon=True)
        self._thread.start()

    def spawn(self) -> Any:
        proc = self._popen(
            child_command(self.python),
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
            cwd=str(REPO_ROOT),
            env=self.env if self.env is not None else child_env(),
            close_fds=True,
        )
        self._proc = proc
        self.spawned.append(int(getattr(proc, "pid", 0) or 0))
        _log(f"BOARD_PROCESS_STARTED pid={getattr(proc, 'pid', None)} parent={os.getpid()} attempt={len(self.spawned)}")
        return proc

    def run_once(self, backoff: float) -> float:
        """Spawn, wait for exit, return the next backoff. Split out so a test can drive it without a thread."""
        started = self._clock()
        proc = self.spawn()
        while not self._stop.is_set():
            try:
                rc = proc.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                continue
        else:
            return backoff
        up = self._clock() - started
        next_backoff = _BACKOFF_FIRST_S if up >= _BACKOFF_RESET_AFTER_UP_S else min(_BACKOFF_MAX_S, max(_BACKOFF_FIRST_S, backoff * 2.0))
        delay = _BACKOFF_FIRST_S if up >= _BACKOFF_RESET_AFTER_UP_S else backoff
        reason = {RECYCLE_EXIT_CODE: "recycle", LOOP_DIED_EXIT_CODE: "loop_died"}.get(rc, "exit")
        self.exits.append((int(getattr(proc, "pid", 0) or 0), rc, up))
        _log(f"BOARD_PROCESS_EXITED pid={getattr(proc, 'pid', None)} rc={rc} reason={reason} uptime_s={int(up)} respawn_in_s={int(delay)}")
        self._proc = None
        self._sleep(delay)
        return next_backoff

    def _run(self) -> None:
        backoff = _BACKOFF_FIRST_S
        while not self._stop.is_set():
            try:
                backoff = self.run_once(backoff)
            except Exception as exc:  # noqa: BLE001 - a spawn failure must not kill the supervisor
                _log(f"BOARD_PROCESS_SPAWN_FAILED {type(exc).__name__}: {exc} retry_in_s={int(backoff)}")
                self._sleep(backoff)
                backoff = min(_BACKOFF_MAX_S, backoff * 2.0)

    def stop(self, timeout: float = 10.0) -> None:
        """For tests and a clean shutdown: close the lifeline, then terminate, then kill."""
        self._stop.set()
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=timeout)
        except Exception:  # noqa: BLE001
            try:
                proc.terminate()
                proc.wait(timeout=timeout)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass


_SUPERVISOR: Optional[BoardProcessSupervisor] = None


def start_board_loop_for_refresh_worker() -> bool:
    """refresh-worker's ONE call to start the board loop. Returns what `INTELLIGENCE_LOOP_START_RESULT` prints.

    Switch off (the default): exactly `start_intelligence_state_background_loop()`, nothing else.
    """
    global _SUPERVISOR
    from pipeline import intelligence_state

    if not board_build_process_enabled():
        return intelligence_state.start_intelligence_state_background_loop()
    ready, why = _posix_ready()
    if not ready:
        _log(f"BOARD_PROCESS_MODE mode=thread reason={why} switch={SWITCH_ENV}=on")
        return intelligence_state.start_intelligence_state_background_loop()
    _log(f"BOARD_PROCESS_MODE mode=process parent={os.getpid()}")
    # What `start_intelligence_state_background_loop` starts beside the loop stays in the parent.
    try:
        from pipeline.venue_odds_loop import start_venue_odds_loop

        start_venue_odds_loop()
    except Exception as exc:  # noqa: BLE001 - same contract as the in-thread starter
        print(f"[intelligence_state] VENUE_ODDS_LOOP_START_FAILED {type(exc).__name__}: {exc}", flush=True)
    try:
        from syndicate.features.shared.game_chip_publisher import ensure_publisher_thread

        ensure_publisher_thread()
    except Exception as exc:  # noqa: BLE001
        _log(f"CHIP_PUBLISHER_START_FAILED {type(exc).__name__}: {exc}")
    service = intelligence_state._INTELLIGENCE_STATE_SERVICE
    service._execution_guard = ParentGuardProbe(getattr(service, "_execution_guard", None))
    if _SUPERVISOR is None:
        _SUPERVISOR = BoardProcessSupervisor(env=child_env())
    _SUPERVISOR.start()
    return True


# -------------------------------------------------------------------------------------------------- the child side


def apply_role_clock(parent_booted_at: float) -> None:
    """Give the child the ROLE's boot time where per-process boot time decides correctness (see the module doc)."""
    from syndicate.features.shared import deploy_drain, live_refresh_loop

    deploy_drain._PROCESS_BOOTED_AT = float(parent_booted_at)
    live_refresh_loop._PROCESS_STARTED_AT = datetime.fromtimestamp(float(parent_booted_at), timezone.utc)


def _start_lifeline(parent_pid: int, gone: threading.Event) -> None:
    """EOF on stdin (or a new ppid) = the parent is gone: SIGTERM ourselves, so the shutdown recorder runs.

    The signal goes FIRST and `gone` is set only if it cannot be sent: set first, the main loop could see it, return
    and exit normally before the handler ran -- and a board build killed that way would leave no record.
    """
    fired = threading.Lock()

    def _on_gone(why: str) -> None:
        if not fired.acquire(blocking=False):
            return
        _log(f"BOARD_PROCESS_PARENT_GONE why={why} pid={os.getpid()} parent={parent_pid}")
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:  # noqa: BLE001
            gone.set()
            os._exit(0)

    def _read_stdin() -> None:
        try:
            while sys.stdin.buffer.read(1):
                pass
        except Exception:  # noqa: BLE001
            pass
        _on_gone("stdin_eof")

    def _watch_ppid() -> None:
        while not gone.wait(5.0):
            if parent_pid and os.getppid() != parent_pid:
                _on_gone("ppid_changed")

    threading.Thread(target=_read_stdin, name="board-process-lifeline", daemon=True).start()
    threading.Thread(target=_watch_ppid, name="board-process-ppid", daemon=True).start()


def _acquire_builder_lease(gone: threading.Event) -> Any:
    """Hold LOCK_EX on BUILDER_LOCK for life. Waits (never builds) while another child still holds it."""
    if fcntl is None:
        return None
    handle = open(builder_lock_path(), "a+", encoding="utf-8")
    waited = 0.0
    while not gone.is_set():
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                handle.seek(0)
                handle.truncate()
                handle.write(f"pid={os.getpid()}\n")
                handle.flush()
            except Exception:  # noqa: BLE001
                pass
            if waited:
                _log(f"BOARD_PROCESS_LEASE_ACQUIRED pid={os.getpid()} waited_s={int(waited)}")
            return handle
        except BlockingIOError:
            if waited % 60 == 0:
                _log(f"BOARD_PROCESS_LEASE_WAIT pid={os.getpid()} waited_s={int(waited)} -- another board process still holds it")
            time.sleep(5.0)
            waited += 5.0
    return None


def _serve_main() -> int:
    parent_pid = int(os.environ.get(PARENT_PID_ENV) or 0)
    try:
        parent_booted_at = float(os.environ.get(PARENT_BOOTED_AT_ENV) or 0) or time.time()
    except ValueError:
        parent_booted_at = time.time()
    started = time.monotonic()
    gone = threading.Event()
    dry_run = str(os.environ.get(DRY_RUN_ENV) or "").strip().lower() in _TRUE
    _log(f"BOARD_PROCESS_CHILD_BOOT pid={os.getpid()} parent={parent_pid} role_booted_at={parent_booted_at:.0f} dry_run={int(dry_run)}")
    if not dry_run:  # a dry run writes nothing, the shutdown record included; SIGTERM's default action ends it
        try:
            from syndicate.features.shared.worker_shutdown import install_shutdown_recorder

            install_shutdown_recorder("refresh-worker-board")
        except Exception as exc:  # noqa: BLE001
            _log(f"SHUTDOWN_RECORDER_FAILED {type(exc).__name__}: {exc}")
    _start_lifeline(parent_pid, gone)
    apply_role_clock(parent_booted_at)
    if dry_run:
        _log(f"BOARD_PROCESS_CHILD_READY pid={os.getpid()} dry_run=1")
        while not gone.wait(1.0):
            pass
        return 0
    from syndicate.features.shared.refresh_state_store import assert_refresh_state_backend_ready

    assert_refresh_state_backend_ready(process_name="refresh-worker-board")
    lease = _acquire_builder_lease(gone)
    if lease is None and fcntl is not None:
        return 0
    from pipeline import intelligence_state

    service = intelligence_state._INTELLIGENCE_STATE_SERVICE
    service._execution_guard = CrossProcessGuard(service._execution_guard, busy_lock_path())
    service.start()
    _log(f"BOARD_PROCESS_CHILD_READY pid={os.getpid()} parent={parent_pid}")
    last_recycle_check = time.monotonic()
    while not gone.wait(5.0):
        thread = getattr(service, "_thread", None)
        if thread is None or not thread.is_alive():
            _log(f"BOARD_PROCESS_LOOP_DIED pid={os.getpid()} uptime_s={int(time.monotonic() - started)}")
            return LOOP_DIED_EXIT_CODE
        if time.monotonic() - last_recycle_check >= 60.0:
            last_recycle_check = time.monotonic()
            try:
                from syndicate.features.shared.worker_recycle import maybe_recycle

                if maybe_recycle(parent_pid=os.getpid(), uptime_seconds=max(1.0, time.monotonic() - started)):
                    _log(f"BOARD_PROCESS_RECYCLE pid={os.getpid()} -- the parent respawns this process")
                    return RECYCLE_EXIT_CODE
            except Exception as exc:  # noqa: BLE001
                _log(f"RECYCLE_CHECK_FAILED {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    if "--serve" not in sys.argv[1:]:
        raise SystemExit(2)
    raise SystemExit(_serve_main())
