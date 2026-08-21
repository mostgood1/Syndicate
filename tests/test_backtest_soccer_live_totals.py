"""The cutoff-replay harness's own arithmetic.

A harness that scores a model is itself a measuring instrument, and an
instrument nobody checked is how a wrong number acquires authority. These pin
the parts that would silently produce a flattering result.
"""
from __future__ import annotations

import json
import pytest

from scripts.backtest_soccer_live_totals import _p_over, _ratings_from_artifact, _NEUTRAL


def test_p_over_sums_the_arm_above_the_line():
    dist = {"2-0": 0.40, "3-0": 0.25, "2-1": 0.20, "3-1": 0.10, "4-1": 0.05}
    assert _p_over(dist, 2.5) == pytest.approx(0.60)   # 3,3,4,5 goals
    assert _p_over(dist, 3.5) == pytest.approx(0.15)   # 4 and 5 goals
    assert _p_over(dist, 1.5) == pytest.approx(1.0)


def test_non_normalised_distribution_scores_nothing_rather_than_something():
    """Scoring against missing mass would produce a LOW Brier -- i.e. it would
    look like accuracy. Refusing is the only safe direction here."""
    assert _p_over({"1-0": 0.2, "2-0": 0.3}, 2.5) is None


@pytest.mark.parametrize("bad", [None, {}, {"garbage": 1.0}])
def test_unusable_distribution_returns_none(bad):
    assert _p_over(bad, 2.5) is None


def test_ratings_fall_back_to_neutral_and_SAY_SO(tmp_path):
    """A score produced under different ratings than production ran is not a
    reading about production, so the source must travel with the number."""
    p = tmp_path / "recommendations_2026-08-21.json"
    p.write_text(json.dumps({"matches": []}), encoding="utf-8")
    home, away, source = _ratings_from_artifact(p, "Rayo Vallecano")
    assert home == _NEUTRAL and away == _NEUTRAL
    assert "neutral" in source and p.name in source


def test_ratings_are_taken_from_the_production_artifact_when_present(tmp_path):
    p = tmp_path / "recommendations_2026-08-21.json"
    p.write_text(json.dumps({"matches": [{
        "matchup": {"home_team": "Marseille", "away_team": "Strasbourg"},
        "adapter_metadata": {
            "home_rating_detail": {"attack_rating": 0.172, "defense_rating": 0.0257},
            "away_rating_detail": {"attack_rating": 0.0447, "defense_rating": 0.0116},
        },
    }]}), encoding="utf-8")
    home, away, source = _ratings_from_artifact(p, "Marseille")
    assert home["attack_rating"] == 0.172
    assert away["attack_rating"] == 0.0447
    assert "production artifact" in source


def test_unreadable_artifact_is_named_not_swallowed(tmp_path):
    p = tmp_path / "missing.json"
    home, away, source = _ratings_from_artifact(p, "Anyone")
    assert home == _NEUTRAL
    assert "unreadable" in source
