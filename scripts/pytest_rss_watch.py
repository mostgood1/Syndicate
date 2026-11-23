"""Per-test memory lines for the nightly ci-suite (lane board-split-memory-guard, todo #850, findings section 19).

WHY. Every night one chunk of the fleet's ci-suite climbs ~2.5 GB in 2-3 minutes and sits at 3.05-3.37 GB, and on
2026-11-20 the same chunk ran away to 8,386 MB at ~1.6 GB a minute and was killed by the kernel (findings section 16,
H-O2). The heartbeat samples the process every ~12 s, so it can say WHICH CHUNK, never WHICH TEST: the 30 files that
move together between chunks are known, the test inside them is not. Running those files one at a time on the fleet
host would put multi-GB test processes beside the live roles. This plugin names the test from inside the run the
suite already makes, at no extra process.

LOADED ONLY BY `scripts/run_ci_suite.py`'s `_pytest_step` (`-p scripts.pytest_rss_watch`). GitHub's ci.yml calls
`pytest_baseline.py` directly and never loads it. It is tooling: no role imports it, and it changes no test's result.

WHAT IT MEASURES, per test (its whole setup + call + teardown): VmRSS at the start, the peak (VmHWM after a
`/proc/self/clear_refs` 5 reset at the start, and the highest sample the watchdog took), and VmRSS at the end. Only
THIS process: memory a test spends in a child process is invisible here (the heartbeat still sees it).

LINES. Each starts with a UTC timestamp, then `[pytest_rss_watch]`, on its own line:
  TEST_RSS_WATCH on pid= jump_mb= climb_floor_mb= climb_step_mb= interval_s= hwm_reset=yes|no
  TEST_RSS_WATCH off reason=no_proc|xdist_workers|error ...     (and then it says nothing more)
  TEST_RSS_JUMP nodeid= start_mb= peak_mb= end_mb= seconds=      peak >= jump_mb over the start (end = what it kept)
  TEST_RSS_CLIMB nodeid= rss_mb= start_mb= test_elapsed_s=       from the watchdog, WHILE the test runs: at
                                                                 >= climb_floor_mb and each climb_step_mb the test
                                                                 has grown, so a test the kernel kills is still named
  TEST_RSS_TOP rank= nodeid= start_mb= peak_mb= end_mb=          session end, by peak - start
  TEST_RSS_FILE_TOP rank= file= peak_mb= growth_mb= tests=       session end, by the file's peak
  TEST_RSS_FILE_GROWTH_TOP rank= file= growth_mb= peak_mb= tests=  session end, by retained growth (a leak)
  TEST_RSS_SUMMARY tests= jumps= climbs= start_mb= session_peak_mb= end_mb=

HOW IT WRITES. Through a dup of fd 1 taken when `-p` imports this module, which pytest does before its capture
starts (`Config._preparse`: `consider_preparse` runs before `pytest_load_initial_conftests`). So the watchdog's
lines reach the log even while a test's output is captured, and even if the kernel kills the process a second later.

SAFETY. It never fails a test and never changes a result: every hook body is guarded, and the first error writes one
`off reason=error` line and makes the plugin go quiet. In an xdist WORKER it does nothing at all, not even the dup
(a worker's stdout carries execnet's channel). With xdist workers running (`-n` > 0) the controller only says
`off reason=xdist_workers`: the tests run elsewhere. The fleet's suite runs `-n 0`, in-process.

KNOBS (environment; the fleet's ci-suite scrubs its env, so the defaults are what runs there):
PYTEST_RSS_WATCH_JUMP_MB 256, PYTEST_RSS_WATCH_CLIMB_FLOOR_MB 2048, PYTEST_RSS_WATCH_CLIMB_STEP_MB 512,
PYTEST_RSS_WATCH_INTERVAL_S 2, PYTEST_RSS_WATCH_TOP 10. A missing, junk or non-positive value is the default.
"""
from __future__ import annotations

import datetime as _dt
import heapq
import os
import sys
import threading
import time
from typing import Any, Callable

_STATUS = "/proc/self/status"
_CLEAR_REFS = "/proc/self/clear_refs"
_PREFIX = "[pytest_rss_watch]"

DEFAULTS = {
    "PYTEST_RSS_WATCH_JUMP_MB": 256.0,
    "PYTEST_RSS_WATCH_CLIMB_FLOOR_MB": 2048.0,
    "PYTEST_RSS_WATCH_CLIMB_STEP_MB": 512.0,
    "PYTEST_RSS_WATCH_INTERVAL_S": 2.0,
    "PYTEST_RSS_WATCH_TOP": 10.0,
}


def env_number(name: str, env: Any = None) -> float:
    """The knob's value; a missing, junk or non-positive value is its default."""
    source = os.environ if env is None else env
    try:
        value = float(str(source.get(name, "")).strip())
    except (TypeError, ValueError):
        return DEFAULTS[name]
    return value if value > 0 else DEFAULTS[name]


