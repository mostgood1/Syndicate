"""Tests for scripts/inplay_sched_probe.py (lane inplay-recorder-weeknight-stalls). No network, no real priority change."""

from __future__ import annotations

import ctypes
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inplay_sched_probe as probe  # noqa: E402


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
        value = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ulong)).contents.value
        self.calls.append(("info", klass, value, size))
        return self.info_ok


def test_idle_and_normal_reach_different_calls():
    # Reachability: the two modes must not be the same call (off != on).
    idle, normal = FakeK32(), FakeK32()
    probe.set_priority("idle", k32=idle)
    probe.set_priority("normal", k32=normal)
    assert idle.calls == [("class", 0x40), ("info", 0, 2, 4)]
    assert normal.calls == [("class", 0x20), ("info", 0, 5, 4)]
    assert idle.calls != normal.calls


@pytest.mark.parametrize("cls_ok,info_ok", [(False, True), (True, False)])
def test_set_priority_fails_loudly(cls_ok, info_ok):
    # The recorder's Idle call once failed SILENTLY for months (2026-10-21); a probe that did not apply its
    # priority would compare two identical copies and read as "priority does not matter".
    with pytest.raises(SystemExit):
        probe.set_priority("normal", k32=FakeK32(cls_ok=cls_ok, info_ok=info_ok))


def test_read_priority_reads_back_class_and_memory_priority():
    class K:
        def GetCurrentProcess(self):
            return -1

        def GetPriorityClass(self, h):
            return 0x20

        def GetProcessInformation(self, h, klass, ptr, size):
            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ulong)).contents.value = 5
            return True

    assert probe.read_priority(k32=K()) == (0x20, 5)


def test_host_busy_share():
    seq = iter([(100, 200, 50), (130, 300, 150)])  # idle, kernel (incl. idle), user
    hb = probe.HostBusy(times=lambda: next(seq))
    # d_idle 30 over d_kernel + d_user 200 -> 85% busy
    assert hb.read() == pytest.approx(0.85)


def test_host_busy_unavailable_is_none():
    hb = probe.HostBusy(times=lambda: None)
    assert hb.read() is None


def test_next_slot_is_shared_across_copies():
    assert probe.next_slot(1000.0, 10.0) == 1010.0
    assert probe.next_slot(1003.7, 10.0) == 1010.0
    assert probe.next_slot(1009.99, 10.0) == 1010.0


class FakeClock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


def test_run_records_slots_lateness_latency_and_errors():
    clock = FakeClock(1_000.0)
    perf_t = [0.0]
    calls = []

    def get(url):
        calls.append(url)
        if "series_ticker" in url:
            return {"markets": [{"ticker": "KXNBAGAME-A"}, {"ticker": "KXNBAGAME-B"}]}, {}
        n = len(calls)
        perf_t[0] += 0.25 if n != 3 else 42.0  # the second slot's request is slow
        clock.t += 0.25 if n != 3 else 42.0
        if n == 4:
            raise OSError("timed out")
        return {"markets": [{"ticker": "KXNBAGAME-A"}]}, {}

    busy = iter([0.5, 0.99, 0.97, 0.4, 0.4, 0.4, 0.4, 0.4])
    fh = io.StringIO()
    a = SimpleNamespace(start="", until="1970-01-01T00:18:20Z", n=2, period=10.0, priority="idle", out="unused")
    rc = probe.run(a, get=get, clock=clock, sleep=clock.sleep, busy=SimpleNamespace(read=lambda: next(busy)),
                   out_fh=fh, perf=lambda: perf_t[0], prio=lambda: (0x40, 2))
    assert rc == 0
    rows = [json.loads(x) for x in fh.getvalue().splitlines()]
    assert rows[0]["event"] == "start" and rows[0]["tickers"] == 2
    assert rows[0]["class"] == 0x40 and rows[0]["memory_priority"] == 2
    assert rows[-1]["event"] == "stop"
    slots = [r for r in rows if "slot" in r]
    assert calls[1].endswith("tickers=KXNBAGAME-A,KXNBAGAME-B")
    assert slots[0]["slot"] == "1970-01-01T00:16:50.00Z" and slots[0]["late_s"] == 0.0
    assert slots[1]["req_s"] == 42.0 and slots[1]["ok"] is True
    # After a 42 s request the copy skips the slots it missed (00:17:00..00:17:40) and takes the next one on time.
    assert slots[2]["slot"] == "1970-01-01T00:17:50.00Z" and slots[2]["late_s"] == 0.0
    assert slots[2]["ok"] is False and "timed out" in slots[2]["err"] and slots[2]["req_s"] == 0.25
    assert [s["slot"][14:19] for s in slots] == ["16:50", "17:00", "17:50", "18:00", "18:10", "18:20"]
    assert [s["host_busy"] for s in slots] == [0.5, 0.99, 0.97, 0.4, 0.4, 0.4]


def test_run_sleeps_until_start():
    clock = FakeClock(0.0)
    fh = io.StringIO()
    a = SimpleNamespace(start="1970-01-01T00:01:40Z", until="1970-01-01T00:01:40Z", n=1, period=10.0,
                        priority="normal", out="unused")
    probe.run(a, get=lambda u: ({"markets": []}, {}), clock=clock, sleep=clock.sleep,
              busy=SimpleNamespace(read=lambda: None), out_fh=fh, prio=lambda: (0x20, 5))
    assert clock.t == 100.0
    assert [json.loads(x)["event"] for x in fh.getvalue().splitlines()] == ["start", "stop"]


def _write(p: Path, rows):
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_analyse_pairs_by_slot_and_buckets_by_host_busy(tmp_path):
    slots = [f"2026-11-19T00:00:{i:02d}.00Z" for i in range(0, 60, 10)]
    busy = [0.5, 0.6, 0.97, 0.99, 0.98, 0.85]
    idle_req = [0.2, 0.3, 12.0, 45.0, 4.0, 0.4]
    normal_req = [0.2, 0.2, 0.3, 0.4, 0.3, 0.2]
    _write(tmp_path / "idle.jsonl", [{"event": "start"}] + [
        {"slot": s, "late_s": 0.01, "host_busy": b, "req_s": r, "ok": True} for s, b, r in zip(slots, busy, idle_req)])
    _write(tmp_path / "normal.jsonl", [
        {"slot": s, "late_s": 0.001, "host_busy": b, "req_s": r, "ok": True} for s, b, r in zip(slots[:-1], busy, normal_req)])
    res = probe.analyse(str(tmp_path))
    assert res["pairs"] == 5 and res["idle_only"] == 1 and res["normal_only"] == 0
    hot = res["buckets"]["0.95-1.00"]
    assert hot["pairs"] == 3
    assert hot["idle"]["req_max"] == 45.0 and hot["idle"]["share_req_over_10s"] == pytest.approx(2 / 3, abs=1e-4)
    assert hot["normal"]["req_max"] == 0.4 and hot["normal"]["share_req_over_10s"] == 0.0
    assert res["buckets"]["0.00-0.80"]["pairs"] == 2


def test_main_requires_probe_args():
    with pytest.raises(SystemExit):
        probe.main(["--priority", "idle"])
