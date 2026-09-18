"""`load_recent_ranking_records`' per-chunk parse cache and its fingerprint.

Lane `ranking-records-build-cost` (2026-09-18). Every board build re-read all 15
ledger chunks (~3.4 GB) to keep ~17k settled records. The cache keeps what each
chunk contributes and re-parses only what changed. These tests pin:

* REACHABILITY -- a second load reuses every chunk and parses no bytes, and the
  `SYNDICATE_RANKING_RECORDS_CACHE=0` switch really turns it off (off != on);
* EQUALITY -- after every kind of write the ledger sees (append, settlement's
  temp-file + `os.replace`, an unterminated line in flight, a same-inode
  rewrite, a new day, a day leaving the window) the cached result is identical
  to a fresh uncached read: records, order, and every counter;
* the FINGERPRINT moves when kept records change and stays put when only
  pending lines are appended (today's chunk grows all day with those).
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import intelligence_evaluation as ie
from syndicate.features.shared import ranking_records as rr

_COUNTERS = ("chunks_read", "lines_seen", "kept", "skipped_unsettled", "kept_superseding_pending", "unparseable", "bytes_read")


def _day(n: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    ledger_path = tmp_path / "evaluation_ledger.jsonl"
    (tmp_path / "evaluation_ledger_chunks").mkdir()
    monkeypatch.setattr(ie, "_is_chunked_ledger_path", lambda path: True)
    monkeypatch.delenv("SYNDICATE_RANKING_RECORDS_CACHE", raising=False)
    rr.reset_ranking_records_cache()
    yield ledger_path
    rr.reset_ranking_records_cache()


def _chunk(ledger_path: Path, n: int) -> Path:
    return ie._ledger_chunk_path(ledger_path, _day(n))


def _line(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"


def _write(ledger_path: Path, n: int, records: list[dict]) -> Path:
    path = _chunk(ledger_path, n)
    path.write_bytes(b"".join(_line(r) for r in records))
    return path


def _append(ledger_path: Path, n: int, data: bytes) -> None:
    with _chunk(ledger_path, n).open("ab") as handle:
        handle.write(data)


def _replace(ledger_path: Path, n: int, records: list[dict]) -> None:
    """Settlement's write: temp file + os.replace (a new inode)."""
    path = _chunk(ledger_path, n)
    tmp = path.with_suffix(path.suffix + ".replace.tmp")
    tmp.write_bytes(b"".join(_line(r) for r in records))
    os.replace(tmp, path)


