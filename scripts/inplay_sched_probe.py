"""Scheduling A/B probe for the in-play recorder (lane inplay-recorder-weeknight-stalls, 2026-11-18). Read-only.

Why: the recorder runs at Windows Idle priority, and inherits memory priority 2 (of 5) from the Task Scheduler
task. On a live weeknight the host's 12 cores are saturated, and the recorder's Kalshi requests have taken
30-110 s each (11-16: 70 s at 01:24:58Z), which stalls every market at once. This probe measures, side by side,
whether a Normal-priority process making the SAME request at the SAME instant stays fast.

Run two copies (Windows), one per priority, over the live evening:

    py -3 scripts/inplay_sched_probe.py --priority idle   --out C:/tmp/inplay_sched_probe/2026-11-18 \
        --start 2026-11-18T23:30:00Z --until 2026-11-19T03:30:00Z
    py -3 scripts/inplay_sched_probe.py --priority normal --out (same) --start (same) --until (same)

`idle` = Idle class + memory priority 2 (what the nightly's recorder runs at); `normal` = Normal class + memory
priority 5. Every --period seconds, aligned to the wall clock so both copies fire in the same slot, a copy:
  * records how late it woke for the slot (scheduler lateness);
  * sends ONE recorder-shaped request (Kalshi's public /markets, `tickers=` a fixed list of --n tickers, the
    recorder's own get_json) and times it;
  * reads the host's busy share since its previous slot (GetSystemTimes; every core, every process).
Rows go to <out>/<priority>.jsonl, flushed every 60 s. Cost: 2 requests per --period on Kalshi's public endpoint
(0.2 req/s at 10 s, beside the recorder's ~0.5 req/s on a weeknight) and ~1 ms of CPU per slot.

    py -3 scripts/inplay_sched_probe.py --analyse C:/tmp/inplay_sched_probe/2026-11-18

pairs the two files by slot and prints request latency and wake lateness per host-busy bucket.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inplay_recorder import KALSHI, get_json  # noqa: E402  (the recorder's own request code)

IDLE_PRIORITY_CLASS = 0x40
NORMAL_PRIORITY_CLASS = 0x20
PROCESS_MEMORY_PRIORITY = 0  # PROCESS_INFORMATION_CLASS.ProcessMemoryPriority
# mode -> (priority class, memory priority). Memory priority 2 is what a Task Scheduler task at its default
# priority 7 hands its children (read from the nightly's pythonw on 2026-11-18); 5 is MEMORY_PRIORITY_NORMAL.
MODES = {"idle": (IDLE_PRIORITY_CLASS, 2), "normal": (NORMAL_PRIORITY_CLASS, 5)}
BUSY_BUCKETS = ((0.0, 0.80), (0.80, 0.95), (0.95, 1.01))


def _ep(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _iso(e: float) -> str:
    return datetime.fromtimestamp(e, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4] + "Z"


def set_priority(mode: str, k32=None) -> None:
    """Set this process's priority class and memory priority for `mode`. Raises if either call fails."""
    cls, mem = MODES[mode]
    if k32 is None:
        if os.name != "nt":
            if mode == "idle" and hasattr(os, "nice"):
                os.nice(19)
            return
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    h = k32.GetCurrentProcess()
    if not k32.SetPriorityClass(h, cls):
        raise SystemExit(f"could not set priority class {cls:#x}")
    info = ctypes.c_ulong(mem)
    if not k32.SetProcessInformation(h, PROCESS_MEMORY_PRIORITY, ctypes.byref(info), ctypes.sizeof(info)):
        raise SystemExit(f"could not set memory priority {mem}")


def read_priority(k32=None):
    """Read back this process's (priority class, memory priority): the start row proves which mode actually ran."""
    if k32 is None:
        if os.name != "nt":
            return None, None
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetPriorityClass.argtypes = [ctypes.c_void_p]
        k32.GetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    h = k32.GetCurrentProcess()
    info = ctypes.c_ulong(0)
    ok = k32.GetProcessInformation(h, PROCESS_MEMORY_PRIORITY, ctypes.byref(info), ctypes.sizeof(info))
    return k32.GetPriorityClass(h), (info.value if ok else None)


class HostBusy:
    """Share of all cores busy since the previous call (GetSystemTimes; kernel time includes idle)."""

    def __init__(self, times=None):
        self._times = times or self._system_times
        self._prev = self._times()

    @staticmethod
    def _system_times():
        if os.name != "nt":
            return None
        idle, kern, user = (ctypes.c_ulonglong() for _ in range(3))
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        return idle.value, kern.value, user.value

    def read(self):
        cur = self._times()
        prev, self._prev = self._prev, cur
        if cur is None or prev is None:
            return None
        di, dk, du = (c - p for c, p in zip(cur, prev))
        total = dk + du
        return round(1.0 - di / total, 4) if total > 0 else None


