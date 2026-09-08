"""`lane pricing-plane-v1`, P5 -- the shared probability-calibration seam.

Pins the contract in `layer2_board._calibrate_model_edge` and
`probability_calibration`:

  * `SYNDICATE_PRICING_CALIBRATION` absent/`off` => `build_layer2_rows` is
    BYTE-IDENTICAL to a board that never heard of calibration.
  * `on` + no profile => identity, with the four stamps on the candidate and
    the same edge float the producer priced.
  * `on` + affine cell => the PROBABILITY is calibrated and the edge is
    re-differenced against the same fair; the raw probability and raw edge
    survive beside it.
  * isotonic interpolates between breakpoints and clamps outside them.
  * a row its sport already calibrated (`basketball_props_edges` shape) is
    skipped as `upstream`.
  * an exact certainty produced BY the curve is refused, not priced.
  * the harness writes only a cell that beats raw held-out with enough test
    rows, and refuses to pool artifact roots.
"""
from __future__ import annotations

import json
import math
import random

import pytest

from syndicate.features.shared import probability_calibration as pc
from syndicate.features.shared.layer2_board import build_layer2_rows


def _grid_row(**overrides):
    row = {
        "sport": "wnba",
        "event_id": "evt-1",
        "kind": "prop",
        "market": "player_points",
        "segment": "full",
        "line": 18.5,
        "player_name": "A. Player",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2099-01-01T00:00:00Z",
        "sides": ["over", "under"],
        "books_quoting": 2,
        # Both sides at one book => a measured two-sided consensus fair of 0.5
        # each (`_fair_by_side`), which is what the seam re-differences against.
        "cells": {
            "draftkings": {"over": {"price": -110}, "under": {"price": -110}},
            "fanduel": {"over": {"price": -110}, "under": {"price": -110}},
        },
        "best": {
            "over": {"price": -110, "bookmaker": "draftkings", "books_quoting": 2, "age_seconds": 30.0},
            "under": {"price": -110, "bookmaker": "fanduel", "books_quoting": 2, "age_seconds": 30.0},
        },
    }
    row.update(overrides)
    return row


def _projection(**overrides):
    projection = {"edge_vs_market_pct": 6.0, "side": "over", "model_prob_over": 0.56, "mean": 21.4}
    projection.update(overrides)
    return projection


def _opps(row):
    return list(build_layer2_rows([row]).get("opportunities") or [])


def _by_side(rows):
    return {str(r.get("side")): r for r in rows}


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(root))
    pc.clear_profile_cache()
    yield root
    pc.clear_profile_cache()


def _write_profile(root, sport, cells, version="v-test"):
    profile = pc.ProbabilityCalibrationProfile(version=version, sport=sport, cells=cells)
    path = pc.save_profile(profile, data_root=root)
    pc.clear_profile_cache()
    return path


STAMPS = ("model_probability_raw", "model_probability_cal", "model_edge_pct_raw", "calibration_version", "calibration_method")


# --------------------------------------------------------------------------
# Off => byte-identical
# --------------------------------------------------------------------------


def test_env_absent_is_byte_identical_and_stamps_nothing(monkeypatch, data_root):
    _write_profile(data_root, "wnba", {"player_points|full": {"method": "affine_logit", "a": 0.0, "b": 0.5}})
    monkeypatch.delenv("SYNDICATE_PRICING_CALIBRATION", raising=False)
    absent = json.dumps(build_layer2_rows([_grid_row(projection=_projection())]), sort_keys=True, default=str)
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "off")
    off = json.dumps(build_layer2_rows([_grid_row(projection=_projection())]), sort_keys=True, default=str)
    assert absent == off
    for stamp in STAMPS:
        assert stamp not in absent, f"{stamp} leaked onto an OFF board"
    rows = _by_side(_opps(_grid_row(projection=_projection())))
    assert rows["over"]["model_edge_pct"] == 6.0
    assert rows["under"]["model_edge_pct"] == -6.0
    # The projection object is carried verbatim -- the seam never writes to it.
    assert rows["over"]["projection"] == _projection()


# --------------------------------------------------------------------------
# On, no profile => identity with stamps
# --------------------------------------------------------------------------


