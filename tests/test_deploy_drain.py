"""`#409` phase 2 -- drain the pipeline before a deploy.

The failure-mode table in docs/reports/refresh_worker_drain_and_restart_proposal.md
is the spec; each row here is a test. They were written before the code shipped
rather than discovered in production, and every one is a shape this repo has
already been bitten by.

THE CENTRAL ASYMMETRY, and most of what these assert: the same unreadable state
means OPPOSITE things depending on who asks.
  - worker "am I drained?"       -> unreadable = NO  (a wrong yes is a permanent outage)
  - deployer "is it idle?"       -> unreadable = UNKNOWN, BLOCK (a wrong idle costs a 23-min build)
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import deploy_drain as dd


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    dd._IN_FLIGHT.clear()
    return tmp_path


# --- worker side ----------------------------------------------------------

def test_no_drain_by_default(_root):
    assert dd.drain_active() is False
    assert dd.drain_hold_reason() is None


def test_a_requested_drain_holds_new_work(_root):
    dd.request_drain("deployer-1", reason="shipping #409")
    assert dd.drain_active() is True
    assert dd.drain_hold_reason() == "deploy_drain_requested"


def test_AN_EXPIRED_DRAIN_IS_IGNORED_even_if_never_cleared(_root):
    """A drain flag that outlives its deployer would be a worker that never
    builds the board again -- a permanent outage manufactured by a crashed
    deploy script. The bound lives in the data, not in a defer counter."""
    dd.request_drain("crashed-deployer", ttl_seconds=60)
    assert dd.drain_active() is True
    # Fast-forward past the expiry without clearing anything.
    real_now = dd._now
    dd._now = lambda: real_now() + 3600
    try:
        assert dd.drain_active() is False, "expired drain still silencing the worker"
        assert dd.drain_hold_reason() is None
    finally:
        dd._now = real_now


def test_an_unreadable_flag_means_NOT_draining_for_the_worker(_root, monkeypatch):
    """Permissive on purpose: a keyvalue hiccup must not stop the board
    building forever. Wrong 'no' costs one build; wrong 'yes' costs everything."""
    import syndicate.features.shared.refresh_state_store as store

    monkeypatch.setattr(store, "read_json_file", lambda p: (_ for _ in ()).throw(RuntimeError("redis down")))
    assert dd.drain_active() is False


def test_clearing_is_owner_scoped(_root):
    dd.request_drain("deployer-A")
    assert dd.clear_drain("deployer-B") is False, "a second deployer cleared someone else's drain"
    assert dd.drain_active() is True
    assert dd.clear_drain("deployer-A") is True
    assert dd.drain_active() is False


# --- deployer side --------------------------------------------------------

def test_nothing_published_reads_as_UNKNOWN_not_idle(_root):
    """`#401`'s lesson: a flag read by code that is not deployed is inert. A
    worker running a build that predates drain support publishes nothing, and
    that must not look like compliance."""
    state, verdict = dd.read_worker_state("refresh-worker")
    assert verdict == "unknown"
    assert state is None


def test_a_stale_heartbeat_reads_as_UNKNOWN_not_idle(_root):
    dd.publish_worker_state("refresh-worker")
    state, verdict = dd.read_worker_state("refresh-worker")
    assert verdict == "idle"

    real_now = dd._now
    dd._now = lambda: real_now() + 10 * 60
    try:
        _, verdict = dd.read_worker_state("refresh-worker")
        assert verdict == "unknown", "a dead worker's last 'in_flight: {}' read as idle"
    finally:
        dd._now = real_now


def test_in_flight_work_reads_as_busy(_root):
    dd.set_in_flight("mlb_sim", True)
    dd.publish_worker_state("refresh-worker")
    _, verdict = dd.read_worker_state("refresh-worker")
    assert verdict == "busy"

    dd.set_in_flight("mlb_sim", False)
    dd.publish_worker_state("refresh-worker")
    _, verdict = dd.read_worker_state("refresh-worker")
    assert verdict == "idle"


def test_state_without_drain_awareness_reads_as_UNKNOWN(_root):
    """Published by a build that does not understand drain -- indistinguishable
    from compliance unless it says so positively."""
    from syndicate.features.shared.refresh_state_store import write_json_file

    write_json_file(dd._worker_state_path("refresh-worker"),
                    {"worker": "refresh-worker", "heartbeat_at": dd._now(), "in_flight": {}})
    _, verdict = dd.read_worker_state("refresh-worker")
    assert verdict == "unknown"


def test_a_failed_read_reads_as_UNKNOWN_not_idle(_root, monkeypatch):
    import syndicate.features.shared.refresh_state_store as store

    dd.publish_worker_state("refresh-worker")
    monkeypatch.setattr(store, "read_json_file_result", lambda p: (None, False))
    _, verdict = dd.read_worker_state("refresh-worker")
    assert verdict == "unknown"


def test_the_worker_acks_the_drain_so_the_deployer_can_tell(_root):
    dd.publish_worker_state("refresh-worker")
    state, _ = dd.read_worker_state("refresh-worker")
    assert state["acked_drain_at"] is None

    dd.request_drain("deployer-1")
    dd.publish_worker_state("refresh-worker")
    state, _ = dd.read_worker_state("refresh-worker")
    assert state["acked_drain_at"] is not None, "worker did not ack a live drain"


def test_publishing_never_raises(_root, monkeypatch):
    import syndicate.features.shared.refresh_state_store as store

    monkeypatch.setattr(store, "write_json_file", lambda p, v: (_ for _ in ()).throw(RuntimeError("redis down")))
    dd.publish_worker_state("refresh-worker")  # must not raise


# --- the wiring -----------------------------------------------------------

def test_the_board_build_defers_while_drained(_root):
    """The refusal point that matters -- a drain that does not stop the 23-minute
    build stops nothing worth stopping."""
    from pipeline.intelligence_state import _board_build_deferral_reason

    assert dd.drain_active() is False
    dd.request_drain("deployer-1")
    try:
        reason = _board_build_deferral_reason(consecutive_odds_defers=0, consecutive_sim_defers=0)
        assert reason == "deploy_drain_requested", reason
    finally:
        dd.clear_drain("deployer-1")


def test_the_drain_deferral_is_not_subject_to_the_starvation_bounds(_root):
    """The hazards below it are bounded so the build eventually pushes through.
    Drain must NOT be -- pushing through defeats the mechanism. Its bound is the
    flag's expiry instead."""
    from pipeline.intelligence_state import _board_build_deferral_reason

    dd.request_drain("deployer-1")
    try:
        for defers in (0, 5, 50, 500):
            assert _board_build_deferral_reason(
                consecutive_odds_defers=defers, consecutive_sim_defers=defers
            ) == "deploy_drain_requested", f"drain pushed through after {defers} defers"
    finally:
        dd.clear_drain("deployer-1")


