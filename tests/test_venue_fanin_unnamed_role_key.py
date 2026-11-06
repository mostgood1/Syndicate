"""`#764`: a live venue's quote that names NO game may not price a totals or
spreads row.

WHY
---

`_unconfirmed_on_a_contested_key` (`#603`) lets an unnamed quote answer a bare
key that only ONE GRID game claims. The grid is not the venue's slate: Kalshi
lists games the board does not carry, and a totals key
(`sport|totals|side|line`) holds no game term, so "uncontested on the grid" is
not "uncontested".

Measured 2026-11-06 (read-only replay of the fan-in, fleet `3d376da7c`, every
sport with a grid): unnamed Kalshi totals priced 26 board sides, and all 26 were
another game's market. `KXNCAAMBTOTAL-26NOV06CSNKSU-163` (CSU Northridge /
Kansas St) priced Texas Southern @ LSU 162.5. The same replay found 0 correct
sides priced that way, and 143 of 143 unnamed Kalshi MONEYLINE sides were the
right game, which is why h2h is out of scope.

The tests below are the off != on reachability pair on both paths, the live
benchmark the defect would have rewritten, and the coverage that must survive.
"""

from __future__ import annotations

import copy
import time

import pytest

from syndicate.features.shared import venue_quote_fanin as fanin
from syndicate.features.shared.venue_quote_adapters import quote_key
from syndicate.features.shared.venue_quote_fanin import (
    Quote,
    _row_game_token,
    _unnamed_venue_quote_on_a_role_key,
    apply_venue_quotes,
    apply_venue_quotes_to_grid,
)

SPORT = "ncaab"
DATE = "2026-11-06"
LINE = 162.5
# The OTHER game's contract: CSU Northridge / Kansas St, not Texas Southern @ LSU.
OTHER_GAME_TICKER = "KXNCAAMBTOTAL-26NOV06CSNKSU-163"


def _grid_row(*, state: str = "pre") -> dict:
    return {
        "sport": SPORT,
        "kind": "game",
        "event_id": "evt-txso-lsu",
        "market": "totals",
        "segment": "full",
        "line": LINE,
        "sides": ["over", "under"],
        "home_team": "LSU Tigers",
        "away_team": "Texas Southern Tigers",
        "game": {"state": state},
        "books": ["fanduel"],
        "books_quoting": 1,
        "age_seconds": 600.0,
        "best": {
            side: {"price": -110, "bookmaker": "fanduel", "age_seconds": 600.0}
            for side in ("over", "under")
        },
        "cells": {"fanduel": {"over": {"price": -110}, "under": {"price": -110}}},
        "consensus": {"over": -110, "under": -110},
    }


def _quote(now: float, side: str, *, game: str | None, source: str = "kalshi",
           market: str = "totals", price: int = 150) -> tuple[str, Quote]:
    key = str(quote_key(SPORT, market, side, LINE))
    return key, Quote(
        key=key, source=source, sport=SPORT, market=market, side=side,
        probability=None, american=price, line=LINE, fetched_at=now - 5.0,
        venue_ref=OTHER_GAME_TICKER, game=game,
    )


def _unnamed_pair(now: float, **kw) -> dict:
    return dict([_quote(now, "over", game=None, **kw), _quote(now, "under", game=None, **kw)])


def _grid(grid, quotes, now):
    return apply_venue_quotes_to_grid(grid, SPORT, DATE, collected={"quotes": quotes}, now=now)


def test_the_shipped_default_REFUSES():
    assert fanin._UNNAMED_ROLE_KEY_REFUSAL_ENABLED is True


# ---------------------------------------------------------------------------
# 1. REACHABILITY: off != on, on the grid path production runs.
# ---------------------------------------------------------------------------


def test_off_the_other_games_total_prices_the_row(monkeypatch):
    """The defect, reproduced: with the refusal off, one game claims the key on
    the grid, so `#603` lets the unnamed quote through."""
    monkeypatch.setattr(fanin, "_UNNAMED_ROLE_KEY_REFUSAL_ENABLED", False)
    now = time.time()
    grid = [_grid_row()]

    stats = _grid(grid, _unnamed_pair(now), now)

    assert grid[0]["best"]["over"]["price"] == 150
    assert grid[0]["best"]["over"].get("price_source") == "kalshi"
    assert stats["ambiguous_unnamed_rejected"] == 0
    # Counted even when off: the counter is the defect's size, not its repair.
    assert stats["unnamed_role_key_detected"] == 2
    assert stats["unnamed_role_key_refusal_enabled"] is False


