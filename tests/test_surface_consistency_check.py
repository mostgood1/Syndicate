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


def _ev(p, price, fee=0.0):
    from syndicate.features.shared.cheat_sheets import ev_pct

    return ev_pct(p, price, fee)


def test_same_price_ev_compares_the_boards_net_ev_not_its_gross():
    # 2026-11-27: 10 of 25 "gaps" were the board's GROSS ev_pct against the sheet's NET ev_market.
    fee = 0.02
    net = _ev(0.5, 110, fee)
    row = _l2_row(ev_pct=_ev(0.5, 110), score_v2={"ev_net_pct": net, "fee_per_contract": fee},
                  quote={"fair_probability": 0.5, "bookmaker": "kalshi", "price": 110})
    l2 = scc.layer2_records({"rows": [row]})
    sheet_net = scc.cheat_records({"rows": [_cheat_row(check={"p_market": 0.5, "ev_market": net, "book": "kalshi", "price": 110})]})
    assert scc.check_same_price_ev(l2, sheet_net, name="cheat")["bad"] == 0
    # a sheet that showed the GROSS number at a fee venue is a real disagreement
    sheet_gross = scc.cheat_records({"rows": [_cheat_row(check={"p_market": 0.5, "ev_market": _ev(0.5, 110), "book": "kalshi", "price": 110})]})
    assert scc.check_same_price_ev(l2, sheet_gross, name="cheat")["bad"] == 1
    # a row without score_v2 still compares its ev_pct (a sportsbook: gross == net)
    plain = scc.layer2_records({"rows": [_l2_row()]})
    assert plain[next(iter(plain))]["ev_judged"] == 4.0


def test_same_price_ev_reads_a_moved_fair_as_age_and_a_rule_gap_as_bad():
    # the board's fair moved 0.50 -> 0.52 after the sheet was published; the price stayed +110
    row = _l2_row(ev_pct=_ev(0.52, 110), quote={"fair_probability": 0.52, "bookmaker": "betmgm", "price": 110})
    l2 = scc.layer2_records({"rows": [row]})
    then = scc.cheat_records({"rows": [_cheat_row(check={"p_market": 0.5, "ev_market": _ev(0.5, 110), "book": "betmgm", "price": 110})]})
    out = scc.check_same_price_ev(l2, then, name="cheat")
    assert out["n"] == 1 and out["bad"] == 0 and out["fair_moved"] == 1
    # the same move, but the sheet's EV is 2 pts off its own fair: the rule differs
    off = scc.cheat_records({"rows": [_cheat_row(check={"p_market": 0.5, "ev_market": _ev(0.5, 110) - 2.0, "book": "betmgm", "price": 110})]})
    out = scc.check_same_price_ev(l2, off, name="cheat")
    assert out["bad"] == 1 and out["fair_moved"] == 0
    assert abs(out["examples"][0]["after_fair_move"] - 2.0) < 0.02


def test_same_price_ev_moved_fair_uses_the_fee_formula():
    # Kalshi at +9900 (1c): a 0.01 pp fair move is about 1 pt of EV -- measured 2026-11-27, it read as a rule gap
    fee = 0.0007
    row = _l2_row(ev_pct=_ev(0.0097, 9900), score_v2={"ev_net_pct": _ev(0.0097, 9900, fee), "fee_per_contract": fee},
                  quote={"fair_probability": 0.0097, "bookmaker": "kalshi", "price": 9900})
    l2 = scc.layer2_records({"rows": [row]})
    then = scc.cheat_records({"rows": [_cheat_row(check={"p_market": 0.0096, "ev_market": _ev(0.0096, 9900, fee), "book": "kalshi", "price": 9900})]})
    out = scc.check_same_price_ev(l2, then, name="cheat")
    assert out["bad"] == 0 and out["fair_moved"] == 1


def test_pick_flag_checks_the_sheets_verdict_against_the_board_flag_it_copied():
    l2 = scc.layer2_records({"rows": [_l2_row()]})
    assert scc.check_pick_flag(l2, scc.cheat_records({"rows": [_cheat_row()]}))["bad"] == 0
    # the board's pick, but the sheet's verdict is not "value": the sheet refused the board's pick
    refused = _cheat_row(check={"p_market": 0.5, "ev_market": 4.0, "book": "betmgm", "price": 110, "verdict": "neutral"})
    assert scc.check_pick_flag(l2, scc.cheat_records({"rows": [refused]}))["bad"] == 1
    # "value" on a row the board did not suggest
    assert scc.check_pick_flag(l2, scc.cheat_records({"rows": [_cheat_row(suggested=False)]}))["bad"] == 1


def test_pick_flag_reports_a_board_change_since_the_sheet_without_counting_it():
    l2 = scc.layer2_records({"rows": [_l2_row(suggested=False)]})  # the board dropped it after the sheet was published
    out = scc.check_pick_flag(l2, scc.cheat_records({"rows": [_cheat_row()]}))
    assert out["bad"] == 0 and out["changed_since_sheet"] == 1 and out["on_board_now"] == 1


def test_pick_flag_skips_a_rebuilt_game_the_board_never_judged():
    # a rebuilt row keeps the price rule: "value" with no board flag is not a disagreement
    payload = {"rows": [_cheat_row(suggested=False)], "games": [{"event_id": "e1", "rebuilt": True}]}
    out = scc.check_pick_flag({}, scc.cheat_records(payload))
    assert out["n"] == 0 and out["bad"] == 0


def test_ask_headline_flags_non_picks_and_off_sport_rows_and_only_reports_model_skill():
    good = {"structured_response": {"top_opportunities": [
        {"sport": "nba", "suggested": True, "model_skill_status": "measured", "model_skill_verdict": "beats the close"},
        # a board pick on price whose sim is rated as losing is NOT bad: the verdict is information
        {"sport": "nba", "suggested": True, "model_skill_status": "measured", "model_skill_verdict": "loses to the close"},
    ]}}
    out = scc.check_ask_headline(good, asked_sport="nba")
    assert (out["bad"], out["losing_model"]) == (0, 1)
    bad = {
        "structured_response": {
            "top_opportunities": [
                {"sport": "nfl", "suggested": True, "model_skill_status": "measured", "model_skill_verdict": "loses to the de-vigged market"},
                {"sport": "nba", "model_skill_status": "unmeasured", "model_skill_verdict": "never backtested"},
            ]
        }
    }
    out = scc.check_ask_headline(bad, asked_sport="nba")
    assert (out["bad"], out["not_a_board_pick"], out["off_sport"], out["losing_model"], out["unmeasured_model"]) == (2, 1, 1, 1, 1)


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
