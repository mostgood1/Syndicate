# state — layer2

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [layer2-board-keyvalue-ceiling] THE BOARD'S CEILING IS THE COMBINED KEY, NOT THE SHARDS — and `per_sport=3000` corrupted production for ~29 min `[verified 2026-08-31 18:25-20:0xZ, lane layer2-cap-raise]`

**Rows are sharded per sport and the merge SERVES the board.** `combined_keeps_rows=False`
on the writer while web served 1,634 rows — an empty combined key cannot otherwise
yield rows. Board 932 → 1,634 at `per_sport=1000`.

**`per_sport=3000` BROKE IT.** The combined key carries card/metadata that scales at
~2,200 B/row **even with `rows: []`** (3,754,595 B at 1,634 rows; 9,648,192 B at
4,552). The write refused at `9,648,192 > 8,388,608` **after the shards had already
landed**, freezing `shard_row_total=1635`; the merge then dropped
`unplaceable=2917` rows and **all of NCAAF**, for ≥3 cycles. It does not self-heal.
So the ceiling is **~3,600 TOTAL rows**, not per-sport, and shard headroom says
nothing about it.

**Live config (refresh-worker only):** `SYNDICATE_LAYER2_ROWS_PER_SPORT=1000`,
`SYNDICATE_LAYER2_ROWS_TOTAL=3000`, `SYNDICATE_LAYER2_COMBINED_ROWS=0`. Web and
live-odds-worker carry NO `LAYER2` keys. **`ROWS_TOTAL=3000` is UNEXERCISED** —
today's board is ~1,600 rows, so it has never bound.

**Fixed and live** (`865c89be` 19:46:59Z, still in live `132559e1`): the merge sizes
from `max(index_total, highest_position+1)`, so a refused write leaves the board
STALE not WRONG, and `written_at` comes from the shards when stamps disagree —
without that the corrupted board reported `18:02:05Z` while serving 18:25 rows and
was **unfalsifiable** to any watcher keyed on `written_at`.

**THE FLIP IS VERIFIED IN PRODUCTION `[2026-08-31 22:50:26Z]`.** `cards` split into
per-sport keys makes the combined key FLAT in row count (451 → **0 B/row**,
measured on the real writer). `SYNDICATE_LAYER2_CARDS_INLINE=0` is live on
refresh-worker `7e678674`; web `7e678674` was deployed FIRST and its deployed SHA
confirmed to contain `_hydrate_layer2_cards` (it had ZERO an hour earlier — that
gate prevented a silent `cards_present=0`). Two clean pre-flip cycles passed
(1468==rows, 1498==rows, three sports each).

**EXERCISED AND PASSED** on the first rebuild under the flip: `combined_keeps_cards=False`
with `cards_present=2216 == rows`, all three sports — the writer stopped filling the
combined key AND web served every card back from the shards. The combined key is now
FLAT in row count, so the ~3,600-row ceiling that made `per_sport=3000` corrupt the
board is GONE. **A cap raise is now defensible but UNATTEMPTED, and must be measured
against the COMBINED key, not the shards** — that mistake caused the 18:25Z incident.
The 1534 → 2216 row change is SLATE (soccer 187 → 834), not headroom. **REVERT:** set
`SYNDICATE_LAYER2_CARDS_INLINE=1` and redeploy.

