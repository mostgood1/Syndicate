import unittest
from unittest.mock import patch

from syndicate import app as syndicate_app


class AppBootstrapTests(unittest.TestCase):
    def test_bootstrap_render_data_runs_when_enabled(self) -> None:
        calls: list[int] = []

        with patch("syndicate.app._env_bool", return_value=True):
            syndicate_app._bootstrap_render_data(lambda: calls.append(1) or 0)

        self.assertEqual(calls, [1])

    def test_create_app_triggers_bootstrap(self) -> None:
        with patch("syndicate.app._bootstrap_render_data") as bootstrap_mock:
            syndicate_app.create_app()

        bootstrap_mock.assert_called_once()

    def test_bootstrap_render_data_runs_on_render_web_dyno_when_enabled(self) -> None:
        calls: list[int] = []

        with patch("syndicate.app._env_bool", return_value=True):
            syndicate_app._bootstrap_render_data(lambda: calls.append(1) or 0)

        self.assertEqual(calls, [1])

    def test_bootstrap_render_data_skips_when_disabled(self) -> None:
        calls: list[int] = []

        with patch("syndicate.app._env_bool", return_value=False):
            syndicate_app._bootstrap_render_data(lambda: calls.append(1) or 0)

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()