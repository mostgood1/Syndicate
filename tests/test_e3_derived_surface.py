"""Hermetic tests for scripts/e3_derived_surface.py (lane e3-derived-surface)."""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("e3_derived_surface", ROOT / "scripts" / "e3_derived_surface.py")
e3 = importlib.util.module_from_spec(_SPEC)
sys.modules["e3_derived_surface"] = e3
_SPEC.loader.exec_module(e3)  # type: ignore[union-attr]


# ----------------------------------------------------------------------------- normal surface

def test_normal_location_prices_the_anchor_exactly():
    for line0, p0, sigma in ((-5.5, 0.52, 12.0), (221.5, 0.47, 18.0), (3.5, 0.9, 13.5)):
        mu = e3.normal_solve_mu(line0, p0, sigma)
        assert e3.normal_p_over(line0, mu, sigma) == pytest.approx(p0, abs=1e-9)


def test_normal_ladder_is_monotone_and_symmetric():
    mu, sigma = 4.0, 12.0
    prices = [e3.normal_p_over(line, mu, sigma) for line in (-10.5, -0.5, 4.0, 10.5, 20.5)]
    assert prices == sorted(prices, reverse=True)
    assert e3.normal_p_over(4.0, mu, sigma) == pytest.approx(0.5)


# ----------------------------------------------------------------------------- lattice pmf

def _football_like() -> "e3.Pmf":
    counts = {k: 1.0 for k in range(-30, 31)}
    for key in (-7, -3, 3, 7):
        counts[key] = 6.0
    return e3.Pmf.from_counts(counts)


def test_pmf_tail_and_half_point_lines():
    pmf = e3.Pmf(0, [0.2, 0.3, 0.5])
    assert pmf.p_over(-0.5) == pytest.approx(1.0)
    assert pmf.p_over(0.5) == pytest.approx(0.8)
    assert pmf.p_over(1.5) == pytest.approx(0.5)
    assert pmf.p_over(2.5) == 0.0
    assert pmf.mean() == pytest.approx(1.3)


def test_lattice_shift_prices_the_anchor_and_keeps_key_numbers():
    pmf = _football_like()
    u = e3.pmf_solve_shift(pmf, -2.5, 0.61)
    assert u is not None
    assert pmf.p_over_shifted(-2.5, u) == pytest.approx(0.61, abs=1e-9)
    # an integer shift moves the key-number mass intact: P(X+3 in {6,10}) lumps survive
    k = 3.0
    jump_at_key = pmf.p_over_shifted(9.5, k) - pmf.p_over_shifted(10.5, k)
    jump_off_key = pmf.p_over_shifted(10.5, k) - pmf.p_over_shifted(11.5, k)
    assert jump_at_key > 3 * jump_off_key


def test_lattice_shift_is_monotone_and_continuous():
    pmf = _football_like()
    grid = [x / 10 for x in range(-50, 51)]
    vals = [pmf.p_over_shifted(0.5, u) for u in grid]
    assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:]))
    assert max(abs(b - a) for a, b in zip(vals, vals[1:])) < 0.05


def test_lattice_shift_out_of_reach_is_none():
    pmf = e3.Pmf(0, [0.5, 0.5])
    assert e3.pmf_solve_shift(pmf, 0.5, 1.5) is None


def test_negate_swaps_sides():
    pmf = e3.Pmf(-1, [0.2, 0.3, 0.5])  # -1, 0, 1
    neg = pmf.negate()
    assert neg.p_over(0.5) == pytest.approx(0.2)  # P(-X > 0.5) = P(X <= -1)
    assert neg.mean() == pytest.approx(-pmf.mean())


# ----------------------------------------------------------------------------- count models

def test_poisson_and_negbin_are_normalised_with_the_right_moments():
    p = e3.poisson_probs(3.1)
    assert sum(p) == pytest.approx(1.0, abs=1e-9)
    assert sum(k * q for k, q in enumerate(p)) == pytest.approx(3.1, abs=1e-6)
    nb = e3.negbin_probs(4.4, 6.0)
    mean = sum(k * q for k, q in enumerate(nb))
    var = sum((k - mean) ** 2 * q for k, q in enumerate(nb))
    assert mean == pytest.approx(4.4, abs=1e-4)
    assert var == pytest.approx(4.4 + 4.4 ** 2 / 6.0, rel=1e-3)