def test_on_without_profile_is_identity_with_stamps(monkeypatch, data_root):
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    rows = _by_side(_opps(_grid_row(projection=_projection())))
    over, under = rows["over"], rows["under"]
    assert over["model_edge_pct"] == 6.0 and under["model_edge_pct"] == -6.0
    for r in (over, under):
        assert r["calibration_method"] == "identity"
        assert r["calibration_version"] is None
        assert r["model_edge_pct_raw"] == r["model_edge_pct"]
        assert r["model_probability_raw"] == r["model_probability_cal"]
    # -110/-110 de-vigs to 0.5 a side, so the recovered probability is fair + edge/100.
    assert over["model_probability_raw"] == pytest.approx(0.56, abs=1e-6)
    assert under["model_probability_raw"] == pytest.approx(0.44, abs=1e-6)
    assert over["projection"] == _projection(), "the seam must not write to the shared projection dict"


# --------------------------------------------------------------------------
# On + affine cell => probability calibrated, edge re-differenced, raw kept
# --------------------------------------------------------------------------


def test_on_with_affine_profile_recomputes_edge_and_keeps_raw(monkeypatch, data_root):
    a, b = 0.0, 0.5
    _write_profile(data_root, "wnba", {"player_points|full": {"method": "affine_logit", "a": a, "b": b}}, version="v-affine")
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    rows = _by_side(_opps(_grid_row(projection=_projection())))
    for side, raw_edge in (("over", 6.0), ("under", -6.0)):
        r = rows[side]
        fair = r["model_probability_raw"] - raw_edge / 100.0
        p_cal = pc.apply_affine_logit(r["model_probability_raw"], a, b)
        assert r["calibration_method"] == "affine_logit"
        assert r["calibration_version"] == "v-affine"
        assert r["calibration_cell"] == "player_points|full"
        assert r["model_edge_pct_raw"] == raw_edge
        assert r["model_probability_cal"] == pytest.approx(p_cal, abs=1e-6)
        assert r["model_edge_pct"] == pytest.approx((p_cal - fair) * 100.0, abs=1e-3)
        assert r["model_edge_pct"] != raw_edge
    # Halving the logit shrinks a +6 edge at p=0.56 to about +3.
    assert rows["over"]["model_edge_pct"] == pytest.approx(3.011, abs=0.01)
    assert rows["under"]["model_edge_pct"] == pytest.approx(-3.011, abs=0.01)
    # The projection itself is untouched: two sides share it.
    assert rows["over"]["projection"] == _projection()


def test_wildcard_segment_answers_when_exact_cell_is_absent(monkeypatch, data_root):
    _write_profile(data_root, "wnba", {"player_points|*": {"method": "affine_logit", "a": 0.0, "b": 0.5}})
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    over = _by_side(_opps(_grid_row(projection=_projection())))["over"]
    assert over["calibration_cell"] == "player_points|*"
    assert over["calibration_method"] == "affine_logit"


def test_explicit_model_probability_on_projection_is_preferred(monkeypatch, data_root):
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    over = _by_side(_opps(_grid_row(projection=_projection(model_probability=0.61))))["over"]
    assert over["model_probability_raw"] == pytest.approx(0.61)


# --------------------------------------------------------------------------
# The transform itself
# --------------------------------------------------------------------------


def test_isotonic_interpolates_and_clamps():
    profile = pc.ProbabilityCalibrationProfile(
        version="v-iso",
        sport="mlb",
        cells={"batter_hits|*": {"method": "isotonic", "x": [0.2, 0.4, 0.8], "y": [0.1, 0.5, 0.7]}},
    )
    mid, meta = pc.calibrate("mlb", "batter_hits", "full", 0.3, profile=profile)
    assert mid == pytest.approx(0.3)  # halfway between (0.2,0.1) and (0.4,0.5)
    assert meta["method"] == "isotonic" and meta["cell"] == "batter_hits|*" and meta["version"] == "v-iso"
    low, _ = pc.calibrate("mlb", "batter_hits", "full", 0.05, profile=profile)
    high, _ = pc.calibrate("mlb", "batter_hits", "full", 0.99, profile=profile)
    assert low == pytest.approx(0.1) and high == pytest.approx(0.7), "outside the fitted range the curve clamps, never extrapolates"
    exact, _ = pc.calibrate("mlb", "batter_hits", "full", 0.4, profile=profile)
    assert exact == pytest.approx(0.5)


def test_identity_when_no_cell_or_malformed_cell():
    profile = pc.ProbabilityCalibrationProfile(
        version="v", sport="nhl", cells={"totals|*": {"method": "isotonic", "x": [0.5, 0.2], "y": [0.1, 0.9]}}
    )
    p, meta = pc.calibrate("nhl", "h2h", "full", 0.42, profile=profile)
    assert p == 0.42 and meta["method"] == "identity" and meta["cell"] is None
    p, meta = pc.calibrate("nhl", "totals", "full", 0.42, profile=profile)
    assert p == 0.42 and meta["method"] == "identity" and "cell_error" in meta
    p, meta = pc.calibrate("nhl", "totals", "full", 0.42, profile=None)
    assert p == 0.42 and meta["method"] == "identity" and meta["version"] is None


