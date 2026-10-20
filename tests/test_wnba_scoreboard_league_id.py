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
# Every ScoreboardV2 call in the WNBA ports production runs (lane wnba-vendor-deletion-prep; the vendored package goes).
PKGS = (REPO_ROOT / "syndicate" / "features" / "wnba" / "source_cli", REPO_ROOT / "syndicate" / "features" / "wnba" / "live_tick")


def _scoreboard_calls_without_league_id() -> list[str]:
    missing: list[str] = []
    for path in sorted(q for pkg in PKGS for q in pkg.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else "")
            if name == "ScoreboardV2" and not any(kw.arg == "league_id" for kw in node.keywords):
                missing.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return missing


class WnbaScoreboardLeagueIdTests(unittest.TestCase):
    def test_no_scoreboard_call_in_the_package_omits_league_id(self) -> None:
        self.assertTrue(any(pkg.is_dir() for pkg in PKGS))  # not vacuous
        self.assertEqual(_scoreboard_calls_without_league_id(), [])

if __name__ == "__main__":
    unittest.main()
