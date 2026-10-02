"""Rebuilding the live record from the venues' settlement history.

What must hold, because this writes a money record: one graded row per market
and never two (a two-sided market would be un-graded by `repair_multi_side_grades`
and could never re-grade); nothing a re-run or an existing live row would
duplicate; `apply` only with the dry run's exact count; and a normal settlement
tick leaves the rebuilt rows exactly as written.
"""

from __future__ import annotations

import copy
import json

import pytest

import syndicate.features.shared.execution_ledger as led
from syndicate.features.shared import venue_ledger_rebuild as vr
from syndicate.features.shared import venue_settlement as vs

NOW = "2026-10-02T18:00:00Z"


def _k(ticker="KXNFLGAME-26SEP21-NE", **over):
    row = {
        "ticker": ticker, "market_result": "yes", "yes_count_fp": "10.00", "no_count_fp": "0.00",
        "yes_total_cost_dollars": "5.4000", "no_total_cost_dollars": "0.0000", "revenue": 1000,
        "fee_cost": "0.3400", "settled_time": "2026-09-22T03:10:00Z",
    }
    row.update(over)
    return row


def _p(slug="aec-mlb-tex-cws-2026-09-20", before=3.0, after=-6.6, side="POSITION_RESOLUTION_SIDE_LONG", trade="t1",
       cost="9.6000", qty="16"):
    position = {"realized": {"value": str(before)}}
    if cost is not None:
        position.update(cost={"value": cost, "currency": "USD"}, qtyBought=qty)
    return {
        "marketSlug": slug, "side": side, "tradeId": trade, "updateTime": "2026-09-21T02:00:00Z",
        "beforePosition": position, "afterPosition": {"realized": {"value": str(after)}},
    }


def test_a_kalshi_settlement_becomes_one_graded_live_row():
    row, reason = vr.kalshi_row(_k(), NOW)
    assert reason is None
    assert row["mode"] == "live" and row["status"] == "filled" and row["source"] == "venue_rebuild"
    assert (row["outcome"], row["pnl_dollars"]) == ("won", pytest.approx(4.26))
    assert row["selected_date"] == "2026-09-21" and row["selected_date_source"] == "ticker"
    # Probability dollars -- the unit profit_per_dollar reads for a contract.
    assert row["fill_price"] == pytest.approx(0.54) and row["fill_stake_dollars"] == pytest.approx(5.4)
    assert row["settled_by"] == "venue" and row["held_side"] == "yes"
    assert row["idempotency_key"] == "venue_rebuild:kalshi:kxnflgame-26sep21-ne:yes"


def test_a_polymarket_resolution_becomes_a_row_and_zero_delta_is_refused():
    row, reason = vr.polymarket_row(_p(), NOW)
    assert reason is None
    assert (row["outcome"], row["pnl_dollars"]) == ("lost", pytest.approx(-9.6))
    assert (row["selected_date"], row["sport"], row["side"]) == ("2026-09-20", "mlb", "long")
    # The position's own cost basis: $9.60 for 16 shares -> 0.60 a share.
    assert (row["fill_stake_dollars"], row["fill_price"]) == (pytest.approx(9.6), pytest.approx(0.6))
    assert vr.polymarket_row(_p(before=3.0, after=3.0), NOW) == (None, "zero_realized_delta")


def test_no_polymarket_cost_basis_is_invented_and_a_non_probability_price_is_dropped():
    no_cost, _ = vr.polymarket_row(_p(cost=None), NOW)
    assert (no_cost["fill_stake_dollars"], no_cost["fill_price"]) == (None, None)
    odd, _ = vr.polymarket_row(_p(cost="9.6", qty="4"), NOW)  # 2.40 a share is not a probability
    assert (odd["fill_stake_dollars"], odd["fill_price"]) == (pytest.approx(9.6), None)


@pytest.mark.parametrize("slug,sport,league", [
    ("aec-epl-ars-che-2026-09-20", "soccer", "epl"),
    ("asc-cfb-bama-lsu-2026-09-20", "ncaaf", "cfb"),
    ("aec-wnba-lv-ny-2026-09-20", "wnba", "wnba"),
])
def test_polymarket_league_codes_map_to_sports(slug, sport, league):
    row, _ = vr.polymarket_row(_p(slug=slug), NOW)
    assert (row["sport"], row["league"]) == (sport, league)


def test_build_skips_existing_markets_merges_same_side_and_refuses_two_sided():
    existing = [{"mode": "live", "venue": "kalshi", "venue_ticker": "KXHELD-26SEP20-A", "idempotency_key": "x"}]
    built = vr.build_rows(
        [_k(), _k("KXHELD-26SEP20-A"), _k("KXNONE-26SEP20-B", yes_count_fp="0")],
        [_p(), _p(slug="aec-nfl-a-b-2026-09-21", before=0, after=2.0, trade="a"),
         _p(slug="aec-nfl-a-b-2026-09-21", before=2.0, after=5.0, trade="b"),
         _p(slug="aec-nhl-c-d-2026-09-22", before=0, after=1.0, trade="c"),
         _p(slug="aec-nhl-c-d-2026-09-22", before=0, after=-1.0, side="POSITION_RESOLUTION_SIDE_SHORT", trade="d")],
        existing, now=NOW,
    )
    rows = built["rows"]
    tickers = sorted(r["venue_ticker"] for r in rows)
    assert tickers == ["KXNFLGAME-26SEP21-NE", "aec-mlb-tex-cws-2026-09-20", "aec-nfl-a-b-2026-09-21"]
    merged = next(r for r in rows if r["venue_ticker"] == "aec-nfl-a-b-2026-09-21")
    assert (merged["pnl_dollars"], merged["outcome"], merged["merged_settlements"]) == (pytest.approx(5.0), "won", 2)
    assert built["skipped"] == {
        "kalshi:already_in_ledger": 1, "kalshi:no_position_held": 1,
        "polymarket:merged_into_one": 1, "polymarket:multi_side_market": 2,
    }
    # One row per market, always.
    assert len({(r["venue"], r["venue_ticker"]) for r in rows}) == len(rows)


