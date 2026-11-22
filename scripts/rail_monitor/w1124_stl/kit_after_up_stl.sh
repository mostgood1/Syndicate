#!/bin/bash
# After the load: the served live rail's NHL games, per game, how many full-game moneyline + puck-line rows carry a live
# model (live_model_probability). With the key on, a live St. Louis Blues game must read N of N like every other NHL
# game (11-21 6:43 PM CST before the fix: St. Louis 0 of 1, every other game all). NHL totals are excluded: they are
# refused at the join by design (no total distribution). Prints the role env too. Read-only; run at nice 19, during a
# live Blues game (a game with no live rows prints nothing).
set -u
cd /home/amyn/Syndicate || exit 4
for r in refresh-worker web; do
  v=$(python3 scripts/local_production.py env --role "$r" 2>/dev/null | grep -E "^SYNDICATE_LIVE_GAMELINE_NHL_TEAM_ALIASES=" || true)
  echo "role_env[$r]: ${v:-ABSENT}"
done
nice -n 19 python3 - <<'EOF'
import collections, json, urllib.request
rail = json.load(urllib.request.urlopen("http://127.0.0.1:10000/api/board/live-rail", timeout=30))
by = collections.defaultdict(lambda: [0, 0])
for r in rail.get("rows") or []:
    if r.get("sport") != "nhl" or r.get("player_name") or str(r.get("segment") or "full") != "full":
        continue
    if str(r.get("market") or "").lower() not in ("h2h", "spreads", "alternate_spreads", "spreads_alt"):
        continue
    g = by[r.get("matchup")]
    g[0] += 1
    g[1] += r.get("live_model_probability") is not None
print("read_at", rail.get("read_at"), "nhl sports entry", (rail.get("sports") or {}).get("nhl"))
for mu, (n, m) in sorted(by.items()):
    flag = "  <-- St. Louis" if "louis" in str(mu).lower() else ""
    print("  %-48s h2h/puck rows %d, with a live model %d%s" % (mu, n, m, flag))
if not by:
    print("  no live NHL moneyline / puck-line rows on the rail right now")
EOF
