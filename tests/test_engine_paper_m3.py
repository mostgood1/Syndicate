"""M3, the paper book (lane engine-paper-m3): the registered replay and gate mechanics, on synthetic quotes."""
from __future__ import annotations

import ast
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.shared import engine_paper_m3 as m3  # noqa: E402

T0 = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc).timestamp()
GAME = {"event_id": "E1", "home_team": "Vanderbilt Commodores", "away_team": "Alabama Crimson Tide",
        "commence_time": None}


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _row(ticker, t, ya, na, sub, fs=None, st="active", res=""):
    return {"ts": _iso(t), "t": ticker, "ev": ticker.rsplit("-", 1)[0], "st": st, "ya": f"{ya:.4f}",
            "yb": f"{1 - na:.4f}", "na": f"{na:.4f}", "nb": f"{1 - ya:.4f}", "sub": sub, "fs": fs, "res": res}


def _recorder(tmp_path, rows):
    p = tmp_path / "kalshi.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _index(tmp_path, rows):
    markets = m3.load_recorder(_recorder(tmp_path, rows), "ncaaf")
    return m3.KalshiIndex(markets, "ncaaf", [GAME])


def _cand(t_d, *, market="totals", line=44.5, family="totals", p_prior=0.5, p_decision=0.6, tick=None, event="E1"):
    return m3.Candidate(sport="ncaaf", event_id=event, family=family, market=market, line=line,
                        tick=tick or _iso(t_d), t_d=t_d, p_prior=p_prior, p_decision=p_decision, prior_age_s=20.0)


def _frame_ok(n=25, ticker="KXNCAAFTOTAL-26NOV14ALAVAN-45"):
    """Rows + candidates that pass the frame check: the book prior equals Kalshi's standing mid."""
    rows, cands = [], []
    for k in range(n):
        t = T0 - 3600 + 60 * k
        rows.append(_row(ticker, t, 0.71, 0.31, "Over 44.5 points", 44.5))   # Kalshi's mid 0.70
        cands.append(_cand(t + 5, p_prior=0.70, p_decision=0.70))  # A = 0: frame evidence only, never a bet
    return rows, cands


# ----------------------------------------------------------------------------- recorder and placement


def test_series_sport_kind():
    assert m3.series_sport_kind("KXNCAAFSPREAD") == ("ncaaf", "spreads")
    assert m3.series_sport_kind("KXNBAGAME") == ("nba", "h2h")
    assert m3.series_sport_kind("KXNFLTOTAL") == ("nfl", "totals")
    assert m3.series_sport_kind("KXNHL1PTOTAL") is None
    assert m3.series_sport_kind("KXWNBAGAME") is None


def test_load_recorder_sorts_and_keeps_the_result(tmp_path):
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    rows = [_row(tk, T0 + 20, 0.6, 0.41, "Over 44.5 points", 44.5), _row(tk, T0, 0.5, 0.51, "Over 44.5 points", 44.5),
            _row(tk, T0 + 40, 0.99, 0.02, "Over 44.5 points", 44.5, st="finalized", res="yes"),
            _row("KXNBAGAME-26NOV14BKNMEM-BKN", T0, 0.4, 0.61, "Brooklyn")]
    mk = m3.load_recorder(_recorder(tmp_path, rows), "ncaaf")
    assert list(mk) == [tk]
    m = mk[tk]
    assert m.ts == [T0, T0 + 20, T0 + 40] and m.ya == [0.5, 0.6, 0.99] and m.active == [True, True, False]
    assert m.result == "yes" and m.settled_at() == T0 + 40 and m.kind == "totals" and m.strike == 44.5


