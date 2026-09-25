"""A refused refresh launch must NAME itself, and say which KIND of refusal it is.

THE PRODUCTION FAILURE, measured 2026-09-25 on live-odds-worker.

`launch_refresh_run` refuses before it starts anything when the service's
refresh lane is already busy. That refusal was raised as a bare `ValueError`,
swallowed by `live_refresh_loop` into `meta["error"]`, and printed NOWHERE --
while the loop's own `ODDS_SWEEP_LAUNCHED` line, which fires BEFORE the launch,
positively asserted `sports=mlb,nhl count=2`. No run containing nhl was created.
NHL's collector produced nothing from 15:44Z, its board carried ZERO rows on a
four-game night, and FOUR separate causes were proposed and retracted before the
mutex was suspected at all.

THE MUTEX ITSELF IS NOT THE BUG AND IS NOT WIDENED HERE. Two
`refresh_odds_sources.py` process trees in one 2GB container is the documented
OOM it was built to prevent, and `_refresh_lane_key` already draws the line
exactly where the risk is ("only same-container runs pose any real OOM risk").
What was broken is that losing the mutex was invisible, and that a benign
collision was indistinguishable from a fail-closed one.

THE DISTINCTION THESE TESTS EXIST TO PROTECT:

  lane_busy          a real job holds the lane. It finishes, the lane frees,
                     the next tick succeeds. Self-correcting.
  state_unconfirmed  the lane's state cannot be READ or is self-contradictory.
                     NOTHING is running, so nothing will ever release it --
                     every future launch is refused, permanently.

Both produce the same symptom (refreshes stop) and the same `str(exc)` shape.
Only one is an incident. Collapsing them is how a permanent outage gets read as
a busy afternoon.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.features.shared.ops_refresh as ops  # noqa: E402


# --------------------------------------------------------------------------
# Backwards compatibility. This is the load-bearing one: these exceptions are
# raised through `launch_refresh_run`, whose callers catch `ValueError`. If the
# subclassing ever breaks, every one of those handlers stops catching and a
# refused launch becomes a crashed tick.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [ops.RefreshRunRefused, ops.RefreshLaneBusy, ops.RefreshStateUnconfirmed])
def test_every_refusal_is_still_a_ValueError(cls):
    assert issubclass(cls, ValueError)


def test_an_existing_except_ValueError_handler_still_catches_both():
    for cls in (ops.RefreshLaneBusy, ops.RefreshStateUnconfirmed):
        try:
            raise cls("refused")
        except ValueError as exc:
            assert isinstance(exc, cls)
        else:  # pragma: no cover
            pytest.fail(f"{cls.__name__} escaped an except ValueError handler")


def test_the_two_refusal_kinds_are_distinguishable():
    """The whole point. Same base, same str(), different reason_code."""
    busy = ops.RefreshLaneBusy("refreshes stopped")
    unconfirmed = ops.RefreshStateUnconfirmed("refreshes stopped")
    assert str(busy) == str(unconfirmed), "precondition: the messages alone cannot tell them apart"
    assert busy.reason_code != unconfirmed.reason_code
    assert busy.reason_code == "lane_busy"
    assert unconfirmed.reason_code == "state_unconfirmed"


def test_a_handler_filtering_on_lane_busy_does_not_swallow_the_fail_closed_one():
    """`state_unconfirmed` must never be absorbed by a benign-collision branch."""
    with pytest.raises(ops.RefreshStateUnconfirmed):
        try:
            raise ops.RefreshStateUnconfirmed("cannot read lane state")
        except ops.RefreshLaneBusy:  # pragma: no cover - must not match
            pytest.fail("the fail-closed refusal was caught as a benign collision")


def test_detail_drops_None_so_the_log_line_carries_only_known_facts():
    exc = ops.RefreshLaneBusy("busy", lane="live-odds-worker", pid=42, run_stamp=None)
    assert exc.detail == {"lane": "live-odds-worker", "pid": 42}


# --------------------------------------------------------------------------
# The real raise paths.
# --------------------------------------------------------------------------

def test_an_unreadable_manifest_fails_CLOSED_and_says_so():
    with pytest.raises(ops.RefreshStateUnconfirmed) as caught:
        ops._assert_refresh_manifest_read_ok({"manifest_read_ok": False})
    assert caught.value.reason_code == "state_unconfirmed"


def test_a_self_contradictory_lane_fails_CLOSED_and_says_so():
    with pytest.raises(ops.RefreshStateUnconfirmed) as caught:
        ops._ensure_refresh_context_consistent({"consistency_error": "pid says running, stamp says finished"})
    assert caught.value.reason_code == "state_unconfirmed"


def test_a_genuinely_running_job_raises_lane_busy_carrying_who_holds_it(monkeypatch):
    """The 2026-09-25 case: WNBA's run stamp 20260925_212433 held the lane."""
    context = {
        "manifest": {"state": "running", "pid": 4242, "runStamp": "20260925_212433"},
        "run_summary": {},
        "manifest_read_ok": True,
    }
    monkeypatch.setattr(ops, "_latest_refresh_manifest_context", lambda lane=None: dict(context))
    monkeypatch.setattr(ops, "_refresh_run_still_active", lambda *a, **k: True)

    with pytest.raises(ops.RefreshLaneBusy) as caught:
        ops._assert_no_active_refresh_run(lane="live-odds-worker")

    exc = caught.value
    assert exc.reason_code == "lane_busy"
    # The holder must be nameable from the log line alone -- identifying it took
    # a log sweep and three retracted theories on the day this was measured.
    assert exc.detail["pid"] == 4242
    assert exc.detail["run_stamp"] == "20260925_212433"
    assert exc.detail["lane"] == "live-odds-worker"


