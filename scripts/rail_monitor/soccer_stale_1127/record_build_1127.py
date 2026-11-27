"""Record the soccer lane-age ceiling build (#865): todo item at the top of todo.md, lane STATUS, a findings section,
and copies of the kit and readers into scripts/rail_monitor/soccer_stale_1127/. .tmp + os.replace; idempotent; reads
the clock for its stamps."""
import os
import shutil
from datetime import datetime, timedelta, timezone

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
TODO = os.path.join(W, "docs", "ai_context", "todo.md")
LANES = os.path.join(W, ".syndicate", "lanes.md")
FIND = os.path.join(W, ".syndicate", "findings_2026-11-26_layer2_rail_monitor.md")
now = datetime.now(timezone.utc)
ct = now - timedelta(hours=6)
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


HEAD = "### `#865` \u2014"
item = [
    "### `#865` \u2014 **SOCCER LIVE PRICING HAD NO LANE-AGE CEILING, AND ITS LANES CARRIED NO TIME: 11-27 20:02-21:47Z the "
    "soccer live lens was frozen (its memory gate skipped every tick on the over-cap live-odds-worker) and the join kept "
    "pricing the six matches already in it, 14-38 rows per build, from a model that ended ~95 min old (2 in-play PAPER "
    "orders, 0 live money). Fix BUILT, DEFAULT OFF, on main; QUEUED FOR THE 12-08 WINDOW** `[2026-11-27, lane "
    "soccer-live-lane-age-ceiling, session d58574cb (rail monitor); user \"Yes, build it here\" ~4:35 PM CST to \"Should "
    "I build a soccer lane-age ceiling, default-off, queued for the 12-08 window?\"; findings "
    "`.syndicate/findings_2026-11-26_layer2_rail_monitor.md` \"Soccer lane-age ceiling built\"]`",
    "",
    f"- **BUILT {STAMP} 11-27, DEFAULT OFF.** `SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE`: absent = off = today (no lane time "
    "stamped, no ceiling); `shadow` = the lens time is stamped and the 600 s ceiling judged, nothing refused, counted on "
    "LIVE_GAMELINE_JOIN `lane_age_would_refuse`; `on` (and any other set value) = a soccer lane older than 600 s, or with "
    "no time, is not priced. The global `SYNDICATE_LIVE_GAMELINE_LANE_AGE_GATE` still rules over it. "
    "`soccer_live_gameline_source.soccer_live_games(stamp_snapshot_time=...)` copies the lens's top-level `generated_at` "
    "onto each match, only while the switch is not off.",
    "- **Ceiling measured** (fleet logs 11-23 12:05Z..11-27 22:34Z, 146 soccer builds with a match in play): no gate skip "
    "since the last lens write n 102, p95 101 s, max 195 s; a gate skip since it n 44, p50 488 s, max 6,032 s. 600 s "
    "refuses 20 builds (493 of 1,903 priceable rows), all stalls, 0 fresh. **No Saturday slate in that sample: R-N owed** "
    "(re-run `scripts/rail_monitor/soccer_stale_1127/soccer_lane_age_1127.sh` after 11-28; MET if the no-skip max stays "
    "under 450 s, else raise `SOCCER_MAX_LANE_AGE_SECONDS` before 12-08 and tell the user).",
    "- **Tests:** `tests/test_soccer_live_lane_age_gate.py` 34 / 34 (off != on through the join and through "
    "`board_enrichment`; off stamps nothing; on refuses at 601 s and an untimed lens, prices at 600 s; shadow prices as "
    "off and counts; global gate rules; other sports' ceilings unmoved). Join, lane-age, soccer and board-enrichment "
    "suites 780 passed. A/B (switch absent) vs the pre-change modules on the same inputs: 8 of 8 cases byte-identical; "
    "control with the switch on: 700 s and 6,063 s builds price 0 of 12, 60 s 12 of 12 (`soccer_lane_age_ab.py`).",
    "- **Line for the window:** ONE GLOBAL `SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE=on` on the window's drained down/up "
    "(or `shadow` first, NOT a betting change, if the user wants a reading before `on`). Kit `C:\\tmp\\w1208_soccer_lane_age\\` "
    "(`kit_env_soccer_lane_age.sh check|apply shadow|on|restore`, self-test PASS, real env untouched: key ABSENT on all three "
    "roles); after-load reader `kit_after_up_soccer_lane_age.sh <since_utc>` (BEFORE 11-27 19:00Z+: 29 soccer lines with a "
    "match in play, `lane_age_max` None on all 29). A fleet ff carrying the code is NOT a betting change (absent = "
    "identical); loading the env line `on` IS. The LOAD yes is owed on the day. The fleet-watcher keeps the 12-08 queue.",
    "- **Not covered:** soccer live PROPS (`soccer_live_prop_index`, LIVE_PROJECTION_JOIN) read the same lens with no age "
    "check (edged 0 while it was frozen, so no prop edge came from it on 11-27); the memory gate itself (live-odds-worker "
    "over its 3,072 MB cap most of 11-27 afternoon; MLB 112 / WNBA 118 / soccer ~120 low-headroom skips that day).",
    "",
]
s, nl = load(TODO)
if HEAD in s:
    print("todo item already there")
