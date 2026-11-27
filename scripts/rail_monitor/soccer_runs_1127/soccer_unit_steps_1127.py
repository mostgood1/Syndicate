"""Read-only: for each 11-27 soccer run whose unit is bundesliga|2026-12-04, its --phase / --mode and which bundesliga
steps it ran (name: rc), and when recommendations_2026-12-04.json was written relative to each run."""
import glob, json, os

base = os.path.expanduser("~/syndicate-prod/data/reports/migration_runs/2026-11-27")
for p in sorted(glob.glob(os.path.join(base, "odds_refresh_*", "odds_refresh.json"))):
    try:
        d = json.load(open(p))
    except Exception:
        continue
    c = d.get("command") or []
    arg = lambda k: c[c.index(k) + 1] if k in c else None
    if arg("--soccer-leagues") != "bundesliga" or arg("--soccer-date") != "2026-12-04":
        continue
    seen = {}
    def walk(o):
        if isinstance(o, dict):
            if "name" in o and ("return_code" in o or "returnCode" in o):
                seen[o["name"]] = o.get("return_code", o.get("returnCode"))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    bl = {k: v for k, v in seen.items() if "bundesliga" in k and "_live" not in k}
    print(os.path.basename(os.path.dirname(p))[13:], "phase", arg("--phase"), "mode", arg("--mode"), "rc", d.get("returnCode"),
          d.get("startedAt"), "->", d.get("finishedAt"), "| bundesliga steps", bl, "| total steps", len(seen))
rec = os.path.expanduser("~/syndicate-prod/data/soccer_source/bundesliga/api/recommendations/recommendations_2026-12-04.json")
print("rec 12-04 generated_at", json.load(open(rec)).get("generated_at"))
