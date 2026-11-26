"""11-25 nightly close (lean), written 11-26 ~11:35 AM CST: the DAILY SUMMARY, R-B #844's final grade (findings, todo,
deploys.md), the day log line, and R-B DONE in the runbook. Each file is read whole with newline="", its own line
ending kept, every anchor asserted once, written to .tmp and os.replace'd."""
import os

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
FIND = os.path.join(W, ".syndicate", "findings_2026-11-25_layer2_rail_monitor.md")
F844 = os.path.join(W, ".syndicate", "findings_2026-11-18_college_quote_age_text_max.md")
TODO = os.path.join(W, "docs", "ai_context", "todo.md")
DEPLOYS = os.path.join(W, ".syndicate", "deploys.md")
LOG = os.path.join(W, ".syndicate", "log", "2026-11-25.md")
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


def append(p, lines):
    s, nl = load(p)
    assert "## DAILY SUMMARY" not in s or p != FIND, "summary already present"
    s = s.rstrip("\r\n") + nl + nl + nl.join(lines) + nl
    save(p, s)


SUMMARY = [
    "## DAILY SUMMARY -- Wed 11-25 (day 11), closed 11:35 AM CST 11-26",
    "",
    "The close ran about 10.5 hours late: the 12:47 AM cron's first attempt did not finish. The Windows task took **48 "
    "readings**, every 20 min from 10:03 AM to 1:43 AM CST, with no failed tick (3 `p29` timeouts recovered on their "
    "retry). Readings covered the last 90 min of the slate. Every reading ran on fleet head `e37a9697f`. POP_START is "
    "16:00Z. Flags are graded on their first sighting against the finals by date (`C:\\tmp\\railmon\\grade_2026-11-25_out.json`). "
    "Every game was final at the grade; 10 flags were skipped (8 no chip, 2 team unmatched).",
    "",
    "### The grade",
    "",
    "| bucket | flags | games | W-L-P | hit | fair | hit - fair, 90% CI (game-clustered) |",
    "|---|---|---|---|---|---|---|",
    "| **ALL** | 550 | 91 | 281-268-1 | **0.512** | 0.481 | [-0.012, +0.075] |",
    "| P3 first reading: yes | 93 | 52 | 41-52 | 0.441 | 0.477 | [-0.131, +0.046] |",
    "| P4 fair < 0.40 | 59 | 23 | 10-49 | 0.169 | 0.232 | [-0.143, +0.039] |",
    "| P5 NCAAB full totals | 136 | 54 | 80-55-1 | 0.593 | 0.503 | [+0.002, +0.165] |",
    "| sport: NCAAB | 335 | 56 | 182-152-1 | 0.545 | 0.504 | [-0.017, +0.100] |",
    "| sport: NBA | 159 | 9 | 66-93 | 0.415 | 0.424 | [-0.068, +0.051] |",
    "| sport: WNCAAB | 24 | 9 | 16-8 | 0.667 | 0.526 | [-0.040, +0.316] |",
    "| sport: NHL | 23 | 13 | 10-13 | 0.435 | 0.477 | [-0.242, +0.141] |",
    "| sport: soccer | 9 | 4 | 7-2 | 0.778 | 0.515 | (4 games) |",
    "",
    "- **The flags beat their fair price on the point for the 8th day in a row (11-18 to 11-25), but the CI does not "
    "clear 0** after 3 days that did (11-22 to 11-24). The model's mean p was 0.584 against a 0.512 hit, ~7 pp "
    "over-confident on its own side (#847); 11-24 was ~5 pp.",
    "- **By market:** full-game totals 0.547 vs 0.475 (193 flags, CI [+0.003, +0.138], clear of 0); full-game spreads "
    "0.449 vs 0.469 (158, below fair); segment spreads 0.558 vs 0.471 (43, above fair after 4 of 5 days below); segment "
    "totals 0.518 vs 0.504 (112); moneyline 0.523 vs 0.504 (44).",
    "- **NCAAB full totals:** unders 0.620 (93 flags), overs 0.535 (43). The flagged lines went over 59 of 136.",
    "- **NBA** was the drag: 159 flags in 9 games at 0.415 vs 0.424. Its calibrated or scaled live totals went 0.395 vs "
    "0.436 (86 flags, CI [-0.121, +0.045]). The NBA live total anchor (#834) loaded 11-24; its Kalshi re-check is "
    "registered by lane `engine-learner` (12-01).",
    "- **NHL** had 23 flags in 13 games (1 flag on 11-24, a smaller slate), 0.435 vs 0.477, within noise.",
    "",
    "### Pre-registered verdicts (standing P1-P6, P8)",
    "",
    "| # | prediction | result | verdict |",
    "|---|---|---|---|",
    "| P1 | 0 rail-card contradictions | 1 recorded (R20, Liberty @ Princeton), reclassified as two ticks of one re-sim "
    "(`ours_resim_tick`, section above); 1 skew-consistent (R35 Omaha @ UC Davis u159.5, OURS = own 162.4) | **MET** (0 real) |",
    "| P2 | board publication gap median <= 600 s, none > 1,800 s, 5:30-10:30 PM | 44 publications, median **361 s**, "
    "max 628 s (7:50 PM), 5 over 600 s (`p2_boardpub.py`) | **MET** (11-24: median 314 s, max 536 s, 0 over 600 s) |",
    "| P3 | first-reading flags at or below fair | 0.441 vs 0.477, -3.6 pp, CI [-0.131, +0.046] | **MET** (below fair, within noise) |",
    "| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.169 vs 0.232, 59 flags, 23 games | **MET** |",
    "| P5 | report NCAAB calibrated live full totals | 136 flags / 54 games, 0.593 vs 0.503; under 93 (0.620) / over 43 "
    "(0.535); the flagged lines went over 59 of 136 | report |",
    "| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 48 readings | **MET** |",
    "| P8 | score floor: 0 college calibrated full totals below the score | **1 of 2,793** rows, R12 (1:43 PM), N Colorado "
    "@ Detroit Mercy o175.5, `live_total` 175.1 with 176 scored | **timing, not the floor** |",
    "",
    "- **P8's row:** the chip read H2 0:00 (end of regulation), and its own newer re-sim (as of 19:41:12Z) had a final "
    "total of 176.6, at the score. So the row was priced from a re-sim older than the last basket, the 11-20 pattern. "
    "The game had **0 live bets** (`live_bets_for.py \"Detroit Mercy\"`). `ours_below_points` (#824) was 1 at R28 and 1 at R36.",
    "",
    "### Fleet-watcher flags and owned readings",
    "",
    "- **R8 (12:23 PM), overlay gap 1,009 s, WNCAAB: reclassified QUIET** (idle between games). `d4metrics.py` now counts "
    "such a gap as quiet (section above).",
    "- **R20 (4:23 PM), `ours_contradictions=1`, Liberty @ Princeton o134.5: reclassified `ours_resim_tick`** (the row and "
    "the chip were adjacent ticks of one re-sim). `dash_update.py` counts it apart (section above). The card's own "
    "mismatch (LEAD 2) is a user decision, below.",
    "- **R-H (#860, CHANGE M), 7:12 PM: MET.** St. Louis read 2 of 2 rows with a live model at STL @ NYI, like every live "
    "NHL game (section above; deploys.md 2026-11-26 01:12Z).",
    "- **R-B (#844, CHANGE D): P2 and P3 PREDICTED; #844 is graded** (deploys.md 2026-11-26 17:35Z). NCAAB moneyline rows "
    "fresh by row age 274 of 352 (77.8%) over 43 distinct grids, equal to fresh by cell (77.8%), 0 mismatch rows (11-19: "
    "31.2% vs 80.1%, 304 mismatches). NBA mismatch 0 over 48 samples. P1 PREDICTED again (1,053 of 2,696 venue rows). "
    "P4 stays NEITHER (11-25 interim).",
    "",
    "### What the day found",
    "",
    "- **Change G (#854, the I-29 orientation join) held for a 2nd evening.** 12 of the 15 college games whose lane was "
    "REVERSED carried a live model, at 62 of 74 game-readings (11-24: 9 of 10). The 3 that never did: 2 WNCAAB "
    "`no_margin_anchor` (Grand Canyon @ Winthrop, James Madison @ Arkansas) and Saint Louis @ Stanford `no_plays` (2 readings).",
    "- **Games with no live model, as unique games: 60** (38 on 11-24). Mostly deliberate or by design: "
    "`key_player_out` 12, `competition_not_modelled` 9 (soccer), `in_intermission` 5, `no_plays` 4, "
    "`resimmed_model_by_helper_read` 9. `not_in_resim` 6, each for one reading (games tipping after the snapshot). "
    "`resimmed_no_row_model` 3, each for one reading (Albany @ Syracuse, Cavaliers @ Knicks, Norfolk St @ NC State), "
    "so not persistent.",
    "- **R46 (1:03 AM), one 665 s NCAAB overlay gap.** It was on the **11-26** overlay file, which held 7 in-play rows "
    "of the late 11-25 games (Incarnate Word @ Hawai'i, Saint Louis @ Stanford, Clemson @ Colorado St) after the "
    "midnight roll. This is R-J's evening UTC/Central split, seen in NCAAB. Change O moved only soccer's shard. "
    "**Lead, no owner** (lane `evening-utc-date-split` closed 11-25): one gap at 1 AM, cost not measured.",
    "- **Sweeps refused fell to 139 of 499 (28%)**, all `lane_busy`; 11-24 had 193 of 473 (41%) by the same row sum.",
    "- **Dark rows: 18 at 6 readings, all `board_cadence`** (rows aged from the board build, by design).",
    "- NHL odds child age max 219 s (limit 600 s). 0 false flags, 0 missed flags.",
    "",
    "### Loads (11-25 slate)",
    "",
    "- **7:54 AM:** web: quiet-worker memory watch on by default (`e37a9697f`, lane `web-silent-worker-kills`; not a "
    "betting change). The `/ops/dashboards` hub and cheat-sheet rules v4 (display only) rode along. Nothing else loaded.",
    "",
    "### Open user decisions",
    "",
    "- **Rail card OURS for a flagged total** (asked 11-25 4:40 PM CST, unanswered): show the flagged row's own "
    "`live_total` beside its probability (a web change plus reload-web, not a betting change), or leave the card as is. "
    "It is about 0.7% of college total flags.",
    "- **Close lane `nhl-live-join-stl-alias` and todo #860** (asked 11-25 7:15 PM CST after R-H MET, unanswered).",
    "- The next betting-change window is 12-08.",
]
append(FIND, SUMMARY)

