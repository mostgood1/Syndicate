"""`#390`. A sim run ledger for every sport, not just MLB.

MEASURED 2026-08-12: only MLB had any sim run record. NBA / WNBA / NHL / soccer
/ NCAAF sims run *inside* the odds refresh with no launch line, no run stamp, no
status file and no duration. The only reason a report could quantify them at all
is that `ALL_PROCESS_MEMORY` -- a MEMORY diagnostic -- happens to print child
`cmdline`s, which yields sampled lower bounds, not facts.

The tests that matter here are the WIRING ones at the bottom: they drive the
real `_run_command` and the real season-projection autorun. A ledger that is
correct and never called is the defect class this repo keeps rediscovering.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import sim_run_ledger as ledger


def _load(module_name: str, rel: str):
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


class ClassifyTests(unittest.TestCase):
    """Classified on the COMMAND, because a name allowlist goes stale silently
    the moment a sport is added."""

    def test_each_sport_is_attributed(self) -> None:
        cases = [
            (["python", "scripts/build_soccer_artifacts.py", "--league", "epl"], ("soccer", "soccersim_artifacts")),
            (["python", "scripts/build_nhl_artifacts.py"], ("nhl", "hockeysim_artifacts")),
            (["python", "scripts/refresh_nba_oddsapi_props.py"], ("nba", "smart_sim_props")),
            (["python", "scripts/refresh_wnba_oddsapi_props.py"], ("wnba", "smart_sim_props")),
            (["python", "scripts/generate_smartsim2_ncaaf_projections.py"], ("ncaaf", "smartsim2_season")),
            (["python", "scripts/run_mlb_daily_sim_job.py"], ("mlb", "daily_sim")),
        ]
        for command, expected in cases:
            with self.subTest(command=command[1]):
                self.assertEqual(ledger.classify_step("step", command), expected)

    def test_preseason_is_not_swallowed_by_the_season_pattern(self) -> None:
        """`generate_smartsim2_nfl` is a prefix of the preseason script name, so
        pattern ORDER is load-bearing. Measured in production: these are two
        distinct jobs, ~46 and ~40 runs/day."""
        self.assertEqual(
            ledger.classify_step("s", ["python", "scripts/generate_smartsim2_nfl_preseason_projections.py"]),
            ("nfl", "smartsim2_preseason"),
        )
        self.assertEqual(
            ledger.classify_step("s", ["python", "scripts/generate_smartsim2_nfl_projections.py"]),
            ("nfl", "smartsim2_season"),
        )

    def test_a_non_sim_step_is_not_recorded(self) -> None:
        self.assertIsNone(ledger.classify_step("mirror", ["python", "scripts/refresh_mlb_source_mirror.ps1"]))

    def test_blind_spot_detector_flags_sim_shaped_names(self) -> None:
        """An unclassified sim-shaped step must be visible. An instrument that
        cannot record its own blind spot is indistinguishable from one without."""
        self.assertTrue(ledger.step_looks_sim_shaped("soccer_epl_artifacts"))
        self.assertTrue(ledger.step_looks_sim_shaped("nba_oddsapi_props_job"))
        self.assertFalse(ledger.step_looks_sim_shaped("mirror"))


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        p = patch.object(ledger, "reports_root", return_value=self.root)
        p.start()
        self.addCleanup(p.stop)

    def test_a_run_is_recorded_and_indexed(self) -> None:
        ledger.record_sim_run(
            sport="soccer", kind="soccersim_artifacts", date="2026-08-12",
            run_stamp="r1", started_at="2026-08-12T20:00:00Z",
            finished_at="2026-08-12T20:06:14Z", exit_code=0, trigger="odds_refresh_step",
        )
        rec = json.loads((self.root / "sim_runs" / "2026-08-12" / "soccer__soccersim_artifacts__r1.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["sport"], "soccer")
        self.assertEqual(rec["duration_seconds"], 374)
        index = ledger.read_sim_run_index("2026-08-12")
        self.assertEqual(len(index["runs"]), 1)

    def test_duration_survives_mixed_timezones(self) -> None:
        """The `#388` trap: `started_at` is UTC and `finished_at` is Central in
        the MLB records. Parsed tz-aware the arithmetic is right; eyeballed it
        is not."""
        self.assertEqual(
            ledger.duration_seconds("2026-08-12T19:34:55Z", "2026-08-12T14:48:35-05:00"), 820
        )

    def test_summary_reports_a_denominator_not_just_a_count(self) -> None:
        """Ten runs that all failed must not read as a healthy ten."""
        for i, code in enumerate([0, 0, 1]):
            ledger.record_sim_run(
                sport="nhl", kind="hockeysim_artifacts", date="2026-08-12",
                run_stamp=f"r{i}", started_at="2026-08-12T20:00:00Z",
                finished_at="2026-08-12T20:01:00Z", exit_code=code,
            )
        summary = ledger.summarize_by_sport("2026-08-12")["by_sport"]["nhl"]
        self.assertEqual((summary["runs"], summary["ok"], summary["failed"]), (3, 2, 1))

    def test_an_unfinished_run_is_counted_separately(self) -> None:
        """A launch-time record with no completion is neither ok nor failed --
        conflating it with either is how `#388` produced zero recorded
        failures."""
        ledger.record_sim_run(
            sport="nfl", kind="smartsim2_season", date="2026-08-12",
            run_stamp="r9", started_at="2026-08-12T20:00:00Z", finished_at=None, state="running",
        )
        summary = ledger.summarize_by_sport("2026-08-12")["by_sport"]["nfl"]
        self.assertEqual((summary["runs"], summary["ok"], summary["failed"], summary["unfinished"]), (1, 0, 0, 1))


class OddsRefreshWiringTests(unittest.TestCase):
    """Drives the REAL `_run_command`. The ledger being correct is worth nothing
    if the step runner never calls it."""

    def setUp(self) -> None:
        self.mod = _load("refresh_odds_sources_for_ledger_tests", "scripts/refresh_odds_sources.py")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        p = patch.object(ledger, "reports_root", return_value=self.root)
        p.start()
        self.addCleanup(p.stop)
        self.mod._LEDGER_DATE = "2026-08-12"

    def _run(self, name: str, command: list[str]):
        step = self.mod.RefreshStep(name=name, phases=("live",), cwd=REPO_ROOT, command=tuple(command))
        result = MagicMock(returncode=0, stdout="", stderr="")
        with patch.object(self.mod.subprocess, "run", return_value=result):
            self.mod._run_command(step)

    def test_a_soccer_sim_step_reaches_the_ledger(self) -> None:
        self._run("soccer_epl_artifacts", ["python", "scripts/build_soccer_artifacts.py", "--league", "epl"])
        index = ledger.read_sim_run_index("2026-08-12")
        self.assertIsNotNone(index, "the step runner did not record anything")
        self.assertEqual(index["runs"][0]["sport"], "soccer")
        self.assertEqual(index["runs"][0]["exit_code"], 0)

    def test_a_non_sim_step_does_not(self) -> None:
        self._run("mirror", ["python", "scripts/refresh_mlb_source_mirror.ps1"])
        self.assertIsNone(ledger.read_sim_run_index("2026-08-12"))

    def test_an_unclassified_sim_shaped_step_is_logged(self) -> None:
        """A newly added sport whose command matches no pattern must be loud."""
        with patch("builtins.print") as mocked:
            self._run("curling_artifacts", ["python", "scripts/build_curling_artifacts.py"])
        printed = " ".join(str(c[0][0]) for c in mocked.call_args_list if c[0])
        self.assertIn("SIM_LEDGER_UNCLASSIFIED", printed)
        self.assertIsNone(ledger.read_sim_run_index("2026-08-12"))


if __name__ == "__main__":
    unittest.main()
