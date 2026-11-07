"""The venue fan-in names a Kalshi quote's game with Kalshi's OWN code -> name pairs.

`#764` follow-up, lane `kalshi-fanin-college-naming`, 2026-11-07.

`_kalshi_game_token_uncached` resolved a ticker with `match_event_blob` and no
`code_names`, then named the match with `game_token` alone. Kalshi's college
codes (`CSF`, `SDAK`) are not in our alias maps, and `game_token` refuses NCAAF
by design, so on the fleet's 11-07 data ncaaf named 0 of its Kalshi quotes.
With `#764` refusing unnamed quotes on totals keys, that cost correct prices:
`KXNCAAFTOTAL-26NOV07CINHOU-61` on Cincinnati @ Houston and
`KXNCAAMBTOTAL-26NOV07CSFSDAK-177` on CSU Fullerton @ South Dakota were refused.

The fix resolves through `kalshi_board_join._resolve_event` -- the order path's
resolver, with Kalshi's published "<Club> wins" pairs -- and names a match the
way `venue_quote_fanin._row_game_token` names a row.

Fixtures are the real market rows read off the fleet's Kalshi state 2026-11-07.
"""

from __future__ import annotations

import json
import time
from functools import partial

import pytest

from syndicate.features.shared import venue_quote_adapters as adapters
from syndicate.features.shared.venue_quote_adapters import _kalshi_ok_reason, kalshi_outcome
from syndicate.features.shared.venue_quote_fanin import (
    _row_game_token,
    apply_venue_quotes_to_grid,
    collect_quotes,
)

DATE = "2026-11-07"


def _market(ticker, series, title, yes, no):
    return {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "series": series,
        "title": title,
        "yes_ask_dollars": yes,
        "no_ask_dollars": no,
        "close_time": "2026-11-09T20:00:00Z",
        "status": "active",
    }


CINHOU = [
    _market("KXNCAAFGAME-26NOV07CINHOU-CIN", "KXNCAAFGAME", "Cincinnati wins", "0.2300", "0.7800"),
    _market("KXNCAAFGAME-26NOV07CINHOU-HOU", "KXNCAAFGAME", "Houston wins", "0.7800", "0.2300"),
    _market("KXNCAAFTOTAL-26NOV07CINHOU-62", "KXNCAAFTOTAL", "Full Game: Over 61.5 points scored", "0.4900", "0.5200"),
    _market("KXNCAAFTOTAL-26NOV07CINHOU-64", "KXNCAAFTOTAL", "Full Game: Over 63.5 points scored", "0.4400", "0.5700"),
]
# West Florida / North Alabama: not on our board, and Kalshi publishes no name for `UWF`.
UWFLUNA = [
    _market("KXNCAAFTOTAL-26NOV07UWFLUNA-43", "KXNCAAFTOTAL", "Full Game: Over 42.5 points scored", "0.6100", "0.4800"),
]
CSFSDAK = [
    _market("KXNCAAMBGAME-26NOV07CSFSDAK-CSF", "KXNCAAMBGAME", "Cal State Fullerton wins", "0.4800", "0.5300"),
    _market("KXNCAAMBGAME-26NOV07CSFSDAK-SDAK", "KXNCAAMBGAME", "South Dakota wins", "0.5200", "0.4900"),
    _market("KXNCAAMBTOTAL-26NOV07CSFSDAK-177", "KXNCAAMBTOTAL", "Full Game: Over 176.5 points scored", "0.4800", "0.5300"),
]

CIN_HOU = {"event_id": "evt-cin-hou", "home_team": "Houston Cougars", "away_team": "Cincinnati Bearcats"}
OKST_KSU = {"event_id": "evt-okst-ksu", "home_team": "Kansas State Wildcats", "away_team": "Oklahoma State Cowboys"}
IOWA_NW = {"event_id": "evt-iowa-nw", "home_team": "Northwestern Wildcats", "away_team": "Iowa Hawkeyes"}
CSF_SDAK = {"event_id": "evt-csf-sdak", "home_team": "South Dakota Coyotes", "away_team": "CSU Fullerton Titans"}


@pytest.fixture
def kalshi_state(tmp_path, monkeypatch):
    """A real-shaped `kalshi_markets.json`, read through the same path production uses."""

    def _write(*markets):
        series: dict[str, dict] = {}
        for market in markets:
            series.setdefault(market["series"], {"markets": []})["markets"].append(market)
        root = tmp_path / "reports"
        (root / "intelligence").mkdir(parents=True, exist_ok=True)
        (root / "intelligence" / "kalshi_markets.json").write_text(
            json.dumps({"fetched_at": time.time(), "series": series})
        )
        monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(root))

    return _write


def _quotes_by_ref(sport, games):
    out = kalshi_outcome(sport, DATE, games=games)
    return out, {q.venue_ref + "|" + q.side: q for q in out.quotes if q.venue_ref}


