from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.wnba.cards import _source_game_from_row
from syndicate.features.wnba.cards import build_source_cards_payload


class WnbaCardsEvidencePackTests(unittest.TestCase):
    def test_source_game_from_row_builds_normalized_evidence_pack(self) -> None:
        row = {
            "visitor_team": "Las Vegas Aces",
            "home_team": "Indiana Fever",
            "away_tri": "LAS",
            "home_tri": "IND",
            "commence_time": "2026-07-02T23:00:00Z",
            "pred_total": 169.5,
            "pred_margin": 5.5,
        }
        picks = [
            {
                "display_pick": "Aces -2.5",
                "selection": "HOME",
                "market": "spread",
                "line": -2.5,
                "price": -110,
                "p_win": 0.72,
                "ev_pct": 4.8,
                "basketball_summary": "Model projects the home side and a clean spread edge.",
                "tier": "A",
                "recommendation_priority_score": 8.4,
                "historical_context": {"roi_segment": 0.142, "sample_size": 28},
            }
        ]

        game = _source_game_from_row(
            row,
            idx=1,
            selected_date="2026-07-02",
            rec_index={("LAS", "IND"): picks},
            sim_index={},
            props_index={},
        )

        evidence_pack = game.get("evidence_pack") or []
        self.assertEqual(len(evidence_pack), 1)
        first = evidence_pack[0]
        self.assertEqual(first.get("plain_text"), "Aces -2.5")
        self.assertEqual(first.get("confidence"), "A")
        self.assertEqual(first.get("market_line"), "-2.5")
        self.assertEqual(first.get("best_reason"), "Model projects the home side and a clean spread edge.")
        self.assertEqual(first.get("historical_context"), "Historical context: +0.142 ROI across 28 settled bets")
        self.assertEqual(first.get("edge_pct"), 4.8)
        self.assertEqual(first.get("win_probability"), 0.72)
        self.assertIn("Score", str(first.get("model_projection")))
        self.assertGreaterEqual(len(first.get("show_more_lines") or []), 5)

    def test_source_cards_payload_propagates_evidence_pack(self) -> None:
        artifact_bundle = {
            "rows": [
                {
                    "visitor_team": "Las Vegas Aces",
                    "home_team": "Indiana Fever",
                    "away_tri": "LAS",
                    "home_tri": "IND",
                    "gamePk": "401857500",
                    "event_id": "401857500",
                    "commence_time": "2026-07-02T23:00:00Z",
                    "pred_total": 169.5,
                    "pred_margin": 5.5,
                }
            ],
            "recommendations": {
                ("LAS", "IND"): [
                    {
                        "display_pick": "Aces -2.5",
                        "selection": "HOME",
                        "market": "spread",
                        "line": -2.5,
                        "price": -110,
                        "p_win": 0.72,
                        "ev_pct": 4.8,
                        "basketball_summary": "Model projects the home side and a clean spread edge.",
                        "tier": "A",
                        "recommendation_priority_score": 8.4,
                        "historical_context": {"roi_segment": 0.142, "sample_size": 28},
                    }
                ]
            },
            "sim": {},
            "props": {},
        }

        with patch("syndicate.features.wnba.cards._artifact_bundle", return_value=artifact_bundle), patch(
            "syndicate.features.wnba.cards.has_games_for_date",
            return_value=True,
        ):
            payload = build_source_cards_payload("2026-07-02", allow_stored_date_fallback=False)

        game = (payload.get("games") or [{}])[0]
        evidence_pack = game.get("evidence_pack") or []
        self.assertEqual(payload.get("date"), "2026-07-02")
        self.assertEqual(len(evidence_pack), 1)
        self.assertEqual(evidence_pack[0].get("plain_text"), "Aces -2.5")
        self.assertEqual(evidence_pack[0].get("confidence"), "A")

    def test_evidence_pack_handles_missing_values_gracefully(self) -> None:
        row = {
            "visitor_team": "Las Vegas Aces",
            "home_team": "Indiana Fever",
            "away_tri": "LAS",
            "home_tri": "IND",
            "commence_time": "2026-07-02T23:00:00Z",
        }
        picks = [
            {
                "display_pick": "Aces ML",
                "selection": "HOME",
                "market": "moneyline",
            }
        ]

        game = _source_game_from_row(
            row,
            idx=1,
            selected_date="2026-07-02",
            rec_index={("LAS", "IND"): picks},
            sim_index={},
            props_index={},
        )

        evidence_pack = game.get("evidence_pack") or []
        self.assertEqual(len(evidence_pack), 1)
        first = evidence_pack[0]
        self.assertEqual(first.get("confidence"), "-")
        self.assertEqual(first.get("edge_pct"), None)
        self.assertEqual(first.get("win_probability"), None)
        self.assertEqual(first.get("market_line"), "-")
        self.assertEqual(first.get("best_reason"), "Aces ML")
        self.assertIsInstance(first.get("show_more_lines"), list)

    def test_cards_parity_source_contains_main_board_evidence_pack_markup(self) -> None:
        js_path = Path(__file__).resolve().parents[1] / "syndicate" / "static" / "wnba" / "cards-parity.js"
        js_content = js_path.read_text(encoding="utf-8")

        self.assertIn("renderEvidencePack(game)", js_content)
        self.assertIn("Main board evidence pack", js_content)
        self.assertIn("cards-evidence-card", js_content)
        self.assertIn("cards-evidence-more", js_content)
        self.assertIn("Show more lines", js_content)
        self.assertIn("cards-live-lens-grid cards-evidence-pack-grid", js_content)

    def test_cards_parity_source_contains_prop_lens_promotion_markup(self) -> None:
        js_path = Path(__file__).resolve().parents[1] / "syndicate" / "static" / "wnba" / "cards-parity.js"
        js_content = js_path.read_text(encoding="utf-8")

        self.assertIn("Why This Pick", js_content)
        self.assertIn("Confidence", js_content)
        self.assertIn("Projection", js_content)
        self.assertIn("Win Probability", js_content)
        self.assertIn("Edge ${fmtPercentValue(evPct)}", js_content)
        self.assertIn("Confidence ${confidence}", js_content)


if __name__ == "__main__":
    unittest.main()