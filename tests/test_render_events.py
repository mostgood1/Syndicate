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

    events, page_count, truncated = render_events.fetch_events(service="refresh-worker")
    assert page_count == 2
    assert len(events) == render_events._PAGE + 1
    assert truncated == ""  # a short final page IS the end of the window


def test_pager_returns_oldest_first(monkeypatch):
    rows = [
        _row(_event("2026-08-14T22:00:00Z"), "a"),
        _row(_event("2026-08-14T20:00:00Z"), "b"),
    ]
    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: rows)

    events, _, _ = render_events.fetch_events(service="refresh-worker")
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

    events, page_count, truncated = render_events.fetch_events(service="refresh-worker")
    assert page_count == 2  # one real page, one that returned nothing new
    assert calls["n"] == 2
    assert len(events) == render_events._PAGE
    # Stopping is right; calling it the end of the window is not. Whatever lay
    # past the stall was never read, and the report must say so.
    assert "cursor" in truncated


def test_duplicate_events_across_pages_are_counted_once(monkeypatch):
    shared = _event("2026-08-14T20:03:11Z")
    pages = [
        [_row(shared, "a")] * 1 + [_row(_event("2026-08-14T21:00:00Z"), "b")],
        [_row(shared, "c")],
    ]
    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: pages.pop(0) if pages else [])

    events, _, _ = render_events.fetch_events(service="refresh-worker")
    assert len(events) == 2


# --------------------------------------------------------------------------
# READ vs EVENT SPAN. The defect this catches shipped and cost a retraction:
# on 2026-08-17 a 5-hour read that found one 4-event deploy cycle printed
# `COVERED 14:33 .. 14:39` and was read as a 6-minute read, turning a correct
# all-clear into "mostly unverified".
# --------------------------------------------------------------------------


def test_a_sparse_window_that_reads_whole_is_not_reported_as_truncated(monkeypatch):
    """Few events over a long window is a SPARSE window, not a short read.

    The four events span ~6 minutes of a requested 5 hours. `truncated` must
    still be empty -- the span of what was found carries no information about
    how much was read.
    """
    rows = [
        _row(_event("2026-08-17T14:33:36Z", "build_started"), "a"),
        _row(_event("2026-08-17T14:33:36.8Z", "deploy_started"), "b"),
        _row(_event("2026-08-17T14:38:18Z", "build_ended"), "c"),
        _row(_event("2026-08-17T14:39:32Z", "deploy_ended"), "d"),
    ]
    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: rows)

    events, pages, truncated = render_events.fetch_events(
        service="refresh-worker", start="2026-08-17T10:55:37Z"
    )
    assert len(events) == 4
    assert pages == 1
    assert truncated == ""


def test_a_malformed_response_is_not_reported_as_the_end_of_the_window(monkeypatch):
    """An unrecognised shape must not land on the permissive branch."""
    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: {"unexpected": "dict"})

    events, _, truncated = render_events.fetch_events(service="refresh-worker")
    assert events == []
    assert truncated  # NOT "" -- this read failed, it did not finish


def test_hitting_the_page_cap_is_reported_as_truncated(monkeypatch):
    """Running out of pages is the one case with no break at all."""
    counter = {"n": 0}

    def _always_full(url, key):
        counter["n"] += 1
        # Every page full, every cursor new -> nothing ever ends the walk.
        return [
            _row(_event(f"2026-08-14T{counter['n']:02d}:{i:02d}:00Z"), f"c{counter['n']}-{i}")
            for i in range(render_events._PAGE)
        ]

    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", _always_full)

    _, pages, truncated = render_events.fetch_events(service="refresh-worker", max_pages=3)
    assert pages == 3
    assert "page cap" in truncated


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


# --------------------------------------------------------------------------
# `details.reason` IS NOT ALWAYS A MAPPING. Measured 2026-09-04 over a fully
# paged read of refresh-worker (7,525 events, 76 pages): 759 `server_failed`
# carry an object there, and all 9 `auto_deploy_disabled` carry the bare string
# `"setting_change"`. `_reason_detail` assumed the mapping, so the listing died
# at 2026-07-01 with `AttributeError: 'str' object has no attribute 'get'` --
# after printing 289 lines of plausible rows and never reaching the recent
# window. A false-negative instrument: `learnings.md` 2026-09-02 FORBIDDEN.
# --------------------------------------------------------------------------


def test_a_string_reason_does_not_crash_the_reader():
    """The exact shape and event that broke it, verbatim from the API."""
    event = {
        "id": "ev-auto-deploy-disabled",
        "timestamp": "2026-07-01T21:19:15.826277Z",
        "type": "auto_deploy_disabled",
        "details": {"fromTrigger": "commit", "reason": "setting_change"},
    }
    assert render_events._reason_detail(event) == "setting_change"


