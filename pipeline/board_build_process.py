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

THE PARENT'S RATCHET -- two more switches, same rule (user "Yes, build it", 2026-11-21; findings §9-§12). Loaded, the
four above held the first evening (11-19: 4 refusals) and not the second (11-20: 13). The parent keeps ~+0.6 GB a day
that its trims do not return (785 MB 11-19 11 AM -> 1,610 MB 11-20 -> 2,166 MB 11-21 9 AM), and under the split nothing
restarts it: its refusal count stays 0 and the board child always counts as a running child.
- `SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_MB=<n>`: the PARENT exits at the worker main loop's own recycle point (a check
  it registers with `worker_recycle.maybe_recycle`; the main loop returns and the supervisor restarts the role) when
  its own RSS >= n MB, the UTC hour is inside `SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_UTC_HOURS` (default 09-12 =
  3:00-5:59 AM CST), it has been up >= `..._MIN_UPTIME_SECONDS` (default 6 h, so at most once a morning), no child
  other than the board child is alive, the board child is not building, no drain is requested, and the checkout's
  HEAD is still the one this process booted with. That last rule means a self-recycle never loads code: an ff that has
  not been deployed holds it (`held=code_on_disk_changed`) until someone restarts the role on purpose.
- `SYNDICATE_BOARD_PROCESS_RECURRING_JOBS_MARGIN_MB=<n>`: the post-build check above counts n MB of other jobs as
  RECURRING. The child recycles when the pair cannot carry them (max - pair - n < floor), even if the snapshot is
  sufficient right now. Without it, a shortfall the pair alone does not explain is "transient" and holds; measured
  11-20, 3 of 3 such holds were followed by 3 refused builds and the same recycle anyway. The role's other processes
  measured p50 0, p90 288-427 MB, max 784-820 MB (11-20 day, evening and night): they run about half the time.
- `SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_HEAD_RULE=loaded` (user "Yes build it now", 2026-11-26; findings §21-§22):
  which checkout change holds the self-recycle. Absent / empty / anything else = `any`: every HEAD move holds, as
  above. Measured 11-25: the parent was held 4 times of 4 by `code_on_disk_changed` after web-only ffs whose range
  changed `gunicorn.conf.py`, `syndicate/app.py`, a web blueprint and two ci scripts, none of them loaded by
  refresh-worker. The board child and every job child are fresh interpreters started from the checkout, so they
  already run whatever is on disk at each spawn. A parent restart newly loads only the PARENT's own modules (and any
  non-Python file it reads). So `loaded` holds only when `git diff --no-renames --name-only <boot> <disk>` names a
  `.py` file in this process's `sys.modules` (with `__main__`), or a non-Python file outside the exempt paths at
  `_HEAD_RULE_NON_RUNTIME_PREFIXES` (each pinned by a source-scan test). A diff it cannot read holds
  (`code_diff_unknown`), and so does a loaded set it cannot read.

