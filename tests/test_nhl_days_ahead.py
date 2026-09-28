"""NHL generation must build TOMORROW as well as the slate date.

MEASURED 2026-09-28, the evening before the NHL regular-season opener.
`refresh_nhl_oddsapi.py`'s `_date_window(date, days_ahead)` builds only the dates
it is handed, and `--days-ahead` defaults to 0 -- so the nightly step built
exactly one date: the slate that had already happened. The NHL cards board
renders saved prediction rows, so it served `games: 0` for opening night while
the odds were entirely healthy: 260 book-grid rows across all five games, 235
layer-2 candidates, every one in the `opportunity` lane.

The failure mode is that this is INDISTINGUISHABLE FROM BREAKAGE from outside.
It was reported as "NHL odds are missing for tomorrow" when no odds were missing.
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import refresh_odds_sources as ros  # noqa: E402

ENV = "SYNDICATE_NHL_DAYS_AHEAD"


class NhlDaysAheadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prior = os.environ.get(ENV)
        os.environ.pop(ENV, None)

    def tearDown(self) -> None:
        if self._prior is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = self._prior

    def test_the_flag_actually_REACHES_the_command(self) -> None:
        """A default nothing passes through is the defect, not the fix."""
        step = ros._build_nhl_steps(argparse.Namespace(date="2026-09-28"))[0]
        cmd = [str(c) for c in step.command]
        self.assertIn("--days-ahead", cmd)
        self.assertEqual(cmd[cmd.index("--days-ahead") + 1], "1")

    def test_absent_env_means_ONE_not_zero(self) -> None:
        """Absent is not off. The code's default is what decides (CLAUDE.md), and
        the whole point is that zero leaves tomorrow unbuilt."""
        self.assertEqual(ros._nhl_days_ahead(), 1)

    def test_it_can_be_turned_OFF_without_a_deploy(self) -> None:
        """Each extra day re-runs slate inputs, predictions, recommendations AND a
        props sim, so the cost is roughly linear on a 2 GB service. If a real
        slate proves too expensive, this must be reversible without shipping."""
        os.environ[ENV] = "0"
        self.assertEqual(ros._nhl_days_ahead(), 0)
        step = ros._build_nhl_steps(argparse.Namespace(date="2026-09-28"))[0]
        cmd = [str(c) for c in step.command]
        self.assertEqual(cmd[cmd.index("--days-ahead") + 1], "0")

    def test_off_differs_from_on(self) -> None:
        """Reachability: the env must change the emitted command, or it is inert."""
        os.environ[ENV] = "0"
        off = [str(c) for c in ros._build_nhl_steps(argparse.Namespace(date="2026-09-28"))[0].command]
        os.environ.pop(ENV)
        on = [str(c) for c in ros._build_nhl_steps(argparse.Namespace(date="2026-09-28"))[0].command]
        self.assertNotEqual(off, on)

    def test_a_JUNK_value_does_not_crash_the_nightly_refresh(self) -> None:
        """A typo in an env var must not take the whole NHL step down with it."""
        for bad in ("junk", "", "   ", "-4"):
            os.environ[ENV] = bad
            self.assertGreaterEqual(ros._nhl_days_ahead(), 0)


if __name__ == "__main__":
    unittest.main()
