"""Lane ncaaf-grid-build-speed: the anchor loop offers `market_sides_for_quote` only the rows on the anchor's line or
its mirror (`_line_candidate_index` / `_side_candidates`), and the grid must not change by one cell.

Measured on the fleet's 11-14 NCAAF shard before the change: 13,703 anchors walked 3,398,922 rows to price 124,344,
and that walk was 76% of the pivot. The equivalence tests compare against the old behaviour by forcing every anchor
to see the whole group, which is exactly what the loop did before.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone

import pytest

from syndicate.features.shared import book_grid
from syndicate.features.shared.book_grid import _line_candidate_index, _side_candidates, build_book_grid

NOW = datetime(2026, 11, 14, 22, 0, 0, tzinfo=timezone.utc)


def _quote(**overrides):
    row = {
        "sport": "ncaaf",
        "kind": "game",
        "event_id": "evt-1",
        "segment": "full",
        "market": "spreads",
        "player_name": "",
        "selection": "home",
        "line": -3.5,
        "price": -110,
        "bookmaker": "draftkings",
        "home_team": "Ohio State Buckeyes",
        "away_team": "Michigan Wolverines",
        "commence_time": "2026-11-14T20:30:00Z",
        "snapshot_ts": "2026-11-14T21:00:00Z",
    }
    row.update(overrides)
    return row


def _live_day(seed: int, n: int = 1500) -> list[dict]:
    """A synthetic live day: spreads and totals walking their lines, both signs, h2h with NaN lines, props, and the
    edge rows the index must not lose (string lines, lines inside the 1e-9 tolerance, rounding edges, non-finite and
    huge lines, empty selections, same-timestamp ties)."""
    rng = random.Random(seed)
    books = ["draftkings", "fanduel", "betmgm", "caesars", "kalshi"]
    rows = []
    for i in range(n):
        event = f"evt-{rng.randint(1, 3)}"
        stamp = f"2026-11-14T{18 + i * 4 // n:02d}:{rng.randint(0, 59):02d}:{rng.choice([0, 0, 30]):02d}Z"
        kind = rng.random()
        if kind < 0.40:
            line = rng.choice([-10.5, -7, -6.5, -3.5, -3, -2.5, -1, 0, 1, 2.5, 3, 3.5, 6.5, 7, 10.5])
            side = rng.choice(["home", "away"])
            rows.append(_quote(event_id=event, market="spreads", selection=side, line=line if side == "home" else -line,
                               price=rng.randint(-130, 110), bookmaker=rng.choice(books), snapshot_ts=stamp))
        elif kind < 0.75:
            line = rng.choice([44.5, 45, 45.5, 47.5, 51, 51.5, 52.5])
            rows.append(_quote(event_id=event, market="totals", selection=rng.choice(["Over", "Under"]), line=line,
                               price=rng.randint(-130, 110), bookmaker=rng.choice(books), snapshot_ts=stamp))
        elif kind < 0.85:
            rows.append(_quote(event_id=event, market="h2h", selection=rng.choice(["home", "away"]), line=float("nan"),
                               price=rng.randint(-400, 300), bookmaker=rng.choice(books), snapshot_ts=stamp))
        else:
            rows.append(_quote(event_id=event, kind="player", market="Receiving Yards",
                               player_name=rng.choice(["Jeremiah Smith", "Carnell Tate"]),
                               selection=rng.choice(["Over", "Under"]), line=rng.choice([55.5, 59.5, 60.5]),
                               price=rng.randint(-130, 110), bookmaker=rng.choice(books), snapshot_ts=stamp))
    edge = [
        _quote(line="3.5", selection="away", bookmaker="fanduel"),                 # string line
        _quote(line="+3.5", selection="away", bookmaker="betmgm"),                 # signed string line
        _quote(line=-3.5000000004, selection="home", bookmaker="caesars"),         # inside 1e-9 of -3.5
        _quote(line=3.5000000004, selection="away", bookmaker="caesars"),          # and of its mirror
        _quote(line=-3.5000005, selection="home", bookmaker="espnbet"),            # a different line, 5e-7 off
        _quote(line=0.0000005, selection="home", bookmaker="draftkings"),          # on a bucket's rounding edge
        _quote(line=0.0000005 + 5e-10, selection="away", bookmaker="fanduel"),     # its tolerance twin, other side
        _quote(line=-0.0, selection="home", bookmaker="betmgm"),
        _quote(line=0.0, selection="away", bookmaker="betmgm"),
        _quote(line=float("inf"), selection="home", bookmaker="draftkings"),
        _quote(line=float("-inf"), selection="away", bookmaker="draftkings"),
        _quote(line=2e12, selection="home", bookmaker="fanduel"),
        _quote(line=-2e12, selection="away", bookmaker="fanduel"),
        _quote(line=-3.5, selection="", bookmaker="draftkings"),                   # empty selection
        _quote(line=None, selection="home", market="h2h", bookmaker="caesars"),
        _quote(line="n/a", selection="away", market="h2h", bookmaker="caesars"),   # unparseable -> line-less
        _quote(line=-3.5, selection="home", bookmaker="draftkings", price=-105),   # same stamp, same cell: a tie
        _quote(line=-3.5, selection="home", bookmaker="draftkings", price=-125),   # last-wins must still win
        _quote(line=-3.5, selection="home", bookmaker="fanduel", price=None),      # priceless
    ]
    for i, row in enumerate(edge):
        rows.insert(rng.randint(0, len(rows)), row if i < 16 else dict(row))
    return rows


def _dump(grid) -> str:
    return json.dumps(grid, sort_keys=True, default=str)


def _whole_group(group, index, anchor):
    """The behaviour before the index: every anchor sees the whole group."""
    return group


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_the_grid_is_identical_to_walking_the_whole_group(seed, monkeypatch):
    rows = _live_day(seed)
    indexed = _dump(build_book_grid(rows, now=NOW))
    monkeypatch.setattr(book_grid, "_side_candidates", _whole_group)
    walked = _dump(build_book_grid(rows, now=NOW))
    same = indexed == walked  # a bool, so a failure does not make pytest diff two long strings
    first = next((i for i, (a, b) in enumerate(zip(indexed, walked)) if a != b), min(len(indexed), len(walked)))
    assert same, f"first difference at char {first}: {indexed[first - 80:first + 80]!r} vs {walked[first - 80:first + 80]!r}"
    assert len(json.loads(indexed)) > 20  # a real grid, not two empty lists agreeing


def test_the_index_is_reached_and_walks_fewer_rows(monkeypatch):
    """Reachability, off != on: count the rows `market_sides_for_quote` is handed."""
    rows = _live_day(7)
    real = book_grid.market_sides_for_quote
    seen = {"rows": 0}

    def counting(group, anchor):
        group = list(group)
        seen["rows"] += len(group)
        return real(group, anchor)

    monkeypatch.setattr(book_grid, "market_sides_for_quote", counting)
    build_book_grid(rows, now=NOW)
    indexed = seen["rows"]
    seen["rows"] = 0
    monkeypatch.setattr(book_grid, "_side_candidates", _whole_group)
    build_book_grid(rows, now=NOW)
    assert indexed * 3 < seen["rows"], (indexed, seen["rows"])


def test_candidates_keep_the_tolerance_twins_the_mirror_and_the_group_order():
    group = [
        _quote(line=-3.5, selection="home", bookmaker="a"),
        _quote(line=7, selection="home", bookmaker="b"),
        _quote(line=3.5, selection="away", bookmaker="c"),
        _quote(line=-3.5000000004, selection="home", bookmaker="d"),
        _quote(line=float("inf"), selection="home", bookmaker="e"),
        _quote(line=None, market="h2h", bookmaker="f"),
    ]
    index = _line_candidate_index(group)
    got = [row["bookmaker"] for row in _side_candidates(group, index, group[0])]
    assert got == ["a", "c", "d", "e"]  # same line, mirror, tolerance twin, wild -- in group order; 7 and None skipped
    assert [row["bookmaker"] for row in _side_candidates(group, index, group[5])] == ["f"]


def test_a_bucket_rounding_edge_still_offers_the_twin_across_it():
    # 5e-7 * 1e6 = 0.5 rounds one way and 0.5 + 5e-4 the other, yet the two lines are 5e-10 apart (inside 1e-9).
    group = [_quote(line=0.0000005, selection="home", bookmaker="a"),
             _quote(line=0.0000005 + 5e-10, selection="home", bookmaker="b")]
    index = _line_candidate_index(group)
    assert [row["bookmaker"] for row in _side_candidates(group, index, group[0])] == ["a", "b"]
    assert [row["bookmaker"] for row in _side_candidates(group, index, group[1])] == ["a", "b"]


def test_a_non_finite_or_huge_anchor_line_gets_the_whole_group():
    group = [_quote(line=float("inf"), bookmaker="a"), _quote(line=-3.5, bookmaker="b"), _quote(line=5e12, bookmaker="c")]
    index = _line_candidate_index(group)
    assert _side_candidates(group, index, group[0]) is group
    assert _side_candidates(group, index, group[2]) is group
