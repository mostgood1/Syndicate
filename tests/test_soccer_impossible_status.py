"""A soccer match cannot be FINAL before it has kicked off.

MEASURED ON PRODUCTION 2026-08-17 19:3xZ. `/api/board/game-chips?sports=soccer`
returned 89 chips, one of which was:

    eredivisie  EXC @ NEC  state=final  token=FINAL  0-0
                start_time_utc=2026-08-22T18:00:00+00:00

-- five days in the future. Traced to the source rather than the renderer:
`/soccer/eredivisie/api/cards` served that game with `live_state: {"final":
true}` while all SEVEN sibling fixtures in the same league and week read
`false`, so a single `status_state: "post"` is corrupt in the schedule
artifact. The git mirror of the same event (`401875636`, generated
2026-07-20) still reads `"pre"`.

Why it mattered beyond the badge: `_game_flags` sets the chip's `state` from
`live_state`, and `live_edge_policy` keys on that state to decide whether to
withhold an edge. A `post` arriving five days early presents an unplayed match
as settled to every one of those readers at once, and NOTHING between the
artifact and the chip checked the claim against the clock.

The guard only ever DOWNGRADES. It cannot promote a match to live/final, so it
cannot reintroduce the "stuck at pregame" defect `_live_state_block` was built
to fix (that one cost 45 bettable rows on games in play or already over).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.soccer.cards import (
    _effective_status_state,
    _live_state_block,
    _status_label,
)


def _iso(delta_seconds: float) -> str:
    stamp = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return stamp.strftime("%Y-%m-%dT%H:%M") + "Z"


class TestTheMeasuredCase:
    def test_the_exact_production_row_is_refused(self):
        # The literal shape that shipped: ESPN's "...T18:00Z" (no seconds).
        state = _effective_status_state("post", "2036-08-22T18:00Z")
        assert state == "pre", "a match ten years out still read as played"

    def test_final_five_days_out_does_not_reach_live_state(self):
        block = _live_state_block("post", _iso(5 * 86400))
        assert block == {"in_progress": False, "final": False}

    def test_final_five_days_out_does_not_reach_the_badge(self):
        assert _status_label("post", _iso(5 * 86400)) != "Final"

    def test_live_five_days_out_is_refused_too(self):
        # `in` is the same class of error and the same consequence: an edge is
        # withheld or served on the strength of a state the clock contradicts.
        assert _effective_status_state("in", _iso(5 * 86400)) == "pre"
        assert _live_state_block("in", _iso(5 * 86400))["in_progress"] is False


class TestItDoesNotBreakTheCaseItProtects:
    """The failure this must not reintroduce is the OPPOSITE one."""

    def test_a_finished_match_stays_final(self):
        block = _live_state_block("post", _iso(-3 * 3600))
        assert block == {"in_progress": False, "final": True}
        assert _status_label("post", _iso(-3 * 3600)) == "Final"

    def test_a_match_in_play_stays_live(self):
        block = _live_state_block("in", _iso(-45 * 60))
        assert block == {"in_progress": True, "final": False}
        assert _status_label("in", _iso(-45 * 60)) == "Live"

    def test_a_match_kicking_off_right_now_stays_live(self):
        assert _effective_status_state("in", _iso(60)) == "in"

    def test_the_grace_window_covers_listed_kickoff_drift(self):
        # Kickoff times drift by minutes; the guard must not fire on that.
        assert _effective_status_state("in", _iso(20 * 60)) == "in"
        assert _effective_status_state("in", _iso(45 * 60)) == "pre"

    def test_pregame_is_untouched_in_both_directions(self):
        # The guard never promotes. A `pre` match stays `pre` whether its
        # kickoff is hours away or hours past -- inferring liveness from the
        # clock is explicitly out of scope (see _live_state_block's docstring).
        assert _effective_status_state("pre", _iso(-6 * 3600)) == "pre"
        assert _effective_status_state("pre", _iso(6 * 3600)) == "pre"


class TestUnknownIsNotTreatedAsAContradiction:
    """A missing kickoff and a future one are different facts."""

    def test_absent_kickoff_leaves_the_source_state_alone(self):
        assert _effective_status_state("post", None) == "post"
        assert _effective_status_state("post", "") == "post"

    def test_unparseable_kickoff_leaves_the_source_state_alone(self):
        assert _effective_status_state("post", "not-a-timestamp") == "post"
        # A bare date carries no clock to compare against.
        assert _effective_status_state("post", "2036-08-22") == "post"

    def test_the_default_call_signature_still_works(self):
        # `_live_state_block` kept `kickoff` optional so any caller with no
        # timestamp behaves exactly as it did before this guard existed.
        assert _live_state_block("post") == {"in_progress": False, "final": True}