def test_placement_frame_by_the_order_paths_resolver(tmp_path):
    rows = [_row("KXNCAAFGAME-26NOV14ALAVAN-ALA", T0, 0.86, 0.15, "Alabama"),
            _row("KXNCAAFGAME-26NOV14ALAVAN-VAN", T0, 0.15, 0.86, "Vanderbilt"),
            _row("KXNCAAFSPREAD-26NOV14ALAVAN-ALA10", T0, 0.63, 0.38, "Alabama wins by over 9.5 points", 9.5),
            _row("KXNCAAFSPREAD-26NOV14ALAVAN-VAN3", T0, 0.1, 0.91, "Vanderbilt wins by over 2.5 points", 2.5),
            _row("KXNCAAFTOTAL-26NOV14ALAVAN-45", T0, 0.5, 0.51, "Over 44.5 points", 44.5)]
    idx = _index(tmp_path, rows)
    assert idx.stats.get("indexed") == 5, idx.stats
    away_spread = idx.place("E1", "spreads", -9.5)      # home covers at -9.5 == NOT (Alabama wins by over 9.5)
    assert away_spread.market.ticker.endswith("-ALA10") and away_spread.orient == -1
    home_spread = idx.place("E1", "spreads", 2.5)
    assert home_spread.market.ticker.endswith("-VAN3") and home_spread.orient == 1
    assert idx.place("E1", "spreads", 9.5) is None       # the 2026-08-08 shape: never the away market at +s
    h2h = idx.place("E1", "h2h", None)
    assert h2h.market.ticker.endswith("-VAN") and h2h.orient == 1   # the home-named moneyline is the one traded
    tot = idx.place("E1", "totals_alt", 44.5)
    assert tot.market.ticker.endswith("-45") and tot.orient == 1
    assert idx.place("E2", "totals", 44.5) is None


def test_unresolvable_title_is_refused_not_guessed(tmp_path):
    rows = [_row("KXNCAAFGAME-26NOV14ALAVAN-ALA", T0, 0.86, 0.15, "Alabama"),
            _row("KXNCAAFGAME-26NOV14ALAVAN-VAN", T0, 0.15, 0.86, "Vanderbilt"),
            _row("KXNCAAFSPREAD-26NOV14ALAVAN-ALA10", T0, 0.63, 0.38, "Alabama wins by over 10.5 points", 9.5)]
    idx = _index(tmp_path, rows)
    assert idx.stats.get("spread_title_or_strike_unreadable") == 1
    assert idx.place("E1", "spreads", -9.5) is None


# ----------------------------------------------------------------------------- entry, mark, arms


def test_entry_is_the_first_quote_after_the_latency_never_one_before(tmp_path):
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    frame_rows, frame_cands = _frame_ok(ticker=tk)
    t_d = T0 + 1000
    rows = frame_rows + [_row(tk, t_d - 5, 0.40, 0.61, "Over 44.5 points", 44.5),    # stale: before the decision
                         _row(tk, t_d + 4, 0.41, 0.60, "Over 44.5 points", 44.5),    # before t_d + 10 s
                         _row(tk, t_d + 12, 0.50, 0.51, "Over 44.5 points", 44.5),   # the entry quote
                         _row(tk, t_d + 330, 0.56, 0.45, "Over 44.5 points", 44.5)]  # the mark
    idx = _index(tmp_path, rows)
    bets, rep = m3.replay(frame_cands + [_cand(t_d, p_prior=0.5, p_decision=0.6)], idx, date="2026-11-14")
    a1 = [b for b in bets if b["arm"] == "A1"]
    assert rep["frame"]["totals"]["verdict"] == "ok"
    assert len(a1) == 1 and a1[0]["ask"] == 0.5 and a1[0]["entry_lag_s"] == 12.0 and a1[0]["side"] == "yes"
    from syndicate.features.shared.venue_fees import kalshi_taker_fee_dollars

    fee = kalshi_taker_fee_dollars(10, 0.5, fee_multiplier=1.0) / 10      # the series has no stored multiplier
    assert fee == pytest.approx(0.0175)
    assert a1[0]["fee"] == pytest.approx(fee) and a1[0]["fee_unresolved"] is True
    assert a1[0]["mark_kind"] == "mid" and a1[0]["mark_value"] == pytest.approx(0.555)
    assert a1[0]["markout"] == pytest.approx(0.555 - 0.5 - fee)


def test_no_quote_in_the_entry_window_is_no_entry(tmp_path):
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    frame_rows, frame_cands = _frame_ok(ticker=tk)
    t_d = T0 + 1000
    idx = _index(tmp_path, frame_rows + [_row(tk, t_d + 71, 0.5, 0.51, "Over 44.5 points", 44.5)])
    st: dict[str, int] = {}
    bets, _ = m3.replay(frame_cands + [_cand(t_d, p_decision=0.7)], idx, date="d", stats=st)
    assert bets == [] and st["A1:no_quote_in_entry_window"] == 1


