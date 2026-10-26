"""Decision policy v1 (lane `decision-policy-paper`, Decision Engine Phase 2 #736): the policy math and selection.

Pre-registration: .syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md (8d16ab07). Records are built
by the REAL `decision_record.build_record`, so these tests read the record exactly as the paper job will.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import decision_policy_v1 as dp
from syndicate.features.shared import decision_record as dr

NOW = datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc)
DECIDED = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
PARAMS = dp.Params(z_s1=1.0, z_s2=0.7, r2_s2={"game": 0.002, "game|totals": 0.0015, "game|totals|t6h": 0.0019},
                   loaded=True, version="test")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(**over):
    row = {
        "sport": "nba", "event_id": "ev1", "kind": "game", "market": "totals", "segment": "full",
        "player_name": None, "side": "over", "line": 220.5, "commence_time": _iso(NOW + timedelta(hours=6)),
        "home_team": "Home", "away_team": "Away", "game_state": "pregame", "suggested": False,
        "suggested_reasons": [], "ev_pct": 1.0, "model_edge_pct": 0.0,
        "quote": {"fair_probability": 0.50, "fair_devig_method": "shin", "fair_method": "consensus",
                  "books_quoting": 8, "book_age_seconds": 30.0, "quote_seen_age_seconds": 5.0,
                  "suspect_stale": False, "bookmaker": "draftkings", "price": 105,
                  "book_prices": {"draftkings": 105, "kalshi": 115, "polymarket": -110}},
    }
    for key, value in over.items():
        if key == "quote":
            row["quote"] = {**row["quote"], **value}
        else:
            row[key] = value
    return row


def _rec(**over):
    ctx = dr.RecordContext(selected_date="2026-10-27", now=NOW)
    return dr.build_record(_row(**over), ctx)


def _cand(rec, venue="kalshi", sigma=(0.045, dp.SIGMA_S2, "test"), decided=DECIDED):
    return dp.evaluate(rec, venue, decided, sigma, PARAMS)


# --------------------------------------------------------------------------- math


def test_logit_sigmoid_round_trip():
    for p in (0.01, 0.3, 0.5, 0.77, 0.99):
        assert dp.sigmoid(dp.logit(p)) == pytest.approx(p)


def test_dispersion_matches_stage1_code_with_equal_weights():
    """Parity with `syndicate_fair.dispersion_var` (the code sigma_fair_v1 was fitted with), pi = 1/n."""
    np = pytest.importorskip("numpy")
    from syndicate.features.shared import syndicate_fair as sf

    books = [[0.52, 0.48], [0.49, 0.51], [0.55, 0.45]]
    ds = sf.build_dataset([{"books": [(f"b{i}", 60.0, p) for i, p in enumerate(books)], "mfam": "totals",
                            "tts": "t6h", "t": [0.5, 0.5]}], [f"b{i}" for i in range(3)], target_key="t")
    p, _z, pi = sf.pooled(ds, np.zeros(3))
    ref = sf.dispersion_var(ds, pi, p)
    for j in (0, 1):
        assert dp.dispersion_var(books, j) == pytest.approx(float(ref[0, j]), rel=1e-9)
    assert dp.dispersion_var([[0.5, 0.5], [0.5, 0.5]], 0) == pytest.approx(0.0)


def test_baker_mchale_shrink():
    assert dp.baker_mchale(0.50, 0.52, 0.05) == 0.0                     # no edge -> no stake
    lam = dp.baker_mchale(0.55, 0.50, 0.05)
    assert 0.0 < lam < 1.0
    assert dp.baker_mchale(0.55, 0.50, 1e-9) == pytest.approx(1.0)       # a certain edge is not shrunk
    assert dp.baker_mchale(0.55, 0.50, 0.20) < lam                      # more uncertainty, more shrink


def test_kelly_on_the_lower_bound():
    assert dp.kelly_lb(0.55, 0.50) == pytest.approx(0.1)
    assert dp.kelly_lb(0.45, 0.50) == 0.0
    assert dp.kelly_lb(0.55, 1.0) == 0.0


def test_z_guard():
    assert dp.guarded_z(0.677) == 0.677
    assert dp.guarded_z(0.3) == dp.Z_DEFAULT
    assert dp.guarded_z(2.5) == dp.Z_DEFAULT
    assert dp.guarded_z(None) == dp.Z_DEFAULT
    assert dp.z_for(dp.SIGMA_S1, dp.Params(z_s1=None, z_s2=0.8)) == 0.8   # S1 unfitted -> z_S2
    assert dp.z_for(dp.SIGMA_S3, PARAMS) == 0.7


def test_r2_fallback_chain():
    assert dp.r2_for(PARAMS, "game", "totals", "t6h") == 0.0019
    assert dp.r2_for(PARAMS, "game", "totals", "t2h") == 0.0015         # cell absent -> (kind, mfam)
    assert dp.r2_for(PARAMS, "game", "h2h", "t2h") == 0.002             # -> kind
    assert dp.sigma_s3(PARAMS) == pytest.approx(2 * math.sqrt(0.002))


def test_committed_params_are_the_registered_fit():
    params = dp.load_params()
    assert params.loaded, params.error
    raw = json.loads(dp.PARAMS_PATH.read_text(encoding="utf-8"))
    assert raw["preregistration"] == "8d16ab07"
    assert raw["lower_bound_tail"] == dp.LOWER_BOUND_TAIL == 0.1587
    for z in (params.z_s1, params.z_s2):
        assert dp.Z_GUARD[0] <= z <= dp.Z_GUARD[1]
    for kind in ("game", "prop"):
        assert kind in params.r2_s2


# --------------------------------------------------------------------------- one candidate


def test_evaluate_reads_the_record_and_computes_ev_lb():
    rec = _rec()
    cand = _cand(rec)
    assert cand.eligible, cand.failed_gates
    q = next(p for p in rec.prices if p.role == "venue" and p.book == "kalshi")
    assert cand.cost == pytest.approx(q.price_prob + q.fee_per_contract)
    assert cand.ev_net_pct == pytest.approx((0.5 / cand.cost - 1) * 100, abs=1e-3)
    assert cand.p_lb == pytest.approx(dp.sigmoid(dp.logit(0.5) - 0.7 * 0.045), abs=1e-6)
    assert cand.ev_lb_pct == pytest.approx((cand.p_lb / cand.cost - 1) * 100, abs=1e-3)
    assert cand.ev_lb_pct < cand.ev_net_pct
    assert cand.axis == "total|full"


def test_p_fair_v1_is_never_read():
    """Only sigma_fair_v1 may reach the policy (user 2026-10-26): moving p_fair_v1 changes nothing."""
    rec = _rec()
    base = _cand(rec)
    rec.fair_v1.p_fair_v1 = 0.99
    moved = _cand(rec)
    assert (moved.p, moved.p_lb, moved.ev_lb_pct, moved.ev_net_pct) == (base.p, base.p_lb, base.ev_lb_pct,
                                                                         base.ev_net_pct)


@pytest.mark.parametrize("over, gate", [
    ({"commence_time": _iso(NOW - timedelta(minutes=5))}, "not_pregame"),
    ({"game_state": "live"}, "not_pregame"),
    ({"commence_time": _iso(NOW + timedelta(hours=40))}, "outside_decision_window"),
    ({"quote": {"fair_method": "book_margin_model"}}, "one_sided_fair"),
    ({"quote": {"suspect_stale": True}}, "stale_quote"),
    ({"quote": {"fair_probability": None}}, "no_market_fair"),
    ({"quote": {"book_prices": {"draftkings": 105, "kalshi": 200}}}, "implausible_venue_price"),
])
def test_per_line_gates(over, gate):
    cand = _cand(_rec(**over))
    assert gate in cand.failed_gates
    assert not dp.qualifies(dp.STRATEGY_EV_LB, cand)


def test_no_venue_price_is_no_candidate():
    assert _cand(_rec(quote={"book_prices": {"draftkings": 105}})) is None


def test_no_sigma_is_a_failed_gate_never_a_default():
    cand = _cand(_rec(), sigma=(None, None, "none"))
    assert "no_sigma" in cand.failed_gates and cand.ev_lb_pct is None


# --------------------------------------------------------------------------- strategies


def test_strategy_qualification():
    cand = _cand(_rec())
    assert cand.ev_lb_pct > 0 and dp.qualifies(dp.STRATEGY_EV_LB, cand)
    assert dp.qualifies(dp.STRATEGY_NET_FLOOR, cand) == (cand.ev_net_pct >= 1.0)
    assert not dp.qualifies(dp.STRATEGY_SUGGESTED, cand)
    assert dp.qualifies(dp.STRATEGY_SUGGESTED, _cand(_rec(suggested=True)))
    wide = _cand(_rec(), sigma=(0.4, dp.SIGMA_S3, "inflated"))
    assert wide.eligible and not dp.qualifies(dp.STRATEGY_EV_LB, wide)  # uncertainty shrinks, it does not exclude


def test_polymarket_floor_is_half_a_point():
    cand = _cand(_rec(quote={"book_prices": {"polymarket": 109}}), venue="polymarket")
    assert 0.5 <= cand.ev_net_pct < 1.0
    assert dp.qualifies(dp.STRATEGY_NET_FLOOR, cand)


def test_one_bet_per_game_axis_across_rungs_and_venues():
    """#711 R1: a ladder is ONE position. The moneyline and a spread rung share the margin axis."""
    ml = _cand(_rec(market="h2h", side="home", line=None, quote={"book_prices": {"kalshi": 110}}))
    rung = _cand(_rec(market="spreads", side="home", line=-3.5, quote={"book_prices": {"polymarket": 115}}),
                 venue="polymarket")
    total = _cand(_rec())
    other_game = _cand(_rec(event_id="ev2"))
    chosen = dp.select(dp.STRATEGY_EV_LB, [ml, rung, total, other_game])
    assert set(chosen) == {("ev1", "margin|full"), ("ev1", "total|full"), ("ev2", "total|full")}
    best = max((ml, rung), key=lambda c: c.ev_lb_pct)
    assert chosen[("ev1", "margin|full")] is best


def test_stake_caps():
    cand = _cand(_rec())
    cand.fraction = 0.03
    assert dp.stake_units(cand, 0.0) == (30.0, 0.03)          # fraction is already <= MAX_BET_FRACTION upstream
    cand.fraction = 0.02
    assert dp.stake_units(cand, 0.0) == (20.0, 0.02)
    assert dp.stake_units(cand, 0.04) == (10.0, 0.01)          # the game has 0.01 of room left
    assert dp.stake_units(cand, 0.05) == (0.0, 0.0)
    assert _cand(_rec()).fraction <= dp.MAX_BET_FRACTION
