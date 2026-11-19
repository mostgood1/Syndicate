"""I-29 check: for each live college game, the rail rows' (away @ home) vs the live re-sim snapshot's away/home.

  WSL: ~/.venvs/syndicate/bin/python /mnt/c/tmp/railmon/p29_orient.py
Read-only: redis GET of the re-sim snapshots, one GET of /api/board/live-rail.
"""
import json, subprocess, urllib.request

KEY = "syndicate:refresh-state:/home/amyn/syndicate-prod/data/live/{}_live_resim.json"


def norm(s):
    return " ".join(str(s or "").lower().replace(".", "").split())


rail = json.load(urllib.request.urlopen("http://127.0.0.1:10000/api/board/live-rail", timeout=30))
rows = rail.get("rows") or []
out = []
for sport in ("ncaab", "wncaab"):
    raw = subprocess.run(["redis-cli", "--raw", "GET", KEY.format(sport)], capture_output=True, text=True).stdout
    try:
        snap = json.loads(raw) if raw.strip() else {}
    except Exception:
        snap = {}
    games = snap.get("games") or []
    by_pair = {}
    for g in games:
        by_pair[(norm(g.get("away")), norm(g.get("home")))] = g
    matchups = {}
    for r in rows:
        if r.get("sport") != sport or r.get("player_name"):
            continue
        m = matchups.setdefault(r.get("matchup"), {"rows": 0, "with_model": 0})
        m["rows"] += 1
        m["with_model"] += 1 if r.get("live_model_probability") is not None else 0
    for mu, c in matchups.items():
        away, _, home = str(mu).partition(" @ ")
        direct = by_pair.get((norm(away), norm(home)))
        reversed_ = by_pair.get((norm(home), norm(away)))
        state = "direct" if direct else ("REVERSED" if reversed_ else "not_in_resim")
        out.append(dict(sport=sport, matchup=mu, rows=c["rows"], with_model=c["with_model"], resim=state,
                        event_id=(direct or reversed_ or {}).get("event_id")))
    out.append(dict(sport=sport, resim_generated=snap.get("generatedAt"), resim_games=len(games), counts=snap.get("counts")))
for o in out:
    print(json.dumps(o))