def test_ot_rule_removes_ties_and_adds_a_goal():
    pm = e3.pair_pmfs(e3.poisson_probs(3.0), e3.poisson_probs(2.8), tie_rule="ot_plus_one")
    margin = pm["margin"]
    assert margin.p_over(-0.5) - margin.p_over(0.5) == pytest.approx(0.0, abs=1e-12)  # no ties
    plain = e3.pair_pmfs(e3.poisson_probs(3.0), e3.poisson_probs(2.8), tie_rule="none")
    tie = plain["margin"].p_over(-0.5) - plain["margin"].p_over(0.5)
    assert pm["total"].mean() == pytest.approx(plain["total"].mean() + tie, abs=1e-6)
    # a two-goal win can only come from regulation
    assert pm["margin"].p_over(1.5) == pytest.approx(plain["margin"].p_over(1.5), abs=1e-12)


def test_count_solver_reproduces_puck_line_and_total():
    sol = e3.solve_count_means(total_line=6.5, p_over=0.48, margin_line=1.5, p_margin_over=0.33,
                               size=None, tie_rule="ot_plus_one")
    assert sol is not None
    h, a = sol
    pm = e3.pair_pmfs(e3.poisson_probs(h), e3.poisson_probs(a), tie_rule="ot_plus_one")
    assert pm["total"].p_over(6.5) == pytest.approx(0.48, abs=2e-3)
    assert pm["margin"].p_over(1.5) == pytest.approx(0.33, abs=2e-3)
    assert h > a


def test_count_solver_soccer_1x2():
    sol = e3.solve_count_means(total_line=2.5, p_over=0.55, p_home_minus_away=0.20, size=None, tie_rule="none")
    assert sol is not None
    h, a = sol
    pm = e3.pair_pmfs(e3.poisson_probs(h), e3.poisson_probs(a), tie_rule="none")
    m = pm["margin"]
    assert m.p_over(0.5) - (1 - m.p_over(-0.5)) == pytest.approx(0.20, abs=2e-3)
    assert pm["total"].p_over(2.5) == pytest.approx(0.55, abs=2e-3)


# ----------------------------------------------------------------------------- scoring

def test_log_loss_is_clipped():
    assert e3.log_loss(0.0, 1) == pytest.approx(-math.log(e3.LL_CLIP))
    assert e3.log_loss(0.7, 1) == pytest.approx(-math.log(0.7))
    assert e3.log_loss(0.7, 0) == pytest.approx(-math.log(0.3))


def test_fee_net_return_and_predicted_ev():
    assert e3.fee_net_return(1, 0.40, 0.02) == pytest.approx(1 / 0.42 - 1)
    assert e3.fee_net_return(0, 0.40, 0.02) == pytest.approx(-1.0)
    assert e3.predicted_ev(0.5, 0.40, 0.02) == pytest.approx(0.5 / 0.42 - 1)


def test_numpy_pair_matches_the_reference_loops():
    for rule in ("none", "ot_plus_one"):
        ref = e3.pair_pmfs(e3.negbin_probs(4.4, 5.0), e3.negbin_probs(3.9, 5.0), tie_rule=rule)
        fast = e3.pair_arrays(e3.negbin_probs(4.4, 5.0), e3.negbin_probs(3.9, 5.0), tie_rule=rule)
        for key in ("margin", "total", "home", "away"):
            for line in (-3.5, -0.5, 0.5, 1.5, 4.5, 8.5, 12.5):
                assert fast[key].p_over(line) == pytest.approx(ref[key].p_over(line), abs=1e-9)


def test_fast_solver_matches_and_whole_lines_condition_on_no_push():
    a = e3.solve_count_means(total_line=6.5, p_over=0.48, margin_line=1.5, p_margin_over=0.33, size=None,
                             tie_rule="ot_plus_one", kmax=25)
    b = e3.solve_count_means(total_line=6.5, p_over=0.48, margin_line=1.5, p_margin_over=0.33, size=None,
                             tie_rule="ot_plus_one", kmax=25, fast=True)
    assert a == pytest.approx(b, abs=1e-6)
    sol = e3.solve_count_means(total_line=8.0, p_over=0.5, margin_line=1.5, p_margin_over=0.4, size=6.0,
                               tie_rule="ot_plus_one", kmax=30, fast=True)
    pm = e3.pair_arrays(e3.negbin_probs(sol[0], 6.0, 30), e3.negbin_probs(sol[1], 6.0, 30), tie_rule="ot_plus_one")
    assert e3.two_way_over(pm["total"], 8.0) == pytest.approx(0.5, abs=2e-3)


