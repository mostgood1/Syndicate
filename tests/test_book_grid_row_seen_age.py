"""`#366` -- the second clock existed per-cell and never reached the row.

`book_grid` has computed BOTH ages per book cell since it first documented why
they differ:

    age_seconds       time since this price last MOVED
    seen_age_seconds  time since we last LOOKED at this market

and only ever summarised the first to row level. The board renders ROWS, so
every consumer above `build_book_grid` could see only the moved-clock.

`book_quotes` is a change log -- an unchanged price writes no row -- so a
motionless market reads as ancient. Measured on the served board 2026-08-11:
NFL rows at a median 424 minutes and soccer at 786. Both read as a capture
outage; both were normal pregame markets nobody had repriced. The module's own
docstring warns about exactly this ("all 100 MLB rows carried ~11.9h ages inside
a 1.2-minute window, which read as a capture outage and was in fact 100
motionless markets") -- and the board was making that mistake anyway, because
the answer stopped one level short of where it was needed.

Production evidence the data was always there: 12,254 of 12,254 cells in the
live MLB artifact carried `seen_age_seconds`, 12,212 non-null, with a sample
cell reading `age_seconds 243.2` against `seen_age_seconds 62.8`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.shared.book_grid import build_book_grid

NOW = datetime(2026, 8, 11, 23, 45, 0, tzinfo=timezone.utc)


def _quote(book: str, side: str, *, moved_minutes: float, price: int = -110) -> dict:
    observed = NOW - timedelta(minutes=moved_minutes)
    return {
        "sport": "nfl",
        #  is part of _INSTANCE_FIELDS; without it the pivot groups rows
        # under a different key and builds nothing.
        "kind": "game",
        "event_id": "evt-1",
        "market": "h2h",
        "segment": "full",
        "home_team": "Cincinnati Bengals",
        "away_team": "Detroit Lions",
        "bookmaker": book,
        # _freshest_per_book_side reads "selection", not "side".
        "selection": side,
        "side": side,
        "price": price,
        "line": None,
        # _observed_at reads book_updated_at/snapshot_ts/captured_at -- NOT observed_at.
        "book_updated_at": observed.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _last_seen_for(rows, *, seen_minutes: float) -> dict:
    """A sidecar stamping every quote key as observed `seen_minutes` ago."""
    from syndicate.features.shared.odds_book_quotes import quote_key

    stamp = (NOW - timedelta(minutes=seen_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {quote_key(row): stamp for row in rows}


def test_the_row_carries_both_clocks():
    rows = [_quote("fanduel", "home", moved_minutes=420), _quote("draftkings", "away", moved_minutes=420)]
    grid = build_book_grid(rows, now=NOW, last_seen=_last_seen_for(rows, seen_minutes=1))
    assert grid, "no grid row built"
    row = grid[0]
    assert row["age_seconds"] > 20000, "the moved-clock should still report ~7 hours"
    assert row["seen_age_seconds"] is not None, "the row lost the second clock again"
    assert row["seen_age_seconds"] < 120, (
        "a market observed one minute ago must not read as seven hours stale -- "
        "this is the NFL 424m / soccer 786m misreading"
    )


def test_absent_sidecar_leaves_the_row_clock_unknown_not_fresh():
    # Omitting `last_seen` must yield None -- "unknown", never a fabricated zero.
    rows = [_quote("fanduel", "home", moved_minutes=30), _quote("draftkings", "away", moved_minutes=30)]
    grid = build_book_grid(rows, now=NOW)
    assert grid[0]["seen_age_seconds"] is None
    assert grid[0]["age_seconds"] is not None


def test_the_row_takes_the_freshest_observation():
    # MIN, matching `freshest_row_age`: an average is a number no book offers.
    rows = [_quote("fanduel", "home", moved_minutes=400), _quote("draftkings", "away", moved_minutes=400)]
    from syndicate.features.shared.odds_book_quotes import quote_key

    stale = (NOW - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = (NOW - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    last_seen = {quote_key(rows[0]): stale, quote_key(rows[1]): fresh}
    grid = build_book_grid(rows, now=NOW, last_seen=last_seen)
    assert grid[0]["seen_age_seconds"] < 200, "the row should report its freshest look, not its stalest"


def test_the_two_clocks_can_disagree_by_hours():
    # The whole point: a price untouched for 7h that we checked 60s ago is a
    # motionless market, not a dead feed. If these ever collapse into one number
    # the board is back to guessing.
    rows = [_quote("fanduel", "home", moved_minutes=420), _quote("draftkings", "away", moved_minutes=420)]
    grid = build_book_grid(rows, now=NOW, last_seen=_last_seen_for(rows, seen_minutes=1))
    row = grid[0]
    assert row["age_seconds"] - row["seen_age_seconds"] > 20000
