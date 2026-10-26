"""Decision policy v1 PAPER book (lane `decision-policy-paper`, #736 Phase 2): booking, grading, the gate.

Hermetic: every file is under tmp_path. Records go through the REAL `decision_record.build_record` and
`write_records`, and booking through the REAL job entrypoint, so `off != paper` is tested where it runs.
"""

from __future__ import annotations

import ast
import gzip
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from syndicate.features.shared import decision_policy_paper as paper
from syndicate.features.shared import decision_policy_v1 as dp
from syndicate.features.shared import decision_record as dr
from syndicate.features.shared import syndicate_fair_runtime as sfr

REPO = Path(__file__).resolve().parents[1]
PARAMS = dp.Params(z_s1=1.0, z_s2=0.7, r2_s2={"game": 0.002, "game|totals": 0.0015, "game|h2h": 0.003},
                   loaded=True, version="test")
OUR_FILES = ("syndicate/features/shared/decision_policy_v1.py", "syndicate/features/shared/decision_policy_paper.py",
             "scripts/run_decision_policy_paper.py", "scripts/evaluate_decision_policy_paper.py",
             "scripts/fit_decision_policy_z.py")
ORDER_MODULES = ("kalshi_orders", "polymarket_us_orders", "execute_portfolio", "execution_ledger", "portfolio_commit",
                 "kalshi_maker_pilot", "inplay_entries_live", "execution_exits")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(start: float, **over):
    row = {
        "sport": "nba", "event_id": "ev1", "kind": "game", "market": "totals", "segment": "full",
        "player_name": None, "side": "over", "line": 220.5, "commence_time": _iso(start),
        "home_team": "Home", "away_team": "Away", "game_state": "pregame", "suggested": False,
        "suggested_reasons": [], "ev_pct": 1.0, "model_edge_pct": 0.0,
        "quote": {"fair_probability": 0.50, "fair_devig_method": "shin", "fair_method": "consensus",
                  "books_quoting": 8, "book_age_seconds": 30.0, "quote_seen_age_seconds": 5.0,
                  "suspect_stale": False, "bookmaker": "draftkings", "price": 105,
                  "book_prices": {"draftkings": 105, "kalshi": 115}},
    }
    for key, value in over.items():
        if key == "quote":
            row["quote"] = {**row["quote"], **value}
        else:
            row[key] = value
    return row


def _write_build(root: Path, rows, *, written_at: float | None = None, build_id: str = "b1",
                 selected_date: str | None = None) -> Path:
    now = time.time() if written_at is None else written_at
    sel = selected_date or sfr._central_date(now)
    ctx = dr.RecordContext(selected_date=sel, now=datetime.fromtimestamp(now, tz=timezone.utc))
    records = dr.build_records(rows, ctx)
    path = dr.write_records(sel, records, build_id=build_id, root=root)
    if written_at is not None:  # the writer stamps wall time; a test pins the decision instant
        doc = dr.read_records_file(path)
        doc["written_at"] = _iso(written_at)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(doc, fh)
    return path


def _write_grid(root: Path, start: float, observed: float, *, sport="nba", market="totals", line=220.5,
                sides=("over", "under"), books=None, selected_date: str | None = None) -> None:
    books = books or {"draftkings": (-110, -110), "fanduel": (-105, -115), "betmgm": (-115, -105)}
    cells = {b: {sides[0]: {"price": p[0], "observed_at": _iso(observed)},
                 sides[1]: {"price": p[1], "observed_at": _iso(observed)}} for b, p in books.items()}
    row = {"kind": "game", "event_id": "ev1", "market": market, "segment": "full", "player_name": None, "line": line,
           "sides": list(sides), "commence_time": _iso(start), "updated_at": _iso(observed), "cells": cells}
    sel = selected_date or sfr._central_date(observed)
    path = root / f"{sport}_source" / "data" / "book_grid" / f"book_grid_{sel}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": [row]}), encoding="utf-8")


@pytest.fixture
def params(monkeypatch):
    monkeypatch.setattr(dp, "load_params", lambda path=None: PARAMS)
    return PARAMS


def _run_job(argv):
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_decision_policy_paper", REPO / "scripts" / "run_decision_policy_paper.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(argv)


# --------------------------------------------------------------------------- the switch + reachability


