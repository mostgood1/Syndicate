"""The reconciled sheet grades its same-game parlays (lane `cheat-sheets`, user 2026-10-17: "why arent SGPs reconciled
for NHL on the live site"). The paper grader wrote `sgp_graded.jsonl` and the page never read it, so a reconciled NHL
sheet showed its parlays with no result. Now the page grades each ticket from the day's own reconciled file by the
ledger's rule (`cheat_sheets.sgp_results`, which `grade_sgp_paper.grade_one` calls), and states the count against what
our probabilities said -- paper, so never units."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from syndicate.app import app
from syndicate.blueprints import cheat_sheets as route
from syndicate.features.shared import cheat_sheets as cs

DAY = "2026-10-16"
ROOT = Path(__file__).resolve().parents[1]


def _leg(player, market, side, line):
    return {"player": player, "market": market, "side": side, "line": line, "bet": f"{player} {side.upper()} {line} {market}"}


def _sheet():
    won = {"sgp_id": "sgp_a", "event_id": "e1", "p_joint": 0.12, "size": 2, "family": "correlation",
           "legs": [_leg("Michael DiPietro", "SAVES", "over", 30.5), _leg("Jackson LaCombe", "SOG", "over", 2.5)]}
    lost = {"sgp_id": "sgp_b", "event_id": "e1", "p_joint": 0.40, "size": 2, "family": "hit_rate",
            "legs": [_leg("Jackson LaCombe", "SOG", "under", 1.5), _leg("Troy Terry", "POINTS", "under", 0.5)]}
    open_ = {"sgp_id": "sgp_c", "event_id": "e2", "p_joint": 0.30, "size": 2, "family": "hit_rate",
             "legs": [_leg("Erik Karlsson", "SOG", "under", 2.5), _leg("Sidney Crosby", "POINTS", "over", 0.5)]}
    rows = [dict(_leg("Jackson LaCombe", "SOG", "over", 2.5), event_id="e1", commence_time="2026-10-17T02:10:00Z",
                 check={"price": 120, "verdict": "neutral"}),
            dict(_leg("Michael DiPietro", "SAVES", "over", 27.5), event_id="e1", commence_time="2026-10-17T02:10:00Z",
                 check={"price": -120, "verdict": "neutral"}),
            dict(_leg("Troy Terry", "POINTS", "under", 0.5), event_id="e1", commence_time="2026-10-17T02:10:00Z",
                 check={"price": -150, "verdict": "neutral"})]
    reconciled = {"sport": "nhl", "date": DAY,
                  "props": {cs.prop_result_key(rows[0]): {"y": 1.0, "v": 3.0},          # LaCombe 3 SOG
                            cs.prop_result_key(rows[1]): {"y": 1.0, "v": 33.0},         # DiPietro 33 saves (alt rung 30.5)
                            cs.prop_result_key(rows[2]): {"y": 0.0, "v": 1.0}},         # Terry 1 point
                  "lines": {}, "counts": {}}
    return {"sport": "nhl", "date": DAY, "generated_at": "2026-10-16T23:00:00Z", "rows": rows,
            "games": [{"event_id": "e1", "matchup": "SJ @ ANA"}, {"event_id": "e2", "matchup": "PIT @ COL"}],
            "sgp": [won, lost, open_]}, reconciled


def test_each_ticket_is_graded_from_the_days_results_and_alt_rungs_from_the_actual():
    sheet, rec = _sheet()
    got = cs.sgp_results(sheet["sgp"], rec)
    assert [g["status"] for g in got] == ["won", "lost", "pending"]
    assert [(l["result"], l["actual"]) for l in got[0]["legs"]] == [("won", 33.0), ("won", 3.0)]
    assert [(l["result"], l["actual"]) for l in got[1]["legs"]] == [("lost", 3.0), ("lost", 1.0)]


def test_the_paper_ledger_and_the_page_use_one_rule():
    spec = importlib.util.spec_from_file_location("grade_sgp_paper", ROOT / "scripts" / "grade_sgp_paper.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    sheet, rec = _sheet()
    for ticket, page in zip(sheet["sgp"], cs.sgp_results(sheet["sgp"], rec)):
        ledger = g.grade_one(dict(ticket, date=DAY), rec)
        assert (ledger["status"], ledger["legs"]) == (page["status"], page["legs"])


def test_page_payload_attaches_results_only_on_a_reconciled_day():
    sheet, rec = _sheet()
    assert all("result" not in s for s in cs.page_payload([dict(sheet)])["nhl"]["sgp"])
    doc = cs.page_payload([dict(sheet, reconciled=rec)])["nhl"]
    assert [s["result"]["status"] for s in doc["sgp"]] == ["won", "lost", "pending"]
    assert all("result" not in s for s in sheet["sgp"])                       # the stored sheet is never mutated


def test_the_live_reconciled_page_serves_graded_parlays(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(route, "_today", lambda: "2026-10-17")
    sheet, rec = _sheet()
    folder = tmp_path / "cheatsheets" / "nhl"
    folder.mkdir(parents=True)
    (folder / f"{DAY}.json").write_text(json.dumps(sheet), encoding="utf-8")
    (folder / f"{DAY}.reconciled.json").write_text(json.dumps(rec), encoding="utf-8")
    html = app.test_client().get(f"/cheatsheets?sport=nhl&date={DAY}&view=reconciled").get_data(as_text=True)
    data = json.loads(re.search(r"const DATA = (.*?);\n", html).group(1))["nhl"]
    assert [s["result"]["status"] for s in data["sgp"]] == ["won", "lost", "pending"]
    assert "function sgpRecap" in html and "SGP_STATUS[res.status]" in html
