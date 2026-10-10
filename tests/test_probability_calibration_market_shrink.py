"""`market_shrink` cells: `p_cal = fair + w*(p - fair)` (lane mlb-probability-calibration).

Pins: the math, that it scales the edge without flipping its side, w=0 lands on
the fair (edge 0), a cell missing w or a row missing fair degrades to identity
WITH a cell_error, and the board seam passes the row's own fair through.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import probability_calibration as pc
from syndicate.features.shared.layer2_board import build_layer2_rows

from tests.test_probability_calibration_seam import _by_side, _grid_row, _opps, _projection, _write_profile, data_root  # noqa: F401


def _profile(w):
    return pc.ProbabilityCalibrationProfile(version="v-shrink", sport="mlb", cells={"totals|full": {"method": "market_shrink", "w": w}})


def test_market_shrink_math_and_side_preserved():
    p, meta = pc.calibrate("mlb", "totals", "full", 0.60, profile=_profile(0.25), fair=0.52)
    assert meta["method"] == "market_shrink" and meta["cell"] == "totals|full"
    assert p == pytest.approx(0.52 + 0.25 * 0.08)
    p_under, _ = pc.calibrate("mlb", "totals", "full", 0.40, profile=_profile(0.25), fair=0.48)
    assert p + p_under == pytest.approx(1.0), "symmetric across sides when the fairs are complementary"


def test_w_zero_lands_on_the_fair():
    p, meta = pc.calibrate("mlb", "totals", "full", 0.71, profile=_profile(0.0), fair=0.47)
    assert p == pytest.approx(0.47) and meta["method"] == "market_shrink"


@pytest.mark.parametrize("cell", [{"method": "market_shrink"}, {"method": "market_shrink", "w": 1.5}])
def test_bad_cell_is_identity_with_error(cell):
    prof = pc.ProbabilityCalibrationProfile(version="v", sport="mlb", cells={"totals|full": cell})
    p, meta = pc.calibrate("mlb", "totals", "full", 0.6, profile=prof, fair=0.5)
    assert p == 0.6 and meta["method"] == "identity" and "w in [0, 1]" in meta["cell_error"]


def test_missing_fair_is_identity_with_error():
    p, meta = pc.calibrate("mlb", "totals", "full", 0.6, profile=_profile(0.3))
    assert p == 0.6 and meta["method"] == "identity" and "fair" in meta["cell_error"]


def test_seam_passes_the_rows_fair(monkeypatch, data_root):  # noqa: F811
    _write_profile(data_root, "wnba", {"player_points|full": {"method": "market_shrink", "w": 0.5}}, version="v-ms")
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    rows = _by_side(_opps(_grid_row(projection=_projection())))
    for side, raw_edge in (("over", 6.0), ("under", -6.0)):
        r = rows[side]
        assert r["calibration_method"] == "market_shrink"
        assert r["model_edge_pct_raw"] == raw_edge
        # fair is 0.5 a side at -110/-110: half the edge, same sign.
        assert r["model_edge_pct"] == pytest.approx(raw_edge * 0.5, abs=1e-3)


def test_seam_w_zero_zeroes_the_edge(monkeypatch, data_root):  # noqa: F811
    _write_profile(data_root, "wnba", {"player_points|full": {"method": "market_shrink", "w": 0.0}}, version="v-ms0")
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    rows = _by_side(_opps(_grid_row(projection=_projection())))
    assert rows["over"]["model_edge_pct"] == pytest.approx(0.0, abs=1e-9)
    assert rows["over"]["model_probability_cal"] == pytest.approx(0.5, abs=1e-6)
