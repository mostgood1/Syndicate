"""`shared_disk_fleet`: on the local one-disk fleet a publish is delivered by the
write and a pull is already current -- not a FAILURE (2,838 false
BOOK_GRID_PUBLISH_FAILED lines on 2026-10-02). Render, which sets the publish
URL, must behave exactly as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.shared import artifact_publisher as ap


@pytest.fixture()
def grid(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    path = tmp_path / "wnba_source" / "data" / "book_grid" / "book_grid_2026-10-02.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    monkeypatch.delenv("SYNDICATE_WEB_PUBLISH_URL", raising=False)
    return path


def test_local_fleet_publish_is_delivered_silently(grid, monkeypatch, capsys):
    monkeypatch.setenv("SYNDICATE_LOCAL_PRODUCTION", "1")
    assert ap.shared_disk_fleet() is True
    assert ap.publish_hot_artifact(grid) is True
    assert "SKIP_NOT_CONFIGURED" not in capsys.readouterr().out


def test_local_fleet_missing_file_is_still_a_failure(grid, monkeypatch):
    monkeypatch.setenv("SYNDICATE_LOCAL_PRODUCTION", "1")
    assert ap.publish_hot_artifact(grid.with_name("book_grid_2026-10-03.json")) is False


def test_local_fleet_pulls_are_current_and_quiet(grid, monkeypatch, capsys):
    monkeypatch.setenv("SYNDICATE_LOCAL_PRODUCTION", "1")
    assert ap.pull_streamed_artifact("wnba_source/data/book_grid/book_grid_2026-10-02.json") == (True, 0)
    assert ap.pull_hot_artifacts(date_str="2026-10-02") == 0
    assert "PULL_SKIP_NOT_CONFIGURED" not in capsys.readouterr().out


def test_unconfigured_outside_the_fleet_still_reports_not_configured(grid, monkeypatch, capsys):
    """Off != on: without the fleet flag the old, loud behaviour is unchanged."""
    monkeypatch.delenv("SYNDICATE_LOCAL_PRODUCTION", raising=False)
    assert ap.shared_disk_fleet() is False
    assert ap.publish_hot_artifact(grid) is False
    assert "SKIP_NOT_CONFIGURED" in capsys.readouterr().out


def test_a_publish_url_wins_over_the_fleet_flag(grid, monkeypatch):
    """Render (and `up --publish-loopback`) set the URL: the network path runs."""
    monkeypatch.setenv("SYNDICATE_LOCAL_PRODUCTION", "1")
    monkeypatch.setenv("SYNDICATE_WEB_PUBLISH_URL", "http://127.0.0.1:9")
    assert ap.shared_disk_fleet() is False
    calls = []
    monkeypatch.setattr(ap, "_publish_url", lambda: calls.append(1) or "")
    ap.publish_hot_artifact(grid)
    assert calls, "the configured network path was not reached"
