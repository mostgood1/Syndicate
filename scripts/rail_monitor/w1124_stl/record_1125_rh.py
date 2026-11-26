"""Record R-H (#860 St. Louis live join) in lanes.md, todo.md, deploys.md, the 11-25 findings and the runbook.
Every file is read whole with newline="", its own line ending kept, each anchor asserted once, written to .tmp, os.replace."""
import os

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
LANES = os.path.join(W, ".syndicate", "lanes.md")
TODO = os.path.join(W, "docs", "ai_context", "todo.md")
DEPLOYS = os.path.join(W, ".syndicate", "deploys.md")
FIND = os.path.join(W, ".syndicate", "findings_2026-11-25_layer2_rail_monitor.md")
RUNBOOK = r"C:\tmp\railmon\MONITOR_RUNBOOK.md"


def load(p):
    s = open(p, encoding="utf-8", newline="").read()
    return s, ("\r\n" if "\r\n" in s else "\n")


def save(p, s):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    os.replace(tmp, p)
    print("wrote", p)


def insert_after_line(s, nl, block_head, anchor_prefix, new_line):
    i = s.index(block_head)
    assert s.count(block_head) == 1, block_head
    j = s.find(nl + "### ", i + 1)
    j = len(s) if j < 0 else j
    blk = s[i:j]
    k = blk.find(nl + anchor_prefix)
    assert k >= 0 and blk.count(nl + anchor_prefix) == 1, (block_head, anchor_prefix)
    e = blk.find(nl, k + len(nl))
    e = len(blk) if e < 0 else e
    blk = blk[:e] + nl + new_line + blk[e:]
    return s[:i] + blk + s[j:]


# 1. lanes.md: READING line in lane nhl-live-join-stl-alias, after its LOADED line
s, nl = load(LANES)
s = insert_after_line(
    s, nl, "### nhl-live-join-stl-alias \u2014 OPEN \u2014 opened 2026-11-21", "- LOADED 2026-11-24 08:30:37Z",
    "- READING 2026-11-26 01:12:00Z (7:12 PM CST 11-25), lane layer2-rail-monitor (R-H), read-only at nice 19, "
    "STL @ NYI P2 18:48 0-0: **MET**. `kit_after_up_stl.sh`: key `on` in refresh-worker and web; "
    "`St Louis Blues @ New York Islanders h2h/puck rows 2, with a live model 2` (NYR @ BUF 3 of 3, VAN @ DET 1 of 1, "
    "WPG @ BOS 1 of 1; 11-21 before the fix 0 of 1). Full NHL grid 01:11:50Z: St. Louis like every live NHL game, the "
    "moneyline priced by the live lane (p 0.490, 200 sims, as of 01:10:42Z) and the puck line display-only. Not join "
    "misses: 01:07Z first intermission (P1 0:00; the rail showed only an STL total, refused by design), and 01:11:31Z the "
    "moneyline quote over the 120 s pricing ceiling (`quote_older_than_live_pricing_ceiling`), fresh (6.2 s) by 01:11:50Z. "
    "Closing this lane is the user's call (asked 11-25 ~7:15 PM CST). deploys.md 2026-11-26 01:12Z; "
    "findings_2026-11-25_layer2_rail_monitor.md.")
save(LANES, s)

# 2. todo.md: the #860 entry
s, nl = load(TODO)
s = insert_after_line(
    s, nl, "### `#860` \u2014 **EVERY ST. LOUIS BLUES GAME MISSES ITS NHL LIVE LANE", "- **11-24: no St. Louis Blues game**",
    "- **11-25 7:12 PM CST (01:12:00Z 11-26): READING MET** at STL @ NYI (P2 18:48): the kit read St. Louis 2 of 2 rows "
    "with a live model, like every other live NHL game (11-21: 0 of 1); on the full grid the moneyline is priced by the "
    "live lane and the puck line is display-only, as on every game. Two not-misses: the first intermission at 01:07Z, and "
    "a moneyline quote over the 120 s ceiling at 01:11:31Z (fresh 19 s later). Closing lane `nhl-live-join-stl-alias` "
    "(and this item) is the user's call. deploys.md 2026-11-26 01:12Z; `.syndicate/findings_2026-11-25_layer2_rail_monitor.md`.")
save(TODO, s)

