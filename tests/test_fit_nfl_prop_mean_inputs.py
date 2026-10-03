"""Unit tests for scripts/fit_nfl_prop_mean_inputs.py -- weighting, inputs and the verdict rule."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fit_nfl_prop_mean_inputs.py"
_spec = importlib.util.spec_from_file_location("fit_nfl_mean", _PATH)
fit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fit)  # type: ignore[union-attr]


def test_ewma_weights_recent_games_more():
    assert fit.ewma([], 3.0) is None
    assert fit.ewma([5.0, 5.0, 5.0], 2.0) == pytest.approx(5.0)
    # most recent value last: a short half-life sits closer to it than a long one
    assert fit.ewma([0.0, 0.0, 10.0], 1.0) > fit.ewma([0.0, 0.0, 10.0], 12.0)


def test_every_market_reads_a_game_key_the_usage_table_writes():
    # the first run read g["rushing_attempts"], which Usage never writes; a defaultdict returned 0 and
    # the ewma mean was silently 0 for both attempts markets
    written = {"targets", "receptions", "receiving_yards", "rushes", "rushing_yards", "pass_att", "passing_yards"}
    assert set(fit.GAME_KEY) == set(fit.CONTINUOUS)
    assert set(fit.GAME_KEY.values()) <= written
    assert {u for u, _n, _m in fit.USAGE.values()} <= written


def test_load_injuries_keeps_only_out_and_doubtful_regular_season(tmp_path):
    d = tmp_path / "tracking" / "nflverse" / "injuries"
    d.mkdir(parents=True)
    (d / "injuries_2025.csv").write_text(
        "season,game_type,team,week,gsis_id,report_status\n"
        "2025,REG,KC,3,A,Out\n2025,REG,KC,3,B,Questionable\n2025,REG,KC,3,C,Doubtful\n"
        "2025,POST,KC,19,D,Out\n2025,REG,KC,3,,Out\n", encoding="utf-8")
    inj = fit.load_injuries(tmp_path, [2025])
    assert inj[(2025, 3, "KC")] == {"A", "C"}
    assert (2025, 19, "KC") not in inj


def test_info_beyond_line_detects_signal_and_its_absence():
    rows, means = [], []
    for i in range(200):
        line = 50.0
        dev = (i % 20) - 10.0
        rows.append({"gid": f"g{i}", "player": "p", "book": "dk", "p_book": 0.5, "line": line, "actual": line + dev})
        means.append(line + dev)          # mean predicts the deviation exactly
    assert fit.info_beyond_line(rows, means)["corr"] == pytest.approx(1.0)
    flat = [50.0 + ((i * 7) % 13) - 6 for i in range(200)]   # unrelated to the outcome
    assert abs(fit.info_beyond_line(rows, flat)["corr"]) < 0.3


def test_verdict_requires_slope_ci_above_zero_and_a_brier_gain_for_both_markets():
    good = {"2025 holdout": {"slope_ci": {"ci95": [0.1, 0.4]}, "dbrier_vs_prod": {"ci95": [-0.01, -0.001]}}}
    flat = {"2025 holdout": {"slope_ci": {"ci95": [-0.1, 0.3]}, "dbrier_vs_prod": {"ci95": [-0.01, -0.001]}}}
    prod = {"2025 holdout": {"slope_ci": {"ci95": [-0.1, 0.1]}, "dbrier_vs_prod": {"ci95": [0.0, 0.0]}}}
    met = fit.verdict({"receptions": {"arms": {"prod": prod, "share": good}},
                       "receiving_yards": {"arms": {"prod": prod, "share": good}}})
    assert met["LANE_BAR"] == "MET"
    not_met = fit.verdict({"receptions": {"arms": {"prod": prod, "share": good}},
                           "receiving_yards": {"arms": {"prod": prod, "share": flat}}})
    assert not_met["LANE_BAR"] == "NOT MET"
