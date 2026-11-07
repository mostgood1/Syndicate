"""Live re-sim draws in worker PROCESSES, one GIL each (lane `ncaab-live-resim-capacity`, todo #762).

WHY. The live re-sim loops (NBA, NCAAB, WNCAAB) are `threading.Thread`s inside the live-odds-worker process,
beside the live-lens loop, the venue / in-play / exit loops and the main refresh loop. The possession engine is
pure-Python CPU work, so every one of those threads shares ONE interpreter lock. Measured on the fleet
2026-11-07 22:25-22:35Z (per-thread `/proc/<pid>/task/<tid>/stat`, 2 s samples): the process ran at 103% of a
core -- saturated -- across 11 CPU-active threads; the NCAAB re-sim thread got 12.1% of that core, 18.0% across
its 22:27:40-22:31:40Z tick (43.2 CPU-s in 240 s), and that tick re-simmed 1 of 15 live games. Offline, the same
re-sim took 8.25 s alone, 17.9 s as one of two threads (x2.17, thread CPU share 0.48) and 7.5 s as one of two
processes (`scripts/ncaab_resim_contention_probe.py`). Serialising the loops cannot help: the lock already
serialises them. A worker process has its own lock.

WHY NOT `multiprocessing`. Its `spawn` child re-imports the parent's `__main__` -- for the live-odds-worker that is
`scripts/run_live_odds_refresh_worker.py` and its 31 import lines, in every worker -- and `fork` in a process with
20+ threads can copy a lock some other thread holds. A plain `python -m` child imports only what the job needs, and
its stdin is its lifeline: when the parent dies the pipe closes and the child exits.

PROTOCOL. One job at a time per child: the parent writes `(module, function, kwargs)` as one length-prefixed
pickle on the child's stdin and reads `(status, value, meta)` back from its stdout. Only functions named in
`ALLOWED_JOBS` run. The child points its own `sys.stdout` at stderr before serving, so a stray `print` in the engine
lands in the worker log and can never corrupt the reply stream.

FAILURE IS NAMED, NEVER SILENT. A child that dies mid-job fails that job's future (`ResimWorkerError`); the next job
starts a fresh child. After `MAX_CONSECUTIVE_FAILURES` failed jobs in a row the pool marks itself `disabled` and the
caller runs in its own thread again, as before this module existed.
"""

from __future__ import annotations

import importlib
import os
import pickle
import queue
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
# "module:function" pairs a child may run. Nothing else is importable through the pipe.
ALLOWED_JOBS = frozenset({
    "syndicate.features.ncaab.live_resim:pool_resim_job",
})
MAX_CONSECUTIVE_FAILURES = 3
# The children yield to the board builds and odds jobs when the host is saturated (POSIX nice; ignored on Windows).
# The fleet shares 12 cores with them; a re-sim that waits is carried, a board that waits is not saved.
WORKER_NICE = 5
_HEADER = struct.Struct("!Q")


class ResimWorkerError(RuntimeError):
    """A job the pool could not complete: the child died, the pipe broke, or the job raised."""


def _write(stream: Any, obj: Any) -> None:
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_HEADER.pack(len(data)))
    stream.write(data)
    stream.flush()


def _read(stream: Any) -> Any:
    head = stream.read(_HEADER.size)
    if not head or len(head) < _HEADER.size:
        raise EOFError("worker pipe closed")
    (size,) = _HEADER.unpack(head)
    data = stream.read(size)
    if len(data) < size:
        raise EOFError("worker pipe closed mid-message")
    return pickle.loads(data)


