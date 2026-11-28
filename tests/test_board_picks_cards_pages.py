"""#861 step 1g: the NBA / NCAAF / NFL / NCAAB game cards carry the board's pick first, the NBA props page and the NFL
season betting card lead with the board's picks, and the board joins a card to its game when the two feeds spell the
clubs differently.

Measured 2026-11-27 23:51-23:53Z (findings Reading 9): the NCAAF cards joined 0 of 69 games on the folded pair (the
board spells "Kent State Golden Flashes", the card "Kent State"); the NBA cards' tiles showed only the sim's EV; the NBA
props page was empty all season; the NFL betting card showed the 12 SmartSim candidates and no board."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from syndicate.features.shared import board_game_picks as bgp

REPO_ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-11-27"
SATURDAY = "2026-11-28T20:30:00Z"  # 2:30 PM CST Saturday
SUNDAY = "2026-11-29T18:00:00Z"  # 12 PM CST Sunday
_REAL_UPCOMING = bgp.upcoming_view
_REAL_SPORT_VIEW = bgp.sport_view

# A stand-in for `team_aliases.chip_join_key`: the CFBD-style canonical club for both feeds' spellings.
_CLUBS = {
    "Kent State": "Kent State", "Kent State Golden Flashes": "Kent State",
    "Buffalo": "Buffalo", "Buffalo Bulls": "Buffalo",
    "Miami (OH)": "Miami (OH)", "Miami (OH) RedHawks": "Miami (OH)",
    "Ohio": "Ohio", "Ohio Bobcats": "Ohio",
}


def _row(**kw):
    base = {
        "sport": "ncaaf",
        "kind": "game",
        "market": "spreads",
        "side": "home",
        "line": -3.5,
        "segment": "full",
        "away_team": "Kent State Golden Flashes",
        "home_team": "Buffalo Bulls",
        "commence_time": SATURDAY,
        "game_state": "pregame",
        "is_live": False,
        "ev_pct": 4.1,
        "score_v2": {"ev_net_pct": 4.1, "fee_per_contract": 0.0},
        "score": {"score": 2.0},
        "suggested": True,
        "suggested_reasons": [],
        "quote": {"bookmaker": "fanduel", "price": -110, "fair_probability": 0.55, "books_quoting": 7},
    }
    base.update(kw)
    return base


def _board(rows):
    return {"rows": rows, "written_at": "2026-11-27T23:47:37Z"}


def _reader(payload):
    return lambda d: payload if d == DAY else None


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    bgp.clear_cache()
    monkeypatch.setattr(bgp, "_central_today", lambda: DAY)
    yield
    bgp.clear_cache()


@pytest.fixture()
def clubs(monkeypatch):
    import syndicate.features.shared.team_aliases as ta

    monkeypatch.setattr(ta, "chip_join_key", lambda sport, value: _CLUBS.get(str(value)))
    bgp.clear_cache()


# --- the canonical club join ----------------------------------------------------------------------------------------


def test_the_canonical_club_joins_a_card_the_folded_pair_misses(clubs):
    view = bgp.sport_view("ncaaf", "2026-11-28", reader=_reader(_board([_row()])))
    assert bgp.game_key("Kent State", "Buffalo") not in view._by_game
    lines = view.game_lines("Kent State", "Buffalo")
    assert [x.side_label for x in lines] == ["Buffalo Bulls -3.5"]


def test_without_the_canonical_club_the_ncaaf_card_does_not_join(monkeypatch):
    """off != on: the same board and card, with the resolver answering nothing (as for a sport with no map)."""
    import syndicate.features.shared.team_aliases as ta

    monkeypatch.setattr(ta, "chip_join_key", lambda sport, value: None)
    bgp.clear_cache()
    view = bgp.sport_view("ncaaf", "2026-11-28", reader=_reader(_board([_row()])))
    assert view.game_lines("Kent State", "Buffalo") == ()


def test_the_exact_pair_still_wins_and_the_canonical_pair_comes_before_one_side(clubs):
    # Two board games that day: the card's own (both clubs resolve) and one sharing the card's raw home spelling.
    rows = [_row(), _row(away_team="Ohio Bobcats", home_team="Buffalo", suggested=False, ev_pct=-2.0)]
    view = bgp.sport_view("ncaaf", "2026-11-28", reader=_reader(_board(rows)))
    assert view.resolve_game("Ohio Bobcats", "Buffalo") == bgp.game_key("Ohio Bobcats", "Buffalo")
    # The one-side rule alone would pick the Ohio game (the only board game with raw home "buffalo").
    assert view.resolve_game("Kent State", "Buffalo") == bgp.game_key("Kent State Golden Flashes", "Buffalo Bulls")


def test_one_resolved_side_joins_when_exactly_one_board_game_has_that_club(clubs):
    view = bgp.sport_view("ncaaf", "2026-11-28", reader=_reader(_board([_row()])))
    assert view.resolve_game("Some FCS School", "Buffalo") == bgp.game_key("Kent State Golden Flashes", "Buffalo Bulls")
    assert view.resolve_game("Some FCS School", "Another FCS School") is None


def test_a_resolver_that_raises_costs_nothing(monkeypatch):
    import syndicate.features.shared.team_aliases as ta

    def boom(sport, value):
        raise RuntimeError("registry CSV unreadable")

    monkeypatch.setattr(ta, "chip_join_key", boom)
    bgp.clear_cache()
    view = bgp.sport_view("ncaaf", "2026-11-28", reader=_reader(_board([_row()])))
    assert bgp.club_key("ncaaf", "Kent State") is None
    assert view.game_lines("Kent State Golden Flashes", "Buffalo Bulls")  # the exact pair still joins
    assert view.game_lines("Kent State", "Buffalo") == ()


def test_the_real_ncaaf_resolver_strips_mascots_when_its_registry_is_present():
    """The fleet's resolver (`chip_join_key` -> the CFBD registry). Skipped in a checkout without the NCAAF data."""
    bgp.clear_cache()
    if bgp.club_key("ncaaf", "Kent State") is None:
        pytest.skip("the NCAAF team registry is not on disk here")
    assert bgp.club_key("ncaaf", "Kent State Golden Flashes") == bgp.club_key("ncaaf", "Kent State")
    assert bgp.club_key("ncaaf", "Miami (OH) RedHawks") == bgp.club_key("ncaaf", "Miami (OH)")
    assert bgp.club_key("ncaaf", "Miami (OH)") != bgp.club_key("ncaaf", "Miami")


