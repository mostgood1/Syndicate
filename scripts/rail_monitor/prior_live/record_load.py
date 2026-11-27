"""Record the after-midnight rail fix load (8455f25c0): deploys.md entry, lane STATUS, 11-26 findings section,
runbook R-M, and copy the readers to scripts/rail_monitor/prior_live/. .tmp then os.replace; idempotent."""
import os
import shutil

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
DEPLOYS = os.path.join(W, ".syndicate", "deploys.md")
LANES = os.path.join(W, ".syndicate", "lanes.md")
FIND = os.path.join(W, ".syndicate", "findings_2026-11-26_layer2_rail_monitor.md")
RUNBOOKS = [r"C:\tmp\railmon\MONITOR_RUNBOOK.md", os.path.join(W, "scripts", "rail_monitor", "RUNBOOK.md")]
TITLE = ("## 2026-11-27 16:29:54Z (10:29:54 AM CST 11-27) -- DEPLOY (claimed web, ff + reload-web, no env change): after "
         "midnight CT the Today rail keeps a game from the evening before that is still live (scoreboard card), `8455f25c0` "
         "(lane `layer2-rail-monitor`, user \"Yes fix it here\" + \"Yes, lend it\") -- **LOADED on web; MET**")


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
    "- betting change: no (display only: the Games rail's chip list and its date filter. No board, no row, no shortlist, nothing that places or sizes money reads `/api/board/game-chips?carry_prior_live=1`; money paths read the worker's chip artifact, never this endpoint)",
    "- **Why:** rail monitor R-L (findings 11-26). At the midnight CT roll the Today rail moved to 11-27 and Baylor @ Gonzaga / Texas Tech @ Oregon (15 rows each at 11:43 PM) had no card from 12:03 AM; 11-25 lost five (Spurs @ Trail Blazers 125 rows). The 12:43 AM reading held 0 chips, 0 board rows, 0 live-rail rows for them, while the prior-date carryover kept republishing 11-26's chips to 07:03Z.",
    "- **Change:** `/api/board/game-chips?carry_prior_live=1` adds the PRIOR Central date's LIVE chips from that date's published artifact (no inline build), tagged `carried_from_date` / `carried_onto`, when the request is for Central today, within `_layer2_carryover_max_hours` (6) of midnight, and the prior artifact is <= 900 s old. The Games rail asks with it and keeps a live chip whose `carried_onto` is its own date. Off switch `SYNDICATE_RAIL_PRIOR_DATE_LIVE_CHIPS=off` (absent = on). Other consumers (market_board.js) do not opt in and get the same response. Scoreboard only: the card has no rows, because the board's lower date bound (#779) keeps those rows off today's board on purpose.",
    "- **Loan:** `intelligence.html` (the rail date filter and the chip fetch) lent by `surface-consistency-oversight` and `ncaab-total-overprojection`, user \"Yes, lend it\" 11-27 ~9:45 AM CST (lanes.md).",
    "- **Tests:** `tests/test_board_game_chips_prior_date.py` 12 / 12; `tests/js/game_rail_prior_date_live.test.mjs` 11 / 11, of which 4 FAIL on the pre-change template; chip endpoint suites 37 / 37; rail and chip JS suites all pass (`board_chip_freshness_badge` needs an LF template: passes on an LF copy, fails on this CRLF checkout before and after).",
    "- **Ride-alongs `fe46fb249..8455f25c0`:** runtime: `syndicate/blueprints/intelligence.py` + `syndicate/templates/intelligence.html` (this change); `pipeline/board_build_process.py` (`8e2149f0f`, lane `board-split-memory-guard`, the J head-rule switch, DEFAULT OFF, absent = today's rule, queued for 12-08); `scripts/surface_consistency_check.py` (`af65dcac1`, lane `surface-consistency-oversight`, a check script, not a fleet scheduled job). J's checkout-HEAD hold was already in effect (HEAD has moved off the parent's 11-26 boot head since 17:28Z 11-26) and its window is 09-12Z, so this ff changes nothing for refresh-worker. Fleet checkout's local modifications (engines/mlb statcast features, reports/) do not overlap.",
    "- **Preflight** `--betting-change no`, 3 expect / baseline pairs (baseline read 16:29:10Z, `C:\\tmp\\railmon\\prior_live\\served_check.sh baseline`): **CLEAR 16:29:30Z**. Claim acquired 16:29:05Z.",
    "- **ff + reload:**",
    "  - `git merge --ff-only 8455f25c0` at **16:29:54Z** (`fe46fb249` -> `8455f25c0`, ancestor checked first; reflog HEAD@{16:29:54Z}).",
    "  - `RELOAD_WEB {\"elapsed_s\": 4.0, \"failures\": 0, \"state\": \"done\"}` at 16:29:58Z. Workers 707088 / 707401 -> **708246 / 708247**; master 413 unchanged.",
    "- **expect / measured** (served, 16:30:09Z, `served_check.sh after`):",
    "  - `fleet_commit` fe46fb249 -> 8455f25c0: **MET**.",
    "  - `served_page_has_railKeepsChip` 0 -> 1: **MET** (`served_page_has_carry_param` 0 -> 1 too).",
    "  - `endpoint_has_prior_date_live` 0 -> 1: **MET**, `{\"reason\": \"outside_window\", \"hours_since_midnight\": 10.5, \"added\": 0}`, correct for mid-morning; 498 chips, 0 carried, `source worker_artifact`.",
    "  - Web log 16:29:54Z on (34 lines): UNHANDLED_500 0, Traceback 0, WORKER TIMEOUT 0, TemplateSyntaxError 0, BOARD_GAME_CHIPS_PRIOR_DATE_READ_FAILURE 0.",
    "  - Live page in the built-in browser ~16:31Z: chip fetch `?date=2026-11-27&carry_prior_live=1&sports=...`, 173 rail cards, 0 console errors.",
    "- **Not yet exercised on live data:** a carried chip exists only after midnight CT with a game still live. The probe now asks with `carry_prior_live=1` too and counts a carried chip as today's, so `live_chips_without_live_card` checks it (`scripts/layer2_rail_monitor_probe.py`, this lane).",
    "- **verify:** at the 11-27 close (runbook R-M): in every probe reading after 06:00Z 11-28 while refresh-worker's `LAYER2_CARRYOVER date=2026-11-27` reports `chips_live_now` > 0, each such game appears in `teams.carried_chips` and none in `live_chips_without_live_card`. A post-roll reading where a live 11-27 game has no Today card while the 11-27 chip artifact is <= 900 s old falsifies it. No game live after midnight: N = 0, carried forward.",
    "- **Revert:** `git revert 8455f25c0` on main, then ff + reload-web; or `WEB__SYNDICATE_RAIL_PRIOR_DATE_LIVE_CHIPS=off` with a drained down/up.",
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
marker = "- **STATUS 2026-11-27 ~9:50 AM CST: after-midnight rail fix (a1), BUILDING**"
new_status = ("- **STATUS 2026-11-27 10:33 AM CST: after-midnight rail fix (a1) LOADED on web, MET** (`8455f25c0`, ff + "
              "reload-web 16:29:54Z; served page and endpoint carry it; 0 errors). Betting change no. Owed: R-M at the 11-27 "
              "close (deploys.md 2026-11-27 16:29:54Z). The loan of intelligence.html from `surface-consistency-oversight` and "
              "`ncaab-total-overprojection` ends with this load; both lanes keep their claims.")
