from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.run_mlb_daily_sim_job import _hydrate_vendor_oddsapi_mirror
from scripts.run_mlb_daily_sim_job import _parse_game_progress
from scripts.run_mlb_daily_sim_job import _progress_poll_interval_seconds
from scripts.run_mlb_daily_sim_job import _vendor_mlb_data_dir
from scripts.run_mlb_daily_sim_job import _write_progress_snapshot


def _write_snapshot(data_root: Path, date_str: str, filename: str, payload: dict) -> Path:
    snapshot_dir = data_root / "mlb_source" / "source_artifacts" / "data" / "daily" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / filename
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# Every test clears MLB_BETTING_DATA_ROOT/MLB_BETTING_DATA_ROOT_DIR explicitly
# (patch.dict does not clear existing keys by default) -- render.yaml sets
# MLB_BETTING_DATA_ROOT on all three services in production, and a first
# version of this fix wrote to the wrong tree precisely because the fallback
# (vendor_cwd/data, used only when neither var is set) was assumed to be what
# production actually reads. _vendor_mlb_data_dir must be tested under both
# conditions so that mistake can't recur silently.
_NO_OVERRIDE_ENV = {"MLB_BETTING_DATA_ROOT": "", "MLB_BETTING_DATA_ROOT_DIR": ""}


class VendorMlbDataDirTests(unittest.TestCase):
    def test_falls_back_to_vendor_cwd_data_when_unset(self) -> None:
        vendor_cwd = Path("/tmp/vendor/mlb_bettingv2")
        with patch.dict(os.environ, _NO_OVERRIDE_ENV):
            self.assertEqual(_vendor_mlb_data_dir(vendor_cwd), (vendor_cwd / "data").resolve())

    def test_uses_mlb_betting_data_root_override_when_set(self) -> None:
        with TemporaryDirectory() as tmp:
            override = Path(tmp) / "mlb_source" / "source_artifacts" / "data"
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            with patch.dict(os.environ, {**_NO_OVERRIDE_ENV, "MLB_BETTING_DATA_ROOT": str(override)}):
                self.assertEqual(_vendor_mlb_data_dir(vendor_cwd), override.resolve())


