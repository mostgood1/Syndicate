"""Web worker anon growth past the first board build, and what a higher recycle limit would do.

Lane `web-recycle-anon-limit` (todo #853 lead, 2026-11-20). READ-ONLY. Stdlib only, so it runs
under the fleet's system python3 in WSL at nice 19, from anywhere:

    nice -n 19 python3 web_anon_curve.py extract --logs ~/syndicate-prod/logs --out /mnt/c/tmp/wral/x
    nice -n 19 python3 web_anon_curve.py report  --out /mnt/c/tmp/wral/x [--from 2026-11-17T23:00:00 --to ...]

`extract` streams the logs once and writes compact files; `report` reads only those.

WHAT IT READS
- web.log*: gunicorn `Booting worker with pid`, `Worker exiting`, `WORKER TIMEOUT`; the guard's
  `WEB_MEMORY_GUARD_ARMED` / `WEB_WORKER_MEMORY_RECYCLE` / `..._DEFERRED`; the first combined-board
  call (`COMBINED_BOARD_OVERLAY_WARMER_STARTED pid=`); `GROWTH_EPISODE`.
- live-odds-worker.log*: `ALL_PROCESS_MEMORY`, which lists EVERY fleet process (pid, ppid, cmdline,
  rss_mb) every few seconds. The gunicorn workers are the gunicorn-cmdline processes whose parent
  is also a gunicorn-cmdline process. That is the only per-worker time series on the fleet.
  Every line also carries `accounted_rss_mb` (sum of all processes' RSS; shared pages counted
  more than once), which is the fleet total this script reports.

RSS vs ANON. The guard recycles on `RssAnon`; the series is RSS (= anon + file + shmem). The
report calibrates the offset at each recycle (guard anon vs the last RSS sample before it).

Lines are matched on the emitter text and the timestamp prefix, never on a bare word: the
`ALL_PROCESS_MEMORY` line quotes every process's cmdline, including any grep that happens to run.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z ")
BOOT_RE = re.compile(r"\[INFO\] Booting worker with pid: (\d+)")
EXIT_RE = re.compile(r"\[INFO\] Worker exiting \(pid: (\d+)\)")
TIMEOUT_RE = re.compile(r"\[CRITICAL\] WORKER TIMEOUT \(pid:(\d+)\)")
# gunicorn `--max-requests` (the fleet's GUNICORN_CMD_ARGS sets 1000, jitter 100): "[<ts>] [<pid>] [INFO] Autorestarting ..."
MAXREQ_RE = re.compile(r"\[(\d+)\] \[INFO\] Autorestarting worker after current request")
WARMER_RE = re.compile(r"\[intelligence_state\] COMBINED_BOARD_OVERLAY_WARMER_STARTED pid=(\d+)")
MASTER_RE = re.compile(r"\[INFO\] (Starting gunicorn|Listening at|Handling signal: \w+)")
JSON_MARKERS = (
    "WEB_MEMORY_GUARD_ARMED",
    "WEB_WORKER_MEMORY_RECYCLE_DEFERRED",
    "WEB_WORKER_MEMORY_RECYCLE",
    "GROWTH_EPISODE",
    "WEB_WORKER_DRAINED",
)


def _ts(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ordered(paths: list[str]) -> list[str]:
    """web.log.2, web.log.1, web.log -- oldest first."""
    def key(p: str) -> int:
        tail = p.rsplit(".log", 1)[1]
        return -int(tail[1:]) if tail.startswith(".") and tail[1:].isdigit() else 0
    return sorted(paths, key=key)


def extract(logs: str, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    events = []
    for path in _ordered(glob.glob(os.path.join(logs, "web.log*"))):
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                m = TS_RE.match(line)
                if not m:
                    continue
                t = _ts(m.group(1))
                body = line[m.end():]
                for marker in JSON_MARKERS:
                    if body.startswith(marker + " {"):
                        try:
                            payload = json.loads(body[len(marker) + 1:])
                        except ValueError:
                            break
                        events.append({"t": t, "ev": marker, **payload})
                        break
                else:
                    for ev, rx in (("BOOT", BOOT_RE), ("EXIT", EXIT_RE), ("TIMEOUT", TIMEOUT_RE), ("MAXREQ", MAXREQ_RE), ("WARMER", WARMER_RE)):
                        mm = rx.search(body)
                        if mm and (ev != "WARMER" or body.startswith("[intelligence_state]")):
                            events.append({"t": t, "ev": ev, "pid": int(mm.group(1))})
                            break
                    else:
                        mm = MASTER_RE.search(body)
                        if mm and body.startswith("["):
                            events.append({"t": t, "ev": "MASTER", "what": mm.group(1)})
    with open(os.path.join(out, "web_events.jsonl"), "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")

    series = open(os.path.join(out, "worker_rss.tsv"), "w", encoding="utf-8")
    fleet = open(os.path.join(out, "fleet.tsv"), "w", encoding="utf-8")
    fleet.write("t\taccounted_mb\tweb_mb\tweb_workers_mb\tboard_child_mb\trefresh_mb\tlive_odds_mb\tredis_mb\tother_mb\tn\n")
    seen = set()
    for path in _ordered(glob.glob(os.path.join(logs, "live-odds-worker.log*"))):
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                m = TS_RE.match(line)
                if not m or not line[m.end():].startswith("ALL_PROCESS_MEMORY {"):
                    continue
                t = round(_ts(m.group(1)), 1)
                if int(t) in seen:  # several emitters print the same snapshot within ms
                    continue
                seen.add(int(t))
                try:
                    payload = json.loads(line[m.end() + len("ALL_PROCESS_MEMORY "):])
                except ValueError:
                    continue
                procs = payload.get("processes") or []
                gun = {p["pid"]: p for p in procs if any("gunicorn" in str(a) for a in (p.get("cmdline") or [])[:3])}
                sums = defaultdict(float)
                for p in procs:
                    cmd = " ".join(str(a) for a in (p.get("cmdline") or []))
                    rss = float(p.get("rss_mb") or 0)
                    if p["pid"] in gun:
                        sums["web"] += rss
                        if p.get("ppid") in gun:
                            sums["web_workers"] += rss
                            series.write(f"{t}\t{p['pid']}\t{p.get('ppid')}\t{rss}\n")
                    elif "board_build_process" in cmd:
                        sums["board"] += rss
                    elif "run_refresh_worker.py" in cmd:
                        sums["refresh"] += rss
                    elif "run_live_odds_refresh_worker.py" in cmd:
                        sums["live"] += rss
                    elif "redis-server" in cmd:
                        sums["redis"] += rss
                    else:
                        sums["other"] += rss
                fleet.write(
                    f"{t}\t{payload.get('accounted_rss_mb')}\t{sums['web']:.1f}\t{sums['web_workers']:.1f}\t{sums['board']:.1f}\t"
                    f"{sums['refresh']:.1f}\t{sums['live']:.1f}\t{sums['redis']:.1f}\t{sums['other']:.1f}\t{len(procs)}\n"
                )
    series.close()
    fleet.close()
    print(f"extract: {len(events)} web events, {len(seen)} memory snapshots -> {out}", flush=True)


# ---------------------------------------------------------------- report

def pct(values, q):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def load(out: str):
    events = [json.loads(x) for x in open(os.path.join(out, "web_events.jsonl"), encoding="utf-8")]
    rss = defaultdict(list)
    for row in open(os.path.join(out, "worker_rss.tsv"), encoding="utf-8"):
        t, pid, _ppid, mb = row.split("\t")
        rss[int(pid)].append((float(t), float(mb)))
    fleet = []
    with open(os.path.join(out, "fleet.tsv"), encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for row in fh:
            parts = row.rstrip("\n").split("\t")
            rec = {}
            for k, v in zip(header, parts):
                try:
                    rec[k] = float(v)
                except ValueError:
                    rec[k] = None
            fleet.append(rec)
    return events, rss, fleet


def workers(events):
    w = defaultdict(dict)
    for e in events:
        pid = e.get("pid")
        if pid is None:
            continue
        rec = w[pid]
        ev = e["ev"]
        if ev == "BOOT":
            rec.setdefault("boot", e["t"])
        elif ev == "WEB_MEMORY_GUARD_ARMED":
            rec.setdefault("armed", e["t"])
            rec["limit"] = e.get("anon_limit_mb")
        elif ev == "WARMER":
            rec.setdefault("board", e["t"])
        elif ev == "WEB_WORKER_MEMORY_RECYCLE":
            rec["recycle"] = e
        elif ev == "WEB_WORKER_MEMORY_RECYCLE_DEFERRED":
            rec.setdefault("deferred", []).append(e)
        elif ev == "GROWTH_EPISODE":
            rec.setdefault("growth", []).append(e)
        elif ev == "EXIT":
            rec.setdefault("exit", e["t"])
        elif ev == "TIMEOUT":
            rec["timeout"] = e["t"]
    return {pid: r for pid, r in w.items() if "boot" in r or "armed" in r}


def _evening(t: float) -> bool:
    """5-11 PM CST (UTC-6), the window every #853 reading uses."""
    return 17 <= datetime.fromtimestamp(t - 6 * 3600, tz=timezone.utc).hour < 23


