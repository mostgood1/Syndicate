"""No ScoreboardV2 call in the vendored WNBA package may read the NBA slate (lane wnba-scoreboard-league-id).

nba_api's ScoreboardV2 defaults to league_id "00", the NBA. Called without it from the WNBA package it returns NBA
games: predictions_<date>.csv held NBA preseason games (fixed in dfb193bb) and league_status_<date>.csv flagged NBA
teams on slate (fc6ecc96). This file guards the whole package structurally and checks the remaining reachable
callers (boxscores, pbp, finals) end to end.

Subprocess pattern as tests/test_wnba_predict_date_league.py: the vendored package's `src` must not join this
process's sys.path.
"""

from __future__ import annotations

import ast
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
PKG = SRC / "wnba_betting"


def _scoreboard_calls_without_league_id() -> list[str]:
    missing: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else "")
            if name == "ScoreboardV2" and not any(kw.arg == "league_id" for kw in node.keywords):
                missing.append(f"{path.relative_to(PKG)}:{node.lineno}")
    return missing


_HARNESS = """
import json
from unittest.mock import patch
import nba_api.stats.endpoints.scoreboardv2 as sbmod
from wnba_betting import boxscores, pbp, finals

# What the real API returns: the NBA slate under "00" (the default), the WNBA one under "10".
SLATES = {
    "00": [(1, 1610612737, "ATL", 1610612750, "MIN")],
    "10": [(3, 1611661330, "ATL", 1611661313, "NYL"), (4, 1611661317, "PHO", 1611661322, "WAS")],
}
calls = []

class FakeScoreboard:
    def __init__(self, game_date=None, day_offset=0, league_id="00", timeout=None, **kw):
        calls.append(league_id)
        self.rows = SLATES.get(league_id, [])
    def get_normalized_dict(self):
        gh = [{"GAME_ID": g, "HOME_TEAM_ID": h, "VISITOR_TEAM_ID": v, "GAME_STATUS_ID": 3} for g, h, _, v, _ in self.rows]
        ls = [{"GAME_ID": g, "TEAM_ID": t, "TEAM_ABBREVIATION": a, "PTS": 80} for g, h, ha, v, va in self.rows
              for t, a in ((h, ha), (v, va))]
        return {"GameHeader": gh, "LineScore": ls}

def no_network(*a, **k):
    raise AssertionError("finals must not read the NBA CDN for the WNBA")

with patch.object(sbmod, "ScoreboardV2", FakeScoreboard), patch.object(finals, "_scoreboardv2", sbmod), \\
        patch("requests.get", side_effect=no_network):
    box_ids = sorted(int(x) for x in boxscores._scoreboard_games("2026-10-07")["GAME_ID"])
    pbp_ids = sorted(int(x) for x in pbp._scoreboard_games("2026-10-07")["GAME_ID"])
    fin = finals._finals_from_stats("2026-10-07")
    cdn = finals._finals_from_cdn("2026-10-07")
print(json.dumps({
    "calls": calls,
    "box_ids": box_ids,
    "pbp_ids": pbp_ids,
    "finals": sorted(zip(fin["home_tri"], fin["away_tri"])),
    "cdn_rows": int(len(cdn)),
}))
"""


class WnbaScoreboardLeagueIdTests(unittest.TestCase):
    def test_no_scoreboard_call_in_the_package_omits_league_id(self) -> None:
        self.assertEqual(_scoreboard_calls_without_league_id(), [])

    def test_reachable_callers_read_the_wnba_slate_only(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            env = dict(os.environ, PYTHONPATH=str(SRC), WNBA_BETTING_DATA_ROOT=data_root)
            done = subprocess.run([sys.executable, "-c", textwrap.dedent(_HARNESS)], capture_output=True, text=True,
                                  env=env, cwd=str(REPO_ROOT), timeout=300)
        if done.returncode != 0:
            raise AssertionError(f"subprocess failed rc={done.returncode}\nSTDERR:\n{done.stderr[-3000:]}")
        out = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(out["calls"], ["10", "10", "10"])
        self.assertEqual(out["box_ids"], [3, 4])
        self.assertEqual(out["pbp_ids"], [3, 4])
        # stats-API spellings PHO/WAS map to this package's PHX/WSH
        self.assertEqual(out["finals"], [["ATL", "NYL"], ["PHX", "WSH"]])
        self.assertEqual(out["cdn_rows"], 0)


if __name__ == "__main__":
    unittest.main()
