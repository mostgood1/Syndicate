# Sequential production pulls for the audit: predictions, game markets, prop odds.
import os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
S = Path(os.environ.get("SOCCER_AUDIT_CACHE") or HERE)
LEAGUES = ["epl", "championship", "la_liga", "bundesliga", "serie_a", "ligue_1",
           "eredivisie", "primeira_liga", "belgian_pro_league", "mls"]


def run(pattern, out, pause):
    subprocess.run([sys.executable, str(HERE / "prodfetch.py"), "batch", pattern, str(S / "prod" / out), str(pause)])


for lg in LEAGUES:
    run(f"soccer_source/{lg}/api/recommendations/recommendations_2026-*.json", "recs", 8)
for lg in LEAGUES:
    run(f"soccer_source/{lg}/props/game_markets_*.json", "game_markets", 8)
for lg in LEAGUES:
    for dek in ("2026-08-0", "2026-08-1", "2026-08-2", "2026-08-3", "2026-09-0", "2026-09-1"):
        run(f"soccer_source/{lg}/props/{dek}*.csv", "props", 20)
print("CHAIN DONE", flush=True)
