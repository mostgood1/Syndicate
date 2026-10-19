"""A Kalshi club code two clubs share inside one competition is settled from the EVENT's own markets.

Lane `kalshi-event-scoped-codes`, 2026-10-19. On the fleet, four KXUEL events (OFILEV, VIKLEV,
CELRCC, CELRBS) could not reach their fixture: `LEV` is Leverkusen AND Levski and `CEL` is Celtic
AND Celje in KXUEL, so the competition-wide map drops them and the global alias map reads `LEV`
as Levante. Each event's own "-CODE" market is titled "<Club> wins", which names the club for
THAT game. Hermetic: the club branding is stubbed, no network.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_board_join as kbj

_BRANDING = {
    "uel": [
        {"name": "OFI Crete", "short_name": "OFI"},
        {"name": "Bayer Leverkusen", "short_name": "Leverkusen"},
        {"name": "Viktoria Plzen", "short_name": "Plzen"},
        {"name": "Levski Sofia", "short_name": "Levski"},
        {"name": "Celtic", "short_name": "Celtic"},
        {"name": "Celta Vigo", "short_name": "Celta"},
        {"name": "NK Celje", "short_name": "Celje"},
        {"name": "RB Salzburg", "short_name": "Salzburg"},
        {"name": "Feyenoord", "short_name": "Feyenoord"},
    ],
    "la_liga": [{"name": "Levante", "short_name": "Levante", "abbreviation": "LEV"},
                {"name": "Celta Vigo", "short_name": "Celta", "abbreviation": "CEL"}],
}


@pytest.fixture(autouse=True)
def stub_branding(monkeypatch):
    from syndicate.features.shared import team_aliases as ta
    from syndicate.features.soccer import sources

    monkeypatch.setattr(sources, "all_teams", lambda league: [dict(r) for r in _BRANDING.get(league, [])])
    ta._soccer_alias_to_name.cache_clear()
    ta._soccer_alias_by_league.cache_clear()
    ta._CANONICAL_MEMO.clear()
    ta._ALIAS_VALUES_MEMO.clear()
    yield
    ta._soccer_alias_to_name.cache_clear()
    ta._soccer_alias_by_league.cache_clear()
    ta._CANONICAL_MEMO.clear()
    ta._ALIAS_VALUES_MEMO.clear()


def _m(ticker, title, series="KXUELGAME"):
    return {"ticker": ticker, "series": series, "title": title}


# Two KXUEL games that share `LEV`, and two that share `CEL` -- the 2026-10-22 slate.
MARKETS = [
    _m("KXUELGAME-26OCT22OFILEV-OFI", "OFI Crete wins"),
    _m("KXUELGAME-26OCT22OFILEV-LEV", "Leverkusen wins"),
    _m("KXUELGAME-26OCT22OFILEV-TIE", "Tie is the result"),
    _m("KXUELGAME-26OCT22VIKLEV-VIK", "Plzen wins"),
    _m("KXUELGAME-26OCT22VIKLEV-LEV", "Levski Sofia wins"),
    _m("KXUELGAME-26OCT22CELRCC-CEL", "Celtic wins"),
    _m("KXUELGAME-26OCT22CELRCC-RCC", "Celta Vigo wins"),
    _m("KXUELGAME-26OCT22CELRBS-CEL", "NK Celje wins"),
    _m("KXUELGAME-26OCT22CELRBS-RBS", "Salzburg wins"),
]


def _game(event_id, home, away):
    return {"event_id": event_id, "home_team": home, "away_team": away, "commence_time": "2026-10-22T19:00:00Z"}


GAMES = [
    _game("e-ofi", "OFI Crete", "Bayer Leverkusen"),
    _game("e-vik", "Viktoria Plzen", "Levski Sofia"),
    _game("e-cel", "Celtic", "Celta Vigo"),
    _game("e-cje", "NK Celje", "RB Salzburg"),
]


def _resolve(market, games=GAMES, *, event_names=True, markets=MARKETS):
    return kbj._resolve_event(
        market, games, kbj.build_club_code_names(markets),
        games=games, collided=kbj.build_club_code_collisions(markets),
        event_names=kbj.build_event_club_code_names(markets) if event_names else None,
    )


def test_event_code_names_are_per_event_and_skip_the_draw_leg():
    names = kbj.build_event_club_code_names(MARKETS)
    assert names[("KXUEL", "26OCT22OFILEV")] == {"OFI": "OFI Crete", "LEV": "Leverkusen"}
    assert names[("KXUEL", "26OCT22VIKLEV")] == {"VIK": "Plzen", "LEV": "Levski Sofia"}
    # The competition-wide map still (correctly) refuses the shared codes.
    assert kbj.build_club_code_collisions(MARKETS) == {"KXUEL": {"CEL", "LEV"}}
    # A code given two names inside one event is dropped there too.
    clash = MARKETS + [_m("KXUELGAME-26OCT22OFILEV-LEV", "Levante wins")]
    assert "LEV" not in kbj.build_event_club_code_names(clash)[("KXUEL", "26OCT22OFILEV")]
    assert kbj._event_segment("KXUELTOTAL-26OCT22OFILEV-2") == "26OCT22OFILEV"


@pytest.mark.parametrize(("ticker", "event_id"), [
    ("KXUELGAME-26OCT22OFILEV-TIE", "e-ofi"),
    ("KXUELGAME-26OCT22VIKLEV-TIE", "e-vik"),
    ("KXUELGAME-26OCT22CELRCC-TIE", "e-cel"),
    ("KXUELGAME-26OCT22CELRBS-TIE", "e-cje"),
    # A TOTAL market of the same game shares the event segment and the family.
    ("KXUELTOTAL-26OCT22OFILEV-2", "e-ofi"),
])
def test_a_collided_code_resolves_from_its_own_event(ticker, event_id):
    market = {"ticker": ticker, "series": ticker.split("-")[0]}
    before = _resolve(market, event_names=False)
    after = _resolve(market)
    assert before.get("status") != "ok", before  # the defect: refused or no match
    assert after.get("status") == "ok" and after.get("event_id") == event_id, after


def test_a_named_club_absent_from_the_matched_game_is_refused():
    """The 2026-10-15 defect stays fixed: Kalshi's Celtic v Feyenoord on a board carrying only
    Celta Vigo v Feyenoord. The raw code `CEL` reads as Celta Vigo in the global map, so the
    match must contain the club the event NAMED (Celtic), or it is refused."""
    markets = MARKETS + [_m("KXUELGAME-26OCT22CELFEY-CEL", "Celtic wins"),
                         _m("KXUELGAME-26OCT22CELFEY-FEY", "Feyenoord wins")]
    board = [_game("e-wrong", "Celta Vigo", "Feyenoord")]
    got = _resolve({"ticker": "KXUELGAME-26OCT22CELFEY-TIE", "series": "KXUELGAME"}, board, markets=markets)
    assert got.get("status") != "ok", got


def test_events_without_a_collided_code_resolve_byte_identically():
    markets = MARKETS + [_m("KXUELGAME-26OCT22RBSFEY-RBS", "Salzburg wins"),
                         _m("KXUELGAME-26OCT22RBSFEY-FEY", "Feyenoord wins")]
    board = GAMES + [_game("e-rbs", "RB Salzburg", "Feyenoord")]
    market = {"ticker": "KXUELGAME-26OCT22RBSFEY-TIE", "series": "KXUELGAME"}
    assert _resolve(market, board, markets=markets) == _resolve(market, board, markets=markets, event_names=False)
    # And with no event names at all, nothing that was refused before is resolved.
    for m in MARKETS:
        assert _resolve(m, event_names=False) == kbj._resolve_event(
            m, GAMES, kbj.build_club_code_names(MARKETS), games=GAMES,
            collided=kbj.build_club_code_collisions(MARKETS))


def test_the_join_prices_leverkusen_and_levski_on_their_own_games(monkeypatch):
    """End to end through `join_kalshi_to_board`: each `-LEV` contract prices its own club's row."""
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")

    def rows(event_id, home, away):
        return [{"sport": "soccer", "event_id": event_id, "market": "h2h", "home_team": home, "away_team": away,
                 "side": side, "line": None, "segment": "full", "model_edge_pct": 2.0,
                 "quote": {"bookmaker": "kalshi", "price": 100}} for side in ("home", "away", "draw")]

    markets = [dict(m, yes_american=-120, no_american=110, yes_probability=0.55, no_probability=0.47) for m in MARKETS[:5]]
    board = rows("e-ofi", "OFI Crete", "Bayer Leverkusen") + rows("e-vik", "Viktoria Plzen", "Levski Sofia")
    report = kbj.join_kalshi_to_board(markets, board, selected_date="2026-10-22")
    got = {(m["board_event_id"], m["board_side"], m["ticker"]) for m in report["matches"]}
    assert ("e-ofi", "away", "KXUELGAME-26OCT22OFILEV-LEV") in got, (got, report["reasons"])
    assert ("e-vik", "away", "KXUELGAME-26OCT22VIKLEV-LEV") in got, (got, report["reasons"])
    assert not any(e == "e-ofi" and t.endswith("VIKLEV-LEV") for e, _, t in got)
