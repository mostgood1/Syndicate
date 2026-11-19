"""Grade lane odds-lane-sport-deadline's pre-registered live prediction over one NHL evening window.

Usage (from ~/syndicate-prod): python3 livewin.py <window_start_utc> <window_end_utc> <slate_date>
  e.g. livewin.py 2026-11-19T00:00:00Z 2026-11-19T05:00:00Z 2026-11-18

Reads only: logs/live-odds-worker.log, logs/refresh-worker.log, odds_refresh manifests, the NHL
timeout marker. Prints every count with its denominator.

Prediction (findings_2026-11-17_odds_lane_sport_deadline.md, registered 11-17 ~9:10 PM CST):
 1 max live run <= 1,200 s; 2 lane_busy <= 50% of attempts in a slow-API window;
 3 NHL_LIVE_GENERATION_COOLDOWN after a generation timeout (NHL step fast 40-90 s);
 4 NHL team odds age <= ~1,200 s during live NHL games, in-play rows not at 0-5 longer than one hold.
 Healthy API: each live generation is a deferred nhl_live_generation step and nothing times out.
"""
import datetime as dt
import glob
import json
import os
import re
import sys

W0 = dt.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
W1 = dt.datetime.fromisoformat(sys.argv[2].replace("Z", "+00:00"))
SLATE = sys.argv[3]
UTC = dt.timezone.utc


def ts(v):
    try:
        x = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=UTC)
    except Exception:
        return None


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))] if v else None


def line_time(line):
    return ts(line[:24]) if line[:4].isdigit() else None


def cst(t):
    return (t - dt.timedelta(hours=6)).strftime("%I:%M %p").lstrip("0") + " CST"


# --- 2. sweep attempts: launched vs refused lane_busy ------------------------------------------
launched, refused = [], []
for raw in (r for f in ("logs/live-odds-worker.log.1", "logs/live-odds-worker.log") if os.path.exists(f) for r in open(f, "rb")):
    if True:
        if b"ODDS_SWEEP_" not in raw:
            continue
        line = raw.decode("utf-8", "replace")
        t = line_time(line)
        if not t or not (W0 <= t < W1) or "ALL_PROCESS_MEMORY" in line:
            continue
        sm = re.search(r"sports=([a-z,]+)", line)
        sports_set = tuple(sorted((sm.group(1) if sm else "").split(",")))
        if "ODDS_SWEEP_LAUNCHED" in line:
            launched.append((t, sports_set))
        elif "ODDS_SWEEP_REFUSED" in line and "reason=lane_busy" in line:
            m = re.search(r"phase=(\w+)", line)
            refused.append((t, m.group(1) if m else "?", sports_set))
# ODDS_SWEEP_LAUNCHED is printed BEFORE launch_refresh_run (live_refresh_loop.py ~6400), so every
# attempt has a LAUNCHED line and a lane_busy refusal is a SUBSET of them (the registered measure).
att = len(launched)
print(f"window {W0:%Y-%m-%dT%H:%MZ}..{W1:%H:%MZ} ({cst(W0)}..{cst(W1)}), slate {SLATE}")
print(f"[2] sweep attempts (LAUNCHED lines) {att}: refused lane_busy {len(refused)} "
      f"({(100.0 * len(refused) / att) if att else 0:.0f}%); refused by phase "
      f"{ {p: sum(1 for _, x, _ in refused if x == p) for p in sorted({x for _, x, _ in refused})} }")
# The attempts that RAN: a LAUNCHED line with no lane_busy refusal for the same sport set within 15 s.
ran = []
for t, ss in launched:
    if not any(ss == rs and 0 <= (rt - t).total_seconds() <= 15 for rt, _, rs in refused):
        ran.append((t, ss))
launched = ran

