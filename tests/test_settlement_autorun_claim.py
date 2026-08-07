"""#256 -- the settlement autorun must not be able to retry itself to death.

The outage this covers, in full: refresh-worker was OOM-killed 111 times over
eleven hours at ~4 minute intervals -- one boot-to-kill cycle, repeating.

    boot -> settlement fires (last run never completed)
         -> 21 date chunks read whole and accumulated into one list
         -> OOM
         -> status file never written, so the epoch never advanced
         -> boot -> settlement fires ...

`_evaluation_settlement_should_run_now` is "self-catching-up by construction"
(its own docstring), and the status file was written only after the work. Those
two are individually reasonable and jointly a crash loop.

Six mitigations shipped that night and all missed it, because every one guarded
the BOARD path: the circuit breakers live in `_build_candidate_pool`, and the
ledger-streaming fix (#254) streamed readers in `intelligence_evaluation.py` --
a module the settlement autorun never calls.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "run_refresh_worker_for_test", REPO_ROOT / "scripts" / "run_refresh_worker.py"
)
worker = importlib.util.module_from_spec(_spec)
sys.modules["run_refresh_worker_for_test"] = worker
_spec.loader.exec_module(worker)


DAY = 86400.0


@pytest.fixture(autouse=True)
def _clear_interval_override(monkeypatch):
    # The interval override short-circuits the daily gate entirely; these tests
    # are about the daily gate itself.
    monkeypatch.delenv("EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS", raising=False)


def test_a_claimed_run_is_not_retried_the_same_day():
    """THE regression. A run that claimed the day must not fire again that day,
    whether or not it completed -- otherwise a fatal run retries forever."""
    now = 1_754_000_000.0
    # last_epoch == a claim written moments ago
    assert worker._evaluation_settlement_should_run_now(now_epoch=now, last_epoch=now - 60.0) is False


def test_it_still_fires_when_it_has_never_run():
    assert worker._evaluation_settlement_should_run_now(now_epoch=1_754_000_000.0, last_epoch=0.0) is True


def test_it_still_self_catches_up_on_a_new_central_day():
    """The property the daily gate exists for must survive #256: a worker that
    was down through the window still settles when it comes back."""
    now = 1_754_000_000.0
    assert worker._evaluation_settlement_should_run_now(now_epoch=now, last_epoch=now - (2 * DAY)) is True


def test_the_interval_override_still_works_for_diagnostics():
    import os

    os.environ["EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS"] = "60"
    try:
        now = 1_754_000_000.0
        assert worker._evaluation_settlement_should_run_now(now_epoch=now, last_epoch=now - 120.0) is True
        assert worker._evaluation_settlement_should_run_now(now_epoch=now, last_epoch=now - 5.0) is False
    finally:
        os.environ.pop("EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS", None)


def test_lookback_window_is_bounded():
    # 21 dates read into memory is the allocation that killed the worker. The
    # bound is what stops a typo turning it into a full-season scan; pinned
    # because the per-date bridging in #256 assumes a sane ceiling.
    import os

    os.environ["EVALUATION_SETTLEMENT_LOOKBACK_DAYS"] = "9999"
    try:
        assert worker._evaluation_settlement_lookback_days() == 60
    finally:
        os.environ.pop("EVALUATION_SETTLEMENT_LOOKBACK_DAYS", None)


def test_autorun_is_off_unless_explicitly_enabled():
    # The kill switch used to stop the live outage on 2026-08-07. It must stay
    # opt-IN: an unset var means the autorun does not run.
    import os

    os.environ.pop("EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN", None)
    assert worker._evaluation_settlement_auto_refresh_enabled() is False
    os.environ["EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN"] = "true"
    try:
        assert worker._evaluation_settlement_auto_refresh_enabled() is True
    finally:
        os.environ.pop("EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN", None)
