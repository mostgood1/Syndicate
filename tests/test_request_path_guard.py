from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from syndicate.features.bankroll_manager import compute_bet_size
from syndicate.features.wnba.live_lens import build_live_lens_page_context
from syndicate.features.shared.request_path_guard import ComputeInRequestPathError
from syndicate.features.shared.request_path_guard import _HOSTED_FLAGS
from syndicate.features.shared.request_path_guard import _HOSTED_MARKERS
from syndicate.features.shared.request_path_guard import hosted_signal
from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path

_ALL_HOSTED_KEYS = tuple(_HOSTED_FLAGS) + tuple(_HOSTED_MARKERS)


class RequestPathGuardTests(unittest.TestCase):
    def test_live_lens_page_context_logs_warning_in_request_context(self) -> None:
        app = Flask(__name__)
        with app.test_request_context("/wnba/live-lens?date=2026-06-19", method="GET"):
            # has_games_for_date() falls through to a real ESPN scoreboard
            # fetch (and its own warn_if_compute_in_request_path call) for
            # any date not already confirmed via the local artifact mirror --
            # 2026-06-19 ages out of that mirror's rolling window over time,
            # which would otherwise make this test's warning count depend on
            # how recently data/wnba_source was refreshed. Stub the schedule
            # check so this test only measures the one warning it's actually
            # about: build_live_lens_page_context's own guard call.
            with patch("syndicate.features.wnba.cards.has_games_for_date", return_value=True), patch(
                "syndicate.features.shared.request_path_guard.logger.warning"
            ) as mocked_warning:
                build_live_lens_page_context("2026-06-19")

        mocked_warning.assert_called_once_with(
            "WARNING: compute in request path (operation=%s)",
            "build_live_lens_page_context",
            extra={"operation": "build_live_lens_page_context"},
        )

    def test_compute_function_logs_warning_in_request_context(self) -> None:
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with patch("syndicate.features.shared.request_path_guard.logger.warning") as mocked_warning:
                result = compute_bet_size({"model_probability": 0.55, "implied_probability": 0.5, "odds": -110})

        mocked_warning.assert_called_once_with(
            "WARNING: compute in request path (operation=%s)",
            "compute_bet_size",
            extra={"operation": "compute_bet_size"},
        )
        self.assertIn("recommended_bet_size", result)

    def test_refuse_raises_in_request_context_on_hosted_deployment(self) -> None:
        # #56/#98/#109: this is the hard structural gate -- unlike the
        # warn-only helper above, a hosted (Render) deployment must never
        # merely log and proceed. #98's OOM (ops.py's admin-gated
        # candidate-trace debug endpoint calling _build_candidate_pool
        # directly) and #109's memory spike (the query API's force_refresh
        # cache-miss fallback calling _compute_response directly) were both
        # exactly this: heavy compute reached from a live web request on
        # production. No exemption for the debug endpoint either -- #98's
        # incident is exactly why not.
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
                with self.assertRaises(ComputeInRequestPathError):
                    refuse_if_compute_in_request_path("some_heavy_operation")

    def test_refuse_only_warns_in_request_context_when_not_hosted(self) -> None:
        # Local dev (no separate refresh-worker process) must keep working --
        # only a real hosted deployment enforces the hard gate.
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with patch.dict(os.environ, {}, clear=False):
                for key in _ALL_HOSTED_KEYS:
                    os.environ.pop(key, None)
                with patch("syndicate.features.shared.request_path_guard.logger.warning") as mocked_warning:
                    refuse_if_compute_in_request_path("some_heavy_operation")
        mocked_warning.assert_called_once_with(
            "WARNING: compute in request path (operation=%s)",
            "some_heavy_operation",
            extra={"operation": "some_heavy_operation"},
        )

    def test_refuse_is_a_no_op_outside_any_request_context(self) -> None:
        # refresh-worker is a plain script with no Flask app, so this must
        # never fire for its background loop regardless of hosted status --
        # has_request_context() is always False there.
        with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            refuse_if_compute_in_request_path("some_heavy_operation")  # must not raise

    def test_build_candidate_pool_refuses_on_hosted_web_request(self) -> None:
        # Integration-level: the actual entry point #98's incident went
        # through, not just the guard helper in isolation.
        from pipeline.intelligence_state import IntelligenceStateService

        service = IntelligenceStateService()
        app = Flask(__name__)
        with app.test_request_context("/api/ops/intelligence/candidate-trace", method="GET"):
            with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
                with self.assertRaises(ComputeInRequestPathError):
                    service._build_candidate_pool("2026-07-27", "fingerprint-1")

    def test_compute_response_refuses_on_hosted_web_request(self) -> None:
        # Integration-level: the actual entry point #109's incident went
        # through, not just the guard helper in isolation.
        from pipeline.intelligence_state import IntelligenceStateService

        service = IntelligenceStateService()
        app = Flask(__name__)
        with app.test_request_context("/api/intelligence/query", method="POST"):
            # RENDER=true alone also flips refresh_state_store's own strict
            # hosted-storage check, which requires SYNDICATE_DATA_ROOT to be
            # set before it will even read a manifest for fingerprinting --
            # unrelated to this guard, but has to be satisfied to reach it.
            with patch.dict(os.environ, {"RENDER": "true", "SYNDICATE_DATA_ROOT": str(Path(__file__).resolve().parent.parent / "data")}, clear=False):
                with self.assertRaises(ComputeInRequestPathError):
                    service._compute_response({"question": "top edges today", "date": "2026-07-27"}, force_refresh=True)


