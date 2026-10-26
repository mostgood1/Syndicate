"""Hermetic tests for scripts/e4_combo_correlation.py (lane `e4-combo-correlation`, prereg 9f8d759e + A1/A2)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import e4_combo_correlation as e4  # noqa: E402
from syndicate.features.nfl.sgp import joint_over  # noqa: E402
from syndicate.features.shared.nba_prop_calibration import combo_scale, transform_values  # noqa: E402


# ------------------------------------------------------------------ market marginals (A1)
def test_american_prob_and_devig_two_sided_only():
    assert e4.american_prob(-110) == pytest.approx(110 / 210)
    assert e4.american_prob(150) == pytest.approx(0.4)
    assert e4.american_prob(50) is None                      # not American odds
    d = e4.devig_book({"over": -110, "under": -110}, ("over", "under"))
    assert d["over"] == pytest.approx(0.5)
    assert e4.devig_book({"over": -110}, ("over", "under")) is None   # one-sided book never priced


def test_main_line_most_books_then_nearest_half():
    by_line = {0.5: {"dk": {"over": -300, "under": 240}},
               1.5: {"dk": {"over": 150, "under": -180}, "fd": {"over": 145, "under": -175}}}
    leg = e4.main_line_leg(by_line, ("over", "under"), "over")
    assert leg["line"] == 1.5 and leg["n_books"] == 2
    tie = {0.5: {"dk": {"over": -300, "under": 240}}, 1.5: {"dk": {"over": 110, "under": -130}}}
    assert e4.main_line_leg(tie, ("over", "under"), "over")["line"] == 1.5


def test_soccer_three_way_devig():
    by_line = {None: {"b1": {"home": 150, "draw": 230, "away": 190}}}
    ps = [e4.main_line_leg(by_line, ("home", "draw", "away"), s)["p"] for s in ("home", "draw", "away")]
    assert sum(ps) == pytest.approx(1.0)


def test_venues_excluded():
    assert e4.is_venue("kalshi") and e4.is_venue("polymarket_us") and e4.is_venue("novig")
    assert not e4.is_venue("draftkings") and not e4.is_venue("pinnacle")


def test_load_quotes_drops_inplay_and_venues_keeps_last_pregame(tmp_path):
    d = tmp_path / "mlb_source" / "tracking" / "book_quotes"
    d.mkdir(parents=True)
    base = {"sport": "mlb", "event_id": "e1", "commence_time": "2026-10-10T20:00:00Z", "home_team": "H", "away_team": "A",
            "market": "batter_hits", "segment": "full", "player_name": "Yandy Díaz", "line": 0.5, "selection": "over"}
    rows = [dict(base, bookmaker="dk", captured_at="2026-10-10T18:00:00Z", price=-200),
            dict(base, bookmaker="dk", captured_at="2026-10-10T19:30:00Z", price=-220),     # last pregame: kept
            dict(base, bookmaker="dk", captured_at="2026-10-10T20:30:00Z", price=-500),     # in-play: dropped
            dict(base, bookmaker="kalshi", captured_at="2026-10-10T19:00:00Z", price=-210)]  # venue: dropped
    (d / "2026-10-10.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    latest, events, cnt = e4.load_quotes(tmp_path, "mlb", {"batter_hits"})
    assert cnt["inplay_excluded"] == 1 and cnt["venue_excluded"] == 1
    (key, (cap, price)), = latest.items()
    assert price == -220 and key[3] == "yandy diaz"


# ------------------------------------------------------------------ arm (b): MLB joint
def test_packed_index_and_joint_lookup():
    # labels L0, L1, L2 -> lower triangle (1,0), (2,0), (2,1)
    joint = {"labels": ["L0", "L1", "L2"], "corr_lower": [500, -32768, -250], "scale": 1000, "undefined": -32768}
    idx = {k: i for i, k in enumerate(joint["labels"])}
    assert e4.packed_index(1, 0) == 0 and e4.packed_index(2, 0) == 1 and e4.packed_index(2, 1) == 2
    assert e4.packed_index(0, 2) == 1
    assert e4.joint_rho_s(joint, idx, "L0", "L1") == pytest.approx(0.5)
    assert e4.joint_rho_s(joint, idx, "L2", "L0") is None            # undefined dropped
    assert e4.joint_rho_s(joint, idx, "L1", "L2") == pytest.approx(-0.25)


def test_spearman_to_gauss_is_platform_map():
    assert e4.spearman_to_gauss(0.0) == 0.0
    assert e4.spearman_to_gauss(1.0) == pytest.approx(1.0)
    assert e4.spearman_to_gauss(0.5) == pytest.approx(2 * math.sin(math.pi * 0.5 / 6))


def test_composed_rho():
    assert e4.composed_rho(0.0, 0.0, 0.1, "total") == 0.0
    assert e4.composed_rho(0.3, 0.3, 0.0, "own_win") == 0.0
    assert e4.composed_rho(0.3, 0.0, 0.0, "own_win") > 0 and e4.composed_rho(0.3, 0.0, 0.0, "total") > 0


# ------------------------------------------------------------------ arm (b): NBA back-out
def _ladder(vals):
    vals = [int(v) for v in vals]
    dist = {}
    for v in vals:
        dist[str(v)] = dist.get(str(v), 0) + 1
    return {"distribution": dist}


def test_nba_cov_recovers_raw_covariance_through_the_calibration_widening():
    rng = np.random.default_rng(1)
    cov = np.array([[36.0, 6.0, 4.0], [6.0, 9.0, 1.0], [4.0, 1.0, 4.0]])
    draws = np.maximum(0, np.round(rng.multivariate_normal([20, 8, 5], cov, size=20000))).astype(int)
    p, r, a = draws[:, 0], draws[:, 1], draws[:, 2]
    k = {"pts": 1.25, "reb": 1.25, "ast": 1.25, "pra": 1.5}
    raw_sd = {"pts": p.std(), "reb": r.std(), "ast": a.std(), "pra": (p + r + a).std()}
    row = {f"{s}_sd": raw_sd[s] * k[s] for s in raw_sd}
    row["nba_prop_calibration"] = {"sd_scale": dict(k)}
    lad = {}
    for key, parts, vals in (("pr", ("pts", "reb"), p + r), ("pa", ("pts", "ast"), p + a), ("ra", ("reb", "ast"), r + a)):
        kk = combo_scale(parts, raw_sd, k)
        lad[key] = _ladder(transform_values(list(vals), 0.0, kk))      # the served widening, undone by nba_cov
    row["prop_ladders"] = lad
    sig, why = e4.nba_cov(row, k, applied=True)
    assert why == "ok"
    emp = np.cov(np.stack([p, r, a]), bias=True)
    assert sig[0, 1] == pytest.approx(emp[0, 1], rel=0.15)
    assert sig[0, 2] == pytest.approx(emp[0, 2], rel=0.15)
    assert sig[1, 2] == pytest.approx(emp[1, 2], abs=0.35)
    # reachability: NOT undoing the widening gives a materially different covariance
    sig_wrong, _ = e4.nba_cov(row, None, applied=False)
    assert sig_wrong is None or abs(sig_wrong[0, 1] - sig[0, 1]) > 1.0


def test_nba_cov_gate_rejects_inconsistent_pra():
    row = {"pts_sd": 6, "reb_sd": 3, "ast_sd": 2, "pra_sd": 30,      # PRA sd far from the parts
           "prop_ladders": {"pr": _ladder([10, 20, 30]), "pa": _ladder([10, 20, 30]), "ra": _ladder([5, 6, 7])}}
    sig, why = e4.nba_cov(row, None, applied=False)
    assert sig is None and why == "pra_identity"


def test_nba_rho_and_kind():
    sig = np.array([[36.0, 6.0, 4.0], [6.0, 9.0, 1.0], [4.0, 1.0, 4.0]])
    assert e4.nba_rho(sig, "player_points", "player_rebounds") == pytest.approx(6 / (6 * 3))
    assert e4.nba_kind("player_points", "player_rebounds") == "SP-disjoint"
    assert e4.nba_kind("player_points", "player_rebounds_assists") == "SP-disjoint"
    assert e4.nba_kind("player_points", "player_points_rebounds") == "SP-nested"
    assert e4.nba_rho(sig, "player_points", "player_points_rebounds") > 0.8


# ------------------------------------------------------------------ arm (b): soccer
def test_tetrachoric_round_trip_and_bounds():
    p11 = float(joint_over(0.45, 0.55, 0.3))
    assert e4.tetrachoric(0.45, 0.55, p11) == pytest.approx(0.3, abs=1e-6)
    assert e4.tetrachoric(0.0, 0.5, 0.0) is None


def test_soccer_events_signs():
    sl = {"0-0": 0.1, "1-0": 0.2, "2-1": 0.2, "1-1": 0.2, "0-2": 0.1, "3-1": 0.2}
    ev = e4.soccer_events(sl, 2.5)
    w = ev["w"]
    assert float((w * ev["h2h_home"]).sum()) == pytest.approx(0.6)
    p1, p2 = float((w * ev["btts"]).sum()), float((w * ev["totals"]).sum())
    p11 = float((w * ev["btts"] * ev["totals"]).sum())
    assert p11 > p1 * p2 and e4.tetrachoric(p1, p2, p11) > 0     # BTTS and over move together


def test_plackett():
    assert e4.plackett_p11(0.4, 0.3, 1.0) == pytest.approx(0.12)
    hi = e4.plackett_p11(0.4, 0.3, 5.0)
    assert 0.12 < hi <= 0.3


# ------------------------------------------------------------------ scoring
def test_four_cell_sums_and_independence():
    P = e4.four_cell(np.array([0.3, 0.6]), np.array([0.5, 0.2]), 0.0)
    assert np.allclose(P.sum(axis=1), 1.0, atol=1e-5)
    assert P[0, 0] == pytest.approx(0.15)


def test_cell_index_partition():
    assert list(e4.cell_index([1, 1, 0, 0], [1, 0, 1, 0])) == [0, 1, 2, 3]


def test_clustered_se_matches_hand():
    v = np.array([1.0, 2.0, 3.0, 4.0])
    g = np.array(["a", "a", "b", "b"])
    per = np.array([(1 - 2.5) + (2 - 2.5), (3 - 2.5) + (4 - 2.5)])
    assert e4.clustered_se(v, g) == pytest.approx(math.sqrt((per ** 2).sum() * 2 / 1) / 4)


def test_holm():
    res = e4.holm({"a": 0.001, "b": 0.02, "c": 0.04, "d": 1.0})
    assert res == {"a": True, "b": False, "c": False, "d": False}
    assert e4.holm({"a": 0.01, "b": 0.02})["b"] is True


def _sim_pairs(n_games=200, per=10, rho=0.5, rho_b=0.5, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        for _ in range(per):
            z = rng.multivariate_normal([0, 0], [[1, rho], [rho, 1]])
            pa, pb = 0.4, 0.55
            rows.append({"sport": "t", "cell": "c", "stat_pair": "x", "game": f"g{g}", "date": f"d{g % 7}",
                         "pa": pa, "pb": pb, "ya": int(z[0] > 0.2533),        # P = 0.40
                         "yb": int(z[1] > -0.1257), "rho_b": rho_b, "rho_c": None})   # P = 0.55
    return rows


def test_score_cell_reachability_and_direction():
    rows = _sim_pairs()
    res = e4.score_cell(rows)
    assert res["pairs"] == 2000 and res["games"] == 200
    assert res["ll_b"] != res["ll_a"]                     # off != on
    assert res["D_ba"]["mean"] < 0 and res["D_ba"]["ci"][1] < 0
    assert e4.verdict_cell(res) == "CANDIDATE"
    null = e4.score_cell(_sim_pairs(rho=0.0, rho_b=0.5))
    assert null["D_ba"]["mean"] > 0                       # a wrong correlation is penalised
    assert e4.verdict_cell(null) == "KILLED"


def test_score_cell_insufficient():
    res = e4.score_cell(_sim_pairs(n_games=10, per=5))
    assert e4.verdict_cell(res) == "INSUFFICIENT"


def test_mle_rho_recovers():
    rows = _sim_pairs(n_games=300, per=10, rho=0.5)
    pa = np.array([r["pa"] for r in rows])
    pb = np.array([r["pb"] for r in rows])
    obs = e4.cell_index([r["ya"] for r in rows], [r["yb"] for r in rows])
    out = e4.mle_rho(pa, pb, obs, np.array([r["game"] for r in rows]), boot=50)
    assert 0.35 < out["rho"] < 0.65 and out["ci"][0] < out["rho"] < out["ci"][1]


def test_name_lookup_never_guesses():
    t = {"nicolas claxton": 1, "jalen williams": 2, "jaylin williams": 3}
    assert e4.name_lookup(t, "nic claxton") == 1
    assert e4.name_lookup(t, "j williams") is None


def test_c_ledger_reads_graded_and_ledger(tmp_path):
    base = tmp_path / "cheatsheets" / "nhl"
    base.mkdir(parents=True)
    led = [{"sgp_id": "s1", "p_independent": 0.2, "legs": [{"side": "over", "p_market": 0.5}, {"side": "over", "p_market": 0.4}]},
           {"sgp_id": "s2", "p_independent": 0.3, "legs": [{"side": "under", "p_market": 0.5}]}]
    gr = [{"sgp_id": "s1", "status": "won", "p_joint": 0.25, "event_id": "g1"},
          {"sgp_id": "s2", "status": "lost", "p_joint": 0.35, "event_id": "g2"},
          {"sgp_id": "s3", "status": "pending", "p_joint": 0.3, "event_id": "g3"}]
    (base / "sgp_ledger.jsonl").write_text("\n".join(json.dumps(x) for x in led), encoding="utf-8")
    (base / "sgp_graded.jsonl").write_text("\n".join(json.dumps(x) for x in gr), encoding="utf-8")
    out = e4.c_ledger(tmp_path)["nhl"]
    assert out["settled"] == 2 and out["n_market_product"] == 1
