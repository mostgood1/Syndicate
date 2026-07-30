from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _load_module(repo_root: Path):
    script_path = repo_root / "scripts" / "build_soccer_picks.py"
    spec = importlib.util.spec_from_file_location("test_build_soccer_picks", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NormalizePlayerNameTests(unittest.TestCase):
    def test_strips_accents_and_case(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        self.assertEqual(module._normalize_player_name("Kévin Denkey"), "kevin denkey")
        self.assertEqual(module._normalize_player_name("  Kevin   Denkey "), "kevin denkey")


class BuildPropPicksTests(unittest.TestCase):
    # #150 follow-up. build_soccer_picks.py originally only graded game
    # markets (ML/TOTAL/SPREAD); player props (anytime-goalscorer) reached
    # the board with a real simulated probability but no real market price,
    # which intelligence.py's classify_candidate then rejected as
    # missing_projection_or_odds. This grades the sim's
    # anytime_scorer_probability against a real captured price the same way
    # build_picks already grades game markets.
    def _write_fixture(self, tmp_dir: str, *, iso_date: str, props_date: str, player_name: str, odds_player: str) -> Path:
        source_root = Path(tmp_dir)
        rec_dir = source_root / "mls" / "api" / "recommendations"
        rec_dir.mkdir(parents=True, exist_ok=True)
        (rec_dir / f"recommendations_{iso_date}.json").write_text(
            json.dumps(
                {
                    "player_props": [
                        {
                            "player_name": player_name,
                            "team": "Arsenal",
                            "match_id": "12345",
                            "anytime_scorer_probability": 0.35,
                        },
                        {
                            "player_name": "No Odds Player",
                            "team": "Arsenal",
                            "match_id": "12345",
                            "anytime_scorer_probability": 0.10,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        props_dir = source_root / "mls" / "props"
        props_dir.mkdir(parents=True, exist_ok=True)
        props_dir.joinpath(f"{props_date}.csv").write_text(
            "player,market,market_key,line,over_price,under_price,home_team,away_team\n"
            f'"{odds_player}",Anytime Goalscorer,player_goal_scorer_anytime,,150,,Arsenal,Chelsea\n',
            encoding="utf-8",
        )
        return source_root

    def test_grades_matched_player_against_real_price(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            source_root = self._write_fixture(
                tmp_dir, iso_date="2026-08-21", props_date="2026-08-21", player_name="Kevin Denkey", odds_player="Kévin Denkey"
            )
            module = _load_module(Path(__file__).resolve().parents[1])
            df = module.build_prop_picks("mls", "2026-08-21", source_root=source_root)
        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertEqual(row["player"], "Kevin Denkey")
        self.assertEqual(row["market"], "PROP")
        self.assertEqual(row["side"], "anytime_scorer")
        self.assertEqual(row["price"], 150.0)
        self.assertAlmostEqual(row["model_probability"], 0.35)
        self.assertIsNotNone(row["market_probability"])
        self.assertIsNotNone(row["edge"])
        self.assertIsNotNone(row["ev"])

    def test_player_with_no_matching_odds_row_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            source_root = self._write_fixture(
                tmp_dir, iso_date="2026-08-21", props_date="2026-08-21", player_name="Kevin Denkey", odds_player="Kévin Denkey"
            )
            module = _load_module(Path(__file__).resolve().parents[1])
            df = module.build_prop_picks("mls", "2026-08-21", source_root=source_root)
        self.assertNotIn("No Odds Player", df["player"].tolist())

    def test_reads_props_from_a_nearby_date_file(self) -> None:
        # The fetch script files its capture under the day it ran, not the
        # match's own date -- a pregame sweep 2 days before this match is a
        # realistic capture-to-match date gap this must still bridge.
        with TemporaryDirectory() as tmp_dir:
            source_root = self._write_fixture(
                tmp_dir, iso_date="2026-08-21", props_date="2026-08-19", player_name="Kevin Denkey", odds_player="Kevin Denkey"
            )
            module = _load_module(Path(__file__).resolve().parents[1])
            df = module.build_prop_picks("mls", "2026-08-21", source_root=source_root)
        self.assertEqual(len(df), 1)

    def test_no_recommendations_file_returns_empty(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            module = _load_module(Path(__file__).resolve().parents[1])
            df = module.build_prop_picks("mls", "2026-08-21", source_root=Path(tmp_dir))
        self.assertTrue(df.empty)


if __name__ == "__main__":
    unittest.main()
