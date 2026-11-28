"""Record the MLS ratings season-rollover fix (#866): todo item, lane STATUS, a findings section, and copies of the
study / A/B into scripts/rail_monitor/mls_rollover/. .tmp + os.replace; idempotent; reads the clock.
  py -3 record_mls_rollover_1127.py "<regression result line>" """
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
TODO = os.path.join(W, "docs", "ai_context", "todo.md")
LANES = os.path.join(W, ".syndicate", "lanes.md")
FIND = os.path.join(W, ".syndicate", "findings_2026-11-26_layer2_rail_monitor.md")
REG = sys.argv[1]
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


item = [
    "### `#866` \u2014 **MLS TEAM RATINGS WOULD HAVE COLLAPSED AT THE 2027 OPENER: the MLS branch of `build_soccer_artifacts."
    "_load_team_ratings` fetched ASA's aggregates for `date.today().year`, so from 2027-01-01 it reads season 2027, which "
    "has no games until late February: 0 teams rated (measured on ASA 11-27), every MLS team on the same "
    "PROMOTED_TEAM_RATING. FIXED ON MAIN, identical for every 2026 build** `[2026-11-27, lane mls-ratings-season-rollover, "
    "session d58574cb (rail monitor); user \"Fix the ratings year rollover before January\" ~6:05 PM CST; findings "
    "`.syndicate/findings_2026-11-26_layer2_rail_monitor.md` \"MLS ratings season rollover\"]`",
    "",
    f"- **FIXED {STAMP} 11-27.** The season is the build date's (`_mls_season_for(as_of)`), and until a team has 34 games "
    "this season the gap is filled at last season's per-match rates (`_mls_team_rows`, window 34 = one regular season); a "
    "team with no game yet takes last season's alone, an expansion team this season's alone, a failed last-season fetch "
    "falls back to this season alone (`MLS_SEASON_CARRY_UNAVAILABLE`). Prints `MLS_SEASON_CARRY` when it carries.",
    "- **Measured** (`scripts/rail_monitor/mls_rollover/mls_rollover_study.py`, ASA per-game xG, every 2025 and 2026 match "
    "rated from games before its day, Poisson log-likelihood vs season-to-date only): 1-4 games +0.304 +- 0.220 (n 122), "
    "all +0.050 +- 0.030 (n 1,060; 2025 +0.028, 2026 +0.072), 1X2 Brier 0.6365 -> 0.6235; best of seven rules. A stand-in "
    "for the engine's rating -> goals mapping: it ranks input rules, it does not reproduce the engine's numbers.",
    f"- **Proof:** tests `tests/test_mls_ratings_season_rollover.py` 10 / 10; {REG}. A/B on the real ASA pull "
    "(`mls_rollover_ab.py`): 2026-11-28, 11-29 and 12-05 IDENTICAL to the old code (30 teams, 34-36 games, last season "
    "not fetched); 2027-02-27: old 0 teams, new 30 teams with 30 distinct attack ratings.",
    "- **Load / betting-change note:** `build_soccer_artifacts.py` runs as a fresh subprocess on each soccer refresh, so "
    "the code takes effect at the first soccer run after the next fleet ff, no restart. It changes NOTHING while every "
    "team has 34+ games (all 2026 builds). It first changes MLS pricing at the first build for a 2027 MLS date (~mid-Feb "
    "2027, the opener's look-ahead), against an old path that would have priced every team equal. For the betting-change "
    "log: `no` at the ff that carries it; the 2027 effect is the fleet-watcher's / user's call to log.",
    "- **Players checked, no cliff:** `_load_player_rows` concatenates every `players_*.csv` (`build_soccer_artifacts.py:723`), "
    "so `players_2026.csv` stays in use after the year turns. **Not covered:** the MLS 2027 schedule path, and the "
    "study's mapping is a stand-in (above).",
    "",
]
s, nl = load(TODO)
if "### `#866` \u2014" in s:
    print("todo already there")
else:
    k = s.index("### `#865`")
    save(TODO, s[:k] + nl.join(item) + nl + s[k:])

s, nl = load(LANES)
head = "### mls-ratings-season-rollover \u2014 OPEN \u2014 opened 2026-11-27"
i = s.index(head)
j = s.find(nl + "### ", i + 1)
j = len(s) if j < 0 else j
blk = s[i:j]
TAG = "FIXED ON MAIN, identical for every 2026 build"
status = (f"- **STATUS 2026-11-27 {STAMP}: {TAG} (`#866`).** H1 CONFIRMED (ASA 2027 returns 0 teams today), H2 "
          "CONFIRMED (window-34 carry +0.050 +- 0.030 log-lik over 1,060 matches, +0.304 at 1-4 games), H3 CONFIRMED (A/B on "
          f"the real pull: 2026-11-28 / 11-29 / 12-05 identical). Tests 10 / 10; {REG}. Loads with the next fleet ff (a "
          "subprocess per run); first effect at the first 2027 MLS build.")
if TAG in blk:
    print("lane status already there")
else:
    lines = blk.split(nl)
    k = next(n for n, l in enumerate(lines) if l.startswith("- Blocked by:")) + 1
    lines.insert(k, status)
    save(LANES, s[:i] + nl.join(lines) + s[j:])

s, nl = load(FIND)
title = "## MLS ratings season rollover fixed (#866; user \"Fix the ratings year rollover before January\")"
if title in s:
    print("findings already there")
else:
    sec = [
        "", title, "",
        "- **Defect:** `fetch_asa_mls_team_history(date.today().year)`. ASA season 2027 read 11-27: 0 teams, so a February "
        "2027 build rates nobody and `_fill_promoted` puts every MLS team on PROMOTED_TEAM_RATING.",
        "- **Fix:** the build date's season, and last season fills each team's first 34 games (games-weighted). Identical "
        "while every team has 34+ (all of 2026); last season is not fetched then.",
        "- **Study** (`scripts/rail_monitor/mls_rollover/mls_rollover_study.py`; rules A season-to-date, B last season, C5/C10/"
        "C17 switch, D17/D34 window), pooled 2025+2026, log-lik vs A: 0 games -0.029 +- 0.120 (n 30, all carries equal); "
        "1-4 D34 +0.304 +- 0.220 (n 122); 5-9 +0.030 (n 153); 10-16 +0.029 (n 214); 17-33 +0.011 +- 0.009 (n 501); all D34 "
        "+0.050 +- 0.030, D17 +0.045 +- 0.027, C10 +0.034 +- 0.031, B +0.020 +- 0.037; Brier A 0.6365, D34 0.6235. D34 is "
        "best in both seasons.",
        f"- **Proof:** 10 / 10 new tests; {REG}; real-pull A/B 3 of 3 2026 dates identical; 2027-02-27 old 0 teams, new 30.",
        "",
    ]
    save(FIND, s.rstrip("\r\n") + nl + nl.join(sec))

dst = os.path.join(W, "scripts", "rail_monitor", "mls_rollover")
os.makedirs(dst, exist_ok=True)
for f in ("mls_rollover_study.py", "mls_rollover_ab.py", "record_mls_rollover_1127.py"):
    out = os.path.join(dst, f)
    shutil.copyfile(os.path.join(r"C:\tmp\railmon\mls_rollover", f), out + ".tmp")
    os.replace(out + ".tmp", out)
print("copied | stamp", STAMP)
