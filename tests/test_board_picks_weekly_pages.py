"""#861 step 1f: the NFL props page, and the NFL / NCAAF / NBA picks pages, lead with the board's picks; the page's own
cards follow as a labelled view, and every NFL rate card carries the board's verdict on the same line of the same game.

Measured 2026-11-27 (findings Reading 8): `/nfl/props` headlined 2,189 rate cards at up to +50.9% "edge", 0 of the top
50 board Suggested; the NFL, NCAAF and NBA picks pages showed none of the board's picks."""

from __future__ import annotations

import pytest

from syndicate.features.shared import board_game_picks as bgp

DAY = "2026-11-27"
SUNDAY = "2026-11-29T18:00:00Z"  # 12 PM CST Sunday
MONDAY = "2026-12-01T01:15:00Z"  # 7:15 PM CST Monday 11-30
_REAL_UPCOMING = bgp.upcoming_view
_REAL_SPORT_VIEW = bgp.sport_view


def _row(**kw):
    base = {
        "sport": "nfl",
        "kind": "prop",
        "market": "Receptions",
        "player_name": "David Montgomery",
        "side": "over",
        "line": 1.5,
        "segment": "full",
        "away_team": "Baltimore Ravens",
        "home_team": "Houston Texans",
        "commence_time": SUNDAY,
        "game_state": "pregame",
        "is_live": False,
        "ev_pct": 5.23,
        "score_v2": {"ev_net_pct": 5.23, "fee_per_contract": 0.0},
        "score": {"score": 2.0},
        "suggested": True,
        "suggested_reasons": [],
        "quote": {"bookmaker": "fanduel", "price": -120, "fair_probability": 0.57, "books_quoting": 8},
    }
    base.update(kw)
    return base


def _fehoko(**kw):
    return _row(player_name="Simi Fehoko", side="under", line=1.5, suggested=False,
                suggested_reasons=["ev_below_min", "ev_net_of_fee_below_min"], ev_pct=-1.47,
                score_v2={"ev_net_pct": -1.47, "fee_per_contract": 0.0}, score={"score": 0.1},
                away_team="Los Angeles Chargers", home_team="New England Patriots",
                quote={"bookmaker": "draftkings", "price": 140, "fair_probability": 0.40, "books_quoting": 6}, **kw)


def _board(rows):
    return {"rows": rows, "written_at": "2026-11-27T20:28:25Z"}


def _reader(payload):
    return lambda d: payload if d == DAY else None


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    bgp.clear_cache()
    monkeypatch.setattr(bgp, "_central_today", lambda: DAY)
    yield
    bgp.clear_cache()


# --- the weekly view and the prop lookup ---------------------------------------------------------------------------


def test_upcoming_view_spans_every_day_and_sport_view_keeps_one():
    rows = [_row(), _row(commence_time=MONDAY, away_team="Chicago Bears", home_team="Green Bay Packers"),
            _row(sport="ncaaf"), _row(game_state="live", is_live=True)]
    up = bgp.upcoming_view("nfl", reader=_reader(_board(rows)))
    assert up.ok and up.day == bgp.UPCOMING and len(up.lines) == 2
    assert up.game_days == ("2026-11-29", "2026-11-30")
    one = bgp.sport_view("nfl", "2026-11-29", reader=lambda d: _board(rows))
    assert [x.home for x in one.lines] == ["Houston Texans"]


def test_upcoming_view_without_a_shortlist_is_not_ok():
    view = bgp.upcoming_view("nfl", reader=lambda d: None)
    assert not view.ok and view.lines == ()


def test_find_prop_folds_the_market_and_keeps_to_the_cards_game():
    rows = [_row(), _row(away_team="Detroit Lions", home_team="Chicago Bears", line=1.5, ev_pct=-3.0, suggested=False)]
    view = bgp.upcoming_view("nfl", reader=_reader(_board(rows)))
    assert view.find_prop("David Montgomery", "receptions", "over", 1.5).away in ("Baltimore Ravens", "Detroit Lions")
    hit = view.find_prop("David Montgomery", "Receptions", "OVER", 1.5, away="Baltimore Ravens", home="Houston Texans")
    assert hit is not None and hit.suggested and hit.home == "Houston Texans"
    other = view.find_prop("David Montgomery", "Receptions", "over", 1.5, away="Detroit Lions", home="Chicago Bears")
    assert other is not None and not other.suggested
    assert view.find_prop("David Montgomery", "Receptions", "over", 2.5, away="Baltimore Ravens", home="Houston Texans") is None
    assert view.find_prop("David Montgomery", "Receptions", "over", 1.5, away="Miami Dolphins", home="New York Jets") is None


