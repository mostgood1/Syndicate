"""#861 step 1d: the per-sport pages (NHL picks, NHL cards, NHL / soccer game cards) lead with the board's picks, and
the raw sim's rows are labelled as the sim's, each with the board's verdict on the same line."""

from __future__ import annotations

import copy

import pytest

from syndicate.features.shared import board_game_picks as bgp

DAY = "2026-11-25"
_REAL_SPORT_VIEW = bgp.sport_view  # captured before any test patches the module attribute
NHL_START = "2026-11-26T00:00:00Z"  # 6 PM CST on 11-25


def _row(**kw):
    base = {
        "sport": "nhl",
        "kind": "game",
        "market": "totals",
        "side": "under",
        "line": 6.5,
        "segment": "full",
        "away_team": "Winnipeg Jets",
        "home_team": "Boston Bruins",
        "commence_time": NHL_START,
        "game_state": "pregame",
        "is_live": False,
        "ev_pct": 3.2,
        "score_v2": {"ev_net_pct": 3.2, "fee_per_contract": 0.0},
        "score": {"score": 1.0},
        "suggested": True,
        "suggested_reasons": [],
        "quote": {"bookmaker": "fanduel", "price": -105, "fair_probability": 0.53, "books_quoting": 9},
    }
    base.update(kw)
    return base


def _board(rows, written_at="2026-11-25T16:06:33Z"):
    return {"rows": rows, "written_at": written_at}


def _reader(payload):
    return lambda d: payload if d == DAY else None


@pytest.fixture(autouse=True)
def _fresh_cache():
    bgp.clear_cache()
    yield
    bgp.clear_cache()


# --- the view ---------------------------------------------------------------------------------------------------


def test_view_keeps_pregame_rows_of_the_sport_and_day_only():
    rows = [
        _row(),
        _row(game_state="live", is_live=True, side="over"),
        _row(sport="soccer"),
        _row(commence_time="2026-11-27T00:00:00Z", away_team="Utah Mammoth", home_team="Minnesota Wild"),
    ]
    view = bgp.sport_view("nhl", DAY, reader=_reader(_board(rows)))
    assert view.ok and view.written_at == "2026-11-25T16:06:33Z"
    assert [(x.sport, x.side, x.away) for x in view.lines] == [("nhl", "under", "Winnipeg Jets")]


def test_picks_are_suggested_rows_in_the_boards_order_score_then_ev():
    rows = [
        _row(side="over", suggested=False, suggested_reasons=["ev_below_min"], score={"score": 9.0}),
        _row(market="h2h", side="away", line=None, score={"score": 1.0}, ev_pct=5.0),
        _row(score={"score": 2.0}, ev_pct=2.5),
        _row(market="spreads", side="away", line=1.5, score={"score": 1.0}, ev_pct=6.0),
    ]
    view = bgp.sport_view("nhl", DAY, reader=_reader(_board(rows)))
    assert [(p.family, p.side) for p in view.picks] == [("totals", "under"), ("spreads", "away"), ("h2h", "away")]


def test_game_resolution_exact_then_one_side_then_ambiguous():
    rows = [
        _row(sport="soccer", away_team="Manchester United", home_team="Sporting Lisbon", market="h2h", side="home",
             line=None, commence_time="2026-11-25T20:00:00Z"),
        _row(sport="soccer", away_team="Villarreal", home_team="Slavia Praha", market="h2h", side="home", line=None,
             commence_time="2026-11-25T17:45:00Z"),
        _row(sport="soccer", away_team="Villarreal B", home_team="Slavia Praha", market="h2h", side="away", line=None,
             commence_time="2026-11-25T17:45:00Z"),
    ]
    view = bgp.sport_view("soccer", DAY, reader=_reader(_board(rows)))
    # exact
    assert len(view.game_lines("Manchester United", "Sporting Lisbon")) == 1
    # one side, unique on the day ("Sporting CP" is the page's spelling)
    assert len(view.game_lines("Manchester United", "Sporting CP")) == 1
    # one side matches two board games -> refuse rather than guess
    assert view.game_lines("Someone Else", "Slavia Praha") == ()


