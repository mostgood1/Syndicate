"""#851 P6 (R-D): read the fleet's OddsAPI quota counter and append one line to C:\\tmp\\railmon\\p851_quota.jsonl.

  py -3 C:\\tmp\\railmon\\p851_quota.py <label>      (run from the worktree so `scripts/_base_url.py` imports)
Prints and appends {read_at, label, used, ...} with only numeric fields: never the token, never a header.
"""
import datetime as dt
import json
import os
import sys
import urllib.request

sys.path.insert(0, "scripts")
from _base_url import admin_token  # noqa: E402

BASE = "http://127.0.0.1:10000"
label = sys.argv[1] if len(sys.argv) > 1 else ""
req = urllib.request.Request(BASE + "/api/ops/oddsapi/quota", headers={"X-Admin-Token": admin_token(BASE)})
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read().decode("utf-8"))
q = d.get("quota") if isinstance(d.get("quota"), dict) else d
latest = q.get("latest") if isinstance(q.get("latest"), dict) else {}
out = {"read_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "label": label,
       "used": latest.get("used"), "remaining": latest.get("remaining"), "observedAt": latest.get("observedAt"),
       "credits_per_hour": q.get("credits_per_hour"), "projected_30d_credits": q.get("projected_30d_credits")}
assert isinstance(out["used"], int), "quota.latest.used missing"
line = json.dumps(out)
with open(r"C:\tmp\railmon\p851_quota.jsonl", "a", encoding="utf-8") as f:
    f.write(line + "\n")
print(line)
