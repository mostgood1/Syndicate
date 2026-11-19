"""Read-only fleet metrics for one rail-monitor reading window. Prints one JSON object.

Usage (WSL, nice 19): python3 d4metrics.py <start ISO Z, e.g. 2026-11-18T18:33> [today YYYY-MM-DD]
Reads only the tail of each role log, plus the odds-refresh manifests. Writes nothing.
"""
import collections, datetime as dt, glob, json, os, re, statistics as st, subprocess, sys

S = sys.argv[1]
TODAY = sys.argv[2] if len(sys.argv) > 2 else dt.datetime.utcnow().strftime("%Y-%m-%d")
E = sys.argv[3] if len(sys.argv) > 3 else "9999"
LOGS = os.path.expanduser("~/syndicate-prod/logs")
out = {"start": S}


def tail_lines(name, nbytes):
    p = os.path.join(LOGS, name)
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            f.seek(max(0, size - nbytes))
            data = f.read().decode("utf-8", "replace").splitlines()[1:]
    except OSError:
        return [], False
    covered = bool(data) and data[0][:16] <= S
    if not covered and os.path.exists(p + ".1"):
        try:
            size1 = os.path.getsize(p + ".1")
            with open(p + ".1", "rb") as f:
                f.seek(max(0, size1 - nbytes))
                prev = f.read().decode("utf-8", "replace").splitlines()[1:]
            covered = bool(prev) and prev[0][:16] <= S
            data = prev + data
        except OSError:
            pass
    return [l for l in data if S[:19] <= l[:19] < E[:19]], covered


def ts(line):
    try:
        return dt.datetime.fromisoformat(line[:19])
    except ValueError:
        return None


def num(rx, line):
    m = re.search(rx, line)
    return float(m.group(1)) if m else None


try:
    la = open("/proc/loadavg").read().split()
    out["host_load1"] = float(la[0]) if E == "9999" else None
except Exception:
    out["host_load1"] = None

rw, rw_cov = tail_lines("refresh-worker.log", 25_000_000)
lo, lo_cov = tail_lines("live-odds-worker.log", 30_000_000)
web, web_cov = tail_lines("web.log", 20_000_000)
out["log_window_covered"] = bool(rw_cov and lo_cov and web_cov)

# board builds
walls = []
pub_ts = []
for l in rw:
    if "BOARD_BUILD_TIMING" in l:
        w = num(r"wall_s=([0-9.]+)", l)
        if w is not None:
            walls.append(w)
            t = ts(l)
            if t:
                pub_ts.append(t)
pgaps = [(b - a).total_seconds() for a, b in zip(pub_ts, pub_ts[1:])]
out["board_pub_gap_max_s"] = round(max(pgaps)) if pgaps else None
out["board_pub_gap_median_s"] = round(st.median(pgaps)) if pgaps else None
cad = [num(r"elapsed_s=([0-9.]+)", l) for l in rw if "LAYER2_TODAY_CADENCE" in l and "ran=yes" in l]
cad = [c for c in cad if c is not None]
out["today_cadence_step_max_s"] = round(max(cad)) if cad else None
out["board_builds"] = len(walls)
out["board_wall_median_s"] = round(st.median(walls), 1) if walls else None
out["board_wall_max_s"] = round(max(walls), 1) if walls else None
out["board_over_300"] = sum(1 for w in walls if w > 300)
spans = [num(r"elapsed_s=([0-9.]+)", l) for l in rw if "BUILD_SPAN_EXIT stage=layer2_shortlist_build" in l]
spans = [x for x in spans if x is not None]
out["shortlist_span_max_s"] = round(max(spans), 1) if spans else None
out["deferred_board_builds"] = sum(1 for l in rw if "DEFERRED_BOARD_BUILD" in l)

# ticks
tick_ts, deferred = [], 0
for l in rw:
    if "BOOK_GRID_TICK " in l:
        t = ts(l)
        if t:
            tick_ts.append(t)
        try:
            j = json.loads(l.split("BOOK_GRID_TICK ", 1)[1])
            if j.get("deferred_slow"):
                deferred += 1
        except Exception:
            pass
gaps = [(b - a).total_seconds() for a, b in zip(tick_ts, tick_ts[1:])]
out["ticks"] = len(tick_ts)
out["tick_gap_max_s"] = round(max(gaps), 1) if gaps else None
out["deferred_slow_ticks"] = deferred

# overlay
last, gmax, over = {}, collections.defaultdict(float), collections.Counter()
for l in rw:
    m = re.search(r"INPLAY_OVERLAY sport=(\w+)", l)
    if not m:
        continue
    sp, t = m.group(1), ts(l)
    if t is None:
        continue
    if sp in last:
        g = (t - last[sp]).total_seconds()
        gmax[sp] = max(gmax[sp], g)
        if g > 360:
            over[sp] += 1
    last[sp] = t
