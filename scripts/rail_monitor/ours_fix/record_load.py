"""Record the rail card OURS fix load (fe46fb249): deploys.md entry, lane STATUS, 11-26 findings section, and copy the
readers to scripts/rail_monitor/ours_fix/. .tmp then os.replace; idempotent."""
import os, shutil

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
DEPLOYS = os.path.join(W, ".syndicate", "deploys.md")
LANES = os.path.join(W, ".syndicate", "lanes.md")
FIND = os.path.join(W, ".syndicate", "findings_2026-11-26_layer2_rail_monitor.md")
TITLE = ("## 2026-11-27 04:39:59Z (10:39:59 PM CST 11-26) -- DEPLOY (claimed web, ff + reload-web, no env change): the rail "
         "card shows a flagged full-game total's OWN live total as OURS, `fe46fb249` (lane `layer2-rail-monitor`, user "
         "\"Yes, fix it here\" + \"Yes, lend it\") -- **LOADED on web; MET**")


def load(p):
    s = open(p, encoding="utf-8", newline="").read()
    return s, ("\r\n" if "\r\n" in s else "\n")


def save(p, s):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    os.replace(tmp, p)
    print("wrote", p)


entry = [
    TITLE,
    "- betting change: no (display only: `liveRailSummary`'s OURS string and its tooltip; the flag rule, `freshEdges` and every row are untouched, and nothing that places or sizes money reads the rail card)",
    "- **Why:** 11-25 R20, Liberty @ Princeton o134.5 p 0.59: the flagged row's own live total was 137.7, while the card's OURS showed the chip's PROJ box, 134.3, from the next re-sim tick (2.5 s newer). OURS and the flag sat on opposite sides of the line. Over 11-15..11-25, 11 of 1,483 college full-game total flags (0.7%) were this case (findings 11-25, `ours_resim_tick`).",
    "- **Change:** a FLAGGED, uncalibrated FULL-GAME total's OURS is the flagged row's own `live_total`; when the PROJ box differs to one decimal, the tooltip says so (\"The PROJ box shows X, from another re-sim tick\"). Unflagged lines, calibrated college totals and intervals (the 11-11 decision) are unchanged. 12 new assertions in `tests/js/games_rail_live_lines.test.mjs`, 5 of which fail on the old template; 134 / 134 pass, `test_college_calibrated_total_display.py` 25 / 25, `test_layer2_live_rail_edges.py` 4 / 4, `board_rail_sport_and_fold.test.mjs` all.",
    "- **Loan:** the totals OURS line is lane `ncaab-total-overprojection`'s claim, lent to this lane by the user (\"Yes, lend it\", 11-26 ~9:58 PM CST; main `20634ff89`).",
    "- **Ride-alongs `b709934b2..fe46fb249`:** runtime code is `syndicate/templates/intelligence.html` only (this change). Also `tests/js/games_rail_live_lines.test.mjs` (this change), `tests/test_web_draining_worker.py` (`f9b72e447`, lane `web-silent-worker-kills`, tests only) and `.syndicate/lanes.md`. No overlap with the fleet checkout's locally modified files (reports/, engines/mlb statcast features, untracked data/).",
    "- **Order:** held until lane `web-silent-worker-kills` loaded `b709934b2` (gunicorn.conf.py) to its exact SHA (04:35:28Z) and released the web claim (04:38:28Z), so neither load carried the other's change.",
    "- **Preflight** `--betting-change no`, 3 expect / baseline pairs (baseline read 04:39:28Z, `C:\\tmp\\railmon\\ours_fix\\served_check.sh baseline`): **CLEAR 04:39:42Z**. Claim acquired 04:39:18Z.",
    "- **ff + reload:**",
    "  - `git merge --ff-only fe46fb249` at **04:39:58Z** (`b709934b2` -> `fe46fb249`, ancestor checked first).",
    "  - `RELOAD_WEB {\"elapsed_s\": 2.0, \"failures\": 0, \"state\": \"done\"}` at 04:39:59Z. Workers 266330 / 266831 -> **267022 / 267023**; master 413 unchanged.",
    "- **expect / measured** (served, 04:40:09Z, `served_check.sh after`):",
    "  - `fleet_commit` b709934b2 -> fe46fb249: **MET**.",
    "  - `served_page_has_flaggedOwn` 0 -> 1: **MET**.",
    "  - `served_page_has_tooltip` 0 -> 1: **MET**.",
    "  - Web log 04:39:59-04:40:52Z (32 lines): UNHANDLED_500 0, Traceback 0, WORKER TIMEOUT 0, TemplateSyntaxError 0.",
    "  - Live page in the built-in browser, ~04:41Z: 79 rail cards, 5 OURS cells, 0 console errors. The one flag up was a 2H spread.",
    "  - The served page's own rail code (`read_ours_fix.py`, the probe's runner) over the 04:03:10Z reading: 1 flagged uncalibrated full-game total (TCU @ Texas Tech o70.5), OURS 73.4 == own 73.4. Over the 04:23:05Z reading: none.",
    "- **Thin population, said plainly:** no flagged total had its PROJ box a tick away from its row at load time, so the new branch's different answer was exercised only by the unit test, not on the served rail. It is a ~0.7% case.",
    "- **verify:** at the nightly closes, the monitor's `ours_resim_tick` count (dash_update `classify_ours`) reads 0 on every reading after 04:39:59Z 11-27. One flagged total whose card OURS differs from its own row's `live_total` after that instant falsifies it.",
    "- **For lane `web-silent-worker-kills`:** this reload retired workers 266330 / 266831 at 04:39:59Z, 4.5 min after your load.",
    "- **Revert:** `git revert fe46fb249` on main, then ff + reload-web.",
]
s, nl = load(DEPLOYS)
if TITLE in s:
    print("deploys entry already there")
