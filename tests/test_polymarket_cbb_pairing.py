"""Polymarket college basketball (`cbb` / `wcbb`) pairs with the NCAAB / WNCAAB boards.

Lane `polymarket-cbb-pairing`, todo `#755`. Every slug, outcome and price below
was read off the fleet's Polymarket slate on 2026-11-04 17:10Z, and every board
name off that day's NCAAB / WNCAAB board.

Three defects, each with an off != on test:

1. `cbb` / `wcbb` were never mapped to `ncaab` / `wncaab`, so 0 quotes reached
   either board (`_VENUE_LEAGUE_ALIASES`).
2. A Polymarket quote whose pair was LEARNED from the moneyline carried
   `evt:<event_id>`, while a college board row, whose clubs now canonicalise,
   carries the club pair -- so no learned total could ever match
   (`venue_quote_adapters._learned_game_token`).
3. College moneylines name only the mascot ("Lancers", "Hawks"), which
   `canonical_team` rightly refuses, and the order-path join resolves Polymarket's
   own slug codes (`longwd`, `stjoe`) to nothing (the learned-pair fallbacks).
"""
from __future__ import annotations

import time
from functools import partial

import pytest

from syndicate.features.shared import polymarket_board_join as pbj
from syndicate.features.shared import venue_quote_adapters as adapters
from syndicate.features.shared import venue_quote_fanin as fanin
from syndicate.features.shared.venue_quote_fanin import (
    _row_game_token,
    apply_venue_quotes_to_grid,
    collect_quotes,
)

_DATE = "2026-11-04"

# Longwood @ Saint Joseph's: both MASCOTS are ambiguous in the registry, both slug
# codes resolve to nothing -- the case every defect above bites on.
_LONGWOOD = {
    "event_id": "evt-longwd-stjoe",
    "away_team": "Longwood Lancers",
    "home_team": "Saint Joseph's Hawks",
}
# CSU Northridge @ Wichita State: a SECOND game, so a learned pair has someone to
# be confused with.
_CSUN = {
    "event_id": "evt-csunr-wichst",
    "away_team": "CSU Northridge Matadors",
    "home_team": "Wichita St Shockers",
}
_GAMES = [_LONGWOOD, _CSUN]


def _slate():
    return {
        "fetched_at": time.time(),
        "markets": [
            {"slug": "aec-cbb-longwd-stjoe-2026-11-04", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
             "outcomes": '["Lancers","Hawks"]', "outcomePrices": '["0.16","0.85"]',
             "gameStartTime": "2026-11-05T00:00:00Z", "orderPriceMinTickSize": 0.01,
             "minimumTradeQty": 1, "orderable": True},
            {"slug": "tsc-cbb-longwd-stjoe-2026-11-04-150pt5", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
             "line": 150.5, "outcomes": '["Over","Under"]', "outcomePrices": '["0.54","0.50"]',
             "gameStartTime": "2026-11-05T00:00:00Z", "orderPriceMinTickSize": 0.01,
             "minimumTradeQty": 1, "orderable": True},
            {"slug": "aec-cbb-csunr-wichst-2026-11-04", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
             "outcomes": '["Matadors","Shockers"]', "outcomePrices": '["0.08","0.93"]',
             "gameStartTime": "2026-11-05T00:30:00Z", "orderPriceMinTickSize": 0.01,
             "minimumTradeQty": 1, "orderable": True},
            {"slug": "tsc-cbb-csunr-wichst-2026-11-04-161pt5", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
             "line": 161.5, "outcomes": '["Over","Under"]', "outcomePrices": '["0.50","0.52"]',
             "gameStartTime": "2026-11-05T00:30:00Z", "orderPriceMinTickSize": 0.01,
             "minimumTradeQty": 1, "orderable": True},
        ],
    }


@pytest.fixture
def slate(monkeypatch):
    payload = _slate()
    monkeypatch.setattr(adapters, "_artifact", lambda parts: (payload, time.time()))
    return payload


# ---------------------------------------------------------------------------
# 1. The league aliases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token, sport", [("cbb", "ncaab"), ("wcbb", "wncaab")])
def test_college_basketball_league_tokens_map_to_our_sports(token, sport):
    assert pbj._effective_league({"league": token}) == sport