# 3. deploys.md: one READING entry at the end
s, nl = load(DEPLOYS)
entry = [
    "## 2026-11-26 01:12Z (7:12 PM CST 11-25) -- READING (no deploy): #860 NHL St. Louis live join, first live Blues "
    "game STL @ NYI (CHANGE M of the 11-24 window batch; lane `nhl-live-join-stl-alias`, read by lane "
    "`layer2-rail-monitor`, R-H; read-only, nice 19) -- **MET**",
    "- betting change: no",
    "- **Load:** CHANGE M of the 2026-11-24 08:30:10Z window batch (register BC-069). `SYNDICATE_LIVE_GAMELINE_NHL_TEAM_ALIASES=on` "
    "in refresh-worker and web, re-read 01:07:15Z and 01:12:00Z.",
    "- **Readers:** the registered kit `C:\\tmp\\w1124_stl\\kit_after_up_stl.sh` (the served rail), plus `grid_1125_rh.py` "
    "(the full NHL book grid per market, since the rail is a capped selection). Outputs `watch_1125_rh.out` and "
    "`watch2_1125_rh.out` in the same folder.",
    "- **Kit at read_at 2026-11-26T01:12:00Z:**",
    "  - New York Rangers @ Buffalo Sabres: h2h/puck rows 3, with a live model 3",
    "  - **St Louis Blues @ New York Islanders: h2h/puck rows 2, with a live model 2**",
    "  - Vancouver Canucks @ Detroit Red Wings: h2h/puck rows 1, with a live model 1",
    "  - Winnipeg Jets @ Boston Bruins: h2h/puck rows 1, with a live model 1",
    "- **Grid at 01:11:50Z:** each of the 10 live games carries `live_gameline` on its full-game rows, with the "
    "moneyline priced by the live lane and the puck line `live_margin_published_for_display_only`. St. Louis matches: "
    "2 rows, 2 joined, moneyline p 0.490 vs market 0.5256, 200 sims, as of 01:10:42Z.",
    "- **Before the fix (11-21 6:43 PM CST):** St. Louis 0 of 1, every other game all.",
    "- **Not join misses:**",
    "  - 01:07Z: first intermission (`P1 0:00`). The rail showed only an STL total, which NHL refuses by design.",
    "  - 01:11:31Z, 1:12 into P2: the moneyline quote was over the 120 s pricing ceiling "
    "(`quote_older_than_live_pricing_ceiling`). It was fresh (6.2 s) by 01:11:50Z.",
    "- **Action:** none. Closing the lane is the user's call; asked.",
    "- verify: the kit line `St Louis Blues @ New York Islanders h2h/puck rows 2, with a live model 2` at read_at "
    "2026-11-26T01:12:00Z.",
]
s = s.rstrip("\r\n") + nl + nl + nl.join(entry) + nl
save(DEPLOYS, s)

# 4. findings: a short section
s, nl = load(FIND)
sec = [
    "",
    "## R-H: #860 St. Louis live join at STL @ NYI (7:12 PM CST); read-only, nice 19 -- MET",
    "",
    "- **MET.** The kit (`C:\\tmp\\w1124_stl\\kit_after_up_stl.sh`, read_at 2026-11-26T01:12:00Z) read `St Louis Blues @ "
    "New York Islanders h2h/puck rows 2, with a live model 2`, like every other game on the rail (NYR @ BUF 3 of 3, "
    "VAN @ DET 1 of 1, WPG @ BOS 1 of 1). On 11-21, before the fix, St. Louis read 0 of 1. The key is `on` in "
    "refresh-worker and web.",
    "- **The full grid agrees (01:11:50Z, `grid_1125_rh.py`).** Each of the 10 live NHL games joins its live lane on its "
    "full-game rows: the moneyline is priced by the lane and the puck line is display-only. St. Louis is the same: "
    "moneyline p 0.490 vs market 0.5256, 200 sims, as of 01:10:42Z.",
    "- **Two reads earlier were not join misses.**",
    "  - 01:07Z: STL @ NYI was in the first intermission (`P1 0:00`), and the rail showed only an STL total, which NHL "
    "refuses by design.",
    "  - 01:11:31Z, 1:12 into P2: both STL rows had joined (live display lane `live`), but the moneyline quote was over "
    "the 120 s pricing ceiling (`quote_older_than_live_pricing_ceiling`). It was fresh (6.2 s) by 01:11:50Z.",
    "- Recorded in lane `nhl-live-join-stl-alias`, todo `#860` and deploys.md 2026-11-26 01:12Z. Closing the lane is the "
    "user's call.",
    "",
]
s = s.rstrip("\r\n") + nl + nl.join(sec)
save(FIND, s)

# 5. runbook: R-H DONE
s, nl = load(RUNBOOK)
old = "**R-H. #860 St. Louis live join"
assert s.count(old) == 1, s.count(old)
s = s.replace(old, "**R-H. DONE 11-25 7:12 PM CST: MET (St. Louis 2 of 2 rows with a live model, like every live NHL game; "
                   "deploys.md 2026-11-26 01:12Z; closing the lane is the user's call). #860 St. Louis live join", 1)
save(RUNBOOK, s)
