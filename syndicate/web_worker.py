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
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import os
import selectors
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
