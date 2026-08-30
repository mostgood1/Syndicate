"""`#603`, second pass: an UNNAMED venue quote may not answer a contested key.

WHY A SECOND PASS WAS NEEDED
----------------------------

The first pass added a game-qualified key and refused a quote that NAMES a
different fixture. Measured in production 2026-08-30, on the first board pool
built after it deployed, it rejected NOTHING -- because the quotes doing the
damage name nothing at all:

    distinct venue_refs in use      35
    refs answering >1 FIXTURE       11
    rows served by such a ref      108 / 148   (73%)

    KXBELGIANPLGAME-26SEP06BEVOHL-TIE   claimed by 33 fixtures, five countries
    KXMLBTOTAL-26AUG301410CWSMIN-5      the SERVED HEADLINE price, at -525,
                                        on Baltimore Orioles@Athletics

A bare key is `sport|market|side|line` and carries no game term, so one unnamed
quote answers every row that shares it. The first pass documented its own
asymmetry -- "a quote that names none is allowed through exactly as it is
today" -- which was true, and was the wrong bar: it made the fix unable to touch
the majority case, and the majority case was wrong.

The rule now is COLLIDABILITY: an unnamed quote may answer a key only if
exactly ONE game claims it.
"""

from __future__ import annotations

import time

from syndicate.features.shared.venue_quote_adapters import quote_key
from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes_to_grid


def _row(event_id: str, away: str, home: str, *, line: float = 7.5) -> dict:
    return {
        "sport": "mlb",
        "kind": "game",
        "event_id": event_id,
        "market": "totals",
        "segment": "full_game",
        "line": line,
        "sides": ["over", "under"],
        "home_team": home,
        "away_team": away,
        "game": {"state": "live"},
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


def _quote(now: float, side: str, *, game: str | None, line: float = 7.5, price: int = -525):
    key = str(quote_key("mlb", "totals", side, line))
    return key, Quote(
        key=key, source="kalshi", sport="mlb", market="totals", side=side,
        probability=None, american=price, line=line, fetched_at=now - 10.0,
        venue_ref="KXMLBTOTAL-26AUG301410CWSMIN-8", game=game,
    )


def _apply(grid, quotes, now):
    return apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-29", collected={"quotes": quotes}, now=now
    )


def test_TWO_games_sharing_a_key_refuse_an_unnamed_quote():
    """THE PRODUCTION CASE. One CWS@MIN ticker priced Orioles@Athletics at -525.

    Neither game may take it: the quote cannot say which it belongs to, and a
    wrong price is worse than none -- no price shows an empty cell, a wrong one
    shows a spectacular edge.
    """
    now = time.time()
    grid = [
        _row("evt-bal-ath", "Baltimore Orioles", "Athletics"),
        _row("evt-phi-laa", "Philadelphia Phillies", "Los Angeles Angels"),
    ]
    quotes = dict([_quote(now, "over", game=None), _quote(now, "under", game=None)])
    stats = _apply(grid, quotes, now)

    assert stats["ambiguous_unnamed_rejected"] == 4, stats
    assert stats["repriced"] == 0, "a contested key was allowed to reprice"
    for row in grid:
        assert row["best"]["over"]["price"] == -110, "the wrong-game price landed"
        assert row["best"]["over"].get("price_source") is None


def test_ONE_game_claiming_the_key_still_takes_an_unnamed_quote():
    """off != on, and the COVERAGE half of it.

    The guard must bite only where the key is contested. A sport with one live
    game must keep working exactly as before, or this trades a wrong-price bug
    for a no-price bug.
    """
    now = time.time()
    grid = [_row("evt-bal-ath", "Baltimore Orioles", "Athletics")]
    quotes = dict([_quote(now, "over", game=None), _quote(now, "under", game=None)])
    stats = _apply(grid, quotes, now)

    assert stats["ambiguous_unnamed_rejected"] == 0
    assert stats["repriced"] == 2, stats
    assert grid[0]["best"]["over"]["price"] == -525


