"""A refusal that never started anything must not cost a refresh interval.

TWO DEFECTS, both found 2026-09-25 from the refusal line that shipped that day.

(1) THE GLOBAL MARKER LIED. `_record_odds_refresh_launch` is written BEFORE the
    launch. Its consumers read it as "when did odds last refresh":
    `_off_hours_gate_blocks_launch` BLOCKS a launch while
    `now - epoch < ceiling`, and `_odds_refresh_starved` uses it to decide
    whether refreshes have stalled. So a refused launch -- which swept nothing --
    advanced the marker and then SUPPRESSED REAL LAUNCHES on the strength of a
    refresh that never happened. Observed on production at 22:37:09Z:
    `ODDS_SWEEP_REFUSED reason=lane_busy phase=live sports=mlb,ncaaf`, refused
    by a run started 2m11s earlier.

(2) CONTENTION WAS DETECTED BY SUBSTRING. `_is_refresh_run_contention_error`
    tested `"already active" in str(exc)`. `launch_refresh_run` ALSO refuses
    with "A refresh run is already QUEUED for the external runner", which
    contains no such substring -- so that contention was not recognised and all
    four autoruns using this helper reset a FULL 4h cadence epoch over one lost
    race. That is precisely the `#472` bug, still live on the other message.

THE LINE THAT MUST NOT MOVE. Only refusals raised BEFORE any work starts are
safe to treat this way. A launch that DIED mid-flight may have started a sweep,
and for that case the record-first trade is correct and deliberate: "a launch
that dies costs one skipped interval instead of a duplicate sweep" (`#20`).
`RefreshRunRefused` is exactly the before-anything-starts class, which is why
these tests pin the generic-exception case just as hard as the typed one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import ops_refresh  # noqa: E402
import syndicate.features.shared.live_refresh_loop as loop  # noqa: E402
import scripts.run_live_odds_refresh_worker as worker  # noqa: E402


# --------------------------------------------------------------------------
# (2) contention detection, by type
# --------------------------------------------------------------------------

def test_lane_busy_is_contention():
    assert worker._is_refresh_run_contention_error(
        ops_refresh.RefreshLaneBusy("A refresh run is already active (pid=1).")
    )


def test_the_EXTERNAL_RUNNER_refusal_is_contention_too():
    """THE REGRESSION THIS FIXES. No "already active" substring anywhere in it."""
    exc = ops_refresh.RefreshLaneBusy(
        "A refresh run is already queued for the external runner. Cancel it before starting a new run."
    )
    assert "already active" not in str(exc), "precondition: the old substring test could not see this"
    assert worker._is_refresh_run_contention_error(exc)


def test_a_launch_that_DIED_is_not_contention():
    """It may have started a sweep. It must still cost an interval (`#20`)."""
    assert not worker._is_refresh_run_contention_error(RuntimeError("boom"))
    assert not worker._is_refresh_run_contention_error(ValueError("some other problem"))


def test_the_legacy_substring_still_works():
    """A plain ValueError from any not-yet-typed path must keep being caught."""
    assert worker._is_refresh_run_contention_error(ValueError("A refresh run is already active (pid=9)."))


def test_state_unconfirmed_also_preserves_the_epoch():
    """Nothing started, so the cadence must not be burned.

    It is NOT contention in the english sense, and that is deliberate: this
    helper's question is only "was anything attempted", and the answer is no.
    The condition stays visible because it logs `reason=state_unconfirmed` on
    every refusal.
    """
    assert worker._is_refresh_run_contention_error(ops_refresh.RefreshStateUnconfirmed("cannot read lane state"))


# --------------------------------------------------------------------------
# (1) the global marker
# --------------------------------------------------------------------------

@pytest.fixture
def marker(monkeypatch):
    """In-memory stand-in for last_odds_refresh_launch.json."""
    store: dict = {}
    monkeypatch.setattr(loop, "_read_last_odds_refresh_launch", lambda: dict(store))
    monkeypatch.setattr(loop, "_last_odds_refresh_launch_path", lambda: Path("last_odds_refresh_launch.json"))

    def _write(path, payload):
        store.clear()
        store.update(payload)

    monkeypatch.setattr(loop, "write_json_file", _write)
    return store


def test_restoring_the_prior_epoch_undoes_the_record(marker):
    """The composition the tick relies on: capture -> record -> restore."""
    marker.update({"epoch": 1000.0, "recordedAt": "t0"})
    prior = loop._read_last_odds_refresh_launch()

    loop._record_odds_refresh_launch(9000.0)
    assert marker["epoch"] == 9000.0, "precondition: the record lands first"

    loop.write_json_file(loop._last_odds_refresh_launch_path(), prior)
    assert marker["epoch"] == 1000.0


def test_the_off_hours_gate_is_what_makes_this_matter(monkeypatch, marker):
    """Pins the CONSUMER, so the cost is not just asserted in a docstring.

    `_off_hours_gate_blocks_launch` blocks while `now - epoch < ceiling`. With
    the marker wrongly advanced by a refusal, a launch 60s later is blocked;
    with the marker restored, it is not.
    """
    monkeypatch.setattr(loop, "_any_tracked_sport_has_upcoming_game", lambda d, now_epoch=None: False)
    monkeypatch.setattr(loop, "_off_hours_max_staleness_seconds", lambda: 1800)

    marker.update({"epoch": 9000.0})  # the lie a refusal used to leave behind
    assert loop._off_hours_gate_blocks_launch(now_epoch=9060.0, any_live=False, date_str="2026-09-25") is True

    marker.clear()
    marker.update({"epoch": 1000.0})  # rewound to the real last refresh
    assert loop._off_hours_gate_blocks_launch(now_epoch=9060.0, any_live=False, date_str="2026-09-25") is False


# --------------------------------------------------------------------------
# wiring. A rewind that exists and is never reached is inert.
# --------------------------------------------------------------------------

def test_the_tick_captures_the_prior_marker_before_recording_it():
    """Order is the whole fix: capture must precede the overwrite."""
    import inspect

    body = inspect.getsource(loop._run_live_refresh_tick)
    cap = body.index("_global_launch_prior = _read_last_odds_refresh_launch()")
    rec = body.index("_record_odds_refresh_launch(tick_started_epoch)")
    assert cap < rec, "the prior value is captured AFTER it was overwritten -- the rewind restores the lie"


def test_the_tick_gates_the_rewind_on_the_typed_refusal():
    import inspect

    body = inspect.getsource(loop._run_live_refresh_tick)
    assert "_launch_refused_before_start = isinstance(exc, RefreshRunRefused)" in body
    assert "if _launch_refused_before_start:" in body