def test_a_zero_adjustment_places_no_bet_and_a_real_one_does(tmp_path):
    """off != on: with p_decision == p_prior (A = 0) neither arm can bet; with A > 0 A1 does."""
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    frame_rows, frame_cands = _frame_ok(ticker=tk)
    t_d = T0 + 1000
    rows = frame_rows + [_row(tk, t_d + 12, 0.50, 0.51, "Over 44.5 points", 44.5)]
    off, _ = m3.replay(frame_cands + [_cand(t_d, p_prior=0.6, p_decision=0.6)], _index(tmp_path, rows), date="d")
    on, _ = m3.replay(frame_cands + [_cand(t_d, p_prior=0.6, p_decision=0.7)], _index(tmp_path, rows), date="d")
    assert off == [] and [b["arm"] for b in on].count("A1") == 1


def test_a1_bets_the_adjustment_on_kalshis_mid_and_a2_the_raw_probability(tmp_path):
    """A book-vs-Kalshi gap alone (p_prior far from the mid, tiny A) is an A2 bet and not an A1 bet."""
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    frame_rows, frame_cands = _frame_ok(ticker=tk)
    t_d = T0 + 1000
    rows = frame_rows + [_row(tk, t_d + 12, 0.50, 0.51, "Over 44.5 points", 44.5)]
    bets, _ = m3.replay(frame_cands + [_cand(t_d, p_prior=0.62, p_decision=0.63)], _index(tmp_path, rows), date="d")
    assert [b["arm"] for b in bets] == ["A2"]


def test_the_other_side_is_bought_when_the_learner_points_down(tmp_path):
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    frame_rows, frame_cands = _frame_ok(ticker=tk)
    t_d = T0 + 1000
    rows = frame_rows + [_row(tk, t_d + 12, 0.50, 0.51, "Over 44.5 points", 44.5),
                         _row(tk, t_d + 200, 0.0001, 0.0001, "Over 44.5 points", 44.5, st="closed", res="no")]
    bets, _ = m3.replay(frame_cands + [_cand(t_d, p_prior=0.5, p_decision=0.4)], _index(tmp_path, rows), date="d")
    a1 = [b for b in bets if b["arm"] == "A1"][0]
    assert a1["side"] == "no" and a1["our_side"] is False and a1["ask"] == 0.51
    assert a1["mark_kind"] == "settled" and a1["mark_value"] == 1.0 and a1["payout"] == 1.0
    assert a1["roi"] == pytest.approx((1.0 - a1["cost"]) / a1["cost"])


def test_one_entry_per_game_and_market_and_the_best_edge_at_one_instant(tmp_path):
    t45, t48 = "KXNCAAFTOTAL-26NOV14ALAVAN-45", "KXNCAAFTOTAL-26NOV14ALAVAN-48"
    frame_rows, frame_cands = _frame_ok(ticker=t45)
    t1, t2 = T0 + 1000, T0 + 1200
    rows = frame_rows + [_row(t45, t1 + 12, 0.50, 0.51, "Over 44.5 points", 44.5),
                         _row(t48, t1 + 12, 0.40, 0.61, "Over 47.5 points", 47.5),
                         _row(t45, t2 + 12, 0.50, 0.51, "Over 44.5 points", 44.5),
                         _row(t48, t2 + 12, 0.40, 0.61, "Over 47.5 points", 47.5)]
    tick1 = _iso(t1)
    cands = frame_cands + [_cand(t1, line=44.5, p_prior=0.5, p_decision=0.62, tick=tick1),
                           _cand(t1, line=47.5, p_prior=0.4, p_decision=0.58, tick=tick1),
                           _cand(t2, line=44.5, p_prior=0.5, p_decision=0.62),
                           _cand(t2, line=47.5, p_prior=0.4, p_decision=0.58)]
    bets, _ = m3.replay(cands, _index(tmp_path, rows), date="d")
    a1 = [b for b in bets if b["arm"] == "A1"]
    assert [b["ticker"] for b in a1] == [t48, t45]       # instant 1: the larger edge (47.5); instant 2: the other one


def test_an_ask_outside_the_band_is_not_taken(tmp_path):
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    frame_rows, frame_cands = _frame_ok(ticker=tk)
    t_d = T0 + 1000
    rows = frame_rows + [_row(tk, t_d + 12, 0.03, 0.98, "Over 44.5 points", 44.5)]
    st: dict[str, int] = {}
    bets, _ = m3.replay(frame_cands + [_cand(t_d, p_prior=0.03, p_decision=0.2)], _index(tmp_path, rows),
                        date="d", stats=st)
    assert bets == [] and st["A1:below_floor"] == 1