class HydrateVendorOddsapiMirrorTests(unittest.TestCase):
    # tools/daily_update_multi_profile.py's K-ladder-targets builder reads
    # pitcher prop lines from _DATA_DIR/market/oddsapi/ -- on Render that's
    # MLB_BETTING_DATA_ROOT/market/oddsapi (render.yaml sets
    # MLB_BETTING_DATA_ROOT to .../mlb_source/source_artifacts/data on all
    # three services), a real subfolder of the same source_artifacts tree the
    # odds orchestrator already keeps synced -- but the orchestrator only
    # ever writes the daily/snapshots/<date>/ copy, never a market/oddsapi/
    # one. These tests cover _hydrate_vendor_oddsapi_mirror, the local-copy
    # step that closes that gap without making any network/OddsAPI call.

    def test_copies_snapshot_into_market_oddsapi_under_data_root_override(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write_snapshot(
                data_root,
                "2026-07-30",
                "oddsapi_pitcher_props_2026_07_30.json",
                {"pitcher_props": {"shane mcclanahan": {"strikeouts": {"line": 4.5}}}},
            )
            source_artifacts_data = data_root / "mlb_source" / "source_artifacts" / "data"
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            env = {**_NO_OVERRIDE_ENV, "SYNDICATE_DATA_ROOT": str(data_root), "MLB_BETTING_DATA_ROOT": str(source_artifacts_data)}
            with patch.dict(os.environ, env):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                # Must land under MLB_BETTING_DATA_ROOT, NOT vendor_cwd/data --
                # the exact distinction the first (wrong) version of this fix missed.
                dest = source_artifacts_data / "market" / "oddsapi" / "oddsapi_pitcher_props_2026_07_30.json"
                vendor_local_miss = vendor_cwd / "data" / "market" / "oddsapi" / "oddsapi_pitcher_props_2026_07_30.json"
                self.assertTrue(dest.exists())
                self.assertFalse(vendor_local_miss.exists())
                self.assertEqual(
                    json.loads(dest.read_text(encoding="utf-8")),
                    {"pitcher_props": {"shane mcclanahan": {"strikeouts": {"line": 4.5}}}},
                )

    def test_copies_snapshot_into_vendor_tree_when_no_override_set(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write_snapshot(
                data_root,
                "2026-07-30",
                "oddsapi_pitcher_props_2026_07_30.json",
                {"pitcher_props": {"shane mcclanahan": {"strikeouts": {"line": 4.5}}}},
            )
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            env = {**_NO_OVERRIDE_ENV, "SYNDICATE_DATA_ROOT": str(data_root)}
            with patch.dict(os.environ, env):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                dest = vendor_cwd / "data" / "market" / "oddsapi" / "oddsapi_pitcher_props_2026_07_30.json"
                self.assertTrue(dest.exists())
                self.assertEqual(
                    json.loads(dest.read_text(encoding="utf-8")),
                    {"pitcher_props": {"shane mcclanahan": {"strikeouts": {"line": 4.5}}}},
                )

    def test_copies_all_three_market_files(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            for kind in ("game_lines", "pitcher_props", "hitter_props"):
                _write_snapshot(data_root, "2026-07-30", f"oddsapi_{kind}_2026_07_30.json", {"kind": kind})
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            env = {**_NO_OVERRIDE_ENV, "SYNDICATE_DATA_ROOT": str(data_root)}
            with patch.dict(os.environ, env):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                dest_dir = vendor_cwd / "data" / "market" / "oddsapi"
                for kind in ("game_lines", "pitcher_props", "hitter_props"):
                    self.assertTrue((dest_dir / f"oddsapi_{kind}_2026_07_30.json").exists())

    def test_missing_snapshot_is_a_silent_noop(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            env = {**_NO_OVERRIDE_ENV, "SYNDICATE_DATA_ROOT": str(data_root)}
            with patch.dict(os.environ, env):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                self.assertFalse((vendor_cwd / "data" / "market" / "oddsapi").exists())

    def test_does_not_overwrite_an_up_to_date_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write_snapshot(
                data_root, "2026-07-30", "oddsapi_pitcher_props_2026_07_30.json", {"pitcher_props": {"a": 1}}
            )
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            env = {**_NO_OVERRIDE_ENV, "SYNDICATE_DATA_ROOT": str(data_root)}
            with patch.dict(os.environ, env):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                dest = vendor_cwd / "data" / "market" / "oddsapi" / "oddsapi_pitcher_props_2026_07_30.json"
                mtime_before = dest.stat().st_mtime_ns
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                self.assertEqual(dest.stat().st_mtime_ns, mtime_before)

    def test_refreshes_copy_when_snapshot_is_newer(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            snapshot_path = _write_snapshot(
                data_root, "2026-07-30", "oddsapi_pitcher_props_2026_07_30.json", {"pitcher_props": {"a": 1}}
            )
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            env = {**_NO_OVERRIDE_ENV, "SYNDICATE_DATA_ROOT": str(data_root)}
            with patch.dict(os.environ, env):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                dest = vendor_cwd / "data" / "market" / "oddsapi" / "oddsapi_pitcher_props_2026_07_30.json"

                new_mtime = snapshot_path.stat().st_mtime + 5
                os.utime(snapshot_path, (new_mtime, new_mtime))
                snapshot_path.write_text(json.dumps({"pitcher_props": {"a": 2}}), encoding="utf-8")
                os.utime(snapshot_path, (new_mtime, new_mtime))

                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), {"pitcher_props": {"a": 2}})


class ParseGameProgressTests(unittest.TestCase):
    # Confirmed live 2026-08-02: a scoped sim run sat at "state": "running"
    # for 49+ minutes with no signal at all whether it was progressing or
    # hung -- these lock in the parser that turns the vendored sim's own
    # existing "[N/M] ..." per-game log lines into a readable progress
    # snapshot, without needing to change any vendored code.

    def test_no_progress_markers_returns_none(self) -> None:
        self.assertIsNone(_parse_game_progress("no markers here\njust noise"))

    def test_empty_text_returns_none(self) -> None:
        self.assertIsNone(_parse_game_progress(""))

    def test_single_marker_is_parsed(self) -> None:
        result = _parse_game_progress("[core] Loaded 15 scheduled game(s).\n[3/15] Preparing rosters: LAS @ SEA")
        self.assertEqual(result, {"game_index": 3, "game_total": 15, "last_line": "Preparing rosters: LAS @ SEA"})

    def test_multiple_markers_keeps_the_last_one(self) -> None:
        text = "\n".join(
            [
                "[1/15] Preparing rosters: A @ B",
                "[1/15] Simulating: A @ B",
                "[2/15] Preparing rosters: C @ D",
                "[2/15] Simulating: C @ D",
            ]
        )
        result = _parse_game_progress(text)
        self.assertEqual(result["game_index"], 2)
        self.assertEqual(result["game_total"], 15)
        self.assertEqual(result["last_line"], "Simulating: C @ D")

    def test_last_line_is_truncated(self) -> None:
        long_suffix = "x" * 500
        result = _parse_game_progress(f"[1/1] {long_suffix}")
        self.assertLessEqual(len(result["last_line"]), 200)


class ProgressPollIntervalTests(unittest.TestCase):
    def test_default_is_twenty_seconds(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_MLB_SIM_PROGRESS_POLL_SECONDS", None)
            self.assertEqual(_progress_poll_interval_seconds(), 20)

    def test_env_override_is_honored(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_MLB_SIM_PROGRESS_POLL_SECONDS": "5"}):
            self.assertEqual(_progress_poll_interval_seconds(), 5)

    def test_floor_is_five_seconds(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_MLB_SIM_PROGRESS_POLL_SECONDS": "1"}):
            self.assertEqual(_progress_poll_interval_seconds(), 5)


class WriteProgressSnapshotTests(unittest.TestCase):
    def test_writes_parsed_progress_and_elapsed_time(self) -> None:
        with TemporaryDirectory() as tmp:
            capture_path = Path(tmp) / "sim.log"
            capture_path.write_text("[4/15] Simulating: E @ F", encoding="utf-8")
            progress_path = Path(tmp) / "progress.json"
            _write_progress_snapshot(progress_path, capture_path=capture_path, started_epoch=0.0, done=False)
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["game_index"], 4)
        self.assertEqual(payload["game_total"], 15)
        self.assertFalse(payload["done"])
        self.assertIn("updated_at", payload)
        self.assertGreater(payload["elapsed_seconds"], 0)

    def test_marks_done_true_on_final_write(self) -> None:
        with TemporaryDirectory() as tmp:
            capture_path = Path(tmp) / "sim.log"
            capture_path.write_text("[15/15] Simulating: Y @ Z", encoding="utf-8")
            progress_path = Path(tmp) / "progress.json"
            _write_progress_snapshot(progress_path, capture_path=capture_path, started_epoch=0.0, done=True)
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["done"])

    def test_missing_log_still_writes_a_snapshot(self) -> None:
        with TemporaryDirectory() as tmp:
            capture_path = Path(tmp) / "does_not_exist.log"
            progress_path = Path(tmp) / "progress.json"
            _write_progress_snapshot(progress_path, capture_path=capture_path, started_epoch=0.0, done=False)
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
        self.assertNotIn("game_index", payload)
        self.assertIn("updated_at", payload)


if __name__ == "__main__":
    unittest.main()
