from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class WnbaRefreshRunnerZeroRecsTests(unittest.TestCase):
    @staticmethod
    def _load_module(repo_root: Path):
        script_path = repo_root / "scripts" / "refresh_wnba_oddsapi_props.py"
        spec = importlib.util.spec_from_file_location("test_refresh_wnba_oddsapi_props_zero_recs", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_main_does_not_fail_when_recommendations_rows_are_zero(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            source_root.mkdir(parents=True, exist_ok=True)
            artifact_root.mkdir(parents=True, exist_ok=True)

            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                "2026-06-22",
                "--regions",
                "us",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
                "--mode",
                "fast",
            ]
            fake_state = {
                "date": "2026-06-22",
                "started_at": "2026-06-23T02:00:00Z",
                "ended_at": "2026-06-23T02:00:05Z",
                "phase": "done",
                "phase_started_at": "2026-06-23T02:00:05Z",
                "heartbeat_at": "2026-06-23T02:00:05Z",
                "rc_snapshot": 0,
                "rc_edges": 0,
                "rc_export": 0,
                "snapshot_rows": 12,
                "predictions_rows": 8,
                "edges_rows": 6,
                "recs_rows": 0,
                "game_cards_rows": 2,
                "snapshot_path": str(source_root / "data" / "raw" / "odds_wnba_player_props_2026-06-22.csv"),
                "predictions_path": str(artifact_root / "data" / "processed" / "props_predictions_2026-06-22.csv"),
                "edges_path": str(artifact_root / "data" / "processed" / "props_edges_2026-06-22.csv"),
                "recs_path": str(artifact_root / "data" / "processed" / "props_recommendations_2026-06-22.csv"),
                "snapshot_alias_path": str(artifact_root / "data" / "processed" / "oddsapi_player_props_2026-06-22.csv"),
                "snapshot_alias_rows": 12,
                "duration_s": 5.0,
                "error": None,
                "mode": "fast",
            }

            with patch.object(module, "_existing_refresh_state", return_value=None), patch.object(module, "_existing_artifact_bundle_state", return_value=None), patch.object(module, "_run_refresh_via_cli", return_value=fake_state), patch.object(module, "_run_playoff_transition_if_needed", return_value={"status": "unavailable"}), patch.object(sys, "argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)

    def test_main_does_not_fail_when_refresh_produces_no_rows(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            source_root.mkdir(parents=True, exist_ok=True)
            artifact_root.mkdir(parents=True, exist_ok=True)

            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                "2026-06-29",
                "--regions",
                "us",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
                "--mode",
                "full",
            ]
            fake_state = {
                "date": "2026-06-29",
                "started_at": "2026-06-23T02:00:00Z",
                "ended_at": "2026-06-23T02:00:05Z",
                "phase": "done",
                "phase_started_at": "2026-06-23T02:00:05Z",
                "heartbeat_at": "2026-06-23T02:00:05Z",
                "rc_snapshot": 2,
                "rc_edges": 1,
                "rc_export": 1,
                "snapshot_rows": 0,
                "predictions_rows": 0,
                "edges_rows": 0,
                "recs_rows": 0,
                "game_cards_rows": 0,
                "snapshot_path": str(source_root / "data" / "raw" / "odds_wnba_player_props_2026-06-29.csv"),
                "predictions_path": str(artifact_root / "data" / "processed" / "props_predictions_2026-06-29.csv"),
                "edges_path": str(artifact_root / "data" / "processed" / "props_edges_2026-06-29.csv"),
                "recs_path": str(artifact_root / "data" / "processed" / "props_recommendations_2026-06-29.csv"),
                "snapshot_alias_path": str(artifact_root / "data" / "processed" / "oddsapi_player_props_2026-06-29.csv"),
                "snapshot_alias_rows": 0,
                "duration_s": 5.0,
                "error": None,
                "mode": "full",
            }

            with patch.object(module, "_existing_refresh_state", return_value=None), patch.object(module, "_existing_artifact_bundle_state", return_value=None), patch.object(module, "_run_refresh_via_cli", return_value=fake_state), patch.object(module, "_run_playoff_transition_if_needed", return_value={"status": "unavailable"}), patch.object(sys, "argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)

    def test_zero_recs_refresh_still_writes_recommendations_slate(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            processed_root = tmp_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            (processed_root / "game_cards_2026-06-22.csv").write_text(
                "gamePk,away_tri,home_tri,commence_time\n",
                encoding="utf-8",
            )

            rc, out_path = module._build_local_recommendations_slate_artifact(
                processed_root=processed_root,
                date_str="2026-06-22",
            )

            self.assertEqual(rc, 0)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            self.assertTrue(out_path.exists())
            payload = out_path.read_text(encoding="utf-8")
            self.assertIn('"date": "2026-06-22"', payload)
            self.assertIn('"per_game": []', payload)

    def test_schedule_only_slate_keeps_all_games_without_picks(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            processed_root = tmp_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            (processed_root / "game_cards_2026-06-28.csv").write_text(
                "game_id,home_team,visitor_team,commence_time,home_tri,away_tri\n",
                encoding="utf-8",
            )
            (processed_root / "schedule_2026.csv").write_text(
                "game_id,season_year,game_label,game_subtype,season_type_slug,game_status,game_status_text,date_utc,time_utc,datetime_utc,date_est,time_est,datetime_est,home_team_id,home_tricode,home_city,home_name,away_team_id,away_tricode,away_city,away_name,arena_name,arena_city,arena_state,broadcasters_national\n"
                "401857028,2026,Regular Season,STD,regular-season,1,Scheduled,2026-06-28,00:00,2026-06-28 00:00:00+00:00,2026-06-27,20:00,2026-06-27 20:00:00-04:00,5,IND,Indiana,Fever,6,LAS,Los Angeles,Sparks,Gainbridge Fieldhouse,Indianapolis,IN,CBS | Paramount+\n"
                "401857029,2026,Regular Season,STD,regular-season,1,Scheduled,2026-06-28,01:00,2026-06-28 01:00:00+00:00,2026-06-27,21:00,2026-06-27 21:00:00-04:00,14,SEA,Seattle,Storm,20,ATL,Atlanta,Dream,Climate Pledge Arena,Seattle,WA,WNBA League Pass | Atlanta News First | Victory+ ATL | KOMO-TV | Prime Video-Seattle\n"
                "401857030,2026,Regular Season,STD,regular-season,1,Scheduled,2026-06-28,18:00,2026-06-28 18:00:00+00:00,2026-06-28,14:00,2026-06-28 14:00:00-04:00,3,DAL,Dallas,Wings,8,MIN,Minnesota,Lynx,College Park Center,Arlington,TX,CBS | Paramount+\n"
                "401857031,2026,Regular Season,STD,regular-season,1,Scheduled,2026-06-28,19:00,2026-06-28 19:00:00+00:00,2026-06-28,15:00,2026-06-28 15:00:00-04:00,16,WSH,Washington,Mystics,132052,POR,Portland,Fire,CareFirst Arena,Washington,DC,WNBA League Pass | Fox 12 Plus | MNMT\n",
                encoding="utf-8",
            )

            rc, out_path = module._build_local_recommendations_slate_artifact(
                processed_root=processed_root,
                date_str="2026-06-28",
            )

            self.assertEqual(rc, 4)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            payload = out_path.read_text(encoding="utf-8")
            self.assertIn('"date": "2026-06-28"', payload)
            self.assertIn('"games": 4', payload)
            self.assertIn('"picks": 0', payload)
            self.assertIn('"per_game": [', payload)


if __name__ == "__main__":
    unittest.main()
