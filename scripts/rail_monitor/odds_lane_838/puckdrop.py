"""Per NHL game: puck drop (ESPN state flip in the in-play recorder) -> first in-game NHL odds refresh, and the parts.

Run on WSL from ~/syndicate-prod:  nice -n 19 python3 puckdrop.py [nights...]
Read-only. Sources:
  /mnt/c/tmp/inplay_<D>/espn.jsonl         ESPN scoreboard per poll, UTC receive time (puck drop truth)
  data/reports/migration_runs/*/odds_refresh_*/odds_refresh.json   step started_at / finished_at
  logs/live-odds-worker.log*               ODDS_SWEEP_LAUNCHED / REFUSED, PREGAME_CADENCE_DETAIL, SLATE_PHASE nhl
"""
import datetime as dt
import glob
import json
import os
import re
import statistics
import subprocess
import sys

UTC = dt.timezone.utc
NIGHTS = sys.argv[1:] or ["2026-11-10", "2026-11-11", "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16",
                          "2026-11-17", "2026-11-18"]


def ts(v):
    try:
        x = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=UTC)
    except Exception:
        return None


def ct(t):  # Central (CST, UTC-6, after 11-01)
    return (t - dt.timedelta(hours=6)).strftime("%H:%M:%S") if t else "-"


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


