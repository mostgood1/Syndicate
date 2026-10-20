"""WNBA odds and slates must only ever be WNBA (repointed at the ports, lane wnba-vendor-deletion-prep; the two Bovada game-odds
fetcher tests retired: production never runs fetch_bovada_odds_current, which the ports do not carry).

Measured 2026-10-02 on the local fleet: with no WNBA game on 2026-10-03,
WNBA `predict-date` fell back to Bovada, whose WNBA-repo fetcher queried the
NBA repo's categories (basketball/nba + nba-pre-season). It wrote the NBA
preseason game Miami Heat @ Toronto Raptors (MIA@TOR) as a WNBA game, and the
WNBA cards page and market board served it.

The vendored package is exercised in a SUBPROCESS with its `src` on
PYTHONPATH: adding that dir to this process's sys.path changes other tests'
imports (see tests/test_wnba_refresh_runner.py). The fixtures are real Bovada
responses recorded 2026-10-02, trimmed to each event's game-lines group.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT  # the PORTS production runs, not the vendored package (lane wnba-vendor-deletion-prep)
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(code: str) -> dict:
    env = dict(os.environ, PYTHONPATH=str(SRC))
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True,
                          env=env, cwd=str(REPO_ROOT), timeout=120)
    if done.returncode != 0:
        raise AssertionError(f"subprocess failed rc={done.returncode}\nSTDERR:\n{done.stderr[-3000:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


class BovadaWnbaLeagueTests(unittest.TestCase):
    def test_endpoints_and_referer_are_wnba_only(self) -> None:
        out = _run("""
            import json
            import syndicate.features.wnba.live_tick.odds_bovada as ob
            print(json.dumps({"endpoints": ob.ENDPOINTS, "referer": ob.HEADERS["Referer"]}))
        """)
        self.assertTrue(out["endpoints"])
        self.assertTrue(all("/basketball/wnba" in u for u in out["endpoints"]), out["endpoints"][:3])
        self.assertFalse([u for u in out["endpoints"] if "/nba" in u])
        self.assertTrue(out["referer"].endswith("/basketball/wnba"))

    def test_is_wnba_team_is_by_name_not_tricode(self) -> None:
        out = _run("""
            import json
            from syndicate.features.wnba.source_cli.teams import is_wnba_team, to_tricode
            names = ["Toronto Tempo", "Golden State Valkyries", "Dallas Wings", "Toronto Raptors", "Miami Heat", ""]
            print(json.dumps({"is_wnba": {n: is_wnba_team(n) for n in names},
                              "raptors_tri": to_tricode("Toronto Raptors"), "tempo_tri": to_tricode("Toronto Tempo")}))
        """)
        self.assertEqual(out["is_wnba"], {"Toronto Tempo": True, "Golden State Valkyries": True, "Dallas Wings": True,
                                          "Toronto Raptors": False, "Miami Heat": False, "": False})
        self.assertEqual(out["tempo_tri"], "TOR")  # why a tricode check would have let MIA@TOR through

    def test_predict_date_has_no_bovada_game_odds_fallback(self) -> None:
        """Decision 2026-10-02: OddsAPI is the game-odds source; no WNBA game -> no game-odds file."""
        out = _run("""
            import inspect, json
            import syndicate.features.wnba.source_cli.cli as cli
            cmd = cli.predict_date_cmd
            src = inspect.getsource(getattr(cmd, "callback", None) or cmd)  # a click Command wraps the function
            print(json.dumps({"calls_bovada": "fetch_bovada_odds_current(" in src, "has_guard": "is_wnba_team" in src}))
        """)
        self.assertFalse(out["calls_bovada"])
        self.assertTrue(out["has_guard"])

if __name__ == "__main__":
    unittest.main()