**CAPS NOW STAGED AT 2000/6000, NOT DEPLOYED `[2026-09-01 01:3xZ]`.**
`SYNDICATE_LAYER2_ROWS_PER_SPORT=2000` + `ROWS_TOTAL=6000` are SET on
refresh-worker but the live SHA `6d024dc7` predates them; the 75% warn threshold
(`c461693e`) is on main and also undeployed. Both apply on the next
refresh-worker deploy by anyone. **MEASURED SAFE against REAL production rows —
combined key 220 B (0.0%), worst shard 50.6–55.2%** — which is the check that was
skipped before the 18:25Z incident. **UNTESTED AND UNTESTABLE TONIGHT: the board
is MLB-ONLY at ~547 rows** (slates finished; `LAYER2_BOARD_HEALTH` 01:14:48Z mlb
547, ncaaf 0, soccer 0), so nothing approaches even the OLD 1000 cap. Verifiable
only on a full multi-sport slate. **Two caveats:** the shard percentage is
SLATE-DEPENDENT (same config read 55.2% on a three-sport board, 50.6% on tonight's),
and 3000/sport sits at 74.6% — just UNDER the 75% line, so the warning is NOT a
guard against a 3000 raise.

**ALL THREE INCIDENT DEFECTS ARE CLOSED AND VERIFIED `[2026-09-01 00:15Z]`:** (1) the
refused write that left CORRUPTION not staleness — `865c89be`; (2) the shed that could
not shrink the combined key — cards split + flip; (3) the size instrument that measured
a payload nothing writes — `6d024dc7`, live 23:41:30Z on refresh-worker.
`SHORTLIST_PERSIST_LARGE` is GONE; `LAYER2_KEY_LARGE` reports **one number per KEY** and
names the lever that matches whichever key is biggest. Verified over two builds
(23:54:28Z, 00:15:02Z): both counters 0, `cards_present == rows`. Before the fix it fired
on EVERY build at `88.5 → 90.6 → 116.8 → 122.5` pct on a healthy board, advising a cap
that was not the constraint. **Do not act on any surviving reference to
`SHORTLIST_PERSIST_LARGE`; it no longer exists.** `openings` needs no split — `openings_index` never reaches the artifact.

**The board is GROUPED BY SPORT and always was** (FLOOR-THEN-MERIT, `layer2_board.py:2744`,
`4ef894e3`/#524) — NOT a sharding artifact. Reading `rows[:25]` reads the top of the
FIRST SPORT, not the board.

## [layer2-realized-accuracy] THE LAYER 2 BOARD'S REALIZED ACCURACY — the portfolio book is the surface, and the measurement chain is broken in four places `[verified 2026-08-31T17:3x-18:0xZ, lane layer2-accuracy-audit]`

**START HERE FOR ANY BOARD-ACCURACY QUESTION, NOT AT THE EVALUATION LEDGER.**
`pipeline/portfolio_commit.py:357` commits BOTH the paper and live portfolios
straight off `read_layer2_shortlist`, so `/api/portfolio/paper?date=` and
`/api/portfolio/live` are direct measurements of this board. The evaluation
ledger is the learning loop's INPUT, not the accuracy surface, and it currently
settles 0.2% (19,692 settleable, 35 settled).

**7 days, 2026-08-24..08-30, by bet type (paper):** game_line 142 settled 56.7%
**+25.3% ROI [95% CI +7.2..+43.4]** — the only bucket excluding zero;
game_total 141 / 47.5% / +9.8% [-9.3..+29.0]; player_prop 119 / 37.8% /
**-13.5%** [-33.5..+6.5]. **REAL MONEY INVERTS game_line:** h2h+spreads
12W-23L = **34.3% win, -23.9% ROI**. By sport (paper): mlb 375 settled (93% of
all), wnba 22, soccer 5, nfl 0, **ncaaf 0 — never bet, ever**.

**FOUR BROKEN LINKS, each measured, working backward from the board:**
1. **Board retention is ~4 days.** `/api/board/layer2-shortlist?date=` answers
   `no_shortlist_artifact` for 08-25/26/27. No retrospective longer than that
   is possible.
2. **MLB grading joins ~1 game in 14. FIX IS LIVE AND HAS NOT MOVED THE
   NUMBER. DO NOT RECORD THIS AS FIXED.** `[2026-08-31, lane layer2-accuracy-audit]`
   Baseline across the full window, both disks agreeing: `rows.all` =
   1/1/2/1/1/1/7 for 08-24..08-30 with 0/14/14/6/12/12/13 `Missing game-line
   match` warnings — **14 graded rows total, 71 lost joins.** That supply is
   what starves settlement (19,692 settleable, 35 settled).
   **WHAT IS LIVE:** `49c43aeb` (`_odds_paths` best-found-not-first-found +
   `daily/snapshots/` search), `04185203` (multi-date backfill), `a35591dc`
   (publish the rebuilt payload). `132559e1` (re-run a date that built but
   never published) is on main, NOT live.
   **THE BACKLOG REGRADE RAN AND RECOVERED NOTHING.** All seven dates rebuilt
   `ok=True` 19:03:47-19:08:33Z, each in **0.4-0.9 seconds** reporting
   `cards: 1`. A 14-game slate cannot be joined and graded in 0.4s. `ok=True`
   is an exit code, not a result.
   **WHY THE 14/14 PROOF DID NOT TRANSFER — READ THIS BEFORE TRUSTING ANY
   ARTIFACT-BASED PROOF IN THIS REPO.** The fix was proven on the freeze and
   live docs pulled from `/api/ops/artifacts/export`, **which runs on WEB and
   reads WEB's disk**. refresh-worker has its own disk. The proof established
   "the resolver works given these files present" and was used to claim "works
   on the worker", which was never tested. Presence is not reachability, across
   a service boundary this repo documents.
   **RESOLVED, and the resolver fix WORKS `[verified 2026-08-31 20:33Z]`.** The
   freeze IS reachable on refresh-worker at `daily/snapshots/<date>/`:
   2026-08-30 now reads `(pregame-freeze, 14 games)` with `Missing game-line
   match` **13 -> 0**, and raw moneyline candidates went **1-4 -> 12** against
   three pre-fix control dates. **The graded ROW count did not move (7 -> 7)**
   because `caps.ml = 1` absorbs the whole gain — so my claim that the join
   rate was starving settlement is **FALSIFIED by its own fix**. Graded rows
   come from the locked card, i.e. the policy's picks. See `todo #610`.
   **MLB prop supply is a SEPARATE defect (`todo #611`):** the prop pregame
   seal has produced nothing since 2026-08-16, so hitter/pitcher props grade
   against a post-slate remnant (~1 game). Leading cause **cadence** — measured
   2026-08-31, the MLB refresh ran 22:12:30Z against a 22:05:00Z first pitch,
   so `slate_started` was True and props were skipped by design. Not yet proven
   to be the whole cause. MLB odds refresh runs on **live-odds-worker**.
   **THE READING THAT DECIDES IT** is the always-on diagnostic shipped in
   `49c43aeb`: `Game lines read: <path> (pregame-freeze|live, N games)` in the
   payload warnings. `(live, 1 games)` => freeze unreachable worker-side, fix
   inert in production. `(pregame-freeze, 14 games)` => freeze found, failure
   is elsewhere. **It needs `132559e1` deployed** — the seven payloads carrying
   it were built before the publish call existed and nothing exports them.
   **MARKERS CANNOT BE CLEARED FROM OUTSIDE, measured:**
   `keyvalue/expire-run-artifacts` returns `matched_keys: 1` (surgical) and
   `skipped_no_run_stamp: 1` (refuses — run-stamped keys only); `keyvalue/sweep`
   only touches 10-day-stale keys. Hence the self-heal in `132559e1`.
   **THREE INSTRUMENTS WERE BLIND, all chosen for reachability rather than for
   answering the question:** `/mlb/api/market-accuracy` (wrong disk, and the
   backfill had no publisher), `graded_rows_available` (STALE — `epoch`
   unchanged for ~2h; moves only when the settlement autorun fires), and the
   builder's `stdout_tail` (JSON summary only, no warnings).
3. **NCAAF has never produced a graded row.** `_ncaaf_graded_rows_for_date`
   reads `cfbd_lines_*.json`; zero in the hot-artifact set.
4. **Soccer's biggest board market is ungradeable by construction.** Grader
   covers 3-way ML / totals@2.5 / BTTS; the board's #1 market is
   `alternate_totals_corners`, **573 of 2,623 rows (22%)**.

**THE FUNNEL IS THE OPTIMIZATION TARGET.** Refusals 08-24..08-31:
`no_model_edge_pct` **2,506**, `below_min_ev_pct` 1,567, below_min_stake 46,
zero_kelly 37 — ~4,150 against ~458 orders. Board side agrees:
**`model_edge_pct` is numeric on only 902 of 2,623 rows (34.4%)**,
`model_ev_pct` on 201. `ev_basis` = market_fair 1,451 / model_edge 184 /
model_probability 17 / unset 971 — on a `market_fair` basis the board is a
stale-price detector, not a model-vs-market edge.

**BOARD QUALITY, n=2,623 over the 4 dated snapshots:** books_quoting<=1 on
**1,511 (57.6%)**; book_age median 4,498s, **p90 36,816s (10.2h)**, >6h 21.3%,
`suspect_stale` 8.8%; movement not tracked 42.1%; `ev_pct`>0 on only 444
(16.9%), median **-2.35%**; model_skill measured 625 / unmeasured 882 / no
projection block 1,116. **Composition mismatch:** soccer 51% of board / 1.2% of
settled bets; ncaaf 33% / 0%; mlb 16% / 93%.

**NOT MEASURED, and it is the read that decides how to rank:** whether the
board's own `ev_pct`/`model_edge_pct`/`score` PREDICT the outcome. The
portfolio endpoints serve settlement marginals only (`by_sport`,
`by_market_family`, `by_venue_family`), never per-order rows, so no calibration
curve exists. Exposing settled orders with their board fields is the unblock.

## [layer2-score-outcomes] THE BOARD'S SCORE, GRADED ON OUTCOMES AND CLOSES FOR THE FIRST TIME -- real price edge, fee-blind ranking, non-monotone deciles `[2026-09-21, lane layer2-score-outcome-calibration, MEASURED on production files; fee-net score, score_v2 shadow + recorder fields and the venue fee/ceiling LIVE and VERIFIED 2026-09-21/22]`

**Read `findings_2026-09-21_layer2_score_outcomes.md` before changing any score term.** Three datasets: the recorder graded row by row (194,983 rows, 09-14..09-20, `scripts/score_ranking_backtest.py`), CLV on published openings with today's score recomputed exactly (157,079 rows, 931 games, 82 slates, 09-01..09-20), and paper bets (2,699 settled).

- **Price edge is REAL:** today's top-10 per slate beat the same book's close by +3.94% ROI-equivalent [+3.19, +4.80], 59.5% of the time. Outlier prices (5+ pp off the median book) correct toward us (+4.59%): no winner's curse in CLV terms.
- **But the ranking is FEE-BLIND:** Kalshi rows trail Kalshi's own close by -1.58 pts [-2.05, -1.15] before fees; 90 of 109 positive-EV Kalshi rows on the 09-21 board are non-positive after the fee; paper orders above 5.27% stated EV (all Kalshi/Polymarket) lost -26.7% [-46, -6].
- **Deciles are non-monotone:** top score decile ROI -14.9%, no better than deciles 2/3/6/8; paper bets hit 45.6% vs 45.2% break-even.
- **Efficient markets are where edge is least real:** 7+ books quoting = lowest CLV (+1.57%) and -13.8% ROI [-26, -3]; main pregame lines at EV 2-5.27% -21.2% [-37, -3].
- **`book_margin_model` fair is overstated 8.5 pp** (hit 18.0% vs 26.5%, 264 games).
- **A global favourite-longshot recalibration was measured and REJECTED:** slope > 1 in aggregate, but +EV longshots are calibrated; the +EV shortfall is at even money.

**LIVE AND VERIFIED (2026-09-21/22):** the fee-net value term (`SYNDICATE_SCORE_FEE_NET=1`, `dd43fd49`; MLB Kalshi half-rate series `03d3f801`, live 23:03:59Z 09-21 -- the first MLB fix `569ebca1` was INERT, 0 of 82, because the ticker is stamped after scoring); the `score_v2` shadow on every row (quarter-Kelly growth at the fee-net price x reliability; ranks nothing) and the recorder's `s2/n2/fb/bk` fields (`053ddd9e`); venue plans refuse `venue_ev_implausible` (> 5.263%) and `below_min_ev_pct_net_of_fee` and size on the fee-inclusive price (`4ee86561`). All on refresh-worker since `f0e60bec` 2026-09-22 00:12:34Z: Kalshi venue positions 53 -> 6, max EV 12.63 -> 5.11. Polymarket charges no fee at submit (`210dd3aa`, live-odds-worker 13:53:35Z 09-22). `ev_pct` stays gross. **Fee-netting beats the old score: +0.71 pts fee-net CLV at the top 25 [+0.40, +1.04], 82 slates.** The Kelly re-rank raises the top-10 break-even 0.378 -> 0.464 at equal edge overall, but is sport-dependent (soccer +3.00, NCAAF -2.71): NOT promoted, todo `#679` step 5 after 14+ days of recorder grading (from 09-22). The live-order half of the ceiling is owed by scheduled task `venue-fee-ceiling-live-orders-reading-0922` (13:00 CT 09-22).

  **THE FIRST SLATE AFTER THE DEPLOY WAS GRADED, AND IT IS NOT A VERDICT** `[2026-09-22, session dc70079c, no lane, substrate render]`. 09-21 was a 14-game Monday (MLB 3 — the whole league, confirmed against statsapi; NFL 1 MNF; NHL 8 preseason; WNBA 2; **no NCAAF and no soccer kickoffs**) and it CANNOT grade the fee-net score, for two structural reasons: the term only moves rows priced at a FEE VENUE (315 rows at the deploy reading, 158 of 1,837 later), and the recorder keeps FIRST sightings, so most of the day carries a pre-change `sc` even though the served board rescored it from 16:49 CDT. Measured anyway, 182,769 rows graded 09-14..09-21, bootstraps over GAMES: served-equivalent 7,124 rows **hit 48.1% vs 51.6% break-even, ROI -10.2% [-12.3, -7.0]**; bet window (EV 2-5.26) **-1.4% [-17.4, +20.4]** against a **-2.1%** week-before baseline; top-10 per slate **+15.1% [-42.5, +76.8]** against **+0.9%** — every contrast spans zero. **Deciles are still non-monotone** (top decile -16.7%, second worst of ten). `score_v2` on the 3,595 rows carrying `s2`: top-25 **hit 62.9% vs 53.1% break-even, ROI +6.4% [-11.9, +24.2]** against `sc`'s **+1.7% [-33.7, +41.5]** on the same rows — same direction as the in-sample fit, n=35, **filed as a LEAD, not a result**. Full working: `findings_2026-09-22_layer2_board_0921_reading.md`.

  **THE OWED VERIFICATION NOW HAS AN OWNER AND A DATE** `[2026-09-22]`. Scheduled task **`layer2-fee-net-7-slate-reading-0929`** (2026-09-29 10:00 CDT; brief `scheduled_task_layer2_fee_net_7_slate.md`) runs the paired top-K contrast with its verdict rule pre-registered (MET / INCONCLUSIVE / NOT MET on the top-25 interval) and fires on 09-29 rather than 09-28 because the recorder route needs 7 slates of `s2`/`n2`/`fb`/`bk` from 09-22. **`layer2-score-v2-promotion-decision-1006`** (2026-10-06 10:00 CDT; brief `scheduled_task_score_v2_promotion_decision.md`) is `#679` step 5, decided per sport, with a mandatory multiple-comparisons guard. Both are READ-ONLY and recommend only; neither deploys or promotes. **UNVERIFIED: whether either fires unattended** — scheduled tasks run only while the desktop app is open, otherwise at next launch.

## [layer2-movement-term] EVERY LAYER 2 ROW IS NOW COMPARED WITH ITS OWN LINE'S OPENING — line_moved 913 -> 0, verified `[2026-09-20 16:23Z -> 2026-09-21 14:41Z, lanes layer2-line-movement-scoring / layer2-line-move-magnitude]`

**ADVERSE-MOVEMENT CHECK `[verified 2026-09-21, lane layer2-adverse-movement-sanity]`:** the top of
the board is enriched for price moves AGAINST the pick (67% of the top 100 vs 50% board-wide) because a
lengthened price carries more EV (H1). Those rows are NOT adverse selection: same-book forward CLV
(observation -> close) on 09-20's finished, trail-covered games, toward minus away -- nfl -9.92
[-11.49, -8.36] n 213/206, wnba -6.50 [-7.62, -5.38] n 382/466, mlb -14.23 [-20.15, -8.32] n 31/31;
circular controls near 0. Away-moved rows revert and beat the close. NCAAF unmeasured until its
first trail-covered slate (Thu 09-24). The term's sign therefore looks backwards for a bet-now
ranking -- **NOT changed**: one evening of evidence; re-run over 5-7 days first
(`findings_2026-09-21_top_opps_adverse_movement.md`).

**Movement is the board's second-largest value term and was already wired end to
end** — unusual here. `blended_score` = `ev_pct` + capped sim + capped movement,
then `min(value, value x reliability)`.

**DEPLOYED COEFFICIENTS, FITTED OUT OF THE SERVED PAYLOAD rather than read from
config** (1,413 real delta -> component pairs, rms 2.7e-5): **weight 0.05, cap
1.0, saturating curve** — equal to the code defaults, so no env drift.

Served board 2026-09-20T16:23:40Z, 2,000 of 5,556 rows:

    term                  coverage   non-zero   mean |x|   signed mean
    ev_component            100%        —         2.585        —
    movement_component      94.3%      70.7%      0.343      -0.255
    sim_component           76.1%      76.0%      0.740      +0.223

**LINE MOVEMENT SCORED EXACTLY 0.0, and it is the sharpest class of move.**
`_movement_from_opening` withholds `movement_price_delta` when the line moved —
correct, a price at a different handicap is not a price move — and NOTHING
replaced it. The 114 rows with a null `movement_component` were **exactly** the
114 `movement_basis=line_moved` rows. The steam detector reads the same withheld
delta, so steam on a line move was **structurally impossible**, not rare.

**MOVEMENT IS A NET PENALTY**: 1,151 rows negative vs 262 positive,
`movement_vs_pick` 60.5% away / 15.8% toward. Of 357 `rows_admitted_by_blend`,
movement admitted **0** and the sim **38** — and demotions were UNCOUNTABLE,
because a dropped row is not in the served payload either. Line-moved rows split
**59 away / 55 toward**, i.e. balanced: a discovery signal, not another penalty.

Removing the term reorders **99.5%** of rows (median 61 places of 2,000).

**DEPLOYED AND MEASURED** (refresh-worker + web `96e17478`, live 18:25:13Z; read against
`written_at` 18:34:07Z): line-moved rows scoring nothing **1266 -> 160**, so **1,063 rows now
score a line move that scored 0.0**. `rows_refused_by_movement` 349, `rows_admitted_by_movement`
167 (it had admitted 0). Signed mean **-0.2545 -> +0.0170**: no longer a net penalty. Cap held.
The moneyline line-gate waiver (`088f39fe`) is also live.

**THOSE 1,063 WERE MOSTLY NOT MOVES — FOUND 2026-09-21, FIXED AND VERIFIED THE SAME DAY.**
The openings index in `pipeline/layer2_shortlist.py` was keyed by the LINE-LESS
`movement_join_key`, first write wins, while the board publishes several lines of one bet
at once -- so every line but the first-recorded was compared with a DIFFERENT line's
opening. Live board 13:52:19Z: 538 of 912 line-moved rows (59%) still had their opening
line published in the same build; 506 were scored at median |component| 0.975 (233 at the
cap) against 0.352 for the rest.

**FIXED: a PER-LINE openings index** (`c1710042` + `c70329c2`, refresh-worker live
2026-09-21T14:36:42Z). `index_openings` keeps the earliest opening per bet AND the first
opening at each line; `_movement_from_opening` uses the row's OWN line first and the earliest
only when the row's line was never published. **Verified on the 14:40:44Z board, 4 of 4:**
`line_moved` **913 -> 0**; `movement_opening_match=same_line` on **1,949 / 2,000**; rows at
the cap **317 -> 63**; `rows_admitted_by_blend` 119 -> 112 (negative control). The other 51
rows are moneyline (`earliest_line`, line None both ends, `088f39fe` waiver) and get a price
comparison too. So the board's movement term is now, in effect, PRICE movement of the same
bet at the same line -- the calibrated path.

**THE CROSS-HANDICAP MAGNITUDE STILL EXISTS FOR GENUINE LINE MOVES AND IS STILL UNSOUND**
(`|fair_now - fair_open|` at two handicaps; can contradict its own sign) -- but on the verified
board it has **0 non-moneyline rows to act on**. Whether genuine line moves need a better
magnitude is an OPEN question, not a live defect.

**THE SAME-BET FIX (`d419cc24`) WAS FALSIFIED AND REVERTED (`f1fe4ee1`) — and the cause was
mis-diagnosed at first.** 174 of 342 scored rows conflicted. It was blamed on inconsistent
alternate-line fairs, from one vivid spreads row; decomposing all 173 showed **86% had a
correctly monotone curve** (only 14% did not) and only 7 were spreads. The dominant cause was
the openings index above -- the opening read at L0 was often not that bet's opening.

**THE WEIGHT REMAINS UNVALIDATED.** `scripts/decompose_movement_clv.py` ran end to end
2026-09-20 (n=101 from one 35-minute trail chunk, one date, one sport) after three of its own
defects were fixed by running it; **no CLV result is claimed.** It measures FORWARD CLV
(observation -> close), because movement is a leading segment of the open -> close path and
the naive contrast is circular.


## [sim-weight-clv-decomposition] `_SCORE_SIM_WEIGHT`'s OWN UNBLOCK CONDITION WAS RUN, AND THE ANSWER IS NO — leave `(0.125, 1.5)` alone `[2026-09-04, lane sim-clv-decomposition, READ-ONLY: no deploy, no env var]`

**A non-zero `sim_component` does NOT predict better CLV.** In the direction the
board rewards it predicts slightly WORSE CLV. Measured at adequate power — this
is a falsification, not an underpowered null.

**THE ORDER-SIDE JOIN IS DEAD, AND NOT FOR A SAMPLING REASON.** `_LEAN_FIELDS`
began persisting `model_edge_pct`/`ev_pct` at `04187cdf` (2026-09-03 14:22 CT)
and `sim_view` at `cb223b62` (17:26 CT); settlement is a once-per-Central-day
job at ~06:00 CT. Production `/api/ops/execution/ledger-summary?days=60&mode=paper`:
`sim_view` on **104 of 852 orders (12.21%)** and **13 of 667 settled (1.95%)**,
**all 13 `agrees`**. `disagrees` and `neutral` have never been placed ONCE.
Power: a 10pp ROI gap needs **3,796** settled attributed orders (per-bet ROI SD
~110pp) — ~108 days at ~55 attributed/day, and the treatment arm still would not
fill, because `disagrees` is EV-censored by the stake gates. **Do not wait on it.**

**WHAT WORKED INSTEAD.** `clv_opening_ledger._opening_record` has carried
`model_edge_pct`/`ev_pct` on every published row since **2026-08-15**, and
`clv_join` carries both onto each resolved row beside `clv_pct`. `sim_component`
needs no storage — it is exactly `clip(0.125 * model_edge_pct, +/-1.5)`. Harvested
17,714 resolved rows over 21 dates x 5 sports via `/api/ops/clv/report?rows=1`.
Two properties make this arm STRICTLY better than the order arm: it is
**uncensored** (no stake gate), and **`sim_view` IS the sign of `sim_component`**
(`layer2_board.py:3021-3035`), so the sign buckets ARE the agree/disagree split.

**RESULTS.** Pregame closes only (3,563 unknown-timing rows EXCLUDED, not folded
in; 40 in-play excluded; n=14,111). Book scopes never pooled. Fixed-effect pooled
WITHIN-CELL differences, stratified on sport x market x side x price bucket, cells
>=15/arm. CLV in **probability points**:

    contrast                                    diff     95% CI            n a/b
    props (book_agnostic) positive - negative  -0.113  [-0.253, +0.027]  2717/2448
    props (book_agnostic) has-view - absent    +0.176  [+0.074, +0.277]  6160/2658
    game lines (same_book) positive - negative -0.186  [-0.340, -0.033]  1309/1069
    game lines (same_book) has-view - absent   -0.099  [-0.237, +0.039]  2280/757
    props CAPPED - uncapped (positive only)    +0.017  [-0.155, +0.189]   655/2214
    game lines CAPPED - uncapped (pos only)    +0.010  [-0.511, +0.532]    40/119

Negative in BOTH scopes; the game-line CI excludes zero; 16/22 props cells and
12/17 game-line cells put the endorsed arm behind. Props dose-response is
monotone the wrong way (Q1 -1.500..-0.604 -> +1.6026 CLV; Q5 +1.248..+1.500 ->
+1.0805). **Powered:** props detects 0.25pp at 1,297/arm and has >2,400/arm, so
a props effect above **+0.03pp** is ruled out at 95%.

**HELD OUT, THE SIGN DOES NOT REPLICATE — and the two scopes disagree about what
tail calibration (shipped 2026-09-01) did:**

    props      PRE  -0.4137 (z -3.54, 12 cells)   POST +0.1155 (z +1.13,  9 cells)
    game lines PRE  -0.1245 (z -1.32, 15 cells)   POST -0.5177 (z -2.74,  5 cells, 247 rows -- THIN)

**COMPONENT AGAINST COMPONENT:** `corr(ev_pct, clv)` +0.4109 props / +0.0673 game
lines; `corr(sim_component, clv)` **-0.0821 / -0.0454**; and the load-bearing one,
`corr(ev_pct, sim_component)` = **-0.3644** — the terms pull against each other,
so weight moved onto the sim comes off the better-correlated term. **Caveat:** in
`book_agnostic_close` the opening is our best-of-N price and the close is
market-wide, so a high-EV row is far from consensus BY CONSTRUCTION and +0.411 is
inflated. In the clean `same_book` scope the EV contrast is -0.132 (z -2.03) —
*neither* component beats the close there.

**THE ARITHMETIC SCREEN CANNOT GATE A WEIGHT CHANGE, and this is its own finding.**
`scripts/score_sim_weight_impact.py` returns the IDENTICAL PASS at weight 0.125,
0.25, 0.5 and **1.0** with the cap at 1.5: `promoted` fires only when
`-5 + contribution > 0`, and the cap bounds contribution at 1.5. Uncapped its
boundary is `5.0/10.36 = 0.4826` (the spreads median), i.e. **3.9x headroom above
today's value**. It screens the CAP and is BLIND to the WEIGHT. Still a valid cap
screen; never cite it as validation of a weight.

**DECISION: LEAVE BOTH ALONE.** Do not raise (claim falsified at power; terms
anti-correlated). Do not lower to 0.0 — `blended_score` then reduces to `ev_pct`,
identical for every side under a proportional de-vig, so the board cannot pick a
side at all and the screen FAILs it; the measured cost of keeping 0.125 is at most
0.19 probability points, which is cheap for the only side-picking capability the
board has, and props presence is worth +0.176 [+0.074, +0.277]. Do not touch the
cap — inert in CLV terms but the only structural bar to the 2026-08-08 domination
failure. The surface's "price-led, sim-breaks-ties" description stays CORRECT.

**WHAT WOULD CHANGE IT.** POST-calibration props is the one cut that moved toward
the sim (+0.1155, z +1.13, n 1156/982). Re-run `scripts/decompose_sim_clv.py` over
2026-09-01..~09-18 once that window stands alone at ~2,500/arm. A positive
`positive - negative` with a CI excluding zero, AND game lines no longer negative,
is the first real evidence for a raise — and it is a NEW hypothesis, because this
data generated it.

**NOT CLAIMED:** this is the published BOARD population, not the bet slate (the
right population for a RANKING weight, not a claim about fills); CLV is not ROI;
the HRR-poisoned window 2026-06-04..07-08 **cannot** contaminate it — the openings
ledger starts 2026-08-15 and returns 0 for 08-14 and earlier.

## [layer2_board_display] LAYER 2 BOARD -- USER-VISIBLE DISPLAY BUGS, 2026-08-20 AUDIT

### 2026-08-21 -- FOUR MORE, ALL THE SAME SHAPE: a number computed in one frame, displayed in another `[code + artifact evidence, NOT a served-board read -- see the gap below]`

Found from a user screenshot of the served board (one MLB game, all LIVE rows).
Fixed on `claude/layer2-odds-refresh-kbcxs8`, lane
`layer2-sim-view-and-live-projection`. **NOT deployed** -- `autoDeploy = no`.

- **`Win%` WAS THE BOOKS-QUOTING MULTIPLIER, NOT A PROBABILITY.** `layer2_board.py`
  published `score["book_confidence"]` as `confidence`, and
  `intelligence.html:2180` renders `confidence` as the column labelled **Win%**.
  So **"Win% 100%" meant "5+ books quote this market"**. Confirmed 5/5 against the
  screenshot with nothing left over: 1 book -> 50%, 2 -> 70%, 3 -> 85%, 14 -> 100%,
  21 -> 100%, exactly `_book_confidence`'s `((1,0.5),(2,0.7),(4,0.85))` ladder.
  This is the most severe of the four: a reader takes it as a certainty.
  Now carries the side-correct model probability; blank where there is no model.
- **`model_probability` WAS THE WRONG SIDE'S.** `layer2_board.py` published
  `projection["model_prob_over"]` with no side awareness. That field is always the
  OVER/HOME framing -- the same file proves it at `_model_edge_for`, which maps
  `"home": model_prob_over`. `sim_view` IS side-adjusted, so **away and draw rows
  rendered a coherent badge beside the other side's probability**. Repro:
  home -> `agrees`/0.62 (right); away -> `disagrees`/0.62 (away is 0.38).
  Fixed by `_model_prob_for_side`, mirroring `_model_edge_for`'s three-way/two-way
  logic rather than reimplementing it.
- **THREE HITTER MARKETS COULD NEVER PROJECT.** `_HITTER_BUCKETS` named mean fields
  that do not exist in the artifact, so `projected` was `None` on every row of
  those markets forever -- indistinguishable from thin model coverage.
  Measured at bucket-row level against a real `daily_summary` (2026-07-10):

      batter_runs_scored  wanted runs_mean     artifact writes  r_mean
      batter_doubles      wanted doubles_mean  artifact writes  2b_mean
      batter_triples      wanted triples_mean  artifact writes  3b_mean

  Matches the screenshot exactly: all 8 `batter_runs_scored` rows blank, every
  `batter_hits`/`batter_rbis`/`batter_hits_runs_rbis` row populated.
  **MEASURED BEFORE/AFTER ON THE SAME REAL ARTIFACT** (15 games, 6,210 hitter
  bucket rows), which is the strongest evidence in this whole block because it
  is a coverage number rather than a code reading:

      market               mean key BEFORE   before        after (r_mean/2b_mean/3b_mean)
      batter_runs_scored   runs_mean          0/810   0%     810/810   100%
      batter_doubles       doubles_mean       0/270   0%     270/270   100%
      batter_triples       triples_mean       0/270   0%     270/270   100%

  **0% -> 100% on 1,350 projections.** Values are the right MAGNITUDE, not merely
  non-null: triples projects 0.058 against P(1+) 0.057, and for a rare event the
  mean must approximate the probability -- a wrong-field join would not do that.
  **THE FILE ALREADY KNEW** -- `_HRR_COMPONENT_MEANS` is
  `("h_mean", "r_mean", "rbi_mean")`, so the HRR derivation read runs correctly
  while the runs MARKET did not, twenty lines apart.
- **THE LIVE SIM'S VERDICT WAS UNLABELLED.** `live_projection_join` already
  recomputes `edge_vs_market_pct` from `live_prob_over`, so on a re-priced live row
  `sim_view` WAS the live sim's -- nothing said so. "our pregame model dislikes
  this" and "the re-sim, watching the game, dislikes this" rendered identically.
  Now `sim_view: live_disagrees` + `sim_basis`, gated on
  `projection["basis"] == "live_resim"` and NOT on game state, so a pregame
  projection sitting in a live game is not mislabelled live.
- Also: exactly-zero `model_edge_pct` was bucketed as `agrees` (`>= 0`); now
  `neutral`. And `pipeline/layer2_shortlist.py` now PRINTS the live-join
  telemetry (`LIVE_PROJECTION_JOIN sport=... projected=... lens_indexed=...
  miss_player=...`), which previously existed only inside the artifact payload --
  so "why is the Live column blank" was unanswerable from production logs.

**THE VERIFICATION GAP, STATED SO IT IS NOT CITED AS DONE:** none of this was read
off the served board. This session's egress proxy returns **403 for
`syndicate-an21.onrender.com`**, so the evidence is code + the real artifact files
+ the user's screenshot. Per this section's own 2026-08-20 note, checking the raw
shortlist row shape is NOT sufficient for this class of fix -- the read owed is of
`boardContract.cards`. Tests discriminate (5/5 fail pre-fix, pass post-fix), which
is not the same thing as a production measurement.

**Blank LIVE cells are NOT all a bug.** `attach_live_projections`' own telemetry
records the ceiling: the live lens indexed 81 rows against 1,385 live board rows
(2026-08-13). The join cannot project what the lens never produced, so some blanks
are correct and the fix for them is in the lens, not the board. The new log line is
what separates "lens produced nothing" from "lens had rows, join missed".


**All five items from the 2026-08-20 user-directed board audit are FIXED and
LIVE-VERIFIED.** `syndicate/templates/intelligence.html` unless noted.

- **Over/Under picks now show direction.** `propLine()` dropped the
  selection word (`"Under"`/`"Over"`) whenever it matched the card's
  fallback title, which is EXACTLY when both were the same placeholder
  value. **VERIFIED live: 273/273 (100%)** over/under rows show direction
  post-fix.
- **Projected is no longer blank for most moneyline rows.**
  `displayProjection()` had no fallback for h2h (no natural number to
  project pregame). Added a probability-derived fallback. **VERIFIED
  live: 84 of 94** previously-blank h2h `Projected` cells now populated
  (remaining 10 lack `model_probability` upstream — a real backend
  coverage gap, correctly left blank, not fabricated).
- **Live-game Projected/Live/Actual semantics fixed, backend.** Two
  independent gaps: (1) `live_projection_join.py` preserved the pregame
  number under `sim_projected` (`#412`) but then still overwrote
  `projected` itself with the live re-sim value three lines later,
  contradicting its own comment — measured 34/40 live rows with
  `projected == live_projected` pre-fix. (2) `_live_projection_columns`
  (`layer2_board.py`) never mapped `actual_so_far` to `actual` at all —
  zero hits repo-wide before the fix. **VERIFIED live (on the actual
  served surface, `boardContract.cards` — the raw `/api/board/layer2-
  shortlist` row shape exposes this data differently and checking only
  that is NOT sufficient for this class of fix): 36/48** live MLB prop
  cards now show a populated `Actual` and a distinct `Live` projection.
- **Movement/steam display fixed.** `renderMovement()` only read the
  legacy `line_odds_movement` nested shape; the real data moved to
  top-level `movement_state`/`movement_price_delta`/etc months ago
  (`#372`) and the frontend never followed — every tracked/flat row
  rendered blank regardless of real movement data existing. **VERIFIED
  live: 169/169 (100%)** tracked/flat rows now render real movement text
  (e.g. "Odds +226 · 12h ago"). Steam badge logic confirmed correct by
  code read; no real steam event occurred during the verification window
  to observe directly (`steamRows: 0` at check time — a real, expected
  state given the size-and-clock bar, not a rendering gap).
- **Compact game-card "uniformity" was a render-order race, NOT a
  chip-matching bug.** Original hypothesis REFUTED by measurement: chip-
  matching is 100% correct for today's real games (15/15). The actual
  cause: `loadGameChips()` fired AFTER the synchronous initial render, so
  the mini-card strip's first paint always used the chip-less fallback
  style — even for today's real games — then visibly relaid out once
  chips arrived a moment later. Fixed: fetch chips first, gate the
  strip's first paint on a `gameChipsLoadedOnce` flag with a sized
  skeleton placeholder instead of the wrong-shape fallback.
  **NOT live-verified with a timed capture** — confirmed by code read
  (exact line numbers for both bug and fix) plus the existing
  `deriveGameCards` Node harness (unaffected, still 10/10), not by
  screenshot/network-waterfall. Flag this gap to whoever next touches
  the game-card strip.

---

- **The soccer projection read was ONE DATE against a SEVEN-DATE quote window**
  `[moved here 2026-08-18 from a WNBA state snapshot]`. `#379`'s widening shipped
  inert — its only caller never passed `window_dates`. Fixed (`b4d82364`), **NOT
  deployed**. `window="slate"` is required; the resolver defaults to `"day"`.
- **Soccer's `recommendations_<date>.json` is NOT in `HOT_ARTIFACT_PATTERNS`** —
  it lives under `soccer_source/<league>/api/recommendations/` while the allowlist
  covers `source_artifacts/data/processed/`. `/api/ops/artifacts/export` returns
  `count=0` for it. **`/soccer/<league>/api/cards` is the readable substitute.**

## [layer1-layer2-boards] LAYER 1 / LAYER 2 BOARDS — session briefs exist; three facts worth not re-deriving `[code read 08-16 11:2x CDT, NOT a production measurement]`

Full briefs: `.syndicate/brief_2026-08-16_layer1_board.md`,
`.syndicate/brief_2026-08-16_layer2_board.md` (commit `01c53f56`). Lane names
`layer1-board-coverage` / `layer2-board-quality` are RESERVED BY BRIEF and
deliberately NOT opened in `lanes.md` — no session holds them yet.

- **L2 MOVEMENT IS LIVE ON EVERY ROW WITH AN OPENING `[verified in production 2026-09-15 19:57Z, refresh-worker `5686a555` / web `7ed1a18a`, lane `layer2-row-parity`]`.** It supersedes the 08-16 "disabled in code" note.
  - Source: the CLV opening ledger (`reports/intelligence/clv_openings/<date>.jsonl`), joined on `movement_join_key` = event, market, player, segment, side, with no line and no book.
    - Props are included.
    - It does not load the ~20MB odds history that stalled the build in `#372`.
  - Movement fields:
    - `movement_price_delta` is on the continuous cents scale (±100 both map to 0).
    - `movement_vs_pick` is the one direction verdict.
    - Steam needs `movement_basis=same_book`.
  - Sparklines: `clv_price_trail.py` records a change-only price trail each build (`SYNDICATE_CLV_PRICE_TRAIL`, absent = ON).
    - `movement_series` plots the implied probability of the label's own price from our publish to now, so a line cannot contradict its arrow.
    - The no-vig consensus move is `movement_fair_delta_pp`, shown in the tooltip only.
  - The score's movement term is POSITIVE when the market moved toward the pick.
  - Reading on 2,153 rows: `not_tracked` 0; 0 of 1,369 series against their arrow; movement component wrong sign 0 of 1,360.
  - When the L2-A fallback has cards, `read_combined_intelligence_response` withholds legacy prop/game rows: 0 on the board at 19:29:06Z.
- **The L2 scoring model EXISTS** — `blended_score()`,
  `opportunity_signals.py:497-575`, `min(value, value*reliability)`. Auditing it
  is the work; rebuilding it is not. The `min()` is load-bearing (it corrects a
  sign inversion on negative-value rows, `corr -0.8312` vs `+0.8560` control).
- **Layer 1 already publishes its own projection-coverage instrument** — the
  header's `N markets / M with a projection`, via `_classify_enrichment`
  (`layer1_board.py:328`) / `_row_is_enriched` (`:176`). Do not build a second.

**NOT established, and stated here so it is not cited as if it were:** "Layer 2
has no book allowlist" is a **negative from a grep over one file**. Layer 1's
list IS confirmed (`DEFAULT_BOOKS`, `templates/shared/layer1_board.html:267`,
client-side JS). Trace the served `book` field to its writer before acting.

## [layer1-board-date-scoping] THE BOARD WAS DROPPING GAMES TWO WAYS — both FIXED AND VERIFIED; a THIRD (soccer projections, late kickoffs) found 2026-09-19, FIXED `6419eea5` and VERIFIED 18:36Z — `[verified 2026-08-30 05:0x-05:5xZ, web+refresh-worker `d7cda903`]`

1. **A 9pm Central game was invisible.** The grid artifact is keyed by **UTC**
   date; the board scopes by **CENTRAL** game date; the read set was window+today.
   `window=day&date=2026-08-29` served **7 games** while
   `book_grid_2026-08-30.json` held Memphis @ UNLV at `02:19Z` = 9:19pm Central
   on the 29th. **7 -> 8 games, `rows_other_dates=0`.** Same game and cause
   `ncaaf/sources.py` already recorded; that fix corrected ONE consumer and the
   board was the second. Rule now lives in `layer1_board.artifact_read_dates`.
2. **Whole slates had no artifact.** `_SLATE_WINDOW_DAYS["ncaaf"]=7` sized BOTH
   display and BUILD; NCAAF week 1 spans ten days, so the last three days were
   unreachable by date. `?date=2026-09-05` **0 -> 67 games / 353 rows**; 09-06
   and 09-07 also reachable for the first time. Split into
   `artifact_window_days` (never below the display window). **The display width
   is UNCHANGED at 7** and `#565`'s per-sport cost pruning survives — three extra
   shard checks for NCAAF, none for any other sport.
4. **READING THE NEXT DAY'S GRID COULD SHOW ONE MARKET TWICE** `[verified 2026-09-21 17:06Z, web
   `7882372f`]`: a game whose kickoff MOVED (NCAAF announces times late) has quote rows in two
   shards, hence two grids, both inside the window. Served NCAAF 09-26 board: 11 duplicate
   game-market rows on 4 evening games -> 0; `merge_grid_rows_across_dates` keeps the fresher
   `updated_at` copy and the payload reports `rows_dropped_cross_date_duplicates`: 11 at 17:06Z,
   **55 at 19:21Z on grids rebuilt 18:30Z after the NCAAF writer fix** (fresh 09-26 copies win;
   still 0 duplicates; = an offline merge of the same two grids).
3. **THE PROJECTION SIDE OF (1) WAS STILL OPEN FOR SOCCER** `[defect verified
   2026-09-19 16:06-16:10Z, lane mls-board-evening-gaps; FIXED by `6419eea5`,
   VERIFIED 18:29-18:36Z on refresh-worker `aebc040d`: the UTC-09-20 grid reads
   09-19..09-26, `unmatched_by_league` mls 3730 -> 0, and all 13 MLS 09-19 fixtures
   are projected]`.
   - The grid build's soccer projection read (`board_enrichment._attach_projections_by_sport`
     → `resolve_window_dates(..., "slate")`, forward-only) is anchored on the
     artifact's UTC date. The sim files a fixture under its LOCAL date.
   - The UTC-09-20 grid read `recommendations_2026-09-20..26` and reported
     `unmatched_by_league {"mls": 3730}`.
   - All nine MLS fixtures kicking off after 00:00Z carried 0-1 projected rows on
     Layer 1 09-19, though every one was in `recommendations_2026-09-19.json`.
     The four 23:30Z fixtures, in the 09-19 grid, were projected (133-185 rows).
   - Nightly, for every late kickoff. The Ask and prop-evidence readers anchor on
     the local date and are not affected.
   - Also measured there, NOT this defect: the soccer 09-19 grid is `rows_total`
     11,673, `rows_truncated` 5,673. The cap is 6000, applied after a
     `-books_quoting, market` sort. That keeps all 5,143 multi-book rows and
     single-book rows in MARKET-NAME order; 6,538 rows are single-book.

## [board-chip-coverage] Layer 2 compact game cards — FULL chip coverage, verified 2026-08-26

Every compact card on the board resolves a live-scoreboard chip, measured from
refresh-worker logs the same evening:

    mlb 400/400   wnba 400/400   nfl 106/106   soccer 400/400

`CHIP_JOIN_COVERAGE` (`pipeline/layer2_shortlist.py`, per sport, every build) is
the instrument. It reports `chips=`, `chip_dates=`, resolution by index
(`by_id` / `by_matchup` / `by_canonical`), plus `needs_fallback`,
`no_chip_available` and `unknown_no_key` with named samples. Before it existed
this defect class was found ONLY by a person looking at the board — twice.

Three causes were closed, all previously invisible:

* **Phase offset.** The chip build resolved ONE matchday per league from
  `default_week(reference_date=today)`; on a Monday that is the matchday just
  played. 65 of 96 chips described finished fixtures. Soccer
  `no_chip_available` 251 -> 0; NFL was the same defect via an exact-date
  filter, 106 -> 0.
* **Two different names for one club.** Normalisation cannot bridge
  "Athletic Bilbao"/"Athletic Club"; both sides now carry `canonical_team`'s
  answer as a join key.
* **Alias gaps**, named by the telemetry itself: soccer `unknown_no_key`
  7 -> 0.

**The horizon is the CALLER's to ask for** (`include_upcoming`, default False).
`provider.games()` serves the home rail (means "today") and the chip strip
(means "the board's forward horizon"); overloading it silently doubled the
soccer home rail 98 -> 210 while fixing the board.

**The alias map has TWO CONSUMERS WITH DIFFERENT REACH.** `teams_match` falls
through to a shared-suffix heuristic; `canonical_team` is map-only and the chip
join calls it directly. A club can join fixtures fine and still return None for
a chip key. The asymmetry is principled: `teams_match` holds BOTH names and
answers "same club?", so a loose rule is safe; the chip index holds ONE name and
must mint a globally unique KEY, where the same rule mints collisions.

**`DIRECT_FEED_BOOKS` needs no widening.** `near_misses={}` across many builds,
one at 27,070 rows — the aggregator uses no spelling the exact match misses.
Reproduced independently by lane `board-staleness-visibility`.

## [chip-artifact-content-age] A chip artifact's TIMESTAMP and its CONTENT age are different numbers — verified 2026-08-27 (lane `mlb-chip-live-state`)

**`/api/board/game-chips` `published_at` bounds when the artifact was WRITTEN,
not how old the live state inside it is.** Measured 00:09:03Z, refresh-worker on
`f8d8b05f`: `published_at` 79 seconds old, content two innings — roughly fifteen
minutes — behind StatsAPI. `BOS` read `TOP 3` against `Bottom 5`; `MIL` read
`BOT 1 0-0` against `Bottom 3 4-0`.

**`#564`'s 120s freshness threshold and the page's stale badge both key on
`published_at`, so BOTH read healthy through this.** Same shape as
`[board-quote-staleness]`. A board build that takes ~750s cold stamps its
artifact at the END.

**THE DISCRIMINATOR BETWEEN A STALE CHIP AND A BLANKED ONE IS THE TOKEN, NOT
THE SCORE.** A blanked game (`#581`) carries `0-0` AND a bare `LIVE`/`FINAL`
with no inning. A stale game carries a real inning that is merely behind. Both
present as "the score is wrong", and reading the score alone gets it backwards
— this was nearly called a `#581` regression off a watcher line that reported
only score mismatches.

**THE CAUSE IS BOARD-BUILD DURATION, NOT THE LENS BOUND.** A first hypothesis
blaming `_MLB_LIVE_LENS_MAX_AGE_SECONDS = 15 * 60` was FALSIFIED the same hour:
one build later, WARM, the same worker with the same bound served an inning gap
of **max 1, mean 0.25 over 8 live games** (`pub=00:15:18Z`). A bound does not
know which build it is in — if it were admitting the staleness, a warm build
would be just as stale. The content is about ONE BUILD old, and this file
already carries the numbers: **cold 747.8s, warm 107.8s**.

**So the exposure is a ~12-minute window after every worker RESTART, not a
standing lag** — and a restart is what every deploy causes. refresh-worker was
deployed three times on the evening of 2026-08-26. Same family as
`[board-quote-staleness]` and `#563`'s deploy-cadence finding.

**Open as `todo.md #585`, not fixed.**

## [chip-refresh-worker-pull-hop] REFRESH-WORKER'S HOT-ARTIFACT PULL FLOOR WAS SET BY LIVE-ODDS-WORKER — one shared keyvalue watermark; fix `082da3e3` LIVE on both workers and VERIFIED on two pulls `[verified 2026-09-15 20:38-21:04Z, lane soccer-live-scoreboard-range-stale]`

- **Where the soccer chips' live state comes from:** refresh-worker builds `/api/board/game-chips` every ~120 s from ITS OWN disk copy of `soccer_source/<league>/api/live_state/live_state_<date>.json`. That copy arrives only through `pull_hot_artifacts` inside the heavy board build, one date per build, alternating today and tomorrow. Nothing writes a keyvalue copy of that path.
- **The floor was one key:** `reports_root()/refresh_status/latest/hot_artifact_pull_watermark.json`, keyvalue-backed, with the same `SYNDICATE_REPORTS_ROOT` on both workers. refresh-worker's requests carried live-odds-worker's pull start as `since=` (20:41:05Z -> 20:39:04Z; 21:02:50Z -> 20:58:06Z).
- **Web's `/api/ops/artifacts/export?pattern=*<today>*` timed out** on ~1 in 6 of refresh-worker's today-pull requests on 09-15 (10 of 60 lines, 08:57-20:41Z), and on both workers in the same seconds (20:17Z, 20:41Z).
- **Measured effect:** the chips served pre-deploy soccer state for 11 publishes (20:38:19-21:01:41Z) while web held the fresh file. They were fresh on the first publish after refresh-worker's first successful today-pull (21:02:50Z -> 21:04:02Z).
- **Exonerated:** the card builder (web's own cards from the fresh copy were correct), the source roots (`/opt/render/project/data/soccer_source` on both workers), and a stale keyvalue copy.
- **Fix `082da3e3`, LIVE and VERIFIED:** live-odds-worker 21:38:19Z, refresh-worker 22:12:03Z (both `2d579fd1`). Readings, `deploys.md` 22:14Z and 22:39Z: refresh-worker's first pull after go-live carried the 2 h clamp (`since=` 20:12:51Z, its new key empty) and its second carried **22:12:51.435Z, its own previous start** (a 26.7-minute window) while live-odds-worker pulled ~13 times on its own floors (22:16:58Z..22:37:20Z). Under the shared key that request would have inherited ~22:34:42Z, a ~5-minute window. A FAILED pull still does not advance a floor (live-odds-worker repeated `since=22:26:31Z` across two DNS errors and a timeout).
- **Shape:** the key is `.../hot_artifact_pull_watermark/<service>/<date|all>.json`. A new scope starts at the 2 h clamp; export size measured flat (15.5 MB JSON at 30 min and at 2 h). It rides `8c089e8c` (live-odds-worker build in progress 21:33Z). **Production reading OWED:** refresh-worker's first pull after go-live must carry its own floor.
- **THE WATERMARK NO LONGER SKIPS A TRUNCATED EXPORT** `[2026-09-16, lane web-export-timeout; web + refresh-worker `e6b4bb94`, live-odds-worker `09c3e44a`]`: a `since` read is filled oldest-first and returns `next_since`; the pull records that cursor, and HOLDS its floor if a truncated read carries none. Verified on production by forced truncation: 6 reads, 6 of 6 files, 0 missing. A cursor rounded UP by a caller no longer skips its file (count 0 -> 1 on the same file). The client's resume branch has not fired in production — nothing truncates at 48 MB. The 2 h window clamp remains a separate, now-logged skip (`PULL_WINDOW_CLAMPED`).
- **WEB'S EXPORT WALK IS PREFILTERED BY DATE** `[2026-09-17, lane web-export-walk-prefilter, web `4515ae77` live 03:41:10Z]`: a dated export matches ~59,180 files across history and now stats only those its date can match (19-1,738). `names_only` walk median 37.3 s -> 2.55 s (n=10 each); warm real body pulls median 2.5 s, 0 of 76 over 30 s; worker dated pulls 0 of 73 timed out. Each request logs `ARTIFACT_EXPORT_WALK` counters. The first requests after a web restart are still slow (cold cache: 134.5 s probe, 70-83 s pulls).
- **REFRESH-WORKER'S DATED PULLS NO LONGER TIME OUT** `[2026-09-16, lane web-export-timeout; `6ac08075` via off-main `793b621b` 19:33:20Z, then main tip `a1047e60` 20:15:12Z]`: `pull_hot_artifacts` defaults to 90 s, and the live-lens tick passes an explicit 30 s. **0 of 12** dated pulls timed out after go-live against 13 of 28 (46%) before; live-odds-worker, still at 30 s, timed out 12% in the same window. Tomorrow's floor is now recorded by its own successful pull (next request `since` = prior start, no clamp). **The walk's cost is unchanged** (web's export still stats every pattern-matched file across history before the date filter; hypothesis H5, not measured on production). **The 2 h window clamp BITES:** 20:35:20Z skipped 2,821.9 s of tomorrow's changes after a floor frozen by timeouts and a 2 h gap between tomorrow pulls; 3 files, 0 provably lost (`deploys.md` 20:47Z).
- **The web export timeouts are DIAGNOSED, and the truncation beside them is PARTLY fixed** `[2026-09-16, lane web-export-timeout; cap LIVE web `1ddb5854` 04:04:57Z, refresh-worker + live-odds-worker `5abc20f3`]`: a per-file cap (8 MB) now keeps the accumulators out of the bulk export and names them, and the workers log `PULL_INCOMPLETE`. Verified: refresh-worker's first pulls received **95** and **77** files where the same window pre-fix returned 4. Truncation then persisted on the 24 MB budget (77 files, ZERO oversize skips), so **the budget was raised to 48 MB, LIVE on web `62694269` 14:09:41Z** and verified on a discriminating read: 38.54 MB across 134 eligible files returned `truncated=False` with all 134 delivered. Memory impact at long uptime is unmeasured, and the watermark still advances past anything a future truncation skips. The timeout itself is NOT fixed. Before the fix: the cost is the tree WALK, whose duration on identical work spans 13.10-38.13 s (median 15.21 s, 1 of 7 over the client's 30 s timeout — production sees ~1 in 6). Bodies do not drive it; hitting the 24 MB budget `break`s the walk early, so a bigger change-set returns FEWER files FASTER. **Next to it and worse: every full export sampled came back `truncated: true`, the client never reads that field, and the watermark advances past every undelivered file** — same shape as `082da3e3`. Evidence: `findings_2026-09-16_web_export_walk_and_truncation.md`.
- **OPTION 2, THE HOP REMOVED FROM THE CHIP PATH (LIVE: web `4f65f2b2` 00:21:07Z, refresh-worker `1175e0ef` 00:36:13Z; landed `2df28280` + memo `1175e0ef`).** `syndicate/features/soccer/cards.py`'s two live reads (`_live_state_entry`, `_live_vintage`) now go through `sources.board_live_state_payload`, which overlays `live/soccer_live_lens.json` -- the keyvalue-backed aggregate all three services share -- on top of the per-league file whenever the aggregate is strictly newer. `games` is replaced (a match it no longer lists has ENDED); `finals` is written OVER an existing `match_box` record so six settlement scalars cannot delete the goal list; an absent or FAILED league (`leagues_checked` minus `errors`) is never read as `nothing in play`.
  - **REACHABILITY MEASURED, not assumed** `[2026-09-15 23:57Z, web /api/ops/live-lens/{status,snapshot-index}]`: the soccer tick runs on a **60-second** interval, `lastTickAt` 23:57:09Z, `lastTickOk: true`, soccer `ok: true`, `activeSports` includes soccer, and the snapshot sits at `/opt/render/project/data/live/soccer_live_lens.json` -- the exact path, and therefore the exact keyvalue key, `board_live_state_payload` builds. `snapshot_date` 2026-09-15, `snapshot_game_count` 0 (nothing live at that minute). ONE writer: web reports `enabled: false` for its own loop and reads the owner's status out of the shared store.
  - **THE TWO STAMPS ARE NOT COMPARABLE AS TEXT, and production proves it:** that snapshot is stamped `2026-09-15T18:57:08-05:00` (CENTRAL -- `write_json_file` -> `normalize_timestamped_payload` rewrites `generated_at`), while the per-league file keeps UTC (`23:22:19+00:00`, a plain `write_text` in `poll_league`). The aggregate is 34m49s NEWER and a string compare ranks it FIVE HOURS STALE. The overlay compares parsed instants; `test_a_CENTRAL_stamped_aggregate_is_not_read_as_stale` pins it.
  - **Both deploys verified as REGRESSION readings only** (`deploys.md` 00:17:53Z, 00:33:10Z): web's own card build and refresh-worker's published chips are byte-identical across the deploy (`cards_digest` c9db0b04e0f9873a; `chip_score_digest` 6c8725cacf0633ca on the first artifact published after go-live, 00:37:17Z). That is what was PREDICTED -- the overlay must be a no-op while `games` is empty -- so it proves the reader did not break the board and nothing more.
  - **Effect MEASURED on a live match** `[verified 2026-09-16 17:31-17:43Z, La Liga OSA @ ATM + SEV @ DEP, web e6b4bb94, refresh-worker 03851b5a -> 9c98fd8f; deploys.md 17:44Z]`: the chips are no longer bounded by the today-pull. Every chip built after the aggregate held the match was served **0-4 match-minutes** behind ESPN, score correct (7 reads). Chip clocks equal ESPN's clock at the latest aggregate stamp to within 1 minute, and they do not advance across a publish when the aggregate has not ticked. **Two corrections to what was predicted:** (a) while games are live the aggregate ticks every **143-187 s**, not 60 s, so served lag is that tick plus the ~2 min publish, with a worst case of about 5-6 match-minutes; (b) a match that is in play but not yet in the aggregate still reads the pull-hop file. SEV @ DEP's first chips read 6-7 behind while the aggregate held 1 of 2 games (inference from stamps, one match). `e115cd6b` was not exercised (no penalty or own goal).
  - **CONFIRMED by a second live match, and the score path is exercised** `[verified 2026-09-16 19:57-20:18Z, La Liga RAC @ BAR, web e0aee286, refresh-worker 793b621b; deploys.md 20:19Z]`: over 22 same-instant reads the chip clock was 1-5 match-minutes behind ESPN. The live aggregate ticked every **136-176 s** (9 stamps, `snapshot_game_count` 1), so a new goal reaches the chip one tick plus one publish later (measured 2m45s, 2m48s, 4m06s). A publish built just before a tick misses a goal ESPN has shown for 80+ s. A `penalty---scored` goal is counted on the chip (`e115cd6b` live); no own goal has been observed live. **`published_at` does not stamp the served content:** the chip score and clock advanced twice while it stayed at 20:11:11Z (cause unread).
  - **A REFRESH-WORKER RESTART CAN SERVE OLDER SOCCER DATA THAN WEB** `[verified 2026-09-17 00:05-00:38Z, lane soccer-postponed-served-final; deploys.md 00:39Z]`: after refresh-worker `1011bfef` went live 00:04:19Z, the chip for the postponed ATH @ LEV (`401882870`) went from `pregame` (23:00-23:57Z) back to `final 0-0` on every publish to 00:37:34Z, while web on the same card code (`c49ecd3d`) served it correctly at 00:38:55Z and web's own `recommendations_2026-09-16.json` (23:34Z) and la_liga live_state (00:33Z) no longer held the match. **Traced 2026-09-17 01:25Z (`deploys.md`):** NOT the recommendations copy (refresh-worker published its own at the clean 171,140 B before and after the restart). A fixture absent from recommendations is carded by `cards._unsimulated_game` from the SCHEDULE artifact. refresh-worker's la_liga `schedule_2026.json` was last built by refresh-worker itself at 21:51Z on OLD code (`post`), and is never re-pulled (the file has no date in its name). `schedule_payload`'s `@lru_cache` had frozen a pre-postponement read until the 00:04Z restart. The disk copy itself was NOT read. Fix `bea2a355` (the memo follows the file; `_unsimulated_game` refuses unplayed) is live on refresh-worker `05b808cc` since 05:47:43Z; verification needs the next unplayed fixture.
  - **The live aggregate has ONE writer, live-odds-worker** `[verified 2026-09-17 00:37Z, single-key env reads]`: `SYNDICATE_ENABLE_LIVE_LENS_LOOP` live-odds-worker `true`, refresh-worker `false`, web absent. The soccer pregame artifact autorun runs on live-odds-worker only (`SYNDICATE_ENABLE_SOCCER_PREGAME_REFRESH_AUTORUN=true`, interval 14400), yet la_liga recommendations for 2026-09-16 were generated at 21:37, 22:43, 22:56 and 23:34Z (cause unread).
  - **Originally expected (superseded by the line above):** the chips stop being bounded by the last successful today-pull (~15-30 min apart, ~1 in 6 timing out) and become bounded by the 60 s aggregate tick. The pull hop is NOT removed from anything else -- every other per-league soccer artifact still rides it.

