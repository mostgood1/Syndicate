"""Tests for the hockeysim calibration lane (benchmark / evaluator / derive / convergence).

All synthetic + offline. The key test is *convergence*: deriving profile overrides from a truth
snapshot and applying them must drive the accept score close to 1.0 — i.e. the calibration loop
actually makes the projection reproduce the truth.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.calibration import (
    Benchmark,
    CALIBRATED_METRIC_NAMES,
    PROJECTION_METRIC_NAMES,
    derive_projection_overrides,
    evaluate,
    measure_projection_profile,
    render_calibration_report,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import (
    HistoricalGameRecord,
    build_truth_snapshot,
)
from syndicate.features.nhl.sim_engine.hockeysim.projection import NHL_PROJECTION_PROFILE


def _synthetic_snapshot(home_goals=3, away_goals=3, p_goals=((1, 1), (1, 1), (1, 1))):
    """Build a TruthSnapshot from N identical synthetic games (deterministic targets)."""
    recs = [
        HistoricalGameRecord(
            game_id=str(i), date="2026-01-10", season="20252026", game_type=2,
            home_abbr="AAA", away_abbr="BBB", home_goals=home_goals, away_goals=away_goals,
            home_sog=30, away_sog=30, period_goals=p_goals,
        )
        for i in range(20)
    ]
    return build_truth_snapshot(recs)


def test_benchmark_from_truth_has_targets_and_tolerances():
    bench = Benchmark.from_truth(_synthetic_snapshot())
    names = bench.metric_names()
    assert "goals_per_game" in names and "period2_share" in names
    for t in bench.targets:
        assert t.tolerance > 0


def test_evaluate_perfect_match_scores_one():
    bench = Benchmark.from_truth(_synthetic_snapshot())
    measured = bench.target_map()  # measured == target exactly
    res = evaluate(bench, measured)
    assert res.score == pytest.approx(1.0)


def test_evaluate_penalizes_error():
    bench = Benchmark.from_truth(_synthetic_snapshot())
    measured = dict(bench.target_map())
    measured["goals_per_game"] += 1.5  # ~2 tolerances off
    res = evaluate(bench, measured)
    assert res.score < 1.0
    worst = res.worst(1)[0]
    assert worst.name == "goals_per_game"


def test_evaluate_metric_names_restriction():
    bench = Benchmark.from_truth(_synthetic_snapshot())
    measured = bench.target_map()
    res = evaluate(bench, measured, metric_names=["goals_per_game"])
    assert [m.name for m in res.metric_scores] == ["goals_per_game"]


def test_measure_projection_profile_keys_and_shares():
    measured = measure_projection_profile(n_sims=5000)
    assert set(measured) == set(PROJECTION_METRIC_NAMES)
    # measured period shares equal the profile's configured shares (projection applies them).
    p = NHL_PROJECTION_PROFILE
    assert measured["period1_share"] == pytest.approx(p.period_shares[0], abs=1e-3)


def test_derive_projection_overrides_math():
    # goals 6.0, home 3.3, away 2.7 -> base 3.0, home_ice 1.1, away_ice 0.9
    snap = _synthetic_snapshot(home_goals=33, away_goals=27, p_goals=((10, 8), (11, 9), (12, 10)))
    ov = derive_projection_overrides(snap)
    assert ov["league_baseline_goals_per_60"] == pytest.approx(30.0, abs=0.01)
    assert ov["home_ice_attack_mult"] == pytest.approx(1.1, abs=0.01)
    assert ov["away_ice_attack_mult"] == pytest.approx(0.9, abs=0.01)
    assert len(ov["period_shares"]) == 3
    assert sum(ov["period_shares"]) == pytest.approx(1.0, abs=1e-3)


def test_calibration_convergence():
    """Deriving + applying overrides must drive the calibrated-metric score near 1.0."""
    # Realistic-ish truth: home 3.5 / away 3.0 with a P2-heavy shape.
    snap = _synthetic_snapshot(home_goals=7, away_goals=6, p_goals=((2, 1), (3, 3), (2, 2)))
    bench = Benchmark.from_truth(snap)

    before = evaluate(bench, measure_projection_profile(n_sims=8000), metric_names=CALIBRATED_METRIC_NAMES)
    overrides = derive_projection_overrides(snap)
    calibrated = replace(NHL_PROJECTION_PROFILE, **overrides)
    after = evaluate(
        bench, measure_projection_profile(calibrated, n_sims=8000), metric_names=CALIBRATED_METRIC_NAMES
    )
    assert after.score > before.score
    assert after.score > 0.95  # calibrated profile reproduces the directly-tuned truth metrics

    # home_win_pct is emergent (Poisson consequence of the means), so only sanity-check its band.
    measured = measure_projection_profile(calibrated, n_sims=8000)
    assert 0.45 < measured["home_win_pct"] < 0.65


def test_render_calibration_report_smoke():
    snap = _synthetic_snapshot()
    bench = Benchmark.from_truth(snap)
    before = evaluate(bench, measure_projection_profile(n_sims=4000), metric_names=PROJECTION_METRIC_NAMES)
    md = render_calibration_report(title="Test", truth=snap.to_dict(), before=before)
    assert "# Test" in md and "Accept score before" in md
