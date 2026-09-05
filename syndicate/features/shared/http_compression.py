"""Ask upstream APIs for gzip, on every `urllib` fetch this platform makes.

WHY. Measured 2026-09-05, lane `render-egress-transport`. A worker fetching
the public internet is BILLED egress -- it is the "Service-Initiated" half of
Render's bandwidth page, **5.06 GB of the month's 24.4 GB**. And every one of
those fetches pulls uncompressed.

**IT IS WORSE THAN "does not ask".** `http.client.HTTPConnection.putrequest`
sends `Accept-Encoding: identity` whenever the caller supplies no value of its
own -- an EXPLICIT REFUSAL of compression, on the wire, on every request. So
the **122 `urllib.request.Request` call sites across `syndicate/`, `scripts/`
and `pipeline/`** were not passively missing a header; they were actively
telling every upstream not to compress. (`requests` avoids this by always
setting its own.) Found by the control test in
`tests/test_http_compression.py`, which was written expecting an empty header
and asserted the real value instead. The upstreams all serve gzip already:

    ESPN CFB scoreboard ?groups=80&limit=200   1,441,192 -> 107,229   13.4x
    ESPN NFL scoreboard                          255,887 ->  20,912   12.2x
    MLB StatsAPI schedule                         21,296 ->   2,864    7.4x
    ESPN NBA scoreboard                            9,467 ->   2,095    4.5x

Worked example, from the lane that surfaced this: an ESPN college-football
scoreboard poll on a 180s tick costs 691 MB/day at one fetch per tick and
1.38 GB/day at two -- more than refresh-worker's ENTIRE bandwidth for Sep 1-5
(1.07 GB). The fix is the header, not a longer interval.

WHY A GLOBAL OPENER RATHER THAN 122 EDITS. `learnings.md`: fix the choke point
every caller shares, not the one you can see. `urllib.request.install_opener`
is that choke point -- `urlopen` routes through it, and nothing in this repo
builds its own opener (checked: zero `build_opener` / `install_opener` /
`OpenerDirector` uses outside this file), so nothing bypasses or clobbers it.
The alternative was editing 122 sites and having the 123rd arrive next week
without the header.

INSTALLED FROM `syndicate/__init__.py`, which is the ONLY module all three
services import: web enters via `wsgi:application` -> `syndicate.app`, and both
workers' `startCommand` scripts import `syndicate.features.shared.*`. An
import-time side effect is a real cost and it is taken deliberately, because
the two worker entrypoints are claimed by other OPEN lanes and the point of a
choke point is that it covers callers who never opted in.

THE ESPN HAZARD IS HANDLED, NOT ASSUMED AWAY. `schedule_adapter.py:377-386`
records ESPN returning **HTTP 403 to Render's outbound IP** for a bare
`User-Agent: Mozilla/5.0` while working with no custom UA at all -- so ESPN
demonstrably discriminates on request headers *specifically from Render*, and
the ratios above were measured from a dev machine, not from a worker. A header
this code adds must therefore be assumed capable of breaking a fetch that
worked. `_AcceptEncodingHandler.http_error_*` retries once WITHOUT the header
and remembers the host for the life of the process, so the failure mode is one
retried request rather than a dead feed. Nothing here is load-bearing on the
header being accepted.

WHAT IS DELIBERATELY NOT TOUCHED:

- A request that already sets `Accept-Encoding`. The caller decided.
- A request carrying `Range`. Range plus `Content-Encoding` is ambiguous about
  whether the range indexes the encoded or the decoded body, and
  `artifact_publisher.pull_streamed_artifact` fetches append-only shard TAILS
  by byte offset -- getting that wrong corrupts an artifact rather than merely
  costing bytes.
- The decoded stream is read INCREMENTALLY through `gzip.GzipFile`, so a 51 MB
  shard still costs one chunk of memory and not the whole body. That property
  is why `pull_streamed_artifact` exists at all.
"""

from __future__ import annotations

import gzip
import io
import os
import threading
import urllib.request
from typing import Any
from urllib.parse import urlparse

# Cumulative, process-local, and the REACHABILITY INSTRUMENT for this change.
# A silently-inert compression layer looks exactly like a working one, so the
# counters record both sides of every decoded response and a periodic line
# prints them. `decoded_bytes - wire_bytes` is the saving, measured rather
# than projected.
_STATS_LOCK = threading.Lock()
_STATS: dict[str, int] = {
    "requests_tagged": 0,
    "responses_gzip": 0,
    "responses_plain": 0,
    "wire_bytes": 0,
    "decoded_bytes": 0,
    "hosts_refused": 0,
    "retries_without_header": 0,
}

