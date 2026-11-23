"""Read-only: live-book orders whose matchup/event matches a substring.

Usage: py -3 live_bets_for.py <substring> [<substring> ...]
Reads /api/portfolio/live?on=all&show=all on the fleet with the ops token (never printed).
Prints each matching order's own fields minus anything token-like.
"""
import json
import sys
import urllib.request

sys.path.insert(0, "C:" + chr(92) + "Users" + chr(92) + "tempadmin" + chr(92) + "Coding" + chr(92) + "Syndicate" + chr(92) + "scripts")
import _base_url  # noqa: E402

subs = [s.lower() for s in sys.argv[1:]]
tok = _base_url.fleet_admin_token()
req = urllib.request.Request(_base_url.FLEET_BASE_URL + "/api/portfolio/live?on=all&show=all",
                             headers={"X-Admin-Token": tok})
with urllib.request.urlopen(req, timeout=60) as r:
    d = json.load(r)


def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


print("top keys", list(d.keys())[:20] if isinstance(d, dict) else type(d))
seen = 0
for o in walk(d):
    blob = json.dumps(o, default=str).lower()
    if len(blob) > 6000:
        continue
    if all(s in blob for s in subs) and any(k in o for k in ("odds", "price", "stake", "side", "line")):
        seen += 1
        print(json.dumps({k: v for k, v in o.items() if "token" not in k.lower() and "key" != k.lower()}, default=str)[:900])
print("matches", seen)
