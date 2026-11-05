"""Budget fairness in the NBA live re-sim (lane nba-live-proj-actuals).

The tick used to walk ESPN scoreboard order under ONE deadline, so the games at the end of the scoreboard were
refused every tick once the slate outgrew the budget (2026-11-02: UTA@SAS refused 10 ticks running). These tests
drive `build_live_lens_snapshot` over several ticks with a fake clock and a stub engine, and assert that no game is
refused twice running, that a carried lane is the previous real result stamped as carried, and that carrying stays
out of the history and out of `resimmed`. Hermetic: no network, no data/."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from syndicate.features.nba import live_resim as lr
from tests.basketball_engine_fixtures import synthetic_game_kwargs
from tests.basketball_pbp_fixtures import Game

DATE = "2026-01-15"
T0 = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)
RESULT = {
    "sims_run": 100, "home_win_prob": 0.6, "total_mean": 220.0, "home_margin_mean": 3.0,
    "total_dist": {"220": 100}, "margin_dist": {"3": 100}, "segments": {},
    "player_remainders": {"home": {}, "away": {}},
}


def _summary():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").shot(1, "10:30", "away", "a1", pts=3)
    return g.summary()


def _scoreboard(*ids):
    return {"events": [{"id": i, "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]}
                       for i in ids]}


@pytest.fixture
def slate(tmp_path, monkeypatch):
    """Three live games, a fake clock, a stub engine costing `cost` seconds per game, and a state clock that gives
    every resumed game its own `as_of` (minutes after T0, in the order the tick reaches them)."""
    kw = synthetic_game_kwargs(np.random.default_rng(7), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    lr.persist_engine_inputs(DATE, "GSW", "NYK", {**{k: None for k in lr._INPUT_KEYS}, **kw}, root=tmp_path)
    state = {"t": 0.0, "cost": 100.0, "minute": 0, "order": []}

    real_resume = lr.resume_from_summary

    def resume(summary, *, date="", as_of="", league=lr.LEAGUE):
        state["minute"] += 1
        return real_resume(summary, date=date, league=league,
                           as_of=(T0 + timedelta(minutes=state["minute"])).isoformat())

    def resim(inputs, gs, *, deadline=None, clock=None, **_k):
        state["t"] += state["cost"]
        if deadline is not None and state["t"] > deadline:
            return lr.NbaResimRefusal("budget_exhausted", "50/100")
        return dict(RESULT)

    summaries = {}

    def fetch_summary(_league, event_id):
        state["order"].append(event_id)
        return summaries.setdefault(event_id, _summary())

    monkeypatch.setattr(lr, "resume_from_summary", resume)
    monkeypatch.setattr(lr, "resim_live_game", resim)

    def tick(previous=None, *, ids=("A", "B", "C"), now_minutes=None, **kwargs):
        state["t"] = 0.0
        state["order"] = []
        now = T0 + timedelta(minutes=now_minutes if now_minutes is not None else state["minute"] + 1)
        return lr.build_live_lens_snapshot(DATE, budget_seconds=250, fetch_scoreboard=lambda *_a: _scoreboard(*ids),
                                           fetch_summary=fetch_summary, inputs_root=tmp_path,
                                           clock=lambda: state["t"], previous=previous, now=now, **kwargs)

    state["tick"] = tick
    return state


def _lane(snap, event_id):
    return next(g for g in snap["games"] if g["event_id"] == event_id)["gameLens"][0]


def _fresh(snap):
    return {g["event_id"] for g in snap["games"]
            if g["gameLens"][0]["source"] == lr.LIVE_RESIM_LENS_SOURCE and not g["gameLens"][0].get("carriedForward")}


def test_without_a_previous_snapshot_the_tick_is_unchanged_scoreboard_order_nothing_carried(slate):
    snap = slate["tick"]()
    assert slate["order"] == ["A", "B", "C"]
    assert _fresh(snap) == {"A", "B"}
    assert _lane(snap, "C")["source"] == lr.PREGAME_LENS_SOURCE
    assert _lane(snap, "C")["liveResimRefusal"] == "budget_exhausted"
    assert snap["refusalsByReason"] == {"budget_exhausted": 1} and snap["carriedForward"] == 0


def test_the_tail_is_never_starved_twice_running_and_every_game_has_a_lane_every_tick(slate):
    snaps = [slate["tick"]()]
    for _ in range(5):
        snaps.append(slate["tick"](snaps[-1]))
    # Tick 2 starts with the game tick 1 could not reach (it has no lane yet), then the oldest state.
    assert slate["order"]  # sanity: the stub fetched something
    assert _fresh(snaps[1]) == {"C", "A"}
    for prev, cur in zip(snaps, snaps[1:]):
        missed_before = {"A", "B", "C"} - _fresh(prev)
        assert missed_before <= _fresh(cur), "a game refused last tick must be re-simmed first this tick"
        for event_id in ("A", "B", "C"):
            assert _lane(cur, event_id)["source"] == lr.LIVE_RESIM_LENS_SOURCE  # carried or fresh, never blank


def test_a_carried_lane_is_the_previous_result_stamped_with_its_own_age(slate):
    first = slate["tick"]()
    prev_b = next(g for g in first["games"] if g["event_id"] == "B")
    prev_b["liveProps"] = [{"playerName": "H1", "prop": "player_points", "line": 10.5, "liveProjection": 12.0}]
    second = slate["tick"](first)
    b = next(g for g in second["games"] if g["event_id"] == "B")
    lane = b["gameLens"][0]
    assert lane["carriedForward"] is True and lane["source"] == lr.LIVE_RESIM_LENS_SOURCE
    assert lane["liveStateAsOf"] == prev_b["gameLens"][0]["liveStateAsOf"]  # the ORIGINAL state's time
    assert lane["simsRun"] == 100 and lane["modelHomeWinProb"] == 0.6  # a real full result, never thinner
    assert lane["carriedRefusal"] == "budget_exhausted" and lane["carriedAgeSeconds"] > 0
    assert lane["refusedStateAsOf"]  # this tick's own state, which it could not price
    assert b["liveProps"] == prev_b["liveProps"]
    assert second["refusalsByReason"] == {"budget_exhausted": 1} and second["carriedForward"] == 1


def test_a_state_older_than_the_ceiling_is_refused_not_carried(slate):
    first = slate["tick"]()
    second = slate["tick"](first, now_minutes=30, carry_max_age=600)  # B's state is ~28 min old
    b = _lane(second, "B")
    assert b["source"] == lr.PREGAME_LENS_SOURCE and b["liveResimRefusal"] == "budget_exhausted"
    assert second["carriedForward"] == 0


def test_carry_off_keeps_the_fair_order_but_refuses_as_before(slate):
    first = slate["tick"]()
    second = slate["tick"](first, carry=False)
    assert _fresh(second) == {"C", "A"}
    assert _lane(second, "B")["source"] == lr.PREGAME_LENS_SOURCE and second["carriedForward"] == 0


def test_a_previous_snapshot_from_another_date_neither_reorders_nor_feeds(slate):
    first = slate["tick"]()
    first["date"] = "2026-01-14"
    second = slate["tick"](first)
    assert slate["order"] == ["A", "B", "C"] and second["carriedForward"] == 0


def test_the_mid_run_and_before_start_budget_paths_both_carry(slate):
    slate["cost"] = 130.0  # A done at 130; B passes the 250 s deadline mid-run; C never starts
    first = slate["tick"]()
    assert _lane(first, "B")["liveResimRefusalDetail"] == "50/100"
    assert _lane(first, "C")["liveResimRefusalDetail"] == "before_start"
    slate["cost"] = 100.0
    second = slate["tick"](first)          # B, C first (never re-simmed); A carried
    third = slate["tick"](second)          # A (carried, oldest state) first
    assert _fresh(second) == {"B", "C"} and _lane(second, "A")["carriedForward"] is True
    assert "A" in _fresh(third)


def test_history_records_a_carried_lane_as_the_refusal_this_tick_produced(slate, tmp_path):
    second = slate["tick"](slate["tick"]())
    rows = lr.history_rows(second)
    carried = [r for r in rows if r.get("carried_forward")]
    assert len(carried) == 1
    row = carried[0]
    assert row["source"] == lr.PREGAME_LENS_SOURCE and row["refusal"] == "budget_exhausted"
    assert row["total"] is None and row["p_home"] is None and row["sims"] is None  # not a new measurement
    assert sum(1 for r in rows if r["source"] == lr.LIVE_RESIM_LENS_SOURCE) == 2


def test_the_tick_reads_its_previous_snapshot_and_counts_only_fresh_lanes(monkeypatch, tmp_path):
    import syndicate.features.shared.refresh_state_store as store

    seen = {}

    def build(date_str, **kwargs):
        seen["previous"] = kwargs.get("previous")
        return {"games": [
            {"gameLens": [{"source": "live_resim"}]},
            {"gameLens": [{"source": "live_resim", "carriedForward": True, "carriedRefusal": "budget_exhausted"}]},
        ], "refusalsByReason": {"budget_exhausted": 1}, "carriedForward": 1}

    monkeypatch.setattr(lr, "build_live_lens_snapshot", build)
    monkeypatch.setattr(store, "read_json_file", lambda path: {"date": "2026-10-20", "games": [], "marker": path.name})
    monkeypatch.setattr(store, "write_json_file", lambda path, payload: None)
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    st = lr.run_live_resim_tick("2026-10-20")
    assert seen["previous"]["marker"] == "nba_live_resim.json"
    assert st["resimmed"] == 1 and st["carried"] == 1 and st["refusals"] == {"budget_exhausted": 1}


def test_an_unreadable_previous_snapshot_is_the_old_behaviour_not_a_failed_tick(monkeypatch, tmp_path):
    import syndicate.features.shared.refresh_state_store as store

    seen = {}
    monkeypatch.setattr(lr, "build_live_lens_snapshot",
                        lambda d, **k: seen.update(previous=k.get("previous")) or {"games": [], "refusalsByReason": {}})

    def boom(path):
        raise OSError("keyvalue down")
    monkeypatch.setattr(store, "read_json_file", boom)
    monkeypatch.setattr(store, "write_json_file", lambda path, payload: None)
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    st = lr.run_live_resim_tick("2026-10-20")
    assert seen["previous"] is None and st["written"] is True


@pytest.mark.parametrize("raw,expected", [("", 600.0), ("900", 900.0), ("0", 600.0), ("-5", 600.0),
                                          ("nan", 600.0), ("abc", 600.0)])
def test_the_age_ceiling_never_parses_into_carry_forever(raw, expected):
    assert lr.carry_max_age_seconds({lr.CARRY_MAX_AGE_ENV: raw}) == expected


def test_carry_is_on_unless_switched_off():
    assert lr.carry_enabled({}) is True
    assert lr.carry_enabled({lr.CARRY_ENV: "off"}) is False and lr.carry_enabled({lr.CARRY_ENV: "0"}) is False