class RequestPathGuardArmingTests(unittest.TestCase):
    """`[user decision 2026-09-04]` -- items (a) and (b) of
    `findings_2026-09-04_web_request_path_intelligence.md`.

    The audit could prove the guard was ARMED on web (348 refusals on
    2026-08-27, a branch unreachable otherwise) but not WHICH key armed it, and
    one candidate -- `SYNDICATE_REQUIRE_HOSTED_STORAGE`, a name about storage --
    was deletable from the dashboard. These lock the durable answer.
    """

    def _clean_env(self):
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        for key in _ALL_HOSTED_KEYS:
            os.environ.pop(key, None)
        self.addCleanup(env.stop)

    def test_an_injected_render_marker_arms_the_guard_on_its_own(self) -> None:
        """The real production shape: measured 2026-09-04, the live web dyno
        reports RENDER_INSTANCE_ID from its own environment while NONE of the
        RENDER_* markers appear among its 76 user-defined env vars. Deleting
        every key a human can edit must still leave the gate hard."""
        self._clean_env()
        os.environ["RENDER_INSTANCE_ID"] = "srv-d88ahvrbc2fs73eodu30-7cff65c8c4-68pvq"
        self.assertEqual(hosted_signal(), "RENDER_INSTANCE_ID")
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with self.assertRaises(ComputeInRequestPathError):
                refuse_if_compute_in_request_path("some_heavy_operation")

    def test_render_false_no_longer_disarms_the_storage_flag(self) -> None:
        """The original chained the LOOKUPS, not the results: `os.environ.get
        ("RENDER") or os.environ.get("SYNDICATE_...")` short-circuits on ANY
        non-empty RENDER, so `RENDER=false` suppressed the fallback entirely and
        the guard went warn-only with the storage flag sitting at `true`."""
        self._clean_env()
        os.environ["RENDER"] = "false"
        os.environ["SYNDICATE_REQUIRE_HOSTED_STORAGE"] = "true"
        self.assertEqual(hosted_signal(), "SYNDICATE_REQUIRE_HOSTED_STORAGE")
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with self.assertRaises(ComputeInRequestPathError):
                refuse_if_compute_in_request_path("some_heavy_operation")

    def test_hosted_signal_is_none_off_render(self) -> None:
        """Local dev keeps warn-only. The gate must not fire on a laptop."""
        self._clean_env()
        self.assertIsNone(hosted_signal())

    def test_the_refusal_log_names_the_operation_and_the_signal(self) -> None:
        """All 348 refusals on 2026-08-27 were byte-identical: `operation` went
        only into `extra`, which the default formatter drops, so
        `_compute_response` could not be told from `_build_candidate_pool`."""
        self._clean_env()
        os.environ["RENDER"] = "true"
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with patch("syndicate.features.shared.request_path_guard.logger.error") as mocked_error:
                with self.assertRaises(ComputeInRequestPathError):
                    refuse_if_compute_in_request_path("_build_candidate_pool")

        rendered = mocked_error.call_args.args[0] % mocked_error.call_args.args[1:]
        self.assertIn("_build_candidate_pool", rendered)
        self.assertIn("RENDER", rendered)


