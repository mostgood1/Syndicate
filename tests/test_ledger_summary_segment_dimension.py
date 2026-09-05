"""The ledger summary counts SEGMENT, because nothing else did.

`bet_status.segment_refusal` (2026-09-05) stopped a segment order being graded
against the WHOLE-GAME actual -- `segment` reached the order row and no resolver
read it. The immediate follow-up, "how many were mis-settled before that
landed", was unanswerable from `/api/ops/execution/ledger-summary`: it grouped by
`mode:venue` and dropped `segment` on the floor. Same defect one level up --
the field existed and nothing counted it.

`settled` is the number that answers it: an order carrying an `outcome` has been
GRADED, so a non-`full` segment with `settled > 0` is exactly the exposed
population.

THE ENDPOINT'S SAFETY PROPERTY IS PRESERVED BY CONSTRUCTION. It increments
counters and never places an order dict in the response -- no ticker, price,
client id or idempotency key is read. `segment` is a low-cardinality label like
`status`, so counting it adds no order-level data. These tests pin that.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _orders():
    return [
        # graded whole-game
        {"selected_date": "2026-09-05", "mode": "paper", "venue": "kalshi",
         "status": "filled", "segment": "full", "outcome": "won",
         "fill_stake_dollars": 10.0},
        # graded SEGMENT -- the exposed population
        {"selected_date": "2026-09-05", "mode": "paper", "venue": "kalshi",
         "status": "filled", "segment": "first5", "outcome": "lost",
         "fill_stake_dollars": 5.0},
        # segment, NOT yet graded
        {"selected_date": "2026-09-05", "mode": "paper", "venue": "kalshi",
         "status": "filled", "segment": "first5", "outcome": None,
         "fill_stake_dollars": 5.0},
        # no segment recorded at all
        {"selected_date": "2026-09-05", "mode": "paper", "venue": "kalshi",
         "status": "filled", "outcome": "won", "fill_stake_dollars": 1.0},
    ]


@pytest.fixture()
def summary(monkeypatch):
    from syndicate import app as app_module

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda *a, **k: {"orders": _orders()},
    )
    client = app_module.app.test_client()
    import os

    token = os.environ.get("ADMIN_TOKEN") or "test-token"
    monkeypatch.setenv("ADMIN_TOKEN", token)
    res = client.get("/api/ops/execution/ledger-summary?days=60",
                     headers={"X-Admin-Token": token})
    assert res.status_code == 200, res.status_code
    body = res.get_json()
    assert body.get("ok") is True, body
    return body["summary"]["2026-09-05"]["paper:kalshi"]


def test_a_graded_segment_order_is_COUNTED_as_settled(summary):
    """The number that answers 'how many were mis-settled'."""
    seg = summary["by_segment"]
    assert seg["first5"]["orders"] == 2
    assert seg["first5"]["settled"] == 1, (
        "only the order carrying an outcome has been graded"
    )


def test_an_UNGRADED_segment_order_is_not_counted_as_settled(summary):
    """`orders` and `settled` must not collapse -- a pending segment bet was
    never scored against anything and is not exposure."""
    assert summary["by_segment"]["first5"]["orders"] > summary["by_segment"]["first5"]["settled"]


def test_ABSENT_segment_is_reported_separately_from_full(summary):
    """The GRADER maps absent onto `full` deliberately. A COUNTER that did the
    same would make 'no segment was ever recorded' and 'this is a whole-game
    bet' indistinguishable, and telling those apart is the whole question."""
    seg = summary["by_segment"]
    assert "(unset)" in seg, sorted(seg)
    assert seg["(unset)"]["orders"] == 1
    assert seg["full"]["orders"] == 1
    assert seg["full"]["settled"] == 1


def test_the_existing_dimensions_are_unchanged(summary):
    """Additive. A regression here would silently change what every existing
    reader of this endpoint sees."""
    assert summary["orders"] == 4
    assert summary["filled"] == 4
    assert summary["by_status"] == {"filled": 4}
    assert summary["staked_dollars"] == pytest.approx(21.0)


def test_NO_order_level_data_leaks_into_the_response(summary):
    """The endpoint's stated safety property: counters only. Adding a label
    dimension must not become a route for order rows."""
    import json

    blob = json.dumps(summary)
    for forbidden in ("ticker", "idempotency", "client_id", "fill_price",
                      "requested_price", "player_name"):
        assert forbidden not in blob, forbidden
    for value in summary["by_segment"].values():
        assert set(value) == {"orders", "settled"}, value
