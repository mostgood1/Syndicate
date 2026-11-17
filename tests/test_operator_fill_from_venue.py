"""`operator_fill_from_venue`: a live order the venue GRADED before any reconcile pass saw it fill.

[2026-11-17, lane stuck-kalshi-fill-repair] Key `f8b62e6a` (an in-play IOC for 4 NO, 2026-11-14 05:55:45Z)
filled at once, was graded `lost` by venue settlement four minutes later, and then sat `submitted` for
three days, because `reconcile_live_orders` only takes rows whose outcome is None. These pin that the
operator path writes exactly the reconciled fill, leaves the grade alone, keeps what it overwrote, and
refuses everything that is not this case.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import execution_ledger as ledger  # noqa: E402
from syndicate.features.shared.execution_ledger import (  # noqa: E402
    LIVE,
    PAPER,
    STATUS_FILLED,
    STATUS_SUBMITTED,
    OperatorResolutionError,
)

KEY = "f8b62e6ad863263bf537d607"
VENUE_ID = "01a1d8a0-46e8-793d-adf0-7bae673a159f"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    ledger._ARCHIVE_PARSE_CACHE.clear()
    yield
    ledger._ARCHIVE_PARSE_CACHE.clear()


def _stuck(**over):
    """The row as it stood on the fleet, 2026-11-17."""
    row = {
        "idempotency_key": KEY, "mode": LIVE, "venue": "kalshi", "status": STATUS_SUBMITTED,
        "selected_date": "2026-11-13", "venue_ticker": "KXNHLGAME-26NOV13NSHVGK-NSH", "side": "no",
        "venue_order_id": VENUE_ID, "requested_price": 0.62, "requested_stake_dollars": 2.5201,
        "fill_price": None, "fill_stake_dollars": 0.0, "contracts": None, "fees_dollars": 0.069,
        "outcome": "lost", "pnl_dollars": -1.829, "settled_by": "venue",
        "settled_at": "2026-11-14T05:55:45.462260Z", "settled_at_venue": "2026-11-14T05:59:19.622834Z",
        "graded_at": "2026-11-14T06:01:52.124864Z", "reconciled_at": None, "venue_status": None,
    }
    row.update(over)
    return row


# The reconciler's normalized view of Kalshi's per-order read for this order, as read on the fleet.
SEEN = {
    "client_order_id": KEY, "order_id": VENUE_ID, "ticker": "KXNHLGAME-26NOV13NSHVGK-NSH", "state": "filled",
    "venue_status": "executed", "filled_count": 4, "remaining_count": 0.0, "open_at_venue": False,
    "fill_price": 0.44, "fill_cost_dollars": 1.76, "fees_dollars": 0.069, "taker_fill_cost_dollars": 1.76,
    "maker_fill_cost_dollars": 0.0, "yes_price": 0.38, "no_price": 0.62,
}
NOTE = "graded by venue settlement before reconcile saw the IOC fill; Kalshi per-order read 2026-11-17"


def _row(key=KEY):
    return next(o for o in ledger._load()["orders"] if o["idempotency_key"] == key)


def test_the_fill_is_recorded_and_the_grade_is_left_alone(capsys):
    ledger._persist({"orders": [_stuck()]})
    ledger.operator_fill_from_venue(KEY, seen=SEEN, note=NOTE)
    row = _row()
    assert row["status"] == STATUS_FILLED and row["contracts"] == 4
    assert row["fill_price"] == 0.44 and row["fill_stake_dollars"] == 1.76 and row["fees_dollars"] == 0.069
    assert row["venue_status"] == "executed" and row["venue_open"] is False and row["venue_remaining_count"] == 0.0
    assert row["reconciled_from"] == STATUS_SUBMITTED and row["reconciled_at"]
    # The grade is the venue's and stays exactly as it was.
    assert (row["outcome"], row["pnl_dollars"], row["settled_by"]) == ("lost", -1.829, "venue")
    assert row["settled_at_venue"] == "2026-11-14T05:59:19.622834Z"
    # The money adds up: fill cost + fee is the graded loss.
    assert round(row["fill_stake_dollars"] + row["fees_dollars"], 3) == -row["pnl_dollars"]
    # What it overwrote, and why, are kept on the row.
    assert row["pre_operator_fill"]["status"] == STATUS_SUBMITTED and row["pre_operator_fill"]["contracts"] is None
    assert row["operator_fill"]["note"] == NOTE and row["operator_fill"]["evidence"]["filled_count"] == 4
    assert "[execution_ledger] OPERATOR_FILL key=" + KEY in capsys.readouterr().out


def test_the_repaired_row_is_no_longer_unreconcilable(capsys):
    ledger._persist({"orders": [_stuck()]})
    ledger.unreconciled_orders()
    assert "UNRECONCILABLE_ORDER" in capsys.readouterr().out
    ledger.operator_fill_from_venue(KEY, seen=SEEN, note=NOTE)
    capsys.readouterr()
    assert ledger.unreconciled_orders() == []
    assert "UNRECONCILABLE_ORDER" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "row_over, seen_over, note, reason",
    [
        ({}, {}, "", "note_required"),
        ({"mode": PAPER}, {}, NOTE, "not_live"),
        ({"venue": "polymarket"}, {}, NOTE, "venue_mismatch"),
        ({"status": STATUS_FILLED}, {}, NOTE, "not_submitted"),
        ({"outcome": None, "pnl_dollars": None}, {}, NOTE, "not_graded"),
        ({}, {"client_order_id": "someone-else", "order_id": "another-id"}, NOTE, "identity_mismatch"),
        ({}, {"state": "dead"}, NOTE, "not_filled_at_venue"),
        ({}, {"filled_count": 0}, NOTE, "no_filled_contracts"),
        ({}, {"fill_cost_dollars": 400.0}, NOTE, "absurd_fill"),
    ],
)
def test_it_refuses_everything_that_is_not_this_case(row_over, seen_over, note, reason):
    ledger._persist({"orders": [_stuck(**row_over)]})
    with pytest.raises(OperatorResolutionError, match=reason):
        ledger.operator_fill_from_venue(KEY, seen={**SEEN, **seen_over}, note=note)
    row = _row()
    assert "operator_fill" not in row and row["status"] == _stuck(**row_over)["status"]


def test_an_unknown_key_is_refused():
    ledger._persist({"orders": [_stuck()]})
    with pytest.raises(OperatorResolutionError, match="order_not_found"):
        ledger.operator_fill_from_venue("nope", seen=SEEN, note=NOTE)