else:
    k = s.index("### `#864`")
    save(TODO, s[:k] + nl.join(item) + nl + s[k:])

s, nl = load(LANES)
head = "### soccer-live-lane-age-ceiling \u2014 OPEN \u2014 opened 2026-11-27"
i = s.index(head)
j = s.find(nl + "### ", i + 1)
j = len(s) if j < 0 else j
blk = s[i:j]
TAG = "BUILT, DEFAULT OFF, on main"
status = (f"- **STATUS 2026-11-27 {STAMP}: {TAG}; QUEUED FOR 12-08 (`#865`).** Tests 34 / 34 new, 780 regression; "
          "A/B switch-absent 8 of 8 byte-identical to the pre-change modules (control with `on`: stale builds price 0 of "
          "12). Kit `C:\\tmp\\w1208_soccer_lane_age\\` self-test PASS, real env untouched (key absent on all roles). Owed: "
          "R-N Saturday re-measure after 11-28 (rail monitor close); the load-day yes; the after-load reading. The ceiling "
          "is 600 s (fresh max 195 s, 11-23..11-27).")
if TAG in blk:
    print("lane status already there")
else:
    lines = blk.split(nl)
    k = next(n for n, l in enumerate(lines) if l.startswith("- Blocked by:")) + 1
    lines.insert(k, status)
    save(LANES, s[:i] + nl.join(lines) + s[j:])

s, nl = load(FIND)
title = "## Soccer lane-age ceiling built (#865, 11-27; user \"Yes, build it here\")"
if title in s:
    print("findings already there")
else:
    sec = [
        "", title, "",
        "- **What:** `SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE` (absent = off = today; shadow; on) gives soccer live pricing "
        "a 600 s lane-age ceiling, and the soccer source stamps the lens time onto each match while the switch is not off "
        "(lane `soccer-live-lane-age-ceiling`, todo `#865`). Default off on main; queued for the 12-08 window.",
        "- **Why soccer lanes had no time:** the poller writes `generated_at` at the top of the lens only; "
        "`soccer_live_gameline_index` read `game.get(\"generated_at\")`, so `as_of` was None and `lane_age_max=None` on all "
        "287 soccer LIVE_GAMELINE_JOIN lines 11-27. A ceiling alone would have refused every soccer row as untimed.",
        "- **The ceiling, measured** (`soccer_lane_age_1127.sh`, fleet logs 11-23 12:05Z..11-27 22:34Z, 146 soccer builds "
        "with a match in play, age = build time minus the last soccer lens write): no gate skip since the write n 102, p50 "
        "45 s, p95 101 s, p99 137 s, max 195 s; a gate skip since it n 44, p50 488 s, p95 5,333 s, max 6,032 s. At 600 s: "
        "20 builds refused (493 of 1,903 priceable rows), every one a stall, 0 fresh. The probe readings sample 11-21 "
        "(Saturday) held two readings at 501-581 s with 11 matches in the lens, and that day's logs have rotated, so a "
        "heavy Saturday's normal cadence is NOT measured: R-N.",
        "- **Proof:** tests 34 / 34; 780 regression; A/B with the switch absent 8 of 8 byte-identical to the pre-change "
        "modules (aggregate and per-league lens, h2h / totals / spreads, 60 / 700 / 6,063 s); control `on`: 700 s and 6,063 s "
        "price 0 of 12, 60 s 12 of 12; control `shadow`: 12 of 12 at every age.",
        "- **Owed:** R-N (Saturday re-measure after 11-28); the load-day yes; the after-load reading (`kit_after_up_soccer_lane_age.sh`).",
        "",
    ]
    save(FIND, s.rstrip("\r\n") + nl + nl.join(sec))

dst = os.path.join(W, "scripts", "rail_monitor", "soccer_stale_1127")
os.makedirs(dst, exist_ok=True)
for src in (r"C:\tmp\railmon\soccer_lane_age_1127.sh", r"C:\tmp\railmon\soccer_lane_age_ab.py",
            r"C:\tmp\railmon\soccer_age_dist_1127.py", r"C:\tmp\railmon\soccer_tick_gaps_1127.sh",
            r"C:\tmp\w1208_soccer_lane_age\kit_env_soccer_lane_age.sh",
            r"C:\tmp\w1208_soccer_lane_age\kit_selftest_soccer_lane_age.sh",
            r"C:\tmp\w1208_soccer_lane_age\kit_after_up_soccer_lane_age.sh",
            r"C:\tmp\w1208_soccer_lane_age\record_build_1127.py"):
    out = os.path.join(dst, os.path.basename(src))
    shutil.copyfile(src, out + ".tmp")
    os.replace(out + ".tmp", out)
print("copied kit and readers to", dst, "| stamp", STAMP)
