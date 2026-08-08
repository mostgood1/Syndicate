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

import unittest
from unittest.mock import patch

from syndicate.features.shared import live_lens_loop


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
    clock = {"t": 0.0}

    def _tick_clock() -> float:
        clock["t"] += 1.0
        return clock["t"]

    def _publish(since_epoch):
        windows.append(since_epoch)
        if publish_side_effect is not None:
            publish_side_effect()
        return 1

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
        live_lens_loop, "publish_changed_hot_artifacts", side_effect=_publish
    ), patch.object(live_lens_loop, "write_json_file"), patch.object(
        live_lens_loop, "_live_lens_loop_interval_seconds", return_value=60
    ):
        live_lens_loop._LIVE_LENS_LOOP_STOP.clear()
        with patch.object(live_lens_loop._LIVE_LENS_LOOP_STOP, "wait", side_effect=stop_after_n):
            live_lens_loop._live_lens_background_loop()
    return windows


class PublishWatermarkTests(unittest.TestCase):
    def tearDown(self) -> None:
        live_lens_loop._LIVE_LENS_LOOP_STOP.set()

    def test_the_watermark_is_stamped_at_the_publish_not_the_cycle_start(self) -> None:
        """The whole bug in one assertion.

        Clock ticks 1 per call. Per cycle the loop reads it at the cycle start,
        then again just before publishing, then once more for the elapsed line:

            init            t=1
            cycle 1  start=2   publish_start=3   (elapsed read t=4)
            cycle 2  start=5   publish_start=6   (elapsed read t=7)
            cycle 3  start=8   publish_start=9

        So the windows must be [1, 3, 6] -- each one the PREVIOUS PUBLISH.
        The old code stored `started_epoch` and produced [1, 2, 5], reaching
        back before its own tick had written anything and re-sending all of it.
        """
        windows = _run_cycles(3)

        self.assertEqual(
            windows,
            [1.0, 3.0, 6.0],
            "watermark must be the previous publish start; [1, 2, 5] is the cycle-start bug",
        )

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

        windows = _run_cycles(2, publish_side_effect=_boom)

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
