"""NCAAB live re-sim (lane ncaab-native-live-tier, P4): inputs, refusals, rotation, size, engine reachability."""

from __future__ import annotations

import csv
import datetime as dt
import json

import numpy as np
import pytest

from syndicate.features.ncaab import live_resim as lr
from syndicate.features.ncaab import live_team_model as tm

PRIOR_COLS = ("season", "as_of", "team_id", "athlete_id", "player_name", "games", "minutes", "min_proj", "starter_prob",
              "last_game", "prior_season_minutes") + tuple(f"{k}_pm" for k in lr.RATE_STATS)
RATES = {"pts_pm": 0.42, "fga_pm": 0.33, "fgm_pm": 0.15, "threes_att_pm": 0.13, "threes_pm": 0.045, "fta_pm": 0.11,
         "ftm_pm": 0.08, "oreb_pm": 0.04, "dreb_pm": 0.1, "reb_pm": 0.14, "ast_pm": 0.07, "tov_pm": 0.055, "stl_pm": 0.03,
         "blk_pm": 0.015, "pf_pm": 0.075}


def _write_priors(directory, as_of, teams=("10", "20"), n=9):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"player_priors_2026_asof_{as_of.replace('-', '')}.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=PRIOR_COLS)
        w.writeheader()
        for t in teams:
            for i in range(n):
                w.writerow({"season": 2026, "as_of": as_of, "team_id": t, "athlete_id": f"{t}{i}", "player_name": f"P{t}_{i}",
                            "games": 5, "minutes": 100, "min_proj": [34, 32, 30, 28, 26, 20, 15, 10, 5, 2][i],
                            "starter_prob": 1.0 if i < 5 else 0.0, "last_game": as_of, "prior_season_minutes": 0, **RATES})
    return path


def _team_prior(h="10", a="20"):
    return tm.NcaabGamePrior(home_id=h, away_id=a, neutral=False, possessions=68.0, home_ppp=1.08, away_ppp=1.02,
                             home_points=73.0, away_points=69.0, total=142.0, home_margin=4.0, ratings_season=2026,
                             ratings_as_of=dt.date(2026, 1, 9), prior_season_fallback=False, home_games=10, away_games=10)


def test_priors_newest_on_or_before_the_game_date(tmp_path):
    _write_priors(tmp_path, "2026-01-10")
    _write_priors(tmp_path, "2026-01-12")
    assert lr.load_player_priors(dt.date(2026, 1, 11), dirs=[tmp_path]).as_of == dt.date(2026, 1, 10)
    assert lr.load_player_priors(dt.date(2026, 1, 12), dirs=[tmp_path]).as_of == dt.date(2026, 1, 12)
    r = lr.load_player_priors(dt.date(2026, 1, 9), dirs=[tmp_path])
    assert isinstance(r, lr.NcaabResimRefusal) and r.reason == "no_player_priors"


def test_frame_contract_minutes_and_starters(tmp_path):
    _write_priors(tmp_path, "2026-01-10")
    pri = lr.load_player_priors(dt.date(2026, 1, 10), dirs=[tmp_path])
    frame = lr.team_frame(pri.by_team["10"], team_code="AAA", date="2026-01-10")
    assert frame["_sim_min"].sum() == pytest.approx(lr.TEAM_MINUTES, abs=1e-6)
    assert int(frame["is_starter"].sum()) == 5
    for k in lr.RATE_STATS:
        assert f"_prior_{k}_pm" in frame.columns and (frame[f"_prior_{k}_pm"] > 0).all(), k
    for col in ("player_name", "starter_prob", "pred_pts", "team", "asof_date"):
        assert col in frame.columns


def test_thin_rotation_refuses(tmp_path):
    _write_priors(tmp_path, "2026-01-10", n=6)
    pri = lr.load_player_priors(dt.date(2026, 1, 10), dirs=[tmp_path])
    r = lr.team_frame(pri.by_team["10"], team_code="AAA", date="2026-01-10")
    assert isinstance(r, lr.NcaabResimRefusal) and r.reason == "thin_rotation"


