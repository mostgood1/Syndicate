"""The publish sweep must carry TODAY's slate, not the archive.

Measured 2026-08-08: live-odds-worker was republishing May artifacts
(`oddsapi_player_props_2026-05-25.csv`, `smart_sim_2026-05-27_*.json`) on every
boot, because the sweep selected on mtime alone and the artifact PULL kept
touching them. Web wrote them, mtime moved again, and the loop repeated.

`publish_hot_artifact` holds four full copies of a file at once, so that sweep
was fatal on a 2Gi service -- on BOTH ends, since web parses the body whole.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from syndicate.features.shared.artifact_publisher import (
    _PUBLISH_MAX_BYTES,
    _artifact_date,
    _publish_skip_reason,
)

TODAY = date(2026, 8, 8)


def test_reads_a_dashed_date_from_the_name():
    assert _artifact_date(Path("oddsapi_player_props_2026-05-25.csv")) == date(2026, 5, 25)


def test_reads_an_underscored_date_from_the_name():
    """MLB writes `daily_summary_2026_08_07.json`; the separator differs by sport."""
    assert _artifact_date(Path("live_lens_report_2026_08_07.json")) == date(2026, 8, 7)


def test_reads_a_date_embedded_mid_name():
    assert _artifact_date(Path("smart_sim_2026-05-27_NYL_PHX.json")) == date(2026, 5, 27)


def test_undated_file_has_no_date():
    assert _artifact_date(Path("current_week.json")) is None
    assert _artifact_date(Path("boxscores_history.csv")) is None


def test_todays_artifact_publishes(tmp_path):
    p = tmp_path / "live_lens_report_2026_08_08.json"
    p.write_text("{}", encoding="utf-8")
    assert _publish_skip_reason(p, TODAY) is None


def test_yesterdays_artifact_still_publishes(tmp_path):
    """A slate crosses UTC midnight and last night's finals settle this morning."""
    p = tmp_path / "live_lens_report_2026_08_07.json"
    p.write_text("{}", encoding="utf-8")
    assert _publish_skip_reason(p, TODAY) is None


def test_the_may_artifacts_that_caused_the_outage_are_skipped(tmp_path):
    p = tmp_path / "oddsapi_player_props_2026-05-25.csv"
    p.write_text("x", encoding="utf-8")
    reason = _publish_skip_reason(p, TODAY)
    assert reason is not None and reason.startswith("stale_slate")


def test_undated_file_is_never_aged_out(tmp_path):
    """Dropping these would be a coverage bug wearing a memory fix's clothes."""
    p = tmp_path / "current_week.json"
    p.write_text("{}", encoding="utf-8")
    assert _publish_skip_reason(p, TODAY) is None


def test_oversized_undated_file_is_skipped(tmp_path):
    """The date rule cannot age out an undated file; the size rule still can."""
    p = tmp_path / "boxscores_history.csv"
    p.write_bytes(b"x" * (_PUBLISH_MAX_BYTES + 1))
    reason = _publish_skip_reason(p, TODAY)
    assert reason is not None and reason.startswith("too_large")


def test_todays_oversized_artifact_is_still_skipped(tmp_path):
    """The odds-history shard is today's AND huge. Four copies of it is what
    killed the service, so recency does not exempt it -- `/api/ops/artifacts/stream`
    is the channel for that file class."""
    p = tmp_path / "odds_history_2026-08-08.json"
    p.write_bytes(b"y" * (_PUBLISH_MAX_BYTES + 1))
    reason = _publish_skip_reason(p, TODAY)
    assert reason is not None and reason.startswith("too_large")


def test_a_malformed_date_does_not_crash_the_sweep(tmp_path):
    p = tmp_path / "report_2026-13-45.json"
    p.write_text("{}", encoding="utf-8")
    assert _artifact_date(p) is None
    assert _publish_skip_reason(p, TODAY) is None