def test_on_the_row_keeps_its_book_price(monkeypatch):
    monkeypatch.setattr(fanin, "_UNNAMED_ROLE_KEY_REFUSAL_ENABLED", True)
    now = time.time()
    grid = [_grid_row()]

    stats = _grid(grid, _unnamed_pair(now), now)

    assert stats["repriced"] == 0, stats
    for side in ("over", "under"):
        assert grid[0]["best"][side]["price"] == -110
        assert grid[0]["best"][side].get("price_source") is None
        assert grid[0]["best"][side].get("venue_ref") is None
    assert stats["unnamed_role_key_detected"] == 2
    assert stats["unnamed_role_key_refusal_enabled"] is True
    # The contract is NAMED in the log/payload, so a production reading can be
    # checked against the ticker rather than only a count.
    assert stats["unnamed_role_key_sample"] == [OTHER_GAME_TICKER]
    shape = stats["venue_key_shape"]["role"]
    assert shape.get("refused_unnamed_role_key") == 2
    assert not shape.get("taken")


def test_a_LIVE_row_keeps_its_book_benchmark(monkeypatch):
    """Where the damage was real: `_reprice_live_benchmark` moves a live row's
    `cells`/`consensus` onto the venue, checking one VENUE, not one game. Off,
    the other game's line rewrites them; on, they are untouched."""
    now = time.time()

    monkeypatch.setattr(fanin, "_UNNAMED_ROLE_KEY_REFUSAL_ENABLED", False)
    off_row = _grid_row(state="live")
    before = copy.deepcopy(off_row)
    _grid([off_row], _unnamed_pair(now), now)
    assert (off_row["cells"], off_row["consensus"]) != (before["cells"], before["consensus"]), (
        "fixture does not reach the live benchmark rewrite, so the ON half proves nothing"
    )

    monkeypatch.setattr(fanin, "_UNNAMED_ROLE_KEY_REFUSAL_ENABLED", True)
    on_row = _grid_row(state="live")
    before = copy.deepcopy(on_row)
    _grid([on_row], _unnamed_pair(now), now)
    assert on_row["cells"] == before["cells"]
    assert on_row["consensus"] == before["consensus"]
    assert on_row["best"] == before["best"]


# ---------------------------------------------------------------------------
# 2. COVERAGE that must survive.
# ---------------------------------------------------------------------------


def test_a_quote_that_NAMES_this_game_still_prices_the_row():
    now = time.time()
    grid = [_grid_row()]
    token = _row_game_token(grid[0], SPORT)
    assert token
    quotes = dict([_quote(now, "over", game=token), _quote(now, "under", game=token)])

    stats = _grid(grid, quotes, now)

    assert stats["repriced"] == 2, stats
    assert grid[0]["best"]["over"]["price"] == 150
    assert stats["unnamed_role_key_detected"] == 0


@pytest.mark.parametrize("market", ["totals", "totals_alt", "spreads", "spreads_alt"])
@pytest.mark.parametrize("source", ["kalshi", "polymarket_us"])
def test_the_rule_covers_every_role_keyed_market_on_both_live_venues(market, source):
    _key, quote = _quote(time.time(), "over", game=None, source=source, market=market)
    assert _unnamed_venue_quote_on_a_role_key(quote, market) is True


@pytest.mark.parametrize("market", ["h2h", "player_points", None, ""])
def test_a_market_whose_side_names_the_club_or_player_is_out_of_scope(market):
    """h2h's side IS the club: 143 of 143 unnamed Kalshi moneyline sides were the
    right game. Props key by player."""
    _key, quote = _quote(time.time(), "over", game=None)
    assert _unnamed_venue_quote_on_a_role_key(quote, market) is False


def test_OddsAPI_is_deliberately_out_of_scope():
    """Its shard is the feed the grid is built from, and it was not measured."""
    _key, quote = _quote(time.time(), "over", game=None, source="oddsapi")
    assert _unnamed_venue_quote_on_a_role_key(quote, "totals") is False


def test_a_named_quote_is_never_this_rules_business():
    _key, quote = _quote(time.time(), "over", game="evt:evt-txso-lsu")
    assert _unnamed_venue_quote_on_a_role_key(quote, "totals") is False


# ---------------------------------------------------------------------------
# 3. THE OTHER PATH -- `apply_venue_quotes`, same helper, same switch.
# ---------------------------------------------------------------------------


def _board_rows() -> list[dict]:
    return [{
        "sport": SPORT, "market": "totals", "side": "over", "line": LINE,
        "event_id": "evt-txso-lsu",
        "home_team": "LSU Tigers", "away_team": "Texas Southern Tigers",
    }]


def test_board_path_off_vs_on(monkeypatch):
    now = time.time()
    collected = {SPORT: {"quotes": _unnamed_pair(now), "by_source": {}, "ceiling_seconds": 86400}}

    monkeypatch.setattr(fanin, "_UNNAMED_ROLE_KEY_REFUSAL_ENABLED", False)
    off = apply_venue_quotes(_board_rows(), DATE, collected_by_sport=collected, now=now)
    monkeypatch.setattr(fanin, "_UNNAMED_ROLE_KEY_REFUSAL_ENABLED", True)
    on = apply_venue_quotes(_board_rows(), DATE, collected_by_sport=collected, now=now)

    assert off["stamped"] == 1, off
    assert on["stamped"] == 0, on
    assert off["unnamed_role_key_detected"] == on["unnamed_role_key_detected"] == 1
    assert on["unnamed_role_key_refusal_enabled"] is True
