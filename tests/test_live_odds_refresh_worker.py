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


# PHASE 2 of the migration off the daily-update GHA cron. Phase 1 moved
# NFL/NCAAF/NCAAB to refresh-worker's weekly autorun; WNBA was never re-homed,
# so NOTHING called refresh_wnba_oddsapi_props.main() on any cadence. Measured
# 2026-08-17: MAIN_ENTRY 0 hits over 8h on BOTH workers, GAME_CARDS_CENSUS 0
# over ~2 days with the emitter confirmed present in both deployed SHAs. That
# is why the shipped game_cards coverage fix could not be measured at all.
class LiveOddsRefreshWorkerWnbaPregameAutorunTests(unittest.TestCase):
    @staticmethod
    def _load_module(repo_root: Path):
        script_path = repo_root / "scripts" / "run_live_odds_refresh_worker.py"
        spec = importlib.util.spec_from_file_location("test_run_live_odds_worker_wnba", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_is_off_by_default(self) -> None:
        """DEFAULT OFF is the safety property, not a stylistic choice.

        New periodic worker work is never free -- `#241` caused a production
        restart loop -- and this worker is 2GB with documented OOM history.
        Enabling it must be a deliberate config act.
        """
        module = self._load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")},
            clear=True,
        ), patch.object(module, "launch_refresh_run") as mocked_launch:
            module._launch_autorun_wnba_pregame_refresh()
            mocked_launch.assert_not_called()

    def test_skips_when_wnba_not_active_for_date(self) -> None:
        module = self._load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
                "SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN": "1",
            },
            clear=True,
        ), patch.object(module, "central_today_iso", return_value="2026-12-25"), patch.object(
            module, "_wnba_active_for_date", return_value=False
        ), patch.object(module, "launch_refresh_run") as mocked_launch:
            module._launch_autorun_wnba_pregame_refresh()
            mocked_launch.assert_not_called()

    def test_launches_wnba_with_PREGAME_phase_when_enabled_and_due(self) -> None:
        """THE TEST THAT MATTERS. `phase="pregame"` is load-bearing.

        This worker is 2GB and already carries WNBA SmartSim + live-lens load;
        `render.yaml` records sim workers cut to 1 and the WNBA sim count cut
        500 -> 250 -> 100 fighting for that memory, against a WNBA refresh leg
        measured at ~1.3-1.5GB RSS. Pregame covers schedule/odds/props/picks and
        EXCLUDES the sim leg. A full-phase autorun here would OOM the service,
        so if this assertion ever loosens, the service falls over.
        """
        module = self._load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
                "SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN": "1",
            },
            clear=True,
        ), patch.object(module, "central_today_iso", return_value="2026-08-18"), patch.object(
            module, "_wnba_active_for_date", return_value=True
        ), patch.object(module, "launch_refresh_run") as mocked_launch:
            mocked_launch.return_value = {"artifactsDir": "/tmp/a", "runStamp": "s1"}
            module._launch_autorun_wnba_pregame_refresh()
            mocked_launch.assert_called_once()
            kwargs = mocked_launch.call_args.kwargs
            self.assertEqual(kwargs["sports"], "wnba")
            self.assertEqual(kwargs["phase"], "pregame")
            self.assertEqual(kwargs["date"], "2026-08-18")

    def test_the_cadence_gate_stops_a_second_launch(self) -> None:
        module = self._load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
                "SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN": "1",
            },
            clear=True,
        ), patch.object(module, "central_today_iso", return_value="2026-08-18"), patch.object(
            module, "_wnba_active_for_date", return_value=True
        ), patch.object(module, "launch_refresh_run") as mocked_launch:
            mocked_launch.return_value = {"artifactsDir": "/tmp/a", "runStamp": "s1"}
            module._launch_autorun_wnba_pregame_refresh()
            module._launch_autorun_wnba_pregame_refresh()
            self.assertEqual(mocked_launch.call_count, 1, "the interval gate must hold")

    def test_a_launch_failure_is_recorded_and_swallowed(self) -> None:
        """A WNBA failure must never take down the soccer autorun or the tick.

        And it must be RECORDED -- `#433` is that soccer odds stopped for four
        days with no visible error, because launch_refresh_run spawns detached
        with stdout/stderr to DEVNULL and the launch is otherwise the last thing
        anyone hears about the run.
        """
        module = self._load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
                "SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN": "1",
            },
            clear=True,
        ), patch.object(module, "central_today_iso", return_value="2026-08-18"), patch.object(
            module, "_wnba_active_for_date", return_value=True
        ), patch.object(module, "launch_refresh_run", side_effect=RuntimeError("boom")):
            module._launch_autorun_wnba_pregame_refresh()  # must not raise
            status = module.read_json_file(module._wnba_pregame_autorun_status_path()) or {}
            self.assertIn("boom", str(status.get("error")))
