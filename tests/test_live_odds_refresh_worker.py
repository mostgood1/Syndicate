from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


# #148. Soccer's pregame steps (schedule/odds/props/picks) depend on
# _run_live_refresh_tick's shared adaptive phase ever actually resolving to
# "pregame" -- but that phase is a single GLOBAL decision across ALL active
# sports, not per-sport, and with MLB/WNBA/NBA running live games most
# evenings it rarely coincides with soccer's own pregame-cadence window in
# practice. This is the fix: an independent, soccer-scoped trigger on
# live-odds-worker that never depends on the shared tick's cross-sport phase
# at all, matching the class of autorun already proven for MLB/weekly-sports/
# reconciliation on refresh-worker (test_refresh_worker.py), just placed on
# the service that actually owns odds.
class LiveOddsRefreshWorkerSoccerPregameAutorunTests(unittest.TestCase):
    @staticmethod
    def _load_module(repo_root: Path):
        script_path = repo_root / "scripts" / "run_live_odds_refresh_worker.py"
        spec = importlib.util.spec_from_file_location("test_run_live_odds_refresh_worker", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_skips_when_disabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")},
            clear=True,
        ), patch.object(module, "launch_refresh_run") as mocked_launch:
            module._launch_autorun_soccer_pregame_refresh()
            mocked_launch.assert_not_called()

    def test_skips_when_soccer_not_active_for_date(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
                "SYNDICATE_ENABLE_SOCCER_PREGAME_REFRESH_AUTORUN": "1",
            },
            clear=True,
        ), patch.object(module, "central_today_iso", return_value="2026-07-29"), patch.object(
            module, "_soccer_active_for_date", return_value=False
        ), patch.object(module, "launch_refresh_run") as mocked_launch:
            module._launch_autorun_soccer_pregame_refresh()
            mocked_launch.assert_not_called()

    def test_launches_with_pregame_phase_when_enabled_and_due(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            fake_launch_result = {"ok": True, "pid": 5151, "state": "running"}

            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_ENABLE_SOCCER_PREGAME_REFRESH_AUTORUN": "1",
                },
                clear=True,
            ), patch.object(module, "central_today_iso", return_value="2026-07-29"), patch.object(
                module, "_soccer_active_for_date", return_value=True
            ), patch.object(module, "launch_refresh_run", return_value=fake_launch_result) as mocked_launch:
                module._launch_autorun_soccer_pregame_refresh()

                mocked_launch.assert_called_once()
                called_kwargs = mocked_launch.call_args.kwargs
                self.assertEqual(called_kwargs["sports"], "soccer")
                self.assertEqual(called_kwargs["phase"], "pregame")
                self.assertEqual(called_kwargs["launch_mode"], "web_process")

                # Reading the status file back must happen while
                # SYNDICATE_REPORTS_ROOT is still patched -- reports_root()
                # reads the env var fresh on every call, so once this `with`
                # block exits it resolves back to the real repo path.
                status_path = module._soccer_pregame_autorun_status_path()
                self.assertEqual(status_path.name, "soccer_pregame_autorun_status.json")
                status = json.loads(status_path.read_text(encoding="utf-8"))
                self.assertEqual(status["sports"], "soccer")
                self.assertNotIn("error", status)

    def test_skips_second_call_inside_the_interval(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            fake_launch_result = {"ok": True, "pid": 5151, "state": "running"}

            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_ENABLE_SOCCER_PREGAME_REFRESH_AUTORUN": "1",
                },
                clear=True,
            ), patch.object(module, "central_today_iso", return_value="2026-07-29"), patch.object(
                module, "_soccer_active_for_date", return_value=True
            ), patch.object(module, "launch_refresh_run", return_value=fake_launch_result) as mocked_launch:
                module._launch_autorun_soccer_pregame_refresh()
                mocked_launch.reset_mock()
                # Second call, same (fresh) interval window -- must be a no-op.
                module._launch_autorun_soccer_pregame_refresh()
                mocked_launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
