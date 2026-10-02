"""The idle tick wakes when a sport's own pregame sweep is due (lane `layer2-freshness-1h`).

MEASURED 2026-10-02 on the local fleet: with nothing live the loop slept the
900s idle interval after every tick, so per-sport intervals were only CHECKED
every ~16 min. NFL/NCAAF set to 1800s ticked at 19:34, 19:50, 20:06Z -- ~32 min
-- and the board's oldest NFL/NCAAF/WNBA rows peaked at 59-60 min against the
1h freshness rule. Two more gates held a shorter interval back: the GLOBAL
off-hours ceiling (any sport's sweep reset it) and the flat 1800s per-sport
relaunch cooldown. Reachability first: each test flips one of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.features.shared.live_refresh_loop as loop  # noqa: E402

NOW = 1_000_000.0


@pytest.fixture
def world(monkeypatch):
    """nfl/nhl not live with markers; soccer league-scoped; ncaaf has no marker."""
    state = {
        "markers": {"nfl": NOW - 1200.0, "nhl": NOW - 600.0, "soccer": NOW - 7000.0},
        "intervals": {"nfl": 1500, "nhl": 1800, "ncaaf": 1500, "soccer": 3600},
        "live": {"nfl": False, "nhl": False, "ncaaf": False, "soccer": False},
    }
    monkeypatch.delenv("SYNDICATE_PREGAME_TICK_FOLLOWS_DUE", raising=False)
    monkeypatch.setattr(loop, "_live_refresh_loop_sports", lambda: "nfl,nhl,ncaaf,soccer")
    monkeypatch.setattr(
        loop,
        "_LIVE_STATUS_CHECKERS",
        {sport: (lambda _date, s=sport: state["live"][s]) for sport in ("nfl", "nhl", "ncaaf", "soccer")},
    )
    monkeypatch.setattr(loop, "_read_pregame_sport_sweep_epochs", lambda: dict(state["markers"]))
    monkeypatch.setattr(
        loop, "_pregame_sweep_interval_for_tick", lambda sport, now_epoch=None: state["intervals"][sport]
    )
    return state


def test_reachability_the_idle_wait_follows_the_next_due_sport(world):
    # nfl is due in 300s (1500 - 1200): wake then, not 900s from now.
    assert loop._pregame_sports_due_in_seconds(now_epoch=NOW) == {"nfl": 300.0, "nhl": 1200.0}
    assert loop._pregame_idle_wait_seconds(900, now_epoch=NOW) == 305


def test_off_switch_restores_the_fixed_idle_wait(world, monkeypatch):
    monkeypatch.setenv("SYNDICATE_PREGAME_TICK_FOLLOWS_DUE", "0")
    assert loop._pregame_idle_wait_seconds(900, now_epoch=NOW) == 900


def test_never_longer_than_idle_and_never_under_a_minute(world):
    world["markers"] = {"nhl": NOW - 10.0}
    assert loop._pregame_idle_wait_seconds(900, now_epoch=NOW) == 900
    world["markers"] = {"nfl": NOW - 5000.0}  # long overdue, e.g. its launch was refused
    assert loop._pregame_idle_wait_seconds(900, now_epoch=NOW) == 60


def test_only_definite_not_live_stamped_sports_count(world):
    """Strict, unlike the fail-open cadence filter: anything else would wake the
    loop and bypass the off-hours gate on every tick."""
    world["live"]["nfl"] = True
    due = loop._pregame_sports_due_in_seconds(now_epoch=NOW)
    assert "nfl" not in due, "a live sport rides the live cadence"
    assert "ncaaf" not in due, "no marker"
    assert "soccer" not in due, "league-scoped: decided per league"


def test_the_idle_branch_of_the_loop_uses_it(world, monkeypatch):
    monkeypatch.setattr(loop.time, "time", lambda: NOW)
    monkeypatch.setattr(loop, "_live_refresh_loop_idle_interval_seconds", lambda: 900)
    assert loop._live_refresh_loop_interval_for_meta({"adaptive": True, "anyLive": False}) == 305
    monkeypatch.setattr(loop, "_live_refresh_loop_interval_seconds", lambda: 60)
    assert loop._live_refresh_loop_interval_for_meta({"adaptive": True, "anyLive": True}) == 60


def _gate(monkeypatch, *, last_launch_age: float):
    monkeypatch.setattr(loop, "_read_last_odds_refresh_launch", lambda: {"epoch": NOW - last_launch_age})
    monkeypatch.setattr(loop, "_any_tracked_sport_has_upcoming_game", lambda *a, **k: True)
    monkeypatch.setattr(loop, "_off_hours_game_day_max_staleness_seconds", lambda: 900)
    monkeypatch.setattr(loop._slate_phase, "starting_soon_enabled", lambda: False)
    return loop._off_hours_gate_blocks_launch(now_epoch=NOW, any_live=False, date_str="2026-10-02")


def test_a_due_sport_is_not_held_by_another_sports_recent_sweep(world, monkeypatch, capsys):
    world["markers"]["nfl"] = NOW - 1600.0  # nfl due (1500)
    assert _gate(monkeypatch, last_launch_age=300.0) is False
    assert "OFF_HOURS_GATE_BYPASSED_SPORT_DUE sports=nfl" in capsys.readouterr().out


def test_with_nothing_due_the_gate_still_blocks(world, monkeypatch):
    assert _gate(monkeypatch, last_launch_age=300.0) is True


def _cooldown(monkeypatch, *, sport_age: float):
    monkeypatch.setattr(loop, "_pregame_relaunch_cooldown_seconds", lambda: 1800)
    monkeypatch.setattr(loop._slate_phase, "starting_soon_enabled", lambda: False)
    monkeypatch.setattr(
        loop,
        "_read_last_pregame_launch",
        lambda: {"date": "2026-10-02", "epoch": NOW - sport_age, "sports": {"nfl": NOW - sport_age}},
    )
    return loop._pregame_relaunch_blocked(now_epoch=NOW, date_str="2026-10-02", sports=["nfl"])


def test_an_explicit_shorter_interval_shortens_that_sports_cooldown(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_NFL", "1500")
    assert _cooldown(monkeypatch, sport_age=1600.0) is False


def test_without_one_the_full_cooldown_still_holds(monkeypatch):
    monkeypatch.delenv("SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_NFL", raising=False)
    assert _cooldown(monkeypatch, sport_age=1600.0) is True