if "after-midnight rail fix (a1) LOADED on web" in blk:
    print("lane status already there")
else:
    assert blk.count(marker) == 1
    k = blk.index(marker)
    blk = blk[:k] + new_status + nl + blk[k:]
    save(LANES, s[:i] + blk + s[j:])

s, nl = load(FIND)
sec_title = "## After-midnight rail fix loaded (10:30 AM CST 11-27; user \"Yes fix it here\", \"Yes, lend it\")"
if sec_title in s:
    print("findings already there")
else:
    sec = [
        "", sec_title, "",
        "- **What:** a game from the evening before that is still live after midnight CT keeps a SCOREBOARD card on the Today rail. `/api/board/game-chips?carry_prior_live=1` lends the prior date's live chips from its published artifact (within 6 h of midnight, artifact <= 900 s old), and the rail keeps a live chip whose `carried_onto` is its date. `8455f25c0`, display only, not a betting change. No rows: the board's lower date bound (#779) still keeps them off today's board, on purpose.",
        "- **Load:** ff + reload-web 16:29:54Z 11-27. All 3 predictions MET (commit, served rule, endpoint report `outside_window` 10.5 h); web log 0 errors; live page 173 cards, 0 console errors. deploys.md 2026-11-27 16:29:54Z.",
        "- **Owed at the 11-27 close (R-M):** the first live reading, if a game is still live after midnight tonight. The probe asks with the same parameter now.",
        "",
    ]
    save(FIND, s.rstrip("\r\n") + nl + nl.join(sec))

rm = ("**R-M. After-midnight carry (8455f25c0, loaded 11-27 16:29:54Z; deploys.md that entry).** At the 11-27 close "
      "(D = 2026-11-27, roll 06:00Z 11-28), and at each close after until it has a population:")
rm_body = [
    rm,
    "1. Check the primary tree holds the probe change (`git -C C:\\Users\\tempadmin\\Coding\\Syndicate merge-base --is-ancestor <the probe commit> HEAD`); readings before it hold `carried None`.",
    "2. `wsl -- bash /mnt/c/tmp/railmon/prior_live/read_carry.sh <D> <D+1>` (nice 19): the prior-date carryover's builds (`chips_live_now`) and D's chip publications after the roll.",
    "3. `py -3 C:\\tmp\\railmon\\prior_live\\read_carry.py <D+1>`: per reading after the roll, `carried` and `live without card`.",
    "4. MET: in every reading after the roll while `chips_live_now` > 0, each live D game is in `carried` and 0 carried games are in `live without card`. FALSIFIED: a live D game with no Today card while D's chip artifact is <= 900 s old. N = 0 (nothing live after midnight): carry R-M to the next close.",
    "5. Write the result in the lane and the day's findings; deploys.md 2026-11-27 16:29:54Z names the verify.",
]
for rb in RUNBOOKS:
    s, nl = load(rb)
    if rm in s:
        print("runbook already has R-M", rb)
        continue
    anchor = nl + "## NIGHTLY CLOSE"
    assert s.count(anchor) == 1, rb
    k = s.index(anchor)
    s = s[:k].rstrip("\r\n") + nl + nl + nl.join(rm_body) + nl + s[k:]
    save(rb, s)

dst = os.path.join(W, "scripts", "rail_monitor", "prior_live")
os.makedirs(dst, exist_ok=True)
for f in ("served_check.sh", "ridealong.sh", "ridealong2.sh", "ff_reload.sh", "after.sh", "read_carry.sh", "read_carry.py", "record_load.py"):
    tmp = os.path.join(dst, f + ".tmp")
    shutil.copyfile(os.path.join(r"C:\tmp\railmon\prior_live", f), tmp)
    os.replace(tmp, os.path.join(dst, f))
print("copied readers to", dst)
