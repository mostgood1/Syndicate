"""The season-artifact pull must sit in the sweep, not in one of its callers.

WHY (2026-09-07, measured twice in production). `_LAST_PUBLISHED_CHECKSUM` is
in-process by design, and refresh-worker cannot REBUILD the season-scoped MLB
inputs (arsenal / quality / batted_ball) -- they come from pybaseball Statcast
leaderboards, not in that image. So after every restart the first sweep
republished whatever stale copy the disk held over web's newer one:
`arsenal` and `quality` reverted to their 2026-08-18 build at 18:38Z, and again
at 20:17:47Z on a boot that ALREADY CONTAINED a fix.

The fix was inert because it sat on ONE caller. `sweep_changed_hot_artifacts`
has four paths into it:

    live_lens_loop.py:979        sweep_changed_hot_artifacts(...)
    live_refresh_loop.py:5849    sweep_changed_hot_artifacts(...)
    publish_changed_hot_artifacts(...)  -> used by run_mlb_daily_sim_job.py
                                           and run_queued_refresh_job.py

The live-lens loop swept first on that boot, so the guard never ran. These tests
pin the properties that make the choke-point version un-bypassable.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import artifact_publisher as ap


@pytest.fixture(autouse=True)
def _reset_process_flag():
    """The flag is module state with process lifetime -- reset it per test, or
    the first test to run would silently satisfy every later one."""
    ap._SEASON_ARTIFACTS_PULLED_THIS_PROCESS = False
    yield
    ap._SEASON_ARTIFACTS_PULLED_THIS_PROCESS = False


def _configure(monkeypatch):
    """Get past the sweep's config guard without touching a network."""
    monkeypatch.setattr(ap, "_publish_url", lambda: "https://example.invalid")
    monkeypatch.setattr(ap, "_admin_token", lambda: "token")


def test_the_sweep_itself_pulls(monkeypatch, tmp_path):
    calls = []
    _configure(monkeypatch)
    monkeypatch.setattr(ap, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(ap, "pull_season_artifacts", lambda **kw: calls.append("pull") or 0)

    ap.sweep_changed_hot_artifacts(0.0)
    assert calls == ["pull"], (
        "the pull must happen inside sweep_changed_hot_artifacts -- a guard on a "
        "caller is bypassed by the other three paths, which is how the artifacts "
        "reverted on a boot that contained the fix"
    )


def test_it_pulls_ONCE_per_process_however_many_sweeps(monkeypatch, tmp_path):
    calls = []
    _configure(monkeypatch)
    monkeypatch.setattr(ap, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(ap, "pull_season_artifacts", lambda **kw: calls.append("pull") or 0)

    for _ in range(5):
        ap.sweep_changed_hot_artifacts(0.0)
    assert calls == ["pull"], f"expected exactly one pull across five sweeps, got {len(calls)}"


def test_a_FAILING_pull_does_not_break_or_retry_the_sweep(monkeypatch, tmp_path):
    """Two properties in one, and the second is the load-bearing one.

    Never fatal: a pull that raises must leave exactly the old behaviour.
    And never retried: `pull_season_artifacts` carries a 60s timeout PER
    PATTERN, inside a loop that runs on a live cadence -- so retrying on every
    sweep would turn one broken endpoint into a stalled publisher. The flag is
    set BEFORE the attempt precisely to bound that.
    """
    calls = []

    def _boom(**kw):
        calls.append("pull")
        raise RuntimeError("web is down")

    _configure(monkeypatch)
    monkeypatch.setattr(ap, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(ap, "pull_season_artifacts", _boom)

    result = ap.sweep_changed_hot_artifacts(0.0)          # must not raise
    result2 = ap.sweep_changed_hot_artifacts(0.0)
    assert result.published_count == 0 and result2.published_count == 0
    assert calls == ["pull"], (
        "a failed pull must be attempted once per process, not once per sweep -- "
        f"got {len(calls)} attempts"
    )


def test_it_pulls_BEFORE_the_candidate_scan(monkeypatch, tmp_path):
    """Ordering is the whole mechanism.

    The scan compares each candidate's `st_mtime` against the watermark. A pull
    that lands AFTER it has refreshed nothing the scan can see, so the stale
    copy is still what gets republished.
    """
    order = []
    _configure(monkeypatch)
    monkeypatch.setattr(ap, "pull_season_artifacts", lambda **kw: order.append("pull") or 0)

    def _root():
        order.append("scan")
        return tmp_path

    monkeypatch.setattr(ap, "_data_root", _root)
    ap.sweep_changed_hot_artifacts(0.0)
    assert order == ["pull", "scan"], f"pull must precede the scan, got {order}"


def test_an_unconfigured_process_does_not_pull(monkeypatch, tmp_path):
    """The sweep returns early when there is nowhere to publish; a process that
    cannot publish cannot pull either, and attempting it would spend a timeout
    on every sweep of a service that is deliberately not wired to web."""
    calls = []
    monkeypatch.setattr(ap, "_publish_url", lambda: "")
    monkeypatch.setattr(ap, "_admin_token", lambda: "")
    monkeypatch.setattr(ap, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(ap, "pull_season_artifacts", lambda **kw: calls.append("pull") or 0)

    ap.sweep_changed_hot_artifacts(0.0)
    assert calls == [], "an unconfigured sweep must not attempt a pull"


def test_the_wrapper_path_pulls_too(monkeypatch, tmp_path):
    """`publish_changed_hot_artifacts` is the fourth path in -- used by
    run_mlb_daily_sim_job.py and run_queued_refresh_job.py. It delegates, so it
    inherits the pull; this pins that it keeps doing so."""
    calls = []
    _configure(monkeypatch)
    monkeypatch.setattr(ap, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(ap, "pull_season_artifacts", lambda **kw: calls.append("pull") or 0)

    ap.publish_changed_hot_artifacts(0.0)
    assert calls == ["pull"], "the wrapper path must reach the same pull"