# --- manifests in the window -------------------------------------------------------------------
runs = []
for d in glob.glob("data/reports/migration_runs/*/odds_refresh_*"):
    m = re.search(r"odds_refresh_(\d{8}_\d{6})", d)
    if not m:
        continue
    launch = dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
    if not (W0 - dt.timedelta(minutes=40) <= launch < W1):
        continue
    try:
        doc = json.load(open(os.path.join(d, "odds_refresh.json")))
    except Exception:
        continue
    s = doc["result"] if isinstance(doc.get("result"), dict) else doc
    steps = []
    for r in s.get("results") or []:
        for st in r.get("refresh_steps") or []:
            a, b = ts(st.get("started_at")), ts(st.get("finished_at"))
            if a and b:
                cmd = st.get("command") or []
                cmd = " ".join(map(str, cmd)) if isinstance(cmd, list) else str(cmd)
                mode = "fast" if "--mode fast" in cmd else ("generate" if "--mode generate" in cmd else "full")
                steps.append(dict(sport=r.get("sport"), name=st.get("name"), a=a, b=b, sec=(b - a).total_seconds(),
                                  ok=bool(st.get("ok")), to=bool(st.get("timed_out")), mode=mode))
    if not steps:
        continue
    a0 = min(x["a"] for x in steps); b1 = max(x["b"] for x in steps)
    runs.append(dict(name=os.path.basename(d), launch=launch, phase=s.get("phase"), date=s.get("date"), ok=s.get("ok"),
                     a=a0, b=b1, sec=(b1 - a0).total_seconds(), steps=steps,
                     sports=sorted({x["sport"] for x in steps})))
runs.sort(key=lambda r: r["a"])
inwin = [r for r in runs if W0 <= r["a"] < W1]
by_stamp = {r["launch"]: r for r in runs}
lane = []
lt = sorted(launched)
for i, (t, ss) in enumerate(lt):
    hit = next((r for k, r in by_stamp.items() if abs((k - t).total_seconds()) <= 5 and tuple(sorted(r["sports"])) == ss), None)
    nxt = lt[i + 1][0] if i + 1 < len(lt) else None
    lane.append(dict(t=t, run=hit, ub=(nxt - t).total_seconds() if nxt else None))
nomf = [x for x in lane if x["run"] is None]
lsec = [x["run"]["sec"] for x in lane if x["run"]]
lph = {}
for x in lane:
    if x["run"]:
        lph.setdefault(x["run"]["phase"], []).append(x["run"]["sec"])
print(f"[1] LANE sweeps launched {len(lane)}: with a manifest {len(lane) - len(nomf)}, without {len(nomf)}; "
      + "; ".join(f"{ph} n={len(v)} p50 {q(v, .5):.0f}s max {max(v):.0f}s over1200 {sum(1 for y in v if y > 1200)}" for ph, v in sorted(lph.items(), key=str)))
for x in nomf[:6]:
    print(f"     no manifest: launched {x['t']:%H:%M:%SZ}, next launch after {x['ub'] if x['ub'] is not None else 'n/a'} s (upper bound on its hold)")
for x in sorted([x for x in lane if x["run"]], key=lambda x: -x["run"]["sec"])[:3]:
    r = x["run"]; top = sorted(r["steps"], key=lambda y: -y["sec"])[:2]
    print(f"     longest lane sweep: {r['name']} {r['phase']} {r['sec']:.0f}s ok={r['ok']} " + "; ".join(f"{y['sport']}:{y['name']} {y['sec']:.0f}s" for y in top))
live = [r for r in inwin if r["phase"] == "live"]
live_nhl = [r for r in live if "nhl" in r["sports"]]

# --- 1. max live run --------------------------------------------------------------------------
lv = [r["sec"] for r in live]
print(f"[1b] ALL live-phase runs (any launcher) {len(live)} (with NHL {len(live_nhl)}): p50 {q(lv, .5) or 0:.0f}s p90 {q(lv, .9) or 0:.0f}s "
      f"max {max(lv) if lv else 0:.0f}s; over 1,200 s {sum(1 for x in lv if x > 1200)} of {len(lv)}")
for r in sorted(live, key=lambda r: -r["sec"])[:3]:
    top = sorted(r["steps"], key=lambda x: -x["sec"])[:2]
    print(f"     longest: {r['name']} {r['sec']:.0f}s ok={r['ok']} " + "; ".join(f"{x['sport']}:{x['name']} {x['sec']:.0f}s" for x in top))
allwin = [r["sec"] for r in inwin]
print(f"    all runs in window {len(inwin)}: max {max(allwin) if allwin else 0:.0f}s, over 1,800 s {sum(1 for x in allwin if x > 1800)}")

