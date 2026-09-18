"""The 7-day odds-events history index is built once per file version, not once per candidate.

Lane `market-history-index-memo`, 2026-09-18. cProfile of candidate collection on
refresh-worker `ef3fb857` put 517.5 of 641.0 s in
`build_recent_market_history_index`, run 1,311 times -- once per candidate --
over the same ~14k events. These tests pin: one build for many candidates over
unchanged files; exactly the rows a fresh build gives; a rebuild when a file is
appended or the date moves; and copies out, so no caller can edit the memo.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from syndicate.features.shared import odds_lifecycle

END = "2026-09-18"


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    root = tmp_path / "odds_events"
    root.mkdir()
    monkeypatch.setenv("SYNDICATE_ODDS_EVENTS_ROOT", str(root))
    monkeypatch.setattr(odds_lifecycle, "_maybe_compact_stale_odds_lifecycle_files", lambda: None)
    odds_lifecycle._JSONL_ROWS_CACHE.clear()
    odds_lifecycle._RECENT_INDEX_MEMO = None
    yield root
    odds_lifecycle._JSONL_ROWS_CACHE.clear()
    odds_lifecycle._RECENT_INDEX_MEMO = None


def _event(i, *, player, stat, event_id, ts, line):
    return {
        "market_id": f"m-{player}-{stat}", "event_id": event_id, "player_name": player, "entity": player,
        "stat": stat, "market": stat, "line": line, "timestamp": ts, "captured_at": ts, "sport": "mlb", "seq": i,
    }


def _write_day(root, day, events):
    path = root / f"{day}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def _seed(root):
    _write_day(root, "2026-09-17", [
        _event(1, player="Aaron Judge", stat="hits", event_id="g1", ts="2026-09-17T18:00:00Z", line=1.5),
        _event(2, player="Juan Soto", stat="hits", event_id="g1", ts="2026-09-17T18:05:00Z", line=0.5),
    ])
    return _write_day(root, END, [
        _event(3, player="Aaron Judge", stat="hits", event_id="g1", ts="2026-09-18T12:00:00Z", line=1.5),
        _event(4, player="Aaron Judge", stat="total_bases", event_id="g1", ts="2026-09-18T12:01:00Z", line=1.5),
        _event(5, player="Juan Soto", stat="hits", event_id="g1", ts="2026-09-18T12:02:00Z", line=1.5),
        _event(6, player="Pete Alonso", stat="hits", event_id="g2", ts="2026-09-18T12:03:00Z", line=0.5),
    ])


CANDIDATES = [
    {"market_id": "m-Aaron Judge-hits", "player_name": "Aaron Judge", "stat": "hits", "event_id": "g1", "sport": "mlb"},
    {"player_name": "Juan Soto", "entity": "Juan Soto", "stat": "hits", "event_id": "g1", "candidate_type": "prop", "sport": "mlb"},
    {"player_name": "Aaron Judge", "entity": "Aaron Judge", "stat": "total_bases", "event_id": "g1", "candidate_type": "prop", "sport": "mlb"},
    {"event_id": "g2", "sport": "mlb"},
    {"event_id": "nope", "player_name": "Nobody", "sport": "mlb"},
    {},
]


def _rows(candidate):
    return odds_lifecycle._recent_history_rows(candidate, sport="mlb", end_date=END)


def _count_builds(monkeypatch):
    real = odds_lifecycle.build_recent_market_history_index
    calls = {"n": 0}

    def counted(events):
        calls["n"] += 1
        return real(events)

    monkeypatch.setattr(odds_lifecycle, "build_recent_market_history_index", counted)
    return calls


def test_many_candidates_over_unchanged_files_build_the_index_once(_root, monkeypatch):
    _seed(_root)
    builds = _count_builds(monkeypatch)
    for _ in range(5):
        for candidate in CANDIDATES:
            _rows(candidate)
    # Was one build per call: 30 here, 1,311 on production's 09-18 build.
    assert builds["n"] == 1, builds


def test_rows_equal_a_fresh_build_for_every_candidate(_root):
    _seed(_root)
    memoised = [_rows(c) for c in CANDIDATES]
    fresh = []
    for candidate in CANDIDATES:
        odds_lifecycle._RECENT_INDEX_MEMO = None
        fresh.append(_rows(candidate))
    assert memoised == fresh
    assert sum(1 for r in memoised if r) >= 3, "a grid where nothing matches would pass vacuously"


def test_an_appended_file_rebuilds_and_shows_the_new_row(_root, monkeypatch):
    today = _seed(_root)
    before = _rows(CANDIDATES[3])
    builds = _count_builds(monkeypatch)
    time.sleep(0.01)
    with today.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_event(7, player="Pete Alonso", stat="hits", event_id="g2", ts="2026-09-18T13:00:00Z", line=1.5)) + "\n")
    stat = today.stat()
    os.utime(today, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    after = _rows(CANDIDATES[3])
    assert builds["n"] == 1
    assert len(after) == len(before) + 1


def test_another_end_date_or_lookback_is_another_index(_root, monkeypatch):
    _seed(_root)
    _rows(CANDIDATES[0])
    builds = _count_builds(monkeypatch)
    odds_lifecycle._recent_history_rows(CANDIDATES[0], sport="mlb", end_date="2026-09-17")
    odds_lifecycle._recent_history_rows(CANDIDATES[0], sport="mlb", end_date=END, lookback_days=1)
    assert builds["n"] == 2


def test_callers_get_copies_and_cannot_edit_the_memo(_root):
    _seed(_root)
    first = _rows(CANDIDATES[0])
    assert first
    first[0]["line"] = 999
    first.clear()
    again = _rows(CANDIDATES[0])
    assert again and all(row["line"] != 999 for row in again)


def test_no_files_means_no_rows_and_no_crash(_root):
    assert _rows(CANDIDATES[0]) == []


def test_a_swapped_loader_gets_its_own_index_not_the_last_ones(_root, monkeypatch):
    """The loader is part of the key. Found by `test_odds_lifecycle_shards`: tests
    patch `load_recent_odds_events` with their own events and no files, and a
    files-only key served each one the index built from the previous test's events."""
    _seed(_root)
    real_rows = _rows(CANDIDATES[3])
    assert real_rows
    fake = [_event(9, player="Other", stat="hits", event_id="g2", ts="2026-09-18T14:00:00Z", line=7.5)]
    monkeypatch.setattr(odds_lifecycle, "load_recent_odds_events", lambda **_k: fake)
    swapped = _rows(CANDIDATES[3])
    assert [row["line"] for row in swapped] == [7.5]