class RequestPathGuardCounterTests(unittest.TestCase):
    """`[user decision 2026-09-04]` -- item (c). 348 refusals on 2026-08-27 with
    nothing counting them; the gap was discovered by reading logs a week later.
    """

    def setUp(self) -> None:
        from syndicate.features.shared.request_path_guard import reset_guard_counters

        reset_guard_counters()
        self.addCleanup(reset_guard_counters)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        for key in _ALL_HOSTED_KEYS:
            os.environ.pop(key, None)
        self.addCleanup(env.stop)

    def _refuse(self, operation: str) -> None:
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with self.assertRaises(ComputeInRequestPathError):
                refuse_if_compute_in_request_path(operation)

    def test_refusals_are_counted_and_attributed_to_the_operation(self) -> None:
        from syndicate.features.shared.request_path_guard import guard_counters

        os.environ["RENDER"] = "true"
        self._refuse("_compute_response")
        self._refuse("_compute_response")
        self._refuse("_build_candidate_pool")

        snap = guard_counters()
        self.assertEqual(snap["refused"], 3)
        self.assertEqual(snap["by_operation"]["_compute_response"]["refused"], 2)
        self.assertEqual(snap["by_operation"]["_build_candidate_pool"]["refused"], 1)
        self.assertEqual(snap["last_refused_operation"], "_build_candidate_pool")
        self.assertIsNotNone(snap["first_refusal_at"])
        self.assertIsNotNone(snap["last_refusal_at"])

    def test_the_snapshot_states_that_it_covers_one_worker(self) -> None:
        """web runs WEB_CONCURRENCY=2. A per-process count presented as a
        service total would halve the truth, which is the instrument defect this
        repo keeps paying for -- so the scope travels WITH the number."""
        from syndicate.features.shared.request_path_guard import guard_counters

        snap = guard_counters()
        self.assertEqual(snap["pid"], os.getpid())
        self.assertIn("worker", snap["covers"])

    def test_the_operation_map_is_bounded_and_overflow_is_visible(self) -> None:
        """A caller passing dynamic names must not grow this without limit --
        and the overflow must be COUNTED, not dropped, or the total stops
        reconciling with the per-operation map."""
        from syndicate.features.shared.request_path_guard import _MAX_TRACKED_OPERATIONS
        from syndicate.features.shared.request_path_guard import _OVERFLOW_KEY
        from syndicate.features.shared.request_path_guard import guard_counters

        os.environ["RENDER"] = "true"
        extra = 5
        for index in range(_MAX_TRACKED_OPERATIONS + extra):
            self._refuse(f"operation_{index}")

        snap = guard_counters()
        self.assertEqual(len(snap["by_operation"]), _MAX_TRACKED_OPERATIONS + 1)  # + the overflow bucket
        self.assertEqual(snap["by_operation"][_OVERFLOW_KEY]["refused"], extra)
        self.assertEqual(snap["refused"], _MAX_TRACKED_OPERATIONS + extra)
        self.assertEqual(sum(v["refused"] for v in snap["by_operation"].values()), snap["refused"])

    def test_warnings_are_counted_separately_from_refusals(self) -> None:
        """Off Render the guard warns instead of refusing; conflating the two
        would make a local dev run look like a production incident."""
        from syndicate.features.shared.request_path_guard import guard_counters

        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            refuse_if_compute_in_request_path("some_heavy_operation")  # not hosted -> warns

        snap = guard_counters()
        self.assertEqual(snap["refused"], 0)
        self.assertEqual(snap["warned"], 1)
        self.assertIsNone(snap["first_refusal_at"])

    def test_counting_survives_concurrent_threads(self) -> None:
        """GUNICORN_THREADS=4 share one process, so this has to hold under
        concurrency.

        NOT the reason for the lock, and the difference is worth writing down.
        Measured 2026-09-04 on CPython 3.11: an UNLOCKED counter lost **zero** of
        80,000 increments across four threads, five trials -- so "an unlocked
        counter would drop counts" is a claim this repo cannot make. What the
        lock actually buys is SNAPSHOT CONSISTENCY: `guard_counters()` copies the
        total, the per-operation map and the timestamps together, and without the
        lock a reader can catch `refused` already incremented while
        `by_operation` is not, so the two stop reconciling. That is the invariant
        `test_the_operation_map_is_bounded_and_overflow_is_visible` asserts."""
        import threading as _threading

        from syndicate.features.shared.request_path_guard import guard_counters

        os.environ["RENDER"] = "true"
        errors: list[BaseException] = []

        def hammer() -> None:
            try:
                for _ in range(50):
                    self._refuse("_compute_response")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [_threading.Thread(target=hammer) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(guard_counters()["refused"], 200)

