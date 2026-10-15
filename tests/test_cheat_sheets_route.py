"""/cheatsheets serves the sheets the generator wrote; it builds nothing on a request (lane `cheat-sheets`)."""
from __future__ import annotations

import json
import re

import pytest

from syndicate.app import app
from syndicate.blueprints import cheat_sheets as route
from syndicate.features.shared import cheat_sheets as cs


def _sheet(sport="nfl", day="2026-10-14", **extra):
    rows = [{"event_id": "e1", "player": "Tyler Allgeier", "team": "ATL", "pos": "RB", "market": "Receptions", "line": 2.5,
             "side": "under", "kickoff_ct": "Sun Oct 18 · 3:05 PM CT", "headshot_url": "https://a.espncdn.com/x.png",
             "team_logo": "https://a.espncdn.com/atl.png", "check": {"verdict": "value", "ev_market": 3.0}},
            {"event_id": "e1", "player": "Bench Guy", "check": {"verdict": "neutral"}}]
    doc = {"sport": sport, "date": day, "generated_at": "2026-10-14T23:39:44Z", "rows": rows,
           "sections": {"value": [0], "streaks_with_room": [], "streaks_priced_in": [], "shop_gaps": []},
           "games": [{"event_id": "e1", "matchup": "Arizona Cardinals @ Los Angeles Rams", "kickoff_ct": "Sun Oct 18 · 3:05 PM CT",
                      "home_logo": "https://a.espncdn.com/lar.png", "away_logo": "https://a.espncdn.com/ari.png"}],
           "groups_built": 1, "groups_on_board": 1, "method": {"prior_strength_k": 40, "k_is_provisional": True}}
    doc.update(extra)
    return doc


@pytest.fixture()
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_sheet_dir", lambda: tmp_path / "cheatsheets")
    return app.test_client(), tmp_path / "cheatsheets"


def _write(root, doc):
    path = root / doc["sport"] / f"{doc['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _data(html: str) -> dict:
    return json.loads(re.search(r"const DATA = (.*?);\n", html).group(1))


def test_the_page_serves_the_newest_sheet_per_sport_with_the_site_menu(http):
    client, root = http
    _write(root, _sheet(day="2026-10-13", generated_at="old"))
    _write(root, _sheet())
    _write(root, _sheet("nhl"))
    page = client.get("/cheatsheets")
    html = page.data.decode()
    assert page.status_code == 200 and "standalone-app-header" in html and ">Cheatsheets</a>" in html
    assert 'standalone-app-header__link--active" href="/cheatsheets"' in html
    data = _data(html)
    assert list(data) == ["nfl", "nhl"] and data["nfl"]["generated_at"] == "2026-10-14T23:39:44Z"
    assert len(data["nfl"]["rows"]) == 1 and data["nfl"]["games"][0]["props"] == 2 and data["nfl"]["rows_on_sheet"] == 2
    assert "__LOGO_SRC__" not in html and "<!--__SITE" not in html


def test_a_date_selects_that_day_and_an_unknown_day_is_an_empty_page(http):
    client, root = http
    _write(root, _sheet(day="2026-10-13", generated_at="old"))
    _write(root, _sheet())
    assert _data(client.get("/cheatsheets?date=2026-10-13").data.decode())["nfl"]["generated_at"] == "old"
    empty = client.get("/cheatsheets?date=2026-01-01")
    assert empty.status_code == 200 and _data(empty.data.decode()) == {} and "No cheat sheet has been published" in empty.data.decode()
    assert client.get("/cheatsheets?date=yesterday").status_code == 400


def test_the_api_lists_and_serves_sheets_as_written(http):
    client, root = http
    _write(root, _sheet())
    assert client.get("/api/cheatsheets").get_json()["sports"] == {"nfl": ["2026-10-14"]}
    assert client.get("/api/cheatsheets/nfl/2026-10-14").get_json()["rows"][1]["player"] == "Bench Guy"
    assert client.get("/api/cheatsheets/nfl/2026-10-15").status_code == 404
    assert client.get("/api/cheatsheets/../2026-10-14").status_code in (400, 404)


def test_no_string_in_the_data_can_close_the_script():
    html = cs.render_page("<script>const DATA = /*__DATA__*/null;\n</script>", [_sheet(rows=[{"player": "</script><b>x"}])],
                          logo_src="/l.webp")
    assert "</script><b>" not in html and "<\\/script>" in html


def test_the_template_shows_time_team_position_logos_and_headshots():
    text = route.TEMPLATE.read_text(encoding="utf-8")
    for needle in ("r.kickoff_ct", "r.team_logo", "r.headshot_url", "r.pos", "r.opponent_logo", "g.home_logo", "g.away_logo",
                   "slateBlock", "<!--__SITE_HEADER__-->", "__LOGO_SRC__", "/*__DATA__*/null"):
        assert needle in text, needle
