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


@unittest.skipUnless(POSIX, "gunicorn workers need POSIX")
class FastExitTests(unittest.TestCase):
    """2026-11-21: a recycled worker spent ~55 s in CPython's own shutdown (the 17:04:54Z dump: one thread,
    no Python frame), its slot unfilled until it was reaped. With the real `gunicorn.conf.py`, a worker
    whose loop returned leaves through `os._exit(0)`: the app's atexit handler -- standing in for the whole
    interpreter shutdown -- never runs. Off != on: with the switch off, the same handler runs in every
    exiting worker."""

    def _recycle_twice(self, fast_exit: str) -> tuple[str, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "toyexit.py").write_text(textwrap.dedent("""
                import atexit
                import os

                def _stock_shutdown_ran():
                    with open(os.path.join(os.environ["TOY_EXIT_MARKS"], str(os.getpid())), "w") as fh:
                        fh.write("atexit ran")

                atexit.register(_stock_shutdown_ran)

                def application(environ, start_response):
                    start_response("200 OK", [("Content-Length", "2")])
                    return [b"ok"]
            """), encoding="utf-8")
            marks = Path(tmp, "marks")
            marks.mkdir()
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=f"{REPO_ROOT}{os.pathsep}{tmp}", TOY_EXIT_MARKS=str(marks),
                       SYNDICATE_WEB_WORKER_FAST_EXIT=fast_exit)
            env.pop("GUNICORN_CMD_ARGS", None)
            proc = subprocess.Popen(
                [sys.executable, "-m", "gunicorn", "-c", str(CONF), "toyexit:application",
                 "--bind", f"127.0.0.1:{port}", "--workers", "1", "--threads", "2",
                 "--max-requests", "5", "--max-requests-jitter", "0", "--log-level", "info"],
                cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            try:
                served = 0
                deadline = time.time() + 30
                while served < 12 and time.time() < deadline:
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
                        served += 1
                    except OSError:
                        time.sleep(0.2)
                time.sleep(2.0)  # let the second recycled worker finish leaving
            finally:
                proc.terminate()
                output = proc.communicate(timeout=60)[0].decode(errors="replace")
            self.assertEqual(served, 12, output[-2000:])
            return output, sorted(p.name for p in marks.iterdir())

    def test_a_returned_worker_skips_the_interpreter_shutdown(self) -> None:
        output, marks = self._recycle_twice("1")
        exits = output.count("Worker exiting (pid:")
        self.assertGreaterEqual(exits, 3, output[-3000:])  # two recycles and the final stop
        self.assertEqual(output.count("WEB_WORKER_FAST_EXIT "), exits, output[-3000:])
        self.assertEqual(marks, [], "an atexit handler ran: the worker went through CPython's shutdown")

    def test_off_is_not_on_the_stock_exit_runs_the_shutdown(self) -> None:
        output, marks = self._recycle_twice("0")
        self.assertNotIn("WEB_WORKER_FAST_EXIT ", output)
        self.assertGreaterEqual(len(marks), 3, output[-3000:])


if __name__ == "__main__":
    unittest.main()
