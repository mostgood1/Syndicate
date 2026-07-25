"""Tests for the props producer (props_recommendations_{date}.csv).

Covers the props-lines reader normalization, the Poisson p_over tail, the recommendation row
(side selection / EV / edge_score), and the end-to-end producer against the real 2026-06-14 mirror.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.artifacts import (
    PROPS_RECOMMENDATIONS_COLUMNS,
    prop_recommendation_row,
)
from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyPropProjection
from syndicate.features.nhl.sim_engine.hockeysim.features.props_lines import normalize_name


def _proj(p_over=None, p_under=None, **kw):
    base = dict(
        date="2026-06-14", player_id=1, player="Test Player", team="CAR", opp="VGK",
        market="SOG", proj_lambda=2.0, proj=2.0, line=0.5, p_over=p_over, p_under=p_under,
    )
    base.update(kw)
    return HockeyPropProjection(**base)


def test_normalize_name():
    assert normalize_name("Alexander Nikishin") == "alexander nikishin"
    assert normalize_name("T.J. Oshie") == "tj oshie"
    assert normalize_name("Tim Stützle") == "tim stutzle"   # accent folded


def test_poisson_p_over_matches_mirror():
    # mirror sample: proj_lambda=2.0, line=0.5 -> p_over = 1 - e^-2 = 0.8647
    from scripts.build_nhl_artifacts import _poisson_p_over
    assert _poisson_p_over(0.5, 2.0) == pytest.approx(0.864664, abs=1e-5)
    assert _poisson_p_over(2.5, 2.0) == pytest.approx(1 - (2.718281828 ** -2) * (1 + 2 + 2), abs=1e-3)


def test_prop_recommendation_row_picks_higher_ev_side():
    # strong over lean, plus-money over -> Over selected
    row = prop_recommendation_row(_proj(p_over=0.86, p_under=0.14), over_price=-195, under_price=145, book="pinnacle")
    assert row is not None
    assert set(row.keys()) == set(PROPS_RECOMMENDATIONS_COLUMNS)
    assert row["side"] == "Over"
    assert row["chosen_prob"] == pytest.approx(0.86)
    assert row["edge_score"] == pytest.approx(2 * 0.86 - 1)
    assert "JUICE+" in row["edge_drivers"]        # -195 <= -150
    assert row["price"] == -195


def test_prop_recommendation_row_none_without_line_probs():
    assert prop_recommendation_row(_proj(p_over=None, p_under=None), over_price=-110, under_price=-110, book="x") is None


def test_prop_recommendation_row_none_without_prices():
    assert prop_recommendation_row(_proj(p_over=0.6, p_under=0.4), over_price=None, under_price=None, book="x") is None


def test_props_producer_end_to_end_real_slate(tmp_path):
    from scripts.build_nhl_artifacts import build_props_for_date

    path, n = build_props_for_date("2026-06-14", n_sims=120, out_dir=tmp_path)
    if n == 0:
        pytest.skip("no mirrored scoreboard/props lines for 2026-06-14")
    with Path(path).open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == PROPS_RECOMMENDATIONS_COLUMNS
        rows = list(reader)
    assert len(rows) == n
    r = rows[0]
    assert r["side"] in ("Over", "Under")
    assert 0.0 <= float(r["chosen_prob"]) <= 1.0
    assert r["market"] in ("SOG", "GOALS", "ASSISTS", "POINTS", "SAVES", "BLOCKS")