# R-B final section in the #844 findings
F844_SEC = [
    "## READING 2026-11-26 11:35 AM CST: the 11-25 evening, rail monitor R-B; FINAL (P2, P3 graded)",
    "",
    "Reader: `C:\\tmp\\railmon\\p844_2026-11-25.jsonl`, written by `p844.sh` at every Windows-task tick, 48 NCAAB and 48 "
    "NBA samples, 16:04Z 11-25 to 07:44Z 11-26. After midnight the 11-25 NCAAB grid stopped rebuilding at 06:02Z, so the "
    "last 6 samples read one grid: the NCAAB sums below count each distinct grid once (43 of 48). Read-only.",
    "",
    "| # | prediction | 11-19 baseline | 11-25 | verdict |",
    "|---|---|---|---|---|",
    "| P1 | venue rows with a sportsbook-spelled `updated_at` > 0 | 22 of 1,213 (1.8%) | 1,053 of 2,696 venue rows, "
    "> 0 in 42 of 48 samples | **PREDICTED** |",
    "| P2 | h2h rows fresh by row age >= 70% over the evening, near fresh-by-cell | 44 of 141 (31.2%) vs 80.1% by cell; "
    "304 mismatch rows | **274 of 352 (77.8%)**, cell 274 of 352 (77.8%), **0 mismatch** rows over 43 grids | **PREDICTED** |",
    "| P3 | NBA / NHL grids unchanged | NBA mismatch 0 | NBA mismatch 0 over 48 samples (22 with rows, 63 h2h rows) | "
    "**PREDICTED** (NBA; NHL is not sampled) |",
    "| P4 | NCAAB / WNCAAB stale-quote withholds per build fall | -- | 11-24 (interim above) | **NEITHER** |",
    "",
    "- **#844 does what it was built for.** The row's age now reads the newest stamp by time: fresh by row and fresh by "
    "cell agree on every row (0 mismatches), against 304 mismatches on 11-19.",
    "- P4 was never #844's own test (the join's ceiling is per quote), and its two halves split by sport.",
    "- Recorded in deploys.md 2026-11-26 17:35Z (betting change: no) and todo #844.",
]
append(F844, F844_SEC)


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