def test_only_games_cuts_to_the_pages_games_and_kind():
    rows = [_row(), _row(kind="game", market="h2h", side="home", line=None, player_name=None),
            _row(away_team="Seattle Seahawks", home_team="San Francisco 49ers")]
    view = bgp.upcoming_view("nfl", reader=_reader(_board(rows)))
    cut = view.only_games([("Baltimore Ravens", "Houston Texans")], kind="prop")
    assert [(x.kind, x.home) for x in cut.lines] == [("prop", "Houston Texans")]


# --- lead_with_board_picks ----------------------------------------------------------------------------------------


def _page(cards, **extra):
    return {"rank_cards": list(cards), "card_sections": [], "header_stats": [{"label": "Cards", "value": str(len(cards))}],
            "empty_state": None, **extra}


SIM_CARD = {"title": "JAX vs TEN SmartSim 2.0 candidate", "badge": "82.7% win prob", "eyebrow": "SmartSim 2.0"}


def test_the_boards_picks_lead_and_the_pages_cards_follow_labelled():
    view = bgp.upcoming_view("nfl", reader=_reader(_board([_row(), _fehoko()])))
    ctx = bgp.lead_with_board_picks(_page([SIM_CARD]), view, sport_label="NFL",
                                    other_title="SmartSim view: not the board's picks", other_note="note")
    assert [c["source"] for c in ctx["rank_cards"]] == ["board"]
    assert ctx["rank_cards"][0]["title"] == "David Montgomery Over 1.5 receptions"
    assert ctx["rank_cards"][0]["badge"] == "EV +5.2%"
    assert "Sun 11-29 12:00 PM CT" in ctx["rank_cards"][0]["meta"]
    assert [s["key"] for s in ctx["card_sections"]] == ["board", "page"]
    assert ctx["card_sections"][1]["title"] == "SmartSim view: not the board's picks"
    assert ctx["card_sections"][1]["cards"] == [SIM_CARD]
    assert ctx["card_sections"][0]["board"]["picks_total"] == 1
    assert "for games on Sun 11-29" in ctx["card_sections"][0]["meta"]
    assert ctx["header_stats"][0] == {"label": "Board picks", "value": "1"}


def test_reachability_the_headline_changes_with_the_boards_picks():
    page = [SIM_CARD]
    off = bgp.lead_with_board_picks(_page(page), bgp.upcoming_view("nfl", reader=_reader(_board([_fehoko()]))),
                                    sport_label="NFL", other_title="t", other_note="n")
    bgp.clear_cache()  # the shortlist is cached per date for a minute, whatever the reader
    on = bgp.lead_with_board_picks(_page(page), bgp.upcoming_view("nfl", reader=_reader(_board([_row(), _fehoko()]))),
                                   sport_label="NFL", other_title="t", other_note="n")
    assert off["rank_cards"] == [] and on["rank_cards"] != []
    assert "suggests no NFL bet" in off["card_sections"][0]["meta"]
    assert off["card_sections"][1]["cards"] == on["card_sections"][1]["cards"] == page


def test_an_empty_page_keeps_its_reason_under_the_boards_picks():
    empty = {"eyebrow": "NBA picks", "title": "No stored NBA picks were available for this date",
             "body": "The picks board only renders saved NBA recommendation-slate artifacts."}
    view = bgp.sport_view("nba", DAY, reader=_reader(_board([
        _row(sport="nba", market="Points", player_name="Luka Doncic", line=32.5, commence_time="2026-11-28T01:00:00Z",
             away_team="Los Angeles Lakers", home_team="San Antonio Spurs")])))
    ctx = bgp.lead_with_board_picks(_page([], empty_state=empty), view, sport_label="NBA",
                                    other_title="Sim slate view: not the board's picks", other_note="The sim's slate.")
    assert ctx["empty_state"] is None and len(ctx["rank_cards"]) == 1
    assert "No stored NBA picks" in ctx["card_sections"][1]["meta"]
    assert "for 2026-11-27" in ctx["card_sections"][0]["meta"]
    assert "CT" not in ctx["rank_cards"][0]["meta"]  # a one-day page needs no kickoff


