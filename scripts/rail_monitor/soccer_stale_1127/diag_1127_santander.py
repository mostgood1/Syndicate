"""Read-only (nice 19): how the soccer live lens and the rail spell Real Racing Club de Santander @ Levante, and what
p29_orient's norm/find make of them."""
import json, subprocess, sys, urllib.request
sys.path.insert(0, "/mnt/c/tmp/railmon")
import importlib.util

spec = importlib.util.spec_from_file_location("p29", "/mnt/c/tmp/railmon/p29_orient.py")
src = open("/mnt/c/tmp/railmon/p29_orient.py", encoding="utf-8").read()
head = src.split("\nrail = json.load(")[0]  # the helper's functions only, not its main
ns = {}
exec(compile(head, "p29_head", "exec"), ns)

PFX = "syndicate:refresh-state:/home/amyn/syndicate-prod/data/live/"
raw = subprocess.run(["redis-cli", "--raw", "GET", PFX + "soccer_live_lens.json"], capture_output=True, text=True,
                     errors="replace").stdout
snap = json.loads(raw) if raw.strip() else None
if isinstance(snap, dict) and isinstance(snap.get("payload"), dict):
    snap = snap["payload"]
games = (snap or {}).get("games") or []
print("lens generated", (snap or {}).get("generatedAt") or (snap or {}).get("generated_at"), "games", len(games))
KEYS = ("santander", "racing", "levante")
for g in games:
    blob = json.dumps(g, ensure_ascii=False, default=str).lower()
    if any(k in blob for k in KEYS):
        mom = g.get("momentum") if isinstance(g.get("momentum"), dict) else {}
        print("LENS GAME:", json.dumps({k: g.get(k) for k in ("event_id", "league", "away", "home", "away_name", "home_name",
                                                              "away_team", "home_team", "matchup", "status", "state")},
                                       ensure_ascii=False, default=str)[:900])
        print("   projection is None:", g.get("projection") is None, "momentum.reason:", mom.get("reason"),
              "gameLens:", type(g.get("gameLens")).__name__)
        print("   names():", sorted(ns["names"](g)))
        print("   lens_reason():", ns["lens_reason"](g))

rail = json.load(urllib.request.urlopen("http://127.0.0.1:10000/api/board/live-rail", timeout=30))
seen = set()
for r in rail.get("rows") or []:
    mu = str(r.get("matchup") or "")
    if r.get("sport") == "soccer" and any(k in mu.lower() for k in KEYS) and mu not in seen:
        seen.add(mu)
        away, _, home = mu.partition(" @ ")
        print("RAIL MATCHUP:", repr(mu), "league", r.get("league"), "read_at", rail.get("read_at"))
        print("   norm:", repr(ns["norm"](away)), repr(ns["norm"](home)))
        index = [(ns["names"](g), g) for g in games if isinstance(g, dict)]
        hit = ns["find"](index, away, home, "soccer")
        rev = ns["find"](index, home, away, "soccer") if hit is None else None
        print("   find direct:", (hit or {}).get("event_id"), "reversed:", (rev or {}).get("event_id"))
if not seen:
    print("no Santander / Levante rows on the rail at", rail.get("read_at"))
