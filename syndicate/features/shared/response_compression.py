"""gzip Syndicate's HTTP responses.

THIS IS NOT A FIX FOR THE RENDER BANDWIDTH BILL. READ THIS BEFORE CREDITING IT
WITH ONE. It was built for that in lane `render-egress-transport` on
2026-09-05, and the attribution it was built on was RETRACTED the same session
before deploying: internal service-to-service traffic is NOT billed (2026-09-05
04:00-05:00Z carried 5,243 MB of it and metered 33.9 MB), and Render's edge
ALREADY gzips public responses for any client that sends `Accept-Encoding`
(measured on the same requests in two logs: 198.8 MB at the origin, 4.2 MB at
the edge). `lanes.md` carries the full retraction and the three eliminated
hypotheses.

WHAT IT IS ACTUALLY WORTH, which is why it was kept rather than reverted. The
bytes it removes are real even though they are not billed:

    /api/ops/artifacts/export?pattern=*<date>*      15.4 MB, every ~90s, x2 workers
    /api/ops/artifacts/export?pattern=*book_quotes* 80-199 MB per call
    /api/intelligence/query                         53-67 MB per call

Every one of those is materialised WHOLE inside a 2 GB web process that `#632`
has shown does not return memory between requests, and a parallel lane took
HTTP 502 off this endpoint twice under ordinary reads. Smaller bodies mean less
socket time holding that buffer, less worker time on the far side, and a real
saving for the one class of caller the edge cannot help: clients that never
send `Accept-Encoding` at all, which includes `Python-urllib` -- i.e. every
worker and every script in this repo.

THE RATIO IS MEASURED, NOT ASSUMED. `mlb_source/tracking/book_quotes/
2026-07-07.jsonl`, 13.92 MB on disk: gzip level 1 -> 0.49 MB (**3.5%**) in
0.20s; level 6 -> 0.33 MB (2.4%) in 0.41s. The `.state.json` sibling,
1.40 MB -> 0.13 MB (9.0%). Odds capture is line-oriented JSON with enormous
key repetition, which is the best case gzip has.

LEVEL 1 ON PURPOSE. Level 6 buys another 1.1 points of ratio for 2x the CPU,
on a 2 GB web service that has an open OOM investigation (`#632`) and is the
one service that must stay responsive. 3.5% is already a 28x cut.

WHAT THIS DELIBERATELY DOES NOT TOUCH:

- `direct_passthrough` responses. `send_file` (which is what
  `/api/ops/artifacts/stream` uses) hands back a file wrapper precisely so the
  body never lands in memory; calling `get_data()` on it would buffer the whole
  artifact and re-create the 2 GB-instance problem the streaming form exists to
  avoid. Those bodies are already served in 1 MB reads and are left alone.
- Anything already carrying `Content-Encoding`.
- Bodies below `_MIN_BYTES`, where the gzip header costs more than it saves.

`Vary: Accept-Encoding` is set on every response we CONSIDERED compressing,
not only the ones we did -- a cache that stored an uncompressed body under a
key that ignores the request's encoding would serve it to a client that got
the compressed variant, and vice versa.
"""

from __future__ import annotations

import os
import zlib
from typing import Any

# Streamed rather than `gzip.compress(data)` so peak memory is the COMPRESSED
# output plus one chunk, not a second full copy of the body. On the 80-199 MB
# book_quotes exports measured above that is the difference between ~7 MB and
# ~199 MB of extra resident bytes on a 2 GB instance.
_CHUNK_BYTES = 256 * 1024

# Below this, the 20-byte gzip envelope plus the CPU is not worth it, and the
# response was never going to matter to the bill.
_DEFAULT_MIN_BYTES = 4096

# Prefix match, so `application/json; charset=utf-8` and the `+json` suffix
# types are covered. Everything absent from this list (images, pdf, zip,
# gzip, protobuf) is either already compressed or not worth the CPU.
_COMPRESSIBLE_PREFIXES = (
    "application/json",
    "application/javascript",
    "application/manifest+json",
    "application/xml",
    "image/svg+xml",
    "text/",
)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _enabled() -> bool:
    # ON by default, and the kill switch is a value check rather than a
    # presence check: `absent` must mean `on` here, because the whole point is
    # that a service which has not been told anything still stops paying for
    # uncompressed artifact transport.
    return _env("SYNDICATE_RESPONSE_GZIP", "on").lower() not in {"0", "off", "false", "no"}


