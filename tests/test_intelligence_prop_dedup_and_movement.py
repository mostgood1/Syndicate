from __future__ import annotations

import unittest

from syndicate.features import intelligence


class MergeDuplicatePropCandidatesTests(unittest.TestCase):
    """2026-07-24 fix: the same prop bet (same player/market/line/side) was
    independently produced by two upstream pipelines with different pick
    text ("Over 4+" vs "OVER Tomoyuki Sugano"), so the existing dedup guard
    (which compares exact pick strings) never caught it. Confirmed live on
    the board: a Tomoyuki Sugano strikeouts prop shown twice, one copy with
    Projected populated and no reasoning, the other with reasoning but
    Projected blank.
    """

    def _artifact_style_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Tomoyuki Sugano",
            "market": "strikeouts",
            "pick": "Over 4+",
            "name": "Over 4+",
            "line": "3.5",
            "projected": "4.9",
            "detail": "Over 4+ Strikeouts | Pitcher top props",
        }

    def _game_rec_style_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Tomoyuki Sugano",
            "market": "pitcher strikeouts",
            "pick": "OVER Tomoyuki Sugano",
            "name": "OVER Tomoyuki Sugano",
            "line": "3.5",
            "projected": "-",
            "detail": (
                "The model lands on the over side in 73.5% of sims, while the market "
                "is pricing it closer to 45.7%. The model baseline sits around 4.8 "
                "strikeouts against a line of 3.5."
            ),
        }

    def test_merges_duplicate_across_pipelines_into_one_row(self) -> None:
        candidates = [self._artifact_style_candidate(), self._game_rec_style_candidate()]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 1)

    def test_merged_row_keeps_projected_and_backfills_detail(self) -> None:
        candidates = [self._artifact_style_candidate(), self._game_rec_style_candidate()]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        row = merged[0]
        self.assertEqual(row.get("projected"), "4.9")
        self.assertIn("model baseline sits around 4.8", row.get("detail", ""))

    def test_market_key_normalization_treats_pitcher_prefix_as_same_market(self) -> None:
        bare = self._artifact_style_candidate()
        prefixed = self._game_rec_style_candidate()
        self.assertEqual(
            intelligence._prop_merge_dedup_key(bare)[2],
            intelligence._prop_merge_dedup_key(prefixed)[2],
        )

    def test_different_players_are_not_merged(self) -> None:
        other = self._artifact_style_candidate()
        other["player_name"] = "Shane Drohan"
        other["name"] = "Over 5+"
        candidates = [self._artifact_style_candidate(), other]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 2)

    def test_different_lines_are_not_merged(self) -> None:
        other = self._game_rec_style_candidate()
        other["line"] = "5.5"
        candidates = [self._artifact_style_candidate(), other]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 2)

    def test_game_candidates_are_left_untouched(self) -> None:
        game_candidate = {"candidate_type": "game", "sport_slug": "mlb", "market": "moneyline", "pick": "Home ML"}
        candidates = [game_candidate, dict(game_candidate)]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 2)


class OddsHistoryMatchScoreCrossMarketGuardTests(unittest.TestCase):
    """2026-07-24 fix: a player-prop candidate must never adopt a GAME-level
    market's odds history (h2h/spreads/totals) just because it shares the
    same matchup text. Confirmed live: a Sugano strikeouts-prop candidate
    was showing the Milwaukee Brewers moneyline's price delta as its own
    "Move" value.
    """

    def _prop_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "matchup": "COL @ MIL",
            "market": "pitcher strikeouts",
            "name": "OVER Tomoyuki Sugano",
            "pick": "OVER Tomoyuki Sugano",
            "line": "3.5",
        }

    def test_rejects_game_level_market_key_with_no_player_identity_match(self) -> None:
        market_key = "event_id=abc|home_team=Milwaukee Brewers|away_team=Colorado Rockies|market=h2h|bookmaker=draftkings"
        state = {"last_line": -258.0}
        score = intelligence._candidate_odds_history_match_score(self._prop_candidate(), market_key, state)
        self.assertEqual(score, 0.0)

    def test_accepts_genuine_player_prop_market_key(self) -> None:
        market_key = "event_id=abc|player_name=Tomoyuki Sugano|market=pitcher_strikeouts|bookmaker=draftkings"
        state = {"last_line": 3.5}
        score = intelligence._candidate_odds_history_match_score(self._prop_candidate(), market_key, state)
        self.assertGreater(score, 0.0)

    def test_game_level_candidate_still_matches_game_level_market(self) -> None:
        game_candidate = {
            "candidate_type": "game",
            "matchup": "COL @ MIL",
            "market": "Moneyline",
            "pick": "Home ML",
            "name": "Home ML",
            "line": "-258",
        }
        market_key = "event_id=abc|home_team=Milwaukee Brewers|away_team=Colorado Rockies|market=h2h|bookmaker=draftkings"
        state = {"last_line": -258.0}
        score = intelligence._candidate_odds_history_match_score(game_candidate, market_key, state)
        self.assertGreater(score, 0.0)


if __name__ == "__main__":
    unittest.main()
