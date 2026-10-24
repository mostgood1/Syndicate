"""NBA / NHL board rows -> their Polymarket US markets, on the venue's REAL shapes.

Every slug, outcome array and price below was read from the fleet's slate
artifact (`intelligence/polymarket_us_games.json`, 21,624 markets) on
2026-10-24T00:3xZ, and the spread polarity from the venue's own catalogue
(`web.polymarket.us ... EventsService/GetEvents`, `marketSides[i].team` +
`question`): 1,442 of 1,442 spread sides (721 markets) across 10 events in
nba/nhl/nfl/cfb/mlb
put `outcomes[0]` on the slug's FIRST club at the slug's signed line, and
`outcomes[1]` on the second club at the opposite sign.

    asc-nba-min-orl-2026-10-23-pos-14pt5
      "Will the MIN Timberwolves cover 14.5 vs the ORL Magic ...?"
      marketSides: ("+14.50", team=min, long=True), ("-14.50", team=orl)

Each fix has a REACHABILITY test: the same fixture through the pre-fix rule
(monkeypatched back in) gives a different answer than through the fix.
"""

from __future__ import annotations

import json
import re

import pytest

from syndicate.features.shared import polymarket_board_join as mod


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


def _row(sport, market, side, line, home, away, event_id, date="2026-10-23"):
    # The fleet board's own row shape (Layer 2 shortlist, read 2026-10-24).
    return {
        "sport": sport, "market": market, "side": side, "line": line,
        "segment": "full", "home_team": home, "away_team": away,
        "event_id": event_id, "selected_date": date,
        "commence_time": f"{date}T23:10:00Z",
    }


_LEGACY_SEGMENT = re.compile(r"(?:[1-4](?:q|h|p)|f[357]|fh|sh)")


def _legacy_segments(monkeypatch):
    monkeypatch.setattr(mod, "_SEGMENT_TOKEN", _LEGACY_SEGMENT)


def _legacy_spreads(monkeypatch):
    monkeypatch.setattr(mod, "_SIGNED_SPREAD_LEAGUES", frozenset())


# --------------------------------------------------------------------------
# 1. Letter-first periods and team totals are not the full game
# --------------------------------------------------------------------------


@pytest.mark.parametrize("token", ["q1", "q4", "p1", "p3", "i1", "tt", "tt1h", "tt2h", "h1"])
def test_the_venues_letter_first_period_and_team_total_tokens_are_segments(token):
    assert mod._has_segment([token, "60pt5"])


@pytest.mark.parametrize("mods", [["223pt5"], ["neg", "12pt5"], ["total", "17pt5"], []])
def test_full_game_slugs_are_still_full_game(mods):
    assert not mod._has_segment(mods)


_NHL_PUCK_LINES = [
    _m("asc-nhl-tb-col-2026-10-23-pos-1pt5", "SPREAD", ("+1.50", "-1.50"), ("0.6900", "0.32")),
    _m("asc-nhl-tb-col-2026-10-23-p1-pos-1pt5", "SPREAD", ("+1.50", "-1.50"), ("0.9100", "0.10")),
]
_NHL_ROW = _row("nhl", "spreads", "away", 1.5, "Colorado Avalanche",
                "Tampa Bay Lightning", "b7e4d8193096703065db318c2813168f")


def test_nhl_puck_line_pairs_the_full_game_contract_not_the_first_period(monkeypatch):
    """TB @ COL `spreads away 1.5` refused `ambiguous_polymarket_match` on the
    fleet: `p1-pos-1pt5` was indexed as a full-game rung beside `pos-1pt5`."""
    after = mod.join_polymarket_to_board(_NHL_PUCK_LINES, [_NHL_ROW])
    assert after["matched"] == 1
    (match,) = after["matches"]
    assert match["polymarket_slug"] == "asc-nhl-tb-col-2026-10-23-pos-1pt5"
    assert match["polymarket_probability"] == pytest.approx(0.69)

    _legacy_segments(monkeypatch)
    before = mod.join_polymarket_to_board(_NHL_PUCK_LINES, [_NHL_ROW])
    assert before["matched"] == 0
    assert before["refusals"].get("ambiguous_polymarket_match") == 1


