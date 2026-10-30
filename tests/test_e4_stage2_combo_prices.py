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
    m, ub, _ = s2.read_fee_multiplier("KXMVECROSSCATEGORY", get=lambda p: {"series": {"fee_type": "quadratic",
                                                                                     "fee_multiplier": 0.5}})
    assert (m, ub) == (0.5, False)
    assert s2.read_fee_multiplier("KXMVECROSSCATEGORY", get=lambda p: None)[:2] == (1.0, True)
    # the combo series' real reading (2026-10-28): an unknown fee type is refused, the bound applies, the raw is kept
    m, ub, raw = s2.read_fee_multiplier("KXMVECROSSCATEGORY", get=lambda p: {"series": {
        "fee_type": "quadratic_with_combo_maker_fees", "fee_multiplier": 1}})
    assert (m, ub) == (1.0, True) and raw == {"fee_type": "quadratic_with_combo_maker_fees", "fee_multiplier": 1}


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
    g, why = s2.join_game(dict(c, game_date="2026-10-09",
                               legs=[{"ticker": "KXMLBHIT-26OCT091908NYYTOR-NYYAJUDGE99-2"}]), games, bg, {})
    assert g is None and why == "no_stage1_game_in_slot"


def test_join_game_series_rematch_next_day_is_not_ambiguous():
    """A4: a postseason series plays the same blob on consecutive days; the ticker's start time picks the game."""
    games = [{"game": "mlb:1", "date": "2026-10-05", "event": "e1"}, {"game": "mlb:2", "date": "2026-10-06", "event": "e2"}]
    events = {"e1": {"home": "TOR", "away": "NYY", "commence": s2.s1.parse_ts("2026-10-05T23:08:00Z")},
              "e2": {"home": "TOR", "away": "NYY", "commence": s2.s1.parse_ts("2026-10-06T23:08:00Z")}}
    bg = s2.blob_games(games, events)
    c = {"sport": "mlb", "league": None, "game_date": "2026-10-06",
         "legs": [{"ticker": "KXMLBHIT-26OCT061908NYYTOR-NYYAJUDGE99-2"}]}
    g, why = s2.join_game(c, games, bg, {})
    assert why == "ok" and g["game"] == "mlb:2"
    # no start time in the ticker (NBA, soccer): the US/Eastern date decides; a 00:30Z tip is the previous ET day
    assert s2.same_slot("2026-10-21T00:30:00Z", "2026-10-20", None)
    assert not s2.same_slot("2026-10-21T00:30:00Z", "2026-10-21", None)


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


def test_r3_drops_combos_whose_grading_disagrees_with_kalshi():
    agree = [{"y_kalshi": i % 2, "y_ours": i % 2, "p_a": 0.4, "p_b": 0.45, "game": f"g{i % 5}"} for i in range(20)]
    bad = [{"y_kalshi": 1, "y_ours": 0, "p_a": 0.1, "p_b": 0.9, "game": "g0"},
           {"y_kalshi": None, "y_ours": 1, "p_a": 0.1, "p_b": 0.9, "game": "g1"}]
    got, want = s2.r3_logloss(agree + bad), s2.r3_logloss(agree)
    assert got["D_ba"]["n"] == len(agree)
    assert got["D_ba"]["mean"] == pytest.approx(want["D_ba"]["mean"]) and got["mean_y"] == want["mean_y"]


# ------------------------------------------------------------------ Amendment A5 (lane e4-pregame-prints): the pregame print
from datetime import date as _date, datetime as _dt, timezone as _tz  # noqa: E402

KICK = _dt(2026, 11, 1, 15, 0, tzinfo=_tz.utc)
GL = ["KXEPLGAME-26NOV01ARSCRY-ARS", "KXEPLTOTAL-26NOV01ARSCRY-3"]
GL_GROUP = [{"sport": "soccer", "league": "epl", "game": "26NOV01ARSCRY", "legs": [0, 1]}]


def _print(hhmm, side, yes, no=None):
    h, m = hhmm.split(":")
    return {"t": f"2026-11-01T{h}:{m}:00Z", "taker_side": side, "yes": yes,
            "no": round(1 - yes, 4) if no is None else no, "count": 1.0}


PRINTS = [_print("12:00", "yes", 0.28), _print("13:30", "no", 0.33), _print("14:10", "yes", 0.30),
          _print("14:50", "no", 0.31), _print("15:40", "no", 0.04), _print("16:30", "yes", 0.97)]