# ----------------------------------------------------------------------------- sim pmf, venue plumbing

def test_kde_preserves_mean_and_variance():
    hist = {str(k): float(v) for k, v in {-14: 3, -7: 9, -3: 14, 0: 6, 3: 20, 7: 16, 10: 8, 14: 7, 21: 3}.items()}
    raw = e3.raw_pmf(hist)
    kde = e3.kde_pmf(hist)
    assert kde.mean() == pytest.approx(raw.mean(), abs=0.05)
    assert kde.sd() == pytest.approx(raw.sd(), rel=0.03)


def test_series_rules_drive_the_second_half_definition():
    assert e3.reg_variant("... in the 2nd half (not including overtime) of ...", "h2") == "h2reg"
    assert e3.reg_variant("... in the 2nd half (including overtime) of ...", "h2") == "h2"
    assert e3.reg_variant("... 4th quarter (excluding overtime) ...", "q4") == "q4"
    assert e3.excludes_overtime("scores, excluding overtime")


def test_code_side_reads_the_blob_order():
    assert e3.code_side("DENOKC", "OKC", "nba") == "home"
    assert e3.code_side("DENOKC", "DEN", "nba") == "away"
    assert e3.code_side("RMAATM", "RMA", "soccer") == "home"
    assert e3.code_side("LALLAL", "LAL", "nba") is None


def test_parse_series():
    assert e3.parse_series("KXNBA1QSPREAD") == {"sport": "nba", "league": "NBA", "segment": "q1", "kind": "spread"}
    assert e3.parse_series("KXMLBTEAMTOTAL")["kind"] == "team_total"
    assert e3.parse_series("KXEPL1HTOTAL")["segment"] == "h1"
    assert e3.parse_series("KXNBAGAME") is None
    assert e3.parse_series("KXNBAPTS") is None


def test_quote_prefers_the_minute_candle_and_falls_back_to_the_hour():
    from datetime import datetime, timezone
    t = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
    ts = t.timestamp()
    hourly = [(ts - 7200, 0.40, 0.44), (ts - 3600, 0.41, 0.45)]
    minute = [(ts - 300, 0.42, 0.46), (ts + 60, 0.10, 0.90)]
    assert e3.quote_two_res(minute, hourly, t) == (0.42, 0.46)
    assert e3.quote_two_res([], hourly, t) == (0.41, 0.45)
    assert e3.quote_two_res([(ts - 60, 0.0, 0.05)], hourly, t) is None   # one-sided book


def test_cluster_bootstrap_centres_on_the_mean_and_widens_with_clustering():
    vals = [1.0] * 50 + [0.0] * 50
    m, lo, hi = e3.cluster_boot(vals, [str(i) for i in range(100)])
    assert m == pytest.approx(0.5) and lo < 0.5 < hi
    _, lo2, hi2 = e3.cluster_boot(vals, ["a"] * 50 + ["b"] * 50)
    assert (hi2 - lo2) > (hi - lo)


def test_verdict_needs_both_clauses():
    base = {"ll": {"n": 400, "games": 40, "delta": (-0.01, -0.02, -0.001)},
            "ev_bands": [{"n": 40, "games": 20, "ci_bonf": (0.01, 0.2)}]}
    assert e3.verdict(base) == "SURVIVES"
    assert e3.verdict({**base, "ll": {"n": 400, "games": 40, "delta": (-0.01, -0.02, 0.001)}}).startswith("KILL")
    assert e3.verdict({**base, "ev_bands": [{"n": 40, "games": 20, "ci_bonf": (-0.01, 0.2)}]}).startswith("KILL")
    assert e3.verdict({**base, "ll": {"n": 100, "games": 40, "delta": (-0.01, -0.02, -0.001)}}) == "UNDERPOWERED"


def test_away_rung_prices_the_complement_side():
    s = e3.Surface()
    s.dists[("margin", "full")] = ("normal", 5.0, 12.0)
    # away wins by over 3.5 == home margin < -3.5 (<= -4)
    assert s.price("margin", "full", 3.5, below=True) == pytest.approx(e3.N01.cdf((-3.5 - 5.0) / 12.0))
    pmf = e3.Pmf(-2, [0.1, 0.2, 0.3, 0.25, 0.15])    # -2..2
    s.dists[("margin", "q1")] = ("pmf", pmf, 0.0)
    assert s.price("margin", "q1", 0.5, below=True) == pytest.approx(0.3)     # P(M <= -1)
