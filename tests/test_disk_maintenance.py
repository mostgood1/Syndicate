"""The runner that makes `#396`/`#398`/`#399` actually execute.

Until this existed, nothing called either job, so
`SYNDICATE_ARTIFACT_RETENTION_ENABLED=true` was read by code that never ran --
an enable flag with no effect, which reads as success.

THE TESTS THAT MATTER ARE THE GATES. `#241` put production into a restart loop
by adding periodic work to these workers, and retention deletes files on the
service that is the source of truth. Every default here is off.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import disk_maintenance as dm


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    for key in (
        "SYNDICATE_DISK_MAINTENANCE_ENABLED",
        "SYNDICATE_BOOK_QUOTES_COMPACTION_ENABLED",
        "SYNDICATE_ARTIFACT_RETENTION_ENABLED",
        "SYNDICATE_ARTIFACT_RETENTION_OBSERVE",
        "SYNDICATE_DISK_MAINTENANCE_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_it_does_nothing_at_all_by_default(_clean):
    """The switch that gates every other switch."""
    out = dm.run_disk_maintenance()
    assert out["ran"] is False
    assert out["reason"] == "disabled"


def test_enabling_the_runner_alone_deletes_nothing(_clean, monkeypatch):
    """The observation rung: produces production numbers, touches nothing.

    Needs SYNDICATE_ARTIFACT_RETENTION_OBSERVE since the sweep stopped being
    free -- see test_retention_sweep_is_skipped_unless_asked_for.
    """
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_OBSERVE", "true")
    old = _clean / "mlb_source" / "data" / "book_grid" / "book_grid_2020-01-01.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("x" * 2048, encoding="utf-8")

    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["ran"] is True
    assert out["retention"]["dry_run"] is True
    assert out["retention"]["deleted"] == 0
    assert out["retention"]["reclaimable_mb"] >= 0
    assert out["compaction_applied"] is False
    assert old.exists(), "dry run deleted a file"


def test_retention_deletes_only_when_its_own_flag_is_set(_clean, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    old = _clean / "mlb_source" / "data" / "book_grid" / "book_grid_2020-01-01.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("x" * 2048, encoding="utf-8")

    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["retention"]["dry_run"] is False
    assert out["retention"]["deleted"] >= 1
    assert not old.exists()


def test_the_two_apply_switches_are_independent(_clean, monkeypatch):
    """Retention deleting must not imply compaction acting, or vice versa."""
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    shard = _clean / "mlb_source" / "tracking" / "book_quotes" / "2020-01-01.jsonl"
    shard.parent.mkdir(parents=True, exist_ok=True)
    shard.write_text('{"a":1}\n' * 50, encoding="utf-8")

    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["compaction_applied"] is False
    assert not shard.with_name(shard.name + ".gz").exists(), "compaction acted without its flag"


def test_it_runs_once_per_day_not_once_per_tick(_clean, monkeypatch):
    """`#241`: periodic work on these workers is never free."""
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    first = dm.run_disk_maintenance(sports=("mlb",))
    assert first["ran"] is True
    second = dm.run_disk_maintenance(sports=("mlb",))
    assert second["ran"] is False
    assert second["reason"] == "not_due"


def test_a_zero_interval_does_not_mean_every_tick(_clean, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_INTERVAL_SECONDS", "0")
    assert dm._interval_seconds() == dm._INTERVAL_DEFAULT_SECONDS
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_INTERVAL_SECONDS", "banana")
    assert dm._interval_seconds() == dm._INTERVAL_DEFAULT_SECONDS


def test_it_declines_to_run_under_memory_pressure(_clean, monkeypatch):
    """A tidy-up job that OOMs the worker it is tidying for is worse than the
    disk it was managing. refresh-worker peaks at 3.29 GB of 4 GiB."""
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setattr(dm, "_memory_pressure_blocks", lambda: (True, {"rss_bytes": 9, "limit_bytes": 10}))
    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["ran"] is False
    assert out["reason"] == "memory_pressure"


def test_unmeasurable_memory_does_not_block(_clean, monkeypatch):
    """An unmeasurable guard that refuses would disable maintenance forever, and
    the job it guards deletes nothing by default. Unknown must not be the
    permissive branch for DELETION -- it is not; it is only permissive for
    whether the sweep RUNS."""
    monkeypatch.setattr(dm, "_container_limit_bytes", lambda: 0)
    blocked, facts = dm._memory_pressure_blocks()
    assert blocked is False


def test_a_failing_job_never_takes_the_worker_down(_clean, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_OBSERVE", "true")

    def _boom():
        raise RuntimeError("retention exploded")

    import syndicate.features.shared.artifact_retention as ar

    monkeypatch.setattr(ar, "run_retention_sweep", _boom)
    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["ran"] is True
    assert "error" in str(out["retention"])


def test_the_daily_stamp_is_written_only_after_a_completed_pass(_clean, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    assert dm._due() is True
    dm.run_disk_maintenance(sports=("mlb",))
    assert dm._due() is False


def test_retention_sweep_is_skipped_unless_asked_for(_clean, monkeypatch):
    """Measured in production 2026-08-12: the dry-run sweep blocked
    refresh-worker's main poll loop for >10 minutes (rglob over 14.2 GB,
    117,377 files, on a box already at 100% CPU). Benchmarked at 15.6s against a
    38k-file local mirror -- the mirror was a third of the real disk.

    An observation pass that costs a stalled loop is not free, so it needs its
    own opt-in. Compaction is unaffected."""
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    called = {"n": 0}

    import syndicate.features.shared.artifact_retention as ar

    def _tracked(*a, **k):
        called["n"] += 1
        raise AssertionError("retention swept without opt-in")

    monkeypatch.setattr(ar, "run_retention_sweep", _tracked)
    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["ran"] is True
    assert called["n"] == 0
    assert out["retention"] == {"skipped": "not_enabled_and_not_observing"}


def test_observe_flag_runs_the_sweep_without_deleting(_clean, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_OBSERVE", "true")
    old = _clean / "mlb_source" / "data" / "book_grid" / "book_grid_2020-01-01.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("x" * 2048, encoding="utf-8")

    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["retention"]["dry_run"] is True
    assert out["retention"]["deleted"] == 0
    assert old.exists()


def test_enabling_deletion_still_implies_running_the_sweep(_clean, monkeypatch):
    """The observe flag must not become a second thing to remember before
    deletion works."""
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_ARTIFACT_RETENTION_ENABLED", "true")
    monkeypatch.delenv("SYNDICATE_ARTIFACT_RETENTION_OBSERVE", raising=False)
    old = _clean / "mlb_source" / "data" / "book_grid" / "book_grid_2020-01-01.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("x" * 2048, encoding="utf-8")

    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["retention"]["deleted"] >= 1
    assert not old.exists()


def test_compaction_still_runs_when_retention_is_skipped(_clean, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("SYNDICATE_BOOK_QUOTES_COMPACTION_ENABLED", "true")
    shard = _clean / "mlb_source" / "tracking" / "book_quotes" / "2020-01-01.jsonl"
    shard.parent.mkdir(parents=True, exist_ok=True)
    shard.write_text('{"a":1}\n' * 200, encoding="utf-8")

    out = dm.run_disk_maintenance(sports=("mlb",))
    assert out["compaction_applied"] is True
    assert shard.with_name(shard.name + ".gz").exists()
    assert out["retention"] == {"skipped": "not_enabled_and_not_observing"}


def test_the_daily_stamp_is_PER_SERVICE_not_shared(_clean, monkeypatch):
    """Found in production within an hour of shipping the runner.

    The stamp path is keyvalue-backed (`_keyvalue_backed` excludes only
    `migration_runs/`) and both workers share one Redis, so a single shared path
    made the daily gate global: whichever worker ran first stood the other down
    for 24 hours. Both compacted on night one only by race -- refresh-worker
    passed the check ~26s before live-odds-worker wrote the stamp.
    """
    monkeypatch.setenv("SYNDICATE_REFRESH_LANE", "refresh-worker")
    a = dm._status_path()
    monkeypatch.setenv("SYNDICATE_REFRESH_LANE", "live-odds-worker")
    b = dm._status_path()
    assert a != b, "both workers would share one daily gate"
    assert "refresh-worker" in a.name and "live-odds-worker" in b.name


def test_one_workers_run_does_not_stand_the_other_down(_clean, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DISK_MAINTENANCE_ENABLED", "true")

    monkeypatch.setenv("SYNDICATE_REFRESH_LANE", "refresh-worker")
    first = dm.run_disk_maintenance(sports=("mlb",))
    assert first["ran"] is True
    assert dm._due() is False, "same worker should now be stood down"

    monkeypatch.setenv("SYNDICATE_REFRESH_LANE", "live-odds-worker")
    assert dm._due() is True, "the OTHER worker was stood down by its peer"
    second = dm.run_disk_maintenance(sports=("mlb",))
    assert second["ran"] is True


def test_an_unidentifiable_service_still_gets_a_stamp(_clean, monkeypatch):
    for key in ("SYNDICATE_REFRESH_LANE", "RENDER_SERVICE_NAME", "RENDER_SERVICE_ID"):
        monkeypatch.delenv(key, raising=False)
    assert dm._service_slug() == "local"
    assert dm._status_path().name.endswith("_local.json")