def test_accents_and_punctuation_fold():
    rows = [_row(away_team="Montreal Canadiens", home_team="St Louis Blues")]
    view = bgp.sport_view("nhl", DAY, reader=_reader(_board(rows)))
    assert len(view.game_lines("Montréal Canadiens", "St. Louis Blues")) == 1


def test_find_game_line_matches_market_side_and_line():
    rows = [_row(line=6.0), _row(line=6.5, side="over", suggested=False, suggested_reasons=["ev_below_min"])]
    view = bgp.sport_view("nhl", DAY, reader=_reader(_board(rows)))
    assert view.find_game_line("Winnipeg Jets", "Boston Bruins", "TOTAL", "under", 6.5) is None
    assert view.find_game_line("Winnipeg Jets", "Boston Bruins", "totals", "under", "6.0").line == 6.0
    assert view.find_game_line("Winnipeg Jets", "Boston Bruins", "totals", "over", 6.5).suggested is False


def test_find_prop():
    rows = [_row(kind="prop", market="GOALS", side="over", line=1.5, player_name="T.J. Hughes",
                 suggested=False, suggested_reasons=["single_book_fair", "one_sided_fair"])]
    view = bgp.sport_view("nhl", DAY, reader=_reader(_board(rows)))
    hit = view.find_prop("T.J. Hughes", "GOALS", "Over", 1.5)
    assert hit is not None and not hit.suggested
    assert view.find_prop("T.J. Hughes", "GOALS", "Over", 0.5) is None


def test_verdict_text_for_pick_refusal_and_absence():
    rows = [
        _row(),
        _row(side="over", suggested=False, suggested_reasons=["single_book_fair"], ev_pct=2.4,
             score_v2={"ev_net_pct": 1.1, "fee_per_contract": 0.012}, quote={"bookmaker": "kalshi", "price": 110}),
    ]
    view = bgp.sport_view("nhl", DAY, reader=_reader(_board(rows)))
    pick = view.find_game_line("Winnipeg Jets", "Boston Bruins", "totals", "under", 6.5)
    refused = view.find_game_line("Winnipeg Jets", "Boston Bruins", "totals", "over", 6.5)
    assert bgp.verdict_text(pick) == "Board pick: EV +3.2% at fanduel -105."
    # the EV the board judged on: net of the venue fee, and labelled so
    assert bgp.verdict_text(refused) == (
        "Board: not a pick (its fair price comes from one book only); EV +1.1% net of fee at kalshi +110."
    )
    assert bgp.verdict_text(None) == "Board: this line is not on the board."
    assert bgp.verdict_text(None, game_on_board=False) == "Board: this game has no pregame line on the board."


def test_an_absent_line_names_the_shortlists_floor():
    payload = {**_board([_row()]), "min_value_pct": -2.0}
    view = bgp.sport_view("nhl", DAY, reader=_reader(payload))
    assert view.verdict(None, "Winnipeg Jets", "Boston Bruins") == (
        "Board: this line is not on the board, which lists lines at EV -2% or better at the best price."
    )
    assert view.verdict(None, "Seattle Kraken", "Chicago Blackhawks") == (
        "Board: this game has no pregame line on the board."
    )


def test_cache_reads_once_per_window_and_a_failed_read_is_not_ok(monkeypatch):
    calls = []

    def reader(d):
        calls.append(d)
        return _board([_row()]) if d == DAY else None

    bgp.sport_view("nhl", DAY, reader=reader)
    bgp.sport_view("soccer", DAY, reader=reader)
    assert calls == [DAY]  # one shortlist parse serves every sport inside the window

    bgp.clear_cache()

    def broken(d):
        raise OSError("disk")

    monkeypatch.setattr(bgp, "_central_today", lambda: DAY)
    view = bgp.sport_view("nhl", DAY, reader=broken)
    assert view.ok is False and view.picks == ()


