"""odds_book_quotes fetch heartbeat (Test B F0): one line per fetch that OBSERVED anything, including a fetch whose
every price was unchanged -- the case the change log cannot record -- in its own directory, never in book_quotes/."""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import odds_book_quotes as obq


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(obq, "data_root", lambda: tmp_path)
    return tmp_path


def _row(book, event="e1", price=-110, selection="home"):
    return {"event_id": event, "bookmaker": book, "market": "spreads", "selection": selection, "line": -3.5,
            "price": price, "commence_time": "2026-10-26T00:00:00Z", "kind": "game"}


def test_a_heartbeat_is_written_even_when_no_price_moved(root):
    rows = [_row("pinnacle"), _row("draftkings", event="e2")]
    first = obq.append_book_quotes(sport="nfl", date_str="2026-10-25", rows=rows, captured_at="2026-10-25T17:00:00Z", publish=False)
    again = obq.append_book_quotes(sport="nfl", date_str="2026-10-25", rows=rows, captured_at="2026-10-25T17:02:30Z", publish=False)
    assert first["appended"] == 2 and again["appended"] == 0          # the change log records nothing the 2nd time
    beats = obq.read_fetch_heartbeats("nfl", "2026-10-25")
    assert [b["captured_at"] for b in beats] == ["2026-10-25T17:00:00Z", "2026-10-25T17:02:30Z"]   # ...the heartbeat does
    assert beats[1]["pinnacle_events"] == ["e1"] and beats[1]["events"] == ["e1", "e2"]
    assert beats[1]["books"] == ["draftkings", "pinnacle"]


def test_the_heartbeat_never_lands_where_quote_readers_glob(root):
    obq.append_book_quotes(sport="soccer", date_str="2026-10-25", rows=[_row("pinnacle")],
                           captured_at="2026-10-25T17:00:00Z", publish=False)
    quotes_dir = obq.book_quotes_path("soccer", "2026-10-25").parent
    assert [p.name for p in quotes_dir.glob("*.jsonl")] == ["2026-10-25.jsonl"]
    assert obq.heartbeat_path("soccer", "2026-10-25").parent.name == obq.HEARTBEAT_DIRNAME
    for line in obq.book_quotes_path("soccer", "2026-10-25").read_text().splitlines():
        assert "pinnacle_events" not in json.loads(line)


def test_no_observation_no_heartbeat_and_a_failure_never_raises(root, monkeypatch):
    obq.append_book_quotes(sport="nba", date_str="2026-10-25", rows=[], captured_at="2026-10-25T17:00:00Z", publish=False)
    assert obq.read_fetch_heartbeats("nba", "2026-10-25") == []
    monkeypatch.setattr(obq, "heartbeat_path", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    out = obq.append_book_quotes(sport="nba", date_str="2026-10-25", rows=[_row("pinnacle")],
                                 captured_at="2026-10-25T17:01:00Z", publish=False)
    assert out["appended"] == 1                                        # the quote still lands
