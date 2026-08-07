"""S1 / L1-A -- the per-book price grid.

The grid is a serve-time pivot over `book_quotes`, which already holds every
book: measured 2026-08-07, 11 books captured while the board rendered one best
price. These cover the ways a pivot like this goes silently wrong -- sides
landing in different rows (which under-reports book coverage), spreads pairing
on an equal line instead of a mirrored one (which manufactured 716 phantom
arbitrages on 2026-08-06), and an all-day append log putting a stale price next
to a fresh one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from syndicate.features.shared.book_grid import book_grid_summary, build_book_grid

NOW = datetime(2026, 8, 7, 20, 0, 0, tzinfo=timezone.utc)


def _quote(**overrides):
    row = {
        "sport": "mlb",
        "kind": "game",
        "event_id": "evt-1",
        "segment": "full_game",
        "market": "h2h",
        "player_name": "",
        "selection": "home",
        "line": None,
        "price": -110,
        "bookmaker": "draftkings",
        "home_team": "Baltimore Orioles",
        "away_team": "Los Angeles Angels",
        "commence_time": "2026-08-07T23:05:00Z",
        "snapshot_ts": "2026-08-07T19:55:00Z",
    }
    row.update(overrides)
    return row


def test_both_sides_land_in_one_row():
    # If over and under split across rows the grid under-reports coverage and
    # no-vig can never be computed.
    grid = build_book_grid(
        [
            _quote(selection="home", price=-120, bookmaker="draftkings"),
            _quote(selection="away", price=+105, bookmaker="draftkings"),
            _quote(selection="home", price=-115, bookmaker="fanduel"),
            _quote(selection="away", price=+100, bookmaker="fanduel"),
        ],
        now=NOW,
    )
    assert len(grid) == 1
    row = grid[0]
    assert sorted(row["sides"]) == ["away", "home"]
    assert sorted(row["books"]) == ["draftkings", "fanduel"]
    assert row["books_quoting"] == 2


def test_spreads_pair_signed_not_equal_line():
    """home -1.5 pairs with away +1.5. Pairing on an EQUAL line is what
    manufactured 716 phantom arbitrages out of bets that were not opposite
    sides of anything."""
    grid = build_book_grid(
        [
            _quote(market="spreads", selection="home", line=-1.5, price=+130),
            _quote(market="spreads", selection="away", line=1.5, price=-150),
        ],
        now=NOW,
    )
    assert len(grid) == 1
    assert sorted(grid[0]["sides"]) == ["away", "home"]


def test_a_different_alternate_line_is_a_different_row():
    grid = build_book_grid(
        [
            _quote(market="spreads", selection="home", line=-1.5, price=+130),
            _quote(market="spreads", selection="away", line=1.5, price=-150),
            _quote(market="spreads", selection="home", line=-2.5, price=+210),
            _quote(market="spreads", selection="away", line=2.5, price=-260),
        ],
        now=NOW,
    )
    assert len(grid) == 2
    assert {abs(float(row["line"])) for row in grid} == {1.5, 2.5}


def test_best_price_is_the_best_PAYOUT_in_both_signs():
    # Raw int comparison is correct for American odds in both signs -- larger
    # positive, and negative closer to zero. It looks like it needs a branch.
    grid = build_book_grid(
        [
            _quote(selection="home", price=+140, bookmaker="a"),
            _quote(selection="home", price=+165, bookmaker="b"),
            _quote(selection="away", price=-200, bookmaker="a"),
            _quote(selection="away", price=-180, bookmaker="b"),
        ],
        now=NOW,
    )
    best = grid[0]["best"]
    assert best["home"]["price"] == 165 and best["home"]["bookmaker"] == "b"
    assert best["away"]["price"] == -180 and best["away"]["bookmaker"] == "b"


def test_freshest_quote_per_book_wins():
    # The shard is an append-only log for the whole day; a naive pass would keep
    # whichever row happened to come last in file order.
    grid = build_book_grid(
        [
            _quote(selection="home", price=-200, bookmaker="dk", snapshot_ts="2026-08-07T12:00:00Z"),
            _quote(selection="home", price=-130, bookmaker="dk", snapshot_ts="2026-08-07T19:50:00Z"),
            _quote(selection="home", price=-175, bookmaker="dk", snapshot_ts="2026-08-07T15:00:00Z"),
        ],
        now=NOW,
    )
    assert grid[0]["cells"]["dk"]["home"]["price"] == -130


def test_a_best_price_lagging_the_market_is_labelled_suspect():
    """A best price far clear of consensus is usually a stale line, not an edge.

    Observed on the real 2026-07-29 shard: draftkings +388 where consensus was
    +116, and 885 of 3,049 rows carried a laggard best. Layer 1 must not DROP it
    -- a researcher wants to see it -- but presenting a six-hour-old number as
    the best available bet is how a research surface becomes a trap.
    """
    grid = build_book_grid(
        [
            _quote(selection="home", price=+388, bookmaker="stale_book", snapshot_ts="2026-08-07T12:00:00Z"),
            _quote(selection="home", price=+110, bookmaker="fresh_a", snapshot_ts="2026-08-07T19:59:00Z"),
            _quote(selection="home", price=+115, bookmaker="fresh_b", snapshot_ts="2026-08-07T19:59:00Z"),
        ],
        now=NOW,
    )
    best = grid[0]["best"]["home"]
    assert best["bookmaker"] == "stale_book"          # still reported
    assert best["suspect_stale"] is True              # but labelled
    assert best["lag_behind_freshest_seconds"] > 900


def test_a_fresh_best_is_not_labelled_suspect():
    grid = build_book_grid(
        [
            _quote(selection="home", price=+150, bookmaker="a", snapshot_ts="2026-08-07T19:58:00Z"),
            _quote(selection="home", price=+120, bookmaker="b", snapshot_ts="2026-08-07T19:59:00Z"),
        ],
        now=NOW,
    )
    assert grid[0]["best"]["home"]["suspect_stale"] is False


def test_single_book_rows_survive_and_are_counted():
    # 948 of 3,049 real rows are single-book. They render as an empty grid with
    # one number, and that fraction is the honest measure of the surface --
    # dropping them would make the board look better than the data is.
    grid = build_book_grid([_quote(selection="home", price=-110, bookmaker="only")], now=NOW)
    assert len(grid) == 1
    summary = book_grid_summary(grid)
    assert summary["rows_single_book"] == 1
    assert summary["rows_with_3plus_books"] == 0


def test_summary_reports_coverage():
    rows = []
    for book in ("a", "b", "c", "d"):
        rows.append(_quote(selection="home", price=-110, bookmaker=book))
        rows.append(_quote(selection="away", price=-105, bookmaker=book))
    rows.append(_quote(event_id="evt-2", selection="home", price=+120, bookmaker="a"))
    summary = book_grid_summary(build_book_grid(rows, now=NOW))
    assert summary["rows"] == 2
    assert summary["distinct_books"] == 4
    assert summary["rows_with_3plus_books"] == 1
    assert summary["rows_single_book"] == 1
    assert summary["max_books_on_a_row"] == 4


def test_rows_without_a_price_are_ignored_not_crashed_on():
    grid = build_book_grid(
        [_quote(price=None), _quote(selection="home", price=-110, bookmaker="a")], now=NOW
    )
    assert len(grid) == 1


def test_a_stale_cell_carries_a_human_reason_not_just_a_flag():
    """The UI greys cells WITH A REASON. The string is written once, here --
    a UI that re-derives it will drift from the flag and they will disagree."""
    grid = build_book_grid(
        [
            _quote(selection="home", price=+388, bookmaker="stale_book", snapshot_ts="2026-08-07T12:00:00Z"),
            _quote(selection="home", price=+110, bookmaker="fresh", snapshot_ts="2026-08-07T19:59:00Z"),
        ],
        now=NOW,
    )
    row = grid[0]
    stale_cell = row["cells"]["stale_book"]["home"]
    fresh_cell = row["cells"]["fresh"]["home"]

    assert stale_cell["stale"] is True
    assert "behind the freshest quote" in stale_cell["reason"]
    assert "7h" in stale_cell["reason"]          # human duration, not raw seconds
    assert fresh_cell["stale"] is False and fresh_cell["reason"] is None


def test_row_gaps_explain_why_a_row_is_not_a_full_grid():
    single = build_book_grid([_quote(selection="home", price=-110, bookmaker="only")], now=NOW)[0]
    assert single["complete"] is False
    joined = " | ".join(single["gaps"])
    assert "only 1 book quoting" in joined
    assert "one-sided" in joined          # no-vig cannot be computed


def test_a_complete_row_has_no_gaps():
    rows = []
    for book in ("a", "b", "c"):
        rows.append(_quote(selection="home", price=-110, bookmaker=book))
        rows.append(_quote(selection="away", price=-105, bookmaker=book))
    row = build_book_grid(rows, now=NOW)[0]
    assert row["complete"] is True
    assert row["gaps"] == []


def test_empty_input_is_an_empty_grid():
    assert build_book_grid([], now=NOW) == []
    assert book_grid_summary([])["rows"] == 0


def test_widest_rows_come_first():
    rows = [_quote(event_id="thin", selection="home", price=-110, bookmaker="a")]
    for book in ("a", "b", "c"):
        rows.append(_quote(event_id="wide", selection="home", price=-110, bookmaker=book))
    grid = build_book_grid(rows, now=NOW)
    assert grid[0]["event_id"] == "wide"
