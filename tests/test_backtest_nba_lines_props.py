"""Unit tests for scripts/backtest_nba_lines_props.py -- the parts a wrong answer would hide in."""
from __future__ import annotations

import csv
import importlib.util
import io
import contextlib
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bt_nba", REPO / "scripts" / "backtest_nba_lines_props.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)  # type: ignore[union-attr]


def test_pick_never_takes_a_version_committed_at_or_after_first_tip():
    versions = [(100, "a"), (200, "b"), (300, "c")]
    sha, info = bt._pick(versions, cutoff_ts=300)
    assert sha == "b" and info["pre_tip"] == 2
    sha, info = bt._pick(versions, cutoff_ts=100)  # equal to tip is NOT pre-tip
    assert sha is None and info["pre_tip"] == 0


def test_devig_is_proportional_and_symmetric():
    p = bt._devig(-110, -110)
    assert p == pytest.approx(0.5)
    p = bt._devig(-150, 130)
    ia, ib = 150 / 250, 100 / 230
    assert p == pytest.approx(ia / (ia + ib))
    assert bt._devig(-110, None) is None


def test_pred_mean_follows_production_column_rule_and_sums_combos():
    # mean_<stat> column exists -> it is used even if pred_ differs; NaN there stays None (no silent fallback)
    row = {"mean_pts": "20", "pred_pts": "25", "mean_reb": "5", "pred_reb": "9", "mean_ast": "", "pred_ast": "4"}
    m = bt._pred_mean(row, row.keys())
    assert m["pts"] == 20 and m["reb"] == 5 and m["ast"] is None
    assert m["pr"] == 25 and m["pa"] is None
    row2 = {"pred_pts": "25", "pred_reb": "9", "pred_ast": "4"}
    m2 = bt._pred_mean(row2, row2.keys())
    assert m2["pts"] == 25 and m2["ra"] == 13


def test_sim_quarters_reads_both_smart_sim_shapes():
    new = {"periods": {f"q{i}": {"home_mean": 27.0 + i, "away_mean": 26.0} for i in range(1, 5)}}
    old = {"quarters": [{"home_pts_mu": 27.0 + i, "away_pts_mu": 26.0} for i in range(1, 5)]}
    assert bt._sim_quarters(new) == bt._sim_quarters(old) == [(28.0, 26.0), (29.0, 26.0), (30.0, 26.0), (31.0, 26.0)]


def test_boot_ci_clusters_by_game():
    rows = [("g1", 1.0), ("g1", 1.0), ("g2", -1.0)]
    point, lo, hi = bt._boot_ci(rows, n_boot=200)
    assert point == pytest.approx(1 / 3)
    assert lo <= point <= hi
    # a constant difference has a degenerate CI at that constant
    p, lo, hi = bt._boot_ci([("a", 0.2), ("b", 0.2)], n_boot=50)
    assert p == lo == hi == pytest.approx(0.2)


def test_verdict_requires_ci_entirely_one_side_and_min_n():
    assert bt._verdict({"point": -0.1, "ci95": [-0.2, -0.01]}, 500, 200) == "MODEL_BETTER"
    assert bt._verdict({"point": -0.1, "ci95": [-0.2, 0.01]}, 500, 200) == "NO_DIFFERENCE"
    assert bt._verdict({"point": 0.1, "ci95": [0.01, 0.2]}, 500, 200) == "MODEL_WORSE"
    assert bt._verdict({"point": -0.1, "ci95": [-0.2, -0.01]}, 50, 200) == "INSUFFICIENT_N"