THE HOST'S HEADROOM -- one more switch, same rule (user "Yes, build it", 2026-11-23; findings §16 and §18). A fresh
parent on a busy slate still reaches the refusal zone by evening (11-21: 12 refusals, gaps of 19-26 min), so neither the
morning restart nor the parent self-recycle covers it. The guard compares the role tree with a DECLARED ceiling that
nothing on the fleet enforces; the global OOM acts on the VM's MemAvailable. Measured 11-20 to 11-23 (149 heavy-build
refusals): the declared shortfall was p50 85-157 MB a day, max 940; the host had 5.3 and 6.5 GB available in the only
two evening samples (6:23 PM CST 11-21, 10:03 PM CST 11-19). The evening minimum was never sampled.
- `SYNDICATE_BOARD_PROCESS_HOST_OVERDRAFT_MB=<n>`: in the board CHILD only (registered at `_serve_main` start; the
  parent, web, live-odds-worker and the in-thread loop never register it), a headroom gate that the declared ceiling
  refuses is allowed when (1) the shortfall is at most n MB (capped at `HOST_OVERDRAFT_MAX_MB`) and (2) `/proc/meminfo`
  `MemAvailable` is at least the gate's floor + `SYNDICATE_BOARD_PROCESS_HOST_RESERVE_MB` (default 2048, the room the
  host's other roles keep for their own transients). An unreadable host refuses. Each grant logs
  `MEMORY_GUARD_HOST_OVERRIDE`, its own token, so `MEMORY_GUARD_ABORT` still counts refusals only; a refusal's snapshot
  carries `host_available_mb` and `host_override_reason`. This applies to every gate the child runs: the heavy-build
  guard, the Layer 2 shortlist's floor, and the post-build recycle check, which then agrees with the next build's guard.
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
# The parent's ratchet (2026-11-21): each absent = unchanged behaviour. See the module doc, "THE PARENT'S RATCHET".
PARENT_RECYCLE_ENV = "SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_MB"
PARENT_RECYCLE_HOURS_ENV = "SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_UTC_HOURS"
PARENT_RECYCLE_MIN_UPTIME_ENV = "SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_MIN_UPTIME_SECONDS"
PARENT_RECYCLE_HEAD_RULE_ENV = "SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_HEAD_RULE"
RECURRING_JOBS_MARGIN_ENV = "SYNDICATE_BOARD_PROCESS_RECURRING_JOBS_MARGIN_MB"
# The host's headroom (2026-11-23): absent = unchanged behaviour. See the module doc, "THE HOST'S HEADROOM".
HOST_OVERDRAFT_ENV = "SYNDICATE_BOARD_PROCESS_HOST_OVERDRAFT_MB"
HOST_RESERVE_ENV = "SYNDICATE_BOARD_PROCESS_HOST_RESERVE_MB"
HOST_RESERVE_DEFAULT_MB = 2048
HOST_OVERDRAFT_MAX_MB = 2048  # a typo (10000) must not turn the declared ceiling into nothing
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


# THE HOST'S HEADROOM (module doc). `/proc/meminfo` is the WSL VM's on the fleet: every role, redis and the ci-suite.
_MEMINFO_PATH = Path("/proc/meminfo")
_MIB = 1024 * 1024


