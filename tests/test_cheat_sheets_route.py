"""/cheatsheets serves the sheets the generator wrote; it builds nothing on a request (lane `cheat-sheets`).

User 2026-10-14: today's games only, each day kept as a record, a sheet per game, every section exportable as its
own image, and a pick graphic for a single pick -- with no UTC anywhere a viewer looks."""
from __future__ import annotations

import json
import re

import pytest

from syndicate.app import app
from syndicate.blueprints import cheat_sheets as route
from syndicate.features.shared import cheat_sheet_images as images
from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import play_cards as pc

TODAY = "2026-10-14"


def _value_row(**extra):
    row = {"event_id": "e1", "player": "Tyler Allgeier", "team": "ARI", "pos": "RB", "market": "Receptions", "line": 2.5,
           "side": "under", "books_quoting": 4, "fair_method": "consensus", "kickoff_ct": "Sun Oct 18 · 3:05 PM CT",
           "commence_time": "2026-10-14T23:15:00Z", "headshot_url": "https://a.espncdn.com/x.png", "book_prices": {"fd": -139},
           "check": {"verdict": "value", "ev_market": 3.0, "price": -139, "book": "betonlineag", "p_market": 0.6018,
                     "p_model": 0.5456, "form10": {"games": 10, "hits": 9, "rate": 0.9, "values": [2, 2, 2, 4, 2, 2, 1, 0, 1, 0]},
                     "reasons": []}}
    row.update(extra)
    return row


def _sheet(sport="nfl", day=TODAY, **extra):
    rows = [_value_row(),
            {"event_id": "e1", "player": "Bench Guy", "commence_time": "2026-10-14T23:15:00Z", "check": {"verdict": "neutral"}},
            _value_row(event_id="e2", player="Other Game", check={"verdict": "streak_priced_in", "ev_posterior": -2.0, "price": -120})]
    doc = {"sport": sport, "date": day, "generated_at": "2026-10-14T23:39:44Z", "rows": rows,
           "sections": cs.sections(rows),
           "games": [{"event_id": "e1", "matchup": "Arizona Cardinals @ Los Angeles Rams", "commence_time": "2026-10-14T23:15:00Z",
                      "home_team": "Los Angeles Rams", "away_team": "Arizona Cardinals"},
                     {"event_id": "e2", "matchup": "A @ B", "commence_time": "2026-10-15T00:15:00Z"}]}
    doc.update(extra)
    return doc


@pytest.fixture()
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(route, "_today", lambda: TODAY)
    return app.test_client(), tmp_path


def _write(root, doc):
    path = root / "cheatsheets" / doc["sport"] / f"{doc['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _js(html: str, name: str):
    return json.loads(re.search(rf"const {name} = (.*?)(?: \|\| \{{mode: \"static\"\}})?;\n", html).group(1))


def test_the_page_is_todays_sheet_with_the_site_menu_and_past_days_as_records(http):
    client, root = http
    _write(root, _sheet(day="2026-10-13", generated_at="2026-10-13T21:30:00Z"))
    _write(root, _sheet())
    _write(root, _sheet("nhl"))
    html = client.get("/cheatsheets").data.decode()
    assert "standalone-app-header" in html and 'standalone-app-header__link--active" href="/cheatsheets"' in html
    data, meta = _js(html, "DATA"), _js(html, "META")
    assert list(data) == ["nfl", "nhl"] and data["nfl"]["date"] == TODAY
    logos = meta.pop("logos")                       # each sport's badge holds its ball; hockey's, a puck
    assert logos["nfl"] == "/static/brand/syndicate_roi_badge_football.webp" and logos["nhl"] == "/static/brand/syndicate_roi_badge_puck.webp"
    assert meta == {"mode": "app", "date": TODAY, "today": TODAY, "beta": True, "dates": [TODAY, "2026-10-13"]}
    record = client.get("/cheatsheets?date=2026-10-13").data.decode()
    assert _js(record, "DATA")["nfl"]["generated_at"] == "2026-10-13T21:30:00Z"
    assert "__LOGO_SRC__" not in html and "<!--__SITE" not in html and "/*__META__*/" not in html
    # An exported image re-counts what it exports (user 2026-10-15: "make sure the counts match what is exported").
    assert "recountExport(body, d);" in html and "function recountExport(sec, d)" in html


def test_no_sheet_yet_today_is_an_empty_page_not_yesterdays(http):
    client, root = http
    _write(root, _sheet(day="2026-10-13"))
    html = client.get("/cheatsheets").data.decode()
    assert _js(html, "DATA") == {} and "publish at 8:30 AM CT" in html
    assert client.get("/cheatsheets?date=yesterday").status_code == 400


