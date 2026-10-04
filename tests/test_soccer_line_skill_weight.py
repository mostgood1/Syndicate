"""Per-line skill weight for soccer edges (lane soccer-skill-registry-line-weighting).

Every line is still judged on its own; the weight sets how much of the model's disagreement with the de-vigged book
each line's edge keeps. REACHABILITY FIRST (model_engine_standard 4.3): flag off leaves the edge exactly as before;
flag on scales it and keeps the raw edge beside it. Live rows and markets without a fitted weight are untouched.
"""

from __future__ import annotations

from unittest import mock

import pytest

from syndicate.features.shared import soccer_projections as sp


def _row(**over):
    row = {"sport": "soccer", "kind": "game", "market": "totals", "line": 2.5, "sides": ["over", "under"],
           "consensus": {"over": -110, "under": -110}, "game": {"state": "pregame"}}
    row.update(over)
    return row


def _price(flag: bool, weights=None, **over):
    projection = {"model_prob_over": 0.62, "basis": "over_2_5_probability"}
    env = {sp._LINE_SKILL_WEIGHT_ENV: "1"} if flag else {}
    with mock.patch.dict("os.environ", env, clear=False):
        if not flag:
            import os
            os.environ.pop(sp._LINE_SKILL_WEIGHT_ENV, None)
        if weights is not None:
            with mock.patch.dict(sp._LINE_SKILL_WEIGHTS, weights):
                sp._price_against_market(_row(**over), projection)
        else:
            sp._price_against_market(_row(**over), projection)
    return projection


def test_control_the_fixture_prices_an_edge():
    p = _price(False)
    assert p["edge_vs_market_pct"] == pytest.approx(12.0, abs=0.01)


def test_flag_off_is_unchanged_and_stamps_nothing():
    p = _price(False)
    assert "skill_edge_weight" not in p and "edge_vs_market_pct_raw" not in p


def test_flag_on_scales_the_edge_and_keeps_the_raw_one():
    p = _price(True, weights={"totals": {"w": 0.25, "ci95": (0.0, 0.5), "n": 1, "fitted": "test"}})
    assert p["edge_vs_market_pct_raw"] == pytest.approx(12.0, abs=0.01)
    assert p["skill_edge_weight"] == 0.25
    assert p["edge_vs_market_pct"] == pytest.approx(3.0, abs=0.01)


def test_reachability_off_differs_from_on():
    assert _price(False)["edge_vs_market_pct"] != _price(True, weights={"totals": {"w": 0.25}})["edge_vs_market_pct"]


def test_the_shipped_weight_zeroes_the_edge_today():
    """The measured w is 0.000 for totals; flag-on today is a zero edge, which is why it is HELD."""
    assert _price(True)["edge_vs_market_pct"] == 0.0


def test_alias_market_uses_its_base_weight():
    p = _price(True, weights={"totals": {"w": 0.5}}, market="totals_alt")
    assert p["skill_edge_weight"] == 0.5


def test_a_market_without_a_weight_is_untouched():
    p = _price(True, market="btts")
    assert "skill_edge_weight" not in p


def test_a_live_row_is_untouched():
    p = _price(True, weights={"totals": {"w": 0.25}}, game={"state": "live"})
    assert p.get("edge_vs_market_pct") is None and "skill_edge_weight" not in p
