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
    #
    # #417 moved this by +34.3MB, to 3428.1. That number is this fixture's
    # `active_file` exactly, and the change is deliberate: active_file is clean
    # page cache and is now credited as reclaimable like inactive_file. The
    # conclusion this test was written to protect is untouched -- 868 vs 3428
    # rather than 868 vs 3393 -- and #79's own reasoning already noted shmem
    # was 0, i.e. none of the cache here is pinned.
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
    # approx because the fixture truncates MB->bytes; the point is 3428 vs 868,
    # not the tenth.
    assert snapshot["headroom_mb"] == pytest.approx(3428.1, abs=0.2)
    # Both numbers stay visible, so the difference never has to be rediscovered.
    # Renamed by #417: it holds max - current, which EXCLUDES the file cache.
    assert snapshot["headroom_excluding_file_cache_mb"] == pytest.approx(867.7, abs=0.2)
    assert "headroom_including_file_cache_mb" not in snapshot
    assert snapshot["reclaimable_file_mb"] == pytest.approx(2560.4, abs=0.2)
    # 662.5 anon + 0 shmem + 1.0 slab_unreclaimable = 663.5 proven, against a
    # residual basis of 3228.3 - 2560.4 = 667.9. The larger wins, so the 4.4MB
    # memory.stat does not attribute counts against the guard, not for it.
    assert snapshot["unreclaimable_mb"] == pytest.approx(667.9, abs=0.2)
    assert snapshot["basis"] == "unreclaimable"


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


def test_shmem_is_not_treated_as_reclaimable(monkeypatch):
    # This was test_active_file_and_shmem_are_not_treated_as_reclaimable, and it
    # asserted that BOTH terms count as used, on the reasoning that this was
    # "deliberately the conservative reading of reclaimable".
    #
    # #417 overturned the active_file half of that premise. Excluding
    # active_file is not conservative, it is UNSTABLE: the kernel promotes
    # inactive_file -> active_file on its own, so the guard's verdict moved
    # ~243MB with nothing about memory pressure changing. See
    # test_417_page_cache_promotion_must_not_move_the_guard below, which now
    # owns the active_file case and asserts the opposite.
    #
    # The shmem half is kept because it is still true and for a different
    # reason: shmem is not clean page cache at all. Without swap the kernel
    # cannot evict it, so it is unreclaimable and must count against headroom
    # exactly like anon does.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(3000 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(4096 * BYTES_PER_MB))
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {
            "anon": int(500 * BYTES_PER_MB),
            "shmem": int(1300 * BYTES_PER_MB),
            "inactive_file": 0,
            "active_file": 0,
            "slab_unreclaimable": 0,
        },
    )

    snapshot = memory_observability.memory_headroom_snapshot(900 * BYTES_PER_MB)
    assert snapshot is not None
    # 500 anon + 1300 shmem = 1800MB unreclaimable, so 2296MB is genuinely
    # available -- but none of it comes from crediting shmem back.
    assert snapshot["reclaimable_file_mb"] == 0.0
    assert snapshot["sufficient"] is True


# --- #417 falsification tests -------------------------------------------------
#
# These are written BEFORE the fix and are EXPECTED TO FAIL against the current
# formula. They encode the hypothesis; if they pass today, the hypothesis is
# wrong and the lane's premise dies before any code changes.
#
# Source: refresh-worker 2026-08-13, the 300 consecutive
# MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint cycles that served a
# 4h12m-stale board (#417). Container max 4096MB, floor 1900MB.
#
# slab_reclaimable is not in the recorded table; each row's value is back-solved
# from the recorded headroom and lands at 34-39MB across all four samples, which
# is what makes this fixture self-validating: if the reproduction of
# `headroom_mb` below ever breaks, the fixture is wrong, not the code.

_417_FLOOR_BYTES = 1900 * BYTES_PER_MB
_417_MAX_BYTES = int(4096 * BYTES_PER_MB)

# (label, current, anon, active_file, inactive_file, slab_reclaimable, recorded_headroom)
_417_SERIES = (
    ("09:29:27", 2988.6, 1659.0, 553.9, 735.4, 34.2, 1877.0),
    ("10:37:27", 2993.7, 1641.1, 553.9, 757.7, 35.3, 1895.3),
    ("11:02:03", 2705.3, 1648.9, 797.4, 218.0, 34.8, 1643.5),
    ("14:54:44", 2988.3, 1677.9, 790.7, 474.7, 39.3, 1621.7),
)


