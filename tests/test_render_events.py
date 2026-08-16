"""Tests for `scripts/render_events.py`.

These cover the two things that make an events read trustworthy rather than
merely plausible: the pager reaching the whole window, and a failure reason
never landing in the wrong bucket. Both are falsification tests -- each one
fails loudly under the specific defect it exists to catch.

No network. The API is a stub; what is under test is our handling of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import render_events  # noqa: E402


def _event(stamp: str, kind: str = "server_failed", **details) -> dict:
    return {"id": f"ev-{stamp}", "timestamp": stamp, "type": kind, "details": details}


def _row(event: dict, cursor: str) -> dict:
    return {"cursor": cursor, "event": event}


# --------------------------------------------------------------------------
# classify: a reason must never be flattened, and an unrecognised one must not
# be absorbed into a known bucket.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "details,expected",
    [
        ({"reason": {"evicted": False, "oomKilled": {"memoryLimit": "4Gi"}}}, "oomKilled"),
        ({"reason": {"evicted": True}}, "evicted"),
        ({"reason": {"evicted": False, "unhealthy": "HTTP health check failed"}}, "unhealthy"),
        ({"reason": {"earlyExit": True, "evicted": False}}, "earlyExit"),
    ],
)
def test_classify_names_each_failure_reason(details, expected):
    assert render_events.classify(_event("2026-08-14T20:03:11Z", **details)) == expected


def test_unrecognised_reason_does_not_land_in_a_known_bucket():
    """A new failure mode must be visibly unknown, not silently familiar.

    `learnings.md`: an unknown that defaults onto a familiar branch is how a new
    failure mode stays invisible.
    """
    event = _event("2026-08-14T20:03:11Z", reason={"someFutureReason": True})
    assert render_events.classify(event) == "failed:unknown"


def test_empty_reason_is_unknown_not_oom():
    assert render_events.classify(_event("2026-08-14T20:03:11Z", reason={})) == "failed:unknown"


def test_non_failure_events_keep_their_type():
    assert render_events.classify(_event("2026-08-14T20:03:11Z", "deploy_ended")) == "deploy_ended"


def test_oom_false_is_not_an_oom():
    """`oomKilled` absent-or-falsey must read as not-an-OOM, not as truthy."""
    event = _event("2026-08-14T20:03:11Z", reason={"evicted": True, "oomKilled": None})
    assert render_events.classify(event) == "evicted"


# --------------------------------------------------------------------------
# The pager. The defect this catches is real: against the 2026-08-14 window a
# single page returns 20 oomKilled and the whole window holds 29.
# --------------------------------------------------------------------------


def test_pager_walks_past_the_first_page(monkeypatch):
    page_one = [_row(_event(f"2026-08-14T2{i}:00:00Z"), f"c{i}") for i in range(render_events._PAGE)]
    page_two = [_row(_event("2026-08-14T10:00:00Z"), "last")]
    pages = [page_one, page_two]

    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: pages.pop(0) if pages else [])

    events, page_count = render_events.fetch_events(service="refresh-worker")
    assert page_count == 2
    assert len(events) == render_events._PAGE + 1


def test_pager_returns_oldest_first(monkeypatch):
    rows = [
        _row(_event("2026-08-14T22:00:00Z"), "a"),
        _row(_event("2026-08-14T20:00:00Z"), "b"),
    ]
    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: rows)

    events, _ = render_events.fetch_events(service="refresh-worker")
    stamps = [e["timestamp"] for e in events]
    assert stamps == sorted(stamps)


def test_pager_terminates_when_the_cursor_stops_advancing(monkeypatch):
    """A server that keeps handing back the same page must not spin _MAX_PAGES."""
    page = [_row(_event(f"2026-08-14T2{i}:00:00Z"), "stuck") for i in range(render_events._PAGE)]
    calls = {"n": 0}

    def _stuck(url, key):
        calls["n"] += 1
        return page

    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", _stuck)

    events, page_count = render_events.fetch_events(service="refresh-worker")
    assert page_count == 2  # one real page, one that returned nothing new
    assert calls["n"] == 2
    assert len(events) == render_events._PAGE


def test_duplicate_events_across_pages_are_counted_once(monkeypatch):
    shared = _event("2026-08-14T20:03:11Z")
    pages = [
        [_row(shared, "a")] * 1 + [_row(_event("2026-08-14T21:00:00Z"), "b")],
        [_row(shared, "c")],
    ]
    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: pages.pop(0) if pages else [])

    events, _ = render_events.fetch_events(service="refresh-worker")
    assert len(events) == 2


# --------------------------------------------------------------------------
# A deploy nobody ordered is findable (CLAUDE.md `#284`).
# --------------------------------------------------------------------------


def test_deploy_with_no_user_and_no_flag_is_named_as_the_blueprint_sync_shape():
    event = _event("2026-08-14T20:03:11Z", "deploy_started", trigger={"manual": False, "rollback": False})
    assert "blueprint_sync" in render_events._deploy_trigger(event)


def test_a_failure_is_never_labelled_with_a_deploy_trigger():
    """The defect this catches shipped and was caught in its own output.

    `server_failed` carries no `trigger`. Reading that absence as "no user" put
    `NO USER (blueprint_sync shape?)` against all 20 live-odds-worker
    `earlyExit` events, which would have read as a config-push finding.
    """
    event = _event("2026-08-16T16:38:05Z", reason={"earlyExit": True, "evicted": False})
    assert render_events._deploy_trigger(event) == ""


def test_an_unknown_reason_shows_its_raw_shape():
    event = _event("2026-08-16T16:38:05Z", reason={"someFutureReason": True})
    detail = render_events._reason_detail(event)
    assert "someFutureReason" in detail


def test_deploy_by_a_user_reports_the_user():
    event = _event(
        "2026-08-14T20:03:11Z",
        "deploy_started",
        trigger={"manual": True, "user": {"email": "mostgood@gmail.com"}},
    )
    detail = render_events._deploy_trigger(event)
    assert "mostgood@gmail.com" in detail
    assert "manual" in detail
    assert "blueprint_sync" not in detail


def test_oom_detail_carries_the_memory_limit():
    event = _event("2026-08-14T20:03:11Z", reason={"oomKilled": {"memoryLimit": "4Gi"}})
    assert render_events._reason_detail(event) == "memoryLimit=4Gi"