def host_available_mb(path: Path | None = None) -> float | None:
    """`MemAvailable` in MB, or None when it cannot be read (no /proc, a junk line). None always refuses."""
    try:
        with open(_MEMINFO_PATH if path is None else path, "r", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def host_headroom_decision(
    *,
    headroom_mb: float | None,
    floor_mb: float,
    host_mb: float | None,
    overdraft_mb: int,
    reserve_mb: int,
) -> tuple[bool, str]:
    """(granted, reason) for one snapshot the declared ceiling refused. Every unknown refuses."""
    if host_mb is None:
        return False, "host_unreadable"
    if headroom_mb is None:
        return False, "no_declared_headroom"
    if floor_mb - headroom_mb > overdraft_mb:
        return False, "overdraft_exceeded"
    if host_mb < floor_mb + reserve_mb:
        return False, "host_below_floor_plus_reserve"
    return True, "granted"


def _make_host_headroom_hook(overdraft_mb: int, reserve_mb: int) -> Callable[..., dict[str, Any]]:
    def _hook(snapshot: Mapping[str, Any], min_required_bytes: int, context: Mapping[str, str]) -> dict[str, Any]:
        floor_mb = min_required_bytes / _MIB
        try:
            headroom_mb: float | None = float(snapshot.get("headroom_mb"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            headroom_mb = None
        host_mb = host_available_mb()
        granted, reason = host_headroom_decision(
            headroom_mb=headroom_mb, floor_mb=floor_mb, host_mb=host_mb, overdraft_mb=overdraft_mb, reserve_mb=reserve_mb,
        )
        shortfall = None if headroom_mb is None else round(floor_mb - headroom_mb, 1)
        host = None if host_mb is None else round(host_mb, 1)
        if granted:
            _log(
                f"MEMORY_GUARD_HOST_OVERRIDE stage={context.get('stage', '-')} caller={context.get('caller', '-')} "
                f"floor_mb={floor_mb:.0f} headroom_mb={headroom_mb} shortfall_mb={shortfall} host_available_mb={host} "
                f"overdraft_mb={overdraft_mb} reserve_mb={reserve_mb}"
            )
        return {
            "host_override": granted,
            "host_override_reason": reason,
            "host_available_mb": host,
            "declared_shortfall_mb": shortfall,
            "host_overdraft_mb": overdraft_mb,
            "host_reserve_mb": reserve_mb,
        }

    return _hook


def install_host_headroom_override(env: Mapping[str, str] | None = None) -> dict[str, int] | None:
    """CHILD side: register the host headroom hook in this process. Absent / 0 / junk: nothing (returns None).

    Refuses outside the board child (no `CHILD_MARKER_ENV`), so a stray key on the role can never reach the parent's
    or any in-thread caller's gates. The reserve's absent / 0 / junk is the default, never zero.
    """
    source = os.environ if env is None else env
    overdraft = _positive_int_env(HOST_OVERDRAFT_ENV, source)
    if overdraft <= 0:
        return None
    if str(source.get(CHILD_MARKER_ENV) or "").strip() != "1":
        _log(f"BOARD_PROCESS_HOST_HEADROOM held=not_board_child overdraft_mb={overdraft}")
        return None
    if overdraft > HOST_OVERDRAFT_MAX_MB:
        _log(f"BOARD_PROCESS_HOST_HEADROOM capped from_mb={overdraft} to_mb={HOST_OVERDRAFT_MAX_MB}")
        overdraft = HOST_OVERDRAFT_MAX_MB
    reserve = _positive_int_env(HOST_RESERVE_ENV, source) or HOST_RESERVE_DEFAULT_MB
    from syndicate.features.shared.memory_observability import set_headroom_override

    set_headroom_override(_make_host_headroom_hook(overdraft, reserve))
    host = host_available_mb()
    _log(
        f"BOARD_PROCESS_HOST_HEADROOM installed pid={os.getpid()} overdraft_mb={overdraft} reserve_mb={reserve} "
        f"host_available_mb={None if host is None else round(host, 1)}"
    )
    return {"overdraft_mb": overdraft, "reserve_mb": reserve}


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


# ------------------------------------------------------------ the parent self-recycle (parent side, #850, 2026-11-21)

_PARENT_RECYCLE_DEFAULT_HOURS = (9, 12)  # [09:00, 12:00) UTC = 3:00-5:59 AM CST (4:00-6:59 AM CDT)
_PARENT_RECYCLE_DEFAULT_MIN_UPTIME_S = 6 * 3600
_PARENT_RECYCLE_QUIET_REASONS = frozenset({"disabled", "below_threshold"})
PARENT_RECYCLE_CHECK_NAME = "board_parent_rss"


def parent_recycle_window(env: Mapping[str, str] | None = None) -> tuple[int, int]:
    """`SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_UTC_HOURS` as [start, end) UTC hours, e.g. "09-12"; it may wrap
    ("22-03"). Absent or junk -> the default 09-12."""
    raw = str((os.environ if env is None else env).get(PARENT_RECYCLE_HOURS_ENV) or "").strip()
    try:
        start_s, end_s = raw.split("-", 1)
        start, end = int(start_s), int(end_s)
    except ValueError:
        return _PARENT_RECYCLE_DEFAULT_HOURS
    if not (0 <= start <= 23 and 1 <= end <= 24) or start == end:
        return _PARENT_RECYCLE_DEFAULT_HOURS
    return start, end


def _hour_in_window(hour: int, window: tuple[int, int]) -> bool:
    start, end = window
    return start <= hour < end if start < end else (hour >= start or hour < end)


def parent_recycle_min_uptime_seconds(env: Mapping[str, str] | None = None) -> int:
    return _positive_int_env(PARENT_RECYCLE_MIN_UPTIME_ENV, env) or _PARENT_RECYCLE_DEFAULT_MIN_UPTIME_S


# Paths that no role imports or reads at runtime. A NON-Python change outside these holds the self-recycle under
# `head_rule=loaded`, because this rule cannot see which data files a process read at boot (a `.py` file it CAN see:
# `sys.modules`). Each exemption is pinned by a source-scan test in `tests/test_board_split_memory_guard.py`:
# - `reports/live_gameline_accuracy/history.jsonl` is committed every night (~11:31 PM CST); only comments name it.
# - `.md` outside `data/` and `reports/`: role code names no tracked markdown file (its `.md` literals are citations
#   and three MLB recaps generated under a season data directory).
# - `syndicate/templates/` and `syndicate/static/`: only `syndicate/app.py` builds an app that serves them (its
#   `template_folder` / `static_folder` and every `register_blueprint`), so they are exempt only while this process
#   has not loaded `syndicate/app.py`.
_HEAD_RULE_NON_RUNTIME_PREFIXES = (".syndicate/", "docs/", "tests/", ".claude/", ".github/")
_HEAD_RULE_NON_RUNTIME_FILES = frozenset({"reports/live_gameline_accuracy/history.jsonl"})
_HEAD_RULE_GENERATED_PREFIXES = ("data/", "reports/")
_HEAD_RULE_WEB_APP_PREFIXES = ("syndicate/templates/", "syndicate/static/")
_HEAD_RULE_WEB_APP_MODULE = "syndicate/app.py"


def parent_recycle_head_rule(env: Mapping[str, str] | None = None) -> str:
    """`SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_HEAD_RULE`: "loaded" only for `loaded`; anything else (absent, empty,
    junk) is "any", today's rule, so an unknown value can never loosen the hold."""
    raw = str((os.environ if env is None else env).get(PARENT_RECYCLE_HEAD_RULE_ENV) or "").strip().lower()
    return "loaded" if raw == "loaded" else "any"


def _head_rule_non_runtime(path: str, *, web_app_loaded: bool = True) -> bool:
    """A non-Python path that a parent restart cannot newly read (see the exemptions above `_HEAD_RULE_*`)."""
    return (
        path in _HEAD_RULE_NON_RUNTIME_FILES
        or path.startswith(_HEAD_RULE_NON_RUNTIME_PREFIXES)
        or (path.endswith(".md") and not path.startswith(_HEAD_RULE_GENERATED_PREFIXES))
        or (not web_app_loaded and path.startswith(_HEAD_RULE_WEB_APP_PREFIXES))
    )


def head_change_holds(changed: list[str], loaded: set[str] | frozenset[str]) -> list[str]:
    """Pure. The changed paths (repo-relative, posix) that hold a self-recycle under `head_rule=loaded`: a `.py` file
    this process has loaded, or a non-Python file outside the non-runtime paths. A `.py` file it has not loaded does
    not hold: if the process ever imports it, it reads it from disk anyway, restart or not."""
    web_app_loaded = _HEAD_RULE_WEB_APP_MODULE in loaded
    held: list[str] = []
    for path in changed:
        if path.endswith(".py"):
            if path in loaded:
                held.append(path)
        elif not _head_rule_non_runtime(path, web_app_loaded=web_app_loaded):
            held.append(path)
    return held


def _loaded_repo_files(
    modules: Mapping[str, Any] | None = None, *, repo: Path = REPO_ROOT, cwd: str | None = None
) -> set[str]:
    """Repo-relative posix paths of every module file this process has loaded, `__main__` included. A relative
    `__file__` is tried against both the repo and the working directory (both are kept), so it can only ADD holds."""
    root = repo.resolve()
    out: set[str] = set()
    for module in list((sys.modules if modules is None else modules).values()):
        raw = getattr(module, "__file__", None)
        if not raw:
            continue
        candidates = [Path(raw)] if os.path.isabs(raw) else [root / raw, Path(cwd or os.getcwd()) / raw]
        for candidate in candidates:
            try:
                out.add(candidate.resolve().relative_to(root).as_posix())
            except (ValueError, OSError):
                continue
    return out


_CHANGED_PATHS_CACHE: dict[tuple[str, str], Optional[list[str]]] = {}


def _changed_paths(
    boot_head: str, disk_head: str, *, repo: Path = REPO_ROOT, run: Callable[..., Any] = subprocess.run
) -> list[str] | None:
    """`git diff --no-renames --name-only <boot> <disk>` (a rename lists both names), or None when it cannot be read
    (None holds). Cached per (boot, disk): the check runs every main-loop cycle while everything else says recycle."""
    key = (boot_head, disk_head)
    if key in _CHANGED_PATHS_CACHE:
        return _CHANGED_PATHS_CACHE[key]
    try:
        out = run(
            ["git", "-C", str(repo), "diff", "--no-renames", "--name-only", boot_head, disk_head],
            capture_output=True, text=True, timeout=20,
        )
        paths: list[str] | None = (
            [line.strip() for line in str(getattr(out, "stdout", "") or "").splitlines() if line.strip()]
            if getattr(out, "returncode", 1) == 0 else None
        )
    except Exception:  # noqa: BLE001 - unreadable holds
        paths = None
    if paths is not None:  # a failure is retried next cycle; a success never changes for the same pair
        _CHANGED_PATHS_CACHE[key] = paths
    return paths


def parent_recycle_decision(
    *,
    threshold_mb: int,
    parent_rss_mb: float | None,
    utc_hour: int,
    window: tuple[int, int],
    uptime_s: float,
    min_uptime_s: float,
    other_children: list[int] | None,
    board_building: bool,
    draining: bool,
    boot_head: str | None,
    disk_head: str | None,
    head_rule: str = "any",
    head_diff: Mapping[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """(recycle, reason, detail). Pure. Should the split's PARENT exit now so the supervisor restarts it fresh?

    In order: switched on; its own RSS known and >= the threshold; inside the quiet window; up long enough; no child
    but the board child (a restart kills children exactly as a deploy does; unreadable = unknown = hold); the board
    child not mid-build (its busy flock); no drain; and the checkout's HEAD equal to the one it booted with, so a
    self-recycle never loads code (unreadable = hold). With `head_rule="loaded"` a different HEAD holds only when
    `head_diff["held"]` is non-empty (`head_change_holds`), and a diff it could not read (`head_diff["changed"]`
    None, or no `head_diff`) holds as `code_diff_unknown`.
    """
    detail: dict[str, Any] = {
        "parent_rss_mb": None if parent_rss_mb is None else round(float(parent_rss_mb), 1),
        "threshold_mb": int(threshold_mb),
        "utc_hour": int(utc_hour),
        "window_utc": f"{window[0]:02d}-{window[1]:02d}",
        "uptime_s": int(uptime_s),
        "min_uptime_s": int(min_uptime_s),
    }
    if threshold_mb <= 0:
        return False, "disabled", detail
    if parent_rss_mb is None:
        return False, "rss_unknown", detail
    if float(parent_rss_mb) < float(threshold_mb):
        return False, "below_threshold", detail
    if not _hour_in_window(int(utc_hour), window):
        return False, "outside_window", detail
    if uptime_s < min_uptime_s:
        return False, "min_uptime", detail
    if other_children is None:
        return False, "children_unknown", detail
    detail["children"] = len(other_children)
    if other_children:
        return False, "children_running", detail
    if board_building:
        return False, "board_building", detail
    if draining:
        return False, "drain_requested", detail
    detail["boot_head"] = (boot_head or "")[:12] or None
    detail["disk_head"] = (disk_head or "")[:12] or None
    if not boot_head or not disk_head:
        return False, "code_unknown", detail
    if boot_head != disk_head:
        if head_rule != "loaded":
            return False, "code_on_disk_changed", detail
        detail["head_rule"] = "loaded"
        changed = None if head_diff is None else head_diff.get("changed")
        if changed is None:
            return False, "code_diff_unknown", detail
        held = list((head_diff or {}).get("held") or [])
        detail["changed_files"] = len(changed)
        if held:
            detail["changed_held_n"] = len(held)
            detail["changed_held"] = held[:3]
            return False, "code_on_disk_changed", detail
        detail["changed_ignored"] = len(changed)
    return True, "recycle", detail


def _git_head(repo: Path = REPO_ROOT, *, run: Callable[..., Any] = subprocess.run) -> str | None:
    """The checkout's HEAD SHA, or None when it cannot be read (None holds a self-recycle)."""
    try:
        out = run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return None
    sha = str(getattr(out, "stdout", "") or "").strip()
    if getattr(out, "returncode", 1) != 0 or len(sha) != 40:
        return None
    return sha


def _own_rss_mb() -> float | None:
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss) / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001 - unknown holds
        return None


def _supervisor_child_pid(supervisor: Any) -> int | None:
    proc = getattr(supervisor, "_proc", None)
    pid = getattr(proc, "pid", None)
    return int(pid) if pid else None


def _gather_parent_recycle_decision(
    *,
    threshold_mb: int,
    boot_head: str | None,
    board_child_pid: Callable[[], int | None],
    env: Mapping[str, str] | None = None,
    head: Callable[[], str | None] | None = None,
    now: Callable[[], float] | None = None,
    changed_paths: Callable[[str, str], list[str] | None] | None = None,
    loaded_files: Callable[[], set[str]] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """The live inputs for `parent_recycle_decision`. The HEAD is read only when everything else says recycle, and
    the diff (head rule `loaded`) only when that HEAD differs from the boot HEAD."""
    from syndicate.features.shared import worker_recycle

    head = head or _git_head
    now = now or time.time

    try:
        children = worker_recycle.child_process_pids(os.getpid())
    except Exception:  # noqa: BLE001
        children = None
    board_pid = board_child_pid()
    try:
        from syndicate.features.shared.deploy_drain import drain_active

        draining = bool(drain_active())
    except Exception:  # noqa: BLE001 - an unreadable drain must not read as "no drain" for an unattended exit
        draining = True
    args: dict[str, Any] = dict(
        threshold_mb=threshold_mb,
        parent_rss_mb=_own_rss_mb(),
        utc_hour=time.gmtime(now()).tm_hour,
        window=parent_recycle_window(env),
        uptime_s=max(0.0, now() - _role_booted_at()),
        min_uptime_s=parent_recycle_min_uptime_seconds(env),
        other_children=None if children is None else [pid for pid in children if pid != board_pid],
        board_building=child_board_busy(),
        draining=draining,
        boot_head=boot_head,
    )
    recycle, reason, detail = parent_recycle_decision(**args, disk_head=boot_head)
    if not recycle:
        return recycle, reason, detail
    disk_head = head()
    rule = parent_recycle_head_rule(env)
    head_diff: dict[str, Any] | None = None
    if rule == "loaded" and boot_head and disk_head and disk_head != boot_head:
        try:
            changed = (changed_paths or _changed_paths)(boot_head, disk_head)
            held = None if changed is None else head_change_holds(changed, (loaded_files or _loaded_repo_files)())
        except Exception:  # noqa: BLE001 - unreadable holds
            changed, held = None, None
        head_diff = {"changed": changed, "held": held or []}
    return parent_recycle_decision(**args, disk_head=disk_head, head_rule=rule, head_diff=head_diff)


class ParentSelfRecycler:
    """PARENT side. Registered with `worker_recycle.maybe_recycle`, which the worker's main loop calls at its own safe
    point every cycle. True -> the main loop returns and the supervisor restarts the role. A held check logs once per
    reason change; below the threshold it is silent."""

    def __init__(self, decide: Callable[[], tuple[bool, str, dict[str, Any]]]) -> None:
        self._decide = decide
        self._held: Optional[str] = None

    def __call__(self) -> bool:
        recycle, reason, detail = self._decide()
        if recycle:
            _log(f"BOARD_PROCESS_PARENT_RECYCLE pid={os.getpid()} {detail} -- the supervisor restarts refresh-worker")
            return True
        if reason in _PARENT_RECYCLE_QUIET_REASONS:
            self._held = None
            return False
        if reason != self._held:
            self._held = reason
            _log(f"BOARD_PROCESS_PARENT_RECYCLE_CHECK held={reason} {detail}")
        return False


def install_parent_self_recycle(
    supervisor: Any,
    env: Mapping[str, str] | None = None,
    *,
    register: Callable[[str, Callable[[], bool]], None] | None = None,
    head: Callable[[], str | None] | None = None,
) -> Optional[ParentSelfRecycler]:
    """PARENT side, process mode only. None unless `SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_MB` > 0: then the worker's
    main loop and its recycle check behave exactly as before."""
    threshold = _positive_int_env(PARENT_RECYCLE_ENV, env)
    if threshold <= 0:
        return None
    if register is None:
        from syndicate.features.shared.worker_recycle import register_recycle_check as register
    head = head or _git_head
    boot_head = head()
    recycler = ParentSelfRecycler(
        lambda: _gather_parent_recycle_decision(
            threshold_mb=threshold,
            boot_head=boot_head,
            board_child_pid=lambda: _supervisor_child_pid(supervisor),
            env=env,
            head=head,
        )
    )
    register(PARENT_RECYCLE_CHECK_NAME, recycler)
    window = parent_recycle_window(env)
    _log(
        f"BOARD_PROCESS_PARENT_RECYCLE_ARMED pid={os.getpid()} threshold_mb={threshold} "
        f"window_utc={window[0]:02d}-{window[1]:02d} min_uptime_s={parent_recycle_min_uptime_seconds(env)} "
        f"boot_head={(boot_head or 'unknown')[:12]} head_rule={parent_recycle_head_rule(env)}"
    )
    return recycler


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
    try:  # a no-op unless SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_MB is set (2026-11-21)
        install_parent_self_recycle(_SUPERVISOR)
    except Exception as exc:  # noqa: BLE001 - never cost the board its start
        _log(f"BOARD_PROCESS_PARENT_RECYCLE_SETUP_FAILED {type(exc).__name__}: {exc}")
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
    jobs_margin_mb: float = 0.0,
) -> tuple[bool, str, dict[str, Any]]:
    """(recycle, reason, detail). Pure. Would the NEXT build be refused, and would recycling THIS process help?

    `snapshot` is the heavy guard's own `memory_headroom_snapshot(floor)`; `sufficient` is exactly what the next
    build's guard would decide. `pair_rss_mb` is the parent's RSS plus this child's: when the pair alone leaves the
    floor free, the shortfall is someone else's transient job (an odds sweep, a sim) and a recycle would cost a cold
    build for nothing, so it holds. The rest are `worker_recycle`'s own conditions.

    `jobs_margin_mb` > 0 (`SYNDICATE_BOARD_PROCESS_RECURRING_JOBS_MARGIN_MB`): the other jobs RECUR, so the question is
    whether the pair can carry `jobs_margin_mb` of them. It fits -> hold (`headroom_ok` if the snapshot is sufficient
    now, else `transient_jobs`); it does not -> go on to the recycle conditions, even when the snapshot is sufficient
    right now, because the next build that overlaps a typical job will be refused. An unknown pair falls back to the
    rule without the margin. 0 (the default) is the rule without the margin, unchanged.
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
    margin = max(0.0, float(jobs_margin_mb or 0.0))
    if margin > 0:
        detail["jobs_margin_mb"] = round(margin, 1)
    if not recycle_enabled:
        return False, "disabled", detail
    if snapshot is None:
        return False, "headroom_unknown", detail  # the guard itself proceeds on an unreadable snapshot
    max_mb = snapshot.get("max_mb")
    if margin > 0 and pair_rss_mb is not None and isinstance(max_mb, (int, float)):
        if float(max_mb) - float(pair_rss_mb) - margin >= float(floor_mb):
            return False, ("headroom_ok" if snapshot.get("sufficient", True) else "transient_jobs"), detail
        detail["basis"] = "pair_plus_recurring_jobs"
    else:
        if snapshot.get("sufficient", True):
            return False, "headroom_ok", detail
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
        jobs_margin_mb=float(_positive_int_env(RECURRING_JOBS_MARGIN_ENV)),
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
    # Before the dry-run branch, so a dry-run child shows the switch reaching a real process (it builds nothing).
    host_headroom: Optional[dict[str, int]] = None
    try:
        host_headroom = install_host_headroom_override()
    except Exception as exc:  # noqa: BLE001 - a broken install grants nothing and must never cost the board
        _log(f"HOST_HEADROOM_SETUP_FAILED {type(exc).__name__}: {exc}")
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
    margin = _positive_int_env(RECURRING_JOBS_MARGIN_ENV)
    _log(
        f"BOARD_PROCESS_CHILD_SWITCHES pid={os.getpid()} raw_lifeline={int(_switch_on(RAW_LIFELINE_ENV))} "
        f"recycle_after_build={int(recycler is not None)} ceiling_credit={os.environ.get(CEILING_CREDIT_APPLIED_ENV) or 'none'}"
        + (f" jobs_margin_mb={margin}" if margin > 0 else "")
        + (
            f" host_overdraft_mb={host_headroom['overdraft_mb']} host_reserve_mb={host_headroom['reserve_mb']}"
            if host_headroom
            else ""
        )
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
