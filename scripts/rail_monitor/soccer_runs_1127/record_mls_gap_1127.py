"""Record the MLS history gap check (user 11-27 "check the MLS history gap"): lane STATUS (DIAGNOSED), a findings
section that also corrects the earlier lead line, and copy the readers into scripts/rail_monitor/soccer_runs_1127/.
.tmp + os.replace; idempotent; reads the clock."""
import os
import shutil
from datetime import datetime, timedelta, timezone

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
LANES = os.path.join(W, ".syndicate", "lanes.md")
FIND = os.path.join(W, ".syndicate", "findings_2026-11-26_layer2_rail_monitor.md")
STAMP = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("%I:%M %p").lstrip("0") + " CST"


def load(p):
    s = open(p, encoding="utf-8", newline="").read()
    return s, ("\r\n" if "\r\n" in s else "\n")


def save(p, s):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    os.replace(tmp, p)
    print("wrote", p)


TAG = "MLS history gap: DIAGNOSED, no gap reaches the models"
s, nl = load(LANES)
head = "### layer2-rail-monitor \u2014 OPEN \u2014 opened 2026-11-15"
i = s.index(head)
j = s.find(nl + "### ", i + 1)
j = len(s) if j < 0 else j
blk = s[i:j]
marker = "- **STATUS 2026-11-27 5:51 PM CST: MLS history gap: DIAGNOSING**"
status = (f"- **STATUS 2026-11-27 {STAMP}: {TAG}** (H1 CONFIRMED, H2 CONFIRMED, H3 FALSIFIED). Ratings: the live ASA "
          "pull, 520 scored 2026 games through 11-25 UTC, default stage includes the 10 playoff games (18 teams at 35-36 "
          "games; Regular Season alone 34 each). Corners: 402 history rows (02-21..09-27) + 118 live_state rows "
          "(09-30..11-24) = 520, 0 duplicates, the same 520. The 10-07 file is a one-off backfill by design; the earlier "
          "lead (\"MLS playoff matches not in its history\") is true of the FILE only and is withdrawn. Findings 11-26 "
          "file, \"MLS history gap\".")
if TAG in blk:
    print("lane status already there")
else:
    assert blk.count(marker) == 1
    k = blk.index(marker)
    save(LANES, s[:i] + blk[:k] + status + nl + blk[k:] + s[j:])

s, nl = load(FIND)
title = "## MLS history gap (user \"check the MLS history gap\", 11-27): no gap reaches the models"
if title in s:
    print("findings already there")
else:
    sec = [
        "", title, "",
        "- **Corrects** the lead in \"SOCCER_RUN_FAILED exit 1\" above: `mls/history/matches_2026.csv` does stop in "
        "September, but nothing that prices MLS depends on it for recent matches. Hypotheses H1-H3 were written into the "
        "lane before the read (5:51 PM CST).",
        "- **The file:** 402 rows, 2026-02-21..2026-09-27, every row with corners (written 10-07; a one-off backfill, "
        "`scripts/soccer_season_audit/backfill_mls_corner_history.py`). The sweep has no MLS history step on purpose: "
        "\"MLS ratings are a live ASA fetch and need no step\" (`scripts/refresh_odds_sources.py:2268`).",
        "- **H1 CONFIRMED, ratings:** `build_soccer_artifacts._load_team_ratings` calls `fetch_asa_mls_team_history(today's "
        "year)` on every build (`/mls/teams/xgoals`, season aggregates) and never reads `history/` for MLS. ASA's 2026 game "
        "list, read 11-27: 520 games, all scored, the latest dated 11-25 UTC.",
        "- **H3 FALSIFIED, playoffs are in the ratings:** the call passes `season_name` only, and ASA's default spans every "
        "stage: 30 teams, 34-36 games (16 at 35, 2 at 36); `stage_name=Regular Season` gives exactly 34 each; "
        "`stage_name=Playoffs` 18 teams with 1-2 (10 matches, 11-19..11-25 UTC).",
        "- **H2 CONFIRMED, corners:** `corners_estimator.league_corner_rows` on the fleet's code: 402 history rows (last "
        "09-27) + 118 `live_state` match-box rows (09-30..11-24) = 520 rows, 0 sharing (day, home, away). 520 is ASA's game "
        "count, so no match between the backfill's end and the live boxes' start is missing. (My own corner check over the "
        "boxes read 0 with corners: wrong key path; the estimator's count is the measurement.)",
        "- **Not a gap, noted only:** the ratings fetch takes `date.today().year`; from 2027-01-01 it reads the 2027 season, "
        "which has no games until late February. MLS 2026 ends in December, so nothing priced is affected this year.",
        "- **Readers:** `scripts/rail_monitor/soccer_runs_1127/mls_hist_gap_1127.py`, `mls_asa_lag_1127.py`.",
        "",
    ]
    save(FIND, s.rstrip("\r\n") + nl + nl.join(sec))

dst = os.path.join(W, "scripts", "rail_monitor", "soccer_runs_1127")
for f in ("mls_hist_gap_1127.py", "mls_asa_lag_1127.py", "record_mls_gap_1127.py"):
    out = os.path.join(dst, f)
    shutil.copyfile(os.path.join(r"C:\tmp\railmon", f), out + ".tmp")
    os.replace(out + ".tmp", out)
print("copied readers | stamp", STAMP)
