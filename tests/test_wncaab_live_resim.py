"""WNCAAB live re-sim (lane wncaab-module, user 2026-11-03 "Build it"): NCAAB's tick, resumed under the women's
rules -- four 10:00 quarters, two shots from the 5th team foul of a quarter, overtime extending the 4th quarter.

Every test that flips the league asserts something the men's path does NOT do (reachability: off != on)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from syndicate.features.ncaab import live_resim as lr
from syndicate.features.shared import basketball_league_rules as rulebook
from syndicate.features.shared import basketball_live_state as live
from syndicate.features.shared import basketball_pbp as pbp
from tests.basketball_pbp_fixtures import Game
from tests.test_ncaab_live_resim import _team_prior, _write_priors


def _state(game: Game):
    return live.build_live_game_state(game.summary(), "wncaab", date="2026-11-03", built_at="t")


# ------------------------------------------------------------------ the rules


def test_rules_are_quarters_with_the_bonus_from_the_fifth_and_overtime_extends_q4():
    r = pbp.rules_for("wncaab")
    assert (r.regulation_periods, r.period_sec, r.ot_sec, r.foul_out) == (4, 600, 300, 5)
    assert [r.foul_bucket(p) for p in (1, 2, 3, 4, 5, 6)] == [1, 2, 3, 4, 4, 4]
    assert (r.penalty_after, r.ot_penalty_after, r.double_bonus_after) == (4, 4, None)
    book = rulebook.rules_for("wncaab")
    assert [book.foul_count_resets(p) for p in (1, 2, 3, 4, 5)] == [True, True, True, True, False]
    assert book.bonus_free_throws(5, period=2, remaining_in_period=300.0) == "two_shots"
    assert book.bonus_free_throws(4, period=2, remaining_in_period=30.0) == "none"  # no last-two-minute rule
    # The men's geometry is untouched: halves, overtime continuing the second.
    assert [pbp.rules_for("ncaab").foul_bucket(p) for p in (1, 2, 3)] == [1, 2, 2]


def test_live_state_counts_fouls_per_quarter_and_carries_q4_into_overtime():
    g = Game("wncaab", state="in")
    for i in range(4):
        g.foul(1, f"{9 - i}:00", "away", f"a{i + 1}")
    st = _state(g)
    assert st.away.team_fouls_period == 4 and st.home.shooting_bonus == "bonus" and st.away.fouls_to_give == 0
    g.foul(2, "9:00", "away", "a5")
    assert _state(g).away.team_fouls_period == 1  # resets at the quarter (the men's count would be 5)
    ot = Game("wncaab", state="in")
    for i in range(3):
        ot.foul(4, f"{5 - i}:00", "away", f"a{i + 1}")
    ot.foul(5, "4:00", "away", "a4")
    assert _state(ot).away.team_fouls_period == 4  # overtime continues the 4th quarter


def test_scoreboard_asks_espn_for_the_womens_division_one(monkeypatch):
    seen = []
    monkeypatch.setattr(pbp, "espn_get", lambda league, path, **k: seen.append((league, path)) or {})
    pbp.fetch_scoreboard("wncaab", "20261103")
    assert pbp.ESPN_SPORT_PATH["wncaab"] == "basketball/womens-college-basketball"
    assert seen == [("wncaab", "scoreboard?dates=20261103&groups=50&limit=500")]


# ------------------------------------------------------------------ the resume


def test_resume_inside_the_third_quarter():
    g = Game("wncaab", state="in")
    g.shot(1, "9:00", "home", "h1").end_period(1)
    g.shot(2, "8:00", "away", "a1", pts=3).end_period(2)
    g.shot(3, "7:00", "home", "h2")
    _st, gs, facts = lr.resume_from_summary(g.summary(), date="2026-11-03", league="wncaab")
    assert (gs.period, gs.seconds_remaining) == (3, 420)
    assert gs.home_period_pts == (2, 0, 2) and gs.away_period_pts == (0, 3, 0)
    assert len(gs.home_on_floor) == 5 and len(gs.away_on_floor) == 5
    assert (facts.home_score, facts.away_score, facts.period) == (4, 3, 3)


def test_halftime_resumes_the_third_quarter_where_the_mens_clock_would_end_the_game():
    g = Game("wncaab", state="in")
    g.shot(1, "9:00", "home", "h1").end_period(1)
    g.shot(2, "1:00", "away", "a1", pts=3).end_period(2)
    _st, gs, _f = lr.resume_from_summary(g.summary(), league="wncaab")
    assert gs.period == 3 and gs.seconds_remaining is None and gs.home_period_pts == (2, 0, 0)
    assert lr.resume_from_summary(g.summary(), league="ncaab") == lr.NcaabResimRefusal("regulation_over")


def test_end_of_the_fourth_quarter_refuses_decided_and_resumes_overtime_tied():
    decided = Game("wncaab", state="in")
    for q in (1, 2, 3):
        decided.end_period(q)
    decided.shot(4, "1:00", "home", "h1").end_period(4)
    assert lr.resume_from_summary(decided.summary(), league="wncaab") == lr.NcaabResimRefusal("regulation_over")
    tied = Game("wncaab", state="in")
    for q in (1, 2, 3, 4):
        tied.end_period(q)
    _st, gs, _f = lr.resume_from_summary(tied.summary(), league="wncaab")
    assert gs.period == 5 and len(gs.home_period_pts) == 5


def test_engine_resumes_under_womens_rules_and_a_lead_moves_it(tmp_path):
    """off != on with the real engine: the tip resume is seed-identical to pregame, every draw has four quarters,
    and a fourth-quarter lead raises the home win probability."""
    from syndicate.features.basketball_engine.resume import GameState

    _write_priors(tmp_path, "2026-01-10")
    pri = lr.load_player_priors(dt.date(2026, 1, 10), dirs=[tmp_path])
    inputs = lr.build_engine_inputs("2026-01-10", "10", "20", neutral=False, priors=pri, team_prior=_team_prior(),
                                    league="wncaab")
    engine = lr.ncaab_engine(league="wncaab")
    kw = {k: inputs[k] for k in lr._ENGINE_KWARGS}
    tip = GameState(period=1, seconds_remaining=None, home_period_pts=(0,), away_period_pts=(0,))
    a = [engine.simulate_pbp_game_boxscore(rng=np.random.default_rng(s), **kw)[2:] for s in range(3)]
    b = [engine.simulate_pbp_game_boxscore(rng=np.random.default_rng(s), **kw, state=tip)[2:] for s in range(3)]
    assert a == b
    assert all(len(hq) >= 4 for hq, _aq in a), "four quarters, not two halves"

    def wins(lead):
        gs = GameState(period=4, seconds_remaining=120, home_period_pts=(17, 17, 17, 14 + max(lead, 0)),
                       away_period_pts=(17, 17, 17, 14 + max(-lead, 0)), possession="home")
        outs = [engine.simulate_pbp_game_boxscore(rng=np.random.default_rng(s), **kw, state=gs)[2:] for s in range(20)]
        return sum(1 for hq, aq in outs if sum(hq) > sum(aq))

    assert wins(10) > wins(-10)


# ------------------------------------------------------------------ the tick


def test_snapshot_runs_the_womens_league_with_its_own_cursor(monkeypatch):
    events = [{"event_id": str(i), "status_state": "in"} for i in range(3)]
    seen = {"scoreboard": [], "summary": [], "resume": [], "inputs": [], "resim": []}
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path", lambda *_: None)
    monkeypatch.setattr("syndicate.features.shared.basketball_pbp.scoreboard_events", lambda sb: events)
    monkeypatch.setattr(lr, "load_player_priors", lambda *a, **k: lr.NcaabResimRefusal("no_player_priors"))
    monkeypatch.setattr(lr, "odds_team_names", lambda *a, **k: {})
    facts = lr.ResumeFacts("x", "10", "20", 40, 38, 3, 300.0, "home", 300, "t")
    monkeypatch.setattr(lr, "resume_from_summary", lambda s, **k: seen["resume"].append(k.get("league")) or (None, None, facts))
    monkeypatch.setattr(lr, "build_engine_inputs",
                        lambda *a, **k: seen["inputs"].append(k.get("league")) or {"home_players": None, "away_players": None})
    monkeypatch.setattr("syndicate.features.nba.live_resim.map_state_names", lambda gs, h, a: (gs, {}))

    def resim(inputs, gs, **kw):
        seen["resim"].append(kw.get("league"))
        return {"sims_run": 100, "home_win_prob": 0.6, "total_mean": 130.0, "home_margin_mean": 3.0,
                "total_dist": {}, "margin_dist": {}, "segments": {}}

    monkeypatch.setattr(lr, "resim_live_game", resim)
    lr._ROTATION_CURSOR.clear()
    lr._ROTATION_CURSOR["2026-11-03"] = 7  # the men's cursor for the same date
    snap = lr.build_live_lens_snapshot(
        "2026-11-03", previous={}, league="wncaab", dirs=[],
        fetch_scoreboard=lambda league, d: seen["scoreboard"].append(league) or {},
        fetch_summary=lambda league, eid: seen["summary"].append(league) or {"header": {}},
    )
    assert snap["sport"] == "wncaab" and snap["counts"]["resimmed"] == 3
    assert set(seen["scoreboard"] + seen["summary"] + seen["resume"] + seen["inputs"] + seen["resim"]) == {"wncaab"}
    assert lr._ROTATION_CURSOR["2026-11-03"] == 7, "the women's tick must not move the men's cursor"
    assert "wncaab|2026-11-03" in lr._ROTATION_CURSOR


def test_tick_writes_its_own_key_logs_its_own_prefix_and_takes_its_own_budget(monkeypatch, capsys):
    got = {}

    def build(date_str, **kw):
        got.update(kw)
        return {"counts": {"live": 0}, "games": [], "refusalsByReason": {}}

    monkeypatch.setattr(lr, "build_live_lens_snapshot", build)
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.write_json_file",
                        lambda path, payload: got.setdefault("path", path))
    monkeypatch.delenv("SYNDICATE_WNCAAB_LIVE_RESIM_BUDGET_SECONDS", raising=False)
    status = lr.run_live_resim_tick("2026-11-03", league="wncaab")
    assert status["written"] and got["path"].name == "wncaab_live_resim.json"
    assert got["league"] == "wncaab" and got["budget_seconds"] == lr.WNCAAB_DEFAULT_BUDGET_SECONDS
    assert capsys.readouterr().out.startswith("WNCAAB_LIVE_RESIM_TICK date=2026-11-03")
    monkeypatch.setenv("SYNDICATE_WNCAAB_LIVE_RESIM_BUDGET_SECONDS", "90")
    assert lr._tick_kwargs("wncaab")["budget_seconds"] == 90.0
    assert lr._tick_kwargs("ncaab") == {}, "the men's tick keeps its own defaults"


def test_switch_follows_the_mens_when_absent_and_stops_alone():
    assert lr.wncaab_live_resim_enabled({}) is False
    assert lr.wncaab_live_resim_enabled({"SYNDICATE_NCAAB_LIVE_RESIM": "on"}) is True
    assert lr.wncaab_live_resim_enabled({"SYNDICATE_NCAAB_LIVE_RESIM": "on", "SYNDICATE_WNCAAB_LIVE_RESIM": "0"}) is False
    assert lr.wncaab_live_resim_enabled({"SYNDICATE_WNCAAB_LIVE_RESIM": "1"}) is True


def test_the_mens_starter_also_starts_the_womens_thread(monkeypatch):
    calls = []
    monkeypatch.setattr(lr, "_start_loop", lambda league: calls.append(league) or league == "ncaab")
    assert lr.start_ncaab_live_resim_loop() is True
    assert calls == ["ncaab", "wncaab"]


# ------------------------------------------------------------------ the board interlock

AWAY, HOME = "Army Black Knights", "Duke Blue Devils"


def test_the_board_lists_wncaab_reads_its_own_key_and_accepts_the_stamp():
    from syndicate.features.shared.board_enrichment import _LIVE_GAMELINE_SNAPSHOT_PATHS, _LIVE_GAMELINE_SPORTS
    from syndicate.features.shared.live_gameline_join import lens_sources_for_sport
    from syndicate.features.shared.live_gameline_score import LEVEL_FINAL_IS_A_BAD_ROW

    assert "wncaab" in _LIVE_GAMELINE_SPORTS and "wncaab" in LEVEL_FINAL_IS_A_BAD_ROW
    assert _LIVE_GAMELINE_SNAPSHOT_PATHS["wncaab"] == lr.live_lens_snapshot_path("wncaab").name
    assert _LIVE_GAMELINE_SNAPSHOT_PATHS["wncaab"] != _LIVE_GAMELINE_SNAPSHOT_PATHS["ncaab"]
    assert lens_sources_for_sport("wncaab") == ("live_resim",)


def test_a_womens_live_lane_indexes_and_prices_the_row():
    from syndicate.features.shared.live_gameline_join import (attach_live_gamelines, build_live_gameline_index,
                                                               lens_sources_for_sport)

    def simulate(rng, gs, i=[0]):
        i[0] += 1
        return {}, {}, [18, 18, 18, 18], [18, 18, 18, 8 if i[0] % 20 else 30]

    result = lr.resim_live_game({}, None, sims=200, simulate=simulate, league="wncaab")
    facts = lr.ResumeFacts("501", "10", "20", 66, 56, 4, 120.0, "home", 400, "2026-11-04T01:00:00+00:00")
    snap = {"games": [lr._lane_row("501", {"home": HOME, "away": AWAY, "source": "odds"}, facts, result)]}
    index = build_live_gameline_index(snap, sources=lens_sources_for_sport("wncaab"), sport="wncaab")
    assert len(index) == 1
    row = {"kind": "game", "market": "h2h", "segment": "full", "away_team": AWAY, "home_team": HOME,
           "age_seconds": 30.0, "game": {"state": "live"},
           "projection": {"model_prob_over": 0.62, "market_fair_prob_over": 0.40, "basis": "college_pregame_sim"}}
    attach_live_gamelines([row], index)
    assert row["projection"]["live_aware"] is True
    assert row["live_gameline"]["home_win_prob"] == pytest.approx(0.95)
