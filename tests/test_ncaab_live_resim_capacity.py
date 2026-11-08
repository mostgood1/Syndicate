"""NCAAB / WNCAAB live re-sim capacity (#762, lane ncaab-live-resim-capacity): the carry bound and the re-sim workers.

The bound is judged through `build_live_lens_snapshot` and switched by its ENV (off != on through the worker's own
path); the worker pool is checked against the thread path game for game, under the budget, on a failing worker,
and once with REAL child processes running the real engine (where the draws ran is read off the result, not assumed).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.ncaab import live_resim as lr
from syndicate.features.ncaab import live_team_model as tm
from syndicate.features.shared import live_resim_workers as lw

NOW = datetime(2026, 11, 7, 22, 30, 0, tzinfo=timezone.utc)
RESULT = {"sims_run": 200, "home_win_prob": 0.6, "total_mean": 140.0, "home_margin_mean": 3.0,
          "total_dist": {"140": 200}, "margin_dist": {"3": 200}, "segments": {}}


def _iso(seconds_ago: float) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


def _prev_row(event_id: str, *, age: float | None, source: str = lr.LIVE_RESIM_LENS_SOURCE) -> dict:
    lane = {"key": "live", "label": "Live", "source": source, "closed": False,
            "liveStateAsOf": "" if age is None else _iso(age)}
    if source == lr.LIVE_RESIM_LENS_SOURCE:
        lane.update({"modelHomeWinProb": 0.61, "simsRun": 200, "projection": {"homeMargin": 3.0, "total": 141.0}})
    else:
        lane.update({"liveResimRefusal": "no_margin_anchor"})
    return {"event_id": event_id, "home": f"Home {event_id}", "away": f"Away {event_id}", "home_name": f"Home {event_id}",
            "away_name": f"Away {event_id}", "home_id": "10", "away_id": "20", "nameSource": "odds",
            "status": {"detailedState": "In Progress"}, "gameLens": [lane]}


@pytest.fixture
def slate(monkeypatch):
    """Every input faked except the tick's own control flow. `resim` is swappable per test."""
    monkeypatch.setenv("SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR", "0")
    for key in (lr.CARRY_BOUND_ENV, lr.CARRY_MAX_AGE_ENV, lr.WORKERS_ENV):
        monkeypatch.delenv(key, raising=False)
    state: dict = {"events": [], "resim": lambda inputs, gs, **kw: dict(RESULT), "resim_calls": []}
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path", lambda *_: None)
    monkeypatch.setattr("syndicate.features.shared.basketball_pbp.scoreboard_events", lambda sb: state["events"])
    monkeypatch.setattr(lr, "load_player_priors", lambda *a, **k: lr.NcaabResimRefusal("no_player_priors"))
    monkeypatch.setattr(lr, "odds_team_names", lambda *a, **k: {})

    def resume(summary, **k):
        eid = summary["eid"]
        return (None, {"gs": eid}, lr.ResumeFacts(eid, "10", "20", 40, 38, 2, 600.0, "home", 300, NOW.isoformat()))

    monkeypatch.setattr(lr, "resume_from_summary", resume)
    monkeypatch.setattr(lr, "build_engine_inputs", lambda *a, **k: {k2: k2 for k2 in lr._ENGINE_KWARGS}
                        | {"home_players": "H", "away_players": "A"})
    monkeypatch.setattr("syndicate.features.nba.live_resim.map_state_names", lambda gs, h, a: (gs, {}))

    def resim(inputs, gs, **kw):
        state["resim_calls"].append((gs["gs"], threading.get_ident()))
        return state["resim"](inputs, gs, **kw)

    monkeypatch.setattr(lr, "resim_live_game", resim)
    lr._ROTATION_CURSOR.clear()

    def run(n_games: int, *, previous=None, budget=240.0, clock=None, **kw):
        state["events"] = [{"event_id": str(i), "status_state": "in"} for i in range(n_games)]
        return lr.build_live_lens_snapshot("2026-11-07", previous=previous or {}, d1_ids=frozenset(), now=NOW,
                                           fetch_scoreboard=lambda *a: {},
                                           fetch_summary=lambda league, eid: {"header": {}, "eid": eid},
                                           budget_seconds=budget, clock=clock or time.monotonic, **kw)

    state["run"] = run
    return state


# ------------------------------------------------------------------ the carry bound: switches