def read_status_mb(path: str = _STATUS) -> dict[str, float]:
    """{"VmRSS": MB, "VmHWM": MB} from /proc/self/status; {} when unreadable."""
    out: dict[str, float] = {}
    try:
        with open(path, "r", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    key, rest = line.split(":", 1)
                    out[key] = int(rest.split()[0]) / 1024.0
    except (OSError, ValueError, IndexError):
        return {}
    return out


def reset_hwm(path: str = _CLEAR_REFS) -> bool:
    """Reset this process's peak RSS to its current RSS (Linux >= 4.0). False when the kernel refuses."""
    try:
        with open(path, "w", encoding="ascii") as fh:
            fh.write("5")
        return True
    except OSError:
        return False


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def _xdist_worker() -> bool:
    return bool(os.environ.get("PYTEST_XDIST_WORKER"))


# The real stdout, duplicated at import (before pytest's capture). None in an xdist worker or where dup fails.
_OUT_FD: int | None = None
if not _xdist_worker():
    try:
        _OUT_FD = os.dup(1)
    except OSError:
        _OUT_FD = None


def _fd_writer(text: str) -> None:
    if _OUT_FD is None:
        return
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.write(_OUT_FD, f"\n{stamp} {_PREFIX} {text}\n".encode("utf-8", "replace"))


class Watch:
    """The per-test bookkeeping. `read` and `write` are injectable so it can be tested without /proc."""

    def __init__(
        self,
        *,
        read: Callable[[], dict[str, float]] = read_status_mb,
        reset: Callable[[], bool] = reset_hwm,
        write: Callable[[str], None] = _fd_writer,
        env: Any = None,
    ) -> None:
        self.read, self.reset, self.write = read, reset, write
        self.jump_mb = env_number("PYTEST_RSS_WATCH_JUMP_MB", env)
        self.floor_mb = env_number("PYTEST_RSS_WATCH_CLIMB_FLOOR_MB", env)
        self.step_mb = env_number("PYTEST_RSS_WATCH_CLIMB_STEP_MB", env)
        self.interval_s = env_number("PYTEST_RSS_WATCH_INTERVAL_S", env)
        self.top_n = int(env_number("PYTEST_RSS_WATCH_TOP", env))
        self.dead = False
        self.hwm_ok = False
        self._lock = threading.Lock()
        self._current: tuple[str, float, float] | None = None  # (nodeid, t0, start_mb)
        self._test_max = 0.0
        self._climb_last = 0.0
        self._top: list[tuple[float, str, float, float, float]] = []  # min-heap of (jump, nodeid, start, peak, end)
        self._files: dict[str, list[float]] = {}  # file -> [peak, growth, tests]
        self.tests = self.jumps = self.climbs = 0
        self.start_mb = self.session_peak = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- life cycle
    def begin(self) -> None:
        status = self.read()
        if "VmRSS" not in status:
            self.dead = True
            self.write("TEST_RSS_WATCH off reason=no_proc")
            return
        self.start_mb = self.session_peak = status["VmRSS"]
        self.hwm_ok = self.reset()
        self.write(
            f"TEST_RSS_WATCH on pid={os.getpid()} jump_mb={self.jump_mb:.0f} climb_floor_mb={self.floor_mb:.0f} "
            f"climb_step_mb={self.step_mb:.0f} interval_s={self.interval_s:g} hwm_reset={'yes' if self.hwm_ok else 'no'}"
        )

    def start_thread(self) -> None:
        if self.dead:
            return
        self._thread = threading.Thread(target=self._run, name="pytest_rss_watch", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            if self.dead:
                return
            try:
                self.sample()
            except Exception as exc:  # never let the watchdog take the run down
                self.fail("watchdog", exc)
                return

    def fail(self, where: str, exc: BaseException) -> None:
        if self.dead:
            return
        self.dead = True
        try:
            self.write(f"TEST_RSS_WATCH off reason=error where={where} error={type(exc).__name__}")
        except Exception:
            pass

    # -- per test
    def start_test(self, nodeid: str) -> None:
        if self.dead:
            return
        start = self.read().get("VmRSS", 0.0)
        if self.hwm_ok:
            self.reset()
        with self._lock:
            self._current = (nodeid, time.monotonic(), start)
            self._test_max = start
            self._climb_last = 0.0

    def sample(self) -> None:
        """One watchdog sample: track the test's peak, and write a CLIMB line at each new step."""
        rss = self.read().get("VmRSS")
        if rss is None:
            return
        line = None
        with self._lock:
            if rss > self.session_peak:
                self.session_peak = rss
            cur = self._current
            if cur is None:
                return
            nodeid, t0, start = cur
            if rss > self._test_max:
                self._test_max = rss
            grown = rss - start
            if rss >= self.floor_mb and grown >= self.step_mb and rss >= self._climb_last + self.step_mb:
                self._climb_last = rss
                self.climbs += 1
                line = (f"TEST_RSS_CLIMB nodeid={nodeid} rss_mb={rss:.0f} start_mb={start:.0f} "
                        f"test_elapsed_s={time.monotonic() - t0:.1f}")
        if line:
            self.write(line)

    def finish_test(self, nodeid: str) -> None:
        if self.dead:
            return
        status = self.read()
        end = status.get("VmRSS", 0.0)
        with self._lock:
            cur = self._current
            self._current = None
            sampled = self._test_max
        if cur is None or cur[0] != nodeid:
            return
        _, t0, start = cur
        peaks = [start, end, sampled]
        if self.hwm_ok and "VmHWM" in status:
            peaks.append(status["VmHWM"])
        peak = max(peaks)
        with self._lock:
            if peak > self.session_peak:
                self.session_peak = peak
        self.tests += 1
        jump = peak - start
        item = (jump, nodeid, start, peak, end)
        if len(self._top) < self.top_n:
            heapq.heappush(self._top, item)
        elif jump > self._top[0][0]:
            heapq.heapreplace(self._top, item)
        rec = self._files.setdefault(file_of(nodeid), [0.0, 0.0, 0.0])
        rec[0] = max(rec[0], peak)
        rec[1] += end - start
        rec[2] += 1
        if jump >= self.jump_mb:  # the peak includes the end, so this also catches what a test KEPT
            self.jumps += 1
            self.write(f"TEST_RSS_JUMP nodeid={nodeid} start_mb={start:.0f} peak_mb={peak:.0f} end_mb={end:.0f} "
                       f"seconds={time.monotonic() - t0:.1f}")

    # -- session end
    def summary(self) -> None:
        self._stop.set()
        if self.dead:
            return
        end = self.read().get("VmRSS", 0.0)
        for rank, (jump, nodeid, start, peak, stop) in enumerate(sorted(self._top, reverse=True), 1):
            self.write(f"TEST_RSS_TOP rank={rank} nodeid={nodeid} start_mb={start:.0f} peak_mb={peak:.0f} "
                       f"end_mb={stop:.0f}")
        by_peak = sorted(self._files.items(), key=lambda kv: kv[1][0], reverse=True)[: self.top_n]
        for rank, (name, (peak, growth, count)) in enumerate(by_peak, 1):
            self.write(f"TEST_RSS_FILE_TOP rank={rank} file={name} peak_mb={peak:.0f} growth_mb={growth:.0f} "
                       f"tests={count:.0f}")
        by_growth = sorted(self._files.items(), key=lambda kv: kv[1][1], reverse=True)[: self.top_n]
        for rank, (name, (peak, growth, count)) in enumerate(by_growth, 1):
            self.write(f"TEST_RSS_FILE_GROWTH_TOP rank={rank} file={name} growth_mb={growth:.0f} peak_mb={peak:.0f} "
                       f"tests={count:.0f}")
        self.write(f"TEST_RSS_SUMMARY tests={self.tests} jumps={self.jumps} climbs={self.climbs} "
                   f"start_mb={self.start_mb:.0f} session_peak_mb={self.session_peak:.0f} end_mb={end:.0f}")


# ---------------------------------------------------------------- pytest hooks (this module is the plugin)
_WATCH: Watch | None = None


def _workers_requested(config: Any) -> bool:
    try:
        value = config.getoption("numprocesses", None)
    except (ValueError, AttributeError):
        return False
    if value in (None, 0, "0"):
        return False
    return True


def pytest_configure(config: Any) -> None:
    global _WATCH
    if _xdist_worker() or _OUT_FD is None:
        return
    try:
        if _workers_requested(config):
            _fd_writer("TEST_RSS_WATCH off reason=xdist_workers")
            return
        watch = Watch()
        watch.begin()
        watch.start_thread()
        _WATCH = watch
    except Exception as exc:
        try:
            _fd_writer(f"TEST_RSS_WATCH off reason=error where=configure error={type(exc).__name__}")
        except Exception:
            pass


def _guarded(where: str, fn: Callable[[], None]) -> None:
    watch = _WATCH
    if watch is None or watch.dead:
        return
    try:
        fn()
    except Exception as exc:
        watch.fail(where, exc)


try:
    import pytest as _pytest

    @_pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_protocol(item: Any, nextitem: Any):  # noqa: ARG001 - pytest's signature
        watch = _WATCH
        if watch is not None:
            _guarded("start_test", lambda: watch.start_test(item.nodeid))
        try:
            return (yield)
        finally:
            if watch is not None:
                _guarded("finish_test", lambda: watch.finish_test(item.nodeid))

    def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:  # noqa: ARG001 - pytest's signature
        watch = _WATCH
        if watch is not None:
            _guarded("summary", watch.summary)
except ImportError:  # pragma: no cover - imported without pytest only by tests of the helpers
    pass
