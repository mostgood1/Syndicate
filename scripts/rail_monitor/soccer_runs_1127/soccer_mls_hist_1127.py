"""Read-only: the latest 11-27 run that carried MLS steps -- each mls step's name, rc, and stdout/stderr tail -- to see
why mls/history/matches_2026.csv was last written 10-07 while no mls history step ever failed."""
import glob, json, os

base = os.path.expanduser("~/syndicate-prod/data/reports/migration_runs/2026-11-27")
latest = None
for p in sorted(glob.glob(os.path.join(base, "odds_refresh_*", "odds_refresh.json"))):
    try:
        d = json.load(open(p))
    except Exception:
        continue
    c = d.get("command") or []
    if "soccer_mls_history" in json.dumps(d) or "soccer_mls_artifacts" in json.dumps(d):
        latest = (p, d)
if not latest:
    print("no mls run on 11-27")
else:
    p, d = latest
    print("run", os.path.basename(os.path.dirname(p)), "rc", d.get("returnCode"), "cmd", " ".join((d.get("command") or [])[3:]))
    seen = {}
    def walk(o):
        if isinstance(o, dict):
            if "name" in o and "mls" in str(o["name"]) and ("return_code" in o or "returnCode" in o):
                seen[o["name"]] = o
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    for name, o in seen.items():
        print(f"  {name}: rc {o.get('return_code', o.get('returnCode'))}")
        for k in ("command", "stdout_tail", "stderr_tail", "stdoutTail", "stderrTail"):
            if o.get(k):
                v = o[k] if isinstance(o[k], str) else " ".join(map(str, o[k]))
                print(f"     {k}: ..{v[-360:]}".replace("\n", " | "))