# --- raised on review: the expiry must outlast the work it waits on ---------

def test_the_default_expiry_exceeds_the_worst_observed_build(_root):
    """Was 45 min against a build once observed at 77 min (4620s,
    intelligence.py:9976). A drain that expires mid-wait lets the deploy land on
    the build anyway -- reporting success while destroying what it protected,
    and only on the slowest builds, which are the most expensive to lose."""
    assert dd._DEFAULT_TTL_SECONDS > 4620, "drain can expire during a worst-case build"


def test_a_drain_requested_before_this_process_booted_is_already_satisfied(_root):
    """Nothing cleared the flag on SUCCESS. The restart IS the completion
    signal: once the worker has restarted, the drain's purpose is served."""
    dd.request_drain("deployer-1")
    assert dd.drain_active() is True

    # Simulate this process having booted AFTER the drain was requested, i.e.
    # the deploy the drain was waiting for has happened.
    real_boot = dd._PROCESS_BOOTED_AT
    dd._PROCESS_BOOTED_AT = dd._now() + 1
    try:
        assert dd.drain_active() is False, "stale drain still deferring after the restart it wanted"
    finally:
        dd._PROCESS_BOOTED_AT = real_boot


def test_a_drain_requested_after_boot_still_holds(_root):
    """The self-clear must not swallow a live drain."""
    real_boot = dd._PROCESS_BOOTED_AT
    dd._PROCESS_BOOTED_AT = dd._now() - 600
    try:
        dd.request_drain("deployer-1")
        assert dd.drain_active() is True
    finally:
        dd._PROCESS_BOOTED_AT = real_boot
