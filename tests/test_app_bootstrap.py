import os
import tempfile
import unittest
from unittest.mock import patch

from syndicate import app as syndicate_app


class _ImmediateThread:
    """Runs the bootstrap thread body inline so a test can observe it."""

    def __init__(self, *, target=None, name=None, daemon=None):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()


def _run_bootstrap_once(bootstrap_main, *, data_root):
    """One web-dyno boot, with the background thread run inline."""
    with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": data_root}), patch(
        "syndicate.app._env_bool", return_value=True
    ), patch("syndicate.app._is_render_web_dyno", return_value=True), patch(
        "syndicate.app.threading.Thread",
        side_effect=lambda **kwargs: _ImmediateThread(**kwargs),
    ), patch("time.sleep"):
        syndicate_app._bootstrap_render_data(bootstrap_main)


def _remove_lock() -> None:
    try:
        os.remove(syndicate_app._bootstrap_lock_path())
    except OSError:
        pass


class AppBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        # The lock is container-local, so every test in this class shares one
        # real path. Leaving one behind would make the NEXT test skip its sync
        # -- the very bug under test, reproduced against ourselves.
        _remove_lock()
        self.addCleanup(_remove_lock)

    def test_bootstrap_render_data_runs_when_enabled(self) -> None:
        calls: list[int] = []

        with patch("syndicate.app._env_bool", return_value=True), patch(
            "syndicate.app._is_render_web_dyno",
            return_value=False,
        ):
            syndicate_app._bootstrap_render_data(lambda: calls.append(1) or 0)

        self.assertEqual(calls, [1])

    def test_create_app_triggers_bootstrap(self) -> None:
        with patch("syndicate.app._bootstrap_render_data") as bootstrap_mock, patch(
            "syndicate.app._is_render_web_dyno",
            return_value=False,
        ):
            syndicate_app.create_app()

        bootstrap_mock.assert_called_once()

    def test_bootstrap_render_data_runs_in_background_on_render_web_dyno(self) -> None:
        calls: list[int] = []

        with tempfile.TemporaryDirectory() as tmp:
            _run_bootstrap_once(lambda: calls.append(1) or 0, data_root=tmp)
            # A second gunicorn worker booting in the same window, with the
            # first still running: the lock must dedupe. The holder pid is THIS
            # process, which is genuinely alive -- the old version of this test
            # wrote "1", and under the pid-aware lock that would have asserted
            # something about init rather than about a sibling worker.
            try:
                with open(syndicate_app._bootstrap_lock_path(), "w", encoding="utf-8") as handle:
                    handle.write(str(os.getpid()))
                _run_bootstrap_once(lambda: calls.append(2) or 0, data_root=tmp)
            finally:
                _remove_lock()

        self.assertEqual(calls, [1])

    # --- the lock, after 2026-08-20 -----------------------------------------
    #
    # The incident: web's boot sync was killed 63s in by a `/healthz` timeout.
    # gunicorn shut down gracefully so the daemon thread was never joined, the
    # `finally` never removed the lock, and because the lock lived on the
    # PERSISTENT DISK it was still there for the next container -- 78 seconds
    # old, well inside the 1800s age check. The replacement instance skipped
    # its sync entirely. Every test below would have failed against that code.

    def test_lock_lives_in_the_container_not_on_the_persistent_disk(self) -> None:
        # The structural half of the fix: a file under SYNDICATE_DATA_ROOT
        # survives the container that wrote it, and this lock must not.
        with tempfile.TemporaryDirectory() as data_root:
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": data_root}):
                lock_path = syndicate_app._bootstrap_lock_path()

        self.assertFalse(
            os.path.abspath(lock_path).startswith(os.path.abspath(data_root)),
            "the bootstrap lock must not live on the mounted data disk",
        )
        self.assertTrue(
            os.path.abspath(lock_path).startswith(os.path.abspath(tempfile.gettempdir()))
        )

    def test_a_fresh_lock_whose_holder_is_dead_is_reclaimed(self) -> None:
        # THE REGRESSION TEST. A lock 78 seconds old -- far inside the age
        # backstop -- left by a process that no longer exists. The old code
        # returned on the age check alone and skipped the sync.
        calls: list[int] = []

        with tempfile.TemporaryDirectory() as tmp:
            try:
                with open(syndicate_app._bootstrap_lock_path(), "w", encoding="utf-8") as handle:
                    handle.write("4242")
                with patch("syndicate.app._pid_is_running", return_value=False):
                    _run_bootstrap_once(lambda: calls.append(1) or 0, data_root=tmp)
            finally:
                _remove_lock()

        self.assertEqual(calls, [1], "a dead holder's lock must not skip this boot's sync")

    def test_a_lock_held_by_a_live_process_still_blocks(self) -> None:
        # `off != on`. Without this the reclaim above could be implemented as
        # "always steal the lock", which would delete the mutual exclusion the
        # lock exists for -- two gunicorn workers syncing 33k files at once.
        calls: list[int] = []

        with tempfile.TemporaryDirectory() as tmp:
            try:
                with open(syndicate_app._bootstrap_lock_path(), "w", encoding="utf-8") as handle:
                    handle.write("4242")
                with patch("syndicate.app._pid_is_running", return_value=True):
                    _run_bootstrap_once(lambda: calls.append(1) or 0, data_root=tmp)
            finally:
                _remove_lock()

        self.assertEqual(calls, [], "a live sibling's lock must still dedupe")

    def test_an_ancient_lock_is_reclaimed_even_when_its_pid_looks_alive(self) -> None:
        # The backstop, for PID reuse inside one long-lived container.
        calls: list[int] = []

        with tempfile.TemporaryDirectory() as tmp:
            try:
                lock_path = syndicate_app._bootstrap_lock_path()
                with open(lock_path, "w", encoding="utf-8") as handle:
                    handle.write("4242")
                ancient = os.path.getmtime(lock_path) - (
                    syndicate_app._BOOTSTRAP_LOCK_MAX_AGE_SECONDS + 60
                )
                os.utime(lock_path, (ancient, ancient))
                with patch("syndicate.app._pid_is_running", return_value=True):
                    _run_bootstrap_once(lambda: calls.append(1) or 0, data_root=tmp)
            finally:
                _remove_lock()

        self.assertEqual(calls, [1])

    def test_the_lock_is_released_after_the_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                _run_bootstrap_once(lambda: 0, data_root=tmp)
                self.assertFalse(os.path.exists(syndicate_app._bootstrap_lock_path()))
            finally:
                _remove_lock()

    def test_the_lock_is_released_even_when_the_sync_raises(self) -> None:
        # A sync that throws must not leave the lock behind either -- that is
        # the same poisoning shape, reached by a different door.
        def _boom() -> int:
            raise RuntimeError("simulated bootstrap failure")

        with tempfile.TemporaryDirectory() as tmp:
            try:
                _run_bootstrap_once(_boom, data_root=tmp)
                self.assertFalse(os.path.exists(syndicate_app._bootstrap_lock_path()))
            finally:
                _remove_lock()

    def test_pid_is_running_agrees_with_reality_for_this_process(self) -> None:
        # The helper itself, not a mock of it. Kept portable: a made-up high pid
        # raises OSError rather than ProcessLookupError on some platforms, and
        # this code deliberately reads that as "alive", so it is not asserted.
        self.assertTrue(syndicate_app._pid_is_running(os.getpid()))
        self.assertFalse(syndicate_app._pid_is_running(0))
        self.assertFalse(syndicate_app._pid_is_running(-1))

    def test_bootstrap_render_data_skips_when_disabled(self) -> None:
        calls: list[int] = []

        with patch("syndicate.app._env_bool", return_value=False):
            syndicate_app._bootstrap_render_data(lambda: calls.append(1) or 0)

        self.assertEqual(calls, [])

    def test_create_app_starts_intelligence_loop_on_render_web_when_enabled(self) -> None:
        class _ImmediateThread:
            def __init__(self, *, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if self._target is not None:
                    self._target()

        with patch("syndicate.app._bootstrap_render_data") as bootstrap_mock, patch(
            "syndicate.app._is_render_web_dyno",
            return_value=True,
        ), patch(
            "syndicate.app._env_bool",
            side_effect=lambda name, default=False: name == "SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP",
        ), patch(
            "syndicate.app.threading.Thread",
            side_effect=lambda **kwargs: _ImmediateThread(**kwargs),
        ), patch(
            "syndicate.app.start_intelligence_state_background_loop"
        ) as mocked_start_intel, patch("syndicate.app.start_live_refresh_background_loop") as mocked_start_live:
            syndicate_app.create_app()

        bootstrap_mock.assert_called_once()
        mocked_start_intel.assert_called_once()
        mocked_start_live.assert_not_called()


if __name__ == "__main__":
    unittest.main()