"""Tests for syndicate/features/nba/live_resim.py (P3, lane nba-native-live-resim).

Summaries come from P2's synthetic ESPN builder (`tests/basketball_pbp_fixtures.Game`); engine inputs from P1's
`tests/basketball_engine_fixtures.synthetic_game_kwargs`. Hermetic: no network, no data/."""
from __future__ import annotations

import numpy as np
import pytest

from syndicate.features.nba import live_resim as lr
from tests.basketball_engine_fixtures import synthetic_game_kwargs
from tests.basketball_pbp_fixtures import Game


def _in_q2():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").shot(1, "10:30", "away", "a1", pts=3).foul(1, "9:00", "home", "h2")
    g.end_period(1)
    g.shot(2, "11:40", "home", "h1").sub(2, "10:00", "away", "a6", "a5").shot(2, "9:30", "away", "a6")
    return g


# ------------------------------------------------------------------------------------------- resume state

def test_resume_mid_period_carries_score_split_clock_fouls_and_fives():
    st, gs, facts = lr.resume_from_summary(_in_q2().summary(), date="2026-01-15")
    assert (gs.period, gs.seconds_remaining) == (2, 570)
    assert gs.home_period_pts == (2, 2) and gs.away_period_pts == (3, 2)
    assert (facts.home_score, facts.away_score) == (4, 5)
    assert set(gs.away_on_floor) == {"A1", "A2", "A3", "A4", "A6"}  # ESPN display names, re-keyed later
    assert gs.home_player_fouls == {"H2": 1} and gs.away_player_fouls == {}
    assert gs.home_team_fouls == 0  # the Q1 foul is not in the Q2 bucket


def test_resume_at_a_quarter_end_starts_the_next_period_from_its_tip():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").end_period(1)
    _st, gs, _f = lr.resume_from_summary(g.summary())
    assert (gs.period, gs.seconds_remaining) == (2, None)
    assert gs.home_period_pts == (2, 0) and gs.away_period_pts == (0, 0)
    assert gs.home_on_floor == () and gs.possession is None  # a new period: lineup sampled, tip is a coin flip


def test_end_of_regulation_tied_resumes_overtime_and_decided_refuses():
    tied = Game("nba", state="in")
    tied.shot(1, "11:00", "home", "h1").shot(4, "1:00", "away", "a1").end_period(4)
    _st, gs, _f = lr.resume_from_summary(tied.summary())
    assert gs.period == 5 and gs.seconds_remaining is None
    decided = Game("nba", state="in")
    decided.shot(1, "11:00", "home", "h1").end_period(4)
    assert lr.resume_from_summary(decided.summary()) == lr.NbaResimRefusal("regulation_over")


@pytest.mark.parametrize("state,reason", [("pre", "game_not_started"), ("post", "game_final"),
                                          ("halftime??", "game_state_unrecognised")])
def test_status_refusals_are_named(state, reason):
    g = Game("nba", state=state)
    g.shot(1, "11:00", "home", "h1")
    assert lr.resume_from_summary(g.summary()).reason == reason


def test_pbp_score_disagreeing_with_the_official_score_is_refused():
    g = _in_q2()
    out = lr.resume_from_summary(g.summary(official=(9, 5)))
    assert isinstance(out, lr.NbaResimRefusal) and out.reason == "pbp_score_mismatch"


# ------------------------------------------------------------------------------------------- inputs

