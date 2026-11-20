"""#853 first-evening readout: P1-P6 of `.syndicate/findings_2026-11-19_board_read_cold_share.md`, graded.
READ-ONLY; run at nice 19 from `~/syndicate-prod` on the fleet.

    cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/<path>/p853_readout.py \
        <base_from_utc> <base_to_utc> <after_from_utc> <after_to_utc>

Each argument is UTC, `YYYY-MM-DDTHH:MM:SS`. 5-11 PM CST is 23:00Z to 05:00Z the next day. The BASELINE is the same
window on the last evening before the load; AFTER is the first live evening after it. The user's decision, on
2026-11-20, to who reads it: "Rail monitor takes it".

It runs `coldread_attrib.py` (same directory) on both windows, reads the web log's recycle and shared-copy lines,
and prints one verdict per prediction, as registered:
  LOAD CHECK  >= 1 COMBINED_BOARD_SHARED_ARMED, >= 1 PUBLISHED, 0 OFF in AFTER. Anything else is VOID.
  CONFOUNDED  < 30 queries in either window, or a gunicorn master start ("Starting gunicorn" / "Listening at")
              inside AFTER. A restart, drain or deploy lands as one.
  P1 cold share (board_read > 2 s)          <= 25% PREDICTED   > 30% FALSIFIED
  P2 new-worker first-read share of queries <= 20% PREDICTED   > 25% FALSIFIED
  P3 fresh-worker penalty IN AFTER           <= 1,500 ms PREDICTED  > 2,500 ms FALSIFIED (restated 11-20, before any load)
     = query total p50 of queries that ADOPTED a shared copy - total p50 of warm queries that touched no shared
     marker, both from the SAME evening, so evening-level load cancels. Baseline penalty (boot_cold - warm) was
     5.3 s on 11-18, 3.0 s on 11-19 and 3.8 s on 11-17. Whole-evening p50 / p90 is printed as EXPLORATORY only: two
     PRE-LOAD evenings differ by x0.72 / x0.67, so it cannot separate the fix from the evening.
  P4 SHARED_ADOPTED load_s p50               <= 1.5 s PREDICTED > 2.5 s FALSIFIED
  P5 builds per hour vs baseline            <= 0.75x PREDICTED > 0.9x FALSIFIED
     baseline = warmer rebuilds + cold queries; after = COMBINED_BOARD_SHARED_BUILD lines. After also counts other
     routes' builds, which baseline does not, so the comparison is conservative.
  P6 SAFETY recycles/h <= 1.3x AND anon p50 at recycle <= 1.1x: OK. Both above: ROLL BACK (switch off at the next
     down/up). One above: WATCH.
Anything between PREDICTED and FALSIFIED is NEITHER. Count only lines that START with a timestamp: ALL_PROCESS_MEMORY
lines quote grep command lines.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def attrib(a: str, b: str) -> dict:
    out = subprocess.run([sys.executable, os.path.join(HERE, "coldread_attrib.py"), a, b],
                         capture_output=True, text=True, errors="replace").stdout
    return json.loads(out.splitlines()[0])


def grep(pattern: str, a: str, b: str) -> list[str]:
    lines = []
    for path in sorted(glob.glob("logs/web.log*")):
        out = subprocess.run(["grep", "-a", "-E", pattern, path], capture_output=True, text=True,
                             errors="replace").stdout
        for line in out.splitlines():
            if "ALL_PROCESS_MEMORY" in line or not line[:4].isdigit():
                continue
            if a <= line[:19] < b:
                lines.append(line)
    return sorted(set(lines))


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


def recycles(a: str, b: str) -> dict:
    anon = []
    for line in grep(r"WEB_WORKER_MEMORY_RECYCLE \{", a, b):
        try:
            anon.append(float(json.loads(line[line.index("{"):]).get("anon_mb")))
        except Exception:  # noqa: BLE001
            continue
    return {"n": len(anon), "anon_p50": q(anon, .5)}


def hours(a: str, b: str) -> float:
    from datetime import datetime
    fmt = "%Y-%m-%dT%H:%M:%S"
    return max((datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds() / 3600.0, 1e-9)


def band(value, predicted_max, falsified_above):
    if value is None:
        return "NO DATA"
    if value <= predicted_max:
        return "PREDICTED"
    if value > falsified_above:
        return "FALSIFIED"
    return "NEITHER"


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    ba, bb, aa, ab = (x[:19] for x in argv[1:5])
    base, after = attrib(ba, bb), attrib(aa, ab)
    rb, ra = recycles(ba, bb), recycles(aa, ab)
    hb, ha = hours(ba, bb), hours(aa, ab)

    def marker(name):
        return grep(r"COMBINED_BOARD_SHARED_" + name + " ", aa, ab)

    armed, published, off = marker("ARMED"), marker("PUBLISHED"), marker("OFF")
    adopted, build = marker("ADOPTED"), marker("BUILD")
    pub_failed, read_failed, sstale = marker("PUBLISH_FAILED"), marker("READ_FAILED"), marker("SERVED_STALE")
    load_s = [float(m.group(1)) for line in adopted for m in [re.search(r"load_s=([0-9.]+)", line)] if m]
    master_starts = grep(r"Starting gunicorn|Listening at:", aa, ab)

    load_ok = len(armed) >= 1 and len(published) >= 1 and len(off) == 0
    confounded = []
    if base["queries"] < 30 or after["queries"] < 30:
        confounded.append(f"queries base {base['queries']} / after {after['queries']} (< 30)")
    if master_starts:
        confounded.append(f"{len(master_starts)} gunicorn master start line(s) in AFTER (a restart)")

    n_after = after["queries"] or 1
    p1 = 100.0 * after["cold"][0] / n_after
    p2 = 100.0 * after["class"].get("boot_cold", [0])[0] / n_after
    bp50, bp90 = base["all_total_p50_p90_ms"]
    ap50, ap90 = after["all_total_p50_p90_ms"]
    r50, r90 = (ap50 / bp50 if bp50 else None), (ap90 / bp90 if bp90 else None)
    pen_base = (base.get("fresh_worker_penalty_ms") or {}).get("cold")
    pen_after = (after.get("fresh_worker_penalty_ms") or {}).get("adopted")
    n_adopted = (after.get("fresh_worker_penalty_ms") or {}).get("n_adopted", 0)
    p3 = band(pen_after, 1500, 2500)
    p4v = q(load_s, .5)
    builds_base = (base["warmer_rebuilds"] + base["cold"][0]) / hb
    builds_after = len(build) / ha
    p5r = builds_after / builds_base if builds_base else None
    rec_rate_r = (ra["n"] / ha) / (rb["n"] / hb) if rb["n"] else None
    anon_r = (ra["anon_p50"] / rb["anon_p50"]) if (ra["anon_p50"] and rb["anon_p50"]) else None
    above = [x for x in ((rec_rate_r, 1.3), (anon_r, 1.1)) if x[0] is not None and x[0] > x[1]]
    p6 = "ROLL BACK" if len(above) == 2 else ("WATCH" if above else "OK")

    def v(verdict):
        return verdict if load_ok else f"VOID (would read {verdict})"

    def f(x, d=2):
        return "n/a" if x is None else f"{x:.{d}f}"

    print(f"#853 readout  base {ba}..{bb}Z  after {aa}..{ab}Z")
    print(f"LOAD CHECK: {'MET' if load_ok else 'VOID'} (ARMED {len(armed)}, PUBLISHED {len(published)}, OFF {len(off)}; "
          f"PUBLISH_FAILED {len(pub_failed)}, READ_FAILED {len(read_failed)}, SERVED_STALE {len(sstale)}, ADOPTED {len(adopted)})")
    print(f"CONFOUNDED: {'; '.join(confounded) if confounded else 'no'}")
    print("| # | metric | baseline | after | verdict |")
    print("|---|---|---|---|---|")
    bq = base["queries"] or 1
    print(f"| P1 | cold share | {100.0 * base['cold'][0] / bq:.1f}% ({base['cold'][0]}/{base['queries']}) | "
          f"{p1:.1f}% ({after['cold'][0]}/{after['queries']}) | {v(band(p1, 25, 30))} |")
    print(f"| P2 | new-worker first-read share | {100.0 * base['class'].get('boot_cold', [0])[0] / bq:.1f}% | {p2:.1f}% | "
          f"{v(band(p2, 20, 25))} |")
    print(f"| P3 | fresh-worker penalty ms (same evening) | {f(pen_base, 0)} (cold) | {f(pen_after, 0)} "
          f"(adopted, n {n_adopted}) | {v(p3)} |")
    print(f"| P4 | adopt load_s p50 | n/a | {f(p4v)} (n {len(load_s)}) | {v(band(p4v, 1.5, 2.5))} |")
    print(f"| P5 | builds per hour | {builds_base:.1f} | {builds_after:.1f} (x{f(p5r)}) | "
          f"{v(band(p5r, 0.75, 0.9))} |")
    print(f"| P6 | SAFETY recycles/h, anon p50 at recycle | {rb['n'] / hb:.1f}/h, {f(rb['anon_p50'], 0)} MB | "
          f"{ra['n'] / ha:.1f}/h (x{f(rec_rate_r)}), {f(ra['anon_p50'], 0)} MB (x{f(anon_r)}) | {v(p6)} |")
    print(f"| EXPLORATORY | query p50 / p90 ms, whole evening | {bp50} / {bp90} | {ap50} / {ap90} "
          f"(x{f(r50)} / x{f(r90)}) | not graded |")
    if not load_ok:
        print("VOID: the switch did not arm or publish in AFTER; every P above describes the old behaviour.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
