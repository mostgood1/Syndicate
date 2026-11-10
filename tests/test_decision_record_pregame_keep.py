"""The kept pregame lines (Phase 1B M1 slice 2, lane `pregame-record-keep`, 2026-11-10).

The DecisionRecord file keeps only a date's latest build and the board drops a line once its game starts, so the
11-09 file held no NBA line. `keep_pregame_lines` keeps every line's FIRST and LAST pregame record past the start."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

import pytest

from syndicate.features.shared import decision_record as dr

DATE = "2026-11-10"
T0 = datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)


def _row(event="ev1", line=220.5, commence="2026-11-11T00:30:00Z", fair=0.50, model=0.56, side="over", **over):
    row = {
        "sport": "nba", "event_id": event, "kind": "game", "market": "totals", "segment": "full",
        "player_name": None, "side": side, "line": line, "commence_time": commence,
        "home_team": "Home", "away_team": "Away", "game_state": "pregame", "suggested": False,
        "model_probability_cal": model,
        "projection": {"model_prob_over": model, "source": "sim", "basis": "sim_total_dist/full"},
        "quote": {"fair_probability": fair, "fair_devig_method": "shin", "fair_method": "consensus",
                  "books_quoting": 8, "book_age_seconds": 30.0, "bookmaker": "draftkings", "price": -110,
                  "book_prices": {"draftkings": -110}},
    }
    row.update(over)
    return row


def _records(rows):
    ctx = dr.RecordContext(selected_date=DATE)
    ctx.paper_bankroll = 1000.0
    return dr.build_records(rows, ctx)


def _kept(root):
    return {row["k"]: row for row in dr.read_pregame_lines(DATE, root)}


def test_off_writes_nothing_on_writes_the_file(tmp_path):
    recs = _records([_row()])
    off = dr.keep_pregame_lines(DATE, recs, build_id="b1", now=T0, root=tmp_path, env={dr.PREGAME_KEEP_ENV: "off"})
    assert off == {"status": "off"} and not dr.pregame_lines_path(DATE, tmp_path).exists()
    on = dr.keep_pregame_lines(DATE, recs, build_id="b1", now=T0, root=tmp_path, env={})
    assert on["status"] == "ok" and on["added"] == 1 and dr.pregame_lines_path(DATE, tmp_path).exists()


def test_first_then_last_and_a_started_line_is_frozen(tmp_path):
    early = _row(event="early", commence="2026-11-10T17:00:00Z", fair=0.50)
    late = _row(event="late", commence="2026-11-11T02:00:00Z", fair=0.50)
    dr.keep_pregame_lines(DATE, _records([early, late]), build_id="b1", now=T0, root=tmp_path, env={})
    first = _kept(tmp_path)
    assert set(first) == {dr.line_key(early), dr.line_key(late)}
    assert all(r["last"] is None and r["n"] == 1 and r["ft"] == "2026-11-10T16:00:00Z" for r in first.values())

    # 18:00Z: the early game has started; both lines are still on this build's board with moved prices.
    t1 = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
    moved = [_row(event="early", commence="2026-11-10T17:00:00Z", fair=0.40),
             _row(event="late", commence="2026-11-11T02:00:00Z", fair=0.45)]
    s = dr.keep_pregame_lines(DATE, _records(moved), build_id="b2", now=t1, root=tmp_path, env={})
    assert s["started"] == 1 and s["updated"] == 1 and s["kept"] == 1
    kept = _kept(tmp_path)
    e, l = kept[dr.line_key(early)], kept[dr.line_key(late)]
    assert e["last"] is None and e["n"] == 1  # frozen at its pregame sighting, never the in-play price
    assert l["n"] == 2 and l["lt"] == "2026-11-10T18:00:00Z" and l["lb"] == "b2"
    assert l["first"]["market"]["p_market"] == pytest.approx(0.50) and l["last"]["market"]["p_market"] == pytest.approx(0.45)


def test_a_line_the_build_no_longer_lists_is_never_dropped(tmp_path):
    rows = [_row(event=f"e{i}") for i in range(5)]
    dr.keep_pregame_lines(DATE, _records(rows), build_id="b1", now=T0, root=tmp_path, env={})
    for i in range(3):
        dr.keep_pregame_lines(DATE, _records([_row(event="new")]), build_id=f"b{i + 2}", now=T0, root=tmp_path, env={})
    kept = _kept(tmp_path)
    assert len(kept) == 6 and kept[dr.line_key(_row(event="new"))]["n"] == 3


def test_unknown_start_is_not_kept_and_is_counted(tmp_path):
    s = dr.keep_pregame_lines(DATE, _records([_row(commence=None, game_state=None)]), build_id="b1", now=T0,
                              root=tmp_path, env={})
    assert s["unknown_start"] == 1 and s["lines"] == 0


def test_the_slim_record_drops_policy_and_expands_back(tmp_path):
    rec = _records([_row()])[0]
    slim = dr.slim_record(rec)
    assert set(slim) <= set(dr.PREGAME_SLIM_SECTIONS)
    assert not {"gates", "verdicts", "sizes", "contracts"} & set(slim)
    back = dr.expand_record(slim)
    assert back.identity.line_key == rec.identity.line_key
    assert back.market.p_market == pytest.approx(rec.market.p_market)
    assert back.model.p_model == pytest.approx(rec.model.p_model)


def test_a_torn_line_is_skipped_and_counted(tmp_path):
    dr.keep_pregame_lines(DATE, _records([_row(event="a")]), build_id="b1", now=T0, root=tmp_path, env={})
    path = dr.pregame_lines_path(DATE, tmp_path)
    good = gzip.open(path, "rt", encoding="utf-8").read()
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(good + '{"k": "torn')
    s = dr.keep_pregame_lines(DATE, _records([_row(event="b")]), build_id="b2", now=T0, root=tmp_path, env={})
    assert s["torn"] == 1 and s["kept"] == 1 and s["added"] == 1


def test_a_failed_merge_leaves_the_old_file_and_no_temp(tmp_path, monkeypatch):
    dr.keep_pregame_lines(DATE, _records([_row(event="a")]), build_id="b1", now=T0, root=tmp_path, env={})
    path = dr.pregame_lines_path(DATE, tmp_path)
    before = path.read_bytes()

    def boom(rec):
        raise RuntimeError("boom")

    monkeypatch.setattr(dr, "slim_record", boom)
    with pytest.raises(RuntimeError):
        dr.keep_pregame_lines(DATE, _records([_row(event="a")]), build_id="b2", now=T0, root=tmp_path, env={})
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir() if ".tmp" in p.name] == []


def test_run_shadow_keeps_the_pregame_lines(tmp_path, monkeypatch):
    monkeypatch.delenv(dr.MODE_ENV, raising=False)
    monkeypatch.delenv(dr.PREGAME_KEEP_ENV, raising=False)
    row = _row(commence="2099-11-11T00:30:00Z")
    out = dr.run_shadow(DATE, {"rows": [row], "written_at": "t"}, root=tmp_path, plans={}, live_orders=[])
    assert out["status"] == "ok" and out["pregame_keep"]["added"] == 1
    assert dr.line_key(row) in _kept(tmp_path)
    monkeypatch.setenv(dr.PREGAME_KEEP_ENV, "off")
    out = dr.run_shadow(DATE, {"rows": [row], "written_at": "t"}, root=tmp_path, plans={}, live_orders=[])
    assert out["pregame_keep"] == {"status": "off"}


def test_the_kept_file_is_inside_the_export_allowlisted_records_dir(tmp_path):
    from syndicate.features.shared.artifact_publisher import EXPORT_ONLY_ARTIFACT_PATTERNS

    assert "reports/intelligence/decision_records/*" in EXPORT_ONLY_ARTIFACT_PATTERNS
    assert dr.pregame_lines_path(DATE, tmp_path).parent == dr.records_dir(tmp_path)
