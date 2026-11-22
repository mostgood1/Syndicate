"""#851 P6: the fleet's OddsAPI quota endpoint's SHAPE, and any time-stamped 'used' samples near a UTC instant. Read-only.
Prints keys and numeric fields only (never a token or header).

  py -3 C:\\tmp\\railmon\\p851_quota_history.py 2026-11-22T05:00   (run from the worktree)
"""
import datetime as dt, json, sys, urllib.request

sys.path.insert(0, "scripts")
from _base_url import admin_token  # noqa: E402

BASE = "http://127.0.0.1:10000"
at = sys.argv[1] if len(sys.argv) > 1 else None
req = urllib.request.Request(BASE + "/api/ops/oddsapi/quota", headers={"X-Admin-Token": admin_token(BASE)})
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read().decode("utf-8"))
q = d.get("quota") if isinstance(d.get("quota"), dict) else d


def shape(o, path="", depth=0):
    if depth > 3:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, (dict, list)):
                print("%s%s: %s(%d)" % ("  " * depth, path + k, type(v).__name__, len(v)))
                shape(v, path + k + ".", depth + 1)
            elif isinstance(v, (int, float, bool)) or v is None or (isinstance(v, str) and len(v) < 40 and "token" not in k.lower()):
                print("%s%s = %r" % ("  " * depth, path + k, v))
    elif isinstance(o, list) and o:
        print("%s[0] of %d:" % ("  " * depth, len(o)))
        shape(o[0], path + "[0].", depth + 1)


shape(q)
# any list of samples with a time and a 'used'
for k, v in q.items():
    if isinstance(v, list) and v and isinstance(v[0], dict):
        tk = next((c for c in ("observedAt", "observed_at", "at", "ts", "time") if c in v[0]), None)
        uk = next((c for c in ("used", "requests_used", "x_requests_used") if c in v[0]), None)
        if tk and uk and at:
            near = sorted(v, key=lambda s: abs((dt.datetime.fromisoformat(str(s[tk]).replace("Z", "+00:00"))
                                                - dt.datetime.fromisoformat(at + "+00:00")).total_seconds()))[:3]
            print("samples in", k, "nearest", at, ":", [(s[tk], s[uk]) for s in near])
            ts = sorted(str(s[tk]) for s in v)
            print("  span", ts[0], "->", ts[-1], "n", len(v))
