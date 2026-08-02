"""NFL/NCAAF pick cards must carry a game-level "market" key.

home.py's _is_game_level_rank_card_market returns False for a missing
"market" key, so an unstamped team-level pick card flows into
pregame_props() mislabeled as a player prop -- the exact bug class fixed
for WNBA on 2026-07-27. Every football pick-card builder emits game-level
bets only (no props pipeline exists), so every card must be stamped.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.blueprints.home import _is_game_level_rank_card_market
from syndicate.blueprints.home import _pregame_prop_rows_from_betting_card
from syndicate.features.ncaaf import picks as ncaaf_picks
from syndicate.features.nfl import picks as nfl_picks
from syndicate.features.nfl.smartsim2_projection import SmartSimNflProjection


def _projection(game_id: str = "2026_01_ARI_SEA") -> SmartSimNflProjection:
    return SmartSimNflProjection(
        game_id=game_id, season=2026, week=1, home_team="SEA", away_team="ARI",
        home_score_mean=23.2, away_score_mean=21.9, margin_mean=1.3, total_mean=45.1,
        margin_stdev=14.0, total_stdev=11.4, home_win_rate=0.533, seeds_used=300,
        profile_name="nfl_v1", rating_source="test", generated_at="2026-01-01T00:00:00Z",
    )


class NflPickCardMarketStampTests(unittest.TestCase):
    def test_build_cards_stamps_game_level_market(self) -> None:
        rows = [
            {"home_team": "SEA", "away_team": "ARI", "type": "MONEYLINE", "confidence": "High", "ev_pct": 4.2},
            {"home_team": "SEA", "away_team": "ARI", "type": "SPREAD", "confidence": "Medium", "ev_pct": 2.0},
            {"home_team": "SEA", "away_team": "ARI", "type": "TOTAL", "confidence": "Low", "ev_pct": 1.1},
            {"home_team": "SEA", "away_team": "ARI", "type": "EXOTIC", "confidence": "Low", "ev_pct": 0.5},
        ]
        cards = nfl_picks._build_cards(rows)
        self.assertEqual(len(cards), 4)
        for card in cards:
            self.assertTrue(
                _is_game_level_rank_card_market(card.get("market")),
                f"card not stamped game-level: {card.get('title')} -> {card.get('market')!r}",
            )

    def test_standalone_smartsim2_cards_stamp_game_level_market(self) -> None:
        with patch.object(nfl_picks, "read_projection_artifact", return_value=(_projection(),)):
            cards = nfl_picks._standalone_smartsim2_pick_cards(2026, 1)
        self.assertTrue(cards)
        for card in cards:
            self.assertTrue(_is_game_level_rank_card_market(card.get("market")))


class NcaafPickCardMarketStampTests(unittest.TestCase):
    def test_collapse_results_stamps_game_level_market(self) -> None:
        summary = {
            "results": [
                {"home_team": "UGA", "away_team": "BAMA", "market": "moneyline", "side": "UGA", "provider": "book", "edge": 0.05},
                {"home_team": "UGA", "away_team": "BAMA", "market": "spread", "side": "UGA -3.5", "provider": "book", "edge": 0.04},
                {"home_team": "UGA", "away_team": "BAMA", "market": "total", "side": "Over 52.5", "provider": "book", "edge": 0.03},
                {"home_team": "UGA", "away_team": "BAMA", "market": "", "side": "?", "provider": "book", "edge": 0.02},
            ]
        }
        cards = ncaaf_picks._collapse_results(summary)
        self.assertEqual(len(cards), 4)
        for card in cards:
            self.assertTrue(
                _is_game_level_rank_card_market(card.get("market")),
                f"card not stamped game-level: {card.get('title')} -> {card.get('market')!r}",
            )

    def test_standalone_smartsim2_cards_stamp_game_level_market(self) -> None:
        row = {"home_team": "UGA", "away_team": "BAMA", "projection": _projection("2026_01_BAMA_UGA")}
        with patch.object(ncaaf_picks, "_smartsim2_standalone_rows", return_value=[row]):
            cards = ncaaf_picks._standalone_smartsim2_pick_cards(2026, 1)
        self.assertTrue(cards)
        for entry in cards:
            card = entry["card"] if isinstance(entry, dict) and "card" in entry else entry
            self.assertTrue(_is_game_level_rank_card_market(card.get("market")))


class PregamePropsFilterIntegrationTests(unittest.TestCase):
    def test_nfl_game_picks_no_longer_reach_pregame_props(self) -> None:
        rows = [
            {"home_team": "SEA", "away_team": "ARI", "type": "MONEYLINE", "confidence": "High", "ev_pct": 4.2},
            {"home_team": "SEA", "away_team": "ARI", "type": "TOTAL", "confidence": "Low", "ev_pct": 1.1},
        ]
        cards = nfl_picks._build_cards(rows)
        with patch(
            "syndicate.blueprints.home._betting_card_rank_cards",
            return_value=(cards, "/nfl/season/2026/betting-card", None),
        ):
            prop_rows = _pregame_prop_rows_from_betting_card(
                "nfl", context_label="2026 Week 1", season=2026, week=1
            )
        self.assertEqual(prop_rows, [])


if __name__ == "__main__":
    unittest.main()