def report(out: str, t_from: float | None, t_to: float | None, bins: list[int], full_mb: float,
           limits: list[int], model_mb: float) -> dict:
    events, rss, fleet = load(out)
    ws = workers(events)
    in_window = lambda t: t is not None and (t_from is None or t >= t_from) and (t_to is None or t < t_to)
    res: dict = {"window": [_iso(t_from) if t_from else None, _iso(t_to) if t_to else None], "full_board_mb": full_mb}

    # 1. RSS - anon offset at recycle (guard anon vs the last RSS sample <= 15 s before it).
    offsets = []
    for pid, r in ws.items():
        rc = r.get("recycle")
        if not rc or not in_window(rc["t"]) or pid not in rss:
            continue
        before = [(t, mb) for t, mb in rss[pid] if rc["t"] - 15 <= t <= rc["t"]]
        if before:
            offsets.append(before[-1][1] - rc["anon_mb"])
    res["rss_minus_anon_at_recycle_mb"] = {"n": len(offsets), "p10": pct(offsets, .1), "p50": pct(offsets, .5), "p90": pct(offsets, .9)}
    off = pct(offsets, .5) or 0.0

    # 2. Trajectories from the first sample at which the worker HOLDS THE FULL BOARD (anon-eq >= full_mb).
    #    `WARMER_STARTED` is the first combined-board call of ANY key (a sport-filtered call too), so it
    #    is not used as the origin: many such workers never exceed ~600 MB.
    traj = []
    for pid, series in rss.items():
        series = sorted(series)
        crossed = [t for t, mb in series if mb - off >= full_mb]
        if not crossed or not in_window(crossed[0]):
            continue
        tf = crossed[0]
        traj.append({"pid": pid, "evening": _evening(tf), "post": [(t - tf, mb - off) for t, mb in series if t >= tf]})
    res["workers_holding_full_board"] = {"n": len(traj), "evening": sum(1 for x in traj if x["evening"])}

    def curve(sel):
        rows = []
        for i, b in enumerate(bins):
            e = bins[i + 1] if i + 1 < len(bins) else float("inf")
            meds, peaks = [], []
            for x in traj:
                if not sel(x):
                    continue
                vals = [a for dt, a in x["post"] if b <= dt < e]
                if vals:
                    meds.append(statistics.median(vals))
                    peaks.append(max(vals))
            if meds:
                rows.append({"from_s": b, "n": len(meds), "median_p10": pct(meds, .1), "median_p50": pct(meds, .5),
                             "median_p90": pct(meds, .9), "peak_p90": pct(peaks, .9), "peak_max": pct(peaks, 1)})
        return rows

    def paired(sel):
        rows = []
        for lo, hi in ((180, 300), (300, 600), (600, 900), (900, 1200), (1200, 3600), (3600, float("inf"))):
            d = []
            for x in traj:
                if not sel(x):
                    continue
                a = [v for dt, v in x["post"] if 60 <= dt < 180]
                b = [v for dt, v in x["post"] if lo <= dt < hi]
                if a and b:
                    d.append(statistics.median(b) - statistics.median(a))
            if d:
                rows.append({"window_s": [lo, hi], "n": len(d), "p10": pct(d, .1), "p50": pct(d, .5), "p90": pct(d, .9), "max": pct(d, 1)})
        return rows

    def hazard(sel):
        rows = []
        for L in limits:
            for w0, w1 in ((0, 120), (120, 600), (600, float("inf")), (0, float("inf"))):
                cross, expo = 0, 0.0
                for x in traj:
                    if not sel(x) or any(a >= L for dt, a in x["post"] if dt < w0):
                        continue
                    inwin = [(dt, a) for dt, a in x["post"] if w0 <= dt < w1]
                    if not inwin:
                        continue
                    hit = [dt for dt, a in inwin if a >= L]
                    cross += 1 if hit else 0
                    expo += (hit[0] if hit else inwin[-1][0]) - w0
                rows.append({"limit_mb": L, "window_s": [w0, w1], "crossings": cross, "worker_h": round(expo / 3600, 2),
                             "per_worker_h": round(cross / (expo / 3600), 2) if expo else None})
        return rows

    for name, sel in (("evening", lambda x: x["evening"]), ("not_evening", lambda x: not x["evening"])):
        res[f"curve_{name}"] = curve(sel)
        res[f"paired_growth_{name}"] = paired(sel)
        res[f"crossing_hazard_{name}"] = hazard(sel)

    # 3. Recycles in window.
    rcs = [r["recycle"] for r in ws.values() if r.get("recycle") and in_window(r["recycle"]["t"])]
    lo_t = t_from or min(e["t"] for e in events)
    hi_t = t_to or max(e["t"] for e in events)
    hours = (hi_t - lo_t) / 3600
    res["recycles"] = {"n": len(rcs), "per_h": round(len(rcs) / hours, 1) if hours else None, "hours": round(hours, 2),
                       "hard": sum(1 for x in rcs if x.get("hard")),
                       "anon_p10_p50_p90": [pct([x["anon_mb"] for x in rcs], q) for q in (.1, .5, .9)],
                       "age_p50": pct([x["age_s"] for x in rcs], .5), "limit_p50": pct([x["limit_mb"] for x in rcs], .5),
                       "max_requests_restarts": sum(1 for e in events if e["ev"] == "MAXREQ" and in_window(e["t"])),
                       "worker_timeouts": sum(1 for e in events if e["ev"] == "TIMEOUT" and in_window(e["t"]))}

    # 4. Fleet memory, observed and with both web workers at `model_mb` anon (+ the RSS offset) whenever lower.
    fw = [f for f in fleet if in_window(f["t"])]
    web_model = 2 * (model_mb + off)
    def dist(vals):
        return {"p50": pct(vals, .5), "p90": pct(vals, .9), "p99": pct(vals, .99), "max": pct(vals, 1)}
    res["fleet"] = {"n_snapshots": len(fw), "web_workers_model_mb": round(web_model),
                    **{k: dist([f[k] for f in fw if f.get(k) is not None]) for k in
                       ("accounted_mb", "web_workers_mb", "board_child_mb", "refresh_mb", "live_odds_mb", "redis_mb", "other_mb")},
                    "accounted_mb_counterfactual": dist([f["accounted_mb"] - f["web_workers_mb"] + max(f["web_workers_mb"], web_model)
                                                         for f in fw if f.get("accounted_mb") is not None and f.get("web_workers_mb") is not None])}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("--logs", default=os.path.expanduser("~/syndicate-prod/logs"))
    ex.add_argument("--out", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--out", required=True)
    rp.add_argument("--from", dest="t_from")
    rp.add_argument("--to", dest="t_to")
    rp.add_argument("--bins", default="0,60,120,300,600,900,1200,1800,2700,3600,7200")
    rp.add_argument("--full-mb", type=float, default=850.0, help="anon-eq at which a worker holds the full board")
    rp.add_argument("--limits", default="900,1000,1100,1200,1300,1400,1500")
    rp.add_argument("--model-mb", type=float, default=1060.0, help="per-worker anon when both hold the board")
    args = ap.parse_args(argv)
    if args.cmd == "extract":
        extract(args.logs, args.out)
        return 0
    res = report(args.out, _ts(args.t_from) if args.t_from else None, _ts(args.t_to) if args.t_to else None,
                 [int(x) for x in args.bins.split(",")], args.full_mb, [int(x) for x in args.limits.split(",")], args.model_mb)
    json.dump(res, sys.stdout, indent=1, default=str)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
