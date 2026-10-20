"""A kickoff that moves across a date must not leave a ghost row in the old date's grid.

Measured on the fleet 2026-10-20: NCAAF Iowa @ Minnesota sat in
`book_grid_2026-10-23` at a superseded `2026-10-24T04:00Z` placeholder with
prices last looked at 10-17, `servable: True` and +8.21 pts "better than
consensus", while `book_grid_2026-10-24` carried the real 19:30Z game. These
pin the drop, the refusal to drop on ABSENCE, and that the builder actually
runs it (off != on).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import board_enrichment, book_grid_artifact
from syndicate.features.shared.book_grid_artifact import drop_events_moved_to_another_date
from syndicate.features.shared.odds_book_quotes import quote_key

NOW = datetime(2026, 10, 20, 22, 0, tzinfo=timezone.utc)
GHOST = "6dab7d3b"
FRIDAY = "fri-game"


def _quote(event_id, commence, price=-150, selection="away", stamp="2026-10-17T18:32:14Z"):
    return {
        "sport": "ncaaf",
        "kind": "game",
        "event_id": event_id,
        "segment": "full",
        "market": "h2h",
        "player_name": "",
        "selection": selection,
        "line": None,
        "price": price,
        "bookmaker": "fanduel",
        "home_team": "Minnesota Golden Gophers" if event_id == GHOST else "Duke Blue Devils",
        "away_team": "Iowa Hawkeyes" if event_id == GHOST else "Virginia Cavaliers",
        "commence_time": commence,
        "snapshot_ts": stamp,
    }


def _grid_rows():
    return [
        {"event_id": GHOST, "market": "h2h", "commence_time": "2026-10-24T04:00:00Z",
         "away_team": "Iowa Hawkeyes", "home_team": "Minnesota Golden Gophers"},
        {"event_id": GHOST, "market": "totals", "commence_time": "2026-10-24T04:00:00Z"},
        {"event_id": FRIDAY, "market": "h2h", "commence_time": "2026-10-24T00:00:00Z"},
    ]


def _own_seen():
    return {
        quote_key(_quote(GHOST, "2026-10-24T04:00:00Z")): "2026-10-17T18:32:14+00:00",
        quote_key(_quote(FRIDAY, "2026-10-24T00:00:00Z")): "2026-10-20T21:55:00+00:00",
    }


def _reader(by_date):
    calls = []

    def _read(sport, date_str):
        calls.append(date_str)
        return by_date.get(date_str, {})

    _read.calls = calls
    return _read


def _moved_to_saturday():
    return {"2026-10-24": {quote_key(_quote(GHOST, "2026-10-24T19:30:00Z")): "2026-10-20T21:55:59+00:00"}}


def test_ghost_event_is_dropped_and_the_live_one_kept(monkeypatch):
    monkeypatch.delenv("SYNDICATE_BOOK_GRID_DROP_MOVED_KICKOFF", raising=False)
    kept, counters = drop_events_moved_to_another_date(
        _grid_rows(), sport="ncaaf", date_str="2026-10-23", last_seen=_own_seen(),
        now=NOW, read_last_seen=_reader(_moved_to_saturday()),
    )
    assert [r["event_id"] for r in kept] == [FRIDAY]
    assert counters["candidates"] == 1
    assert counters["events_moved"] == 1
    assert counters["rows_dropped"] == 2
    assert counters["sample"][0]["moved_to"] == "2026-10-24"


def test_quiet_event_seen_nowhere_else_is_kept():
    """Absence elsewhere is not a move: a market nobody re-quoted keeps its row."""
    kept, counters = drop_events_moved_to_another_date(
        _grid_rows(), sport="ncaaf", date_str="2026-10-23", last_seen=_own_seen(),
        now=NOW, read_last_seen=_reader({}),
    )
    assert len(kept) == 3
    assert counters["candidates"] == 1
    assert counters["events_moved"] == 0


def test_an_older_look_on_another_date_does_not_move_it():
    older = {"2026-10-22": {quote_key(_quote(GHOST, "2026-10-23T04:00:00Z")): "2026-10-10T12:00:00+00:00"}}
    kept, counters = drop_events_moved_to_another_date(
        _grid_rows(), sport="ncaaf", date_str="2026-10-23", last_seen=_own_seen(),
        now=NOW, read_last_seen=_reader(older),
    )
    assert len(kept) == 3
    assert counters["events_moved"] == 0


def test_recently_looked_events_read_no_neighbour_shard():
    """An ordinary build opens no extra file: the neighbour read is candidate-gated."""
    fresh = {k: "2026-10-20T21:55:00+00:00" for k in _own_seen()}
    reader = _reader(_moved_to_saturday())
    kept, counters = drop_events_moved_to_another_date(
        _grid_rows(), sport="ncaaf", date_str="2026-10-23", last_seen=fresh,
        now=NOW, read_last_seen=reader,
    )
    assert len(kept) == 3
    assert counters["candidates"] == 0
    assert reader.calls == []


def test_a_forward_game_filed_under_a_past_slate_date_is_not_a_move():
    """Capture-dated copies (NFL/soccer 10-18/10-19 on the fleet) are that day's view."""
    rows = [{"event_id": GHOST, "market": "h2h", "commence_time": "2026-10-25T17:00:00Z"}]
    kept, counters = drop_events_moved_to_another_date(
        rows, sport="nfl", date_str="2026-10-19", last_seen=_own_seen(),
        now=NOW, read_last_seen=_reader({"2026-10-20": {quote_key(_quote(GHOST, "x")): "2026-10-20T21:55:59+00:00"}}),
    )
    assert kept == rows
    assert counters["candidates"] == 0


