"""The Layer 2 price trail (lane `layer2-row-parity`).

What each test pins is a defect measured on the served board 2026-09-15:

  * in the legacy sparklines before this trail: MLB unders plotted the OVER
    price, 6 of 58 series drew a line change as a price move, and one price per
    side came from whichever book was met first;
  * in this trail's FIRST design (18:08:02Z): 45 of 94 series sloped against
    their own arrow, because they started later than the row's opening and
    plotted a different quantity than the label (user decision: "Plot the
    label's price from our open").

plus the two properties that keep a per-build writer affordable on
refresh-worker: change-only appends and a bounded file.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from syndicate.features.shared import clv_price_trail as trail_mod
from syndicate.features.shared.clv_price_trail import (
    load_price_trail,
    price_move_series,
    price_trail_path,
    record_price_trail,
)
from syndicate.features.shared.opportunity_signals import implied_probability

T0 = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
E0 = int(T0.timestamp())
DATE = "2026-09-15"


def _key(row):
    return f"{row['event_id']}|{row['market']}|{row.get('side')}"


def _row(*, price=-110, line=6.5, book="draftkings", side="over"):
    return {
        "event_id": "e1",
        "market": "strikeouts",
        "side": side,
        "line": line,
        "quote": {"price": price, "bookmaker": book, "fair_probability": 0.5},
    }


def _record(tmp_path, rows, minutes, trail=None):
    return record_price_trail(
        rows, date=DATE, trail=trail, now=T0 + timedelta(minutes=minutes), root=tmp_path, key_fn=_key
    )


def _bp(price):
    return int(round(implied_probability(price) * 10000))


# ---------------------------------------------------------------------------
# The writer.
# ---------------------------------------------------------------------------


def test_an_unchanged_observation_is_not_appended(tmp_path):
    first = _record(tmp_path, [_row()], 0)
    second = _record(tmp_path, [_row()], 15)
    assert first["points_written"] == 1
    assert second["points_written"] == 0 and second["unchanged"] == 1
    assert len(load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]) == 1


def test_a_price_or_book_change_is_recorded(tmp_path):
    _record(tmp_path, [_row()], 0)
    assert _record(tmp_path, [_row(price=-120)], 15)["points_written"] == 1
    assert _record(tmp_path, [_row(price=-120, book="fanduel")], 30)["points_written"] == 1


def test_a_fair_only_change_writes_nothing(tmp_path):
    """The line now draws the label's price, so a devig wobble is not a point."""
    _record(tmp_path, [_row()], 0)
    moved_fair = _row()
    moved_fair["quote"]["fair_probability"] = 0.53
    assert _record(tmp_path, [moved_fair], 15)["points_written"] == 0


def test_a_file_from_the_first_design_still_loads(tmp_path):
    path = price_trail_path(DATE, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"k": "x", "t": E0, "l": 6.5, "f": 0.44, "p": -110, "b": "dk"}) + "\n", encoding="utf-8")
    assert load_price_trail(DATE, root=tmp_path)["x"] == [(E0, 6.5, -110.0, "dk")]


def test_a_torn_final_line_is_skipped_not_fatal(tmp_path):
    _record(tmp_path, [_row()], 0)
    path = price_trail_path(DATE, root=tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"k": "e1|strikeouts|over", "t": 12')
    assert len(load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]) == 1


def test_the_file_stops_at_the_ceiling(tmp_path, monkeypatch):
    monkeypatch.setattr(trail_mod, "_MAX_TRAIL_BYTES", 150)
    report = _record(tmp_path, [_row(price=-110 - i, side=f"s{i}") for i in range(10)], 0)
    assert report["truncated_at_ceiling"] is True
    assert 0 < report["points_written"] < 10
    assert price_trail_path(DATE, root=tmp_path).stat().st_size <= 150


def test_the_index_keeps_the_first_point_when_trimming(tmp_path, monkeypatch):
    monkeypatch.setattr(trail_mod, "_MAX_POINTS_PER_KEY", 4)
    for i in range(10):
        _record(tmp_path, [_row(price=-110 - i)], i * 10)
    points = load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]
    assert len(points) == 4
    assert points[0][2] == -110, "the opening-most point survives the trim"
    assert points[-1][2] == -119


def test_old_trail_files_are_pruned_on_write(tmp_path):
    old = price_trail_path("2026-09-01", root=tmp_path)
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps({"k": "x", "t": 1, "p": -110}) + "\n", encoding="utf-8")
    keep = price_trail_path("2026-09-13", root=tmp_path)
    keep.write_text(json.dumps({"k": "x", "t": 1, "p": -110}) + "\n", encoding="utf-8")
    report = _record(tmp_path, [_row(price=-115)], 0)
    assert report["files_pruned"] == 1
    assert not old.exists() and keep.exists()


