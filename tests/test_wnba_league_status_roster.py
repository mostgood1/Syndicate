"""WNBA league_status_<date>.csv must hold WNBA players only (lane wnba-league-status-roster).

Measured 2026-10-06 on the production data root: every wnba_source league_status file 09-30..10-08 held the NBA
roster (~600 rows, 30 NBA teams, no WNBA player). With no processed rosters file, build_league_status fell through
to nba_api's static_teams (the NBA list) + CommonTeamRoster, and its ScoreboardV2 call had no league_id, so NBA
ATL/GSW/... were flagged on slate.

Subprocess pattern as tests/test_wnba_predict_date_league.py: the vendored package's `src` must not join this
process's sys.path.
"""

from __future__ import annotations

import csv
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
import json
from unittest.mock import patch
from nba_api.stats.endpoints import scoreboardv2, commonteamroster
from wnba_betting import league_status as ls

SLATES = {
    "00": [("ATL", "MIN"), ("GSW", "LAL")],      # NBA preseason, what league "00" (the default) returns
    "10": [("ATL", "NYL"), ("GSV", "LVA")],      # WNBA semifinals
}
calls = []

class FakeScoreboard:
    def __init__(self, game_date=None, day_offset=0, league_id="00", timeout=None, **kw):
        calls.append(league_id)
        self.rows = SLATES.get(league_id, [])
    def get_normalized_dict(self):
        return {"LineScore": [{"TEAM_ABBREVIATION": t} for pair in self.rows for t in pair]}

def no_nba_roster(*a, **k):
    raise AssertionError("CommonTeamRoster (NBA team roster) must not be called")

with patch.object(scoreboardv2, "ScoreboardV2", FakeScoreboard), \\
        patch.object(commonteamroster, "CommonTeamRoster", side_effect=no_nba_roster):
    df = ls.build_league_status("2026-10-07")
print(json.dumps({
    "league_ids": calls,
    "teams": sorted(set(df["team"].astype(str))),
    "players": sorted(df["player_name"].astype(str)),
    "on_slate": sorted(set(df.loc[df["team_on_slate"].astype(bool), "team"].astype(str))),
    "playing": sorted(df.loc[df["playing_today"] == True, "player_name"].astype(str)),
    "status": {r["player_name"]: r["injury_status"] for _, r in df.iterrows() if str(r["injury_status"]).strip() not in ("", "nan")},
}))
"""


def _write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


class WnbaLeagueStatusRosterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        logs = ["GAME_DATE", "PLAYER_NAME", "PLAYER_ID", "TEAM_ABBREVIATION"]
        _write(root / "processed" / "player_logs.csv", logs, [
            ["2026-09-24", "Allisha Gray", 1628932, "ATL"],
            ["2026-09-24", "Breanna Stewart", 1627668, "NYL"],
            ["2026-06-01", "Kelsey Plum", 1628276, "LAS"],      # traded mid-season...
            ["2026-09-20", "Kelsey Plum", 1628276, "LVA"],      # ...latest team wins
            ["2026-09-21", "Kate Martin", 1642801, "GSV"],
            ["2026-09-21", "Tina Charles", 201600, "MIN"],      # WNBA team not on the slate
            ["2026-05-10", "Niger Guard", 900001, "NIGER"],     # exhibition opponent, not a WNBA team
            ["2025-09-01", "Retired Player", 900002, "SEA"],    # last season only
            ["2026-10-20", "Future Row", 900003, "ATL"],        # after the date
        ])
        _write(root / "raw" / "injuries.csv", ["team", "player", "status", "injury", "date"], [
            ["ATL", "Allisha Gray", "OUT", "Out", "2026-10-06"],
            ["NYL", "Breanna Stewart", "DAY-TO-DAY", "Knee", "2026-10-06"],
        ])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _build(self) -> dict:
        env = dict(os.environ, PYTHONPATH=str(SRC), WNBA_BETTING_DATA_ROOT=self._tmp.name)
        done = subprocess.run([sys.executable, "-c", textwrap.dedent(_HARNESS)], capture_output=True, text=True,
                              env=env, cwd=str(REPO_ROOT), timeout=300)
        if done.returncode != 0:
            raise AssertionError(f"subprocess failed rc={done.returncode}\nSTDERR:\n{done.stderr[-3000:]}")
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_roster_is_wnba_only_from_the_seasons_player_logs(self) -> None:
        out = self._build()
        self.assertEqual(out["teams"], ["ATL", "GSV", "LVA", "MIN", "NYL"])
        self.assertEqual(out["players"], ["Allisha Gray", "Breanna Stewart", "Kate Martin", "Kelsey Plum", "Tina Charles"])

    def test_slate_comes_from_the_wnba_scoreboard(self) -> None:
        out = self._build()
        self.assertEqual(out["league_ids"], ["10"])
        self.assertEqual(out["on_slate"], ["ATL", "GSV", "LVA", "NYL"])

    def test_injuries_drive_playing_today(self) -> None:
        out = self._build()
        self.assertEqual(out["status"], {"Allisha Gray": "OUT", "Breanna Stewart": "DAY-TO-DAY"})
        # OUT -> not playing; day-to-day on slate -> playing; off-slate team -> not playing
        self.assertEqual(out["playing"], ["Breanna Stewart", "Kate Martin", "Kelsey Plum"])


if __name__ == "__main__":
    unittest.main()