def test_started_games_are_not_candidates():
    later = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    kept, counters = drop_events_moved_to_another_date(
        _grid_rows(), sport="ncaaf", date_str="2026-10-23", last_seen=_own_seen(),
        now=later, read_last_seen=_reader(_moved_to_saturday()),
    )
    assert len(kept) == 3
    assert counters["candidates"] == 0


def test_off_keeps_the_rows_but_still_counts(monkeypatch):
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_DROP_MOVED_KICKOFF", "off")
    kept, counters = drop_events_moved_to_another_date(
        _grid_rows(), sport="ncaaf", date_str="2026-10-23", last_seen=_own_seen(),
        now=NOW, read_last_seen=_reader(_moved_to_saturday()),
    )
    assert len(kept) == 3
    assert counters["enabled"] is False
    assert counters["events_moved"] == 1


def test_a_reader_failure_returns_the_grid_unchanged():
    def _boom(sport, date_str):
        raise OSError("disk")

    rows = _grid_rows()
    kept, counters = drop_events_moved_to_another_date(
        rows, sport="ncaaf", date_str="2026-10-23", last_seen=_own_seen(),
        now=NOW, read_last_seen=_boom,
    )
    assert kept is rows
    assert "OSError" in counters["error"]


@pytest.mark.parametrize("switch, expect_ghost", [("on", False), ("off", True)])
def test_reachability_through_the_real_builder(monkeypatch, tmp_path, capsys, switch, expect_ghost):
    """off != on through `build_book_grid_artifact` itself, with the real pivot."""
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_DROP_MOVED_KICKOFF", switch)
    shard = tmp_path / "2026-10-23.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    # The builder reads the real clock, so the kickoffs must stay in the future
    # whenever this runs; the quote KEY carries no kickoff, so the 10-24 sidecar
    # below still names the same markets.
    quotes = [
        _quote(GHOST, "2099-10-24T04:00:00Z", -182, "away"),
        _quote(GHOST, "2099-10-24T04:00:00Z", 150, "home"),
        _quote(FRIDAY, "2099-10-24T00:00:00Z", -120, "away", stamp="2026-10-20T21:55:00Z"),
        _quote(FRIDAY, "2099-10-24T00:00:00Z", 100, "home", stamp="2026-10-20T21:55:00Z"),
    ]
    own = {quote_key(q): ("2026-10-17T18:32:14+00:00" if q["event_id"] == GHOST else "2026-10-20T21:55:00+00:00")
           for q in quotes}
    by_date = {"2099-10-23": own, "2099-10-24": {quote_key(quotes[0]): "2026-10-20T21:55:59+00:00"}}
    monkeypatch.setattr(book_grid_artifact, "book_quotes_path", lambda *a, **k: shard)
    monkeypatch.setattr(book_grid_artifact, "iter_book_quotes", lambda *a, **k: iter(list(quotes)))
    monkeypatch.setattr(book_grid_artifact, "read_quote_last_seen", lambda sport, d: by_date.get(d, {}))
    for name in ("attach_game_state", "attach_projections", "attach_margin_model",
                 "attach_live_game_state_from_lens", "attach_live_projections_for_sport",
                 "attach_live_gamelines_for_sport"):
        monkeypatch.setattr(board_enrichment, name, lambda grid, **kwargs: {})
    monkeypatch.setattr(book_grid_artifact, "_remember_inplay_rows", lambda *a, **k: None)
    import syndicate.features.shared.live_gameline_ledger as ledger
    import syndicate.features.shared.live_gameline_accuracy as accuracy
    monkeypatch.setattr(ledger, "record_live_gamelines", lambda grid, **k: {})
    monkeypatch.setattr(accuracy, "record_live_gameline_score", lambda *a, **k: {})
    monkeypatch.setattr(book_grid_artifact, "score_block_for_grid", lambda grid, **k: {})
    monkeypatch.setattr(book_grid_artifact, "live_gameline_build_line", lambda *a, **k: "")

    payload = book_grid_artifact.build_book_grid_artifact("ncaaf", "2099-10-23")

    events = {row["event_id"] for row in payload["rows"]}
    assert FRIDAY in events
    assert (GHOST in events) is expect_ghost
    assert payload["moved_kickoff"]["events_moved"] == 1
    assert "MOVED_KICKOFF_ROWS_DROPPED sport=ncaaf date=2099-10-23" in capsys.readouterr().out
