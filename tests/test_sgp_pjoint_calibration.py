"""Hermetic tests for scripts/sgp_pjoint_calibration.py (lane `sgp-pjoint-calibration`, prereg 1e7793e3 + A1)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import sgp_pjoint_calibration as cal  # noqa: E402
from syndicate.features.nfl import sgp as core  # noqa: E402

CELLS = {"cells": {"type": {"SOG|F1~SOG|F2~teammate": {"rho": 0.35}, "POINTS|F1~SOG|F1~same_player": {"rho": 0.4}},
                   "market": {"SOG~SOG~opponent": {"rho": -0.05}}}}


def _leg(player, team, market, role, p_over, side="over", line=2.5, book_price=-150, p_market=None, hits=8, games=10):
    p_side = p_over if side in ("over", "yes") else 1 - p_over
    return {"player": player, "team": team, "market": market, "side": side, "line": line, "p_over": p_over,
            "p_side": p_side, "type": f"{market}|{role}", "role": role, "prices": {"dk": book_price, "fd": book_price},
            "event_id": "E1", "p_market": p_market if p_market is not None else round(p_side - 0.02, 4),
            "hits": hits, "games": games}


def _record(legs, event_id="E1", day="2026-10-20"):
    """A ledger record exactly as the builders write one (`core._ticket` -> `core.ledger_records`)."""
    pj, lv = core.ticket_joints([legs], CELLS, core.relation_of)
    rels = [core.relation_of(legs[i], legs[j]) for i in range(len(legs)) for j in range(i + 1, len(legs))]
    bk, prod = core._best_book(legs)
    tk = core._ticket(event_id, legs, float(pj[0]), lv[0], {}, bk, prod, rels)
    tk["family"] = "hit_rate"
    return core.ledger_records([tk], day=day, generated_at=f"{day}T12:00:00+00:00")[0]


def _graded(rec, status, results):
    return {"sgp_id": rec["sgp_id"], "date": rec["date"], "event_id": rec["event_id"], "p_joint": rec["p_joint"],
            "status": status, "legs": [{"bet": leg["bet"], "result": r} for leg, r in zip(rec["legs"], results)]}


# ------------------------------------------------------------------ §2 the clean population (reachability)
def test_clean_filter_removes_a_lost_ticket_with_a_void_leg():
    a = _record([_leg("A B", "T1", "SOG", "F1", 0.7), _leg("C D", "T1", "SOG", "F2", 0.6)])
    b = _record([_leg("E F", "T1", "SOG", "F1", 0.7), _leg("G H", "T1", "SOG", "F2", 0.6)])
    c = _record([_leg("I J", "T1", "SOG", "F1", 0.7), _leg("K L", "T1", "SOG", "F2", 0.6)])
    graded = [_graded(a, "won", ["won", "won"]), _graded(b, "lost", ["lost", "void"]), _graded(c, "void", ["won", "void"])]
    tickets, counts = cal.build_tickets("nhl", [a, b, c], graded)
    as_graded = {t["sgp_id"] for t in tickets if t["as_graded"]}
    clean = {t["sgp_id"] for t in tickets if t["clean"]}
    assert as_graded == {a["sgp_id"], b["sgp_id"]}
    assert clean == {a["sgp_id"]}                       # off != on: the void-leg LOSS is out of the primary
    assert counts["status_void"] == 1


def test_freeze_and_first_ledger_record_win():
    a = _record([_leg("A B", "T1", "SOG", "F1", 0.7), _leg("C D", "T1", "SOG", "F2", 0.6)], day="2026-10-27")
    tickets, counts = cal.build_tickets("nhl", [a], [_graded(a, "won", ["won", "won"])])
    assert tickets == [] and counts["after_freeze"] == 1
    b = _record([_leg("A B", "T1", "SOG", "F1", 0.7), _leg("C D", "T1", "SOG", "F2", 0.6)])
    later = dict(b, p_joint=0.99)
    tickets, _ = cal.build_tickets("nhl", [b, later], [_graded(b, "won", ["won", "won"])])
    assert tickets[0]["p_joint"] == b["p_joint"]


# ------------------------------------------------------------------ §3 the registered SE is grade_sgp_paper's
def test_citl_se_is_grade_sgp_paper_estimator():
    import grade_sgp_paper

    rng = np.random.default_rng(1)
    graded = []
    for i in range(60):
        p = float(rng.uniform(0.2, 0.6))
        graded.append({"event_id": f"G{i % 9}", "status": "won" if rng.random() < p - 0.05 else "lost", "p_joint": p})
    ref = grade_sgp_paper.summarize(graded)
    p = [g["p_joint"] for g in graded]
    y = [1.0 if g["status"] == "won" else 0.0 for g in graded]
    mine = cal.citl(p, y, [g["event_id"] for g in graded], boot=False)
    assert mine["se"] == pytest.approx(ref["gap_se_game_clustered"], abs=1e-4)
    assert mine["citl"] == pytest.approx(-ref["gap"], abs=1e-4)          # sign: ours is p - y


def test_holm_step_down():
    h = cal.holm({"a": 0.01, "b": 0.02, "c": 0.04, "d": 0.5})
    assert h["a"]["reject"] and h["b"]["reject"] is False           # 0.02 > 0.05 / 3
    assert h["a"]["p_holm"] == pytest.approx(0.04)
    assert not h["d"]["reject"]


def test_logistic_recalibration_recovers_a_slope():
    rng = np.random.default_rng(7)
    p = rng.uniform(0.1, 0.9, 6000)
    true = 1 / (1 + np.exp(-(0.2 + 0.6 * cal.logit(p))))
    y = (rng.random(6000) < true).astype(float)
    r = cal.recal(p, y, [f"g{i % 300}" for i in range(6000)])
    assert r["b_ci"][0] < 0.6 < r["b_ci"][1]
    assert r["b_vs_1_p"] < 1e-6


# ------------------------------------------------------------------ §6 arms, legs, pairs
def test_arm_b_reproduces_the_ledgers_p_independent():
    rec = _record([_leg("A B", "T1", "SOG", "F1", 0.7), _leg("C D", "T1", "SOG", "F2", 0.4, side="under")])
    tickets, _ = cal.build_tickets("nhl", [rec], [_graded(rec, "won", ["won", "won"])])
    t = tickets[0]
    assert math.prod(x["q"] for x in t["legs"]) == pytest.approx(rec["p_independent"], abs=1e-4)
    assert t["legs"][1]["q"] == pytest.approx(0.6)


def test_reconstruction_reproduces_the_builders_p_joint_and_fails_a_wrong_one():
    recs = [_record([_leg("A B", "T1", "SOG", "F1", 0.7), _leg("C D", "T1", "SOG", "F2", 0.6)]),
            _record([_leg("A B", "T1", "POINTS", "F1", 0.55), _leg("A B", "T1", "SOG", "F1", 0.65), _leg("Q R", "T2", "SOG", "F1", 0.6)])]
    graded = [_graded(r, "lost", ["lost"] * len(r["legs"])) for r in recs]
    tickets, _ = cal.build_tickets("nhl", recs, graded)
    rec = cal.reconstruct("nhl", tickets, CELLS)
    assert rec["ok"] and rec["frac"] == 1.0
    tickets[0]["p_joint"] += 0.05
    assert cal.reconstruct("nhl", tickets, CELLS)["reproduced"] == 1


def test_lambda_zero_is_independence_and_rho_zero_pairs_score_equal():
    rec = _record([_leg("A B", "T1", "SOG", "F1", 0.7), _leg("C D", "T1", "SOG", "F2", 0.6)])
    tickets, _ = cal.build_tickets("nhl", [rec], [_graded(rec, "won", ["won", "won"])])
    p0 = cal.price_tickets("nhl", tickets, cal.scale_cells(CELLS, 0.0))
    assert p0[0] == pytest.approx(0.7 * 0.6, abs=1e-6)
    assert cal.price_tickets("nhl", tickets, CELLS)[0] > p0[0]        # the measured +0.35 lifts the joint
    pairs = cal.pair_rows("nhl", tickets, cal.scale_cells(CELLS, 0.0))
    sc = cal.pair_scores(pairs, "m")
    assert sc["llc"] == pytest.approx(sc["lli"])


def test_pair_rows_dedup_and_signed_relation():
    legs = [_leg("A B", "T1", "SOG", "F1", 0.7), _leg("C D", "T1", "SOG", "F2", 0.6)]
    r1, r2 = _record(legs), _record(legs + [_leg("Q R", "T2", "SOG", "F1", 0.6)])
    tickets, _ = cal.build_tickets("nhl", [r1, r2], [_graded(r1, "won", ["won", "won"]), _graded(r2, "lost", ["won", "won", "lost"])])
    pairs = cal.pair_rows("nhl", tickets, CELLS)
    assert len(pairs) == 3                                  # A-C once, A-Q, C-Q
    assert {p["relation"] for p in pairs} == {"teammate", "opponent"}
    assert sorted(p["rho"] for p in pairs) == pytest.approx([-0.05, -0.05, 0.35])


def test_unique_legs_dedups_across_tickets_and_drops_void():
    legs = [_leg("A B", "T1", "SOG", "F1", 0.7), _leg("C D", "T1", "SOG", "F2", 0.6)]
    r1, r2 = _record(legs), _record(legs + [_leg("Q R", "T2", "SOG", "F1", 0.6)])
    tickets, _ = cal.build_tickets("nhl", [r1, r2], [_graded(r1, "won", ["won", "won"]), _graded(r2, "void", ["won", "won", "void"])])
    assert len(cal.unique_legs(tickets)) == 2


def test_posterior_at_k40_is_the_sheets_consistency_posterior():
    from syndicate.features.shared.cheat_sheets import consistency_posterior

    assert cal.posterior(0.8, 9, 10, 40.0) == pytest.approx(consistency_posterior(0.8, 9, 10), abs=1e-4)
    assert cal.posterior(0.8, 9, 10, math.inf) == 0.8


# ------------------------------------------------------------------ §6d the haircut never enters p_joint
def test_assumed_discount_changes_no_p_joint(monkeypatch):
    legs = {"E1": [_leg("A B", "T1", "SOG", "F1", 0.55, book_price=120), _leg("C D", "T1", "SOG", "F2", 0.5, book_price=110),
                   _leg("Q R", "T2", "SOG", "F1", 0.6, book_price=-120)]}
    games = [{"event_id": "E1"}]
    out = {}
    for d in (0.0, 0.185, 0.5):
        monkeypatch.setattr(core, "ASSUMED_BOOK_DISCOUNT", d)
        tks = core.pair_legs(legs, CELLS, games)
        out[d] = [(t["sgp_id"], t["p_joint"]) for t in tks]
    assert out[0.0] and out[0.0] == out[0.185] == out[0.5]          # same tickets, same order, same p_joint


# ------------------------------------------------------------------ §7 leave-one-date-out never sees its date
def test_lodo_fits_without_the_held_out_date():
    units = [{"date": d, "v": float(i)} for i, d in enumerate(["d1", "d1", "d2", "d3"])]
    seen = []

    def fit(train):
        seen.append({u["date"] for u in train})
        return len(train)

    scores, params = cal._lodo(units, fit, lambda th, us: np.full(len(us), th))
    assert seen == [{"d2", "d3"}, {"d1", "d3"}, {"d1", "d2"}]
    assert params == {"d1": 2, "d2": 3, "d3": 3}
    assert list(scores) == [2, 2, 3, 3]
