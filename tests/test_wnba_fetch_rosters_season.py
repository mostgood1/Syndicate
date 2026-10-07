"""fetch-rosters must never file today's roster under another season (lane wnba-fetch-rosters-season).

ESPN's roster endpoint serves only the CURRENT roster; the vendored fetch_rosters used its `season` argument only to
label the output. Both CLI commands (and the vendored app's cron route) defaulted to the NBA-style "2025-26", which
wrote the 2026 rosters as rosters_2025-26.csv / SEASON 2025-26 / LEAGUE_SEASON 2025 -- a file pick_rosters_file
then matches for 2025 dates.

Subprocess pattern as tests/test_wnba_predict_date_league.py: the vendored package's `src` must not join this
process's sys.path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "vendor" / "wnba_betting_repo" / "src"

_HARNESS = """
import json, os
from unittest.mock import patch
from click.testing import CliRunner
from wnba_betting import rosters, cli
from wnba_betting.config import paths

TEAMS = [{"id": "20", "display_name": "Atlanta Dream", "team_abbreviation": "ATL"}]
ATHLETES = [{"id": "3058901", "displayName": "Allisha Gray", "firstName": "Allisha", "lastName": "Gray"}]

def run(fn):
    for f in paths.data_processed.glob("rosters_*"):
        f.unlink()
    with patch.object(rosters, "_fetch_espn_teams", return_value=TEAMS), \\
            patch.object(rosters, "_fetch_espn_roster", return_value=ATHLETES):
        fn()
    files = sorted(p.name for p in paths.data_processed.glob("rosters_*.csv"))
    import pandas as pd
    seasons = sorted({str(x) for f in files for x in pd.read_csv(paths.data_processed / f)["SEASON"]})
    return {"files": files, "seasons": seasons}

import datetime
from wnba_betting.league import season_label_from_date
out = {"current": str(season_label_from_date(datetime.date.today()))}
out["direct_2025_26"] = run(lambda: rosters.fetch_rosters(season="2025-26"))
out["cli_fetch_rosters_default"] = run(lambda: CliRunner().invoke(cli.cli, ["fetch-rosters"]))
out["cli_fetch_rosters_cmd_default"] = run(lambda: CliRunner().invoke(cli.cli, ["fetch-rosters-cmd"]))
print(json.dumps(out))
"""


class WnbaFetchRostersSeasonTests(unittest.TestCase):
    def test_roster_is_always_labelled_with_the_current_season(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            Path(data_root, "processed").mkdir()
            env = dict(os.environ, PYTHONPATH=str(SRC), WNBA_BETTING_DATA_ROOT=data_root, WNBA_ROSTERS_RATE_DELAY="0")
            done = subprocess.run([sys.executable, "-c", textwrap.dedent(_HARNESS)], capture_output=True, text=True,
                                  env=env, cwd=str(REPO_ROOT), timeout=300)
        if done.returncode != 0:
            raise AssertionError(f"subprocess failed rc={done.returncode}\nSTDERR:\n{done.stderr[-3000:]}")
        out = json.loads(done.stdout.strip().splitlines()[-1])
        current = out["current"]
        self.assertNotIn("-", current)  # a WNBA label is a single year
        expected = {"files": [f"rosters_{current}.csv"], "seasons": [current]}
        self.assertEqual(out["direct_2025_26"], expected)
        self.assertEqual(out["cli_fetch_rosters_default"], expected)
        self.assertEqual(out["cli_fetch_rosters_cmd_default"], expected)
        self.assertIn("ROSTER_SEASON_NORMALISED requested=2025-26", done.stdout)


if __name__ == "__main__":
    unittest.main()