else:
    save(DEPLOYS, s.rstrip("\r\n") + nl + nl + nl.join(entry) + nl)

s, nl = load(LANES)
head = "### layer2-rail-monitor \u2014 OPEN \u2014 opened 2026-11-15"
i = s.index(head)
j = s.find(nl + "### ", i + 1)
j = len(s) if j < 0 else j
blk = s[i:j]
marker = "- **STATUS 2026-11-26 ~10:00 PM CST: rail card OURS fix, BUILDING**"
new_status = ("- **STATUS 2026-11-26 10:40 PM CST: rail card OURS fix LOADED on web, MET** (`fe46fb249`, ff + reload-web "
              "04:39:59Z 11-27; served page carries the branch; 0 errors). Betting change no. Owed: `ours_resim_tick` stays 0 "
              "at the nightly closes (deploys.md 2026-11-27 04:39:59Z). The loan from `ncaab-total-overprojection` ends with "
              "this load; that lane keeps its claim.")
if "rail card OURS fix LOADED on web" in blk:
    print("lane status already there")
else:
    assert blk.count(marker) == 1
    k = blk.index(marker)
    blk = blk[:k] + new_status + nl + blk[k:]
    save(LANES, s[:i] + blk + s[j:])

s, nl = load(FIND)
sec_title = "## Rail card OURS fix loaded (10:40 PM CST; user \"Yes, fix it here\", \"Yes, lend it\")"
if sec_title in s:
    print("findings already there")
else:
    sec = [
        "", sec_title, "",
        "- **What:** a flagged full-game total's OURS on the rail card is now the flagged row's own live total, not the chip's PROJ box, which can be one re-sim tick apart (11-25 R20). The tooltip names the box's number when they differ. `fe46fb249`, display only, not a betting change.",
        "- **Load:** ff + reload-web at 04:39:59Z 11-27, after lane `web-silent-worker-kills` loaded `b709934b2` to its exact SHA. Served page carries the branch; web log 0 errors; live page 0 console errors. deploys.md 2026-11-27 04:39:59Z.",
        "- **Owed at the closes:** `ours_resim_tick` reads 0 on every reading after the load. No flagged total was a tick apart from its row at load time, so only the unit test exercised the new answer.",
        "",
    ]
    save(FIND, s.rstrip("\r\n") + nl + nl.join(sec))

dst = os.path.join(W, "scripts", "rail_monitor", "ours_fix")
os.makedirs(dst, exist_ok=True)
for f in ("read_ours_fix.py", "served_check.sh", "weblog_check.sh", "record_load.py"):
    tmp = os.path.join(dst, f + ".tmp")
    shutil.copyfile(os.path.join(r"C:\tmp\railmon\ours_fix", f), tmp)
    os.replace(tmp, os.path.join(dst, f))
print("copied readers to", dst)