## [layer2-rail-group-join-keys] THE GAMES RAIL BUILT EACH GAME FROM ITS FIRST ROW, AND A SHORT CLUB NAME MINTED A FAKE ABBR — both FIXED and VERIFIED in production `[verified 2026-09-16 14:20-14:50Z, web `3b26ca89` + `9dceb84a`, refresh-worker `1923d677`, lane layer2-chip-rail-duplicate]`

- **`deriveGameCards` (`intelligence.html`) takes a group's join fields from its FIRST row.** The two soccer row families disagree: La Liga steam/prop rows (`sport: "la liga"`, abbr matchup, NO `away_key`/`home_key`) vs `layer2_shortlist` rows (full names, keys). When a keyless row ranks first, `chipForGame` misses on all four indexes and the unclaimed chip seeds a SECOND, count-0 card. Measured on SEV @ DEP 2026-09-16: 3 keyless rows ranked 8/13/15, 20 keyed rows from 32. **Fixed `acad4e44`:** the group backfills the key PAIR from any row (no overwrite, no half-pairs). Only `awayKey`/`homeKey` are merged; `matchup`, `sport` and `fallbackDate` are still first-row values.
- **The replay's detectors 1 and 2 (`chips seating MORE THAN ONE card`, `normalized team pairs`) CANNOT see this shape**, and they read 0 on the broken template. `tests/js/game_rail_production_replay.mjs` detector 3 (a chip-SEEDED card whose game has keyed board rows) reads 1 old / 0 new, and is the one to use.
- **`soccer/cards._abbr` mints `longest_token[:8].title()` on a `team_by_name` miss**, so a club the branding CSV spells differently from ESPN shows a truncated name (`Deportiv`) in a tri-code slot. The chip `key` was right: `game_chip_scoreboard` asks `canonical_team`, and `team_by_name` did not. **Fixed `68f54d81`:** `team_by_name` retries through `canonical_team("soccer", ...)` LAST, accepted only if the club is in that league's index (`Athletic` -> Charlton Athletic -> None in La Liga). Census, 410 (league, name) pairs: 1 changed, 0 existing hits moved.
- **Board CSS** `9dceb84a`: the strips used the LIGHT native scrollbar (`scrollbar-color: auto`, root `color-scheme: normal`), and the bet-slip rail column started on the exact pixel the full-width Games section ended. Now a dark thin scrollbar and 16 px (`.board-games-section`).
- **Readings:** `deploys.md` 2026-09-16 14:20:54Z (rail, with a same-payload control), 14:31:13Z (chip abbrs 3 -> 0 on the first post-go-live artifact), 14:43:13Z (CSS served + rendered at 1600x900).

