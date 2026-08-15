"""#252 -- the book-quotes shard is parsed once per identity, not once per row.

The defect: `read_book_quotes` had no cache and exactly one caller,
`quote_ref_for_bet`, as its FIRST statement -- and that caller runs inside a
`for row in rows:` loop at three sites in `quote_enrichment.py`. MLB's shard is
90,155,656 bytes / ~122k rows and a board build enriches ~200 candidates, so the
whole shard was materialised ~200 times per build.

Nothing was retained, which is why this looked like a leak and why tracemalloc
could never see it: each parse is freed before the next begins, so peak barely
moves while RSS ratchets on arena fragmentation glibc never returns to the OS.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import odds_book_quotes


@pytest.fixture(autouse=True)
def _clear_cache():
    odds_book_quotes._BOOK_QUOTES_CACHE.clear()
    yield
    odds_book_quotes._BOOK_QUOTES_CACHE.clear()


def _write_shard(tmp_path, rows):
    path = tmp_path / "shard.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _point_at(monkeypatch, path):
    monkeypatch.setattr(odds_book_quotes, "book_quotes_path", lambda sport, date_str: path)


def test_repeated_reads_parse_the_file_once(tmp_path, monkeypatch):
    # The actual regression, measured the way it matters: PARSE COUNT, not
    # return value. 200 reads stands in for 200 enriched candidates.
    path = _write_shard(tmp_path, [{"event_id": f"e{i}"} for i in range(50)])
    _point_at(monkeypatch, path)

    opens = {"count": 0}
    real_open = type(path).open

    def counting_open(self, *args, **kwargs):
        opens["count"] += 1
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "open", counting_open)

    for _ in range(200):
        rows = odds_book_quotes.read_book_quotes("mlb", "2026-08-07")
        assert len(rows) == 50

    assert opens["count"] == 1


def test_appending_to_the_shard_invalidates_the_cache(tmp_path, monkeypatch):
    # The shard is append-only and grows all day. A cache that served a stale
    # copy would be worse than no cache -- the board would price against
    # quotes it can no longer see.
    path = _write_shard(tmp_path, [{"event_id": "e1"}])
    _point_at(monkeypatch, path)

    assert len(odds_book_quotes.read_book_quotes("mlb", "2026-08-07")) == 1

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_id": "e2"}) + "\n")

    assert len(odds_book_quotes.read_book_quotes("mlb", "2026-08-07")) == 2


def test_missing_shard_is_not_cached_as_empty(tmp_path, monkeypatch):
    # A shard that has not arrived yet must not pin an empty answer: the pull
    # writes it moments later and the next build has to see it.
    path = tmp_path / "absent.jsonl"
    _point_at(monkeypatch, path)
    assert odds_book_quotes.read_book_quotes("mlb", "2026-08-07") == []

    path.write_text(json.dumps({"event_id": "e1"}) + "\n", encoding="utf-8")
    assert len(odds_book_quotes.read_book_quotes("mlb", "2026-08-07")) == 1


def test_cache_is_bounded_by_BYTES_not_entry_count(tmp_path, monkeypatch):
    """The bound is a byte budget, per the worker-cache rule.

    An entry count is the wrong shape for a value whose size varies by orders of
    magnitude between sports. MEASURED 2026-08-08: two entries, sized on the 4Gi
    worker, meant ~1.14GB on live-odds-worker's 2Gi limit -- essentially the
    whole parent -- and it died.
    """
    # Tiny shards: all five fit inside the budget, so a COUNT bound would evict
    # where a BYTE bound correctly does not.
    for i in range(5):
        shard = tmp_path / f"shard_{i}.jsonl"
        shard.write_text(json.dumps({"event_id": f"e{i}"}) + "\n", encoding="utf-8")
        _point_at(monkeypatch, shard)
        odds_book_quotes.read_book_quotes("mlb", f"2026-08-0{i}")

    assert odds_book_quotes._book_quotes_cache_estimated_bytes() <= odds_book_quotes._BOOK_QUOTES_CACHE_MAX_RSS_BYTES
    assert len(odds_book_quotes._BOOK_QUOTES_CACHE) == 5, "a count bound would have evicted these"


def test_a_shard_over_the_whole_budget_still_serves_from_cache(tmp_path, monkeypatch):
    """Never evict the entry just inserted.

    Production's MLB shard estimates above the entire budget. Evicting it on
    insert would reintroduce the per-row full-shard re-read #252 exists to stop
    -- ~200 materialisations of a 122k-dict list per board build.
    """
    big = tmp_path / "big.jsonl"
    big.write_text("\n".join(json.dumps({"event_id": f"e{i}"}) for i in range(200)) + "\n", encoding="utf-8")
    monkeypatch.setattr(odds_book_quotes, "_BOOK_QUOTES_CACHE_MAX_RSS_BYTES", 1)
    _point_at(monkeypatch, big)

    odds_book_quotes.read_book_quotes("mlb", "2026-08-07")
    assert len(odds_book_quotes._BOOK_QUOTES_CACHE) == 1


def test_eviction_is_logged(tmp_path, monkeypatch, capsys):
    """A cache that evicts silently cannot be told apart from one that is never
    hit -- "is the cache working?" then needs a heap dump to answer."""
    monkeypatch.setattr(odds_book_quotes, "_BOOK_QUOTES_CACHE_MAX_RSS_BYTES", 100)
    for i in range(3):
        shard = tmp_path / f"s{i}.jsonl"
        shard.write_text("\n".join(json.dumps({"event_id": f"e{i}-{j}"}) for j in range(50)) + "\n", encoding="utf-8")
        _point_at(monkeypatch, shard)
        odds_book_quotes.read_book_quotes("mlb", f"2026-08-0{i}")

    assert "CACHE_EVICT" in capsys.readouterr().out


def test_quote_ref_for_bet_reads_the_shard_once_across_many_rows(tmp_path, monkeypatch):
    # End to end at the real call site shape: quote_ref_for_bet calls
    # read_book_quotes as its first statement, and enrichment calls it per row.
    path = _write_shard(
        tmp_path,
        [
            {
                "event_id": "evt-1",
                "player_name": "Drew Anderson",
                "market": "batter_hits",
                "selection": "over",
                "line": 0.5,
                "price": -120,
                "bookmaker": "draftkings",
            }
        ],
    )
    _point_at(monkeypatch, path)

    # `#435` moved this caller onto the LATEST-PER-KEY reader, so the counter
    # follows it. `#252`'s claim is unchanged and is still what is asserted
    # below: the reader is called per row, and the FILE is parsed once.
    calls = {"count": 0}
    real_read = odds_book_quotes.read_book_quotes_latest

    def counting_read(sport, date_str):
        calls["count"] += 1
        return real_read(sport, date_str)

    monkeypatch.setattr(odds_book_quotes, "read_book_quotes_latest", counting_read)

    opens = {"count": 0}
    real_open = type(path).open

    def counting_open(self, *args, **kwargs):
        opens["count"] += 1
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "open", counting_open)

    for _ in range(100):
        odds_book_quotes.quote_ref_for_bet(
            sport="mlb",
            date_str="2026-08-07",
            event_id="evt-1",
            player_name="Drew Anderson",
            market="batter_hits",
            selection="over",
        )

    # Still called per row -- that part is the caller's shape and is unchanged.
    assert calls["count"] == 100
    # But the file is parsed once. That is the whole fix.
    assert opens["count"] == 1
