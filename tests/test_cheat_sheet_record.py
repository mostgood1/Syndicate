"""The cheat sheets' running season record (user 2026-10-15: "add a running season record page for the cheat sheets"):
what each sheet FEATURED, graded, 1 unit a bet at its best price; a bet counted once a day across sections; both-sided
lists never in it; the beta kept apart from the official record; the page only reads the file."""
from __future__ import annotations

import json

from syndicate.app import app
from syndicate.blueprints import cheat_sheets as route
from syndicate.features.shared import cheat_sheet_record as csr
from syndicate.features.shared import cheat_sheets as cs


def _row(player, side="under", price=-139, verdict="value", hits=9, **extra):
    row = {"event_id": "e1", "player": player, "market": "Receptions", "line": 2.5, "side": side, "books_quoting": 4,
           "commence_time": "2026-10-15T23:15:00Z",
           "check": {"verdict": verdict, "ev_market": 3.0 if verdict == "value" else -1.0, "price": price, "p_market": 0.6,
                     "form10": {"games": 10, "hits": hits, "rate": hits / 10}, "form5": {"games": 5, "hits": min(hits, 5)}}}
    row.update(extra)
    return row


def _day(date, sport="nfl", results=(1.0, 0.0, 1.0)):
    rows = [_row("A"), _row("B", price=120), _row("C", verdict="neutral", hits=3), _row("C", side="over", verdict="neutral", hits=3)]
    sheet = {"sport": sport, "date": date, "rows": rows}
    props = {cs.prop_result_key(r): {"y": y} for r, y in zip(rows, results)}
    rec = {"props": props, "lines": {}, "counts": {"props": 4, "props_graded": len(props), "lines": 0, "lines_graded": 0}}
    return sheet, rec


def test_a_day_counts_what_the_sheet_featured_once_each():
    sheet, rec = _day("2026-10-15")
    secs = cs.sections(sheet["rows"])
    assert secs["value"] == [0, 1] and 0 in secs["consistency"]          # A is in two sections ...
    d = csr.day_record(sheet, rec)
    assert d["sections"]["value"] == {"w": 1, "l": 1, "n": 2, "units": round(100 / 139 - 1, 2), "win_pct": 50.0,
                                      "roi_pct": round(100 * round(100 / 139 - 1, 2) / 2, 1)}
    assert d["featured"]["n"] == 2                                       # ... and counted once; C (neutral, both sides) never
    assert d["beta"] is False and d["graded"] == 3 and d["bets"] == 4


def test_the_season_keeps_the_beta_apart_and_runs_a_series():
    days = [csr.day_record(*_day("2026-10-14", "mlb")), csr.day_record(*_day("2026-10-15")),
            csr.day_record(*_day("2026-10-16", results=(0.0, 0.0, 0.0)))]
    rec = csr.season_record(days, generated_at="2026-10-17T12:45:00+00:00")
    assert rec["beta"]["days"] == 1 and rec["official"]["days"] == 2
    assert rec["official"]["totals"]["featured"]["w"] == 1 and rec["official"]["totals"]["featured"]["l"] == 3
    assert list(rec["official"]["by_sport"]) == ["nfl"] and list(rec["beta"]["by_sport"]) == ["mlb"]
    series = rec["official"]["series"]
    assert [x["date"] for x in series] == ["2026-10-15", "2026-10-16"]
    assert series[-1]["cum_units"] == round(series[0]["cum_units"] - 2, 2)            # two losses on the 16th
    assert [x["date"] for x in rec["days"]] == ["2026-10-16", "2026-10-15", "2026-10-14"]   # newest first
    assert {"key": "featured", "label": "All featured picks"} in rec["sections"]             # the parlays follow it


def test_the_record_page_only_reads_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    client = app.test_client()
    page = client.get("/cheatsheets/record").get_data(as_text=True)
    assert '"page": "record"' in page and "const DATA = null" in page                   # nothing graded yet: an empty record
    assert client.get("/api/cheatsheets/record").status_code == 404
    rec = csr.season_record([csr.day_record(*_day("2026-10-15"))], generated_at="2026-10-16T12:45:00+00:00")
    (tmp_path / "cheatsheets").mkdir()
    (tmp_path / "cheatsheets" / "record.json").write_text(json.dumps(rec), encoding="utf-8")
    page = client.get("/cheatsheets/record").get_data(as_text=True)
    assert "function renderRecordPage" in page and '"official_start": "2026-10-15"' in page
    assert client.get("/api/cheatsheets/record").get_json()["official"]["days"] == 1


def test_picks_the_sim_backs_and_price_plays_keep_separate_records():
    # User 2026-10-15: "split the season record into picks vs price plays" -- so the record says whether the sim's
    # backing adds anything. A pick stamped before the label existed is read by the same rule (cs.pick_label).
    pick = lambda pid, line, **kw: {"pick_id": pid, "kind": "game", "event_id": "e7", "market": "totals", "side": "over",
                                     "line": line, "segment": "full", "price": 110, "p_market": 0.5, **kw}
    picks = [pick("a", 47.5, label="SYNDICATE PICK"), pick("b", 48.5, label="PRICE PLAY"),
             pick("c", 49.5, sim_view="contradicts", p_model=0.12)]                     # no label: a price play by the rule
    sheet = {"sport": "ncaaf", "date": "2026-10-15", "rows": [], "picks": picks}
    graded = {cs.pick_result_key(picks[0]): {"y": 1}, cs.pick_result_key(picks[1]): {"y": 0}, cs.pick_result_key(picks[2]): {"y": 1}}
    d = csr.day_record(sheet, {"picks": graded, "props": {}, "lines": {}, "counts": {"picks": 3, "picks_graded": 3}})
    assert d["sections"]["picks"]["w"] == 1 and d["sections"]["picks"]["n"] == 1
    assert (d["sections"]["price_plays"]["w"], d["sections"]["price_plays"]["l"]) == (1, 1)
    assert d["featured"]["n"] == 3                                                     # all of them, once each
    keys = [k for k, _ in csr.FEATURED]
    assert keys[:2] == ["picks", "price_plays"]
