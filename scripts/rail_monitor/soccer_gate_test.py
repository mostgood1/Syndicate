"""Test: are the soccer live-lens False ticks the low_headroom gate, and what in live-odds-worker's process tree fills it? Read-only.

For every `live_lens_tick_before_soccer` ALL_PROCESS_MEMORY sample on live-odds-worker since a UTC time, rebuilds the
ROLE's process tree (root = run_live_odds_refresh_worker.py, every descendant by ppid), labels each process, and joins
the sample to the tick's soccer verdict (TICK_COMPLETE) and to any `LIVE_LENS_TICK_DIAG sport=soccer` line in between.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/soccer_gate_test.py 2026-11-21T05:00
"""
import collections, json, re, statistics as st, subprocess, sys

since = sys.argv[1][:19]
until = sys.argv[2][:19] if len(sys.argv) > 2 else "9999"
pat = r"ALL_PROCESS_MEMORY \{|live_lens_loop\] TICK_COMPLETE|LIVE_LENS_TICK_DIAG\] sport=soccer|LIVE_ODDS_WORKER_MEMORY"
lines = []
for f in ("logs/live-odds-worker.log.1", "logs/live-odds-worker.log"):
    out = subprocess.run(["grep", "-a", "-E", pat, f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        if re.match(r"20\d\d-\d\d-\d\dT", l) and since <= l[:19] <= until:
            lines.append(l)
lines.sort(key=lambda l: l[:24])


def arg(cmd, flag):
    try:
        return cmd[cmd.index(flag) + 1]
    except (ValueError, IndexError):
        return "?"


def label_of(p):
    cmd = p.get("cmdline") or []
    s = " ".join(cmd)
    if "run_live_odds_refresh_worker.py" in s:
        return "worker"
    if "live_resim_workers" in s:
        return "resim_worker"
    if "refresh_odds_sources.py" in s:
        return "odds_run:%s/%s/%s" % (arg(cmd, "--sports"), arg(cmd, "--phase"), arg(cmd, "--mode"))
    if "run_refresh_odds_job.py" in s:
        return "odds_job_wrapper"
    for c in cmd:
        m = re.search(r"([A-Za-z0-9_]+)\.py$", c)
        if m:
            return m.group(1)
    if "-m" in cmd:
        return arg(cmd, "-m")
    return (p.get("name") or "?")


def tree(procs):
    by_pid = {p["pid"]: p for p in procs if isinstance(p, dict) and "pid" in p}
    roots = [p for p in by_pid.values() if "run_live_odds_refresh_worker.py" in " ".join(p.get("cmdline") or [])]
    if not roots:
        return None
    root = roots[0]["pid"]
    kids = collections.defaultdict(list)
    for p in by_pid.values():
        kids[p.get("ppid")].append(p["pid"])
    out, stack = [], [(root, None)]
    while stack:
        pid, run = stack.pop()
        p = by_pid[pid]
        lab = label_of(p)
        if lab.startswith("odds_run:"):
            run = lab
        out.append((pid, lab, run, float(p.get("rss_mb") or 0)))
        for k in kids.get(pid, []):
            stack.append((k, run))
    return out


samples = []  # dicts
pending = None
diag = None
for l in lines:
    if "ALL_PROCESS_MEMORY {" in l:
        try:
            body = json.loads(l[l.index("{"):])
        except Exception:
            continue
        if body.get("stage") != "live_lens_tick_before_soccer":
            continue
        t = tree(body.get("processes") or [])
        if t is None:
            continue
        pending = {"at": l[:19], "container_mb": body.get("container_memory_mb"), "tree": t}
        diag = None
    elif "LIVE_LENS_TICK_DIAG] sport=soccer" in l and pending is not None:
        m = re.search(r"reason=(\w+)", l)
        h = re.search(r"'headroom_mb': (-?[0-9.]+)", l)
        diag = (m.group(1) if m else "?", float(h.group(1)) if h else None)
    elif "TICK_COMPLETE" in l and pending is not None:
        m = re.search(r"'soccer': (True|False)", l)
        if m:
            pending["soccer"] = m.group(1) == "True"
            pending["diag"] = diag
            pending["tick_at"] = l[:19]
            samples.append(pending)
        pending, diag = None, None

false = [s for s in samples if not s["soccer"]]
true = [s for s in samples if s["soccer"]]
print("window", since, "->", until, "| soccer ticks joined to a before_soccer sample:", len(samples), "True", len(true), "False", len(false))
print("False with soccer low_headroom DIAG:", sum(1 for s in false if s["diag"] and s["diag"][0] == "low_headroom"),
      "| False with other DIAG:", sum(1 for s in false if s["diag"] and s["diag"][0] != "low_headroom"),
      "| False with NO DIAG:", sum(1 for s in false if not s["diag"]),
      "| True with a DIAG:", sum(1 for s in true if s["diag"]))


def tot(s):
    return sum(r for _, _, _, r in s["tree"])


def worker_rss(s):
    return sum(r for _, lab, _, r in s["tree"] if lab == "worker")


def group(s):
    g = collections.Counter()
    for _, lab, run, r in s["tree"]:
        if lab == "worker":
            g["worker"] += r
        elif lab == "resim_worker":
            g["resim_workers"] += r
        elif run:
            g[run] += r
        else:
            g[lab] += r
    return g


for name, ss in (("True", true), ("False", false)):
    if ss:
        print("%-5s tree MB median %.0f min %.0f max %.0f | worker alone median %.0f max %.0f | container_mb median %.0f" % (
            name, st.median(map(tot, ss)), min(map(tot, ss)), max(map(tot, ss)),
            st.median(map(worker_rss, ss)), max(map(worker_rss, ss)), st.median(float(s["container_mb"] or 0) for s in ss)))

# runs of consecutive False
runs, cur = [], []
for s in samples:
    if not s["soccer"]:
        cur.append(s)
    elif cur:
        runs.append(cur)
        cur = []
if cur:
    runs.append(cur)
print()
print("False runs (CST = UTC-6):")
for r in runs:
    g = collections.defaultdict(list)
    for s in r:
        for k, v in group(s).items():
            g[k].append(v)
    top = sorted(((max(v), k, len(v)) for k, v in g.items() if k != "worker"), reverse=True)[:6]
    print("  %s -> %s  ticks %d  tree median %.0f  worker max %.0f  | %s" % (
        r[0]["at"][11:16], r[-1]["at"][11:16], len(r), st.median(map(tot, r)), max(map(worker_rss, r)),
        ", ".join("%s %.0f (%d/%d)" % (k, m, n, len(r)) for m, k, n in top)))

# presence of each group in False vs True samples
print()
print("group present in: False share | True share | median MB when present (False / True)")
keys = set()
for s in samples:
    keys.update(group(s))
rows = []
for k in keys:
    if k == "worker":
        continue
    fv = [group(s)[k] for s in false if group(s)[k] > 0]
    tv = [group(s)[k] for s in true if group(s)[k] > 0]
    rows.append((len(fv) / max(1, len(false)), k, len(tv) / max(1, len(true)), st.median(fv) if fv else 0, st.median(tv) if tv else 0))
for fs, k, ts, fm, tm in sorted(rows, reverse=True)[:14]:
    print("  %-48s %5.2f | %5.2f | %6.0f / %6.0f" % (k[:48], fs, ts, fm, tm))
