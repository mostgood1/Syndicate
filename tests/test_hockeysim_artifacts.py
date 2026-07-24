"""Tests for the hockeysim artifact writer + local producer (Phase 5).

Covers the predictions_{date}.csv column contract, row mapping, the consensus market-lines reader,
and the end-to-end producer against the shipped 2026-06-14 mirror.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.artifacts import (
    PREDICTIONS_COLUMNS,
    prediction_to_row,
    write_predictions_csv,
)
from syndicate.features.nhl.sim_engine.hockeysim.contracts import (
    HockeyGamePrediction,
    HockeyMarketLines,
)


def _pred(**kw) -> HockeyGamePrediction:
    base = dict(
        home="Home", away="Away", date="2026-01-15", game_pk="9001",
        proj_home_goals=3.2, proj_away_goals=2.9, model_total=6.1, model_spread=0.3,
        period_home_proj=(1.0, 1.1, 1.1), period_away_proj=(0.9, 1.0, 1.0),
        p_home_ml=0.55, p_away_ml=0.45, p_over=0.5, p_under=0.45, p_push_total=0.05,
        p_home_pl_minus_1_5=0.3, p_away_pl_plus_1_5=0.7, p_f10_yes=0.6, p_f10_no=0.4,
        totals_line_used=6.0, ev={"home_ml": 0.02, "over": -0.03},
    )
    base.update(kw)
    return HockeyGamePrediction(**base)


def test_prediction_to_row_has_exact_columns():
    row = prediction_to_row(_pred(), HockeyMarketLines(home_ml_odds=-120, away_ml_odds=100, total_line=6.0))
    assert set(row.keys()) == set(PREDICTIONS_COLUMNS)
    assert row["home"] == "Home"
    assert row["model_spread"] == pytest.approx(0.3)
    assert row["home_ml_odds"] == -120
    assert row["ev_home_ml"] == pytest.approx(0.02)
    assert row["ev_over"] == pytest.approx(-0.03)
    # a market not carrying puckline odds -> None passthrough
    assert row["home_pl_-1.5_odds"] is None


def test_write_predictions_csv_roundtrip(tmp_path):
    out = tmp_path / "predictions_2026-01-15.csv"
    n = write_predictions_csv(out, [_pred(game_pk="1"), _pred(game_pk="2", home="H2", away="A2")],
                              markets={"1": HockeyMarketLines(home_ml_odds=-120, away_ml_odds=100)})
    assert n == 2
    with out.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == PREDICTIONS_COLUMNS
        rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["home_ml_odds"] == "-120"      # market 1 applied
    assert rows[1]["home_ml_odds"] == ""          # game 2 had no market


def test_market_lines_reader_real_mirror():
    from syndicate.features.nhl.sim_engine.hockeysim.features.market_lines import load_market_lines, market_for_game
    lines = load_market_lines("2026-06-14")
    if not lines:
        pytest.skip("no mirrored team odds for 2026-06-14")
    m = market_for_game(lines, "Vegas Golden Knights", "Carolina Hurricanes")
    assert m is not None
    assert m.total_line == pytest.approx(6.0)
    assert m.home_ml_odds is not None and m.away_ml_odds is not None


def test_producer_end_to_end_real_slate(tmp_path):
    from scripts.build_nhl_artifacts import build_predictions_for_date

    path, n = build_predictions_for_date("2026-06-14", out_dir=tmp_path)
    if n == 0:
        pytest.skip("no mirrored scoreboard for 2026-06-14")
    with Path(path).open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == PREDICTIONS_COLUMNS
        rows = list(reader)
    assert len(rows) == n
    r = rows[0]
    total = float(r["model_total"])
    assert 4.0 <= total <= 9.0                      # sane NHL total (vs the stale vendor 11.4)
    assert 0.0 < float(r["p_home_ml"]) < 1.0
    assert abs(float(r["p_home_ml"]) + float(r["p_away_ml"]) - 1.0) < 1e-6