def test_absent_switch_is_off(monkeypatch):
    monkeypatch.delenv(paper.MODE_ENV, raising=False)
    assert paper.mode() == paper.MODE_OFF
    for value in ("", "shadow", "nope", "off"):
        monkeypatch.setenv(paper.MODE_ENV, value)
        assert paper.mode() == paper.MODE_OFF
    monkeypatch.setenv(paper.MODE_ENV, "paper")
    assert paper.mode() == paper.MODE_PAPER


def test_off_is_not_on_through_the_real_job(tmp_path, monkeypatch, params):
    """REACHABILITY: the same record file, the same job; off writes NOTHING, paper books."""
    start = time.time() + 6 * 3600
    _write_build(tmp_path, [_row(start), _row(start, suggested=True, event_id="ev2", ev_pct=2.5)])
    _write_grid(tmp_path, start, time.time() - 60)
    monkeypatch.setenv(paper.MODE_ENV, "off")
    assert _run_job(["book", "--data-root", str(tmp_path)]) == 0
    assert _run_job(["nightly", "--data-root", str(tmp_path)]) == 0     # the nightly job too: no book, no trace
    assert not paper.store_dir(tmp_path).exists()
    monkeypatch.setenv(paper.MODE_ENV, "paper")
    assert _run_job(["book", "--data-root", str(tmp_path)]) == 0
    bets = paper.load_bets(tmp_path)
    assert {(b["strategy"], b["event_id"]) for b in bets} >= {("ev_lb", "ev1"), ("suggested_2pct", "ev2")}
    assert all(b["preregistration"] == "8d16ab07" and b["policy_version"] == dp.POLICY_VERSION for b in bets)
    builds = [json.loads(x) for x in (paper.store_dir(tmp_path) / "builds.jsonl").read_text().splitlines()]
    assert len(builds) == 1 and builds[0]["records"] == 2 and builds[0]["eligible"] >= 2


def test_booking_is_idempotent_and_decides_once(tmp_path, monkeypatch, params):
    monkeypatch.setenv(paper.MODE_ENV, "paper")
    t0 = time.time() - 600
    start = t0 + 6 * 3600
    _write_grid(tmp_path, start, t0 - 120)                     # S2 sigma: EV_lb qualifies at the first build
    _write_build(tmp_path, [_row(start)], written_at=t0, build_id="b1")
    paper.run_book(tmp_path)
    first = paper.load_bets(tmp_path)
    assert {b["strategy"] for b in first} == {"ev_lb", "net_floor_719"}
    paper.run_book(tmp_path)                                   # same build again: nothing new
    assert paper.load_bets(tmp_path) == first
    # a LATER build with a better rung on the SAME axis: the axis was decided at the first build
    _write_build(tmp_path, [_row(start, line=221.5, quote={"book_prices": {"kalshi": 118}})],
                 written_at=t0 + 300, build_id="b2")
    paper.run_book(tmp_path)
    again = paper.load_bets(tmp_path)
    for strategy in ("ev_lb", "net_floor_719"):
        mine = [b for b in again if b["strategy"] == strategy]
        assert len(mine) == 1 and mine[0]["line"] == 220.5 and mine[0]["build_id"] == "b1"


def test_an_older_build_is_never_booked_after_a_newer_one(tmp_path, monkeypatch, params):
    monkeypatch.setenv(paper.MODE_ENV, "paper")
    t0 = time.time() - 600
    start = t0 + 6 * 3600
    newer = _write_build(tmp_path, [_row(start, event_id="evA")], written_at=t0, build_id="new")
    paper.book_build(newer, root=tmp_path, params=params)
    older = _write_build(tmp_path, [_row(start, event_id="evB")], written_at=t0 - 60, build_id="old")
    assert paper.book_build(older, root=tmp_path, params=params)["status"] == "already_processed"


# --------------------------------------------------------------------------- sigma sources


def _expanded(start: float, now: float, **over):
    ctx = dr.RecordContext(selected_date=sfr._central_date(now), now=datetime.fromtimestamp(now, tz=timezone.utc))
    return dr.build_record(_row(start, **over), ctx)


def test_sigma_s1_wins_where_recorded(tmp_path):
    now = time.time()
    rec = _expanded(now + 6 * 3600, now)
    rec.fair_v1.sigma_fair_v1, rec.fair_v1.family = 0.031, "ncaaf|regular|game"
    sigma, source, _ = paper.sigma_for_record(rec, {}, PARAMS, now)
    assert (sigma, source) == (0.031, dp.SIGMA_S1)


