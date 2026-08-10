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

import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import live_lens_loop


class _Sweep:
    def __init__(self, published_count: int, failed_paths: tuple = ()) -> None:
        self.published_count = published_count
        self.failed_paths = failed_paths
        self.all_succeeded = not failed_paths


def _run_one_cycle(*, publish_raises: bool = False, pull_enabled: bool = True, in_sweep_mb=None):
    """Drive exactly one loop iteration, capturing every memory sample.

    `in_sweep_mb` is the sequence of cgroup readings the in-sweep sampler will
    see, one per published artifact -- how a mid-sweep transient is simulated.
    """
    samples: list[tuple[str, dict]] = []
    readings = list(in_sweep_mb or [])

    def _record(stage, **kwargs):
        samples.append((stage, kwargs))
        return {"stage": stage}

    def _sweep(_since):
        # ONE positional arg, exactly like the real signature and like the
        # doubles in test_live_lens_loop_publish_watermark. The sampler runs on
        # its own thread, so the sweep is not asked to cooperate at all.
        if publish_raises:
            raise RuntimeError("publish exploded")
        # Give the sampler thread time to take its readings while "publishing".
        deadline = time.time() + 1.5
        while readings and time.time() < deadline:
            time.sleep(0.02)
        return _Sweep(len(readings) or 7, ())

    def stop_after_one(_seconds: float) -> bool:
        live_lens_loop._LIVE_LENS_LOOP_STOP.set()
        return True

    # The sampler polls on a timer; hand it the sequence and then hold the
    # last value so a slow thread cannot run off the end.
    cgroup = list(readings)
    cursor = {"i": 0}

    def _next_reading():
        if not cgroup:
            return None
        value = cgroup[min(cursor["i"], len(cgroup) - 1)]
        cursor["i"] += 1
        return value

    with patch.object(live_lens_loop, "_PUBLISH_SAMPLER_INTERVAL_SECONDS", 0.01), patch.object(
        live_lens_loop, "log_and_persist_process_memory", side_effect=_record
    ), patch.object(
        live_lens_loop, "container_memory_current_mb", side_effect=_next_reading
    ), patch.object(
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


class InSweepSamplingTests(unittest.TestCase):
    """`#327`: the endpoints are blind to a transient INSIDE the sweep.

    Measured in production 2026-08-10 and the reason the fifth elimination was
    retracted: a 94-artifact 53.6s sweep whose before/after read +152MB while a
    mid-sweep sample caught +970MB and container 3459.1MB, 84% of the cap. The
    peak was allocated and released BETWEEN the endpoints, so no amount of
    before/after precision could ever have seen it.
    """

    def tearDown(self) -> None:
        live_lens_loop._LIVE_LENS_LOOP_STOP.set()

    def test_a_midsweep_spike_invisible_to_the_endpoints_is_captured(self) -> None:
        """The exact production shape: low, low, SPIKE, low, low.

        A before/after pair sees the two lows and reports nothing. The in-sweep
        sampler must report the spike and where it happened.
        """
        readings = [1080.0, 1090.0, 3459.1, 1200.0, 1233.0]
        after = next(
            kw for stage, kw in _run_one_cycle(in_sweep_mb=readings)
            if stage == "live_lens_publish_after"
        )
        self.assertEqual(after.get("peak_container_mb_in_sweep"), 3459.1)
        self.assertGreater(after.get("peak_sample_count") or 0, 0, "sampler must have run")

    def test_the_peak_is_the_max_not_the_last_reading(self) -> None:
        """A running max, not a final sample.

        Taking the last reading would reproduce the exact bug being fixed --
        the transient is gone by the end, which is why the endpoints missed it.
        """
        after = next(
            kw for stage, kw in _run_one_cycle(in_sweep_mb=[900.0, 2500.0, 950.0])
            if stage == "live_lens_publish_after"
        )
        self.assertEqual(after.get("peak_container_mb_in_sweep"), 2500.0)

    def test_an_unreadable_cgroup_leaves_the_peak_absent_not_zero(self) -> None:
        """Off-container (no /sys/fs/cgroup) the reader returns None.

        Recording 0.0 would say "the sweep peaked at nothing", which is a
        measurement. None says "not measured". Those must not render the same.
        """
        after = next(
            kw for stage, kw in _run_one_cycle(in_sweep_mb=[])
            if stage == "live_lens_publish_after"
        )
        self.assertIsNone(after.get("peak_container_mb_in_sweep"))

    def test_the_sweep_signature_is_untouched(self) -> None:
        """The sampler must NOT require cooperation from the sweep.

        An earlier version threaded an `on_artifact` callback through
        `sweep_changed_hot_artifacts`. That broke three tests in
        test_live_lens_loop_publish_watermark whose `_publish(since)` double
        takes one positional argument -- the SECOND time this change disturbed
        that file. A test double is a signature contract. Sampling from a
        thread needs no such change, so this pins the signature to one
        parameter and stops the callback design coming back.
        """
        import inspect

        # Inspected through the reference live_lens_loop already holds, rather
        # than importing artifact_publisher here: a fresh import of that module
        # inside the test session pulls in the publish app config and leaves
        # ADMIN_TOKEN in os.environ, which turns a later
        # test_artifact_publisher expectation of 503 into 401.
        signature = inspect.signature(live_lens_loop.sweep_changed_hot_artifacts)
        self.assertEqual(
            list(signature.parameters), ["since_epoch_seconds"],
            "sweep_changed_hot_artifacts gained a parameter -- existing test doubles will break",
        )


if __name__ == "__main__":
    unittest.main()
