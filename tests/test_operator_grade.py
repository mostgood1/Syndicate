"""An operator grade of ONE live fill from the venue's own settled result (lane `kalshi-aged-out-grade`).

The case: key `970ec063`, 1 NO on `KXNFLGAME-26OCT25MIANYJ-NYJ` @ 0.43 (fee $0.0172), Kalshi `market_result=no`,
and a settlement row that also carries `yes_count_fp=0.01` -- our own take-profit exit, filled 0.01 of 1 and
recorded `dead`, so the venue grader refuses `both_sides_held` forever. The outcome must come from the VENUE
(the order's own leg against `market_result`), the money from the order's OWN fill, and the operator's part --
evidence and note -- must be on the row with everything it overwrote.
"""

from __future__ import annotations

import pytest

from tests.test_execution_ledger import _live_order

TICKER = "KXNFLGAME-26OCT25MIANYJ-NYJ"


@pytest.fixture
def mod():
    from syndicate.features.shared import execution_ledger as m
    return m


def _set(mod, key, **fields):
    state = mod._load()
    for order in state["orders"]:
        if order["idempotency_key"] == key:
            order.update(fields)
    mod._persist(state)


def _won_no(mod, monkeypatch, key="op-no"):
    key = _live_order(mod, monkeypatch, key=key, status=mod.STATUS_FILLED, venue_order_id="ord-1",
                      fill_price=0.43, fill_stake_dollars=0.43, venue_ticker=TICKER)
    _set(mod, key, side="no", market="h2h", line=None, contracts=1, fees_dollars=0.0172,
         venue_status="executed", venue_remaining_count=0.0)
    return key


EVIDENCE = {"settlement": {"ticker": TICKER, "market_result": "no", "yes_count_fp": "0.01", "no_count_fp": "1.00"}}


def test_grades_the_leg_against_the_venue_result_from_its_own_fill(mod, monkeypatch, capsys):
    key = _won_no(mod, monkeypatch)
    row = mod.operator_grade_from_venue(key, market_result="no", settled_at_venue="2026-10-25T20:01:52Z",
                                        evidence=EVIDENCE, note="exit x403f59b5 dust fill; user yes")
    assert row["outcome"] == "won"
    assert row["pnl_dollars"] == pytest.approx(0.5528), "1 x (1 - 0.43) - 0.0172"
    assert row["settled_by"] == "venue" and row["held_side"] == "no"
    assert row["settled_at_venue"] == "2026-10-25T20:01:52Z" and row["graded_at"]
    assert row["pre_operator_grade"] == {f: None for f in mod._OPERATOR_GRADE_FIELDS}
    grade = row["operator_grade"]
    assert grade["market_result"] == "no" and grade["pnl_basis"] == "own_fill"
    assert grade["evidence"] == EVIDENCE and grade["note"].startswith("exit x403f59b5")
    persisted = mod.find_order(key)
    assert persisted["outcome"] == "won" and persisted["operator_grade"]["at"] == grade["at"]
    assert "OPERATOR_GRADE key=" in capsys.readouterr().out


def test_the_same_leg_loses_on_the_other_result(mod, monkeypatch):
    key = _won_no(mod, monkeypatch)
    row = mod.operator_grade_from_venue(key, market_result="yes", settled_at_venue=None, evidence={}, note="x")
    assert row["outcome"] == "lost" and row["pnl_dollars"] == pytest.approx(-0.4472)


@pytest.mark.parametrize("kwargs, token", [
    ({"market_result": "scalar", "note": "x"}, "unsupported_market_result"),
    ({"market_result": "", "note": "x"}, "unsupported_market_result"),
    ({"market_result": "no", "note": "  "}, "note_required"),
])
def test_refuses_without_a_venue_result_or_a_reason(mod, monkeypatch, kwargs, token):
    key = _won_no(mod, monkeypatch)
    with pytest.raises(mod.OperatorResolutionError, match=token):
        mod.operator_grade_from_venue(key, settled_at_venue=None, evidence={}, **kwargs)
    assert mod.find_order(key).get("outcome") is None


def test_refuses_a_second_grade_and_leaves_the_first(mod, monkeypatch):
    key = _won_no(mod, monkeypatch)
    mod.operator_grade_from_venue(key, market_result="no", settled_at_venue=None, evidence={}, note="first")
    with pytest.raises(mod.OperatorResolutionError, match="already_settled"):
        mod.operator_grade_from_venue(key, market_result="yes", settled_at_venue=None, evidence={}, note="second")
    assert mod.find_order(key)["outcome"] == "won"


