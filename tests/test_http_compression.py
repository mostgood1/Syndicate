"""Tests for the outbound `Accept-Encoding: gzip` opener.

Driven against a REAL local HTTP server through REAL `urllib.request.urlopen`,
not a mocked handler. The thing under test is whether a global opener changes
what 122 un-modified call sites do, and a fake `urlopen` is exactly the seam
that would hide the answer.

The order these assert in is deliberate (`learnings.md`, reachability before
correctness): first that the header is actually sent and the body actually
arrives smaller, then that the decoded bytes are right, then the three ways it
must decline to act.
"""

from __future__ import annotations

import gzip
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from syndicate.features.shared import http_compression as hc


def _payload(rows: int = 500) -> bytes:
    """Shaped like the feeds this exists for -- repeated JSON keys."""
    return json.dumps(
        [{"id": i, "home": "TEAM_A", "away": "TEAM_B", "status": "pre"} for i in range(rows)]
    ).encode("utf-8")


BODY = _payload()


class _Handler(BaseHTTPRequestHandler):
    # Set per-test on the server object.
    refuse_encoding = False
    seen: list[dict[str, str]] = []

    def log_message(self, *_args):  # noqa: D102 - silence the test server
        return

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        accept = self.headers.get("Accept-Encoding", "")
        rng = self.headers.get("Range", "")
        type(self).seen.append({"accept_encoding": accept, "range": rng, "path": self.path})

        if type(self).refuse_encoding and "gzip" in accept:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if "gzip" in accept:
            body = gzip.compress(BODY, 1)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)


@pytest.fixture
def server():
    _Handler.refuse_encoding = False
    _Handler.seen = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(autouse=True)
def clean_opener(monkeypatch):
    """Every test starts from no opener, and leaves none behind.

    `install_http_compression` mutates PROCESS-GLOBAL urllib state, so a test
    that installed it and did not clean up would silently change the meaning
    of every later test in the session.
    """
    monkeypatch.delenv("SYNDICATE_HTTP_GZIP", raising=False)
    hc._reset_for_tests()
    yield
    hc._reset_for_tests()


def test_without_the_opener_urllib_refuses_compression_outright(server):
    """The control, and it is worse than "no header".

    `http.client.putrequest` sends `Accept-Encoding: identity` unless the
    caller supplies one -- an EXPLICIT REFUSAL. So all 122 un-modified call
    sites were not merely failing to ask for gzip, they were actively telling
    every upstream not to compress. Asserted rather than assumed, because if a
    future Python changed this default the `off != on` tests below would
    quietly stop meaning anything.
    """
    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        body = response.read()

    assert body == BODY
    assert _Handler.seen[-1]["accept_encoding"] == "identity"


def test_installed_opener_asks_for_gzip_and_shrinks_the_wire(server):
    assert hc.install_http_compression() is True

    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        body = response.read()

    # Correctness: the caller sees the same bytes it always saw.
    assert body == BODY
    assert json.loads(body.decode("utf-8"))[0]["home"] == "TEAM_A"
    # Reachability: the header went out, and the wire body really was smaller.
    assert "gzip" in _Handler.seen[-1]["accept_encoding"]
    stats = hc.stats()
    assert stats["responses_gzip"] == 1
    assert stats["decoded_bytes"] == len(BODY)
    assert stats["wire_bytes"] < len(BODY) / 4
    assert stats["saved_bytes"] == stats["decoded_bytes"] - stats["wire_bytes"]


def test_decoded_response_still_looks_like_an_http_response(server):
    hc.install_http_compression()

    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        assert response.status == 200
        assert response.getcode() == 200
        assert response.geturl().endswith("/feed")
        # Both headers described the ENCODED body and must be gone.
        assert response.headers.get("Content-Encoding") is None
        assert response.headers.get("Content-Length") is None
        assert response.headers.get("Content-Type") == "application/json"
        assert json.load(response)[0]["away"] == "TEAM_B"


def test_chunked_reads_stream_rather_than_buffer(server):
    """`pull_streamed_artifact` reads 1 MB at a time out of 51 MB shards.

    A decoder that only worked for `read()` would trade billed bytes for
    resident bytes on a worker that has neither spare.
    """
    hc.install_http_compression()

    chunks = []
    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        while True:
            chunk = response.read(997)
            if not chunk:
                break
            assert len(chunk) <= 997
            chunks.append(chunk)

    assert b"".join(chunks) == BODY
    assert len(chunks) > 1


def test_kill_switch_restores_the_old_behaviour(server, monkeypatch):
    monkeypatch.setenv("SYNDICATE_HTTP_GZIP", "off")

    assert hc.install_http_compression() is False
    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        assert response.read() == BODY
    assert "gzip" not in _Handler.seen[-1]["accept_encoding"]


