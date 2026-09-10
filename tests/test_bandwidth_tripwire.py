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

    def fake_logs(key, resource, start, end, log_type, max_pages=200):
        calls.append((log_type, start, end))
        return []

    monkeypatch.setattr(tw, "_logs", fake_logs)
    monkeypatch.setattr(tw, "_get", lambda *a, **k: [])
    monkeypatch.setattr(tw, "_metric", lambda *a, **k: {})

    report = tw.capture("web", "2026-09-08T20:00:00Z", "key", metered_mb=220.7)

    assert report["window_covered"] == {"start": "2026-09-08T20:00:00Z", "end": "2026-09-08T21:00:00Z"}
    assert len(calls) == 4, calls
    assert all((s, e) == ("2026-09-08T20:00:00Z", "2026-09-08T21:00:00Z") for _t, s, e in calls), calls
