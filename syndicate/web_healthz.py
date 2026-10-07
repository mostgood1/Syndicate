"""Pure /healthz helpers for the web worker -- NO gunicorn import.

Split out of `syndicate/web_worker.py` (lane `web-restart-healthz`, 2026-10-07) because
that module imports gunicorn at module scope, and gunicorn imports `fcntl`, which does
not exist on Windows: `tests/test_web_worker_fast_healthz.py` importing these from there
killed pytest COLLECTION on Windows (0 of 22,003 tests ran; reported by lane
live-gameline-rescore). The worker re-exports them, so nothing else changes.
"""

from __future__ import annotations

import os


_HEALTHZ_BODY = b'{"ok":true,"service":"syndicate"}\n'
_HEALTHZ_PEEK_BYTES = 4096
_HEADER_END = b"\r\n\r\n"


def fast_healthz_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_WEB_FAST_HEALTHZ") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def healthz_request(head: bytes) -> str | None:
    """`"GET"`/`"HEAD"` when `head` is a COMPLETE, body-less `/healthz` request, else None.

    Anything else -- another path, a body, headers not all arrived yet -- returns
    None and goes to a thread exactly as before, so being wrong here can only ever
    send a request down the normal path."""
    end = head.find(_HEADER_END)
    if end < 0:
        return None
    lines = head[:end].split(b"\r\n")
    parts = lines[0].split(b" ")
    if len(parts) != 3 or not parts[2].startswith(b"HTTP/1."):
        return None
    method, target = parts[0], parts[1]
    if method not in (b"GET", b"HEAD"):
        return None
    if target != b"/healthz" and not target.startswith(b"/healthz?"):
        return None
    for line in lines[1:]:
        name = line.split(b":", 1)[0].strip().lower()
        if name in (b"content-length", b"transfer-encoding", b"expect", b"upgrade"):
            return None
    return method.decode("ascii")


def healthz_response(method: str) -> bytes:
    head = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(_HEALTHZ_BODY)}\r\n"
        "Cache-Control: no-store\r\n"
        "X-Syndicate-Health: worker-loop\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    return head if method == "HEAD" else head + _HEALTHZ_BODY
