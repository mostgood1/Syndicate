"""Tests for the recommendations_sim producer (leaning pick per market)."""
from __future__ import annotations

import csv

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.artifacts import (
    RECOMMENDATIONS_SIM_COLUMNS,
    recommendation_sim_rows,
    write_recommendations_sim_csv,
)
from syndicate.features.nhl.sim_engine.hockeysim.contracts import (
    HockeyGamePrediction,
    HockeyMarketLines,
)


def _pred(**kw):
    base = dict(
        home="Home", away="Away", date="2026-01-15", game_pk="1",
        proj_home_goals=3.2, proj_away_goals=2.8, model_total=6.0, model_spread=0.4,
        period_home_proj=(1.0, 1.1, 1.1), period_away_proj=(0.9, 1.0, 0.9),
        p_home_ml=0.58, p_away_ml=0.42, p_over=0.55, p_under=0.45, p_push_total=0.0,
        p_home_pl_minus_1_5=0.34, p_away_pl_plus_1_5=0.66, p_f10_yes=0.6, p_f10_no=0.4,
        totals_line_used=6.0, ev={"home_ml": 0.03, "over": -0.02, "away_pl_+1.5": 0.01},
    )
    base.update(kw)
    return HockeyGamePrediction(**base)


def test_recommendation_rows_pick_leaning_side_and_conf():
    rows = recommendation_sim_rows(_pred(), HockeyMarketLines(home_ml_odds=-140, over_odds=-110, away_pl_odds=120))
    by_market = {r["market"]: r for r in rows}
    assert set(by_market) == {"ML", "TOTAL", "PL"}
    # ML -> home (higher prob), conf = prob - 0.5
    assert by_market["ML"]["side"] == "Home"
    assert by_market["ML"]["conf"] == pytest.approx(0.58 - 0.5)
    assert by_market["ML"]["price"] == -140
    # TOTAL -> Over (0.55 > 0.45)
    assert by_market["TOTAL"]["side"] == "Over"
    # PL -> away +1.5 (0.66 > 0.34)
    assert by_market["PL"]["side"] == "Away +1.5"
    assert by_market["PL"]["conf"] == pytest.approx(0.66 - 0.5)


def test_write_recommendations_sim_csv(tmp_path):
    out = tmp_path / "recommendations_sim_2026-01-15.csv"
    n = write_recommendations_sim_csv(out, [_pred(game_pk="1"), _pred(game_pk="2")],
                                      markets={"1": HockeyMarketLines(home_ml_odds=-140)})
    assert n == 6  # 3 markets x 2 games
    with out.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == RECOMMENDATIONS_SIM_COLUMNS
        rows = list(reader)
    assert len(rows) == 6
    assert all(float(r["conf"]) >= 0.0 for r in rows)


def test_recommendations_producer_end_to_end(tmp_path):
    from scripts.build_nhl_artifacts import build_recommendations_for_date

    path, n = build_recommendations_for_date("2026-06-14", out_dir=tmp_path)
    if n == 0:
        pytest.skip("no mirrored scoreboard for 2026-06-14")
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows and set(rows[0].keys()) == set(RECOMMENDATIONS_SIM_COLUMNS)
    assert all(r["market"] in ("ML", "TOTAL", "PL") for r in rows)
