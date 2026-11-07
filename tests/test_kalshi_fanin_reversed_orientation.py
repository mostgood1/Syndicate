"""A Kalshi ticker that lists a game's clubs in the OTHER order still names that game.

Lane `kalshi-fanin-reversed-orientation`, 2026-11-07.

`kalshi_catalogue._candidate_blobs` builds `AWAY+HOME` only, for every sport but
soccer. A neutral-site game has no real home, and Kalshi and our odds feed can each
pick a different one: measured on the fleet 2026-11-07 20:14Z, `NEBPROV` (Kalshi:
Nebraska first) against our Providence @ Nebraska was `no_match`, and `ok` onto that
one event with home/away swapped. Its totals named no game, so `#764` refused them.

The fan-in now retries once with home/away swapped, after a `no_match` only, over the
games played on the ticker's own date.

Fixture rows are the real market rows read off the fleet's Kalshi state 2026-11-07
(tickers and titles verbatim). `KXNCAAMBTOTAL-26NOV10KUUK-150` is modelled on them:
no KUUK total was listed yet.
"""

from __future__ import annotations

import json
import time
from functools import partial

import pytest

from syndicate.features.shared import kalshi_board_join
from syndicate.features.shared import venue_quote_adapters as adapters
from syndicate.features.shared.venue_quote_adapters import _kalshi_ok_reason, kalshi_outcome
from syndicate.features.shared.venue_quote_fanin import (
    _distinct_games,
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
        "close_time": "2026-11-12T00:00:00Z",
        "status": "active",
    }


NEBPROV = [
    _market("KXNCAAMBGAME-26NOV07NEBPROV-PROV", "KXNCAAMBGAME", "Providence wins", "0.4300", "0.5800"),
    _market("KXNCAAMBGAME-26NOV07NEBPROV-NEB", "KXNCAAMBGAME", "Nebraska wins", "0.5900", "0.4200"),
    _market("KXNCAAMBTOTAL-26NOV07NEBPROV-184", "KXNCAAMBTOTAL", "Full Game: Over 183.5 points scored", "0.4900", "0.5200"),
]
# The same event, dated two days later: what a reversed ticker for ANOTHER day looks like.
NEBPROV_NOV09 = [
    _market("KXNCAAMBTOTAL-26NOV09NEBPROV-184", "KXNCAAMBTOTAL", "Full Game: Over 183.5 points scored", "0.4900", "0.5200"),
]
KUUK = [
    _market("KXNCAAMBGAME-26NOV10KUUK-UK", "KXNCAAMBGAME", "Kentucky wins", "0.3400", "0.6700"),
    _market("KXNCAAMBGAME-26NOV10KUUK-KU", "KXNCAAMBGAME", "Kansas wins", "0.7000", "0.3300"),
    _market("KXNCAAMBTOTAL-26NOV10KUUK-150", "KXNCAAMBTOTAL", "Full Game: Over 149.5 points scored", "0.4800", "0.5300"),
]
# A ticker in the board's OWN order, as the control.
CSFSDAK = [
    _market("KXNCAAMBGAME-26NOV07CSFSDAK-CSF", "KXNCAAMBGAME", "Cal State Fullerton wins", "0.4800", "0.5300"),
    _market("KXNCAAMBGAME-26NOV07CSFSDAK-SDAK", "KXNCAAMBGAME", "South Dakota wins", "0.5200", "0.4900"),
    _market("KXNCAAMBTOTAL-26NOV07CSFSDAK-177", "KXNCAAMBTOTAL", "Full Game: Over 176.5 points scored", "0.4800", "0.5300"),
]

# Our board's orientation for the neutral-site game: Providence @ Nebraska.
PROV_NEB = {"event_id": "evt-prov-neb", "home_team": "Nebraska Cornhuskers", "away_team": "Providence Friars",
            "commence_time": "2026-11-07T23:00:00Z"}
