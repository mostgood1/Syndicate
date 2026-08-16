"""Each published recommendation carries its own `clv_pct`, joined by identity.

An opening IS a published recommendation -- same key -- so this is a join, not a
new computation. The number existed already; it was only reachable on an ops
diagnostic endpoint.

Coverage is asserted as hard as the values are: measured 2026-08-15, most
published rows have no recorded opening (the ledger is first-sighting-only and
odds history is thin), so partial coverage is normal. An unstated 12% is what
gets quoted as 100%.
"""
from __future__ import annotations

from syndicate.features.shared.clv_join import attach_clv_to_rows
from syndicate.features.shared.clv_opening_ledger import _opening_key


def _row(**over):
    row = {
        "event_id": "evt1", "market": "h2h", "player_name": None,
        "segment": "full", "side": "away", "line": None, "bookmaker": "fanduel",
        "sport": "mlb", "model_edge_pct": 6.35,
    }
    row.update(over)
    return row


def _report_for(rows, **fields):
    """A joiner report keyed exactly as `_opening_key` keys the rows."""
    out = []
    for r, extra in rows:
        base = {"key": _opening_key(r), "clv_pct": 1.5, "beat_close": True,
                "open_price": -110, "close_price": -130,
                "close_source": "last_pregame_quote", "close_book_scope": "same_book",
                "close_timing": "pregame", "matched_bookmaker": "fanduel"}
        base.update(extra)
        out.append(base)
    return {"rows": out, **fields}


def test_a_matching_row_gets_its_own_clv():
    row = _row()
    res = attach_clv_to_rows([row], "2026-08-15", "mlb", report=_report_for([(row, {})]))
    assert res["rows"][0]["clv"]["clv_pct"] == 1.5
    assert res["rows"][0]["clv"]["beat_close"] is True
    assert res["coverage"]["with_clv"] == 1


def test_provenance_travels_with_the_number():
    """A same-book pregame CLV is not comparable to a book-agnostic in-play one."""
    row = _row()
    res = attach_clv_to_rows([row], "2026-08-15", "mlb", report=_report_for(
        [(row, {"close_book_scope": "book_agnostic_close", "close_timing": "in_play"})]))
    clv = res["rows"][0]["clv"]
    assert clv["close_book_scope"] == "book_agnostic_close"
    assert clv["close_timing"] == "in_play"
    assert clv["close_source"] == "last_pregame_quote"


def test_an_unmatched_row_is_left_alone_and_counted():
    matched, unmatched = _row(), _row(event_id="evt2")
    res = attach_clv_to_rows([matched, unmatched], "2026-08-15", "mlb",
                             report=_report_for([(matched, {})]))
    assert "clv" in res["rows"][0]
    assert "clv" not in res["rows"][1], "no CLV is absent, never a zero"
    assert res["coverage"] == {"rows": 2, "with_clv": 1, "unmatched": 1,
                               "openings_joined": 1, "date": "2026-08-15", "sport": "mlb"}


def test_the_join_is_by_full_identity_not_by_event():
    """side/line/book are part of the key -- home -1.5 is not away +1.5."""
    home = _row(side="home", market="spreads", line=-1.5)
    away = _row(side="away", market="spreads", line=1.5)
    res = attach_clv_to_rows([home, away], "2026-08-15", "mlb",
                             report=_report_for([(home, {"clv_pct": 9.9})]))
    assert res["rows"][0]["clv"]["clv_pct"] == 9.9
    assert "clv" not in res["rows"][1]


def test_input_rows_are_not_mutated():
    row = _row()
    attach_clv_to_rows([row], "2026-08-15", "mlb", report=_report_for([(row, {})]))
    assert "clv" not in row


def test_zero_coverage_is_reported_not_hidden():
    row = _row()
    res = attach_clv_to_rows([row], "2026-08-15", "mlb", report={"rows": []})
    assert res["coverage"]["with_clv"] == 0
    assert res["coverage"]["unmatched"] == 1
    assert "clv" not in res["rows"][0]


def test_a_failing_joiner_degrades_the_rows_instead_of_failing_the_board():
    import syndicate.features.shared.clv_join as mod
    original = mod.compute_clv_for_date
    mod.compute_clv_for_date = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("artifact gone"))
    try:
        res = attach_clv_to_rows([_row()], "2026-08-15", "mlb")
    finally:
        mod.compute_clv_for_date = original
    assert res["rows"] and "clv" not in res["rows"][0]
    assert "RuntimeError" in res["coverage"]["error"]
    assert res["coverage"]["with_clv"] == 0


def test_non_mapping_rows_are_skipped():
    res = attach_clv_to_rows([_row(), "junk", None], "2026-08-15", "mlb", report={"rows": []})
    assert res["coverage"]["rows"] == 1
