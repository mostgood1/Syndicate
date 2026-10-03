"""The NCAAF player-stats refresh backfills every earlier week the snapshot lacks.

Measured 2026-10-03: the local fleet started with no 2026 rows, and a refresh
that only re-fetched the target week plus its 2-week lookback never asked CFBD
for weeks 1-2, so every prop projection was built on 2 of 4 weeks. These tests
fail on the code before the fix (no `missing_weeks`; the job asked for (4, 5)).
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import refresh_ncaaf_player_game_stats as job
from syndicate.features.ncaaf.player_stats_refresh import missing_weeks


def _snapshot(path: Path, groups: dict[tuple[int, int], int]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["season", "week", "game_id", "player_id"])
        writer.writeheader()
        for (season, week), n in groups.items():
            for i in range(n):
                writer.writerow({"season": season, "week": week, "game_id": f"{week}{i}", "player_id": str(i)})
    return path


def test_missing_weeks_lists_only_earlier_empty_weeks_of_this_season(tmp_path):
    snap = _snapshot(tmp_path / "s.csv", {(2025, 1): 3, (2025, 2): 3, (2026, 3): 2, (2026, 4): 2})
    assert missing_weeks(snap, season=2026, target_week=5) == (1, 2)
    # another season's rows never count as this season's history
    assert missing_weeks(snap, season=2026, target_week=3) == (1, 2)
    assert missing_weeks(snap, season=2025, target_week=4) == (3,)


def test_missing_weeks_on_an_absent_file_is_the_whole_season_and_none_is_safe(tmp_path):
    assert missing_weeks(tmp_path / "absent.csv", season=2026, target_week=5) == (1, 2, 3, 4)
    assert missing_weeks(tmp_path / "absent.csv", season=2026, target_week=None) == ()
    assert missing_weeks(tmp_path / "absent.csv", season=2026, target_week=1) == ()


@pytest.fixture
def captured(monkeypatch):
    calls = {}

    class _Report:
        ok = True

        def as_dict(self):
            return {}

    def fake_refresh(*, client, season, weeks, output_path, season_type, source_snapshot_date):
        calls["weeks"] = tuple(weeks)
        return _Report()

    monkeypatch.setattr(job, "refresh_player_game_stats", fake_refresh)
    monkeypatch.setattr(job.CfbdClient, "from_env", classmethod(lambda cls, **kw: object()))
    monkeypatch.setattr(job, "_load_env", lambda: None)
    import syndicate.features.shared.artifact_publisher as publisher

    monkeypatch.setattr(publisher, "publish_hot_artifact", lambda *a, **k: False)
    return calls


def _run(tmp_path, snap, *extra):
    return job.main(["--force", "--season", "2026", "--target-week", "5", "--output-path", str(snap), "--json", *extra])


def test_the_job_fetches_the_window_plus_the_missing_weeks(tmp_path, captured):
    snap = _snapshot(tmp_path / "s.csv", {(2025, 1): 3, (2026, 3): 2, (2026, 4): 2})
    assert _run(tmp_path, snap) == 0
    assert captured["weeks"] == (1, 2, 4, 5)


def test_a_fresh_disk_backfills_the_whole_season(tmp_path, captured):
    assert _run(tmp_path, tmp_path / "absent.csv") == 0
    assert captured["weeks"] == (1, 2, 3, 4, 5)


def test_explicit_weeks_and_no_backfill_are_unchanged(tmp_path, captured):
    snap = _snapshot(tmp_path / "s.csv", {(2026, 4): 2})
    assert _run(tmp_path, snap, "--weeks", "3") == 0
    assert captured["weeks"] == (3,)
    assert _run(tmp_path, snap, "--no-backfill") == 0
    assert captured["weeks"] == (4, 5)


def test_a_complete_season_adds_nothing(tmp_path, captured):
    snap = _snapshot(tmp_path / "s.csv", {(2026, w): 2 for w in (1, 2, 3, 4)})
    assert _run(tmp_path, snap) == 0
    assert captured["weeks"] == (4, 5)
