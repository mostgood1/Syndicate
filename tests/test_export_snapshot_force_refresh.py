"""`--force-refresh` must actually rebuild the props snapshot exports.

WHAT THIS PINS, AND WHY IT IS THE BUILDER CALL AND NOT THE FILE CONTENT.

All three props-snapshot exporters copy any prior `<name>_<date>.json` into the
processed root and, if one is found, return it WITHOUT calling their builder.
Two of WNBA's three took a `force_refresh` bypass; `_export_cards_props_snapshot`
took none, and NBA's whole trio took none. So a forced refresh regenerated
`recommendations_slate` and `top_by_game` while `cards_props_snapshot` kept
re-serving the first file written for that date -- silently, since the exporter
still returns a valid path.

Found 2026-08-16 while explaining a `rows=0` reading on the `win_prob` null
counter: the 04:24 run fetched (`decision=will_fetch`) and still computed no
`win_prob`, because pid 2466 emitted only its exit record and no per-builder
record -- the builders were never CALLED. That is why these tests assert on the
call, not on bytes: "the file changed" can be satisfied by a copy, and "the file
did not change" is exactly what a correct no-op reuse looks like too. The call is
the only signal that separates the two.
"""

from __future__ import annotations

import os
import time

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load(script_name: str):
    spec = importlib.util.spec_from_file_location(f"_producer_{script_name}", REPO_ROOT / "scripts" / f"{script_name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# (exporter, builder it must call, file it short-circuits on)
TRIO = [
    ("_export_cards_props_snapshot", "_build_local_cards_props_snapshot_artifact", "cards_props_snapshot_{date}.json"),
    ("_export_recommendations_slate_snapshot", "_build_local_recommendations_slate_artifact", "recommendations_slate_{date}.json"),
    ("_export_top_by_game_snapshot", "_build_local_top_by_game_snapshot", "props_recommendations_top_by_game_{date}.json"),
]
PRODUCERS = ["refresh_wnba_oddsapi_props", "refresh_nba_oddsapi_props"]
DATE = "2026-08-16"


@pytest.fixture
def roots(tmp_path):
    source_root = tmp_path / "source"
    processed_root = tmp_path / "processed"
    (source_root / "data" / "processed").mkdir(parents=True)
    processed_root.mkdir(parents=True)
    return source_root, processed_root


def _seed_existing(source_root: Path, processed_root: Path, file_name: str) -> None:
    # A prior artifact for this date, in both roots -- whichever the exporter's
    # copy helper finds, `existing` is truthy and the short-circuit is armed.
    for root in ((source_root / "data" / "processed"), processed_root):
        (root / file_name).write_text('{"stale": true}', encoding="utf-8")


def _patch_builder(monkeypatch, module, builder_name: str, calls: list[str]) -> None:
    def _fake(*, processed_root: Path, date_str: str):
        calls.append(date_str)
        out = Path(processed_root) / "rebuilt.json"
        out.write_text('{"rebuilt": true}', encoding="utf-8")
        return 1, out

    monkeypatch.setattr(module, builder_name, _fake)


@pytest.mark.parametrize("script_name", PRODUCERS)
@pytest.mark.parametrize(("exporter", "builder", "file_tpl"), TRIO)
def test_force_refresh_rebuilds_even_when_the_snapshot_exists(script_name, exporter, builder, file_tpl, roots, monkeypatch):
    source_root, processed_root = roots
    module = _load(script_name)
    _seed_existing(source_root, processed_root, file_tpl.format(date=DATE))
    calls: list[str] = []
    _patch_builder(monkeypatch, module, builder, calls)

    getattr(module, exporter)(
        source_root=source_root,
        date_str=DATE,
        processed_root=processed_root,
        force_refresh=True,
    )

    assert calls == [DATE], f"{script_name}.{exporter} did not rebuild under force_refresh"


@pytest.mark.parametrize("script_name", PRODUCERS)
@pytest.mark.parametrize(("exporter", "builder", "file_tpl"), TRIO)
def test_without_force_refresh_the_existing_snapshot_is_still_reused(script_name, exporter, builder, file_tpl, roots, monkeypatch):
    # The other half of the fix: reuse is the cheap default and must SURVIVE.
    # `live_refresh_loop` runs these exporters constantly; turning the gate off
    # unconditionally would rebuild every artifact on every tick.
    source_root, processed_root = roots
    module = _load(script_name)
    _seed_existing(source_root, processed_root, file_tpl.format(date=DATE))
    calls: list[str] = []
    _patch_builder(monkeypatch, module, builder, calls)

    getattr(module, exporter)(
        source_root=source_root,
        date_str=DATE,
        processed_root=processed_root,
    )

    assert calls == [], f"{script_name}.{exporter} rebuilt when it should have reused"


@pytest.mark.parametrize("script_name", PRODUCERS)
@pytest.mark.parametrize(("exporter", "builder", "file_tpl"), TRIO)
def test_missing_snapshot_always_builds(script_name, exporter, builder, file_tpl, roots, monkeypatch):
    source_root, processed_root = roots
    module = _load(script_name)
    calls: list[str] = []
    _patch_builder(monkeypatch, module, builder, calls)

    getattr(module, exporter)(source_root=source_root, date_str=DATE, processed_root=processed_root)

    assert calls == [DATE], f"{script_name}.{exporter} skipped the build with no existing file"


@pytest.mark.parametrize("script_name", PRODUCERS)
def test_the_trio_is_symmetric(script_name):
    # The defect was an ASYMMETRY -- two siblings had the escape and one did not,
    # which is invisible at any single call site. Asserted as a property of the
    # trio so a future exporter added without the parameter fails here.
    import inspect

    module = _load(script_name)
    missing = [
        name for name, _builder, _tpl in TRIO
        if "force_refresh" not in inspect.signature(getattr(module, name)).parameters
    ]
    assert missing == [], f"{script_name}: exporters without a force_refresh escape: {missing}"


# --- freshness gate (2026-08-16, the stale-board fix) -------------------------
#
# force_refresh alone did not fix the board: nothing in the routine cycle passes
# it, so the first build of a date won permanently and the served picks drifted
# up to 2.0 points from the live market. These pin the gate that runs on EVERY
# cycle: rebuild when an input is newer than the snapshot.


def _touch(path: Path, when: float) -> None:
    path.write_text('{"x": 1}', encoding="utf-8")
    os.utime(path, (when, when))


@pytest.mark.parametrize("script_name", PRODUCERS)
@pytest.mark.parametrize(("exporter", "builder", "file_tpl"), TRIO)
def test_rebuilds_when_the_source_csv_is_newer(script_name, exporter, builder, file_tpl, roots, monkeypatch):
    source_root, processed_root = roots
    module = _load(script_name)
    snapshot = file_tpl.format(date=DATE)
    _seed_existing(source_root, processed_root, snapshot)
    # snapshot built an hour ago; its input CSV rewritten a minute ago
    now = time.time()
    for root in ((source_root / "data" / "processed"), processed_root):
        _touch(root / snapshot, now - 3600)
    for csv_name in (f"props_recommendations_{DATE}.csv", f"recommendations_{DATE}.csv"):
        _touch(processed_root / csv_name, now - 60)
    calls: list[str] = []
    _patch_builder(monkeypatch, module, builder, calls)

    getattr(module, exporter)(source_root=source_root, date_str=DATE, processed_root=processed_root)

    assert calls == [DATE], f"{script_name}.{exporter} re-served a snapshot older than its own input"


@pytest.mark.parametrize("script_name", PRODUCERS)
@pytest.mark.parametrize(("exporter", "builder", "file_tpl"), TRIO)
def test_reuses_when_the_snapshot_is_newer_than_its_inputs(script_name, exporter, builder, file_tpl, roots, monkeypatch):
    # The other half: reuse must survive, or every cycle rebuilds everything.
    source_root, processed_root = roots
    module = _load(script_name)
    snapshot = file_tpl.format(date=DATE)
    _seed_existing(source_root, processed_root, snapshot)
    now = time.time()
    for csv_name in (f"props_recommendations_{DATE}.csv", f"recommendations_{DATE}.csv"):
        _touch(processed_root / csv_name, now - 3600)
    for root in ((source_root / "data" / "processed"), processed_root):
        _touch(root / snapshot, now - 60)
    calls: list[str] = []
    _patch_builder(monkeypatch, module, builder, calls)

    getattr(module, exporter)(source_root=source_root, date_str=DATE, processed_root=processed_root)

    assert calls == [], f"{script_name}.{exporter} rebuilt though its snapshot was newer than every input"


@pytest.mark.parametrize("script_name", PRODUCERS)
def test_unreadable_mtime_rebuilds_rather_than_reusing(script_name):
    # "Unknown" must not land on the permissive branch -- that is what made the
    # staleness silent in the first place.
    module = _load(script_name)
    assert module._snapshot_inputs_are_newer(None, []) is True
    assert module._snapshot_inputs_are_newer("/nonexistent/snapshot.json", []) is True
