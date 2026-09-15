"""The Layer 2 price trail (lane `layer2-row-parity`).

What each test pins is a defect measured on the served board 2026-09-15, in the
sparklines that existed before this trail:

    wrong side    MLB unders plotted the OVER price
    wrong line    6 of 58 series drew a line change as a price move
    wrong book    one price per side from whichever book came first

plus the two properties that keep a per-build writer affordable on
refresh-worker: change-only appends and a bounded file.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from syndicate.features.shared import clv_price_trail as trail_mod
from syndicate.features.shared.clv_price_trail import (
    load_price_trail,
    price_trail_path,
    price_trail_series,
    record_price_trail,
    row_trail_point,
)

T0 = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
DATE = "2026-09-15"


def _key(row):
    return f"{row['event_id']}|{row['market']}|{row.get('side')}"


def _row(*, price=-110, fair=0.50, line=6.5, book="draftkings", side="over"):
    return {
        "event_id": "e1",
        "market": "strikeouts",
        "side": side,
        "line": line,
        "quote": {"price": price, "bookmaker": book, "fair_probability": fair},
    }


def _record(tmp_path, rows, minutes, trail=None):
    return record_price_trail(
        rows, date=DATE, trail=trail, now=T0 + timedelta(minutes=minutes), root=tmp_path, key_fn=_key
    )


def test_an_unchanged_observation_is_not_appended(tmp_path):
    first = _record(tmp_path, [_row()], 0)
    second = _record(tmp_path, [_row()], 15)
    assert first["points_written"] == 1
    assert second["points_written"] == 0 and second["unchanged"] == 1
    assert len(load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]) == 1


def test_fair_noise_below_the_epsilon_is_not_a_change(tmp_path):
    _record(tmp_path, [_row(fair=0.5000)], 0)
    assert _record(tmp_path, [_row(fair=0.5010)], 15)["points_written"] == 0
    assert _record(tmp_path, [_row(fair=0.5030)], 30)["points_written"] == 1


def test_a_price_or_book_change_is_recorded(tmp_path):
    _record(tmp_path, [_row()], 0)
    assert _record(tmp_path, [_row(price=-120)], 15)["points_written"] == 1
    assert _record(tmp_path, [_row(price=-120, book="fanduel")], 30)["points_written"] == 1


def test_the_series_rises_when_the_market_moves_toward_the_pick(tmp_path):
    """Green = toward the pick (user decision 2026-09-15). Fair 44% -> 47%."""
    _record(tmp_path, [_row(fair=0.44)], 0)
    _record(tmp_path, [_row(fair=0.47)], 30)
    points = load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]
    out = price_trail_series(points, line=6.5, book="draftkings")
    assert out["movement_series_basis"] == "fair"
    assert out["movement_series"] == [[0, 4400], [30, 4700]]
    assert out["movement_series_start"] == "2026-09-15T12:00:00Z"


def test_a_line_move_ends_the_series_rather_than_joining_it(tmp_path):
    """6 of 58 legacy series spanned a line change and drew it as a price move."""
    _record(tmp_path, [_row(line=16.5, fair=0.50)], 0)
    _record(tmp_path, [_row(line=17.5, fair=0.40)], 30)
    _record(tmp_path, [_row(line=17.5, fair=0.43)], 60)
    points = load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]
    out = price_trail_series(points, line=17.5, book="draftkings")
    assert out["movement_series"] == [[0, 4000], [30, 4300]], "only the 17.5 points"
    assert price_trail_series(points, line=16.5, book="draftkings") is None, "one point draws nothing"


def test_price_fallback_is_same_book_and_plots_implied_probability(tmp_path):
    """No fair movement -> ONE book's price. A best-book switch must not draw."""
    _record(tmp_path, [_row(price=-117, fair=None)], 0)
    _record(tmp_path, [_row(price=-131, fair=None)], 20)
    _record(tmp_path, [_row(price=+105, fair=None, book="kalshi")], 40)
    points = load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]
    out = price_trail_series(points, line=6.5, book="draftkings")
    assert out["movement_series_basis"] == "price"
    # -117 -> 53.9%, -131 -> 56.7%: the shortening price RISES.
    assert [v for _, v in out["movement_series"]] == [5392, 5671]
    assert price_trail_series(points, line=6.5, book="kalshi") is None


def test_across_even_money_the_series_is_continuous(tmp_path):
    """-104 -> +104 is a ~2-point probability move, not a 208-point jump."""
    _record(tmp_path, [_row(price=-104, fair=None)], 0)
    _record(tmp_path, [_row(price=104, fair=None)], 10)
    points = load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]
    values = [v for _, v in price_trail_series(points, line=6.5, book="draftkings")["movement_series"]]
    assert values[0] - values[1] < 300


def test_a_flat_series_draws_nothing(tmp_path):
    _record(tmp_path, [_row(fair=0.44)], 0)
    _record(tmp_path, [_row(fair=0.44, price=-115)], 30)
    points = load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]
    assert price_trail_series(points, line=6.5, book="nobody") is None


def test_the_current_build_extends_the_series_to_now(tmp_path):
    _record(tmp_path, [_row(fair=0.44)], 0)
    points = load_price_trail(DATE, root=tmp_path)["e1|strikeouts|over"]
    now_epoch = int((T0 + timedelta(minutes=45)).timestamp())
    current = row_trail_point(_row(fair=0.48), epoch=now_epoch)
    out = price_trail_series(points, line=6.5, book="draftkings", current=current)
    assert out["movement_series"] == [[0, 4400], [45, 4800]]


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
    assert points[0][3] == -110, "the opening-most point survives the trim"
    assert points[-1][3] == -119


def test_old_trail_files_are_pruned_on_write(tmp_path):
    old = price_trail_path("2026-09-01", root=tmp_path)
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps({"k": "x", "t": 1}) + "\n", encoding="utf-8")
    keep = price_trail_path("2026-09-13", root=tmp_path)
    keep.write_text(json.dumps({"k": "x", "t": 1}) + "\n", encoding="utf-8")
    report = _record(tmp_path, [_row()], 0)
    assert report["files_pruned"] == 1
    assert not old.exists() and keep.exists()


def test_off_switch(monkeypatch):
    monkeypatch.delenv("SYNDICATE_CLV_PRICE_TRAIL", raising=False)
    assert trail_mod.price_trail_enabled() is True
    monkeypatch.setenv("SYNDICATE_CLV_PRICE_TRAIL", "off")
    assert trail_mod.price_trail_enabled() is False
