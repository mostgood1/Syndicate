"""Web's gunicorn worker serves what it accepted before it recycles.

Stock gthread (gunicorn 21.2.0) leaves its loop and closes its poller with
accepted-but-unread connections still registered, so every recycle -- web's
memory guard, `--max-requests`, SIGTERM -- could reset a request. Measured
2026-10-01: an isolated repro (2 workers x 4 threads, recycle every 25 requests,
16 clients, 4,000 requests) failed 101-106 requests per round with the stock
worker and 0 with `DrainingThreadWorker`, over three rounds each.

gunicorn needs POSIX (`fcntl`), so the worker tests skip on Windows; the config
tests run everywhere.
"""

from __future__ import annotations

import os
import runpy
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
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
CONF = REPO_ROOT / "gunicorn.conf.py"

try:
    import fcntl  # noqa: F401

    POSIX = True
except ImportError:
    POSIX = False


class ConfigSelectsTheDrainingWorker(unittest.TestCase):
    def _load(self, value: str | None) -> dict:
        env = {k: v for k, v in os.environ.items() if k != "SYNDICATE_WEB_WORKER_DRAIN"}
        if value is not None:
            env["SYNDICATE_WEB_WORKER_DRAIN"] = value
        with patch.dict(os.environ, env, clear=True):
            return runpy.run_path(str(CONF))

    def test_on_by_default(self) -> None:
        self.assertEqual(self._load(None).get("worker_class"), "syndicate.web_worker.DrainingThreadWorker")

    def test_the_switch_restores_stock_gthread(self) -> None:
        for off in ("0", "false", "off"):
            self.assertNotIn("worker_class", self._load(off), off)


@unittest.skipUnless(POSIX, "gunicorn workers need POSIX")
class DrainingWorkerTests(unittest.TestCase):
    def test_gunicorn_resolves_the_class_to_a_thread_worker(self) -> None:
        from gunicorn.config import Config
        from gunicorn.workers.gthread import ThreadWorker

        cfg = Config()
        cfg.set("worker_class", "syndicate.web_worker.DrainingThreadWorker")
        cfg.set("threads", 4)
        self.assertTrue(issubclass(cfg.worker_class, ThreadWorker))
        self.assertEqual(cfg.worker_class.__name__, "DrainingThreadWorker")

    def test_drain_seconds_is_bounded_by_graceful_timeout(self) -> None:
        from syndicate.web_worker import drain_seconds

        with patch.dict(os.environ, {"SYNDICATE_WEB_WORKER_DRAIN_SECONDS": "30"}):
            self.assertEqual(drain_seconds(10), 10.0)
        with patch.dict(os.environ, {"SYNDICATE_WEB_WORKER_DRAIN_SECONDS": "bad"}):
            self.assertEqual(drain_seconds(30), 5.0)

    def test_recycling_under_load_drops_nothing(self) -> None:
        """The end-to-end property: a real gunicorn recycling every 10 requests
        under concurrent fresh connections answers every request."""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "toyapp.py").write_text(textwrap.dedent("""
                import time
                def application(environ, start_response):
                    time.sleep(0.005)
                    start_response("200 OK", [("Content-Length", "2")])
                    return [b"ok"]
            """), encoding="utf-8")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=f"{REPO_ROOT}{os.pathsep}{tmp}")
            proc = subprocess.Popen(
                [sys.executable, "-m", "gunicorn", "toyapp:application", "--bind", f"127.0.0.1:{port}",
                 "--workers", "2", "--threads", "4", "--max-requests", "10", "--max-requests-jitter", "0",
                 "--worker-class", "syndicate.web_worker.DrainingThreadWorker", "--log-level", "warning"],
                cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.time() + 15
                while time.time() < deadline:
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2).read()
                        break
                    except OSError:
                        time.sleep(0.2)
                failures: list[str] = []
                lock = threading.Lock()

                def client() -> None:
                    for _ in range(60):
                        try:
                            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read()
                        except Exception as exc:  # noqa: BLE001
                            with lock:
                                failures.append(type(exc).__name__)

                threads = [threading.Thread(target=client) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            finally:
                proc.terminate()
                output = proc.communicate(timeout=30)[0].decode(errors="replace")
        self.assertEqual(failures, [])
        self.assertIn("WEB_WORKER_DRAINED", output)  # the drain path actually ran


if __name__ == "__main__":
    unittest.main()