# --- the game's day and the kind cut ----------------------------------------------------------------------------------


def test_a_weekly_card_takes_its_own_day_and_a_label_date_falls_back_to_today():
    assert bgp._game_day({"startTime": "2026-11-29T18:00Z"}, "2026 Week 13") == "2026-11-29"
    assert bgp._game_day({"start_time_utc": "2026-11-28T01:00:00Z"}, DAY) == "2026-11-27"  # 7 PM CST the 27th
    assert bgp._game_day({}, "2026 Week 13") == DAY
    assert bgp._game_day({"startTime": "TBD"}, "2026-11-28") == DAY


def test_only_kind_keeps_every_game():
    rows = [_row(), _row(kind="prop", market="player_points", player_name="Luka Doncic", side="over", line=32.5,
                         sport="nba", away_team="Los Angeles Lakers", home_team="San Antonio Spurs",
                         commence_time="2026-11-28T01:00:00Z"),
            _row(sport="nba", away_team="Los Angeles Lakers", home_team="San Antonio Spurs",
                 commence_time="2026-11-28T01:00:00Z")]
    view = bgp.sport_view("nba", DAY, reader=_reader(_board(rows)))
    assert len(view.lines) == 2
    assert [x.kind for x in view.only_kind("prop").lines] == ["prop"]


# --- attach_board_picks on the weekly cards ---------------------------------------------------------------------------


def _card(away, home, start, tiles=None):
    return {"away": {"name": away}, "home": {"name": home}, "startTime": start,
            "market_tiles": tiles if tiles is not None else [{"label": "Spread", "title": "LAR -2.5",
                                                               "sub": "Model LAR -5.0 · +2.5 vs market"}]}


def test_weekly_cards_get_the_board_tile_from_each_games_day(clubs):
    payload = _board([_row(sport="nfl", away_team="Los Angeles Rams", home_team="Carolina Panthers",
                           commence_time=SUNDAY, side="away", line=-2.5)])
    ctx = {"date": "2026 Week 13", "games": [_card("Los Angeles Rams", "Carolina Panthers", "2026-11-29T18:00Z"),
                                             _card("Detroit Lions", "Chicago Bears", "2026-11-27T17:30Z")]}
    out = bgp.attach_board_picks(ctx, "nfl", reader=_reader(payload))
    first, second = out["games"]
    assert [t["label"] for t in first["market_tiles"]] == ["Board pick", "Spread"]
    assert first["market_tiles"][0]["title"] == "Los Angeles Rams -2.5"
    assert first["board_picks"][0]["side_label"] == "Los Angeles Rams -2.5"
    assert second["market_tiles"][0]["title"] == "No board pick"
    assert set(out["board_view"]) == {"2026-11-29", "2026-11-27"}


# --- the routes (reachability: each route calls the helper) -----------------------------------------------------------


@pytest.fixture()
def client():
    from syndicate.app import create_app

    return create_app().test_client()


def _patch_board(monkeypatch, rows):
    payload = _board(rows)
    monkeypatch.setattr(bgp, "upcoming_view", lambda sport, **kw: _REAL_UPCOMING(sport, reader=_reader(payload)))
    monkeypatch.setattr(bgp, "sport_view", lambda sport, day=None, **kw: _REAL_SPORT_VIEW(sport, day, reader=_reader(payload)))