s, nl = load(TODO)
s = insert_after_line(
    s, nl, "### `#844` \u2014 **COLLEGE LIVE QUOTES READ STALE", "- **READ 2026-11-25 ~1:10 AM CST (rail monitor R-B), INTERIM:**",
    "- **READ 2026-11-26 11:35 AM CST (rail monitor R-B), FINAL, over the 11-25 evening:** P2 **PREDICTED**: NCAAB "
    "moneyline rows fresh by row age 274 of 352 (77.8%) over 43 grids, equal to fresh by cell, 0 mismatch rows (11-19: "
    "31.2% vs 80.1%, 304 mismatches). P3 **PREDICTED**: NBA mismatch 0 over 48 samples (NHL not sampled). P1 PREDICTED "
    "again (1,053 of 2,696 venue rows). P4 NEITHER (interim). Verdict: #844's own test (P1, P2) is met. deploys.md "
    "2026-11-26 17:35Z; `.syndicate/findings_2026-11-18_college_quote_age_text_max.md`. Closing #844 belongs to lane "
    "`ncaab-total-overprojection`.")
save(TODO, s)

DEP = [
    "## 2026-11-26 17:35Z (11:35 AM CST) -- READING (no deploy): #844 book-grid newest stamp by time, the 11-25 evening "
    "(CHANGE D of the 11-24 window batch; lane `ncaab-total-overprojection`, read by lane `layer2-rail-monitor`, R-B; "
    "read-only) -- **P1-P3 PREDICTED, P4 NEITHER; FINAL**",
    "- betting change: no",
    "- **Load:** CHANGE D of the 2026-11-24 08:30:10Z window batch (register BC-062), `SYNDICATE_BOOK_GRID_NEWEST_BY_TIME=on`.",
    "- **Reader:** `C:\\tmp\\railmon\\p844_2026-11-25.jsonl` (`p844.sh` at every Windows-task tick; 48 NCAAB + 48 NBA "
    "samples, 16:04Z 11-25 to 07:44Z 11-26). NCAAB sums count each distinct grid once (43 of 48; the 11-25 grid stopped "
    "rebuilding at 06:02Z after the midnight roll).",
    "- **P1:** 1,053 of 2,696 venue rows carry a sportsbook-spelled stamp, > 0 in 42 of 48 samples (11-19: 22 of 1,213). PREDICTED.",
    "- **P2:** NCAAB moneyline rows fresh by row age 274 of 352 (77.8%), fresh by cell 274 of 352 (77.8%), 0 mismatch "
    "rows (11-19: 31.2% vs 80.1%, 304 mismatches over 22 samples). PREDICTED.",
    "- **P3:** NBA mismatch 0 over 48 samples (22 with rows). PREDICTED. NHL is not sampled.",
    "- **P4:** NEITHER (the 11-25 1:10 AM interim, in the findings).",
    "- **Action:** none. Closing #844 belongs to lane `ncaab-total-overprojection`.",
    "- verify: `p844_2026-11-25.jsonl`, NCAAB `h2h_row_fresh` 274 = `h2h_cell_fresh` 274 of `h2h` 352 and `mismatch` 0 "
    "over 43 distinct `grid_generated_at`.",
]
s, nl = load(DEPLOYS)
s = s.rstrip("\r\n") + nl + nl + nl.join(DEP) + nl
save(DEPLOYS, s)

