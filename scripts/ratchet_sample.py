"""Sample refresh-worker memory for the slow RATCHET, and analyse the trough.

WHY THIS EXISTS. After the ledger fix removed the fast excursion (+2.1-2.9GB in
16-51s), a slow climb remained: 85.0% -> 90.9% unreclaimable over 10.05h on
`59c07221`, i.e. **0.59 points/hour**. A first attempt to measure that on the
next build produced -17.63, +7.39 and -0.28 pts/h in the same hour -- garbage,
for two reasons this script fixes:

1. **THE SIGNAL IS SMALLER THAN THE CYCLE.** Unreclaimable oscillates ~10 points
   within an hour as board builds allocate and release. A two-point slope over a
   sub-hour span measures which phase of the cycle the samples landed in, not the
   ratchet. **Track the TROUGH** -- the floor the process returns to between
   builds. Peaks swing; the floor is what actually ratchets, and it is what the
   original 85->90.9 figure compared.

2. **HALF THE SAMPLES WERE DROPPED SILENTLY.** The previous extractor took the
   last of 3 rows and many rows carry no `memory_unreclaimable_pct_of_max`, so
   it printed `?` and lost the point. Here every row is scanned and only rows
   that CARRY the field are used; the count of usable rows is recorded so a thin
   sample is visible rather than inferred.

Collection and analysis are separate on purpose: samples append to a CSV, and
`--analyse` can be run at any time without disturbing the watch.

    py -3 scripts/ratchet_sample.py --collect --minutes 240
    py -3 scripts/ratchet_sample.py --analyse
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import time
import urllib.request

OWNER = "tea-d2bb5n95pdvs73cje4fg"
SERVICE = "srv-d91dpertqb8s73co8ls0"
CSV = pathlib.Path("reports/ratchet/refresh_worker_ratchet.csv")
# Bucket width for the trough. Board cycles run ~60-100s, so 30 min contains many
# full cycles -- wide enough that the bucket minimum is a real floor rather than
# a lucky sample, narrow enough to see movement inside a few hours.
BUCKET_MIN = 30
PRIOR_RATE = 0.59  # pts/h on 59c07221, the figure this is compared against


def _key() -> str:
    for line in pathlib.Path(".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("RENDER_API_KEY"):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("RENDER_API_KEY not found in .env")


def _get(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def live_commit(key: str) -> str:
    d = _get(f"https://api.render.com/v1/services/{SERVICE}/deploys?limit=1", key)
    return ((d[0]["deploy"].get("commit") or {}).get("id") or "")[:8]


def killed_since(key: str, since_iso: str) -> str | None:
    rows = _get(f"https://api.render.com/v1/services/{SERVICE}/events?limit=10", key)
    for r in rows:
        e = r.get("event", r)
        reason = (e.get("details") or {}).get("reason") or {}
        if e.get("type") == "server_failed" and reason.get("oomKilled") and e.get("timestamp", "") > since_iso:
            return e["timestamp"]
    return None


def trough_from_rows(rows: list[dict]) -> tuple[float | None, int, int]:
    """(min unreclaimable_pct, usable rows, total rows). Pure -- no network.

    Split out from `sample` so the defect that made the first attempt unreadable
    is testable: the previous extractor took the LAST of 3 rows, and most rows
    carry no `memory_unreclaimable_pct_of_max`, so it silently yielded nothing
    roughly half the time. Every row is scanned here, and `usable` is returned so
    a thin batch is visible rather than inferred.

    Returns the MINIMUM, not the latest: peaks oscillate ~10 points with the
    board cycle; the floor is the quantity that ratchets.
    """
    vals: list[float] = []
    for l in rows:
        m = l.get("message", "")
        i = m.find("{")
        if i < 0:
            continue
        try:
            payload = json.loads(m[i:])
        except Exception:
            continue
        v = payload.get("memory_unreclaimable_pct_of_max") if isinstance(payload, dict) else None
        if isinstance(v, (int, float)):
            vals.append(float(v))
    return (min(vals) if vals else None), len(vals), len(rows)


def sample(key: str) -> tuple[float | None, int, int]:
    d = _get(
        "https://api.render.com/v1/logs"
        f"?ownerId={OWNER}&resource={SERVICE}&text=CONTAINER_MEMORY&limit=100",
        key,
    )
    return trough_from_rows(d.get("logs") or [])


def collect(minutes: int, boot_iso: str, interval: int = 300) -> None:
    key = _key()
    mine = live_commit(key)
    CSV.parent.mkdir(parents=True, exist_ok=True)
    if not CSV.exists():
        CSV.write_text("ts_utc,commit,uptime_h,trough_pct,usable_rows,total_rows\n", encoding="utf-8")
    boot = dt.datetime.fromisoformat(boot_iso.replace("Z", ""))
    print(f"collecting every {interval}s for {minutes} min; commit={mine} boot={boot_iso}", flush=True)
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        now = dt.datetime.utcnow()
        cur = live_commit(key)
        if cur != mine:
            print(f"STOP: commit changed {mine} -> {cur} (run invalidated)", flush=True)
            return
        k = killed_since(key, boot_iso)
        if k:
            print(f"STOP: oomKilled at {k} -- the ratchet reached the ceiling", flush=True)
            return
        trough, usable, total = sample(key)
        up = (now - boot).total_seconds() / 3600.0
        if trough is not None:
            with CSV.open("a", encoding="utf-8") as fh:
                fh.write(f"{now.isoformat()}Z,{cur},{up:.3f},{trough:.1f},{usable},{total}\n")
            print(f"  {now.strftime('%H:%M:%S')}  up={up:.2f}h  trough={trough:.1f}%  usable={usable}/{total}", flush=True)
        else:
            # SAY SO. A silent drop is what made the first attempt unreadable.
            print(f"  {now.strftime('%H:%M:%S')}  up={up:.2f}h  NO USABLE ROWS ({total} scanned)", flush=True)
        time.sleep(interval)


def analyse() -> None:
    if not CSV.exists():
        print("no samples yet"); return
    rows = [l.split(",") for l in CSV.read_text(encoding="utf-8").strip().splitlines()[1:]]
    pts = [(float(r[2]), float(r[3])) for r in rows if len(r) >= 4]
    if not pts:
        print("no usable samples"); return
    print(f"samples: {len(pts)}   span: {pts[0][0]:.2f}h -> {pts[-1][0]:.2f}h")
    buckets: dict[int, list[float]] = {}
    for up, v in pts:
        buckets.setdefault(int(up * 60 // BUCKET_MIN), []).append(v)
    print(f"\n  {BUCKET_MIN}-min bucket troughs (the floor is what ratchets):")
    mins = []
    for b in sorted(buckets):
        lo = min(buckets[b])
        mins.append((b * BUCKET_MIN / 60.0, lo))
        print(f"    t+{b*BUCKET_MIN:>4} min   trough={lo:5.1f}%   n={len(buckets[b])}")
    span = mins[-1][0] - mins[0][0]
    print()
    if span < 2.0:
        print(f"  NO RATE YET: {span:.2f}h of buckets. Against a {PRIOR_RATE} pts/h signal and")
        print(f"  ~10-point cycle oscillation, a rate needs >=2h. Reporting one now would")
        print(f"  repeat the -17.63/+7.39 pts/h garbage that made this script necessary.")
        return
    rate = (mins[-1][1] - mins[0][1]) / span
    print(f"  trough rate: {rate:+.2f} pts/h over {span:.2f}h   (prior build: +{PRIOR_RATE} pts/h)")
    if rate < PRIOR_RATE * 0.5:
        print("  -> materially SLOWER than the prior build")
    elif rate > PRIOR_RATE * 1.5:
        print("  -> FASTER than the prior build")
    else:
        print("  -> comparable to the prior build; the ratchet is independent of the ledger path")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--analyse", action="store_true")
    ap.add_argument("--minutes", type=int, default=240)
    ap.add_argument("--boot", default="2026-08-17T14:39:32Z")
    a = ap.parse_args()
    os.chdir(pathlib.Path(__file__).resolve().parents[1])
    if a.collect:
        collect(a.minutes, a.boot)
    if a.analyse or not a.collect:
        analyse()
