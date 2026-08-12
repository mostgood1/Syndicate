"""Compress `book_quotes` at rest instead of deleting or downsampling it.

WHY COMPRESSION AND NOT RETENTION. `book_quotes` is the largest artifact family
on every disk (196.4 MB/day measured 2026-08-12) and the one that genuinely
cannot be regenerated. Measured on the real mlb/2026-08-09 shard: 99.5% of rows
carry a real price change, so there is nothing to dedupe -- but the text is
hugely redundant, and gzip -6 takes 207.4MB to 5.4MB (38.7x). A full year
compressed costs less disk than three days raw, with every tick intact.

THE TESTS THAT MATTER HERE ARE THE GUARD AND THE REFUSALS, not the happy-path
round-trip. `book_quotes_read_affordable` projects resident memory from shard
size x6.3 and exists because web OOM-killed twice in 60s reading one. Sizing a
compressed shard by its ON-DISK bytes would under-report by ~39x and let exactly
the read it was built to stop sail through -- a guard still present, still
logging, and blind in the only case that matters.
"""

from __future__ import annotations

import gzip
import json

import pytest

from syndicate.features.shared import odds_book_quotes as obq


def _rows(n):
    return [
        {
            "captured_at": f"2026-08-09T04:{i % 60:02d}:00+00:00",
            "sport": "mlb",
            "date": "2026-08-09",
            "kind": "game",
            "event_id": "evt1",
            "bookmaker": "draftkings",
            "market": "h2h",
            "segment": "full",
            "selection": "home",
            "player_name": None,
            "line": None,
            "price": -110 - i,
        }
        for i in range(n)
    ]


def _write_plain(root, sport, date_str, rows):
    p = root / f"{sport}_source" / "tracking" / "book_quotes" / f"{date_str}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    return p


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    obq._BOOK_QUOTES_CACHE.clear()
    return tmp_path


# --- reading a compressed shard -------------------------------------------

def test_a_compressed_shard_reads_identically_to_the_plain_one(_root):
    rows = _rows(50)
    plain = _write_plain(_root, "mlb", "2026-08-09", rows)
    expected = obq.read_book_quotes("mlb", "2026-08-09")
    assert len(expected) == 50

    obq._BOOK_QUOTES_CACHE.clear()
    with plain.open("rb") as src, gzip.open(str(plain) + ".gz", "wb") as dst:
        dst.write(src.read())
    plain.unlink()

    got = obq.read_book_quotes("mlb", "2026-08-09")
    assert got == expected, "compressed shard did not round-trip"
    assert [r["price"] for r in got] == [r["price"] for r in rows]


def test_iter_streams_a_compressed_shard(_root):
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(20))
    with plain.open("rb") as src, gzip.open(str(plain) + ".gz", "wb") as dst:
        dst.write(src.read())
    plain.unlink()
    assert len(list(obq.iter_book_quotes("mlb", "2026-08-09"))) == 20


def test_plain_wins_when_both_exist(_root):
    """Mid-compaction the .gz exists and the original has not been removed.
    Only the original is guaranteed complete at that instant."""
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(7))
    with gzip.open(str(plain) + ".gz", "wt", encoding="utf-8") as dst:
        dst.write("")  # deliberately truncated/incomplete
    assert obq.resolve_book_quotes_path("mlb", "2026-08-09") == plain
    assert len(obq.read_book_quotes("mlb", "2026-08-09")) == 7


# --- the memory guard must not be disarmed by compression ------------------

def test_logical_bytes_reports_UNCOMPRESSED_size_for_a_gz(_root):
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(500))
    raw_size = plain.stat().st_size
    packed = plain.with_name(plain.name + ".gz")
    with plain.open("rb") as src, gzip.open(packed, "wb") as dst:
        dst.write(src.read())

    assert packed.stat().st_size < raw_size, "fixture did not actually compress"
    assert obq.book_quotes_logical_bytes(packed) == raw_size
    assert obq.book_quotes_logical_bytes(plain) == raw_size


