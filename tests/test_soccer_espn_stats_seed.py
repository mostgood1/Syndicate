"""`espn_match_stats.json` must reach refresh-worker's disk.

WHY THIS EXISTS (2026-09-07), and it was found by MEASUREMENT rather than by
reading code. The first soccer `sim_input_report` ever published from production
(19:42:35Z, host=worker, data_root=/opt/render/project/data) split cleanly:

    shots_per_match / corners_per_match / points_per_match   ok    <- matches_*.csv
    possession_share / set_piece_xg_share x2 / availability  ALARM <- espn_match_stats.json

Same `history/` directory, opposite verdicts. The cause is the seed glob:
refresh-worker runs NO general bootstrap (it is a plain script with no Flask
app, so `_bootstrap_render_data` never runs there), and its narrow seeder was
called with `glob_pattern="*.csv"` for `history/`, which silently excludes the
JSON sitting beside those CSVs. The file has been git-tracked for 9 leagues
since 2026-08-19 and had never reached that disk.

The seeder skips a directory that already has ANY file matching its pattern, so
this MUST be its own call with its own pattern -- widening the CSV call to `*`
would let the already-present `matches_*.csv` suppress the JSON forever. That is
the property the last test here pins.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_worker_module():
    path = REPO_ROOT / "scripts" / "run_refresh_worker.py"
    spec = importlib.util.spec_from_file_location("run_refresh_worker_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _committed_espn_leagues() -> list[str]:
    root = REPO_ROOT / "data" / "soccer_source"
    if not root.is_dir():
        return []
    return sorted(
        d.name for d in root.iterdir()
        if (d / "history" / "espn_match_stats.json").is_file()
    )


def test_the_checkout_actually_carries_espn_match_stats():
    """Guards the premise. If this file stops being committed, the seed below
    silently copies nothing and every ESPN-derived input goes quietly unfed --
    which is the state production was in until today."""
    leagues = _committed_espn_leagues()
    if not leagues:
        pytest.skip("data/soccer_source not present in this checkout (sparse worktree)")
    assert len(leagues) >= 5, f"expected the ESPN backfill for several leagues, got {leagues}"


def test_espn_match_stats_is_seeded_onto_the_worker_disk():
    leagues = _committed_espn_leagues()
    if not leagues:
        pytest.skip("data/soccer_source not present in this checkout (sparse worktree)")
    module = _load_worker_module()
    with TemporaryDirectory() as tmp_dir:
        fake_root = Path(tmp_dir) / "data_root"
        fake_root.mkdir(parents=True)
        with patch.object(module, "_refresh_state_store",
                          return_value={"data_root": lambda: fake_root}):
            seeded = module._bootstrap_soccer_seed_files(
                relative_subdir="history", glob_pattern="espn_match_stats.json")
        assert sorted(seeded) == leagues, "every league carrying the file should be seeded"
        for league in leagues:
            dest = fake_root / "soccer_source" / league / "history" / "espn_match_stats.json"
            assert dest.is_file(), f"{league} did not receive espn_match_stats.json"
            # Real content, not a touched empty file -- an empty JSON would make
            # `espn_stats=[]` and be indistinguishable from the bug being fixed.
            payload = json.loads(dest.read_text(encoding="utf-8"))
            assert payload, f"{league}'s seeded ESPN stats are empty"


def test_the_csv_glob_alone_does_NOT_carry_the_json():
    """The regression, stated directly.

    This is what production was doing: seed `history/` with `*.csv` and the JSON
    beside it never moves. If someone 'simplifies' the two calls back into one
    CSV call, this fails.
    """
    leagues = _committed_espn_leagues()
    if not leagues:
        pytest.skip("data/soccer_source not present in this checkout (sparse worktree)")
    module = _load_worker_module()
    with TemporaryDirectory() as tmp_dir:
        fake_root = Path(tmp_dir) / "data_root"
        fake_root.mkdir(parents=True)
        with patch.object(module, "_refresh_state_store",
                          return_value={"data_root": lambda: fake_root}):
            module._bootstrap_soccer_seed_files(relative_subdir="history", glob_pattern="*.csv")
        for league in leagues:
            history = fake_root / "soccer_source" / league / "history"
            assert list(history.glob("*.csv")), f"{league} should have received its CSVs"
            assert not (history / "espn_match_stats.json").exists(), (
                "the *.csv glob must not be assumed to carry the JSON -- it does not, "
                "which is exactly why a separate seed call exists"
            )


def test_a_separate_pattern_survives_the_csvs_already_being_present():
    """The seeder skips a directory that already has ANY file matching its
    pattern. With CSVs already seeded, a `*` glob would find them and skip --
    leaving the JSON absent forever. A distinct pattern gets its own presence
    test, and that is the whole reason for a second call."""
    leagues = _committed_espn_leagues()
    if not leagues:
        pytest.skip("data/soccer_source not present in this checkout (sparse worktree)")
    module = _load_worker_module()
    with TemporaryDirectory() as tmp_dir:
        fake_root = Path(tmp_dir) / "data_root"
        fake_root.mkdir(parents=True)
        with patch.object(module, "_refresh_state_store",
                          return_value={"data_root": lambda: fake_root}):
            module._bootstrap_soccer_seed_files(relative_subdir="history", glob_pattern="*.csv")
            seeded = module._bootstrap_soccer_seed_files(
                relative_subdir="history", glob_pattern="espn_match_stats.json")
        assert sorted(seeded) == leagues, (
            "the JSON seed must still fire after the CSV seed has populated the "
            "same directory"
        )


def test_the_history_bootstrap_ACTUALLY_CALLS_the_json_seed():
    """OFF != ON for the fix itself.

    Every test above exercises `_bootstrap_soccer_seed_files` directly, so they
    pass with or without the call-site change and guard nothing about it. This
    one pins the reachability: `_bootstrap_soccer_history_seed_files` -- the
    function the worker actually runs at boot -- must request the JSON pattern,
    not only `*.csv`. Remove the new call and this fails; that is the point.
    """
    module = _load_worker_module()
    seen: list[str] = []

    def _spy(*, relative_subdir, glob_pattern):
        seen.append(f"{relative_subdir}:{glob_pattern}")
        return []

    with patch.object(module, "_bootstrap_soccer_seed_files", _spy):
        module._bootstrap_soccer_history_seed_files()

    assert "history:*.csv" in seen, f"the CSV seed disappeared: {seen}"
    assert "history:espn_match_stats.json" in seen, (
        "the worker's history bootstrap does not request espn_match_stats.json, so "
        "possession_share / set_piece_xg_share / availability_index go unfed in "
        "production exactly as they did before 2026-09-07. Seen: " + repr(seen)
    )