def _cards_context(cards, date="2026-11-27"):
    return {"date": date, "games": cards, "header_stats": [], "module_links": [], "empty_state": None}


def test_ncaaf_cards_route_and_page_put_the_board_first(monkeypatch, client, clubs):
    import syndicate.blueprints.ncaaf as ncaaf_bp

    monkeypatch.setattr(ncaaf_bp, "build_smartsim_cards_page_context",
                        lambda week: _cards_context([_card("Kent State", "Buffalo", SATURDAY)], date="2026 Week 13"))
    _patch_board(monkeypatch, [_row()])
    body = client.get("/ncaaf/api/cards").get_json()
    tiles = body["games"][0]["market_tiles"]
    assert [t["label"] for t in tiles][:2] == ["Board pick", "Spread"]
    assert tiles[0]["title"] == "Buffalo Bulls -3.5"


def test_nfl_cards_route_puts_the_board_first(monkeypatch, client):
    import syndicate.blueprints.nfl as nfl_bp

    monkeypatch.setattr(nfl_bp, "build_cards_page_context", lambda week, season=None: _cards_context(
        [_card("Los Angeles Rams", "Carolina Panthers", "2026-11-29T18:00Z")], date="2026 Week 13"))
    _patch_board(monkeypatch, [_row(sport="nfl", away_team="Los Angeles Rams", home_team="Carolina Panthers",
                                    commence_time=SUNDAY, side="away", line=-2.5)])
    body = client.get("/nfl/api/cards").get_json()
    assert body["games"][0]["market_tiles"][0] == {
        "label": "Board pick", "title": "Los Angeles Rams -2.5", "sub": "EV +4.1% at fanduel -110"}


def test_ncaab_cards_routes_put_the_board_first(monkeypatch, client):
    import syndicate.blueprints.ncaab as ncaab_bp

    monkeypatch.setattr(ncaab_bp, "build_cards_page_context", lambda day: _cards_context(
        [_card("Virginia Cavaliers", "Xavier Musketeers", "2026-11-28T01:00:00Z")]))
    _patch_board(monkeypatch, [_row(sport="ncaab", market="totals", side="over", line=141.5,
                                    away_team="Virginia Cavaliers", home_team="Xavier Musketeers",
                                    commence_time="2026-11-28T01:00:00Z")])
    body = client.get(f"/ncaab/api/cards?date={DAY}").get_json()
    assert body["games"][0]["market_tiles"][0]["title"] == "Over 141.5"
    html = client.get(f"/ncaab/cards?date={DAY}&client=board").get_data(as_text=True)
    assert html.index("Board pick") < html.index("Model LAR -5.0")


def test_nba_cards_api_carries_the_board_tile_for_the_client(monkeypatch, client):
    import syndicate.blueprints.nba as nba_bp

    monkeypatch.setattr(nba_bp, "build_cards_api_payload", lambda d, **kw: _cards_context(
        [_card("Los Angeles Lakers", "San Antonio Spurs", "2026-11-28T01:00:00Z",
               tiles=[{"label": "Away ML", "title": "+181", "sub": "LAL @ SAS"}])]))
    _patch_board(monkeypatch, [_row(sport="nba", market="h2h", side="home", line=None,
                                    away_team="Los Angeles Lakers", home_team="San Antonio Spurs",
                                    commence_time="2026-11-28T01:00:00Z")])
    body = client.get(f"/nba/api/cards?date={DAY}").get_json()
    assert [t["label"] for t in body["games"][0]["market_tiles"]] == ["Board pick", "Away ML"]
    assert body["games"][0]["market_tiles"][0]["title"] == "San Antonio Spurs"


