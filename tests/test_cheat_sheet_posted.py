"""Posted graphics stay posted (lane `cheat-sheets`, user 2026-10-17: "we need to look at why consistency sheets changed
for NHL yesterday. Trying to promote these on twitter and the changes dont help for reconciling").

NHL 10-16: the 12:34 PM CT consistency graphic showed LaCombe SOG u1.5 and Karlsson SOG u2.5. Every later build re-picked
the section from its own rows, and a section shows the main line's better-EV side -- by the 8:27 PM build that was
Karlsson's OVER (3/10), so he left the section, and the record graded a section nobody posted. An exported section is
now recorded, its rows lead the section on the page and in the record (at the posted price), and builds keep them."""
from __future__ import annotations

import json
import re

import pytest

from syndicate.app import app
from syndicate.blueprints import cheat_sheets as route
from syndicate.features.shared import cheat_sheet_record as csr
from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import play_cards as pc

DAY = "2026-10-16"


def _row(player, side, line, *, price, ev, hits, event="ana", verdict="neutral", books=6):
    rate = hits / 10
    return {"event_id": event, "player": player, "market": "SOG", "line": line, "side": side, "books_quoting": books,
            "commence_time": "2026-10-17T02:10:00Z",
            "check": {"verdict": verdict, "ev_market": ev, "price": price, "book": "draftkings", "p_market": 0.6,
                      "form10": {"games": 10, "hits": hits, "rate": rate}, "form5": {"games": 5, "hits": min(hits, 5), "rate": min(hits, 5) / 5}}}


def _karlsson(under_ev, over_ev):
    """Karlsson SOG 2.5: the under cleared 7 of 10, the over 3 of 10; which side the sheet shows follows the EV."""
    return [_row("Erik Karlsson", "under", 2.5, price=-180, ev=under_ev, hits=7, event="pit"),
            _row("Erik Karlsson", "over", 2.5, price=140, ev=over_ev, hits=3, event="pit")]


def _sheet(rows):
    return {"sport": "nhl", "date": DAY, "generated_at": "2026-10-16T17:34:00Z", "rows": rows,
            "games": [{"event_id": "ana", "matchup": "X @ ANA"}, {"event_id": "pit", "matchup": "PIT @ COL"}]}


def _post(sheet, section, card_rows, at="2026-10-16T17:34:00Z", price=None):
    entries = []
    for r in card_rows:
        c = r.get("check") or {}
        entries.append({"card_id": pc.card_id("nhl", DAY, r), "price": c.get("price") if price is None else price,
                        "book": c.get("book"), "item": dict(r)})
    return {"sport": "nhl", "date": DAY, "posts": [{"section": section, "posted_at": at, "rows": entries, "lines": []}]}


def _consistency_players(rows, ids):
    return [(rows[i]["player"], rows[i]["side"]) for i in ids]


def test_the_10_16_failure_a_side_flip_drops_a_posted_row_from_its_section():
    lacombe = _row("Jackson LaCombe", "under", 1.5, price=-103, ev=-1.85, hits=7)
    at_post = _sheet([lacombe] + _karlsson(under_ev=-3.6, over_ev=-6.0))
    assert ("Erik Karlsson", "under") in _consistency_players(at_post["rows"], cs.sections(at_post["rows"])["consistency"])
    later = _sheet([lacombe] + _karlsson(under_ev=-4.14, over_ev=-0.94))       # the 8:27 PM build's numbers
    secs = cs.sections(later["rows"])["consistency"]
    assert _consistency_players(later["rows"], secs) == [("Jackson LaCombe", "under")]   # Karlsson gone: the old behaviour
    posted = _post(at_post, "consistency", at_post["rows"][:2])
    cids = [pc.card_id("nhl", DAY, r) for r in later["rows"]]
    pinned = cs.pin_posted(cs.sections(later["rows"]), cids, cs.posted_entries(posted, "rows"))["consistency"]
    assert _consistency_players(later["rows"], pinned) == [("Jackson LaCombe", "under"), ("Erik Karlsson", "under")]


