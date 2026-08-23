"""The Kalshi-native board: opening lines, bounded history, movement, cadence."""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_board


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


def _market(ticker: str, yes: float, **extra):
    payload = {
        "ticker": ticker,
        "yes_ask_dollars": yes,
        "no_ask_dollars": round(1.0 - yes, 4),
        "title": f"{ticker} title",
        "series": "KXMLBKS",
        "close_time": "2026-08-24T23:10:00Z",
    }
    payload.update(extra)
    return payload


def test_first_sight_records_an_opening_and_counts_it():
    result = kalshi_board.record_snapshot([_market("A", 0.40)], now="2026-08-23T10:00:00Z")

    assert result["status"] == "ok"
    assert result["opened"] == 1
    assert result["appended"] == 1
    assert result["unchanged"] == 0

    opening = kalshi_board.opening_line("A")
    assert opening["opening_yes"] == 0.40
    assert opening["opened_at"] == "2026-08-23T10:00:00Z"


def test_an_unchanged_price_is_not_appended():
    kalshi_board.record_snapshot([_market("A", 0.40)], now="2026-08-23T10:00:00Z")
    second = kalshi_board.record_snapshot([_market("A", 0.40)], now="2026-08-23T11:00:00Z")

    # A point per fetch recording that nothing happened would push real moves
    # out of the bounded window.
    assert second["appended"] == 0
    assert second["unchanged"] == 1
    assert second["opened"] == 0
    assert kalshi_board.opening_line("A")["observations"] == 1


def test_the_opening_survives_the_window_filling():
    """The bug this file's design exists to prevent.

    Trimming is oldest-first, and oldest-first is the opening. If movement were
    measured from `points[0]`, a full window would silently change the meaning
    of every CLV number from "since the open" to "since some arbitrary hour"
    with no visible change in the output.
    """
    price = 0.10
    for hour in range(kalshi_board._MAX_POINTS_PER_TICKER + 6):
        price = round(price + 0.005, 4)
        kalshi_board.record_snapshot(
            [_market("A", price)], now=f"2026-08-23T{hour % 24:02d}:{hour:02d}:00Z"
        )

    opening = kalshi_board.opening_line("A")
    assert opening["opening_yes"] == 0.105, "the opening was rewritten or trimmed away"
    assert opening["observations"] == kalshi_board._MAX_POINTS_PER_TICKER

    report = kalshi_board.movement_report()
    mover = report["movers"][0]
    assert mover["opening_yes"] == 0.105
    assert mover["move_points"] == pytest.approx((price - 0.105) * 100.0, abs=0.01)


def test_trimming_is_reported_not_silent():
    for hour in range(kalshi_board._MAX_POINTS_PER_TICKER + 1):
        result = kalshi_board.record_snapshot(
            [_market("A", round(0.10 + hour * 0.005, 4))],
            now=f"2026-08-23T{hour % 24:02d}:{hour:02d}:00Z",
        )
    assert result["trimmed_points"] == 1


def test_one_observation_is_too_new_never_a_zero_mover():
    kalshi_board.record_snapshot([_market("A", 0.40)], now="2026-08-23T10:00:00Z")

    report = kalshi_board.movement_report()
    # "We have not watched this long enough" and "this has not moved" license
    # opposite decisions, so they must not share a bucket.
    assert report["tickers"] == 1
    assert report["too_new"] == 1
    assert report["moved"] == 0
    assert report["movers"] == []


def test_movement_is_in_probability_points_and_sorted_by_magnitude():
    kalshi_board.record_snapshot(
        [_market("UP", 0.40), _market("DOWN", 0.60), _market("FLAT", 0.50)],
        now="2026-08-23T10:00:00Z",
    )
    kalshi_board.record_snapshot(
        [_market("UP", 0.45), _market("DOWN", 0.42), _market("FLAT", 0.50)],
        now="2026-08-23T11:00:00Z",
    )

    report = kalshi_board.movement_report()
    by_ticker = {m["ticker"]: m for m in report["movers"]}
    assert by_ticker["UP"]["move_points"] == pytest.approx(5.0)
    assert by_ticker["DOWN"]["move_points"] == pytest.approx(-18.0)
    # Sorted by absolute move: the biggest move is a move whichever way it went.
    assert report["movers"][0]["ticker"] == "DOWN"
    # FLAT never got a second point, so it is too_new -- not unmoved.
    assert "FLAT" not in by_ticker
    assert report["too_new"] == 1


def test_a_market_with_no_price_is_skipped_not_opened():
    result = kalshi_board.record_snapshot(
        [{"ticker": "A", "yes_ask_dollars": None, "no_ask_dollars": None}],
        now="2026-08-23T10:00:00Z",
    )
    assert result["opened"] == 0
    assert result["tickers"] == 0
    assert kalshi_board.opening_line("A") is None


def test_opening_line_is_none_for_an_untracked_ticker():
    kalshi_board.record_snapshot([_market("A", 0.40)], now="2026-08-23T10:00:00Z")
    # None means "not tracked". A caller must not read it as "no movement".
    assert kalshi_board.opening_line("NEVER_SEEN") is None


def test_board_groups_by_close_day_not_close_timestamp():
    """#370 in a new place: a night game closes after midnight UTC."""
    markets = [
        _market("A", 0.4, close_time="2026-08-24T23:10:00Z"),
        _market("B", 0.4, close_time="2026-08-24T02:40:00Z"),
        _market("C", 0.4, close_time="2026-08-25T01:05:00Z", series="KXMLBOUTS"),
    ]
    board = kalshi_board.board_by_game_date(markets)

    assert board["by_date"] == {"2026-08-24": 2, "2026-08-25": 1}
    assert board["by_date_series"]["2026-08-24"] == {"KXMLBKS": 2}
    assert board["by_date_series"]["2026-08-25"] == {"KXMLBOUTS": 1}


def test_a_market_without_a_close_time_is_named_not_dropped():
    board = kalshi_board.board_by_game_date([_market("A", 0.4, close_time=None)])
    # Dropping it would make the board's total silently disagree with the fetch.
    assert board["by_date"] == {"<no_close_time>": 1}
