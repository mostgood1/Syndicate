"""The tip-off sim fires ONCE PER GAME, not once per tick-while-in-window.

MEASURED on production over 3 hours of a live slate (2026-08-07 21:32-00:32Z):

    10 mlbDailySim launches, 8 of them tip_off_window
    49 game-sims across 15 distinct games -> 3.3x per game, two games 5x

The tip-off branch sits BEFORE the 600s interval check and returns early, so it
bypassed the rate limiter entirely. It fires for any game within 30 minutes and
returns ALL of them, so on a staggered slate the window is effectively always
open and a game sitting in it was resimmed on every launch opportunity.

The only thing holding the rate lower was resource contention -- 239
`intelligence_pipeline_busy` plus 49 `previous_run_still_active` deferrals in the
same window. The effective resim rate was therefore set by how busy the box was,
not by any deliberate rule, and would have risen on its own the moment the worker
got faster.

The trigger exists to catch a LATE SCRATCH before first pitch. One forced
recheck per game does that.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import live_refresh_loop


@pytest.fixture
def meta_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(live_refresh_loop, "_meta_dir", lambda: tmp_path)
    return tmp_path


def test_marker_starts_empty(meta_dir):
    assert live_refresh_loop._read_mlb_tip_off_simmed("2026-08-07") == set()


def test_recorded_games_are_remembered(meta_dir):
    live_refresh_loop._record_mlb_tip_off_simmed("2026-08-07", ["822699", "823349"])
    assert live_refresh_loop._read_mlb_tip_off_simmed("2026-08-07") == {"822699", "823349"}


def test_recording_unions_rather_than_replaces(meta_dir):
    """Games enter the window in waves -- a later launch must not forget earlier
    ones. Measured: successive launches covered 3 then 6 games, the second a
    superset of the first."""
    live_refresh_loop._record_mlb_tip_off_simmed("2026-08-07", ["822699", "823349", "823428"])
    live_refresh_loop._record_mlb_tip_off_simmed("2026-08-07", ["823515", "823836"])
    assert live_refresh_loop._read_mlb_tip_off_simmed("2026-08-07") == {
        "822699", "823349", "823428", "823515", "823836",
    }


def test_marker_is_date_scoped_and_self_clearing(meta_dir):
    """A record for another date reads as empty, so the set clears on rollover
    with no sweep -- yesterday's games must not suppress today's tip-off sims."""
    live_refresh_loop._record_mlb_tip_off_simmed("2026-08-07", ["822699"])
    assert live_refresh_loop._read_mlb_tip_off_simmed("2026-08-08") == set()


def test_unreadable_marker_fails_open(meta_dir):
    """Fails OPEN on a corrupt marker.

    An unreadable marker means we resim a game once more than needed -- the same
    cost as today. The opposite failure, wrongly believing a game was already
    simmed, would silently skip the late-scratch check this trigger exists for.
    """
    (meta_dir / "mlb_tip_off_simmed.json").write_text("{not json", encoding="utf-8")
    assert live_refresh_loop._read_mlb_tip_off_simmed("2026-08-07") == set()


def test_wrong_shape_fails_open(meta_dir):
    (meta_dir / "mlb_tip_off_simmed.json").write_text(
        json.dumps({"date": "2026-08-07", "game_pks": "822699"}), encoding="utf-8"
    )
    assert live_refresh_loop._read_mlb_tip_off_simmed("2026-08-07") == set()


def test_recording_never_raises(meta_dir, monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(live_refresh_loop, "write_json_file", _boom)
    live_refresh_loop._record_mlb_tip_off_simmed("2026-08-07", ["822699"])  # must not raise


def test_empty_input_is_a_no_op(meta_dir):
    live_refresh_loop._record_mlb_tip_off_simmed("2026-08-07", [])
    assert not (meta_dir / "mlb_tip_off_simmed.json").exists()


# ---------------------------------------------------------------------------
# The decision itself.
# ---------------------------------------------------------------------------


class _Event:
    def __init__(self, event_id, start_epoch):
        self.event_id = event_id
        self._start = start_epoch
        self.home = "H"
        self.away = "A"
        self.home_team_id = None
        self.away_team_id = None

    def start_time_epoch(self):
        return self._start


@pytest.fixture
def decision_env(meta_dir, monkeypatch):
    """Reach the tip-off branch: every guard before it must pass."""
    now = 1_775_000_000.0
    events = [_Event("822699", now + 600), _Event("823349", now + 900)]
    monkeypatch.setattr(live_refresh_loop, "_mlb_daily_sim_enabled", lambda: True)
    monkeypatch.setattr(live_refresh_loop, "_sim_pipeline_deferral_reason", lambda **_k: None)
    monkeypatch.setattr(live_refresh_loop, "_mlb_daily_sim_process_still_running", lambda: False)
    monkeypatch.setattr(live_refresh_loop, "is_refresh_run_active", lambda: False)
    monkeypatch.setattr(live_refresh_loop, "_mlb_sim_memory_headroom_snapshot", lambda: None)
    monkeypatch.setattr(live_refresh_loop, "fetch_schedule_for_date", lambda *_a, **_k: events)
    monkeypatch.setattr(live_refresh_loop, "_mlb_daily_summary_path", lambda d: meta_dir / "summary.json")
    (meta_dir / "summary.json").write_text("{}", encoding="utf-8")
    return now


def test_first_pass_forces_every_game_in_the_window(decision_env):
    out = live_refresh_loop._mlb_daily_sim_decision(now_epoch=decision_env, date_str="2026-08-07")
    assert out["force"] is True
    assert out["reason"] == "tip_off_window"
    assert sorted(out["game_pks"]) == ["822699", "823349"]


def test_second_pass_does_not_repeat_an_already_simmed_game(decision_env, meta_dir):
    live_refresh_loop._record_mlb_tip_off_simmed("2026-08-07", ["822699"])
    out = live_refresh_loop._mlb_daily_sim_decision(now_epoch=decision_env, date_str="2026-08-07")
    assert out["force"] is True
    assert out["game_pks"] == ["823349"], "an already-simmed game was queued again"


def test_window_fully_covered_falls_through_instead_of_returning(decision_env, meta_dir):
    """The old code returned unconditionally from this branch, which denied the
    fingerprint / join-mismatch / board-missing triggers their turn for the
    whole pregame window. Once every game in the window is done we must fall
    through to them, not report tip_off_window again."""
    live_refresh_loop._record_mlb_tip_off_simmed("2026-08-07", ["822699", "823349"])
    out = live_refresh_loop._mlb_daily_sim_decision(now_epoch=decision_env, date_str="2026-08-07")
    assert out["reason"] != "tip_off_window"
