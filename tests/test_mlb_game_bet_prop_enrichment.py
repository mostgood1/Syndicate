from __future__ import annotations

import unittest

import syndicate.blueprints.home as home


class MlbPropProjectionHelperTests(unittest.TestCase):
    def test_pitcher_prop_uses_stat_specific_mean(self) -> None:
        row = {"prop": "outs", "outs_mean": 20.703, "mean_support": 9.2, "pitcher_id": 679883}
        self.assertAlmostEqual(home._mlb_prop_projected_value(row), 20.703)
        self.assertEqual(home._mlb_prop_player_id(row), 679883)

    def test_hitter_prop_ignores_plate_appearance_means(self) -> None:
        # batter_total_bases carries ab_mean + pa_mean noise alongside the
        # real tb_mean -- a naive "first *_mean" would return plate
        # appearances, not total bases.
        row = {"prop": "batter_total_bases", "ab_mean": 3.9, "pa_mean": 4.3, "tb_mean": 1.55, "batter_id": 670764}
        self.assertAlmostEqual(home._mlb_prop_projected_value(row), 1.55)
        self.assertEqual(home._mlb_prop_player_id(row), 670764)

    def test_unknown_prop_with_single_mean_is_used(self) -> None:
        self.assertAlmostEqual(home._mlb_prop_projected_value({"prop": "novel", "xyz_mean": 7.7}), 7.7)

    def test_unknown_prop_with_ambiguous_means_returns_none(self) -> None:
        self.assertIsNone(home._mlb_prop_projected_value({"prop": "novel", "a_mean": 1, "b_mean": 2}))

    def test_missing_ids_returns_none(self) -> None:
        self.assertIsNone(home._mlb_prop_player_id({"prop": "outs", "outs_mean": 5}))


class MlbGameBetCandidateEnrichmentTests(unittest.TestCase):
    def _game(self) -> dict:
        return {
            "gamePk": 777,
            "game_id": "777",
            "matchup": "KC @ DET",
            "status": {"abstract": "Preview", "detailed": "Pre-Game"},
            "summary": "test",
            "markets": {
                "pitcherProps": [
                    {"prop": "outs", "market": "pitcher_props", "outs_mean": 20.703, "mean_support": 9.2,
                     "pitcher_id": 679883, "pitcher_name": "Luinder Avila", "selection": "over",
                     "market_line": 15.5, "edge": 0.30, "model_prob": 0.75, "odds": "+125"},
                ],
                "hitterProps": [
                    {"prop": "batter_total_bases", "market": "hitter_props", "ab_mean": 3.9, "pa_mean": 4.3,
                     "tb_mean": 1.55, "batter_id": 670764, "player_name": "Some Hitter", "selection": "over",
                     "market_line": 1.5, "edge": 0.18, "model_prob": 0.58, "odds": "+141"},
                ],
            },
        }

    def test_prop_candidates_get_projection_and_headshot(self) -> None:
        cands = home._game_bet_candidates_from_game({"slug": "mlb", "name": "MLB"}, self._game(), fallback_epoch=1784900000.0)
        by_player = {c.get("player_name"): c for c in cands if c.get("player_name")}

        pitcher = by_player.get("Luinder Avila")
        self.assertIsNotNone(pitcher)
        self.assertEqual(pitcher["projected"], "20.7")
        self.assertEqual(pitcher["player_id"], 679883)
        self.assertIn("people/679883/headshot", pitcher["headshot_url"])

        hitter = by_player.get("Some Hitter")
        self.assertIsNotNone(hitter)
        self.assertEqual(hitter["projected"], "1.6")  # tb_mean 1.55, not ab/pa
        self.assertEqual(hitter["player_id"], 670764)
        self.assertIn("people/670764/headshot", hitter["headshot_url"])


if __name__ == "__main__":
    unittest.main()
