import unittest

from syndicate.features.mlb.game_state import mlb_status_is_final
from syndicate.features.mlb.game_state import mlb_status_is_live


class MlbGameStateTests(unittest.TestCase):
    def test_warmup_is_not_live_even_though_abstract_reads_live(self) -> None:
        # #98/#100: MLB StatsAPI reports status.abstract "Live" during warmup,
        # before the game has actually started. detailedState "Warmup" is the
        # only reliable signal. Real production example: BAL @ DET.
        self.assertFalse(mlb_status_is_live("Live", "Warmup"))
        self.assertFalse(mlb_status_is_final("Live", "Warmup"))

    def test_pregame_states_are_not_live(self) -> None:
        for detailed in ("Pre-Game", "Scheduled", "Preview"):
            self.assertFalse(mlb_status_is_live("Preview", detailed))

    def test_in_progress_is_live(self) -> None:
        self.assertTrue(mlb_status_is_live("Live", "In Progress"))

    def test_final_is_not_live(self) -> None:
        self.assertFalse(mlb_status_is_live("Final", "Final"))
        self.assertTrue(mlb_status_is_final("Final", "Final"))
        # abstractGameState alone reporting Final is enough, independent of
        # detailedState wording ("Game Over", "Completed Early", etc.).
        self.assertTrue(mlb_status_is_final("Final", "Game Over"))
        self.assertTrue(mlb_status_is_final("Final", "Completed Early"))
        self.assertFalse(mlb_status_is_live("Final", "Completed Early"))

    def test_missing_detailed_state_falls_back_to_abstract(self) -> None:
        self.assertTrue(mlb_status_is_live("Live", ""))
        self.assertFalse(mlb_status_is_live("Preview", ""))

    def test_missing_everything_is_not_live_or_final(self) -> None:
        self.assertFalse(mlb_status_is_live(None, None))
        self.assertFalse(mlb_status_is_final(None, None))


if __name__ == "__main__":
    unittest.main()