def test_a_rerun_over_its_own_output_adds_nothing():
    first = vr.build_rows([_k()], [_p()], [], now=NOW)["rows"]
    again = vr.build_rows([_k()], [_p()], first, now=NOW)
    assert again["rows"] == [] and again["skipped"] == {"kalshi:already_in_ledger": 1, "polymarket:already_in_ledger": 1}


@pytest.fixture()
def ledger(monkeypatch):
    state = {"orders": [{"mode": "paper", "venue": "paper", "idempotency_key": "p1", "selected_date": "2026-10-02"}]}
    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([_k()], None))
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([_p()], None))
    return state


def _fetch():
    return {"kalshi": lambda: ([_k()], None), "polymarket": lambda: ([_p()], None)}


def test_dry_run_writes_nothing_and_apply_needs_the_exact_count(ledger):
    dry = vr.rebuild(dry_run=True, fetch=_fetch())
    assert dry["status"] == "ok" and dry["summary"]["rows"] == 2 and len(ledger["orders"]) == 1
    assert vr.rebuild(dry_run=False, expect_rows=3, fetch=_fetch())["status"] == "refused_count_mismatch"
    assert vr.rebuild(dry_run=False, expect_rows=None, fetch=_fetch())["status"] == "refused_count_mismatch"
    assert len(ledger["orders"]) == 1
    done = vr.rebuild(dry_run=False, expect_rows=2, fetch=_fetch())
    assert done["status"] == "ok" and done["written"] == 2 and len(ledger["orders"]) == 3


def test_a_fetch_error_refuses_rather_than_rebuilding_half(ledger):
    fetch = {"kalshi": lambda: ([_k()], None), "polymarket": lambda: ([], "http_503")}
    assert vr.rebuild(dry_run=False, expect_rows=1, fetch=fetch)["status"] == "refused_fetch_error"
    assert len(ledger["orders"]) == 1


def test_settlement_tick_and_its_repairs_leave_rebuilt_rows_untouched(ledger):
    """The rows must be STABLE under the code that runs every tick: graded rows
    are skipped (`already`), and none of the three repairs may clear them."""
    vr.rebuild(dry_run=False, expect_rows=2, fetch=_fetch())
    before = copy.deepcopy([o for o in ledger["orders"] if o.get("source") == "venue_rebuild"])
    result = vs.settle_from_venue()
    after = [o for o in ledger["orders"] if o.get("source") == "venue_rebuild"]
    assert result["status"] == "ok" and result["settled"] == 0 and result["already"] == 2
    assert not any(k in result for k in ("repaired", "repaired_pushes", "repaired_pnl"))
    assert after == before


def test_rebuilt_rows_never_count_against_todays_live_spend(ledger):
    from syndicate.features.shared.execution_guard import spent_today

    vr.rebuild(dry_run=False, expect_rows=2, fetch=_fetch())
    assert spent_today("2026-10-02") == {"dollars": 0.0, "orders": 0}
    # Positive control: the reader DOES see a rebuilt row on its own slate date,
    # so the zero above is about the date, not a reader that sees nothing.
    assert spent_today("2026-09-21")["orders"] == 1


def test_the_live_book_and_ledger_summary_render_rebuilt_rows(ledger):
    """Rebuilt rows carry no market/line/plan. The readers that show the live
    book must render them, not raise on the Nones."""
    from syndicate.app import app
    from syndicate.blueprints.intelligence import _live_portfolio_payload
    from syndicate.features.shared.execution_ledger import ledger_summary

    vr.rebuild(dry_run=False, expect_rows=2, fetch=_fetch())
    assert ledger_summary() is not None
    assert ledger_summary("2026-09-21") is not None
    with app.test_request_context("/portfolio?on=all"):
        payload = _live_portfolio_payload("2026-10-02", show_all=True, on_date="all")
    assert isinstance(payload, dict)
    text = json.dumps(payload, default=str)
    assert "KXNFLGAME-26SEP21-NE" in text and "aec-mlb-tex-cws-2026-09-20" in text


def test_request_file_runs_once_and_writes_a_result(tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(vr, "rebuild", lambda **kw: {"status": "ok", "mode": "dry_run", "summary": {"rows": 2}})
    (tmp_path / vr.REQUEST_NAME).write_text(json.dumps({"mode": "dry_run"}), encoding="utf-8")
    result = vr.process_rebuild_request(tmp_path)
    assert result["status"] == "ok"
    assert json.loads((tmp_path / vr.RESULT_NAME).read_text(encoding="utf-8"))["request"] == {"mode": "dry_run"}
    assert not (tmp_path / vr.REQUEST_NAME).exists() and (tmp_path / (vr.REQUEST_NAME + ".done")).exists()
    assert vr.process_rebuild_request(tmp_path) is None  # nothing waiting: a no-op
