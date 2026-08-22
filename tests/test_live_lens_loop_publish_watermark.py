"""The publish watermark was stamped at the cycle start, so every file went twice.

`_live_lens_background_loop` published files changed since `last_publish_epoch`
and then set that watermark to `started_epoch` -- the timestamp taken at the TOP
of the cycle, before its own tick had written anything. Every artifact the tick
writes has an mtime in `[cycle_start, publish_start]`, strictly greater than a
watermark of `cycle_start`, so the next cycle matched all of them again.

MEASURED on refresh-worker 2026-08-08 21:31-22:05Z (n=8 cycles, deploy-free):

    publish_changed_hot_artifacts   48-74s per cycle, 73-103 artifacts
    pull_hot_artifacts               8-27s per cycle, 33-103 artifacts
    median loop cycle               246s   (configured interval 60s)

~20-30% of the loop's wall clock, roughly half of it a resend, on the tick's own
thread ahead of every subsequent sport build.

There is deliberately NO threshold in this fix. A guessed publish interval is
exactly the kind of number this file's own history shows silently disabling the
stage it guards (the 1200MB WNBA headroom gate; a 900s staleness bound). The
watermark is either correct or it is not, and it was not.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch

from syndicate.features.shared import live_lens_loop


class _Sweep(NamedTuple):
    """Stand-in for HotArtifactSweepResult: the real one's `all_succeeded` is
    what lets a watermark-based caller refuse to advance past a window in which
    some file silently failed. `publish_hot_artifact` never raises, so
    "did not throw" was never the same claim."""

    published_count: int
    failed_paths: tuple

    @property
    def all_succeeded(self) -> bool:
        return not self.failed_paths


class _Run(NamedTuple):
    """What one driven loop observed.

    `publish_starts` exists because **the clock tick count per cycle is NOT
    fixed**, which an earlier version of this file assumed. The in-sweep memory
    sampler reads `time.time()` a variable number of times depending on how
    long the sweep takes, so a hardcoded tick table (`[1, 3, 6]`) is only
    correct when nothing else has warmed the module. Measured 2026-08-22:
    the same test yields `[1, 3, 6]` alone and `[1, 3, 7]` when
    `test_live_lens_loop_publish_instrumentation.py` runs first in the same
    process -- a second reproducibility defect underneath `#503`'s watermark
    one, and invisible until the first was fixed.

    Capturing the publish instant lets the tests assert the INVARIANT (each
    window is the PREVIOUS publish start) rather than a clock arithmetic that
    is only incidentally stable.
    """

    windows: list
    publish_starts: list


def _run_cycles(count: int, *, publish_side_effect=None):
    """Drive the real background loop for `count` cycles and return the
    `since_epoch` argument each publish call received.

    `time.time` is replaced by a monotonic counter so that the cycle start and
    the publish start get DISTINCT values. Under a real clock a mocked loop
    completes in microseconds and the two are indistinguishable -- which is
    precisely the difference this bug lived in, so the test has to be able to
    see it.
    """
    windows: list[float] = []
    publish_starts: list[float] = []
    clock = {"t": 0.0}

    def _tick_clock() -> float:
        clock["t"] += 1.0
        return clock["t"]

    def _publish(since_epoch):
        windows.append(since_epoch)
        # The clock value AS OF this publish. The loop reads `time.time()`
        # immediately before calling, so this is the publish start -- captured
        # rather than derived from a tick table, for the reason in `_Run`.
        publish_starts.append(clock["t"])
        if publish_side_effect is not None:
            result = publish_side_effect()
            if result is not None:
                return result
        return _Sweep(1, ())

    remaining = {"n": count}

    def stop_after_n(_seconds: float) -> bool:
        remaining["n"] -= 1
        if remaining["n"] <= 0:
            live_lens_loop._LIVE_LENS_LOOP_STOP.set()
        return True

    with patch.object(live_lens_loop.time, "time", side_effect=_tick_clock), patch.object(
        live_lens_loop, "_live_lens_pull_enabled", return_value=False
    ), patch.object(
        live_lens_loop, "_run_live_lens_tick", return_value={"ok": True, "results": {}}
    ), patch.object(live_lens_loop, "_live_lens_publish_enabled", return_value=True), patch.object(
        live_lens_loop, "sweep_changed_hot_artifacts", side_effect=_publish
    ), patch.object(live_lens_loop, "write_json_file"), patch.object(
        live_lens_loop, "_live_lens_loop_interval_seconds", return_value=60
    ):
        live_lens_loop._LIVE_LENS_LOOP_STOP.clear()
        with patch.object(live_lens_loop._LIVE_LENS_LOOP_STOP, "wait", side_effect=stop_after_n):
            live_lens_loop._live_lens_background_loop()
    return _Run(windows, publish_starts)


class _IsolatedWatermarkTestCase(unittest.TestCase):
    """`#503`. Every test here runs against an ISOLATED watermark file.

    **WHY THIS EXISTS, because the failure was invisible and self-inflicted.**
    These tests drove the real loop, which persists its watermark through
    `_record_live_lens_publish_watermark` -> the REAL
    `reports/refresh_status/latest/live_lens_publish_watermark.json` in the
    working tree. The next run then READ it back, and
    `test_the_watermark_is_stamped_at_the_publish_not_the_cycle_start` failed
    with the first window equal to whatever epoch the previous run had left
    behind. Measured 2026-08-22 over two consecutive single-test runs:

        run 1 -> passed, and wrote {"epoch": 9.0}
        run 2 -> AssertionError: [9.0, 3.0, 6.0] != [1.0, 3.0, 6.0]

    Cycles 2 and 3 stayed correct in both, which is what made it read as a
    logic bug. **It passed on a clean checkout and failed on any machine that
    had run it before**, so CI was green throughout and the failure attached
    itself to whatever change a session happened to be making.

    **THE PATCH THAT LOOKED LIKE ISOLATION AND WAS NOT.** `_run_cycles` patches
    `live_lens_loop.write_json_file`, which is a real module-level binding
    (`live_lens_loop.py:37`) and does intercept the loop's three other write
    sites. But `_record_live_lens_publish_watermark` (`:229`) re-imports the
    same name INSIDE the function, so that one call escapes the patch. Three of
    four writes captured is exactly the shape that reads as "isolated" and is
    not -- and this file has been bitten by the same shadowing before: the
    aliased import at `:621` carries a comment calling it "load-bearing rather
    than style" after an UnboundLocalError.

    So the isolation is applied at `_live_lens_publish_watermark_path` instead.
    Both the read (`_live_lens_publish_since_epoch`) and the write go through
    it, so redirecting it is immune to which import binding wins -- where
    patching either `write_json_file` name would have to be right about that.
    The sibling `test_live_lens_publish_watermark.py` patches
    `refresh_state_store.read_json_file` at the SOURCE module for the same
    reason; this is the same lesson applied to a call that both reads and
    writes.
    """

    def setUp(self) -> None:
        # Captured BEFORE the patch, so the guard test below can assert against
        # the genuine location rather than against its own redirect.
        self._real_watermark_path = live_lens_loop._live_lens_publish_watermark_path()
        self._real_watermark_before = self._real_watermark_state()

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.isolated_watermark_path = Path(self._tmp.name) / "live_lens_publish_watermark.json"

        patcher = patch.object(
            live_lens_loop,
            "_live_lens_publish_watermark_path",
            return_value=self.isolated_watermark_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        live_lens_loop._LIVE_LENS_LOOP_STOP.set()

    def _real_watermark_state(self) -> str | None:
        """Content of the REAL watermark, or None when absent. Content rather
        than a mtime: an mtime can collide inside one fast test run."""
        try:
            return self._real_watermark_path.read_text(encoding="utf-8")
        except OSError:
            return None


class PublishWatermarkTests(_IsolatedWatermarkTestCase):
    def test_the_loop_does_not_write_its_watermark_into_the_repo_tree(self) -> None:
        """`#503`'s regression guard: the property that makes the suite
        reproducible, asserted directly rather than inferred from the other
        tests happening to pass twice.

        **CHECKS CONTENT, NOT EXISTENCE, and the difference is not academic.**
        The first version of this guard compared `path.exists()` before and
        after -- and PASSED while the real file was still being rewritten,
        because an earlier test in the same run had already created it, so both
        readings were True. The un-isolated `SilentFailureTests` below was the
        writer, and this guard's own weakness is what hid it.
        """
        _run_cycles(3)
        self.assertEqual(
            self._real_watermark_state(),
            self._real_watermark_before,
            f"the loop touched {self._real_watermark_path} -- the next run of this "
            f"suite will read it back and fail",
        )

    def test_the_watermark_is_still_actually_persisted_just_somewhere_isolated(self) -> None:
        """**The check that stops this 'fix' from being a disabled write.**

        Redirecting the path would also 'fix' the flake if it silently stopped
        the watermark being written at all -- and then these tests would pass
        while asserting nothing about persistence, which is the failure mode
        `learnings.md` calls shipping a verification you have not falsified.
        The write must still happen, and land at the isolated path.
        """
        windows = _run_cycles(3).windows
        self.assertTrue(
            self.isolated_watermark_path.exists(),
            "the watermark was never written -- isolation disabled the behaviour under test",
        )
        payload = json.loads(self.isolated_watermark_path.read_text(encoding="utf-8"))

        # THE INVARIANT, NOT A CLOCK VALUE. An earlier draft asserted `== 9.0`
        # from the tick table below and was itself flaky: the number of
        # `time.time()` calls per cycle is NOT fixed, because the in-sweep
        # memory sampler reads the clock a variable number of times depending
        # on how long the sweep takes. Observed 9.0 and 11.0 on consecutive
        # runs of this same test.
        #
        # Pinning a guessed constant to fix a flake would have replaced one
        # non-reproducible assertion with another -- which is what `#503` is
        # about, so getting it wrong here in the same file would be its own
        # punchline. What must hold is that the watermark is at or after the
        # last publish this run started, and never before it.
        self.assertIsNotNone(payload.get("epoch"))
        self.assertGreaterEqual(
            float(payload["epoch"]),
            max(windows),
            "the recorded watermark predates the last publish this run started",
        )

    def test_the_watermark_is_stamped_at_the_publish_not_the_cycle_start(self) -> None:
        """The whole bug in one assertion.

        **EACH WINDOW MUST BE THE PREVIOUS CYCLE'S PUBLISH START.** The old
        code stored `started_epoch` -- the timestamp taken at the TOP of the
        cycle, before its own tick had written anything -- so every artifact
        the tick wrote had an mtime strictly greater than the watermark and was
        re-sent on the next cycle.

        **THIS USED TO ASSERT `== [1.0, 3.0, 6.0]` AND THAT WAS A SECOND
        REPRODUCIBILITY BUG** (`#503`). The list came from a tick table that
        assumed exactly three `time.time()` reads per cycle; the in-sweep
        memory sampler reads the clock a variable number of times, so the same
        test yields `[1, 3, 6]` alone and `[1, 3, 7]` when
        `test_live_lens_loop_publish_instrumentation.py` runs first in the same
        process. The property was never about those numbers.

        Comparing observed windows against observed publish instants asserts
        the same thing strictly MORE tightly -- it would still catch the
        cycle-start bug, which shifts every window one clock read earlier --
        while being immune to how many times anything else reads the clock.
        """
        run = _run_cycles(3)

        self.assertEqual(
            run.windows[1:],
            run.publish_starts[:-1],
            "each window must be the PREVIOUS publish start; using the cycle "
            "start is the bug this test exists for",
        )
        # And the first window is the cold-start floor, not a publish: nothing
        # had been published yet, so it must precede the first publish rather
        # than coincide with it.
        self.assertLess(run.windows[0], run.publish_starts[0])

    def test_a_failed_publish_does_not_advance_past_the_unsent_files(self) -> None:
        """An exception means an unknown subset was sent. Advancing past a
        failed window drops those files permanently -- pull_hot_artifacts
        already applies this reasoning to its own persisted watermark, and this
        call site did not."""

        calls = {"n": 0}

        def _boom():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("publish failed")

        windows = _run_cycles(2, publish_side_effect=_boom).windows

        self.assertEqual(len(windows), 2)
        self.assertEqual(
            windows[0], windows[1], "a failed sweep must retry its window, not skip it"
        )

    def test_the_published_line_reports_the_window_it_covered(self) -> None:
        """A bare count cannot distinguish "103 files changed" from "103 files
        resent". The window and elapsed seconds are what make the next
        measurement attributable without another code read."""
        import inspect

        source = inspect.getsource(live_lens_loop._live_lens_background_loop)
        self.assertIn("window_seconds=", source)
        self.assertIn("elapsed_seconds=", source)


if __name__ == "__main__":
    unittest.main()


class SilentFailureTests(_IsolatedWatermarkTestCase):
    """`publish_hot_artifact` NEVER RAISES -- a network blip or an unreachable
    web service returns False and is logged. So "the call did not throw" was
    never the same claim as "every file went through", and the watermark fix
    above still advanced past silently-failed files.

    `HotArtifactSweepResult.all_succeeded` exists for exactly this and its own
    docstring names the failure: *"a caller that advances a persisted watermark
    on any non-raising return would permanently skip a file that failed for a
    transient reason"*. This call site was that caller.
    """

    def tearDown(self) -> None:
        live_lens_loop._LIVE_LENS_LOOP_STOP.set()

    def test_a_silently_failed_file_holds_the_watermark(self) -> None:
        calls = {"n": 0}

        def _one_failure():
            calls["n"] += 1
            if calls["n"] == 1:
                # Published some, failed one, returned normally. No exception.
                return _Sweep(5, (object(),))
            return None

        windows = _run_cycles(3, publish_side_effect=_one_failure).windows

        self.assertEqual(
            windows[0], windows[1],
            "a sweep with failed paths must retry its window, not skip past the failures",
        )
        self.assertNotEqual(
            windows[1], windows[2],
            "...and must resume advancing once a later sweep is clean",
        )

    def test_the_failure_count_is_reported_not_just_the_published_count(self) -> None:
        """A published count alone cannot distinguish a clean sweep from one
        that dropped files -- the same class of ambiguity as "103 changed" vs
        "103 resent", which is what let the watermark bug live four months."""
        import inspect

        source = inspect.getsource(live_lens_loop._live_lens_background_loop)
        self.assertIn("failed=", source)
        self.assertIn("all_succeeded", source)
