"""A gthread worker that serves what it accepted before it exits.

WHY. gunicorn's `ThreadWorker` (21.2.0) accepts a connection and parks it in its
poller until the request bytes arrive (`accept` -> `poller.register`); only then
is it handed to a thread. When the worker decides to stop -- `alive = False`,
set by `--max-requests`, by SIGTERM, or by web's memory guard in
`gunicorn.conf.py::decide_recycle` -- `run()` leaves its loop and calls
`poller.close()`, abandoning every connection it accepted but had not yet read.
The process exits and those clients get a reset.

Measured 2026-10-01: the local-fleet audit sweep got `ConnectionResetError`
after 0.0s on `/wnba/market-board` the second web's memory guard recycled
worker 181021 (`WEB_WORKER_MEMORY_RECYCLE`, non-hard). An isolated repro under
the same gunicorn (2 workers x 4 threads, recycling every 25 requests, 16
clients) failed 108 of 4,000 requests (2.7%) with the stock worker.

WHAT THIS CHANGES -- only the exit path:
  1. stop listening: unregister this worker's listening sockets and close its
     copies (the listening socket is shared, so the other workers and the
     master's next worker keep accepting; nothing queued in the kernel is lost);
  2. drain: keep the event loop turning until every connection it already
     accepted has been read and served, bounded by
     `SYNDICATE_WEB_WORKER_DRAIN_SECONDS` (default 5, never past
     `graceful_timeout`);
  3. then exit exactly as the stock worker does.
Requests are served the stock way throughout; keep-alive connections are
closed after their response once the worker is stopping (the stock rule).
Proof line: `WEB_WORKER_DRAINED`.

`/healthz` IS ANSWERED BY THE WORKER'S OWN LOOP, NOT BY A REQUEST THREAD -- lane
`web-restart-healthz` `[2026-10-06]`. MEASURED on the local fleet 18:53-19:00Z:
every one of web's 8 slots (2 workers x 4 threads) was held 234-404 s by cold
`/api/board/game-chips` builds, and `/healthz` -- 0-1 ms once a thread ran it --
waited behind them, so the watchdog logged web DOWN for ~8 minutes while both
worker processes were alive and serving. A FRESH connection whose request is a
complete, body-less `GET`/`HEAD /healthz` is now answered here, in the event loop,
instead of being queued for a thread: no slot needed. It still proves the worker
PROCESS accepts and its loop turns (the same loop that heartbeats the master); it
no longer proves a Flask thread is free -- `/api/health` still does that.
Proof: the response carries `X-Syndicate-Health: worker-loop`, and each worker logs
`WEB_FAST_HEALTHZ_ACTIVE` once, on its first fast answer. Switch:
`SYNDICATE_WEB_FAST_HEALTHZ` (default on; 0/false/off restores the Flask route).
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import os
import selectors
import socket
import time
from functools import partial

from gunicorn.workers.gthread import ThreadWorker


def drain_seconds(graceful_timeout: float) -> float:
    raw = str(os.environ.get("SYNDICATE_WEB_WORKER_DRAIN_SECONDS") or "").strip()
    try:
        value = float(raw) if raw else 5.0
    except ValueError:
        value = 5.0
    return max(0.0, min(value, float(graceful_timeout or 0) or value))


from syndicate.web_healthz import (  # noqa: E402 -- pure helpers, no gunicorn
    _HEADER_END,
    _HEALTHZ_BODY,
    _HEALTHZ_PEEK_BYTES,
    fast_healthz_enabled,
    healthz_request,
    healthz_response,
)


class DrainingThreadWorker(ThreadWorker):
    def run(self) -> None:
        # Stock `ThreadWorker.run` loop, unchanged, until the worker is told to stop.
        for sock in self.sockets:
            sock.setblocking(False)
            server = sock.getsockname()
            self.poller.register(sock, selectors.EVENT_READ, partial(self.accept, server))

        while self.alive:
            self.notify()
            if self.nr_conns < self.worker_connections:
                events = self.poller.select(1.0)
                for key, _ in events:
                    key.data(key.fileobj)
                result = futures.wait(self.futures, timeout=0, return_when=futures.FIRST_COMPLETED)
            else:
                result = futures.wait(self.futures, timeout=1.0, return_when=futures.FIRST_COMPLETED)
            for fut in result.done:
                self.futures.remove(fut)
            if not self.is_parent_alive():
                break
            self.murder_keepalived()

        self._stop_listening()
        self._drain()

        self.tpool.shutdown(False)
        self.poller.close()
        futures.wait(self.futures, timeout=self.cfg.graceful_timeout)

    def on_client_socket_readable(self, conn, client) -> None:
        # Fresh connections only: a keep-alive conn has been `init()`ed (blocking,
        # parser attached) and stays on the stock path.
        if not conn.initialized and fast_healthz_enabled() and self._answer_healthz(conn, client):
            return
        super().on_client_socket_readable(conn, client)

    def _answer_healthz(self, conn, client) -> bool:
        try:
            head = conn.sock.recv(_HEALTHZ_PEEK_BYTES, socket.MSG_PEEK)
        except OSError:
            return False  # not readable after all, or reset: the stock path handles it
        method = healthz_request(head)
        if method is None:
            return False
        with self._lock:
            try:
                self.poller.unregister(client)
            except (KeyError, ValueError, OSError):
                return False
        try:
            conn.sock.recv(head.find(_HEADER_END) + len(_HEADER_END))  # exactly the peeked request
            conn.sock.settimeout(2.0)
            conn.sock.sendall(healthz_response(method))
        except OSError:
            pass
        finally:
            self.nr_conns -= 1
            try:
                conn.sock.close()
            except OSError:
                pass
        if not getattr(self, "_syndicate_fast_healthz_logged", False):
            self._syndicate_fast_healthz_logged = True
            print("WEB_FAST_HEALTHZ_ACTIVE " + json.dumps({"pid": os.getpid()}), flush=True)
        return True

    def _stop_listening(self) -> None:
        for sock in self.sockets:
            with self._lock:
                try:
                    self.poller.unregister(sock)
                except (KeyError, ValueError, OSError):
                    pass
            try:
                sock.close()
            except OSError:
                pass

    def _accepted_unread(self) -> int:
        """Client connections parked in the poller that are NOT idle keep-alives:
        accepted, request not yet read. These are what the stock exit dropped."""
        with self._lock:
            return max(0, len(self.poller.get_map()) - len(self._keep))

    def _drain(self) -> None:
        started = time.monotonic()
        deadline = started + drain_seconds(self.cfg.graceful_timeout)
        pending_at_stop = self._accepted_unread()
        in_flight_at_stop = len(self.futures)
        while time.monotonic() < deadline:
            if self._accepted_unread() <= 0 and not self.futures:
                break
            self.notify()
            for key, _ in self.poller.select(0.1):
                key.data(key.fileobj)
            result = futures.wait(self.futures, timeout=0, return_when=futures.FIRST_COMPLETED)
            for fut in result.done:
                self.futures.remove(fut)
            self.murder_keepalived()
        abandoned = self._accepted_unread()
        print("WEB_WORKER_DRAINED " + json.dumps({
            "pid": os.getpid(),
            "accepted_unread_at_stop": pending_at_stop,
            "in_flight_at_stop": in_flight_at_stop,
            "abandoned": abandoned,
            "still_in_flight": len(self.futures),
            "drain_s": round(time.monotonic() - started, 3),
        }, sort_keys=True), flush=True)