def test_sigma_s2_is_dispersion_plus_fitted_residual(tmp_path):
    from syndicate.features.shared.opportunity_signals import devig

    now = time.time()
    start = now + 6 * 3600
    _write_grid(tmp_path, start, now - 120)
    rec = _expanded(start, now)
    grid = paper.load_grid(tmp_path, {"nba": {"game"}}, sfr._central_date(now))
    sigma, source, detail = paper.sigma_for_record(rec, grid, PARAMS, now)
    books = [devig(list(p), method="shin") for p in ((-110, -110), (-105, -115), (-115, -105))]
    tts = sfr.tts_bucket(start - now)
    expect = (dp.dispersion_var(books, 0) + dp.r2_for(PARAMS, "game", "totals", tts)) ** 0.5
    assert source == dp.SIGMA_S2 and sigma == pytest.approx(expect) and detail.startswith("books=3")


def test_sigma_ignores_quotes_seen_after_the_decision(tmp_path):
    """No look-ahead: a book quote first observed after the build instant did not exist at the decision."""
    now = time.time()
    start = now + 6 * 3600
    _write_grid(tmp_path, start, now + 60)
    rec = _expanded(start, now)
    grid = paper.load_grid(tmp_path, {"nba": {"game"}}, sfr._central_date(now))
    sigma, source, detail = paper.sigma_for_record(rec, grid, PARAMS, now)
    assert source == dp.SIGMA_S3 and detail == "under_min_books:0" and sigma == pytest.approx(dp.sigma_s3(PARAMS))


def test_sigma_s3_without_a_grid_line():
    now = time.time()
    sigma, source, detail = paper.sigma_for_record(_expanded(now + 3600, now), {}, PARAMS, now)
    assert source == dp.SIGMA_S3 and detail == "no_grid_line"


# --------------------------------------------------------------------------- grading


def _bet(start: float, **over):
    bet = {"bet_id": "x1", "strategy": "ev_lb", "sport": "nfl", "event_id": "g1", "kind": "game", "market": "spreads",
           "segment": "full", "player": None, "side": "away", "line": 3.5, "commence_time": _iso(start),
           "home_team": "Home", "away_team": "Away", "axis": "margin|full", "cost": 0.48, "venue": "kalshi",
           "stake_units": 5.0, "in_band": True, "sigma_source": "S2_dispersion"}
    bet.update(over)
    return bet


def _q(start, book, sel, line, price, minutes_before, market="spreads"):
    return {"event_id": "g1", "bookmaker": book, "selection": sel, "market": market, "segment": "full",
            "player_name": None, "line": line, "price": price, "commence_time": _iso(start),
            "captured_at": _iso(start - minutes_before * 60)}


def _quotes(start):
    return [
        _q(start, "pinnacle", "home", -3.5, -120, 300), _q(start, "pinnacle", "away", 3.5, 100, 300),
        _q(start, "pinnacle", "home", -3.5, -125, 10), _q(start, "pinnacle", "away", 3.5, 105, 10),   # the close
        _q(start, "pinnacle", "home", -3.5, -200, -30), _q(start, "pinnacle", "away", 3.5, 160, -30),  # in play: ignored
        _q(start, "draftkings", "home", -3.5, -118, 20), _q(start, "draftkings", "away", 3.5, -102, 20),
        _q(start, "fanduel", "home", -3.5, -122, 15), _q(start, "fanduel", "away", 3.5, 100, 15),
    ]


def _fake_sc(final=(17, 24)):
    real = paper._scorecard()
    return SimpleNamespace(index_chips=lambda chips: {"nfl": chips},
                           match_chip=lambda rec, cands: (cands[0], None) if cands else (None, "no_chip"),
                           grade=real.grade), [{"state": "final", "scores": list(final)}]


def _write_bets(root: Path, bets):
    store = paper.store_dir(root)
    store.mkdir(parents=True, exist_ok=True)
    (store / "bets.jsonl").write_text("".join(json.dumps(b) + "\n" for b in bets), encoding="utf-8")