# Hosts that answered 4xx to a request carrying our header and succeeded
# without it. Process-local and cleared by a restart, exactly like
# `artifact_publisher._LAST_PUBLISHED_CHECKSUM`: this is a negotiation cache,
# not a config store, and "try again after a deploy" is the correct direction.
_REFUSING_HOSTS: set[str] = set()

_LOG_EVERY = 200

# Retried without the header, then remembered. 406 and 415 are the honest
# "cannot produce that representation" answers; 403 is in the list because it
# is what ESPN actually returned to Render for an unwelcome header, and the
# documented precedent outranks what the RFC says it should have sent.
_ENCODING_REFUSAL_STATUSES = (403, 406, 415)

_MARKER = "X-Syndicate-Added-Accept-Encoding"


def _enabled() -> bool:
    # ABSENT MEANS ON. `#284`'s rule is to state what absent means for any key
    # you add, and the answer here is deliberate: a service nobody has
    # configured should still stop pulling uncompressed.
    return str(os.environ.get("SYNDICATE_HTTP_GZIP") or "on").strip().lower() not in {
        "0",
        "off",
        "false",
        "no",
    }


def stats() -> dict[str, int]:
    """A copy of the counters. Cheap; safe to call from a route or a loop."""
    with _STATS_LOCK:
        snapshot = dict(_STATS)
    snapshot["saved_bytes"] = max(snapshot["decoded_bytes"] - snapshot["wire_bytes"], 0)
    return snapshot


def _bump(field: str, amount: int = 1) -> None:
    with _STATS_LOCK:
        _STATS[field] += amount
        should_log = field == "responses_gzip" and _STATS["responses_gzip"] % _LOG_EVERY == 0
        wire = _STATS["wire_bytes"]
        decoded = _STATS["decoded_bytes"]
        gzipped = _STATS["responses_gzip"]
        plain = _STATS["responses_plain"]
    if should_log:
        ratio = (decoded / wire) if wire else 0.0
        print(
            f"[http_compression] HTTP_COMPRESSION gzip_responses={gzipped} plain_responses={plain} "
            f"wire_bytes={wire} decoded_bytes={decoded} saved_bytes={max(decoded - wire, 0)} "
            f"ratio={ratio:.2f}x refused_hosts={len(_REFUSING_HOSTS)}",
            flush=True,
        )