def test_off_switch(monkeypatch):
    monkeypatch.delenv("SYNDICATE_CLV_PRICE_TRAIL", raising=False)
    assert trail_mod.price_trail_enabled() is True
    monkeypatch.setenv("SYNDICATE_CLV_PRICE_TRAIL", "off")
    assert trail_mod.price_trail_enabled() is False


# ---------------------------------------------------------------------------
# The series: the label's own price pair, from our publish to now.
# ---------------------------------------------------------------------------


def test_the_ends_of_the_series_are_the_labels_pair():
    """-117 -> -131 shortened: toward the pick, so the line RISES."""
    out = price_move_series((), line=4.5, price_from=-117, price_to=-131, opened_epoch=E0, now_epoch=E0 + 3600)
    assert out["movement_series"] == [[0, _bp(-117)], [60, _bp(-131)]]
    assert out["movement_series"][-1][1] > out["movement_series"][0][1]
    assert out["movement_series_start"] == "2026-09-15T12:00:00Z"
    assert out["movement_series_basis"] == "best_price"


def test_a_lengthening_price_falls_even_when_the_market_consensus_rose():
    """The first design plotted fair probability and drew exactly this row
    rising beside a red arrow (Yandy Diaz over 1.5, 18:08:02Z)."""
    out = price_move_series((), line=1.5, price_from=-120, price_to=100, opened_epoch=E0, now_epoch=E0 + 600)
    assert out["movement_series"][-1][1] < out["movement_series"][0][1]


def test_trail_points_between_are_time_placed_and_line_filtered():
    points = [
        (E0 - 600, 6.5, -140.0, "dk"),     # before our publish: excluded
        (E0 + 1200, 6.5, -125.0, "dk"),    # between: included
        (E0 + 1800, 7.5, -300.0, "dk"),    # a different line: excluded
        (E0 + 99999, 6.5, -500.0, "dk"),   # after now: excluded
    ]
    out = price_move_series(points, line=6.5, price_from=-110, price_to=-130, opened_epoch=E0, now_epoch=E0 + 3600)
    assert out["movement_series"] == [[0, _bp(-110)], [20, _bp(-125)], [60, _bp(-130)]]


def test_a_same_book_pair_uses_only_that_books_points():
    points = [(E0 + 600, 6.5, -125.0, "kalshi"), (E0 + 900, 6.5, 150.0, "betmgm")]
    out = price_move_series(points, line=6.5, price_from=-110, price_to=-130, opened_epoch=E0,
                            now_epoch=E0 + 3600, book="kalshi")
    assert [v for _, v in out["movement_series"]] == [_bp(-110), _bp(-125), _bp(-130)]
    assert out["movement_series_basis"] == "same_book"


def test_across_even_money_the_series_is_continuous():
    """-104 -> +104 is a ~2-point probability move, not a 208-point jump."""
    out = price_move_series((), line=None, price_from=-104, price_to=104, opened_epoch=E0, now_epoch=E0 + 600)
    values = [v for _, v in out["movement_series"]]
    assert 0 < values[0] - values[1] < 300


def test_an_unchanged_price_with_no_wiggle_draws_nothing():
    assert price_move_series((), line=6.5, price_from=-110, price_to=-110, opened_epoch=E0, now_epoch=E0 + 600) is None


def test_an_unchanged_price_that_moved_and_came_back_draws_the_round_trip():
    points = [(E0 + 300, 6.5, -130.0, "dk")]
    out = price_move_series(points, line=6.5, price_from=-110, price_to=-110, opened_epoch=E0, now_epoch=E0 + 600)
    assert [v for _, v in out["movement_series"]] == [_bp(-110), _bp(-130), _bp(-110)]


def test_no_opening_time_or_price_means_no_series():
    assert price_move_series((), line=6.5, price_from=None, price_to=-110, opened_epoch=E0, now_epoch=E0 + 60) is None
    assert price_move_series((), line=6.5, price_from=-120, price_to=-110, opened_epoch=None, now_epoch=E0 + 60) is None


def test_a_long_trail_is_downsampled_keeping_both_ends(monkeypatch):
    monkeypatch.setattr(trail_mod, "_SERIES_MAX_POINTS", 4)
    points = [(E0 + 60 * i, 6.5, -110.0 - i, "dk") for i in range(1, 30)]
    out = price_move_series(points, line=6.5, price_from=-110, price_to=-150, opened_epoch=E0, now_epoch=E0 + 3600)
    assert len(out["movement_series"]) == 4
    assert out["movement_series"][0] == [0, _bp(-110)] and out["movement_series"][-1] == [60, _bp(-150)]
