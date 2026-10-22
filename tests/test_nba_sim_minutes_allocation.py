"""NBA SmartSim minutes: the priced-first shrink (lane nba-sim-minutes-allocation, todo #723).

Reachability before correctness (model engine standard 4.3): off != on is proven through the REAL worker
(`_smart_sim_worker_init_local` + `_smart_sim_worker_run_local`) and the real orchestrator, by the minutes the engine
receives and the minutes the artifact publishes. The switch is SYNDICATE_NBA_SIM_MINUTES_PRICED_FIRST; absent = off.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as b

FLAG = b.NBA_SIM_MINUTES_PRICED_FIRST_FLAG
DATE = "2026-10-21"
# 12 per team: 5 starters, 7 bench; sum 276 > 240, so the shrink always runs.
MINUTES = [32.0, 31.0, 30.0, 29.0, 28.0, 24.0, 22.0, 20.0, 18.0, 16.0, 14.0, 12.0]
TEAMS = {"BOS": "Boston Celtics", "NYK": "New York Knicks"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.setenv("SYNDICATE_NBA_TEAM_INPUTS", "0")
    b._MARKET_PLAYER_NAMES_CACHE_LOCAL.clear()
    prev = b._SMARTSIM_WORKER_STATE
    yield
    b._MARKET_PLAYER_NAMES_CACHE_LOCAL.clear()
    b._SMARTSIM_WORKER_STATE = prev


def _name(team: str, i: int) -> str:
    return f"{team.title()} Player{chr(65 + i)}"


def _props_rows():
    rows = []
    for team, opp in (("BOS", "NYK"), ("NYK", "BOS")):
        for i, m in enumerate(MINUTES):
            rows.append({"player_name": _name(team, i), "team": team, "opponent": opp, "roll5_min": m, "roll10_min": m,
                         "roll3_min": m, "lag1_min": m, "pred_pts": round(0.5 * m, 1), "pred_reb": round(0.18 * m, 1),
                         "pred_ast": round(0.12 * m, 1), "pred_threes": round(0.05 * m, 2), "mean_pts": round(0.5 * m, 1)})
    return rows


def _write_snapshot(raw: Path, priced_per_team: int) -> None:
    """A pre-tip props snapshot pricing the first `priced_per_team` players of each team (the 5 starters + bench)."""
    raw.mkdir(parents=True, exist_ok=True)
    with (raw / f"odds_nba_player_props_{DATE}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["snapshot_ts", "event_id", "commence_time", "bookmaker", "market", "outcome_name",
                                           "player_name", "point", "price", "home_team", "away_team"])
        w.writeheader()
        for team in TEAMS:
            for i in range(priced_per_team):
                w.writerow({"snapshot_ts": f"{DATE}T18:00:00+00:00", "event_id": "e1", "commence_time": f"{DATE}T23:30:00Z",
                            "bookmaker": "draftkings", "market": "player_points", "outcome_name": "Over",
                            "player_name": _name(team, i), "point": 10.5, "price": -110,
                            "home_team": TEAMS["BOS"], "away_team": TEAMS["NYK"]})


@pytest.fixture
def tree(tmp_path):
    processed = tmp_path / "nba_source" / "data" / "processed"
    processed.mkdir(parents=True)
    pd.DataFrame(_props_rows()).to_csv(processed / f"props_predictions_{DATE}.csv", index=False)
    _write_snapshot(processed.parent / "raw", priced_per_team=6)
    return processed


def _team_df(team: str) -> pd.DataFrame:
    return pd.DataFrame([r for r in _props_rows() if r["team"] == team]).reset_index(drop=True)


def _derive(processed: Path, team: str, mode: str | None, monkeypatch, *, league: str = "nba") -> np.ndarray:
    if mode is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, mode)
    b._SMARTSIM_WORKER_STATE = {"date_str": DATE}
    view = b._build_local_smart_sim_module(processed_root=processed, league_code=league)
    # Pregame mode hands the derive the AS-OF date (slate - 1); the switch must still read the slate's snapshot.
    return b._derive_sim_minutes_local(smart_sim_module=view, team_df=_team_df(team), date_str="2026-10-20",
                                       team_tri=team, league_code=league).to_numpy(dtype=float)


# --- the switch ------------------------------------------------------------------------------------------------------


def test_mode_is_off_unless_set():
    assert b._nba_sim_minutes_priced_first_mode_local({}) == "off"
    assert b._nba_sim_minutes_priced_first_mode_local({FLAG: "junk"}) == "off"
    assert b._nba_sim_minutes_priced_first_mode_local({FLAG: "0"}) == "off"
    assert b._nba_sim_minutes_priced_first_mode_local({FLAG: "shadow"}) == "shadow"
    assert b._nba_sim_minutes_priced_first_mode_local({FLAG: "on"}) == "on"
    assert b._nba_sim_minutes_priced_first_mode_local({FLAG: "1"}) == "on"


# --- the fill ----------------------------------------------------------------------------------------------------------


def test_fill_takes_the_excess_off_the_unpriced_first():
    base = np.array([30.0] * 5 + [20.0] * 6)          # 150 priced + 120 unpriced = 270, excess 30
    priced = np.array([True] * 5 + [False] * 6)
    out = b._priced_first_fill_local(base, total=240.0, caps=None, priced=priced)
    assert out.sum() == pytest.approx(240.0)
    assert np.allclose(out[:5], 30.0)                  # priced untouched
    assert np.allclose(out[5:], 15.0)                  # the same 5 min off each unpriced player
    # The plain water-fill takes it off everyone: each player loses 30/11.
    off = b._water_fill_minutes_local(base, total=240.0, caps=None)
    assert np.allclose(off, base - 30.0 / 11.0)


def test_fill_zeroes_the_unpriced_then_water_fills_the_priced():
    base = np.array([36.0] * 7 + [10.0] * 3)           # 252 priced + 30 unpriced, excess 42 > 30
    priced = np.array([True] * 7 + [False] * 3)
    out = b._priced_first_fill_local(base, total=240.0, caps=None, priced=priced)
    assert out.sum() == pytest.approx(240.0)
    assert np.allclose(out[7:], 0.0)
    assert np.allclose(out[:7], 240.0 / 7.0)


def test_fill_respects_caps_and_returns_none_without_an_excess():
    base = np.array([40.0] * 5 + [20.0] * 6)
    caps = np.array([34.0] * 5 + [30.0] * 6)          # the priced are capped at 34 before anything else
    priced = np.array([True] * 5 + [False] * 6)
    out = b._priced_first_fill_local(base, total=240.0, caps=caps, priced=priced)
    assert np.allclose(out[:5], 34.0) and out.sum() == pytest.approx(240.0)
    assert b._priced_first_fill_local(np.array([20.0] * 10), total=240.0, caps=None, priced=np.array([True] * 10)) is None


# --- the derive (the production function) ----------------------------------------------------------------------------


def test_derive_off_is_the_water_fill_and_on_differs(tree, monkeypatch, capsys):
    off = _derive(tree, "BOS", None, monkeypatch)
    explicit_off = _derive(tree, "BOS", "off", monkeypatch)
    on = _derive(tree, "BOS", "on", monkeypatch)
    assert np.allclose(off, explicit_off)
    assert off.sum() == pytest.approx(240.0) and on.sum() == pytest.approx(240.0)
    assert not np.allclose(off, on)                                   # reachability
    assert (on[:6] - off[:6]).min() > 0.0                             # every priced player gains
    assert (on[6:] - off[6:]).max() < 0.0                             # every unpriced player loses
    out = capsys.readouterr().out
    assert "NBA_SIM_MINUTES_PRICED_FIRST mode=on date=2026-10-21 team=BOS pool=12 priced=6 engaged=1" in out


def test_shadow_logs_but_returns_off(tree, monkeypatch, capsys):
    off = _derive(tree, "NYK", None, monkeypatch)
    capsys.readouterr()
    shadow = _derive(tree, "NYK", "shadow", monkeypatch)
    assert np.allclose(off, shadow)
    assert "NBA_SIM_MINUTES_PRICED_FIRST mode=shadow date=2026-10-21 team=NYK pool=12 priced=6 engaged=1" in capsys.readouterr().out


def test_off_logs_nothing(tree, monkeypatch, capsys):
    _derive(tree, "BOS", None, monkeypatch)
    assert "NBA_SIM_MINUTES_PRICED_FIRST" not in capsys.readouterr().out


def test_too_few_priced_players_does_not_engage(tree, monkeypatch, capsys):
    _write_snapshot(tree.parent / "raw", priced_per_team=4)
    off = _derive(tree, "BOS", None, monkeypatch)
    b._MARKET_PLAYER_NAMES_CACHE_LOCAL.clear()
    on = _derive(tree, "BOS", "on", monkeypatch)
    assert np.allclose(off, on)
    assert "priced=4 engaged=0 reason=priced_below_5" in capsys.readouterr().out


def test_no_snapshot_does_not_engage(tree, monkeypatch):
    (tree.parent / "raw" / f"odds_nba_player_props_{DATE}.csv").unlink()
    assert np.allclose(_derive(tree, "BOS", None, monkeypatch), _derive(tree, "BOS", "on", monkeypatch))


def test_the_slate_date_not_the_asof_date_picks_the_snapshot(tree, monkeypatch):
    """Without the worker state the derive only knows the as-of date (2026-10-20), which has no snapshot here: off."""
    monkeypatch.setenv(FLAG, "on")
    b._SMARTSIM_WORKER_STATE = None
    view = b._build_local_smart_sim_module(processed_root=tree, league_code="nba")
    on_wrong_date = b._derive_sim_minutes_local(smart_sim_module=view, team_df=_team_df("BOS"), date_str="2026-10-20",
                                                team_tri="BOS", league_code="nba").to_numpy(dtype=float)
    assert np.allclose(on_wrong_date, _derive(tree, "BOS", None, monkeypatch))


def test_wnba_is_never_touched(tree, monkeypatch, capsys):
    off = _derive(tree, "BOS", None, monkeypatch, league="wnba")
    on = _derive(tree, "BOS", "on", monkeypatch, league="wnba")
    assert np.allclose(off, on)
    assert "NBA_SIM_MINUTES_PRICED_FIRST" not in capsys.readouterr().out


# --- reachability through the REAL worker ----------------------------------------------------------------------------


def _run_worker(processed: Path, mode: str | None, monkeypatch):
    if mode is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, mode)
    b._MARKET_PLAYER_NAMES_CACHE_LOCAL.clear()
    seen: list[dict] = []
    real = b._call_native_engine_local

    def spy(*, entrypoint_name, league_code, kwargs):
        if entrypoint_name == "simulate_pbp_game_boxscore":
            seen.append({side: dict(zip(kwargs[f"{side}_players"]["player_name"], kwargs[f"{side}_players"]["_sim_min"]))
                         for side in ("home", "away")})
        return real(entrypoint_name=entrypoint_name, league_code=league_code, kwargs=kwargs)

    monkeypatch.setattr(b, "_call_native_engine_local", spy)
    monkeypatch.setattr(b, "_persist_engine_inputs_once_local", lambda *a, **k: None)
    props_path = processed / f"props_predictions_{DATE}.csv"
    b._smart_sim_worker_init_local(DATE, 3, 7, True, str(props_path), "pregame", "nba", {}, {}, {}, {}, {})
    out_path = processed / f"smart_sim_{DATE}_BOS_NYK.json"
    result = b._smart_sim_worker_run_local({"date_str": DATE, "home_tri": "BOS", "away_tri": "NYK", "out_path": str(out_path),
                                            "market_total": 225.5, "home_spread": -3.5, "home_pace": 99.0, "away_pace": 98.0})
    assert result["status"] == "wrote", result
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    published = {side: {r["player_name"]: float(r["min_mean"]) for r in payload["players"][side]} for side in ("home", "away")}
    assert seen, "the engine was never called"
    return seen[0], published


def test_worker_off_vs_on_reaches_the_engine_and_the_artifact(tree, monkeypatch, capsys):
    engine_off, pub_off = _run_worker(tree, None, monkeypatch)
    engine_on, pub_on = _run_worker(tree, "on", monkeypatch)
    for side, team in (("home", "BOS"), ("away", "NYK")):
        priced = {_name(team, i) for i in range(6)}
        assert set(engine_off[side]) == set(engine_on[side]) == {_name(team, i) for i in range(12)}
        assert engine_off[side] != engine_on[side]                     # off != on, at the engine's input
        assert pub_off[side] != pub_on[side]                           # and in what the artifact publishes
        for name in priced:
            assert engine_on[side][name] > engine_off[side][name]
        for name in set(engine_on[side]) - priced:
            assert engine_on[side][name] < engine_off[side][name]
        assert sum(engine_on[side].values()) == pytest.approx(240.0, abs=0.5)
    assert "NBA_SIM_MINUTES_PRICED_FIRST mode=on date=2026-10-21 team=BOS" in capsys.readouterr().out