def test_each_game_gets_its_own_sections_over_all_its_rows(http):
    client, root = http
    _write(root, _sheet())
    nfl = _js(client.get("/cheatsheets").data.decode(), "DATA")["nfl"]
    assert len(nfl["rows"]) == 3 and "book_prices" not in nfl["rows"][0]
    assert nfl["game_sections"]["e1"]["value"] == [0] and nfl["game_sections"]["e2"]["streaks_priced_in"] == [2]
    assert nfl["games"][0]["props"] == 2 and nfl["rows"][0]["card_ok"] is True and nfl["rows"][1]["card_ok"] is False
    assert nfl["rows"][0]["card_id"] == pc.card_id("nfl", TODAY, _value_row())


def test_a_pick_graphic_exists_only_where_the_price_clears_the_fair(http):
    client, root = http
    _write(root, _sheet())
    good = pc.card_id("nfl", TODAY, _value_row())
    page = client.get(f"/cheatsheets/card/nfl/{TODAY}/{good}")
    html = page.data.decode()
    assert page.status_code == 200 and "TYLER ALLGEIER" in html.upper() and "UNDER 2.5 RECEPTIONS" in html
    assert 'id="pc-toolbar"' in html and "FREE PLAY #1" in html and "$" not in html.split("<script")[0].replace("$$", "")
    bench = pc.card_id("nfl", TODAY, _sheet()["rows"][1])
    refused = client.get(f"/cheatsheets/card/nfl/{TODAY}/{bench}")
    assert refused.status_code == 404 and "does not clear the fair" in refused.get_json()["error"]
    assert client.get(f"/cheatsheets/card/nfl/{TODAY}/zzz").status_code == 404


def test_an_exported_graphic_is_logged_once_to_the_graded_record(http):
    client, root = http
    _write(root, _sheet())
    good = pc.card_id("nfl", TODAY, _value_row())
    first = client.post("/api/cheatsheets/cards", json={"sport": "nfl", "date": TODAY, "card_id": good}).get_json()
    again = client.post("/api/cheatsheets/cards", json={"sport": "nfl", "date": TODAY, "card_id": good}).get_json()
    assert first["logged"] is True and again["logged"] is False and first["number"] == 1
    ledger = pc.read_ledger(pc.ledger_path(root))
    assert len(ledger) == 1 and ledger[0]["source"] == "exported" and ledger[0]["price"] == -139 and ledger[0]["result"] is None
    assert ledger[0]["beta"] is True                                        # 10-14 is the beta day: never in the record
    bench = pc.card_id("nfl", TODAY, _sheet()["rows"][1])
    assert client.post("/api/cheatsheets/cards", json={"sport": "nfl", "date": TODAY, "card_id": bench}).status_code == 404


def test_cached_images_are_served_by_key_only(http):
    client, root = http
    cache = images.cache_dir(root)
    cache.mkdir(parents=True)
    key = images.cache_key("https://a.espncdn.com/x.png", 96)
    (cache / f"{key}.bin").write_bytes(b"RIFF....WEBPVP8 ")
    got = client.get(f"/cheatsheets/img/{key}.webp")
    assert got.status_code == 200 and got.mimetype == "image/webp"
    assert client.get("/cheatsheets/img/not-a-key.webp").status_code == 400
    assert client.get(f"/cheatsheets/img/{'0' * 40}.webp").status_code == 404


def test_the_api_lists_and_serves_sheets_as_written(http):
    client, root = http
    _write(root, _sheet())
    assert client.get("/api/cheatsheets").get_json()["sports"] == {"nfl": [TODAY]}
    assert client.get(f"/api/cheatsheets/nfl/{TODAY}").get_json()["rows"][1]["player"] == "Bench Guy"
    assert client.get("/api/cheatsheets/nfl/2026-10-15").status_code == 404


def test_no_string_in_the_data_can_close_the_script():
    html = cs.render_page("<script>const DATA = /*__DATA__*/null;\n</script>", [_sheet(rows=[{"player": "</script><b>x"}])],
                          logo_src="/l.webp")
    assert "</script><b>" not in html and "<\\/script>" in html


def test_the_template_has_exports_game_sheets_graphics_and_no_utc():
    text = route.TEMPLATE.read_text(encoding="utf-8")
    for needle in ("data-export", "game_sections", "/cheatsheets/card/", "data-game", "html-to-image@1.11.11", "America/Chicago",
                   "r.kickoff_ct", "r.headshot_src", "r.team_logo_src", "slateBlock", "<!--__SITE_HEADER__-->", "/*__META__*/null"):
        assert needle in text, needle
    assert "UTC" not in text and "k = ${" not in text and "provisional" not in text