def test_affine_logit_identity_parameters_are_identity():
    for p in (0.05, 0.3, 0.5, 0.77, 0.95):
        assert pc.apply_affine_logit(p, 0.0, 1.0) == pytest.approx(p, abs=1e-9)


# --------------------------------------------------------------------------
# Upstream-calibrated rows are skipped
# --------------------------------------------------------------------------


def test_upstream_calibrated_basketball_row_is_not_double_calibrated(monkeypatch, data_root):
    _write_profile(data_root, "nba", {"player_points|full": {"method": "affine_logit", "a": 0.0, "b": 0.5}})
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    projection = _projection(source="basketball_props_edges", model_prob_raw=0.58, prob_calibrated=True)
    rows = _by_side(_opps(_grid_row(sport="nba", projection=projection)))
    assert rows["over"]["calibration_method"] == "upstream"
    assert rows["over"]["model_edge_pct"] == 6.0
    assert rows["over"]["model_probability_cal"] == rows["over"]["model_probability_raw"]


# --------------------------------------------------------------------------
# Certainty refusal survives the curve
# --------------------------------------------------------------------------


def test_certainty_refusal_upstream_still_blanks_the_edge(monkeypatch, data_root):
    _write_profile(data_root, "wnba", {"player_points|full": {"method": "affine_logit", "a": 0.0, "b": 0.5}})
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    rows = _by_side(_opps(_grid_row(projection=_projection(model_prob_over=0.0, edge_vs_market_pct=-50.0))))
    assert rows, "the row still ranks on its measured market EV -- it just carries no model view"
    for r in rows.values():
        # `refuse_published_certainty` blanked the projection BEFORE the seam,
        # so there is no edge to calibrate and nothing is stamped.
        assert r["model_edge_pct"] is None
        assert r["projection"]["model_prob_over"] is None
        assert r["projection"]["model_prob_over_refused"] == "exact_certainty"
        assert "calibration_method" not in r


def test_certainty_produced_by_the_curve_is_refused_not_priced(monkeypatch, data_root):
    # A clamped isotonic cell that maps everything to exactly 1.0.
    _write_profile(data_root, "wnba", {"player_points|full": {"method": "isotonic", "x": [0.0, 1.0], "y": [1.0, 1.0]}})
    monkeypatch.setenv("SYNDICATE_PRICING_CALIBRATION", "on")
    rows = _by_side(_opps(_grid_row(projection=_projection())))
    assert rows, "the row still ranks on its measured market EV"
    for r in rows.values():
        assert r["model_edge_pct"] is None, "an exact certainty out of the curve is refused, not priced"
        assert r["calibration_refused"] == "exact_certainty"
        assert r["calibration_method"] == "isotonic"
        assert r["model_probability_cal"] == 1.0
        assert r["model_edge_pct_raw"] in (6.0, -6.0)


# --------------------------------------------------------------------------
# Profile store round-trip
# --------------------------------------------------------------------------


def test_profile_round_trips_through_calibration_profile_store(data_root):
    path = _write_profile(data_root, "soccer", {"h2h|*": {"method": "affine_logit", "a": 0.1, "b": 0.9, "n": 500}}, version="v-rt")
    assert path == data_root / "soccer_source" / "calibration" / "probability_calibration.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == "v-rt" and payload["fields"]["cells"]["h2h|*"]["a"] == 0.1
    profile, meta = pc.load_profile("soccer", data_root=data_root)
    assert meta["source"] == "artifact" and profile.version == "v-rt"
    assert profile.cells["h2h|*"]["n"] == 500
    missing, meta = pc.load_profile("nhl", data_root=data_root)
    assert missing is pc.IDENTITY_PROFILE and meta["source"] == "default"


def test_profile_path_is_allowlisted():
    from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path

    for sport in ("mlb", "soccer", "wnba", "nba", "nhl", "nfl", "ncaaf", "ncaab"):
        assert is_hot_artifact_relative_path(f"{sport}_source/calibration/probability_calibration.json")


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------