def test_inputs_refuse_by_name(tmp_path):
    _write_priors(tmp_path, "2026-01-10")
    pri = lr.load_player_priors(dt.date(2026, 1, 10), dirs=[tmp_path])
    r = lr.build_engine_inputs("2026-01-10", "10", "99", neutral=False, priors=pri, team_prior=_team_prior("10", "99"))
    assert isinstance(r, lr.NcaabResimRefusal) and r.reason == "team_has_no_player_priors"
    r = lr.build_engine_inputs("2026-01-10", "10", "20", neutral=False, priors=pri,
                               team_prior=tm.NcaabPriorRefusal("team_unrated", "x"))
    assert isinstance(r, lr.NcaabResimRefusal) and r.reason == "team_unrated"
    ok = lr.build_engine_inputs("2026-01-10", "10", "20", neutral=False, priors=pri, team_prior=_team_prior())
    assert ok["cfg"].possessions_per_game == 68.0 and ok["target_home_points"] == 73.0
    assert ok["_provenance"]["playerPriorsAsOf"] == "2026-01-10"


def _fake_simulate(margin=3):
    def simulate(rng, gs):
        h = 70 + int(rng.integers(0, 10))
        return {}, {}, [h // 2, h - h // 2], [(h - margin) // 2, (h - margin) - (h - margin) // 2]
    return simulate


def test_resim_aggregates_and_floors():
    r = lr.resim_live_game({}, None, sims=100, simulate=_fake_simulate())
    assert r["sims_run"] == 100 and r["home_win_prob"] == 1.0 and set(r["segments"]) == {"h1", "h2"}
    assert lr.resim_live_game({}, None, sims=50, simulate=_fake_simulate()).reason == "sims_below_floor"


def test_budget_discards_partial_draws():
    ticks = iter(range(10_000))
    r = lr.resim_live_game({}, None, sims=100, simulate=_fake_simulate(), deadline=40, clock=lambda: next(ticks))
    assert isinstance(r, lr.NcaabResimRefusal) and r.reason == "budget_exhausted"


def test_refusal_lane_carries_no_probability():
    lane = lr.build_game_lens(None, lr.NcaabResimRefusal("thin_rotation", "x"))[0]
    assert lane["source"] == lr.PREGAME_LENS_SOURCE and "modelHomeWinProb" not in lane
    assert lane["liveResimRefusal"] == "thin_rotation"


def test_board_name_prefers_the_odds_spelling():
    odds = {"duke": "Duke Blue Devils"}
    assert lr.board_name("Duke Blue Devils", odds) == ("Duke Blue Devils", "odds")
    assert lr.board_name("Duke", odds) == ("Duke Blue Devils", "odds")
    assert lr.board_name("Nowhere Tech", odds) == ("Nowhere Tech", "espn_display")


def test_two_hundred_game_slate_fits_the_budget():
    r = lr.resim_live_game({}, None, sims=200, simulate=_fake_simulate())
    facts = lr.ResumeFacts("1", "10", "20", 40, 38, 2, 600.0, "home", 300, "2026-01-10T01:00:00+00:00")
    games = [lr._lane_row(str(i), {"home": "Home U", "away": "Away St"}, facts, r, {"home_on_floor_matched": 5},
                          {"ratingsAsOf": "2026-01-09"}) for i in range(200)]
    snap = {"sport": "ncaab", "games": games}
    per_game = len(json.dumps(games[0], separators=(",", ":")))
    snap, size = lr.fit_snapshot_to_budget(snap)
    assert per_game <= lr.MAX_LANE_BYTES and size <= lr.MAX_SNAPSHOT_BYTES, (per_game, size)


def test_oversize_lane_loses_its_histograms_not_its_number():
    r = lr.resim_live_game({}, None, sims=100, simulate=_fake_simulate())
    r["total_dist"] = {str(i): 1 for i in range(5000)}
    facts = lr.ResumeFacts("1", "10", "20", 40, 38, 2, 600.0, "home", 300, "t")
    snap = {"games": [lr._lane_row("1", {}, facts, r)]}
    snap, _size = lr.fit_snapshot_to_budget(snap)
    lane = snap["games"][0]["gameLens"][0]
    assert lane["distDroppedForSize"] and "totalRunsDist" not in lane["projection"]
    assert lane["modelHomeWinProb"] == r["home_win_prob"] and lane["projection"]["total"] == r["total_mean"]


def test_rotation_and_carry_forward(monkeypatch):
    """A tick that runs out of budget carries forward the last lane and resumes from where it stopped."""
    events = [{"event_id": str(i), "status_state": "in"} for i in range(4)]
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path", lambda *_: None)
    monkeypatch.setattr("syndicate.features.shared.basketball_pbp.scoreboard_events", lambda sb: events)
    monkeypatch.setattr(lr, "load_player_priors", lambda *a, **k: lr.NcaabResimRefusal("no_player_priors"))
    monkeypatch.setattr(lr, "odds_team_names", lambda *a, **k: {})
    facts = lr.ResumeFacts("x", "10", "20", 40, 38, 2, 600.0, "home", 300, "t")
    monkeypatch.setattr(lr, "resume_from_summary", lambda s, **k: (None, None, facts))
    monkeypatch.setattr(lr, "build_engine_inputs", lambda *a, **k: {"home_players": None, "away_players": None})
    monkeypatch.setattr("syndicate.features.nba.live_resim.map_state_names", lambda gs, h, a: (gs, {}))
    now = {"t": 0.0}

    def resim(inputs, gs, **kw):
        now["t"] += 10.0
        return {"sims_run": 100, "home_win_prob": 0.6, "total_mean": 140.0, "home_margin_mean": 3.0,
                "total_dist": {}, "margin_dist": {}, "segments": {}}

    monkeypatch.setattr(lr, "resim_live_game", resim)
    lr._ROTATION_CURSOR.clear()
    kw = dict(fetch_scoreboard=lambda *a: {}, fetch_summary=lambda *a: {"header": {}}, budget_seconds=25,
              clock=lambda: now["t"])
    first = lr.build_live_lens_snapshot("2026-01-10", previous={}, **kw)
    assert first["counts"]["resimmed"] == 3 and first["counts"]["not_reached"] == 1
    prev = {g["event_id"]: g for g in first["games"]}
    now["t"] = 0.0
    second = lr.build_live_lens_snapshot("2026-01-10", previous=prev, **kw)
    # The second tick STARTS at game 3 (the one the first tick never reached) and carries forward the rest.
    assert second["counts"]["resimmed"] == 3 and second["counts"]["carried_forward"] == 1
    assert [g["event_id"] for g in second["games"]] == ["0", "1", "2", "3"]
    carried = [g for g in second["games"] if g.get("carriedForward")]
    assert len(carried) == 1 and all(l.get("liveStateCarriedForward") for l in carried[0]["gameLens"])
    assert not any(l.get("liveStateCarriedForward") for g in second["games"] if not g.get("carriedForward")
                   for l in g["gameLens"])


def test_loop_is_off_unless_switched_on():
    assert lr.ncaab_live_resim_enabled({}) is False
    assert lr.ncaab_live_resim_enabled({"SYNDICATE_NCAAB_LIVE_RESIM": "1"}) is True


def test_engine_reachability_tip_equals_pregame_and_lead_moves_it(tmp_path):
    """off != on: the real P1 engine under NCAAB params, resumed. A tip resume is seed-identical to pregame;
    a second-half lead raises the home win probability."""
    from syndicate.features.basketball_engine.resume import GameState

    _write_priors(tmp_path, "2026-01-10")
    pri = lr.load_player_priors(dt.date(2026, 1, 10), dirs=[tmp_path])
    inputs = lr.build_engine_inputs("2026-01-10", "10", "20", neutral=False, priors=pri, team_prior=_team_prior())
    engine = lr.ncaab_engine()
    kw = {k: inputs[k] for k in lr._ENGINE_KWARGS}
    assert engine.simulate_pbp_game_boxscore  # bound
    tip = GameState(period=1, seconds_remaining=None, home_period_pts=(0,), away_period_pts=(0,))
    a = [engine.simulate_pbp_game_boxscore(rng=np.random.default_rng(s), **kw)[2:] for s in range(3)]
    b = [engine.simulate_pbp_game_boxscore(rng=np.random.default_rng(s), **kw, state=tip)[2:] for s in range(3)]
    assert a == b
    assert all(len(hq) >= 2 for hq, _aq in a), "two halves, not four quarters"

    def wins(lead):
        gs = GameState(period=2, seconds_remaining=120, home_period_pts=(35, 30 + max(lead, 0)),
                       away_period_pts=(35, 30 + max(-lead, 0)), possession="home")
        outs = [engine.simulate_pbp_game_boxscore(rng=np.random.default_rng(s), **kw, state=gs)[2:] for s in range(20)]
        return sum(1 for hq, aq in outs if sum(hq) > sum(aq))

    assert wins(10) > wins(-10)


# ------------------------------------------------------------------ the board interlock, end to end
# Mirrors tests/test_ncaaf_live_gameline_registration.py: presence != reachability. The lane must index,
# PRICE the row from the live probability, and RELEASE the edge -- and a refusal must do none of that.

AWAY, HOME = "Army Black Knights", "Duke Blue Devils"


def _grid_row(*, state="live", age_seconds=30.0):
    return {
        "kind": "game", "market": "h2h", "segment": "full", "away_team": AWAY, "home_team": HOME,
        "age_seconds": age_seconds, "game": {"state": state},
        "projection": {"model_prob_over": 0.62, "market_fair_prob_over": 0.40, "basis": "ncaab_team_model"},
    }


def _lanes(result=None, facts=True, carried=False):
    from syndicate.features.ncaab.live_resim import _carry

    if result is None:
        # A clear home lead late: 190 of 200 draws won, so the interval is narrow and PRICEABLE_SIGMA passes
        # for the right reason, and the live probability is NOT the pregame 0.62.
        def simulate(rng, gs, i=[0]):
            i[0] += 1
            return {}, {}, [40, 40], [40, 30 if i[0] % 20 else 45]
        result = lr.resim_live_game({}, None, sims=200, simulate=simulate)
    f = lr.ResumeFacts("401", "10", "20", 70, 58, 2, 120.0, "home", 400, "2026-11-05T01:00:00+00:00") if facts else None
    game = lr._lane_row("401", {"home": HOME, "away": AWAY, "source": "odds"}, f, result)
    if carried:
        game = _carry(game)
    return {"games": [game]}


def _index(snapshot):
    from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport

    return build_live_gameline_index(snapshot, sources=lens_sources_for_sport("ncaab"), sport="ncaab")


def test_the_board_gate_lists_ncaab_and_reads_its_own_key():
    from syndicate.features.shared.board_enrichment import _LIVE_GAMELINE_SNAPSHOT_PATHS, _LIVE_GAMELINE_SPORTS

    assert "ncaab" in _LIVE_GAMELINE_SPORTS
    assert _LIVE_GAMELINE_SNAPSHOT_PATHS["ncaab"] == lr.live_lens_snapshot_path().name


def test_a_live_resim_lane_indexes_prices_and_releases_the_edge():
    from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
    from syndicate.features.shared.live_gameline_join import attach_live_gamelines

    index = _index(_lanes())
    assert len(index) == 1
    row = _grid_row()
    assert live_edge_unavailable_reason(row) is not None, "the pregame row alone stays suppressed"
    coverage = attach_live_gamelines([row], index)
    assert coverage["index_size"] == 1
    proj = row["projection"]
    assert proj["live_aware"] is True and proj["edge_basis"] == "live"
    assert row["live_gameline"]["home_win_prob"] == pytest.approx(0.95)
    # From the LIVE number: the pregame pairing (0.62 - 0.40) would be 22.0.
    assert proj["edge_vs_market_pct"] is not None and round(proj["edge_vs_market_pct"], 1) != 22.0
    assert proj["edge_vs_market_pct"] > 40
    assert live_edge_unavailable_reason(row) is None


def test_a_refused_lane_indexes_nothing_and_the_edge_stays_suppressed():
    from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
    from syndicate.features.shared.live_gameline_join import attach_live_gamelines

    snap = _lanes(result=lr.NcaabResimRefusal("thin_rotation", "x"), facts=False)
    assert _index(snap) == {}
    row = _grid_row()
    attach_live_gamelines([row], _index(snap))
    assert "live_aware" not in row["projection"] and live_edge_unavailable_reason(row) is not None


def test_a_carried_forward_lane_reaches_the_row_marked_as_carried():
    from syndicate.features.shared.live_gameline_join import attach_live_gamelines

    row = _grid_row()
    attach_live_gamelines([row], _index(_lanes(carried=True)))
    assert row["live_gameline"]["carried_forward"] is True


def test_exact_target_switch_is_off_unless_set_and_binds_a_different_engine(monkeypatch):
    monkeypatch.delenv("SYNDICATE_NCAAB_EXACT_TARGET", raising=False)
    assert lr.exact_target_enabled() is False
    assert lr.exact_target_enabled({"SYNDICATE_NCAAB_EXACT_TARGET": "1"}) is True
    off, on = lr.ncaab_engine(False), lr.ncaab_engine(True)
    assert off is not on
    assert off.EXACT_TARGET_CALIBRATION is False and on.EXACT_TARGET_CALIBRATION is True


def test_half_split_is_off_unless_set_and_shifts_the_halves(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_NCAAB_HALF_SPLIT", raising=False)
    _write_priors(tmp_path, "2026-01-10")
    pri = lr.load_player_priors(dt.date(2026, 1, 10), dirs=[tmp_path])
    off = lr.build_engine_inputs("2026-01-10", "10", "20", neutral=False, priors=pri, team_prior=_team_prior())
    assert off["quarters"] is None and off["_provenance"]["halfSplit"] is False
    monkeypatch.setenv("SYNDICATE_NCAAB_HALF_SPLIT", "1")
    on = lr.build_engine_inputs("2026-01-10", "10", "20", neutral=False, priors=pri, team_prior=_team_prior())
    h1, h2 = on["quarters"]
    assert h1["home_pts_mu"] + h2["home_pts_mu"] == pytest.approx(73.0)
    assert h1["home_pts_mu"] / 73.0 == pytest.approx(lr.H1_SHARE)
    engine = lr.ncaab_engine(False)

    def halves(inputs):
        kw = {k: inputs[k] for k in lr._ENGINE_KWARGS}
        outs = [engine.simulate_pbp_game_boxscore(rng=np.random.default_rng(s), **kw) for s in range(30)]
        return np.mean([hq[0] + aq[0] for _hb, _ab, hq, aq in outs]), np.mean([hq[1] + aq[1] for _hb, _ab, hq, aq in outs])

    off_h1, off_h2 = halves(off)
    on_h1, on_h2 = halves(on)
    assert (on_h2 - on_h1) > (off_h2 - off_h1) + 2, ((off_h1, off_h2), (on_h1, on_h2))


def test_mechanisms_env_is_off_unless_valid_and_reaches_the_cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_NCAAB_LIVE_MECHANISMS", raising=False)
    assert lr.live_mechanisms_from_env() == {}
    assert lr.live_mechanisms_from_env({"SYNDICATE_NCAAB_LIVE_MECHANISMS": "{not json"}) == {}
    assert lr.live_mechanisms_from_env({"SYNDICATE_NCAAB_LIVE_MECHANISMS": '{"no_such_field": 1}'}) == {}
    got = lr.live_mechanisms_from_env({"SYNDICATE_NCAAB_LIVE_MECHANISMS": '{"endgame_foul_window_s": 120, "endgame_foul_p_by_deficit": [0.25, 0.5, 0.6]}'})
    assert got == {"endgame_foul_window_s": 120, "endgame_foul_p_by_deficit": (0.25, 0.5, 0.6)}
    _write_priors(tmp_path, "2026-01-10")
    pri = lr.load_player_priors(dt.date(2026, 1, 10), dirs=[tmp_path])
    monkeypatch.setenv("SYNDICATE_NCAAB_LIVE_MECHANISMS", '{"bonus_free_throws": true, "bonus_nonshoot_foul_per_poss": 0.08}')
    inputs = lr.build_engine_inputs("2026-01-10", "10", "20", neutral=False, priors=pri, team_prior=_team_prior())
    assert inputs["cfg"].bonus_free_throws is True and inputs["cfg"].bonus_nonshoot_foul_per_poss == 0.08
    assert inputs["_provenance"]["mechanisms"] == ["bonus_free_throws", "bonus_nonshoot_foul_per_poss"]
