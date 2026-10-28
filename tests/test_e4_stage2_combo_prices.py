"""Hermetic tests for scripts/e4_stage2_combo_prices.py (E4 Stage 2, prereg 9f8d759e + A1/A2/A3)."""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import e4_stage2_combo_prices as s2  # noqa: E402


# ------------------------------------------------------------------ cell shape from tickers alone
def test_shape_cell_mlb_same_batter_nested_and_other():
    a = "KXMLBHIT-26OCT05NYYTOR-NYYAJUDGE99-2"
    assert s2.shape_cell("mlb", None, a, "KXMLBTB-26OCT05NYYTOR-NYYAJUDGE99-3") == "SP-nested"
    assert s2.shape_cell("mlb", None, a, "KXMLBRBI-26OCT05NYYTOR-NYYAJUDGE99-1") == "SP-other"
    assert s2.shape_cell("mlb", None, a, "KXMLBTB-26OCT05NYYTOR-NYYGSTANTON27-3") is None     # teammate: not passing
    assert s2.shape_cell("mlb", None, a, "KXMLBHIT-26OCT05NYYTOR-NYYAJUDGE99-3") is None      # same stat, two lines
    assert s2.shape_cell("mlb", None, a, "KXMLBHRR-26OCT05NYYTOR-NYYAJUDGE99-3") is None      # HRR is no Stage 1 market


def test_shape_cell_nba_nested_vs_disjoint():
    a = "KXNBAPTS-26OCT20BOSDET-DETJDUREN0-10"
    assert s2.shape_cell("nba", None, a, "KXNBAPRA-26OCT20BOSDET-DETJDUREN0-25") == "SP-nested"
    assert s2.shape_cell("nba", None, a, "KXNBAREB-26OCT20BOSDET-DETJDUREN0-6") == "SP-disjoint"
    assert s2.shape_cell("nba", None, a, "KXNBA3PT-26OCT20BOSDET-DETJDUREN0-1") is None


def test_shape_cell_soccer_full_match_only_and_stage1_leagues_only():
    g, t, b = "KXEPLGAME-26OCT10ARSLEE-ARS", "KXEPLTOTAL-26OCT10ARSLEE-3", "KXEPLBTTS-26OCT10ARSLEE-BTTS"
    assert s2.shape_cell("soccer", "epl", g, t) == "GL"
    assert s2.shape_cell("soccer", "epl", b, t) == "GL"
    assert s2.shape_cell("soccer", "epl", g, "KXEPLGAME-26OCT10ARSLEE-TIE") is None           # result x result
    assert s2.shape_cell("soccer", "epl", g, "KXEPL1HTOTAL-26OCT10ARSLEE-2") is None          # first half
    assert s2.shape_cell("soccer", "ucl", "KXUCLGAME-26OCT13X-Y", "KXUCLTOTAL-26OCT13X-3") is None  # no Stage 1 sim
    assert s2.soccer_kind("KXUCLTEAMTOTAL") is None


# ------------------------------------------------------------------ the capture store
def _row(ticker, legs, **kw):
    groups = kw.pop("groups", [{"sport": "mlb", "league": None, "game": "26OCT05NYYTOR", "legs": [0, 1]}])
    row = {"ticker": ticker, "n_legs": len(legs), "traded": True, "result": "yes", "volume_fp": 10.0,
           "quote_at_capture": {"last_price": 0.31}, "same_game": groups,
           "legs": [{"market_ticker": t, "event_ticker": t.rsplit("-", 2)[0], "side": "yes"} for t in legs]}
    row.update(kw)
    return row


LEGS = ["KXMLBHIT-26OCT05NYYTOR-NYYAJUDGE99-2", "KXMLBTB-26OCT05NYYTOR-NYYAJUDGE99-3"]


def test_candidate_filters_each_refusal_by_name():
    f = Counter()
    ok = s2.candidate(_row("C1", LEGS), f)
    assert ok["shape_cell"] == "SP-nested" and ok["q"] == pytest.approx(0.31) and ok["game_date"] == "2026-10-05"
    assert s2.candidate(_row("C2", LEGS + ["KXMLBRBI-26OCT05NYYTOR-NYYAJUDGE99-1"]), f) is None
    assert s2.candidate(_row("C3", LEGS, traded=False), f) is None
    assert s2.candidate(_row("C4", LEGS, groups=[{"sport": "mlb", "game": "x", "legs": [0]},
                                                 {"sport": "mlb", "game": "y", "legs": [1]}]), f) is None
    late = ["KXMLBHIT-26OCT27NYYTOR-NYYAJUDGE99-2", "KXMLBTB-26OCT27NYYTOR-NYYAJUDGE99-3"]
    assert s2.candidate(_row("C5", late), f) is None
    assert s2.candidate(_row("C6", LEGS, quote_at_capture={"last_price": 0.0}), f) is None
    assert f["untraded"] == 1 and f["not_one_game"] == 1 and f["outside_window"] == 1 and f["no_print_price"] == 1