def test_carry_bound_mode_and_age_parse_safely():
    assert lr.carry_bound_mode({}) == "shadow"
    assert lr.carry_bound_mode({lr.CARRY_BOUND_ENV: "ON"}) == "on"
    assert lr.carry_bound_mode({lr.CARRY_BOUND_ENV: "off"}) == "off"
    assert lr.carry_bound_mode({lr.CARRY_BOUND_ENV: "yes"}) == "shadow"  # unrecognised = default, never unbounded
    assert lr.carry_max_age_seconds({}) == 900.0
    assert lr.carry_max_age_seconds({lr.CARRY_MAX_AGE_ENV: "1200"}) == 1200.0
    for bad in ("0", "-5", "inf", "nan", "soon"):
        assert lr.carry_max_age_seconds({lr.CARRY_MAX_AGE_ENV: bad}) == 900.0


def _budget_out(slate, previous, mode, monkeypatch):
    """A tick that reaches no game (budget 0): every live game is carried or refused by the bound alone."""
    monkeypatch.setenv(lr.CARRY_BOUND_ENV, mode)
    return slate["run"](len(previous), previous=previous, budget=0.0)


def test_off_and_on_differ_through_the_env_on_an_old_lane(slate, monkeypatch):
    """off != on via `SYNDICATE_COLLEGE_LIVE_RESIM_CARRY_BOUND`, through the worker's path: a 1,506 s lane (11-07's
    oldest) is carried under off and refused under on, keyed by its board names, with no probability."""
    previous = {"0": _prev_row("0", age=1506.0)}
    off = _budget_out(slate, previous, "off", monkeypatch)
    on = _budget_out(slate, previous, "on", monkeypatch)
    assert off["counts"]["carried_forward"] == 1 and off["counts"]["carry_expired"] == 0
    lane_off = off["games"][0]["gameLens"][0]
    assert lane_off["source"] == lr.LIVE_RESIM_LENS_SOURCE and lane_off["liveStateCarriedForward"] is True
    assert lane_off["carriedAgeSeconds"] == 1506.0 and off["carryBound"]["carriedAgeMaxSeconds"] == 1506.0
    assert on["counts"]["carried_forward"] == 0 and on["counts"]["carry_expired"] == 1
    assert on["counts"]["not_reached"] == 1
    game_on = on["games"][0]
    lane_on = game_on["gameLens"][0]
    assert lane_on["source"] == lr.PREGAME_LENS_SOURCE and "modelHomeWinProb" not in lane_on
    assert lane_on["liveResimRefusal"] == "budget_exhausted"
    assert lane_on["liveResimRefusalDetail"] == "carry_expired:1506s>900s"
    assert (game_on["home"], game_on["away"], game_on["home_id"]) == ("Home 0", "Away 0", "10")
    assert on["refusalsByReason"] == {"budget_exhausted": 1}
    assert on["carryBound"] == {"mode": "on", "maxAgeSeconds": 900.0, "carriedAgeMaxSeconds": None}


def test_shadow_publishes_exactly_what_off_publishes_and_counts_the_expiry(slate, monkeypatch):
    previous = {"0": _prev_row("0", age=1506.0), "1": _prev_row("1", age=300.0)}
    off = _budget_out(slate, previous, "off", monkeypatch)
    shadow = _budget_out(slate, previous, "shadow", monkeypatch)
    assert json.dumps(shadow["games"], sort_keys=True) == json.dumps(off["games"], sort_keys=True)
    assert shadow["counts"]["carry_expired"] == 1 and off["counts"]["carry_expired"] == 0
    assert shadow["counts"]["carried_forward"] == off["counts"]["carried_forward"] == 2


def test_absent_env_is_shadow(slate, monkeypatch):
    previous = {"0": _prev_row("0", age=1506.0)}
    snap = slate["run"](1, previous=previous, budget=0.0)
    assert snap["carryBound"]["mode"] == "shadow" and snap["counts"]["carry_expired"] == 1
    assert snap["games"][0]["gameLens"][0]["source"] == lr.LIVE_RESIM_LENS_SOURCE


def test_on_keeps_a_lane_inside_the_bound_and_honours_the_age_env(slate, monkeypatch):
    previous = {"0": _prev_row("0", age=899.0), "1": _prev_row("1", age=1100.0)}
    on = _budget_out(slate, previous, "on", monkeypatch)
    assert [g["gameLens"][0]["source"] for g in on["games"]] == [lr.LIVE_RESIM_LENS_SOURCE, lr.PREGAME_LENS_SOURCE]
    monkeypatch.setenv(lr.CARRY_MAX_AGE_ENV, "1200")
    wider = _budget_out(slate, previous, "on", monkeypatch)
    assert wider["counts"]["carried_forward"] == 2 and wider["counts"]["carry_expired"] == 0


