"""`scripts/live_totals_width_fit.py` fits k on the ENGINE's number (lane width-fit-engine-prob, user 2026-11-24 "Yes,
land it").

Since the #780 scales loaded (11-13), `model_home_win_prob` on a tempered market's priced rows is the TEMPERED number.
The script read it, so a re-fit fitted k on numbers k had already tempered: on NCAAF spreads through 11-21 it returned
exactly the shipped 1.800, where the engine's number gives 1.894 (`.syndicate/findings_2026-11-24_ncaaf_raw_spreads_k_
refit.md`). `fit_prob` picks the engine's number per P_SOURCE; these tests pin each source on every row kind the fleet
ledger holds, and reachability first: the two reads give different populations THROUGH `load()`.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from syndicate.features.shared.live_gameline_join import agresti_coull_point, scale_prob

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_totals_width_fit.py"


def _load_script(monkeypatch, name, **env):
    """A fresh copy of the script, so its module-level env reads (P_SOURCE, MARKET, UNTIL) see `env`."""
    monkeypatch.setattr(sys, "argv", list(sys.argv))  # the script reassigns sys.argv at import
    for key in ("P_SOURCE", "MARKET", "UNTIL", "FROM", "SPORTS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def wf(monkeypatch):
    return _load_script(monkeypatch, "_width_fit_under_test")


# The row kinds on the fleet's NCAAF spreads ledger (measured 2026-11-24, `C:\tmp\t780k_ncaaf\out\instrument.txt`):
SHARE = 46 / 120  # refused before the point estimator: the raw share k/n, no market price
POINT = {"model_home_win_prob": round(agresti_coull_point(0.75, 120), 4), "model_home_win_prob_raw": 0.75,
         "point_estimator": "agresti_coull", "sims_run": 120}                       # priced before the 11-13 load
U = agresti_coull_point(0.9, 120)
TEMPERED = {"model_home_win_prob": scale_prob(U, 1.8), "model_home_win_prob_raw": 0.9,
            "model_home_win_prob_unscaled": U, "prob_scale": 1.8, "point_estimator": "agresti_coull",
            "sims_run": 120}                                                         # priced after it
SHARE_ROW = {"model_home_win_prob": SHARE, "point_estimator": None, "sims_run": 120}


def test_tempered_row_engine_reads_the_unscaled_number_recorded_reads_the_tempered_one(wf):
    assert wf.fit_prob(TEMPERED, "engine") == pytest.approx(U)
    assert wf.fit_prob(TEMPERED, "ac") == pytest.approx(U)
    assert wf.fit_prob(TEMPERED, "recorded") == pytest.approx(scale_prob(U, 1.8))
    assert abs(wf.fit_prob(TEMPERED, "recorded") - U) > 0.05  # the trap is not a rounding difference


def test_point_estimated_row_is_the_same_under_every_source(wf):
    for source in wf.P_SOURCES:
        assert wf.fit_prob(POINT, source) == pytest.approx(POINT["model_home_win_prob"])


def test_share_row_ac_is_the_joins_agresti_coull_point_the_others_keep_the_share(wf):
    assert wf.fit_prob(SHARE_ROW, "engine") == pytest.approx(SHARE)
    assert wf.fit_prob(SHARE_ROW, "recorded") == pytest.approx(SHARE)
    assert wf.fit_prob(SHARE_ROW, "ac") == pytest.approx(agresti_coull_point(SHARE, 120))
    assert wf.fit_prob(SHARE_ROW, "ac") == pytest.approx((46 + 2) / 124)


def test_ac_without_a_sim_count_is_unusable(wf):
    assert wf.fit_prob({**SHARE_ROW, "sims_run": None}, "ac") is None


def test_tempered_row_with_no_engine_number_is_dropped_except_when_recorded(wf):
    row = {k: v for k, v in TEMPERED.items() if k != "model_home_win_prob_unscaled"}
    assert wf.fit_prob(row, "engine") is None
    assert wf.fit_prob(row, "ac") is None
    assert wf.fit_prob(row, "recorded") == pytest.approx(TEMPERED["model_home_win_prob"])


def test_k_of_one_is_untempered(wf):
    row = {**SHARE_ROW, "prob_scale": 1.0}
    assert wf.fit_prob(row, "engine") == pytest.approx(SHARE)


def test_college_total_calibration_reads_the_uncalibrated_number(wf):
    """#816: on a college totals row k left at 1, `model_home_win_prob` is the CALIBRATED number."""
    row = {"model_home_win_prob": 0.41, "model_home_win_prob_uncalibrated": 0.62, "total_cal": {"a": -0.2},
           "prob_scale": 1.0, "point_estimator": "agresti_coull", "sims_run": 400}
    assert wf.fit_prob(row, "engine") == pytest.approx(0.62)
    assert wf.fit_prob(row, "ac") == pytest.approx(0.62)
    assert wf.fit_prob(row, "recorded") == pytest.approx(0.41)
    assert wf.fit_prob({k: v for k, v in row.items() if k != "model_home_win_prob_uncalibrated"}, "engine") is None


