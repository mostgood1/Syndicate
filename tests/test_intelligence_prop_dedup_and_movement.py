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


class OddsHistoryPlayerIndexTests(unittest.TestCase):
    """2026-07-24 fix: _candidate_odds_history_state used to linear-scan
    every market for every candidate. Fine when MLB only had ~33 game-level
    entries, but once MLB prop odds-history started being written
    (same-day fix), that payload grew past 3,000 entries and the resulting
    O(candidates * markets) scan made one production compute cycle take
    147s instead of ~1.3s, directly contributing to a worker timeout and
    an empty board. _build_odds_history_player_index buckets by player so
    a prop candidate only ever scans its own player's handful of entries.
    """

    def _big_odds_history(self, *, real_player: str, other_player_count: int) -> dict:
        markets = {
            "event_id=abc|home_team=Milwaukee Brewers|away_team=Colorado Rockies|market=h2h|bookmaker=draftkings": {"last_line": -258.0},
        }
        for i in range(other_player_count):
            markets[f"player_name=filler player {i}|market=strikeouts|selection=over"] = {"last_line": 3.5}
        markets[f"player_name={real_player}|market=strikeouts|selection=over"] = {"last_line": 3.5, "last_odds": 106.0}
        return {"markets": markets}

    def test_prop_candidate_only_scans_its_own_player_bucket(self) -> None:
        odds_history = self._big_odds_history(real_player="tomoyuki sugano", other_player_count=2000)
        index = intelligence._build_odds_history_player_index(odds_history)
        by_player, unattributed = index
        # 2000 filler players + the real one = 2001 buckets; the game-level
        # entry is the only thing in the unattributed pool.
        self.assertEqual(len(by_player), 2001)
        self.assertEqual(len(unattributed), 1)

        candidate = {
            "candidate_type": "prop",
            "player_name": "Tomoyuki Sugano",
            "matchup": "COL @ MIL",
            "market": "strikeouts",
            "pick": "Over 3.5",
            "name": "Over 3.5",
            "line": "3.5",
        }
        market_key, state = intelligence._candidate_odds_history_state(candidate, index)
        self.assertIsNotNone(state)
        self.assertIn("tomoyuki sugano", market_key.lower())

    def test_game_candidate_still_matches_via_unattributed_pool(self) -> None:
        odds_history = self._big_odds_history(real_player="tomoyuki sugano", other_player_count=50)
        index = intelligence._build_odds_history_player_index(odds_history)
        game_candidate = {
            "candidate_type": "game",
            "matchup": "COL @ MIL",
            "market": "Moneyline",
            "pick": "Home ML",
            "name": "Home ML",
            "line": "-258",
        }
        market_key, state = intelligence._candidate_odds_history_state(game_candidate, index)
        self.assertIsNotNone(state)
        self.assertIn("h2h", market_key)

    def test_empty_odds_history_returns_empty_index(self) -> None:
        by_player, unattributed = intelligence._build_odds_history_player_index(None)
        self.assertEqual(by_player, {})
        self.assertEqual(unattributed, [])


if __name__ == "__main__":
    unittest.main()
