"""Settle whether automatic `malloc_trim` is NET-POSITIVE on web. `#632`.

WHY THIS SCRIPT EXISTS RATHER THAN A NOTE. The trim was enabled in production on
2026-09-06 and its headline result was RETRACTED the same evening: the claim
"without the trims the container would have reached ~2,361 MB" was built entirely
from the intervention's own instrumentation while the intervention was running.
The counterfactual -- what the memory does with the flag OFF -- was never
observed. This runs that observation.

    py -3 scripts/malloc_trim_ab.py arm OFF <golive-ts>     # after deploying with the flag 0
    py -3 scripts/malloc_trim_ab.py arm ON  <golive-ts>     # after deploying with the flag 1
    py -3 scripts/malloc_trim_ab.py compare

THE DECISION METRIC IS CONTAINER UNRECLAIMABLE -- its level and its peak. NOT the
trim's own reported savings. Those savings are exactly the numbers that produced
the retracted claim.

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

KNOWN CONFOUND, stated up front: the arms are SEQUENTIAL, not interleaved, so
traffic drift between them is not controlled. Interleaving would need four
deploys. Each arm therefore records its REQUEST VOLUME, and `compare` REFUSES to
call a winner when the arms differ by more than 25% -- a normalisation chosen
after seeing the data is not a control.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://syndicate-an21.onrender.com"
SETTLE_MIN = 12.0
WINDOW_MIN = 30.0
CADENCE_S = 20
VOLUME_TOLERANCE = 0.25
OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "malloc_trim_ab"


def _token() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("ADMIN_TOKEN"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _get(path: str, token: str, timeout: int = 60):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("X-Admin-Token", token)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_arm(label: str, golive_ts: str) -> None:
    token = _token()
    golive = time.mktime(time.strptime(golive_ts, "%Y-%m-%dT%H:%M:%S")) - time.timezone
    print(f"[{label}] settling {SETTLE_MIN:.0f} min from {golive_ts}", flush=True)
    while (time.time() - golive) / 60.0 < SETTLE_MIN:
        time.sleep(20)

    print(f"[{label}] measuring {WINDOW_MIN:.0f} min", flush=True)
    samples = []
    restarted = False
    prev_total = None
    end = time.time() + WINDOW_MIN * 60
    while time.time() < end:
        try:
            mem = _get("/api/ops/memory", token)["memory"]
        except Exception as exc:
            # A run of failures is the 502 window of somebody's deploy.
            print(f"  [{label}] fetch failed: {type(exc).__name__}", flush=True)
            time.sleep(CADENCE_S)
            continue
        total = float(mem.get("container_memory_mb") or 0)
        if prev_total is not None and total < prev_total * 0.5:
            restarted = True
            print(f"  [{label}] ** RESTART DETECTED mid-window -- this arm is INVALID",
                  flush=True)
        prev_total = total
        samples.append({
            "t": time.time(),
            "unreclaimable": float(mem.get("container_memory_unreclaimable_mb") or 0),
            "total": total,
        })
        time.sleep(CADENCE_S)

    volume = 0
    try:
        from scripts import read_render_logs  # type: ignore
    except Exception:
        read_render_logs = None
    if read_render_logs is not None:
        try:
            volume = read_render_logs.solo_request_volume("web", golive_ts)
        except Exception:
            volume = 0

    unre = [s["unreclaimable"] for s in samples]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "label": label, "golive": golive_ts, "restarted_mid_window": restarted,
        "n": len(samples),
        "span_min": (samples[-1]["t"] - samples[0]["t"]) / 60.0 if len(samples) > 1 else 0.0,
        "unreclaimable": {
            "first": unre[0] if unre else None, "last": unre[-1] if unre else None,
            "min": min(unre) if unre else None, "max": max(unre) if unre else None,
            "mean": round(sum(unre) / len(unre), 1) if unre else None,
        },
        "solo_requests": volume,
        "samples": samples,
    }
    out = OUT_DIR / f"arm_{label}.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"[{label}] n={len(samples)}  mean {payload['unreclaimable']['mean']}  "
          f"max {payload['unreclaimable']['max']}  restarted={restarted}")
    print(f"[{label}] -> {out}")
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
        if a.get("restarted_mid_window"):
            print(f"  arm {label} had a RESTART mid-window -- INVALID. Re-run it.")
            return
        if a["n"] < 30:
            print(f"  arm {label} has only {a['n']} samples -- too few. Re-run it.")
            return

    off, on = arms["OFF"], arms["ON"]
    print(f"  {'arm':>4} {'n':>4} {'mean':>9} {'max':>9} {'first':>9} {'last':>9} {'requests':>9}")
    for label, a in (("OFF", off), ("ON", on)):
        u = a["unreclaimable"]
        print(f"  {label:>4} {a['n']:>4} {u['mean']:>9.1f} {u['max']:>9.1f} "
              f"{u['first']:>9.1f} {u['last']:>9.1f} {a['solo_requests']:>9}")

    vo, vn = off["solo_requests"], on["solo_requests"]
    if vo and vn:
        skew = abs(vn - vo) / max(vo, vn)
        print(f"\n  request-volume skew between arms: {100.0 * skew:.0f}%")
        if skew > VOLUME_TOLERANCE:
            print(f"  ARMS ARE NOT COMPARABLE (>{100 * VOLUME_TOLERANCE:.0f}% apart).")
            print("  Reported as INCONCLUSIVE rather than adjusted: a normalisation")
            print("  chosen after seeing the data is not a control.")
            return
    else:
        print("\n  request volume unavailable for at least one arm -- the traffic")
        print("  confound cannot be checked, so any difference is UNATTRIBUTABLE.")
        return

    d_mean = on["unreclaimable"]["mean"] - off["unreclaimable"]["mean"]
    d_max = on["unreclaimable"]["max"] - off["unreclaimable"]["max"]
    print(f"\n  ON minus OFF:  mean {d_mean:+.1f} MB   peak {d_max:+.1f} MB")
    print()
    if d_mean <= -50.0 and d_max <= -50.0:
        print("  TRIM IS NET-POSITIVE: it holds both the average and the peak lower.")
    elif d_mean >= 50.0 or d_max >= 50.0:
        print("  TRIM IS NET-NEGATIVE: memory is no lower with it on, and it costs")
        print("  page faults and a malloc-lock hold. Leave the flag OFF.")
    else:
        print("  NO MATERIAL DIFFERENCE (<50 MB either way). The trim moves memory")
        print("  around without lowering what the container holds -- so it buys")
        print("  nothing, and the flag should stay OFF.")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "arm" and len(sys.argv) == 4:
        collect_arm(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2 and sys.argv[1] == "compare":
        compare()
    else:
        print(__doc__)
