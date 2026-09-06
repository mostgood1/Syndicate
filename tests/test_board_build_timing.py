"""`#567` -- is the board build SLOW, or is it WAITING?

WHY THIS EXISTS, and it is a method failure rather than a code defect. Every
estimate of where the board build's time goes has been read from the GAP BETWEEN
two log lines, and on 2026-08-25 that produced three wrong answers in one
session:

  * "~12.5 s per soccer league-week"  -- really 0.17 s. The gap was everything
    happening between two builds, not the build.
  * "the per-sport window will change nothing" -- it took seven minutes off.
  * a memory emergency, read off a page-cache-inclusive percentage while
    anonymous memory sat at 28-43% with zero OOM kills in two days.

A gap measures ELAPSED WALL TIME ON A SHARED WORKER. Measured on `-427jr`
2026-08-26, the 9m34s "candidate pool" window contained per-sport
`live_lens_tick_*` cycles, NFL `board_contract_*` cycles, `artifact_publisher`
pull traffic and a ~350 MB `refresh_odds_sources.py` CHILD PROCESS -- while the
board's own identifiable work was ~55 s of MLB card contexts plus soccer
contexts now 89.5% memoised.

WALL MINUS CPU SEPARATES THE TWO. `time.process_time()` counts CPU for THIS
process only, so a child process burning a core does not appear in it -- which
is precisely what makes the gap readable as contention.
"""

from __future__ import annotations

import io
import os
import sys
import time
import unittest
from unittest.mock import patch
import contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import intelligence_state as state