def _synthetic_rows(n, *, seed, sport="mlb", market="batter_hits", segment="full", root="/root/a", overconfident=2.0):
    """Model says p; truth is sigmoid(logit(p)/overconfident) -- the model is
    overconfident by that factor, so an affine curve with b ~ 1/overconfident
    should beat raw held out."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        p = min(0.98, max(0.02, rng.betavariate(2.0, 2.0)))
        true = 1.0 / (1.0 + math.exp(-math.log(p / (1 - p)) / overconfident))
        rows.append(
            {
                "sport": sport,
                "market": market,
                "segment": segment,
                "model_probability": p,
                "y": 1 if rng.random() < true else 0,
                "date": f"2026-{1 + i // 900:02d}-{1 + (i // 30) % 28:02d}",
                "scorer_version": "s1",
                "artifact_root": root,
            }
        )
    return rows


def _load_harness():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "fit_probability_calibration.py"
    spec = importlib.util.spec_from_file_location("fit_probability_calibration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_harness_writes_only_a_winning_cell_with_enough_test_rows(data_root, capsys):
    harness = _load_harness()
    rows = _synthetic_rows(3000, seed=7) + _synthetic_rows(120, seed=8, market="batter_home_runs")
    code, report = harness.run(rows, artifact_root="/root/a", scorer_version=None, train_frac=0.7, min_test=200, write=True, data_root=data_root, version="v-h")
    assert code == 0
    cells = {(c["market"], c["winner"]) for c in report["cells"]}
    assert ("batter_hits", "affine_logit") in cells or ("batter_hits", "isotonic") in cells
    thin = next(c for c in report["cells"] if c["market"] == "batter_home_runs")
    assert thin["winner"] == "raw" and "n_test" in str(thin["reason"])
    profile, meta = pc.load_profile("mlb", data_root=data_root)
    assert meta["source"] == "artifact"
    assert set(profile.cells) == {"batter_hits|full"}
    cell = profile.cells["batter_hits|full"]
    assert cell["held_out_brier_cal"] < cell["held_out_brier_raw"]
    assert cell["n_test"] >= 200 and cell["version"] == "v-h" and cell["scorer_version"] == "s1"
    for key in ("fitted_on", "n", "held_out_logloss_raw", "held_out_logloss_cal", "artifact_root"):
        assert key in cell
    out = capsys.readouterr().out
    assert "batter_hits" in out and "batter_home_runs" in out, "the per-cell table prints either way"


def test_harness_dry_run_by_default_writes_nothing(data_root):
    harness = _load_harness()
    code, report = harness.run(_synthetic_rows(3000, seed=7), artifact_root="/root/a", scorer_version=None, train_frac=0.7, min_test=200, write=False, data_root=data_root)
    assert code == 0 and report["written"] == []
    assert not (data_root / "mlb_source").exists()


def test_harness_refuses_to_pool_artifact_roots(data_root):
    harness = _load_harness()
    rows = _synthetic_rows(1500, seed=1, root="/root/a") + _synthetic_rows(1500, seed=2, root="/root/b")
    code, report = harness.run(rows, artifact_root="/root/a", scorer_version=None, train_frac=0.7, min_test=200, write=True, data_root=data_root)
    assert code == harness.EXIT_REFUSED and report["refused"] and report["written"] == []
    assert not (data_root / "mlb_source").exists()


def test_harness_refuses_mixed_scorer_versions_unless_selected(data_root):
    harness = _load_harness()
    rows = _synthetic_rows(1500, seed=1)
    for r in rows[:700]:
        r["scorer_version"] = "s0"
    code, report = harness.run(rows, artifact_root="/root/a", scorer_version=None, train_frac=0.7, min_test=200, write=True, data_root=data_root)
    assert code == 0 and report["refused"] and report["written"] == []
    code, report = harness.run(rows, artifact_root="/root/a", scorer_version="s1", train_frac=0.7, min_test=200, write=False, data_root=data_root)
    assert code == 0 and not report["refused"] and report["cells"][0]["n"] == 800


def test_harness_recovers_probability_from_an_order_the_way_the_sizer_does():
    harness = _load_harness()
    order = {"sport": "mlb", "market": "h2h", "segment": None, "outcome": "won", "fill_price": -110, "ev_pct": 3.0, "model_edge_pct": 4.0, "selected_date": "2026-09-01"}
    row = harness.row_from_order(order, artifact_root="/r")
    profit = 100.0 / 110.0
    fair = (0.03 + 1.0) / (profit + 1.0)
    assert row["model_probability"] == pytest.approx(fair + 0.04)
    assert row["y"] == 1 and row["segment"] == "*" and row["scorer_version"] == "unversioned"
    assert harness.row_from_order({**order, "outcome": "push"}, artifact_root="/r") is None
