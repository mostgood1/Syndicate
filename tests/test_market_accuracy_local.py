from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.mlb.market_accuracy import build_market_accuracy_payload as build_mlb_market_accuracy
from syndicate.features.nba.market_accuracy import build_market_accuracy_payload as build_nba_market_accuracy
from syndicate.features.wnba.market_accuracy import build_market_accuracy_payload as build_wnba_market_accuracy


def _write_market_accuracy_artifacts(root: Path, date_str: str) -> None:
    (root / f"recommendations_{date_str}.csv").write_text(
        "market,side,home,away,date,ev,price,implied_prob,edge,line,pred_margin,market_home_margin,pred_total,tier\n"
        f"ATS,Home Team,Home Team,Away Team,{date_str},0.01,-110,0.52,1.0,-4.5,5.5,4.5,,Low\n"
        f"TOTAL,Over,Home Team,Away Team,{date_str},0.02,-110,0.52,1.0,160.5,,,165.0,Low\n",
        encoding="utf-8",
    )
    (root / f"recon_games_{date_str}.csv").write_text(
        "game_id,home_team,visitor_team,home_pts,visitor_pts,total_actual\n"
        "1234567890,Home Team,Away Team,90,80,170\n",
        encoding="utf-8",
    )
    plays = json.dumps([
        {"market": "pts", "side": "OVER", "line": 19.5, "price": -110, "ev_pct": 5.0}
    ])
    (root / f"props_recommendations_{date_str}.csv").write_text(
        f"player,team,plays\nJane Doe,HTM,{json.dumps(plays)}\n",
        encoding="utf-8",
    )
    (root / f"recon_props_{date_str}.csv").write_text(
        "game_id,player_name,team_abbr,pts\n1234567890,Jane Doe,HTM,24\n",
        encoding="utf-8",
    )


class LocalMarketAccuracyTests(unittest.TestCase):
    def test_mlb_market_accuracy_uses_betting_day_payload_results(self) -> None:
        build_mlb_market_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            payload_path = artifact_root / "season_betting_day_2026_05_19.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "date": "2026-05-19",
                        "profile": "retuned",
                        "results": {
                            "ml": {"n": 1, "wins": 1, "losses": 0, "stake_u": 1.0, "profit_u": 0.9},
                            "totals": {"n": 1, "wins": 0, "losses": 1, "stake_u": 1.0, "profit_u": -1.0},
                            "pitcher_props": {"n": 1, "wins": 1, "losses": 0, "stake_u": 1.0, "profit_u": 1.2},
                            "hitter_props": {"n": 2, "wins": 1, "losses": 1, "stake_u": 1.0, "profit_u": -0.1},
                            "combined": {"n": 5, "wins": 3, "losses": 2, "stake_u": 4.0, "profit_u": 1.0},
                        },
                        "games": {
                            "12345": {
                                "markets": {
                                    "ml": {"away_abbr": "AWY", "home_abbr": "HOM"}
                                },
                                "settled_rows": [
                                    {
                                        "game_pk": 12345,
                                        "market": "ml",
                                        "selection": "away",
                                        "odds": "+130",
                                        "stake_u": 1.0,
                                        "actual": "away",
                                        "result": "win",
                                        "profit_u": 1.3,
                                    }
                                ],
                                "playable_settled_rows": [
                                    {
                                        "game_pk": 12345,
                                        "market": "pitcher_props",
                                        "player_name": "Jane Pitcher",
                                        "selection": "under",
                                        "market_line": 17.5,
                                        "actual": 16.0,
                                        "odds": "+110",
                                        "stake_u": 1.0,
                                        "result": "win",
                                        "profit_u": 1.1,
                                    }
                                ],
                                "all_settled_rows": [
                                    {
                                        "game_pk": 12345,
                                        "market": "hitter_hits",
                                        "player_name": "Jane Hitter",
                                        "selection": "over",
                                        "market_line": 0.5,
                                        "actual": 1.0,
                                        "odds": "-125",
                                        "stake_u": 0.5,
                                        "result": "win",
                                        "profit_u": 0.4,
                                    }
                                ],
                            }
                        },
                        "summary": {"warnings": ["Removed 1 low-support card"]},
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "syndicate.features.mlb.market_accuracy.season_betting_card_day_path",
                return_value=payload_path,
            ):
                payload = build_mlb_market_accuracy("date=2026-05-19")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "accuracy-market-v1")
        self.assertEqual(payload["summary"]["combined"]["overall"]["wins"], 3)
        self.assertEqual(payload["summary"]["games"]["overall"]["losses"], 1)
        self.assertEqual(payload["summary"]["props"]["overall"]["bets"], 3)
        self.assertEqual(len(payload["days"][0]["rows"]["official"]), 1)
        self.assertEqual(payload["days"][0]["rows"]["official"][0]["matchup"], "AWY @ HOM")
        self.assertEqual(payload["days"][0]["rows"]["playable"][0]["title"], "Jane Pitcher Under 17.5 Pitcher Props")

    def test_wnba_market_accuracy_prefers_local_artifacts(self) -> None:
        build_wnba_market_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_market_accuracy_artifacts(artifact_root, "2026-05-19")
            # the module resolves its artifact directory via _artifact_root()
            with patch(
                "syndicate.features.wnba.market_accuracy._artifact_root",
                return_value=artifact_root,
            ):
                payload = build_wnba_market_accuracy("date=2026-05-19")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "accuracy-market-v1")
        self.assertEqual(payload["summary"]["combined"]["overall"]["wins"], 2)

    def test_wnba_market_accuracy_returns_local_empty_payload_without_artifacts(self) -> None:
        build_wnba_market_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            with patch(
                "syndicate.features.wnba.market_accuracy._artifact_root",
                return_value=artifact_root,
            ):
                payload = build_wnba_market_accuracy("date=2026-05-19")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["summary"]["combined"]["available"])

    def test_nba_market_accuracy_uses_local_artifacts_when_present(self) -> None:
        build_nba_market_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_market_accuracy_artifacts(artifact_root, "2026-05-19")
            # fully local now: no source_api_json fallback seam remains
            with patch(
                "syndicate.features.nba.market_accuracy._artifact_root",
                return_value=artifact_root,
            ):
                payload = build_nba_market_accuracy("date=2026-05-19")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "accuracy-market-v1")
        self.assertEqual(payload["summary"]["combined"]["overall"]["wins"], 2)