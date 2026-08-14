"""`#430` — the board reported how old the BUILD was and never how old the ODDS were.

THE MEASUREMENT THAT PROMPTED THIS, production 2026-08-14 15:00Z, MLB
(`/api/board/layer1?sport=mlb&date=2026-08-14&window=slate`):

    generated_at                 2026-08-14T14:58:49Z   ->  1.6 min old
    freshest row `updated_at`    2026-08-14T13:09:05Z   ->  1h51m old
    min `seen_age_seconds`       6576.8s                ->  1h50m, agrees

The header said "built 2m old" and nothing on the page contradicted it. Both
clocks independently put the odds nearly two hours behind the board.

These cover the three ways that number can go wrong once it is being served:
reading the price-MOVE clock instead of the LOOK clock, forgetting that the
stored ages are relative to the worker's build and not to now, and letting a row
with no age at all read as a fresh one.
"""

from __future__ import annotations

from syndicate.features.shared.layer1_board import (
    _odds_freshness,
    build_layer1_board,
    partition_board_by_state,
)


def _row(event_id="evt-1", state="pregame", seen_age=120.0, move_age=600.0, **extra):
    row = {
        "sport": "mlb",
        "event_id": event_id,
        "kind": "game",
        "market": "h2h",
        "segment": "full",
        "sides": ["away", "home"],
        "away_team": "St. Louis Cardinals",
        "home_team": "Chicago Cubs",
        "commence_time": "2026-08-14T18:20:00Z",
        "game": {"state": state},
    }
    if seen_age is not None:
        row["seen_age_seconds"] = seen_age
    if move_age is not None:
        row["age_seconds"] = move_age
    row.update(extra)
    return row


def test_freshest_look_is_the_minimum_seen_age_not_the_move_age():
    """The headline is the LOOK clock, and the two must not be conflated.

    `book_quotes` is a change log, so a motionless pregame market reads as hours
    old on the move clock while being perfectly current -- 424-minute NFL medians
    were once read as a capture outage and were nothing of the kind. Here every
    row was looked at 2 minutes ago and none has moved in an hour; the board is
    fresh and only one of these two numbers says so.
    """
    freshness = _odds_freshness([_row(seen_age=120.0, move_age=3600.0)])

    assert freshness["seen_age_seconds_min"] == 120.0
    assert freshness["price_move_age_seconds_min"] == 3600.0


def test_median_is_reported_beside_the_min_so_one_fresh_row_cannot_speak_for_the_board():
    """A single re-quoted market must not make 200 stale ones look current."""
    rows = [_row(seen_age=30.0), _row(seen_age=6000.0), _row(seen_age=6600.0)]

    freshness = _odds_freshness(rows)

    assert freshness["seen_age_seconds_min"] == 30.0
    assert freshness["seen_age_seconds_median"] == 6000.0
    assert freshness["seen_age_seconds_max"] == 6600.0


def test_rows_without_a_seen_age_are_counted_as_unknown_never_as_fresh():
    """Absent must not default permissive.

    A row predating last-seen tracking carries no `seen_age_seconds`. Dropping it
    silently would let a board with one datable row claim that row's freshness
    for all of them.
    """
    freshness = _odds_freshness([_row(seen_age=60.0), _row(seen_age=None), _row(seen_age=None)])

    assert freshness["seen_age_seconds_min"] == 60.0
    assert freshness["rows_with_seen_age"] == 1
    assert freshness["rows_missing_seen_age"] == 2


def test_a_board_with_no_seen_age_at_all_reports_none_rather_than_a_number():
    """No age is not age zero. The caller renders "unknown", not "fresh"."""
    freshness = _odds_freshness([_row(seen_age=None, move_age=None)])

    assert freshness["seen_age_seconds_min"] is None
    assert freshness["seen_age_seconds_median"] is None
    assert freshness["rows_with_seen_age"] == 0
    assert freshness["rows_missing_seen_age"] == 1


def test_board_carries_freshness_over_the_date_scoped_rows_only():
    """Scoped, not grid-wide.

    A 7-day soccer window read from one artifact would otherwise report the
    freshness of days the caller is not looking at. The off-window row here is
    the freshest in the grid and must not be the board's answer.
    """
    board = build_layer1_board(
        [
            _row(event_id="evt-1", seen_age=6600.0),
            _row(event_id="evt-2", seen_age=5.0, commence_time="2026-09-30T18:20:00Z"),
        ],
        sport="mlb",
        selected_date="2026-08-14",
        window_dates=["2026-08-14"],
    )

    assert board["counts"]["rows"] == 1
    assert board["odds_freshness"]["seen_age_seconds_min"] == 6600.0


def test_a_filtered_view_recomputes_freshness_instead_of_inheriting_the_slates():
    """Live games are re-quoted on a tighter cadence than pregame ones.

    `partition_board_by_state` copies the payload, so the pregame board would
    otherwise inherit the whole slate's freshest look -- which is routinely a
    live row the pregame view does not contain, i.e. a freshness claim borrowed
    from a game it is not showing.
    """
    board = build_layer1_board(
        [
            _row(event_id="evt-live", state="live", seen_age=20.0),
            _row(event_id="evt-pre", state="pregame", seen_age=6600.0),
        ],
        sport="mlb",
        selected_date="2026-08-14",
        window_dates=["2026-08-14"],
    )
    assert board["odds_freshness"]["seen_age_seconds_min"] == 20.0

    pregame = partition_board_by_state(board, "pregame")

    assert pregame["odds_freshness"]["seen_age_seconds_min"] == 6600.0