def _run(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = state._timed_candidate_pool(fn, *args)
    return result, buf.getvalue()


def _field(line: str, key: str) -> str:
    for part in line.split():
        if part.startswith(key + "="):
            return part.split("=", 1)[1]
    raise AssertionError(f"{key} not in {line!r}")


class _ScriptedClock:
    """`time` for ONE module, with `monotonic`/`process_time` handed to it.

    WHY THESE TWO TESTS CANNOT USE THE REAL CLOCKS. `_timed_candidate_pool`
    reads `time.process_time()`, which is CPU for the whole PROCESS -- every
    thread in it. That is the right choice for the instrument (its docstring
    says so: a child process burning a core must not appear, which is what
    makes the wall/CPU gap readable as contention). It is the wrong thing for a
    test to assert against, because a pytest worker's process is not the test's
    to control.

    MEASURED 2026-09-06, and TWO leaked CPU-burning threads are enough:

        leaked threads   sleeping cpu_s   sleeping off_cpu_pct
              0               0.00              100.0
              2               0.30                5.2
              8               0.60               18.4

    At 2 threads `assertLess(cpu, 0.1)` and `assertGreater(off, 80.0)` both
    fail. This suite leaks daemon threads by design of its fixtures
    (`syndicate-venue-poll`, `memory-watchdog`, the live-lens reporter), and at
    full-suite scale an xdist worker has accumulated many -- which is why these
    passed alone, passed across 192 files, and failed only in the full run.

    An EARLIER attempt to reproduce this with multiprocessing burners could
    never have worked: `process_time` does not count other PROCESSES. Threads,
    not processes, and that distinction is the whole defect.

    Scripting the clocks tests strictly more than the real ones did -- the
    exact reported arithmetic, not a threshold that happened to hold on an idle
    box. Patched onto the module's own name, never onto the `time` singleton.
    """

    def __init__(self, wall_deltas, cpu_deltas):
        self._wall = list(wall_deltas)
        self._cpu = list(cpu_deltas)

    def monotonic(self):
        return self._wall.pop(0)

    def process_time(self):
        return self._cpu.pop(0)

    def __getattr__(self, name):
        return getattr(time, name)


def _run_with_clock(fn, wall_deltas, cpu_deltas):
    with patch.object(state, "time", _ScriptedClock(wall_deltas, cpu_deltas)):
        return _run(fn)


class BoardBuildTimingTests(unittest.TestCase):
    def test_it_returns_the_builds_value_unchanged(self):
        # A timer that alters the board is worse than no timer.
        sentinel = {"candidate_count": 7, "deep": {"x": [1, 2]}}
        result, _out = _run(lambda a, b: sentinel, "2026-08-25", "fp")
        self.assertIs(result, sentinel)

    def test_it_passes_arguments_through(self):
        seen = {}

        def build(date, fingerprint):
            seen["args"] = (date, fingerprint)
            return {}

        _run(build, "2026-08-25", "fp123")
        self.assertEqual(seen["args"], ("2026-08-25", "fp123"))

    def test_a_sleeping_build_reads_as_WAITING(self):
        # THE LOAD-BEARING CASE. Blocked on IO or queued behind another loop:
        # wall accrues, CPU does not. This is the shape the 9m34s window is
        # suspected of, and the one no existing log line can distinguish.
        #
        # Clocks are SCRIPTED -- see `_ScriptedClock`. With the real ones this
        # asserted a property of the pytest worker's process, and failed in the
        # full suite once leaked daemon threads burned CPU during the sleep.
        _result, out = _run_with_clock(
            lambda: {}, wall_deltas=[100.0, 100.25], cpu_deltas=[10.0, 10.001]
        )
        line = [l for l in out.splitlines() if "BOARD_BUILD_TIMING" in l][0]
        wall = float(_field(line, "wall_s"))
        cpu = float(_field(line, "cpu_s"))
        off = float(_field(line, "off_cpu_pct"))
        self.assertGreaterEqual(wall, 0.2)
        self.assertLess(cpu, 0.1, "a sleeping build must not accrue CPU")
        self.assertGreater(off, 80.0, "off_cpu_pct must show this as waiting")

    def test_a_busy_build_reads_as_COMPUTING(self):
        # The other half. Without this the test above would pass on a timer
        # that always reported "waiting".
        #
        # HISTORY, because this test has now been wrong TWICE in opposite
        # directions. It first asserted `off_cpu_pct < 40.0`, an absolute bound
        # that holds only when a core is free; in a full `-n auto` suite it read
        # 79.7 and the instrument was RIGHT. I replaced that with a comparison
        # against a SLEEPING build measured in the same process -- which was
        # sound only while a sleeping build reads ~100, and leaked CPU-burning
        # threads make it read 5.2. That second version failed at full-suite
        # scale for the same underlying reason as the first: both asserted
        # against a process the test does not control.
        #
        # Scripted clocks end it. The distinction this test exists for -- a
        # computing build must not read as a waiting one -- is now asserted on
        # the instrument's arithmetic, which is the only part that is actually
        # this code's responsibility.
        _result, out = _run_with_clock(
            lambda: {"total": 1}, wall_deltas=[100.0, 100.26], cpu_deltas=[10.0, 10.25]
        )
        line = [l for l in out.splitlines() if "BOARD_BUILD_TIMING" in l][0]
        cpu = float(_field(line, "cpu_s"))
        off = float(_field(line, "off_cpu_pct"))
        self.assertGreaterEqual(cpu, 0.2, "a busy build must accrue CPU")
        self.assertLess(off, 40.0, "off_cpu_pct must show this as computing")

    def test_the_real_clocks_are_still_wired_up(self):
        """`_ScriptedClock` proves the ARITHMETIC; this proves the WIRING.

        Without it, both tests above would keep passing if
        `_timed_candidate_pool` stopped reading the clocks entirely. No
        threshold and no timing assertion -- only that a real run emits the
        line with numbers that parse and a wall that advanced.
        """
        # 0.25 s, not 0.05: `wall_s` prints at ONE DECIMAL, so a 0.05 s sleep
        # renders as `0.0` whenever it lands a hair under the rounding
        # boundary, and this test would flake for a formatting reason.
        _result, out = _run(lambda: (time.sleep(0.25), {})[1])
        line = [l for l in out.splitlines() if "BOARD_BUILD_TIMING" in l][0]
        self.assertGreaterEqual(
            float(_field(line, "wall_s")), 0.2,
            "the real monotonic clock must be read -- a timer stuck at zero "
            "would satisfy every scripted-clock test above",
        )
        # CPU and the percentage are only required to PARSE here. Asserting a
        # bound on either is what made this file machine-dependent twice.
        self.assertGreaterEqual(float(_field(line, "cpu_s")), 0.0)
        float(_field(line, "off_cpu_pct"))

    def test_it_reports_even_when_the_build_RAISES(self):
        # A build that dies partway is exactly when the timing matters most,
        # and a plain `print` after the call would lose it.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(RuntimeError):
                state._timed_candidate_pool(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        out = buf.getvalue()
        self.assertIn("BOARD_BUILD_TIMING", out)
        self.assertIn("ok=False", out)

    def test_the_exception_is_not_swallowed(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                state._timed_candidate_pool(lambda: (_ for _ in ()).throw(ValueError("x")))

    def test_a_broken_clock_never_costs_the_build(self):
        # Telemetry must never be able to fail a board build. The first draft
        # read both clocks BEFORE the try, so a raising clock would have killed
        # the build to protect a log line -- the exact inversion the function's
        # own docstring forbids. The build must still return its value, and the
        # timing line is simply skipped.
        import unittest.mock as mock

        sentinel = {"ok": True}
        with mock.patch.object(state.time, "process_time", side_effect=RuntimeError("no clock")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = state._timed_candidate_pool(lambda: sentinel)
        self.assertIs(result, sentinel, "a broken clock must not cost the board")
        self.assertNotIn("BOARD_BUILD_TIMING", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
