"""`#383` -- the reuse guard checked that files EXIST, never when they were written.

MEASURED 2026-08-12, end of a four-step chain:

    Layer 1   WNBA served 848 rows priced off quotes 10.1h old, board healthy
    `#378`    sweep ran and wrote nothing:
              `sport=wnba wrote=False exists=True sidecar_age_s=36537`
              against `sport=nfl wrote=True sidecar_age_s=169` from the SAME loop
    `#382`    mlb and wnba carried identical marker ages -- one shared launch,
              one sport wrote
    decision  /api/ops/wnba/refresh-decision -> "reused_artifact_bundle"

THE FIXPOINT. `_existing_artifact_bundle_state` validated that every required
file exists and has content. `input_hash` is computed from the INPUTS, so if
those never change the hash never changes and the bundle stays reusable
forever: reuse the bundle -> skip the fetch -> inputs do not change -> reuse the
bundle. Nothing in the key encoded quote freshness, so a 10-hour-old capture
satisfied a guard designed to prevent redundant work.

This is `#344` recurring verbatim -- "the reuse guards above returned a cached
state and the fetch was skipped silently" -- and `#344` is also why it was
diagnosable at all: it persisted the decision to the keyvalue store and exposed
it at an ops endpoint, knowing this script's stdout lands on a disk web cannot
read. That endpoint answered in one call what would otherwise have been another
deploy and another two hours.

BOUND = THE SWEEP INTERVAL, tied by configuration rather than import: the same
env vars `_pregame_sweep_interval_seconds` reads, same 2h fallback, so both move
from one knob without coupling a standalone script to the loop module. That
interval is the cadence that CALLS this, so a bundle written before a due sweep
is by definition not what the sweep was for. Tighter re-fetches inside one
cadence window and spends credits the `#344` family exists to protect; looser
reopens this bug.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "wnba_reuse_under_test", _REPO / "scripts" / "refresh_wnba_oddsapi_props.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["wnba_reuse_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _bundle(tmp_path: Path, *, age_seconds: float) -> Path:
    """A complete, content-bearing bundle whose snapshot has a chosen age."""
    root = tmp_path / "artifacts"
    raw = root / "data" / "raw"
    proc = root / "data" / "processed"
    raw.mkdir(parents=True, exist_ok=True)
    proc.mkdir(parents=True, exist_ok=True)
    date = "2026-08-12"
    body = "a,b\n1,2\n"
    files = [
        raw / f"odds_wnba_player_props_{date}.csv",
        proc / f"predictions_{date}.csv",
        proc / f"props_predictions_{date}.csv",
        proc / f"props_edges_{date}.csv",
        proc / f"props_recommendations_{date}.csv",
        proc / f"game_cards_{date}.csv",
    ]
    for f in files:
        f.write_text(body, encoding="utf-8")
    (proc / f"recommendations_slate_{date}.json").write_text('{"games":[{"x":1}]}', encoding="utf-8")
    stamp = time.time() - age_seconds
    snapshot = raw / f"odds_wnba_player_props_{date}.csv"
    os.utime(snapshot, (stamp, stamp))
    return root


def _call(mod, root: Path):
    return mod._existing_artifact_bundle_state(
        artifact_root=root, date_str="2026-08-12", do_edges=True, do_export=True
    )


def test_a_ten_hour_old_bundle_is_declined(mod, tmp_path, capsys):
    # The measured case: sidecar_age_s=36537 (10.1h) against a 2h interval.
    root = _bundle(tmp_path, age_seconds=36537)
    assert _call(mod, root) is None, "a 10-hour-old bundle satisfied the guard again"
    out = capsys.readouterr().out
    assert "BUNDLE_REUSE_DECLINED" in out, "a decline must say so -- silence is what caused this"
    assert "snapshot_age_s=36" in out


def test_a_fresh_bundle_is_still_reused(mod, tmp_path):
    # The guard's whole purpose. Breaking reuse would re-fetch every tick and
    # spend the OddsAPI budget the #344 family exists to protect.
    root = _bundle(tmp_path, age_seconds=300)
    state = _call(mod, root)
    assert state is not None
    assert state.get("reused_existing_artifact_bundle") is True


def test_the_boundary_sits_at_the_sweep_interval(mod, tmp_path):
    # Just inside 2h reuses; just outside declines. The bound IS the behaviour.
    assert _call(mod, _bundle(tmp_path / "in", age_seconds=2 * 3600 - 120)) is not None
    assert _call(mod, _bundle(tmp_path / "out", age_seconds=2 * 3600 + 120)) is None


def test_the_bound_follows_the_sweep_interval_env(mod, tmp_path, monkeypatch):
    # Tied by configuration: the same knob that widens the sweep widens reuse,
    # so the two cannot drift into disagreeing about what "due" means.
    monkeypatch.setenv("SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_WNBA", "43200")  # 12h
    assert mod._reuse_max_age_seconds("wnba") == 43200.0
    assert _call(mod, _bundle(tmp_path / "wide", age_seconds=36537)) is not None, (
        "a widened sweep interval must widen reuse to match"
    )


def test_the_default_matches_the_loop_fallback(mod, monkeypatch):
    for name in (
        "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_WNBA",
        "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS",
        "SYNDICATE_WNBA_REUSE_MAX_AGE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    # _PREGAME_SWEEP_INTERVAL_FALLBACK in live_refresh_loop is 2 * 3600.
    assert mod._reuse_max_age_seconds("wnba") == 2 * 3600.0


def test_an_unreadable_mtime_does_not_block_reuse(mod, tmp_path):
    # Unknown age must not become a hard decline: that would turn an IO hiccup
    # into a full re-fetch storm against the budget.
    root = _bundle(tmp_path, age_seconds=300)
    missing = tmp_path / "nope" / "gone.csv"
    assert mod._bundle_age_seconds(missing) is None
    assert _call(mod, root) is not None


def test_an_incomplete_bundle_is_still_rejected_first(mod, tmp_path):
    # The pre-existing content checks must keep running; freshness is additive.
    root = _bundle(tmp_path, age_seconds=60)
    (root / "data" / "raw" / "odds_wnba_player_props_2026-08-12.csv").write_text("", encoding="utf-8")
    assert _call(mod, root) is None
