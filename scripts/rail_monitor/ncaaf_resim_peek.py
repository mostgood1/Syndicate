"""Print the NCAAF live re-sim snapshot's entries for named teams (Redis keyvalue copy). Read-only.

  cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/ncaaf_resim_peek.py Purdue "Ole Miss" Army
"""
import json, subprocess, sys

KEY = "syndicate:refresh-state:/home/amyn/syndicate-prod/data/live/ncaaf_live_lens.json"
raw = subprocess.run(["redis-cli", "--raw", "GET", KEY], capture_output=True, text=True, errors="replace").stdout
if not raw.strip():
    sys.exit("empty key " + KEY)
doc = json.loads(raw)
if isinstance(doc, dict) and isinstance(doc.get("payload"), (dict, list)):
    print("unwrapping payload; wrapper keys", list(doc.keys()))
    doc = doc["payload"]
print("top keys", list(doc.keys())[:30])
for k in ("generatedAt", "generated_at", "date", "coverage"):
    if k in doc:
        print(k, json.dumps(doc[k], default=str)[:600])


def walk(o, path=""):
    if isinstance(o, dict):
        s = json.dumps(o, default=str)
        hit = [t for t in sys.argv[1:] if t.lower() in s.lower()]
        if hit and len(s) < 6000 and any(x in o for x in ("away", "home", "away_team", "home_team", "matchup", "event_id")):
            yield path, o
            return
        for kk, v in o.items():
            yield from walk(v, path + "/" + str(kk))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, path + f"[{i}]")


seen = 0
for path, o in walk(doc):
    seen += 1
    small = {k: v for k, v in o.items() if not isinstance(v, (dict, list)) or len(json.dumps(v, default=str)) < 300}
    print("--", path)
    print("  ", json.dumps(small, default=str)[:1500])
    if seen > 12:
        break
print("matches", seen)
