"""NFL SGP correlations (lane `nfl-sgp-builder`, 2026-10-16): the copula maths the joint price rests on."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

scipy = pytest.importorskip("scipy")
from scipy.stats import multivariate_normal  # noqa: E402

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_nfl_sgp_correlations.py"
_spec = importlib.util.spec_from_file_location("build_nfl_sgp_correlations", _PATH)
sgp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sgp)


@pytest.mark.parametrize("h,k,rho", [(0.3, -0.4, 0.5), (-1.1, 0.7, -0.3), (0.0, 0.0, 0.6), (1.5, 1.2, 0.85),
                                     (-0.2, -0.9, 0.0), (0.0, 0.8, -0.7)])
def test_bvn_lower_matches_scipy(h, k, rho):
    want = multivariate_normal(mean=[0, 0], cov=[[1, rho], [rho, 1]]).cdf([h, k])
    got = float(sgp.bvn_lower(np.array([h]), np.array([k]), rho)[0])
    assert got == pytest.approx(want, abs=1e-6)


def test_joint_over_at_the_median_is_the_closed_form():
    # P(both over) for two 50/50 legs = 1/4 + asin(rho) / (2 pi), the orthant identity.
    for rho in (-0.6, 0.0, 0.3, 0.8):
        got = float(sgp.joint_over(np.array([0.5]), np.array([0.5]), rho)[0])
        assert got == pytest.approx(0.25 + math.asin(rho) / (2 * math.pi), abs=1e-7)


def test_independence_is_the_product():
    p_a, p_b = np.array([0.31, 0.55, 0.72]), np.array([0.48, 0.66, 0.2])
    assert np.allclose(sgp.joint_over(p_a, p_b, 0.0), p_a * p_b, atol=1e-9)


def test_fit_rho_recovers_a_known_correlation_with_per_leg_marginals():
    rng = np.random.default_rng(7)
    n, rho = 40_000, 0.35
    z = rng.multivariate_normal([0, 0], [[1, rho], [rho, 1]], size=n)
    p_a = rng.uniform(0.35, 0.65, n)            # each leg has its own line, so its own marginal
    p_b = rng.uniform(0.3, 0.6, n)
    o_a = (z[:, 0] > sgp.ndtri(1 - p_a)).astype(float)
    o_b = (z[:, 1] > sgp.ndtri(1 - p_b)).astype(float)
    games = np.arange(n) // 40
    fit = sgp.fit_rho(p_a, p_b, o_a, o_b, games)
    assert abs(fit["rho"] - rho) < 3 * fit["se"] + 0.01
    assert 0 < fit["se"] < 0.05


def test_fit_rho_finds_nothing_in_independent_legs():
    rng = np.random.default_rng(11)
    n = 30_000
    p_a, p_b = np.full(n, 0.5), np.full(n, 0.45)
    o_a = (rng.uniform(size=n) < p_a).astype(float)
    o_b = (rng.uniform(size=n) < p_b).astype(float)
    fit = sgp.fit_rho(p_a, p_b, o_a, o_b, np.arange(n) // 30)
    assert abs(fit["rho"]) < 3 * fit["se"] + 0.005


def test_american_prices():
    assert sgp.american_to_prob(-110) == pytest.approx(110 / 210)
    assert sgp.american_to_prob(150) == pytest.approx(0.4)


def test_a_miscalibrated_low_probability_marginal_does_not_fake_a_correlation():
    # Two Anytime-TD-like legs, both priced above what they hit (0.25 -> 0.18, 0.30 -> 0.22), independent. Without
    # the within-cell recalibration the concordance moment reads this as rho +0.33 (measured 2026-10-16); with it, ~0.
    # (One leg at exactly 0.5 cancels the bias -- delta * (1 - 2 p_b) -- so the case needs both legs off 0.5.)
    rng = np.random.default_rng(3)
    n = 60_000
    p_a, p_b = np.full(n, 0.25), np.full(n, 0.30)
    o_a = (rng.uniform(size=n) < 0.18).astype(float)
    o_b = (rng.uniform(size=n) < 0.22).astype(float)
    fit = sgp.fit_rho(p_a, p_b, o_a, o_b, np.arange(n) // 30)
    assert abs(fit["rho"]) < 3 * fit["se"] + 0.005


def test_shrinkage_pulls_noise_to_zero_and_keeps_signal():
    cells = {"type": {f"a{i}~b~teammate": {"rho": r, "se": 0.08} for i, r in enumerate([0.1, -0.12, 0.05, -0.04, 0.09, -0.1])},
             "market": {}}
    cells["type"]["strong~b~teammate"] = {"rho": 0.45, "se": 0.02}
    sgp.shrink_cells(cells)
    noisy = [v["rho"] for k, v in cells["type"].items() if k.startswith("a")]
    assert max(abs(r) for r in noisy) < 0.1
    assert cells["type"]["strong~b~teammate"]["rho"] > 0.4
    assert all("rho_raw" in v for v in cells["type"].values())


# ------------------------------------------------------------------------------------------- the sheet's SGPs
from syndicate.features.nfl import sgp as sheet_sgp  # noqa: E402

CELLS = {"cells": {"type": {"Passing Yards|QB~Receiving Yards|R1~teammate": {"rho": 0.32},
                            "Receiving Yards|R1~Receptions|R1~same_player": {"rho": 0.8}},
                   "market": {"Passing Yards~Rushing Yards~opponent": {"rho": -0.02}}}}
ROLES = {("KC", ("p", "mahomes")): "QB", ("KC", ("t", "kelce")): "R1", ("LV", ("j", "jacobs")): "RB1"}


def _row(player, team, market, side, line, p_side, prices, suggested=True):
    return {"player": player, "team": team, "market": market, "side": side, "line": line, "event_id": "e1",
            "suggested": suggested, "book_prices": prices, "check": {"p_market": p_side, "ev_market": 1.0}}


def _sheet(rows):
    return {"rows": rows, "games": [{"event_id": "e1", "matchup": "Las Vegas Raiders @ Kansas City Chiefs",
                                     "kickoff_ct": "Sun 12:00 PM CT", "commence_time": "2026-10-18T17:00:00Z"}]}


def test_a_teammate_stack_is_priced_from_the_measured_correlation_with_fair_and_worth_it_odds():
    rows = [_row("Patrick Mahomes", "KC", "Passing Yards", "over", 260.5, 0.5, {"draftkings": -115, "fanduel": -110}),
            _row("Travis Kelce", "KC", "Receiving Yards", "over", 55.5, 0.5, {"draftkings": -115})]
    out = sheet_sgp.suggest(_sheet(rows), CELLS, ROLES)
    assert len(out) == 1
    s = out[0]
    want = 0.25 + math.asin(0.32) / (2 * math.pi)
    assert s["relation"] == "teammate" and s["rho_level"] == "role" and s["p_joint"] == pytest.approx(want, abs=1e-4)
    assert s["book"] == "draftkings"                                   # the one book quoting both legs
    assert s["fair_odds"] == sheet_sgp.decimal_to_american(1 / s["p_joint"])
    assert s["worth_it_odds"] > s["fair_odds"]                         # a cushion above fair
    product = sheet_sgp.american_to_decimal(-115) ** 2
    assert s["est_book_odds"] == sheet_sgp.decimal_to_american(product * (1 - sheet_sgp.ASSUMED_BOOK_DISCOUNT))
    assert s["commence_time"] == "2026-10-18T17:00:00Z" and not s["same_player"]


def test_an_under_leg_uses_the_other_orthant():
    a = {"p_over": 0.5, "side": "over"}
    b = {"p_over": 0.4, "side": "under"}
    oo = float(sheet_sgp.joint_over(0.5, 0.4, 0.3))
    assert sheet_sgp.joint_prob(a, b, 0.3) == pytest.approx(0.5 - oo)
    assert sheet_sgp.joint_prob(dict(a, side="under"), b, 0.3) == pytest.approx(1 - 0.5 - 0.4 + oo)


def test_no_shared_book_no_lift_or_no_measured_cell_means_no_parlay():
    no_book = [_row("Patrick Mahomes", "KC", "Passing Yards", "over", 260.5, 0.5, {"fanduel": -110}),
               _row("Travis Kelce", "KC", "Receiving Yards", "over", 55.5, 0.5, {"draftkings": -115})]
    assert sheet_sgp.suggest(_sheet(no_book), CELLS, ROLES) == []
    against = [_row("Patrick Mahomes", "KC", "Passing Yards", "over", 260.5, 0.5, {"draftkings": -115}),
               _row("Travis Kelce", "KC", "Receiving Yards", "under", 55.5, 0.5, {"draftkings": -115})]
    assert sheet_sgp.suggest(_sheet(against), CELLS, ROLES) == []     # the correlation works against this pair
    unmeasured = [_row("Patrick Mahomes", "KC", "Passing Yards", "over", 260.5, 0.5, {"draftkings": -115}),
                  _row("Josh Jacobs", "LV", "Rushing Yards", "over", 70.5, 0.5, {"draftkings": -115})]
    assert sheet_sgp.suggest(_sheet(unmeasured), CELLS, ROLES) == []  # |rho| too small to lift past MIN_LIFT
    assert sheet_sgp.suggest(_sheet(no_book), None, ROLES) == []      # no correlations file, no section


def test_a_same_player_pair_is_flagged_and_ranks_below_a_cross_player_pair_at_an_equal_estimate():
    rows = [_row("Travis Kelce", "KC", "Receiving Yards", "over", 55.5, 0.5, {"draftkings": -115}),
            _row("Travis Kelce", "KC", "Receptions", "over", 5.5, 0.5, {"draftkings": -115}),
            _row("Patrick Mahomes", "KC", "Passing Yards", "over", 260.5, 0.5, {"draftkings": -115})]
    out = sheet_sgp.suggest(_sheet(rows), CELLS, ROLES)
    flags = {tuple(sorted(l["market"] for l in s["legs"])): s["same_player"] for s in out}
    assert flags[("Receiving Yards", "Receptions")] is True
    same = next(s for s in out if s["same_player"])
    cross = next(s for s in out if not s["same_player"])
    if abs(same["est_ev_pct"] - cross["est_ev_pct"]) < 5:
        assert out.index(cross) < out.index(same)


def test_the_record_keeps_started_games_and_the_ledger_appends_each_parlay_once(tmp_path):
    old = [{"sgp_id": "a", "event_id": "e0"}, {"sgp_id": "b", "event_id": "e1"}]
    fresh = [{"sgp_id": "c", "event_id": "e1"}, {"sgp_id": "d", "event_id": "e0"}]
    merged = sheet_sgp.merge_record(fresh, old, started={"e0"})
    assert [s["sgp_id"] for s in merged] == ["a", "c"]                 # e0 started: its old parlay stays
    path = tmp_path / "sgp_ledger.jsonl"
    recs = [{"sgp_id": "x"}, {"sgp_id": "y"}]
    assert sheet_sgp.append_ledger(path, recs) == 2 and sheet_sgp.append_ledger(path, recs) == 0
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_the_page_leads_with_worth_it_and_labels_the_book_price_an_estimate():
    page = (Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "cheat_sheets.html").read_text(encoding="utf-8")
    block = page[page.index("function sgpBlock"):page.index("const SECTIONS = [")]
    row = page[page.index("function sgpRow"):page.index("function sgpBlock")]
    assert "Worth it at" in row and "estimate" in row and row.index("Fair odds") < row.index("Est. book price")
    assert "not a quote" in block and "no edge is claimed" in block
    assert "Layer 2" not in block + row and "board" not in (block + row).lower()
    assert "sgpBlock(d, game)" in page