def test_on_refuses_a_number_with_no_state_time_and_keeps_a_carried_refusals_reason(slate, monkeypatch):
    previous = {"0": _prev_row("0", age=None), "1": _prev_row("1", age=4000.0, source=lr.PREGAME_LENS_SOURCE)}
    on = _budget_out(slate, previous, "on", monkeypatch)
    by_id = {g["event_id"]: g["gameLens"][0] for g in on["games"]}
    assert by_id["0"]["liveResimRefusalDetail"] == "carry_expired:no_state_time"
    assert by_id["1"]["liveResimRefusal"] == "no_margin_anchor" and by_id["1"]["liveStateCarriedForward"] is True
    assert on["counts"]["carry_expired"] == 1 and on["counts"]["carried_forward"] == 1


def test_on_also_judges_a_game_whose_own_resim_ran_out_mid_draws(slate, monkeypatch):
    """The second carry site: the re-sim started, hit the deadline, and the game falls back to its old lane."""
    monkeypatch.setenv(lr.CARRY_BOUND_ENV, "on")
    slate["resim"] = lambda inputs, gs, **kw: lr.NcaabResimRefusal("budget_exhausted", "57/200")
    snap = slate["run"](1, previous={"0": _prev_row("0", age=2000.0)})
    assert snap["counts"]["carry_expired"] == 1 and snap["counts"]["carried_forward"] == 0
    assert snap["games"][0]["gameLens"][0]["liveResimRefusalDetail"] == "carry_expired:2000s>900s"


# ------------------------------------------------------------------ the re-sim workers

def test_workers_env_parses_to_zero_unless_valid():
    assert lr.resim_workers({}) == 0
    assert lr.resim_workers({lr.WORKERS_ENV: "2"}) == 2
    assert lr.resim_workers({lr.WORKERS_ENV: "99"}) == lr.MAX_WORKERS
    for bad in ("-1", "two", "1.5"):
        assert lr.resim_workers({lr.WORKERS_ENV: bad}) == 0
    assert lr._college_pool(0) is None


def test_the_loop_defaults_to_two_workers_and_hands_them_to_the_tick(monkeypatch):
    """off != on for the LOOP's default (user 2026-11-07 "Yes, load workers=2"): absent = 2 for the loop only; a
    direct call still runs in its own thread; "0" switches the loop back."""
    assert lr.loop_resim_workers({}) == 2 and lr.resim_workers({}) == 0
    assert lr.loop_resim_workers({lr.WORKERS_ENV: "0"}) == 0
    assert lr.loop_resim_workers({lr.WORKERS_ENV: "3"}) == 3
    assert lr.loop_resim_workers({lr.WORKERS_ENV: "two"}) == 0
    monkeypatch.delenv(lr.WORKERS_ENV, raising=False)
    seen = []

    def tick(**kw):
        seen.append(kw)
        lr._LOOP_STOP.set()

    monkeypatch.setattr(lr, "run_live_resim_tick", tick)
    lr._LOOP_STOP.clear()
    try:
        lr._loop("wncaab")
    finally:
        lr._LOOP_STOP.clear()
    assert seen == [{"league": "wncaab", "workers": 2}]


def test_workers_reach_the_pool_through_the_tick(slate, monkeypatch):
    """The hop the loop uses: run_live_resim_tick(workers=2) -> build_live_lens_snapshot -> _college_pool(2)."""
    asked = []
    fake = None

    def college_pool(n):
        nonlocal fake
        asked.append(n)
        fake = fake or FakePool(workers=n)
        return fake if n > 0 else None

    monkeypatch.setattr(lr, "_college_pool", college_pool)
    on = slate["run"](2, workers=2)
    off = slate["run"](2, workers=0)
    assert asked == [2, 0]
    assert on["resimTiming"]["workers"] == 2 and on["resimTiming"]["worker_pids"] == [4242]
    assert off["resimTiming"]["workers"] == 0 and off["resimTiming"]["worker_pids"] == []
    seen = {}
    monkeypatch.setattr(lr, "build_live_lens_snapshot", lambda date_str, **kw: seen.update(kw) or {
        "counts": {}, "games": [], "refusalsByReason": {}})
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.write_json_file", lambda *a, **k: None)
    lr.run_live_resim_tick("2026-11-07", workers=2)
    assert seen["workers"] == 2


