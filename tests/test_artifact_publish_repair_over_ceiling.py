"""A file over `_PUBLISH_MAX_BYTES` had no retry path, which is the inverse of
what either half of the code says on its own.

`publish_hot_artifact` records its checksum ONLY after the upload is
acknowledged, and states the reason plainly:

    "Recorded only after the upload is acknowledged -- a failed publish must be
     retried next sweep, not suppressed by its own attempt."

That is the entire recovery design. But `_publish_skip_reason` refuses anything
over `_PUBLISH_MAX_BYTES` BEFORE `publish_hot_artifact` is reached, so for a
file above the ceiling **the retry it names does not exist**. The biggest
artifacts — the ones a stale copy hurts most — were the only ones with no way
back.

MEASURED 2026-08-22: `soccer_source/data/book_grid/book_grid_2026-08-22.json`
at 14.3MB against a 12MB ceiling, in `SWEEP_SKIPPED_DETAIL` every cycle. Its
direct stream publishes were succeeding that day, so nothing was visibly broken
— which is exactly why this survived: the hole only opens on a failure, and the
failure is rare.

WHAT THIS DELIBERATELY DOES NOT DO: raise the ceiling. Its own comment forbids
that without a measured reason, and the reason still holds — the sweep would
ship 51MB `odds_history` shards every cycle. The exemption is scoped to paths a
direct publish has already tried and failed, and it ends the moment one
succeeds.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import syndicate.features.shared.artifact_publisher as publisher


def _big(tmp_path: Path, name: str = "book_grid_2026-08-22.json") -> Path:
    path = tmp_path / name
    path.write_bytes(b"x" * (publisher._PUBLISH_MAX_BYTES + 1))
    return path


def _small(tmp_path: Path, name: str = "cards_2026-08-22.json") -> Path:
    path = tmp_path / name
    path.write_bytes(b"x" * 32)
    return path


def _clear() -> None:
    publisher._FAILED_DIRECT_PUBLISH.clear()


def test_an_oversized_file_is_normally_skipped(tmp_path: Path) -> None:
    """The bound still does its job -- this is not a ceiling raise."""
    _clear()
    reason = publisher._publish_skip_reason(_big(tmp_path), date(2026, 8, 22))
    assert reason is not None and reason.startswith("too_large:")


def test_an_oversized_file_whose_DIRECT_publish_failed_is_swept(tmp_path: Path, monkeypatch) -> None:
    """The whole point: the sweep resumes being the retry it is documented as."""
    _clear()
    path = _big(tmp_path)
    monkeypatch.setattr(publisher, "_data_root", lambda: tmp_path)
    relative = publisher.relative_to_data_root(path)
    assert relative, "fixture must sit under the data root"
    publisher._note_direct_publish_failed(relative)
    assert publisher._publish_skip_reason(path, date(2026, 8, 22)) is None


def test_the_exemption_ENDS_when_a_publish_succeeds(tmp_path: Path, monkeypatch) -> None:
    """Otherwise one failure would put a 14MB file on every sweep forever --
    which is the cost the ceiling exists to prevent, arrived at sideways."""
    _clear()
    path = _big(tmp_path)
    monkeypatch.setattr(publisher, "_data_root", lambda: tmp_path)
    relative = publisher.relative_to_data_root(path)
    publisher._note_direct_publish_failed(relative)
    assert publisher._publish_skip_reason(path, date(2026, 8, 22)) is None
    publisher._note_direct_publish_succeeded(relative)
    reason = publisher._publish_skip_reason(path, date(2026, 8, 22))
    assert reason is not None and reason.startswith("too_large:")


def test_a_STALE_slate_is_never_repaired_however_it_failed(tmp_path: Path, monkeypatch) -> None:
    """Staleness is checked first and has no exemption.

    Repairing a slate the receiver correctly ages out is not a repair; it is
    shipping something nobody wants, on the largest files available.
    """
    _clear()
    path = _big(tmp_path, "book_grid_2026-08-01.json")
    monkeypatch.setattr(publisher, "_data_root", lambda: tmp_path)
    publisher._note_direct_publish_failed(publisher.relative_to_data_root(path))
    reason = publisher._publish_skip_reason(path, date(2026, 8, 22))
    assert reason is not None and reason.startswith("stale_slate:")


def test_a_small_file_is_unaffected_either_way(tmp_path: Path, monkeypatch) -> None:
    """Files under the ceiling already retried; this must not change them."""
    _clear()
    path = _small(tmp_path)
    monkeypatch.setattr(publisher, "_data_root", lambda: tmp_path)
    assert publisher._publish_skip_reason(path, date(2026, 8, 22)) is None
    publisher._note_direct_publish_failed(publisher.relative_to_data_root(path))
    assert publisher._publish_skip_reason(path, date(2026, 8, 22)) is None


def test_an_unrelated_oversized_file_is_not_exempted_by_someone_elses_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """The exemption is per-path. A blanket flag would be a ceiling raise."""
    _clear()
    failed = _big(tmp_path, "book_grid_2026-08-22.json")
    other = _big(tmp_path, "odds_history_2026-08-22.json")
    monkeypatch.setattr(publisher, "_data_root", lambda: tmp_path)
    publisher._note_direct_publish_failed(publisher.relative_to_data_root(failed))
    assert publisher._publish_skip_reason(failed, date(2026, 8, 22)) is None
    reason = publisher._publish_skip_reason(other, date(2026, 8, 22))
    assert reason is not None and reason.startswith("too_large:")


def test_marking_is_tolerant_of_an_empty_path() -> None:
    """`relative_to_data_root` returns None for a file outside the root, and an
    instrument that raises while recording a failure would turn a recoverable
    publish error into a crash."""
    _clear()
    publisher._note_direct_publish_failed("")
    assert publisher._FAILED_DIRECT_PUBLISH == set()