def test_a_team_total_never_prices_a_game_total(monkeypatch):
    """`tt-was-fg-115pt5` is the Wizards' points. Only the team total sits at
    115.5 here, so before the fix the game-total row paired with it."""
    markets = [_m("tsc-nba-tor-was-2026-10-23-tt-was-fg-115pt5", "TOTAL",
                  ("Over", "Under"), ("0.4800", "0.53"))]
    row = _row("nba", "totals", "under", 115.5, "Washington Wizards",
               "Toronto Raptors", "8540b2b24fe0b2042a07c8c20452aead")
    after = mod.join_polymarket_to_board(markets, [row])
    assert after["matched"] == 0
    assert after["refusals"]["segment_market_not_full_game"] == 1

    _legacy_segments(monkeypatch)
    assert mod.join_polymarket_to_board(markets, [row])["matched"] == 1


def test_a_quarter_total_never_prices_a_game_total():
    markets = [_m("tsc-nba-dal-ind-2026-10-23-q2-60pt5", "TOTAL",
                  ("Over", "Under"), ("0.4000", "0.61"))]
    row = _row("nba", "totals", "over", 60.5, "Indiana Pacers",
               "Dallas Mavericks", "d36eac2ef6bf2d6c0af0073612f6193d")
    assert mod.join_polymarket_to_board(markets, [row])["matched"] == 0


# --------------------------------------------------------------------------
# 2. Spreads: the outcome is the HANDICAP, the slug's first club owns its sign
# --------------------------------------------------------------------------

# MIN @ ORL. `neg-12pt5`: MIN -12.5 (outcomes[0]) / ORL +12.5 (outcomes[1]).
# `pos-12pt5`: MIN +12.5 / ORL -12.5. Both listed, so a rule that ignores WHOSE
# handicap it is has two markets to pick from at every |line|.
_MIN_ORL = [
    _m("asc-nba-min-orl-2026-10-23-neg-12pt5", "SPREAD", ("-12.50", "+12.50"), ("0.3200", "0.71")),
    _m("asc-nba-min-orl-2026-10-23-pos-12pt5", "SPREAD", ("+12.50", "-12.50"), ("0.9500", "0.06")),
]
_MIN_ORL_EVENT = "7763ba1c6e1e163be38cbe1b880d4cd9"


def _min_orl(side, line):
    return _row("nba", "spreads", side, line, "Orlando Magic",
                "Minnesota Timberwolves", _MIN_ORL_EVENT)


@pytest.mark.parametrize(
    "side, line, slug, price",
    [
        # Away = slug-first club: its line IS the slug's line, outcomes[0].
        ("away", -12.5, "asc-nba-min-orl-2026-10-23-neg-12pt5", 0.32),
        ("away", 12.5, "asc-nba-min-orl-2026-10-23-pos-12pt5", 0.95),
        # Home = slug-second club: the slug states the OTHER club's line.
        ("home", 12.5, "asc-nba-min-orl-2026-10-23-neg-12pt5", 0.71),
        ("home", -12.5, "asc-nba-min-orl-2026-10-23-pos-12pt5", 0.06),
    ],
)
def test_nba_spread_prices_the_boards_own_club_at_its_own_handicap(side, line, slug, price):
    body = mod.join_polymarket_to_board(_MIN_ORL, [_min_orl(side, line)])
    assert body["matched"] == 1, body["refusals"]
    (match,) = body["matches"]
    assert match["polymarket_slug"] == slug
    assert match["polymarket_probability"] == pytest.approx(price)


def test_spread_reachability_before_the_fix_every_signed_spread_refused(monkeypatch):
    _legacy_spreads(monkeypatch)
    body = mod.join_polymarket_to_board(_MIN_ORL, [_min_orl("away", -12.5)])
    assert body["matched"] == 0
    assert body["refusals"]["side_not_an_outcome_of_this_market"] == 1


