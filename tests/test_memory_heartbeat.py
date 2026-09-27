"""The standalone memory heartbeat: owned by no job, readable by both consumers.

WHY THIS EXISTS, measured 2026-09-27. `ALL_PROCESS_MEMORY` was emitted only by a
thread that `refresh_odds_sources` starts and stops around its own run, so the
line carrying container memory existed exactly while a job ran. Two consequences,
both measured:

  * refresh-worker terminated 8 times in 16.8 h (1 per 2.1 h), one an explicit
    `oomKilled` that discarded a 14-minute MLB sim -- and there was no memory
    telemetry within minutes of either kill, so "these earlyExits are OOMs" was
    untestable.
  * `deploy_preflight.py` samples the process list from that same token, so a
    job running meant HOLD and no job running meant a stale sample and UNKNOWN.
    80 consecutive polls over 37 minutes: 41 HOLD, 39 UNKNOWN, ZERO CLEAR.

So the tests that matter are not "does it print". They are: does it print the
token the EXISTING readers parse, does it survive a failing snapshot, and is it
genuinely independent of any job.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import memory_observability as mo  # noqa: E402


@pytest.fixture(autouse=True)
def _always_stop_the_thread():
    """A leaked daemon heartbeat would emit into every later test's stderr."""
    yield
    mo.stop_standalone_memory_heartbeat()


# --------------------------------------------------------------------------
# the switch -- and absent must mean ON
# --------------------------------------------------------------------------

def test_absent_env_means_ON_at_the_default_interval(monkeypatch):
    """`absent != off`. The whole point of this thread is to be running when
    nobody remembered to ask for it."""
    monkeypatch.delenv("SYNDICATE_MEMORY_HEARTBEAT_SECONDS", raising=False)
    assert mo.memory_heartbeat_interval_seconds() == mo._MEMORY_HEARTBEAT_DEFAULT_SECONDS


@pytest.mark.parametrize("raw", ["off", "OFF", "false", "no", "0", "-5"])
def test_it_can_be_switched_off_without_a_deploy(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_MEMORY_HEARTBEAT_SECONDS", raw)
    assert mo.memory_heartbeat_interval_seconds() == 0.0
    assert mo.start_standalone_memory_heartbeat(label="t") is False


def test_junk_falls_back_to_the_default_rather_than_disabling(monkeypatch):
    """A typo must not silently turn the instrument off -- that is the failure
    mode this replaces."""
    monkeypatch.setenv("SYNDICATE_MEMORY_HEARTBEAT_SECONDS", "every-minute-please")
    assert mo.memory_heartbeat_interval_seconds() == mo._MEMORY_HEARTBEAT_DEFAULT_SECONDS


# --------------------------------------------------------------------------
# it beats, once, and only once per process
# --------------------------------------------------------------------------

def test_it_emits_and_is_idempotent(monkeypatch, capfd):
    monkeypatch.setenv("SYNDICATE_MEMORY_HEARTBEAT_SECONDS", "0.05")
    calls: list[dict] = []
    monkeypatch.setattr(mo, "log_all_process_memory",
                        lambda stage, **kw: calls.append({"stage": stage, **kw}))

    assert mo.start_standalone_memory_heartbeat(label="unit") is True
    # A SECOND CALL MUST NOT START A SECOND THREAD. The start is invoked from a
    # per-tick code path, so a non-idempotent start would accumulate one thread
    # per tick -- periodic worker work is never free (`#241`).
    assert mo.start_standalone_memory_heartbeat(label="unit") is False

    deadline = __import__("time").monotonic() + 5.0
    while not calls and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.02)
    assert calls, "the heartbeat never beat"
    assert calls[0]["stage"] == "standalone_heartbeat"
    assert calls[0]["label"] == "unit"


def test_a_RAISING_snapshot_does_not_kill_the_thread_and_says_so(monkeypatch, capfd):
    """A monitor must not be able to kill what it monitors -- and a permanently
    failing snapshot must be visible, not a quiet gap in the telemetry."""
    monkeypatch.setenv("SYNDICATE_MEMORY_HEARTBEAT_SECONDS", "0.05")
    state = {"n": 0}

    def _boom(stage, **kw):
        state["n"] += 1
        raise RuntimeError("procfs went away")

    monkeypatch.setattr(mo, "log_all_process_memory", _boom)
    assert mo.start_standalone_memory_heartbeat(label="unit") is True

    deadline = __import__("time").monotonic() + 5.0
    while state["n"] < 2 and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.02)
    assert state["n"] >= 2, "the thread died on the first failure"
    assert "MEMORY_HEARTBEAT_FAILED" in capfd.readouterr().err


# --------------------------------------------------------------------------
# THE CONTRACT WITH THE EXISTING READERS. This is the test that decides whether
# the fix is a fix.
# --------------------------------------------------------------------------

def test_what_it_emits_is_PARSEABLE_BY_DEPLOY_PREFLIGHT(capfd):
    """Same token, same shape, or half the defect survives.

    The OOM blindness and the preflight's permanent HOLD/UNKNOWN are the SAME
    missing line. Emitting a new token would fix the first and leave the second
    exactly where it was, so this feeds a real beat to `deploy_preflight`'s own
    parser rather than asserting on the text.
    """
    from scripts.deploy_preflight import parse_processes

    payload = mo.log_all_process_memory("standalone_heartbeat", label="unit", pid=1)
    captured = capfd.readouterr().err
    line = [l for l in captured.splitlines() if l.startswith("ALL_PROCESS_MEMORY")]
    assert line, "the token changed -- deploy_preflight samples ALL_PROCESS_MEMORY"

    parsed = parse_processes(line[-1])
    assert parsed is not None, "deploy_preflight cannot parse the heartbeat's line"
    assert "processes" in parsed
    # The process list is what the job check reads; without it a CLEAR is
    # unreachable no matter how fresh the line is.
    assert isinstance(parsed["processes"], list)
    assert "container_memory_mb" in payload or "accounted_rss_mb" in payload, (
        "the memory fields the OOM investigation needs are absent"
    )


def test_the_heartbeat_is_started_from_a_path_the_WORKER_runs(monkeypatch):
    """REACHABILITY, not presence. The thread is worth nothing if nothing on the
    worker ever starts it.

    `scripts/run_refresh_worker.py` calls `_run_mlb_sim_tick` every non-drained
    cycle, and that is the only function the worker imports from a module this
    lane holds -- the worker's own boot file is claimed by another lane. So the
    start must live there, and this asserts the wiring by calling the start the
    tick calls, through the tick's module.
    """
    from syndicate.features.shared import live_refresh_loop as loop

    # ASSERTED ON THE COMPILED CODE OBJECT, NOT ON THE SOURCE TEXT. A source
    # grep would match the long COMMENT above that call, which names the
    # function -- so it would pass with the call deleted and the comment left
    # behind. That is the precise mistake caught in an NCAAF test earlier today:
    # matching prose about a thing instead of the thing.
    names = loop._run_mlb_sim_tick.__code__.co_names
    assert "start_standalone_memory_heartbeat" in names, (
        "_run_mlb_sim_tick no longer starts the heartbeat -- the worker would "
        "have no memory telemetry and deploy_preflight would go back to never "
        "reaching CLEAR"
    )
    assert "syndicate.features.shared.memory_observability" in names