def test_refuses_a_row_that_is_not_a_live_fill(mod, monkeypatch):
    submitted = _live_order(mod, monkeypatch, key="op-sub", status=mod.STATUS_SUBMITTED, venue_order_id="ord-2")
    with pytest.raises(mod.OperatorResolutionError, match="not_filled"):
        mod.operator_grade_from_venue(submitted, market_result="no", settled_at_venue=None, evidence={}, note="x")
    paper = _won_no(mod, monkeypatch, key="op-paper")
    _set(mod, paper, mode="paper")
    with pytest.raises(mod.OperatorResolutionError, match="not_live"):
        mod.operator_grade_from_venue(paper, market_result="no", settled_at_venue=None, evidence={}, note="x")
    with pytest.raises(mod.OperatorResolutionError, match="order_not_found"):
        mod.operator_grade_from_venue("nope", market_result="no", settled_at_venue=None, evidence={}, note="x")


def test_the_venue_repair_passes_leave_an_operator_grade_alone(mod, monkeypatch):
    from syndicate.features.shared import venue_settlement as vs

    key = _won_no(mod, monkeypatch)
    mod.operator_grade_from_venue(key, market_result="no", settled_at_venue=None, evidence={}, note="x")
    vs.repair_impossible_venue_pnl()
    vs.repair_multi_side_grades()
    vs.repair_zero_delta_pushes()
    row = mod.find_order(key)
    assert row["outcome"] == "won" and row["pnl_dollars"] == pytest.approx(0.5528)


# --------------------------------------------------------------------------
# scripts/kalshi_operator_grade.py -- the dry run that rests the grade on the venue's own rows.
# --------------------------------------------------------------------------


def _fake_get(settlement, fills=()):
    def get(path):
        if path.startswith("/portfolio/settlements"):
            return {"settlements": [settlement] if settlement else []}
        if path.startswith("/portfolio/fills"):
            return {"fills": list(fills)}
        raise AssertionError(path)
    return get


SETTLED_BOTH = {"ticker": TICKER, "market_result": "no", "settled_time": "2026-10-25T20:01:52Z",
                "yes_count_fp": "0.01", "no_count_fp": "1.00", "revenue": 100}


def test_plan_would_grade_the_measured_case(mod, monkeypatch):
    from scripts import kalshi_operator_grade as tool

    key = _won_no(mod, monkeypatch)
    out = tool.plan(key, get=_fake_get(SETTLED_BOTH, [{"order_id": "01a17426", "side": "yes", "count_fp": "0.01"}]))
    assert "refused" not in out, out.get("refused")
    assert out["venue_grader"] == {"graded": False, "reason": "both_sides_held"}
    assert out["would_write"]["outcome"] == "won" and out["would_write"]["pnl_dollars"] == pytest.approx(0.5528)
    assert mod.find_order(key).get("outcome") is None, "a plan writes nothing"


@pytest.mark.parametrize("settlement, token", [
    ({**SETTLED_BOTH, "yes_count_fp": "0.00"}, "venue_grader_can_grade_it"),
    ({**SETTLED_BOTH, "no_count_fp": "0.50"}, "settlement_does_not_hold_our_leg"),
    ({**SETTLED_BOTH, "market_result": "scalar"}, "unsupported_market_result"),
    (None, "no_single_settlement_row"),
])
def test_plan_refuses_what_an_operator_must_not_grade(mod, monkeypatch, settlement, token):
    from scripts import kalshi_operator_grade as tool

    key = _won_no(mod, monkeypatch)
    out = tool.plan(key, get=_fake_get(settlement))
    assert str(out.get("refused") or "").startswith(token), out.get("refused")


def test_main_writes_only_with_apply_and_a_note(mod, monkeypatch, capsys):
    from scripts import kalshi_operator_grade as tool

    key = _won_no(mod, monkeypatch)
    monkeypatch.setattr(tool, "kalshi_get", _fake_get(SETTLED_BOTH))
    monkeypatch.setattr(tool, "plan", lambda k, get=None, _p=tool.plan: _p(k, get=_fake_get(SETTLED_BOTH)))
    assert tool.main(["--key", key]) == 0
    assert mod.find_order(key).get("outcome") is None
    assert tool.main(["--key", key, "--apply"]) == 2
    assert mod.find_order(key).get("outcome") is None
    assert tool.main(["--key", key, "--apply", "--note", "user yes in chat"]) == 0
    row = mod.find_order(key)
    assert row["outcome"] == "won" and row["operator_grade"]["evidence"]["tool"] == "scripts/kalshi_operator_grade.py"