class _CountingReader(io.RawIOBase):
    """Counts the bytes that actually crossed the wire, under the decoder."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        if chunk:
            _bump("wire_bytes", len(chunk))
        return chunk

    def readinto(self, buffer: Any) -> int:
        chunk = self.read(len(buffer))
        length = len(chunk)
        buffer[:length] = chunk
        return length

    def close(self) -> None:
        try:
            self._raw.close()
        finally:
            super().close()


class _GzipResponse(io.BufferedIOBase):
    """An `http.client.HTTPResponse` lookalike that gunzips as it is read.

    `gzip.GzipFile` over the socket, NOT `gzip.decompress` over a buffered
    body: callers here include ones that read 1 MB at a time out of a 51 MB
    artifact, and buffering the whole thing would trade billed bytes for
    resident bytes on a worker that has neither to spare.
    """

    def __init__(self, response: Any) -> None:
        self._response = response
        # Built BEFORE the headers are edited. If this raises, `http_response`
        # hands the caller the untouched original -- a response whose headers
        # had already been stripped would claim to be plain while carrying a
        # gzip body, which is worse than either outcome on its own.
        self._stream = gzip.GzipFile(fileobj=_CountingReader(response), mode="rb")
        headers = response.headers
        # Both of these describe the ENCODED body and stop being true here.
        # Leaving `Content-Length` in place would be a lie a caller could act
        # on; no caller in this repo reads it (checked), so deleting is safe
        # and honest rather than merely safe.
        del headers["Content-Encoding"]
        del headers["Content-Length"]
        self.headers = headers
        self.status = getattr(response, "status", None)
        self.code = self.status
        self.reason = getattr(response, "reason", "")
        self.msg = getattr(response, "msg", "")
        self._url = response.geturl()

    def read(self, size: int | None = -1) -> bytes:
        # `read(None)` is how `json.load` and `shutil.copyfileobj` ask for
        # "everything"; GzipFile spells that -1.
        chunk = self._stream.read(-1 if size is None else size)
        if chunk:
            _bump("decoded_bytes", len(chunk))
        return chunk

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)

    def readline(self, size: int = -1) -> bytes:  # type: ignore[override]
        line = self._stream.readline(size)
        if line:
            _bump("decoded_bytes", len(line))
        return line

    def readable(self) -> bool:
        return True

    def info(self) -> Any:
        return self.headers

    def geturl(self) -> str:
        return self._url

    def getcode(self) -> int | None:
        return self.status

    def getheader(self, name: str, default: Any = None) -> Any:
        return self.headers.get(name, default)

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            try:
                self._response.close()
            finally:
                super().close()

    def __enter__(self) -> "_GzipResponse":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class _AcceptEncodingHandler(urllib.request.BaseHandler):
    # Late, so a caller's own Accept-Encoding is already on the request and
    # visible to `has_header` by the time this runs.
    handler_order = 900

    def http_request(self, request: Any) -> Any:
        if not _enabled():
            return request
        # `Request.has_header` capitalises, so this matches a caller who wrote
        # the header in any casing.
        if request.has_header("Accept-encoding") or request.has_header("Range"):
            return request
        try:
            host = urlparse(request.full_url).hostname or ""
        except Exception:
            host = ""
        if host and host in _REFUSING_HOSTS:
            return request
        request.add_header("Accept-Encoding", "gzip")
        request.add_header(_MARKER, "1")
        _bump("requests_tagged")
        return request

    https_request = http_request

    def http_response(self, request: Any, response: Any) -> Any:
        encoding = str(response.headers.get("Content-Encoding") or "").strip().lower()
        if encoding != "gzip":
            if request.has_header(_MARKER.capitalize()):
                _bump("responses_plain")
            return response
        _bump("responses_gzip")
        try:
            return _GzipResponse(response)
        except Exception:
            # A malformed gzip header must degrade to the caller's own error
            # handling on the raw body, never to an exception raised out of a
            # transport layer nobody asked for.
            return response

    https_response = http_response

    def _retry_without_header(self, request: Any, response: Any, code: int) -> Any:
        """Re-issue once without our header, and remember the host if it works.

        THIS IS THE ESPN CASE, and it is the whole reason this handler is
        allowed to touch every request in the platform. ESPN answers 403 to
        Render's outbound IP for header shapes it dislikes
        (`schedule_adapter.py:377-386`), and these ratios were measured from a
        dev machine. If the header breaks a fetch, the fetch must still
        happen.
        """
        if not request.has_header(_MARKER.capitalize()):
            return None
        host = ""
        try:
            host = urlparse(request.full_url).hostname or ""
        except Exception:
            host = ""

        retry = urllib.request.Request(
            request.full_url,
            data=request.data,
            method=request.get_method(),
        )
        for key, value in request.header_items():
            if key.lower() in {"accept-encoding", _MARKER.lower()}:
                continue
            retry.add_header(key, value)

        # ADDING THE HOST HERE IS WHAT STOPS THE RECURSION: `http_request`
        # skips a host in this set, so the retry goes out bare. It is removed
        # again below if the retry fails the SAME way, because then the header
        # was never the problem and marking the host would silently cost this
        # process compression on a host that was fine.
        if host:
            _REFUSING_HOSTS.add(host)
        _bump("retries_without_header")
        try:
            response.close()
        except Exception:
            pass
        try:
            retried = self.parent.open(retry, timeout=getattr(request, "timeout", None))
        except Exception:
            if host:
                _REFUSING_HOSTS.discard(host)
            return None
        if host:
            _bump("hosts_refused")
        print(
            f"[http_compression] ACCEPT_ENCODING_REFUSED host={host or '?'} status={code} "
            "retried_without_header=1 ok=1 -- this host is served uncompressed for the life "
            "of this process; a restart re-arms it.",
            flush=True,
        )
        return retried

    def http_error_403(self, request: Any, response: Any, code: int, msg: str, headers: Any) -> Any:
        return self._retry_without_header(request, response, code)

    def http_error_406(self, request: Any, response: Any, code: int, msg: str, headers: Any) -> Any:
        return self._retry_without_header(request, response, code)

    def http_error_415(self, request: Any, response: Any, code: int, msg: str, headers: Any) -> Any:
        return self._retry_without_header(request, response, code)


_INSTALLED = False
_INSTALL_LOCK = threading.Lock()


def install_http_compression() -> bool:
    """Install the global opener. Idempotent, and never raises.

    Returns True if this call installed it, False if it was already installed
    or the kill switch is set -- so a caller can log which happened rather
    than assume.
    """
    global _INSTALLED

    if not _enabled():
        return False
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        try:
            urllib.request.install_opener(
                urllib.request.build_opener(_AcceptEncodingHandler())
            )
            _INSTALLED = True
            return True
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[http_compression] INSTALL_FAILED error={exc}", flush=True)
            return False


def _reset_for_tests() -> None:
    """Test-only. Undoes the install so a test can assert `off != on`."""
    global _INSTALLED

    with _INSTALL_LOCK:
        _INSTALLED = False
    urllib.request.install_opener(urllib.request.build_opener())
    _REFUSING_HOSTS.clear()
    with _STATS_LOCK:
        for key in _STATS:
            _STATS[key] = 0
