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
        _result, out = _run(lambda: (time.sleep(0.25), {})[1])
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
        # THE ABSOLUTE THRESHOLD HERE WAS A CLAIM ABOUT THE MACHINE, not about
        # the instrument. It asserted `off_cpu_pct < 40.0`, which holds only
        # when a core is free. Measured 2026-09-06 in a full `-n auto` suite:
        # 79.7 -- and the instrument was RIGHT. A build burning 0.25 s of CPU
        # that waits 1 s to be scheduled genuinely did spend ~80% of its wall
        # time off-CPU, and a timer that reported otherwise would be lying.
        #
        # So this now asserts the two things that do not depend on scheduling
        # luck: the reported percentage matches its own inputs, and a busy
        # build still reads as MORE on-CPU than a sleeping one measured under
        # the same conditions. The second is what the comment above is really
        # asking for -- a timer stuck on "waiting" fails it at any load.
        def burn():
            end = time.process_time() + 0.25
            total = 0
            while time.process_time() < end:
                total += sum(range(500))
            return {"total": total}

        _result, out = _run(burn)
        line = [l for l in out.splitlines() if "BOARD_BUILD_TIMING" in l][0]
        cpu = float(_field(line, "cpu_s"))
        off = float(_field(line, "off_cpu_pct"))
        self.assertGreaterEqual(cpu, 0.2, "a busy build must accrue CPU")

        # NOT asserting `off == (wall - cpu) / wall` from this line: the line
        # prints `wall_s` and `cpu_s` at ONE DECIMAL (`:.1f`) while
        # `off_cpu_pct` is computed from the unrounded values
        # (`intelligence_state.py:3992`), so the identity is not recoverable
        # from what is logged -- 20.1 reported against 33.3 recomputed from the
        # rounded pair. Worth knowing before anyone tries to audit a build from
        # its log line alone.
        #
        # The comparison the original threshold was standing in for, taken in
        # the same process so both readings see the same contention.
        _sleep_result, sleep_out = _run(lambda: (time.sleep(0.25), {})[1])
        sleep_line = [l for l in sleep_out.splitlines() if "BOARD_BUILD_TIMING" in l][0]
        sleep_off = float(_field(sleep_line, "off_cpu_pct"))
        self.assertLess(
            off, sleep_off,
            "a busy build must read as more on-CPU than a sleeping one; "
            f"busy={off} sleeping={sleep_off}",
        )

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