# Champions Classic, 8:30 PM ET on 11-10 -- 01:30Z on 11-11, so the UTC date is NOT the game's.
UK_KU = {"event_id": "evt-uk-ku", "home_team": "Kansas Jayhawks", "away_team": "Kentucky Wildcats",
         "commence_time": "2026-11-11T01:30:00Z"}
CSF_SDAK = {"event_id": "evt-csf-sdak", "home_team": "South Dakota Coyotes", "away_team": "CSU Fullerton Titans",
            "commence_time": "2026-11-07T20:00:00Z"}


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


def _grid_row(game, line, market="totals"):
    return {
        "sport": "ncaab",
        "kind": "game",
        "event_id": game["event_id"],
        "commence_time": game["commence_time"],
        "market": market,
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


def _games(*games):
    """The fan-in's OWN game list, built from grid rows -- the shape production hands the adapter."""
    return _distinct_games([_grid_row(game, 150.5) for game in games], "ncaab")


def _quotes_by_ref(games):
    out = kalshi_outcome("ncaab", DATE, games=games)
    return out, {q.venue_ref + "|" + q.side: q for q in out.quotes if q.venue_ref}


def _reprice(grid):
    now = time.time() + 1
    games = _distinct_games(grid, "ncaab")
    collected = collect_quotes(
        "ncaab", DATE, now=now, games=games,
        adapters={"kalshi": partial(kalshi_outcome, games=games)},
    )
    return apply_venue_quotes_to_grid(grid, "ncaab", DATE, collected=collected, now=now)


def _token(game):
    return _row_game_token({**game, "sport": "ncaab"}, "ncaab")


def test_the_shipped_default_tries_the_other_order():
    assert adapters._KALSHI_FANIN_REVERSED_ORDER_ENABLED is True


def test_the_fan_ins_games_carry_local_dates_and_not_commence_time():
    """`commence_time` would change the STRAIGHT match (`match_event_blob` splits pairs on it)."""
    (game,) = _games(UK_KU)
    assert "2026-11-10" in game["start_dates"], game
    assert "commence_time" not in game
    undated = _distinct_games([{**_grid_row(PROV_NEB, 150.5), "commence_time": None}], "ncaab")
    assert undated[0]["start_dates"] == ()


# ---------------------------------------------------------------------------
# 1. REACHABILITY: off != on.
# ---------------------------------------------------------------------------


def test_off_vs_on_a_reversed_ticker_names_its_game(kalshi_state, monkeypatch):
    kalshi_state(*NEBPROV)
    games = _games(PROV_NEB, CSF_SDAK)

    monkeypatch.setattr(adapters, "_KALSHI_FANIN_REVERSED_ORDER_ENABLED", False)
    off_out, off = _quotes_by_ref(games)
    monkeypatch.setattr(adapters, "_KALSHI_FANIN_REVERSED_ORDER_ENABLED", True)
    on_out, on = _quotes_by_ref(games)

    ref = "KXNCAAMBTOTAL-26NOV07NEBPROV-184|over"
    assert off[ref].game is None, "fixture does not reproduce the defect, so ON proves nothing"
    assert on[ref].game == _token(PROV_NEB)
    assert on["KXNCAAMBTOTAL-26NOV07NEBPROV-184|under"].game == _token(PROV_NEB)
    assert "game_line_reversed_order" not in str(off_out.reason)
    # Two moneylines and one total, every one named only by the retry.
    assert "game_line_reversed_order:3" in str(on_out.reason), on_out.reason


def test_off_vs_on_the_reversed_total_prices_its_own_row(kalshi_state, monkeypatch):
    kalshi_state(*NEBPROV)

    monkeypatch.setattr(adapters, "_KALSHI_FANIN_REVERSED_ORDER_ENABLED", False)
    off_grid = [_grid_row(PROV_NEB, 183.5)]
    off = _reprice(off_grid)
    monkeypatch.setattr(adapters, "_KALSHI_FANIN_REVERSED_ORDER_ENABLED", True)
    on_grid = [_grid_row(PROV_NEB, 183.5)]
    on = _reprice(on_grid)

    # OFF: the right game's quote names no game, and `#764` refuses it.
    assert off["unnamed_role_key_detected"] == 2, off
    assert off_grid[0]["best"]["over"].get("venue_ref") is None
    # ON: it names Providence @ Nebraska and prices that row.
    assert on["unnamed_role_key_detected"] == 0, on
    assert on_grid[0]["best"]["over"]["venue_ref"] == "KXNCAAMBTOTAL-26NOV07NEBPROV-184"
    assert on_grid[0]["best"]["under"]["venue_ref"] == "KXNCAAMBTOTAL-26NOV07NEBPROV-184"


# ---------------------------------------------------------------------------
# 2. THE DATE IS THE GAME'S.
# ---------------------------------------------------------------------------


def test_the_date_is_the_games_not_the_slates(kalshi_state):
    """Kentucky @ Kansas sits on the 11-07 slate's grid but is played 11-10 (ET)."""
    kalshi_state(*KUUK)
    _out, on = _quotes_by_ref(_games(UK_KU, PROV_NEB))

    assert on["KXNCAAMBTOTAL-26NOV10KUUK-150|over"].game == _token(UK_KU)


def test_a_reversed_ticker_dated_another_day_stays_unnamed(kalshi_state):
    """The other order of a pair on ANOTHER day is a return leg, not this game."""
    kalshi_state(*NEBPROV[:2], *NEBPROV_NOV09)
    _out, on = _quotes_by_ref(_games(PROV_NEB))

    assert on["KXNCAAMBTOTAL-26NOV09NEBPROV-184|over"].game is None


def test_games_without_dates_never_take_the_retry(kalshi_state):
    """The old game shape carries no `start_dates`: unknown is not permission."""
    kalshi_state(*NEBPROV)
    undated = [{k: v for k, v in PROV_NEB.items() if k != "commence_time"}]
    _out, on = _quotes_by_ref(undated)

    assert on["KXNCAAMBTOTAL-26NOV07NEBPROV-184|over"].game is None


# ---------------------------------------------------------------------------
# 3. NOTHING ELSE MOVES.
# ---------------------------------------------------------------------------


def test_a_straight_match_is_untouched_and_not_counted(kalshi_state):
    kalshi_state(*CSFSDAK)
    out, on = _quotes_by_ref(_games(CSF_SDAK))

    assert on["KXNCAAMBTOTAL-26NOV07CSFSDAK-177|over"].game == _token(CSF_SDAK)
    assert "game_line_reversed_order" not in str(out.reason), out.reason


def test_an_ambiguous_answer_is_a_refusal_and_is_not_retried(kalshi_state, monkeypatch):
    kalshi_state(*NEBPROV)
    monkeypatch.setattr(
        kalshi_board_join, "_resolve_event", lambda *a, **k: {"status": "ambiguous", "sport": "ncaab"}
    )
    tried = []
    monkeypatch.setattr(adapters, "_kalshi_reversed_order_token", lambda *a, **k: tried.append(1) or "evt:x")

    _out, on = _quotes_by_ref(_games(PROV_NEB))

    assert on["KXNCAAMBTOTAL-26NOV07NEBPROV-184|over"].game is None
    assert tried == []


def test_soccer_is_skipped_because_both_orders_are_already_tried():
    naming = adapters._kalshi_naming_context(NEBPROV)
    assert naming is not None
    assert adapters._kalshi_reversed_order_token(NEBPROV[2], "soccer", _games(PROV_NEB), naming) is None


def test_the_reason_keeps_its_old_positional_form():
    assert _kalshi_ok_reason(0, 0, 0) is None
    assert _kalshi_ok_reason(0, 0, 0, game_reversed=2) == "game_line_reversed_order:2"
