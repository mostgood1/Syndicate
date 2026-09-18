"""The book-quote LATEST cache counts what it costs -- lane board-build-stage-slowdown, 2026-09-18.

`LATEST_CACHE_EVICT` per board build rose ~5 -> ~20 between 09-15 and 09-18, and
an eviction line reports the REDUCED rows it drops (~25k), while each miss
re-streams the whole append-only shard (60-70 MB for soccer 09-19/09-20). These
tests pin that the counters report the RAW rows a miss streams, count a hit as
free, count an appended (mtime-changed) shard as a full re-stream, reset on
read, and change nothing the reader returns. Then that Layer 2 prints them once
per build and never lets the instrument cost the build.
"""

from __future__ import annotations

import inspect
import json

import pytest

from syndicate.features.shared import odds_book_quotes


# Captured at import: a test below monkeypatches it to raise, and this fixture's
# teardown must reset the counters whatever order the fixtures unwind in.
_reset_stats = odds_book_quotes.take_latest_cache_stats


@pytest.fixture(autouse=True)
def _clean():
    odds_book_quotes._BOOK_QUOTES_CACHE.clear()
    odds_book_quotes._BOOK_QUOTES_LATEST_CACHE.clear()
    _reset_stats()
    yield
    odds_book_quotes._BOOK_QUOTES_CACHE.clear()
    odds_book_quotes._BOOK_QUOTES_LATEST_CACHE.clear()
    _reset_stats()


def _quote(**over):
    row = {
        "sport": "mlb", "kind": "game", "event_id": "e1", "bookmaker": "draftkings", "segment": "full_game",
        "market": "h2h", "selection": "home", "player_name": "", "line": "", "price": -110,
        "commence_time": "2026-09-18T23:00:00Z", "snapshot_ts": "2026-09-18T12:00:00Z",
        "captured_at": "2026-09-18T12:00:00Z", "home_team": "Baltimore Orioles", "away_team": "Los Angeles Angels",
    }
    row.update(over)
    return row


def _five_observations_of_two_keys():
    return [
        _quote(price=-110, snapshot_ts="2026-09-18T12:00:00Z"),
        _quote(price=-115, snapshot_ts="2026-09-18T13:00:00Z"),
        _quote(price=-120, snapshot_ts="2026-09-18T14:00:00Z"),
        _quote(selection="away", price=100, snapshot_ts="2026-09-18T12:00:00Z"),
        _quote(selection="away", price=105, snapshot_ts="2026-09-18T14:00:00Z"),
    ]


@pytest.fixture
def shard(tmp_path, monkeypatch):
    path = tmp_path / "2026-09-18.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in _five_observations_of_two_keys()) + "\n", encoding="utf-8")
    monkeypatch.setattr(odds_book_quotes, "book_quotes_path", lambda sport, date_str: path)
    return path


def test_a_miss_counts_the_whole_raw_shard_and_a_hit_is_free(shard):
    first = odds_book_quotes.read_book_quotes_latest("mlb", "2026-09-18")
    second = odds_book_quotes.read_book_quotes_latest("mlb", "2026-09-18")
    assert len(first) == 2 and second is first

    stats = odds_book_quotes.take_latest_cache_stats()
    assert (stats["hits"], stats["misses"]) == (1, 1)
    assert stats["raw_rows"] == 5, "a miss streams every observation, not the 2 it keeps"
    assert stats["reduced_rows"] == 2
    assert stats["by_sport"] == {"mlb": {"misses": 1, "raw_rows": 5}}
    assert stats["miss_cpu_s"] >= 0.0 and stats["miss_wall_s"] >= 0.0 and stats["since_s"] >= 0.0


def test_taking_the_stats_resets_them(shard):
    odds_book_quotes.read_book_quotes_latest("mlb", "2026-09-18")
    odds_book_quotes.take_latest_cache_stats()
    again = odds_book_quotes.take_latest_cache_stats()
    assert (again["hits"], again["misses"], again["raw_rows"], again["by_sport"]) == (0, 0, 0, {})


def test_an_appended_shard_is_a_miss_that_re_streams_everything(shard):
    """The mid-build tail sync. The key carries mtime and size, so one appended
    row costs a re-stream of the whole file -- the cost this counter exists to show."""
    odds_book_quotes.read_book_quotes_latest("mlb", "2026-09-18")
    with shard.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_quote(price=-125, snapshot_ts="2026-09-18T15:00:00Z")) + "\n")
    odds_book_quotes.read_book_quotes_latest("mlb", "2026-09-18")

    stats = odds_book_quotes.take_latest_cache_stats()
    assert (stats["hits"], stats["misses"]) == (0, 2)
    assert stats["raw_rows"] == 5 + 6


def test_counting_changes_nothing_the_reader_returns(shard):
    expected = odds_book_quotes.reduce_to_latest_per_key(odds_book_quotes.iter_book_quotes("mlb", "2026-09-18"))
    assert odds_book_quotes.read_book_quotes_latest("mlb", "2026-09-18") == expected


def test_a_failed_read_is_counted_and_still_never_cached(shard, monkeypatch):
    def _boom(*_a, **_k):
        yield _quote()
        raise OSError("transient")

    monkeypatch.setattr(odds_book_quotes, "iter_book_quotes", _boom)
    assert odds_book_quotes.read_book_quotes_latest("mlb", "2026-09-18") == []
    assert len(odds_book_quotes._BOOK_QUOTES_LATEST_CACHE) == 0
    stats = odds_book_quotes.take_latest_cache_stats()
    assert (stats["misses"], stats["raw_rows"], stats["reduced_rows"]) == (1, 1, 0)


# --------------------------------------------------------------------------
# Layer 2 prints them once per build
# --------------------------------------------------------------------------


def test_the_real_layer2_builder_carries_the_report():
    from pipeline import layer2_shortlist

    assert "@_reports_book_quote_cache_stats" in inspect.getsource(layer2_shortlist.build_layer2_shortlist)


def test_a_layer2_build_prints_and_resets_the_stats(shard, capsys):
    from pipeline import layer2_shortlist

    @layer2_shortlist._reports_book_quote_cache_stats
    def build(selected_date, sport_slugs):
        odds_book_quotes.read_book_quotes_latest("mlb", selected_date)
        odds_book_quotes.read_book_quotes_latest("mlb", selected_date)
        return {"rows": []}

    assert build("2026-09-18", ["mlb"]) == {"rows": []}
    line = next(l for l in capsys.readouterr().out.splitlines() if "BOOK_QUOTES_LATEST_STATS" in l)
    assert "date=2026-09-18" in line
    assert "calls=2 hits=1 misses=1 raw_rows=5 reduced_rows=2" in line
    assert 'by_sport={"mlb": {"misses": 1, "raw_rows": 5}}' in line
    assert odds_book_quotes.take_latest_cache_stats()["misses"] == 0, "the print must reset the window"


def test_a_broken_counter_never_costs_the_build(monkeypatch, capsys):
    from pipeline import layer2_shortlist

    def _boom():
        raise RuntimeError("counter broke")

    monkeypatch.setattr(odds_book_quotes, "take_latest_cache_stats", _boom)

    @layer2_shortlist._reports_book_quote_cache_stats
    def build(selected_date, sport_slugs):
        return {"rows": [1]}

    assert build("2026-09-18", []) == {"rows": [1]}
    assert "BOOK_QUOTES_LATEST_STATS_FAILED RuntimeError: counter broke" in capsys.readouterr().out
