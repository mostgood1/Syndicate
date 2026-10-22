"""NFL quarter / half capture ON by code default, option E (user 2026-10-22: "go with E and deploy")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.shared import segment_odds_fetch as sof

NOW = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)


def _ev(eid, minutes_from_now):
    return {"id": eid, "commence_time": (NOW + timedelta(minutes=minutes_from_now)).isoformat()}


def test_nfl_captures_every_segment_with_the_env_unset_and_off_turns_it_off():
    segs = sof.configured_segments("nfl", env={})
    assert set(segs) == {"h1", "h2", "q1", "q2", "q3", "q4"}
    assert len(sof.segment_markets_for("nfl", env={})) == 18                           # 6 segments x h2h/spreads/totals
    assert sof.configured_segments("nfl", env={"SYNDICATE_NFL_SEGMENT_MARKETS": "off"}) == ()
    assert sof.configured_segments("nfl", env={"SYNDICATE_NFL_SEGMENT_MARKETS": "h1"}) == ("h1",)


def test_other_sports_keep_absent_means_off():
    assert sof.configured_segments("ncaaf", env={}) == ()
    assert sof.pregame_interval_seconds("ncaaf", env={}) == 0


def test_nfl_live_tier_covers_the_whole_game_and_pregame_runs_every_30_minutes():
    assert sof.pregame_interval_seconds("nfl", env={}) == 1800
    assert sof.live_interval_seconds("nfl", env={}) == 600                              # unchanged: live every 10 min
    events = [_ev("late_q4", -200), _ev("h1", -60), _ev("ended", -230), _ev("pre", 120), _ev("far", 500)]
    scoped, stats = sof.events_in_window(events, sport="nfl", now=NOW, env={})
    assert {e["id"] for e in scoped} == {"late_q4", "h1", "pre"}                         # 3h20 into a game is still live
    assert stats["live_window_seconds"] == 210 * 60
    _scoped, ncaaf = sof.events_in_window(events, sport="ncaaf", now=NOW, env={})
    assert ncaaf["live_window_seconds"] == sof.DEFAULT_LIVE_WINDOW_SECONDS               # NCAAF unchanged
