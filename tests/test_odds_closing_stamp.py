"""`closing_captured_at` is when the closing PRICE was observed, not when the
transition was noticed.

The stamp records `previous_odds` -- the tick BEFORE the pregame->live
transition -- but used to write `now`, the moment the transition was DETECTED.
On a ~2h pregame sweep those differ by up to a full interval, and detection
necessarily happens after kickoff, so the stamp routinely post-dated first pitch.

Measured mlb 2026-08-15: every stamped close had `close_age_seconds < 0` --
e.g. 20:34:26Z against a 19:08Z first pitch, 86 minutes late -- while the price
itself was a genuine pregame number. A correct price looked like an in-play one
and was excluded from the CLV headline by `close_timing`.

Detection time is kept, under `closing_detected_at`, so nothing is lost and the
two can never be confused again.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared.odds_refresh_tracking import _apply_closing_stamp


PREV_TS = "2026-08-15T18:55:00Z"   # last pregame observation
NOW = "2026-08-15T20:34:26Z"       # when the sweep noticed the market went live


def _state(**over):
    state = {"history": [], "closing_line": None}
    state.update(over)
    return state


def test_the_stamp_is_the_price_observation_time_not_detection():
    state = _state()
    _apply_closing_stamp(state, previous_line=-1.5, previous_odds=-205,
                         previous_snapshot_ts=PREV_TS, now=NOW)
    assert state["closing_captured_at"] == PREV_TS, "must be the tick the price came from"
    assert state["closing_captured_at"] != NOW


def test_detection_time_is_kept_under_an_honest_name():
    state = _state()
    _apply_closing_stamp(state, previous_line=-1.5, previous_odds=-205,
                         previous_snapshot_ts=PREV_TS, now=NOW)
    assert state["closing_detected_at"] == NOW


def test_the_price_and_line_still_come_from_the_previous_tick():
    """Unchanged behaviour -- this fix touches the clock only."""
    state = _state()
    _apply_closing_stamp(state, previous_line=-1.5, previous_odds=-205,
                         previous_snapshot_ts=PREV_TS, now=NOW)
    assert state["closing_line"] == -1.5
    assert state["closing_price"] == -205


def test_unknown_observation_time_is_left_unset_not_faked_to_now():
    """Absent must not be dressed up as known.

    Downstream `_close_timing` maps a missing age to `unknown`, which does not
    take the permissive branch -- that is the correct outcome here.
    """
    state = _state()
    _apply_closing_stamp(state, previous_line=-1.5, previous_odds=-205,
                         previous_snapshot_ts=None, now=NOW)
    assert state.get("closing_captured_at") is None
    assert state["closing_detected_at"] == NOW


def test_an_existing_stamp_is_never_overwritten():
    """Idempotence: the close is the FIRST transition seen, not the latest."""
    state = _state(closing_line=-2.5, closing_captured_at="2026-08-15T17:00:00Z")
    _apply_closing_stamp(state, previous_line=-1.5, previous_odds=-205,
                         previous_snapshot_ts=PREV_TS, now=NOW)
    assert state["closing_line"] == -2.5
    assert state["closing_captured_at"] == "2026-08-15T17:00:00Z"


def test_no_pregame_value_records_nothing():
    """A market first seen already live has no real pregame price."""
    state = _state()
    _apply_closing_stamp(state, previous_line=None, previous_odds=None,
                         previous_snapshot_ts=PREV_TS, now=NOW)
    assert state.get("closing_line") is None
    assert state.get("closing_captured_at") is None


def test_the_stamp_no_longer_post_dates_first_pitch():
    """The end-to-end property the defect violated.

    `close_age_seconds` is `(commence - stamp)`; it must be >= 0 for a close.
    """
    import datetime
    commence = datetime.datetime.fromisoformat("2026-08-15T19:08:00+00:00")
    state = _state()
    _apply_closing_stamp(state, previous_line=-1.5, previous_odds=-205,
                         previous_snapshot_ts=PREV_TS, now=NOW)
    stamp = datetime.datetime.fromisoformat(state["closing_captured_at"].replace("Z", "+00:00"))
    assert (commence - stamp).total_seconds() >= 0, "a close cannot post-date first pitch"
    # and the OLD behaviour would have failed exactly this
    old = datetime.datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    assert (commence - old).total_seconds() < 0
