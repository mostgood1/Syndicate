from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import fetch_basketball_oddsapi_props_local as fetch_module
from scripts.fetch_basketball_oddsapi_props_local import _latest_existing_snapshot_path


class FetchBasketballOddsapiPropsLocalTests(unittest.TestCase):
    def test_latest_existing_snapshot_path_prefers_latest_prior_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "odds_wnba_player_props_2026-06-27.csv").write_text("a\n1\n", encoding="utf-8")
            (root / "odds_wnba_player_props_2026-06-28.csv").write_text("a\n2\n", encoding="utf-8")
            (root / "odds_wnba_player_props_2026-06-30.csv").write_text("a\n3\n", encoding="utf-8")

            chosen = _latest_existing_snapshot_path(
                out_path=root / "odds_wnba_player_props_2026-06-30.csv",
                target_date="2026-06-30",
            )

            self.assertEqual(chosen, root / "odds_wnba_player_props_2026-06-30.csv")

    def test_latest_existing_snapshot_path_ignores_newer_files_for_prior_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "odds_wnba_player_props_2026-06-27.csv").write_text("a\n1\n", encoding="utf-8")
            (root / "odds_wnba_player_props_2026-06-28.csv").write_text("a\n2\n", encoding="utf-8")
            (root / "odds_wnba_player_props_2026-06-30.csv").write_text("a\n3\n", encoding="utf-8")

            chosen = _latest_existing_snapshot_path(
                out_path=root / "odds_wnba_player_props_2026-06-29.csv",
                target_date="2026-06-29",
            )

            self.assertEqual(chosen, root / "odds_wnba_player_props_2026-06-28.csv")


    def test_main_writes_empty_snapshot_and_does_not_preserve_stale_file_on_confirmed_no_events(self) -> None:
        # Confirmed live 2026-07-23: an all-star-break date's raw snapshot
        # kept preserving a prior day's real 6-game slate forever, because a
        # confirmed "zero real events for this date" fetch result was
        # indistinguishable from "the fetch itself failed". fetch_player_
        # props_current now returns None specifically for the confirmed
        # case; main() must not preserve or fall back to a different date's
        # snapshot when it sees that.
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            out_path = root / "odds_wnba_player_props_2026-07-23.csv"
            # Stale data from an earlier (buggy) run -- a real prior day's slate.
            out_path.write_text("event_id,commence_time,home_team,away_team\nabc,2026-07-22T19:00:00Z,LAS,PHX\n", encoding="utf-8")

            with patch.object(fetch_module, "fetch_player_props_current", return_value=None), patch.dict(
                "os.environ", {"ODDS_API_KEY": "test-key"}, clear=False
            ):
                exit_code = fetch_module.main(
                    ["--league", "wnba", "--date", "2026-07-23", "--out", str(out_path)]
                )

            self.assertEqual(exit_code, 0)
            result_df = pd.read_csv(out_path)
            self.assertTrue(result_df.empty)

    def test_main_preserves_existing_snapshot_on_ambiguous_empty_result(self) -> None:
        # An empty DataFrame (not None) means the fetch was inconclusive
        # (network/API issue), not a confirmed no-events date -- the
        # existing preserve-on-failure behavior must be unchanged.
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            out_path = root / "odds_wnba_player_props_2026-07-23.csv"
            out_path.write_text("event_id,commence_time,home_team,away_team\nabc,2026-07-22T19:00:00Z,LAS,PHX\n", encoding="utf-8")

            with patch.object(fetch_module, "fetch_player_props_current", return_value=pd.DataFrame()), patch.dict(
                "os.environ", {"ODDS_API_KEY": "test-key"}, clear=False
            ):
                exit_code = fetch_module.main(
                    ["--league", "wnba", "--date", "2026-07-23", "--out", str(out_path)]
                )

            self.assertEqual(exit_code, 0)
            result_df = pd.read_csv(out_path)
            self.assertEqual(len(result_df), 1)
            self.assertEqual(result_df.iloc[0]["home_team"], "LAS")


if __name__ == "__main__":
    unittest.main()
