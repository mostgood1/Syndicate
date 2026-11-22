"""Each soccer live/fast odds run seen in live-odds-worker's process tree: pid, first/last seen, peak RSS of its subtree,
and what its subtree held at that peak. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/soccer_fast_runs.py 2026-11-21T05:00 [sports=soccer] [phase=live] [mode=fast]
"""
import collections, json, re, subprocess, sys

since = sys.argv[1][:19]
want = (sys.argv[2] if len(sys.argv) > 2 else "soccer", sys.argv[3] if len(sys.argv) > 3 else "live", sys.argv[4] if len(sys.argv) > 4 else "fast")
lines = []
for f in ("logs/live-odds-worker.log.1", "logs/live-odds-worker.log"):
    out = subprocess.run(["grep", "-a", "ALL_PROCESS_MEMORY {", f], capture_output=True, text=True, errors="replace").stdout
    lines += [l for l in out.splitlines() if re.match(r"20\d\d-", l) and l[:19] >= since]
lines.sort(key=lambda l: l[:24])


def arg(cmd, flag):
    try:
        return cmd[cmd.index(flag) + 1]
    except (ValueError, IndexError):
        return "?"


def short(cmd):
    s = " ".join(cmd)
    for c in cmd:
        m = re.search(r"([A-Za-z0-9_]+)\.py$", c)
        if m:
            extra = ""
            if "--league" in cmd:
                extra = " " + arg(cmd, "--league")
            if "--kind" in cmd:
                extra += " " + arg(cmd, "--kind")
            return m.group(1) + extra
    return arg(cmd, "-m") if "-m" in cmd else s[:40]


runs = {}
seen_samples = 0
for l in lines:
    try:
        body = json.loads(l[l.index("{"):])
    except Exception:
        continue
    procs = [p for p in body.get("processes") or [] if isinstance(p, dict) and "pid" in p]
    by_pid = {p["pid"]: p for p in procs}
    kids = collections.defaultdict(list)
    for p in procs:
        kids[p.get("ppid")].append(p["pid"])
    seen_samples += 1
    for p in procs:
        cmd = p.get("cmdline") or []
        if "refresh_odds_sources.py" not in " ".join(cmd):
            continue
        if (arg(cmd, "--sports"), arg(cmd, "--phase"), arg(cmd, "--mode")) != want:
            continue
        sub, stack = [], [p["pid"]]
        while stack:
            q = stack.pop()
            sub.append(by_pid[q])
            stack += kids.get(q, [])
        total = sum(float(x.get("rss_mb") or 0) for x in sub)
        r = runs.setdefault(p["pid"], {"first": l[:19], "last": l[:19], "peak": 0.0, "peak_at": None, "peak_sub": [], "max_n": 0})
        r["last"] = l[:19]
        r["max_n"] = max(r["max_n"], len(sub))
        if total > r["peak"]:
            r["peak"], r["peak_at"] = total, l[:19]
            r["peak_sub"] = sorted(((float(x.get("rss_mb") or 0), short(x.get("cmdline") or [])) for x in sub), reverse=True)

print("samples", seen_samples, "| %s/%s/%s runs" % want, len(runs))
for pid, r in sorted(runs.items(), key=lambda kv: kv[1]["first"]):
    span = (int(r["last"][11:13]) * 60 + int(r["last"][14:16])) - (int(r["first"][11:13]) * 60 + int(r["first"][14:16]))
    if r["peak"] < 500 and span < 10:
        continue
    print("pid %d  %s -> %s (%d min)  peak %.0f MB at %s  max procs %d" % (pid, r["first"][11:19], r["last"][11:19], span, r["peak"], r["peak_at"][11:19], r["max_n"]))
    print("     ", "; ".join("%s %.0f" % (n, m) for m, n in r["peak_sub"][:9]))
