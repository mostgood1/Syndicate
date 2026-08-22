"""`in` -> `post` must be allowed; `post` -> `in` must never be.

MEASURED ON PRODUCTION 2026-08-22 16:5xZ: 8 of 15 soccer cards rendering a LIVE
head were FINISHED matches -- WAT@WXM, CHA@WHU, SHU@SWA, STK@SOU among them --
each carrying `match_box.final: true`, `status_state: "post"`, clock frozen at
`90'+7'`. The live-state poller was correct (it had already moved them out of
`games[]`); the CARD was stale, and `_effective_state_with_box` returned early
for any started match, so a stale `in` could never be corrected once the match
ended.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.soccer.cards import _effective_state_with_box


def _kicked_off(hours_ago: float = 2.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _box(state: str) -> dict:
    return {"status_state": state, "event_id": "e1", "final": state == "post"}


def test_a_stale_live_artifact_is_corrected_to_final_by_the_box():
    """THE DEFECT. The card said `in`; the box said the match had ended."""
    assert _effective_state_with_box("in", _kicked_off(), _box("post")) == "post"


def test_final_is_terminal_and_never_returns_to_live():
    """The guard the early return was protecting, kept intact. Final only ever
    becomes wrong in one direction."""
    assert _effective_state_with_box("post", _kicked_off(), _box("in")) == "post"


def test_a_live_match_stays_live_when_the_box_agrees():
    assert _effective_state_with_box("in", _kicked_off(), _box("in")) == "in"


def test_a_live_match_stays_live_with_no_box_at_all():
    """A fixture the poller has not written must not be disturbed."""
    assert _effective_state_with_box("in", _kicked_off(), None) == "in"


def test_the_pre_to_started_upgrade_still_works():
    """The original purpose of this function -- a stale `pre` artifact against a
    box that knows the match kicked off."""
    assert _effective_state_with_box("pre", _kicked_off(), _box("in")) == "in"


def test_a_box_claiming_post_before_kickoff_is_still_refused():
    """The kickoff guard outranks the box, whichever source claims what."""
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    assert _effective_state_with_box("pre", future, _box("post")) != "post"
