"""Read-only, nice 19: (1) where the big-5 leagues keep their match history (newest files under soccer_source/epl);
(2) the latest soccer runs for unit bundesliga|2026-12-04: every step's name, rc and stdout/stderr tail, and the
12-04 recommendations file's own content summary."""
import glob, json, os, time

root = os.path.expanduser("~/syndicate-prod/data/soccer_source")
now = time.time()
files = []
for dp, _dn, fn in os.walk(os.path.join(root, "epl")):
    for f in fn:
        p = os.path.join(dp, f)
        if "/api/" in p and "recommendations" not in p:
            continue
        files.append((os.path.getmtime(p), p))
print("epl files outside api/ (newest 12) + history-like:")
for m, p in sorted(files, reverse=True)[:12]:
    print(f"  {(now - m) / 3600:7.1f} h  {os.path.relpath(p, root)}")
for m, p in sorted(files, reverse=True):
    if "match" in os.path.basename(p) or "history" in p:
        print(f"  [hist] {(now - m) / 3600:7.1f} h  {os.path.relpath(p, root)}")

base = os.path.expanduser("~/syndicate-prod/data/reports/migration_runs/2026-11-27")
hits = []
for p in sorted(glob.glob(os.path.join(base, "odds_refresh_*", "odds_refresh.json"))):
    try:
        d = json.load(open(p))
    except Exception:
        continue
    c = d.get("command") or []
    if "--soccer-leagues" in c and c[c.index("--soccer-leagues") + 1] == "bundesliga" and "--soccer-date" in c \
            and c[c.index("--soccer-date") + 1] == "2026-12-04":
        hits.append((p, d))
print("runs for bundesliga|2026-12-04 on 11-27:", len(hits), [os.path.basename(os.path.dirname(p))[13:] for p, _ in hits])
if hits:
    p, d = hits[-1]
    print("latest:", os.path.basename(os.path.dirname(p)), "rc", d.get("returnCode"))
    def walk(o, depth=0):
        if isinstance(o, dict):
            if "name" in o and ("return_code" in o or "returnCode" in o or "rc" in o):
                rc = o.get("return_code", o.get("returnCode", o.get("rc")))
                tail = str(o.get("stdout_tail") or o.get("stdoutTail") or "")[-220:].replace("\n", " | ")
                etail = str(o.get("stderr_tail") or o.get("stderrTail") or "")[-160:].replace("\n", " | ")
                print(f"   step {o['name']}: rc {rc}  stdout ..{tail}  stderr ..{etail}")
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)
    walk({k: v for k, v in d.items() if k != "failureSummary"})
rec = os.path.join(root, "bundesliga", "api", "recommendations", "recommendations_2026-12-04.json")
if os.path.exists(rec):
    r = json.load(open(rec))
    keys = sorted(r.keys()) if isinstance(r, dict) else type(r).__name__
    print("rec 12-04 keys:", keys)
    if isinstance(r, dict):
        for k in ("generated_at", "date", "count", "fixtures", "status", "reason"):
            if k in r:
                v = r[k]
                print(f"   {k}: {v if not isinstance(v, (list, dict)) else (type(v).__name__ + ' len ' + str(len(v)))}")
