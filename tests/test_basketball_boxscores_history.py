from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from syndicate.features.shared.basketball_boxscores_history import (
    boxscore_history_is_stale,
    boxscore_history_max_date,
)


class BoxscoreHistoryFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.processed_root = Path(self._tmp.name)

    def _write_csv(self, dates: list[str]) -> None:
        header = "game_id,PLAYER_ID,PLAYER_NAME,date\n"
        rows = "\n".join(f"g{i},1,Player,{d}" for i, d in enumerate(dates))
        (self.processed_root / "boxscores_history.csv").write_text(header + rows + "\n", encoding="utf-8")

    def test_missing_file_is_stale_with_no_max_date(self) -> None:
        self.assertIsNone(boxscore_history_max_date(self.processed_root))
        self.assertTrue(boxscore_history_is_stale(self.processed_root, max_age_days=5))

    def test_empty_file_is_stale(self) -> None:
        (self.processed_root / "boxscores_history.csv").write_text("game_id,PLAYER_ID,PLAYER_NAME,date\n", encoding="utf-8")
        self.assertIsNone(boxscore_history_max_date(self.processed_root))
        self.assertTrue(boxscore_history_is_stale(self.processed_root, max_age_days=5))

    def test_recent_date_is_not_stale(self) -> None:
        import pandas as pd

        today = pd.Timestamp.now().normalize()
        recent = (today - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        self._write_csv([recent])
        self.assertFalse(boxscore_history_is_stale(self.processed_root, max_age_days=5))

    def test_old_date_is_stale(self) -> None:
        import pandas as pd

        today = pd.Timestamp.now().normalize()
        old = (today - pd.Timedelta(days=25)).strftime("%Y-%m-%d")
        self._write_csv([old])
        self.assertTrue(boxscore_history_is_stale(self.processed_root, max_age_days=5))

    def test_max_date_picks_the_newest_row(self) -> None:
        import pandas as pd

        self._write_csv(["2026-06-01", "2026-07-07", "2026-06-28"])
        max_date = boxscore_history_max_date(self.processed_root)
        self.assertEqual(max_date.strftime("%Y-%m-%d"), "2026-07-07")

    def test_boundary_at_exactly_max_age_days_is_not_stale(self) -> None:
        import pandas as pd

        today = pd.Timestamp.now().normalize()
        boundary = (today - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        self._write_csv([boundary])
        self.assertFalse(boxscore_history_is_stale(self.processed_root, max_age_days=5))

    def test_one_day_past_boundary_is_stale(self) -> None:
        import pandas as pd

        today = pd.Timestamp.now().normalize()
        past_boundary = (today - pd.Timedelta(days=6)).strftime("%Y-%m-%d")
        self._write_csv([past_boundary])
        self.assertTrue(boxscore_history_is_stale(self.processed_root, max_age_days=5))


if __name__ == "__main__":
    unittest.main()
