"""Add R-N (the soccer lane-age Saturday re-measure, #865) to both rail monitor runbooks, before NIGHTLY CLOSE, and
name it in the close's owed-readings line. .tmp + os.replace; idempotent; asserts each anchor once."""
import os

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
RUNBOOKS = [r"C:\tmp\railmon\MONITOR_RUNBOOK.md", os.path.join(W, "scripts", "rail_monitor", "RUNBOOK.md")]
RN = ("**R-N. Soccer lane-age ceiling, Saturday re-measure (#865, lane soccer-live-lane-age-ceiling; code fabdd54f7 on "
      "main, default off, queued for 12-08).** At the 11-28 close (after Saturday's slate), once:")
BODY = [
    RN,
    "1. `wsl -- nice -n 19 bash /mnt/c/tmp/railmon/soccer_lane_age_1127.sh` (read-only; every retained, rotated log; a "
    "few minutes). It prints the soccer join builds with a match in play, split by whether the memory gate skipped a tick "
    "since the last lens write.",
    "2. MET: the \"no gate skip since the write\" max stays under 450 s (11-23..11-27: 195 s), so 600 s refuses only "
    "stalls. FALSIFIED: a no-skip build over 450 s -- then the ceiling is too tight for a heavy slate: say so to the user "
    "and propose a new `SOCCER_MAX_LANE_AGE_SECONDS` before 12-08 (a code change in `live_gameline_join.py`, the lane's "
    "section).",
    "3. N = 0 (no soccer in play Saturday): carry to the 11-29 close.",
    "4. Write the result in lane `soccer-live-lane-age-ceiling`, todo `#865` and the day's findings; mark R-N DONE here.",
]
OLD_OWED = "(from 11-27: R-M, the after-midnight carry, and the OURS fix's `ours_resim_tick` count)"
NEW_OWED = ("(from 11-27: R-M, the after-midnight carry, and the OURS fix's `ours_resim_tick` count; from 11-28: R-N, "
            "the soccer lane-age Saturday re-measure)")
for p in RUNBOOKS:
    s = open(p, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in s else "\n"
    changed = False
    if RN not in s:
        anchor = nl + "## NIGHTLY CLOSE"
        assert s.count(anchor) == 1, p
        k = s.index(anchor)
        s = s[:k].rstrip("\r\n") + nl + nl + nl.join(BODY) + nl + s[k:]
        changed = True
    if NEW_OWED not in s:
        assert s.count(OLD_OWED) == 1, p
        s = s.replace(OLD_OWED, NEW_OWED)
        changed = True
    if changed:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(s)
        os.replace(tmp, p)
    print(p, "updated" if changed else "already")
