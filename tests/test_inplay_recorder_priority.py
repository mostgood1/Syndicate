"""The in-play recorder's Windows scheduling (lane inplay-recorder-weeknight-stalls, 2026-11-18). No real priority change."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inplay_recorder as rec  # noqa: E402


class FakeK32:
    def __init__(self, cls_ok=True, info_ok=True):
        self.calls = []
        self.cls_ok, self.info_ok = cls_ok, info_ok

    def GetCurrentProcess(self):
        return -1

    def SetPriorityClass(self, h, cls):
        self.calls.append(("class", cls))
        return self.cls_ok

    def SetProcessInformation(self, h, klass, ptr, size):
        self.calls.append(("memory", klass, ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ulong)).contents.value, size))
        return self.info_ok


def test_normal_and_idle_reach_different_calls():
    # Reachability (off != on): normal must not be the old Idle call under another name.
    normal, idle = FakeK32(), FakeK32()
    rec.set_priority("normal", k32=normal)
    rec.set_priority("idle", k32=idle)
    assert normal.calls == [("class", 0x20), ("memory", 0, 5, 4)]
    assert idle.calls == [("class", 0x40)]  # memory priority left as the task handed it down: the old behaviour


@pytest.mark.parametrize("mode,cls_ok,info_ok", [("normal", False, True), ("normal", True, False), ("idle", False, True)])
def test_a_failed_call_stops_the_recorder(mode, cls_ok, info_ok):
    # 2026-10-21: the Idle call failed silently (truncated HANDLE) and every recorder ran at Normal unnoticed.
    with pytest.raises(SystemExit):
        rec.set_priority(mode, k32=FakeK32(cls_ok=cls_ok, info_ok=info_ok))


class _Stop(Exception):
    pass


@pytest.mark.parametrize("extra,expected", [([], "normal"), (["--priority", "idle"], "idle")])
def test_main_applies_the_priority_first(monkeypatch, tmp_path, extra, expected):
    seen = []

    def fake_set_priority(mode, k32=None):
        seen.append(mode)
        raise _Stop

    monkeypatch.setattr(rec, "set_priority", fake_set_priority)
    monkeypatch.setattr(sys, "argv", ["inplay_recorder.py", "--date", "2026-11-19", "--out", str(tmp_path),
                                      "--until", "2026-11-19T00:00:00Z", *extra])
    with pytest.raises(_Stop):
        rec.main()
    assert seen == [expected]
    assert list(tmp_path.iterdir()) == []  # nothing opened, nothing polled before the priority is set


def test_unknown_priority_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["inplay_recorder.py", "--date", "2026-11-19", "--out", str(tmp_path),
                                      "--until", "2026-11-19T00:00:00Z", "--priority", "high"])
    with pytest.raises(SystemExit):
        rec.main()
