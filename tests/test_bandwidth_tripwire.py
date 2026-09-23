"""The bandwidth spike tripwire's traps, tested without touching the network.

Each test here corresponds to an instrument mistake that produced a WRONG
READING during the 2026-09-01..06 spike investigation. They are the reason the
tool exists in this shape, so they are asserted rather than commented.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scripts import bandwidth_tripwire as tw


def test_bandwidth_buckets_are_labelled_by_the_hours_START():
    """Bucket `X:00` covers `X:00 .. (X+1):00`.

    This test asserted the OPPOSITE until 2026-09-10. The old basis, "confirmed
    against `http-requests`", was true of THAT metric and was applied to
    bandwidth. Same-instant read at 15:13:07Z: the hour in flight was `16:00Z`
    in `http-requests` and `15:00Z` in `bandwidth`. The headline "4,050 MB
    against 2.6 MB of public traffic" for `09-04 18:00Z` was this pairing
    error; its own hour carried 178.2 MB over 1,366 requests.
    """
    start, end = tw._bucket_window("2026-09-04T18:00:00Z")

    assert start == "2026-09-04T18:00:00Z"
    assert end == "2026-09-04T19:00:00Z"


def test_the_window_is_exactly_one_hour():
    start, end = tw._bucket_window("2026-09-05T23:00:00Z")
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    delta = dt.datetime.strptime(end, fmt) - dt.datetime.strptime(start, fmt)

    assert delta == dt.timedelta(hours=1)
    assert end == "2026-09-06T00:00:00Z", "must roll forward across midnight"


def test_unsettled_buckets_are_EXCLUDED(monkeypatch):
    """A fresh low reading is INCOMPLETE, not low.

    Measured: one bucket went 3.2 -> 125.9 MB over ~50 minutes. Judging it
    early reads a 4 GB hour as a quiet one.
    """
    # The CURRENT hour's label is at most 59 minutes old, so it is always
    # inside a 70-minute settle window regardless of what minute this runs at.
    # An earlier version computed `now - 10 minutes` and then truncated, which
    # yields the PREVIOUS hour's label late in the hour and made the test flaky
    # by construction -- it failed at :55 and passed at :05.
    now = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    fresh = now.strftime("%Y-%m-%dT%H:00:00Z")
    old = (now - dt.timedelta(hours=5)).strftime("%Y-%m-%dT%H:00:00Z")
    monkeypatch.setattr(tw, "_metric", lambda *a, **k: {fresh: 3.2, old: 4050.1})

    kept = tw.settled_buckets("key", "web", hours=12, settle_minutes=70)

    assert old in kept, "a settled bucket must be judged"
    assert fresh not in kept, "an unsettled bucket must NOT be judged"


def test_the_access_line_parser_reads_the_RESPONSE_size():
    line = ('10.194.99.6 - - [04/Sep/2026:12:00:24 -0500] '
            '"GET /api/ops/artifacts/export?pattern=%2A2026-09-04%2A HTTP/1.1" 200 10175500 "-" "Python-urllib/3.11"')
    match = tw._ACCESS.match(line)

    assert match is not None
    ip, method, path, status, size = match.groups()
    assert ip == "10.194.99.6" and method == "GET" and status == "200"
    assert size == "10175500"
    assert path.split("?")[0] == "/api/ops/artifacts/export"


def test_a_dash_size_does_not_crash_the_parser():
    """Gunicorn writes `-` when it served no body."""
    line = '10.0.0.1 - - [04/Sep/2026:12:00:24 -0500] "GET /healthz HTTP/1.1" 200 - "-" "Render/1.0"'
    match = tw._ACCESS.match(line)

    assert match is not None
    assert match.groups()[4] == "-"


def test_publish_bytes_does_NOT_match_raw_bytes():
    """`PUBLISH_OK` carries both `bytes=` (wire) and `raw_bytes=` (pre-gzip).

    Counting `raw_bytes` as wire would overstate the flow by ~13x, which is the
    compression ratio -- an error that would look plausible.
    """
    line = ("[artifact_publisher] PUBLISH_OK path=x.json transport=stream "
            "bytes=1132154 raw_bytes=13677409 encoding=gzip")
    found = tw._PUBLISH_BYTES.findall(line)

    assert found == ["1132154"], found


def test_edge_response_bytes_parser():
    message = ('clientIP="73.75.177.190" requestID="abc" responseTimeMS=289 '
               'responseBytes=318 userAgent="Python-urllib/3.11"')

    assert tw._RESP_BYTES.search(message).group(1) == "318"
    assert tw._CLIENT_IP.search(message).group(1) == "73.75.177.190"
    assert tw._USER_AGENT.search(message).group(1) == "Python-urllib/3.11"


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_transient_api_failures_are_retried(monkeypatch, code):
    """A capture that dies halfway is worse than none: the logs it is racing
    keep ageing while somebody retries by hand."""
    import urllib.error

    calls = {"n": 0}

    def flaky(request, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("u", code, "boom", {}, None)

        class _R:
            def read(self):
                return b'{"ok": true}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return _R()

    monkeypatch.setattr(tw.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(tw.time, "sleep", lambda *_a: None)

    assert tw._get("https://example/x", "key") == {"ok": True}
    assert calls["n"] == 3


def test_a_non_transient_failure_is_NOT_retried(monkeypatch):
    """401 means the key is wrong; retrying nine times just delays the error."""
    import urllib.error

    calls = {"n": 0}

    def forbidden(request, timeout=0):
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 401, "nope", {}, None)

    monkeypatch.setattr(tw.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(tw.time, "sleep", lambda *_a: None)

    with pytest.raises(urllib.error.HTTPError):
        tw._get("https://example/x", "key")
    assert calls["n"] == 1


def test_the_threshold_default_sits_far_above_ordinary_hours():
    """Quiet hours are 0.2-0.5 MB and busy interactive ones 25-300 MB. The
    default must fire on the phenomenon, not on somebody using the board."""
    assert tw.DEFAULT_THRESHOLD_MB >= 500
    assert tw.DEFAULT_SETTLE_MINUTES >= 60


def _ts(hh_mm_ss: str, day: str = "2026-09-08") -> str:
    return f"{day}T{hh_mm_ss}.000000Z"


def test_an_emitter_that_DIES_inside_the_window_is_PARTIAL():
    """`09-08 23:00Z` now covers 23:00-00:00, and web's access-log emitter died
    at 23:45:58Z inside it. `app_blind` only catches a WHOLE dead hour, so
    without this the re-derived capture reads 46 minutes of lines as a small
    served total."""
    edge = [_ts(f"23:{m:02d}:10") for m in range(0, 60, 3)]
    access = [_ts(f"23:{m:02d}:10") for m in range(0, 46, 3)]

    gap = tw._emitter_gap(edge, access)

    assert gap is not None and "after the last access line" in gap


def test_an_emitter_that_RETURNS_inside_the_window_is_PARTIAL():
    """Restored 2026-09-09 ~14:38Z: the `14:00Z` bucket has lines only at the end."""
    edge = [_ts(f"14:{m:02d}:00", "2026-09-09") for m in range(0, 60, 4)]
    access = [_ts(f"14:{m:02d}:00", "2026-09-09") for m in range(40, 60, 4)]

    gap = tw._emitter_gap(edge, access)

    assert gap is not None and "before the first access line" in gap


def test_a_fully_logged_hour_is_NOT_partial():
    edge = [_ts(f"20:{m:02d}:00") for m in range(2, 58, 5)]
    access = [_ts(f"20:{m:02d}:01") for m in range(2, 58, 5)]

    assert tw._emitter_gap(edge, access) is None


def test_no_access_lines_at_all_is_left_to_the_blind_check():
    """Zero lines is `instrument_blind`, a different and stronger refusal."""
    assert tw._emitter_gap([_ts("20:10:00")], []) is None


def test_rederive_keeps_the_prior_windows_numbers():
    """Overwriting a capture must not destroy what it used to say: ledger
    entries quote those numbers, and they stay true of the hour BEFORE."""
    old = {
        "bucket": "2026-09-04T18:00:00Z", "captured_at": "2026-09-05T01:00:00Z",
        "window_covered": {"start": "2026-09-04T17:00:00Z", "end": "2026-09-04T18:00:00Z"},
        "metered_mb": 4050.1,
        "edge": {"mb": 2.6, "requests": 131},
        "app": {"served_mb": None, "access_lines": 0, "instrument_blind": True},
        "publish_into_web": {"refresh-worker": {"mb": 1.0}, "live-odds-worker": {"mb": 2.0}},
    }

    prior = tw._prior_numbers(old)

    assert prior["window_covered"]["start"] == "2026-09-04T17:00:00Z"
    assert prior["edge_mb"] == 2.6 and prior["edge_requests"] == 131
    assert prior["app_served_mb"] is None and prior["app_instrument_blind"] is True
    assert prior["publish_into_web_mb"] == 3.0


def test_capture_reads_EVERY_log_over_the_new_window(monkeypatch):
    """Reachability: the window moved in ONE helper, and a capture reads four
    logs through it. Assert every call actually used label..label+1h."""
    calls = []

    def fake_logs(key, resource, start, end, log_type, max_pages=tw.DEFAULT_MAX_LOG_PAGES, meta=None):
        calls.append((log_type, start, end))
        if meta is not None:
            meta.update({"truncated": False, "stop_reason": "reached window start",
                         "pages": 1, "lines": 0, "max_pages": max_pages, "oldest_reached": None})
        return []

    monkeypatch.setattr(tw, "_logs", fake_logs)
    monkeypatch.setattr(tw, "_get", lambda *a, **k: [])
    monkeypatch.setattr(tw, "_metric", lambda *a, **k: {})

    report = tw.capture("web", "2026-09-08T20:00:00Z", "key", metered_mb=220.7)

    assert report["window_covered"] == {"start": "2026-09-08T20:00:00Z", "end": "2026-09-08T21:00:00Z"}
    assert len(calls) == 4, calls
    assert all((s, e) == ("2026-09-08T20:00:00Z", "2026-09-08T21:00:00Z") for _t, s, e in calls), calls


# --- Trap 5: a page budget that runs out is a FLOOR, not a total -------------
#
# 2026-09-23: the 01:00Z web capture landed on exactly `log_lines: 20000` --
# 200 pages x 100 -- and published `served_mb: 395.62` as if it were the hour's
# total. `metered / app-served` computed from it read 1.04, which was really a
# ceiling. Neither `instrument_blind` nor `instrument_partial` can see this:
# both describe the EMITTER writing lines, this is the READER not asking for
# the rest of them.

_WINDOW = ("2026-09-23T01:00:00Z", "2026-09-23T02:00:00Z")


def _page_server(*, reach_start: bool, empty_after: int | None = None):
    """A fake log API. Every page is fresh, so only the budget can stop it."""
    state = {"n": 0}

    def fake_get(url, key):
        state["n"] += 1
        if empty_after is not None and state["n"] > empty_after:
            return {"logs": []}
        # Timestamps stay strictly INSIDE the window unless we want the pager
        # to terminate naturally, so `oldest <= start` never fires by accident.
        stamp = "2026-09-23T01:00:00Z" if reach_start else "2026-09-23T01:30:00Z"
        return {"logs": [{"id": f"p{state['n']}-{i}", "timestamp": stamp,
                          "message": "x", "labels": []} for i in range(100)]}

    return fake_get


def test_a_page_budget_that_RUNS_OUT_is_marked_truncated(monkeypatch):
    monkeypatch.setattr(tw, "_get", _page_server(reach_start=False))
    monkeypatch.setattr(tw.time, "sleep", lambda _s: None)
    meta = {}

    rows = tw._logs("key", "srv", *_WINDOW, "app", max_pages=3, meta=meta)

    assert len(rows) == 300, "3 pages x 100 lines"
    assert meta["truncated"] is True
    assert meta["stop_reason"] == "page budget exhausted"
    assert meta["pages"] == 3


def test_reaching_the_window_start_is_NOT_truncated(monkeypatch):
    """The OFF side of the flag. Without this, a constant True would pass."""
    monkeypatch.setattr(tw, "_get", _page_server(reach_start=True))
    monkeypatch.setattr(tw.time, "sleep", lambda _s: None)
    meta = {}

    tw._logs("key", "srv", *_WINDOW, "app", max_pages=3, meta=meta)

    assert meta["truncated"] is False
    assert meta["stop_reason"] == "reached window start"
    assert meta["pages"] == 1, "it must stop on the FIRST page that reaches start"


def test_running_out_of_lines_is_NOT_truncated(monkeypatch):
    monkeypatch.setattr(tw, "_get", _page_server(reach_start=False, empty_after=2))
    monkeypatch.setattr(tw.time, "sleep", lambda _s: None)
    meta = {}

    tw._logs("key", "srv", *_WINDOW, "app", max_pages=50, meta=meta)

    assert meta["truncated"] is False
    assert meta["stop_reason"] == "no more lines"


def test_an_UNKNOWN_stop_reason_counts_as_truncated():
    """Unknown must not default permissive.

    `_COMPLETE_STOPS` is an allowlist, so a stop reason added later without a
    decision lands on the SAFE branch (floor) rather than silently claiming a
    complete read.
    """
    assert "cursor stalled (a full page of duplicate ids)" not in tw._COMPLETE_STOPS
    assert set(tw._COMPLETE_STOPS) == {"reached window start", "no more lines"}


def _capture_with(monkeypatch, *, truncated: bool):
    access = '10.0.0.1 - - [23/Sep/2026:01:30:00 +0000] "GET /x HTTP/1.1" 200 1048576'

    def fake_logs(key, resource, start, end, log_type, max_pages=tw.DEFAULT_MAX_LOG_PAGES, meta=None):
        if meta is not None:
            meta.update({
                "truncated": truncated,
                "stop_reason": "page budget exhausted" if truncated else "reached window start",
                "pages": max_pages if truncated else 4, "lines": 1,
                "max_pages": max_pages, "oldest_reached": "2026-09-23T01:31:00Z",
            })
        if log_type == "app":
            return [("2026-09-23T01:30:00Z", access, {})]
        return [("2026-09-23T01:30:00Z", 'responseBytes=10 clientIP="1.2.3.4"', {})]

    monkeypatch.setattr(tw, "_logs", fake_logs)
    monkeypatch.setattr(tw, "_get", lambda *a, **k: [])
    monkeypatch.setattr(tw, "_metric", lambda *a, **k: {})
    return tw.capture("web", "2026-09-23T01:00:00Z", "key", metered_mb=411.944)


def test_a_truncated_app_read_makes_served_mb_a_FLOOR(monkeypatch):
    report = _capture_with(monkeypatch, truncated=True)

    assert report["app"]["served_is_floor"] is True
    assert report["app"]["read_truncated"] is True
    assert "NEVER READ" in report["app"]["floor_reason"]
    assert "2026-09-23T01:31:00Z" in report["app"]["floor_reason"], "say WHERE the read stopped"
    # The print path is where the 2026-09-23 misreading actually happened.
    assert _served_starts_with_ge(report["app"])
    assert tw._truncation_warnings(report), "a floor must produce a visible warning line"


def test_a_complete_app_read_is_NOT_a_floor(monkeypatch):
    """The OFF side again, at capture level."""
    report = _capture_with(monkeypatch, truncated=False)

    assert report["app"]["served_is_floor"] is False
    assert report["app"]["read_truncated"] is False
    assert "floor_reason" not in report["app"]
    assert not _served_starts_with_ge(report["app"])
    assert tw._truncation_warnings(report) == []


def _served_starts_with_ge(app: dict) -> bool:
    return tw._served_display(app).startswith(">=")


def test_a_dead_emitter_still_reads_as_UNREADABLE_not_as_a_floor():
    """Precedence: blind outranks floor. `served_mb` is None when blind, and
    `>= None MB` would be worse than the null it replaced."""
    assert tw._served_display({"instrument_blind": True, "served_is_floor": True,
                               "served_mb": None}) == "UNREADABLE (access-log emitter off)"


def test_the_default_budget_is_larger_than_the_one_that_truncated():
    """20,000 lines was not enough for a real spike hour on web."""
    assert tw.DEFAULT_MAX_LOG_PAGES * tw.LOG_PAGE_SIZE > 20_000


# --- --recomplete must never overwrite an expired window -------------------
#
# Render's log retention is why this tool exists at all. Re-reading a window
# whose logs have aged out returns a SMALLER read; writing that over the stored
# capture would destroy the only record of the hour.


def _report(app_lines, access, served, edge_reqs=10, edge_bytes=100, pub=None):
    return {
        "app": {"log_lines": app_lines, "access_lines": access, "served_bytes": served},
        "edge": {"requests": edge_reqs, "bytes": edge_bytes},
        "publish_into_web": pub or {"refresh-worker": {"publishes": 5, "bytes": 500}},
    }


def test_a_SHRINKING_read_is_refused_as_expired():
    stored = _report(20000, 4943, 414832767)
    fresh = _report(1200, 300, 30000000)

    regressions = tw._expiry_regressions(stored, fresh)

    assert regressions, "a smaller re-read must be refused"
    assert any("app.log_lines" in r for r in regressions)


def test_a_GROWING_read_is_accepted():
    """The OFF side: the whole point of the pass is that a complete read is
    LARGER than the truncated one it replaces."""
    stored = _report(20000, 4943, 414832767)
    fresh = _report(20120, 5010, 415775597)

    assert tw._expiry_regressions(stored, fresh) == []


def test_a_shrinking_PUBLISH_count_is_also_refused():
    """The worker logs aged out even though web's did not."""
    stored = _report(100, 10, 1000, pub={"refresh-worker": {"publishes": 264, "bytes": 288000000}})
    fresh = _report(100, 10, 1000, pub={"refresh-worker": {"publishes": 3, "bytes": 4000}})

    regressions = tw._expiry_regressions(stored, fresh)

    assert any("publish_into_web.refresh-worker.publishes" in r for r in regressions), regressions


def test_a_capture_with_no_read_block_needs_recompleting():
    """Every capture written before 2026-09-23 -- its truncation is UNKNOWN,
    which must not read as 'fine'."""
    assert tw._needs_recomplete(_report(20000, 4943, 414832767)) is True


def test_a_capture_already_read_completely_is_skipped():
    complete = _report(20120, 5010, 415775597)
    for section in ("app", "edge"):
        complete[section]["read"] = {"truncated": False}
        complete[section]["read_truncated"] = False
    complete["publish_into_web"]["refresh-worker"]["read"] = {"truncated": False}
    complete["publish_into_web"]["refresh-worker"]["read_truncated"] = False

    assert tw._needs_recomplete(complete) is False


def test_a_truncated_section_needs_recompleting_even_with_a_read_block():
    partly = _report(20000, 4943, 414832767)
    for section in ("app", "edge"):
        partly[section]["read"] = {"truncated": False}
        partly[section]["read_truncated"] = False
    partly["publish_into_web"]["refresh-worker"]["read"] = {"truncated": True}
    partly["publish_into_web"]["refresh-worker"]["read_truncated"] = True

    assert tw._needs_recomplete(partly) is True
