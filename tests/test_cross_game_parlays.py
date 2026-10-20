"""Cross-game parlays (user 2026-10-20: "what about cross slate SGPS?" -> "can we do both?"): one leg per game, any
sport, +100 or better at ONE book. Two kinds: legs built for hit rate, and legs that each beat their own price."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from syndicate.app import app
from syndicate.blueprints import cheat_sheets as route
from syndicate.features.shared import cheat_sheet_record as csr
from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import cross_game_parlays as xg

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-10-20"


def _row(event, player, p_market, prices, *, market="Points", side="over", line=14.5, fair_method="consensus"):
    return {"event_id": event, "player": player, "market": market, "side": side, "line": line, "matchup": f"{event} game",
            "commence_time": "2026-10-20T23:00:00Z", "fair_method": fair_method, "book_prices": prices,
            "check": {"p_market": p_market, "verdict": "value"}}


def _hit_leg(event, player, p, prices, p_market=0.8):
    return {"player": player, "market": "SOG", "side": "over", "line": 0.5, "p_side": p, "p_market": p_market,
            "prices": prices, "player_id": f"id-{player}"}


def test_a_value_leg_keeps_only_parlay_books_where_it_beats_the_fair():
    rows = [_row("e1", "A", 0.55, {"fanduel": 100, "draftkings": -150, "kalshi": 110}),     # fd +10% EV; dk no; kalshi no parlay
            _row("e2", "B", 0.55, {"fanduel": 100}, fair_method="book_margin_model"),     # one-sided fair: never
            _row("e3", "C", 0.70, {"fanduel": 100})]                                      # +40%: a stale quote, never
    legs = xg.value_legs({"sport": "nba", "rows": rows, "games": []})
    assert [(l["player"], l["prices"]) for l in legs] == [("A", {"fanduel": 100})]
    assert legs[0]["ev_by_book"]["fanduel"] == cs.ev_pct(0.55, 100)


def test_value_tickets_take_one_leg_a_game_at_one_book_between_plus_100_and_plus_300():
    legs = xg.value_legs({"sport": "nba", "games": [], "rows": [
        _row("e1", "A", 0.55, {"fanduel": 100, "draftkings": 105}), _row("e2", "B", 0.56, {"fanduel": -105, "draftkings": -110}),
        _row("e3", "C", 0.30, {"draftkings": 280})]})
    got = xg.tickets(legs, "value")
    assert got and all(t["kind"] == "value" and 2.0 <= t["decimal"] <= 4.0 and t["ev_pct"] > 0 for t in got)
    for t in got:
        assert len({l["event_id"] for l in t["legs"]}) == t["size"]                 # one leg a game
        assert all(l["price"] == next(r for r in legs if r["player"] == l["player"])["prices"][t["book"]] for l in t["legs"])
    best = got[0]
    assert abs(best["p_joint"] - 0.55 * 0.56) < 1e-6 or best["p_joint"] >= got[-1]["p_joint"]   # likeliest first


def test_hit_rate_tickets_are_three_or_four_games_at_plus_100_likeliest_first():
    pool = {f"e{i}": [_hit_leg(f"e{i}", f"P{i}", 0.80, {"fanduel": -300, "pinnacle": -320})] for i in range(4)}
    pool["e0"].append(_hit_leg("e0", "Q0", 0.70, {"fanduel": -220}))
    legs = xg.hit_rate_legs("nhl", pool, {})
    got = xg.tickets(legs, "hit_rate")
    assert got and all(t["size"] in (3, 4) and t["decimal"] >= 2.0 for t in got)
    assert all(len({l["event_id"] for l in t["legs"]}) == t["size"] for t in got)
    assert [t["p_joint"] for t in got] == sorted((t["p_joint"] for t in got), reverse=True)
    assert all(l.get("player_id") for t in got for l in t["legs"])             # the reconcile reads box scores by it


def test_a_ticket_is_graded_like_a_parlay_lost_won_void_dropped_pending():
    t = {"legs": [{"sport": "nba", "kind": "prop", "player": "A", "market": "Points", "side": "over", "line": 14.5, "price": 100,
                   "bet": "A", "result_key": "a"},
                  {"sport": "nhl", "kind": "prop", "player": "B", "market": "SOG", "side": "over", "line": 0.5, "price": -300,
                   "bet": "B", "result_key": "b"},
                  {"sport": "nhl", "kind": "line", "event_id": "g", "market": "totals", "side": "over", "line": 6, "price": 110,
                   "bet": "o6", "result_key": "g|totals|over|6"}]}
    nba = {"props": {cs.prop_result_key(t["legs"][0]): {"y": 1.0, "v": 20}}}
    nhl = {"props": {cs.prop_result_key(t["legs"][1]): {"y": 1.0, "v": 2}}, "lines": {"g|totals|over|6": {"y": 1.0}}}
    won = xg.grade(t, {"nba": nba, "nhl": nhl})
    assert won["status"] == "won" and won["units"] == round(2.0 * (4 / 3) * 2.1 - 1, 3)
    nhl_lost = dict(nhl, lines={"g|totals|over|6": {"y": 0.0}})
    assert xg.grade(t, {"nba": nba, "nhl": nhl_lost})["status"] == "lost"
    voided = dict(nhl, lines={"g|totals|over|6": {"y": 0.5}})                     # a push: dropped, the rest re-multiplied
    assert xg.grade(t, {"nba": nba, "nhl": voided})["units"] == round(2.0 * (4 / 3) - 1, 3)
    assert xg.grade(t, {"nba": nba})["status"] == "pending"


def _bcs():
    spec = importlib.util.spec_from_file_location("bcs", ROOT / "scripts" / "build_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_build_writes_the_day_beside_cheatsheets_and_keeps_a_started_ticket(tmp_path, monkeypatch):
    bcs = _bcs()
    monkeypatch.setattr(bcs, "sgp_leg_pool", lambda *a, **k: {})
    folder = tmp_path / "cheatsheets" / "nba"
    folder.mkdir(parents=True)
    rows = [_row("e1", "A", 0.55, {"fanduel": 100}), _row("e2", "B", 0.56, {"fanduel": -105})]
    games = [{"event_id": "e1", "commence_time": "2026-10-20T23:00:00Z"}, {"event_id": "e2", "commence_time": "2026-10-20T23:30:00Z"}]
    (folder / f"{DAY}.json").write_text(json.dumps({"sport": "nba", "date": DAY, "rows": rows, "games": games}), encoding="utf-8")
    before = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
    out = bcs.attach_cross_game(tmp_path, DAY, now=before)
    assert out["kinds"]["value"] and (tmp_path / "cheatsheets_cross" / f"{DAY}.json").is_file()
    assert not (tmp_path / "cheatsheets" / "cross").exists()                     # never a "sport" dir
    first = out["kinds"]["value"][0]["xg_id"]
    rows[0]["book_prices"] = {"fanduel": -200}                                   # after tip-off the line moved: no longer value
    (folder / f"{DAY}.json").write_text(json.dumps({"sport": "nba", "date": DAY, "rows": rows, "games": games}), encoding="utf-8")
    later = bcs.attach_cross_game(tmp_path, DAY, now=datetime(2026, 10, 20, 23, 10, tzinfo=timezone.utc))
    assert [t["xg_id"] for t in later["kinds"]["value"]] == [first]             # started: kept as built, the record


def test_the_page_shows_a_sports_cross_tickets_with_their_result(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(route, "_today", lambda: DAY)
    (tmp_path / "cheatsheets" / "nba").mkdir(parents=True)
    (tmp_path / "cheatsheets" / "nba" / f"{DAY}.json").write_text(json.dumps({"sport": "nba", "date": DAY, "rows": [], "games": [],
                                                                               "picks": [{"event_id": "e1"}]}), encoding="utf-8")
    cross = tmp_path / "cheatsheets_cross"
    cross.mkdir()
    t_nba = {"xg_id": "xg_a", "kind": "value", "legs": [{"sport": "nba", "event_id": "e1"}, {"sport": "nhl", "event_id": "h1"}]}
    t_nhl = {"xg_id": "xg_b", "kind": "value", "legs": [{"sport": "nhl", "event_id": "h1"}, {"sport": "nhl", "event_id": "h2"}]}
    (cross / f"{DAY}.json").write_text(json.dumps({"date": DAY, "kinds": {"value": [t_nba, t_nhl]}}), encoding="utf-8")
    (cross / f"{DAY}.graded.json").write_text(json.dumps({"tickets": {"xg_a": {"status": "won", "units": 1.2}}}), encoding="utf-8")
    doc = route._read("nba", DAY)
    assert [t["xg_id"] for t in doc["cross"]["kinds"]["value"]] == ["xg_a"] and doc["cross"]["kinds"]["value"][0]["result"]["status"] == "won"
    html = app.test_client().get(f"/cheatsheets?sport=nba&date={DAY}").get_data(as_text=True)
    assert "function crossBlock" in html and "crossBlock(d, game)" in html
    assert "cross" not in route._sports()


def test_the_all_sports_scorecard_counts_cross_tickets_in_units_apart_from_featured():
    graded = [{"date": "2026-10-18", "tickets": {"a": {"kind": "value", "status": "won", "units": 1.5},
                                                 "b": {"kind": "value", "status": "lost", "units": -1.0},
                                                 "c": {"kind": "hit_rate", "status": "pending", "units": None}}}]
    rec = csr.season_record([], generated_at="x", cross=graded)
    assert rec["official"]["totals"]["xg_value"] == {"w": 1, "l": 1, "n": 2, "units": 0.5, "win_pct": 50.0, "roi_pct": 25.0}
    assert "xg_hit_rate" not in rec["official"]["totals"]                        # nothing settled
    assert {"key": "xg_value", "label": "Cross-game parlays: value", "cross": True} in rec["sections"]
    assert rec["applies"]["xg_value"] == [] and rec["applies"]["xg_hit_rate"] == []   # the all-sports scorecard only


def test_the_reconcile_grades_the_cross_days_into_their_own_file(tmp_path):
    spec = importlib.util.spec_from_file_location("rc", ROOT / "scripts" / "reconcile_cheat_sheets.py")
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    sheets = tmp_path / "cheatsheets"
    (sheets / "nhl").mkdir(parents=True)
    leg = {"sport": "nhl", "kind": "line", "event_id": "g", "market": "totals", "side": "over", "line": 6, "price": 110,
           "bet": "o6", "result_key": "g|totals|over|6"}
    (tmp_path / "cheatsheets_cross").mkdir()
    (tmp_path / "cheatsheets_cross" / f"{DAY}.json").write_text(json.dumps(
        {"date": DAY, "sports": ["nhl"], "kinds": {"value": [{"xg_id": "xg_1", "price": 110, "legs": [leg]}]}}), encoding="utf-8")
    (sheets / "nhl" / f"{DAY}.reconciled.json").write_text(json.dumps({"lines": {"g|totals|over|6": {"y": 1.0}}}), encoding="utf-8")
    assert rc.grade_cross(tmp_path, sheets, DAY) == 1
    graded = json.loads((tmp_path / "cheatsheets_cross" / f"{DAY}.graded.json").read_text(encoding="utf-8"))
    assert graded["tickets"]["xg_1"]["status"] == "won" and graded["tickets"]["xg_1"]["kind"] == "value"
