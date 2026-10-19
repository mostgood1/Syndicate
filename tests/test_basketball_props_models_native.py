"""The NBA/WNBA props models are Syndicate's: the props path reads its own committed copies, not vendor/.

Lane basketball-props-models-native (2026-10-12). The copies under
syndicate/features/basketball_engine/props_models/<league>/ are byte-identical to the vendored
vendor/<pkg>_repo/models props files they replaced.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from syndicate.features.shared import basketball_props_onnx as onnx
from syndicate.features.shared import basketball_props_predictions as preds

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "syndicate" / "features" / "basketball_engine" / "props_models"
LEAGUES = {"nba": "nba_betting", "wnba": "wnba_betting"}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# [nba] retired 2026-10-19 (lane nba-vendor-deletion-prep): the vendored NBA models go with their tree; see the invariant below.
@pytest.mark.parametrize("league", ["wnba"])
def test_copies_are_byte_identical_to_the_vendored_models_they_replaced(league):
    vendor = ROOT / "vendor" / f"{LEAGUES[league]}_repo" / "models"
    if not vendor.is_dir():
        pytest.skip("vendored models not present in this checkout")
    native = sorted((NATIVE / league).iterdir())
    assert len(native) >= 20, native
    for p in native:
        assert _sha(p) == _sha(vendor / p.name), p.name


@pytest.mark.parametrize("league", sorted(LEAGUES))
def test_resolver_falls_back_to_syndicate_copies_not_vendor(league, tmp_path):
    source_root = tmp_path / f"{league}_source"
    source_root.mkdir()
    resolved = preds._models_dir_for_source_root(source_root)
    assert resolved == NATIVE / league
    assert "vendor" not in resolved.parts


def test_a_data_root_models_dir_still_wins(tmp_path):
    """The vendored playoff_transition retrains into its config root (the data root when run from the bootstrapped src)."""
    source_root = tmp_path / "wnba_source"
    (source_root / "models").mkdir(parents=True)
    (source_root / "models" / "props_feature_columns.joblib").write_bytes(b"x")
    assert preds._models_dir_for_source_root(source_root) == source_root / "models"


@pytest.mark.parametrize("league", sorted(LEAGUES))
def test_the_copies_hold_every_file_the_predictor_loads(league):
    d = NATIVE / league
    for name in ["props_feature_columns.joblib", "props_models.joblib", "pure_linear_props_models.npz"]:
        assert (d / name).is_file(), name
    for target in onnx.PRIMARY_ONNX_TARGETS + onnx.EXTRA_TARGETS:
        assert (d / f"{target}_ridge.onnx").is_file(), target
    assert onnx._load_feature_columns(d), "feature columns did not load"


def test_nba_models_are_committed_and_non_empty():
    """Post-vendor invariant: the NBA props models production reads are git-tracked here and not empty."""
    import subprocess

    tracked = [f for f in subprocess.run(["git", "ls-files", str((NATIVE / "nba").relative_to(ROOT))], cwd=ROOT,
                                         capture_output=True, text=True).stdout.split() if f]
    assert len(tracked) >= 20, tracked
    for f in tracked:
        assert (ROOT / f).stat().st_size > 0, f
