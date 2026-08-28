"""MLB's hydration runs in a capped child, so its excursion cannot kill the worker.

The load-bearing tests here are the ones about the CAP being DERIVED. A fixed
cap is how `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` became unreachable -- the
constant never changed, the parent's baseline drifted up underneath it. A
derived cap cannot repeat that, and these pin the arithmetic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from syndicate.features.shared import overview_subprocess as iso


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for key in (
        "SYNDICATE_OVERVIEW_ISOLATION_ENABLED",
        "SYNDICATE_OVERVIEW_ISOLATION_SPORTS",
        "SYNDICATE_OVERVIEW_ISOLATION_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def test_off_by_default_so_a_deploy_cannot_add_periodic_work_silently():
    assert iso.overview_isolation_enabled() is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_enable_flag_truthy_spellings(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_OVERVIEW_ISOLATION_ENABLED", raw)
    assert iso.overview_isolation_enabled() is True


def test_only_mlb_is_isolated_by_default():
    """The other seven clear the streamed floor; isolating them buys a spawn."""
    assert iso.isolated_sport_slugs() == frozenset({"mlb"})


def test_isolated_sports_are_configurable(monkeypatch):
    monkeypatch.setenv("SYNDICATE_OVERVIEW_ISOLATION_SPORTS", "mlb, soccer")
    assert iso.isolated_sport_slugs() == frozenset({"mlb", "soccer"})


def test_cap_is_derived_from_headroom_not_a_constant(monkeypatch):
    """THE POINT OF THE LANE. cap = headroom - RESERVE, recomputed every call."""
    monkeypatch.setattr(iso, "_headroom_bytes", lambda: 2400 * 1024 * 1024)
    cap, reason = iso._derive_cap_bytes()
    assert reason == "ok"
    assert cap == (2400 - 400) * 1024 * 1024

    # Parent grows; cap SHRINKS with it. A fixed cap would not.
    monkeypatch.setattr(iso, "_headroom_bytes", lambda: 1600 * 1024 * 1024)
    cap2, _ = iso._derive_cap_bytes()
    assert cap2 == (1600 - 400) * 1024 * 1024
    assert cap2 < cap


def test_refuses_when_there_is_not_enough_room_to_try(monkeypatch):
    """A guaranteed-dead child is noise; refusing is a reading."""
    monkeypatch.setattr(iso, "_headroom_bytes", lambda: 1000 * 1024 * 1024)
    cap, reason = iso._derive_cap_bytes()
    assert cap is None
    assert "cap_below_viable" in reason


def test_unmeasurable_headroom_is_not_zero_headroom(monkeypatch):
    """None must not collapse onto 'no room' -- local dev has no cgroups."""
    monkeypatch.setattr(iso, "_headroom_bytes", lambda: None)
    cap, reason = iso._derive_cap_bytes()
    assert cap is None
    assert reason == "headroom_unmeasurable"


def test_a_refusal_returns_none_and_never_raises(monkeypatch, capfd):
    monkeypatch.setattr(iso, "_headroom_bytes", lambda: 1000 * 1024 * 1024)
    row, reason = iso.build_sport_overview_isolated({"slug": "mlb"}, "2026-08-28")
    assert row is None
    assert "cap_below_viable" in reason
    assert "REFUSED sport=mlb" in capfd.readouterr().out


def test_a_child_that_fails_returns_none_rather_than_raising(monkeypatch, capfd):
    """A crashed child must degrade to the OLD behaviour, not to an exception."""
    monkeypatch.setattr(iso, "_headroom_bytes", lambda: 3000 * 1024 * 1024)

    class _Proc:
        returncode = 4
        stdout = "[overview_child] MEMORY_CAP_HIT sport=mlb\n"
        stderr = "MemoryError\n"

    monkeypatch.setattr(iso.subprocess, "run", lambda *a, **k: _Proc())
    row, reason = iso.build_sport_overview_isolated({"slug": "mlb"}, "2026-08-28")
    assert row is None
    assert reason == "child_rc_4"
    out = capfd.readouterr().out
    # The child's own cap evidence must be RELAYED -- it is the only proof the
    # cap did anything, and it lives on the child's stdout.
    assert "MEMORY_CAP_HIT" in out
    assert "CHILD_FAILED sport=mlb rc=4" in out


def test_a_timeout_returns_none_and_is_named(monkeypatch, capfd):
    monkeypatch.setattr(iso, "_headroom_bytes", lambda: 3000 * 1024 * 1024)

    def _boom(*a, **k):
        raise iso.subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(iso.subprocess, "run", _boom)
    row, reason = iso.build_sport_overview_isolated({"slug": "mlb"}, "2026-08-28")
    assert row is None and reason == "timeout"
    assert "CHILD_TIMEOUT sport=mlb" in capfd.readouterr().out


def test_a_successful_child_row_is_returned(monkeypatch, tmp_path, capfd):
    monkeypatch.setattr(iso, "_headroom_bytes", lambda: 3000 * 1024 * 1024)

    def _fake_run(argv, **kwargs):
        out = Path(argv[argv.index("--out") + 1])
        out.write_text(json.dumps({"slug": "mlb", "dashboard_games": [1, 2, 3]}), encoding="utf-8")

        class _P:
            returncode = 0
            stdout = "[overview_child] OK sport=mlb bytes=42\n"
            stderr = ""
        return _P()

    monkeypatch.setattr(iso.subprocess, "run", _fake_run)
    row, reason = iso.build_sport_overview_isolated({"slug": "mlb"}, "2026-08-28")
    assert reason == "ok"
    assert row["slug"] == "mlb"
    assert row["dashboard_games"] == [1, 2, 3]
    assert "OK sport=mlb" in capfd.readouterr().out


def test_the_cap_actually_binds_in_a_real_child(tmp_path):
    """END TO END, with a real process and a real RLIMIT_AS.

    Not a mock: the whole claim is that the OS kills the child instead of the
    parent, and only an actual `setrlimit` can demonstrate that. Asserts the
    parent SURVIVES -- if the cap leaked to the parent this test would take the
    runner down with it.
    """
    resource = pytest.importorskip("resource", reason="POSIX only; Windows dev runs uncapped")
    import subprocess

    script = tmp_path / "hog.py"
    script.write_text(
        "import resource, sys\n"
        "resource.setrlimit(resource.RLIMIT_AS, (200*1024*1024, 200*1024*1024))\n"
        "try:\n"
        "    x = bytearray(400*1024*1024)\n"
        "except MemoryError:\n"
        "    print('CAPPED'); sys.exit(4)\n"
        "print('UNCAPPED'); sys.exit(0)\n",
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 4, f"cap did not bind: rc={proc.returncode} out={proc.stdout}"
    assert "CAPPED" in proc.stdout