def test_grade_sharp_close_clv_and_outcome(tmp_path):
    from syndicate.features.shared.opportunity_signals import devig

    start = time.time() - 2 * 3600
    _write_bets(tmp_path, [_bet(start)])
    sc, chips = _fake_sc(final=(17, 24))           # away 17, home 24: home -3.5 covers, away +3.5 loses
    paper.run_grade(tmp_path, iter_quotes=lambda s, d: _quotes(start), chips_for=lambda d: chips, sc=sc)
    g = paper.load_grades(tmp_path)["x1"]
    p_away = devig([-125, 105], method="power")[1]
    assert g["sharp_close"] == pytest.approx(p_away, abs=1e-6)
    assert g["clv_sharp_pct"] == pytest.approx((p_away / 0.48 - 1) * 100, abs=1e-3)
    assert g["consensus_books"] == 3 and g["consensus_close"] is not None
    assert g["outcome"] == "loss" and g["return_flat"] == -1.0 and g["final"]


def test_a_moved_line_has_no_sharp_close_but_reports_the_consensus(tmp_path):
    start = time.time() - 2 * 3600
    _write_bets(tmp_path, [_bet(start, line=4.5)])
    quotes = _quotes(start) + [_q(start, "draftkings", "home", -4.5, -105, 20), _q(start, "draftkings", "away", 4.5, -115, 20),
                               _q(start, "fanduel", "home", -4.5, -100, 20), _q(start, "fanduel", "away", 4.5, -120, 20)]
    sc, chips = _fake_sc()
    paper.run_grade(tmp_path, iter_quotes=lambda s, d: quotes, chips_for=lambda d: chips, sc=sc)
    g = paper.load_grades(tmp_path)["x1"]
    assert g["sharp_close"] is None and g["sharp_reason"] == "no_pinnacle_close_at_this_line"
    assert g["consensus_close"] is not None and g["clv_consensus_pct"] is not None


def test_grading_reads_book_quotes_through_the_real_reader(tmp_path, monkeypatch):
    """The default reader is odds_book_quotes.iter_book_quotes under SYNDICATE_DATA_ROOT, for D-1 and D."""
    start = time.time() - 2 * 3600
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    shard = tmp_path / "nfl_source" / "tracking" / "book_quotes" / f"{sfr._central_date(start)}.jsonl"
    shard.parent.mkdir(parents=True)
    shard.write_text("".join(json.dumps(q) + "\n" for q in _quotes(start)), encoding="utf-8")
    _write_bets(tmp_path, [_bet(start)])
    sc, chips = _fake_sc()
    paper.run_grade(tmp_path, chips_for=lambda d: chips, sc=sc)
    assert paper.load_grades(tmp_path)["x1"]["sharp_close"] is not None


def test_a_bet_before_its_start_is_not_graded(tmp_path):
    _write_bets(tmp_path, [_bet(time.time() + 3600)])
    assert paper.run_grade(tmp_path, iter_quotes=lambda s, d: [], chips_for=lambda d: [])["graded"] == 0


def test_props_are_roi_ungraded_not_dropped(tmp_path):
    start = time.time() - 2 * 3600
    _write_bets(tmp_path, [_bet(start, market="player_points", player="A Player", kind="prop", side="over",
                                line=20.5, axis="prop|player_points|a player|full")])
    paper.run_grade(tmp_path, iter_quotes=lambda s, d: [], chips_for=lambda d: [], sc=_fake_sc()[0])
    g = paper.load_grades(tmp_path)["x1"]
    assert g["outcome"] is None and g["outcome_reason"] == "no_outcome_grader:prop"


# --------------------------------------------------------------------------- the gate


def test_clustered_se_by_hand():
    out = paper.clustered([1.0, 3.0, -1.0, 5.0], ["a", "a", "b", "b"])
    # mean 2; cluster sums of deviations: a = (-1)+(1) = 0, b = (-3)+(3) = 0 -> SE 0
    assert out["mean"] == 2.0 and out["se"] == 0.0 and out["z"] is None
    out = paper.clustered([1.0, 1.0, 3.0, 3.0], ["a", "a", "b", "b"])
    # deviations: a -2, b +2; SE = sqrt(2/1 * 8) / 4 = 1.0
    assert out["se"] == pytest.approx(1.0) and out["z"] == pytest.approx(2.0)


