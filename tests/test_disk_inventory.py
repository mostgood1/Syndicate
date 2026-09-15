"""The disk inventory measures a worker disk without changing it.

Lane `refresh-worker-disk-inventory` (2026-09-13): refresh-worker's 50 GB disk
filled, and nothing on the platform could say what was on it. These tests pin
the properties that make the instrument safe to ship to a full production disk:
it aggregates correctly, it modifies nothing, it stops at its bounds, it runs
only where asked, once, and it is actually reached from `run_disk_maintenance`.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import disk_inventory as inv

# The fixture tree's "today": 2026-09-13 12:00Z, the date `_tree` names as today.
FIXTURE_NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc).timestamp()


def _write(path: Path, size: int, *, age_seconds: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))


def _tree(root: Path) -> None:
    _write(root / "soccer_source/tracking/book_quotes/2026-09-01.jsonl", 5000, age_seconds=10 * 86400)
    _write(root / "soccer_source/tracking/book_quotes/2026-09-02.jsonl", 4000, age_seconds=9 * 86400)
    _write(root / "soccer_source/tracking/book_quotes/2026-09-03.jsonl.gz", 300, age_seconds=8 * 86400)
    _write(root / "mlb_source/tracking/odds_history/2026-09-01.json", 3000, age_seconds=10 * 86400)
    _write(root / "reports/intelligence/clv_openings/2026-09-13.jsonl", 1000)  # today: not compactable
    _write(root / "live/mlb_live_lens.json", 200)  # undated
    _write(root / "soccer_source/data/book_grid/book_grid_2026-09-12.json.123.abcdef0123.pull.tmp", 700, age_seconds=3600)
    _write(root / "soccer_source/data/book_grid/fresh.tmp", 50)  # too new to be an orphan


def _snapshot(root: Path) -> dict[str, tuple[int, float]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime) for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# 1. AGGREGATES
# ---------------------------------------------------------------------------


def test_totals_and_directory_aggregation(tmp_path):
    _tree(tmp_path)
    report = inv.build_disk_inventory(tmp_path, max_depth=3, now=time.time())

    assert report["files"] == 8
    assert report["bytes"] == 5000 + 4000 + 300 + 3000 + 1000 + 200 + 700 + 50
    assert report["truncated"] is False
    depth1 = {row["path"]: row for row in report["top_dirs"]["1"]}
    assert depth1["soccer_source"]["bytes"] == 5000 + 4000 + 300 + 700 + 50
    depth3 = {row["path"]: row for row in report["top_dirs"]["3"]}
    assert depth3["soccer_source/tracking/book_quotes"]["files"] == 3
    assert report["largest_files"][0] == {"path": "soccer_source/tracking/book_quotes/2026-09-01.jsonl", "bytes": 5000}


def test_extensions_group_compressed_suffixes(tmp_path):
    _tree(tmp_path)
    report = inv.build_disk_inventory(tmp_path)
    ext = {row["path"]: row for row in report["by_extension"]}
    assert ext[".jsonl"]["files"] == 3
    assert ext[".jsonl.gz"]["files"] == 1


def test_compactable_families_are_dated_uncompressed_and_old(tmp_path):
    # Age comes from the date in the NAME, so `now` must be pinned to the fixture's "today".
    # Unpinned, the 2026-09-13 file turned compactable on 2026-09-15 and this test failed.
    _tree(tmp_path)
    report = inv.build_disk_inventory(tmp_path, compactable_min_age_days=2.0, now=FIXTURE_NOW)
    families = {row["path"]: row for row in report["compactable_text_families"]}
    assert families["soccer_source/tracking/book_quotes/<date>.jsonl"] == {
        "path": "soccer_source/tracking/book_quotes/<date>.jsonl", "bytes": 9000, "files": 2}
    assert "mlb_source/tracking/odds_history/<date>.json" in families
    # Today's file is not a candidate, a .gz is already compressed, undated files are not families.
    assert not any("clv_openings" in key for key in families)
    assert not any(key.endswith(".gz") for key in families)


def test_compactable_age_is_the_name_date_against_now(tmp_path):
    # The exclusion above is not vacuous: two days later the same file is a family.
    _tree(tmp_path)
    later = inv.build_disk_inventory(tmp_path, compactable_min_age_days=2.0, now=FIXTURE_NOW + 2 * 86400)
    families = {row["path"] for row in later["compactable_text_families"]}
    assert "reports/intelligence/clv_openings/<date>.jsonl" in families


def test_temp_orphans_need_age(tmp_path):
    _tree(tmp_path)
    report = inv.build_disk_inventory(tmp_path)
    assert report["temp_orphans"]["count"] == 1
    assert report["temp_orphans"]["bytes"] == 700


def test_filesystem_totals_present_or_explained(tmp_path):
    report = inv.build_disk_inventory(tmp_path)
    fs = report["filesystem"]
    assert ("total_bytes" in fs) or ("unavailable" in fs)


# ---------------------------------------------------------------------------
# 2. SAFETY
# ---------------------------------------------------------------------------


def test_nothing_on_disk_changes(tmp_path):
    _tree(tmp_path)
    before = _snapshot(tmp_path)
    report = inv.build_disk_inventory(tmp_path)
    inv.emit_disk_inventory(report, printer=lambda *a, **k: None)
    assert _snapshot(tmp_path) == before


def test_entry_bound_truncates(tmp_path):
    for i in range(50):
        _write(tmp_path / f"d{i % 5}/f{i}.json", 10)
    report = inv.build_disk_inventory(tmp_path, max_entries=10, yield_every=5)
    assert report["truncated"] is True
    assert report["files"] < 50


def test_emitted_lines_are_bounded_and_parse(tmp_path):
    for i in range(400):
        _write(tmp_path / f"sport_{i}_source/tracking/book_quotes/2026-08-{(i % 28) + 1:02d}.jsonl", 10, age_seconds=30 * 86400)
    report = inv.build_disk_inventory(tmp_path, top_n=400)
    printed: list[str] = []
    count = inv.emit_disk_inventory(report, printer=lambda text, **k: printed.append(text))
    assert count == len(printed)
    assert printed[0].startswith("DISK_INVENTORY_SUMMARY ")
    assert printed[-1] == "DISK_INVENTORY_END"
    for line in printed[:-1]:
        tag, _, body = line.partition(" ")
        assert tag.startswith("DISK_INVENTORY_")
        assert len(line) <= inv._MAX_LINE_CHARS + 200
        json.loads(body)


# ---------------------------------------------------------------------------
# 3. WHERE AND HOW OFTEN IT RUNS
# ---------------------------------------------------------------------------


def test_default_runs_only_on_refresh_worker(monkeypatch):
    monkeypatch.delenv("SYNDICATE_DISK_INVENTORY", raising=False)
    monkeypatch.delenv("SYNDICATE_DISK_INVENTORY_SERVICES", raising=False)
    assert inv.disk_inventory_wanted("refresh-worker") is True
    assert inv.disk_inventory_wanted("live-odds-worker") is False
    assert inv.disk_inventory_wanted("web") is False


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("SYNDICATE_DISK_INVENTORY", "0")
    assert inv.disk_inventory_wanted("refresh-worker") is False
    monkeypatch.setenv("SYNDICATE_DISK_INVENTORY", "1")
    assert inv.disk_inventory_wanted("live-odds-worker") is True
    monkeypatch.delenv("SYNDICATE_DISK_INVENTORY")
    monkeypatch.setenv("SYNDICATE_DISK_INVENTORY_SERVICES", "live-odds-worker, web")
    assert inv.disk_inventory_wanted("web") is True
    assert inv.disk_inventory_wanted("refresh-worker") is False


def test_starts_once_per_process(tmp_path, monkeypatch):
    monkeypatch.setitem(inv._STATE, "started", False)
    monkeypatch.setitem(inv._STATE, "thread", None)
    monkeypatch.delenv("SYNDICATE_DISK_INVENTORY", raising=False)
    monkeypatch.delenv("SYNDICATE_DISK_INVENTORY_SERVICES", raising=False)
    calls: list[str] = []
    monkeypatch.setattr(inv, "build_disk_inventory", lambda root, **k: calls.append(str(root)) or {"top_dirs": {}})
    monkeypatch.setattr(inv, "emit_disk_inventory", lambda report, **k: 1)

    assert inv.start_disk_inventory_once(tmp_path, "refresh-worker") is True
    inv._STATE["thread"].join(timeout=5)
    assert inv.start_disk_inventory_once(tmp_path, "refresh-worker") is False
    assert calls == [str(tmp_path)]


def test_not_started_where_not_wanted(tmp_path, monkeypatch):
    monkeypatch.setitem(inv._STATE, "started", False)
    monkeypatch.delenv("SYNDICATE_DISK_INVENTORY", raising=False)
    monkeypatch.delenv("SYNDICATE_DISK_INVENTORY_SERVICES", raising=False)
    assert inv.start_disk_inventory_once(tmp_path, "live-odds-worker") is False
    assert inv._STATE["started"] is False


# ---------------------------------------------------------------------------
# 4. REACHABILITY FROM run_disk_maintenance (off != on)
# ---------------------------------------------------------------------------


def _run_maintenance(monkeypatch, *, enabled: bool) -> list[tuple[str, str]]:
    from syndicate.features.shared import disk_maintenance as dm

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(inv, "start_disk_inventory_once", lambda root, slug, **k: calls.append((str(root), slug)) or True)
    monkeypatch.setattr(dm, "_due", lambda: False)
    monkeypatch.setenv("RENDER_SERVICE_NAME", "refresh-worker")
    monkeypatch.delenv("SYNDICATE_REFRESH_LANE", raising=False)
    if enabled:
        monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    else:
        monkeypatch.delenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", raising=False)
    dm.run_disk_maintenance()
    return calls


def test_run_disk_maintenance_starts_the_inventory_when_enabled(monkeypatch):
    calls = _run_maintenance(monkeypatch, enabled=True)
    assert len(calls) == 1
    assert calls[0][1] == "refresh-worker"


def test_run_disk_maintenance_does_not_start_it_when_disabled(monkeypatch):
    assert _run_maintenance(monkeypatch, enabled=False) == []