def test_later_day_falls_back_to_todays_shortlist(monkeypatch):
    monkeypatch.setattr(bgp, "_central_today", lambda: DAY)
    rows = [_row(commence_time="2026-11-27T00:00:00Z")]  # played 11-26 CT, on 11-25's horizon
    view = bgp.sport_view("nhl", "2026-11-26", reader=_reader(_board(rows)))
    assert view.ok and view.shortlist_date == DAY and len(view.picks) == 1


def test_labels():
    rows = [
        _row(sport="soccer", market="alternate_totals_corners", side="over", line=12.5, away_team="A", home_team="B",
             commence_time="2026-11-25T20:00:00Z"),
        _row(market="spreads", side="away", line=1.5),
        _row(market="h2h", side="home", line=None),
        _row(kind="prop", market="SOG", side="over", line=1.5, player_name="Claude Giroux"),
    ]
    b = _board(rows)
    soccer = bgp.sport_view("soccer", DAY, reader=_reader(b))
    nhl = bgp.sport_view("nhl", DAY, reader=_reader(b))
    assert soccer.picks[0].side_label == "Over 12.5 corners" and soccer.picks[0].market_label == "Corners total"
    labels = {(p.family, p.side_label, p.market_label) for p in nhl.picks}
    assert ("spreads", "Winnipeg Jets +1.5", "Puck line") in labels
    assert ("h2h", "Boston Bruins", "Moneyline") in labels
    assert ("sog", "Claude Giroux Over 1.5 shots on goal", "Shots on goal") in labels


# --- game cards: the board tile leads ---------------------------------------------------------------------------


def test_attach_board_picks_puts_the_boards_tile_first_and_keeps_the_sims():
    rows = [_row(), _row(away_team="Utah Mammoth", home_team="Minnesota Wild", suggested=False,
                         suggested_reasons=["ev_below_min"])]
    sim_tile = {"label": "Sim · Best 1X2 edge", "title": "WPG ML +135", "sub": "Model 45%"}
    context = {
        "date": DAY,
        "games": [
            {"away": {"name": "Winnipeg Jets"}, "home": {"name": "Boston Bruins"}, "market_tiles": [sim_tile],
             "odds": {"commence_time": DAY}},
            {"away": {"name": "Utah Mammoth"}, "home": {"name": "Minnesota Wild"}, "market_tiles": []},
            {"away": {"name": "Seattle Kraken"}, "home": {"name": "Chicago Blackhawks"}},
        ],
    }
    out = bgp.attach_board_picks(copy.deepcopy(context), "nhl", reader=_reader(_board(rows)))
    first, second, third = out["games"]
    assert first["market_tiles"][0] == {"label": "Board pick", "title": "Under 6.5",
                                        "sub": "EV +3.2% at fanduel -105"}
    assert first["market_tiles"][1] == sim_tile
    assert [p["side_label"] for p in first["board_picks"]] == ["Under 6.5"]
    assert second["market_tiles"][0]["title"] == "No board pick"
    assert "1 pregame lines judged" in second["market_tiles"][0]["sub"]
    assert third["market_tiles"][0]["sub"] == "No pregame line on the board for this game"
    # idempotent: a second pass does not stack two board tiles
    again = bgp.attach_board_picks(out, "nhl", reader=_reader(_board(rows)))
    assert [t["label"] for t in again["games"][0]["market_tiles"]].count("Board pick") == 1


def test_attach_without_a_board_says_so():
    context = {"date": DAY, "games": [{"away": {"name": "A"}, "home": {"name": "B"}}]}
    out = bgp.attach_board_picks(context, "nhl", reader=lambda d: None)
    assert out["games"][0]["market_tiles"][0]["title"] == "Board unavailable"


def test_soccer_sim_tiles_are_labelled_as_the_sims():
    from syndicate.features.soccer import cards as soccer_cards

    assert soccer_cards._sim_tile_label("Best 1X2 edge") == "Sim · Best 1X2 edge"
    assert soccer_cards._sim_tile_label("LIVE Best 1X2 edge") == "LIVE sim · Best 1X2 edge"


