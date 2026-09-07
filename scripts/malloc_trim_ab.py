"""Settle whether automatic `malloc_trim` is NET-POSITIVE on web. `#632`.

    py -3 scripts/malloc_trim_ab.py arm OFF     # after deploying with the flag 0
    py -3 scripts/malloc_trim_ab.py arm ON      # after deploying with the flag 1
    py -3 scripts/malloc_trim_ab.py compare

WHY THIS SCRIPT EXISTS RATHER THAN A NOTE. The trim was enabled in production on
2026-09-06 and its headline result was RETRACTED the same evening: the claim
"without the trims the container would have reached ~2,361 MB" was built entirely
from the intervention's own instrumentation while the intervention was running.
The counterfactual -- what the memory does with the flag OFF -- was never
observed. This runs that observation.

--------------------------------------------------------------------------
REWRITTEN 2026-09-07 AFTER `UPDATE 34`. THE ORIGINAL GATE COULD NOT WORK.
--------------------------------------------------------------------------
The first version gated on REQUEST COUNT and judged on container unreclaimable.
Both are now known to be insufficient, from a real retraction:

* `UPDATE 33` compared two arms ~50 minutes apart, passed a 14% request-count
  gate, and was retracted by `UPDATE 34` -- **47% of the difference sat in memory
  the intervention could not touch.** Request count is not WORK PER REQUEST: the
  same tally on a lighter game slate allocates far less.
* A container-level metric sums both workers and hides per-worker spread, which
  is how a two-worker difference looked conclusive twice.

So this now measures PER WORKER and carries a CONTROL TERM:

    PRIMARY   glibc arena      -- what `malloc_trim` actually returns
    CONTROL   pymalloc arenas  -- the trim CANNOT touch these. If they differ
                                  between arms, the WORKLOAD differed and no
                                  comparison of the primary is admissible.
    context   container unreclaimable, anon

The control is the whole point. It is the check that caught `UPDATE 33`, applied
here BEFORE the arms are run rather than after they are published.

WHY IT NEEDS A QUIET WINDOW. Each arm is a 12-minute settle plus a 30-minute
measurement, so the pair needs ~84 minutes with NO DEPLOY. A restart resets every
memory metric and kills the arm outright. Measured 2026-09-06: web took a deploy
roughly every 20-30 minutes through the working day, and a first attempt died
after 3.4 clean minutes. Run this overnight, or hold the `web` deploy claim for
the duration and tell the other sessions why.

THE SETTLE IS LOAD-BEARING, not caution. A fresh worker has not accumulated the
free arena space the trim returns, so a short settle produces a FALSE NEGATIVE --
"trim does not help" -- which is easy to accept because a disappointing result
feels honest.

DATA SOURCE. `growth_episodes.last_capture` on `/api/ops/memory` carries anon,
glibc and pymalloc per worker, refreshed every 15 s by the growth detector --
which is NOT the thing being toggled, so the instrument stays constant across
arms. Letting an intervention supply its own measurement is what produced the
retraction this script exists to repair.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://syndicate-an21.onrender.com"
SETTLE_MIN = 12.0
WINDOW_MIN = 30.0
CADENCE_S = 20
CONTROL_TOLERANCE = 0.10          # pymalloc may differ by this much and no more
OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "malloc_trim_ab"


def _token() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("ADMIN_TOKEN"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _get(path: str, token: str, timeout: int = 90):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("X-Admin-Token", token)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_arm(label: str) -> None:
    token = _token()
    print(f"[{label}] settling {SETTLE_MIN:.0f} min", flush=True)
    settle_end = time.time() + SETTLE_MIN * 60
    while time.time() < settle_end:
        time.sleep(20)

    print(f"[{label}] measuring {WINDOW_MIN:.0f} min", flush=True)
    rows: dict[str, list] = {}
    restarted = False
    prev: dict[str, float] = {}
    end = time.time() + WINDOW_MIN * 60
    i = 0
    while time.time() < end:
        try:
            mem = _get("/api/ops/memory", token)["memory"]
        except Exception as exc:
            print(f"  [{label}] fetch failed: {type(exc).__name__}", flush=True)
            time.sleep(CADENCE_S)
            continue
        g = mem.get("growth_episodes") or {}
        cap = g.get("last_capture") or {}
        pid = g.get("pid")
        if not pid or cap.get("pymalloc") is None or cap.get("glibc") is None:
            time.sleep(CADENCE_S)
            continue
        key = str(pid)
        anon = float(cap["anon"])
        if key in prev and anon < prev[key] * 0.5:
            restarted = True
            print(f"  [{label}] ** RESTART on pid {pid} -- this arm is INVALID", flush=True)
        prev[key] = anon
        rows.setdefault(key, []).append({
            "t": time.time(), "anon": anon,
            "glibc": float(cap["glibc"]), "pymalloc": float(cap["pymalloc"]),
            "unreclaimable": float(mem.get("container_memory_unreclaimable_mb") or 0),
            "reqs": int(g.get("requests_total") or 0),
        })
        if i % 15 == 0:
            print(f"  [{label}] pid {pid} glibc {cap['glibc']:.1f} "
                  f"pymalloc {cap['pymalloc']:.1f} anon {anon:.1f}", flush=True)
        i += 1
        time.sleep(CADENCE_S)

    arm = {"label": label, "restarted": restarted, "pids": {}}
    for pid, series in rows.items():
        if len(series) < 20:
            print(f"  pid {pid}: only {len(series)} samples -- dropped")
            continue
        arm["pids"][pid] = {
            "n": len(series),
            "glibc_mean": round(statistics.mean(s["glibc"] for s in series), 1),
            "pymalloc_mean": round(statistics.mean(s["pymalloc"] for s in series), 1),
            "anon_mean": round(statistics.mean(s["anon"] for s in series), 1),
            "unreclaimable_mean": round(statistics.mean(s["unreclaimable"] for s in series), 1),
            "unreclaimable_max": round(max(s["unreclaimable"] for s in series), 1),
            "requests": series[-1]["reqs"] - series[0]["reqs"],
        }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"arm_{label}.json"
    path.write_text(json.dumps(arm, indent=1), encoding="utf-8")
    print(f"\n[{label}] -> {path}")
    for pid, v in arm["pids"].items():
        print(f"  pid {pid:<5} n={v['n']:<4} glibc {v['glibc_mean']:>7.1f}  "
              f"pymalloc {v['pymalloc_mean']:>7.1f}  anon {v['anon_mean']:>7.1f}  "
              f"reqs {v['requests']}")
    if restarted:
        print(f"[{label}] DISCARD THIS ARM and re-run it. A restart resets every")
        print(f"[{label}] memory metric, so the window measures boot, not the flag.")


def compare() -> None:
    arms = {}
    for label in ("OFF", "ON"):
        p = OUT_DIR / f"arm_{label}.json"
        if not p.exists():
            print(f"  missing arm: {p}")
            return
        arms[label] = json.loads(p.read_text(encoding="utf-8"))

    for label, a in arms.items():
        if a.get("restarted"):
            print(f"  arm {label} saw a RESTART -- INVALID. Re-run it.")
            return
        if len(a["pids"]) < 2:
            print(f"  arm {label} has {len(a['pids'])} usable worker(s). Two workers is")
            print("  already thin; one cannot show a spread at all. Re-run it.")
            return

    def vals(label, key):
        return [v[key] for v in arms[label]["pids"].values()]

    print(f"  {'arm':<5} {'pids':<5} {'glibc':<9} {'pymalloc':<10} {'anon':<9} "
          f"{'unrecl':<9} {'reqs':<7}")
    for label in ("OFF", "ON"):
        a = arms[label]
        print(f"  {label:<5} {len(a['pids']):<5} "
              f"{statistics.mean(vals(label,'glibc_mean')):<9.1f} "
              f"{statistics.mean(vals(label,'pymalloc_mean')):<10.1f} "
              f"{statistics.mean(vals(label,'anon_mean')):<9.1f} "
              f"{statistics.mean(vals(label,'unreclaimable_mean')):<9.1f} "
              f"{sum(v['requests'] for v in a['pids'].values()):<7}")

    # ---- THE CONTROL. Checked BEFORE the primary is even printed. -----------
    off_c = statistics.mean(vals("OFF", "pymalloc_mean"))
    on_c = statistics.mean(vals("ON", "pymalloc_mean"))
    drift = abs(on_c - off_c) / max(off_c, on_c) if max(off_c, on_c) else 1.0
    print(f"\n  CONTROL -- pymalloc, which malloc_trim CANNOT touch:")
    print(f"    OFF {off_c:.1f} -> ON {on_c:.1f} MB   drift {100*drift:.1f}%")
    if drift > CONTROL_TOLERANCE:
        print(f"    THE ARMS SAW DIFFERENT WORKLOADS (>{100*CONTROL_TOLERANCE:.0f}%).")
        print("    A term the intervention cannot affect moved, so any difference in")
        print("    the primary is UNATTRIBUTABLE. This is exactly how UPDATE 33 was")
        print("    wrong -- it passed a request-count gate and failed this one.")
        return
    print("    within tolerance -- the arms are comparable on a term the trim")
    print("    cannot influence, so a difference in the primary is admissible.")

    # ---- the primary --------------------------------------------------------
    off_g, on_g = vals("OFF", "glibc_mean"), vals("ON", "glibc_mean")
    mo, mn = statistics.mean(off_g), statistics.mean(on_g)
    print(f"\n  PRIMARY -- glibc arena, what the trim returns:")
    print(f"    OFF {mo:.1f} -> ON {mn:.1f} MB   ({mn-mo:+.1f})")
    print(f"    per-worker OFF {sorted(round(v,1) for v in off_g)}  "
          f"ON {sorted(round(v,1) for v in on_g)}")
    overlap = not (max(on_g) < min(off_g) or max(off_g) < min(on_g))
    ou = statistics.mean(vals("OFF", "unreclaimable_mean"))
    nu = statistics.mean(vals("ON", "unreclaimable_mean"))
    print(f"    container unreclaimable: OFF {ou:.1f} -> ON {nu:.1f} MB ({nu-ou:+.1f})")
    print()
    if overlap:
        print("  THE PER-WORKER RANGES OVERLAP. Report a DIRECTION at most, never a")
        print("  magnitude -- two workers per arm cannot separate them, and calling a")
        print("  mean difference a result is the failure UPDATE 33 made.")
    elif mn <= mo - 25.0:
        print("  TRIM IS NET-POSITIVE: it holds the glibc arena materially lower, the")
        print("  control did not move, and the per-worker ranges are separated.")
    elif mn >= mo + 25.0:
        print("  TRIM IS NET-NEGATIVE: the arena is HIGHER with it on, and it costs")
        print("  page faults and a malloc-lock hold. Leave the flag OFF.")
    else:
        print("  NO MATERIAL DIFFERENCE (<25 MB). The trim moves memory around")
        print("  without lowering what the process holds -- so it buys nothing, and")
        print("  the flag should stay OFF.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "arm":
        collect_arm(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "compare":
        compare()
    else:
        print(__doc__)
