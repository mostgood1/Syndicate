"""A slate that grows after the first bootstrap reaches game_odds, game_cards and predictions (lane nba-source-cli-native).

Measured 2026-10-13: the NBA bootstrap ran once (03:48Z) when 3 of the 5 games had lines; game_odds, game_cards and
predictions stayed at 3 all day while the board carried props on the other two. Both refreshes now:
  * merge snapshot-priced games that game_odds lacks (never rewriting or dropping an existing row);
  * when predictions lack games game_odds has, rebuild game_cards and re-run predict-date, once per cooldown.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {"nba": "refresh_nba_oddsapi_props.py", "wnba": "refresh_wnba_oddsapi_props.py"}
DATE = "2026-10-13"
GAMES5 = [("Orlando Magic", "Cleveland Cavaliers"), ("Toronto Raptors", "New York Knicks"), ("Oklahoma City Thunder", "Indiana Pacers"),
          ("Los Angeles Lakers", "Golden State Warriors"), ("Sacramento Kings", "Portland Trail Blazers")]


def _mod(league):
    spec = importlib.util.spec_from_file_location(f"refresh_{league}_slate_probe", ROOT / "scripts" / SCRIPTS[league])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _odds_rows(games, price=220.5):
    return pd.DataFrame([{"date": DATE, "commence_time": "2026-10-13T23:00:00Z", "home_team": h, "visitor_team": a, "home_ml": -150,
                          "away_ml": 130, "home_spread": -3.5, "away_spread": 3.5, "total": price, "bookmaker": "consensus"} for h, a in games])


def _setup(tmp_path, league, mod, monkeypatch, *, odds_games, pred_games):
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    _odds_rows(odds_games).to_csv(proc / f"game_odds_{DATE}.csv", index=False)
    pd.DataFrame([{"date": DATE, "home_team": h, "visitor_team": a} for h, a in pred_games]).to_csv(proc / f"predictions_{DATE}.csv", index=False)
    snap = pd.DataFrame([{"home_team": h, "away_team": a, "market": "totals", "player": "", "line": 220.5} for h, a in GAMES5])
    snap.to_csv(proc / f"oddsapi_player_props_{DATE}.csv", index=False)
    monkeypatch.setattr(mod, "_build_game_odds_rows_from_snapshot_frame", lambda frame, date_str: _odds_rows(list(zip(frame["home_team"], frame["away_team"]))))
    return proc


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_seed_merges_newly_priced_games_and_keeps_existing_rows(tmp_path, monkeypatch, league):
    mod = _mod(league)
    proc = _setup(tmp_path, league, mod, monkeypatch, odds_games=GAMES5[:3], pred_games=GAMES5[:3])
    before = pd.read_csv(proc / f"game_odds_{DATE}.csv")
    mod._seed_game_odds_from_props_snapshot(source_root=tmp_path, date_str=DATE, log_file=tmp_path / "run.log")
    after = pd.read_csv(proc / f"game_odds_{DATE}.csv")
    assert len(after) == 5
    pd.testing.assert_frame_equal(after.iloc[:3].reset_index(drop=True), before)  # existing rows untouched, in place
    assert mod._slate_matchups(proc / f"game_odds_{DATE}.csv") == {(h.lower(), a.lower()) for h, a in GAMES5}
    # idempotent
    mod._seed_game_odds_from_props_snapshot(source_root=tmp_path, date_str=DATE, log_file=tmp_path / "run.log")
    assert len(pd.read_csv(proc / f"game_odds_{DATE}.csv")) == 5


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_predictions_rerun_when_the_slate_grew_once_per_cooldown(tmp_path, monkeypatch, league):
    mod = _mod(league)
    proc = _setup(tmp_path, league, mod, monkeypatch, odds_games=GAMES5[:3], pred_games=GAMES5[:3])
    calls = []

    def fake_cards(**kw):
        calls.append("cards")
        return 5, None

    def fake_predict(**kw):
        calls.append(("predict", kw["package_name"]))
        pd.DataFrame([{"date": DATE, "home_team": h, "visitor_team": a} for h, a in GAMES5]).to_csv(proc / f"predictions_{DATE}.csv", index=False)
        return 0

    monkeypatch.setattr(mod, "_build_local_game_cards_artifact", fake_cards)
    monkeypatch.setattr(mod, "_run_source_predict_date", fake_predict)
    out = mod._rerun_predictions_if_slate_grew(source_root=tmp_path, date_str=DATE, log_file=tmp_path / "run.log", heartbeat_cb=None)
    assert out["ran"] is True and out["rc"] == 0 and out["still_missing"] == [] and len(out["missing"]) == 2
    assert calls == ["cards", ("predict", f"{league}_betting")]
    # covered now: no re-run
    assert mod._rerun_predictions_if_slate_grew(source_root=tmp_path, date_str=DATE, log_file=tmp_path / "run.log", heartbeat_cb=None)["ran"] is False
    assert len(calls) == 2


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_cooldown_stops_a_still_missing_game_from_retriggering(tmp_path, monkeypatch, league):
    mod = _mod(league)
    proc = _setup(tmp_path, league, mod, monkeypatch, odds_games=GAMES5[:3], pred_games=GAMES5[:3])
    runs = []
    monkeypatch.setattr(mod, "_build_local_game_cards_artifact", lambda **kw: (5, None))
    monkeypatch.setattr(mod, "_run_source_predict_date", lambda **kw: runs.append(1) or 1)  # predict-date fails: still missing
    first = mod._rerun_predictions_if_slate_grew(source_root=tmp_path, date_str=DATE, log_file=tmp_path / "run.log", heartbeat_cb=None)
    second = mod._rerun_predictions_if_slate_grew(source_root=tmp_path, date_str=DATE, log_file=tmp_path / "run.log", heartbeat_cb=None)
    assert first["ran"] is True and len(first["still_missing"]) == 2
    assert second["ran"] is False and "skipped" in second and runs == [1]
    marker = json.loads((proc / f".predict_date_slate_grew_{DATE}.json").read_text(encoding="utf-8"))
    assert len(marker["missing"]) == 2


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_full_slate_is_a_no_op(tmp_path, monkeypatch, league):
    mod = _mod(league)
    _setup(tmp_path, league, mod, monkeypatch, odds_games=GAMES5, pred_games=GAMES5)
    monkeypatch.setattr(mod, "_run_source_predict_date", lambda **kw: pytest.fail("must not run"))
    out = mod._rerun_predictions_if_slate_grew(source_root=tmp_path, date_str=DATE, log_file=tmp_path / "run.log", heartbeat_cb=None)
    assert out == {"date": DATE, "ran": False, "missing": []}