def test_nba_props_route_and_page_lead_with_the_board(monkeypatch, client):
    import syndicate.blueprints.nba as nba_bp
    from syndicate.features.shared.rank_board import build_rank_page_context

    empty = {"eyebrow": "NBA props", "title": "No stored NBA props were available for this date", "body": "none",
             "list_items": []}

    def fake(d, filters=None):
        ctx = build_rank_page_context(selected_date=DAY, route_path="/nba/prop-ladders", intro_title="NBA Props",
                                      intro_body="x", aria_label="x", source_path="x", source_title="x", rank_cards=[],
                                      using_sample_data=False, header_stats=[{"label": "Cards", "value": "0"}],
                                      module_links=[])
        ctx["empty_state"] = dict(empty)
        return ctx

    monkeypatch.setattr(nba_bp, "build_props_page_context", fake)
    _patch_board(monkeypatch, [
        _row(sport="nba", kind="prop", market="player_points", player_name="Luka Doncic", side="over", line=32.5,
             away_team="Los Angeles Lakers", home_team="San Antonio Spurs", commence_time="2026-11-28T01:00:00Z"),
        _row(sport="nba", market="h2h", side="home", line=None, away_team="Los Angeles Lakers",
             home_team="San Antonio Spurs", commence_time="2026-11-28T01:00:00Z")])
    body = client.get(f"/nba/api/props?date={DAY}").get_json()
    assert [c["title"] for c in body["rank_cards"]] == ["Luka Doncic Over 32.5 points"]  # props only, not the h2h
    assert body["empty_state"] is None and body["header_stats"][0] == {"label": "Board picks", "value": "1"}
    html = client.get(f"/nba/props?date={DAY}").get_data(as_text=True)
    assert html.index("Luka Doncic Over 32.5") < html.index("Sim view: not the board")
    assert "No stored NBA props were available" in html  # the empty file's reason, under the sim's label
    # A player focus is the page's own ladder view, unchanged.
    focus = client.get(f"/nba/api/props?date={DAY}&player=Luka+Doncic").get_json()
    assert focus["rank_cards"] == [] and focus["empty_state"]["title"] == empty["title"]


def _betting_card_context(season, week):
    from syndicate.features.shared.rank_board import build_rank_page_context

    sim = {"title": "JAX vs TEN SmartSim 2.0 candidate", "badge": "82.7% win prob", "eyebrow": "SmartSim 2.0"}
    ctx = build_rank_page_context(selected_date=DAY, route_path="/x", intro_title="x", intro_body="x", aria_label="x",
                                  source_path="x", source_title="x", rank_cards=[sim], using_sample_data=False,
                                  header_stats=[{"label": "Cards", "value": "1"}], module_links=[])
    ctx.update({"season": season, "week": week, "available_weeks": [week], "rows": 1, "data": [], "groups": {}})
    return ctx


def test_nfl_betting_card_leads_with_the_board_and_a_past_season_says_why(monkeypatch, client):
    import syndicate.blueprints.nfl as nfl_bp

    monkeypatch.setattr(nfl_bp, "build_betting_card_page_context",
                        lambda season, week, sort="": _betting_card_context(season, week if week else 12))
    monkeypatch.setattr(nfl_bp, "latest_season", lambda: 2026)
    monkeypatch.setattr(nfl_bp, "default_week", lambda season=None: 12)
    monkeypatch.setattr(nfl_bp, "_selected_week", lambda season: 12)
    _patch_board(monkeypatch, [_row(sport="nfl", away_team="Los Angeles Rams", home_team="Carolina Panthers",
                                    commence_time=SUNDAY, side="away", line=-2.5)])
    body = client.get("/nfl/api/season/2026/betting-card").get_json()
    assert [c["source"] for c in body["rank_cards"]] == ["board"]
    keys = [s["key"] for s in body["card_sections"]]
    assert keys[0] == "board" and body["season"] == 2026 and body["week"] == 12
    html = client.get("/nfl/season/2026/betting-card").get_data(as_text=True)
    assert html.index("Los Angeles Rams -2.5") < html.index("SmartSim view: not the board")
    past = client.get("/nfl/api/season/2025/betting-card").get_json()
    assert past["rank_cards"] == []
    assert "no picks for 2025 Week 12" in past["card_sections"][0]["note"]


# --- the NBA cards client draws the tile ------------------------------------------------------------------------------


def test_the_nba_cards_client_draws_the_board_tile_first_and_labels_the_sims():
    js = (REPO_ROOT / "syndicate" / "static" / "nba" / "cards_source.js").read_text(encoding="utf-8")
    row = js[js.index('<div class="cards-market-row">'):]
    assert row.index("${renderBoardPickTile(game)}") < row.index("renderMarketTile('Moneyline'")
    assert "Sim win ${fmtPercent(pick.probability, 0)} | Sim EV ${fmtPercentValue(pick.ev)}" in js
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    start = js.index("  function renderBoardPickTile(game) {")
    end = js.index("\n  }\n", start) + 4
    script = (
        "const safeArray = (v) => Array.isArray(v) ? v : [];\n"
        "const escapeHtml = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');\n"
        + js[start:end]
        + "\nconst on = renderBoardPickTile({market_tiles: [{label: 'Board pick', title: 'San Antonio Spurs ML',"
          " sub: 'EV +4.1% at -110 | +2 more'}, {label: 'Away ML', title: '+181'}]});\n"
          "const off = renderBoardPickTile({market_tiles: [{label: 'Away ML', title: '+181'}]});\n"
          "console.log(JSON.stringify({on, off}));\n"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60, check=True)
    import json

    drawn = json.loads(out.stdout)
    assert 'data-source="board"' in drawn["on"] and "San Antonio Spurs ML" in drawn["on"] and "+2 more" in drawn["on"]
    assert drawn["off"] == ""