def next_slot(now: float, period: float) -> float:
    """The next wall-clock instant that is a whole multiple of `period` (both copies land on the same slots)."""
    return (int(now // period) + 1) * period


def pick_tickers(n: int, get=get_json) -> list[str]:
    """A fixed list of open full-game tickers, the same request shape the recorder sends."""
    for series in ("KXNBAGAME", "KXNHLGAME", "KXNCAABGAME", "KXNFLGAME", "KXNCAAFGAME"):
        try:
            d, _ = get(KALSHI + f"?series_ticker={series}&status=open&limit={n}")
        except Exception:  # noqa: BLE001
            continue
        ts = [m.get("ticker") for m in d.get("markets", []) if m.get("ticker")]
        if ts:
            return ts[:n]
    return []


def run(a, get=get_json, clock=time.time, sleep=time.sleep, busy=None, out_fh=None, perf=time.perf_counter,
        prio=read_priority) -> int:
    start = _ep(a.start) if a.start else clock()
    until = _ep(a.until)
    # Wait for --start in short chunks against the wall clock: a Windows sleep does not count time the host spends
    # suspended, so one 8-hour sleep across a Modern Standby nap would start the probe late by the nap's length.
    while clock() < start:
        sleep(min(60.0, start - clock()))
    tickers = pick_tickers(a.n, get=get)
    url = KALSHI + "?limit=100&tickers=" + ",".join(tickers)
    busy = busy or HostBusy()
    rows, last_flush = [], clock()
    fh = out_fh or open(Path(a.out) / f"{a.priority}.jsonl", "a", encoding="utf-8")
    cls, mem = prio()
    fh.write(json.dumps({"event": "start", "ts": _iso(clock()), "priority": a.priority, "pid": os.getpid(),
                         "class": cls, "memory_priority": mem, "tickers": len(tickers), "period": a.period}) + "\n")
    fh.flush()
    while clock() < until:
        slot = next_slot(clock(), a.period)
        sleep(max(0.0, slot - clock()))
        woke = clock()
        row = {"slot": _iso(slot), "late_s": round(woke - slot, 4), "host_busy": busy.read(), "prio": a.priority}
        t0 = perf()
        try:
            d, _ = get(url)
            row.update(req_s=round(perf() - t0, 4), ok=True, n=len(d.get("markets", [])))
        except Exception as e:  # noqa: BLE001
            row.update(req_s=round(perf() - t0, 4), ok=False, err=repr(e)[:200])
        rows.append(row)
        if clock() - last_flush >= 60 or clock() >= until:
            fh.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
            fh.flush()
            rows, last_flush = [], clock()
    if rows:
        fh.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    fh.write(json.dumps({"event": "stop", "ts": _iso(clock())}) + "\n")
    fh.flush()
    if out_fh is None:
        fh.close()
    return 0


def _pct(xs, q):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 4) if xs else None


def analyse(out_dir: str) -> dict:
    """Pair idle/normal rows by slot; per host-busy bucket (the normal copy's reading), latency stats per copy."""
    by = {}
    for mode in MODES:
        p = Path(out_dir) / f"{mode}.jsonl"
        by[mode] = {}
        if not p.exists():
            continue
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            if "slot" in r:
                by[mode][r["slot"]] = r
    slots = sorted(set(by["idle"]) & set(by["normal"]))
    res = {"pairs": len(slots), "idle_only": len(set(by["idle"]) - set(by["normal"])),
           "normal_only": len(set(by["normal"]) - set(by["idle"])), "buckets": {}}
    for lo, hi in BUSY_BUCKETS:
        sel = [s for s in slots if by["normal"][s].get("host_busy") is not None and lo <= by["normal"][s]["host_busy"] < hi]
        b = {"pairs": len(sel)}
        for mode in MODES:
            req = [by[mode][s]["req_s"] for s in sel]
            late = [by[mode][s]["late_s"] for s in sel]
            b[mode] = {"req_p50": _pct(req, 0.5), "req_p90": _pct(req, 0.9), "req_max": max(req) if req else None,
                       "share_req_over_10s": round(sum(1 for x in req if x > 10) / len(req), 4) if req else None,
                       "late_p90": _pct(late, 0.9), "late_max": max(late) if late else None,
                       "errors": sum(1 for s in sel if not by[mode][s].get("ok"))}
        res["buckets"][f"{lo:.2f}-{min(hi, 1.0):.2f}"] = b
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--priority", choices=sorted(MODES))
    ap.add_argument("--out")
    ap.add_argument("--start", default="", help="UTC ISO; sleep until then (at the chosen priority)")
    ap.add_argument("--until", help="UTC ISO hard stop")
    ap.add_argument("--period", type=float, default=10.0)
    ap.add_argument("--n", type=int, default=50, help="tickers per request (the recorder sends up to 200)")
    ap.add_argument("--analyse", metavar="OUT_DIR")
    a = ap.parse_args(argv)
    if a.analyse:
        print(json.dumps(analyse(a.analyse), indent=1))
        return 0
    if not (a.priority and a.out and a.until):
        ap.error("--priority, --out and --until are required to probe")
    set_priority(a.priority)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
