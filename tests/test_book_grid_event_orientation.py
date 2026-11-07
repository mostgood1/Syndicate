"""One event, one orientation (`book_grid.orient_events_to_latest`; lane wncaab-module, 2026-11-07).

OddsAPI changed a neutral-site college game's home/away mid-day (Nebraska @ Providence at 12:07Z, Providence @
Nebraska at 16:53Z). The quote log files prices under "home"/"away", so the morning's quotes named the other team:
the spread split into two grid rows, an h2h price could sit under the wrong team, and most of the event's board
rows matched no game on the Games rail. These pin the relabel and that nothing else moves.
"""

from __future__ import annotations

from datetime import datetime, timezone

from syndicate.features.shared.book_grid import build_book_grid, orient_events_to_latest

NOW = datetime(2026, 11, 7, 17, 30, 0, tzinfo=timezone.utc)
NEB, PROV = "Nebraska Cornhuskers", "Providence Friars"


def _q(away, home, captured, **overrides):
    row = {
        "sport": "ncaab", "kind": "game", "event_id": "e8b5", "segment": "full", "market": "h2h", "player_name": None,
        "selection": "home", "line": None, "price": -110, "bookmaker": "draftkings", "away_team": away,
        "home_team": home, "commence_time": "2026-11-08T00:00:00Z", "captured_at": captured, "snapshot_ts": captured,
    }
    row.update(overrides)
    return row


OLD, NEW = "2026-11-07T12:07:00+00:00", "2026-11-07T16:34:44+00:00"


def _flipped_day():
    """Book A quoted only before the change (Nebraska @ Providence), book B only after (Providence @ Nebraska).
    Nebraska is the favourite in both: -130 at A, -135 at B."""
    return [
        _q(NEB, PROV, OLD, bookmaker="booka", selection="away", price=-130),            # Nebraska
        _q(NEB, PROV, OLD, bookmaker="booka", selection="home", price=110),             # Providence
        _q(NEB, PROV, OLD, bookmaker="booka", market="spreads", selection="away", line=-2.5, price=-110),
        _q(NEB, PROV, OLD, bookmaker="booka", market="spreads", selection="home", line=2.5, price=-110),
        _q(NEB, PROV, OLD, bookmaker="booka", market="totals", selection="over", line=158.5, price=-110),
        _q(NEB, PROV, OLD, bookmaker="booka", market="totals", selection="under", line=158.5, price=-110),
        _q(PROV, NEB, NEW, bookmaker="bookb", selection="home", price=-135),            # Nebraska
        _q(PROV, NEB, NEW, bookmaker="bookb", selection="away", price=115),             # Providence
        _q(PROV, NEB, NEW, bookmaker="bookb", market="spreads", selection="home", line=-2.5, price=-112),
        _q(PROV, NEB, NEW, bookmaker="bookb", market="spreads", selection="away", line=2.5, price=-108),
    ]


def test_every_row_takes_the_newest_books_orientation_and_each_price_stays_with_its_team():
    grid = build_book_grid(_flipped_day(), now=NOW)
    assert {(r["away_team"], r["home_team"]) for r in grid} == {(PROV, NEB)}
    h2h = [r for r in grid if r["market"] == "h2h"]
    assert len(h2h) == 1
    assert h2h[0]["cells"]["booka"]["home"]["price"] == -130     # Nebraska at book A, never Providence's +110
    assert h2h[0]["cells"]["bookb"]["home"]["price"] == -135
    assert h2h[0]["cells"]["booka"]["away"]["price"] == 110


def test_the_spread_is_one_row_with_both_books_not_two():
    spreads = [r for r in build_book_grid(_flipped_day(), now=NOW) if r["market"] == "spreads"]
    assert len(spreads) == 1
    assert sorted(spreads[0]["books"]) == ["booka", "bookb"]
    assert spreads[0]["cells"]["booka"]["home"]["price"] == -110   # Nebraska -2.5 at book A, now under home


def test_off_is_not_on_the_old_pivot_split_the_spread():
    """Reachability: without the relabel the same quotes give two spread rows (the 11-07 board's shape)."""
    import syndicate.features.shared.book_grid as bg

    real = bg.orient_events_to_latest
    try:
        bg.orient_events_to_latest = lambda rows: (rows, 0, 0, 0)
        spreads_off = [r for r in bg.build_book_grid(_flipped_day(), now=NOW) if r["market"] == "spreads"]
    finally:
        bg.orient_events_to_latest = real
    assert len(spreads_off) == 2


def test_a_venue_quote_never_decides_the_orientation_and_a_reversed_one_is_dropped_not_relabelled():
    """On 11-07 the newest old-orientation rows were Kalshi/Polymarket, after the books had moved. Polymarket's
    16:52Z row said "away" (Nebraska by its own fields) at +138: a Providence price. Its label could name either
    team, so it is not priced; a venue row already in the latest orientation is kept as it is."""
    late_venue = _q(NEB, PROV, "2026-11-07T17:08:02+00:00", bookmaker="polymarket", selection="away", price=138)
    current_venue = _q(PROV, NEB, "2026-11-07T17:09:00+00:00", bookmaker="kalshi", selection="home", price=-144)
    out, events, relabelled, dropped = orient_events_to_latest(_flipped_day() + [late_venue, current_venue])
    assert (events, dropped) == (1, 1)
    assert {(r["away_team"], r["home_team"]) for r in out} == {(PROV, NEB)}
    assert late_venue not in out
    assert current_venue in out


def test_totals_keep_their_selection_and_take_the_teams():
    out, _, _, _ = orient_events_to_latest(_flipped_day())
    totals = [r for r in out if r["market"] == "totals"]
    assert {r["selection"] for r in totals} == {"over", "under"}
    assert {(r["away_team"], r["home_team"]) for r in totals} == {(PROV, NEB)}


def test_an_event_quoted_one_way_is_returned_untouched():
    rows = [r for r in _flipped_day() if r["bookmaker"] == "bookb"]
    out, events, relabelled, dropped = orient_events_to_latest(rows)
    assert (events, relabelled, dropped) == (0, 0, 0)
    assert all(a is b for a, b in zip(out, rows))


def test_a_row_naming_neither_orientation_is_left_alone():
    odd = _q("Someone Else", PROV, OLD, bookmaker="booka")
    out, _, _, _ = orient_events_to_latest(_flipped_day() + [odd])
    assert out[-1] is odd


def test_two_events_are_decided_separately():
    other = [_q("A Team", "B Team", OLD, event_id="other", bookmaker="booka"),
             _q("A Team", "B Team", NEW, event_id="other", bookmaker="bookb", selection="away")]
    out, events, _, _ = orient_events_to_latest(_flipped_day() + other)
    assert events == 1
    assert {(r["away_team"], r["home_team"]) for r in out if r["event_id"] == "other"} == {("A Team", "B Team")}