def test_the_alias_is_what_makes_the_league_reachable(monkeypatch, slate):
    """off != on: without the alias the adapter finds no ncaab row at all."""
    on = adapters.polymarket_us_outcome("ncaab", _DATE, games=_GAMES)
    monkeypatch.setattr(pbj, "_VENUE_LEAGUE_ALIASES", {"cfb": "ncaaf"})
    off = adapters.polymarket_us_outcome("ncaab", _DATE, games=_GAMES)

    assert on.quotes, on.reason
    assert not off.quotes and off.reason == "no_polymarket_row_for_league_ncaab", off.reason


# ---------------------------------------------------------------------------
# 2. The learned game token is the board row's own
# ---------------------------------------------------------------------------


def test_a_learned_total_carries_the_token_the_board_row_carries(slate):
    totals = [q for q in adapters.polymarket_us_outcome("ncaab", _DATE, games=_GAMES).quotes
              if q.market == "totals"]
    row = {"sport": "ncaab", **_LONGWOOD}

    assert _row_game_token(row, "ncaab") == "longwood+saint joseph's"
    assert {q.game for q in totals if "longwd" in str(q.venue_ref)} == {"longwood+saint joseph's"}


def test_ncaaf_keeps_its_event_token():
    """`game_token` refuses NCAAF, so the learned token is unchanged there."""
    game = {"event_id": "evt-nmxst-flst",
            "away_team": "New Mexico State Aggies", "home_team": "Florida State Seminoles"}

    assert adapters._learned_game_token("ncaaf", game) == "evt:evt-nmxst-flst"


def _grid_row(game, line):
    """`best` per side and a STALE book age, so a matching venue quote would
    genuinely reprice -- a 0 is then a refusal, not an inert fixture."""
    return {
        "sport": "ncaab", "market": "totals", "line": line, **game,
        "sides": ["over", "under"],
        "best": {
            "over": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
            "under": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
        },
        "game": {"state": "live"},
    }


def _reprice(grid):
    now = time.time() + 5
    games = [_LONGWOOD, _CSUN]
    collected = collect_quotes(
        "ncaab", _DATE, now=now, games=games,
        adapters={"polymarket_us": partial(adapters.polymarket_us_outcome, games=games)},
    )
    return apply_venue_quotes_to_grid(grid, "ncaab", _DATE, collected=collected, now=now)


def test_the_grid_reprices_the_right_game_at_the_right_line(slate):
    grid = [_grid_row(_LONGWOOD, 150.5), _grid_row(_CSUN, 161.5)]

    out = _reprice(grid)

    assert out["repriced"] == 4, out
    assert grid[0]["best"]["over"]["bookmaker"] == "polymarket"
    assert grid[0]["best"]["over"]["price"] == adapters.probability_to_american(0.54)
    assert grid[1]["best"]["under"]["price"] == adapters.probability_to_american(0.52)


def test_the_learned_token_is_what_lets_a_total_match(monkeypatch, slate):
    """off != on: with the old `evt:` token the venue's game-qualified key is one
    no college row offers, so nothing matches -- silently, which is why it hid."""
    monkeypatch.setattr(
        adapters, "_learned_game_token",
        lambda sport, game: adapters.event_game_token(game.get("event_id")),
    )
    grid = [_grid_row(_LONGWOOD, 150.5), _grid_row(_CSUN, 161.5)]

    out = _reprice(grid)

    assert out["sides_seen"] == 4 and out["repriced"] == 0, out


# ---------------------------------------------------------------------------
# 3. Mascots, in the price feed and in the order-path join
# ---------------------------------------------------------------------------


def test_a_bare_mascot_moneyline_is_named_by_its_learned_game(slate):
    h2h = {q.side: q.probability for q in adapters.polymarket_us_outcome("ncaab", _DATE, games=_GAMES).quotes
           if q.market == "h2h" and "longwd" in str(q.venue_ref)}

    assert h2h == {"longwood": 0.16, "saint joseph's": 0.85}


def test_without_a_schedule_the_mascots_stay_unresolved(slate):
    """off != on for the naming: no learned game, no name. ("Matadors" is unique
    in the registry and resolves either way, so only Longwood's game is read.)"""
    out = adapters.polymarket_us_outcome("ncaab", _DATE)

    assert not [q for q in out.quotes if q.market == "h2h" and "longwd" in str(q.venue_ref)]
    assert "Lancers" in str(out.reason), out.reason


