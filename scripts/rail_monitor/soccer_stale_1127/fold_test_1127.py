"""Offline: would p29_orient's find() match the rail's 'Real Racing Club de Santander @ Levante' to the spellings ESPN uses?"""
src = open(r"C:\tmp\railmon\p29_orient.py", encoding="utf-8").read().split("\nrail = json.load(")[0]
ns = {}
exec(compile(src, "p29_head", "exec"), ns)
for away, home in [("Racing Santander", "Levante"), ("Racing de Santander", "Levante UD"), ("Real Racing Club", "Levante"),
                   ("Racing Santander", "Real Sociedad")]:
    g = {"away_team": away, "home_team": home, "event_id": away}
    other = {"away_team": "Real Sociedad", "home_team": "Levante", "event_id": "decoy"}
    index = [(ns["names"](x), x) for x in (g, other)]
    hit = ns["find"](index, "Real Racing Club de Santander", "Levante", "soccer")
    print(f"{away} @ {home}: ->", (hit or {}).get("event_id"))
