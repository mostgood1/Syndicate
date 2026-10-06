"""`/healthz` is answered by the worker's event loop, not by a request thread.

Lane `web-restart-healthz`, MEASURED on the local fleet 2026-10-06 18:53-19:00Z:
all 8 of web's slots (2 workers x 4 threads) were held 234-404 s by cold
`/api/board/game-chips` builds, and `/healthz` (0-1 ms once a thread ran it) waited
behind them -- the watchdog logged web DOWN for ~8 minutes while both worker
processes were up and serving. `DrainingThreadWorker` now answers a fresh, complete
`GET`/`HEAD /healthz` in its loop.

gunicorn needs POSIX (`fcntl`), so the end-to-end tests skip on Windows; the request
classifier tests run everywhere.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from syndicate.web_worker import healthz_request, healthz_response

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    import fcntl  # noqa: F401

    POSIX = True
except ImportError:
    POSIX = False


class HealthzRequestClassifier(unittest.TestCase):
    def test_plain_get_and_head(self) -> None:
        self.assertEqual(healthz_request(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n"), "GET")
        self.assertEqual(healthz_request(b"HEAD /healthz HTTP/1.0\r\n\r\n"), "HEAD")
        self.assertEqual(healthz_request(b"GET /healthz?probe=1 HTTP/1.1\r\n\r\n"), "GET")

    def test_everything_else_goes_to_a_thread(self) -> None:
        for raw in (
            b"GET /healthz HTTP/1.1\r\nHost: x\r\n",            # headers not complete yet
            b"GET /healthzz HTTP/1.1\r\n\r\n",
            b"GET /api/health HTTP/1.1\r\n\r\n",
            b"GET / HTTP/1.1\r\n\r\n",
            b"POST /healthz HTTP/1.1\r\nContent-Length: 2\r\n\r\nok",
            b"GET /healthz HTTP/1.1\r\nContent-Length: 2\r\n\r\nok",  # a body
            b"GET /healthz HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
            b"GET /healthz\r\n\r\n",                             # HTTP/0.9 shape
            b"",
        ):
            self.assertIsNone(healthz_request(raw), raw)

    def test_response_matches_the_flask_route_body(self) -> None:
        response = healthz_response("GET")
        head, body = response.split(b"\r\n\r\n", 1)
        self.assertTrue(head.startswith(b"HTTP/1.1 200 OK"))
        self.assertIn(b"X-Syndicate-Health: worker-loop", head)
        self.assertIn(f"Content-Length: {len(body)}".encode(), head)
        import json

        self.assertEqual(json.loads(body), {"ok": True, "service": "syndicate"})
        self.assertEqual(healthz_response("HEAD").split(b"\r\n\r\n", 1)[1], b"")


@unittest.skipUnless(POSIX, "gunicorn workers need POSIX")
class FastHealthzUnderSaturation(unittest.TestCase):
    def _serve(self, tmp: str, extra_env: dict[str, str]) -> tuple[subprocess.Popen, int]:
        Path(tmp, "toyapp.py").write_text(textwrap.dedent("""
            import time
            def application(environ, start_response):
                if environ["PATH_INFO"] == "/slow":
                    time.sleep(6)
                body = b'{"ok":true,"service":"syndicate","via":"flask"}'
                start_response("200 OK", [("Content-Length", str(len(body)))])
                return [body]
        """), encoding="utf-8")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = dict(os.environ, PYTHONPATH=f"{REPO_ROOT}{os.pathsep}{tmp}", **extra_env)
        proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "toyapp:application", "--bind", f"127.0.0.1:{port}",
             "--workers", "1", "--threads", "2", "--timeout", "60",
             "--worker-class", "syndicate.web_worker.DrainingThreadWorker", "--log-level", "warning"],
            cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2).read()
                return proc, port
            except OSError:
                time.sleep(0.2)
        proc.kill()
        raise AssertionError("toy gunicorn never came up")

    def _probe_while_saturated(self, extra_env: dict[str, str]) -> tuple[float, str | None, str]:
        with tempfile.TemporaryDirectory() as tmp:
            proc, port = self._serve(tmp, extra_env)
            try:
                hogs = [threading.Thread(target=lambda: urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/slow", timeout=30).read()) for _ in range(2)]
                for hog in hogs:
                    hog.start()
                time.sleep(1.0)  # both threads are now inside /slow
                started = time.monotonic()
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=30) as response:
                    header = response.headers.get("X-Syndicate-Health")
                    response.read()
                elapsed = time.monotonic() - started
                for hog in hogs:
                    hog.join()
            finally:
                proc.terminate()
                output = proc.communicate(timeout=30)[0].decode(errors="replace")
        return elapsed, header, output

    def test_healthz_answers_while_every_thread_is_busy(self) -> None:
        elapsed, header, output = self._probe_while_saturated({})
        self.assertEqual(header, "worker-loop")          # the fast branch answered, not Flask
        self.assertLess(elapsed, 1.0)
        self.assertIn("WEB_FAST_HEALTHZ_ACTIVE", output)

    def test_the_switch_restores_the_queued_flask_route(self) -> None:
        """Negative control: with the fast path off, the same probe waits for a thread."""
        elapsed, header, _ = self._probe_while_saturated({"SYNDICATE_WEB_FAST_HEALTHZ": "0"})
        self.assertIsNone(header)
        self.assertGreater(elapsed, 3.0)


if __name__ == "__main__":
    unittest.main()
