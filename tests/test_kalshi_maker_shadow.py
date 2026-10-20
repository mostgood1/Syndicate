"""PAPER Kalshi maker shadow (lane kalshi-maker-shadow-paper).

Pre-registration: .syndicate/findings_2026-10-20_kalshi_maker_shadow_preregistration.md.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

from syndicate.features.shared import kalshi_maker_shadow as ms

REPO = Path(__file__).resolve().parent.parent
SHADOW_FILES = (
    REPO / "syndicate/features/shared/kalshi_maker_shadow.py",
    REPO / "scripts/run_kalshi_maker_shadow.py",
    REPO / "scripts/evaluate_kalshi_maker_shadow.py",
)
T0 = 1_800_000_000.0  # an arbitrary epoch; commence below is T0 + 12h
COMMENCE = T0 + 12 * 3600


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ NO ORDER PATH (the lane's hard rule)
ALLOWED_IMPORTS = {
    "__future__", "argparse", "ast", "bisect", "collections", "datetime", "gzip", "json", "math", "os",
    "random", "re", "sys", "time", "typing", "pathlib", "urllib", "urllib.error", "urllib.parse",
    "urllib.request", "fcntl",
    "syndicate.features.shared.kalshi_maker_shadow", "syndicate.features.shared",
    "syndicate.features.shared.kalshi_board_join",
}


@pytest.mark.parametrize("path", SHADOW_FILES, ids=lambda p: p.name)
def test_the_shadow_imports_nothing_that_could_place_an_order(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
            # `from syndicate.features.shared import X` is allowed only for the shadow and the join
            if node.module == "syndicate.features.shared":
                assert {a.name for a in node.names} <= {"kalshi_maker_shadow", "kalshi_board_join"}, ast.dump(node)
                continue
        else:
            continue
        for name in names:
            assert name in ALLOWED_IMPORTS or name.split(".")[0] in {"urllib"}, f"{path.name}: import {name}"


@pytest.mark.parametrize("path", SHADOW_FILES, ids=lambda p: p.name)
def test_the_shadow_only_ever_sends_get(path):
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            assert value not in ("POST", "PUT", "DELETE", "PATCH"), f"{path.name}: HTTP verb {value}"
            assert "/portfolio" not in value and "KALSHI-ACCESS" not in value.upper(), f"{path.name}: {value!r}"
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "Request":
            kw = {k.arg: k.value for k in node.keywords}
            assert "data" not in kw and isinstance(kw.get("method"), ast.Constant) and kw["method"].value == "GET"
    assert "urlopen(" not in text or path.name == "kalshi_maker_shadow.py", "only public_get_json may open URLs"


# ------------------------------------------------------------------ the bid rule
def test_bid_is_the_minimum_of_the_three_terms_and_says_whether_it_improved():
    # bid + 1c binds: fair 0.60 -> floor(0.588)=0.58; ask 0.55 -> 0.54; bid 0.50 -> 0.51
    assert ms.maker_bid(0.60, 0.55, 0.50) == (0.51, True)
    # the edge term binds: fair 0.50 -> floor(0.4901)=0.49; bid 0.52 -> 0.53; ask 0.56 -> 0.55
    assert ms.maker_bid(0.50, 0.56, 0.52) == (0.49, False)
    # ask - 1c binds
    assert ms.maker_bid(0.70, 0.45, 0.43) == (0.44, True)
    # absent bid counts as 0 -> b = 0.01 -> under the 0.03 floor
    assert ms.maker_bid(0.60, 0.55, None) is None
    assert ms.maker_bid(0.04, 0.10, 0.02) == (0.03, True)
    assert ms.maker_bid(None, 0.5, 0.4) is None


def test_every_placed_bid_clears_the_two_percent_floor():
    for fair in [i / 100 for i in range(5, 99)]:
        for bid in [i / 100 for i in range(1, 99, 7)]:
            placed = ms.maker_bid(fair, min(0.99, bid + 0.03), bid)
            if placed:
                b, _ = placed
                assert fair / b - 1 >= 0.02 - 1e-9 and 0.03 <= b <= 0.97


def _pts(*rows):
    return ms.sorted_points([{"ts": ms.iso(t), "yes": ya, "yes_bid": yb, "no": na, "no_bid": nb}
                             for t, ya, yb, na, nb in rows])


def test_placement_takes_the_first_passing_instant_inside_the_window_only():
    pts = _pts(
        (COMMENCE - 30 * 3600, 0.40, 0.38, 0.62, 0.60),  # before the 24h window
        (COMMENCE - 20 * 3600, 0.60, 0.58, 0.42, 0.40),  # inside: b = min(.59, floor(.55/1.02)=.53, .59) = .53
        (COMMENCE - 5 * 60, 0.40, 0.30, 0.62, 0.60),  # after commence - 10m
    )
    order, scanned, n = ms.scan_for_placement(pts, "yes", COMMENCE, lambda t: (0.55, 3), after=None, now=COMMENCE)
    assert n == 1 and order["t"] == COMMENCE - 20 * 3600 and order["b"] == 0.53 and not order["improved"]
    assert scanned == COMMENCE - 20 * 3600 and order["kalshi_mid"] == pytest.approx(0.59)


def test_placement_scan_is_incremental_and_never_reads_the_future():
    pts = _pts((COMMENCE - 10 * 3600, 0.50, 0.40, 0.52, 0.48), (COMMENCE - 2 * 3600, 0.50, 0.40, 0.52, 0.48))
    fair = lambda t: (None, 1)  # noqa: E731 -- one book: no fair, never passes
    order, scanned, n = ms.scan_for_placement(pts, "yes", COMMENCE, fair, after=None, now=COMMENCE - 5 * 3600)
    assert order is None and n == 1 and scanned == COMMENCE - 10 * 3600
    order, scanned2, n2 = ms.scan_for_placement(pts, "yes", COMMENCE, fair, after=scanned, now=COMMENCE)
    assert n2 == 1 and scanned2 == COMMENCE - 2 * 3600


def test_fill_a_needs_an_ask_at_or_below_the_bid_before_commence():
    pts = _pts((T0 + 100, 0.55, 0.50, 0.47, 0.45), (T0 + 200, 0.52, 0.50, 0.50, 0.48),
               (COMMENCE + 10, 0.40, 0.30, 0.62, 0.60))
    assert ms.fill_by_asks(pts, "yes", T0, 0.52, COMMENCE, after=None) == (T0 + 200, T0 + 200)
    assert ms.fill_by_asks(pts, "yes", T0, 0.51, COMMENCE, after=None) == (None, T0 + 200)  # in-play ask ignored
    assert ms.fill_by_asks(pts, "no", T0, 0.47, COMMENCE, after=None)[0] == T0 + 100


def test_fill_b_needs_a_taker_selling_our_leg_and_strict_when_joining_the_queue():
    prints = [{"t": T0 + 10, "taker_side": "yes", "yes": 0.50, "no": 0.50},  # taker BOUGHT yes: not ours
              {"t": T0 + 20, "taker_side": "no", "yes": 0.50, "no": 0.50},
              {"t": T0 + 30, "taker_side": "no", "yes": 0.49, "no": 0.51}]
    assert ms.fill_by_prints(prints, "yes", T0, 0.50, True, COMMENCE) == T0 + 20
    assert ms.fill_by_prints(prints, "yes", T0, 0.50, False, COMMENCE) == T0 + 30  # joined: strictly below
    assert ms.fill_by_prints(prints, "yes", T0 + 25, 0.48, True, COMMENCE) is None
    assert ms.fill_by_prints(prints, "no", T0, 0.50, True, COMMENCE) == T0 + 10  # a taker BUYING yes sells us no
    assert ms.fill_by_prints(prints, "no", T0, 0.49, True, COMMENCE) is None
    late = [{"t": COMMENCE + 1, "taker_side": "no", "yes": 0.10, "no": 0.90}]
    assert ms.fill_by_prints(late, "yes", T0, 0.50, True, COMMENCE) is None  # cancelled at commence


# ------------------------------------------------------------------ fair
def test_consensus_fair_devigs_per_book_needs_two_books_and_carries_forward():
    key = ("ev", "totals", "", 2.5, "over", "full")
    other = ms.complements(key)[0]
    book = ms.QuoteBook()
    for name, (o, u) in {"a": (0.55, 0.50), "b": (0.52, 0.52)}.items():
        book.add(key, name, T0, o)
        book.add(other, name, T0, u)
    book.add(key, "c", T0, 0.9)  # one-sided: excluded
    book.finish()
    fair, n = book.fair(key, T0 + 3600)
    assert n == 2 and fair == pytest.approx((0.55 / 1.05 + 0.5) / 2)
    assert book.fair(key, T0 - 1) == (None, 0)
    spread = ("ev", "spreads", "", -0.5, "home", "full")
    assert ms.complements(spread) == [("ev", "spreads", "", 0.5, "away", "full")]


# ------------------------------------------------------------------ scope
def test_cells_are_the_pre_registered_three():
    assert ms.cell_for("soccer", "totals", "full") == "soccer:totals"
    assert ms.cell_for("soccer", "spreads", "h1") == "soccer:spreads"
    assert ms.cell_for("soccer", "h2h", "full") is None
    assert ms.cell_for("ncaaf", "totals", "h1") == "ncaaf:segment_totals"
    assert ms.cell_for("ncaaf", "totals", "full") is None
    assert ms.cell_for("ncaaf", "spreads", "q1") is None
    assert ms.cell_for("mlb", "totals", "first5") is None


# ------------------------------------------------------------------ population and the stop rule
def _record(i, *, cell="soccer:totals", series="KXSERIEATOTAL", result="yes", leg="yes", b=0.45, fair_close=0.45,
            fill_b=True, fill_a=False, late=False, void=None, title="Serie A Total", mid=0.45, fair=0.47, event=None):
    return {"ticker": f"T{i}", "leg": leg, "series": series, "series_title": title, "cell": cell,
            "event_id": event or f"ev{i}",
            "order": {"t": T0, "b": b, "fair": fair, "kalshi_mid": mid, "late_observed": late, "improved": True},
            "closed": {"void_reason": void, "fair_close": fair_close, "fill_b_status": "ok",
                       "fill_b_t": T0 + 5 if fill_b else None, "fill_a_t": T0 + 5 if fill_a else None,
                       "fair_at_fill_b": 0.44 if fill_b else None},
            "settlement": {"result": result}}


def test_population_excludes_late_void_unsettled_and_mispaired():
    recs = [_record(1), _record(2, late=True), _record(3, void="commence_revised"), _record(4, result=""),
            _record(5, series="KXSERIEAWTOTAL", title="Serie A Femminile Total")]
    recs += [_record(10 + i, series="KXBAD", mid=0.20, fair=0.60) for i in range(5)]
    rows, pop = ms.counted_population(recs)
    assert [r["ticker"] for r in rows] == ["T1"]
    assert pop["excluded"] == {"late_observed": 1, "commence_revised": 1, "unsettled_or_void_result": 1,
                               "mispaired_series": 6}
    assert set(pop["mispaired_series"]) == {"KXSERIEAWTOTAL", "KXBAD"}
    assert rows[0]["win"] == 1.0


def _stats_for(n_events, win_rate, fair_close=0.45, b=0.45):
    # spread the wins evenly, so any prefix has the stated rate
    recs = [_record(i, result="yes" if int((i + 1) * win_rate) > int(i * win_rate) else "no", fair_close=fair_close,
                    b=b) for i in range(n_events)]
    rows, _ = ms.counted_population(recs)
    return ms.cell_stats(rows, "B")


def test_judge_look_go_nogo_continue():
    strong = _stats_for(600, 0.60)  # +15pp vs close, ROI +33%
    assert ms.judge_look(strong, 0.99, final=False) == "GO"
    weak = _stats_for(600, 0.30)  # -15pp
    assert ms.judge_look(weak, 0.99, final=False) == "NO-GO"
    flat = _stats_for(200, 0.46)  # about the close: neither bar
    assert ms.judge_look(flat, 0.99, final=False) == "CONTINUE"
    assert ms.judge_look(flat, 0.95, final=True) == "NO-GO"


def test_go_needs_fifty_events():
    recs = [_record(i, result="yes" if i % 10 < 7 else "no", event=f"ev{i % 40}") for i in range(400)]
    rows, _ = ms.counted_population(recs)
    stats = ms.cell_stats(rows, "B")
    assert stats["events_filled"] == 40
    assert ms.judge_look(stats, 0.95, final=False) == "CONTINUE"


def test_looks_are_taken_once_frozen_and_final_at_600():
    flat = _stats_for(250, 0.46)
    looks = ms.take_looks({}, {"soccer:totals": flat}, "2026-11-10")
    assert looks["soccer:totals"]["looks"][0]["threshold"] == 200
    assert looks["soccer:totals"]["status"] == "CONTINUE"
    again = ms.take_looks(json.loads(json.dumps(looks)), {"soccer:totals": flat}, "2026-11-11")
    assert len(again["soccer:totals"]["looks"]) == 1  # 200 is not re-taken
    final = ms.take_looks(again, {"soccer:totals": _stats_for(620, 0.46)}, "2026-12-20")
    assert [lk["threshold"] for lk in final["soccer:totals"]["looks"]] == [200, 600]
    assert final["soccer:totals"]["status"] == "NO-GO"
    assert final["soccer:spreads"]["looks"] == []


def test_calendar_stop_marks_a_thin_cell_insufficient():
    looks = ms.take_looks({}, {"ncaaf:segment_totals": _stats_for(80, 0.6)}, "2027-01-31")
    assert looks["ncaaf:segment_totals"]["status"] == "INSUFFICIENT"
    assert looks["soccer:totals"]["status"] == "INSUFFICIENT"


# ------------------------------------------------------------------ one run, end to end, with fakes
def _write_inputs(root: Path, now: float, points):
    date = ms.iso(COMMENCE)[:10]
    vo = root / "reports/intelligence/venue_odds"
    vo.mkdir(parents=True)
    (vo / f"kalshi__soccer__{date.replace('-', '_')}.json").write_text(json.dumps({"markets": {
        "KXSERIEATOTAL-X-2": {"market": "totals", "line": 2.5, "points": points},
        "KXSERIEAGAME-X-TIE": {"market": "h2h", "points": points}}}), encoding="utf-8")
    bq = root / "soccer_source/tracking/book_quotes"
    bq.mkdir(parents=True)
    rows = []
    for book, (o, u) in {"a": (-120, 100), "b": (-118, -102), "kalshi": (-500, 300)}.items():
        for sel, price in (("over", o), ("under", u)):
            rows.append({"captured_at": ms.iso(T0 - 3600), "kind": "game", "event_id": "ev1", "market": "totals",
                         "segment": "full", "selection": sel, "line": 2.5, "price": price, "bookmaker": book,
                         "commence_time": ms.iso(COMMENCE), "home_team": "H", "away_team": "A"})
    rows.append({"kind": "prop", "event_id": "ev1", "market": "player_shots"})
    (bq / f"{date}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return date


def _fake_join(sport, kal, board):
    key = ("ev1", "totals", "", 2.5, "over", "full")
    legs = {}
    for date, markets in kal.items():
        if "KXSERIEATOTAL-X-2" in markets:
            legs[("KXSERIEATOTAL-X-2", "yes")] = (key, {"ticker": "KXSERIEATOTAL-X-2"}, date)
    return legs, {}


class _FakeKalshi:
    def __init__(self):
        self.calls = []

    def __call__(self, path, params=None):
        self.calls.append(path)
        if path.startswith("/series/"):
            return {"series": {"fee_type": "quadratic", "fee_multiplier": 1, "title": "Serie A Total"}}
        if path == "/markets/trades":
            return {"trades": [{"created_time": ms.iso(COMMENCE - 3600), "taker_side": "no",
                                "yes_price_dollars": "0.50", "no_price_dollars": "0.50", "count_fp": "3"}],
                    "cursor": None}
        if path.startswith("/markets/"):
            return {"market": {"result": "yes", "status": "finalized"}}
        return None


def test_run_once_places_closes_and_settles_a_paper_order(tmp_path, monkeypatch):
    runner = _load_script("run_kalshi_maker_shadow")
    monkeypatch.setattr(ms.time, "sleep", lambda s: None)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    points = [{"ts": ms.iso(COMMENCE - 6 * 3600), "yes": 0.53, "yes_bid": 0.49, "no": 0.51, "no_bid": 0.47}]
    date = _write_inputs(tmp_path, T0, points)
    fake = _FakeKalshi()
    quiet = lambda *a, **k: None  # noqa: E731
    # run 1: before the decision instant -- nothing placed yet
    runner.run_once(tmp_path, COMMENCE - 8 * 3600, sports=("soccer",), days_back=0, get=fake, join=_fake_join, log=quiet)
    doc = json.loads(ms.orders_path(tmp_path, date).read_text())
    rec = doc["legs"]["KXSERIEATOTAL-X-2|yes"]
    assert rec["order"] is None and rec["instants_scanned"] == 0 and rec["cell"] == "soccer:totals"
    # run 2: after the point -- the order is placed and frozen. fair over = mean(0.5455/1.0455.., ...)
    runner.run_once(tmp_path, COMMENCE - 5 * 3600, sports=("soccer",), days_back=0, get=fake, join=_fake_join, log=quiet)
    rec = json.loads(ms.orders_path(tmp_path, date).read_text())["legs"]["KXSERIEATOTAL-X-2|yes"]
    order = rec["order"]
    assert order["b"] == 0.50 and order["improved"] and order["late_observed"] is False
    assert order["books"] == 2  # the exchange row is not a book
    assert rec["closed"] is None
    # run 3: after commence + 15 min -- closed with fill B from the print, then settled
    summary = runner.run_once(tmp_path, COMMENCE + 3600, sports=("soccer",), days_back=0, get=fake,
                              join=_fake_join, log=quiet)
    rec = json.loads(ms.orders_path(tmp_path, date).read_text())["legs"]["KXSERIEATOTAL-X-2|yes"]
    assert rec["order"]["b"] == 0.50  # never re-priced
    assert rec["closed"]["fill_b_t"] == COMMENCE - 3600 and rec["closed"]["fill_b_status"] == "ok"
    assert rec["closed"]["void_reason"] is None and rec["closed"]["fair_close"] == pytest.approx(order["fair"])
    assert rec["settlement"]["result"] == "yes" and summary["settlement"]["settled"] == 1
    assert (ms.store_dir(tmp_path) / "runs.jsonl").read_text().count("\n") == 3
    assert sum(1 for c in fake.calls if c.startswith("/series/")) == 1  # fee cached
    # and the evaluation reads it back as one counted, B-filled, winning order
    evaluator = _load_script("evaluate_kalshi_maker_shadow")
    report = evaluator.evaluate(tmp_path, COMMENCE + 2 * 86400)
    cell = report["per_cell"]["soccer:totals"]["B"]
    assert report["counted_orders"] == 1 and cell["filled"] == 1
    assert cell["filled_roi"]["mean"] == pytest.approx(1 / 0.50 - 1)
    assert report["looks"]["soccer:totals"]["status"] == "CONTINUE"


def test_a_non_quadratic_series_is_never_shadowed(tmp_path, monkeypatch):
    runner = _load_script("run_kalshi_maker_shadow")
    points = [{"ts": ms.iso(COMMENCE - 6 * 3600), "yes": 0.53, "yes_bid": 0.49, "no": 0.51, "no_bid": 0.47}]
    date = _write_inputs(tmp_path, T0, points)

    def maker_fee_series(path, params=None):
        return {"series": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1, "title": "x"}}

    summary = runner.run_once(tmp_path, COMMENCE - 5 * 3600, sports=("soccer",), days_back=0, get=maker_fee_series,
                              join=_fake_join, log=lambda *a, **k: None)
    assert summary["sports"]["soccer"]["skipped_not_quadratic"] == 1
    assert not ms.orders_path(tmp_path, date).exists() or not json.loads(
        ms.orders_path(tmp_path, date).read_text())["legs"]