def test_nothing_anywhere_keeps_the_pages_empty_state():
    empty = {"title": "No stored NBA picks", "body": "none"}
    view = bgp.sport_view("nba", DAY, reader=_reader(_board([])))
    ctx = bgp.lead_with_board_picks(_page([], empty_state=empty), view, sport_label="NBA", other_title="t", other_note="n")
    assert ctx["empty_state"] == empty and ctx["rank_cards"] == []


def test_without_a_board_the_section_says_so():
    view = bgp.upcoming_view("nfl", reader=lambda d: None)
    ctx = bgp.lead_with_board_picks(_page([SIM_CARD]), view, sport_label="NFL", other_title="t", other_note="n")
    assert ctx["rank_cards"] == [] and "no saved shortlist" in ctx["card_sections"][0]["meta"]
    assert ctx["header_stats"][0]["value"] == "-"


def test_a_page_with_its_own_sections_keeps_them_under_one_label():
    own = [{"key": "spread", "title": "Spread", "meta": "13 recommendations", "cards": [SIM_CARD]},
           {"key": "total", "title": "Total", "note": "totals", "cards": []}]
    page = _page([SIM_CARD], card_sections=[dict(s) for s in own])
    ctx = bgp.lead_with_board_picks(page, bgp.upcoming_view("nfl", reader=_reader(_board([_row()]))),
                                    sport_label="NFL", other_title="Sim view: not the board's picks", other_note="note")
    assert [s["key"] for s in ctx["card_sections"]] == ["board", "page_label", "spread", "total"]
    assert ctx["card_sections"][1]["title"] == "Sim view: not the board's picks" and ctx["card_sections"][1]["cards"] == []
    assert ctx["card_sections"][2:] == own  # each kept exactly as the page built it
    assert [c["source"] for c in ctx["rank_cards"]] == ["board"]


def test_a_page_off_the_boards_slate_shows_no_board_picks_and_says_why():
    view = bgp.upcoming_view("nfl", reader=_reader(_board([_row()])))
    ctx = bgp.lead_with_board_picks(_page([SIM_CARD]), view, sport_label="NFL", other_title="t", other_note="n",
                                    off_slate="2025 Week 17")
    assert ctx["rank_cards"] == []
    assert ctx["card_sections"][0]["meta"] == "The board judges upcoming games only, so it has no picks for 2025 Week 17."
    assert ctx["card_sections"][0]["board"]["picks_total"] == 0 and ctx["header_stats"][0]["value"] == "0"
    assert ctx["card_sections"][1]["cards"] == [SIM_CARD]


# --- the NFL props page ---------------------------------------------------------------------------------------------


def _inventory_row(player, stat, side, line, odds, p_over, away, home):
    from syndicate.features.nfl import props

    return {"game_id": props.nfl_props_key(away, home), "market": props._nfl_prop_join_market_key(stat, player, line),
            "period": "full_game", "entity": player, "side": side, "line": line, "odds": odds,
            "sim_projection": p_over, "projected_value": 0.8, "sim_source": "season", "join_status": "matched"}


def _props_context(monkeypatch, inventory):
    from syndicate.features.nfl import props

    monkeypatch.setattr(props, "nfl_props_rows_for_week", lambda season, week, **kw: ([], []))
    monkeypatch.setattr(props, "join_odds_to_sim", lambda odds, sim: list(inventory))
    return props, props.build_nfl_props_page_context(2026, 12)


INVENTORY = [
    _inventory_row("Simi Fehoko", "receptions", "under", 1.5, 140.0, 0.075,
                   "Los Angeles Chargers", "New England Patriots"),
    _inventory_row("David Montgomery", "receptions", "over", 1.5, -120.0, 0.62, "Baltimore Ravens", "Houston Texans"),
    _inventory_row("Emanuel Wilson", "anytime_td", "over", None, 2250.0, 0.373, "Baltimore Ravens", "Houston Texans"),
]


def test_rate_cards_are_labelled_and_keyed(monkeypatch):
    _, ctx = _props_context(monkeypatch, INVENTORY)
    top = ctx["rank_cards"][0]
    assert top["badge"].startswith("Rate edge +") and top["eyebrow"] == "Rate view · NFL Props"
    assert top["source"] == "rate"
    assert top["line_key"] == {"away": "Los Angeles Chargers", "home": "New England Patriots", "player": "Simi Fehoko",
                               "market": "Receptions", "side": "under", "line": 1.5}
    td = next(c for c in ctx["rank_cards"] if "Anytime" in c["title"])
    assert td["line_key"]["side"] == "yes" and td["line_key"]["line"] is None


