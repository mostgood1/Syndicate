"""`/portfolio`'s two red banners needed a way OUT, not just a way in.

`[user 2026-08-28]` "these items need to get resolved - we cant just keep these
as front facing errors."

Both banners were permanent by construction. The venue paid what it paid, so a
grade conflict never re-grades; and no read this system can make settles an
order that failed with no `venue_order_id` -- Polymarket answers `501` on the
orders list and the per-order read needs the id the 503 lost. A warning that
cannot be actioned teaches the reader to ignore it, which is the same defect
this repo already records from the other direction: "a warning that fires on the
system working correctly teaches the reader to ignore the warning".
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as ledger
from syndicate.features.shared.execution_ledger import (
    OperatorResolutionError,
    acknowledge_grade_conflict,
    resolve_unknown_submit,
)


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    yield


def _seed(order):
    state = ledger._load()
    state["orders"] = [order]
    ledger._persist(state)


def _unknown(**kw):
    """The real shape of the 2026-08-27 Polymarket 503s: sent, unanswered, no id."""
    row = {
        "idempotency_key": "unk-1",
        "mode": "live",
        "venue": "polymarket",
        "status": "failed",
        "error": 'PolymarketUSAuthError: http_503: {"code":14}',
        "venue_order_id": None,
        "requested_stake_dollars": 6.22,
        "selected_date": "2026-08-27",
        "venue_ticker": "aec-mlb-kc-tor-2026-08-27",
    }
    row.update(kw)
    return row


def _conflicted(**kw):
    row = {
        "idempotency_key": "gc-1",
        "mode": "live",
        "venue": "polymarket",
        "status": "filled",
        "market": "h2h",
        "outcome": "lost",
        "pnl_dollars": -5.871,
        "settled_by": "venue",
        "selected_date": "2026-08-27",
        "grade_check": {"agrees": False, "venue_outcome": "lost", "our_outcome": "won"},
    }
    row.update(kw)
    return row


def _stored(key="unk-1"):
    return next(o for o in ledger._load()["orders"] if o["idempotency_key"] == key)


# ---------------------------------------------------------------------------
# Unknown submits
# ---------------------------------------------------------------------------


def test_no_position_marks_it_rejected_so_the_budget_AND_the_retry_are_freed():
    """`rejected` is already the status meaning "never reached the venue", so
    `is_non_position` stops charging the day's budget for it AND `record_order`
    will let the position be retried. Freeing the exposure without freeing the
    retry is half a fix -- this module learned that once already."""
    from syndicate.features.shared.execution_guard import is_non_position

    _seed(_unknown())
    assert is_non_position(_stored()) is False

    resolve_unknown_submit("unk-1", "not_placed", note="venue screen empty")

    row = _stored()
    assert row["status"] == "rejected"
    assert is_non_position(row) is True
    assert row["operator_resolution"]["finding"] == "not_placed"
    assert row["operator_resolution"]["note"] == "venue screen empty"


def test_the_original_status_and_error_are_PRESERVED():
    """An operator can be wrong, and a record that overwrites what actually
    happened leaves nothing to reverse."""
    _seed(_unknown())
    resolve_unknown_submit("unk-1", "not_placed")
    row = _stored()
    assert row["pre_resolution_status"] == "failed"
    assert "http_503" in row["pre_resolution_error"]


def test_a_position_finding_keeps_the_exposure_and_only_retires_the_QUESTION():
    """"We do not know" becomes "we know, and it is real". The stake still
    counts; nothing is graded here -- what it settles for is the venue's
    business."""
    _seed(_unknown())
    resolve_unknown_submit("unk-1", "placed")
    row = _stored()
    assert row["status"] == "failed"          # untouched
    assert row["operator_resolution"]["finding"] == "placed"
    assert "pre_resolution_status" not in row


def test_a_resolved_row_leaves_the_unknown_banner():
    from syndicate.blueprints.intelligence import _is_unknown_submit

    row = _unknown()
    assert _is_unknown_submit(row) is True
    row["operator_resolution"] = {"finding": "placed", "at": "now"}
    assert _is_unknown_submit(row) is False


def test_an_unrecognised_finding_is_REFUSED_not_stored():
    """This writes to the money record. "Whatever the caller typed" is not a
    vocabulary."""
    _seed(_unknown())
    for bad in ("maybe", "", None, "PLACED?"):
        with pytest.raises(OperatorResolutionError, match="unknown_finding|no_idempotency"):
            resolve_unknown_submit("unk-1", bad)
    assert "operator_resolution" not in _stored()


def test_a_row_that_got_SETTLED_while_the_operator_looked_is_refused():
    """Their finding is about an open question that is no longer open."""
    _seed(_unknown(outcome="won"))
    with pytest.raises(OperatorResolutionError, match="already_settled"):
        resolve_unknown_submit("unk-1", "not_placed")


def test_an_unknown_key_is_refused_rather_than_silently_doing_nothing():
    _seed(_unknown())
    with pytest.raises(OperatorResolutionError, match="order_not_found"):
        resolve_unknown_submit("no-such-order", "not_placed")


# ---------------------------------------------------------------------------
# Grade conflicts
# ---------------------------------------------------------------------------


def test_acknowledging_changes_NO_money():
    """The dollars are what the venue actually moved. Rewriting them on our own
    reading is exactly what `_check_venue_grade` refuses to do."""
    _seed(_conflicted())
    acknowledge_grade_conflict("gc-1", note="known wrong-side fill")

    row = _stored("gc-1")
    assert row["outcome"] == "lost"
    assert row["pnl_dollars"] == -5.871
    assert row["grade_check"]["acknowledged_at"]
    assert row["grade_check"]["acknowledged_note"] == "known wrong-side fill"
    # The disagreement itself is NOT erased -- it is still a disagreement.
    assert row["grade_check"]["agrees"] is False


def test_an_acknowledged_conflict_leaves_the_RED_banner_but_stays_counted(monkeypatch):
    """A reviewed disagreement stops being news without stopping being true. A
    count that can never fall cannot signal anything."""
    from syndicate.blueprints import intelligence as mod

    _seed(_conflicted())
    payload = mod._live_portfolio_payload("2026-08-27", on_date="all")
    assert len(payload["grade_conflicts"]) == 1
    assert payload["grade_conflicts_acknowledged"] == 0

    acknowledge_grade_conflict("gc-1")

    payload = mod._live_portfolio_payload("2026-08-27", on_date="all")
    assert payload["grade_conflicts"] == []
    assert payload["grade_conflicts_acknowledged"] == 1


def test_acknowledging_a_row_that_is_not_in_conflict_is_refused():
    """Otherwise the field becomes a place to write anything."""
    _seed(_conflicted(grade_check={"agrees": True, "our_outcome": "lost"}))
    with pytest.raises(OperatorResolutionError, match="not_a_grade_conflict"):
        acknowledge_grade_conflict("gc-1")


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


def test_the_routes_apply_the_finding_and_report_a_refusal_visibly(monkeypatch):
    """A 303 that swallowed a refusal would make "resolved" and "refused,
    nothing changed" look identical on the page."""
    from syndicate.app import app

    _seed(_unknown())
    with app.test_client() as client:
        ok = client.post("/portfolio/live/unknown/unk-1/resolve", data={"finding": "not_placed"})
        assert ok.status_code == 303
        assert "resolved" in ok.headers["Location"]
        assert _stored()["status"] == "rejected"

        bad = client.post("/portfolio/live/unknown/unk-1/resolve", data={"finding": "nope"})
        assert bad.status_code == 303
        assert "refused" in bad.headers["Location"]