# ---------- 1. puck drops from the recorder -------------------------------------------------------
drops = []  # (night, gid, name, sched, drop, lo_bound)
cov_espn = {}
for night in NIGHTS:
    p = f"/mnt/c/tmp/inplay_{night}/espn.jsonl"
    if not os.path.exists(p):
        cov_espn[night] = "no recorder file"
        continue
    rows = {}
    first_poll = None
    polls = set()
    for line in open(p, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("sport") != "nhl":
            continue
        t = ts(r.get("ts"))
        if not t:
            continue
        polls.add(t)
        first_poll = t if first_poll is None or t < first_poll else first_poll
        rows.setdefault(r.get("id"), []).append((t, r.get("state"), r.get("name"), ts(r.get("start"))))
    pl = sorted(polls)
    gaps = [(b - a).total_seconds() for a, b in zip(pl, pl[1:])]
    n_ok = 0
    for gid, seq in rows.items():
        seq.sort()
        first_in = next((i for i, x in enumerate(seq) if x[1] == "in"), None)
        if first_in is None:
            continue
        if first_in == 0:
            drops.append((night, gid, seq[0][2], seq[0][3], None, None))  # censored: recorder started after drop
            continue
        drops.append((night, gid, seq[0][2], seq[0][3], seq[first_in][0], seq[first_in - 1][0]))
        n_ok += 1
    cov_espn[night] = f"{len(rows)} NHL games, {n_ok} drops seen, NHL poll gap p50 {q(gaps, .5) or 0:.0f}s"

# ---------- 2. manifests --------------------------------------------------------------------------
runs = {}  # stamp -> dict
for d in glob.glob("data/reports/migration_runs/2026-11-*/odds_refresh_2026111*"):
    m = re.search(r"odds_refresh_(\d{8}_\d{6})$", d)
    if not m:
        continue
    stamp = m.group(1)
    launch = dt.datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
    if launch < dt.datetime(2026, 11, 10, 12, tzinfo=UTC):
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
                steps.append((r.get("sport"), st.get("name"), a, b, bool(st.get("ok")), bool(st.get("timed_out"))))
    if not steps:
        continue
    runs[stamp] = {
        "launch": launch, "date": s.get("date") or os.path.basename(os.path.dirname(d)), "phase": s.get("phase"),
        "sports": [r.get("sport") for r in s.get("results") or []], "steps": steps,
        "end": max(x[3] for x in steps), "start": min(x[2] for x in steps),
    }
nhl_steps = sorted(
    (b, a, stamp, runs[stamp]["date"], runs[stamp]["phase"], ok)
    for stamp, r in runs.items() for (sp, name, a, b, ok, to) in r["steps"]
    if sp == "nhl" and name == "nhl_oddsapi_refresh"
)

# ---------- 3. live-odds-worker log events --------------------------------------------------------
pat = "ODDS_SWEEP_LAUNCHED|ODDS_SWEEP_REFUSED|PREGAME_CADENCE_DETAIL|SLATE_PHASE sport=nhl|MLB_LIVE_PROBE"
logs = sorted(glob.glob("logs/live-odds-worker.log*"))
cov_logs = {}
events = []
for f in logs:
    out = subprocess.run(["grep", "-aE", pat, f], capture_output=True, text=True, errors="replace").stdout
    first = last = None
    for line in out.splitlines():
        if "ALL_PROCESS_MEMORY" in line or not re.match(r"20\d\d-\d\d-\d\dT", line):
            continue
        t = ts(line[:24])
        if not t:
            continue
        first = t if first is None else first
        last = t
        if "ODDS_SWEEP_LAUNCHED" in line:
            m = re.search(r"sports=(\S+)", line)
            events.append((t, "L", m.group(1).split(",") if m else [], None))
        elif "ODDS_SWEEP_REFUSED" in line:
            m = re.search(r"sports=(\S+)", line)
            h = re.search(r'"run_stamp": "(\d{8}_\d{6})"', line)
            rc = re.search(r"reason=(\S+)", line)
            events.append((t, "R", m.group(1).split(",") if m else [], (rc.group(1) if rc else "?", h.group(1) if h else None)))
        elif "PREGAME_CADENCE_DETAIL" in line and "nhl:" in line:
            events.append((t, "D", [], None))
        elif "SLATE_PHASE sport=nhl" in line:
            m = re.search(r"from=(\S+) to=(\S+)", line)
            events.append((t, "P", [], m.groups() if m else None))
        elif "MLB_LIVE_PROBE" in line:
            events.append((t, "T", [], None))
    cov_logs[os.path.basename(f)] = (first, last)
events.sort(key=lambda e: e[0])
log_lo = min((v[0] for v in cov_logs.values() if v[0]), default=None)
log_hi = max((v[1] for v in cov_logs.values() if v[1]), default=None)

launches = [e for e in events if e[1] == "L"]
refusals = [e for e in events if e[1] == "R"]


def refused(launch_ev):
    for r in refusals:
        if 0 <= (r[0] - launch_ev[0]).total_seconds() <= 3 and r[2] == launch_ev[2]:
            return r
    return None


def lane_runs():
    """Runs that held the live-odds-worker lane: LAUNCHED (not refused) joined to a manifest by +-5 s."""
    out = []
    for ev in launches:
        if refused(ev):
            continue
        best = None
        for stamp, r in runs.items():
            dtl = abs((r["launch"] - ev[0]).total_seconds())
            if dtl <= 5 and sorted(r["sports"]) == sorted(ev[2]):
                best = r
                break
        if best:
            out.append((best["launch"], best["end"]))
    return out


LANE = lane_runs()


def lane_held_seconds(a, b):
    tot = 0.0
    for lo, hi in LANE:
        lo2, hi2 = max(lo, a), min(hi, b)
        if hi2 > lo2:
            tot += (hi2 - lo2).total_seconds()
    return min(tot, (b - a).total_seconds())


# ---------- 4. per game ---------------------------------------------------------------------------
print("COVERAGE")
for n in NIGHTS:
    print(f"  recorder {n}: {cov_espn.get(n)}")
mdates = sorted({r['date'] for r in runs.values()})
print(f"  manifests: {len(runs)} runs with steps, dates {mdates[0]}..{mdates[-1]}; NHL odds steps {len(nhl_steps)}")
for k, (a, b) in cov_logs.items():
    print(f"  {k}: {a:%m-%d %H:%MZ}..{b:%m-%d %H:%MZ}" if a else f"  {k}: empty")
print()
print("night      game          sched(CT) drop(CT) res  age@drop | first in-game refresh: start(CT) end(CT) wait | not_due held idle run | notes")
rows = []
for night, gid, name, sched, drop, lo in sorted(drops, key=lambda x: (x[0], x[4] or dt.datetime.max.replace(tzinfo=UTC))):
    if drop is None:
        print(f"{night} {name:13s} {ct(sched)} CENSORED (recorder started after the drop)")
        continue
    same = [x for x in nhl_steps if x[3] == night]
    prev = [x for x in same if x[0] <= drop and x[5]]
    nxt = [x for x in same if x[1] >= drop and x[5]]
    age = (drop - prev[-1][0]).total_seconds() if prev else None
    if not nxt:
        print(f"{night} {name:13s} {ct(sched)} {ct(drop)} no ok in-game NHL refresh for slate {night}")
        continue
    f_end, f_start, f_stamp, _, f_phase, _ = nxt[0]
    wait = (f_end - drop).total_seconds()
    R = runs[f_stamp]
    rec = {"night": night, "name": name, "drop": drop, "sched": sched, "wait": wait, "age": age, "res": (drop - lo).total_seconds(),
           "phase": f_phase, "logs": bool(log_lo and log_lo <= drop - dt.timedelta(minutes=30) and log_hi >= f_end)}
    notes = [f"run {f_stamp} {f_phase}"]
    if rec["logs"]:
        if R["launch"] < drop:
            nd, held, idle = 0.0, 0.0, 0.0
            run = wait
            notes.append("run launched before the drop")
        else:
            nhl_attempts = [e for e in launches if e[0] >= drop and "nhl" in e[2] and e[0] <= R["launch"] + dt.timedelta(seconds=5)]
            T1 = nhl_attempts[0][0] if nhl_attempts else R["launch"]
            nd = (T1 - drop).total_seconds()
            span = (R["launch"] - T1).total_seconds()
            held = lane_held_seconds(T1, R["launch"]) if span > 0 else 0.0
            idle = max(0.0, span - held)
            run = (f_end - R["launch"]).total_seconds()
            skipped_sweeps = [e for e in launches if drop <= e[0] < T1 and "nhl" not in e[2]]
            details = [e for e in events if e[1] == "D" and drop <= e[0] < T1]
            ticks = [e for e in events if e[1] == "T" and drop <= e[0] < T1]
            nref = sum(1 for e in nhl_attempts if refused(e))
            phase_live = [e for e in events if e[1] == "P" and e[3] and e[3][1] == "live" and e[0] >= drop - dt.timedelta(minutes=20)]
            notes.append(f"{len(skipped_sweeps)} sweeps w/o NHL, {len(details)} nhl cadence-skips, {len(ticks)} ticks, {nref} NHL refusals")
            if phase_live:
                notes.append(f"slate_phase live {ct(phase_live[0][0])}")
        rec.update(nd=nd, held=held, idle=idle, run=run)
        parts = f"{nd:7.0f} {held:4.0f} {idle:4.0f} {run:3.0f}"
    else:
        parts = "   (no logs)       "
    rows.append(rec)
    agetxt = f"{age:7.0f}" if age is not None else "      -"
    print(f"{night} {name:13s} {ct(sched)} {ct(drop)} {rec['res']:3.0f} {agetxt} | {ct(f_start)} {ct(f_end)} {wait:5.0f} | {parts} | {'; '.join(notes)}")

# ---------- 5. summary ----------------------------------------------------------------------------
print()
W = [r["wait"] for r in rows]
print(f"GAMES with a seen drop and an in-game refresh: {len(rows)}; wait p50 {q(W, .5):.0f}s p75 {q(W, .75):.0f}s max {max(W):.0f}s; "
      f"over 600 s {sum(1 for w in W if w > 600)}, over 900 s {sum(1 for w in W if w > 900)}")
first = {}
for r in rows:
    k = (r["night"], r["drop"].replace(second=0, microsecond=0) - dt.timedelta(minutes=r["drop"].minute % 30))
    first.setdefault(k, r)
SW = [r["wait"] for r in first.values()]
print(f"DROP SLOTS (first game per 30-min slot): {len(SW)}; wait p50 {q(SW, .5):.0f}s max {max(SW):.0f}s")
L = [r for r in rows if "nd" in r]
if L:
    tot = {k: sum(r[k] for r in L) for k in ("nd", "held", "idle", "run")}
    T = sum(tot.values())
    print(f"PARTS over {len(L)} games with logs (sum {T:.0f}s): " + ", ".join(f"{k} {v:.0f}s ({100 * v / T:.0f}%)" for k, v in tot.items()))
    for k in ("nd", "held", "idle", "run"):
        xs = [r[k] for r in L]
        print(f"  {k}: p50 {q(xs, .5):.0f}s max {max(xs):.0f}s; dominant in {sum(1 for r in L if max(('nd', 'held', 'idle', 'run'), key=lambda z: r[z]) == k)} games")
    Ls = list({(r['night'], r['drop'].replace(second=0, microsecond=0) - dt.timedelta(minutes=r['drop'].minute % 30)): r for r in L}.values())
    tot = {k: sum(r[k] for r in Ls) for k in ("nd", "held", "idle", "run")}
    T = sum(tot.values())
    print(f"PARTS over {len(Ls)} drop slots with logs (sum {T:.0f}s): " + ", ".join(f"{k} {v:.0f}s ({100 * v / T:.0f}%)" for k, v in tot.items()))
# tick cadence after drops (gaps between successive live-odds-worker launch attempts, any sport, 00:00-05:00Z)
gaps = []
for a, b in zip(launches, launches[1:]):
    if a[0].hour < 5 and b[0].hour < 5 and a[0].date() == b[0].date():
        gaps.append((b[0] - a[0]).total_seconds())
if gaps:
    print(f"LAUNCH-ATTEMPT GAPS 00-05Z (any sport, all logged nights): n {len(gaps)} p50 {q(gaps, .5):.0f}s p90 {q(gaps, .9):.0f}s max {max(gaps):.0f}s")