class FakePool:
    """`ResimWorkerPool`'s surface over threads, running the REAL job function (`pool_resim_job`)."""

    def __init__(self, workers=2, fail=()):
        self.workers = workers
        self.fail = set(fail)
        self.submitted = []
        self.ex = ThreadPoolExecutor(max_workers=workers)

    def submit(self, job, **kw):
        assert job == "syndicate.features.ncaab.live_resim:pool_resim_job"
        eid = kw["game_state"]["gs"]
        self.submitted.append(eid)
        if eid in self.fail:
            fut = Future()
            fut.set_exception(lw.ResimWorkerError("EOFError: worker pipe closed"))
            return fut
        return self.ex.submit(lambda: (lr.pool_resim_job(**kw), {"pid": 4242, "wall_s": 1.0, "cpu_s": 0.9}))


def test_the_pool_publishes_what_the_thread_publishes(slate):
    thread = slate["run"](5, previous={"3": _prev_row("3", age=100.0)})
    cursor_thread = dict(lr._ROTATION_CURSOR)
    lr._ROTATION_CURSOR.clear()
    pool = FakePool()
    pooled = slate["run"](5, previous={"3": _prev_row("3", age=100.0)}, executor=pool)
    assert json.dumps(pooled["games"], sort_keys=True) == json.dumps(thread["games"], sort_keys=True)
    assert pooled["counts"] == thread["counts"] and pooled["counts"]["resimmed"] == 5
    assert dict(lr._ROTATION_CURSOR) == cursor_thread
    assert sorted(pool.submitted) == ["0", "1", "2", "3", "4"]
    assert thread["resimTiming"]["workers"] == 0 and thread["resimTiming"]["worker_pids"] == []
    assert pooled["resimTiming"]["workers"] == 2 and pooled["resimTiming"]["worker_pids"] == [4242]
    assert pooled["resimTiming"]["resim_jobs"] == 5 and pooled["resimTiming"]["resim_cpu_s"] == 4.5


def test_the_job_gets_the_deadline_on_the_wall_clock(slate):
    seen = {}

    def resim(inputs, gs, **kw):
        seen.update(kw)
        return dict(RESULT)

    slate["resim"] = resim
    before = time.time()
    slate["run"](1, budget=30.0, executor=FakePool(workers=1))
    assert seen["clock"] is time.time and before + 29.0 < seen["deadline"] <= time.time() + 30.0
    assert set(seen) >= {"sims", "base_seed", "league"}


def test_the_pool_honours_the_budget_and_resumes_at_the_first_stopped_game(slate):
    """Two slots. Game 0 finishes at once; game 1's draws run to the deadline (the real job returns
    `budget_exhausted` there) and it is carried; game 2 takes the slot game 0 freed and finishes inside the grace;
    game 3 finds both slots busy until the deadline and is never reached. The next tick starts with game 1."""
    def resim(inputs, gs, **kw):
        if gs["gs"] == "1":
            while kw["clock"]() < kw["deadline"]:
                time.sleep(0.01)
            return lr.NcaabResimRefusal("budget_exhausted", "12/200")
        if gs["gs"] == "0":
            return dict(RESULT)
        time.sleep(2.4)  # past the 2 s deadline, inside the grace
        return dict(RESULT)

    slate["resim"] = resim
    previous = {"1": _prev_row("1", age=200.0)}
    # 2 s, not 0.5 s: under load (Idle priority beside ~40 test files, 2026-11-08) the thread's own prep of game 2
    # outran a 0.5 s budget and it was correctly never submitted, which is not what this test pins.
    snap = slate["run"](4, previous=previous, budget=2.0, executor=FakePool(workers=2))
    by_id = {g["event_id"]: g["gameLens"][0] for g in snap["games"]}
    assert by_id["0"]["source"] == lr.LIVE_RESIM_LENS_SOURCE and "liveStateCarriedForward" not in by_id["0"]
    assert by_id["1"]["liveStateCarriedForward"] is True
    assert by_id["2"]["source"] == lr.LIVE_RESIM_LENS_SOURCE
    assert by_id["3"]["liveResimRefusal"] == "budget_exhausted" and by_id["3"]["liveResimRefusalDetail"] == "not_reached"
    c = snap["counts"]
    assert (c["resimmed"], c["carried_forward"], c["not_reached"], c["refused"]) == (2, 1, 1, 0)
    assert lr._ROTATION_CURSOR["2026-11-07"] == 1


