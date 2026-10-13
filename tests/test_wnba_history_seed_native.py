"""WNBA games-history seed and predictions copy are off vendor (lane nba-source-cli-native, 2026-10-13).

  * the seed is Syndicate's committed copy, byte-identical (LF) to the vendored checkout's while that exists;
  * behaviour is unchanged: a cold start (no history) is seeded and derived features are invalidated; a history at
    least as fresh as the seed is left alone;
  * nothing in the NBA refresh resolves a path under vendor/ for the seed or the predictions copy any more.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR_SEED = "vendor/wnba_betting_repo/data/raw/games_nba_api.csv"
SEED = "syndicate/features/wnba/seed_data/games_nba_api.csv"


def _mod():
    spec = importlib.util.spec_from_file_location("refresh_wnba_probe_seed", ROOT / "scripts" / "refresh_wnba_oddsapi_props.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _blob(path: str) -> bytes | None:
    r = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, cwd=ROOT)
    return r.stdout if r.returncode == 0 else None


def test_seed_is_the_syndicate_copy_and_matches_the_vendored_one():
    mod = _mod()
    assert mod.WNBA_GAMES_HISTORY_SEED == ROOT / SEED
    assert "vendor" not in mod.WNBA_GAMES_HISTORY_SEED.relative_to(ROOT).parts
    assert mod.WNBA_GAMES_HISTORY_SEED.is_file()
    vendored, ours = _blob(VENDOR_SEED), _blob(SEED)
    if vendored is None or ours is None:
        pytest.skip("not committed yet / vendor tree removed")
    assert ours == vendored


def test_cold_start_is_seeded_and_fresh_history_is_left_alone(tmp_path):
    mod = _mod()
    raw = tmp_path / "raw" / "games_nba_api.csv"
    feats = (tmp_path / "processed" / "features.csv",)
    feats[0].parent.mkdir(parents=True)
    feats[0].write_text("stale\n", encoding="utf-8")
    log = tmp_path / "run.log"
    assert mod._seed_games_history_from_checkout_if_fresher(raw_path=raw, package_name="wnba_betting", date_str="2026-10-20",
                                                            feature_candidates=feats, log_file=log) is True
    assert raw.read_bytes() == mod.WNBA_GAMES_HISTORY_SEED.read_bytes()
    assert not feats[0].exists()  # derived features invalidated
    # now as fresh as the seed: nothing to do
    assert mod._seed_games_history_from_checkout_if_fresher(raw_path=raw, package_name="wnba_betting", date_str="2026-10-20",
                                                            feature_candidates=feats, log_file=log) is False


def test_no_vendor_path_is_resolved_for_seed_or_predictions():
    src = (ROOT / "scripts" / "refresh_wnba_oddsapi_props.py").read_text(encoding="utf-8")
    assert "_vendor_code_root" not in src
    assert '"data" / "processed" / f"predictions_' not in src.split("WNBA_GAMES_HISTORY_SEED =")[1]
