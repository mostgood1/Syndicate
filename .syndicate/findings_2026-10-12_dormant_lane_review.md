# Review of the 8 dormant OPEN lane blocks over 7 KB

`[2026-10-12, session 4ab694ed, user request "review the eight dormant blocks over 7KB"]`

Read every block in full on `origin/main` `7d6bce16`. Verdicts below are each
lane's OWN recorded verdict where it has one — **I did not change any lane's
verdict, close any lane, or edit any block.** Four of these say outright that
closing is the user's decision.

## The cost of the status quo, measured

These 8 lanes hold **76 of the 339 claims in the ledger — 22% of all
lane-guard enforcement** — while their owners have been quiet 79–243 h:

| lane | bytes | owner quiet | claims | its own verdict |
|---|---|---|---|---|
| `nhl-game-lines-model` | 10,016 | 129 h | 13 | GOAL: NOT MET |
| `book-quotes-splice-repair` | 9,920 | 219 h | 9 | GOAL: NOT MET, 1 clause left |
| `soccer-corners-model-rebuild` | 9,165 | 243 h | 8 | GOAL: NOT MET, waiting on a date |
| `daily-accuracy-suite` | 8,113 | 171 h | 8 | GOAL: NOT MET |
| `web-restart-healthz` | 7,717 | 79 h | **31** | **GOAL: MET** + drift |
| `layer2-restate-series-date` | 7,677 | 219 h | 1 | **GOAL: MET** |
| `live-inplay-board-cadence` | 7,626 | 219 h | 6 | GOAL: NOT MET, blocked on a decision |
| `refresh-worker-oom-0922` | 7,606 | 219 h | 0 | **READY TO CLOSE** |

**Owner liveness** (proxy: transcript `.jsonl` mtime; archive status where
established): `9ed26377` ARCHIVED, `0f5b256e` ARCHIVED (its block says so),
`9b88f9a2` ARCHIVED by deliberate user decision, `46e09dbb` archived (stated in
a 2026-10-12 loan line in its own block), `a1e40980` ARCHIVED (owns TWO of
these). Not established: `abacd435`, `f134a8b3`.

## Per lane

### 1. `refresh-worker-oom-0922` — says READY TO CLOSE
Goal was to EXPLAIN the 2026-09-22 OOM and say whether it recurs. Its own
reading (2026-09-23) is a PASS: the streamed count is flat at full chunk size
(12,775 lines, past the 12,723 that cost +512 MB), no `oomKilled` since
15:48:56Z 09-22, and that zero is explicitly argued not to be instrument
blindness. Holds **0 claims**. Its own words: *"Lane is READY TO CLOSE (user's
call); closing hands `pipeline/intelligence_state.py` back to
`layer2-restate-series-date`."*
**Recommend: close.** Nothing is owed. Note the handback interacts with #2.

### 2. `layer2-restate-series-date` — GOAL: MET, both halves measured
*"(e) PASS, (f) PASS, (g) PASS. GOAL: MET"*, verified on production across four
samples with real populations (`series_live_pairs` 8/8/7/7, so not a null
result), offender count 16 → 0. Holds **1 claim**. Its own words: *"Closing the
lane is the USER's decision; not closed here."* Owner ARCHIVED.
**Recommend: close.** This is the cleanest candidate in the ledger.

### 3. `web-restart-healthz` — GOAL: MET, but **31 claims** and an archived owner
The four named parts are MET with readings in `deploys.md` (healthz 0 failures
/ 100 probes across a HUP, p50 1 ms). The lane then **DRIFTED, user-directed**,
into board refresh cadence, and stays open for: web cold-start Ask 47.9 s,
two "propose only" hotspots, and **loans still out** on
`intelligence_evaluation.py`, `intelligence_state.py`,
`polymarket_board_join.py`, `venue_quote_*`.
**Recommend: split.** The goal is MET; a lane kept open to park drift and loans
is exactly what grows this file. The cadence work deserves its own lane with
its own goal, and the loans need returning before this can close. **31 locked
files behind an archived owner is the single biggest enforcement risk here.**

