"""#327: the live-lens loop's two uninstrumented gaps are now sampled.

WHAT THIS PROTECTS. `#327` chased an in-process 493-878MB excursion that showed
up under `post_mlb_sim_tick` -- a stage proven to be a BYSTANDER, since all five
of its sub-features report `launched=false` at every peak. Four causes were
eliminated (child process, intelligence thread, large artifact read, book-grid
tick), leaving an allocator in an uninstrumented gap. This loop had two:

    pull_hot_artifacts       at cycle start
    sweep_changed_hot_artifacts  after the last per-sport sample, 48-74s per
                                 cycle across 73-103 artifacts, each read into
                                 memory to be POSTed

Both now emit before/after samples.

The two assertions that matter are NOT "a sample was emitted":

  1. `append_to_ring=False` on every one. The ring is a time series whose
     coverage shrinks with sample rate; the excursions arrive 11-42 minutes
     apart. Adding ~4 samples/cycle to the ring would buy instrumentation by
     spending the window the instrument exists to observe.

  2. `cycle_date` is a real local. The per-sport sites take `date_str` from
     `_run_live_lens_tick`'s scope; this loop has no such binding. Referencing
     that name here raises NameError -- and the first sample sits OUTSIDE the
     pull's try/except, so it would have killed the loop thread rather than
     losing a sample. That bug was written and caught before shipping; this is
     what stops it coming back.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.shared import live_lens_loop


class _Sweep:
    def __init__(self, published_count: int, failed_paths: tuple = ()) -> None:
        self.published_count = published_count
        self.failed_paths = failed_paths
        self.all_succeeded = not failed_paths


def _run_one_cycle(*, publish_raises: bool = False, pull_enabled: bool = True):
    """Drive exactly one loop iteration, capturing every memory sample."""
    samples: list[tuple[str, dict]] = []

    def _record(stage, **kwargs):
        samples.append((stage, kwargs))
        return {"stage": stage}

    def _sweep(_since):
        if publish_raises:
            raise RuntimeError("publish exploded")
        return _Sweep(7, ())

    def stop_after_one(_seconds: float) -> bool:
        live_lens_loop._LIVE_LENS_LOOP_STOP.set()
        return True

    with patch.object(live_lens_loop, "log_and_persist_process_memory", side_effect=_record), patch.object(
        live_lens_loop, "_live_lens_pull_enabled", return_value=pull_enabled
    ), patch.object(live_lens_loop, "pull_hot_artifacts", return_value=3), patch.object(
        live_lens_loop, "_run_live_lens_tick", return_value={"ok": True, "results": {}}
    ), patch.object(live_lens_loop, "_live_lens_publish_enabled", return_value=True), patch.object(
        live_lens_loop, "sweep_changed_hot_artifacts", side_effect=_sweep
    ), patch.object(live_lens_loop, "write_json_file"), patch.object(
        live_lens_loop, "_live_lens_loop_interval_seconds", return_value=60
    ):
        live_lens_loop._LIVE_LENS_LOOP_STOP.clear()
        with patch.object(live_lens_loop._LIVE_LENS_LOOP_STOP, "wait", side_effect=stop_after_one):
            live_lens_loop._live_lens_background_loop()
    return samples


class PublishSweepInstrumentationTests(unittest.TestCase):
    def tearDown(self) -> None:
        live_lens_loop._LIVE_LENS_LOOP_STOP.set()

    def test_both_uninstrumented_gaps_are_now_sampled(self) -> None:
        stages = [stage for stage, _ in _run_one_cycle()]
        for expected in (
            "live_lens_pull_before",
            "live_lens_pull_after",
            "live_lens_publish_before",
            "live_lens_publish_after",
        ):
            self.assertIn(expected, stages, f"{expected} not emitted")

    def test_every_sample_keeps_out_of_the_ring(self) -> None:
        """The constraint that makes this instrumentation affordable.

        Not a style preference: at ~4 samples/cycle these would rotate a
        300-record ring below the 11-42 minute gap between the excursions #327
        is hunting. High-water still records, so the stages stay visible from
        web without the time series paying for them.
        """
        for stage, kwargs in _run_one_cycle():
            self.assertIs(
                kwargs.get("append_to_ring"),
                False,
                f"{stage} would append to the ring and shrink its window",
            )

    def test_the_loop_survives_because_cycle_date_is_a_real_local(self) -> None:
        """Regression test for a NameError that would have killed the thread.

        `date_str` is bound inside `_run_live_lens_tick`, NOT in the loop. The
        first sample is emitted before the pull's try/except, so referencing an
        undefined name there takes the whole live-lens loop down rather than
        losing one sample. If this fails, every sample carries `date=None` or
        the loop raises.
        """
        samples = _run_one_cycle()
        self.assertTrue(samples, "no samples emitted -- the loop did not complete a cycle")
        for stage, kwargs in samples:
            self.assertIsNotNone(kwargs.get("date"), f"{stage} emitted without a resolved date")

    def test_publish_sample_carries_the_sweep_counts(self) -> None:
        """A peak means something different at 5 artifacts than at 103.

        Carrying the counts on the sample itself means one line answers "how
        much memory, across how many artifacts" instead of correlating two log
        streams by timestamp.
        """
        after = next(kw for stage, kw in _run_one_cycle() if stage == "live_lens_publish_after")
        self.assertEqual(after.get("published_count"), 7)
        self.assertEqual(after.get("failed_count"), 0)
        self.assertIsNotNone(after.get("elapsed_seconds"))

    def test_a_sweep_that_raises_is_still_measured(self) -> None:
        """A publish that blew up partway has still allocated.

        The after-sample sits outside the try, so the failure mode most likely
        to leave memory behind is exactly the one that must not go unmeasured.
        Counts stay None -- absent rather than falsely zero, so nobody reads a
        crashed sweep as one that published nothing.
        """
        samples = _run_one_cycle(publish_raises=True)
        stages = [stage for stage, _ in samples]
        self.assertIn("live_lens_publish_after", stages)
        after = next(kw for stage, kw in samples if stage == "live_lens_publish_after")
        self.assertIsNone(after.get("published_count"))

    def test_pull_samples_are_skipped_when_the_pull_is_disabled(self) -> None:
        """Instrumentation must not report on a stage that did not run.

        A `live_lens_pull_after` at baseline when pulling is off would read as
        "the pull is cheap" rather than "the pull never happened".
        """
        stages = [stage for stage, _ in _run_one_cycle(pull_enabled=False)]
        self.assertNotIn("live_lens_pull_before", stages)
        self.assertNotIn("live_lens_pull_after", stages)
        self.assertIn("live_lens_publish_after", stages)


if __name__ == "__main__":
    unittest.main()
