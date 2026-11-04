"""odds_book_quotes STATE under concurrent writers (#759, lane book-quotes-state-reset).

Soccer's `<date>.state.json` for 10-31 and 11-01 kept 1,783 of 58,622 and 4,071 of 35,252 shard keys: several
processes write one shard date, and the state's load-compare-write ran outside the shard lock through one shared
temp name. These pin the fix: writers take turns, each writes through its own temp file, and an unreadable state is
said out loud and kept."""
from __future__ import annotations

import json
import threading
import time

import pytest

from syndicate.features.shared import odds_book_quotes as obq

DATE = "2026-10-31"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(obq, "data_root", lambda: tmp_path)
    return tmp_path


def _row(event, price=-110):
    return {"event_id": event, "bookmaker": "pinnacle", "market": "totals", "selection": "over", "line": 2.5,
            "price": price, "commence_time": "2026-10-31T15:00:00Z", "kind": "game"}


def _append(rows, at):
    return obq.append_book_quotes(sport="soccer", date_str=DATE, rows=rows, captured_at=at, publish=False)


def test_two_writers_on_one_shard_keep_each_others_keys(root, monkeypatch):
    # Writer A stalls inside its state write while writer B runs. Before #759, B loaded the state A had not
    # written yet, and A's write then dropped B's key -- so B's unchanged price was appended AGAIN next time.
    original = obq._write_state
    a_writing = threading.Event()

    def slow_first_write(path, state):
        if not a_writing.is_set():
            a_writing.set()
            time.sleep(0.6)
        original(path, state)

    monkeypatch.setattr(obq, "_write_state", slow_first_write)
    a = threading.Thread(target=_append, args=([_row("e1")], "2026-10-31T12:00:00Z"))
    a.start()
    assert a_writing.wait(5)
    b = threading.Thread(target=_append, args=([_row("e2")], "2026-10-31T12:00:01Z"))
    b.start()
    a.join(10)
    b.join(10)

    state = json.loads(obq._state_path("soccer", DATE).read_text())
    assert sorted(key.split("|")[2] for key in state) == ["e1", "e2"]
    again = _append([_row("e1"), _row("e2")], "2026-10-31T12:05:00Z")
    assert again["appended"] == 0                                    # nothing re-appended at an unchanged price
    assert len(obq.book_quotes_path("soccer", DATE).read_text().splitlines()) == 2


def test_each_state_write_uses_its_own_temp_file(root, monkeypatch):
    path = obq._state_path("soccer", DATE)
    path.parent.mkdir(parents=True)
    sources = []
    real_replace = obq.os.replace

    def recording_replace(src, dst):
        sources.append(str(src))
        real_replace(src, dst)

    monkeypatch.setattr(obq.os, "replace", recording_replace)
    obq._write_state(path, {"k": [2.5, -110, "t1"]})
    obq._write_state(path, {"k": [2.5, -105, "t2"]})
    assert len(set(sources)) == 2 and str(path) + ".tmp" not in sources
    assert [p.name for p in path.parent.iterdir()] == [path.name]    # no temp file left behind
    assert json.loads(path.read_text()) == {"k": [2.5, -105, "t2"]}


def test_an_unreadable_state_is_logged_and_kept_and_the_capture_goes_on(root, capsys):
    path = obq._state_path("soccer", DATE)
    path.parent.mkdir(parents=True)
    torn = b'{"soccer|game|e0|pinnacle|full|totals|over||2.5":[2.5,-110,"2026-10-31T11:00:00Z"],"socc'
    path.write_bytes(torn)
    out = _append([_row("e1")], "2026-10-31T12:00:00Z")
    log = capsys.readouterr().out
    assert "BOOK_QUOTES_STATE_UNREADABLE" in log and f"bytes={len(torn)}" in log
    assert path.with_name(path.name + ".unreadable").read_bytes() == torn
    assert out["appended"] == 1 and out["tracked_keys"] == 1
    assert len(json.loads(path.read_text())) == 1                   # valid JSON again


def test_a_missing_state_is_not_unreadable_and_an_empty_call_reads_nothing(root, capsys):
    first = _append([_row("e1")], "2026-10-31T12:00:00Z")
    empty = _append([], "2026-10-31T12:01:00Z")
    assert "BOOK_QUOTES_STATE_UNREADABLE" not in capsys.readouterr().out
    assert first["appended"] == 1 and first["tracked_keys"] == 1
    assert empty["appended"] == 0 and empty["tracked_keys"] is None