def _grid_row(sport, game, line):
    return {
        "sport": sport,
        "kind": "game",
        "event_id": game["event_id"],
        "market": "totals",
        "segment": "full",
        "line": line,
        "sides": ["over", "under"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "game": {"state": "pre"},
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


def _reprice(sport, grid, games):
    now = time.time() + 1
    collected = collect_quotes(
        sport, DATE, now=now, games=games,
        adapters={"kalshi": partial(kalshi_outcome, games=games)},
    )
    return apply_venue_quotes_to_grid(grid, sport, DATE, collected=collected, now=now)


def test_the_shipped_default_names_with_the_venues_pairs():
    assert adapters._KALSHI_FANIN_VENUE_NAMES_ENABLED is True


# ---------------------------------------------------------------------------
# 1. REACHABILITY: off != on, at the adapter.
# ---------------------------------------------------------------------------


def test_off_vs_on_an_ncaaf_total_names_its_game(kalshi_state, monkeypatch):
    kalshi_state(*CINHOU)
    games = [CIN_HOU, OKST_KSU]

    monkeypatch.setattr(adapters, "_KALSHI_FANIN_VENUE_NAMES_ENABLED", False)
    _out, off = _quotes_by_ref("ncaaf", games)
    monkeypatch.setattr(adapters, "_KALSHI_FANIN_VENUE_NAMES_ENABLED", True)
    _out, on = _quotes_by_ref("ncaaf", games)

    ref = "KXNCAAFTOTAL-26NOV07CINHOU-62|over"
    assert off[ref].game is None, "fixture does not reproduce the defect, so ON proves nothing"
    row_token = _row_game_token({**CIN_HOU, "sport": "ncaaf"}, "ncaaf")
    assert row_token
    assert on[ref].game == row_token
    # Both legs of the contract, and the game is in the key, as for every named total.
    assert on["KXNCAAFTOTAL-26NOV07CINHOU-62|under"].game == row_token
    assert row_token in on[ref].key


def test_an_ncaab_code_our_alias_map_lacks_is_named_from_kalshis_title(kalshi_state):
    """`CSF` is "Cal State Fullerton wins" on Kalshi and "CSU Fullerton Titans" on our board."""
    kalshi_state(*CSFSDAK)
    _out, on = _quotes_by_ref("ncaab", [CSF_SDAK])

    assert on["KXNCAAMBTOTAL-26NOV07CSFSDAK-177|over"].game == _row_game_token(
        {**CSF_SDAK, "sport": "ncaab"}, "ncaab"
    )


# ---------------------------------------------------------------------------
# 2. THROUGH THE FAN-IN, where `#764` refuses what names no game.
# ---------------------------------------------------------------------------


def test_off_vs_on_the_correct_ncaaf_total_prices_its_own_row(kalshi_state, monkeypatch):
    kalshi_state(*CINHOU)
    games = [CIN_HOU]

    monkeypatch.setattr(adapters, "_KALSHI_FANIN_VENUE_NAMES_ENABLED", False)
    off_grid = [_grid_row("ncaaf", CIN_HOU, 61.5)]
    off = _reprice("ncaaf", off_grid, games)
    monkeypatch.setattr(adapters, "_KALSHI_FANIN_VENUE_NAMES_ENABLED", True)
    on_grid = [_grid_row("ncaaf", CIN_HOU, 61.5)]
    on = _reprice("ncaaf", on_grid, games)

    # OFF: the correct quote names no game, and `#764` refuses it.
    assert off["unnamed_role_key_detected"] == 2, off
    assert off_grid[0]["best"]["over"].get("price_source") is None
    # ON: it names Cincinnati @ Houston and prices that row.
    assert on["unnamed_role_key_detected"] == 0, on
    assert on_grid[0]["best"]["over"]["venue_ref"] == "KXNCAAFTOTAL-26NOV07CINHOU-62"
    assert on_grid[0]["best"]["under"]["venue_ref"] == "KXNCAAFTOTAL-26NOV07CINHOU-62"


def test_a_ticker_for_another_board_game_does_not_price_this_row(kalshi_state):
    """`CINHOU-64` once priced Oklahoma St @ Kansas St 63.5 (11-06). Named, it keys
    to Cincinnati @ Houston and cannot answer the other game's row."""
    kalshi_state(*CINHOU)
    games = [CIN_HOU, OKST_KSU]
    grid = [_grid_row("ncaaf", OKST_KSU, 63.5)]

    stats = _reprice("ncaaf", grid, games)

    assert grid[0]["best"]["over"].get("venue_ref") is None, stats
    assert grid[0]["best"]["over"]["price"] == -110


def test_a_ticker_for_a_game_we_do_not_carry_stays_refused(kalshi_state):
    """West Florida / North Alabama is not on our board and `UWF` has no name, so
    the quote still names no game, and `#764` still refuses it on Iowa @ Northwestern."""
    kalshi_state(*CINHOU, *UWFLUNA)
    games = [CIN_HOU, IOWA_NW]
    grid = [_grid_row("ncaaf", IOWA_NW, 42.5)]

    stats = _reprice("ncaaf", grid, games)

    assert stats["unnamed_role_key_detected"] == 2, stats
    assert "KXNCAAFTOTAL-26NOV07UWFLUNA-43" in stats["unnamed_role_key_sample"]
    assert grid[0]["best"]["over"].get("venue_ref") is None


# ---------------------------------------------------------------------------
# 3. THE INSTRUMENT.
# ---------------------------------------------------------------------------


def test_the_reason_counts_game_lines_left_unnamed(kalshi_state):
    kalshi_state(*CINHOU, *UWFLUNA)
    out, _quotes = _quotes_by_ref("ncaaf", [CIN_HOU])

    assert "game_line_unnamed:1" in str(out.reason), out.reason


def test_the_reason_keeps_its_old_positional_form():
    assert _kalshi_ok_reason(0, 0, 0) is None
    assert _kalshi_ok_reason(0, 0, 0, game_unnamed=3) == "game_line_unnamed:3"
