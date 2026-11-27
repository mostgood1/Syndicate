"""Read-only: how old the soccer live lens is when read, from the rail readings 11-20..11-27 (each tick's p29 soccer
summary line: resim_generated against the reading's own time). Only readings with soccer games on the rail carry the
line. Prints the age distribution and every reading over 300 s, so stalls can be told from normal cadence."""
import glob, json, os
from datetime import datetime, timezone

ages = []
for p in sorted(glob.glob(r"C:\tmp\railmon\railwatch\extra_2026-11-*.jsonl")):
    for line in open(p, encoding="utf-8", errors="replace"):
        try:
            x = json.loads(line)
        except ValueError:
            continue
        at = datetime.strptime(x.get("at", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) if x.get("at") else None
        for o in x.get("orient") or []:
            if o.get("sport") == "soccer" and not o.get("matchup") and o.get("resim_generated") and at:
                gen = datetime.fromisoformat(o["resim_generated"].replace("Z", "+00:00"))
                ages.append((round((at - gen).total_seconds()), x["at"], o.get("resim_games")))
ages.sort()
vals = [a for a, _, _ in ages]
n = len(vals)
print("soccer readings", n)
if n:
    q = lambda f: vals[min(n - 1, int(f * n))]
    print("p50", q(0.5), "p90", q(0.9), "p95", q(0.95), "p99", q(0.99), "max", vals[-1])
    for lo, hi in ((-1e9, 60), (60, 120), (120, 180), (180, 240), (240, 300), (300, 450), (450, 600), (600, 900), (900, 1e9)):
        print(f"  [{lo:>6.0f}, {hi:>6.0f}) s: {sum(lo <= v < hi for v in vals)}")
    print("over 300 s:")
    for a, at, g in ages:
        if a > 300:
            print("  ", at, a, "s", "games_in_snapshot", g)