def test_harness_normal_matches_production_model_prob_raw(tmp_path):
    """Round-trip the PRODUCTION edges function: the harness's Normal must reproduce model_prob_raw,
    or every probability the backtest scores is a different quantity from the one served."""
    from syndicate.features.shared.basketball_props_edges import _compute_props_edges_file_only_local

    preds = tmp_path / "props_predictions.csv"
    cols = ["player_id", "player_name", "team", "mean_pts", "mean_reb", "mean_ast", "mean_threes", "mean_pra",
            "mean_stl", "mean_blk", "mean_tov", "sd_pts", "sd_reb", "sd_ast"]
    with preds.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerow([1, "Test Player", "AAA", 22.0, 6.0, 4.0, 2.0, 32.0, 1.0, 0.5, 2.0, 6.0, "", 2.0])
    odds = tmp_path / "odds.csv"
    rows = []
    for market, point in (("player_points", 20.5), ("player_rebounds", 5.5), ("player_points_rebounds", 27.5)):
        for side, price in (("Over", -115), ("Under", -105)):
            rows.append(["2026-02-10T20:00:00Z", "e1", "2026-02-11T00:30:00Z", "fanduel", "FanDuel", market, side,
                         "Test Player", point, price, "Home", "Away"])
    with odds.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["snapshot_ts", "event_id", "commence_time", "bookmaker", "bookmaker_title", "market", "outcome_name",
                    "player_name", "point", "price", "home_team", "away_team"])
        w.writerows(rows)
    (tmp_path / "src" / "data" / "processed").mkdir(parents=True)
    with contextlib.redirect_stdout(io.StringIO()):
        edges = _compute_props_edges_file_only_local(source_root=tmp_path / "src", date_str="2026-02-10", raw_path=odds,
                                                     predictions_path=preds, calibrate_prob=True)
    pred_row = {c: v for c, v in zip(cols, ["1", "Test Player", "AAA", "22", "6", "4", "2", "32", "1", "0.5", "2", "6", "", "2"])}
    over = edges[edges["side"] == "OVER"]
    assert len(over) == 3
    for r in over.to_dict("records"):
        mean = bt._pred_mean(pred_row, pred_row.keys())[r["stat"]]
        sig = bt._sigma_for(r["stat"], pred_row)
        assert 1 - bt._ncdf((r["line"] - mean) / sig) == pytest.approx(r["model_prob_raw"], abs=2e-3)
    # sd_reb blank -> production falls back to the fixed sigma, and so must the harness
    assert bt._sigma_for("reb", pred_row) == pytest.approx(3.0)
    assert bt._sigma_for("pr", pred_row) == pytest.approx(math.sqrt(36 + 9))


def test_std_pair_rejects_alt_line_prices_on_a_main_spread():
    assert bt._std_pair(-110, -110) == (-110, -110)
    assert bt._std_pair(-100.0, -100.0) == (-100.0, -100.0)  # no-vig consensus
    assert bt._std_pair(-245, 180) is None
    assert bt._std_pair(None, -110) is None


def test_resolve_falls_back_to_unique_same_date_name_and_counts_it():
    from collections import Counter
    logs = [{"pid": 201, "name": "Jalen Brunson", "team": "NYK", "gid": "g", "date": "2026-05-02", "stype": "Playoffs",
             "min": 30.0, **{k: 1.0 for k in ("pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra", "pr", "pa", "ra")}}]
    h = bt.History(logs)
    c = Counter()
    assert h.resolve(201, "x", "2026-05-02", c) == 201  # by id first
    assert h.resolve(3934672, "Jalen Brunson", "2026-05-02", c) == 201  # ESPN id -> NBA id by name
    assert h.resolve(3934672, "Jalen Brunson", "2026-05-03", c) is None  # never across dates
    assert c["join_by_id"] == 1 and c["join_by_name_same_date"] == 1 and c["join_none"] == 1


def test_murphy_decomposition_adds_up_to_brier_for_binned_forecasts():
    ps = [0.2] * 50 + [0.8] * 50
    ys = [0] * 40 + [1] * 10 + [1] * 40 + [0] * 10
    m = bt._murphy(ps, ys, bins=2)
    assert m["brier"] == pytest.approx(m["rel"] - m["res"] + m["unc"], abs=1e-9)
    assert m["rel"] == pytest.approx(0.0)  # 0.2 -> 20% observed, 0.8 -> 80% observed: perfectly reliable


def test_nb_p_over_matches_poisson_at_unit_dispersion_and_widens_with_variance():
    lam = 3.0
    pois = 1 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(0, 4))
    assert bt._nb_p_over(3.5, lam, lam) == pytest.approx(pois, abs=1e-9)
    # more variance at the same mean puts more mass in the far tail
    assert bt._nb_p_over(8.5, lam, 3 * lam) > bt._nb_p_over(8.5, lam, lam)