def test_a_caller_that_set_its_own_accept_encoding_is_left_alone(server):
    hc.install_http_compression()

    request = urllib.request.Request(f"{server}/feed", headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.read() == BODY

    assert _Handler.seen[-1]["accept_encoding"] == "identity"


def test_a_range_request_is_left_alone(server):
    """Range + Content-Encoding is ambiguous about what the offsets index.

    `pull_streamed_artifact` fetches append-only shard TAILS by byte offset;
    getting this wrong corrupts an artifact rather than merely costing bytes.
    """
    hc.install_http_compression()

    request = urllib.request.Request(f"{server}/feed", headers={"Range": "bytes=100-"})
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()

    assert "gzip" not in _Handler.seen[-1]["accept_encoding"]
    assert _Handler.seen[-1]["range"] == "bytes=100-"


def test_a_host_that_403s_the_header_is_retried_bare_and_remembered(server):
    """THE ESPN CASE.

    `schedule_adapter.py:377-386` records ESPN answering 403 to Render's
    outbound IP over a header it disliked, and the compression ratios were
    measured from a dev machine. If this header breaks a fetch, the fetch must
    still happen.
    """
    hc.install_http_compression()
    _Handler.refuse_encoding = True

    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        assert response.read() == BODY

    # Two requests: the refused one, then the bare retry.
    assert "gzip" in _Handler.seen[0]["accept_encoding"]
    assert "gzip" not in _Handler.seen[1]["accept_encoding"]
    assert hc.stats()["retries_without_header"] == 1
    assert hc.stats()["hosts_refused"] == 1

    # And it is REMEMBERED -- the next call must not pay for the round trip.
    _Handler.seen = []
    with urllib.request.urlopen(urllib.request.Request(f"{server}/other"), timeout=10) as response:
        assert response.read() == BODY
    assert len(_Handler.seen) == 1
    assert "gzip" not in _Handler.seen[0]["accept_encoding"]


def test_a_genuine_403_is_not_blamed_on_the_header(server):
    """A 403 that persists without the header must not mark the host.

    Otherwise one unrelated permission error silently costs this process
    compression on that host for the rest of its life, and nothing says so.
    """
    hc.install_http_compression()

    class _AlwaysForbidden(_Handler):
        def do_GET(self):  # noqa: N802
            type(self).seen.append(
                {"accept_encoding": self.headers.get("Accept-Encoding", ""), "range": "", "path": self.path}
            )
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()

    httpd = HTTPServer(("127.0.0.1", 0), _AlwaysForbidden)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _AlwaysForbidden.seen = []
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/feed"
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(urllib.request.Request(url), timeout=10)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert hc.stats()["hosts_refused"] == 0


def test_install_is_idempotent():
    assert hc.install_http_compression() is True
    assert hc.install_http_compression() is False


def test_traffic_class_splits_billed_from_unbilled():
    """The unsplit total is not an answer to the question this module exists for.

    Internal worker->web transport is not billed (measured 2026-09-05: 5,243 MB
    of it metered 33.9 MB), so a combined "saved 687 MB" mixes a real bandwidth
    saving with a memory saving. Unknown must resolve to EXTERNAL so the billed
    figure over-estimates rather than flatters.
    """
    assert hc._traffic_class("syndicate-an21") == "internal"      # Render service name, no dot
    assert hc._traffic_class("10.197.59.162") == "internal"
    assert hc._traffic_class("127.0.0.1") == "internal"
    assert hc._traffic_class("localhost") == "internal"
    assert hc._traffic_class("site.api.espn.com") == "external"
    assert hc._traffic_class("statsapi.mlb.com") == "external"
    assert hc._traffic_class("") == "external"                     # unknown -> billed
    assert hc._traffic_class("172.32.0.1") == "external"           # just outside the private range


def test_a_loopback_fetch_counts_as_internal_not_billed(server):
    """The test server is 127.0.0.1, so its bytes must NOT land in the billed bucket."""
    hc.install_http_compression()

    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        response.read()

    stats = hc.stats()
    assert stats["responses_gzip"] == 1
    assert stats["responses_gzip_internal"] == 1
    assert stats["responses_gzip_external"] == 0
    assert stats["decoded_bytes_internal"] == len(BODY)
    # The billed figure stays at zero for unbilled traffic -- the whole point.
    assert stats["saved_bytes_external"] == 0
    assert stats["saved_bytes_internal"] > 0


def test_the_first_response_logs_immediately(server, capfd):
    """An instrument whose first reading needs 200 events cannot verify its own deploy.

    That is not hypothetical: it is exactly what happened on the 2026-09-05
    refresh-worker deploy, where HTTP_COMPRESSION was silent at T+10min and the
    silence was indistinguishable from an unreachable emitter.
    """
    hc.install_http_compression()

    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        response.read()

    out = capfd.readouterr().out
    assert "HTTP_COMPRESSION" in out, "the FIRST gzip response must log, not the 200th"
    assert "gzip_responses=1 " in out
    assert "BILLED_saved_bytes=" in out


def test_the_split_reconciles_with_the_total(server):
    """internal + external == total, in both directions.

    Guards the accounting itself: a class counter that silently diverges from
    the aggregate would make the BILLED figure wrong in a way no ratio looks
    odd enough to catch.
    """
    hc.install_http_compression()
    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        response.read()

    s = hc.stats()
    assert s["decoded_bytes"] == s["decoded_bytes_internal"] + s["decoded_bytes_external"]
    assert s["wire_bytes"] == s["wire_bytes_internal"] + s["wire_bytes_external"]
    assert s["responses_gzip"] == s["responses_gzip_internal"] + s["responses_gzip_external"]


def test_the_first_line_reports_a_real_billed_ratio(server, capfd, monkeypatch):
    """REGRESSION. The first line reported BILLED_ratio=0.00x on a 12.9x fetch.

    The aggregate `decoded_bytes` bump is what fires the log, and it was
    landing BEFORE its paired class bump -- so the line was printed from a
    half-updated state, with the billed wire bytes counted and the billed
    decoded bytes not yet. A line of zeros that looks like an answer is worse
    than silence, which is the same failure this early-logging exists to fix.
    """
    monkeypatch.setattr(hc, "_traffic_class", lambda host: "external")
    hc.install_http_compression()

    with urllib.request.urlopen(urllib.request.Request(f"{server}/feed"), timeout=10) as response:
        response.read()

    line = [l for l in capfd.readouterr().out.splitlines() if "HTTP_COMPRESSION" in l][0]
    assert "BILLED_ratio=0.00x" not in line, line
    assert "BILLED_saved_bytes=0 " not in line, line
    s = hc.stats()
    assert s["saved_bytes_external"] > 0
    assert s["saved_bytes_internal"] == 0