def test_a_string_reason_on_a_failure_is_unknown_not_a_crash():
    """`classify` made the same assumption one line further down.

    No `server_failed` has been seen with a scalar reason -- which is the point:
    the shape that breaks a reader is by definition the one nobody has seen yet,
    and this branch must not be waiting to raise when it arrives.
    """
    event = _event("2026-08-14T20:03:11Z", reason="somethingNew")
    assert render_events.classify(event) == "failed:unknown"
    assert render_events._reason_detail(event) == "somethingNew"


def test_a_non_dict_details_block_does_not_crash():
    event = {"id": "x", "timestamp": "2026-07-01T21:19:15Z", "type": "server_failed", "details": "opaque"}
    assert render_events.classify(event) == "failed:unknown"
    assert render_events._reason_detail(event) == ""


def test_a_list_reason_is_shown_rather_than_swallowed():
    """An unreadable shape the operator can SEE is a lead; a dropped one is not."""
    event = _event("2026-07-01T21:19:15Z", "plan_changed", reason=["a", "b"])
    assert "a" in render_events._reason_detail(event)


# --------------------------------------------------------------------------
# One bad event must not cost the census, and a run that dies must never look
# like one that finished.
# --------------------------------------------------------------------------


class _Hostile:
    """A value that raises even on being rendered -- the NEXT bad shape.

    Non-dict reasons are now handled, so this stands in for whatever the API
    does after that. The guarantee under test is not "we anticipated it" but
    "an unanticipated one costs a row, not the run".
    """

    def __repr__(self):
        raise RuntimeError("hostile shape")


def test_one_unrenderable_event_is_a_visible_row_not_an_exception():
    event = {"id": "x", "timestamp": "2026-07-01T21:19:15Z", "type": "server_failed", "details": {"reason": _Hostile()}}
    kind, detail = render_events._describe(event)
    assert kind == "!!UNRENDERABLE"
    assert "hostile shape" in detail


def test_the_listing_ends_with_a_completeness_marker(monkeypatch, capsys):
    """The ABSENCE of this line is how a truncated run is caught. So it must be
    present on a good run, and it must come AFTER the last row."""
    rows = [
        _row(_event("2026-07-01T21:19:15.826277Z", "auto_deploy_disabled", reason="setting_change"), "c0"),
        _row(_event("2026-08-16T16:38:05Z", reason={"earlyExit": True}), "c1"),
    ]
    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: rows)
    monkeypatch.setattr(sys, "argv", ["render_events.py", "--service", "refresh-worker"])

    assert render_events.main() == render_events.EXIT_OK
    lines = capsys.readouterr().out.splitlines()

    def index_of(needle: str) -> int:
        return next(i for i, ln in enumerate(lines) if needle in ln)

    # The marker means "the listing finished", so it has to come after the last
    # row. A marker printed before the rows would certify nothing.
    assert index_of("setting_change") < index_of("OUTPUT COMPLETE")


def test_a_full_run_over_the_real_mixed_shapes_reaches_the_end(monkeypatch, capsys):
    """The regression in one line: the old reader stopped at the string row."""
    mixed = [
        _row(_event("2026-07-01T21:19:15.826277Z", "auto_deploy_disabled", reason="setting_change"), "c0"),
        _row(_event("2026-08-17T03:55:17Z", reason={"oomKilled": {"memoryLimit": "4Gi"}}), "c1"),
        _row(_event("2026-09-01T10:00:00Z", "deploy_started", trigger={"manual": True}), "c2"),
    ]
    monkeypatch.setattr(render_events, "_api_key", lambda: "k")
    monkeypatch.setattr(render_events, "_get", lambda url, key: mixed)
    monkeypatch.setattr(sys, "argv", ["render_events.py", "--service", "refresh-worker"])

    assert render_events.main() == render_events.EXIT_OK
    out = capsys.readouterr().out
    # Every row PAST the string-reason event is what the crash used to eat.
    assert "memoryLimit=4Gi" in out
    assert "2026-09-01T10:00:00Z" in out
    assert "OUTPUT COMPLETE" in out


def test_the_abort_banner_goes_to_stdout_not_stderr(capsys):
    """The caller who most needs the banner is the one piping through `tail`.

    That caller has already discarded stderr -- which is exactly why the
    traceback alone was not enough, and why this assertion is about the STREAM
    and not merely about the text.
    """
    code = render_events._abort(RuntimeError("simulated transport blowup"))
    captured = capsys.readouterr()

    assert code == render_events.EXIT_ABORTED
    assert render_events.EXIT_ABORTED not in (render_events.EXIT_OK, render_events.EXIT_READER_FAILED)
    assert "ABORTED" in captured.out
    assert "INCOMPLETE" in captured.out
    assert "simulated transport blowup" in captured.out
