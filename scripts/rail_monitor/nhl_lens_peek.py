"""The NHL live lens (Redis keyvalue copy): per game, its identity fields, refusal, and the gameLens lanes (market,
source, and whether each lane carries a probability / total). Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/nhl_lens_peek.py [team substring]
"""
import json, subprocess, sys

KEY = "syndicate:refresh-state:/home/amyn/syndicate-prod/data/live/nhl_live_lens.json"
want = sys.argv[1].lower() if len(sys.argv) > 1 else ""
snap = json.loads(subprocess.run(["redis-cli", "--raw", "GET", KEY], capture_output=True, text=True, errors="replace").stdout)
if isinstance(snap.get("payload"), dict):
    snap = snap["payload"]
print("generatedAt", snap.get("generatedAt"), "games", len(snap.get("games") or []))
for g in snap.get("games") or []:
    ident = {k: v for k, v in g.items() if not isinstance(v, (dict, list))}
    if want == "resimmed":
        if not any(isinstance(l, dict) and str(l.get("source") or "").startswith("live") for l in g.get("gameLens") or []):
            continue
    elif want and want not in json.dumps(ident).lower():
        continue
    print("GAME", json.dumps(ident)[:500])
    for k, v in g.items():
        if isinstance(v, (dict, list)) and k != "gameLens":
            print("   ", k, json.dumps(v)[:300])
    for lane in g.get("gameLens") or []:
        if isinstance(lane, dict):
            print("    LANE", json.dumps({k: v for k, v in lane.items() if not isinstance(v, (dict, list))})[:420])
            for k, v in lane.items():
                if isinstance(v, (dict, list)):
                    print("       ", k, json.dumps(v)[:260])
    if not want:
        break