def test_pinned_rows_lead_in_posted_order_and_are_never_repeated():
    rows = [_row(f"P{i}", "under", 1.5, price=-110, ev=-1.0, hits=8) for i in range(4)]
    cids = [pc.card_id("nhl", DAY, r) for r in rows]
    posted = _post(_sheet(rows), "consistency", [rows[2], rows[0]])
    secs = cs.pin_posted(cs.sections(rows), cids, cs.posted_entries(posted, "rows"))
    assert secs["consistency"][:2] == [2, 0] and sorted(secs["consistency"]) == [0, 1, 2, 3]


def test_page_section_names_map_to_the_payloads_and_a_game_sees_only_its_own():
    rows = [_row("A", "under", 1.5, price=-110, ev=-1.0, hits=8), _row("B", "under", 1.5, price=-110, ev=-1.0, hits=8, event="pit")]
    posted = _post(_sheet(rows), "matchups", rows)
    entries = cs.posted_entries(posted, "rows")
    assert {e["section"] for e in entries} == {"matchup_spots"}
    cids = [pc.card_id("nhl", DAY, r) for r in rows]
    one = cs.pin_posted({"matchup_spots": []}, cids, entries, events=[r["event_id"] for r in rows], event="pit")
    assert one["matchup_spots"] == [1]


def test_a_row_the_board_read_lost_comes_back_from_the_prior_sheet_else_as_posted():
    lacombe = _row("Jackson LaCombe", "under", 1.5, price=-103, ev=-1.85, hits=7)
    gone = _row("Gone Guy", "under", 0.5, price=-150, ev=-2.0, hits=8, event="sea")
    posted = _post(_sheet([lacombe, gone]), "consistency", [lacombe, gone])
    fresh = _sheet([lacombe])                                                # the next read lacks Gone Guy and his game
    newer = dict(gone, check=dict(gone["check"], price=-160))
    prior = {"rows": [lacombe, newer], "games": [{"event_id": "sea", "matchup": "SEA @ VAN"}]}
    kept = cs.with_posted(fresh, posted, prior=prior)
    assert kept["posted_kept"] == 1 and kept["rows"][-1]["check"]["price"] == -160 and kept["rows"][-1]["posted_kept"]
    assert {g["event_id"] for g in kept["games"]} == {"ana", "pit", "sea"}
    alone = cs.with_posted(fresh, posted)                                   # no prior: the posted copy
    assert alone["rows"][-1]["check"]["price"] == -150
    assert cs.with_posted(fresh, None) == fresh


def test_page_payload_pins_marks_and_grades_at_the_posted_price():
    lacombe = _row("Jackson LaCombe", "under", 1.5, price=-103, ev=-1.85, hits=7)
    karl = _karlsson(under_ev=-4.14, over_ev=-0.94)
    sheet = _sheet([lacombe] + karl)
    sheet["posted"] = _post(_sheet([lacombe] + _karlsson(-3.6, -6.0)), "consistency", [lacombe, karl[0]])
    sheet["reconciled"] = {"props": {cs.prop_result_key(r): {"y": 1.0} for r in sheet["rows"]}, "lines": {}, "counts": {}}
    karl[0]["check"]["price"] = -250                                          # the price moved after the post
    doc = cs.page_payload([sheet])["nhl"]
    rows = doc["rows"]
    assert _consistency_players(rows, doc["sections"]["consistency"]) == [("Jackson LaCombe", "under"), ("Erik Karlsson", "under")]
    assert rows[1]["posted"]["at"] == "2026-10-16T17:34:00Z" and rows[1]["posted"]["price"] == -180
    assert rows[1]["result"]["units"] == round(100 / 180, 3)                  # graded at -180, not -250
    assert "posted" not in rows[2] and doc["posted"] == {"posts": 1, "rows": 2, "lines": 0}
    assert _consistency_players(rows, doc["game_sections"]["pit"]["consistency"]) == [("Erik Karlsson", "under")]


