"""NBA alternate game lines (`spreads_alt` / `totals_alt`) -> Polymarket's per-rung markets.

Every slug, outcome array and price below was read from the fleet's slate
(`load_polymarket_markets`, 2026-10-24 ~23:0xZ), and every board row from the
fleet's own join input (`portfolio_commit._board_rows_for_join('2026-10-24')`).
Polymarket lists each rung as its own SPREAD/TOTAL market with no "alt" type,
so an alt row is a spreads/totals row at another line.

Fleet replay on that board (code before vs after this change): NBA full-game
alt rows resolving through the ticker resolver 0 -> 296 of 627; Suggested alt
rows 0 -> 27 of 43 full-game; the 174 main-line matches identical.

Each admission has a REACHABILITY test: the same fixture with the alt-line
league set emptied (the pre-change behaviour) pairs nothing.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import polymarket_board_join as mod

DATE = "2026-10-24"
MIA_CHA = "0abd50d04d02296b33809f9458fd47e4"
GS_PHO = "a71197130d9b661f5b29c812583fe652"


def _m(slug, kind, outcomes, prices):
    return {
        "slug": slug,
        "sportsMarketTypeV2": f"SPORTS_MARKET_TYPE_{kind}",
        "outcomes": json.dumps(list(outcomes)),
        "outcomePrices": json.dumps(list(prices)),
        "orderPriceMinTickSize": 0.01,
        "minimumTradeQty": 0.01,
        "orderable": True,
        "yesLegIndex": 0,
    }


_MARKETS = [
    _m("tsc-nba-mia-cha-2026-10-24-236pt5", "TOTAL", ("Over", "Under"), ("0.0600", "0.96")),
    _m("tsc-nba-mia-cha-2026-10-24-216pt5", "TOTAL", ("Over", "Under"), ("0.8100", "0.2")),
    _m("tsc-nba-mia-cha-2026-10-24-sh-121pt5", "TOTAL", ("Over", "Under"), ("0.0200", "0.99")),
    _m("tsc-nba-mia-cha-2026-10-24-tt-mia-fg-121pt5", "TOTAL", ("Over", "Under"), ("0.0200", "0.99")),
    _m("asc-nba-mia-cha-2026-10-24-pos-16pt5", "SPREAD", ("+16.50", "-16.50"), ("0.4400", "0.58")),
    _m("asc-nba-gs-pho-2026-10-24-pos-21pt5", "SPREAD", ("+21.50", "-21.50"), ("0.8200", "0.19")),
    _m("asc-nba-gs-pho-2026-10-24-neg-16pt5", "SPREAD", ("-16.50", "+16.50"), ("0.0300", "0.98")),
    _m("tsc-nba-gs-pho-2026-10-24-235pt5", "TOTAL", ("Over", "Under"), ("0.2200", "0.79")),
    _m("tsc-nba-gs-pho-2026-10-24-237pt5", "TOTAL", ("Over", "Under"), ("0.2000", "0.81")),
]


def _row(event_id, market, side, line, segment="full", sport="nba"):
    # The fleet board's own row shape: no `selected_date`, so the caller's
    # date does the work, exactly as in production.
    teams = {
        MIA_CHA: ("Charlotte Hornets", "Miami Heat", "2026-10-24T22:10:00Z"),
        GS_PHO: ("Phoenix Suns", "Golden State Warriors", "2026-10-25T02:10:00Z"),
    }[event_id]
    return {
        "event_id": event_id, "sport": sport, "market": market, "side": side,
        "line": line, "segment": segment, "home_team": teams[0],
        "away_team": teams[1], "selected_date": None, "commence_time": teams[2],
    }


def _join(rows):
    return mod.join_polymarket_to_board(_MARKETS, rows, selected_date=DATE)


def _pre_change(monkeypatch):
    monkeypatch.setattr(mod, "_ALT_GAME_LINE_LEAGUES", frozenset())


# (row, slug it must pair with, probability of OUR side)
_PAIRS = [
    (_row(MIA_CHA, "totals_alt", "under", 236.5), "tsc-nba-mia-cha-2026-10-24-236pt5", 0.96),
    # Away club at +16.5: the slug-first club's own line -> outcomes[0].
    (_row(MIA_CHA, "spreads_alt", "away", 16.5), "asc-nba-mia-cha-2026-10-24-pos-16pt5", 0.44),
    # Home club at -21.5 is the SECOND slot of `pos-21pt5` (GS +21.5).
    (_row(GS_PHO, "spreads_alt", "home", -21.5), "asc-nba-gs-pho-2026-10-24-pos-21pt5", 0.19),
    # Home club at +16.5 is the second slot of `neg-16pt5` (GS -16.5).
    (_row(GS_PHO, "spreads_alt", "home", 16.5), "asc-nba-gs-pho-2026-10-24-neg-16pt5", 0.98),
    (_row(GS_PHO, "totals_alt", "under", 235.5), "tsc-nba-gs-pho-2026-10-24-235pt5", 0.79),
]


@pytest.mark.parametrize("row,slug,prob", _PAIRS)
def test_an_nba_alt_rung_pairs_with_its_own_polymarket_rung(row, slug, prob, monkeypatch):
    after = _join([row])
    assert after["matched"] == 1, after["refusals"]
    (match,) = after["matches"]
    assert match["polymarket_slug"] == slug
    assert match["polymarket_probability"] == pytest.approx(prob)
    # Recorded as the venue's market; the board's own name is kept beside it.
    assert match["market"] == row["market"][: -len("_alt")]
    assert match["board_market"] == row["market"]

    _pre_change(monkeypatch)
    before = _join([row])
    assert before["matched"] == 0
    assert before["refusals"].get("alt_line_league_not_measured") == 1


@pytest.mark.parametrize("row", [
    # GS +16.5 needs `pos-16pt5`; only `neg-16pt5` (GS -16.5) is listed.
    _row(GS_PHO, "spreads_alt", "away", 16.5),
    # 236.5 is listed for GS@PHO only as 235.5 / 237.5 neighbours.
    _row(GS_PHO, "totals_alt", "under", 236.5),
    # A MIA@CHA rung the venue does not list, beside one it does (236.5).
    _row(MIA_CHA, "totals_alt", "over", 235.5),
])
def test_a_rung_never_pairs_with_a_different_line(row):
    res = _join([row])
    assert res["matched"] == 0
    assert res["refusals"].get("no_matching_polymarket_market") == 1


def test_a_rung_never_pairs_with_a_segment_or_team_total_at_the_same_number():
    """121.5 is listed for MIA@CHA only as a second-half total and a Heat team
    total. Neither is the game, so a game-total alt row at 121.5 pairs nothing."""
    res = _join([_row(MIA_CHA, "totals_alt", "over", 121.5)])
    assert res["matched"] == 0
    assert res["refusals"].get("segment_market_not_full_game") == 2


def test_a_segment_alt_row_is_refused_as_a_segment_bet():
    res = _join([_row(MIA_CHA, "totals_alt", "under", 236.5, segment="q1")])
    assert res["matched"] == 0
    assert res["refusals"].get("board_row_is_a_segment_bet") == 1


def test_an_unmeasured_leagues_alt_row_refuses_by_name():
    row = _row(MIA_CHA, "totals_alt", "under", 236.5, sport="nhl")
    res = _join([row])
    assert res["matched"] == 0
    assert res["refusals"].get("alt_line_league_not_measured") == 1


def test_the_resolvers_find_the_alt_row_the_join_matched(monkeypatch):
    rows = [r for r, _s, _p in _PAIRS]
    matches = _join(rows)["matches"]
    price = mod.polymarket_price_resolver(matches)
    ticker = mod.polymarket_ticker_resolver(matches)
    for row, slug, prob in _PAIRS:
        assert ticker(row)["slug"] == slug
        assert price(row) is not None

    # Pre-change key (no canonicalisation): the row's `spreads_alt` never met
    # the match's `spreads`, so even a matched alt row could not be ordered.
    _pre_change(monkeypatch)
    assert all(ticker(row) is None for row in rows)


def test_an_alt_row_and_a_main_row_at_one_rung_share_one_contract():
    alt = _row(MIA_CHA, "spreads_alt", "away", 16.5)
    main = dict(alt, market="spreads")
    assert mod._resolver_key(alt) == mod._resolver_key(main)


def test_an_unmeasured_leagues_alt_row_never_resolves_to_a_main_line_match():
    """The key canonicalises only in an admitted league, so an NHL alt row
    cannot pick up an NHL main-line match that merely shares its rung."""
    main_match = {"event_id": "e1", "sport": "nhl", "market": "spreads",
                  "side": "away", "line": 1.5, "polymarket_slug": "asc-nhl-x",
                  "polymarket_american": 120.0}
    alt_row = {"event_id": "e1", "sport": "nhl", "market": "spreads_alt",
               "side": "away", "line": 1.5}
    assert mod.polymarket_ticker_resolver([main_match])(alt_row) is None
    assert mod.polymarket_price_resolver([main_match])(alt_row) is None
    assert mod.polymarket_ticker_resolver([main_match])(dict(alt_row, market="spreads"))
