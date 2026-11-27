"""Record the fleet-watcher's SOCCER_RUN_FAILED question (11-27): lane STATUS line, a findings section, and copy the
readers into scripts/rail_monitor/soccer_runs_1127/. .tmp + os.replace; idempotent; reads the clock."""
import os
import shutil
from datetime import datetime, timedelta, timezone

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
LANES = os.path.join(W, ".syndicate", "lanes.md")
FIND = os.path.join(W, ".syndicate", "findings_2026-11-26_layer2_rail_monitor.md")
ct = datetime.now(timezone.utc) - timedelta(hours=6)
STAMP = ct.strftime("%I:%M %p").lstrip("0") + " CST"


def load(p):
    s = open(p, encoding="utf-8", newline="").read()
    return s, ("\r\n" if "\r\n" in s else "\n")


def save(p, s):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    os.replace(tmp, p)
    print("wrote", p)


TAG = "SOCCER_RUN_FAILED is the known Understat outage"
s, nl = load(LANES)
head = "### layer2-rail-monitor \u2014 OPEN \u2014 opened 2026-11-15"
i = s.index(head)
j = s.find(nl + "### ", i + 1)
j = len(s) if j < 0 else j
blk = s[i:j]
marker = "- **STATUS 2026-11-27 4:16 PM CST: Santander @ Levante not_in_resim: NOT a name miss**"
status = (f"- **STATUS 2026-11-27 {STAMP}: {TAG} (`#841`), not a new failure** (the fleet-watcher's ask, user \"yes, send the "
          "soccer failures to the rail monitor\"). 1,157 of 1,157 soccer runs 11-20..11-27 exited 1; 1,129 carry a big-5 "
          "Understat step (maintenance page 3,988, unreachable 166); the other 28 are the 11-26 DNS outage and a few OddsAPI "
          "502/429. Stale: only the big-5 Understat files (team_history/teams_2026.csv ~645 h, players_2026.csv ~637 h). "
          "Bundesliga 12-04 is `#520` by design (artifacts drop while the league is in play). Lead: MLS history 10-07, no "
          "history step. Findings 11-26 file, that section.")
if TAG in blk:
    print("lane status already there")
else:
    assert blk.count(marker) == 1
    k = blk.index(marker)
    save(LANES, s[:i] + blk[:k] + status + nl + blk[k:] + s[j:])

s, nl = load(FIND)
title = "## SOCCER_RUN_FAILED exit 1 (fleet-watcher, 11-27): the known Understat outage, #841"
if title in s:
    print("findings already there")
else:
    sec = [
        "", title, "",
        "- **Ask:** refresh-worker logs `SOCCER_RUN_FAILED exit_code=1` for ~95 run stamps since 01:18Z 11-27, stderr with no "
        "Traceback; what exits 1, and which units are stale? (the fleet-watcher, on the user's \"yes, send the soccer failures "
        "to the rail monitor\").",
        "- **What exits 1:** the run's `odds_refresh.json` `failureSummary` names it (the stderr file holds only the debug "
        "snapshots). In 20261127_200057: `soccer_bundesliga_history_current` and `soccer_bundesliga_players` rc 1, "
        "`UNDERSTAT_UNAVAILABLE ... status=200 content_type='text/html' ... 'Understat.com We will come back soon' (nothing "
        "written; the previous file is KEPT and is now stale)`. Every big-5 league (EPL, La Liga, Serie A, Ligue 1, "
        "Bundesliga) fails these two steps on every run.",
        "- **Rate:** 1,157 of 1,157 soccer runs 11-20 06:23Z..11-27 22:46Z exited 1 (per day 142 / 155 / 169 / 152 / 138 / "
        "150 / 144 / 107); 1,129 carry an Understat failure (reasons: non_json maintenance page 3,988, unreachable 166). The "
        "other 28 failed on the 11-26 DNS outage (artifacts / schedule / odds / props / history / live_state, 06:21-17:09Z) "
        "or single OddsAPI 502 / 429s on 11-20..11-24. 11-27: 107 of 107 failed, all through Understat.",
        "- **Known and owned:** `#841` (Understat down since 11-03 2:54 PM CST). The fleet's `soccer_source/_understat_status.json`: "
        "state down, down_since 2026-11-18T19:22:04Z (the record's start), last_ok_at null, 9,926 probes, last 22:47Z 11-27. "
        "The naming guard is loaded (that is the named stderr_tail); the cooldown stays off by the user's decision; the "
        "alternative-source splice is queued for 12-08 (`#845`).",
        "- **What is actually stale** (mtimes on the fleet, 22:5xZ 11-27): only the big-5 Understat files, "
        "`team_history/teams_2026.csv` ~645 h (10-31) and `players/players_2026.csv` ~637-639 h (11-01). Fresh: every league's "
        "recommendations (<= 0.3 h), odds / props (< 1 h), live state, and the non-Understat leagues' `history/matches_2026.csv` "
        "(5.6 h) and `players_2026.csv` (1.7-5.5 h). So the big-5 pregame sims price on team history frozen at 10-31, as `#841` says.",
        "- **The Bundesliga 12-04 unit is not stale by a defect:** its runs at 06:25, 11:36 and 16:49Z ran "
        "`soccer_bundesliga_artifacts` rc 0 (16:49Z wrote `recommendations_2026-12-04.json`); the 20:56Z run had no artifacts "
        "step because a Bundesliga match was in play, which drops the step from the live phase by design (`#520`, "
        "`scripts/refresh_odds_sources.py:2696`). `wrote_since_launch=False` is that run's shape.",
        "- **Not the lens freeze's cause:** the freeze was the live-odds-worker memory gate; this failing run's own snapshot "
        "read container memory 72.4% (2,193 MB headroom), and Understat fails at any memory level.",
        "- **Lead (not chased):** MLS `history/matches_2026.csv` was last written 10-07, and the live sweep carries no MLS "
        "history step (only `soccer_mls_live_state` and `soccer_mls_artifacts`), so MLS playoff matches since 10-07 are not "
        "in its history.",
        "- **Readers:** `scripts/rail_monitor/soccer_runs_1127/`.",
        "",
    ]
    save(FIND, s.rstrip("\r\n") + nl + nl.join(sec))

dst = os.path.join(W, "scripts", "rail_monitor", "soccer_runs_1127")
os.makedirs(dst, exist_ok=True)
for f in ("soccer_fail_1127.sh", "soccer_fail_agg_1127.py", "soccer_fail_agg2_1127.py", "soccer_stale_files_1127.py",
          "soccer_unit_1204_1127.py", "soccer_unit_steps_1127.py", "soccer_mls_hist_1127.py", "record_soccer_runs_1127.py"):
    out = os.path.join(dst, f)
    shutil.copyfile(os.path.join(r"C:\tmp\railmon", f), out + ".tmp")
    os.replace(out + ".tmp", out)
print("copied readers to", dst, "| stamp", STAMP)
