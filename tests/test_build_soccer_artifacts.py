from __future__ import annotations

import importlib.util
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _load_module(repo_root: Path):
    script_path = repo_root / "scripts" / "build_soccer_artifacts.py"
    spec = importlib.util.spec_from_file_location("test_build_soccer_artifacts", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LoadPlayerRowsTests(unittest.TestCase):
    # #170. Root-caused live 2026-07-31: MLS's board had a fully populated
    # match-level sim (real win probability, projected score, "Simulations:
    # 400") but zero player props for its one match of the day, while every
    # other tracked league had real player-prop counts on the same board at
    # the same time. Traced to `_load_player_rows` having no error path for
    # a missing/empty roster CSV (the same "no error path" shape #146/#148
    # already found and fixed one step downstream of this exact function) --
    # an empty or absent `players/` directory silently returns `[]`, so
    # `adapter.simulate_props()` runs "successfully" every cycle with zero
    # player_outputs and nothing anywhere flags it. These tests lock in the
    # new SOCCER_PLAYER_ROWS_MISSING diagnostic for both failure shapes
    # (directory absent; files present but empty) without changing the
    # return value in either case, and confirm the real-data path is silent
    # and unaffected.

    def test_missing_players_directory_logs_and_returns_empty(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            with patch("sys.stdout", new_callable=StringIO) as captured_stdout:
                rows = module._load_player_rows("mls", source_root)

        self.assertEqual(rows, [])
        log_output = captured_stdout.getvalue()
        self.assertIn("SOCCER_PLAYER_ROWS_MISSING", log_output)
        self.assertIn("league=mls", log_output)

    def test_empty_players_csv_logs_and_returns_empty(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            players_dir = source_root / "mls" / "players"
            players_dir.mkdir(parents=True)
            (players_dir / "players_2026.csv").write_text(
                "league,season,player_id,player_name,team,position,minutes,games,"
                "shots_per90,xg_per90,xa_per90,goals_per90,assists_per90,"
                "key_passes_per90,expected_minutes_share,is_goalkeeper,source\n",
                encoding="utf-8",
            )
            with patch("sys.stdout", new_callable=StringIO) as captured_stdout:
                rows = module._load_player_rows("mls", source_root)

        self.assertEqual(rows, [])
        log_output = captured_stdout.getvalue()
        self.assertIn("SOCCER_PLAYER_ROWS_MISSING", log_output)
        self.assertIn("league=mls", log_output)

    def test_real_roster_data_loads_silently(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        repo_root = Path(__file__).resolve().parents[1]
        source_root = repo_root / "data" / "soccer_source"

        with patch("sys.stdout", new_callable=StringIO) as captured_stdout:
            rows = module._load_player_rows("mls", source_root)

        self.assertGreater(len(rows), 0)
        self.assertNotIn("SOCCER_PLAYER_ROWS_MISSING", captured_stdout.getvalue())
        teams = {str(row.get("team") or "") for row in rows}
        self.assertIn("New York City FC", teams)
        self.assertIn("Toronto FC", teams)


if __name__ == "__main__":
    unittest.main()
