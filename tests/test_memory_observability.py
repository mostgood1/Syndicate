from __future__ import annotations

import sys
from pathlib import Path

import pytest


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

def test_reclaimable_page_cache_does_not_count_against_headroom(monkeypatch):
    # #79. These are the real numbers off refresh-worker 2026-07-26T22:47Z,
    # which had refused to build the board on every cycle for half an hour:
    # 3228MB of 4096 "used", but 2476MB of that is inactive_file -- clean page
    # cache the kernel drops on demand rather than OOM-killing over -- and
    # only 662MB is anonymous. shmem is 0, so none of the cache is pinned.
    #
    # Old behaviour: headroom 867.7 < 900, refuse. New: 3393.7, proceed.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(3228.3 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(4096 * BYTES_PER_MB))
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {
            "anon": int(662.5 * BYTES_PER_MB),
            "file": int(2510.6 * BYTES_PER_MB),
            "inactive_file": int(2476.3 * BYTES_PER_MB),
            "active_file": int(34.3 * BYTES_PER_MB),
            "slab_reclaimable": int(49.8 * BYTES_PER_MB),
            "slab_unreclaimable": int(1.0 * BYTES_PER_MB),
            "shmem": 0,
        },
    )

    snapshot = memory_observability.memory_headroom_snapshot(900 * BYTES_PER_MB)
    assert snapshot is not None
    assert snapshot["sufficient"] is True
    # approx because the fixture truncates MB->bytes; the point is 3393 vs 868,
    # not the tenth.
    assert snapshot["headroom_mb"] == pytest.approx(3393.7, abs=0.2)
    # Both numbers stay visible, so the difference never has to be rediscovered.
    assert snapshot["headroom_including_file_cache_mb"] == pytest.approx(867.7, abs=0.2)
    assert snapshot["reclaimable_file_mb"] == pytest.approx(2526.1, abs=0.2)


def test_anonymous_memory_still_counts_against_headroom(monkeypatch):
    # The other half of the guard, and the reason step 1 read memory.stat
    # before step 2 changed anything: if the container is genuinely full of
    # ANONYMOUS memory, nothing is reclaimable and the build must still be
    # refused. Same totals as the test above, attributed the other way.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(3228.3 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(4096 * BYTES_PER_MB))
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {
            "anon": int(3200 * BYTES_PER_MB),
            "file": int(28 * BYTES_PER_MB),
            "inactive_file": int(20 * BYTES_PER_MB),
            "slab_reclaimable": int(8 * BYTES_PER_MB),
        },
    )

    snapshot = memory_observability.memory_headroom_snapshot(900 * BYTES_PER_MB)
    assert snapshot is not None
    assert snapshot["sufficient"] is False


def test_active_file_and_shmem_are_not_treated_as_reclaimable(monkeypatch):
    # Deliberately the conservative reading of "reclaimable". active_file is
    # evictable but only under real pressure, and shmem is not evictable at
    # all -- counting either would overstate headroom on a container whose
    # cache is hot or shared-memory backed.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(3000 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(4096 * BYTES_PER_MB))
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {
            "anon": int(500 * BYTES_PER_MB),
            "active_file": int(1200 * BYTES_PER_MB),
            "shmem": int(1300 * BYTES_PER_MB),
            "inactive_file": 0,
        },
    )

    snapshot = memory_observability.memory_headroom_snapshot(900 * BYTES_PER_MB)
    assert snapshot is not None
    # 4096 - 3000 = 1096, with nothing added back.
    assert snapshot["headroom_mb"] == 1096.0
    assert snapshot["reclaimable_file_mb"] == 0.0


def test_memory_stat_absent_falls_back_to_the_conservative_calculation(monkeypatch):
    # cgroups missing (local dev) or memory.stat unreadable must degrade to
    # the OLD max - current behaviour, not to "assume it is all reclaimable".
    # Failing safe here is what keeps an unreadable file from re-opening #75.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(3228 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(4096 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_stat", lambda: {})

    snapshot = memory_observability.memory_headroom_snapshot(900 * BYTES_PER_MB)
    assert snapshot is not None
    assert snapshot["headroom_mb"] == 868.0
    assert snapshot["sufficient"] is False
    assert "stat_mb" not in snapshot


def test_container_memory_log_separates_reclaimable_cache_from_anonymous(monkeypatch, capsys):
    # #318. The real web numbers, 2026-08-09T21:00:47Z, seconds before an
    # oomKilled at a 2GiB limit. The line used to carry memory_current_mb
    # 1877.1 / 91.7% and nothing else, next to a PROCESS_TREE_MEMORY reading
    # self_rss_mb 189.1 -- a 1.7GB gap that the logger could not attribute.
    #
    # Attributed here the harmless way: mostly clean page cache. The assertion
    # that matters is that the two readings are DIFFERENT, so 91.7% can no
    # longer be quoted as though it were the pressure.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(1877.1 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(2048 * BYTES_PER_MB))
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {
            "anon": int(402.0 * BYTES_PER_MB),
            "inactive_file": int(1400.0 * BYTES_PER_MB),
            "slab_reclaimable": int(20.0 * BYTES_PER_MB),
        },
    )

    payload = memory_observability.log_container_memory("build_live_lines_payload_local_return")

    # The pre-existing fields are untouched -- this is additive.
    assert payload["memory_current_mb"] == pytest.approx(1877.1, abs=0.2)
    assert payload["memory_pct_of_max"] == pytest.approx(91.7, abs=0.2)
    # ...and the new ones say the container is nowhere near its real ceiling.
    assert payload["memory_anon_mb"] == pytest.approx(402.0, abs=0.2)
    assert payload["memory_reclaimable_mb"] == pytest.approx(1420.0, abs=0.2)
    assert payload["memory_unreclaimable_mb"] == pytest.approx(457.1, abs=0.2)
    assert payload["memory_unreclaimable_pct_of_max"] == pytest.approx(22.3, abs=0.2)
    # Emitted, not merely returned: the log line is the whole point of #318.
    assert "memory_unreclaimable_mb" in capsys.readouterr().err


def test_container_memory_log_omits_the_split_when_memory_stat_is_unreadable(monkeypatch):
    # Unknown must not read as "22% used, plenty of room". With no memory.stat
    # the split keys are ABSENT rather than 0, so a reader that keys off them
    # gets nothing to misread instead of a fabricated all-clear.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(1877.1 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(2048 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_stat", lambda: {})

    payload = memory_observability.log_container_memory("stage")

    assert payload["memory_pct_of_max"] == pytest.approx(91.7, abs=0.2)
    for key in ("memory_anon_mb", "memory_reclaimable_mb", "memory_unreclaimable_mb", "memory_unreclaimable_pct_of_max"):
        assert key not in payload
