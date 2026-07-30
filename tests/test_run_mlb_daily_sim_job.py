from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.run_mlb_daily_sim_job import _hydrate_vendor_oddsapi_mirror


def _write_snapshot(data_root: Path, date_str: str, filename: str, payload: dict) -> Path:
    snapshot_dir = data_root / "mlb_source" / "source_artifacts" / "data" / "daily" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / filename
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class HydrateVendorOddsapiMirrorTests(unittest.TestCase):
    # tools/daily_update_multi_profile.py's K-ladder-targets builder reads
    # pitcher prop lines from a vendored tool-local tree
    # (vendor/mlb_bettingv2/data/market/oddsapi/) that the odds orchestrator
    # never writes to directly -- it only publishes into the shared
    # data/mlb_source/source_artifacts/data/daily/snapshots/<date>/ mirror.
    # These tests cover _hydrate_vendor_oddsapi_mirror, the local-copy step
    # that closes that gap without making any network/OddsAPI call.

    def test_copies_snapshot_into_vendor_tree_when_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write_snapshot(
                data_root,
                "2026-07-30",
                "oddsapi_pitcher_props_2026_07_30.json",
                {"pitcher_props": {"shane mcclanahan": {"strikeouts": {"line": 4.5}}}},
            )
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}):
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
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                dest_dir = vendor_cwd / "data" / "market" / "oddsapi"
                for kind in ("game_lines", "pitcher_props", "hitter_props"):
                    self.assertTrue((dest_dir / f"oddsapi_{kind}_2026_07_30.json").exists())

    def test_missing_snapshot_is_a_silent_noop(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                self.assertFalse((vendor_cwd / "data" / "market" / "oddsapi").exists())

    def test_does_not_overwrite_an_up_to_date_vendor_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write_snapshot(
                data_root, "2026-07-30", "oddsapi_pitcher_props_2026_07_30.json", {"pitcher_props": {"a": 1}}
            )
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                dest = vendor_cwd / "data" / "market" / "oddsapi" / "oddsapi_pitcher_props_2026_07_30.json"
                mtime_before = dest.stat().st_mtime_ns
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                self.assertEqual(dest.stat().st_mtime_ns, mtime_before)

    def test_refreshes_vendor_copy_when_snapshot_is_newer(self) -> None:
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            snapshot_path = _write_snapshot(
                data_root, "2026-07-30", "oddsapi_pitcher_props_2026_07_30.json", {"pitcher_props": {"a": 1}}
            )
            vendor_cwd = Path(tmp) / "vendor" / "mlb_bettingv2"
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}):
                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                dest = vendor_cwd / "data" / "market" / "oddsapi" / "oddsapi_pitcher_props_2026_07_30.json"

                new_mtime = snapshot_path.stat().st_mtime + 5
                os.utime(snapshot_path, (new_mtime, new_mtime))
                snapshot_path.write_text(json.dumps({"pitcher_props": {"a": 2}}), encoding="utf-8")
                os.utime(snapshot_path, (new_mtime, new_mtime))

                _hydrate_vendor_oddsapi_mirror("2026-07-30", vendor_cwd)
                self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), {"pitcher_props": {"a": 2}})


if __name__ == "__main__":
    unittest.main()