### 4. `live-inplay-board-cadence` — blocked on a user decision since 2026-09-26
GOAL: NOT MET, ~60 s off the ~180 s target. Blocked explicitly on USER
decisions: the web OOM first, then lever 2 (grid tick 185 s → 120 s) / lever 3
(capture 154 s → ~80 s, ~2x in-play OddsAPI credits). That decision has been
outstanding **16 days**; owner ARCHIVED.
**Recommend: a decision, not work.** Either take lever 2/3 (lever 3 costs
OddsAPI credits against the 5M cap) or close as NOT MET with the measured
distance recorded. It cannot progress on its own.

### 5. `nhl-game-lines-model` — blocked on an idea, 13 claims incl. production sim files
The calibration half SHIPPED and is MEASURED (settled total bias +0.111 →
+0.008). The ML-discrimination half is NOT MET and the lane states why:
**eight candidate inputs** (machinery, save%, GSAx, prior GSAx, recency,
dispersion, score adjustment, confirmed starters) all fail to beat the as-of
GF/GA baseline with a CI excluding 0, and it is at parity vs the book on
ML/PL/totals. Its `Blocked by` is the real finding: *"the next ML candidate
needs information the book does not already price."*
**Recommend: close as NOT MET and keep the negative result**, or re-scope the
goal to the calibration half that IS met. Leaving it open locks 13 paths
including `game_market_sim.py`, `adapters.py` and `market_lines.py` behind an
archived owner. The negative result is worth promoting to `learnings.md`: it is
the same shape as the MLB "nothing adds to the de-vigged price" rule.

### 6. `daily-accuracy-suite` — **one owed item is already discharged**
UNOWNED by deliberate decision, with a "TO RESUME" note. OWED list is
(a) DISCHARGED 2026-09-21, (b) NBA grading reading at the first regular-season
slate, (c) NCAAB team registry.
**(c) IS SATISFIED AND THE LINE WAS NEVER STRUCK** — verified today:
`syndicate/features/shared/ncaab_team_registry.csv` exists (29,736 B),
`canonical_team("ncaab", "Duke")` returns `duke`, and the pinned test in
`tests/test_population_outcomes_basketball.py` was renamed to
`test_ncaabs_documented_blocker_is_gone_and_ncaab_is_now_registered` — the
mechanism firing as designed. The block's own prose already records the registry
landing; only the OWED line is stale.
**(b) comes due in ~9 days** (NBA regular season, late October). NCAAB grades
nothing until November.
**Recommend: strike (c), and leave open for (b) with a dated reminder.** Do not
flip the goal to MET: "covers EVERY traded sport" is still false as written
because NCAAB has graded nothing.

### 7. `soccer-corners-model-rebuild` — a legitimate calendar wait
GOAL: NOT MET *"and not blocked on work… BLOCKING: sample accrual only."* H27 is
graded forward by scheduled task `soccer-forward-grades-weekly`, final
**2026-11-15**.
**Recommend: leave exactly as is.** This is what a correctly-waiting lane looks
like. Nothing to do until 11-15.

### 8. `book-quotes-splice-repair` — kept open by standing user decision
**USER DECISION 2026-09-17: "leave book-quotes open"** — until a bad line
actually appears. One clause remains: *"0 lines failing `json.loads` in newly
written shards on web and refresh-worker across a full capture day"*, which
needs a shard-CONTENT read; the block is explicit that the refusal count
"stands in for it and is not the clause itself".
**Recommend: keep open (user decision stands), but the owed clause is RUNNABLE
NOW** — read the shard contents on the fleet and count `json.loads` failures.
That is a short job and it would discharge the last clause instead of waiting
indefinitely.

## What this review suggests, in order

1. **Close `layer2-restate-series-date` and `refresh-worker-oom-0922`** — both
   say they are done; 15.3 KB and the `intelligence_state.py` handback.
2. **Split `web-restart-healthz`** — goal MET, 31 locked files, archived owner.
3. **Decide lever 2/3 or close `live-inplay-board-cadence`** — 16 days blocked.
4. **Decide on `nhl-game-lines-model`** — the negative result is the deliverable.
5. **Strike `daily-accuracy-suite` OWED (c)** — verified discharged today.
6. Leave `soccer-corners-model-rebuild` (dated) and `book-quotes-splice-repair`
   (standing user decision) alone, optionally running the latter's owed read.

**Not done here, deliberately:** no lane closed, no verdict changed, no block
edited. Four of these blocks state that closing is the user's call, and the rest
belong to other sessions.
