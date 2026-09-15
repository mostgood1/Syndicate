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
    yield tmp_path
    obq._BAD_LINES_REPORTED.clear()


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
