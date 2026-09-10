"""The arm 2 watcher: what its `wait` line says, and what its gate divides by.

Until 2026-09-10 the reasons were arm B's alone, so a poll where arm A's time
guard skipped the gate read exactly like one where the gate ran and declined --
11 of 14 over-bar polls on the 2026-09-10T01:48:45Z watch, none visible.

Also until 2026-09-10 the gate divided a PARTIAL meter by the FULL PREVIOUS
hour of served bytes. A bandwidth bucket is labelled by its hour's START, so
the denominator is that hour so far
(`.syndicate/findings_2026-09-10_spike_crossing_and_labelling.md`).

The loop tests drive `main()` end to end on --dry-run with the Render reads
stubbed, so what is pinned is the record the watcher actually writes, not the
helper alone.
"""
import datetime as dt
import json
import sys

import pytest

from scripts import controlled_transfer_arm2_watch as watch

BUCKET = "2026-09-10T13:00:00Z"


def _run(monkeypatch, tmp_path, *, metered, left, edge=None, app=None, seen=None):
    """One dry-run poll. `edge`/`app` None means the log scan MUST NOT run."""
    def _edge(key, start, end):
        if edge is None:
            raise AssertionError("arm A's edge scan ran on a poll it should have skipped")
        if seen is not None:
            seen.append(("edge", start, end))
        return edge

    def _app(key, start, end):
        if app is None:
            raise AssertionError("arm A's app scan ran on a poll it should have skipped")
        if seen is not None:
            seen.append(("app", start, end))
        return app

    monkeypatch.setattr(watch, "OUT_DIR", tmp_path)
    monkeypatch.setattr(watch, "_api_key", lambda: "k")
    monkeypatch.setattr(watch, "latest_bucket", lambda key: (BUCKET, metered))
    monkeypatch.setattr(watch, "seconds_left_in_hour", lambda: left)
    monkeypatch.setattr(watch, "edge_mb_for_bucket", _edge)
    monkeypatch.setattr(watch, "app_served_mb_for_bucket", _app)
    monkeypatch.setattr(watch, "fire", lambda *a, **k: pytest.fail("a dry run must never fire"))
    # 05:00-05:00 is the band the live watch runs with: arm B can never fire.
    monkeypatch.setattr(sys, "argv", ["watch", "--dry-run", "--quiet-band", "05:00-05:00"])
    assert watch.main() == 0
    (record_path,) = tmp_path.glob("arm2_watch_*.json")
    return json.loads(record_path.read_text(encoding="utf-8"))


def test_under_the_mb_bar_says_so(monkeypatch, tmp_path):
    poll = _run(monkeypatch, tmp_path, metered=77.3, left=900)["polls"][-1]
    assert poll["decision"] == "wait"
    assert poll["arm_a"] == "arm A: 77.3 MB < 300 MB bar"
    assert poll["why"].startswith("arm A: 77.3 MB < 300 MB bar | arm B: ")


def test_over_the_bar_too_late_in_the_hour_is_NOT_EVALUATED_not_declined(monkeypatch, tmp_path):
    # The case that was invisible: no scan runs (the stubs raise if it does),
    # and the line must say the gate was skipped rather than imply a verdict.
    poll = _run(monkeypatch, tmp_path, metered=400.0, left=900)["polls"][-1]
    assert poll["decision"] == "wait"
    assert poll["arm_a"] == "arm A: over 300 MB bar, NOT EVALUATED -- 900s left <= 1600"
    assert "ratio_verdict" not in poll
    assert poll["why"].startswith(poll["arm_a"])


def test_evaluated_and_declined_carries_the_verdict(monkeypatch, tmp_path):
    poll = _run(monkeypatch, tmp_path, metered=400.0, left=3000,
                edge=(100.0, 300), app=(200.0, 5000, True))["polls"][-1]
    assert poll["decision"] == "wait"
    assert poll["metered_over_app"] == 2.0
    assert poll["arm_a"] == "arm A: metered/app 2.00 < 5.0"
    assert poll["why"].startswith("arm A: metered/app 2.00 < 5.0 | arm B: ")


def test_a_spike_still_fires_arm_a(monkeypatch, tmp_path):
    # The status line must not have disturbed the firing path.
    record = _run(monkeypatch, tmp_path, metered=1000.0, left=3000,
                  edge=(50.0, 300), app=(100.0, 5000, True))
    assert record["polls"][-1]["decision"] == "ARM_A"
    assert record["fired"] == {"arm": "A", "dry_run": True}


# --- the denominator: the bucket's OWN hour, so far ------------------------

T0 = dt.datetime(2026, 9, 10, 13, 0)


def test_mid_hour_the_denominator_is_the_buckets_own_hour_up_to_the_meter_lag():
    start, end = watch.denominator_window(BUCKET, T0 + dt.timedelta(minutes=20))

    assert start == T0, "a bandwidth bucket starts AT its label, not an hour before"
    assert end == T0 + dt.timedelta(minutes=20 - watch.METER_LAG_MINUTES)


def test_once_the_hour_is_over_the_denominator_is_the_whole_hour_and_no_more():
    start, end = watch.denominator_window(BUCKET, T0 + dt.timedelta(minutes=75))

    assert (start, end) == (T0, T0 + dt.timedelta(hours=1))


def test_before_the_meter_has_counted_anything_the_window_is_EMPTY_and_the_gate_refuses():
    start, end = watch.denominator_window(BUCKET, T0 + dt.timedelta(minutes=2))

    assert end == start
    # The readers must not scan an empty window, and the gate must refuse its zero.
    assert watch.edge_mb_for_bucket("k", start, end) == (0.0, 0)
    assert watch.app_served_mb_for_bucket("k", start, end) == (0.0, 0, True)
    decision, _reason, ratio = watch.arm_a_verdict(400.0, 0.0, 0, 0.0, 0, True, 300.0, 5.0)
    assert decision == "UNDECIDABLE" and ratio is None


def test_the_loop_divides_by_the_buckets_own_hour_and_records_the_window(monkeypatch, tmp_path):
    """Reachability: the poll must pass the corrected window to BOTH readers and
    write it into the record, so a verdict can be audited against its hour."""
    seen = []
    poll = _run(monkeypatch, tmp_path, metered=400.0, left=3000,
                edge=(100.0, 300), app=(200.0, 5000, True), seen=seen)["polls"][-1]

    # The test runs long after 13:00Z, so the whole hour is countable.
    want = (T0, T0 + dt.timedelta(hours=1))
    assert [(kind, s, e) for kind, s, e in seen] == [("edge", *want), ("app", *want)]
    assert poll["denominator_window"] == ["2026-09-10T13:00:00Z", "2026-09-10T14:00:00Z"]