def _min_bytes() -> int:
    try:
        value = int(_env("SYNDICATE_RESPONSE_GZIP_MIN_BYTES", str(_DEFAULT_MIN_BYTES)))
    except ValueError:
        return _DEFAULT_MIN_BYTES
    return max(value, 0)


def _level() -> int:
    try:
        value = int(_env("SYNDICATE_RESPONSE_GZIP_LEVEL", "1"))
    except ValueError:
        return 1
    return min(max(value, 1), 9)


def gzip_bytes(payload: bytes, *, level: int = 1) -> bytes:
    """gzip `payload`, holding one chunk at a time on the input side."""
    # wbits = 16 + MAX_WBITS selects the gzip container (header + CRC32 +
    # length trailer), which is what `Content-Encoding: gzip` means. Plain
    # `zlib.compress` emits a zlib container, which is `deflate`, and browsers
    # disagree about that one -- a real interop trap, not a style preference.
    compressor = zlib.compressobj(level, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    out = bytearray()
    for start in range(0, len(payload), _CHUNK_BYTES):
        out += compressor.compress(payload[start : start + _CHUNK_BYTES])
    out += compressor.flush()
    return bytes(out)


def client_accepts_gzip(accept_encoding: str) -> bool:
    """True when the client advertised gzip and did not explicitly refuse it.

    `gzip;q=0` is a REFUSAL, and it is the one form where a substring test
    gets the answer backwards.
    """
    for part in str(accept_encoding or "").split(","):
        token = part.strip().lower()
        if not token:
            continue
        name, _, params = token.partition(";")
        if name.strip() not in {"gzip", "*"}:
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.partition("=")
            if key.strip() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 1.0
        if quality > 0.0:
            return True
    return False


def _is_compressible_type(content_type: str) -> bool:
    lowered = str(content_type or "").split(";")[0].strip().lower()
    return any(lowered.startswith(prefix) for prefix in _COMPRESSIBLE_PREFIXES)


def compress_response(response: Any, accept_encoding: str) -> Any:
    """Compress `response` in place when it is safe and worthwhile.

    Returns the same response object either way, so this is a drop-in
    `after_request` body.
    """
    if not _enabled():
        return response

    # A passthrough response has no body to read without buffering the file.
    # See the module docstring: touching these would undo the streaming form.
    if getattr(response, "direct_passthrough", False):
        return response
    if response.headers.get("Content-Encoding"):
        return response
    if not _is_compressible_type(response.headers.get("Content-Type", "")):
        return response

    # 204/304 have no body by definition; a 3xx/4xx/5xx body is small and its
    # latency matters more than its bytes.
    if response.status_code not in {200, 201, 202}:
        return response

    # Set Vary before the size test, not after. A response we declined to
    # compress for being small is still served from the same URL as one we
    # did, and a shared cache keyed without Accept-Encoding would mix them.
    vary = response.headers.get("Vary", "")
    if "accept-encoding" not in vary.lower():
        response.headers["Vary"] = f"{vary}, Accept-Encoding".strip(", ") if vary else "Accept-Encoding"

    if not client_accepts_gzip(accept_encoding):
        return response

    payload = response.get_data()
    if len(payload) < _min_bytes():
        return response

    compressed = gzip_bytes(payload, level=_level())
    # A body that grew is a body that should not have been compressed. Rare for
    # JSON, but cheap to check and it keeps the invariant "we never make a
    # response bigger" true rather than merely likely.
    if len(compressed) >= len(payload):
        return response

    response.set_data(compressed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(compressed))
    # ETags upstream are computed over the UNCOMPRESSED body. A strong ETag
    # asserts byte equality, which stops being true the moment the body is
    # re-encoded, so weaken it rather than leaving a lie in the header.
    etag = response.headers.get("ETag")
    if etag and not etag.startswith("W/"):
        response.headers["ETag"] = f"W/{etag}"
    return response


def install_response_compression(app: Any) -> None:
    """Register the after_request hook on a Flask app.

    Registered UNCONDITIONALLY, with the WORK gated by the env check inside
    `compress_response` -- same rule as `#241`'s memory hook two hundred lines
    up in `app.py`: a hook installed only when a key is set at import time
    cannot be turned on by an env change, and someone would set the key, see
    nothing, and draw the wrong conclusion.
    """

    @app.after_request
    def _syndicate_gzip_response(response: Any) -> Any:  # pragma: no cover - thin adapter
        from flask import request

        try:
            return compress_response(response, request.headers.get("Accept-Encoding", ""))
        except Exception:
            # Never turn a working response into a 500 over a size optimisation.
            return response