def test_a_job_still_running_past_the_grace_is_discarded_and_carried(slate, monkeypatch):
    monkeypatch.setattr(lr, "WORKER_GRACE_SECONDS", 0.1)
    release = threading.Event()

    def resim(inputs, gs, **kw):
        release.wait(5)  # ignores its deadline, as a wedged worker would
        return dict(RESULT)

    slate["resim"] = resim
    try:
        snap = slate["run"](1, previous={"0": _prev_row("0", age=100.0)}, budget=0.2, executor=FakePool(workers=1))
    finally:
        release.set()
    assert snap["counts"]["carried_forward"] == 1 and snap["counts"]["resimmed"] == 0
    assert snap["elapsedSeconds"] < 3.0


def test_a_failed_worker_is_named_and_the_rest_of_the_tick_runs_in_the_thread(slate):
    pool = FakePool(workers=1, fail={"0"})
    snap = slate["run"](3, previous={"0": _prev_row("0", age=100.0)}, executor=pool)
    assert pool.submitted == ["0"]  # game 0 failed in the worker, so 1 and 2 never went to the pool
    in_thread = {eid for eid, ident in slate["resim_calls"]}
    assert in_thread == {"1", "2"}
    assert snap["resimTiming"]["worker_errors"] == 1
    assert (snap["counts"]["resimmed"], snap["counts"]["carried_forward"]) == (2, 1)
    assert lr._ROTATION_CURSOR["2026-11-07"] == 0  # the failed game is first next tick


