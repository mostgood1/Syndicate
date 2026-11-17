"""`build_book_grid`'s per-build memo (`_BuildMemo`, todo #809, lane ncaaf-grid-build-speed).

The memo answers three questions once per distinct input instead of once per row: a stamp's age, a row's seen age,
and whether a row's selection is the home side. Its whole claim is that the grid does not change, so the main test
builds seeded live days both ways (the memo, and a pass-through that calls the plain functions every time) and
compares the JSON. The reachability tests show the memo is what the build uses and that it asks fewer questions.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone

import pytest

from syndicate.features.shared import book_grid, team_aliases
from syndicate.features.shared.book_grid import _BuildMemo, _row_selection_is_home, build_book_grid
from syndicate.features.shared.odds_book_quotes import quote_key
from tests.test_book_grid_anchor_index import _live_day

NOW = datetime(2026, 11, 14, 22, 0, 0, tzinfo=timezone.utc)

# Last-seen stamps repeat across keys (one pull stamps every quote it saw), in every spelling the reader meets.
_STAMPS = [
    "2026-11-14T21:58:30Z",
    "2026-11-14T21:58:30Z",
    "2026-11-14T21:57:00+00:00",
    "2026-11-14T21:40:00",          # naive: read as UTC
    "2026-11-14T22:05:00Z",         # after `now`: clamped to 0
    "not-a-time",                   # unparseable: None
    "",                             # empty: None
]


def _soccer_rows(rng: random.Random) -> list[dict]:
    """Spreads labelled by CLUB, the case `_row_selection_is_home` resolves through `teams_match`."""
    rows = []
    for _ in range(300):
        line = rng.choice([-2.25, -1.5, -0.75, 0.0, 0.75, 1.5, 2.25])
        home_side = rng.random() < 0.5
        rows.append({
            "sport": "soccer", "kind": "game", "event_id": f"soc-{rng.randint(1, 2)}", "segment": "full",
            "market": "spreads", "player_name": "",
            "selection": rng.choice(["AZ Alkmaar", "AZ"]) if home_side else "Willem II",
            "line": line if home_side else -line, "price": rng.randint(-130, 120),
            "bookmaker": rng.choice(["draftkings", "fanduel", "betmgm"]),
            "home_team": "AZ Alkmaar", "away_team": "Willem II",
            "commence_time": "2026-11-14T19:30:00Z",
            "snapshot_ts": f"2026-11-14T21:{rng.randint(0, 59):02d}:00Z",
        })
    return rows


def _day_with_seen(seed: int) -> tuple[list[dict], dict[str, str]]:
    rng = random.Random(1000 + seed)
    rows = _live_day(seed) + _soccer_rows(rng)
    rng.shuffle(rows)
    last_seen = {}
    for row in rows:
        if rng.random() < 0.85:  # some keys were never stamped: seen age unknown
            last_seen[quote_key(row)] = rng.choice(_STAMPS)
    return rows, last_seen


class _PlainMemo:
    """The behaviour before the memo: every question asked again, of the plain functions."""

    def __init__(self, last_seen, now):
        self.last_seen, self.now = last_seen, now

    def age(self, stamp):
        return book_grid._age_seconds(stamp, now=self.now)

    def seen(self, row):
        return book_grid._seen_age_seconds(row, self.last_seen, now=self.now)

    def is_home(self, row):
        return book_grid._row_selection_is_home(row)


def _dump(grid) -> str:
    return json.dumps(grid, sort_keys=True, default=str)


def _first_difference(a: str, b: str) -> str:
    i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return f"first difference at char {i}: {a[i - 80:i + 80]!r} vs {b[i - 80:i + 80]!r}"


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_the_grid_is_identical_with_and_without_the_memo(seed, monkeypatch):
    monkeypatch.delenv("SYNDICATE_BOOK_GRID_STALE_BASIS", raising=False)  # seen basis + own capture: _capture_index runs
    rows, last_seen = _day_with_seen(seed)
    memoised = _dump(build_book_grid(rows, now=NOW, last_seen=last_seen))
    monkeypatch.setattr(book_grid, "_BuildMemo", _PlainMemo)
    plain = _dump(build_book_grid(rows, now=NOW, last_seen=last_seen))
    same = memoised == plain  # a bool, so a failure does not make pytest diff two long strings
    assert same, _first_difference(memoised, plain)
    grid = json.loads(memoised)
    assert len(grid) > 20
    # The frame could have caught a difference: seen ages are present and varied, and soccer lines were flipped.
    seen = {cell.get("seen_age_seconds") for row in grid for book in row["cells"].values() for cell in book.values()}
    assert None in seen and len(seen - {None}) >= 3
    assert any(row.get("sport") == "soccer" for row in grid)


def test_the_build_uses_the_memo_and_asks_fewer_questions(monkeypatch):
    monkeypatch.delenv("SYNDICATE_BOOK_GRID_STALE_BASIS", raising=False)
    rows, last_seen = _day_with_seen(7)
    counts = {"age": 0, "match": 0}
    real_age, real_match = book_grid._age_seconds, team_aliases.teams_match

    def counting_age(stamp, *, now):
        counts["age"] += 1
        return real_age(stamp, now=now)

    def counting_match(*args, **kwargs):
        counts["match"] += 1
        return real_match(*args, **kwargs)

    monkeypatch.setattr(book_grid, "_age_seconds", counting_age)
    monkeypatch.setattr(team_aliases, "teams_match", counting_match)
    build_book_grid(rows, now=NOW, last_seen=last_seen)
    memo_age, memo_match = counts["age"], counts["match"]
    counts.update(age=0, match=0)
    monkeypatch.setattr(book_grid, "_BuildMemo", _PlainMemo)
    build_book_grid(rows, now=NOW, last_seen=last_seen)
    plain_age, plain_match = counts["age"], counts["match"]
    assert plain_age > 1000 and memo_age * 10 < plain_age, (memo_age, plain_age)
    assert plain_match > 100 and memo_match * 10 < plain_match, (memo_match, plain_match)


def test_each_call_site_asks_its_own_question(monkeypatch):
    """The equivalence test swaps the memo, not the call sites, so this pins each call site to its own input: a cell's
    age is its quote's observed stamp, a cell's seen age is its own key's last-seen stamp, and the row's age is the
    newest observed stamp."""
    monkeypatch.delenv("SYNDICATE_BOOK_GRID_STALE_BASIS", raising=False)
    base = {"sport": "ncaaf", "kind": "game", "event_id": "e1", "segment": "full", "market": "totals", "player_name": "",
            "line": 45.5, "home_team": "Ohio State Buckeyes", "away_team": "Michigan Wolverines",
            "commence_time": "2026-11-14T20:30:00Z"}
    over = dict(base, selection="Over", price=-110, bookmaker="draftkings", snapshot_ts="2026-11-14T21:00:00Z")
    under = dict(base, selection="Under", price=-105, bookmaker="draftkings", snapshot_ts="2026-11-14T21:30:00Z")
    last_seen = {quote_key(over): "2026-11-14T21:58:30Z", quote_key(under): "2026-11-14T21:55:00Z"}
    (row,) = build_book_grid([over, under], now=NOW, last_seen=last_seen)
    cells = row["cells"]["draftkings"]
    assert (cells["Over"]["age_seconds"], cells["Under"]["age_seconds"]) == (3600.0, 1800.0)
    assert (cells["Over"]["seen_age_seconds"], cells["Under"]["seen_age_seconds"]) == (90.0, 300.0)
    assert row["age_seconds"] == 1800.0


def test_is_home_matches_the_plain_function_and_keys_on_sport(monkeypatch):
    memo = _BuildMemo({}, NOW)
    for row in ({"selection": "home"}, {"selection": "1"}, {"selection": ""}, {"selection": "AZ", "home_team": "AZ Alkmaar"},
                {"selection": "Willem II", "home_team": "AZ Alkmaar"}, {"selection": "AZ", "home_team": ""},
                {"selection": "AZ", "home_team": ["AZ Alkmaar"]}):  # unhashable: answered directly, never cached
        assert memo.is_home(row) == _row_selection_is_home(row), row
    # Only the sport differs: a sport-aware matcher must get both answers, not the first one cached.
    monkeypatch.setattr(team_aliases, "teams_match", lambda sport, token, team: sport == "x")
    memo = _BuildMemo({}, NOW)
    a = {"selection": "Lions", "home_team": "Lions", "sport": "x"}
    b = {"selection": "Lions", "home_team": "Lions", "sport": "y"}
    assert (memo.is_home(a), memo.is_home(b)) == (True, False)


def test_seen_and_age_follow_the_builds_own_now_and_last_seen():
    row = {"sport": "ncaaf", "kind": "game", "event_id": "e", "bookmaker": "dk", "segment": "full", "market": "totals",
           "selection": "Over", "player_name": "", "line": 45.5}
    stamps = {quote_key(row): "2026-11-14T21:58:30Z"}
    assert _BuildMemo(stamps, NOW).seen(row) == 90.0
    assert _BuildMemo(stamps, datetime(2026, 11, 14, 22, 1, 30, tzinfo=timezone.utc)).seen(row) == 180.0
    assert _BuildMemo({}, NOW).seen(row) is None and _BuildMemo(None, NOW).seen(row) is None
    memo = _BuildMemo(stamps, NOW)
    assert memo.age("") is None and memo.age("not-a-time") is None
    assert memo.age("2026-11-14T21:40:00") == book_grid._age_seconds("2026-11-14T21:40:00", now=NOW) == 1200.0