def test_unmarked_when_no_quote_lands_in_the_window(tmp_path):
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    frame_rows, frame_cands = _frame_ok(ticker=tk)
    t_d = T0 + 1000
    rows = frame_rows + [_row(tk, t_d + 12, 0.50, 0.51, "Over 44.5 points", 44.5),
                         _row(tk, t_d + 12 + 430, 0.6, 0.41, "Over 44.5 points", 44.5)]
    bets, _ = m3.replay(frame_cands + [_cand(t_d, p_decision=0.7)], _index(tmp_path, rows), date="d")
    a1 = [b for b in bets if b["arm"] == "A1"][0]
    assert a1["mark_kind"] == "unmarked" and a1["markout"] is None


def test_frame_check_refuses_a_flipped_family_and_an_unverified_one(tmp_path):
    tk = "KXNCAAFTOTAL-26NOV14ALAVAN-45"
    rows, cands = [], []
    for k in range(25):
        t = T0 + 60 * k
        rows.append(_row(tk, t, 0.71, 0.31, "Over 44.5 points", 44.5))     # Kalshi says 0.70 over
        cands.append(_cand(t + 5, p_prior=0.30, p_decision=0.45))          # books say 0.30: the flipped frame
    idx = _index(tmp_path, rows)
    st: dict[str, int] = {}
    bets, rep = m3.replay(cands, idx, date="d", stats=st)
    assert rep["frame"]["totals"]["verdict"] == "FLIPPED" and bets == []
    few = m3.frame_check(cands[:5], idx)
    assert few["totals"]["verdict"] == "unverified"


# ----------------------------------------------------------------------------- the M2 line and reproduction


def test_pass_strata_reads_only_a_pass_line():
    line = ("REHEARSAL M2_VERDICT PASS judged=12 pass=3 [ncaaf|spreads|live|a<=60(outcome), "
            "ncaaf|totals|live|a<=60(outcome), nba|h2h|pregame(close)] excluded_reproduction=[]")
    assert m3.pass_strata(line) == ({"ncaaf|spreads", "ncaaf|totals"}, {"nba|h2h"})
    with pytest.raises(ValueError):
        m3.pass_strata("M2_VERDICT FAIL judged=12 pass=0")
    with pytest.raises(ValueError):
        m3.pass_strata("M2_VERDICT PASS judged=1 pass=1 [ncaaf|totals|live|a60-180(outcome)]")


def test_reproduction_attribution():
    lines = ["   JOIN ncaab half_point checked=9 mismatched=4", "   CHECKLIST nba pregame ok=False alarms=2",
             "RESULT date=2026-11-25 opinions=10 alarms_plus_mismatches=6 exit=1"]
    total, fails, attributed = m3.reproduction(lines, "2026-11-25")
    assert (total, attributed) == (6, 6) and fails == {("ncaab", "live"): {"JOIN": 4}, ("nba", "pregame"): {"CHECKLIST": 2}}
    assert m3.reproduction(lines, "2026-11-26")[0] is None
    assert m3.reproduction(["RESULT date=2026-11-25 opinions=1 alarms_plus_mismatches=0 exit=1"], "2026-11-25")[0] is None


# ----------------------------------------------------------------------------- the gate


def _bets(values, games, arm="A1", stratum="ncaaf|totals|live|a<=60", roi=None):
    return [{"arm": arm, "game": g, "markout": v, "stratum": stratum, "roi": (roi if roi is not None else v)}
            for v, g in zip(values, games)]


def test_clustered_z_by_hand():
    s = m3.clustered_z([1.0, 3.0, -1.0, 1.0], ["a", "a", "b", "b"])
    # mean 1; game sums of residuals: a = 0 + 2 = 2, b = -2 + 0 = -2; SE = sqrt(8)/4*sqrt(2) = 1
    assert s["mean"] == 1.0 and s["se"] == pytest.approx(1.0) and s["z"] == pytest.approx(1.0)


