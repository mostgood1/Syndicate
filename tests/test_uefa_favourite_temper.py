"""Hermetic tests for the --favourite-temper option of scripts/backtest_uefa_anchored.py (todo #699).

Registration: .syndicate/findings_2026-10-19_uefa_favourite_temper.md. No network, no data files.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scripts import backtest_uefa_anchored as bua
from scripts import soccer_team_strength_experiments as tse
from syndicate.features.soccer import uefa_close_backtest as ucb
from syndicate.features.soccer import uefa_market_anchor as uma


def _rows(n_per_season=60, seed=7):
    rng = np.random.default_rng(seed)
    clubs = [str(i) for i in range(12)]
    out = []
    for season in range(2020, 2027):
        for j in range(n_per_season):
            h, a = rng.choice(clubs, 2, replace=False)
            lam = [float(np.exp(rng.normal(0.35, 0.45))), float(np.exp(rng.normal(0.05, 0.45)))]
            p = list(uma.probs_from_rates(*lam))
            # a sharper 'close' so the blend has something to prefer
            close = list(tse.temper(np.array([p]), np.array([1.0]), 0.2, 0.0)[0])
            y = int(rng.choice(3, p=close))
            out.append({"event_id": f"{season}-{j}", "season": season, "competition": ("ucl", "uel", "uecl")[j % 3],
                        "pair": "in_in", "home_id": h, "away_id": a, "day": f"{season}-09-{1 + j % 28:02d}",
                        "lam": lam, "p_model": p, "p_close": close, "y": y,
                        "ll_model": ucb.log_loss(p, y), "ll_close": ucb.log_loss(close, y)})
    return out


def test_home_term_uses_only_the_registered_seasons():
    rows = _rows()
    want = np.mean([np.log(r["lam"][0] / r["lam"][1]) for r in rows if r["season"] in (2020, 2021, 2022)])
    assert bua.home_term(rows) == pytest.approx(want)
    for r in rows:
        if r["season"] >= 2023:
            r["lam"] = [9.0, 0.1]  # gate seasons must not move H
    assert bua.home_term(rows) == pytest.approx(want)


def test_zero_temperature_is_the_identity_and_the_frozen_values_are_not():
    rows = _rows(n_per_season=10)
    p = np.array([r["p_model"] for r in rows])
    assert np.allclose(bua.tempered(rows, "p_model", 0.0, 0.0, 1.577, 0.3), p)
    on = bua.tempered(rows, "p_model", -0.066, 0.271, 1.577, 0.3)
    assert not np.allclose(on, p)  # reachability: off != on
    assert np.allclose(on.sum(axis=1), 1.0)


def test_gap_is_in_domestic_units_and_centred_on_h():
    # log(lam_h/lam_a) == H -> |g_hat| = 0 -> tau = exp(t0); a big gap sharpens the favourite more.
    lam_even = [1.5, 1.5 / np.exp(0.3)]
    rows = [{"lam": lam_even, "p": [0.5, 0.3, 0.2]},
            {"lam": [3.0, 0.5], "p": [0.5, 0.3, 0.2]}]
    out = bua.tempered(rows, "p", -0.066, 0.271, 1.577, 0.3)
    assert np.allclose(out[0], tse.temper(np.array([[0.5, 0.3, 0.2]]), np.array([0.0]), -0.066, 0.271)[0])
    g = (np.log(3.0 / 0.5) - 0.3) / 1.577
    assert np.allclose(out[1], tse.temper(np.array([[0.5, 0.3, 0.2]]), np.array([g]), -0.066, 0.271)[0])
    assert out[1][0] > out[0][0]


def test_apply_temper_keeps_raw_and_null_temper_matches_the_control():
    rows = _rows()
    raw = [list(r["p_model"]) for r in rows]
    rep = bua.apply_temper(rows, 0.0, 0.0, 1.577, 0.3)
    assert [r["p_model_raw"] for r in rows] == raw
    assert rep["H_TEMPER"]["w"] == rep["control_model_blend"]["w"]
    for c in ("ucl", "uel", "uecl", "pooled"):
        assert rep["H_TEMPER"][c]["d_vs_close"] == pytest.approx(rep["control_model_blend"][c]["d_vs_close"])
    assert set(rep["H_TEMPER"]["w"]) == {2023, 2024, 2025, 2026}
    assert len(rep["calibration_by_close"]) == len(rep["calibration_by_model"]) == 10


def test_main_end_to_end_writes_the_temper_report(tmp_path, capsys):
    rows = _rows(n_per_season=45)
    (tmp_path / "features.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "report_close_step3.json").write_text(
        json.dumps({"rows": [{"event_id": r["event_id"], "ll_model": r["ll_model"]} for r in rows]}), encoding="utf-8")
    assert bua.main(["--closes", str(tmp_path), "--print-home-term"]) == 0
    assert "H_RULE" in capsys.readouterr().out
    assert bua.main(["--closes", str(tmp_path), "--skip-live", "--favourite-temper", "-0.066,0.271",
                     "--gap-k", "1.577", "--home-term", "0.3"]) == 0
    rep = json.loads((tmp_path / "report_favourite_temper.json").read_text(encoding="utf-8"))
    assert rep["registration"].startswith(".syndicate/findings_2026-10-19_uefa_favourite_temper.md")
    ft = rep["favourite_temper"]
    assert ft["params"] == {"t0": -0.066, "t1": 0.271, "k": 1.577, "h": 0.3}
    assert {"H_TEMPER", "control_model_blend", "sensitivity_h0", "secondary_anchored_tempered",
            "control_anchored_raw"} <= set(ft)
    assert not (tmp_path / "report_anchored.json").exists()


def test_temper_needs_k_and_h(tmp_path):
    with pytest.raises(SystemExit):
        bua.main(["--closes", str(tmp_path), "--favourite-temper", "-0.066,0.271"])