def test_props_page_leads_with_this_weeks_board_props_and_every_card_has_a_verdict(monkeypatch):
    props, ctx = _props_context(monkeypatch, INVENTORY)
    rows = [_row(), _fehoko(),
            _row(market="Anytime TD", player_name="Emanuel Wilson", side="yes", line=None, suggested=False,
                 suggested_reasons=["single_book_fair"], ev_pct=-12.0, score_v2={"ev_net_pct": -12.0}),
            # a pick on a game this page does not show, and a game-line pick on a page game: neither leads
            _row(player_name="Mike Evans", away_team="Seattle Seahawks", home_team="San Francisco 49ers"),
            _row(kind="game", market="h2h", side="home", line=None, player_name=None, score={"score": 9.0})]
    out = props.attach_board_verdicts(ctx, bgp.upcoming_view("nfl", reader=_reader(_board(rows))))
    assert [c["title"] for c in out["rank_cards"]] == ["David Montgomery Over 1.5 receptions"]
    rate = out["card_sections"][1]["cards"]
    assert out["card_sections"][1]["title"] == "Rate view: not the board's picks"
    by_player = {c["line_key"]["player"]: c for c in rate}
    assert by_player["David Montgomery"]["board_pick"] is True
    assert by_player["David Montgomery"]["list_items"][0].startswith("Board pick: EV +5.2%")
    assert by_player["Simi Fehoko"]["board_pick"] is False
    assert by_player["Simi Fehoko"]["list_items"][0].startswith("Board: not a pick")
    assert "EV -1.5%" in by_player["Simi Fehoko"]["board_verdict"]
    assert by_player["Emanuel Wilson"]["board_verdict"].startswith("Board: not a pick")
    assert "vig left in" in out["card_sections"][1]["meta"]
    assert "3 of 3 are on the board, 1 of them board picks" in out["card_sections"][1]["meta"]


def test_a_rate_card_the_board_lacks_says_so(monkeypatch):
    props, ctx = _props_context(monkeypatch, INVENTORY[:1])
    out = props.attach_board_verdicts(ctx, bgp.upcoming_view("nfl", reader=_reader(_board([_row()]))))
    card = out["card_sections"][1]["cards"][0]
    assert card["board_verdict"] == "Board: this game has no pregame line on the board."
    assert out["rank_cards"] == []


# --- the routes (reachability: each route calls the helper) ---------------------------------------------------------


@pytest.fixture()
def client():
    from syndicate.app import create_app

    return create_app().test_client()


def _patch_board(monkeypatch, rows):
    payload = _board(rows)
    monkeypatch.setattr(bgp, "upcoming_view", lambda sport, **kw: _REAL_UPCOMING(sport, reader=_reader(payload)))
    monkeypatch.setattr(bgp, "sport_view", lambda sport, day=None, **kw: _REAL_SPORT_VIEW(sport, day, reader=_reader(payload)))


def _rank_context(cards):
    from syndicate.features.shared.rank_board import build_rank_page_context

    return build_rank_page_context(selected_date=DAY, route_path="/x", intro_title="X", intro_body="x", aria_label="x",
                                   source_path="x", source_title="x", rank_cards=list(cards), using_sample_data=False,
                                   header_stats=[], module_links=[])


def test_nfl_props_route_leads_with_the_board(monkeypatch, client):
    from syndicate.features.nfl import props

    monkeypatch.setattr(props, "nfl_props_rows_for_week", lambda season, week, **kw: ([], []))
    monkeypatch.setattr(props, "join_odds_to_sim", lambda odds, sim: list(INVENTORY))
    _patch_board(monkeypatch, [_row(), _fehoko()])
    body = client.get("/nfl/api/props").get_json()
    assert body["card_sections"][0]["key"] == "board"
    assert [c["source"] for c in body["rank_cards"]] == ["board"]
    assert all(c.get("board_verdict") for c in body["card_sections"][1]["cards"])


