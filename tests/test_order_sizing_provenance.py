"""A recorded order carries the sizing provenance it was staked on (todo #722).

`portfolio_commit` writes `sizing.staked_probability_version` and
`sizing.basis` onto every plan position, and both were dropped at the
`OrderRequest` boundary -- so a settled outcome could not be split by what its
stake was computed FROM.

That is measured, not feared. Lane `published-negative-ev` armed a reading for
2026-10-21 15:00Z to split settled outcomes on `staked_probability_version` and
got **0 settled positions in every cell**: 958 of 3,000 ledger orders were
settled (576 of them live) and none could be attributed to a sizing basis,
because all 658 live orders were unjoinable to a plan -- 552 carrying no
`position_key` at all. `sizing.basis`'s own comment
(`portfolio_commit.py:1456`) states the purpose it was failing to serve:
"Without it, model-edge and market-fair positions land in one settlement pool
and their ROIs stop being separable."

The nested read is the part that ships inert if it is wrong -- the position
nests these under `sizing`, exactly like `attribution` nests `side_picked_by`,
and a flat `position.get(...)` would read `None` forever while every test that
hands the fields in directly still passed. `test_the_nested_read_is_reachable`
is the one that would catch that.
"""

from __future__ import annotations

from pipeline.execute_portfolio import _order_from_position
from syndicate.features.shared.execution_ledger import OrderRequest

# The retained-field list is module-private and its name has changed before, so
# it is looked up by `getattr` rather than imported -- and the test SAYS SO if
# it cannot find it, instead of silently passing.
from syndicate.features.shared import execution_ledger as el


def _position(**over: object) -> dict:
    """A plan position complete enough for `_order_from_position` to accept."""
    row = {
        "position_key": "abc123",
        "event_id": "evt-1",
        "market": "totals",
        "side": "over",
        "sport": "nfl",
        "price": -110.0,
        "stake_dollars": 5.0,
        "line": 44.5,
        "sizing": {"basis": "model_edge", "staked_probability_version": "market_fair@unfitted"},
    }
    row.update(over)
    return row


def test_the_nested_read_is_reachable():
    """OFF != ON, and it is the whole point.

    The fields live under `position["sizing"]`. A flat read would return None
    here while every direct-construction test below still passed.
    """
    req = _order_from_position(_position(), "2026-10-21", "kalshi")
    assert req is not None, "fixture must produce a request"
    assert req.staked_probability_version == "market_fair@unfitted"
    assert req.sizing_basis == "model_edge"


def test_absent_sizing_stays_absent():
    """No `sizing` block -> None, never a default.

    "unfitted" is a REAL profile, so defaulting to it would mislabel a row into
    the very population this field exists to separate.
    """
    pos = _position()
    pos.pop("sizing")
    req = _order_from_position(pos, "2026-10-21", "kalshi")
    assert req is not None
    assert req.staked_probability_version is None
    assert req.sizing_basis is None


def test_a_recorded_order_carries_both_fields():
    req = OrderRequest(
        position_key="k1",
        selected_date="2026-10-21",
        venue="kalshi",
        sport="nfl",
        event_id="evt-1",
        market="totals",
        side="over",
        requested_price=-110.0,
        requested_stake_dollars=5.0,
        staked_probability_version="market_fair@unfitted",
        sizing_basis="model_edge",
    )
    record, _created = el._record_into_state({"orders": []}, req, mode="paper")
    assert record["staked_probability_version"] == "market_fair@unfitted"
    assert record["sizing_basis"] == "model_edge"


def test_a_request_without_them_records_them_as_null_not_missing():
    """Present-and-null, so a summary cannot read "no such key" as "no basis"."""
    req = OrderRequest(
        position_key="k2",
        selected_date="2026-10-21",
        venue="kalshi",
        sport="nfl",
        event_id="evt-2",
        market="totals",
        side="under",
        requested_price=100.0,
        requested_stake_dollars=5.0,
    )
    record, _created = el._record_into_state({"orders": []}, req, mode="paper")
    assert "staked_probability_version" in record and record["staked_probability_version"] is None
    assert "sizing_basis" in record and record["sizing_basis"] is None


def test_the_fields_are_not_in_the_idempotency_key():
    """A row re-sized under a new profile is the SAME BET.

    Same rule the file states for every other attribution field: that key is an
    explicit list so a re-scored row is not mistaken for a new order. If these
    entered it, the 2026-10-19 activation of #704 would have made every open
    position look like a fresh bet.
    """
    base = dict(
        position_key="k3",
        selected_date="2026-10-21",
        venue="kalshi",
        sport="nfl",
        event_id="evt-3",
        market="totals",
        side="over",
        requested_price=-110.0,
        requested_stake_dollars=5.0,
    )
    a = OrderRequest(**base, staked_probability_version="unfitted", sizing_basis="market_fair")
    b = OrderRequest(**base, staked_probability_version="market_fair@unfitted", sizing_basis="model_edge")
    assert el.idempotency_key(a) == el.idempotency_key(b)


def test_both_fields_are_retained_when_the_ledger_trims():
    """A field dropped by the trim is a field that vanishes at the record cap.

    The ledger keeps a `_MAX_RECORDS` window and thins older rows to a retained
    set; provenance that is not in that set survives only as long as the row is
    young, which is the opposite of what a settled-ROI split needs.
    """
    retained = None
    for name in ("_RETAINED_ORDER_FIELDS", "_LEAN_FIELDS", "_KEEP_FIELDS"):
        if hasattr(el, name):
            retained = set(getattr(el, name))
            break
    assert retained is not None, "the retained-field list was renamed; find it and re-point this test"
    assert "staked_probability_version" in retained
    assert "sizing_basis" in retained
