"""The opening half of CLV must be recorded once, completely, and never rewritten.

Lane `clv-without-settlement`, audit §7 ranked fix #1.

Context these tests are defending, measured 2026-08-14: closes are recoverable
for ~100% of markets (`history_points > 0` on 1074/1074 mlb markets) while
openings are readable for **none** — the only store that has them is
`evaluation_ledger_chunks`, whose 2026-08-05 chunk is 367,229,260 bytes and is
SKIPPED at read time against a 256 MB ceiling. Unrecorded is unrecoverable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from syndicate.features.shared.clv_opening_ledger import (
    load_openings,
    opening_ledger_path,
    record_openings,
)

_NOW = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 8, 14, 23, 30, tzinfo=timezone.utc)


def _row(**over):
    row = {
        "sport": "mlb",
        "event_id": "f1e49b28e98e693eaa5d5a27c58ece19",
        "market": "spreads",
        "side": "home",
        "line": 1.5,
        "commence_time": "2026-08-14T23:11:00Z",
        "home_team": "Tampa Bay Rays",
        "away_team": "Baltimore Orioles",
        "model_edge_pct": 2.4,
        "ev_pct": 3.1,
        "quote": {
            "price": 155,
            "bookmaker": "betopenly",
            "books_quoting": 10,
            "fair_probability": 0.411086575093516,
            "fair_method": "consensus",
        },
    }
    quote_over = over.pop("quote", None)
    row.update(over)
    if quote_over:
        row["quote"] = {**row["quote"], **quote_over}
    return row


def test_the_first_price_is_recorded(tmp_path):
    report = record_openings([_row()], date="2026-08-14", now=_NOW, root=tmp_path)
    assert report["openings_written"] == 1
    records = load_openings("2026-08-14", root=tmp_path)
    assert len(records) == 1
    assert records[0]["price"] == 155
    assert records[0]["bookmaker"] == "betopenly"
    assert records[0]["captured_at"] == "2026-08-14T19:00:00Z"


def test_a_later_price_for_the_same_market_never_overwrites_the_opening(tmp_path):
    """The whole contract. An opening that moves is not an opening."""
    record_openings([_row()], date="2026-08-14", now=_NOW, root=tmp_path)
    moved = _row(quote={"price": 120})
    report = record_openings([moved], date="2026-08-14", now=_LATER, root=tmp_path)

    assert report["openings_written"] == 0
    assert report["already_recorded"] == 1
    records = load_openings("2026-08-14", root=tmp_path)
    assert len(records) == 1
    assert records[0]["price"] == 155, "the 19:00 opening was overwritten by a 23:30 price"


def test_side_and_line_are_part_of_the_identity(tmp_path):
    """home -1.5 and home -2.5 are different bets at the same book."""
    rows = [
        _row(side="home", line=1.5),
        _row(side="away", line=1.5),
        _row(side="home", line=2.5),
    ]
    report = record_openings(rows, date="2026-08-14", now=_NOW, root=tmp_path)
    assert report["openings_written"] == 3, "a lossy key collapsed distinct bets"


def test_the_same_market_at_a_different_book_is_a_different_opening(tmp_path):
    rows = [_row(), _row(quote={"bookmaker": "fanduel", "price": 149})]
    report = record_openings(rows, date="2026-08-14", now=_NOW, root=tmp_path)
    assert report["openings_written"] == 2


def test_a_row_with_no_identity_is_skipped_not_written(tmp_path):
    rows = [_row(event_id=""), _row(market=""), _row()]
    report = record_openings(rows, date="2026-08-14", now=_NOW, root=tmp_path)
    assert report["unkeyable_rows"] == 2
    assert report["openings_written"] == 1


def test_duplicates_inside_one_batch_are_written_once(tmp_path):
    report = record_openings([_row(), _row(), _row()], date="2026-08-14", now=_NOW, root=tmp_path)
    assert report["openings_written"] == 1
    assert report["duplicate_in_batch"] == 2


def test_the_report_is_returned_even_when_nothing_is_new(tmp_path):
    # A zero has to be readable, or "already recorded" cannot be told from
    # "never ran". This module's own docstring pays for that lesson.
    record_openings([_row()], date="2026-08-14", now=_NOW, root=tmp_path)
    report = record_openings([_row()], date="2026-08-14", now=_LATER, root=tmp_path)
    assert report["rows_in"] == 1
    assert report["openings_written"] == 0
    assert report["total_openings"] == 1


def test_each_date_is_its_own_file(tmp_path):
    record_openings([_row()], date="2026-08-14", now=_NOW, root=tmp_path)
    record_openings([_row()], date="2026-08-15", now=_NOW, root=tmp_path)
    assert len(load_openings("2026-08-14", root=tmp_path)) == 1
    assert len(load_openings("2026-08-15", root=tmp_path)) == 1


def test_load_is_empty_and_does_not_raise_for_a_date_never_recorded(tmp_path):
    assert load_openings("2026-01-01", root=tmp_path) == []


def test_a_malformed_line_does_not_take_the_file_down(tmp_path):
    record_openings([_row()], date="2026-08-14", now=_NOW, root=tmp_path)
    path = opening_ledger_path("2026-08-14", root=tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    assert len(load_openings("2026-08-14", root=tmp_path)) == 1


def test_the_file_stays_small_across_many_ticks(tmp_path):
    """Bounded by distinct markets, not by ticks -- the 367 MB failure mode."""
    rows = [_row(event_id=f"evt{i}") for i in range(200)]
    for _ in range(50):
        record_openings(rows, date="2026-08-14", now=_NOW, root=tmp_path)
    path = opening_ledger_path("2026-08-14", root=tmp_path)
    assert len(load_openings("2026-08-14", root=tmp_path)) == 200
    assert path.stat().st_size < 200 * 1024, f"50 ticks grew the file to {path.stat().st_size} bytes"


def test_the_recorded_shape_carries_what_a_join_will_need(tmp_path):
    record_openings([_row()], date="2026-08-14", now=_NOW, root=tmp_path)
    rec = load_openings("2026-08-14", root=tmp_path)[0]
    for field in ("event_id", "market", "side", "line", "bookmaker", "price",
                  "commence_time", "home_team", "away_team", "sport"):
        assert rec.get(field) is not None, f"{field} missing; the join can never be built"
    assert json.dumps(rec)  # serialisable


def test_the_shortlist_build_records_openings_and_never_raises(tmp_path, monkeypatch):
    """The wiring, not just the module.

    A recorder nobody calls records nothing, and both the heavy path and
    `_refresh_layer2_shortlist_only` reach the board through this one function.
    """
    import pipeline.layer2_shortlist as mod
    from syndicate.features.shared import clv_opening_ledger

    monkeypatch.setattr(
        clv_opening_ledger, "opening_ledger_path",
        lambda date, root=None: tmp_path / f"{date}.jsonl",
    )
    captured = {}
    real = clv_opening_ledger.record_openings

    def spy(rows, **kw):
        captured["rows"] = list(rows)
        captured["date"] = kw.get("date")
        return real(rows, **kw)

    monkeypatch.setattr(clv_opening_ledger, "record_openings", spy)
    monkeypatch.setattr(mod, "build_layer2_shortlist", mod.build_layer2_shortlist)

    out = mod.build_layer2_shortlist("2026-08-14", [])
    # No sports -> no rows, but the recorder must still have been invoked and
    # must have reported a zero rather than staying silent.
    assert "clv_openings" in out, f"recorder not wired; keys={sorted(out)[:12]}"
    assert out["clv_openings"]["rows_in"] == 0
    assert captured.get("date") == "2026-08-14"


def test_a_recorder_failure_does_not_take_the_board_down(tmp_path, monkeypatch):
    import pipeline.layer2_shortlist as mod
    from syndicate.features.shared import clv_opening_ledger

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(clv_opening_ledger, "record_openings", boom)
    out = mod.build_layer2_shortlist("2026-08-14", [])
    assert "clv_openings_error" in out
    assert "disk on fire" in out["clv_openings_error"]
    assert "rows" in out, "the board payload was lost to an instrumentation failure"


def test_two_players_on_the_same_market_are_two_openings(tmp_path):
    """The exact production collision, 2026-08-14.

    Four distinct batters shared
    `batter_total_bases|over|1.5|betrivers` at 165/165/155/130. A key without
    `player_name` kept ONE of them and attributed its price to all four.
    """
    rows = [
        _row(market="batter_total_bases", line=1.5, player_name="Masataka Yoshida",
             quote={"price": 165, "bookmaker": "betrivers"}),
        _row(market="batter_total_bases", line=1.5, player_name="Jung Hoo Lee",
             quote={"price": 155, "bookmaker": "betrivers"}),
        _row(market="batter_total_bases", line=1.5, player_name="Bryan Reynolds",
             quote={"price": 130, "bookmaker": "betrivers"}),
    ]
    report = record_openings(rows, date="2026-08-14", now=_NOW, root=tmp_path)
    assert report["openings_written"] == 3, "the key collapsed three players onto one"
    prices = sorted(r["price"] for r in load_openings("2026-08-14", root=tmp_path))
    assert prices == [130, 155, 165]


def test_a_first_half_line_is_not_the_full_game_line(tmp_path):
    rows = [_row(segment="full"), _row(segment="1h")]
    assert record_openings(rows, date="2026-08-14", now=_NOW, root=tmp_path)["openings_written"] == 2


def test_the_player_is_recorded_as_a_field_not_only_inside_the_key(tmp_path):
    record_openings([_row(player_name="Jung Hoo Lee", segment="full")],
                    date="2026-08-14", now=_NOW, root=tmp_path)
    rec = load_openings("2026-08-14", root=tmp_path)[0]
    assert rec["player_name"] == "Jung Hoo Lee"
    assert rec["segment"] == "full"