def test_the_record_counts_a_posted_row_in_its_section_at_the_posted_price():
    lacombe = _row("Jackson LaCombe", "under", 1.5, price=-103, ev=-1.85, hits=7)
    karl = _karlsson(under_ev=-4.14, over_ev=-0.94)
    sheet = _sheet([lacombe] + karl)
    rec = {"props": {cs.prop_result_key(r): {"y": 1.0 if r["side"] == "under" else 0.0} for r in sheet["rows"]},
           "lines": {}, "counts": {}}
    before = csr.day_record(sheet, rec)
    assert before["sections"]["consistency"]["n"] == 1                       # LaCombe only: the graphic said two
    posted = _post(_sheet([lacombe] + _karlsson(-3.6, -6.0)), "consistency", [lacombe, karl[0]])
    after = csr.day_record(sheet, rec, posted)
    assert after["sections"]["consistency"] == {"w": 2, "l": 0, "n": 2, "units": round(100 / 103 + 100 / 180, 2),
                                                "win_pct": 100.0, "roi_pct": round(100 * round(100 / 103 + 100 / 180, 2) / 2, 1)}


@pytest.fixture()
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(route, "_today", lambda: DAY)
    return app.test_client(), tmp_path


def test_export_records_the_rows_from_the_sheet_and_the_page_pins_them(http):
    client, root = http
    lacombe = _row("Jackson LaCombe", "under", 1.5, price=-103, ev=-1.85, hits=7)
    sheet = _sheet([lacombe] + _karlsson(-3.6, -6.0))
    path = root / "cheatsheets" / "nhl" / f"{DAY}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(sheet), encoding="utf-8")
    ids = [pc.card_id("nhl", DAY, r) for r in sheet["rows"][:2]]
    res = client.post("/api/cheatsheets/posted", json={"sport": "nhl", "date": DAY, "section": "consistency",
                                                       "card_ids": ids + ["0123456789ab"], "line_ids": []})
    body = res.get_json()
    assert res.status_code == 200 and body["rows"] == 2 and body["missing"] == 1
    saved = json.loads((path.parent / f"{DAY}{cs.POSTED_SUFFIX}").read_text(encoding="utf-8"))
    post = saved["posts"][0]
    assert post["section"] == "consistency" and [e["price"] for e in post["rows"]] == [-103, -180]
    assert post["rows"][1]["item"]["player"] == "Erik Karlsson"
    # the board moves: Karlsson's over becomes the better-EV side, and the build drops nothing that was posted
    sheet["rows"] = [lacombe] + _karlsson(-4.14, -0.94)
    path.write_text(json.dumps(sheet), encoding="utf-8")
    page = client.get(f"/cheatsheets?sport=nhl&date={DAY}").get_data(as_text=True)
    data = json.loads(re.search(r"const DATA = (.*?);\n", page).group(1))["nhl"]
    shown = [(data["rows"][i]["player"], data["rows"][i]["side"]) for i in data["sections"]["consistency"]]
    assert shown == [("Jackson LaCombe", "under"), ("Erik Karlsson", "under")]
    assert data["rows"][1]["posted"]["price"] == -180 and "recordPosted(frame" in page
    assert client.post("/api/cheatsheets/posted", json={"sport": "nhl", "date": DAY, "section": "picks",
                                                        "card_ids": ids}).status_code == 400
    assert client.post("/api/cheatsheets/posted", json={"sport": "nhl", "date": DAY, "section": "consistency",
                                                        "card_ids": ["0123456789ab"]}).status_code == 404