def test_a_free_lane_does_not_raise(monkeypatch):
    """A negative control: without this, every test above passes on a function
    that refuses unconditionally."""
    context = {
        "manifest": {"state": "finished", "pid": 4242},
        "run_summary": {},
        "manifest_read_ok": True,
    }
    monkeypatch.setattr(ops, "_latest_refresh_manifest_context", lambda lane=None: dict(context))
    monkeypatch.setattr(ops, "_refresh_run_still_active", lambda *a, **k: False)
    ops._assert_no_active_refresh_run(lane="live-odds-worker")


# --------------------------------------------------------------------------
# The choke point. `launch_refresh_run` has fourteen call sites that swallow a
# refusal in at least four different shapes; logging in any one of them leaves
# the other thirteen dark. These pin the line to the RAISE site instead.
# --------------------------------------------------------------------------

def test_the_refusal_prints_at_the_raise_site(capsys):
    with pytest.raises(ops.RefreshStateUnconfirmed):
        ops._assert_refresh_manifest_read_ok({"manifest_read_ok": False})
    out = capsys.readouterr().out
    assert "REFRESH_LAUNCH_REFUSED" in out
    assert "reason=state_unconfirmed" in out


def test_the_busy_line_names_the_holder(capsys, monkeypatch):
    """A log line that says only 'refused' would have saved no time at all.

    Identifying WHO held the lane on 2026-09-25 took a log sweep and three
    retracted theories; the pid and run stamp are what make it a one-line read.
    """
    context = {
        "manifest": {"state": "running", "pid": 4242, "runStamp": "20260925_212433"},
        "run_summary": {},
        "manifest_read_ok": True,
    }
    monkeypatch.setattr(ops, "_latest_refresh_manifest_context", lambda lane=None: dict(context))
    monkeypatch.setattr(ops, "_refresh_run_still_active", lambda *a, **k: True)

    with pytest.raises(ops.RefreshLaneBusy):
        ops._assert_no_active_refresh_run(lane="live-odds-worker")

    out = capsys.readouterr().out
    assert "REFRESH_LAUNCH_REFUSED" in out
    assert "reason=lane_busy" in out
    assert "pid=4242" in out
    assert "run_stamp=20260925_212433" in out
    assert "lane=live-odds-worker" in out


def test_a_free_lane_prints_NOTHING(capsys, monkeypatch):
    """The negative control for the log line itself.

    Without this, a helper that printed unconditionally would pass every
    assertion above while making the refusal line meaningless.
    """
    context = {
        "manifest": {"state": "finished", "pid": 4242},
        "run_summary": {},
        "manifest_read_ok": True,
    }
    monkeypatch.setattr(ops, "_latest_refresh_manifest_context", lambda lane=None: dict(context))
    monkeypatch.setattr(ops, "_refresh_run_still_active", lambda *a, **k: False)
    ops._assert_no_active_refresh_run(lane="live-odds-worker")
    assert "REFRESH_LAUNCH_REFUSED" not in capsys.readouterr().out


def test_reporting_a_refusal_never_replaces_it_with_a_logging_error(monkeypatch):
    """If the print fails, the REFUSAL must still be what propagates.

    A guard that turns into a `TypeError` from its own log line would fail
    OPEN at every caller that only catches ValueError.
    """
    def _boom(*a, **k):
        raise RuntimeError("stdout is gone")

    monkeypatch.setattr("builtins.print", _boom)
    with pytest.raises(ops.RefreshLaneBusy):
        ops._raise_refresh_refusal(ops.RefreshLaneBusy("busy", lane="x"))
