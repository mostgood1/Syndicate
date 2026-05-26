import csv
import gzip
from pathlib import Path

p = Path("data/raw/statcast/pitches/2025/2025-09/statcast_2025-09-01_2025-09-30.csv.gz")
print("exists", p.exists(), "size_mb", round(p.stat().st_size / 1e6, 2))

with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
    r = csv.DictReader(f)
    row = next(r)

print("ncols", len(row))
keys = list(row.keys())
print("keys_head", keys[:30])

for k in [
    "game_date",
    "game_pk",
    "batter",
    "pitcher",
    "events",
    "description",
    "home_team",
    "away_team",
    "stand",
    "p_throws",
    "launch_speed",
    "launch_angle",
]:
    print(k, "=", row.get(k))
