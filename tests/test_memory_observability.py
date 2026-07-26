from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.features.shared.memory_observability as memory_observability


BYTES_PER_MB = 1024 * 1024
BYTES_PER_KB = 1024


def _write_procfs_process(root: Path, pid: int, *, name: str, ppid: int, rss_kb: int, cmdline: list[str]) -> None:
    process_dir = root / str(pid)
    process_dir.mkdir(parents=True, exist_ok=True)
    process_dir.joinpath("status").write_text(
        "\n".join(
            [
                f"Name:\t{name}",
                "State:\tS (sleeping)",
                f"Pid:\t{pid}",
                f"PPid:\t{ppid}",
                f"VmRSS:\t{rss_kb} kB",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    process_dir.joinpath("cmdline").write_bytes("\0".join(cmdline).encode("utf-8") + b"\0")
    process_dir.joinpath("comm").write_text(f"{name}\n", encoding="utf-8")


def test_get_all_process_memory_snapshot_uses_procfs_fallback_and_keeps_required_processes(monkeypatch, tmp_path):
    current_pid = 4242
    parent_pid = 4241
    sibling_pid = 4243

    monkeypatch.setattr(memory_observability, "psutil", None)
    monkeypatch.setattr(memory_observability, "_PROCFS_ROOT", tmp_path)
    monkeypatch.setattr(memory_observability.os, "getpid", lambda: current_pid)
    monkeypatch.setattr(memory_observability.os, "getppid", lambda: parent_pid)
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: 96 * BYTES_PER_MB)

    _write_procfs_process(tmp_path, current_pid, name="python", ppid=parent_pid, rss_kb=12000, cmdline=["python", "refresh.py"])
    _write_procfs_process(tmp_path, parent_pid, name="gunicorn", ppid=1, rss_kb=34000, cmdline=["gunicorn", "app:app"])
    _write_procfs_process(tmp_path, sibling_pid, name="worker", ppid=parent_pid, rss_kb=18000, cmdline=["worker"])

    snapshot = memory_observability.get_all_process_memory_snapshot()

    assert snapshot["process_count"] == 3
    assert snapshot["accounted_rss_mb"] == round(((12000 + 34000 + 18000) * BYTES_PER_KB) / BYTES_PER_MB, 3)
    assert snapshot["unexplained_memory_mb"] == round(96 - snapshot["accounted_rss_mb"], 3)

    process_ids = {process["pid"] for process in snapshot["processes"]}
    assert current_pid in process_ids
    assert parent_pid in process_ids
    assert snapshot["processes"][0]["pid"] == parent_pid
    assert snapshot["process_enum_debug"]["psutil_available"] is False
    assert snapshot["process_enum_debug"]["error_count"] >= 1


def test_log_all_process_memory_emits_debug_and_payload(monkeypatch, tmp_path, capsys):
    current_pid = 5151
    parent_pid = 5150

    monkeypatch.setattr(memory_observability, "psutil", None)
    monkeypatch.setattr(memory_observability, "_PROCFS_ROOT", tmp_path)
    monkeypatch.setattr(memory_observability.os, "getpid", lambda: current_pid)
    monkeypatch.setattr(memory_observability.os, "getppid", lambda: parent_pid)
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: 88 * BYTES_PER_MB)

    _write_procfs_process(tmp_path, current_pid, name="python", ppid=parent_pid, rss_kb=9000, cmdline=["python", "refresh.py"])
    _write_procfs_process(tmp_path, parent_pid, name="web", ppid=1, rss_kb=25000, cmdline=["gunicorn", "web:app"])

    payload = memory_observability.log_all_process_memory("startup", script="refresh_odds_sources")
    captured = capsys.readouterr()

    assert "PROCESS_ENUM_DEBUG" in captured.err
    assert "ALL_PROCESS_MEMORY" in captured.err
    assert payload["process_count"] == 2
    assert current_pid in {process["pid"] for process in payload["processes"]}
    assert parent_pid in {process["pid"] for process in payload["processes"]}


def test_memory_headroom_snapshot_none_when_unmeasurable(monkeypatch):
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: None)
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: 2048 * BYTES_PER_MB)

    assert memory_observability.memory_headroom_snapshot(1800 * BYTES_PER_MB) is None


def test_memory_headroom_snapshot_reports_insufficient_and_sufficient(monkeypatch):
    max_bytes = 2048 * BYTES_PER_MB
    min_required_bytes = 1800 * BYTES_PER_MB

    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(1900 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: max_bytes)
    tight = memory_observability.memory_headroom_snapshot(min_required_bytes)
    assert tight is not None
    assert tight["sufficient"] is False
    assert tight["min_required_mb"] == 1800.0

    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(100 * BYTES_PER_MB))
    roomy = memory_observability.memory_headroom_snapshot(min_required_bytes)
    assert roomy is not None
    assert roomy["sufficient"] is True

def test_memory_stat_breakdown_is_diagnostic_only_and_never_moves_the_gate(monkeypatch):
    # #79. The board build refuses to start every cycle on refresh-worker
    # because headroom is computed as max - memory.current, and cgroup v2's
    # memory.current includes reclaimable page cache: 3309MB of 4096 used with
    # only 451MB owned by any process.
    #
    # This pins the shape of the reading that will settle whether the guard is
    # measuring the wrong thing -- AND that adding it did not quietly relax the
    # guard. `sufficient` must still be driven by max - current alone, even
    # when the breakdown says almost all of it is evictable file cache.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(3309 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(4096 * BYTES_PER_MB))
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {
            "anon": int(451 * BYTES_PER_MB),
            "file": int(2670 * BYTES_PER_MB),
            "inactive_file": int(2622 * BYTES_PER_MB),
            "active_file": int(48 * BYTES_PER_MB),
            "slab_reclaimable": int(28 * BYTES_PER_MB),
        },
    )

    snapshot = memory_observability.memory_headroom_snapshot(900 * BYTES_PER_MB)
    assert snapshot is not None
    # The gate is unchanged: 4096 - 3309 = 787 < 900.
    assert snapshot["headroom_mb"] == 787.0
    assert snapshot["sufficient"] is False
    # ...while the diagnostic shows what a page-cache-aware gate would decide.
    assert snapshot["stat_mb"]["inactive_file"] == 2622.0
    assert snapshot["reclaimable_file_mb"] == 2650.0
    assert snapshot["would_be_sufficient_excluding_file_cache"] is True


def test_memory_stat_absent_leaves_the_snapshot_untouched(monkeypatch):
    # cgroups may be missing entirely (local dev) or memory.stat unreadable.
    # The snapshot must degrade to exactly its previous shape rather than
    # carrying half-populated diagnostic keys.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(100 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(2048 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_stat", lambda: {})

    snapshot = memory_observability.memory_headroom_snapshot(900 * BYTES_PER_MB)
    assert snapshot is not None
    assert snapshot["sufficient"] is True
    assert "stat_mb" not in snapshot
    assert "would_be_sufficient_excluding_file_cache" not in snapshot
