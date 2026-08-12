"""`#396` -- retention for a disk that had none and fills in ~43 days.

Measured 2026-08-12: ~700 MB/day on a 50 GB volume at ~40%. The only `unlink()`
calls anywhere in the publish path are temp-file cleanup during atomic writes.

The tests that matter here are the REFUSALS, not the deletions. Render is the
source of truth and the git tree is a lossy mirror, so a file removed here may
be the only copy in existence.
"""

from __future__ import annotations

from datetime import date

import pytest

from syndicate.features.shared import artifact_retention as ar

TODAY = date(2026, 8, 12)


def _touch(root, rel, size=1024):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x" * size, encoding="utf-8")
    return p


def test_it_defaults_to_dry_run_and_deletes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", raising=False)
    old = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2020-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.dry_run is True
    assert out.matched == 1 and out.deleted == 0
    assert out.bytes_reclaimable > 0 and out.bytes_deleted == 0
    assert old.exists(), "dry run deleted a file"


def test_it_deletes_only_when_explicitly_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    old = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2020-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.deleted == 1 and out.bytes_deleted > 0
    assert not old.exists()


def test_an_unmatched_path_is_kept_even_when_ancient(tmp_path, monkeypatch):
    """An unknown path is not evidence that a file is disposable."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    keep = _touch(tmp_path, "something_new/invented_2019-01-01.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.matched == 0 and keep.exists()


def test_an_undated_file_is_never_aged_out(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    keep = _touch(tmp_path, "mlb_source/data/book_grid/current_week.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.matched == 0 and keep.exists()


def test_captures_get_a_far_longer_window_than_derived(tmp_path, monkeypatch):
    """A book_grid is rebuildable from book_quotes; a quote is a fact. A single
    window would either shred captures or never reclaim the derived bulk."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    derived = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2026-08-01.json")
    source = _touch(tmp_path, "mlb_source/tracking/book_quotes/2026-08-01.jsonl")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert not derived.exists(), "an 11-day-old derived grid should be reclaimed"
    assert source.exists(), "an 11-day-old CAPTURE must be kept"
    assert out.by_tier == {"derived": 1}


def test_todays_artifacts_are_never_touched(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    live = _touch(tmp_path, "mlb_source/data/book_grid/book_grid_2026-08-12.json")
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert out.matched == 0 and live.exists()


@pytest.mark.parametrize("junk", ["", "nope", "0", "-5"])
def test_a_junk_window_falls_back_to_the_default_not_to_zero(tmp_path, monkeypatch, junk):
    """A window of 0 would delete every dated artifact. An unparseable value
    must never map onto the most destructive branch."""
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_RETENTION_SOURCE_DAYS", junk)
    keep = _touch(tmp_path, "mlb_source/tracking/book_quotes/2026-08-10.jsonl")
    ar.sweep_expired_artifacts(today=TODAY, root=tmp_path)
    assert keep.exists(), f"junk value {junk!r} destroyed a recent capture"


def test_a_missing_root_does_not_raise(tmp_path):
    out = ar.sweep_expired_artifacts(today=TODAY, root=tmp_path / "nope")
    assert out.scanned == 0 and out.deleted == 0
