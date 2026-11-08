"""Basketball interval-projection replay harness (lane basketball-interval-backtest).

Every projector variant gets an OFF != ON reachability test (`docs/ai_context/model_engine_standard.md`): a
variant whose input never reaches its arithmetic or its engine call reads exactly like a working one."""

from __future__ import annotations

import datetime as dt
import gzip
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from syndicate.features.shared import basketball_interval_backtest as bib
from syndicate.features.shared import basketball_pbp as pbp

REPO = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("backtest_basketball_intervals", REPO / "scripts" / "backtest_basketball_intervals.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backtest_basketball_intervals"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ------------------------------------------------------------------------------------------------ fixtures

HOME5 = ["h1", "h2", "h3", "h4", "h5"]
AWAY5 = ["a1", "a2", "a3", "a4", "a5"]


def _event(league, seq, elapsed, side, kind, points=0, made=None, pa=None, players=(), last_ft=None):
    rules = pbp.rules_for(league)
    reg = rules.regulation_seconds()
    if elapsed <= reg:
        period = min(int(elapsed // rules.period_sec) + 1, rules.regulation_periods)
        if elapsed > 0 and elapsed % rules.period_sec == 0:
            period = int(elapsed // rules.period_sec)  # a play AT the horn belongs to the period it ends
        clock = period * rules.period_sec - elapsed
    else:
        period = rules.regulation_periods + 1 + int((elapsed - reg - 1e-9) // rules.ot_sec)
        clock = rules.period_start_elapsed(period) + rules.ot_sec - elapsed
    return pbp.PbpEvent(seq=seq, play_id=str(seq), period=period, clock_left=float(clock), elapsed=float(elapsed), side=side,
                        kind=kind, type_text=kind, text=kind, points=points, home_score=None, away_score=None,
                        players=tuple(players), made=made, points_attempted=pa, last_free_throw=last_ft,
                        shooting_play=kind == "shot")


def make_game(league="ncaab", *, step=40, ot=False, pregame=(140.0, 4.0), extra=None, score_pattern=None):
    """A synthetic final: a made 2 every `step` seconds, alternating sides (home scores a 3 every 5th basket),
    misses + defensive rebounds between, so pace / efficiency / possession are all non-trivial."""
    rules = pbp.rules_for(league)
    reg = rules.regulation_seconds()
    evs = []
    seq = 0
    n = 0
    t = 10.0
    while t < reg:
        side = "home" if n % 2 == 0 else "away"
        pts = 3 if (side == "home" and n % 5 == 0) else 2
        if score_pattern is not None:
            side, pts = score_pattern(n, t)
        shooter = (HOME5 if side == "home" else AWAY5)[n % 5]
        evs.append(_event(league, seq, t, side, "shot", points=pts, made=True, pa=pts, players=(shooter,)))
        seq += 1
        other = "away" if side == "home" else "home"
        evs.append(_event(league, seq, t + step / 2, other, "shot", points=0, made=False, pa=2,
                          players=((AWAY5 if other == "away" else HOME5)[0],)))
        seq += 1
        evs.append(_event(league, seq, t + step / 2, side, "rebound_def", players=(shooter,)))
        seq += 1
        n += 1
        t += step
    if ot:
        # Regulation ends tied only if we force it: add OT points to both sides, home +4 net.
        evs.append(_event(league, seq, reg + 60, "home", "shot", points=7, made=True, pa=3))
        seq += 1
        evs.append(_event(league, seq, reg + 120, "away", "shot", points=3, made=True, pa=3))
    pts = bib.points_by_period(evs)
    meta = pbp.GameMeta(league=league, event_id="g1", date="2026-02-01", season=2026, season_type="regular",
                        status_state="post", completed=True,
                        home=pbp.TeamInfo("home", "100", "HOM", sum(pts["home"].values())),
                        away=pbp.TeamInfo("away", "200", "AWY", sum(pts["away"].values())))
    for pid in HOME5 + ["h6"]:
        meta.box[pid] = pbp.BoxPlayer(pid, f"Home {pid}", "home", pid in HOME5, False, 20.0, 1, 0)
    for pid in AWAY5 + ["a6"]:
        meta.box[pid] = pbp.BoxPlayer(pid, f"Away {pid}", "away", pid in AWAY5, False, 20.0, 1, 0)
    total, margin = pregame if pregame else (None, None)
    return bib.ReplayGame(league=league, game_id="g1", date="2026-02-01", phase="regular", meta=meta, events=tuple(evs),
                          pregame_total=total, pregame_home_margin=margin, pregame_source="test", extra=dict(extra or {}))


# ------------------------------------------------------------------------------------------------ actuals / state

def test_segment_actuals_follow_the_book_overtime_convention():
    g = make_game("nba", ot=True)
    act = bib.segment_actuals(g)
    pts = bib.points_by_period(g.events)
    q = {p: pts["home"].get(p, 0) + pts["away"].get(p, 0) for p in range(1, 6)}
    assert act["q4"][0] == q[4]  # a quarter settles on itself
    assert act["h1"][0] == q[1] + q[2]
    assert act["h2"][0] == q[3] + q[4] + q[5]  # the second half carries overtime
    assert act["full"][0] == sum(q.values())
    assert act["full"][1] - act["q1"][1] - act["q2"][1] - act["q3"][1] - act["q4"][1] == 4  # OT margin rides on full only


def test_segment_actuals_refuse_a_log_that_misses_the_official_final():
    g = make_game("ncaab")
    bad = replace(g, meta=replace(g.meta, home=replace(g.meta.home, score=g.meta.home.score + 2)))
    assert isinstance(bib.segment_actuals(bad), bib.Refusal)
    assert bib.replay_game(bad, [bib.NaivePace()])["game_refusal"] == "pbp_final_mismatch"


def test_state_at_rebuilds_score_period_and_boundary():
    g = make_game("wncaab")
    s = bib.state_at(g, 600.0)  # the end of Q1 is the start of Q2
    assert (s.period, s.clock_left) == (2, 600.0)
    assert len(s.home_period_pts) == 2 and s.home_period_pts[1] == 0 and s.away_period_pts[1] == 0
    assert s.possession is None and s.possession_basis == "period_start"
    s2 = bib.state_at(g, 615.0)
    assert (s2.period, s2.clock_left) == (2, 585.0)
    known = [e for e in g.events if e.elapsed <= 615.0]
    assert s2.total == sum(e.points for e in known)
    assert s2.counts["home"]["fga"] == sum(1 for e in known if e.side == "home" and e.kind == "shot")
    assert s2.possession in ("home", "away")


def test_checkpoints_are_the_bar_minutes_and_its_fractions():
    assert bib.checkpoint_times("ncaab") == {"0m": 0.0, "10m": 600.0, "20m": 1200.0, "30m": 1800.0, "38m": 2280.0}
    assert bib.checkpoint_times("wnba") == {"0m": 0.0, "10m": 600.0, "20m": 1200.0, "30m": 1800.0, "38m": 2280.0}
    assert bib.checkpoint_times("nba") == {"0m": 0.0, "12m": 720.0, "24m": 1440.0, "36m": 2160.0, "45.6m": 2736.0}
    # The old NCAAB app's 2-minute bins: elapsed 10:00-11:59 is one bin.
    assert bib.bucket_of("ncaab", 600) == bib.bucket_of("ncaab", 690) == 0.25
    assert bib.bucket_of("ncaab", 720) == 0.3


def test_live_segments_drop_a_settled_segment_but_never_one_that_carries_overtime():
    g = make_game("nba")
    s = bib.state_at(g, 2500.0)  # Q4
    assert bib.live_segments(g, s) == ["full", "q4", "h2"]


# ------------------------------------------------------------------------------------------------ arithmetic projectors

def _proj(projector, game, t):
    prep = projector.prepare(game)
    return projector.project(game, bib.state_at(game, t), prep)


def test_naive_pace_is_the_old_apps_proj_pace():
    g = make_game("ncaab")
    s = bib.state_at(g, 600.0)
    full = _proj(bib.NaivePace(), g, 600.0)["naive_pace"]["full"]
    assert full[0] == pytest.approx(s.total / 600.0 * 2400.0)  # points so far / elapsed min x 40
    assert full[1] == pytest.approx(s.margin / 600.0 * 2400.0)


def test_pregame_rate_spreads_the_line_over_the_regulation_left():
    g = make_game("ncaab", pregame=(150.0, 6.0))
    s = bib.state_at(g, 1800.0)
    out = _proj(bib.PregameRate(), g, 1800.0)["pregame_rate"]
    assert out["full"][0] == pytest.approx(s.total + 150.0 * 600 / 2400)
    assert out["h2"][1] == pytest.approx(s.margin - s.home_period_pts[0] + s.away_period_pts[0] + 6.0 * 0.25)
    no_line = make_game("ncaab", pregame=None)
    assert bib.PregameRate().supports(no_line).reason == "no_pregame_line"


def test_pooled_rate_spans_naive_pace_and_the_pregame_line_off_ne_on():
    g = make_game("ncaab", pregame=(120.0, -10.0))
    naive = _proj(bib.NaivePace(), g, 900.0)["naive_pace"]["full"]
    pre = _proj(bib.PregameRate(), g, 900.0)["pregame_rate"]["full"]
    k0 = _proj(bib.PooledRate(0.0), g, 900.0)["pooled_rate_k0"]["full"]
    kinf = _proj(bib.PooledRate(1e12), g, 900.0)["pooled_rate_k1000000000000"]["full"]
    mid = _proj(bib.PooledRate(1200.0), g, 900.0)["pooled_rate_k1200"]["full"]
    assert k0 == pytest.approx(naive)
    assert kinf[0] == pytest.approx(pre[0], abs=1e-6) and kinf[1] == pytest.approx(pre[1], abs=1e-6)
    assert min(naive[0], pre[0]) < mid[0] < max(naive[0], pre[0])  # reached: strictly between, not either end


def test_pooled_pace_and_efficiency_read_the_observed_log_off_ne_on():
    extra = {"prior_possessions": 140.0}
    fast = make_game("ncaab", step=20, pregame=(140.0, 0.0), extra=extra)  # more possessions than the prior
    slow = make_game("ncaab", step=80, pregame=(140.0, 0.0), extra=extra)
    for cls, name in ((bib.PooledPace, "pooled_pace_k60"), (bib.PooledEfficiency, "pooled_efficiency_k60")):
        a = _proj(cls(60.0), fast, 1200.0)[name]["full"][0] - bib.state_at(fast, 1200.0).total
        b = _proj(cls(60.0), slow, 1200.0)[name]["full"][0] - bib.state_at(slow, 1200.0).total
        assert a != pytest.approx(b), name  # the rest-of-game projection moves with what the log shows
    huge = _proj(bib.PooledPace(1e9), fast, 1200.0)["pooled_pace_k1000000000"]["full"][0]
    pre = _proj(bib.PregameRate(), fast, 1200.0)["pregame_rate"]["full"][0]
    assert huge == pytest.approx(pre, abs=1e-3)  # infinite prior weight = the line
    assert bib.PooledPace().supports(make_game("ncaab")).reason == "no_prior_possessions"


def test_league_rate_refuses_without_a_walk_forward_rate_and_projects_with_one():
    assert bib.LeagueRate().supports(make_game("nba")).reason == "no_league_rate"
    g = make_game("nba", extra={"league_points_per_second": 0.08})
    s = bib.state_at(g, 1440.0)
    out = _proj(bib.LeagueRate(), g, 1440.0)["league_rate"]
    assert out["full"] == pytest.approx((s.total + 0.08 * 1440.0, s.margin))


def test_interval_projection_reaches_the_shipped_module(monkeypatch):
    from syndicate.features.shared import basketball_interval_projection as bip

    calls = []
    real = bip.project_interval

    def spy(pressure, scoring, probe, *, league_code):
        calls.append((len(pressure), probe, league_code))
        return real(pressure, scoring, probe, league_code=league_code)

    monkeypatch.setattr(bip, "project_interval", spy)
    g = make_game("wnba")
    s = bib.state_at(g, 900.0)
    out = _proj(bib.IntervalModule(), g, 900.0)["interval_projection"]
    assert calls and calls[-1] == (s.n_events, 900.0, "wnba")
    row = real(bib.IntervalModule().prepare(g)["pressure"][: s.n_events],
               [r for r in bib.IntervalModule().prepare(g)["scoring"] if r["clock_seconds"] <= 900.0], 900.0, league_code="wnba")
    q2_so_far = s.home_period_pts[1] + s.away_period_pts[1]
    assert out["q2"][0] == pytest.approx(q2_so_far + row["proj_rest_total"])  # the module's own number
    assert out["q2"][1] == s.home_period_pts[1] - s.away_period_pts[1]  # margin carried
    naive = _proj(bib.NaivePace(), g, 900.0)["naive_pace"]["full"][0]
    assert out["full"][0] != pytest.approx(naive)  # a different projector, not an alias


# ------------------------------------------------------------------------------------------------ re-sims

class _Frame(dict):
    """The two columns the harness reads off an engine frame (`athlete_id`, `player_name`)."""

    def __getitem__(self, key):
        val = dict.__getitem__(self, key)
        return _Col(val)


class _Col(list):
    def tolist(self):
        return list(self)


def _stub_simulate(record, rest_home=30, rest_away=25, ot=(0, 0)):
    def simulate(rng, gs):
        record.append(gs)
        reg = 2 if len(gs.home_period_pts) <= 2 and gs.period <= 2 else 4
        hp = list(gs.home_period_pts) + [0] * (reg - len(gs.home_period_pts))
        ap = list(gs.away_period_pts) + [0] * (reg - len(gs.away_period_pts))
        hp[-1] += rest_home
        ap[-1] += rest_away
        return {"ot_pts": [ot[0]] if ot[0] else []}, {"ot_pts": [ot[1]] if ot[1] else []}, hp, ap
    return simulate


def _college_extra():
    prior = {"home_id": "100", "away_id": "200", "neutral": False, "possessions": 68.0, "home_ppp": 1.05, "away_ppp": 1.0,
             "home_points": 71.0, "away_points": 68.0, "total": 139.0, "home_margin": 3.0, "ratings_season": 2026,
             "ratings_as_of": "2026-01-31", "prior_season_fallback": False, "home_games": 20, "away_games": 20}
    return {"college_resim": {"prior": prior, "season": 2026, "neutral": False, "player_priors": {"100": [], "200": []}}}


def _fake_college_inputs(monkeypatch):
    from syndicate.features.basketball_engine.engine import EventSimConfig
    from syndicate.features.ncaab import live_resim as lr

    def fake_build(date, home_id, away_id, *, neutral, priors, team_prior, league="ncaab", **kw):
        return {"home_players": _Frame(athlete_id=HOME5 + ["h6"], player_name=[f"H {p}" for p in HOME5 + ["h6"]]),
                "away_players": _Frame(athlete_id=AWAY5 + ["a6"], player_name=[f"A {p}" for p in AWAY5 + ["a6"]]),
                "cfg": EventSimConfig(possessions_per_game=float(team_prior.possessions)),
                "target_home_points": team_prior.home_points, "target_away_points": team_prior.away_points, "quarters": None}

    monkeypatch.setattr(lr, "build_engine_inputs", fake_build)


def test_college_resim_resumes_from_the_replay_state_and_anchors(monkeypatch):
    _fake_college_inputs(monkeypatch)
    calls = []
    g = make_game("ncaab", pregame=(140.0, 10.0), extra=_college_extra())
    proj = bib.Resim(sims=100, simulate=_stub_simulate(calls))
    prep = proj.prepare(g)
    assert not isinstance(prep, bib.Refusal)
    assert calls[0].period == 1 and calls[0].home_score == 0  # the tip sim for the anchor
    s = bib.state_at(g, 1800.0)
    out = proj.project(g, s, prep)
    gs = calls[-1]
    assert (gs.period, gs.seconds_remaining, gs.home_period_pts, gs.away_period_pts) == (2, 600, s.home_period_pts, s.away_period_pts)
    assert set(gs.home_on_floor) <= {f"H {p}" for p in HOME5 + ["h6"]}  # ids re-keyed onto the frames' names
    assert out["resim"]["full"] == pytest.approx((s.total + 55, s.margin + 5))
    # Anchored: the tip sim's margin is +5 (stub), the close +10 -> offset +5, scaled by 25% of regulation left.
    assert out["resim_anchored"]["full"][1] == pytest.approx(s.margin + 5 + 5 * 0.25, abs=0.02)
    assert out["resim_anchored"]["full"][0] == out["resim"]["full"][0]  # totals stay raw


def test_college_resim_mechanisms_reach_the_engine_call_off_ne_on(monkeypatch):
    from syndicate.features.ncaab import live_resim as lr

    _fake_college_inputs(monkeypatch)
    seen = []

    class Engine:
        params = type("Params", (), {"exact_target_calibration": False})()  # read by the per-game provenance

        def simulate_pbp_game_boxscore(self, *, rng, cfg, state, **kw):
            seen.append(cfg)
            return _stub_simulate([])(rng, state)

    monkeypatch.setattr(lr, "ncaab_engine", lambda *a, **k: Engine())
    g = make_game("ncaab", pregame=None, extra=_college_extra())
    for proj in (bib.Resim(sims=100), bib.Resim(sims=100, mechanisms={"endgame_foul_window_s": 120, "endgame_foul_p": 0.5})):
        proj.project(g, bib.state_at(g, 2280.0), proj.prepare(g))
    off, on = seen[0], seen[-1]
    assert off.endgame_foul_window_s == 0 and on.endgame_foul_window_s == 120 and on.endgame_foul_p == 0.5
    assert bib.Resim(mechanisms={"endgame_foul_window_s": 1}).name == "resim_mech"


def test_nba_resim_maps_names_and_applies_mechanisms_off_ne_on(monkeypatch):
    from syndicate.features.basketball_engine.engine import EventSimConfig
    from syndicate.features.nba import live_resim as lr

    loads = []

    def fake_load(date, home, away, *, root=None, league="nba"):
        loads.append((date, home, away, root, league))
        return {"home_players": _Frame(player_name=[f"Home {p}" for p in HOME5 + ["h6"]]),
                "away_players": _Frame(player_name=[f"Away {p}" for p in AWAY5 + ["a6"]]),
                "cfg": EventSimConfig(possessions_per_game=98.0)}

    monkeypatch.setattr(lr, "load_engine_inputs", fake_load)
    seen = []

    class Engine:
        def simulate_pbp_game_boxscore(self, *, rng, cfg, state, **kw):
            seen.append((cfg, state))
            return _stub_simulate([])(rng, state)

    import syndicate.features.shared.basketball_props_smart_sim as sm

    monkeypatch.setattr(sm, "_engine_for_league_local", lambda *a, **k: Engine())
    g = make_game("nba", extra={"engine_inputs_root": "/x/nba_source"})
    for proj in (bib.Resim(sims=100), bib.Resim(sims=100, mechanisms={"endgame_foul_window_s": 120})):
        out = proj.project(g, bib.state_at(g, 2500.0), proj.prepare(g))
        assert "resim_anchored" not in out and "resim" in out or "resim_mech" in out
    assert loads[0] == ("2026-02-01", "HOM", "AWY", "/x/nba_source", "nba")
    (off_cfg, off_state), (on_cfg, _s) = seen[0], seen[-1]
    assert off_cfg.endgame_foul_window_s == 0 and on_cfg.endgame_foul_window_s == 120
    assert off_state.home_on_floor and all(n.startswith("Home ") for n in off_state.home_on_floor)


def test_expensive_projectors_run_only_at_the_sim_times(monkeypatch):
    _fake_college_inputs(monkeypatch)
    calls = []
    g = make_game("ncaab", pregame=None, extra=_college_extra())
    res = bib.replay_game(g, [bib.NaivePace(), bib.Resim(sims=100, simulate=_stub_simulate(calls))])
    resim_times = sorted({r["elapsed"] for r in res["rows"] if r["projector"] == "resim"})
    assert resim_times == [0.0, 600.0, 1200.0, 1800.0, 2280.0]  # the tip (pregame) + the four bar points
    assert len(calls) == 5 * 100  # no separate anchor tip sim without a close to anchor to
    naive_times = {r["elapsed"] for r in res["rows"] if r["projector"] == "naive_pace"}
    assert len(naive_times) == 2400 // 30 - 1


def test_nba_tick_reads_the_tick_ladder_through_the_tick_function():
    ladder = {"segments": [{"idx": i, "cum_q": {"p50": 18.0 * i}} for i in range(1, 17)]}  # 6 pts/min, 3-min steps
    g = make_game("nba", extra={"tick_intervals": ladder})
    s = bib.state_at(g, 1500.0)  # 25:00 elapsed, Q3
    out = _proj(bib.NbaTick(), g, 1500.0)["nba_tick"]
    assert out["full"][0] == pytest.approx(max(s.total, s.total + 6.0 * (48 - 25)))
    h2_so_far = s.home_period_pts[2] + s.away_period_pts[2]
    assert out["h2"][0] == pytest.approx(h2_so_far + 6.0 * (48 - 25))
    assert out["full"][1] is None  # totals only
    assert bib.NbaTick().supports(make_game("nba")).reason == "no_smart_sim_intervals"  # off != on
    assert bib.NbaTick().supports(make_game("wnba", extra={"tick_intervals": ladder})).reason == "league_not_supported"


# ------------------------------------------------------------------------------------------------ scoring

def _result(game_id, rows, phase="regular"):
    return {"league": "ncaab", "game_id": game_id, "date": "2026-02-01", "phase": phase, "rows": rows}


def _row(proj, err, cp="10m", seg="full", t=600.0, merr=None):
    return {"projector": proj, "segment": seg, "elapsed": t, "frac": 0.25, "bucket": 0.25, "checkpoint": cp,
            "total": 100.0 + err, "margin": None if merr is None else 5.0 + merr, "actual_total": 100, "actual_margin": 5}


def test_summarize_and_the_paired_gate():
    results = [_result(f"g{i}", [_row("a", 2.0 + 0.1 * i, merr=-1.0), _row("b", 5.0 - 0.1 * i)]) for i in range(10)]
    summ = bib.summarize(results)
    cell = summ["ncaab"]["regular"]["a"]["full"]["10m"]
    assert cell["games"] == 10 and cell["total"]["mae"] == pytest.approx(2.45) and cell["total"]["bias"] == pytest.approx(2.45)
    assert cell["margin"] == {"n": 10, "mae": 1.0, "bias": -1.0}
    gate = bib.paired_delta(results, "a", "b")["ncaab"]["regular"]["full"]["10m"]
    assert gate["games"] == 10 and gate["delta"] == pytest.approx(2.45 - 4.55) and gate["verdict"] == "better"
    assert bib.paired_delta(results, "b", "a")["ncaab"]["regular"]["full"]["10m"]["verdict"] == "worse"


def test_compact_keeps_every_number_the_report_reads():
    g = make_game("ncaab", extra={"league_points_per_second": 0.06})
    res = bib.replay_game(g, [bib.NaivePace(), bib.PregameRate(), bib.LeagueRate()])
    small = bib.compact(res)
    assert "rows" not in small and small["cp_rows"]
    for by in ("checkpoint", "bucket"):
        assert bib.summarize([small], by=by) == bib.summarize([res], by=by)
        assert bib.paired_delta([small], "naive_pace", "pregame_rate", by=by) == bib.paired_delta([res], "naive_pace", "pregame_rate", by=by)


def test_walk_forward_calibration_apply_matches_production(monkeypatch):
    from syndicate.features.college_basketball import prior_calibration as pc
    from syndicate.features.ncaab import live_team_model as tm

    s = _script()
    prior = tm.NcaabGamePrior(home_id="1", away_id="2", neutral=False, possessions=68.0, home_ppp=1.1, away_ppp=1.0,
                              home_points=74.8, away_points=68.0, total=142.8, home_margin=6.8, ratings_season=2026,
                              ratings_as_of=dt.date(2026, 1, 31), prior_season_fallback=False, home_games=20, away_games=20)
    cal = pc.PriorCalibration("ncaab", 2026, dt.date(2026, 2, 1), calibrated=True, target="close", games=90, beta=1.1,
                              gamma=2.0, total_slope=0.75, total_prior_mean=140.0, total_target_mean=143.0)
    monkeypatch.setattr(pc, "calibration_for", lambda *a, **k: cal)
    monkeypatch.setattr(pc, "enabled", lambda *a, **k: True)
    prod = tm._calibrated(prior, dt.date(2026, 2, 1), league="ncaab", dirs=None, calibrate=None)
    assert s._calibrated(prior, cal) == prod
    assert prod.home_margin != prior.home_margin  # the fit is reached
    raw = s._calibrated(prior, None)
    assert raw.home_margin == prior.home_margin and raw.calibration["calibrated"] is False


# ------------------------------------------------------------------------------------------------ end to end (script)

def _write_substrate(root: Path, game: bib.ReplayGame):
    proc = root / "nba_source" / "data" / "processed"
    (proc / "rotation_stints").mkdir(parents=True)
    (proc / "pbp_events" / "2026").mkdir(parents=True)
    header = "league,season,season_type,date,event_id,home,away,official_home,official_away,score_match\n"
    (proc / "rotation_stints" / "games_2026-02-01.csv").write_text(
        header + f"nba,2026,regular,2026-02-01,g1,HOM,AWY,{game.meta.home.score},{game.meta.away.score},1\n", encoding="utf-8")
    rows = ["league,season,season_type,date,event_id,team,player_id,player_name,starter,box_minutes,stint_minutes,minutes_diff,within_1,box_pf,pbp_pf"]
    for pid, p in game.meta.box.items():
        rows.append(f"nba,2026,regular,2026-02-01,g1,{'HOM' if p.side == 'home' else 'AWY'},{pid},{p.name},{int(p.starter)},20,20,0,1,1,1")
    (proc / "rotation_stints" / "player_checks_2026-02-01.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    from dataclasses import asdict

    with gzip.open(proc / "pbp_events" / "2026" / "g1.jsonl.gz", "wt", encoding="utf-8") as fh:
        for ev in game.events:
            fh.write(json.dumps(asdict(ev)) + "\n")


def test_script_runs_end_to_end_on_a_written_substrate(tmp_path):
    s = _script()
    game = make_game("nba")
    _write_substrate(tmp_path / "data", game)
    out = tmp_path / "out"
    rc = s.main(["--league", "nba", "--season", "2026", "--data-root", str(tmp_path / "data"), "--workers", "1",
                 "--projectors", "naive_pace,interval_projection,league_rate,pregame_rate", "--out", str(out)])
    assert rc == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["games_scored"] == 1 and report["coverage"]["INTERSECTION"]["dates"] == 1
    cp = report["checkpoint"]["nba"]["regular"]
    assert cp["naive_pace"]["full"]["12m"]["games"] == 1
    assert report["prepare_refusals"]["pregame_rate"] == {"no_pregame_line": 1}  # named, never silent
    assert report["prepare_refusals"]["league_rate"] == {"no_league_rate": 1}  # one game: no walk-forward rate
    assert (out / "report.md").read_text(encoding="utf-8").count("| naive_pace |") >= 1
    # The rebuilt game equals the written one: same events, same finals, same box.
    task = {"league": "nba", "game_id": "g1", "date": "2026-02-01", "phase": "regular",
            "events_path": str(tmp_path / "data" / "nba_source" / "data" / "processed" / "pbp_events" / "2026" / "g1.jsonl.gz"),
            "game_row": {"event_id": "g1", "date": "2026-02-01", "season": "2026", "season_type": "regular", "home": "HOM",
                         "away": "AWY", "official_home": game.meta.home.score, "official_away": game.meta.away.score},
            "box_rows": [], "pregame": {}, "extra": {}}
    rebuilt = s.build_game(task)
    assert rebuilt.events == game.events and bib.segment_actuals(rebuilt) == bib.segment_actuals(game)


def test_tip_projection_reuses_the_anchor_tip_sim(monkeypatch):
    _fake_college_inputs(monkeypatch)
    calls = []
    g = make_game("ncaab", pregame=(140.0, 10.0), extra=_college_extra())
    res = bib.replay_game(g, [bib.Resim(sims=100, simulate=_stub_simulate(calls))])
    assert len(calls) == 5 * 100  # prepare's tip + 4 in-game points; t=0 reused, not re-simmed
    tip = [r for r in res["rows"] if r["projector"] == "resim" and r["checkpoint"] == "0m" and r["segment"] == "full"]
    assert tip and tip[0]["total"] == 55.0 and tip[0]["margin"] == 5.0
    assert not [r for r in res["rows"] if r["projector"] == "naive_pace"]  # not registered here


def test_tip_projectors_are_defined_even_with_a_play_logged_at_the_tip():
    """ESPN sometimes logs a scoring play AT the tip (elapsed 0). The rate projectors divide by elapsed time, so they
    refuse there by name; the line-based ones still project (measured: 2 of 1,391 NBA 2025-26 games)."""
    g = make_game("nba", extra={"league_points_per_second": 0.08})
    tip_score = _event("nba", -1, 0.0, "home", "free_throw", points=1, made=True)
    g = replace(g, events=(tip_score,) + g.events,
                meta=replace(g.meta, home=replace(g.meta.home, score=g.meta.home.score + 1)))
    s = bib.state_at(g, 0.0)
    assert s.total == 1
    for proj in (bib.NaivePace(), bib.IntervalModule()):
        assert proj.project(g, s, proj.prepare(g)).reason == "no_elapsed"
    pre = bib.PregameRate().project(g, s, None)["pregame_rate"]["full"]
    assert pre[0] == pytest.approx(1 + 140.0)
    res = bib.replay_game(g, [bib.IntervalModule(), bib.PregameRate()])
    assert max(abs(r["total"]) for r in res["rows"] if r["projector"] == "interval_projection") < 1000


# ------------------------------------------------------------------- production's college switches (2026-11-07)

_COLLEGE_SWITCHES = ("SYNDICATE_NCAAB_HALF_SPLIT", "SYNDICATE_NCAAB_EXACT_TARGET", "SYNDICATE_NCAAB_LIVE_MECHANISMS")


def test_college_production_switches_reach_the_engine_inputs_off_ne_on(monkeypatch):
    """live-odds-worker runs the NCAAB re-sim with SYNDICATE_NCAAB_HALF_SPLIT / _EXACT_TARGET / _LIVE_MECHANISMS set
    and refresh-worker with none (measured 2026-11-07); the first replay ran with none. Set in the replay env they
    must reach production's OWN `build_engine_inputs` and engine binding -- and the per-game provenance must read
    them off those inputs, not off the env."""
    from syndicate.features.ncaab import live_resim as lr

    monkeypatch.setattr(lr, "team_frame", lambda rows, **kw: _Frame(athlete_id=HOME5, player_name=[f"P {p}" for p in HOME5]))
    extra = _college_extra()
    extra["college_resim"]["player_priors"] = {"100": [{"min_proj": 30.0}], "200": [{"min_proj": 30.0}]}
    g = make_game("ncaab", pregame=None, extra=extra)  # no close: prepare runs no tip sim
    for key in _COLLEGE_SWITCHES:
        monkeypatch.delenv(key, raising=False)
    off = bib.Resim(sims=100).prepare(g)
    monkeypatch.setenv("SYNDICATE_NCAAB_HALF_SPLIT", "1")
    monkeypatch.setenv("SYNDICATE_NCAAB_EXACT_TARGET", "1")
    monkeypatch.setenv("SYNDICATE_NCAAB_LIVE_MECHANISMS", json.dumps({"endgame_foul_window_s": 120, "endgame_foul_p_by_deficit": [0.1, 0.2]}))
    on = bib.Resim(sims=100).prepare(g)
    assert off["provenance"] == {"halfSplit": False, "cfgFields": [], "exactTarget": False}
    assert on["provenance"] == {"halfSplit": True, "cfgFields": ["endgame_foul_p_by_deficit", "endgame_foul_window_s"],
                                "exactTarget": True}
    assert off["inputs"]["quarters"] is None
    assert on["inputs"]["quarters"][0]["home_pts_mu"] == pytest.approx(71.0 * lr.H1_SHARE)
    assert on["inputs"]["cfg"].endgame_foul_window_s == 120 and off["inputs"]["cfg"].endgame_foul_window_s == 0
    assert lr.ncaab_engine(league="ncaab").params.exact_target_calibration is True  # the engine the re-sim binds


def test_engine_provenance_is_recorded_per_game_and_counted_in_the_report(monkeypatch):
    for key in _COLLEGE_SWITCHES:
        monkeypatch.delenv(key, raising=False)
    _fake_college_inputs(monkeypatch)
    g = make_game("ncaab", pregame=(140.0, 10.0), extra=_college_extra())
    res = bib.replay_game(g, [bib.Resim(sims=100, simulate=_stub_simulate([])), bib.PregameRate()])
    prov = {"halfSplit": False, "cfgFields": [], "exactTarget": False}
    assert res["provenance"] == {"resim": prov, "resim_anchored": prov}  # pregame_rate has no engine inputs
    s = _script()
    assert s.college_switches("nba") is None
    assert s.college_switches("ncaab", {}) == {"half_split": False, "exact_target": False, "live_mechanisms": []}
    assert s.college_switches("ncaab", {"SYNDICATE_NCAAB_HALF_SPLIT": "1", "SYNDICATE_NCAAB_EXACT_TARGET": "true",
                                        "SYNDICATE_NCAAB_LIVE_MECHANISMS": '{"endgame_foul_window_s": 120}'}) == \
        {"half_split": True, "exact_target": True, "live_mechanisms": ["endgame_foul_window_s"]}
    from types import SimpleNamespace

    args = SimpleNamespace(league="ncaab", season=2026, phases=None, projector_names=["pregame_rate", "resim"], sims=100,
                           mechanisms_obj={}, sim_times=None, seed=1, sample=None, code_sha="x", baseline="pregame_rate")
    report = s.build_report([bib.compact(res), bib.compact(res)], {}, args)
    assert report["engine_provenance"]["resim"] == {json.dumps(prov, sort_keys=True): 2}
    assert report["config"]["college_switches"]["half_split"] is False
    assert "College engine switches in the replay env" in s.markdown(report)
