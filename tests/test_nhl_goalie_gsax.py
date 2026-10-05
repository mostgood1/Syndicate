"""Goalie GSAx factor for game-line totals (lane `nhl-game-lines-model`).

Fixtures are REAL: PHI @ NJD 2026020009 play-by-play (nhl_inseason_team_xg), and production's BUF / MIN lineups +
starting goalies for 2026-10-06 (nhl_confirmed_goalies).
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

import scripts.build_nhl_artifacts as producer
from syndicate.features.nhl import goalie_gsax as G
from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyGameFeatures, HockeyTeamFeatures

FX_XG = Path(__file__).parent / "fixtures" / "nhl_inseason_team_xg"
FX_CG = Path(__file__).parent / "fixtures" / "nhl_confirmed_goalies"
PBP = json.loads((FX_XG / "playbyplay_2026020009.json").read_text(encoding="utf-8"))


def test_goalie_order_aligns_and_counts_goals_against():
    rows = G.game_goalie_shots(PBP)
    assert rows is not None and rows
    goals = sum(g for _gk, _x, g in rows)
    assert 4 <= goals <= 5                                   # NJD 3-2; empty-net goals excluded
    assert len({gk for gk, _x, _g in rows}) >= 2             # both teams' goalies faced shots


def test_factor_math_shrinkage_and_no_factor_without_shots():
    table = {1: (10.0, 15.0), 2: (10.0, 5.0)}
    bad, good = G.gsax_factor(1, table, 1.0, prior={}), G.gsax_factor(2, table, 1.0, prior={})
    assert bad == pytest.approx((15 + 160) / (10 + 160)) and good == pytest.approx((5 + 160) / (10 + 160))
    assert bad > 1.0 > good
    assert G.gsax_factor(3, table, 1.0, prior={3: (100.0, 50.0)}) is None      # no shots this season -> no factor (V8)
    assert G.gsax_factor(1, table, 1.0, prior={1: (100.0, 100.0)}) == pytest.approx(
        (15 + 0.25 * 100 + 160) / (10 + 0.25 * 100 + 160))
    assert len(G.PRIOR_2025_26) == 98


def test_season_table_is_as_of_and_writes_nothing(tmp_path):
    root = tmp_path / "nhl_source"
    (root / "data" / "ingestion_cache").mkdir(parents=True)
    (root / "data" / "ingestion_cache" / "playbyplay_2026020009.json").write_text(json.dumps(PBP), encoding="utf-8")
    table, lr, st = G.season_table(root, date(2026, 10, 5))          # played 2026-10-01: counted
    assert st["games"] == 1 and st["misaligned"] == 0 and len(table) == st["goalies"] and lr > 0
    table2, _lr2, st2 = G.season_table(root, date(2026, 10, 1))     # same-day slate: not yet played
    assert table2 == {} and st2["skipped_not_before_day"] == 1
    assert not (root / "data" / "processed").exists()


def _slate(tmp_path, table_rows, monkeypatch):
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    shutil.copy(FX_CG / "lineups_2026-10-06_fleet_BUF_MIN.csv", proc / "lineups_2026-10-06.csv")
    shutil.copy(FX_CG / "starting_goalies_2026-10-06_fleet_BUF_MIN.csv", proc / "starting_goalies_2026-10-06.csv")
    table = {int(p): (float(x), float(g)) for p, x, g in table_rows}
    lr = sum(v[1] for v in table.values()) / sum(v[0] for v in table.values())
    monkeypatch.setattr(G, "season_table", lambda *a, **k: (table, lr, {"stub": True}))
    producer._GOALIE_GSAX_TABLES.clear()
    g = HockeyGameFeatures(game_pk="2026020099", date="2026-10-06",
                           home=HockeyTeamFeatures(name="Buffalo Sabres", abbrev="BUF", period_goal_lambdas=(1.0, 1.0, 1.0)),
                           away=HockeyTeamFeatures(name="Minnesota Wild", abbrev="MIN", period_goal_lambdas=(1.0, 1.0, 1.0)))
    return g, table, lr


def test_opposing_starter_scales_the_other_teams_lambdas(tmp_path, monkeypatch):
    # starters in the fixture: BUF Luukkonen 8480045 (made much worse here), MIN Wallstedt 8482661 (league average)
    g, table, lr = _slate(tmp_path, [(8480045, 20.0, 40.0), (8482661, 20.0, 20.0), (8479312, 60.0, 30.0)], monkeypatch)
    out = producer._apply_goalie_gsax([g], "2026-10-06", tmp_path)[0]
    f_buf, f_min = G.gsax_factor(8480045, table, lr), G.gsax_factor(8482661, table, lr)
    assert out.away.period_goal_lambdas[0] == pytest.approx(f_buf)        # MIN scores more vs a bad BUF goalie
    assert out.home.period_goal_lambdas[0] == pytest.approx(f_min)
    assert f_buf > 1.0
    assert out.home.goals_per_60 == g.home.goals_per_60                  # props' rate untouched


def test_off_switch_and_unmapped_starter(tmp_path, monkeypatch):
    g, _t, _lr = _slate(tmp_path, [(8479312, 60.0, 30.0)], monkeypatch)   # neither starter has shots -> no factor
    assert producer._apply_goalie_gsax([g], "2026-10-06", tmp_path)[0] is g
    monkeypatch.setenv(G.ENV, "off")
    assert producer._apply_goalie_gsax([g], "2026-10-06", tmp_path)[0] is g