def test_reconciled_shared_view_is_exactly_what_was_posted_as_it_was_posted():
    """User 2026-10-22: "after reconciling I need the exported image to only reflect what was shared ... consistency with
    what I'm promoting on X". NHL 10-21: 8 consistency props posted at 11:51 AM CT; the reconciled section led with them
    and then listed what the last build added, and Seth Jones SOG o1.5 showed the last build's -105 BetOnline, not the
    -115 DraftKings on the graphic."""
    lacombe = _row("Jackson LaCombe", "under", 1.5, price=-103, ev=-1.85, hits=7)
    karl = _row("Erik Karlsson", "under", 2.5, price=-180, ev=-3.6, hits=7, event="pit")
    newcomer = _row("Late Add", "under", 0.5, price=-150, ev=-1.0, hits=8)        # entered the section after the post
    sheet = _sheet([lacombe, karl, newcomer])
    import copy

    snap = copy.deepcopy([lacombe, karl])                                          # the graphic is a snapshot
    sheet["posted"] = _post(_sheet(snap), "consistency", snap)
    sheet["reconciled"] = {"props": {cs.prop_result_key(r): {"y": 1.0} for r in sheet["rows"]}, "lines": {}, "counts": {}}
    karl["check"]["price"] = -250                                                  # the price moved after the post
    doc = cs.page_payload([sheet])["nhl"]
    rows = doc["rows"]
    assert ("Late Add", "under") in _consistency_players(rows, doc["sections"]["consistency"])       # pregame view: the build's
    assert _consistency_players(rows, doc["shared"]["sections"]["consistency"]) == [("Jackson LaCombe", "under"), ("Erik Karlsson", "under")]
    assert rows[1]["check"]["price"] == -180                                       # shown as posted, graded as posted
    assert _consistency_players(rows, doc["shared"]["game_sections"]["ana"]["consistency"]) == [("Jackson LaCombe", "under")]
    for key, ids in doc["sections"].items():                                       # a section never posted keeps its rows
        if key != "consistency":
            assert doc["shared"]["sections"].get(key) == ids, key


def test_no_shared_view_before_the_day_is_reconciled_and_rows_show_the_build():
    lacombe = _row("Jackson LaCombe", "under", 1.5, price=-103, ev=-1.85, hits=7)
    sheet = _sheet([lacombe])
    sheet["posted"] = _post(_sheet([lacombe]), "consistency", [lacombe])
    lacombe["check"]["price"] = -130
    doc = cs.page_payload([sheet])["nhl"]
    assert "shared" not in doc and doc["rows"][0]["check"]["price"] == -130


def test_the_reconciled_page_reads_the_shared_sections():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "cheat_sheets.html").read_text(encoding="utf-8")
    assert "const sharedOf = d => (reconciledView(d) && d.shared) ? d.shared : null;" in html
    body = html[html.index("function sectionsFor(d)"):][:300]
    assert "sharedOf(d) || d" in body
    assert "sh.sgp_ids.includes(s.sgp_id)" in html and "const ls = sharedOf(d) || d;" in html


def test_the_record_keeps_all_and_adds_a_shared_value():
    """User 2026-10-22: "actually we should create a new value for shared record vs all". ALL keeps every featured row
    (posted ones pinned in); SHARED is only what went out on a graphic, at the posted price."""
    lacombe = _row("Jackson LaCombe", "under", 1.5, price=-103, ev=-1.85, hits=7)
    newcomer = _row("Late Add", "under", 0.5, price=-150, ev=-1.0, hits=8)        # lost, and was never shared
    sheet = _sheet([lacombe, newcomer])
    rec = {"props": {cs.prop_result_key(lacombe): {"y": 1.0}, cs.prop_result_key(newcomer): {"y": 0.0}},
           "lines": {}, "counts": {}}
    assert "shared" not in csr.day_record(sheet, rec)                              # nothing posted: no shared value
    posted = _post(_sheet([lacombe]), "consistency", [lacombe], price=-110)         # the graphic showed -110
    day = csr.day_record(sheet, rec, posted)
    alls = day["sections"]["consistency"]
    assert (alls["w"], alls["l"], alls["n"]) == (1, 1, 2)                           # ALL: both rows
    shared = day["shared"]["sections"]["consistency"]
    assert (shared["w"], shared["l"], shared["n"]) == (1, 0, 1) and shared["units"] == round(100 / 110, 2)
    assert day["shared"]["featured"]["n"] == 1
    season = csr.season_record([day], generated_at="t")
    scope = season["beta"] if day["beta"] else season["official"]
    assert scope["totals"]["consistency"]["n"] == 2 and scope["shared"]["totals"]["consistency"]["n"] == 1
    assert scope["shared"]["by_sport"]["nhl"]["featured"]["n"] == 1


def test_the_record_page_toggles_all_and_shared():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "cheat_sheets.html").read_text(encoding="utf-8")
    assert 'const REC = {scope: "official", sport: "all", basis: "all"};' in html
    assert 'const scope = shared ? (base.shared || empty) : base;' in html
    assert '[["all", "All featured"], ["shared", "Shared"]]' in html and 'REC.basis = ba.dataset.basis' in html