s, nl = load(LOG)
s = s.rstrip("\r\n") + nl + nl + nl.join([
    "## 11:35 AM CST 11-26 -- lane layer2-rail-monitor: 11-25 nightly close (lean, ~10.5 h late)",
    "- 48 readings, no failed tick. ALL 550 flags / 91 games 0.512 vs fair 0.481, CI [-0.012, +0.075] (does not clear 0 "
    "after 3 days that did). P1 MET (R20 reclassified re-sim tick), P2 MET (median 361 s, max 628 s), P3, P4, P6 MET, "
    "P8 1 row = timing. R-H #860 MET; R-B #844 P2/P3 PREDICTED, graded. Lead: a 665 s NCAAB overlay gap on the 11-26 "
    "file after the midnight roll (no owner). Open: the rail card OURS fix and closing nhl-live-join-stl-alias. "
    "Findings: `.syndicate/findings_2026-11-25_layer2_rail_monitor.md` DAILY SUMMARY.",
]) + nl
save(LOG, s)

s, nl = load(RUNBOOK)
old = "**R-B. #844 newest-stamp-by-time"
if s.count(old) == 0 and "**R-B. DONE 11-26" in s:
    print("runbook already marked"); raise SystemExit(0)
assert s.count(old) == 1, s.count(old)
s = s.replace(old, "**R-B. DONE 11-26 11:35 AM CST: P1-P3 PREDICTED, P4 NEITHER, graded (deploys.md 2026-11-26 17:35Z; "
                   "the 11-25 close). #844 newest-stamp-by-time", 1)
save(RUNBOOK, s)
