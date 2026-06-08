from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from syndicate.features.shared.basketball_props_tracking import (
    enrich_props_edges_with_tracking,
    persist_props_snapshot_tracking,
    sync_basketball_props_tracking_for_source_root,
)


class BasketballPropsTrackingTests(unittest.TestCase):
    def test_persist_tracking_writes_opening_and_deduped_history(self) -> None:
        snapshot_df = pd.DataFrame(
            [
                {
                    "snapshot_ts": "2026-06-07T17:34:36Z",
                    "event_id": "evt-1",
                    "commence_time": "2026-06-07T19:00:00Z",
                    "bookmaker": "fanduel",
                    "market": "player_points",
                    "outcome_name": "Over",
                    "player_name": "Alyssa Thomas",
                    "point": 18.5,
                    "price": -110,
                },
                {
                    "snapshot_ts": "2026-06-07T17:35:36Z",
                    "event_id": "evt-1",
                    "commence_time": "2026-06-07T19:00:00Z",
                    "bookmaker": "fanduel",
                    "market": "player_points",
                    "outcome_name": "Over",
                    "player_name": "Alyssa Thomas",
                    "point": 19.5,
                    "price": -112,
                },
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_dir = Path(tmp_dir)
            first = persist_props_snapshot_tracking(snapshot_df, "2026-06-07", raw_dir=raw_dir, sport="wnba")
            second = persist_props_snapshot_tracking(snapshot_df, "2026-06-07", raw_dir=raw_dir, sport="wnba")

            history_path = raw_dir / "odds_wnba_player_props_history_2026-06-07.csv"
            opening_csv = raw_dir / "odds_wnba_player_props_opening_2026-06-07.csv"

            self.assertEqual(first["opening_rows"], 1)
            self.assertEqual(first["history_appended_rows"], 2)
            self.assertEqual(second["history_appended_rows"], 0)
            self.assertTrue(history_path.exists())
            self.assertTrue(opening_csv.exists())

            history = pd.read_csv(history_path)
            opening = pd.read_csv(opening_csv)

        self.assertEqual(len(history), 2)
        self.assertEqual(len(opening), 1)
        self.assertEqual(float(opening.loc[0, "point"]), 18.5)

    def test_enrich_edges_adds_opening_and_movement_columns(self) -> None:
        snapshot_df = pd.DataFrame(
            [
                {
                    "snapshot_ts": "2026-06-07T17:34:36Z",
                    "event_id": "evt-1",
                    "commence_time": "2026-06-07T19:00:00Z",
                    "bookmaker": "fanduel",
                    "market": "player_points",
                    "outcome_name": "Over",
                    "player_name": "Alyssa Thomas",
                    "point": 18.5,
                    "price": -110,
                }
            ]
        )
        edges_df = pd.DataFrame(
            [
                {
                    "player_name": "Alyssa Thomas",
                    "stat": "pts",
                    "side": "Over",
                    "bookmaker": "fanduel",
                    "line": 20.0,
                    "price": -125,
                    "ev": 0.12,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_dir = Path(tmp_dir)
            persist_props_snapshot_tracking(snapshot_df, "2026-06-07", raw_dir=raw_dir, sport="wnba")
            enriched, meta = enrich_props_edges_with_tracking(edges_df, "2026-06-07", raw_dir=raw_dir, sport="wnba")

        self.assertEqual(meta["rows_with_opening"], 1)
        self.assertEqual(float(enriched.loc[0, "open_line"]), 18.5)
        self.assertEqual(float(enriched.loc[0, "line_move"]), 1.5)
        self.assertEqual(str(enriched.loc[0, "movement_tier"]), "fast")

    def test_sync_for_source_root_writes_signals_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            processed_dir = source_root / "data" / "processed"
            raw_dir = source_root / "data" / "raw"
            processed_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)

            (processed_dir / "oddsapi_player_props_2026-06-07.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,market,outcome_name,player_name,point,price\n"
                "2026-06-07T17:34:36Z,evt-1,2026-06-07T19:00:00Z,fanduel,player_points,Over,Alyssa Thomas,18.5,-110\n",
                encoding="utf-8",
            )
            (processed_dir / "props_edges_2026-06-07.csv").write_text(
                "player_name,stat,side,bookmaker,line,price,ev\n"
                "Alyssa Thomas,pts,Over,fanduel,20.0,-125,0.12\n",
                encoding="utf-8",
            )

            result = sync_basketball_props_tracking_for_source_root(sport="wnba", source_root=source_root, date_str="2026-06-07")

            signals_path = processed_dir / "props_movement_signals_2026-06-07.csv"
            self.assertTrue(result["ok"])
            self.assertFalse(result["skipped"])
            self.assertTrue(signals_path.exists())
            self.assertEqual(result["signals_rows"], 1)
