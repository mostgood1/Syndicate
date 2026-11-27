"""R-M at a nightly close: per probe reading after the midnight roll, the carried chips and whether each has a live
card. Read-only over C:\\tmp\\railmon\\readings. Usage: py -3 read_carry.py <D+1>   e.g. 2026-11-28
A carried chip counts as a live chip for today in the probe (8455f25c0's probe change), so a carried game with no
card shows in `live_chips_without_live_card`."""
import json
import os
import sys

nxt = sys.argv[1]
root = r"C:\tmp\railmon\readings"
stamp = nxt.replace("-", "") + "T"
rows = 0
for name in sorted(os.listdir(root)):
    if not name.startswith(stamp) or name[9:11] > "11":
        continue
    p = os.path.join(root, name, "reading.json")
    if not os.path.exists(p):
        continue
    r = json.load(open(p, encoding="utf-8"))
    t = r.get("teams") or {}
    carried = t.get("carried_chips")
    missing = [m for m in (t.get("live_chips_without_live_card") or [])]
    rows += 1
    print(name, "carried", carried, "| live_chips", t.get("live_chips"), "| live without card", missing)
print("readings", rows)
