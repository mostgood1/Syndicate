"""The evaluation bundle must scan the ledger ONCE, with identical output.

Measured in production 2026-08-17, inside one bundle that ran 81s and ended in
an oomKilled at 02:27:07Z:

    02:26:45.341  LEDGER_CHUNKS_ACCEPTED count=8 bytes=830,832,574 records=22,078
    02:26:46.739  SKIP 08-05 / 08-06 / 08-07        <- second scan begins
    02:27:02.574  LEDGER_CHUNKS_ACCEPTED count=8 bytes=830,832,574 records=22,078

`build_evaluation_history_summary` and `build_recommendation_performance_analytics`
were each passed `records=None`, the branch that re-reads all eight chunks.

This is a REFACTOR, so the load-bearing tests are the equivalence ones: threading
a pre-reduced set must produce byte-identical output to letting each consumer
load for itself. If that does not hold, the sharing is not safe and the double
scan is doing something the single scan is not.

The reduced set is threaded rather than the raw one deliberately -- see the
comment at the call site. Sharing raw records would raise the peak above the
double scan it replaces, which is the opposite of the goal.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import intelligence_evaluation as ie


@pytest.fixture()
def ledger(tmp_path):
    """A ledger exercising both reduction behaviours: duplicate ids and events."""
    rows = [
        {"recommendation_id": "r1", "prediction_id": "p1", "sport": "mlb", "market": "totals",
         "result": "win", "stake": 1.0, "pnl": 0.9, "clv": 0.02, "updated_at": "2026-08-01T00:00:00Z"},
        # same id, later -> must win the reduction
        {"recommendation_id": "r1", "prediction_id": "p1", "sport": "mlb", "market": "totals",
         "result": "loss", "stake": 1.0, "pnl": -1.0, "clv": -0.01, "updated_at": "2026-08-02T00:00:00Z"},
        {"recommendation_id": "r2", "prediction_id": "p2", "sport": "mlb", "market": "totals",
         "result": "push", "stake": 1.0, "pnl": 0.0, "clv": 0.0, "updated_at": "2026-08-02T00:00:00Z"},
        # portfolio_event rows are skipped by the reduction on BOTH passes
        {"record_type": "portfolio_event", "recommendation_id": "r3", "sport": "mlb"},
        # no recommendation_id -> exercises the positional fallback key
        {"prediction_id": "p9", "sport": "mlb", "market": "spreads", "result": "win",
         "stake": 1.0, "pnl": 0.5, "updated_at": "2026-08-03T00:00:00Z"},
    ]
    p = tmp_path / "evaluation_ledger.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def _reduced(path):
    return ie._latest_by_recommendation_id(ie._stream_record_payloads(ledger_path=path))


# --- the equivalence tests: threading must not change the answer -------------

def test_history_summary_identical_whether_loaded_or_threaded(ledger):
    fresh = ie.build_evaluation_history_summary(records=None, ledger_path=ledger, sport="mlb")
    threaded = ie.build_evaluation_history_summary(records=_reduced(ledger), ledger_path=ledger, sport="mlb")
    assert threaded == fresh


def test_performance_analytics_identical_whether_loaded_or_threaded(ledger):
    fresh = ie.build_recommendation_performance_analytics(records=None, ledger_path=ledger)
    threaded = ie.build_recommendation_performance_analytics(records=_reduced(ledger), ledger_path=ledger)
    assert threaded == fresh


def test_equivalence_holds_with_a_sport_filter_applied_after_the_reduce(ledger):
    """Both consumers reduce FIRST and filter SECOND; a pre-reduced input must
    therefore reach the filters unchanged."""
    for sport in ("mlb", "nba", None):
        fresh = ie.build_evaluation_history_summary(records=None, ledger_path=ledger, sport=sport)
        threaded = ie.build_evaluation_history_summary(records=_reduced(ledger), ledger_path=ledger, sport=sport)
        assert threaded == fresh, f"diverged for sport={sport}"


# --- the reduction property the sharing depends on --------------------------

def test_reduction_is_idempotent_on_an_already_reduced_set(ledger):
    once = _reduced(ledger)
    twice = ie._latest_by_recommendation_id(once)
    assert twice == once, "sharing a reduced set requires the reduce to be idempotent"


def test_reduction_drops_portfolio_events_and_keeps_the_latest_row(ledger):
    rows = _reduced(ledger)
    assert not any(str(r.get("record_type") or "") == "portfolio_event" for r in rows)
    r1 = [r for r in rows if r.get("recommendation_id") == "r1"]
    assert len(r1) == 1
    assert r1[0]["result"] == "loss", "the LATER r1 row must survive the reduction"


# --- the scan count, which is the point of the change -----------------------

def test_a_threaded_consumer_does_not_touch_the_ledger_again(ledger, monkeypatch):
    """With records supplied, no consumer may re-open the ledger."""
    opened: list = []
    real = ie._stream_record_payloads

    def spy(records=None, *, ledger_path=None):
        if records is None:
            opened.append(ledger_path)
        return real(records, ledger_path=ledger_path)

    monkeypatch.setattr(ie, "_stream_record_payloads", spy)
    shared = ie._latest_by_recommendation_id(real(ledger_path=ledger))
    opened.clear()
    ie.build_evaluation_history_summary(records=shared, ledger_path=ledger, sport="mlb")
    ie.build_recommendation_performance_analytics(records=shared, ledger_path=ledger)
    assert opened == [], f"consumers re-scanned the ledger: {opened}"


# --- the guard on the CALL SITE, which the tests above do not cover ---------

def test_the_bundle_threads_a_shared_set_instead_of_passing_none():
    """The equivalence tests above prove sharing is SAFE, not that it HAPPENS.

    Without this, reverting the call site to `records=None` would leave every
    test above green while restoring the double scan.
    """
    import inspect

    src = inspect.getsource(ie.build_intelligence_evaluation_bundle)
    # CODE ONLY. The call site carries a comment that quotes `records=None`
    # while explaining the defect, and a naive substring check over the raw
    # source matches that prose and fails on a correct implementation. Strip
    # comment lines first -- a guard that cannot tell code from a comment about
    # code is worse than no guard.
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    ).replace(" ", "")
    assert "shared_ledger_records" in code, "bundle no longer threads a shared set"
    assert "records=None" not in code, (
        "a consumer is back to records=None -- that is the branch that re-reads "
        "all eight chunks"
    )
    assert code.index("shared_ledger_records=") < code.index("build_evaluation_history_summary")
