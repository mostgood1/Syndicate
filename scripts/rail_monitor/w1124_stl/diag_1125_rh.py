"""R-H diag (read-only): every NHL row on the live rail and every NHL chip, with state and any refusal field."""
import collections, json, urllib.request

rail = json.load(urllib.request.urlopen("http://127.0.0.1:10000/api/board/live-rail", timeout=30))
print("read_at", rail.get("read_at"))
rows = [r for r in (rail.get("rows") or []) if r.get("sport") == "nhl"]
print("nhl rows", len(rows))
keys = collections.Counter()
for r in rows:
    keys.update(r.keys())
print("row keys:", sorted(keys))
for r in rows:
    small = {k: r.get(k) for k in sorted(r) if any(t in k for t in (
        "matchup", "market", "segment", "side", "line", "player", "live_model", "refus", "reason", "state", "period",
        "intermission", "status", "clock", "source", "basis", "join", "generated"))}
    print(json.dumps(small, default=str)[:900])
chips = rail.get("chips") or rail.get("games") or {}
print("chips type", type(chips).__name__)
items = chips.items() if isinstance(chips, dict) else enumerate(chips)
for k, c in items:
    if not isinstance(c, dict):
        continue
    if str(c.get("sport") or k).lower().find("nhl") < 0 and "nhl" not in json.dumps(c, default=str)[:300].lower():
        continue
    small = {kk: c.get(kk) for kk in sorted(c) if any(t in kk for t in (
        "matchup", "away", "home", "state", "status", "period", "clock", "score", "intermission", "detail"))}
    print("chip", k, json.dumps(small, default=str)[:600])
print("top-level keys", sorted(rail.keys()))