def test_a5_prices_take_the_last_pregame_print_on_each_taker_side():
    p = s2.a5_prices(PRINTS, KICK)
    assert p["q_yes"] == pytest.approx(0.30)          # the 14:10 YES taker, not the in-play 0.97
    assert p["q_no"] == pytest.approx(0.69)           # the 14:50 NO taker paid its `no` price
    assert p["q_any"] == pytest.approx(0.31)          # the last pregame print's YES price, either side
    assert p["n_prints"] == 6 and p["n_pregame"] == 4 and p["mins_before"] == pytest.approx(10.0)
    assert p["last_in_play"] is True and p["first_in_play"] is False
    p15 = s2.a5_prices(PRINTS, KICK, s2.A5_SENSITIVITY)   # t < 14:45
    assert p15["q_yes"] == pytest.approx(0.30) and p15["q_no"] == pytest.approx(0.67) and p15["q_any"] == pytest.approx(0.30)


def test_a5_prices_skip_a_price_outside_zero_one_and_read_none_when_nothing_is_pregame():
    p = s2.a5_prices([_print("13:00", "yes", 0.25), _print("14:00", "yes", 1.0, no=0.0)], KICK)
    assert p["q_yes"] == pytest.approx(0.25) and p["q_no"] is None and p["q_any"] == pytest.approx(0.25)
    late = s2.a5_prices([_print("15:00", "yes", 0.4), _print("16:00", "no", 0.2)], KICK)  # t == commence is in play
    assert late["q_yes"] is late["q_no"] is late["q_any"] is late["mins_before"] is None
    assert late["first_in_play"] is True and s2.a5_prices(None, KICK)["n_prints"] == 0


def _a5_row(ticker, **kw):
    kw.setdefault("groups", GL_GROUP)
    kw.setdefault("settlement_ts", "2026-11-01T17:05:00Z")
    kw.setdefault("trades_status", "ok")
    kw.setdefault("trades", PRINTS)
    kw.setdefault("quote_at_capture", {"last_price": 0.97})   # the listing's last print: in play
    return _row(ticker, GL, **kw)


def test_a5_candidate_reads_prints_in_the_window_and_counts_missing_rows(monkeypatch):
    monkeypatch.setattr(s2.s1, "WINDOW_START", _date(2026, 10, 31))
    monkeypatch.setattr(s2.s1, "WINDOW_END", _date(2026, 11, 22))
    f = Counter()
    reg = s2.candidate(_a5_row("R1"), Counter())
    assert reg["q"] == pytest.approx(0.97) and reg["trades"] is None      # off: the registered price, the in-play one
    on = s2.candidate(_a5_row("A1"), f, a5=True)
    assert on["q"] is None and on["trades"] == PRINTS                     # on: priced from the prints after the join
    assert s2.candidate(_a5_row("A2", quote_at_capture={"last_price": 0.0}), f, a5=True) is not None
    assert s2.candidate(_a5_row("A3", trades_status="empty", trades=[]), f, a5=True)["trades"] == []
    assert s2.candidate(_a5_row("M1", trades_status="skipped_budget", trades=None), f, a5=True) is None
    assert s2.candidate(_a5_row("M2", trades_status="unreadable", trades=None), f, a5=True) is None
    assert s2.candidate(_a5_row("M3", trades_status=None, trades=None), f, a5=True) is None
    assert s2.candidate(_a5_row("W1", settlement_ts="2026-11-23T01:00:00Z"), f, a5=True) is None
    assert f["a5_shaped:soccer|GL"] == 6 and f["a5_missing:soccer|GL"] == 3
    assert f["a5_missing_by_date:2026-11-01"] == 3 and f["a5_missing_status:none"] == 1
    assert f["a5_settled_outside_window"] == 1 and f["no_print_price"] == 0
    cov = s2.a5_coverage(f)
    assert cov["soccer|GL"] == {"shaped": 6, "missing": 3, "missing_share": 0.5, "coverage_limited": True}
    assert cov["mlb|SP-nested"]["missing_share"] is None and not cov["mlb|SP-nested"]["coverage_limited"]
    assert cov["missing_by_settlement_date"] == {"2026-11-01": 3}


