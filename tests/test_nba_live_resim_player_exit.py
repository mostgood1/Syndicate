"""NBA live re-sim refuses a game a starter has left, and refuses an out player's live props (lane live-player-exit-gate).

The exit is read from the summary the re-sim ALREADY fetched (no extra GET): ejection / foul-out / in-game injury
via `live_player_status.exits_from_espn_summary`; KEY = a boxscore starter. Harness as `test_nba_live_resim`:
synthetic ESPN summaries (`tests/basketball_pbp_fixtures.Game`), synthetic engine inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_status as lps
from tests.basketball_engine_fixtures import synthetic_game_kwargs
from tests.basketball_pbp_fixtures import Game

DATE = "2026-01-15"
SB = {"events": [{"id": "999", "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]}]}
RESULT = {"sims_run": 200, "home_win_prob": 0.4, "total_mean": 1.0, "home_margin_mean": -1.0,
          "total_dist": {"1": 200}, "margin_dist": {"-1": 200}, "segments": {},
          "player_remainders": {"home": {"H1": {"pts": {"6": 100, "12": 100}}}, "away": {}}}


def _summary(ejected: str | None = None, starter: bool = True):
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").shot(1, "10:30", "away", "a1", pts=3).foul(1, "9:00", "home", "h2")
    g.end_period(1)
    g.shot(2, "11:40", "home", "h1").sub(2, "10:00", "away", "a6", "a5").shot(2, "9:30", "away", "a6")
    s = g.summary()
    if ejected:
        for team in s["boxscore"]["players"]:
            for cat in team["statistics"]:
                for entry in cat["athletes"]:
                    if entry["athlete"]["displayName"] == ejected:
                        entry["ejected"] = True
                        entry["starter"] = starter
    return s


@pytest.fixture
def root(tmp_path):
    kw = synthetic_game_kwargs(np.random.default_rng(7), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    lr.persist_engine_inputs(DATE, "GSW", "NYK", {**{k: None for k in lr._INPUT_KEYS}, **kw}, root=tmp_path)
    lr.props_csv_path(DATE, root=tmp_path).write_text(
        "market,outcome_name,player_name,point,home_team,away_team\n"
        "player_points,Over,H1,10.5,Golden State Warriors,New York Knicks\n", encoding="utf-8")
    return tmp_path


def _snap(monkeypatch, root, summary):
    sims: list = []
    monkeypatch.setattr(lr, "resim_live_game", lambda *a, **k: sims.append(1) or dict(RESULT))
    snap = lr.build_live_lens_snapshot(DATE, fetch_scoreboard=lambda *_a: SB, fetch_summary=lambda *_a: summary,
                                       inputs_root=root, carry=False, remember_lines=False)
    return snap, sims


def _lane(snap):
    return snap["games"][0]["gameLens"][0]


def test_a_starter_ejected_refuses_the_game_before_any_sim(monkeypatch, root):
    snap, sims = _snap(monkeypatch, root, _summary(ejected="H1"))
    lane, game = _lane(snap), snap["games"][0]
    assert lane["source"] == lr.PREGAME_LENS_SOURCE and lane["liveResimRefusal"] == "key_player_out"
    assert "H1" in lane["liveResimRefusalDetail"] and "ejection" in lane["liveResimRefusalDetail"]
    assert sims == []  # refused before the engine: no compute spent on a game it will not price
    assert "liveProps" not in game
    assert [(p["player"], p["reason"], p["key"]) for p in game["playersOut"]] == [("H1", "ejection", True)]
    assert snap["refusalsByReason"] == {"key_player_out": 1}
    assert snap["playerExits"]["read"] == 1 and snap["playerExits"]["key_players_out"] == 1


def test_off_ne_on(monkeypatch, root):
    on, _ = _snap(monkeypatch, root, _summary(ejected="H1"))
    monkeypatch.setenv(lps.ENV_SWITCH, "off")
    off, sims = _snap(monkeypatch, root, _summary(ejected="H1"))
    assert _lane(on)["liveResimRefusal"] == "key_player_out"
    assert _lane(off)["source"] == lr.LIVE_RESIM_LENS_SOURCE and sims == [1]
    assert "playersOut" not in off["games"][0] and off["playerExits"]["enabled"] is False


def test_a_clean_game_is_priced_and_publishes_an_empty_exit_list(monkeypatch, root):
    snap, sims = _snap(monkeypatch, root, _summary())
    assert _lane(snap)["source"] == lr.LIVE_RESIM_LENS_SOURCE and sims == [1]
    assert snap["games"][0]["playersOut"] == [] and snap["refusalsByReason"] == {}


def test_a_bench_player_out_keeps_the_game_but_refuses_his_props(monkeypatch, root):
    snap, _ = _snap(monkeypatch, root, _summary(ejected="H1", starter=False))
    game = snap["games"][0]
    assert _lane(snap)["source"] == lr.LIVE_RESIM_LENS_SOURCE
    assert [(p["player"], p["key"]) for p in game["playersOut"]] == [("H1", False)]
    h1 = [r for r in game["liveProps"] if r["playerName"] == "H1"]
    assert h1 and all(r["liveModelProbOver"] is None and r["unpricedReason"] == "player_out" for r in h1)
    assert game["livePropsCoverage"]["player_out_refused"] == len(h1) and game["livePropsCoverage"]["priced"] == 0


def test_build_live_props_refuses_only_the_out_player():
    result = {"sims_run": 100, "player_remainders": {"home": {"A": {"pts": {"5": 100}}, "B": {"pts": {"5": 100}}}}}
    rows, cov = lr.build_live_props(result, {"a": {"pts": 3}, "b": {"pts": 3}},
                                    {("a", "pts"): 7.5, ("b", "pts"): 7.5}, players_out={"a"})
    by = {r["playerName"]: r for r in rows}
    assert by["A"]["unpricedReason"] == "player_out" and by["A"]["liveModelProbOver"] is None
    assert by["B"]["liveModelProbOver"] == 1.0 or by["B"].get("unpricedReason") == "certainty_refused"
    assert cov["player_out_refused"] == 1


def test_the_LIVE_GAMELINE_index_drops_the_game_and_the_entry_hold_fails(monkeypatch, root):
    from syndicate.features.shared.live_gameline_join import (
        analytic_std_err_for_sport,
        build_live_gameline_index,
        lens_sources_for_sport,
    )

    def index(snap):
        return build_live_gameline_index(snap, sources=lens_sources_for_sport("nba"),
                                         analytic_std_err=analytic_std_err_for_sport("nba"),
                                         sport="nba", slate_date=DATE)

    priced, _ = _snap(monkeypatch, root, _summary())
    refused, _ = _snap(monkeypatch, root, _summary(ejected="H1"))
    assert len(index(priced)) >= 1 and index(refused) == {}
    hold = H.ExitHold(read_fn=lambda sport: refused, env={})
    out = hold.check("nba", "Golden State Warriors", "New York Knicks")
    # The synthetic box carries no team abbreviation (a real ESPN box does: "GSW:..."), hence the empty team.
    assert out["verdict"] == "fail" and out["players"] == [":H1:ejection"]
    assert H.ExitHold(read_fn=lambda sport: priced, env={}).check("nba", "New York Knicks", "Golden State Warriors")[
        "verdict"] == "pass"