def test_nfl_picks_route_leads_with_the_board(monkeypatch, client):
    import syndicate.blueprints.nfl as nfl_bp

    ctx = {**_rank_context([SIM_CARD]), "season": 2026, "week": 12, "available_weeks": [12]}
    monkeypatch.setattr(nfl_bp, "build_picks_page_context", lambda week, season=None, sort="": dict(ctx))
    monkeypatch.setattr(nfl_bp, "latest_season", lambda: 2026)
    monkeypatch.setattr(nfl_bp, "default_week", lambda season=None: 12)
    _patch_board(monkeypatch, [_row()])
    body = client.get("/nfl/api/picks").get_json()
    assert [c["source"] for c in body["rank_cards"]] == ["board"]
    assert body["card_sections"][1]["cards"][0]["title"] == SIM_CARD["title"]
    assert body["week"] == 12
    # a past season's week: the board's picks do not appear under its heading
    monkeypatch.setattr(nfl_bp, "build_picks_page_context",
                        lambda week, season=None, sort="": {**dict(ctx), "season": 2025, "week": 17})
    past = client.get("/nfl/api/picks?season=2025&week=17").get_json()
    assert past["rank_cards"] == [] and "no picks for 2025 Week 17" in past["card_sections"][0]["meta"]


def test_ncaaf_picks_route_leads_with_the_board(monkeypatch, client):
    import syndicate.blueprints.ncaaf as ncaaf_bp

    ctx = {**_rank_context([SIM_CARD]), "week": 13, "available_weeks": [13]}
    monkeypatch.setattr(ncaaf_bp, "build_smartsim_picks_page_context", lambda week: dict(ctx))
    _patch_board(monkeypatch, [_row(sport="ncaaf", kind="game", market="spreads", side="home", line=-14.5,
                                    player_name=None, away_team="Washington Huskies", home_team="Oregon Ducks")])
    body = client.get("/ncaaf/api/picks").get_json()
    assert [c["title"] for c in body["rank_cards"]] == ["Oregon Ducks -14.5"]
    assert body["card_sections"][1]["title"].startswith("Price-shopping and model view")
    monkeypatch.setattr(ncaaf_bp, "default_week", lambda: 13)
    other = client.get("/ncaaf/api/picks?week=3").get_json()
    assert other["rank_cards"] == [] and "no picks for Week 13" in other["card_sections"][0]["meta"]


def test_nba_picks_route_and_page_lead_with_the_board(monkeypatch, client):
    import syndicate.blueprints.nba as nba_bp

    empty = {"eyebrow": "NBA picks", "title": "No stored NBA picks were available for this date", "body": "none"}
    monkeypatch.setattr(nba_bp, "build_picks_page_context", lambda d: {**_rank_context([]), "empty_state": empty})
    _patch_board(monkeypatch, [_row(sport="nba", market="Points", player_name="Luka Doncic", line=32.5,
                                    commence_time="2026-11-28T01:00:00Z", away_team="Los Angeles Lakers",
                                    home_team="San Antonio Spurs")])
    body = client.get(f"/nba/api/picks?date={DAY}").get_json()
    assert [c["source"] for c in body["rank_cards"]] == ["board"] and body["empty_state"] is None
    html = client.get(f"/nba/picks?date={DAY}").get_data(as_text=True)
    assert "Luka Doncic Over 32.5" in html
    assert "Sim slate view: not the board" in html
    assert html.index("Luka Doncic") < html.index("Sim slate view")


def test_alternate_lines_and_player_markets_read_like_the_main_ones():
    rows = [_row(sport="nba", kind="game", market="spreads_alt", side="home", line=-14.5, player_name=None,
                 away_team="Los Angeles Lakers", home_team="San Antonio Spurs", commence_time="2026-11-28T01:00:00Z"),
            _row(sport="nba", kind="game", market="totals_alt", side="under", line=231.5, player_name=None,
                 away_team="Los Angeles Lakers", home_team="San Antonio Spurs", commence_time="2026-11-28T01:00:00Z"),
            _row(sport="nba", kind="game", market="alternate_spreads", side="away", line=10.5, player_name=None,
                 away_team="Los Angeles Lakers", home_team="San Antonio Spurs", commence_time="2026-11-28T01:00:00Z"),
            _row(sport="nba", market="player_rebounds", player_name="Brook Lopez", side="under", line=4.5,
                 away_team="Los Angeles Lakers", home_team="San Antonio Spurs", commence_time="2026-11-28T01:00:00Z")]
    view = bgp.sport_view("nba", DAY, reader=_reader(_board(rows)))
    labels = sorted((p.market_label, p.side_label) for p in view.picks)
    assert labels == [("Rebounds", "Brook Lopez Under 4.5 rebounds"), ("Spread", "Los Angeles Lakers +10.5"),
                      ("Spread", "San Antonio Spurs -14.5"), ("Total", "Under 231.5")]
    # matching still keeps an alternate spread apart from the main one
    assert view.find_game_line("Los Angeles Lakers", "San Antonio Spurs", "spreads", "home", -14.5) is None