## [layer2-market-gone-league-cadence] `_drop_market_gone_rows` DELETED LIVE MARKETS whenever a partial pass was the newest stamp (soccer per league, MLB prop chunks) — FIXED `03851b5a`, LIVE on refresh-worker 16:11:39Z and VERIFIED over 4 builds `[verified 2026-09-16 13:33-17:02Z, lane soccer-board-tomorrow-shortlist-collapse]`

- **Symptom:** served soccer rows 1,089 (board state 13:57Z) -> 288 -> 186; rows from the 09-17 shortlist 844 -> 3. The shortlists still SELECT ~1,000 soccer rows each (09-16: 1,069, 09-17: 991); the loss is `pipeline/layer2_shortlist.py:_drop_market_gone_rows`, which logs per build on refresh-worker: `MARKET_GONE_DROPPED` soccer = 770, 794, 9, 12, 828, 851, 883, 827, 20 (13:33-15:06Z). Gate config is identical in every build. **MLB flaps the same way** (1,228 -> 1 -> 1,098 -> 5), mechanism for MLB NOT tested.
- **Mechanism (H5, confirmed):** `_classify_stale_row` first asks `as_fresh_as_sweep` — row seen-age <= 1.5 x the NEWEST stamp in the whole `(sport, selected_date)` state file + 300 s. Soccer is captured PER LEAGUE on different cadences: `2026-09-19.state.json` had 67 events / 9 leagues last seen 14:11-14:12Z and 4 events, all La Liga, at 15:09Z. One league's pass makes the file read as freshly swept, so every other league's row (>= 900 s old) is classified, finds no fresher sibling, and is dropped as `market_gone` — though its league was swept normally. Rows survive only in builds within ~15 min of their own league's pass. Replay, same rows and instant: file-wide newest -> 3,461 `market_gone`; league-scoped newest -> 0.
- **Second defect beside it, NOT the cause (H4 falsified):** the drop reads `read_quote_last_seen(sport, selected_date)`, but game markets are filed by COMMENCE date (`fetch_soccer_oddsapi_props_local.py` groups by `commence_time`), so the 09-16 file holds corners/btts/h2h keys only for the 4 fixtures commencing 09-16. Swapping in the rows' own 09-19 file changes nothing (still all `market_gone`), because the file-wide newest stamp is the binding error in both.
- **Kill switch exists:** `SYNDICATE_DROP_MARKET_GONE_ROWS=0` (env, refresh-worker; needs a deploy to take effect). It also re-admits genuinely dead markets, which is why the drop was added (`b54e6a68`, user 2026-08-30 "Drop them").

