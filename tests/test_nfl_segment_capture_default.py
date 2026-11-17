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
    assert sof.live_interval_seconds("nfl", env={}) == 0                                # every run again: todo #823
    events = [_ev("late_q4", -200), _ev("h1", -60), _ev("ended", -230), _ev("pre", 120), _ev("far", 500)]
    scoped, stats = sof.events_in_window(events, sport="nfl", now=NOW, env={})
    assert {e["id"] for e in scoped} == {"late_q4", "h1", "pre"}                         # 3h20 into a game is still live
    assert stats["live_window_seconds"] == 210 * 60
    _scoped, ncaaf = sof.events_in_window(events, sport="ncaaf", now=NOW, env={})
    assert ncaaf["live_window_seconds"] == sof.DEFAULT_LIVE_WINDOW_SECONDS               # NCAAF unchanged


class _Response:
    status_code = 200
    headers: dict = {}
    url = "https://api.the-odds-api.com/v4/x"
    text = ""

    def __init__(self, event_id):
        self._event_id = event_id

    def json(self):
        return {"id": self._event_id, "bookmakers": []}


class _Session:
    """Records every per-event call: the credit-spending thing is what is asserted."""

    def __init__(self):
        self.event_ids: list[str] = []

    def get(self, url, params=None, timeout=None):
        event_id = url.rstrip("/").split("/")[-2]
        self.event_ids.append(event_id)
        return _Response(event_id)


def _run(session, now, env, state):
    events = [{"id": "live", "commence_time": (now - timedelta(minutes=40)).isoformat().replace("+00:00", "Z")}]
    return sof.fetch_event_segments(api_key="k", sport="nfl", sport_key="americanfootball_nfl",
                                    base_url="https://api.the-odds-api.com/v4", events=events, session=session,
                                    now=now, env=env, pregame_state=state)


def test_reachability_nfl_live_quarter_half_lines_are_fetched_on_every_lines_run(tmp_path):
    """todo #823 (user 2026-11-17, "A: every lines run"). MNF 11-16 under the 600 s gate: quarter/half lines were
    captured 610-660 s apart, so the in-play overlay (rows seen within 300 s) had none for 52% of the game.

    Two NFL lines runs 150 s apart, with NO interval key (the code default, as on the fleet): the live game's
    quarter/half lines are bought on BOTH. Off != on: the env key restoring the gate defers the second run."""
    state = tmp_path / "s.json"
    on = _Session()
    for seconds in (0, 150, 300):
        _, stats = _run(on, NOW + timedelta(seconds=seconds), {}, state)
        assert stats["live_interval_seconds"] == 0 and stats["live_included"] is True
    assert on.event_ids == ["live", "live", "live"]
    assert not (tmp_path / "segment_live_fetch.json").exists(), "every-run writes no live stamp"

    off = _Session()
    gated = {"SYNDICATE_NFL_SEGMENT_LIVE_INTERVAL_SECONDS": "600"}
    _, first = _run(off, NOW, gated, tmp_path / "g.json")
    _, second = _run(off, NOW + timedelta(seconds=150), gated, tmp_path / "g.json")
    assert first["live_included"] is True and second["live_included"] is False and second["live_deferred"] == 1
    assert off.event_ids == ["live"]