def test_the_tick_line_carries_the_new_fields(slate, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(lr, "build_live_lens_snapshot", lambda date_str, **kw: {
        "counts": {"live": 1, "resimmed": 1, "carry_expired": 0}, "refusalsByReason": {}, "games": [],
        "carryBound": {"mode": "shadow", "carriedAgeMaxSeconds": 412.5},
        "resimTiming": {"workers": 2, "resim_jobs": 1, "resim_wall_s": 17.0, "resim_cpu_s": 16.4, "worker_errors": 0}})
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.write_json_file", lambda *a, **k: None)
    status = lr.run_live_resim_tick("2026-11-07")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("NCAAB_LIVE_RESIM_TICK ")
    for token in ("carry_expired=0", "carry_bound=shadow", "carry_age_max_s=412.5", "workers=2", "resim_jobs=1",
                  "resim_wall_s=17.0", "resim_cpu_s=16.4", "worker_errors=0"):
        assert token in line
    assert status["workers"] == 2 and line.rstrip().split(" ")[-1].startswith("elapsed_s=")


# ------------------------------------------------------------------ REAL worker processes (reachability)

_RATES = {"pts_pm": 0.42, "fga_pm": 0.33, "fgm_pm": 0.15, "threes_att_pm": 0.13, "threes_pm": 0.045, "fta_pm": 0.11,
          "ftm_pm": 0.08, "oreb_pm": 0.04, "dreb_pm": 0.1, "reb_pm": 0.14, "ast_pm": 0.07, "tov_pm": 0.055,
          "stl_pm": 0.03, "blk_pm": 0.015, "pf_pm": 0.075}


def _real_inputs(tmp_path):
    cols = ("season", "as_of", "team_id", "athlete_id", "player_name", "games", "minutes", "min_proj", "starter_prob",
            "last_game", "prior_season_minutes") + tuple(f"{k}_pm" for k in lr.RATE_STATS)
    with (tmp_path / "player_priors_2026_asof_20260110.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for t in ("10", "20"):
            for i in range(9):
                w.writerow({"season": 2026, "as_of": "2026-01-10", "team_id": t, "athlete_id": f"{t}{i}",
                            "player_name": f"P{t}_{i}", "games": 5, "minutes": 100,
                            "min_proj": [34, 32, 30, 28, 26, 20, 15, 10, 5][i], "starter_prob": 1.0 if i < 5 else 0.0,
                            "last_game": "2026-01-10", "prior_season_minutes": 0, **_RATES})
    prior = tm.NcaabGamePrior(home_id="10", away_id="20", neutral=False, possessions=68.0, home_ppp=1.08,
                              away_ppp=1.02, home_points=73.0, away_points=69.0, total=142.0, home_margin=4.0,
                              ratings_season=2026, ratings_as_of=dt.date(2026, 1, 9), prior_season_fallback=False,
                              home_games=10, away_games=10)
    pri = lr.load_player_priors(dt.date(2026, 1, 10), dirs=[tmp_path])
    inputs = lr.build_engine_inputs("2026-01-10", "10", "20", neutral=False, priors=pri, team_prior=prior)
    return {k: inputs[k] for k in lr._ENGINE_KWARGS}


def test_real_workers_run_the_real_engine_in_another_process(tmp_path):
    """off != on where it matters: with a pool the draws run in a CHILD (its pid, not ours), the full sims come
    back, the deadline still refuses by name, a disallowed job never reaches a child, and closing the pool ends
    the child (its stdin is its lifeline)."""
    from syndicate.features.basketball_engine.resume import GameState

    inputs = _real_inputs(tmp_path)
    gs = GameState(period=2, seconds_remaining=300, home_period_pts=(36, 30), away_period_pts=(33, 28), possession="home")
    pool = lw.ResimWorkerPool(1, name="test-live-resim")
    try:
        result, meta = pool.submit("syndicate.features.ncaab.live_resim:pool_resim_job", inputs=inputs, game_state=gs,
                                   sims=100, base_seed=7, deadline_epoch=time.time() + 120, league="ncaab").result(timeout=180)
        assert meta["pid"] != os.getpid() and meta["pid"] in pool.pids_started
        assert result["sims_run"] == 100 and 0.0 <= result["home_win_prob"] <= 1.0 and meta["cpu_s"] > 0
        late, _meta = pool.submit("syndicate.features.ncaab.live_resim:pool_resim_job", inputs=inputs, game_state=gs,
                                  sims=100, base_seed=7, deadline_epoch=time.time() - 1, league="ncaab").result(timeout=60)
        assert isinstance(late, lr.NcaabResimRefusal) and late.reason == "budget_exhausted"
        assert _meta["pid"] == meta["pid"]  # one child serves job after job
        with pytest.raises(ValueError):
            pool.submit("os:system", command="echo no")
    finally:
        pool.close()
    proc_gone = True
    for proc in pool._procs:
        proc_gone = proc_gone and proc is None
    assert proc_gone


def test_a_child_that_dies_mid_job_fails_that_job_by_name_and_the_next_job_gets_a_new_child(tmp_path):
    from syndicate.features.basketball_engine.resume import GameState

    inputs = _real_inputs(tmp_path)
    tip = GameState(period=1, seconds_remaining=None, home_period_pts=(0,), away_period_pts=(0,))
    late = GameState(period=2, seconds_remaining=60, home_period_pts=(36, 40), away_period_pts=(33, 38), possession="home")
    job = "syndicate.features.ncaab.live_resim:pool_resim_job"
    pool = lw.ResimWorkerPool(1, name="test-live-resim")
    try:
        long = pool.submit(job, inputs=inputs, game_state=tip, sims=5000, base_seed=1, deadline_epoch=time.time() + 300)
        for _ in range(200):
            if pool._procs[0] is not None:
                break
            time.sleep(0.05)
        time.sleep(0.5)
        first = pool._procs[0]
        first.kill()
        with pytest.raises(lw.ResimWorkerError):
            long.result(timeout=60)
        _r, meta = pool.submit(job, inputs=inputs, game_state=late, sims=100, base_seed=1,
                               deadline_epoch=time.time() + 120).result(timeout=180)
        assert meta["pid"] != first.pid and pool.pids_started == [first.pid, meta["pid"]] and not pool.disabled
    finally:
        pool.close()


def test_the_pool_disables_itself_after_repeated_failures(tmp_path):
    pool = lw.ResimWorkerPool(1, python=str(tmp_path / "no-such-python"), name="test-live-resim")
    try:
        for _ in range(lw.MAX_CONSECUTIVE_FAILURES):
            with pytest.raises(lw.ResimWorkerError):
                pool.submit("syndicate.features.ncaab.live_resim:pool_resim_job").result(timeout=30)
        assert pool.disabled
        with pytest.raises(lw.ResimWorkerError, match="disabled"):
            pool.submit("syndicate.features.ncaab.live_resim:pool_resim_job").result(timeout=5)
    finally:
        pool.close()