def test_a_mascot_that_resolves_directly_is_left_alone(monkeypatch, slate):
    """Only when `canonical_team` fails: a direct answer is never overridden."""
    from syndicate.features.shared import team_aliases

    real = team_aliases.canonical_team
    monkeypatch.setattr(
        team_aliases, "canonical_team",
        lambda sport, value: "direct answer" if value == "Hawks" else real(sport, value),
    )

    h2h = {q.side for q in adapters.polymarket_us_outcome("ncaab", _DATE, games=_GAMES).quotes
           if q.market == "h2h" and "longwd" in str(q.venue_ref)}

    assert h2h == {"longwood", "direct answer"}


def _shortlist_row(game, market, side, line=None):
    return {
        "sport": "ncaab", "market": market, "side": side, "line": line, "segment": "full",
        "commence_time": "2026-11-05 00:00:00+00:00", **game,
    }


def _join(rows):
    return pbj.join_polymarket_to_board(_slate()["markets"], rows, selected_date=_DATE)


def test_the_order_path_join_pairs_college_rows_with_their_own_slug():
    rows = [
        _shortlist_row(_LONGWOOD, "h2h", "home"),
        _shortlist_row(_LONGWOOD, "h2h", "away"),
        _shortlist_row(_LONGWOOD, "totals", "over", 150.5),
    ]

    matches = {(m["market"], m["side"]): m for m in _join(rows)["matches"]}

    assert set(matches) == {("h2h", "home"), ("h2h", "away"), ("totals", "over")}, matches
    assert matches[("h2h", "home")]["polymarket_slug"] == "aec-cbb-longwd-stjoe-2026-11-04"
    assert matches[("h2h", "home")]["polymarket_probability"] == pytest.approx(0.85)
    assert matches[("h2h", "away")]["polymarket_probability"] == pytest.approx(0.16)
    assert matches[("totals", "over")]["polymarket_slug"] == "tsc-cbb-longwd-stjoe-2026-11-04-150pt5"


def test_the_learned_pair_is_what_makes_the_join_pair(monkeypatch):
    """off != on: without the learned pair, Polymarket's codes match nothing."""
    monkeypatch.setattr(pbj, "_LEARNED_PAIR_SPORTS", frozenset())

    assert _join([_shortlist_row(_LONGWOOD, "totals", "over", 150.5)])["matched"] == 0


def test_a_learned_pair_never_pairs_another_game():
    """CSUN's row must not take Longwood's total at a line both could carry."""
    rows = [_shortlist_row(_CSUN, "totals", "over", 150.5)]

    assert _join(rows)["matched"] == 0


def test_a_reversed_pair_is_the_return_fixture_not_this_game():
    """`stjoe-longwd` would be Saint Joseph's at Longwood: another game."""
    markets = _slate()["markets"] + [
        {"slug": "tsc-cbb-stjoe-longwd-2026-11-04-150pt5", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
         "line": 150.5, "outcomes": '["Over","Under"]', "outcomePrices": '["0.40","0.62"]',
         "gameStartTime": "2026-11-05T00:00:00Z", "orderPriceMinTickSize": 0.01,
         "minimumTradeQty": 1, "orderable": True},
    ]
    rows = [_shortlist_row(_LONGWOOD, "totals", "over", 150.5)]

    matches = pbj.join_polymarket_to_board(markets, rows, selected_date=_DATE)["matches"]

    assert [m["polymarket_slug"] for m in matches] == ["tsc-cbb-longwd-stjoe-2026-11-04-150pt5"]


def test_a_pair_whose_mascots_fit_two_games_learns_nothing():
    twin = {"event_id": "evt-other", "away_team": "Notre Dame Lancers", "home_team": "Iona Hawks"}

    pairs = adapters._polymarket_pair_games(_slate()["markets"], "ncaab", [_LONGWOOD, twin])

    assert ("longwd", "stjoe") not in pairs, pairs


