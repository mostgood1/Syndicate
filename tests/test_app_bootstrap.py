import unittest
from unittest.mock import patch

from syndicate import app as syndicate_app


class AppBootstrapTests(unittest.TestCase):
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

    def test_bootstrap_render_data_skips_render_web_dyno(self) -> None:
        calls: list[int] = []

        with patch("syndicate.app._env_bool", return_value=True), patch(
            "syndicate.app._is_render_web_dyno",
            return_value=True,
        ):
            syndicate_app._bootstrap_render_data(lambda: calls.append(1) or 0)

        self.assertEqual(calls, [])

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