- **FIX (live `03851b5a`):** `_sweep_reference_age` -- the reference is the most recent pass that re-observed >= 50% of keys seen within `SHORTLIST_MAX_QUOTE_AGE_SECONDS` (nothing recent -> the newest stamp, the old slow-sweep protection); and a row is judged only by state files that HOLD its group (its commence-date file and the shortlist date's), each with its own reference, dropped only if every judge says `market_gone`. Instrument: `MARKET_GONE_REFERENCE sport= date= keys= newest_age_s= reference_age_s=` per file per build on refresh-worker. Verified: soccer max drop 753 -> 12 and MLB 1,009 -> 217 over the first 4 builds; the 16:19:41Z build ran with a partial pass newest (MLB `913 / 3251`) and dropped mlb 84 / soccer 5; served soccer 1,160 at 17:02Z with both shortlists holding soccer at once. `deploys.md` 16:05:22Z, 17:02Z.
- **Full-day reading `[2026-09-17 16:05Z, scheduled task market-gone-full-day-reading-0917]`: HELD.** 107 builds, 2026-09-16 16:19Z .. 2026-09-17 16:00Z, fully paged. Of those, 89 were PARTIAL-PASS: soccer max drop 23 (median 5), mlb max 171 (median 83). 0 `DROP_FAILED`/`DROP_SKIPPED`. Served soccer 985. Aside, not graded: ncaaf dropped ~460 per build 09-16 17:17-21:46Z. -> deploys.md `2026-09-17 16:05Z (11:05 CT)`.

## [kalshi-prop-quote-identity] KALSHI PROP QUOTES WERE FILED UNDER THE CANONICAL KEY WITH NO GAME, AND REFRESH-WORKER'S NFL PROP ARTIFACT WAS FROZEN FOR TWO DAYS — both fixed; the artifact half MEASURED, the quote half owes a production reading `[2026-09-10/11, refresh-worker 5767e3ac, lane nfl-layer2-kalshi-identity]`

**What the user saw on the NFL board:** a "Matchup" game card holding 65 opportunities from eight games. Every row read NO SIM VIEW at -0.9% EV, the "fair" price was the row's own price +2, and the labels were raw `player_pass_tds`.

**Quote half.**

- The defect had three parts:
  - `odds_book_quotes.quote_rows_from_kalshi_matches` (#617) wrote Kalshi prop quotes under the join's CANONICAL key, with no `home_team`/`away_team`/`commence_time`, into the BOARD-date shard.
  - The NFL/NCAAF OddsAPI capture writes DISPLAY labels (`Receptions`) into Central KICKOFF-date shards.
  - `book_grid._instance_key` keys on the raw market.
- Consequences:
  - Each Kalshi price became its own one-book row. Its fair was de-vigged against itself, so EV = -hold/2.
  - The NFL prop join refused these rows as `unsupported_markets`.
  - The rows had no game and no `game_state`, so no live gate could refuse them. Peer `2edf8b82` measured SF @ LAR's 16 served as pregame during the game.
  - `game_date` fell back to the board date. The rail then folded the label-less groups into one card.
- Measured on web's NFL 09-10 shard: 261 such rows, 0 with `commence_time`, and 150 of them for other days' games.
- Fix:
  - `book_quote_prop_market` relabels nfl/ncaaf props.
  - Identity is stamped from the same event's board rows, for ALL sports.
  - nfl/ncaaf rows are filed by kickoff date.
- Replayed over production's shards: 180/180 rows relabelled. 15/15 (09-10) and 77/77 (09-13) Kalshi instances merge into their sportsbook rows.
- **The production reading is OWED:** the first tick with an NFL prop match. The two ticks after the deploy had none. It is ARMED as scheduled task `nfl-kalshi-identity-sunday-reading`, which fires once on 2026-09-13 at 12:30 CDT (verified enabled via `list_scheduled_tasks`, 2026-09-11). The task takes R1 (relabel), R2 (the 09-13 shard) and R3 (served rows with no game state during live games), and closes the lane only if all three pass.
- **Early evidence, 2026-09-11 -- NOT the formal reading:** web's NFL 09-13 shard holds 498 Kalshi prop rows, all captured after the deploy (04:05-09:53Z). All 498 carry a display label (`Receptions` 316, `Passing TDs` 182), `commence_time` and `home_team`. The user's 09-11 "Matchup" card is residue: web's NFL 09-11 shard holds 205 Kalshi rows, all captured 09-10 20:35-23:31Z by the pre-deploy code, which filed under the board date and also built TOMORROW's board. No 09-12 NFL shard existed at 15:3xZ.

**Artifact half: MEASURED.**

- `build_nfl_prop_projections` repaired only an EMPTY local copy, and refresh-worker cannot build the artifact.
- So the worker kept a 980-row copy built 2026-09-08T20:17:22Z, before the line key existed. Only Anytime TD could match it.
- The builder now pulls over a populated copy and keeps the pull only if it is populated and not older. Otherwise it rolls back.
- Production readings:
  - `REPAIR_PULLED_NEWER 980 -> 1140` at 03:50:19Z.
  - Ingest `artifact_rows` 683 -> 1140, and `rows_with_projection` 237 -> 877.
  - Page sim views 116 -> 602, of which 486 are not Anytime TD.

**Standing rule:** a Kalshi prop price is filed in the shard's own vocabulary and on the shard's own date. `tests/test_kalshi_book_quote_capture.py` pins the label map against both fetchers' `MARKET_STD_MAP`. `Interceptions` is the one label `market_keys` cannot canonicalise, so it passes through unrelabelled.

## [layer2-live-quote-age] LIVE LAYER 2 ROWS WERE AGED ON THE MOVEMENT CLOCK — the observation gate and the in-play sizing refusal are LIVE since 20:20Z, and live cards show the price's age since 21:43Z `[verified 2026-09-12 18:39-21:53Z, lane layer2-live-scorecard-gate]`

**Production behaviour, measured on `/api/board/layer2-shortlist`:**

- `opportunity_gate.evaluate` judges an in-play row on `book_age_seconds` (time since the price MOVED, ceiling 900s) and never on `quote_seen_age_seconds` (time since we LOOKED). `quote_seen_age_seconds` is stamped at BUILD time, so what is served is older by the shortlist's own age.
- Build 18:34:57Z: NCAAF live opportunity rows at seen age p50 351s, p90 1,013s; read 267s and 562s after build. Example: WF @ PUR Q4 10:32 ranked +4.8% EV on book age 618s, seen age 1,013s.
- Build 18:44:05Z, live opportunity rows: MLB 12, all <=120s. NCAAF 53: 26 <=180s, every one venue-quoted; 13 >900s and 14 with no seen clock, every one sportsbook-priced.
- Every NCAAF row is `ev_basis=market_fair` (model edge withheld by the measured gate). Both sides of one total were +EV at once on 2 of 8 two-sided live lines, and 9 of 29 live markets carried more than one line.
- 09-12 builds served: 18:34:57, 18:44:05, 18:54:48, 19:10:31, 19:21:09, 19:28:10Z (gaps 421-943s). Refresh-worker `LAYER2_BOARD_HEALTH sport=ncaaf` at 19:21:06Z: `age_p50s=697 age_p90s=9025`.
- Until 20:20Z `portfolio_commit` had no in-play or quote-age refusal. `execute_portfolio._kalshi_price_for` re-reads the live ask but refuses only when our side got DEARER.

**One-build NCAAF collapse, 19:21:09Z:** refresh-worker `MARKET_GONE_DROPPED ... ncaaf=868 ... total=1214 of 4929` (the four builds before: 1/33/22/1) served 356 of 1,224 selected; the 19:28:10Z build served 1,166. Not the shard merge: web logged 0 `LAYER2_SHARD_MERGE` lines 18:55-19:27Z. The API does not return `rows_market_gone_dropped`, so only refresh-worker's log shows it. Cause (books pulling in-play markets vs a capture gap) is UNPROVEN; see `leads.md` 2026-09-12.

**live-odds-worker, Render events:** `server_failed` oomKilled 2Gi at 18:08:51, 18:30:14, 18:42:16 and 18:59:57Z on 09-12, during the NCAAF slate.

**DEPLOYED 2026-09-12** by lane `nfl-prop-certainty-refusal`, under a user override that session reports: web and refresh-worker `77f8d890` (live 20:11:32Z and 20:20:09Z), carrying `8d4aceff`.

- In-play rows must also be observed within `LIVE_QUOTE_MAX_OBSERVED_AGE_SECONDS` = 300s (`live_quote_unobserved`; env `SYNDICATE_GATE_LIVE_MAX_OBSERVED_AGE_SECONDS`). Its EFFECT is measured on the served board (session capture of `/api/board/layer2-shortlist`, NCAAF, split by build `written_at`): live opportunity row-polls observed more than 400s old at build were 1,637 of 3,716 over 13 builds before 20:20:09Z, and 0 of 14,103 over 60 builds after. 659 after were 300-400s old, which is the ~97s gap between where the gate judges and where the age is stamped. The reason itself is still not read: dead rows are not served, and there is no reason counter.
- **The gate judges an age ~97s younger than the row publishes.** The gate runs inside `build_layer2_rows` at `pipeline/layer2_shortlist.py:1359`, BEFORE `apply_venue_quotes` at `:1495`, whose `stamp_candidate_freshness` re-stamps `quote_seen_age_seconds`. The 39 served Polymarket rows were judged at 256s, published at 353s, and served ~74s later.
- `portfolio_commit` refuses `in_play_market_fair`, and it **fires**: `PLAN_WRITTEN date=2026-09-12` 20:43:45Z `in_play_market_fair: 41`; the live Polymarket plan refused 13. Revert with `SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR=allow`.
- From 20:20Z openings record `game_state`, `book_age_seconds`, `quote_seen_age_seconds` and `quote_source`. None has been read on a production record yet.
- **Live price age on cards:** web `064fb6af`, live 21:43:49Z. `renderFreshness` shows "Price seen ≈Xm ago": the seen age plus the time since the freshest artifact build (`state_meta.read_at - newest_age_seconds`), styled stale over 300s. The served page is content-verified, and the user confirmed on the live board ~21:53Z that it shows a plausible age.

**Before the deploy, refresh-worker's heavy build aborted every cycle** (`MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint floor_mb=1900`, 19:42-20:08Z), so no `PORTFOLIO_COMMIT` ran from 14:34:17Z to 20:45:13Z. There were 0 aborts 20:20-20:40Z after the reboot, which is boot-confounded. **The gate is NOT shown to improve results:** the 09-12 capture at 19:04Z did not discriminate, n=7 vs n=9.

**Grading:** `scripts/layer2_live_scorecard.py` (`a989e256`) settles `reports/intelligence/clv_openings/<date>.jsonl` against `/api/board/game-chips`. `--split-at` splits results into windows by `captured_at`. Departures: refresh-worker records which +EV markets LEFT the board at each build (`clv_departure_ledger`, live since `3e18be8e` 2026-09-13 14:14:19Z); web exports `reports/intelligence/clv_departures/<date>.jsonl` since `9c7d34bc` (14:44:53Z, `PUBLISH_OK` 14:45:37Z); the scorecard reports `n10`/`gone10` from it. Verified end-to-end 2026-09-13 21:45Z against a same-slate NFL capture: 209 of 209 verdicts agree (57 live). The day's file then held 34 builds, 1,739 departures and 665 returns (1,034,914 B). Builds were 222-1,421 s apart, against ~7 min on 09-12, and a later deciding build reads more gone (live 63% when it came within 15 min, 78% beyond). A sighting counts only if the log has a build at its stamp. Openings captured from refresh-worker's 20:20:09Z deploy carry `game_state`, `book_age_seconds`, `quote_seen_age_seconds` and `quote_source` (4,731 of 4,731; 0 of 19,658 before). FULL-SLATE reading (all 80 09-12 NCAAF finals, 1,661 +EV opportunities): in-play after the deploy 264-246-1, +23.56u (+4.61%, 61 games); in-play before it (by clock) 149-161, -9.41u (-3.04%, 33 games). Those are different games and hours, so the gap is not a gate effect. At the shown price, stale live rows did not settle worse (session capture: served under 5 min +5.81% on 71 games, 10 min+ +15.80% on 25), but they were gone at +10 min more often (61% vs 75%). Its team join is complete only with the NCAAF registry reachable (0 unmatched vs 32 without). The opening ledger is heavy: 09-11 closed at 22,607,063 B, 67.4% of the 32 MiB tripwire; 09-12 closed at 23,513,778 B (70.1%), last record captured 04:58:46Z, the Central date roll (full export 2026-09-13 07:35:57Z).

## [layer2-prior-date-carryover] A GAME STILL LIVE AT MIDNIGHT CT LOST ITS LAYER 2 BOARD — the carryover and the stale-live label are LIVE; the midnight crossing itself is NOT yet measured `[verified 2026-09-13 13:23-16:24Z, lane layer2-prior-date-live-carryover]`

**Mechanism, measured on refresh-worker logs 2026-09-13:**
- The board window is `_default_board_window_dates(central_today_iso())`: today..today+2, with future days kept only if they are in `_supported_intelligence_dates()`. At 05:00:00Z (midnight CDT) the prior date leaves it. The last `BOARD_WINDOW_QUEUED date=2026-09-12` was at 04:56:07Z; from 05:00:08Z only 09-13 was queued.
- A queued prior-date payload would be refused anyway: `_watched_payload_eviction_reason` returns `stale_date`. That guard exists because a full publication of a rolled-over date once emptied the served board (2026-07-25).
- The next date's board cannot carry the game. `resolve_window_dates` is forward-only, and NCAAF quote shards are keyed by Central kickoff date (NMS @ HAW kicked off 11:05 PM CT on 09-12).
- Result: `/api/board/layer2-shortlist?sport=ncaaf&date=2026-09-12` kept serving its 04:58:55Z build, 28 rows `live` over six games (five already final), until at least 15:00:41Z.
- On 09-12 every build of that date was the FAST path (`LAYER2_FAST_REFRESH`, `elapsed_s` 133-182); the heavy build was refused throughout.

**Live now:**
- refresh-worker `c114e1aa` (live 16:23:12Z, contains `822ee0ba`):
  - Each `_background_loop` pass calls `_maybe_carry_over_prior_date_layer2`.
  - It rebuilds the prior Central date through `_refresh_layer2_shortlist_only`, never a queued payload, so there is no pool build, no latest-key write and no portfolio commit.
  - It keeps rebuilding while that date's last good build had `live_rows` or `chips_live` > 0. With no signal after a restart, it builds once.
  - Capped by `SYNDICATE_LAYER2_CARRYOVER_MAX_HOURS`: default 6 (absent = 6); 0 disables.
  - It yields to the fast path's 300 s per-date rate limit, a deploy drain, a resident MLB sim and the execution guard.
  - Log lines: `LAYER2_CARRYOVER date= decision= reason=`; `LAYER2_FAST_REFRESH` gains `live_rows=` and `chips_live=`.
- web `822ee0ba` (live 15:07:20Z): `/api/board/layer2-shortlist` serves rows a build older than `SYNDICATE_LAYER2_LIVE_STATE_MAX_BUILD_AGE_SECONDS` stamped `live` as `game_state=unknown`, `is_live=null`, `market_state=unknown`, keeping `game_state_at_build`.
  - The ceiling defaults to 1800 s (absent = 1800); 0 disables.
  - Top-level fields: `build_age_seconds`, `live_state_max_build_age_seconds`, `rows_live_state_stale`.
  - It relabels rows only. The combined board's cards are restated separately, by `_refresh_layer2_live_state`.
  - **`_refresh_layer2_live_state` reads the worker-published chips `[verified 2026-09-15 02:34Z, web c4f45fee]`.** It reads `read_game_chips`, the artifact `/api/board/game-chips` serves (fresh <= 600 s wins over the in-process build), not only `build_game_chips`.
    - The in-process build on web yields no live NFL chips. Before the fix every live NFL L2-A card stayed unrestated and was re-gated watchlist / `no_game_state`: DEN @ KC 72 props, NFL live cards 0.
    - After it: 72 props `opportunity` / `live`, NFL live cards 87, `LAYER2_LIVE_RESTATED` 932 of 2718.
    - The combined board also restates per-date state rows before its first contract build (`dedfede6`); that path had no rows in production.

**Readings:**
- W1 MET, 15:08:17Z: the 09-12 NCAAF board went 28 -> 0 `game_state=live`, with `rows_live_state_stale` 28. The 09-13 board (build 746 s old) kept its 10 live rows, 0 relabelled.
- R1 MET, 16:23:59Z: `LAYER2_CARRYOVER date=2026-09-12 decision=skip reason=past_cap hours_since_roll=11.4 max_hours=6.0`, 6 s after `BACKGROUND_LOOP_START`.

**NOT measured:**
- Whether the carryover keeps rebuilding a board while a game is live across midnight CT, what spacing it holds under production contention, and whether it stops with 0 live rows.
- These are owed to scheduled tasks `layer2-carryover-roll-reading-0914` (the 09-14 roll), `layer2-carryover-crossing-reading-0915`, and backup `layer2-carryover-crossing-reading-0919`.
- Cost: while the carryover runs, today's board and the prior date alternate ~3-minute fast builds.


## [mlb-doubleheader-joins] A TEAM PAIR WAS NOT A GAME: EVERY MLB DOUBLEHEADER JOIN COLLAPSED, AND SIX ARE NOW FIXED AND LIVE `[verified 2026-09-22, lane mlb-doubleheader-e2e]`

TB @ NYY played a split doubleheader on 2026-09-22 (gamePk 823543 17:05Z, 823494 23:05Z; OddsAPI events `394e1e2b` 17:06Z, `574050c1` 23:06Z). Every join that keyed a game on its TEAM PAIR kept one half for both, measured on the served board at 16:29Z:

    join                                    was                                   now (board ~16:37:38Z, deploys.md 16:29:43Z)
    attach_game_state (chip)                G2 rows read G1's chip "12:05P CT"    own chip; rows_resolved_by_start_time 310, ambiguous 0
    attach_live_game_state_from_lens        first lens game per pair              own game (G1 live never moved G2)
    prop_projections game lines             G1 h2h 0.531 (= G2's sim)             0.606 (its own); rows_resolved_by_game_pk 269
    prop_projections player props           both halves 1.502/0.308 (= G2's)      G1 1.513, G2 1.502
    kalshi_board_join props                 both rows -> one ticker               each contract to its own game's row (`prop_game_resolved`)
    polymarket_board_join                   a line only one half lists paired     `dhN` must equal the row's game number
    venue fan-in (`venue_quote_fanin`)      G2 rows stamped G1's ticker/price     `|dh<n>` keys; doubleheader_sides qualified 507
    vendor pick lines (daily_update_multi)  both cards priced off G2's event      823543 -> 394e1e2b 17:06Z, 823494 -> 574050c1 23:06Z (cards 17:28Z)
    `_refresh_layer2_live_state` (web)      G2 cards took G1's state and score     own chip (G2 pregame while G1 LIVE, 17:04:11Z)
    Layer 2 page rail                       one merged card + an empty one        two cards: "TOP 1 ● LIVE" and "6:05P CT PREGAME" (17:03:56Z)

The rule is one helper, `shared/doubleheader.py`: nearest start to the row's own `commence_time`, refusing a pair it cannot separate by 45 min and (MLB) a lone hit more than 12 h away. The same rule fixes a SERIES collision: the pair repeats on consecutive days and a multi-date board took whichever date's chip was indexed first.

**NOT measured:** the ORDER path on a real position -- no TB/NYY venue position was planned or ordered through 17:3xZ, so the Kalshi/Polymarket fixes are verified only offline on production ticker/slug shapes. Kalshi listed no G2 PROP events at all that day (public API), so "G2 prop `venue_ref` = None" is the honest answer, not a join failure.
**STILL PAIR-KEYED (not fixed):** vendor `build_season_betting_cards_manifest._load_game_lines_lookup` (grading), the OddsAPI props file (one entry per player, events merged), `live_gameline_ledger.record_key` (no event_id), `settlement_identity` phases 2/3 for records with no id. Order SETTLEMENT is safe: `bet_status_mlb` matches on commence_time within 1 h and refuses `ambiguous_doubleheader`.

## [nhl-chip-start-time] NHL CHIPS CARRIED NO START TIME AND NO STATUS TOKEN UNTIL 2026-09-22 — FIXED AND LIVE -- BOTH HALVES MEASURED `[verified 2026-09-22 pregame + 2026-09-23 live, lane nhl-compact-card-start-time]`

Every NHL chip read `start_time_utc: None`, `status_token: None` and `game_key` "1".."10" (a row index), so the Layer 2 Games rail showed a bare "NHL PREGAME" where every other sport shows "MLB · 5:35P CT". The NHL card game is built from `predictions_<date>.csv`, which carries only `date` (`odds.commence_time` = "2026-09-22", no `T`). The live overlay `_apply_nhl_live_scores` ALREADY fetched the NHL schedule (`NhlWebClient.scoreboard_day`: id, `startTimeUTC`, state, period, clock; 10 of 10 of that day's cards join by full team name) and `_load_nhl_scoreboard_rows` dropped `gameDate` on the way.

`3e8ff188` (refresh-worker, live 17:34:59Z): the loader keeps `gameDate`, the overlay stamps it (refusing the client's `<date>T00:00:00Z` placeholder) and sets `live_state.period` / `.clock`. Measured: chips 0/10 -> 10/10 with start time and token (artifact 17:35:51Z), rail "NHL · 6:00P CT PREGAME NYI – NYR" (17:36:51Z), NHL now interleaved by start with MLB/WNBA.

**LIVE HALF MEASURED 2026-09-23 00:23:37Z (7:23 PM CT), both halves now MET** (scheduled task `nhl-live-chip-reading-0922`, read-only). Off a `worker_artifact` 18.7 s old: **NHL 7 of 10 chips `state: "live"` with a period token and numeric scores on both sides** -- "P2" x5, "P1" x2 -- while 3 of 3 unstarted kept "8:00P CT"/"9:00P CT"; rail "NHL · P2 | ● LIVE | NYI | 0 | NYR | 3", no bare "LIVE" and no bare "NHL PREGAME" on any of 15 cards. Period agrees with NHL's own `/v1/schedule/2026-09-22` on 10 of 10 (one score off by a goal: ~2 min read skew on a live game). WNBA same-shape check PASSED too: 3 of 5 live at "Q2 0.0" / "Q1 2:03" / "Q1 0.0", period agreeing with ESPN 5 of 5. **The NHL token carries NO clock, and that is the SOURCE:** `/v1/schedule/<date>` returns `clock: null` on 7 of 7 live games and `NhlWebClient.scoreboard_day` (`local_nhl_odds.py:316`) reads exactly that endpoint, so `clock_value` is None before the overlay sees it -- `/v1/score/<date>` or gamecenter would carry one, unclaimed. **`/api/board/game-chips` IGNORES `?sport=`** (`sport=nhl` and `sport=wnba` returned byte-identical 77,136-byte payloads with all four sports); filter on the chip's own `sport` field. The card's `gamePk` is deliberately still the row index: other NHL rows join on it.


## [ncaaf-kickoff-cache] AN UPCOMING NCAAF CARD READ "TBD" BECAUSE THE COMMITTED CFBD CACHE WAS THE JULY SNAPSHOT — FIXED BOTH HALVES `[verified 2026-09-22, lane ncaaf-kickoff-cache-staleness]`

Measured four days before the games: `/api/board/game-chips?sport=ncaaf&date=2026-09-26` returned 65 chips with **43 on the noon-Central fallback** (`2026-09-26T17:00:00+00:00`) and 42 `status_token`s reading "Sat Sep 26 - TBD". `build_ncaaf_chip_games` writes `startTime: None` when the schedule row says `startTimeTBD`, and `_resolve_scheduled_start_utc` then falls back to noon.

**TWO THINGS WERE TRUE AT ONCE, and only the second moved the board:**
1. `games_payload_is_stale` only asked whether a game that kicked off >12 h ago was still `completed: False`, so kickoff times firming up never triggered a refresh. `97066dbe` adds: a `startTimeTBD` whose own kickoff is within 10 days is stale (bounded to CFBD's firming window; the producer stays quota-latched and throttled).
2. **`DEFAULT_CACHE_DIR` IS THE REPO CHECKOUT, NOT THE DISK** (`/opt/render/project/src/data/ncaaf_source/historical_truth/games_2026.json.gz`), so a worker-side refresh is ephemeral and never reaches web -- and the chips for an UPCOMING date are built INLINE ON WEB (`source: inline_artifact_missing`; today's read `worker_artifact`), from web's committed copy. That copy was the July snapshot: 888 rows, `completed: False` on 888 of 888, 42 week-4 TBD. `cc5bdfb1` re-fetched it from CFBD.

After web `cc5bdfb1` (20:11:20Z): placeholder starts **43 -> 0**, "TBD" tokens **42 -> 0**, distinct starts 14 -> 20 matching CFBD/ESPN (19:30Z x12, 16:00Z x11, 23:00Z x7, 23:30Z x6). The single chip still at 17:00Z is LIN @ EMU, a REAL noon-CT kickoff.

**NOT measured:** the worker's in-process interval after the 20:32:19Z revert (config proven; `3600` was proven in-process at 19:52:18Z beforehand). **Worth knowing:** NBA/WNBA/NHL chips for a PAST date read pregame with no score because the live supplement is today-only, while MLB reads final with scores off its per-date `feed_live` artifacts; nobody claims that.