class ResimWorkerPool:
    """`workers` child processes, each fed by one parent thread that blocks on its pipe (no lock held)."""

    def __init__(self, workers: int, *, nice: int = WORKER_NICE, python: Optional[str] = None,
                 env: Optional[Mapping[str, str]] = None, name: str = "live-resim"):
        self.workers = max(1, int(workers))
        self.nice = int(nice)
        self.python = python or sys.executable
        self.env = dict(env) if env is not None else None
        self.name = name
        self._jobs: "queue.Queue[Any]" = queue.Queue()
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._disabled = False
        self._closed = False
        self._procs: list[Optional[subprocess.Popen]] = [None] * self.workers
        self.pids_started: list[int] = []
        self._threads = [threading.Thread(target=self._serve, args=(i,), name=f"{name}-worker-{i}", daemon=True)
                         for i in range(self.workers)]
        for t in self._threads:
            t.start()

    @property
    def disabled(self) -> bool:
        return self._disabled or self._closed

    def submit(self, job: str, **kwargs: Any) -> Future:
        if job not in ALLOWED_JOBS:
            raise ValueError(f"job not allowed: {job}")
        fut: Future = Future()
        if self.disabled:
            fut.set_exception(ResimWorkerError("pool disabled"))
            return fut
        self._jobs.put((fut, job, kwargs))
        return fut

    def close(self) -> None:
        self._closed = True
        for _ in self._threads:
            self._jobs.put(None)
        for i, proc in enumerate(self._procs):
            self._stop(i, proc)

    # ---------------------------------------------------------------------------------------------- internals

    def _spawn(self) -> subprocess.Popen:
        cmd = [self.python, "-m", "syndicate.features.shared.live_resim_workers", "--serve", "--nice", str(self.nice)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, cwd=str(REPO_ROOT),
                                env=self.env, bufsize=0)
        with self._lock:
            self.pids_started.append(proc.pid)
        print(f"{self.name.upper().replace('-', '_')}_WORKER_STARTED pid={proc.pid} parent={os.getpid()}", flush=True)
        return proc

    def _stop(self, i: int, proc: Optional[subprocess.Popen]) -> None:
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        self._procs[i] = None

    def _note(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._consecutive_failures = 0
                return
            self._consecutive_failures += 1
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES and not self._disabled:
                self._disabled = True
                print(f"{self.name.upper().replace('-', '_')}_POOL_DISABLED consecutive_failures="
                      f"{self._consecutive_failures}", flush=True)

    def _serve(self, i: int) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            fut, job, kwargs = item
            if not fut.set_running_or_notify_cancel():
                continue
            if self.disabled:
                fut.set_exception(ResimWorkerError("pool disabled"))
                continue
            proc = self._procs[i]
            try:
                if proc is None or proc.poll() is not None:
                    proc = self._procs[i] = self._spawn()
                module, func = job.split(":", 1)
                _write(proc.stdin, (module, func, kwargs))
                status, value, meta = _read(proc.stdout)
            except BaseException as exc:  # noqa: BLE001 -- the child is gone or the pipe broke: restart it next job
                self._stop(i, proc)
                self._note(False)
                fut.set_exception(ResimWorkerError(f"{type(exc).__name__}: {exc}"))
                continue
            if status == "ok":
                self._note(True)
                fut.set_result((value, meta))
            else:
                self._note(False)
                fut.set_exception(ResimWorkerError(str(value)))


# -------------------------------------------------------------------------------------------------- the child

def _serve_main(nice: int) -> int:
    if nice and hasattr(os, "nice"):
        try:
            os.nice(nice)
        except OSError:
            pass
    stdin = sys.stdin.buffer
    # Replies go to a private copy of fd 1; fd 1 itself (and `sys.stdout`) now point at stderr, so the engine's
    # prints -- Python-level or C-level -- land in the log and can never corrupt the reply stream.
    sys.stdout.flush()
    reply = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    while True:
        try:
            module, func, kwargs = _read(stdin)
        except EOFError:
            return 0  # the parent closed the pipe (or died): nothing left to serve
        name = f"{module}:{func}"
        wall0, cpu0 = time.perf_counter(), time.process_time()
        try:
            if name not in ALLOWED_JOBS:
                raise PermissionError(f"job not allowed: {name}")
            value = getattr(importlib.import_module(module), func)(**kwargs)
            status = "ok"
        except Exception as exc:  # noqa: BLE001 -- reported to the parent, which names it
            status, value = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
        meta = {"pid": os.getpid(), "wall_s": time.perf_counter() - wall0, "cpu_s": time.process_time() - cpu0}
        _write(reply, (status, value, meta))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--nice", type=int, default=WORKER_NICE)
    a = ap.parse_args()
    raise SystemExit(_serve_main(a.nice) if a.serve else 2)
