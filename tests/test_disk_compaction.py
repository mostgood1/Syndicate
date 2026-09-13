"""Compaction of refresh-worker's disk removes only what is provably redundant.

Lane `refresh-worker-disk-inventory` (2026-09-13): the disk read 0.0 MB free.
The user approved three actions -- remove verified duplicates, gzip the
props-history CSVs, stop the history re-append. These tests pin the verify
contracts that make each safe on a disk that may hold the only copy.
"""

from __future__ import annotations

import gzip
import json
import os
import time
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from syndicate.features.shared import disk_compaction as dc

TODAY = date(2026, 9, 13)


def _write_lines(path: Path, n: int, *, age_seconds: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f'{{"row": {i}}}\n' for i in range(n)), encoding="utf-8")
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))


def _write_gz_lines(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(f'{{"row": {i}}}\n')


def _quiet(*_a, **_k):
    return None


# ---------------------------------------------------------------------------
# 1. ORPHAN TEMP FILES
# ---------------------------------------------------------------------------


def test_old_temp_files_removed_recent_kept(tmp_path):
    old = tmp_path / "soccer_source/data/book_grid/book_grid_2026-08-16.json.39.abc.pull.tmp"
    recent = tmp_path / "soccer_source/data/book_grid/book_grid_2026-09-13.json.tmp"
    real = tmp_path / "soccer_source/data/book_grid/book_grid_2026-09-12.json"
    _write_lines(old, 3, age_seconds=7200)
    _write_lines(recent, 3)
    _write_lines(real, 3, age_seconds=7200)

    result = dc.remove_orphan_temp_files(tmp_path, apply=True, printer=_quiet)

    assert result["removed"] == 1 and result["kept_recent"] == 1
    assert not old.exists() and recent.exists() and real.exists()


# ---------------------------------------------------------------------------
# 2. VERIFIED book_quotes DUPLICATES
# ---------------------------------------------------------------------------


def test_plain_shard_removed_only_when_gz_twin_has_same_lines(tmp_path):
    shard_dir = tmp_path / "mlb_source/tracking/book_quotes"
    same = shard_dir / "2026-09-01.jsonl"
    grew = shard_dir / "2026-09-02.jsonl"
    no_twin = shard_dir / "2026-09-03.jsonl"
    recent = shard_dir / "2026-09-12.jsonl"
    _write_lines(same, 50); _write_gz_lines(same.with_name(same.name + ".gz"), 50)
    _write_lines(grew, 60); _write_gz_lines(grew.with_name(grew.name + ".gz"), 50)
    _write_lines(no_twin, 10)
    _write_lines(recent, 10); _write_gz_lines(recent.with_name(recent.name + ".gz"), 10)

    result = dc.remove_verified_shard_duplicates(tmp_path, today=TODAY, apply=True, printer=_quiet)

    assert result["removed"] == 1
    assert not same.exists() and same.with_name(same.name + ".gz").exists()
    assert grew.exists(), "a plain shard with MORE lines than its .gz carries a tail -- never delete it"
    assert result["kept_mismatch"] == 1
    assert no_twin.exists() and result["no_twin"] == 1
    assert recent.exists() and result["kept_recent"] == 1


def test_stale_plain_prefix_removed_so_readers_get_the_fuller_gz(tmp_path):
    """Measured 2026-09-13: 18 MLB shards whose .gz held 1-132 MORE lines than the plain
    file, and `resolve_book_quotes_path` serves plain whenever it exists."""
    shard_dir = tmp_path / "mlb_source/tracking/book_quotes"
    stale = shard_dir / "2026-09-03.jsonl"
    diverged = shard_dir / "2026-09-04.jsonl"
    torn = shard_dir / "2026-09-05.jsonl"
    _write_lines(stale, 40); _write_gz_lines(stale.with_name(stale.name + ".gz"), 52)
    diverged.parent.mkdir(parents=True, exist_ok=True)
    diverged.write_text('{"row": 0}\n{"row": 999}\n', encoding="utf-8")
    _write_gz_lines(diverged.with_name(diverged.name + ".gz"), 30)
    # A write torn mid-line by ENOSPC is still a byte prefix of the complete copy.
    torn.write_text('{"row": 0}\n{"row": 1}\n{"ro', encoding="utf-8")
    _write_gz_lines(torn.with_name(torn.name + ".gz"), 30)

    result = dc.remove_verified_shard_duplicates(tmp_path, today=TODAY, apply=True, printer=_quiet)

    assert not stale.exists() and stale.with_name(stale.name + ".gz").exists()
    assert not torn.exists()
    assert diverged.exists(), "a plain file that differs from the .gz is not provably redundant"
    assert result["removed_stale_prefix"] == 2 and result["kept_mismatch"] == 1 and result["removed"] == 0


def test_stale_plain_prefix_dry_run_only_reports(tmp_path):
    stale = tmp_path / "mlb_source/tracking/book_quotes/2026-09-03.jsonl"
    _write_lines(stale, 40); _write_gz_lines(stale.with_name(stale.name + ".gz"), 52)
    printed: list[str] = []

    result = dc.remove_verified_shard_duplicates(tmp_path, today=TODAY, apply=False, printer=lambda line, **_k: printed.append(line))

    assert stale.exists() and result["removed_stale_prefix"] == 1
    assert any("shard_stale_prefix_would_remove" in line for line in printed)


# ---------------------------------------------------------------------------
# 3. CLOSED HISTORY CSVs, gzipped with verify
# ---------------------------------------------------------------------------


def test_closed_history_csv_gzipped_and_original_removed(tmp_path):
    closed = tmp_path / "soccer_source/tracking/odds_soccer_player_props_history_2026-09-01.csv"
    recent = tmp_path / "soccer_source/tracking/odds_soccer_player_props_history_2026-09-12.csv"
    not_history = tmp_path / "soccer_source/tracking/odds_soccer_player_props_opening_2026-09-01.csv"
    _write_lines(closed, 500)
    _write_lines(recent, 10)
    _write_lines(not_history, 10)

    result = dc.gzip_closed_history_csvs(tmp_path, today=TODAY, apply=True, printer=_quiet, free_bytes=lambda p: 10 ** 12)

    packed = closed.with_name(closed.name + ".gz")
    assert result["compressed"] == 1 and result["kept_recent"] == 1
    assert packed.exists() and not closed.exists()
    with gzip.open(packed, "rt", encoding="utf-8") as fh:
        assert sum(1 for _ in fh) == 500
    assert recent.exists() and not_history.exists()
    assert not list(tmp_path.rglob("*.gz.tmp"))


def test_low_free_space_skips_without_touching(tmp_path):
    closed = tmp_path / "mlb_source/tracking/odds_mlb_hitter_props_history_2026-08-01.csv"
    _write_lines(closed, 100)
    result = dc.gzip_closed_history_csvs(tmp_path, today=TODAY, apply=True, printer=_quiet, free_bytes=lambda p: 0)
    assert result["skipped_low_space"] == 1 and result["compressed"] == 0
    assert closed.exists() and not closed.with_name(closed.name + ".gz").exists()


def test_existing_gz_removes_original_only_when_lines_match(tmp_path):
    match = tmp_path / "mlb_source/tracking/odds_mlb_game_lines_history_2026-08-01.csv"
    mismatch = tmp_path / "mlb_source/tracking/odds_mlb_game_lines_history_2026-08-02.csv"
    _write_lines(match, 20); _write_gz_lines(match.with_name(match.name + ".gz"), 20)
    _write_lines(mismatch, 25); _write_gz_lines(mismatch.with_name(mismatch.name + ".gz"), 20)

    result = dc.gzip_closed_history_csvs(tmp_path, today=TODAY, apply=True, printer=_quiet, free_bytes=lambda p: 10 ** 12)

    assert not match.exists()
    assert mismatch.exists() and result["verify_failed"] == 1


def test_dry_run_changes_nothing(tmp_path):
    _write_lines(tmp_path / "soccer_source/tracking/odds_soccer_player_props_history_2026-09-01.csv", 30)
    shard = tmp_path / "mlb_source/tracking/book_quotes/2026-09-01.jsonl"
    _write_lines(shard, 5); _write_gz_lines(shard.with_name(shard.name + ".gz"), 5)
    _write_lines(tmp_path / "x/y.pull.tmp", 1, age_seconds=7200)
    before = sorted(str(p) for p in tmp_path.rglob("*"))

    summary = dc.run_disk_compaction(tmp_path, today=TODAY, apply=False, printer=_quiet)

    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    assert summary["apply"] is False
    assert summary["shard_duplicates"]["removed"] == 1  # reported, not done


def test_run_order_and_summary_line(tmp_path, monkeypatch):
    """ORDER IS LOAD-BEARING: the two steps that free space without writing must
    run before the step that writes compressed copies. Recorded from the calls
    themselves -- the summary JSON is key-sorted, so its order proves nothing."""
    order: list[str] = []
    monkeypatch.setattr(dc, "remove_orphan_temp_files", lambda *a, **k: order.append("temp_files") or {"removed": 0})
    monkeypatch.setattr(dc, "remove_verified_shard_duplicates", lambda *a, **k: order.append("shard_duplicates") or {"removed": 0})
    monkeypatch.setattr(dc, "gzip_closed_history_csvs", lambda *a, **k: order.append("history_csvs") or {"compressed": 0})
    printed: list[str] = []
    dc.run_disk_compaction(tmp_path, today=TODAY, apply=True, printer=lambda text, **k: printed.append(text))
    assert order == ["temp_files", "shard_duplicates", "history_csvs"]
    assert printed[0].startswith("DISK_COMPACTION_STARTED ")
    assert printed[-1].startswith("DISK_COMPACTION ")
    body = json.loads(printed[-1].split(" ", 1)[1])
    assert {"temp_files", "shard_duplicates", "history_csvs", "free_bytes_before", "seconds"} <= set(body)


# ---------------------------------------------------------------------------
# 4. WHERE AND HOW OFTEN IT RUNS
# ---------------------------------------------------------------------------


def test_default_only_on_refresh_worker(monkeypatch):
    monkeypatch.delenv("SYNDICATE_DISK_COMPACTION", raising=False)
    monkeypatch.delenv("SYNDICATE_DISK_COMPACTION_SERVICES", raising=False)
    monkeypatch.setenv("RENDER", "true")
    assert dc.disk_compaction_wanted("refresh-worker") is True
    assert dc.disk_compaction_wanted("live-odds-worker") is False
    monkeypatch.setenv("SYNDICATE_DISK_COMPACTION", "0")
    assert dc.disk_compaction_wanted("refresh-worker") is False


def test_default_never_runs_off_render(monkeypatch):
    """A dev checkout named refresh-worker (tests do this) must not compact local data/."""
    monkeypatch.delenv("SYNDICATE_DISK_COMPACTION", raising=False)
    monkeypatch.delenv("SYNDICATE_DISK_COMPACTION_SERVICES", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert dc.disk_compaction_wanted("refresh-worker") is False
    monkeypatch.setenv("SYNDICATE_DISK_COMPACTION", "1")
    assert dc.disk_compaction_wanted("refresh-worker") is True


def test_starts_once(tmp_path, monkeypatch):
    monkeypatch.setitem(dc._STATE, "started", False)
    monkeypatch.delenv("SYNDICATE_DISK_COMPACTION", raising=False)
    monkeypatch.delenv("SYNDICATE_DISK_COMPACTION_SERVICES", raising=False)
    monkeypatch.setenv("RENDER", "true")
    calls: list[str] = []
    monkeypatch.setattr(dc, "run_disk_compaction", lambda root, **k: calls.append(str(root)) or {})
    assert dc.start_disk_compaction_once(tmp_path, "refresh-worker") is True
    dc._STATE["thread"].join(timeout=5)
    assert dc.start_disk_compaction_once(tmp_path, "refresh-worker") is False
    assert calls == [str(tmp_path)]


def _maintenance(monkeypatch, *, enabled: bool) -> list[str]:
    from syndicate.features.shared import disk_inventory as inv
    from syndicate.features.shared import disk_maintenance as dm

    calls: list[str] = []
    monkeypatch.setattr(inv, "start_disk_inventory_once", lambda *a, **k: False)
    monkeypatch.setattr(dc, "start_disk_compaction_once", lambda root, slug, **k: calls.append(slug) or True)
    monkeypatch.setattr(dm, "_due", lambda: False)
    monkeypatch.setenv("RENDER_SERVICE_NAME", "refresh-worker")
    monkeypatch.delenv("SYNDICATE_REFRESH_LANE", raising=False)
    if enabled:
        monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    else:
        monkeypatch.delenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", raising=False)
    dm.run_disk_maintenance()
    return calls


def test_run_disk_maintenance_starts_compaction_when_enabled(monkeypatch):
    assert _maintenance(monkeypatch, enabled=True) == ["refresh-worker"]


def test_run_disk_maintenance_does_not_start_compaction_when_disabled(monkeypatch):
    assert _maintenance(monkeypatch, enabled=False) == []


# ---------------------------------------------------------------------------
# 5. THE HISTORY RE-APPEND IS OFF BY DEFAULT
# ---------------------------------------------------------------------------


def _persist(tmp_path: Path) -> dict:
    from syndicate.features.shared.odds_refresh_tracking import _persist_tracking_snapshot

    df = pd.DataFrame(
        [
            {"event_key": "e1", "book": "dk", "market": "h2h", "selection": "A", "line": 0.0, "price": -110, "snapshot_ts": "2026-09-13T12:00:00Z"},
            {"event_key": "e1", "book": "dk", "market": "h2h", "selection": "B", "line": 0.0, "price": -105, "snapshot_ts": "2026-09-13T12:00:00Z"},
        ]
    )
    return _persist_tracking_snapshot(
        tracking_root=tmp_path, prefix="odds_test_game_odds", scope="2026-09-13", snapshot_df=df,
        key_cols=["event_key", "book", "market", "selection"], line_col="line", price_cols=["price"],
    )


def test_history_csv_not_written_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_TRACKING_HISTORY_CSV", raising=False)
    result = _persist(tmp_path)
    assert result["ok"] is True
    assert not (tmp_path / "odds_test_game_odds_history_2026-09-13.csv").exists()
    # The files that ARE read still get written.
    assert (tmp_path / "odds_test_game_odds_opening_2026-09-13.csv").exists()
    assert (tmp_path / "odds_test_game_odds_movement_signals_2026-09-13.csv").exists()


def test_history_csv_append_restored_by_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_TRACKING_HISTORY_CSV", "1")
    _persist(tmp_path)
    _persist(tmp_path)
    history = tmp_path / "odds_test_game_odds_history_2026-09-13.csv"
    assert history.exists()
    assert len(pd.read_csv(history)) == 4  # two appends of two rows