def _a5_priced(result="yes", y_ours=1, q_yes=0.30, q_no=0.69, q_any=0.31, p_b=0.36):
    return {"q": q_any, "q_any": q_any, "q_yes": q_yes, "q_no": q_no, "q_yes_15": q_yes, "q_no_15": None,
            "p_a": 0.30, "p_b": p_b, "p_c": None, "y_ours": y_ours, "result": result}


def test_a5_finish_row_prices_each_side_at_its_own_print():
    m, f = 1.0, Counter()
    r = s2.finish_row(_a5_priced(), m, f, a5=True)
    assert r["ret_yes"] == pytest.approx(1 / (0.30 + s2.fee_per_contract(0.30, m)) - 1)
    assert r["ret_no"] == pytest.approx(-1.0)
    assert r["ev_b"] == pytest.approx(s2.ev_yes(0.36, 0.30, m))
    assert r["ev_b_no"] == pytest.approx(s2.ev_yes(0.64, 0.69, m))
    assert r["ret_yes_any"] == pytest.approx(1 / (0.31 + s2.fee_per_contract(0.31, m)) - 1)   # A3's formula at q_any
    assert r["ev_b_no_any"] == pytest.approx(s2.ev_no(0.36, 0.31, m))
    assert r["ret_no_15"] is None and r["ret_yes_15"] == pytest.approx(r["ret_yes"])
    no_only = s2.finish_row(_a5_priced(result="no", y_ours=0, q_yes=None), m, f, a5=True)
    assert no_only["ret_yes"] is None and no_only["ev_b"] is None             # no YES taker pregame: not in that test
    assert no_only["ret_no"] == pytest.approx(1 / (0.69 + s2.fee_per_contract(0.69, m)) - 1)
    bad = s2.finish_row(_a5_priced(result="no", y_ours=1), m, f, a5=True)     # grading disagrees: leaves R2
    assert bad["ret_yes"] is None and bad["ret_no"] is None and f["grading_disagrees_with_kalshi"] == 1
    assert f["a5_side_yes_priced"] == 2 and f["a5_side_no_priced"] == 3


def test_a5_readings_r2_reads_side_prices_and_the_band_table_reads_q_any():
    m = 1.0
    rows = []
    for i in range(240):
        r = s2.finish_row(_a5_priced(result="yes" if i % 3 else "no", y_ours=1 if i % 3 else 0), m, Counter(), a5=True)
        rows.append(dict(r, sport="soccer", cell="GL", game=f"g{i % 30}", volume=1.0))
    out = s2.readings(rows, a5=True)
    cell = out["cells"]["soccer|GL"]
    yes = [r["ret_yes"] for r in rows]
    assert cell["R2_yes"]["n"] == 240 and cell["R2_yes"]["mean"] == pytest.approx(float(np.mean(yes)))
    assert cell["R2_yes_at_q_any"]["mean"] == pytest.approx(float(np.mean([r["ret_yes_any"] for r in rows])))
    assert cell["R2_yes_sensitivity_15min"]["n"] == 240 and cell["R2_no_sensitivity_15min"]["n"] == 0
    band = cell["bands"][">=5"]
    assert band["realised_yes"]["mean"] == pytest.approx(cell["R2_yes_at_q_any"]["mean"])
    assert set(out["holm"]["pvals"]) == {f"{s}|{c}|{side}" for s, c in s2.PASSING for side in ("yes", "no")}
    t = s2.a5_timing([{"sport": "soccer", "cell": "GL", "q_any": 0.3, "mins_before": 10.0, "first_in_play": False,
                       "last_in_play": True},
                      {"sport": "soccer", "cell": "GL", "q_any": None, "mins_before": None, "first_in_play": True,
                       "last_in_play": True}])["soccer|GL"]
    assert t["joined"] == 2 and t["with_pregame_print"] == 1 and t["last_print_in_play_share"] == 1.0
    assert t["first_print_in_play_share"] == 0.5 and t["mins_last_pregame_to_commence"]["median"] == 10.0


def test_main_refuses_a5_without_a_window_and_a_window_without_a5(tmp_path, capsys):
    base = ["--data-root", str(tmp_path), "--out", str(tmp_path / "o.json"), "--cache", str(tmp_path / "c")]
    assert s2.main(base + ["--a5"]) == 2
    assert s2.main(base + ["--a5", "--window-start", "2026-11-22", "--window-end", "2026-10-31"]) == 2
    assert s2.main(base + ["--window-start", "2026-10-31", "--window-end", "2026-11-22"]) == 2
    assert capsys.readouterr().out.count("REFUSING") == 3


