"""Read-only: soccer orders submitted 20:02Z-21:48Z 11-27 (lens frozen at 20:01:59Z), archive shard + keyvalue doc.
In-play = submitted after commence_time."""
import json, os, subprocess
seen = {}
p = os.path.expanduser("~/syndicate-prod/data/reports/intelligence/execution_ledger_archive/orders_2026-11.jsonl")
for line in open(p, encoding="utf-8", errors="replace"):
    try:
        o = json.loads(line)
    except ValueError:
        continue
    seen[o.get("idempotency_key") or json.dumps(o, sort_keys=True)[:200]] = o
K = "syndicate:refresh-state:/home/amyn/syndicate-prod/data/reports/intelligence/execution_ledger.json"
raw = subprocess.run(["redis-cli", "--raw", "GET", K], capture_output=True, text=True, errors="replace").stdout
doc = json.loads(raw) if raw.strip() else {}
if isinstance(doc, dict) and isinstance(doc.get("payload"), dict):
    doc = doc["payload"]
orders = doc.get("orders") if isinstance(doc, dict) else doc
print("keyvalue doc orders", len(orders or []), "type", type(doc).__name__)
for o in orders or []:
    if isinstance(o, dict):
        seen[o.get("idempotency_key") or json.dumps(o, sort_keys=True)[:200]] = o
rows = [o for o in seen.values() if o.get("sport") == "soccer" and "2026-11-27T20:02" <= str(o.get("submitted_at") or "") <= "2026-11-27T21:48"]
inplay = [o for o in rows if str(o.get("commence_time") or "9") < str(o.get("submitted_at"))]
print("soccer orders in window", len(rows), "| in-play", len(inplay), "| modes", sorted({o.get("mode") for o in rows}))
for o in sorted(inplay, key=lambda x: str(x.get("submitted_at"))):
    print(o.get("submitted_at", "")[:19], o.get("mode"), o.get("venue"), f"{o.get('away_team')} @ {o.get('home_team')}", o.get("market"),
          o.get("segment"), o.get("selection") or o.get("side"), o.get("line"), "ko", str(o.get("commence_time"))[11:16],
          "edge", o.get("model_edge_pct"), "stake", o.get("requested_stake_dollars"), o.get("status"))
