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

MEMORY UNDER THE SPLIT -- three more switches, each absent = everything above unchanged (lane `board-split-memory-guard`,
todo #850, `.syndicate/findings_2026-11-18_board_split_memory_guard.md`). Measured on the fleet's first live evening
under the split (11-18, 5-10 PM CST): the heavy-build guard (`MEMORY_GUARD_ABORT ... floor_mb=1900`) refused 26 builds
(0 the evening before, in-thread), the child recycled 4 times, and the longest gap between board builds was 26.3 min.
The guard measures the ROLE TREE's RSS (parent + child) against the declared `SYNDICATE_LOCAL_MEMORY_LIMIT_MB` (7,168).
RSS is real here (PSS within 85 MB of it); the split added a second interpreter (the parent's calm RSS, p50 777 MB,
n 476), and the parent (tick / overlay) grows ~+1.1 GB from 5 to 9 PM. A child recycle cannot return parent memory.
- `SYNDICATE_BOARD_PROCESS_RAW_LIFELINE=1`: the lifeline reads fd 0 with `os.read`, not `sys.stdin.buffer.read`. The
  buffered read holds the BufferedReader's lock in a daemon thread, and interpreter shutdown then aborts ("Fatal Python
  error: _enter_buffered_busy ... <stdin>"), so every recycle exited rc -6 instead of 75 (4 of 4 on 11-18).
- `SYNDICATE_BOARD_PROCESS_CEILING_CREDIT_MB=<n>`: in the PARENT, before the child is spawned, the role's declared
  local ceiling gains `n` MB -- the second interpreter's cost -- so every headroom gate in both processes keeps the
  margin it had in-thread. Only where a local ceiling is declared (the fleet), only in process mode, once per tree.
  `SYNDICATE_BOARD_PROCESS_PARENT_TRIM_SECONDS=<s>`: the parent `malloc_trim`s every `s` seconds (no gc). In-thread,
  the board loop's trims (250-290 MB released per call, p50) also trimmed the tick's freed heap; the parent has none.
- `SYNDICATE_BOARD_PROCESS_RECYCLE_AFTER_BUILD=1`: the child also recycles RIGHT AFTER a completed build when its next
  build would be refused (the guard's own snapshot and floor, re-read under the build guard after a trim), instead of
  only after N refused cycles. It takes the build guard first, so no build starts in the exiting process; the respawned
  child's cold build then starts right after a publication. Held for: other processes' transient jobs (the board
  pair alone fits under the floor), uptime below the recycle minimum, children, a drain, recycling disabled. The
  refusal-streak recycle above stays as the fallback.
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
from typing import Any, Callable, Mapping, MutableMapping, Optional

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
# Lane `board-split-memory-guard` (todo #850): each absent = unchanged behaviour. See the module doc, "MEMORY".
RAW_LIFELINE_ENV = "SYNDICATE_BOARD_PROCESS_RAW_LIFELINE"
CEILING_CREDIT_ENV = "SYNDICATE_BOARD_PROCESS_CEILING_CREDIT_MB"
CEILING_CREDIT_APPLIED_ENV = "SYNDICATE_BOARD_PROCESS_CEILING_CREDIT_APPLIED"
PARENT_TRIM_ENV = "SYNDICATE_BOARD_PROCESS_PARENT_TRIM_SECONDS"
RECYCLE_AFTER_BUILD_ENV = "SYNDICATE_BOARD_PROCESS_RECYCLE_AFTER_BUILD"
CHILD_MODULE = "pipeline.board_build_process"
# `check_deploy_safety.SERVICE_CHILD_CMDLINE_MARKERS` carries this exact string.
CHILD_CMDLINE_MARKER = f"{CHILD_MODULE} --serve"
RECYCLE_EXIT_CODE = 75
LOOP_DIED_EXIT_CODE = 70

_BACKOFF_FIRST_S = 5.0
_BACKOFF_MAX_S = 300.0
_BACKOFF_RESET_AFTER_UP_S = 600.0
_SERVE_POLL_SECONDS = 5.0  # the child's main-loop poll; a test shortens it

_TRUE = {"1", "true", "yes", "on"}

# This module's own import time; the parent stamps it into the child's env as the ROLE's boot time when deploy_drain
# has not been imported yet (it normally has: run_refresh_worker's main loop imports it).
_MODULE_LOADED_AT = time.time()


def _log(message: str) -> None:
    print(f"[board_process] {message}", flush=True)


def board_build_process_enabled(env: Mapping[str, str] | None = None) -> bool:
    raw = str((os.environ if env is None else env).get(SWITCH_ENV) or "").strip().lower()
    return raw in _TRUE


def _switch_on(name: str, env: Mapping[str, str] | None = None) -> bool:
    return str((os.environ if env is None else env).get(name) or "").strip().lower() in _TRUE


def _positive_int_env(name: str, env: Mapping[str, str] | None = None) -> int:
    """Absent, junk, zero or negative -> 0 (off)."""
    raw = str((os.environ if env is None else env).get(name) or "").strip()
    try:
        value = int(float(raw)) if raw else 0
    except ValueError:
        return 0
    return value if value > 0 else 0


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


def apply_ceiling_credit(env: MutableMapping[str, str] | None = None) -> dict[str, int] | None:
    """PARENT side, process mode only: credit the role's declared local ceiling with the second interpreter's cost.

    `SYNDICATE_BOARD_PROCESS_CEILING_CREDIT_MB` absent / 0 / junk: nothing (returns None). Set: the declared
    `SYNDICATE_LOCAL_MEMORY_LIMIT_MB` becomes base + credit in THIS process's env, before `child_env()` copies it, so
    the parent's gates and the child's guard read the same ceiling (`_local_memory_limit_bytes` reads the env on every
    call). A host with no declared local ceiling (a cgroup host) is left alone. Once per tree: the child inherits the
    applied marker, and a respawned parent starts from the supervisor's env again.
    """
    target = os.environ if env is None else env
    credit = _positive_int_env(CEILING_CREDIT_ENV, target)
    if credit <= 0 or str(target.get(CEILING_CREDIT_APPLIED_ENV) or "").strip():
        return None
    from syndicate.features.shared.memory_observability import LOCAL_MEMORY_LIMIT_ENV

    raw = str(target.get(LOCAL_MEMORY_LIMIT_ENV) or "").strip()
    try:
        base = int(float(raw)) if raw else 0
    except ValueError:
        base = 0
    if base <= 0:
        _log(f"BOARD_PROCESS_CEILING_CREDIT skipped reason=no_local_limit credit_mb={credit}")
        return None
    target[LOCAL_MEMORY_LIMIT_ENV] = str(base + credit)
    target[CEILING_CREDIT_APPLIED_ENV] = f"{base}+{credit}"
    _log(f"BOARD_PROCESS_CEILING_CREDIT from_mb={base} to_mb={base + credit} credit_mb={credit}")
    return {"from_mb": base, "to_mb": base + credit, "credit_mb": credit}


_PARENT_TRIM_MIN_SECONDS = 60
_PARENT_TRIM_STOP = threading.Event()
_PARENT_TRIM_THREAD: Optional[threading.Thread] = None


def start_parent_trim(
    env: Mapping[str, str] | None = None,
    *,
    trim: Callable[[], Any] | None = None,
) -> Optional[threading.Thread]:
    """PARENT side, process mode only: `malloc_trim` (no gc) every `SYNDICATE_BOARD_PROCESS_PARENT_TRIM_SECONDS`.

    Absent / 0: no thread (returns None). Each trim logs `MALLOC_TRIM {... "reason": "board_split_parent_periodic",
    "rss_released_mb": ...}` -- the reading that says whether the parent's evening growth was freed heap.
    """
    global _PARENT_TRIM_THREAD
    seconds = _positive_int_env(PARENT_TRIM_ENV, env)
    if seconds <= 0:
        return None
    if _PARENT_TRIM_THREAD is not None and _PARENT_TRIM_THREAD.is_alive():
        return _PARENT_TRIM_THREAD
    seconds = max(_PARENT_TRIM_MIN_SECONDS, seconds)

    def _default_trim() -> Any:
        from syndicate.features.shared.memory_observability import release_freed_memory_to_os

        return release_freed_memory_to_os("board_split_parent_periodic", collect_first=False)

    do_trim = trim or _default_trim

    def _loop() -> None:
        while not _PARENT_TRIM_STOP.wait(seconds):
            try:
                do_trim()
            except Exception as exc:  # noqa: BLE001 - a trim must never cost the parent
                _log(f"BOARD_PROCESS_PARENT_TRIM_FAILED {type(exc).__name__}: {exc}")

    _PARENT_TRIM_STOP.clear()
    _PARENT_TRIM_THREAD = threading.Thread(target=_loop, name="board-process-parent-trim", daemon=True)
    _PARENT_TRIM_THREAD.start()
    _log(f"BOARD_PROCESS_PARENT_TRIM_STARTED interval_s={seconds} pid={os.getpid()}")
    return _PARENT_TRIM_THREAD


_SUPERVISOR: Optional[BoardProcessSupervisor] = None


def start_board_loop_for_refresh_worker(in_thread_starter: Callable[[], bool] | None = None) -> bool:
    """refresh-worker's ONE call to start the board loop. Returns what `INTELLIGENCE_LOOP_START_RESULT` prints.

    Switch off (the default): exactly the in-thread starter, nothing else. The worker passes its OWN imported name
    (`run_refresh_worker.start_intelligence_state_background_loop`), so the off path calls the very object it called
    before this module existed -- and a test that patches that name still sees the call.
    """
    global _SUPERVISOR
    from pipeline import intelligence_state

    starter = in_thread_starter or intelligence_state.start_intelligence_state_background_loop
    if not board_build_process_enabled():
        return starter()
    ready, why = _posix_ready()
    if not ready:
        _log(f"BOARD_PROCESS_MODE mode=thread reason={why} switch={SWITCH_ENV}=on")
        return starter()
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
    # Lane `board-split-memory-guard`: both no-ops unless their switch is set. The credit must precede child_env().
    try:
        apply_ceiling_credit()
    except Exception as exc:  # noqa: BLE001 - never cost the board its start
        _log(f"BOARD_PROCESS_CEILING_CREDIT_FAILED {type(exc).__name__}: {exc}")
    try:
        start_parent_trim()
    except Exception as exc:  # noqa: BLE001
        _log(f"BOARD_PROCESS_PARENT_TRIM_FAILED {type(exc).__name__}: {exc}")
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


def lifeline_reader(env: Mapping[str, str] | None = None) -> Callable[[], bytes]:
    """One byte from the parent's pipe; b"" at EOF.

    Off (default): `sys.stdin.buffer.read(1)`, as before. On (`SYNDICATE_BOARD_PROCESS_RAW_LIFELINE`): `os.read(0, 1)`.
    The buffered read keeps the BufferedReader's lock while it blocks, in a daemon thread; at interpreter shutdown,
    closing `sys.stdin` cannot get that lock and CPython aborts ("Fatal Python error: _enter_buffered_busy"), so a
    child that returns rc 75 dies of SIGABRT (rc -6) instead -- 4 of 4 recycles on 11-18. `os.read` holds no Python
    lock, so shutdown passes it by. Reproduced on the fleet's Python 3.11.16: buffered rc 134 (SIGABRT), raw rc 75.
    """
    if _switch_on(RAW_LIFELINE_ENV, env):
        return lambda: os.read(0, 1)
    return lambda: sys.stdin.buffer.read(1)


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

    read_one = lifeline_reader()

    def _read_stdin() -> None:
        try:
            while read_one():
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


# ----------------------------------------------------------------------- the post-build recycle (child side, #850)


def post_build_recycle_decision(
    *,
    snapshot: Mapping[str, Any] | None,
    pair_rss_mb: float | None,
    floor_mb: float,
    uptime_s: float,
    min_uptime_s: float,
    recycle_enabled: bool,
    children: list[int] | None,
    draining: bool,
) -> tuple[bool, str, dict[str, Any]]:
    """(recycle, reason, detail). Pure. Would the NEXT build be refused, and would recycling THIS process help?

    `snapshot` is the heavy guard's own `memory_headroom_snapshot(floor)`; `sufficient` is exactly what the next
    build's guard would decide. `pair_rss_mb` is the parent's RSS plus this child's: when the pair alone leaves the
    floor free, the shortfall is someone else's transient job (an odds sweep, a sim) and a recycle would cost a cold
    build for nothing, so it holds. The rest are `worker_recycle`'s own conditions.
    """
    snap = snapshot or {}
    detail: dict[str, Any] = {
        "headroom_mb": snap.get("headroom_mb"),
        "current_mb": snap.get("current_mb"),
        "max_mb": snap.get("max_mb"),
        "floor_mb": round(float(floor_mb), 1),
        "pair_rss_mb": None if pair_rss_mb is None else round(float(pair_rss_mb), 1),
        "uptime_s": int(uptime_s),
        "min_uptime_s": int(min_uptime_s),
    }
    if not recycle_enabled:
        return False, "disabled", detail
    if snapshot is None:
        return False, "headroom_unknown", detail  # the guard itself proceeds on an unreadable snapshot
    if snapshot.get("sufficient", True):
        return False, "headroom_ok", detail
    max_mb = snapshot.get("max_mb")
    if pair_rss_mb is not None and isinstance(max_mb, (int, float)) and float(max_mb) - float(pair_rss_mb) >= float(floor_mb):
        return False, "transient_jobs", detail
    if uptime_s < min_uptime_s:
        return False, "min_uptime", detail
    if children is None:
        return False, "children_unknown", detail
    detail["children"] = len(children)
    if children:
        return False, "children_running", detail
    if draining:
        return False, "drain_requested", detail
    return True, "recycle", detail


def _pair_rss_mb(parent_pid: int) -> float | None:
    try:
        import psutil

        total = int(psutil.Process(os.getpid()).memory_info().rss)
        if parent_pid > 0:
            total += int(psutil.Process(parent_pid).memory_info().rss)
        return total / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001 - unknown pair: fall back to the guard's own verdict
        return None


def _gather_post_build_decision(parent_pid: int, started_monotonic: float, *, trim: bool) -> tuple[bool, str, dict[str, Any]]:
    """The live inputs for `post_build_recycle_decision`. `trim` first, as the build's own guards do before reading."""
    from pipeline import intelligence_state
    from syndicate.features.shared import worker_recycle
    from syndicate.features.shared.memory_observability import memory_headroom_snapshot, release_freed_memory_to_os

    if trim:
        try:
            release_freed_memory_to_os("post_build_recycle_check", collect_first=False)
        except Exception:  # noqa: BLE001
            pass
    floor_bytes = int(intelligence_state._MIN_SAFE_MEMORY_HEADROOM_BYTES)
    try:
        snapshot = memory_headroom_snapshot(floor_bytes)
    except Exception:  # noqa: BLE001
        snapshot = None
    try:
        children = worker_recycle.child_process_pids(os.getpid())
    except Exception:  # noqa: BLE001
        children = None
    try:
        from syndicate.features.shared.deploy_drain import drain_active

        draining = bool(drain_active())
    except Exception:  # noqa: BLE001 - worker_recycle reads an unreadable drain the same way
        draining = False
    return post_build_recycle_decision(
        snapshot=snapshot,
        pair_rss_mb=_pair_rss_mb(parent_pid),
        floor_mb=floor_bytes / (1024.0 * 1024.0),
        uptime_s=max(0.0, time.monotonic() - started_monotonic),
        min_uptime_s=worker_recycle.recycle_min_uptime_seconds(),
        recycle_enabled=worker_recycle.recycle_after_refusals() > 0,
        children=children,
        draining=draining,
    )


_POST_BUILD_RETRY_REASONS = frozenset({"children_running", "children_unknown", "drain_requested"})
_POST_BUILD_QUIET_REASONS = frozenset({"headroom_ok", "headroom_unknown", "disabled"})


class PostBuildRecycler:
    """CHILD side. After each completed build, recycle now if the next build would be refused. One per child.

    `completed()` is `worker_recycle.heavy_builds_completed`; when it advances, a check is PENDING. The check runs
    unguarded first (cheap); only a "recycle" verdict takes the build guard (blocking, bounded -- a running build
    finishes first), and the verdict is re-read under it after a trim. Recycle -> `poll()` returns True and the guard
    stays HELD, so no build starts in a process that is about to exit. Anything else releases it. Retry reasons keep
    the check pending; every other reason settles it until the next completed build.
    """

    def __init__(
        self,
        guard: Any,
        *,
        decide: Callable[[bool], tuple[bool, str, dict[str, Any]]],
        completed: Callable[[], int],
        acquire_timeout_s: float = 30.0,
    ) -> None:
        self._guard = guard
        self._decide = decide
        self._completed = completed
        self._acquire_timeout_s = float(acquire_timeout_s)
        self._seen = int(completed())
        self.pending = False
        self._held_logged: Optional[str] = None

    def poll(self) -> bool:
        done = int(self._completed())
        if done != self._seen:
            self._seen = done
            self.pending = True
            self._held_logged = None
        if not self.pending:
            return False
        recycle, reason, detail = self._decide(False)
        if not recycle:
            return self._settle(reason, detail)
        if not self._guard.acquire(True, self._acquire_timeout_s):
            return False  # a build holds it; ask again after it
        try:
            recycle, reason, detail = self._decide(True)
        except Exception as exc:  # noqa: BLE001
            recycle, reason, detail = False, "decide_failed", {"error": f"{type(exc).__name__}: {exc}"}
        if recycle:
            _log(f"BOARD_PROCESS_RECYCLE pid={os.getpid()} reason=post_build_headroom {detail} -- the parent respawns this process")
            return True
        self._guard.release()
        return self._settle(reason, detail)

    def _settle(self, reason: str, detail: dict[str, Any]) -> bool:
        if reason in _POST_BUILD_RETRY_REASONS:
            if reason != self._held_logged:
                self._held_logged = reason
                _log(f"BOARD_PROCESS_POST_BUILD_CHECK held={reason} pending=1 {detail}")
            return False
        if reason not in _POST_BUILD_QUIET_REASONS:
            _log(f"BOARD_PROCESS_POST_BUILD_CHECK held={reason} {detail}")
        self.pending = False
        return False


def make_post_build_recycler(
    service: Any,
    *,
    parent_pid: int,
    started_monotonic: float,
    env: Mapping[str, str] | None = None,
) -> Optional[PostBuildRecycler]:
    """None unless `SYNDICATE_BOARD_PROCESS_RECYCLE_AFTER_BUILD` is on: then `_serve_main` behaves exactly as before."""
    if not _switch_on(RECYCLE_AFTER_BUILD_ENV, env):
        return None
    from syndicate.features.shared.worker_recycle import heavy_builds_completed

    return PostBuildRecycler(
        service._execution_guard,
        decide=lambda trim: _gather_post_build_decision(parent_pid, started_monotonic, trim=trim),
        completed=heavy_builds_completed,
    )


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
    recycler: Optional[PostBuildRecycler] = None
    try:
        recycler = make_post_build_recycler(service, parent_pid=parent_pid, started_monotonic=started)
    except Exception as exc:  # noqa: BLE001 - the post-build check must never cost the board
        _log(f"POST_BUILD_RECYCLE_SETUP_FAILED {type(exc).__name__}: {exc}")
    _log(
        f"BOARD_PROCESS_CHILD_SWITCHES pid={os.getpid()} raw_lifeline={int(_switch_on(RAW_LIFELINE_ENV))} "
        f"recycle_after_build={int(recycler is not None)} ceiling_credit={os.environ.get(CEILING_CREDIT_APPLIED_ENV) or 'none'}"
    )
    last_recycle_check = time.monotonic()
    while not gone.wait(_SERVE_POLL_SECONDS):
        thread = getattr(service, "_thread", None)
        if thread is None or not thread.is_alive():
            _log(f"BOARD_PROCESS_LOOP_DIED pid={os.getpid()} uptime_s={int(time.monotonic() - started)}")
            return LOOP_DIED_EXIT_CODE
        if recycler is not None:
            try:
                if recycler.poll():
                    return RECYCLE_EXIT_CODE
            except Exception as exc:  # noqa: BLE001
                _log(f"POST_BUILD_RECYCLE_CHECK_FAILED {type(exc).__name__}: {exc}")
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
