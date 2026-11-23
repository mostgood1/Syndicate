"""Tests for scripts/surface_consistency_check.py (lane surface-consistency-oversight, todo #861).

Each check is tested on a fixture that must PASS and one that must FAIL, so a check
that can only ever say OK (or only OVER) is caught here rather than on the fleet.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("surface_consistency_check", ROOT / "scripts" / "surface_consistency_check.py")
scc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scc)


def _l2_row(**kw):
    row = {
        "event_id": "e1",
        "market": "player_points",
        "player_name": "A Player",
        "side": "over",
        "line": 20.5,
        "segment": "full",
        "ev_pct": 4.0,
        "suggested": True,
        "is_live": False,
        "model_probability_cal": 0.5,
        "quote": {"fair_probability": 0.5, "bookmaker": "betmgm", "price": 110},
        "projection": {"p_model_raw": 0.6},
    }
    row.update(kw)
    return row


def _cheat_row(**kw):
    row = {
        "event_id": "e1",
        "market": "player_points",
        "player": "A Player",
        "side": "over",
        "line": 20.5,
        "suggested": True,
        "check": {"p_market": 0.5, "p_model": 0.5, "ev_market": 4.0, "book": "betmgm", "price": 110, "verdict": "value"},
    }
    row.update(kw)
    return row


def test_line_key_normalises_market_side_and_line():
    assert scc.line_key("e1", "player_points", "A Player", "Yes", 20.4) == scc.line_key("e1", "POINTS", "a player ", "over", 20.5)
    assert scc.line_key("e1", "h2h", None, "home", None)[4] is None


def test_american_to_prob():
    assert abs(scc.american_to_prob(100) - 0.5) < 1e-12
    assert abs(scc.american_to_prob(-200) - 2 / 3) < 1e-12
    assert scc.american_to_prob(50) is None  # not an American price
    assert scc.american_to_prob(None) is None


def test_same_price_ev_passes_when_evs_agree_and_fails_when_they_differ():
    l2 = scc.layer2_records({"rows": [_l2_row()]})
    same = scc.cheat_records({"rows": [_cheat_row()]})
    assert scc.check_same_price_ev(l2, same, name="cheat")["bad"] == 0
    differ = scc.cheat_records({"rows": [_cheat_row(check={"p_market": 0.48, "ev_market": 1.0, "book": "betmgm", "price": 110})]})
    out = scc.check_same_price_ev(l2, differ, name="cheat")
    assert out["n"] == 1 and out["bad"] == 1


def test_same_price_ev_ignores_a_different_price():
    # age can move the price; only an identical price makes an EV gap a method gap
    l2 = scc.layer2_records({"rows": [_l2_row()]})
    moved = scc.cheat_records({"rows": [_cheat_row(check={"p_market": 0.5, "ev_market": 1.0, "book": "betmgm", "price": 105})]})
    assert scc.check_same_price_ev(l2, moved, name="cheat")["n"] == 0


def test_pick_flag():
    l2 = scc.layer2_records({"rows": [_l2_row()]})
    assert scc.check_pick_flag(l2, scc.cheat_records({"rows": [_cheat_row()]}))["bad"] == 0
    assert scc.check_pick_flag(l2, scc.cheat_records({"rows": [_cheat_row(suggested=False)]}))["bad"] == 1


def test_ask_headline_flags_losing_unmeasured_and_off_sport_rows():
    good = {"structured_response": {"top_opportunities": [{"sport": "nba", "model_skill_status": "measured", "model_skill_verdict": "beats the close"}]}}
    assert scc.check_ask_headline(good, asked_sport="nba")["bad"] == 0
    bad = {
        "structured_response": {
            "top_opportunities": [
                {"sport": "nfl", "model_skill_status": "measured", "model_skill_verdict": "loses to the de-vigged market"},
                {"sport": "nba", "model_skill_status": "unmeasured", "model_skill_verdict": "never backtested"},
            ]
        }
    }
    out = scc.check_ask_headline(bad, asked_sport="nba")
    assert (out["bad"], out["losing_model"], out["unmeasured_model"], out["off_sport"]) == (2, 1, 1, 1)


def test_sim_attribution_catches_the_market_number_under_the_sims_name():
    l2 = scc.layer2_records({"rows": [_l2_row()]})  # sim ladder 0.60, fair 0.50
    card = {"event_id": "e1", "market": "player_points", "player": "A Player", "side": "over", "line": 20.5}
    lying = {"board_contract": {"cards": [dict(card, detail="Our sim has A Player over 20.5 points at 50.0%; the market says 50.0%.")]}}
    honest = {"board_contract": {"cards": [dict(card, detail="Our sim has A Player over 20.5 points at 60.0%; the market says 50.0%.")]}}
    assert scc.check_sim_attribution(lying, l2)["bad"] == 1
    assert scc.check_sim_attribution(honest, l2)["bad"] == 0


def test_plan_vs_orders():
    plan = {"positions": [{"position_key": "p1"}]}
    live_ok = {"orders": [{"mode": "live", "position_key": "p1"}]}
    live_bad = {"orders": [{"mode": "live", "position_key": "p9"}, {"mode": "paper", "position_key": "p8"}]}
    assert scc.check_plan_vs_orders(plan, live_ok, {})["bad"] == 0
    out = scc.check_plan_vs_orders(plan, live_bad, {})
    assert out["n"] == 1 and out["bad"] == 1  # paper orders are not counted


def test_venue_price_hidden():
    l2 = scc.layer2_records({"rows": [_l2_row(quote={"fair_probability": 0.5, "bookmaker": "betmgm", "price": -250})]})
    base = {"event_id": "e1", "market": "points", "player_name": "A Player", "side": "over", "line": 20.5, "segment": "full", "book": "kalshi"}
    better = {"orders": [dict(base, requested_price=-213)]}
    worse = {"orders": [dict(base, requested_price=-260)]}
    assert scc.check_venue_price_hidden(better, l2)["bad"] == 1
    assert scc.check_venue_price_hidden(worse, l2)["bad"] == 0


def test_sport_card_bias():
    layer1 = {"games": [{"away_team": "Away Club", "home_team": "Home Club", "rows": [{"market": "h2h", "segment": "full", "consensus": {"away": 100, "home": -120}}]}]}
    fair_away = scc.american_to_prob(100) / (scc.american_to_prob(100) + scc.american_to_prob(-120))
    on_fair = {"games": [{"away_name": "Away Club", "home_name": "Home Club", "betting": {"p_away_win": fair_away}}]}
    biased = {"games": [{"away_name": "Away Club", "home_name": "Home Club", "betting": {"p_away_win": fair_away + 0.05}}]}
    assert scc.check_sport_card_bias(on_fair, layer1)["bad"] == 0
    out = scc.check_sport_card_bias(biased, layer1)
    assert out["bad"] == 1 and abs(out["mean_signed_pp"] - 5.0) < 0.01


def test_run_checks_on_an_empty_reading_is_all_ok_with_n_zero():
    # nothing to compare is not a disagreement; main() separately exits 2 on fetch errors
    checks = scc.run_checks({})
    assert checks and all(c["verdict"] == "OK" and c["n"] == 0 for c in checks)