# --- healthy-API reading + 3: generation steps, timeouts, cooldown -------------------------------
gens = [(r, x) for r in live_nhl for x in r["steps"] if x["name"] == "nhl_live_generation"]
odds_steps = [(r, x) for r in live_nhl for x in r["steps"] if x["name"] == "nhl_oddsapi_refresh"]
print(f"[H] live NHL runs {len(live_nhl)}: nhl_oddsapi_refresh modes "
      f"{ {mo: sum(1 for _, x in odds_steps if x['mode'] == mo) for mo in ('fast', 'full', 'generate')} }; "
      f"nhl_live_generation steps {len(gens)}: ok {sum(1 for _, x in gens if x['ok'])}, timed out {sum(1 for _, x in gens if x['to'])}, "
      f"seconds {[round(x['sec']) for _, x in gens]}")
fast = [x["sec"] for _, x in odds_steps if x["mode"] == "fast"]
if fast:
    print(f"    NHL fast step p50 {q(fast, .5):.0f}s max {max(fast):.0f}s (n={len(fast)})")
timeouts = [(r["name"], x["sport"], x["name"], round(x["sec"])) for r in inwin for x in r["steps"] if x["to"]]
print(f"    timed-out steps in window (any sport, any phase): {len(timeouts)} {timeouts[:5]}")
died = [r["name"] for r in inwin if not r["steps"]]
marker = f"data/nhl_source/data/processed/.nhl_live_generation_timeout_{SLATE}.json"
if os.path.exists(marker):
    mt = dt.datetime.fromtimestamp(os.path.getmtime(marker), UTC)
    after = [r for r in live_nhl if mt <= r["a"] < mt + dt.timedelta(seconds=1800)]
    with_gen = [r["name"] for r in after if any(x["name"] == "nhl_live_generation" for x in r["steps"])]
    print(f"[3] timeout marker written {mt:%H:%M:%SZ} ({cst(mt)}): live NHL runs in the next 1,800 s {len(after)}, "
          f"of which ran a generation {len(with_gen)} {with_gen}")
else:
    print("[3] no timeout marker for the slate: no live generation hit its deadline (cooldown not exercised)")

# --- 4a. NHL odds age: gaps between successive ok NHL odds refreshes ----------------------------
fin = sorted(x["b"] for r in runs for x in r["steps"]
             if x["sport"] == "nhl" and x["name"] == "nhl_oddsapi_refresh" and x["ok"] and r["date"] == SLATE)
if live_nhl:
    L0, L1 = live_nhl[0]["a"], live_nhl[-1]["b"]
    pts = [t for t in fin if t <= L1]
    gaps = []
    for t0, t1 in zip(pts, pts[1:]):
        if t1 >= L0:
            gaps.append(((t1 - max(t0, L0)).total_seconds() if t0 < L0 else (t1 - t0).total_seconds(), t0, t1))
    if gaps:
        g = max(gaps, key=lambda x: x[0])
        print(f"[4a] NHL live span {L0:%H:%MZ}-{L1:%H:%MZ}: {len(gaps)} odds-refresh gaps, max {g[0]:.0f}s "
              f"({g[1]:%H:%M:%SZ}->{g[2]:%H:%M:%SZ}), over 1,200 s {sum(1 for x in gaps if x[0] > 1200)}")
else:
    print("[4a] no live NHL run in the window")

# --- 4b. NHL in-play overlay rows ---------------------------------------------------------------
builds = []
pat = re.compile(r"INPLAY_OVERLAY sport=nhl date=(\S+) rows_inplay=(\d+)")
for raw in (r for f in ("logs/refresh-worker.log.1", "logs/refresh-worker.log") if os.path.exists(f) for r in open(f, "rb")):
    if True:
        if b"INPLAY_OVERLAY sport=nhl" not in raw:
            continue
        line = raw.decode("utf-8", "replace")
        t = line_time(line)
        m = pat.search(line)
        if t and m and W0 <= t < W1 and "ALL_PROCESS_MEMORY" not in line:
            builds.append((t, int(m.group(2))))
low = [b for b in builds if b[1] <= 5]
run, longest, start = 0.0, 0.0, None
for t, n in builds:
    if n <= 5:
        start = start or t
        longest = max(longest, (t - start).total_seconds())
    else:
        start = None
nz = [n for _, n in builds if n > 0]
print(f"[4b] NHL in-play overlay builds {len(builds)}: rows_inplay <= 5 in {len(low)}; longest low stretch {longest:.0f}s; "
      f"rows when > 0: p50 {q(nz, .5) or 0} max {max(nz) if nz else 0}")
