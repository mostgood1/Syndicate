"""No WNBA refresh on a host with a data root builds SmartSims from vendor/.

Found 2026-10-04 on the WSL fleet: production smart_sim_<D>_*.json files were
md5-identical to copies under ~/Syndicate/vendor/wnba_betting_repo. The writer
was bootstrap_data_root's boot-time WNBA refresh, which set
SYNDICATE_SOURCE_ROOT_WNBA to the vendor tree while the child took its
--artifact-root from SYNDICATE_DATA_ROOT -- so each `local_production.py up`
built sims from the ephemeral checkout (no injuries.csv, injuries_out = 0) and
copied them over prod. Three hops are covered: the boot caller, the
orchestrator's root resolution, and the leaf script every caller reaches.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import refresh_wnba_oddsapi_props as wnba

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_WNBA = REPO_ROOT / "vendor" / "wnba_betting_repo"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"test_vendor_guard_{name}", REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BootRefreshSourceRootTests(unittest.TestCase):
    def test_boot_refresh_never_points_at_vendor(self) -> None:
        module = _load("bootstrap_data_root")
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data-root"
            env = {"SYNDICATE_BOOTSTRAP_ON_START": "1", "SYNDICATE_BOOTSTRAP_WNBA_TODAY": "1"}
            with patch.dict(os.environ, env, clear=False), patch.object(module.subprocess, "Popen") as popen_mock:
                self.assertTrue(module._bootstrap_wnba_today_artifacts(REPO_ROOT, data_root))
            child_env = popen_mock.call_args.kwargs["env"]
            self.assertEqual(child_env["SYNDICATE_SOURCE_ROOT_WNBA"], str(data_root / "wnba_source"))
            # Input root and artifact root are the same tree, by construction.
            self.assertEqual(child_env["SYNDICATE_DATA_ROOT"], str(data_root))


class OrchestratorSourceRootTests(unittest.TestCase):
    def test_vendor_override_is_refused_when_data_root_set(self) -> None:
        module = _load("refresh_odds_sources")
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {"SYNDICATE_DATA_ROOT": temp_dir, "SYNDICATE_SOURCE_ROOT_WNBA": str(VENDOR_WNBA)}
            with patch.dict(os.environ, env, clear=False):
                root = module._basketball_source_root("wnba", "wnba_betting_repo")
            self.assertEqual(root, (Path(temp_dir) / "wnba_source").resolve())

    def test_non_vendor_override_is_honoured(self) -> None:
        module = _load("refresh_odds_sources")
        with tempfile.TemporaryDirectory() as temp_dir:
            custom = Path(temp_dir) / "elsewhere" / "wnba_source"
            env = {"SYNDICATE_DATA_ROOT": temp_dir, "SYNDICATE_SOURCE_ROOT_WNBA": str(custom)}
            with patch.dict(os.environ, env, clear=False):
                root = module._basketball_source_root("wnba", "wnba_betting_repo")
            self.assertEqual(root, custom.resolve())

    def test_vendor_override_allowed_without_data_root(self) -> None:
        # Local dev with no data root keeps its old behaviour.
        module = _load("refresh_odds_sources")
        env = {k: v for k, v in os.environ.items() if k != "SYNDICATE_DATA_ROOT"}
        env["SYNDICATE_SOURCE_ROOT_WNBA"] = str(VENDOR_WNBA)
        with patch.dict(os.environ, env, clear=True):
            root = module._basketball_source_root("wnba", "wnba_betting_repo")
        self.assertEqual(root, VENDOR_WNBA.resolve())


class LeafScriptGuardTests(unittest.TestCase):
    def test_vendor_source_root_refused_with_data_root(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": "/srv/data"}, clear=False):
            self.assertIsNotNone(wnba._vendor_source_root_refusal(VENDOR_WNBA))
            self.assertIsNotNone(wnba._vendor_source_root_refusal(VENDOR_WNBA / "data" / ".."))

    def test_prod_source_root_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": temp_dir}, clear=False):
                self.assertIsNone(wnba._vendor_source_root_refusal(Path(temp_dir) / "wnba_source"))
                self.assertIsNone(wnba._vendor_source_root_refusal(None))

    def test_main_exits_before_any_work(self) -> None:
        # Reachability: the guard sits in main() ahead of the date loop, so a
        # refused run never reaches a fetch, a sim, or _copy_matching_files.
        argv = ["refresh_wnba_oddsapi_props.py", "--date", "2026-10-04", "--source-root", str(VENDOR_WNBA),
                "--artifact-root", "/srv/data/wnba_source", "--log-file", os.devnull]
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": "/srv/data"}, clear=False), \
                patch.object(sys, "argv", argv), \
                patch.object(wnba, "_target_refresh_dates", side_effect=AssertionError("guard did not stop the run")):
            self.assertEqual(wnba.main(), 2)


if __name__ == "__main__":
    unittest.main()