out["overlay_gap_max_s"] = round(max(gmax.values()), 1) if gmax else None
out["overlay_gap_max_sport"] = max(gmax, key=gmax.get) if gmax else None
out["overlay_gaps_over_360"] = sum(over.values())
out["overlay_over_360_by_sport"] = dict(over)

# web merges
merges, stale = 0, collections.Counter()
for l in web:
    if "INPLAY_OVERLAY_MERGED" in l:
        merges += 1
        for sp, _v in re.findall(r"'(\w+)': '(stale_\d+s)'", l):
            stale[sp] += 1
out["web_merges"] = merges
out["web_merges_stale"] = sum(stale.values())
out["web_stale_by_sport"] = dict(stale)

# sweeps
launched = sum(1 for l in lo if "ODDS_SWEEP_LAUNCHED" in l)
refused = [l for l in lo if "ODDS_SWEEP_REFUSED" in l]
out["sweeps_launched"] = launched
out["sweeps_refused"] = len(refused)
out["sweeps_refused_pct"] = round(100.0 * len(refused) / (launched + len(refused)), 1) if (launched + len(refused)) else None
out["refused_reasons"] = dict(collections.Counter(re.findall(r"reason=([a-z_]+)", " ".join(refused))))
out["nhl_generation_markers"] = sum(1 for l in lo if re.search(r"NHL_(LIVE|PREGAME)_GENERATION", l))
out["nhl_generation_cooldowns"] = sum(1 for l in lo if "NHL_LIVE_GENERATION_COOLDOWN" in l)

# odds children now
try:
    ps = subprocess.run(["ps", "-eo", "etimes,args"], capture_output=True, text=True, timeout=20).stdout.splitlines()
except Exception:
    ps = []
kids = []
for row in ps:
    parts = row.strip().split(None, 1)
    if len(parts) < 2:
        continue
    if re.search(r"refresh_\w*oddsapi\w*\.py|refresh_odds_sources\.py", parts[1]):
        kids.append((int(parts[0]), "nhl" if "nhl" in parts[1] else "other"))
out["odds_child_max_age_s"] = max((k[0] for k in kids), default=0) if E == "9999" else None
out["nhl_child_max_age_s"] = max((k[0] for k in kids if k[1] == "nhl"), default=0) if E == "9999" else None


# odds-refresh manifests
def rt(a, b):
    try:
        return (dt.datetime.fromisoformat(b.replace("Z", "+00:00")) - dt.datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds()
    except Exception:
        return None


runs = []
for d in glob.glob("/home/amyn/syndicate-prod/data/reports/migration_runs/2026-1[12]-*/odds_refresh_*"):
    try:
        j = json.load(open(d + "/odds_refresh.json"))
    except Exception:
        continue
    s = j.get("startedAt")
    if not s or s < S or s >= E:
        continue
    res = j.get("result") or {}
    by = collections.defaultdict(float)
    for r in res.get("results") or []:
        for stp in (r.get("refresh_steps") or []):
            x = rt(stp.get("started_at") or "", stp.get("finished_at") or "")
            if x:
                by[r.get("sport", "?")] += x
    dur = rt(s, j.get("finishedAt") or "")
    date = res.get("date") or "?"
    runs.append({"phase": res.get("phase"), "lookahead": date > TODAY, "dur": dur, "soccer": by.get("soccer"), "by": dict(by)})
live = [r["dur"] for r in runs if r["phase"] == "live" and r["dur"]]
pre = [r["dur"] for r in runs if r["phase"] == "pregame" and not r["lookahead"] and r["dur"]]
la_ = [r for r in runs if r["phase"] == "pregame" and r["lookahead"] and r["dur"]]
out["live_runs"] = len(live)
out["live_run_p50_s"] = round(st.median(live)) if live else None
out["live_run_max_s"] = round(max(live)) if live else None
out["pregame_runs"] = len(pre)
out["pregame_run_max_s"] = round(max(pre)) if pre else None
out["lookahead_runs"] = len(la_)
out["lookahead_max_s"] = round(max(r["dur"] for r in la_)) if la_ else None
out["lookahead_soccer_max_s"] = round(max((r["soccer"] or 0) for r in la_)) if la_ else None

try:
    out["fleet_head"] = subprocess.run(["git", "-C", os.path.expanduser("~/Syndicate"), "rev-parse", "--short=9", "HEAD"],
                                       capture_output=True, text=True, timeout=20).stdout.strip()
except Exception:
    out["fleet_head"] = None

print(json.dumps(out))