def _load(ledger_path: Path, monkeypatch, *, cached: bool) -> "tuple[rr.RankingRecords, dict]":
    stats: dict = {}
    if cached:
        monkeypatch.delenv("SYNDICATE_RANKING_RECORDS_CACHE", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_RANKING_RECORDS_CACHE", "0")
    records = rr.load_recent_ranking_records(days=14, ledger_path=ledger_path, stats=stats)
    monkeypatch.delenv("SYNDICATE_RANKING_RECORDS_CACHE", raising=False)
    return records, stats


def _assert_same_as_fresh(ledger_path: Path, monkeypatch) -> "tuple[rr.RankingRecords, dict]":
    fresh, fresh_stats = _load(ledger_path, monkeypatch, cached=False)
    cached, cached_stats = _load(ledger_path, monkeypatch, cached=True)
    assert list(cached) == list(fresh)
    assert {k: cached_stats[k] for k in _COUNTERS} == {k: fresh_stats[k] for k in _COUNTERS}
    return cached, cached_stats


def _settled(i: int, result: str = "win", **extra) -> dict:
    return {"recommendation_id": f"r{i}", "result": result, "pnl": 1.0 if result == "win" else -1.0, "stake": 1.0, "sport": "mlb", **extra}


def _pending(i: int, **extra) -> dict:
    return {"recommendation_id": f"r{i}", "result": "pending", "sport": "mlb", "pad": "x" * 50, **extra}


# --- reachability ---------------------------------------------------------------

def test_second_load_reuses_every_chunk_and_parses_nothing(ledger, monkeypatch, capsys):
    _write(ledger, 2, [_settled(1), _pending(2)])
    _write(ledger, 1, [_settled(3, "loss"), _pending(4)])
    first, first_stats = _load(ledger, monkeypatch, cached=True)
    assert first_stats["chunks_parsed"] == 2 and first_stats["bytes_parsed"] > 0
    second, second_stats = _load(ledger, monkeypatch, cached=True)
    assert second_stats["chunks_reused"] == 2 and second_stats["chunks_parsed"] == 0
    assert second_stats["bytes_parsed"] == 0
    assert list(second) == list(first)
    assert second.fingerprint and second.fingerprint == first.fingerprint
    line = [l for l in capsys.readouterr().out.splitlines() if "RANKING_RECORDS_LOADED" in l][-1]
    assert "cache=reused:2,extended:0,parsed:0 bytes_parsed=0 " in line


def test_switch_off_really_turns_the_cache_off(ledger, monkeypatch, capsys):
    _write(ledger, 0, [_settled(1)])
    for _ in range(2):
        records, stats = _load(ledger, monkeypatch, cached=False)
        assert stats["chunks_parsed"] == 1 and stats["chunks_reused"] == 0 and stats["bytes_parsed"] > 0
        assert records.fingerprint is None
    assert "cache=off " in capsys.readouterr().out
    # ...and ON differs from OFF on the same ledger.
    _load(ledger, monkeypatch, cached=True)
    records, stats = _load(ledger, monkeypatch, cached=True)
    assert stats["chunks_reused"] == 1 and records.fingerprint is not None


def test_flat_ledger_is_unchanged_and_unfingerprinted(tmp_path, monkeypatch):
    flat = tmp_path / "flat.jsonl"
    flat.write_bytes(_line(_settled(1)) + _line(_pending(2)))
    monkeypatch.setattr(ie, "_is_chunked_ledger_path", lambda path: False)
    records = rr.load_recent_ranking_records(days=14, ledger_path=flat)
    assert [r["recommendation_id"] for r in records] == ["r1"]
    assert records.fingerprint is None


# --- equality after every kind of write -----------------------------------------------

def test_appended_pending_lines_extend_the_chunk_and_keep_the_fingerprint(ledger, monkeypatch):
    _write(ledger, 0, [_settled(1), _pending(2)])
    before, _ = _assert_same_as_fresh(ledger, monkeypatch)
    _append(ledger, 0, _line(_pending(5)) + _line(_pending(6)))
    after, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["chunks_extended"] == 1 and stats["chunks_parsed"] == 0
    assert 0 < stats["bytes_parsed"] < _chunk(ledger, 0).stat().st_size
    assert after.fingerprint == before.fingerprint


def test_appended_settled_line_moves_the_fingerprint(ledger, monkeypatch):
    _write(ledger, 0, [_settled(1)])
    before, _ = _assert_same_as_fresh(ledger, monkeypatch)
    _append(ledger, 0, _line(_settled(7, "loss")))
    after, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["chunks_extended"] == 1
    assert after.fingerprint != before.fingerprint


def test_settlement_rewrite_reparses_the_chunk(ledger, monkeypatch):
    _write(ledger, 3, [_settled(1), _pending(2)])
    _write(ledger, 0, [_settled(9)])
    before, _ = _assert_same_as_fresh(ledger, monkeypatch)
    _replace(ledger, 3, [_settled(1), _settled(2, "loss")])
    after, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["chunks_parsed"] == 1 and stats["chunks_reused"] == 1
    assert after.fingerprint != before.fingerprint


def test_a_settlement_in_an_older_chunk_changes_a_cached_newer_chunks_output(ledger, monkeypatch):
    # r1 is pending in both chunks: nothing kept. Settle it in the OLDER chunk
    # and the NEWER chunk's pending r1 (cached, untouched) now supersedes it --
    # the replay, not the cache, must decide that.
    _write(ledger, 2, [_pending(1)])
    _write(ledger, 0, [_pending(1)])
    before, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert list(before) == [] and stats["kept_superseding_pending"] == 0
    _replace(ledger, 2, [_settled(1)])
    after, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["kept_superseding_pending"] == 1 and stats["chunks_reused"] == 1
    assert [(r["recommendation_id"], r["result"]) for r in after] == [("r1", "win"), ("r1", "pending")]


def test_an_unterminated_line_is_read_again_once_complete(ledger, monkeypatch):
    _write(ledger, 0, [_settled(1)])
    whole = _line(_settled(2, "loss"))
    _append(ledger, 0, whole[:20])
    partial, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["unparseable"] == 1
    _append(ledger, 0, whole[20:])
    complete, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["unparseable"] == 0
    assert [r["recommendation_id"] for r in complete] == ["r1", "r2"]
    assert complete.fingerprint != partial.fingerprint


def test_an_unterminated_settled_line_still_lets_a_later_pending_line_supersede(ledger, monkeypatch):
    # Not reachable in production order (today's chunk is last), but the replay
    # must treat a tail record exactly like any other.
    _write(ledger, 1, [])
    _chunk(ledger, 1).write_bytes(json.dumps(_settled(1)).encode("utf-8"))
    _write(ledger, 0, [_pending(1)])
    records, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["kept_superseding_pending"] == 1


def test_same_inode_rewrite_with_a_new_prefix_is_detected(ledger, monkeypatch):
    path = _write(ledger, 0, [_settled(1), _settled(2)])
    _assert_same_as_fresh(ledger, monkeypatch)
    data = path.read_bytes().replace(b'"win"', b'"los"', 1)  # same length
    with path.open("r+b") as handle:  # same inode
        handle.write(data)
        handle.write(_line(_pending(3)))
    _, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["chunks_parsed"] == 1


def test_a_replaced_file_is_reparsed_even_when_its_tail_matches(ledger, monkeypatch):
    # Settlement flips an EARLY line at the same length ("open" -> "loss") and
    # os.replace()s the chunk: same size, identical last 4 KiB. Only the new
    # inode says the file changed.
    padding = [_pending(100 + i, pad="z" * 80) for i in range(80)]
    first = dict(_settled(1, "loss"), result="open")
    _write(ledger, 0, [first, *padding])
    before, _ = _assert_same_as_fresh(ledger, monkeypatch)
    assert list(before) == []
    _replace(ledger, 0, [_settled(1, "loss"), *padding])
    after, stats = _assert_same_as_fresh(ledger, monkeypatch)
    assert stats["chunks_parsed"] == 1
    assert [r["recommendation_id"] for r in after] == ["r1"]


def test_days_leaving_the_window_are_evicted(ledger, monkeypatch):
    _write(ledger, 0, [_settled(1)])
    _write(ledger, 1, [_settled(2)])
    _load(ledger, monkeypatch, cached=True)
    assert len(rr._CHUNK_CACHE) == 2
    _chunk(ledger, 1).unlink()
    _assert_same_as_fresh(ledger, monkeypatch)
    assert list(rr._CHUNK_CACHE) == [str(_chunk(ledger, 0))]


def test_byte_backstop_partial_chunk_matches_fresh(ledger, monkeypatch):
    rows = [_settled(i, pad="y" * 80) for i in range(10)]
    path = _write(ledger, 0, rows)
    for limit in (path.stat().st_size // 2, path.stat().st_size // 3, path.stat().st_size):
        fresh_stats: dict = {}
        monkeypatch.setenv("SYNDICATE_RANKING_RECORDS_CACHE", "0")
        fresh = rr.load_recent_ranking_records(days=14, ledger_path=ledger, max_total_bytes=limit, stats=fresh_stats)
        monkeypatch.delenv("SYNDICATE_RANKING_RECORDS_CACHE")
        cached_stats: dict = {}
        cached = rr.load_recent_ranking_records(days=14, ledger_path=ledger, max_total_bytes=limit, stats=cached_stats)
        assert list(cached) == list(fresh)
        assert {k: cached_stats[k] for k in _COUNTERS} == {k: fresh_stats[k] for k in _COUNTERS}


@pytest.mark.parametrize("seed", range(6))
def test_randomised_write_sequences_always_match_a_fresh_read(ledger, monkeypatch, seed):
    rng = random.Random(seed)
    chunks: dict[int, list[dict]] = {n: [] for n in range(4)}
    next_id = 0
    last_fp = None
    last_records = None
    for _ in range(40):
        op = rng.choice(("append_pending", "append_settled", "append_dup", "settle", "tail", "blank", "garbage"))
        n = rng.choice(list(chunks))
        path = _chunk(ledger, n)
        if not path.exists():
            path.write_bytes(b"")
        data = path.read_bytes()
        if op == "tail" and not data.endswith(b"\n") and data:
            _append(ledger, n, b"\n")
            continue
        if data and not data.endswith(b"\n"):
            _append(ledger, n, b"\n")
        if op == "append_pending":
            _append(ledger, n, _line(_pending(next_id)))
            next_id += 1
        elif op == "append_settled":
            _append(ledger, n, _line(_settled(next_id, rng.choice(("win", "loss", "push")))))
            next_id += 1
        elif op == "append_dup" and next_id:
            ident = rng.randrange(next_id)
            _append(ledger, n, _line(rng.choice((_pending(ident), _settled(ident, "loss")))))
        elif op == "settle":
            lines = [l for l in path.read_bytes().splitlines() if l.strip()]
            out = []
            for l in lines:
                try:
                    rec = json.loads(l)
                except Exception:
                    out.append(l + b"\n")
                    continue
                if rec.get("result") == "pending" and rng.random() < 0.5:
                    rec["result"] = rng.choice(("win", "loss"))
                out.append(_line(rec))
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(b"".join(out))
            os.replace(tmp, path)
        elif op == "tail":
            _append(ledger, n, _line(_settled(next_id))[:15])
            next_id += 1
        elif op == "blank":
            _append(ledger, n, b"\n")
        elif op == "garbage":
            _append(ledger, n, b"not json\n")
        pending_only = op in ("append_pending", "blank", "garbage")
        records, _stats = _assert_same_as_fresh(ledger, monkeypatch)
        if last_records is not None:
            if list(records) != last_records:
                assert records.fingerprint != last_fp, op
            elif pending_only:
                assert records.fingerprint == last_fp, op
        last_fp, last_records = records.fingerprint, list(records)
