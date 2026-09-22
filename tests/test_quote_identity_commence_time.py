"""A grid row's start time must survive a venue quote that does not know it.

MEASURED 2026-09-22 on the 15:11Z MLB board: 457 of 1,823 prop rows had
`commence_time: null` while carrying `game.start_time_utc` and an `event_id`
whose other rows were dated. Two halves, both fixed here:

* the WRITER -- `_capture_polymarket_quotes` wrote Polymarket's own prop quotes
  with no `commence_time`, `home_team` or `away_team` (5,995 of 5,995 on web's
  09-22 MLB shard); its Kalshi sibling has stamped them from the board rows
  since 2026-09-10;
* the GRID -- `build_book_grid` took the start time from the NEWEST quote, so a
  newest-but-undated Polymarket quote blanked a row every other book had dated.

Downstream the blank read as `commence_unknown` at the Polymarket submitter and
`no_kickoff` in the recorder's grading.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from syndicate.features.shared.book_grid import build_book_grid

NOW = datetime(2026, 9, 22, 15, 10, 0, tzinfo=timezone.utc)
KICKOFF = "2026-09-23T00:41:00Z"


def _prop_quote(**overrides):
    row = {
        "sport": "mlb",
        "kind": "prop",
        "event_id": "afbac30624ec",
        "segment": "full",
        "market": "strikeouts",
        "player_name": "Michael Soroka",
        "selection": "over",
        "line": 4.5,
        "price": -120,
        "bookmaker": "draftkings",
        "home_team": "Colorado Rockies",
        "away_team": "Arizona Diamondbacks",
        "commence_time": KICKOFF,
        "snapshot_ts": "2026-09-22T14:50:52Z",
    }
    row.update(overrides)
    return row


def _polymarket_quote(**overrides):
    # Exactly what the shard held before the fix: no teams, no start time.
    row = _prop_quote(
        bookmaker="polymarket",
        source="venue_direct",
        price=-105,
        home_team=None,
        away_team=None,
        commence_time=None,
        snapshot_ts="2026-09-22T14:59:34Z",
    )
    row.update(overrides)
    return row


def _only_row(rows):
    grid = build_book_grid(rows, now=NOW)
    assert len(grid) == 1, grid
    return grid[0]


# ---------------------------------------------------------------- the grid half
def test_a_newer_undated_venue_quote_does_not_blank_the_start_time():
    """The production case: DraftKings dated at 14:50, Polymarket undated at
    14:59. Before the fix this row read `commence_time: None`."""
    row = _only_row([
        _prop_quote(selection="over"),
        _prop_quote(selection="under", price=-102),
        _polymarket_quote(),
    ])
    assert row["commence_time"] == KICKOFF


def test_a_revised_start_time_still_comes_from_the_freshest_dated_report():
    """`#435` is untouched: among DATED reports the newest one wins, even when
    it revises the start EARLIER, and an undated one newer still is skipped."""
    row = _only_row([
        _prop_quote(commence_time="2026-09-23T00:45:00Z", snapshot_ts="2026-09-22T13:00:00Z"),
        _prop_quote(selection="under", commence_time=KICKOFF, snapshot_ts="2026-09-22T14:50:00Z"),
        _polymarket_quote(snapshot_ts="2026-09-22T15:05:00Z"),
    ])
    assert row["commence_time"] == KICKOFF


def test_teams_come_from_any_row_not_only_the_first():
    row = _only_row([
        _polymarket_quote(snapshot_ts="2026-09-22T14:00:00Z"),
        _prop_quote(selection="under"),
    ])
    assert row["home_team"] == "Colorado Rockies"
    assert row["away_team"] == "Arizona Diamondbacks"


def test_no_dated_quote_at_all_still_reads_none():
    """Unknown stays unknown -- nothing is invented."""
    row = _only_row([_polymarket_quote(), _polymarket_quote(selection="under")])
    assert row["commence_time"] is None


# ---------------------------------------------------------- the writer half
def _polymarket_match(**overrides):
    match = {
        "event_id": "afbac30624ec",
        "market": "strikeouts",
        "player_name": "Michael Soroka",
        "line": 4.5,
        "side": "over",
        "polymarket_american": -105,
        "polymarket_slug": "tsc-mlb-soroka-k-4pt5",
    }
    match.update(overrides)
    return match


def _run_capture(tmp_path, monkeypatch, board_rows, matches):
    """The REAL capture, row builder and appender, reading back what reached
    DISK -- asserting on a builder's return value is how the Kalshi lane's
    `venue_ticker` field passed its test while 0 of 603 written rows carried it."""
    from pipeline import portfolio_commit
    from syndicate.features.shared import artifact_publisher

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(artifact_publisher, "publish_hot_artifact", lambda path: None)
    portfolio_commit._capture_polymarket_quotes(
        {"matches": matches}, board_rows, "2026-09-22"
    )
    shard = tmp_path / "mlb_source" / "tracking" / "book_quotes" / "2026-09-22.jsonl"
    assert shard.is_file(), "the capture wrote nothing"
    return [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_polymarket_capture_writes_the_games_identity(tmp_path, monkeypatch, capsys):
    board_rows = [
        # The row the match joined to may itself be undated (it was, on 457
        # rows); the identity comes from ANY row of the event.
        {"event_id": "afbac30624ec", "sport": "mlb", "commence_time": None,
         "home_team": "Colorado Rockies", "away_team": "Arizona Diamondbacks"},
        {"event_id": "afbac30624ec", "sport": "mlb", "commence_time": KICKOFF,
         "home_team": "Colorado Rockies", "away_team": "Arizona Diamondbacks"},
    ]
    written = _run_capture(tmp_path, monkeypatch, board_rows, [_polymarket_match()])
    assert len(written) == 1
    row = written[0]
    assert row["bookmaker"] == "polymarket"
    assert row["source"] == "venue_direct"
    assert row["commence_time"] == KICKOFF
    assert row["home_team"] == "Colorado Rockies"
    assert row["away_team"] == "Arizona Diamondbacks"
    assert "identity_stamped=1" in capsys.readouterr().out


def test_a_polymarket_only_market_is_dated_end_to_end(tmp_path, monkeypatch):
    """Capture -> shard -> grid with NO other book quoting the market, so the
    grid half cannot rescue it: only the writer's stamp can date this row."""
    board_rows = [{"event_id": "afbac30624ec", "sport": "mlb", "commence_time": KICKOFF,
                   "home_team": "Colorado Rockies", "away_team": "Arizona Diamondbacks"}]
    written = _run_capture(
        tmp_path, monkeypatch, board_rows,
        [_polymarket_match(side="over", polymarket_american=-105),
         _polymarket_match(side="under", polymarket_american=-115)],
    )
    grid = build_book_grid(written, now=NOW)
    assert len(grid) == 1, grid
    assert grid[0]["books"] == ["polymarket"]
    assert grid[0]["commence_time"] == KICKOFF


def test_a_match_with_no_known_event_identity_is_written_unchanged(tmp_path, monkeypatch, capsys):
    board_rows = [{"event_id": "afbac30624ec", "sport": "mlb"}]
    written = _run_capture(tmp_path, monkeypatch, board_rows, [_polymarket_match()])
    assert written[0]["commence_time"] is None
    assert "identity_stamped=0" in capsys.readouterr().out