def _kwargs(seed=7):
    kw = synthetic_game_kwargs(np.random.default_rng(seed), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    return kw


def test_engine_inputs_round_trip_and_named_refusals(tmp_path):
    kw = {k: k for k in lr._INPUT_KEYS}  # values are opaque to the store
    p = lr.persist_engine_inputs("2026-01-15", "gsw", "nyk", kw, root=tmp_path)
    assert p.name == "GSW_NYK.pkl" and "engine_inputs" in str(p)
    assert lr.load_engine_inputs("2026-01-15", "GSW", "NYK", root=tmp_path) == kw
    assert lr.load_engine_inputs("2026-01-15", "BOS", "MIA", root=tmp_path).reason == "no_pregame_inputs"
    lr.persist_engine_inputs("2026-01-15", "LAL", "SAC", {"cfg": 1}, root=tmp_path)
    out = lr.load_engine_inputs("2026-01-15", "LAL", "SAC", root=tmp_path)
    assert out.reason == "pregame_inputs_incomplete" and "home_players" in out.detail


def test_names_map_across_accents_and_suffixes_and_a_partial_five_is_dropped():
    import pandas as pd
    from syndicate.features.basketball_engine.resume import GameState

    hf = pd.DataFrame({"player_name": ["Jusuf Nurkić", "Jaren Jackson Jr.", "A", "B", "C"]})
    af = pd.DataFrame({"player_name": ["X", "Y", "Z", "W", "V"]})
    gs = GameState(period=2, seconds_remaining=300, home_period_pts=(1, 1), away_period_pts=(1, 1),
                   home_on_floor=("JUSUF NURKIC", "Jaren Jackson", "A", "B", "C"),
                   away_on_floor=("X", "Y", "Z", "W", "Nobody"),
                   home_player_fouls={"Jusuf Nurkic": 3}, away_player_fouls={"Nobody": 6})
    new, rep = lr.map_state_names(gs, hf, af)
    assert new.home_on_floor == ("Jusuf Nurkić", "Jaren Jackson Jr.", "A", "B", "C")
    assert new.away_on_floor == () and rep["away_on_floor_matched"] == 4
    assert new.home_player_fouls == {"Jusuf Nurkić": 3} and new.away_player_fouls == {}


# ------------------------------------------------------------------------------------------- the re-sim

def _fake(totals):
    it = iter(totals)

    def simulate(rng, gs):
        h, a = next(it)
        return None, None, [h, 0, 0, 0], [a, 0, 0, 0]
    return simulate


def test_resim_aggregates_distributions_and_win_prob():
    draws = [(110, 100)] * 60 + [(100, 104)] * 40
    out = lr.resim_live_game({}, None, sims=100, simulate=_fake(draws))
    assert out["sims_run"] == 100 and out["home_win_prob"] == 0.6
    assert out["total_dist"] == {"204": 40, "210": 60}
    assert out["margin_dist"] == {"-4": 40, "10": 60}
    assert out["segments"]["q1"]["total_mean"] == pytest.approx(0.6 * 210 + 0.4 * 204)


def test_the_budget_is_a_refusal_never_a_thinner_number():
    t = iter(range(1000))
    out = lr.resim_live_game({}, None, sims=100, simulate=_fake([(1, 0)] * 100), deadline=50,
                             clock=lambda: next(t))
    assert out.reason == "budget_exhausted" and out.detail == "50/100"


def test_too_few_sims_and_engine_errors_are_refused_by_name():
    assert lr.resim_live_game({}, None, sims=10).reason == "sims_below_floor"

    def boom(rng, gs):
        raise ValueError("bad state")
    assert lr.resim_live_game({}, None, sims=100, simulate=boom).reason == "engine_resume_rejected"


def test_stable_seed_reproduces_an_unchanged_state():
    assert lr.stable_seed("401", 55) == lr.stable_seed("401", 55) != lr.stable_seed("401", 56)


def test_real_engine_resume_moves_the_answer_the_right_way():
    """Reachability: the resumed state reaches the engine. Up 15 at 5:00 Q4 must be nearly won; down 15 lost."""
    from syndicate.features.basketball_engine.resume import GameState

    kw = _kwargs()
    up = GameState(period=4, seconds_remaining=300, home_period_pts=(30, 30, 30, 15), away_period_pts=(25, 25, 25, 15))
    down = GameState(period=4, seconds_remaining=300, home_period_pts=(25, 25, 25, 15), away_period_pts=(30, 30, 30, 15))
    r_up = lr.resim_live_game(kw, up, sims=100, base_seed=1)
    r_down = lr.resim_live_game(kw, down, sims=100, base_seed=1)
    assert r_up["home_win_prob"] > 0.9 > 0.1 > r_down["home_win_prob"]
    # completed periods come from the state, so every draw's Q1-Q3 total is exactly the actual
    assert set(r_up["segments"]["q1"]["total_dist"]) == {"55"}
    assert r_up == lr.resim_live_game(kw, up, sims=100, base_seed=1)  # seeded: identical


# ------------------------------------------------------------------------------------------- lanes / snapshot

def test_a_refused_lane_carries_no_probability_at_all():
    lane = lr.build_game_lens(None, lr.NbaResimRefusal("no_pregame_inputs", "GSW_NYK.pkl"))[0]
    assert lane["source"] == lr.PREGAME_LENS_SOURCE == "pregame_only"
    assert "modelHomeWinProb" not in lane and "projection" not in lane
    assert lane["liveResimRefusal"] == "no_pregame_inputs"


def test_a_success_lane_carries_the_distributions_the_join_prices():
    facts = lr.ResumeFacts("401", "GSW", "NYK", 50, 48, 2, 0.0, None, 99, "t")
    res = {"sims_run": 200, "home_win_prob": 0.55, "total_mean": 220.0, "home_margin_mean": 2.0,
           "total_dist": {"220": 200}, "margin_dist": {"2": 200}, "segments": {}}
    lane = lr.build_game_lens(facts, res)[0]
    assert lane["source"] == "live_resim" and lane["simsRun"] == 200 and lane["modelHomeWinProb"] == 0.55
    assert lane["projection"]["totalRunsDist"] == {"220": 200} and lane["projection"]["marginDist"] == {"2": 200}


def test_snapshot_publishes_one_lane_per_live_game_and_counts_refusals(tmp_path, monkeypatch):
    live = _in_q2().summary()
    sb = {"events": [
        {"id": "999", "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]},
        {"id": "998", "competitions": [{"status": {"type": {"state": "pre"}}, "competitors": []}]},
    ]}
    monkeypatch.setattr(lr, "resim_live_game", lambda *a, **k: {
        "sims_run": 200, "home_win_prob": 0.4, "total_mean": 1.0, "home_margin_mean": -1.0,
        "total_dist": {"1": 200}, "margin_dist": {"-1": 200}, "segments": {}})
    snap = lr.build_live_lens_snapshot("2026-01-15", fetch_scoreboard=lambda *_a: sb,
                                       fetch_summary=lambda *_a: live, inputs_root=tmp_path)
    assert len(snap["games"]) == 1  # the pregame game is not a live game
    assert snap["refusalsByReason"] == {"no_pregame_inputs": 1}
    lr.persist_engine_inputs("2026-01-15", "GSW", "NYK", {k: _kwargs()[k] if k in _kwargs() else None
                                                          for k in lr._INPUT_KEYS} | {
        "home_players": _kwargs()["home_players"], "away_players": _kwargs()["away_players"]}, root=tmp_path)
    snap = lr.build_live_lens_snapshot("2026-01-15", fetch_scoreboard=lambda *_a: sb,
                                       fetch_summary=lambda *_a: live, inputs_root=tmp_path)
    lane = snap["games"][0]["gameLens"][0]
    assert lane["source"] == "live_resim" and snap["refusalsByReason"] == {}
    g0 = snap["games"][0]
    assert (g0["home"], g0["away"]) == ("Golden State Warriors", "New York Knicks")  # what the join keys on
    assert (g0["home_code"], g0["away_code"]) == ("GSW", "NYK")


# ------------------------------------------------------------------------------------------- live props

def test_live_props_price_actual_plus_remainder_and_refuse_certainty():
    result = {"sims_run": 100, "player_remainders": {"home": {"Jaren Jackson Jr.": {
        "pts": {"0": 20, "4": 50, "10": 30}, "reb": {"0": 100}}}, "away": {"Nobody": {"pts": {"2": 100}}}}}
    actuals = {"jaren jackson": {"pts": 18, "reb": 9}}
    lines = {("jaren jackson", "pts"): 21.5, ("jaren jackson", "reb"): 6.5, ("nobody", "pts"): 10.5}
    rows, cov = lr.build_live_props(result, actuals, lines)
    by = {r["prop"]: r for r in rows}
    pts = by["player_points"]
    assert pts["liveModelProbOver"] == 0.8 and pts["actualSoFar"] == 18.0  # 18+4 and 18+10 clear 21.5
    assert pts["liveProjection"] == pytest.approx(18 + 0.5 * 4 + 0.3 * 10)
    reb = by["player_rebounds"]  # 9 already banked over 6.5: decided, so no probability is published
    assert reb["liveModelProbOver"] is None and reb["unpricedReason"] == "certainty_refused"
    assert cov == {"players_simmed": 2, "rows": 2, "priced": 1, "no_actual": 1, "certainty_refused": 1}


def test_lines_are_the_mode_across_books_for_this_game_only(tmp_path):
    f = tmp_path / "props.csv"
    hdr = "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
    rows = [
        "t,e1,c,dk,DK,player_points,Over,Stephen Curry,27.5,-110,t,Golden State Warriors,New York Knicks",
        "t,e1,c,fd,FD,player_points,Over,Stephen Curry,26.5,-110,t,Golden State Warriors,New York Knicks",
        "t,e1,c,mg,MG,player_points,Over,Stephen Curry,26.5,-110,t,Golden State Warriors,New York Knicks",
        "t,e1,c,mg,MG,player_points,Under,Stephen Curry,30.5,-110,t,Golden State Warriors,New York Knicks",
        "t,e2,c,dk,DK,player_points,Over,LeBron James,24.5,-110,t,Los Angeles Lakers,Sacramento Kings",
        "t,e1,c,dk,DK,h2h,Golden State Warriors,,,-150,t,Golden State Warriors,New York Knicks",
    ]
    f.write_text(hdr + "\n".join(rows) + "\n", encoding="utf-8")
    out = lr.lines_from_props_csv(f, "Golden State Warriors", "New York Knicks")
    assert out == {("stephen curry", "pts"): 26.5}
    assert lr.lines_from_props_csv(tmp_path / "missing.csv", "A", "B") == {}


def test_actuals_come_from_the_live_box_and_a_bad_cell_is_not_a_zero():
    s = _in_q2().summary(pf={"h2": 1})
    s["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][1] = "--"  # H1's PTS unreadable
    act = lr.actuals_from_summary(s)
    assert "pts" not in act.get("h1", {})
    assert act["h2"]["pts"] == 0  # a genuine zero survives


def test_snapshot_carries_live_props_and_names_the_join_keys_on(tmp_path, monkeypatch):
    live = _in_q2().summary()
    sb = {"events": [{"id": "999", "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]}]}
    kw = _kwargs()
    lr.persist_engine_inputs("2026-01-15", "GSW", "NYK", {**{k: None for k in lr._INPUT_KEYS}, **kw}, root=tmp_path)
    csv = lr.props_csv_path("2026-01-15", root=tmp_path)
    csv.write_text("market,outcome_name,player_name,point,home_team,away_team\n"
                   "player_points,Over,H1,10.5,Golden State Warriors,New York Knicks\n", encoding="utf-8")
    monkeypatch.setattr(lr, "resim_live_game", lambda *a, **k: {
        "sims_run": 200, "home_win_prob": 0.4, "total_mean": 1.0, "home_margin_mean": -1.0,
        "total_dist": {"1": 200}, "margin_dist": {"-1": 200}, "segments": {},
        "player_remainders": {"home": {"H1": {"pts": {"6": 100, "12": 100}}}, "away": {}}})
    snap = lr.build_live_lens_snapshot("2026-01-15", fetch_scoreboard=lambda *_a: sb,
                                       fetch_summary=lambda *_a: live, inputs_root=tmp_path)
    g = snap["games"][0]
    assert (g["away_name"], g["home_name"]) == ("New York Knicks", "Golden State Warriors")
    assert g["status"]["detailedState"] == "In Progress"
    assert g["livePropsCoverage"]["lines_available"] == 1
    # H1 has 0 banked in the fixture box (PTS column), 6 or 12 remaining -> half the draws clear 10.5
    assert [(r["playerName"], r["prop"], r["liveModelProbOver"]) for r in g["liveProps"]] == [("H1", "player_points", 0.5)]


# ------------------------------------------------------------------------------------------- pregame persist hook

def test_pregame_engine_call_persists_inputs_once_per_game_and_changes_nothing(monkeypatch):
    from syndicate.features.shared import basketball_props_smart_sim as bps

    kw = _kwargs(seed=3)
    for side, team in (("home_players", "GSW"), ("away_players", "NYK")):
        kw[side] = kw[side].assign(team=team, asof_date="2026-01-15")
    calls = []
    monkeypatch.setattr(lr, "persist_engine_inputs", lambda d, h, a, k, **_: calls.append((d, h, a, sorted(k))) or _P())
    bps._PERSISTED_ENGINE_INPUT_KEYS.clear()

    def run(seed):
        rng = np.random.default_rng(seed)
        return bps._simulate_pbp_game_boxscore_local(league_code="nba", rng=rng, **kw)

    a = run(5)
    b = run(5)  # a second draw of the SAME game: no second write
    assert len(calls) == 1 and calls[0][:3] == ("2026-01-15", "GSW", "NYK")
    assert set(lr._INPUT_KEYS) - set(calls[0][3]) <= {"cfg", "quarters", "home_team_adj", "away_team_adj",
                                                      "home_lineups", "away_lineups", "home_lineup_weights",
                                                      "away_lineup_weights", "target_home_points", "target_away_points"}
    # same seed, same output -- the hook is write-only
    assert a[2] == b[2] and a[3] == b[3]
    bps._PERSISTED_ENGINE_INPUT_KEYS.clear()
    monkeypatch.setattr(lr, "persist_engine_inputs", lambda *a_, **k_: (_ for _ in ()).throw(OSError("disk full")))
    c = run(5)  # a failing write never reaches the sim
    assert c[2] == a[2] and c[3] == a[3]


class _P:
    def stat(self):
        class _S:
            st_size = 1
        return _S()


# ------------------------------------------------------------------------------------------- live mechanisms switch

def test_live_mechanisms_absent_or_bad_is_off_and_known_fields_pass():
    assert lr.live_mechanisms_from_env({}) == {}
    assert lr.live_mechanisms_from_env({lr.LIVE_MECHANISMS_ENV: ""}) == {}
    assert lr.live_mechanisms_from_env({lr.LIVE_MECHANISMS_ENV: "{not json"}) == {}
    assert lr.live_mechanisms_from_env({lr.LIVE_MECHANISMS_ENV: '{"endgame_foul_p": 0.5, "made_up": 1}'}) == {}
    on = lr.live_mechanisms_from_env({lr.LIVE_MECHANISMS_ENV: '{"endgame_foul_window_s": 120, "endgame_foul_p": 0.5}'})
    assert on == {"endgame_foul_window_s": 120, "endgame_foul_p": 0.5}


def test_with_live_mechanisms_keeps_pregame_values_and_off_is_the_same_object():
    from syndicate.features.shared.basketball_props_smart_sim import EventSimConfigLocal

    cfg = EventSimConfigLocal(possessions_per_game=101.5)
    inputs = {"cfg": cfg, "home_players": 1}
    assert lr.with_live_mechanisms(inputs, {})["cfg"] is cfg
    out = lr.with_live_mechanisms(inputs, {"endgame_foul_window_s": 120})["cfg"]
    assert out.possessions_per_game == 101.5 and out.endgame_foul_window_s == 120 and out.endgame_foul_p == 0.0

# ------------------------------------------------------------------------------------------- tick / loop

def test_loop_is_off_unless_explicitly_on():
    assert lr.nba_live_resim_enabled({}) is False
    assert lr.nba_live_resim_enabled({lr.LIVE_RESIM_ENV: "0"}) is False
    assert lr.nba_live_resim_enabled({lr.LIVE_RESIM_ENV: "on"}) is True


def test_oversize_snapshot_drops_props_never_game_lines():
    snap = {"games": [{"gameLens": [{"source": "live_resim", "simsRun": 200}], "liveProps": [{"x": "y" * 500}]}]}
    out, size = lr.fit_snapshot_to_budget(snap, max_bytes=200)
    g = out["games"][0]
    assert g["liveProps"] == [] and g["livePropsRefusal"] == "props_over_size_budget"
    assert g["gameLens"] == [{"source": "live_resim", "simsRun": 200}] and out["propsDroppedForSize"] is True
    small, n = lr.fit_snapshot_to_budget({"games": []}, max_bytes=200)
    assert "propsDroppedForSize" not in small and n < 200


def test_tick_writes_the_snapshot_and_reports(monkeypatch, tmp_path):
    written = {}
    monkeypatch.setattr(lr, "build_live_lens_snapshot", lambda d, **k: {
        "games": [{"gameLens": [{"source": "live_resim"}]}, {"gameLens": [{"source": "pregame_only"}]}],
        "refusalsByReason": {"no_pregame_inputs": 1}})
    import syndicate.features.shared.refresh_state_store as store
    monkeypatch.setattr(store, "write_json_file", lambda path, payload: written.update(path=path, payload=payload))
    st = lr.run_live_resim_tick("2026-10-20")
    assert st["written"] and st["games"] == 2 and st["resimmed"] == 1
    assert written["path"].name == "nba_live_resim.json"


# ------------------------------------------------------------------------------------------- page-lens merge

def test_page_lens_merges_native_lanes_and_props_for_the_same_date_only(monkeypatch):
    from syndicate.features.nba import live_lens as page

    resim = {"date": "2026-10-20", "generatedAt": "t", "refusalsByReason": {},
             "games": [{"event_id": "401", "gameLens": [{"source": "live_resim"}], "liveProps": [{"p": 1}]}]}
    monkeypatch.setattr(page, "read_json_file", lambda path: resim)
    games = [{"event_id": "401", "home": "BOS"}, {"event_id": "402"}]
    info = page._attach_native_resim(games, "2026-10-20")
    assert info["merged"] == 1 and games[0]["gameLens"] == [{"source": "live_resim"}] and "gameLens" not in games[1]
    games2 = [{"event_id": "401"}]
    assert page._attach_native_resim(games2, "2026-10-21")["reason"] == "native_resim_snapshot_other_date"
    assert "gameLens" not in games2[0]