def test_due_look_in_order_and_at_the_calendar_stop():
    assert m3.due_look({"bets": 399, "games": 150}, [], "2026-12-01") is None
    assert m3.due_look({"bets": 900, "games": 250}, [], "2026-12-01") == "L1"
    assert m3.due_look({"bets": 900, "games": 250}, ["L1"], "2026-12-01") == "L2"
    assert m3.due_look({"bets": 50, "games": 10}, [], "2027-01-31") == "L3"
    assert m3.due_look({"bets": 50, "games": 10}, ["L3"], "2027-02-01") is None


def test_look_verdicts():
    games = [f"g{k // 4}" for k in range(400)]                      # 100 games, 4 bets each
    up = [0.05 + (0.001 if k % 2 else -0.001) for k in range(400)]
    res = m3.look(_bets(up, games), "L1")
    assert res["verdict"] == "PASS" and res["counts"] == {"bets": 400, "games": 100, "unmarked": 0}
    down = [-v for v in up]
    assert m3.look(_bets(down, games), "L1")["verdict"] == "FAIL"
    noisy = [0.3 * math.sin(1.3 * k) for k in range(400)]           # mean ~0, varies across games
    assert m3.look(_bets(noisy, games), "L1")["verdict"] == "CONTINUE"
    assert m3.look(_bets(noisy, games), "L3")["verdict"] == "FAIL"
    contra = _bets(up, games, roi=-0.5)
    for k, b in enumerate(contra):
        b["roi"] = -0.5 + (0.01 if k % 2 else -0.01)
    assert m3.look(contra, "L1")["verdict"] == "CONTRADICTION"
    unmarked = _bets(up, games)
    for b in unmarked[:41]:
        b["markout"] = None
    assert m3.look(unmarked, "L1")["verdict"] == "NOT_A_VERDICT"


def test_harm_per_stratum():
    games = [f"g{k // 4}" for k in range(400)]
    good = _bets([0.05 + (0.001 if k % 2 else -0.001) for k in range(400)], games)
    bad = _bets([-0.05 + (0.001 if k % 2 else -0.001) for k in range(160)], [f"h{k // 4}" for k in range(160)],
                stratum="ncaaf|spreads|live|a<=60")
    res = m3.look(good + bad, "L1")
    assert res["harm"] == ["ncaaf|spreads|live|a<=60"]


# ----------------------------------------------------------------------------- the script's fit file


def test_fit_round_trip_and_check(tmp_path):
    import numpy as np

    from scripts import engine_paper_m3 as cli
    from syndicate.features.shared import engine_learner as el

    rng = np.random.default_rng(7)
    exs = []
    for k in range(400):
        d = float(rng.normal())
        y = 1.0 if rng.random() < 1.0 / (1.0 + math.exp(-0.8 * d)) else 0.0
        exs.append(el.Example(key=f"l{k}|t", line_key=f"l{k}", cluster=f"g{k // 4}", date="2026-11-10",
                              cell=("ncaaf", "totals", "totals", "full", "live", "0-25", "a<=60"),
                              logit_prior=0.0, deltas={"live_resim": d}, y=y))
    model = el.fit(exs)
    table = el.weight_table(model, exs)
    (tmp_path / "read.json").write_text(json.dumps({"weights": table}), encoding="utf-8")
    (tmp_path / "rerun.json").write_text(json.dumps({"weights": table}), encoding="utf-8")
    cli.save_fit_file(model, tmp_path / "fit.npz", {"learner": el.LEARNER_VERSION})
    loaded, _meta = cli.load_fit_file(tmp_path / "fit.npz")
    assert el.p_decision(exs[0], loaded) == el.p_decision(exs[0], model)
    args = cli.argparse.Namespace(fit=str(tmp_path / "fit.npz"), read_json=str(tmp_path / "read.json"),
                                  rerun_json=str(tmp_path / "rerun.json"), rehearse=False)
    assert cli.cmd_check_fit(args) == 0
    table[0]["w"] += 0.0001
    (tmp_path / "read.json").write_text(json.dumps({"weights": table}), encoding="utf-8")
    assert cli.cmd_check_fit(args) == 2


def test_the_module_imports_no_order_module_and_names_no_opinion_producer():
    src = (REPO / "syndicate/features/shared/engine_paper_m3.py").read_text(encoding="utf-8")
    assert "engine_" + "experts" not in src
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    app = {m for m in imported if m.startswith(("syndicate", "pipeline"))}
    assert app == {"syndicate.features.shared", "syndicate.features.shared.kalshi_board_join",
                   "syndicate.features.shared.venue_fees"}, app
