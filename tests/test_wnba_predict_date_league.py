"""WNBA `predict-date` must never turn an NBA slate into WNBA predictions.

Measured 2026-10-06 on the local fleet: on every date with no WNBA game
(10-05, 10-06, 10-08), `wnba_source/data/processed/predictions_<date>.csv`
held that day's NBA preseason games (Hornets-Nets, Warriors-Lakers, ...), all
with the model's constant no-feature output (p=0.6208, spread 5.75, total
132.9). With no WNBA game_cards for the date, predict-date fell back to
nba_api's ScoreboardV2 with no `league_id`, which defaults to "00" (NBA), and
mapped tricodes through `static_teams.get_teams()` -- the NBA list. Measured
live: league "00" on 10-06 -> 4 NBA games; league "10" -> 0; league "10" on
10-07 -> ATL/NYL/GSV/LVA.

Same subprocess pattern as tests/test_wnba_bovada_league.py: the vendored
package's `src` must not join this process's sys.path.
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


def _run(code: str, data_root: str) -> dict:
    env = dict(os.environ, PYTHONPATH=str(SRC), WNBA_BETTING_DATA_ROOT=data_root)
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True,
                          env=env, cwd=str(REPO_ROOT), timeout=300)
    if done.returncode != 0:
        raise AssertionError(f"subprocess failed rc={done.returncode}\nSTDERR:\n{done.stderr[-3000:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


# A stand-in for nba_api's ScoreboardV2 that behaves like the real API: the
# NBA slate for league "00" (its default), the WNBA slate for "10".
_HARNESS = """
import json, sys
from unittest.mock import patch
import pandas as pd
from click.testing import CliRunner
from wnba_betting import cli

SLATES = {
    "00": [(1, 1610612766, "CHA", 1610612751, "BKN"), (2, 1610612737, "ATL", 1610612750, "MIN")],
    "10": [(3, 1611661330, "ATL", 1611661313, "NYL"), (4, 1611661331, "GSV", 1611661319, "LVA")],
}
calls = []

class FakeScoreboard:
    def __init__(self, game_date=None, day_offset=0, league_id="00", timeout=None, **kw):
        calls.append(league_id)
        self.rows = SLATES_FOR_RUN.get(league_id, [])
    def get_normalized_dict(self):
        gh = [{"GAME_ID": g, "HOME_TEAM_ID": h, "VISITOR_TEAM_ID": v, "GAME_DATE_EST": DATE} for g, h, _, v, _ in self.rows]
        ls = [{"GAME_ID": g, "TEAM_ID": t, "TEAM_ABBREVIATION": a} for g, h, ha, v, va in self.rows for t, a in ((h, ha), (v, va))]
        return {"GameHeader": gh, "LineScore": ls}

seen = []
def fake_predict(slate):
    seen.extend(sorted(zip(slate["home_team"], slate["visitor_team"])))
    raise SystemExit(0)

with patch.object(cli.scoreboardv2, "ScoreboardV2", FakeScoreboard), \\
        patch.object(cli, "_predict_from_matchups", side_effect=fake_predict), \\
        patch.object(cli, "_scoreboard_for_date", return_value={"events": []}), \\
        patch.object(cli, "_load_schedule_day", return_value=pd.DataFrame()):
    result = CliRunner().invoke(cli.cli, ["predict-date", "--date", DATE])
print(json.dumps({"league_ids": calls, "predicted": seen, "exit": result.exit_code,
                  "exc": repr(result.exception) if result.exception and not isinstance(result.exception, SystemExit) else None}))
"""


class PredictDateLeagueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        Path(self._tmp.name, "processed").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _predict(self, date: str, slates: str) -> dict:
        return _run(f"DATE = {date!r}\nSLATES_FOR_RUN = None\n" + _HARNESS.replace(
            "calls = []", f"calls = []\nSLATES_FOR_RUN = {slates}"), self._tmp.name)

    def test_no_wnba_date_predicts_nothing(self) -> None:
        # The real API on 10-06: NBA games under "00", none under "10".
        out = self._predict("2026-10-06", '{"00": SLATES["00"]}')
        self.assertIsNone(out["exc"])
        self.assertEqual(out["league_ids"], ["10"])
        self.assertEqual(out["predicted"], [])

    def test_wnba_date_predicts_the_wnba_slate(self) -> None:
        out = self._predict("2026-10-07", "SLATES")
        self.assertIsNone(out["exc"])
        self.assertEqual(out["league_ids"], ["10"])
        self.assertEqual(out["predicted"], [["Atlanta Dream", "New York Liberty"],
                                            ["Golden State Valkyries", "Las Vegas Aces"]])

    def test_non_wnba_rows_from_any_source_are_dropped(self) -> None:
        # Backstop for the history/schedule fallbacks: a slate source that
        # yields NBA names never reaches the model.
        code = """
        import json
        from unittest.mock import patch
        import pandas as pd
        from click.testing import CliRunner
        from wnba_betting import cli
        slate = pd.DataFrame([{"date": pd.Timestamp("2026-10-08").date(), "home_team": "Brooklyn Nets", "visitor_team": "Philadelphia 76ers"},
                              {"date": pd.Timestamp("2026-10-08").date(), "home_team": "Atlanta Dream", "visitor_team": "New York Liberty"}])
        seen = []
        def fake_predict(s):
            seen.extend(sorted(zip(s["home_team"], s["visitor_team"])))
            raise SystemExit(0)
        with patch.object(cli.scoreboardv2, "ScoreboardV2", side_effect=RuntimeError("down")), \\
                patch.object(cli, "_predict_from_matchups", side_effect=fake_predict), \\
                patch.object(cli, "_scoreboard_for_date", return_value={"events": []}), \\
                patch.object(cli, "_load_schedule_day", return_value=pd.DataFrame()), \\
                patch("pandas.read_parquet", return_value=slate.assign(date=pd.to_datetime(slate["date"]))):
            pathlib_hit = (cli.paths.data_processed / "features.parquet")
            pathlib_hit.parent.mkdir(parents=True, exist_ok=True); pathlib_hit.write_bytes(b"stub")
            CliRunner().invoke(cli.cli, ["predict-date", "--date", "2026-10-08"])
        print(json.dumps({"predicted": seen}))
        """
        out = _run(code, self._tmp.name)
        self.assertEqual(out["predicted"], [["Atlanta Dream", "New York Liberty"]])


class TeamHelperTests(unittest.TestCase):
    def test_from_tricode_and_league_id(self) -> None:
        out = _run("""
        import json
        from wnba_betting.teams import from_tricode
        from wnba_betting.league import LEAGUE
        print(json.dumps({"id": LEAGUE.stats_league_id,
                          "map": [from_tricode(t) for t in ("ATL", "PHO", "WAS", "POR", "BKN", "")]}))
        """, tempfile.gettempdir())
        self.assertEqual(out["id"], "10")
        self.assertEqual(out["map"], ["Atlanta Dream", "Phoenix Mercury", "Washington Mystics", "Portland Fire", "", ""])


if __name__ == "__main__":
    unittest.main()