def test_iter_store_streams_first_row_per_ticker(tmp_path):
    d = tmp_path.joinpath(*s2.STORE_SUBDIR)
    d.mkdir(parents=True)
    rows = [_row("C1", LEGS, result="yes"), _row("C1", LEGS, result="no"),
            _row("C2", LEGS + ["KXMLBRBI-26OCT05NYYTOR-NYYAJUDGE99-1"])]
    with gzip.open(d / "combos_2026-10-05.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    got = list(s2.iter_store(tmp_path, s2.s1.WINDOW_START, s2.s1.WINDOW_END))
    assert [r["ticker"] for r in got] == ["C1"] and got[0]["result"] == "yes"


# ------------------------------------------------------------------ leg metadata (real shapes read 2026-10-28)
def test_parse_leg_props_soccer_and_refusals():
    hit = {"title": "Drake Baldwin: 2+ hits?", "floor_strike": 1.5, "strike_type": "greater"}
    leg = s2.parse_leg("mlb", "KXMLBHIT-26SEP271510ATLMIA-ATLDBALDWIN30-2", hit)
    assert leg == {"market": "batter_hits", "subject": "drake baldwin", "line": 1.5}
    pts = {"title": "Jalen Duren: 10+ points", "floor_strike": 9.5, "strike_type": "greater"}
    assert s2.parse_leg("nba", "KXNBAPTS-26OCT20BOSDET-DETJDUREN0-10", pts)["market"] == "player_points"
    assert s2.parse_leg("mlb", "KXMLBHIT-x-y-2", dict(hit, strike_type="less")) is None
    tot = {"title": "Will over 2.5 goals be scored?", "floor_strike": 2.5, "strike_type": "greater"}
    assert s2.parse_leg("soccer", "KXMLSTOTAL-26SEP27CLBMIA-3", tot)["line"] == 2.5
    assert s2.parse_leg("soccer", "KXMLSTOTAL-26SEP27CLBMIA-3", dict(tot, floor_strike=3.0)) is None   # x.5 only
    assert s2.parse_leg("soccer", "KXEPLBTTS-26OCT10ARSLEE-BTTS", {"title": "Both Teams To Score"})["market"] == "btts"
    tie = s2.parse_leg("soccer", "KXEPLGAME-26OCT10ARSLEE-TIE", {"title": "Tie is the result"})
    assert tie["draw"] is True
    club = s2.parse_leg("soccer", "KXMLSGAME-26SEP27CLBMIA-CLB", {"title": "Columbus wins"})
    assert club["club"] == "Columbus" and club["draw"] is False
    assert s2.parse_leg("mlb", "KXMLBHIT-x-y-2", None) is None


def test_soccer_code_names_scoped_per_league():
    metas = [("mls", {"ticker": "KXMLSGAME-26SEP27TORMIA-TOR", "title": "Toronto wins"}),
             ("serie_a", {"ticker": "KXSERIEAGAME-26OCT04TORGEN-TOR", "title": "Torino wins"}),
             ("mls", {"ticker": "KXMLSTOTAL-26SEP27TORMIA-3", "title": "Will over 2.5 goals be scored?"})]
    names = s2.soccer_code_names(metas)
    assert names["mls"]["TOR"] == "Toronto" and names["serie_a"]["TOR"] == "Torino" and len(names["mls"]) == 1


def test_fetch_leg_meta_batches_and_caches(tmp_path):
    calls = []

    def get(path, params):
        calls.append(params["tickers"].split(","))
        return {"markets": [{"ticker": t, "title": f"{t}: 1+ hits?"} for t in params["tickers"].split(",")]}

    tickers = [f"T{i:03d}" for i in range(150)]
    meta, st = s2.fetch_leg_meta(tickers, tmp_path, get=get)
    assert st["gets"] == 2 and len(meta) == 150 and max(len(c) for c in calls) == s2.META_BATCH
    _, st2 = s2.fetch_leg_meta(tickers, tmp_path, get=get)
    assert st2["gets"] == 0                                                  # all cached


def test_fee_multiplier_read_or_upper_bound():
    m, ub = s2.read_fee_multiplier("KXMVECROSSCATEGORY", get=lambda p: {"series": {"fee_type": "quadratic",
                                                                                  "fee_multiplier": 0.5}})
    assert (m, ub) == (0.5, False)
    assert s2.read_fee_multiplier("KXMVECROSSCATEGORY", get=lambda p: None) == (1.0, True)


# ------------------------------------------------------------------ marginal at the combo's own line (A3 §5)
def test_marginal_at_exact_line_two_sided_same_book_median():
    latest = {
        ("e1", "dk", "batter_hits", "aaron judge", 1.5, "over"): (0, 150), ("e1", "dk", "batter_hits", "aaron judge", 1.5, "under"): (0, -180),
        ("e1", "fd", "batter_hits", "aaron judge", 1.5, "over"): (0, 140), ("e1", "fd", "batter_hits", "aaron judge", 1.5, "under"): (0, -170),
        ("e1", "mgm", "batter_hits", "aaron judge", 1.5, "over"): (0, 160),                  # one-sided: never priced
        ("e1", "dk", "batter_hits", "aaron judge", 0.5, "over"): (0, -300), ("e1", "dk", "batter_hits", "aaron judge", 0.5, "under"): (0, 240),
    }
    idx = s2.line_index(latest)
    m = s2.marginal_at(idx, "e1", "batter_hits", "a judge", 1.5, ("over", "under"), "over")
    dk = s2.s1.devig_book({"over": 150, "under": -180}, ("over", "under"))["over"]
    fd = s2.s1.devig_book({"over": 140, "under": -170}, ("over", "under"))["over"]
    assert m["n_books"] == 2 and m["p"] == pytest.approx((dk + fd) / 2)
    assert s2.marginal_at(idx, "e1", "batter_hits", "aaron judge", 2.5, ("over", "under"), "over") is None
    assert s2.marginal_at(idx, "e1", "batter_hits", "someone else", 1.5, ("over", "under"), "over") is None


# ------------------------------------------------------------------ the combo's probabilities, fee, EV
def test_combo_probs_sides_sum_to_one_and_rho_is_reachable():
    pa, pb = 0.6, 0.3
    cells = {(x, y): s2.combo_probs(pa, pb, 0.0, x, y) for x in ("yes", "no") for y in ("yes", "no")}
    assert cells[("yes", "yes")] == pytest.approx(pa * pb)
    assert cells[("yes", "no")] == pytest.approx(pa * (1 - pb))
    assert cells[("no", "no")] == pytest.approx((1 - pa) * (1 - pb))
    assert sum(cells.values()) == pytest.approx(1.0)
    on = s2.combo_probs(pa, pb, 0.5, "yes", "yes")
    assert on > pa * pb + 0.02                                      # off != on: the sim's rho moves the price
    assert s2.combo_probs(pa, pb, 0.5, "yes", "no") == pytest.approx(pa - on)
    assert s2.combo_probs(pa, pb, None, "yes", "yes") is None


def test_fee_and_ev_formulae():
    assert s2.fee_per_contract(0.5, 1.0) == pytest.approx(0.0175)
    assert s2.ev_yes(0.5, 0.4, 1.0) == pytest.approx(0.5 / (0.4 + 0.07 * 0.24) - 1)
    assert s2.ev_no(0.5, 0.4, 0.5) == pytest.approx(0.5 / (0.6 + 0.035 * 0.24) - 1)


@pytest.mark.parametrize("delta,band", [(-0.06, "<=-5"), (-0.05, "<=-5"), (-0.04, "(-5,-3]"), (-0.03, "(-5,-3]"),
                                        (-0.02, "(-3,-1]"), (-0.01, "(-3,-1]"), (-0.005, "(-1,0)"), (0.0, "[0,1)"),
                                        (0.01, "[1,3)"), (0.03, "[3,5)"), (0.05, ">=5")])
def test_bands(delta, band):
    assert s2.band_of(delta) == band


# ------------------------------------------------------------------ joining a combo to a Stage 1 game
def test_join_game_by_blob_and_date():
    games = [{"game": "mlb:1", "date": "2026-10-05", "event": "e1"}, {"game": "mlb:2", "date": "2026-10-05", "event": "e2"}]
    events = {"e1": {"home": "TOR", "away": "NYY", "commence": s2.s1.parse_ts("2026-10-05T23:08:00Z")},
              "e2": {"home": "BOS", "away": "TB", "commence": s2.s1.parse_ts("2026-10-05T23:10:00Z")}}
    bg = s2.blob_games(games, events)
    c = {"sport": "mlb", "league": None, "game_date": "2026-10-05",
         "legs": [{"ticker": "KXMLBHIT-26OCT051908NYYTOR-NYYAJUDGE99-2"}]}
    g, why = s2.join_game(c, games, bg, {})
    assert why == "ok" and g["game"] == "mlb:1"
    g, why = s2.join_game(dict(c, game_date="2026-10-09"), games, bg, {})
    assert g is None and why == "no_stage1_game_that_day"


def test_soccer_side_draw_and_name_fallback():
    meta = {"home": "Alphaville Rovers", "away": "Betatown United"}
    assert s2._soccer_side({"draw": True}, meta) == "draw"
    assert s2._soccer_side({"draw": False, "club": "Alphaville"}, meta) == "home"
    assert s2._soccer_side({"draw": False, "club": "Betatown"}, meta) == "away"
    assert s2._soccer_side({"draw": False, "club": "Gammaburg"}, meta) is None


# ------------------------------------------------------------------ readings (A3 §8-§9)
def test_clustered_slope_recovers_a_known_slope():
    rng = np.random.default_rng(1)
    x = rng.uniform(-0.05, 0.08, 4000)
    games = rng.integers(0, 200, 4000)
    y = 0.03 + 0.8 * x + rng.normal(0, 0.01, 4000)
    res = s2.clustered_slope(x, y, games)
    assert res["slope"] == pytest.approx(0.8, abs=0.03) and res["ci"][0] < 0.8 < res["ci"][1]


def _priced(i, game, delta, ret, q=0.3):
    return {"sport": "soccer", "cell": "GL", "game": game, "q": q, "p_a": 0.25, "p_b": 0.25 + delta, "p_c": None,
            "ev_b": 0.1, "ev_b_no": -0.1, "ret_yes": ret, "ret_no": -ret, "y_kalshi": int(ret > 0), "volume": 5.0}


def test_r2_insufficient_below_min_n_and_never_a_kill():
    rows = [_priced(i, f"g{i % 5}", 0.03, 1.0) for i in range(50)]
    t = s2.r2_test(rows, "yes")
    assert not t["sufficient"] and t["p_holm_input"] == 1.0 and s2.verdict_r2(t, False) == "INSUFFICIENT"


def test_r2_edge_needs_holm_and_ci_above_zero():
    rng = np.random.default_rng(2)
    rows = [_priced(i, f"g{i % 40}", 0.03, float(rng.choice([2.0, -1.0], p=[0.5, 0.5]))) for i in range(600)]
    out = s2.readings(rows)
    t = out["cells"]["soccer|GL"]["R2_yes"]
    assert t["sufficient"] and t["mean"] > 0 and t["verdict"] in ("EDGE", "LEAD")
    assert out["cells"]["mlb|SP-nested"]["R2_yes"]["verdict"] == "INSUFFICIENT"
    assert set(out["holm"]["pvals"]) == {f"{s}|{c}|{side}" for s, c in s2.PASSING for side in ("yes", "no")}
    neg = s2.r2_test([dict(r, ret_yes=-0.5) for r in rows], "yes")
    assert neg["p_holm_input"] == 1.0 and s2.verdict_r2(neg, False) == "NO EDGE"


def test_finish_row_uses_kalshi_result_only_when_our_grading_agrees():
    base = {"q": 0.4, "p_a": 0.3, "p_b": 0.35, "p_c": None, "y_ours": 1}
    f = Counter()
    r = s2.finish_row(dict(base, result="yes"), 1.0, f)
    assert r["ret_yes"] == pytest.approx(1 / (0.4 + s2.fee_per_contract(0.4, 1.0)) - 1) and r["ev_c"] is None
    r = s2.finish_row(dict(base, result="no"), 1.0, f)
    assert r["ret_yes"] is None and f["grading_disagrees_with_kalshi"] == 1
    r = s2.finish_row(dict(base, result="void"), 1.0, f)
    assert r["ret_yes"] is None and f["kalshi_result_not_yes_no"] == 1
