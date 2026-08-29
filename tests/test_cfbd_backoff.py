"""Tests for the shared CFBD retry policy and, first, that it is REACHED.

REACHABILITY BEFORE CORRECTNESS (`model_engine_standard.md`). A policy module
with perfect unit tests that no call site imports is inert, and inert is
indistinguishable from working at every level except production. So the first
two tests here drive the REAL `_cfbd_get` and the REAL `CfbdClient._get_json`
with a transport that returns 429, and assert the call survives it -- those fail
if the wiring is removed, which the pure-policy tests below would not.
"""

from __future__ import annotations

import sys
import urllib.error
from email.utils import formatdate
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf import cfbd_backoff


def _http_error(status: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("https://api.collegefootballdata.com/ppa/teams", status, "boom", headers, None)


# --------------------------------------------------------------------------
# REACHABILITY -- these fail if the call sites stop using the policy.
# --------------------------------------------------------------------------


def test_projection_scripts_cfbd_get_survives_a_429(monkeypatch):
    """The exact production failure: `/ppa/teams` 429s, then succeeds.

    Drives `generate_smartsim2_ncaaf_projections._cfbd_get` itself rather than
    the policy, because the 2026-08-29 outage was a MISSING `except`, not a
    wrong delay. Remove the `call_with_retry` wrapper and this test fails.
    """
    import importlib

    module = importlib.import_module("scripts.generate_smartsim2_ncaaf_projections")
    monkeypatch.setenv("CFBD_API_KEY", "test-key")

    calls = {"n": 0}

    class _Response:
        def read(self):
            return b'[{"team": "Georgia"}]'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def _fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _http_error(429, "0")
        return _Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(cfbd_backoff.time, "sleep", lambda _seconds: None)

    assert module._cfbd_get("/ppa/teams", {"year": 2025}) == [{"team": "Georgia"}]
    assert calls["n"] == 3, "the two 429s must have been retried, not swallowed or raised"


def test_cfbd_client_get_json_survives_a_429(monkeypatch):
    """The OTHER entry point -- ten snapshot builders share this key and quota."""
    requests = pytest.importorskip("requests")
    from syndicate.features.ncaaf.cfbd import CfbdClient

    client = CfbdClient("test-key")
    calls = {"n": 0}

    class _Response:
        def __init__(self, status):
            self.status_code = status
            self.headers = {"Retry-After": "0"}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError("boom", response=self)

        def json(self):
            return [{"team": "Georgia"}]

    def _fake_get(url, **_kwargs):
        calls["n"] += 1
        return _Response(429 if calls["n"] == 1 else 200)

    monkeypatch.setattr(client.session, "get", _fake_get)
    monkeypatch.setattr(cfbd_backoff.time, "sleep", lambda _seconds: None)

    assert client._get_json("/teams/fbs", params={"year": 2026}) == [{"team": "Georgia"}]
    assert calls["n"] == 2


# --------------------------------------------------------------------------
# POLICY
# --------------------------------------------------------------------------


def test_a_non_retryable_status_gives_up_immediately():
    """401 does not improve with waiting. Retrying it turns a clear error slow."""
    assert cfbd_backoff.retry_delay_seconds(status=401, attempt=1, rng=lambda: 1.0) is None
    assert cfbd_backoff.retry_delay_seconds(status=404, attempt=1, rng=lambda: 1.0) is None


def test_429_and_5xx_are_retryable():
    for status in (429, 500, 502, 503, 504):
        assert cfbd_backoff.retry_delay_seconds(status=status, attempt=1, rng=lambda: 1.0) is not None


def test_the_last_attempt_returns_none_rather_than_a_delay():
    """None is the ONLY stop signal, so it must arrive at the attempt cap."""
    assert cfbd_backoff.retry_delay_seconds(status=429, attempt=cfbd_backoff.MAX_ATTEMPTS, rng=lambda: 1.0) is None
    assert cfbd_backoff.retry_delay_seconds(status=429, attempt=cfbd_backoff.MAX_ATTEMPTS - 1, rng=lambda: 1.0) is not None


def test_backoff_grows_between_attempts():
    delays = [
        cfbd_backoff.retry_delay_seconds(status=429, attempt=n, rng=lambda: 1.0)
        for n in range(1, cfbd_backoff.MAX_ATTEMPTS)
    ]
    assert delays == sorted(delays)
    assert delays[0] < delays[-1]


def test_jitter_actually_scales_the_delay():
    """Full jitter, so ten builders throttled at once do not resynchronise."""
    high = cfbd_backoff.retry_delay_seconds(status=429, attempt=2, rng=lambda: 1.0)
    low = cfbd_backoff.retry_delay_seconds(status=429, attempt=2, rng=lambda: 0.1)
    assert low < high


def test_retry_after_seconds_is_obeyed_over_our_guess():
    delay = cfbd_backoff.retry_delay_seconds(status=429, attempt=1, retry_after="7", rng=lambda: 1.0)
    assert delay == pytest.approx(7.0)


def test_retry_after_is_capped_so_one_header_cannot_park_the_subprocess():
    """A 3600s `Retry-After` would hold `_season_projection_process_still_running`
    for an hour and block every later launch of that sport."""
    delay = cfbd_backoff.retry_delay_seconds(status=429, attempt=1, retry_after="3600", rng=lambda: 1.0)
    assert delay == pytest.approx(cfbd_backoff.MAX_DELAY_SECONDS)


def test_retry_after_accepts_an_http_date():
    header = formatdate(timeval=None, usegmt=True)
    assert cfbd_backoff.parse_retry_after(header) is not None


def test_an_unparseable_retry_after_falls_back_rather_than_waiting_zero():
    """None must mean 'the server did not tell us', never 'wait zero'."""
    assert cfbd_backoff.parse_retry_after("soon") is None
    assert cfbd_backoff.parse_retry_after("") is None
    assert cfbd_backoff.parse_retry_after(None) is None
    delay = cfbd_backoff.retry_delay_seconds(status=429, attempt=1, retry_after="soon", rng=lambda: 1.0)
    assert delay == pytest.approx(cfbd_backoff.BASE_DELAY_SECONDS)


def test_total_sleep_is_bounded():
    """The ceiling exists because the worker does not wait on this subprocess."""
    assert (
        cfbd_backoff.retry_delay_seconds(
            status=429, attempt=1, slept_so_far=cfbd_backoff.MAX_TOTAL_SLEEP_SECONDS, rng=lambda: 1.0
        )
        is None
    )
    remaining = cfbd_backoff.retry_delay_seconds(
        status=429, attempt=1, retry_after="30", slept_so_far=cfbd_backoff.MAX_TOTAL_SLEEP_SECONDS - 5, rng=lambda: 1.0
    )
    assert remaining == pytest.approx(5.0)


# --------------------------------------------------------------------------
# EXECUTOR
# --------------------------------------------------------------------------


def test_call_with_retry_reraises_the_original_exception_after_exhausting():
    """A wrapper exception would have hidden the `HTTP Error 429 ... in
    _cfbd_get` line that made this diagnosable in the first place."""
    slept: list[float] = []

    def _always_429():
        raise _http_error(429, "0")

    with pytest.raises(urllib.error.HTTPError) as caught:
        cfbd_backoff.call_with_retry(
            _always_429,
            classify=lambda exc: (exc.code, None),
            sleep=slept.append,
            rng=lambda: 1.0,
        )
    assert caught.value.code == 429
    assert len(slept) == cfbd_backoff.MAX_ATTEMPTS - 1


def test_an_unclassified_exception_is_never_swallowed_into_the_retry_loop():
    """`classify` returning None must re-raise at once -- a bug this backoff does
    not understand must not be reported as a rate limit."""
    slept: list[float] = []

    def _boom():
        raise ValueError("not an http error")

    with pytest.raises(ValueError):
        cfbd_backoff.call_with_retry(_boom, classify=lambda _exc: None, sleep=slept.append)
    assert slept == [], "an unclassified error must not have waited"


def test_a_connection_error_is_not_retried_by_either_classifier():
    """A real outage must fail fast rather than sit behind three minutes of
    sleeping -- see both classifiers' docstrings."""
    import importlib

    module = importlib.import_module("scripts.generate_smartsim2_ncaaf_projections")
    assert module._classify_cfbd_error(urllib.error.URLError("no route to host")) is None

    from syndicate.features.ncaaf.cfbd import _classify_requests_error

    assert _classify_requests_error(ValueError("no response attribute")) is None