def test_home_plus_line_never_takes_the_market_whose_slug_shows_that_number():
    """ATL @ CHA `spreads home 11.5` -- a fleet miss. `pos-11pt5` is ATL +11.5
    and CHA -11.5; reading the slug's number as the home side's line would buy
    CHA -11.5 for a CHA +11.5 row."""
    markets = [_m("asc-nba-atl-cha-2026-10-23-pos-11pt5", "SPREAD", ("+11.50", "-11.50"), ("0.9000", "0.11"))]
    row = _row("nba", "spreads", "home", 11.5, "Charlotte Hornets",
               "Atlanta Hawks", "fd0625e5807950edc0d2d31772639859")
    assert mod.join_polymarket_to_board(markets, [row])["matched"] == 0


def test_an_outcome_array_that_disagrees_with_the_slug_refuses():
    """Position AND number must agree; a reordered array is not guessed at."""
    markets = [_m("asc-nba-min-orl-2026-10-23-neg-12pt5", "SPREAD", ("+12.50", "-12.50"), ("0.7100", "0.32"))]
    body = mod.join_polymarket_to_board(markets, [_min_orl("away", -12.5)])
    assert body["matched"] == 0
    assert body["refusals"]["side_not_an_outcome_of_this_market"] == 1


def test_the_spread_resolvers_key_on_the_board_row():
    body = mod.join_polymarket_to_board(_MIN_ORL, [_min_orl("home", 12.5)])
    price = mod.polymarket_price_resolver(body["matches"])
    ticker = mod.polymarket_ticker_resolver(body["matches"])
    assert price(_min_orl("home", 12.5)) is not None
    assert ticker(_min_orl("home", 12.5))["slug"] == "asc-nba-min-orl-2026-10-23-neg-12pt5"
    assert price(_min_orl("away", 12.5)) is None


def test_an_unmeasured_league_keeps_refusing_signed_spreads():
    markets = [_m("asc-ncaab-duke-unc-2026-11-20-neg-3pt5", "SPREAD", ("-3.50", "+3.50"), ("0.5", "0.5"))]
    row = _row("ncaab", "spreads", "away", -3.5, "North Carolina Tar Heels",
               "Duke Blue Devils", "e1", date="2026-11-20")
    assert mod.join_polymarket_to_board(markets, [row])["matched"] == 0


# --------------------------------------------------------------------------
# 3. Two-word nicknames on moneylines
# --------------------------------------------------------------------------


def test_trail_blazers_moneyline_prices_portland():
    """POR @ SAC `h2h away` refused `side_not_an_outcome_of_this_market` on the
    fleet: "Trail Blazers" resolved to no club."""
    markets = [_m("aec-nba-por-sac-2026-10-23", "MONEYLINE", ("Trail Blazers", "Kings"), ("0.8000", "0.21"))]
    row = _row("nba", "h2h", "away", None, "Sacramento Kings",
               "Portland Trail Blazers", "93ae924d3fc473aadfa50b26a9a2115b")
    body = mod.join_polymarket_to_board(markets, [row])
    assert body["matched"] == 1, body["refusals"]
    assert body["matches"][0]["polymarket_probability"] == pytest.approx(0.80)


@pytest.mark.parametrize(
    "sport, nickname, club",
    [
        ("nba", "Trail Blazers", "portland trail blazers"),
        ("nhl", "Blue Jackets", "columbus blue jackets"),
        ("nhl", "Red Wings", "detroit red wings"),
        ("nhl", "Maple Leafs", "toronto maple leafs"),
        ("nhl", "Golden Knights", "vegas golden knights"),
        ("mlb", "Red Sox", "boston red sox"),
        ("mlb", "White Sox", "chicago white sox"),
    ],
)
def test_two_word_nicknames_resolve(sport, nickname, club):
    from syndicate.features.shared.team_aliases import canonical_team

    assert canonical_team(sport, nickname) == club