def test_affordability_guard_still_refuses_a_compressed_shard_that_will_not_fit(_root, monkeypatch):
    """The regression this whole change could have introduced.

    A shard whose UNCOMPRESSED form blows the budget must still be refused once
    it is stored compressed. Sized off on-disk bytes it would be admitted.
    """
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(4000))
    raw_size = plain.stat().st_size
    packed = plain.with_name(plain.name + ".gz")
    with plain.open("rb") as src, gzip.open(packed, "wb") as dst:
        dst.write(src.read())
    plain.unlink()

    # Budget sits between the compressed and uncompressed projections, so the
    # answer differs depending on which size the guard used.
    compressed_projection = packed.stat().st_size * obq._BOOK_QUOTES_RSS_PER_FILE_BYTE
    raw_projection = raw_size * obq._BOOK_QUOTES_RSS_PER_FILE_BYTE
    assert compressed_projection < raw_projection
    budget = int((compressed_projection + raw_projection) / 2)
    monkeypatch.setattr(obq, "_BOOK_QUOTES_CACHE_MAX_RSS_BYTES", budget)

    affordable, facts = obq.book_quotes_read_affordable("mlb", "2026-08-09")
    assert affordable is False, "compression disarmed the OOM guard"
    assert facts["shard_bytes"] == raw_size


def test_a_corrupt_gzip_trailer_errs_toward_refusing(_root):
    """ISIZE is uncompressed-size mod 2^32. A wrapped or damaged trailer reads
    as absurdly SMALL, which is the dangerous direction, so it must not be
    believed."""
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(500))
    packed = plain.with_name(plain.name + ".gz")
    with plain.open("rb") as src, gzip.open(packed, "wb") as dst:
        dst.write(src.read())
    plain.unlink()
    with packed.open("r+b") as fh:  # zero the ISIZE trailer
        fh.seek(-4, 2)
        fh.write(b"\x00\x00\x00\x00")

    logical = obq.book_quotes_logical_bytes(packed)
    assert logical >= packed.stat().st_size * obq._ASSUMED_GZIP_RATIO
    assert logical > packed.stat().st_size


# --- the compactor ---------------------------------------------------------

def test_dry_run_by_default_compresses_nothing(_root):
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(30))
    out = obq.compress_closed_shards(sport="mlb", today="2026-08-12")
    assert out["apply"] is False
    assert len(out["compressed"]) == 1
    assert plain.exists(), "dry run modified the disk"
    assert not plain.with_name(plain.name + ".gz").exists()


def test_it_never_touches_todays_shard(_root):
    """Today's shard is append-only and still being written. Appending to a gzip
    member yields a file that decompresses to the first member only."""
    today = _write_plain(_root, "mlb", "2026-08-12", _rows(5))
    out = obq.compress_closed_shards(sport="mlb", today="2026-08-12", apply=True)
    assert out["compressed"] == []
    assert out["skipped"].get("too_recent") == 1
    assert today.exists() and not today.with_name(today.name + ".gz").exists()


def test_apply_compresses_and_removes_the_original(_root):
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(400))
    before = plain.stat().st_size
    out = obq.compress_closed_shards(sport="mlb", today="2026-08-12", apply=True)
    packed = plain.with_name(plain.name + ".gz")
    assert not plain.exists()
    assert packed.exists() and packed.stat().st_size < before
    assert out["bytes_saved"] > 0
    assert len(obq.read_book_quotes("mlb", "2026-08-09")) == 400


def test_an_undated_file_is_kept_not_guessed_about(_root):
    odd = _root / "mlb_source" / "tracking" / "book_quotes" / "notadate.jsonl"
    odd.parent.mkdir(parents=True, exist_ok=True)
    odd.write_text('{"a":1}\n', encoding="utf-8")
    out = obq.compress_closed_shards(sport="mlb", today="2026-08-12", apply=True)
    assert out["skipped"].get("undated") == 1
    assert odd.exists()


def test_a_failed_verification_keeps_the_original(_root, monkeypatch):
    """The load-bearing refusal. These captures may be the only copy in
    existence, so a half-written .gz must never cost us the input."""
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(100))

    real_open = gzip.open
    calls = {"n": 0}

    def _lying_open(*args, **kwargs):
        # Second gzip.open in the compactor is the read-back verification.
        calls["n"] += 1
        if calls["n"] == 2:
            import io
            return io.BytesIO(b"short\n")  # fewer lines than the source
        return real_open(*args, **kwargs)

    monkeypatch.setattr(obq.gzip, "open", _lying_open)
    out = obq.compress_closed_shards(sport="mlb", today="2026-08-12", apply=True)

    assert out["skipped"].get("verify_line_count_mismatch") == 1
    assert plain.exists(), "original removed after a failed verification"
    assert not plain.with_name(plain.name + ".gz").exists()


def test_already_compressed_shards_are_skipped(_root):
    plain = _write_plain(_root, "mlb", "2026-08-09", _rows(10))
    with gzip.open(str(plain) + ".gz", "wt", encoding="utf-8") as fh:
        fh.write("{}\n")
    out = obq.compress_closed_shards(sport="mlb", today="2026-08-12", apply=True)
    assert out["skipped"].get("already_compressed") == 1
    assert plain.exists()
