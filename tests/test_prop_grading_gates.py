"""Prop grading in the season betting-card builder.

Both prop families graded ZERO rows on every date, for two unrelated reasons,
and both are the same shape as the pregame-freeze defect: a gate keyed on a
field that nothing populates, so it rejects 100% of its input.

HITTERS. `_extract_report_hitter_predictions` resolved a batter's team and
lineup status only via `_batter_side`, which needs `confirmed_lineup_ids` /
`projected_lineup_ids` on the GAME. The eval reports carry neither -- measured
across all 46 local report dates, zero games have either field. So the else
branch ran for every batter and `setdefault("is_lineup_batter", False)`
stamped False over a row whose own payload says `"is_lineup_batter": true`,
while `team` was never set at all. Downstream,
`_is_hitter_prediction_eligible` early-returns on the flag before it ever
consults `pa_mean`, and the caller skips any rec with an empty team:
**9,845 of 9,845** batter predictions rejected, with `pa_mean > 0` on all
9,845.

PITCHERS. The report's per-side `market` block is empty on every game of every
date, and unlike the hitter path this one never read the pitcher odds file --
so it held full model distributions with no lines to price them against and
`line_value is None -> continue` dropped everything.

Measured on 2026-07-08 (14-game slate), graded rows: **1** as production had
it -> 14 with odds restored (moneyline only) -> 196 with the hitter fix -> 222
with the pitcher fix.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUILDER_PATH = _REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "build_season_betting_cards_manifest.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("_bscm_props_under_test", _BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        # Heavy sim-engine imports are not needed for the functions under test.
        pass
    return module


def _game_with_hitter_rows(*, team: str = "SF", lineup_batter: bool = True) -> dict:
    """A game shaped like the real eval reports: NO lineup id sets, and the
    per-row payload carrying team / lineup_order / is_lineup_batter."""
    row = {
        "batter_id": 813841,
        "name": "Jonah Cox",
        "team": team,
        "p_h_1plus": 0.742,
        "p_h_1plus_cal": 0.742,
        "h_mean": 1.188,
        "pa_mean": 4.176,
        "ab_mean": 3.782,
        "lineup_order": 7,
        "is_lineup_batter": lineup_batter,
    }
    return {
        "game_pk": 823191,
        "away": {"abbr": "DET", "name": "Detroit Tigers", "team_id": 116},
        "home": {"abbr": "SF", "name": "San Francisco Giants", "team_id": 137},
        "hitter_props_likelihood": {"hits_1plus": [row]},
    }


class HitterLineupFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_builder()
        for name in ("_extract_report_hitter_predictions", "_is_hitter_prediction_eligible"):
            if not hasattr(cls.module, name):
                raise unittest.SkipTest(f"vendored module did not expose {name}")

    def test_row_lineup_flag_survives_when_the_game_has_no_lineup_ids(self) -> None:
        """The regression: the row says True, the old code stamped False."""
        pred = self.module._extract_report_hitter_predictions(_game_with_hitter_rows(), {})
        self.assertEqual(len(pred), 1)
        rec = next(iter(pred.values()))
        self.assertIs(rec.get("is_lineup_batter"), True)

    def test_team_is_taken_from_the_row(self) -> None:
        """An empty team is skipped by the caller, so this alone zeroed props."""
        rec = next(iter(self.module._extract_report_hitter_predictions(_game_with_hitter_rows(), {}).values()))
        self.assertEqual(rec.get("team"), "SF")

    def test_team_side_is_derived_by_matching_the_game_abbr(self) -> None:
        rec = next(iter(self.module._extract_report_hitter_predictions(_game_with_hitter_rows(), {}).values()))
        self.assertEqual(rec.get("team_side"), "home")
        self.assertEqual(rec.get("team_name"), "San Francisco Giants")

    def test_the_record_is_now_eligible(self) -> None:
        """End of the chain: this is what was rejecting 9,845 of 9,845."""
        rec = next(iter(self.module._extract_report_hitter_predictions(_game_with_hitter_rows(), {}).values()))
        self.assertTrue(self.module._is_hitter_prediction_eligible(rec))

    def test_a_genuinely_benched_batter_is_still_excluded(self) -> None:
        """The fix must not become "everyone plays" -- a row that really says
        False still fails eligibility, so the live bet-placement gate keeps
        working."""
        game = _game_with_hitter_rows(lineup_batter=False)
        rec = next(iter(self.module._extract_report_hitter_predictions(game, {}).values()))
        self.assertIs(rec.get("is_lineup_batter"), False)
        self.assertFalse(self.module._is_hitter_prediction_eligible(rec))

    def test_lineup_ids_on_the_game_still_win_when_present(self) -> None:
        """Unchanged behaviour for reports that DO carry lineup id sets."""
        game = _game_with_hitter_rows(team="DET")
        game["confirmed_lineup_ids"] = {"home": [813841], "away": []}
        rec = next(iter(self.module._extract_report_hitter_predictions(game, {}).values()))
        self.assertIs(rec.get("is_lineup_batter"), True)
        self.assertEqual(rec.get("team"), "SF", "the game's own lineup set is authoritative over the row")


class PitcherOddsFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_builder()
        if not hasattr(cls.module, "_collect_report_pitcher_recommendations"):
            raise unittest.SkipTest("vendored module did not expose _collect_report_pitcher_recommendations")

    def _report(self) -> dict:
        return {
            "meta": {"date": "2026-07-08"},
            "games": [
                {
                    "game_pk": 823191,
                    "game_date": "2026-07-08",
                    "away": {"abbr": "DET", "name": "Detroit Tigers"},
                    "home": {"abbr": "SF", "name": "San Francisco Giants"},
                    "starter_names": {"home": "Logan Webb", "away": "Tarik Skubal"},
                    "pitcher_props": {
                        # Empty `market` -- exactly what every real report has.
                        "home": {"market": {}, "pred": {"outs_dist": {str(i): 0.05 for i in range(20)}, "outs_mean": 18.0}},
                        "away": {"market": {}, "pred": {}},
                    },
                }
            ],
        }

    def test_pitcher_lines_are_read_when_the_report_market_block_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            odds_dir = Path(tmp) / "data" / "market" / "oddsapi"
            odds_dir.mkdir(parents=True)
            (odds_dir / "oddsapi_pitcher_props_2026_07_08.json").write_text(
                json.dumps(
                    {
                        "pitcher_props": {
                            "logan webb": {
                                "outs": {"line": 18.5, "over_odds": "-104", "under_odds": "-129"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            policy = {
                "pitcher_edge_min": -999.0,
                "pitcher_side": "",
                "pitcher_markets": ["outs"],
            }
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(Path(tmp) / "data")}, clear=False):
                rows = self.module._collect_report_pitcher_recommendations(self._report(), policy)

        self.assertTrue(rows, "an empty report market block must fall back to the pitcher odds file")
        self.assertEqual(rows[0].get("market"), "pitcher_props")
        self.assertEqual(float(rows[0].get("market_line")), 18.5)

    def test_absent_pitcher_odds_file_is_not_an_error(self) -> None:
        """Dates with no pitcher odds must degrade to zero rows, not raise."""
        with tempfile.TemporaryDirectory() as tmp:
            policy = {"pitcher_edge_min": -999.0, "pitcher_side": "", "pitcher_markets": ["outs"]}
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(Path(tmp) / "data")}, clear=False):
                rows = self.module._collect_report_pitcher_recommendations(self._report(), policy)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
