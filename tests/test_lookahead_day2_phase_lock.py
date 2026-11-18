"""`#842` -- refresh-worker's day-2 look-ahead was phase-locked out by its own day-1 run.

Lane `lookahead-day2-phase-lock`. Measured on the fleet (refresh-worker logs
11-10 23:14 .. 11-18 12:55 CST): day 2 was refused `lane_busy` on 115 of 127
attempts, and 114 of those 115 refusals were held by the same hour's day-1
look-ahead run. Both decisions stamp their marker BEFORE launching, so a refused
day 2 waited a full interval and met the next day-1 run again.

These tests drive the REAL `_run_mlb_sim_tick` (decisions, markers on the real
state store under the test's reports root, the real call site) tick by tick on
a fake clock, with one fake refresh lane that refuses a second run exactly like
`ops_refresh` does. The off arm reproduces the fleet's lock; the on arm is the fix.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import live_refresh_loop as lrl
from syndicate.features.shared import memory_observability
from syndicate.features.shared import ops_refresh

TODAY = "2026-11-18"
DAY1 = "2026-11-19"
DAY2 = "2026-11-20"
T0 = datetime(2026, 11, 18, 9, 0, 0, tzinfo=timezone.utc).timestamp()  # 3:00 AM CST
TICK_S = 38.0  # fleet p50 tick gap, 11-10..11-18
DAY1_RUN_S = 386.0  # first day-1 run after the soccer date anchor, 11-18 12:07 PM CST


class _Clock:
    def __init__(self, t: float) -> None:
        self.t = t


class _FakeLane:
    """refresh-worker's refresh lane: one run at a time, each holding it for its date's run length."""

    def __init__(self, clock: _Clock, run_seconds: dict[str, float], *, refusal: type = ops_refresh.RefreshLaneBusy) -> None:
        self.clock = clock
        self.run_seconds = run_seconds
        self.refusal = refusal
        self.busy_until = 0.0
        self.launches: list[tuple[float, str]] = []
        self.refusals: list[tuple[float, str]] = []
        self.active_calls = 0
        self.lie_free = False  # True: the read-only check says free while the mutex still refuses

    def active(self, lane: str | None = None) -> bool:
        self.active_calls += 1
        if self.lie_free:
            return False
        return self.clock.t < self.busy_until

    def launch(self, **kwargs):
        date_str = kwargs["date"]
        if self.clock.t < self.busy_until:
            self.refusals.append((self.clock.t, date_str))
            raise self.refusal("A refresh run is already active (pid=1).", lane="refresh-worker", pid=1)
        self.busy_until = self.clock.t + self.run_seconds.get(date_str, DAY1_RUN_S)
        self.launches.append((self.clock.t, date_str))
        return {"ok": True, "state": "running", "run_stamp": f"r{len(self.launches)}"}

    def launched(self, date_str: str) -> list[float]:
        return [t for t, d in self.launches if d == date_str]

    def refused(self, date_str: str) -> list[float]:
        return [t for t, d in self.refusals if d == date_str]


@pytest.fixture
def tick_env(monkeypatch):
    clock = _Clock(T0)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401 - mirrors datetime.now
            return datetime.fromtimestamp(clock.t, tz or timezone.utc)

    for key in ("SYNDICATE_LOOK_AHEAD_LANE_WAIT", "SYNDICATE_LOOK_AHEAD_48H_ENABLED", "SYNDICATE_REFRESH_STATE_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SYNDICATE_LOOK_AHEAD_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_LOOK_AHEAD_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(lrl, "datetime", _FakeDatetime)
    monkeypatch.setattr(lrl, "central_today_iso", lambda: TODAY)
    monkeypatch.setattr(lrl, "_mlb_sim_tick_owner_here", lambda: True)
    monkeypatch.setattr(lrl, "_mlb_statcast_refresh_decision", lambda **_: {"launch": False, "reason": "test"})
    monkeypatch.setattr(lrl, "_mlb_daily_sim_enabled", lambda: False)
    monkeypatch.setattr(lrl, "_mlb_evening_next_day_sim_enabled", lambda: False)
    monkeypatch.setattr(lrl, "_mlb_daily_sim_decision", lambda **_: {"force": False, "reason": "test"})
    monkeypatch.setattr(lrl, "_live_refresh_loop_adaptive_enabled", lambda: True)
    monkeypatch.setattr(lrl, "_any_tracked_sport_game_live", lambda: False)
    monkeypatch.setattr(lrl, "_report_odds_sweep_outcomes", lambda *_a, **_k: None)
    monkeypatch.setattr(memory_observability, "start_standalone_memory_heartbeat", lambda **_: False)
    schedule_calls: list[tuple[str, str]] = []

    def _schedule(sport, date_str):
        schedule_calls.append((sport, date_str))
        return [{"id": "g1"}]

    monkeypatch.setattr(lrl, "fetch_schedule_for_date", _schedule)

    def _install(lane: _FakeLane) -> None:
        monkeypatch.setattr(lrl, "launch_refresh_run", lane.launch)
        monkeypatch.setattr(lrl, "is_refresh_run_active", lane.active)

    def _run(hours: float) -> list[dict]:
        metas = []
        end = T0 + hours * 3600.0
        while clock.t < end:
            metas.append(lrl._run_mlb_sim_tick())
            clock.t += TICK_S
        return metas

    return {"clock": clock, "install": _install, "run": _run, "schedule_calls": schedule_calls, "monkeypatch": monkeypatch}


def _gaps(times: list[float]) -> list[float]:
    return [b - a for a, b in zip(times, times[1:])]


def test_off_reproduces_the_fleet_phase_lock(tick_env):
    """Switch absent: day 2 is refused once an hour, never launches, and each refusal waits a full interval."""
    lane = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: DAY1_RUN_S})
    tick_env["install"](lane)
    metas = tick_env["run"](6.0)

    assert len(lane.launched(DAY1)) == 6
    assert lane.launched(DAY2) == []
    assert len(lane.refused(DAY2)) == 6
    assert all(gap >= 3600.0 for gap in _gaps(lane.refused(DAY2)))
    # Every refusal lands inside the same hour's day-1 run -- the fleet's 114 of 115.
    for refused_at in lane.refused(DAY2):
        latest_day1 = max(t for t in lane.launched(DAY1) if t <= refused_at)
        assert refused_at - latest_day1 < DAY1_RUN_S
    # The off arm never consults the read-only lane check and never waits.
    assert lane.active_calls == 0
    assert not any((m.get("lookAheadDay2") or {}).get("reason") == "lane_busy_wait" for m in metas)
    refused_metas = [m["lookAheadDay2"] for m in metas if (m.get("lookAheadDay2") or {}).get("skipped")]
    assert refused_metas and all(m.get("reasonCode") == "lane_busy" for m in refused_metas)
    assert not any(m.get("markerRewound") for m in refused_metas)


def test_on_day2_launches_once_per_interval_right_after_day1_frees_the_lane(tick_env):
    tick_env["monkeypatch"].setenv("SYNDICATE_LOOK_AHEAD_LANE_WAIT", "on")
    lane = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: DAY1_RUN_S})
    tick_env["install"](lane)
    metas = tick_env["run"](6.0)

    day1, day2 = lane.launched(DAY1), lane.launched(DAY2)
    assert len(day1) == 6
    assert len(day2) == 6
    assert lane.refusals == []
    # One launch per interval, never more: the stamp is written only at launch.
    assert all(gap >= 3600.0 for gap in _gaps(day1))
    assert all(gap >= 3600.0 for gap in _gaps(day2))
    # Day 2 starts on the first tick after the day-1 run ends.
    for launched_at in day2:
        latest_day1 = max(t for t in day1 if t <= launched_at)
        assert DAY1_RUN_S <= launched_at - latest_day1 < DAY1_RUN_S + TICK_S
    # Waiting costs no schedule fetch: one fetch per launch, none per waiting tick.
    assert len(tick_env["schedule_calls"]) == len(lane.launches)
    # It waits only in the first hour (the 10 ticks inside the first day-1 run).
    # After its first launch its own stamp sits ~418 s behind day 1's, so it
    # comes due after the day-1 run has ended: the lock becomes a stable offset.
    waits = [m for m in metas if (m.get("lookAheadDay2") or {}).get("reason") == "lane_busy_wait"]
    assert len(waits) == int(DAY1_RUN_S // TICK_S)


def test_off_and_on_differ_on_the_same_tick_sequence(tick_env):
    """Reachability: the switch is read on the real tick path and changes what it launches."""
    lane_off = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: DAY1_RUN_S})
    tick_env["install"](lane_off)
    tick_env["run"](2.0)
    off_day2 = len(lane_off.launched(DAY2))

    # Fresh markers + clock for the on arm.
    for name in ("last_look_ahead_check.json", "last_look_ahead_check_day2.json"):
        path = lrl._meta_dir() / name
        if path.exists():
            path.unlink()
    tick_env["clock"].t = T0
    tick_env["monkeypatch"].setenv("SYNDICATE_LOOK_AHEAD_LANE_WAIT", "true")
    lane_on = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: DAY1_RUN_S})
    tick_env["install"](lane_on)
    tick_env["run"](2.0)
    on_day2 = len(lane_on.launched(DAY2))

    assert off_day2 == 0
    assert on_day2 == 2
    assert off_day2 != on_day2


def test_on_day1_waits_for_a_long_day2_run_and_loses_minutes_not_an_hour(tick_env):
    tick_env["monkeypatch"].setenv("SYNDICATE_LOOK_AHEAD_LANE_WAIT", "on")
    lane = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: 3400.0})
    tick_env["install"](lane)
    tick_env["run"](3.0)

    day1, day2 = lane.launched(DAY1), lane.launched(DAY2)
    assert lane.refusals == []
    assert len(day2) >= 1
    # Day 1 came due at ~3600 s while day 2 still held the lane (until ~418 + 3400 s);
    # it launched on the first free tick, not an interval later.
    second_day1 = day1[1]
    day2_end = day2[0] + 3400.0
    assert second_day1 >= day2_end
    assert second_day1 - day2_end < TICK_S
    assert second_day1 - (day1[0] + 3600.0) < 300.0


def test_on_rewinds_a_racing_lane_busy_refusal_to_a_short_retry(tick_env):
    """If the read-only check says free but the mutex refuses, retry in 300 s, not an interval."""
    tick_env["monkeypatch"].setenv("SYNDICATE_LOOK_AHEAD_LANE_WAIT", "on")
    lane = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: DAY1_RUN_S})
    lane.lie_free = True
    tick_env["install"](lane)
    metas = tick_env["run"](1.0)

    refused = lane.refused(DAY2)
    # Busy 386 s after the day-1 launch: refused on tick 1, retried ~300 s later
    # (still busy, refused), then launched on the next retry -- at most 2 refusals.
    assert 1 <= len(refused) <= 2
    assert all(0 < gap <= 300.0 + TICK_S for gap in _gaps(refused))
    assert len(lane.launched(DAY2)) == 1
    rewound = [m["lookAheadDay2"] for m in metas if (m.get("lookAheadDay2") or {}).get("markerRewound")]
    assert len(rewound) == len(refused)
    assert all(m["retryInSeconds"] == 300 for m in rewound)


def test_on_never_rewinds_an_unreadable_lane(tick_env):
    """A state_unconfirmed refusal keeps the full-interval stamp: no every-tick retries."""
    tick_env["monkeypatch"].setenv("SYNDICATE_LOOK_AHEAD_LANE_WAIT", "on")
    lane = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: DAY1_RUN_S}, refusal=ops_refresh.RefreshStateUnconfirmed)
    lane.lie_free = True
    tick_env["install"](lane)
    metas = tick_env["run"](2.0)

    refused = lane.refused(DAY2)
    assert len(refused) == 2
    assert all(gap >= 3600.0 for gap in _gaps(refused))
    skipped = [m["lookAheadDay2"] for m in metas if (m.get("lookAheadDay2") or {}).get("skipped")]
    assert skipped and all(m.get("reasonCode") == "state_unconfirmed" for m in skipped)
    assert not any(m.get("markerRewound") for m in skipped)


def test_lane_busy_wait_decision_stamps_nothing_and_fetches_nothing(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LOOK_AHEAD_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_LOOK_AHEAD_LANE_WAIT", "1")
    monkeypatch.setattr(lrl, "is_refresh_run_active", lambda lane=None: True)
    recorded: list = []
    monkeypatch.setattr(lrl, "_read_last_look_ahead_check_day2", lambda: ({}, True))
    monkeypatch.setattr(lrl, "_record_look_ahead_check_day2", lambda *a, **k: recorded.append((a, k)))
    monkeypatch.setattr(lrl, "fetch_schedule_for_date", lambda *_: pytest.fail("no schedule fetch while waiting"))

    decision = lrl._look_ahead_decision_day2(now_epoch=1000.0, selected_date=TODAY, any_live=False)

    assert decision == {"launch": False, "reason": "lane_busy_wait", "date": DAY2}
    assert recorded == []


def _reset_markers_and_clock(tick_env) -> None:
    for name in ("last_look_ahead_check.json", "last_look_ahead_check_day2.json"):
        path = lrl._meta_dir() / name
        if path.exists():
            path.unlink()
    tick_env["clock"].t = T0


def test_user_choice_b_fixes_day1_and_retires_day2_on_the_real_tick(tick_env):
    """The configuration the user chose 2026-11-18 ("Fix day 1, retire day 2"), against the fleet's today.

    Both arms start with the lane held by another refresh-worker run for 600 s (the weekly soccer autorun held it
    for 5 of day 1's 6 measured refusals). Fleet today (no keys): day 1 is refused, stamps, and loses the hour;
    day 2 is refused behind it. Option (b) (SYNDICATE_LOOK_AHEAD_LANE_WAIT=on + SYNDICATE_LOOK_AHEAD_48H_ENABLED=false):
    day 1 waits and launches on the first free tick; day 2 never decides to launch, so it makes no launch, no
    refusal and no schedule fetch.
    """
    hold_s = 600.0
    fleet = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: DAY1_RUN_S})
    fleet.busy_until = T0 + hold_s
    tick_env["install"](fleet)
    tick_env["run"](3.0)
    fleet_schedule_dates = {d for _s, d in tick_env["schedule_calls"]}

    _reset_markers_and_clock(tick_env)
    tick_env["schedule_calls"].clear()
    tick_env["monkeypatch"].setenv("SYNDICATE_LOOK_AHEAD_LANE_WAIT", "on")
    tick_env["monkeypatch"].setenv("SYNDICATE_LOOK_AHEAD_48H_ENABLED", "false")
    chosen = _FakeLane(tick_env["clock"], {DAY1: DAY1_RUN_S, DAY2: DAY1_RUN_S})
    chosen.busy_until = T0 + hold_s
    tick_env["install"](chosen)
    metas = tick_env["run"](3.0)

    # Fleet today: day 1 refused once and loses the hour; day 2 refused, never launched.
    assert len(fleet.refused(DAY1)) == 1
    assert len(fleet.launched(DAY1)) == 2
    assert fleet.launched(DAY1)[0] - T0 >= 3600.0
    assert fleet.launched(DAY2) == [] and len(fleet.refused(DAY2)) >= 1
    assert DAY2 in fleet_schedule_dates

    # Option (b): day 1 launches on the first free tick after the hold, then once an hour, never refused.
    day1 = chosen.launched(DAY1)
    assert chosen.refusals == []
    assert len(day1) == 3
    assert hold_s <= day1[0] - T0 < hold_s + TICK_S
    assert all(gap >= 3600.0 for gap in _gaps(day1))
    # Day 2 is retired: no launch, no refusal, no schedule fetch for its date, and every tick says why.
    assert chosen.launched(DAY2) == [] and chosen.refused(DAY2) == []
    assert all(d == DAY1 for _s, d in tick_env["schedule_calls"])
    reasons = {(m.get("lookAheadDay2") or {}).get("reason") for m in metas}
    assert reasons <= {"disabled", "day1_launched_this_tick"} and "disabled" in reasons
    # Day 1 waited (no stamp) while the other run held the lane.
    waits = [m for m in metas if (m.get("lookAhead") or {}).get("reason") == "lane_busy_wait"]
    assert len(waits) == int(hold_s // TICK_S) + 1