def test_looks_follow_the_registration():
    state: dict = {}
    assert paper.take_look(state, "ev_lb", {"n": 399, "games": 150, "z": 9.0}, "2026-11-10")["status"] == "waiting"
    look = paper.take_look(state, "ev_lb", {"n": 400, "games": 100, "z": 3.9}, "2026-11-11")
    assert (look["look"], look["boundary"], look["pass"]) == ("L1", 3.935, False)
    assert paper.take_look(state, "ev_lb", {"n": 900, "games": 300, "z": 9.0}, "2026-11-11")["status"] \
        == "look_already_taken_today"
    look = paper.take_look(state, "ev_lb", {"n": 900, "games": 300, "z": 2.8}, "2026-11-12")
    assert (look["look"], look["boundary"], look["pass"]) == ("L2", 2.783, True)
    assert paper.take_look(state, "ev_lb", {"n": 2000, "games": 600, "z": 0.0}, "2026-11-13")["status"] == "already_passed"


def test_the_calendar_final_reads_at_the_l3_boundary_and_closes():
    state: dict = {}
    paper.take_look(state, "net_floor_719", {"n": 450, "games": 120, "z": 1.0}, "2026-12-01")      # L1, fails
    look = paper.take_look(state, "net_floor_719", {"n": 700, "games": 180, "z": 2.3}, paper.FINAL_READ_DATE)
    assert (look["look"], look["boundary"], look["pass"]) == ("L3", 2.272, True)
    state = {}
    paper.take_look(state, "ev_lb", {"n": 450, "games": 120, "z": 1.0}, "2026-12-01")
    paper.take_look(state, "ev_lb", {"n": 700, "games": 180, "z": 2.0}, paper.FINAL_READ_DATE)
    assert state["ev_lb"]["closed"]["reason"] == "final_look_not_passed"
    assert paper.take_look(state, "ev_lb", {"n": 5000, "games": 900, "z": 9.0}, "2027-02-07")["status"] == "test_closed"
    state = {}
    paper.take_look(state, "ev_lb", {"n": 10, "games": 3, "z": 9.0}, paper.FINAL_READ_DATE)
    assert state["ev_lb"]["closed"]["reason"] == "final_underpowered"


def test_evaluate_writes_the_read_and_reports_the_comparator(tmp_path):
    start = time.time() - 2 * 3600
    bets = [_bet(start, bet_id=f"p{i}", event_id=f"g{i}") for i in range(6)]
    bets += [_bet(start, bet_id=f"c{i}", event_id=f"g{i}", strategy="suggested_2pct", cost=0.52) for i in range(6)]
    _write_bets(tmp_path, bets)
    grades = {b["bet_id"]: {"clv_sharp_pct": (0.5 / b["cost"] - 1) * 100, "clv_consensus_pct": 0.0,
                            "return_flat": 1.0 if int(b["bet_id"][1:]) % 2 else -1.0} for b in bets}
    (paper.store_dir(tmp_path) / "grades.json").write_text(json.dumps(grades), encoding="utf-8")
    out = paper.run_evaluate(tmp_path)
    assert out["strategies"]["ev_lb"]["gate_clv_sharp"]["n"] == 6
    assert out["strategies"]["suggested_2pct"]["gate_clv_sharp"]["mean"] < 0
    assert out["looks"]["ev_lb"]["status"] == "waiting" and "suggested_2pct" not in out["looks"]
    assert out["comparison_ev_lb_minus_suggested"]["n"] == 6
    assert (paper.store_dir(tmp_path) / "reads" / f"{out['read_date']}.json").is_file()


# --------------------------------------------------------------------------- no order path


def test_no_order_module_is_imported_by_any_of_our_files():
    for rel in OUR_FILES:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
                names += [a.name for a in node.names]
        for name in names:
            assert not any(bad in name for bad in ORDER_MODULES), f"{rel} imports {name}"


def test_booking_loads_no_order_module_at_run_time(tmp_path):
    """A clean interpreter books one build; afterwards no order module is in sys.modules.

    The record file is written HERE, by the worker's builder (which itself reads portfolio_commit's sizing helper):
    the subprocess runs only the paper job's own path."""
    start = time.time() + 6 * 3600
    _write_build(tmp_path, [_row(start)])
    _write_grid(tmp_path, start, time.time() - 120)
    code = f"""
import os, sys, json
sys.path.insert(0, {str(REPO)!r})
os.environ["SYNDICATE_DECISION_POLICY_PAPER"] = "paper"
from pathlib import Path
from syndicate.features.shared import decision_policy_paper as paper
paper.run_book(Path({str(tmp_path)!r}))
bad = sorted(m for m in sys.modules if any(b in m for b in {ORDER_MODULES!r}))
print(json.dumps(bad))
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO), timeout=240)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []
    assert paper.load_bets(tmp_path), "the subprocess booked nothing, so the import check proved nothing"
