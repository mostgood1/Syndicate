"""SYNDICATE_LOCAL_MEMORY_LIMIT_MB: a measured ceiling where no cgroup exists.

First native-Windows local-production run (2026-09-30): with no cgroup every
`memory_headroom_snapshot` was None, so each gate on it failed closed. The key
must be inert when unset (Render never sets it) and must never outrank a real
cgroup limit.
"""
from __future__ import annotations

import os

import pytest

from syndicate.features.shared import memory_observability as mo

MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(mo.LOCAL_MEMORY_LIMIT_ENV, raising=False)
    monkeypatch.delenv(mo.LOCAL_MEMORY_ROOT_PID_ENV, raising=False)


def test_unset_is_inert(monkeypatch):
    monkeypatch.setattr(mo, "_read_cgroup_memory_max_bytes", lambda: None)
    called = []
    monkeypatch.setattr(mo, "_local_process_tree_rss_bytes", lambda: called.append(1) or 123)
    assert mo._read_container_memory_max_bytes() is None
    mo._read_container_memory_current_bytes()
    assert called == []  # the psutil path is never taken without the key


def test_no_cgroup_measures_the_process_tree_against_the_declared_ceiling(monkeypatch):
    monkeypatch.setattr(mo, "_read_cgroup_memory_max_bytes", lambda: None)
    monkeypatch.setenv(mo.LOCAL_MEMORY_LIMIT_ENV, "4096")
    assert mo._read_container_memory_max_bytes() == 4096 * MB
    current = mo._read_container_memory_current_bytes()
    assert current is not None and 0 < current < 4096 * MB  # this test process, measured
    assert os.environ[mo.LOCAL_MEMORY_ROOT_PID_ENV] == str(os.getpid())
    assert mo.memory_headroom_snapshot(1 * MB)["sufficient"] is True
    assert mo.memory_headroom_snapshot(4096 * MB)["sufficient"] is False


def test_a_real_cgroup_limit_wins(monkeypatch):
    monkeypatch.setattr(mo, "_read_cgroup_memory_max_bytes", lambda: 2048 * MB)
    monkeypatch.setenv(mo.LOCAL_MEMORY_LIMIT_ENV, "4096")
    monkeypatch.setattr(mo, "_local_process_tree_rss_bytes", lambda: pytest.fail("psutil path used under a cgroup"))
    assert mo._read_container_memory_max_bytes() == 2048 * MB
    mo._read_container_memory_current_bytes()


@pytest.mark.parametrize("raw", ["", "0", "-5", "abc"])
def test_unusable_values_stay_unmeasurable(monkeypatch, raw):
    monkeypatch.setattr(mo, "_read_cgroup_memory_max_bytes", lambda: None)
    monkeypatch.setenv(mo.LOCAL_MEMORY_LIMIT_ENV, raw)
    assert mo._read_container_memory_max_bytes() is None


def test_a_vm_wide_memory_stat_is_ignored_under_the_local_ceiling(monkeypatch):
    # WSL2: memory.stat is the whole VM's. Charging one role for every role's
    # anon understated headroom; the role's own RSS is the only usage basis.
    monkeypatch.setattr(mo, "_read_cgroup_memory_max_bytes", lambda: None)
    monkeypatch.setenv(mo.LOCAL_MEMORY_LIMIT_ENV, "4096")
    monkeypatch.setattr(mo, "_local_process_tree_rss_bytes", lambda: 700 * MB)
    assert mo._read_container_memory_stat() == {}
    snapshot = mo.memory_headroom_snapshot(900 * MB)
    assert snapshot["headroom_mb"] == 4096 - 700
    assert snapshot["sufficient"] is True