def test_main_a5_prices_after_the_join_and_writes_coverage_and_timing(tmp_path, monkeypatch):
    """Reachability, end to end with the heavy Stage 1 machinery stubbed: with --a5 the combo is priced at its
    pregame print (not the in-play `last_price`), a combo with no pregame print is counted, and the report carries
    A5's coverage and timing."""
    monkeypatch.setattr(s2.s1, "WINDOW_START", s2.s1.WINDOW_START)   # main sets these; restore after
    monkeypatch.setattr(s2.s1, "WINDOW_END", s2.s1.WINDOW_END)
    rows = [_a5_row("T1"), _a5_row("T2", trades=[_print("16:00", "yes", 0.9)]),
            _a5_row("T3", trades_status="skipped_budget", trades=None)]
    monkeypatch.setattr(s2, "iter_store", lambda root, a, b: iter(rows))
    monkeypatch.setattr(s2, "fetch_leg_meta", lambda tickers, cache: ({t: {} for t in tickers}, {"gets": 0}))
    monkeypatch.setattr(s2, "read_fee_multiplier", lambda series: (1.0, False, {"fee_multiplier": 1}))
    monkeypatch.setattr(s2, "soccer_code_names", lambda metas: {})

    class _Fetch:
        gets, fail = 0, 0

        def __init__(self, cache):
            pass

    monkeypatch.setattr(s2.s1, "Fetcher", _Fetch)
    game = {"event": "ev1", "game": "ARS-CRY", "date": "2026-11-01", "league": "epl"}
    monkeypatch.setattr(s2, "stage1_games",
                        lambda root, fetch, sport: ([game], {}, {"ev1": {"commence": KICK}}, Counter()))
    monkeypatch.setattr(s2, "parse_leg", lambda sport, ticker, meta: {"market": "x", "line": 2.5, "subject": ""})
    monkeypatch.setattr(s2, "join_game", lambda c, games, bgames, names: (games[0], "ok"))
    seen = []

    def fake_price(c, g, legs, idx, cells_c, funnel):
        seen.append((c["ticker"], c["q"]))
        return {"ticker": c["ticker"], "sport": "soccer", "cell": "GL", "stat_pair": "result~totals", "game": g["game"],
                "date": g["date"], "q": c["q"], "volume": 1.0, "result": "yes", "side_a": "yes", "side_b": "yes",
                "pA": 0.5, "pB": 0.6, "yA": 1, "yB": 1, "rho_b": 0.2, "rho_c": None, "line_a": None, "line_b": 2.5,
                "mkt_a": "h2h", "mkt_b": "totals", "p_a": 0.30, "p_b": 0.36, "p_c": None, "y_ours": 1}

    monkeypatch.setattr(s2, "price_combo", fake_price)
    out = tmp_path / "a5.json"
    rc = s2.main(["--a5", "--window-start", "2026-10-31", "--window-end", "2026-11-22", "--data-root", str(tmp_path),
                  "--out", str(out), "--cache", str(tmp_path / "c")])
    assert rc == 0 and seen == [("T1", pytest.approx(0.31))]            # q_any, never the in-play 0.97
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["a5_window"] == ["2026-10-31", "2026-11-22"] and "A5 41cb8aba" in rep["amendments"]
    assert rep["funnel"]["soccer"]["a5_no_pregame_print"] == 1 and rep["funnel"]["soccer"]["priced"] == 1
    assert rep["a5_coverage"]["soccer|GL"]["missing"] == 1 and rep["a5_coverage"]["soccer|GL"]["shaped"] == 3
    assert rep["cells"]["soccer|GL"]["stamp"] == "COVERAGE-LIMITED"
    assert rep["a5_timing"]["soccer|GL"]["joined"] == 2 and rep["a5_timing"]["soccer|GL"]["with_pregame_print"] == 1
    assert rep["cells"]["soccer|GL"]["R2_yes"]["n"] == 1
    csv_text = out.with_suffix(".combos.csv").read_text(encoding="utf-8")
    assert "q_yes" in csv_text.splitlines()[0] and "0.3" in csv_text