# --- NHL picks page ---------------------------------------------------------------------------------------------


SIM_ROWS = [
    {"market": "TOTAL", "side": "Under", "price": "-113", "ev": "0.109", "prob": "0.588", "conf": "0.088",
     "home": "Boston Bruins", "away": "Winnipeg Jets", "totals_line": "6.5"},
    {"market": "PL", "side": "Winnipeg Jets +1.5", "price": "-180", "ev": "0.0395", "prob": "0.668", "conf": "0.168",
     "home": "Boston Bruins", "away": "Winnipeg Jets", "totals_line": "6.5"},
    {"market": "ML", "side": "Boston Bruins", "price": "-157", "ev": "-0.07", "prob": "0.567", "conf": "0.067",
     "home": "Boston Bruins", "away": "Winnipeg Jets", "totals_line": "6.5"},
]


def _nhl_board():
    return _board([
        _row(kind="prop", market="ASSISTS", side="under", line=0.5, player_name="Mark Scheifele"),
        _row(side="under", line=6.5, suggested=False, suggested_reasons=["ev_below_min"], ev_pct=-1.2,
             score_v2={"ev_net_pct": -1.2, "fee_per_contract": 0.0}),
        _row(market="spreads", side="away", line=1.5, suggested=False, suggested_reasons=["ev_below_min"]),
    ])


def _picks_context(monkeypatch, payload):
    from syndicate.features.nhl import picks

    monkeypatch.setattr(picks, "_read_rows", lambda d: list(SIM_ROWS))
    monkeypatch.setattr(picks, "available_dates", lambda: [DAY])
    real = _REAL_SPORT_VIEW
    monkeypatch.setattr(picks.board_game_picks, "sport_view",
                        lambda sport, day=None, **kw: real(sport, day, reader=_reader(payload)))
    return picks.build_picks_page_context(DAY)


def test_nhl_picks_headline_is_the_board_and_the_sim_is_labelled(monkeypatch):
    ctx = _picks_context(monkeypatch, _nhl_board())
    assert [c["source"] for c in ctx["rank_cards"]] == ["board"]
    assert ctx["rank_cards"][0]["title"] == "Mark Scheifele Under 0.5 assists"
    assert ctx["rank_cards"][0]["badge"] == "EV +3.2%"
    board_section, sim_section = ctx["card_sections"]
    assert board_section["key"] == "board" and sim_section["key"] == "sim"
    sim = sim_section["cards"]
    assert all(c["source"] == "sim" and c["eyebrow"].startswith("Sim view") and c["badge"].startswith("Sim EV")
               for c in sim)
    verdicts = {c["title"]: c["list_items"][0] for c in sim}
    assert verdicts["Under"].startswith("Board: not a pick (its EV is below the board's minimum)")
    assert verdicts["Winnipeg Jets +1.5"].startswith("Board: not a pick")
    assert verdicts["Boston Bruins"] == "Board: this line is not on the board."


def test_nhl_picks_reachability_board_picks_change_the_headline(monkeypatch):
    """off != on: the same sim rows, with and without a board pick, give a different headline."""
    with_pick = _picks_context(monkeypatch, _nhl_board())
    bgp.clear_cache()
    no_pick_payload = _board([r for r in _nhl_board()["rows"] if r.get("kind") != "prop"])
    without = _picks_context(monkeypatch, no_pick_payload)
    assert with_pick["rank_cards"] and not without["rank_cards"]
    assert "suggests no NHL bet" in without["card_sections"][0]["note"]
    assert len(without["card_sections"][1]["cards"]) == len(SIM_ROWS)


def test_nhl_picks_without_a_board_keeps_the_sim_labelled(monkeypatch):
    ctx = _picks_context(monkeypatch, None)
    assert ctx["rank_cards"] == []
    assert "no saved shortlist" in ctx["card_sections"][0]["note"]
    assert all(c["eyebrow"].startswith("Sim view") for c in ctx["card_sections"][1]["cards"])