def test_the_join_learns_only_for_college_basketball():
    rows = [{"sport": "ncaaf", "event_id": "e1", "home_team": "A", "away_team": "B"},
            {"sport": "ncaab", **_LONGWOOD}]

    learned = pbj._learn_moneyline_pairs(_slate()["markets"], rows)

    assert set(learned) == {"ncaab"}
    assert ("longwd", "stjoe") in learned["ncaab"]


# ---------------------------------------------------------------------------
# 4. A college quote that names no game is dropped
# ---------------------------------------------------------------------------

# Towson @ Utah, read off the fleet 2026-11-04 21:24Z: `tows` resolves to nothing
# and the game had no learned moneyline, so its alternate-total ladder was
# emitted with `game=None`. One rung sits at CSUN's line, which no other board
# game holds -- the shape that priced Cal Poly @ Arizona from Towson's market.
_TOWSON_RUNG = {
    "slug": "tsc-cbb-tows-utah-2026-11-04-161pt5", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
    "line": 161.5, "outcomes": '["Over","Under"]', "outcomePrices": '["0.80","0.25"]',
    "gameStartTime": "2026-11-06T02:00:00Z", "orderPriceMinTickSize": 0.01,
    "minimumTradeQty": 1, "orderable": True,
}


@pytest.fixture
def slate_with_unnamed_game(monkeypatch):
    payload = _slate()
    payload["markets"].append(dict(_TOWSON_RUNG))
    monkeypatch.setattr(adapters, "_artifact", lambda parts: (payload, time.time()))
    return payload


def test_the_unnamed_fixture_really_names_no_game(slate_with_unnamed_game):
    assert adapters.game_token("ncaab", "utah", "tows") is None


def test_an_unnamed_college_quote_cannot_price_another_game(slate_with_unnamed_game):
    grid = [_grid_row(_LONGWOOD, 150.5), _grid_row(_CSUN, 161.5)]

    _reprice(grid)

    assert grid[1]["best"]["over"]["price"] == adapters.probability_to_american(0.50)
    assert grid[1]["best"]["under"]["price"] == adapters.probability_to_american(0.52)


def test_dropping_unnamed_quotes_is_what_protects_the_row(monkeypatch, slate_with_unnamed_game):
    """off != on: without the drop, Towson's rung answers the bare key first and
    CSUN's total takes Towson's prices -- the fleet's Cal Poly reading.

    The fan-in's own `#764` refusal is switched off as well: it is a second,
    independent guard on the same shape (an unnamed venue quote on a totals
    key), and with it on this row is protected even without the adapter drop.
    `tests/test_venue_fanin_unnamed_role_key.py` pins that half."""
    monkeypatch.setattr(adapters, "_NAMED_GAME_ONLY_SPORTS", frozenset())
    monkeypatch.setattr(fanin, "_UNNAMED_ROLE_KEY_REFUSAL_ENABLED", False)
    grid = [_grid_row(_LONGWOOD, 150.5), _grid_row(_CSUN, 161.5)]

    _reprice(grid)

    assert grid[1]["best"]["over"]["price"] == adapters.probability_to_american(0.80)


def test_the_drop_is_counted_in_the_reason(slate_with_unnamed_game):
    out = adapters.polymarket_us_outcome("ncaab", _DATE, games=_GAMES)

    assert not [q for q in out.quotes if "tows" in str(q.venue_ref)]
    assert "unnamed_game_refused:1" in str(out.reason), out.reason


# ---------------------------------------------------------------------------
# The daily archive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token, sport", [("cbb", "ncaab"), ("wcbb", "wncaab")])
def test_the_archive_files_college_polymarket_rows_under_our_sport(token, sport):
    from syndicate.features.shared.venue_daily_odds import sport_for_polymarket_league

    assert sport_for_polymarket_league(token) == sport


def test_the_archive_keeps_womens_college_basketball(monkeypatch):
    from syndicate.features.shared.venue_daily_odds import in_scope_sports

    monkeypatch.delenv("SYNDICATE_VENUE_ODDS_SPORTS", raising=False)

    assert {"wncaab", "ncaab", "soccer"} <= in_scope_sports()


def test_the_archive_override_still_replaces_the_set(monkeypatch):
    from syndicate.features.shared.venue_daily_odds import in_scope_sports

    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_SPORTS", "nba")

    assert in_scope_sports() == frozenset({"nba"})
