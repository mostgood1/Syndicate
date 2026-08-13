"""`#411` -- a line its own market has moved off is not an available bet.

REPORTED FROM THE BOARD: "Framber Valdez for Detroit shows o15.5, 16.5, and 17.5
and odds are about the same so these must be at different times." Measured on
production 2026-08-13, exactly that:

    outs        15.5  seen 55m  3 books
    outs        16.5  seen 53m  1 book
    outs        17.5  seen 17m  8 books   <- the only live one
    strikeouts   2.5  seen 19m  1 book    <- current, the line falls as he pitches
    strikeouts   3.5  seen 38m  2 books
    strikeouts   4.5  seen 79m  7 books   <- abandoned an hour ago

`book_quotes` is a CHANGE LOG, and the grid keys a market instance by LINE. So
every line a book has ever offered becomes its own row and keeps its last price
forever, with nothing marking it dead. The reader sees three "available"
alternates at similar odds and only one can be bet.

BOOK COUNT IS NOT THE DISCRIMINATOR, which is what makes this subtle:
`strikeouts 4.5` carries SEVEN books and is an hour stale, while `strikeouts 2.5`
carries one and is live. Only `seen_age_seconds` separates them -- which is why
`#366` had to lift that clock to row level before this was fixable at all.

RELATIVE, NOT ABSOLUTE. A flat "drop anything older than 20 minutes" would empty
a thin market where every line is legitimately an hour old and nothing has moved.
A line is dropped only when its OWN market has a materially fresher one, which is
evidence the book repriced and left it behind.
"""

from __future__ import annotations

from syndicate.features.shared.book_grid import (
    _STALE_ALT_LINE_LAG_SECONDS,
    drop_superseded_lines,
)


def _row(market: str, line: float, seen: float | None, books: int = 1, player: str = "Framber Valdez"):
    return {
        "sport": "mlb", "event_id": "evt-1", "kind": "prop", "segment": "full",
        "market": market, "player_name": player, "line": line,
        "seen_age_seconds": seen, "books_quoting": books,
    }


def test_the_reported_valdez_outs_case():
    grid = [
        _row("outs", 15.5, 55 * 60, books=3),
        _row("outs", 16.5, 53 * 60, books=1),
        _row("outs", 17.5, 17 * 60, books=8),
    ]
    kept, dropped = drop_superseded_lines(grid)
    assert dropped == 2
    assert [r["line"] for r in kept] == [17.5], "only the line the market is actually on survives"


def test_book_count_does_not_rescue_a_stale_line():
    # `strikeouts 4.5` had SEVEN books and was an hour dead; `2.5` had one and was
    # live. Any rule that weighted book count would keep exactly the wrong row.
    grid = [
        _row("strikeouts", 2.5, 19 * 60, books=1),
        _row("strikeouts", 4.5, 79 * 60, books=7),
    ]
    kept, _ = drop_superseded_lines(grid)
    assert [r["line"] for r in kept] == [2.5]


def test_a_uniformly_old_market_keeps_every_line():
    # THE FLAT-THRESHOLD TRAP. Every line an hour old with nothing fresher is a
    # quiet market, not a stale one. Dropping them all would empty the board and
    # look like a capture outage.
    grid = [_row("hits_allowed", n, 70 * 60) for n in (5.5, 6.5, 7.5)]
    kept, dropped = drop_superseded_lines(grid)
    assert dropped == 0 and len(kept) == 3


def test_lines_within_the_lag_all_survive():
    # Books stagger their updates; a few minutes apart is normal simultaneity,
    # not evidence anybody moved off a line.
    grid = [_row("earned_runs", 2.5, 60), _row("earned_runs", 3.5, 60 + _STALE_ALT_LINE_LAG_SECONDS - 30)]
    kept, dropped = drop_superseded_lines(grid)
    assert dropped == 0 and len(kept) == 2


def test_markets_do_not_prune_each_other():
    # `outs` being fresh says nothing about whether a `strikeouts` line is live.
    grid = [_row("outs", 17.5, 60), _row("strikeouts", 4.5, 79 * 60)]
    kept, dropped = drop_superseded_lines(grid)
    assert dropped == 0, "a fresh market must not prune a different market's lines"


def test_two_players_do_not_prune_each_other():
    # Same market, different players, is two markets.
    grid = [
        _row("outs", 17.5, 60, player="Framber Valdez"),
        _row("outs", 15.5, 79 * 60, player="Tarik Skubal"),
    ]
    kept, dropped = drop_superseded_lines(grid)
    assert dropped == 0


def test_an_unknown_age_is_never_pruned():
    # Absence of a clock is not evidence of staleness. Pruning on None is how a
    # capture hiccup would silently empty the board -- the same
    # unknown-must-not-default-permissive rule, pointed the other way.
    grid = [_row("outs", 17.5, 60), _row("outs", 15.5, None)]
    kept, dropped = drop_superseded_lines(grid)
    assert dropped == 0 and len(kept) == 2


def test_it_runs_before_the_row_bound():
    # A superseded line must not consume a slot a live one needed.
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "syndicate" / "features" / "shared" / "book_grid.py").read_text(encoding="utf-8")
    drop_at = src.index("grid, superseded = drop_superseded_lines(grid)")
    bound_at = src.index("return grid[: max(0, int(max_rows))]")
    assert drop_at < bound_at