# --- NHL routes -------------------------------------------------------------------------------------------------


@pytest.fixture()
def client():
    from syndicate.app import create_app

    return create_app().test_client()


def _patch_route_view(monkeypatch, payload):
    import syndicate.blueprints.nhl as nhl_bp

    real = _REAL_SPORT_VIEW
    monkeypatch.setattr(nhl_bp.board_game_picks, "sport_view",
                        lambda sport, day=None, **kw: real(sport, DAY, reader=_reader(payload)))
    return nhl_bp


def test_props_route_adds_the_boards_verdict(monkeypatch, client):
    payload = _board([_row(kind="prop", market="GOALS", side="over", line=1.5, player_name="T.J. Hughes",
                           suggested=False, suggested_reasons=["single_book_fair"], ev_pct=-4.86,
                           score_v2={"ev_net_pct": -4.86, "fee_per_contract": 0.0},
                           quote={"bookmaker": "betrivers", "price": 3000})])
    nhl_bp = _patch_route_view(monkeypatch, payload)
    monkeypatch.setattr(nhl_bp, "build_props_cards_payload", lambda date, top=12: {
        "ok": True, "date": DAY,
        "cards": [{"player": "T.J. Hughes", "market": "GOALS", "side": "Over", "line": 1.5, "ev": 3.27},
                  {"player": "Nobody", "market": "GOALS", "side": "Over", "line": 0.5, "ev": 1.0}]})
    body = client.get(f"/nhl/api/cards/props?date={DAY}").get_json()
    first, second = body["cards"]
    assert first["board_pick"] is False
    assert first["board_verdict"].startswith("Board: not a pick (its fair price comes from one book only)")
    assert second["board_verdict"] == "Board: this line is not on the board."
    assert body["board"]["ok"] is True


def test_bundle_route_keys_the_boards_games_by_the_pages_names(monkeypatch, client):
    nhl_bp = _patch_route_view(monkeypatch, _board([_row(away_team="Montreal Canadiens",
                                                           home_team="Colorado Avalanche")]))
    monkeypatch.setattr(nhl_bp, "build_source_bundle_payload", lambda date: {
        "ok": True, "date": DAY,
        "data": {"games": {"predictions": {"rows": [{"away": "Montréal Canadiens", "home": "Colorado Avalanche"}]}}}})
    board = client.get(f"/nhl/api/cards/bundle?date={DAY}").get_json()["data"]["board"]
    key = bgp.game_key("Montréal Canadiens", "Colorado Avalanche")
    assert board["games"][key]["lines"] == 1
    assert [p["side_label"] for p in board["games"][key]["picks"]] == ["Under 6.5"]
    assert board["picks_total"] == 1


def test_nhl_picks_page_renders_both_sections(monkeypatch, client):
    from syndicate.features.nhl import picks

    monkeypatch.setattr(picks, "_read_rows", lambda d: list(SIM_ROWS))
    monkeypatch.setattr(picks, "available_dates", lambda: [DAY])
    real = _REAL_SPORT_VIEW
    monkeypatch.setattr(picks.board_game_picks, "sport_view",
                        lambda sport, day=None, **kw: real(sport, day, reader=_reader(_nhl_board())))
    html = client.get(f"/nhl/picks?date={DAY}").get_data(as_text=True)
    assert "The board&#39;s NHL picks" in html or "The board's NHL picks" in html
    assert "Raw sim view: not the board" in html
    assert html.index("Mark Scheifele") < html.index("Sim view")


def test_nhl_prop_reason_sentence_is_the_sims():
    from syndicate.features.nhl.cards import _prop_reason_summary

    text = _prop_reason_summary({"side": "over", "line": 1.5, "market": "GOALS", "price": 3000, "prob": 0.138, "ev": 3.276})
    assert text.startswith("Sim's case: Over 1.5")
    assert "Sim win rate 13.8%." in text and text.endswith("Sim EV 327.6%.")