def test_unscaled_wins_over_uncalibrated(wf):
    """k applies before the calibration, so the unscaled number is the engine's even when both are recorded."""
    row = {**TEMPERED, "model_home_win_prob_uncalibrated": scale_prob(U, 1.8), "total_cal": {"a": 0.1}}
    assert wf.fit_prob(row, "engine") == pytest.approx(U)


def test_no_model_probability_is_none_under_every_source(wf):
    for source in wf.P_SOURCES:
        assert wf.fit_prob({"model_home_win_prob": None, "sims_run": 120}, source) is None


def test_default_source_is_engine_and_a_bad_one_refuses(monkeypatch):
    assert _load_script(monkeypatch, "_width_fit_default").P_SOURCE == "engine"
    assert _load_script(monkeypatch, "_width_fit_ac", P_SOURCE=" AC ").P_SOURCE == "ac"
    with pytest.raises(SystemExit):
        _load_script(monkeypatch, "_width_fit_bad", P_SOURCE="tempered")


def _write_ledger(root, rows):
    d = root / "ncaaf_source" / "data" / "live_gameline_ledger"
    d.mkdir(parents=True)
    with open(d / "live_gameline_ledger_2026-11-14.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _row(event_id, as_of, extra):
    return {"market": "spreads", "segment": "full", "date": "2026-11-14", "event_id": event_id,
            "live_state_as_of": as_of, "line": -3.5, "home_team": "Ohio State Buckeyes",
            "away_team": "Michigan Wolverines", "home_score": 7, "away_score": 3, "model_total_mean": 48.0,
            "model_margin_mean": 6.0, "market_fair_prob": 0.55, "priceable": True, **extra}


@pytest.mark.parametrize("source", ["engine", "recorded"])
def test_reachability_the_source_changes_what_load_fits_on(monkeypatch, tmp_path, source):
    """off != on THROUGH load(): the same ledger gives the engine's number under `engine` and the tempered one under
    `recorded`, and a tempered row with no engine number is counted and dropped only under `engine`."""
    wf = _load_script(monkeypatch, f"_width_fit_load_{source}", P_SOURCE=source, MARKET="spreads",
                      UNTIL="2026-11-30")
    _write_ledger(tmp_path, [
        _row("e1", "2026-11-14T18:00:00Z", TEMPERED),
        _row("e1", "2026-11-14T18:05:00Z", {k: v for k, v in TEMPERED.items() if k != "model_home_win_prob_unscaled"}),
        _row("e1", "2026-11-14T18:10:00Z", SHARE_ROW),
    ])
    monkeypatch.setattr(wf.g, "DATA", str(tmp_path))
    names = ({wf.g.norm("Ohio State Buckeyes")}, {wf.g.norm("Michigan Wolverines")})
    monkeypatch.setattr(wf, "finals_margin", lambda sport, d: {"401": (names[0], names[1], (28.0, 14.0))})

    rows, drop, n_states = wf.load("ncaaf")

    assert n_states == 3
    by_p = sorted(x["p"] for x in rows)
    if source == "engine":
        assert drop.get("no_engine_probability") == 1
        assert by_p == pytest.approx(sorted([U, SHARE]))
    else:
        assert "no_engine_probability" not in drop
        assert by_p == pytest.approx(sorted([scale_prob(U, 1.8), scale_prob(U, 1.8), SHARE]))
    assert all(x["y"] == 1 for x in rows)  # the home margin, 14, is above the line's -3.5
