"""Unreadable book_quotes lines are counted, not silently skipped (P0).

Lane `book-quotes-splice-repair`: a byte-offset tail pull after a local append
splices headless fragments into shards (29 in web's mlb 09-03), and both readers
dropped them with a bare `continue`, so no instrument could see the damage.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import odds_book_quotes as obq

ROW = {"sport": "mlb", "market": "h2h", "selection": "home", "price": -110}
FRAGMENT = 'Z","sport":"mlb","market":"h2h","price":340}'


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    obq._BOOK_QUOTES_CACHE.clear()
    obq._BAD_LINES_REPORTED.clear()
    obq._SANITIZED_CLEAN_BYTES.clear()
    yield tmp_path
    obq._BAD_LINES_REPORTED.clear()
    obq._SANITIZED_CLEAN_BYTES.clear()


def _shard(root, lines):
    p = root / "mlb_source" / "tracking" / "book_quotes" / "2026-09-03.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_a_fragment_is_counted_once_and_never_yielded(_root, capsys):
    _shard(_root, [json.dumps(ROW), FRAGMENT, json.dumps(ROW), "[1, 2]"])
    rows = list(obq.iter_book_quotes("mlb", "2026-09-03"))
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert "BOOK_QUOTES_BAD_LINES sport=mlb shard=2026-09-03.jsonl bad=2 lines=4" in out

    list(obq.iter_book_quotes("mlb", "2026-09-03"))
    assert "BOOK_QUOTES_BAD_LINES" not in capsys.readouterr().out, "one line per change, not per read"


def test_the_cached_reader_counts_too(_root, capsys):
    _shard(_root, [json.dumps(ROW), FRAGMENT])
    assert len(obq.read_book_quotes("mlb", "2026-09-03")) == 1
    assert "bad=1 lines=2" in capsys.readouterr().out


def test_a_clean_shard_says_nothing(_root, capsys):
    _shard(_root, [json.dumps(ROW), json.dumps(ROW)])
    list(obq.iter_book_quotes("mlb", "2026-09-03"))
    obq.read_book_quotes("mlb", "2026-09-03")
    assert "BOOK_QUOTES_BAD_LINES" not in capsys.readouterr().out


def test_a_growing_bad_count_is_reported_again(_root, capsys):
    p = _shard(_root, [json.dumps(ROW), FRAGMENT])
    list(obq.iter_book_quotes("mlb", "2026-09-03"))
    with p.open("a", encoding="utf-8") as fh:
        fh.write(FRAGMENT + "\n")
    list(obq.iter_book_quotes("mlb", "2026-09-03"))
    out = capsys.readouterr().out
    assert "bad=1 lines=2" in out and "bad=2 lines=3" in out


# --- write faults (2026-09-15): a torn tail, and stale local copies republished ---

PROP = {
    "kind": "prop",
    "event_id": "evt-1",
    "commence_time": "2026-09-03T23:15:00Z",
    "bookmaker": "fanduel",
    "market": "batter_hits",
    "selection": "over",
    "player_name": "Jeremy Pena",
    "line": 0.5,
    "price": "+410",
}
TORN = b'{"captured_at":"2026-09-03T07:31:59.204918+0'


def test_an_append_after_a_torn_tail_does_not_glue_onto_it(_root, capsys):
    p = _shard(_root, [json.dumps(ROW)])
    with p.open("ab") as fh:
        fh.write(TORN)  # a row cut by ENOSPC: no newline
    result = obq.append_book_quotes(
        sport="mlb", date_str="2026-09-03", rows=[PROP], captured_at="2026-09-03T10:22:29Z", publish=False
    )
    assert result["appended"] == 1
    lines = p.read_bytes().splitlines()
    assert lines[1] == TORN, "the torn head stays a line of its own"
    assert json.loads(lines[2])["player_name"] == "Jeremy Pena", "the new row is readable"
    assert "BOOK_QUOTES_TORN_TAIL_TERMINATED" in capsys.readouterr().out


def test_a_clean_append_adds_no_blank_line(_root, capsys):
    p = _shard(_root, [json.dumps(ROW)])
    obq.append_book_quotes(sport="mlb", date_str="2026-09-03", rows=[PROP], captured_at="2026-09-03T10:22:29Z", publish=False)
    assert len(p.read_bytes().splitlines()) == 2
    assert "BOOK_QUOTES_TORN_TAIL_TERMINATED" not in capsys.readouterr().out


def test_sanitize_drops_unreadable_lines_and_then_reads_only_the_new_tail(_root, capsys, monkeypatch):
    p = _shard(_root, [json.dumps(ROW), FRAGMENT, json.dumps(ROW)])
    result = obq.sanitize_book_quotes_shard(p)
    assert (result["dropped"], result["kept"]) == (1, 2)
    assert [json.loads(line) for line in p.read_bytes().splitlines()] == [ROW, ROW]
    assert "BOOK_QUOTES_LOCAL_BAD_DROPPED" in capsys.readouterr().out
    assert obq.sanitize_book_quotes_shard(p) is None

    with p.open("ab") as fh:
        fh.write(json.dumps(ROW).encode("utf-8") + b"\n")
    calls = []
    real = obq._is_json_object_bytes
    monkeypatch.setattr(obq, "_is_json_object_bytes", lambda line: calls.append(line) or real(line))
    assert obq.sanitize_book_quotes_shard(p) is None
    assert len(calls) == 1, "only the bytes appended since the last clean scan are read"


def test_sanitize_leaves_a_clean_shard_byte_identical(_root):
    p = _shard(_root, [json.dumps(ROW), json.dumps(ROW)])
    before = p.read_bytes()
    assert obq.sanitize_book_quotes_shard(p) is None
    assert p.read_bytes() == before