def _417_sample(monkeypatch, current_mb, anon_mb, active_file_mb, inactive_file_mb, slab_reclaimable_mb):
    monkeypatch.setattr(
        memory_observability, "_read_container_memory_current_bytes", lambda: int(current_mb * BYTES_PER_MB)
    )
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: _417_MAX_BYTES)
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {
            "anon": int(anon_mb * BYTES_PER_MB),
            "active_file": int(active_file_mb * BYTES_PER_MB),
            "inactive_file": int(inactive_file_mb * BYTES_PER_MB),
            "slab_reclaimable": int(slab_reclaimable_mb * BYTES_PER_MB),
            # Both measured at 14:54:44 and assumed flat across the window.
            # shmem was 0.0 in the #79 sample too, so this term has never
            # actually been exercised on refresh-worker -- do not read a pass
            # here as evidence that pinned shared memory is handled.
            "slab_unreclaimable": int(0.6 * BYTES_PER_MB),
            "shmem": 0,
        },
    )
    return memory_observability.memory_headroom_snapshot(_417_FLOOR_BYTES)


def test_417_page_cache_promotion_must_not_move_the_guard(monkeypatch):
    # The isolated variable. Two samples identical in every term that OOM
    # responds to -- same current, same anon, same total file cache -- differing
    # only in which LRU bucket 243MB of clean page cache sits in.
    #
    # This is the whole defect in one assertion. The kernel did this on its own
    # at ~11:02 and the board stopped building for four hours.
    before = _417_sample(monkeypatch, 2993.7, 1641.1, 553.9, 757.7, 35.3)
    after = _417_sample(monkeypatch, 2993.7, 1641.1, 796.9, 514.7, 35.3)

    assert before is not None and after is not None
    # Today: 1895.3 -> 1652.3, a 243MB swing bought entirely with bookkeeping.
    assert after["headroom_mb"] == pytest.approx(before["headroom_mb"], abs=1.0)
    # And the decision must be stable across it, in the permissive direction:
    # 4096 - (1641.1 anon + 0 shmem + 0.6 slab_unreclaimable) = 2454.3 available
    # against a 1900 floor. Today both read False and the cycle aborts.
    assert before["sufficient"] is True
    assert after["sufficient"] is True


def test_417_series_never_tightens_while_memory_in_use_falls(monkeypatch):
    # The corollary from learnings.md, stated as an executable invariant:
    # if usage going DOWN can make a guard stricter, the guard is reading the
    # wrong quantity. That inversion is a complete proof on its own.
    readings = []
    for label, current, anon, active_file, inactive_file, slab_reclaimable, recorded in _417_SERIES:
        snapshot = _417_sample(monkeypatch, current, anon, active_file, inactive_file, slab_reclaimable)
        assert snapshot is not None, label
        readings.append((label, current, snapshot))

    # Every one of the 300 aborted cycles had room. None of them should have
    # been refused.
    for label, _current, snapshot in readings:
        assert snapshot["sufficient"] is True, f"{label} refused a build that fits"

    # The inversion itself: 10:37 -> 11:02, memory in use fell 288.4MB and the
    # old formula responded by tightening 251.8MB.
    (_, before_current, before), (_, after_current, after) = readings[1], readings[2]
    assert after_current < before_current
    assert after["headroom_mb"] >= before["headroom_mb"] - 10.0, (
        "usage fell but the guard got stricter -- still reading the wrong quantity"
    )

    # Across the full 5.4h window anon drifted +18.9MB (flat, measured, not a
    # leak), so the guard's own reading must be similarly flat. Today it spans
    # 273.6MB.
    spread = max(s["headroom_mb"] for _, _, s in readings) - min(s["headroom_mb"] for _, _, s in readings)
    assert spread < 60.0, f"guard swung {spread:.1f}MB while real pressure moved ~19MB"


def test_unreadable_anon_must_not_produce_a_rosy_headroom(monkeypatch):
    # memory.stat parsed, but the term the new formula depends on is missing.
    # Computing unreclaimable as anon.get(...) or 0 would read "0MB
    # unreclaimable, 4096MB available" off a container that is nearly full --
    # the permissive-on-unknown shape that turns a failed read into a false
    # all-clear. Degrade to the old max - current basis instead.
    monkeypatch.setattr(memory_observability, "_read_container_memory_current_bytes", lambda: int(3228 * BYTES_PER_MB))
    monkeypatch.setattr(memory_observability, "_read_container_memory_max_bytes", lambda: int(4096 * BYTES_PER_MB))
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {
            "inactive_file": int(20 * BYTES_PER_MB),
            "slab_reclaimable": int(8 * BYTES_PER_MB),
        },
    )

    snapshot = memory_observability.memory_headroom_snapshot(900 * BYTES_PER_MB)
    assert snapshot is not None
    assert snapshot["headroom_mb"] < 1000.0
    assert snapshot["sufficient"] is False


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