def test_an_NCAAF_row_never_takes_a_quote_that_names_a_REAL_fixture():
    """ncaaf has no club map -- `game_token('ncaaf', ...)` returns None for
    every row -- so `_row_game_token` falls back to `evt:<event_id>`.

    THE MECHANISM IS GUARD 1, NOT THIS FILE'S GUARD, and the distinction is
    worth pinning rather than blurring. Because the fallback always yields SOME
    token, `evt:evt-1` versus a real club pair is a provable mismatch and
    `_quote_is_for_another_game` refuses it first. The contested-key rule never
    gets a turn here.

    Pinned anyway, because the OUTCOME is what production depends on and it is
    reachable from two directions: if the `evt:` fallback were ever removed, the
    row token would go None, guard 1 could no longer prove a mismatch, and the
    contested-key rule below would become the only thing standing between a
    Toledo@Miss State ticker and a Memphis@UNLV row.
    """
    now = time.time()
    grid = [
        _row("evt-1", "Memphis Tigers", "UNLV Rebels"),
        _row("evt-2", "Toledo Rockets", "Mississippi State Bulldogs"),
    ]
    for row in grid:                      # ncaaf-style: unresolvable to a token
        row["sport"] = "ncaaf"
    quotes = {}
    for side in ("over", "under"):
        key = str(quote_key("ncaaf", "totals", side, 7.5))
        quotes[key] = Quote(
            key=key, source="kalshi", sport="ncaaf", market="totals", side=side,
            probability=None, american=-525, line=7.5, fetched_at=now - 10.0,
            venue_ref="tsc-cfb-toledo-mst-2026-09-04-total-49pt5",
            game="mississippi state bulldogs+toledo rockets",
        )
    stats = apply_venue_quotes_to_grid(
        grid, "ncaaf", "2026-08-29", collected={"quotes": quotes}, now=now
    )
    assert stats["repriced"] == 0, "a quote landed on a row it does not name"
    for row in grid:
        assert row["best"]["over"]["price"] == -110
    # SOME guard refused all four sides. Which one is an implementation detail
    # today and is asserted loosely on purpose -- asserting the wrong counter is
    # how a test comes to pass for a reason it did not intend.
    refused = stats["cross_game_rejected"] + stats["ambiguous_unnamed_rejected"]
    assert refused == 4, stats


def test_the_claimant_map_reads_BOTH_row_shapes():
    """A grid row carries `sides` (list); a CANDIDATE row carries `side`
    (scalar). Reading only the plural produced an EMPTY map on the candidate
    path, and an absent key takes the permissive branch -- so the guard was
    silently inert there. That is `unknown-must-not-default-permissive`, broken
    inside the helper written to enforce a different rule."""
    from syndicate.features.shared.venue_quote_fanin import _key_claimants

    plural = [
        {"sport": "soccer", "event_id": "e1", "market": "totals", "line": 3.5,
         "sides": ["over", "under"]},
        {"sport": "soccer", "event_id": "e2", "market": "totals", "line": 3.5,
         "sides": ["over", "under"]},
    ]
    singular = [
        {"sport": "soccer", "event_id": "e1", "market": "totals", "line": 3.5, "side": "over"},
        {"sport": "soccer", "event_id": "e2", "market": "totals", "line": 3.5, "side": "over"},
    ]
    assert _key_claimants(plural, "soccer")["soccer|totals|over|3.5"] == {"e1", "e2"}
    assert _key_claimants(singular, "soccer")["soccer|totals|over|3.5"] == {"e1", "e2"}


def test_a_quote_that_NAMES_its_game_survives_a_contested_key():
    """The named path is untouched. This guard is about quotes that cannot say
    which game they price, never about ones that can."""
    now = time.time()
    grid = [
        _row("evt-bal-ath", "Baltimore Orioles", "Athletics"),
        _row("evt-phi-laa", "Philadelphia Phillies", "Los Angeles Angels"),
    ]
    token = "athletics+baltimore orioles"
    quotes = dict([
        _quote(now, "over", game=token),
        _quote(now, "under", game=token),
    ])
    stats = _apply(grid, quotes, now)

    assert stats["ambiguous_unnamed_rejected"] == 0
    # It names Orioles@Athletics, so that row takes it and the other REFUSES it
    # by name -- which is the FIRST pass's guard, still working.
    assert grid[0]["best"]["over"]["price"] == -525
    assert grid[1]["best"]["over"]["price"] == -110
    assert stats["cross_game_rejected"] >= 1


def test_THIRTY_THREE_fixtures_on_one_ticker_yield_ZERO_matches():
    """The Belgian tie ticker, at its measured scale.

    Reduced but faithful: one unnamed quote, many games sharing the key. The
    old behaviour stamped every one of them.
    """
    now = time.time()
    grid = [_row(f"evt-{i}", f"Away {i}", f"Home {i}") for i in range(33)]
    quotes = dict([_quote(now, "over", game=None), _quote(now, "under", game=None)])
    stats = _apply(grid, quotes, now)

    assert stats["repriced"] == 0
    assert stats["ambiguous_unnamed_rejected"] == 66  # 33 games x 2 sides
    assert all(r["best"]["over"]["price"] == -110 for r in grid)


def test_the_guard_is_keyed_per_LINE_not_per_market():
    """Two games on DIFFERENT lines do not contest each other.

    `over 7.5` and `over 8.5` are different keys, so each is claimed by one game
    and both keep their quote. Over-refusing here would silently delete good
    coverage across a whole slate.
    """
    now = time.time()
    grid = [
        _row("evt-a", "Away A", "Home A", line=7.5),
        _row("evt-b", "Away B", "Home B", line=8.5),
    ]
    quotes = dict([
        _quote(now, "over", game=None, line=7.5),
        _quote(now, "under", game=None, line=7.5),
        _quote(now, "over", game=None, line=8.5, price=-300),
        _quote(now, "under", game=None, line=8.5, price=-300),
    ])
    stats = _apply(grid, quotes, now)

    assert stats["ambiguous_unnamed_rejected"] == 0, "distinct lines were treated as contested"
    assert stats["repriced"] == 4
    assert grid[0]["best"]["over"]["price"] == -525
    assert grid[1]["best"]["over"]["price"] == -300