def test_tomorrow_is_offered_as_an_early_look_and_game_lines_reach_the_page(http):
    client, root = http
    lines = [{"event_id": "e1", "market": "spreads", "side": "home", "side_name": "Los Angeles Rams", "line": -3.5,
              "check": {"verdict": "value", "ev_market": 3.1, "price": 105}},
             {"event_id": "e1", "market": "totals", "side": "over", "side_name": "over", "line": 44.5,
              "check": {"verdict": "neutral", "ev_market": -2.0, "price": -110}}]
    _write(root, _sheet(day="2026-10-15", rows=[], sections={}, game_lines=lines))
    _write(root, _sheet())
    meta = _js(client.get("/cheatsheets").data.decode(), "META")
    assert meta["dates"] == ["2026-10-15", TODAY]                              # tomorrow is offered
    nfl = _js(client.get("/cheatsheets?date=2026-10-15").data.decode(), "DATA")["nfl"]   # a lines-only sheet still shows
    assert nfl["game_line_sections"]["value"] == [0] and nfl["game_line_sections_by_game"]["e1"]["all"] == [0, 1]


def test_a_reconciled_day_serves_each_bets_result_and_the_toggle(http):
    # User 2026-10-15: "a button that toggles between pregame sheets and reconciled sheets". The page reads the file
    # the reconcile script wrote; with none, the sheet is served exactly as published.
    client, root = http
    doc = _sheet(day="2026-10-13")
    _write(root, doc)
    page = client.get("/cheatsheets?date=2026-10-13").get_data(as_text=True)
    assert "result" not in _js(page, "DATA")["nfl"]["rows"][0]
    rec = {"sport": "nfl", "date": "2026-10-13", "reconciled_at": "2026-10-14T13:00:00+00:00", "source": "test",
           "props": {cs.prop_result_key(doc["rows"][0]): {"y": 1.0}}, "lines": {},
           "counts": {"props": 3, "props_graded": 1, "lines": 0, "lines_graded": 0}}
    (root / "cheatsheets" / "nfl" / "2026-10-13.reconciled.json").write_text(json.dumps(rec), encoding="utf-8")
    page = client.get("/cheatsheets?date=2026-10-13&view=reconciled").get_data(as_text=True)
    data = _js(page, "DATA")["nfl"]
    assert data["rows"][0]["result"] == {"y": 1.0, "units": round(100 / 139, 3)}             # 1 unit at -139
    assert data["rows"][1]["result"] is None and data["reconciled"]["counts"]["props_graded"] == 1
    assert 'id="viewbar"' in page and 'data-view="reconciled"' in page and "function applyResults" in page
    assert _js(page, "META")["dates"] == ["2026-10-14", "2026-10-13"]                       # the results file is not a date


def test_a_syndicate_pick_gets_a_pick_graphic_and_a_picks_only_sheet_is_served(http):
    # User 2026-10-15: "add the suggested opps as a picks section with pick graphics".
    client, root = http
    pick = {"pick_id": "l2_129acb8c9c927fb9", "kind": "game", "sport": "nba", "event_id": "e9", "matchup": "Toronto Raptors @ New York Knicks",
            "display_name": "New York Knicks", "market": "spreads", "side": "home", "line": -5.5, "segment": "full", "price": 107,
            "book": "betrivers", "books": 2, "fair_price": 100, "p_market": 0.5, "p_model": 0.479, "ev_pct": 3.5,
            "detail": "Our sim has New York Knicks -5.5 at 47.9%; the no-vig market across 2 books says 50.0%. Season metrics: Net rating NYK +4.0.",
            "bet": "New York Knicks -5.5", "commence_time": "2026-10-14T23:30:00Z"}
    _write(root, {"sport": "nba", "date": TODAY, "generated_at": "2026-10-14T13:30:00Z", "rows": [], "games": [], "picks": [pick], "picks_only": True})
    page = client.get("/cheatsheets").get_data(as_text=True)
    assert _js(page, "DATA")["nba"]["picks"][0]["bet"] == "New York Knicks -5.5" and "function picksBlock" in page
    card = client.get(f"/cheatsheets/card/nba/{TODAY}/l2_129acb8c9c927fb9")
    assert card.status_code == 200
    html = card.get_data(as_text=True)
    # The side is the headline and its number the bet line (the 2026-10-15 X-style card); the strip repeats both.
    assert ">New York Knicks</div>" in html and ">-5.5 spread</div>" in html and "New York Knicks -5.5 spread" in html
    # Sim 47.9% vs market 50%: the sim does not back it, so it is a PRICE PLAY -- no sim number on its graphic.
    # The brand-spec card (2026-10-16): its dashboard is the MARKET outlook, never SmartSim, on a price play.
    assert "Market outlook" in html and "SmartSim outlook" not in html and "Season: Net rating NYK +4.0" in html and "Our sim" not in html
    assert ">PRICE PLAY</span>" in html and "PRICE PLAY #" not in html                              # no number
    assert "Our sim has New York Knicks" not in html.split("Why we like it", 1)[1].split("</ul>", 1)[0]   # never the reason
    assert "Only 2 books quote it" in html
    assert client.get(f"/cheatsheets/card/nba/{TODAY}/l2_ffffffffffffffff").status_code == 404
