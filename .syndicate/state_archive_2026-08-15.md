# Syndicate — state.md ARCHIVE, captured 2026-08-15 (2026-08-14 ~22:0x CDT)

> **This is the COMPLETE `state.md` as it stood immediately before the
> 2026-08-15 collapse. Nothing was deleted — everything was copied here first,
> then `state.md` was rewritten to hold only what is CURRENTLY TRUE.**
>
> **Why:** the file had reached 120.8 KB / 1,925 lines / 51 sections while its
> own header said *"Overwrite lines here as facts change. Do not stack
> contradictions."* It was stacking them. `#387` alone appeared in six sections
> with mutually contradictory statuses (`NOT DEPLOYED`, `mechanism SHIPPED
> cutover NOT DONE`, `FIX IS DEPLOYED`, `VERIFIED ON A FULL 3h CLEAN WINDOW`),
> each true when written. A reader taking the first match got a stale fact.
>
> **How to use this file:** it is a search target, not a read-through. If a
> fact is missing from `state.md`, grep here before concluding it was never
> measured. If you find something here that is still true and load-bearing,
> promote it back to `state.md` — do not cite this file as current.
>
> Superseded readings and the reasoning trail behind them also live in
> `deploys.md`, which is the append-only measurement log and stays that way.

---

# Syndicate — Verified System State

> Overwrite lines here as facts change. Do not stack contradictions.
> Every line carries an evidence tag and a date. Untagged lines are invalid.
> **Seeded 2026-08-13 from prior session notes. Lines marked `[unverified]`
> must be confirmed against the dashboard before anyone relies on them.**

## >>> START HERE — HANDOFF (2026-08-15 00:36Z, supersedes the 21:30Z one) <<<

**THE 21:30Z "single next action" IS DONE, AND TWO OF ITS CLAIMS WERE WRONG.**
`docs/ai_context/handoff_tier0_and_board_engine.md` is still the program map;
read it for Tiers 1-6, NOT for the memory item. `.syndicate/plan_2026-08-14_program.md`
for sequencing.

**`#387` FIXED BOARD COVERAGE. IT DID NOT FIX THE OOM, AND THE WORKER IS STILL
BEING KILLED EVERY ~15-20 MINUTES.** `refresh-worker` was OOM-killed **16 times
on 2026-08-14**, five of them inside the window this file previously called
clean, the last at **00:41:16Z — 26 minutes after both halves were live**.
Source: `/v1/services/<id>/events`, NOT the logs (a killed process cannot log
its own death; the log grep that returned 0 is worthless for this question).

**THE KILL IS MLB GAME HYDRATION IN pid 39, NOT THE OVERVIEW.** At 00:41:16 the
main worker went 1612MB -> 3079MB in 28s with children small (166MB, 95MB) and
payloads tagged `game_count: 15`. At the handoff's canonical 20:03:11 kill the
container was at **28.8%** twelve seconds prior, `stage=post_build_overview` —
the overview had already finished. The 2026-08-07 guard comment had this right:
it is a circuit breaker around MLB's cost, not a fix for it, and the real work is
`build_cards_page_context` running HYDRATED on the worker.

**Leave the 3000MB floor in front of MLB alone.** It guards the wrong stage, but
lowering it only admits more work to a process that is dying elsewhere.

**MEMORY / `#387` SHIPPED — TWO commits, and what it actually delivered is
BOARD COVERAGE, not memory.**
- `cfee9c6e` — the streaming cutover, rebased onto the then-live SHA. Live
  22:55:35Z. Now carried inside `96e3a9b7` and `705eeefc`.
- `705eeefc` — **the other half.** Live 00:15:08Z. Without it the cutover
  truncated the board to ONE sport for 80 minutes.
- **Live SHA at 00:43Z is `098877e1`** (another session's `mlb props`, live
  00:22:24Z). It has `705eeefc` as an ANCESTOR and carries
  `_OVERVIEW_MIN_SAFE_HEADROOM_STREAMED_BYTES` — checked by ancestry AND marker.
  The verified build ran on `098877e1`, not on `705eeefc`; say the SHA that was
  actually live, because this one moved 90 seconds after mine went live.
- VERIFIED 00:28:50Z, re-read 00:43Z: `BOARD_OVERVIEW_READY sports=8` on **1
  build**, against **5 consecutive `sports=1`** before the fix.
  `OVERVIEW_STOPPED_FOR_MEMORY` 0 since 00:15:08Z. **~~`oomKilled` 0 since
  22:55Z~~ RETRACTED 00:5xZ — false, and it came from a log grep; there were
  five kills in that window. See the retraction in `deploys.md`.**
  peak anon **1404.5MB = 34.3%** of the ceiling with the trace falling
  1404 -> 1172MB as MLB is released. Layer 2 unaffected (142 rows / 12,826
  considered). **The pre-fix baseline is the strong half — one post-fix build is
  a result, not yet a rate.** Full working in `deploys.md`, 00:36Z entry.

**CORRECTION 1 — `086702ae` was never deployable.** It is not a descendant of
any SHA that was live after 22:12Z; deploying it would have rolled back
`clv-opening-ledger`. It was also THREE commits, not one. Rebase, do not deploy
a branch tip that has sat while others shipped.

**CORRECTION 2 — the diagnosis it rested on is FALSIFIED.** "Eight hydrated
sports cannot fit in 4GiB / the floor plays no part" — the same 8-sport pass ran
twice that evening at 613MB and 804MB. **The 20:03:11Z kill is UNEXPLAINED.**
See `learnings.md` 2026-08-15 EXONERATED. Streaming caps the transient; it did
not explain the outlier, and the 3000MB floor in front of MLB stays until
someone does.

**CORRECTION 3 — the test baseline in the old handoff is for the wrong lineage.**
`tests/test_intelligence_state.py` carries **6 pre-existing failures** on the
deployed lineage (measured at `2b14fbeb`: 218 passed / 6 failed), not the "223
passed, 1 failure" of `main`. Gate against the lineage you are shipping.

**Deploy method that worked 3/3 with ZERO jobs killed:** poll
`deploy_preflight.py` every 10-12s, require TWO consecutive CLEARs, fire in the
next step. Windows are rare (~30 min of HOLD is normal) but they do come.

Still held on branches: `9ec20a06` (odds cadence — needs `soccer-odds-coverage`
sign-off and an OddsAPI spend call). Local only: `0ddecded`.


## BOARD / INTELLIGENCE ENGINE AUDIT — notes exist, ~70% of the brief `[measured 08-14 21:xxZ]`

**Read `.syndicate/audit_2026-08-14_board_engine_SYNTHESIS.md` first** — it
carries the brief's five deliverables. Passes 1-3 are the working.

Structural facts now measured, none previously in this ledger:
- Board path: **506 files / 238,071 lines**, 43 over 1,000 lines.
- **24 import cycles. 24 hub modules >10 importers** — `rank_board` (29) and
  `game_board_contract` (28) are board CONCEPTS carrying hub load.
- **164 of 390 modules statically unreachable** from any route or loop entry.
  **SHORTLIST, NOT A DELETION LIST** — thread targets and registries not followed.
- **38 functions whose every return is `None`/`[]`/`{}`.**
- Config: web **73** keys, workers **104**, code reads **127**.
- **42 sites define or convert a probability.** The `edge`/`EV`/`confidence`
  collisions are probably ONE substrate problem, not three bugs.
- **`model_skill` and `min_value_pct` have ZERO defining functions.**
- **19 freshness / 23 market-movement / 18 prob<->odds implementations.**
- Neutral-default surface: 40x `0.5`, 240 bare `except: pass`, 388 filters that
  return their input unchanged on empty.
- **91 of 390 modules branch on liveness; there is no single pregame/live
  boundary** — it is a cross-cutting conditional, not a seam.
- Chat reads the shortlist ARTIFACT directly (2 of 4 `read_layer2_shortlist`
  call sites are `ask_the_syndicate_data.py`), so chat staleness IS artifact age.

**Proposed invariant (§7), not yet implemented:** a probability, edge or EV not
computed from data must be `None`, never a number — enforced in
`game_board_contract`, which 28 modules import and every card passes through.

**BLOCKED ON INPUTS, not effort:** §9 needs the shadow candidate ledger turned
ON (it is off, so filter precision is structurally unmeasurable); §10's target
architecture needs the §5 glossary, which must be built by READING — two
mechanical attempts failed and are recorded.

**GUARD ON TWO LISTS IN THAT AUDIT.** The 164 unreachable modules and the 71
configured-but-unread env keys are shortlists. The env list contains
`MLB_LIVE_LENS_DIR`, whose only reader is a VENDORED module called at import
scope; `learnings.md` records that deleting it would have broken MLB live-lens.
The scan excluded `vendor/` and `scripts/` — the exclusion that produced seven
false positives before.

**Three of the audit brief's own "known" inputs are wrong:**
`static/mlb/board.js` does not exist (cited twice), the devig count is not
settled at 5, and `.claude/worktrees/` holds full repo copies that triple-count
any unscoped grep.

## SESSION / LANE CENSUS `[re-measured 2026-08-15 02:11Z / 21:11 CDT]`

**SIX ORPHANED LANES WERE RELEASED. The 20:4xZ census below is superseded —
read this block first, it contradicts it in two places.**

Method, and why it is different from last time: `list_sessions` with
**`include_archived: true`**. The default call HIDES archived sessions, so a
session that ended reads as "absent" exactly like one that never existed, and
`board-ui-defects` archived *during* this census — present at 02:07Z, gone at
02:10Z. Only two sessions are doing work.

| lane | owning session | verdict |
|---|---|---|
| `clv-without-settlement` | model-audit | **LIVE** (`local_7d3a0641`, fork) |
| `recommendation-lane-correctness` | model-audit | **LIVE** — 7 claims still enforced |
| `memory-cutover-ship` | memory-cutover-ship | **LIVE** (`local_4226a973`) — 4 claims still enforced |
| `mlb-oom-outlier-2003z` | memory-cutover-ship | **LIVE**, 0 claims (read-only) |
| `mlb-hydration-oom-435` | memory-cutover-ship | **LIVE**, 0 claims (read-only) |
| `soccer-odds-coverage` | board-ui | RELEASED — owner archived 19:36Z |
| `soccer-projection-gap` | board-ui | RELEASED — owner archived 19:36Z |
| `mlb-props-regen` | mlb-props-regen | RELEASED — owner archived 08-13 |
| `ask-board-candidates` | ask-audit | RELEASED — owner absent entirely |
| `board-contract-absent-not-neutral` | board-ui-defects | RELEASED — owner archived **02:07:33Z** |
| `odds-props-fabricated-probability` | board-ui-defects | RELEASED — owner archived **02:07:33Z** |

**RELEASED MEANS THE CLAIMS, NOT THE WORK.** Every released lane keeps its
findings verbatim under an `ORPHANED-CLAIMS-RELEASED` header. Three carry
committed work that was never verified against its own stated outcome
(`dda83c18`, `cd2d2866`, `bd40056c`) — do not read those commits as closure.
To resume any of them: `/lane open <slug>` and re-take the files.

**PROVEN, not asserted:** `lane-guard.py` was run on stdin against each released
path — 7 ALLOW. Controls `recommendation_engine.py` and `intelligence_state.py`
still return **exit 2**, so the guard is live and was not disabled.

### >>> A REVERT OF SHIPPED ASK WORK IS STAGED IN THE SHARED GIT INDEX <<<

`git diff --cached --stat` = **6 files, 4993 deletions**, and nothing else is
staged. It removes `ask-board-candidates`' M1 work (`b16eb1f7`): 256 lines from
`ask_the_syndicate_data.py`, 36 from `ask_syndicate_regression.py`, a staged
delete of `tests/test_ask_board_candidates.py`, and three
`reports/ask_regression/*.json`. **All six files exist on disk and the working
tree matches `HEAD`** — the revert lives ONLY in the index.

**Consequence: any session running a bare `git commit` un-ships M1 without
touching one working-tree file.** Fix is index-only and cannot disturb another
session's edits: `git restore --staged <the 6 paths>`. **NOT DONE** — the index
is shared state with two live sessions; it needs an owner's call.

### `.current-lane` CANNOT REPRESENT PARALLEL SESSIONS — this is the root cause

One single-valued file, N sessions. `lane-guard` compares a lane slug against it,
so whichever session wrote last is the only one whose own edits are permitted;
every other session is blocked from ITS OWN lane. That is what "thrash" was, and
releasing orphans reduces the blast radius without fixing it. It held
`memory-watchdog-435` throughout this cleanup and was deliberately left alone.

## SESSION / LANE CENSUS `[measured 08-14 20:4xZ — SUPERSEDED, kept for the record]`

- **TWO LIVE SESSIONS SHARE ONE LANE.** `Model audit` and
  `Audit 2026-08-14 models` are both active and both on
  `recommendation-lane-correctness`. **`lane-guard` matches on SLUG, so it
  cannot separate them, and `.current-lane` is single-valued, so it cannot
  represent them.** Two sessions editing one file set with the guard providing
  neither any protection from the other, and nothing in the harness reports it.
- **MOST OPEN LANES ARE ORPHANED — owner session gone, file claims still held.**
  Only `recommendation-lane-correctness` has a live session. `soccer-odds-coverage`,
  `soccer-projection-gap` (board-ui), `anon-allocation-site`,
  `refresh-worker-anon-leak` (memory-guard), `mlb-props-regen` and
  `ask-board-candidates` have none. This is why `.current-lane` thrashed between
  sessions that no longer exist, and why a cross-lane override was needed for
  `live_refresh_loop.py` — blocked by a lane whose owner had finished.
- **`recommendation-lane-correctness` is disciplined, not sprawling** —
  correcting an over-read of my own. It claims 6 things
  (`recommendation_engine.py`, `layer2_board.py` A3/A4, `opportunity_signals.py`,
  `blueprints/intelligence.py`, 4 test files), each expansion carrying its own
  collision check. It took `blueprints/intelligence.py` at 19:2xZ **after**
  `board-ui-freshness-slip-books` closed. The paths that made it look like a
  land-grab are in its COLLISION-CHECK line as files claimed elsewhere.
  **A regex over a hand-written ledger read "NOT claimed, deliberately" as a
  claim.** Read the block, not a pattern match over it.

## >>> REFRESH-WORKER DEPLOY FREEZE — TRAIN FORMING 2026-08-14 20:3xZ <<<

**Do not fire an ad-hoc refresh-worker deploy. Add to the train instead.**

WHY. refresh-worker took a deploy every ~20 min this evening — `530fc5d8`
15:42, `214f5151` 15:59, `294f9ca9` 16:16, `29ed6de1` 19:49. **Every one resets
every session's measurement window.** One 3h window was lost to this and had to
be re-run. With 4+ sessions shipping, ad-hoc deploys mean we invalidate each
other's evidence faster than we can gather it.

WHY BATCHING IS ALLOWED HERE, against `learnings.md`'s "one substantive change
per deploy while diagnosing": that rule is about changes contending for the
**same metric**. A train is safe when each rider names a metric no other rider
can move. State yours when you board.

BOARDING
1. Name your branch/commits, and **the ONE metric that is yours**.
2. Metrics claimed so far:
   - `layer2-freshness`: memory PEAK on one hydrated overview pass (MB).
     Branch `memory/overview-sum-to-max` = `c39569ef` -> `946d77e3` ->
     `086702ae`.
   - `recommendation-lane-correctness` (model-audit): shortlist row composition
     / EV / which rows seat a slot. Asked, not yet confirmed.
3. **Held OFF the train deliberately**: `odds/pregame-cooldown-per-sport`
   (`9ec20a06`). It changes odds cadence and would confound
   `soccer-odds-coverage`'s per-league measurement. Needs that lane's sign-off.

MECHANICS
- One deploy, assembled on `origin/main`, gate + `/preflight` first.
- **There is no idle window**: MLB sims run near-continuously with ~60-90s
  lulls, so the deploy must be fired from inside a detected lull. A 10s-interval
  poller that fires the POST in the same step as the CLEAR is the method that
  worked at 15:36 (zero jobs killed). A first `CLEAR` is often just a lull
  between sims — confirm with spaced samples.
- Then a **30-minute measurement freeze**, no further deploys, while each rider
  reads their own metric.

BASELINE THAT MAKES THIS WORTH DOING, from tonight's kill: `OVERVIEW_SPORT_BEGIN
mlb` -> `oomKilled` in 25s from a 522MB floor. After the train, that pass should
track one sport and never approach 4GiB.


## Config

- **`#423` — the leak is NOT glibc arena fragmentation. `[measured 08-14 02:18Z]`**
  Ten readings at `anon` ~2031MB: arena coverage **11.0-24.4%**, and
  `system_current` **plateaus at ~393MB while `anon` climbs**. The allocator is
  bounded; the growth is outside it. `mmapped` 0.7MB, `arenas` 2 (cap applied).
  Explains `malloc_trim` returning 0.0-2.9MB at guard time. **Stop tuning the
  allocator.** What holds the other ~1700MB is UNMEASURED — NumPy/Monte Carlo
  buffers are the leading candidate, not a finding.
- **`#414` quote-join index: 21.5x in production. `[measured 08-14 00:18Z]`**
  216,135 -> 10,043 rows walked per call; board-build 21-54s -> 7-8s. Quote
  21.5x, NOT the 130x measured locally — the shard grew ~83k -> ~216k rows/call.
  The profiler counters are CUMULATIVE across the window.
- **Deployed SHAs `[measured 08-14 17:54Z]` — re-read before use. They moved
  FIVE times in one evening, TWICE inside 25 minutes on 08-14, and web moved
  AGAIN during this session's own reconciliation. A stale read nearly shipped a
  rollback and made one blast-radius claim wrong by 20 commits.**
  **SUPERSEDED 08-15 00:2xZ (UTC) — refresh-worker is on `098877e1`.**
  `[measured 00:22Z, deploy status == live]` refresh-worker **`098877e1`**
  (MLB prop skill, cherry-picked `aac18260` onto `705eeefc`). It supersedes
  `705eeefc` (#387 overview floor, another session), `96e3a9b7`, `cfee9c6e`,
  `2b14fbeb`, `7b1f3fdc`, `79148d8e`, `29ed6de1`. Web unchanged at `ea1d2ed6`.
  **DEPLOY RACES ARE REAL HERE:** a deploy of mine was CANCELED at 00:08:31Z
  because another session triggered one 1 second earlier — Render cancels an
  in-flight deploy when a new one starts. Check for an in-flight deploy and
  HOLD rather than firing into it; retrying kills the other session's build.

  **PRIOR (kept for the SHA trail):**
  `[measured 08-14 21:0xZ, deploy status == live]`
  web **`ea1d2ed6`** (19:37:00Z, A3 reader),
  refresh-worker **`7b1f3fdc`** (21:01Z, instrument), which supersedes
  `79148d8e` (20:13Z, ranked #3/#4) and `29ed6de1` (19:49:15Z, A3 builder),
  live-odds-worker **`9a3a5bc6`** (17:42:02Z, unchanged).
  **WEB AND REFRESH-WORKER DIVERGE FROM `b98f5ed7` AND NO SINGLE BRANCH
  FAST-FORWARDS BOTH.** Verified 08-14: deploying web's branch to
  refresh-worker would have DROPPED four commits including `294f9ca9`, the
  `#429` MLB HRR fix. Cut every deploy branch from the TARGET SERVICE's own
  live SHA and check `git merge-base --is-ancestor` before deploying.
  - **Two services are deliberately NOT on `origin/main`.** `9a3a5bc6` and
    `8ff4e513` are cherry-picks onto each service's own live commit, pushed as
    `deploy/soccer-step-order-433` and `deploy/ops-oddsapi-catalogue-433`.
    Deploying either from main's tip would have carried **22 production files**
    from four other lanes — `memory_observability.py`, `run_refresh_worker.py`,
    `intelligence_state.py`, `board_enrichment.py`, `projection_skill.py` —
    onto a 2GB service with an OOM history. The same patches ARE on main
    (`e9990ccb`, and `1bb6fd53`/`18215ef9` local-only); only the deploys are
    pinned. Do not "reconcile" a service to main without re-reading that delta.
  - **`aac18260` (`#428` MLB prop skill) is on origin and on NEITHER service.**
    Checked by ancestry against both live commits at 17:54Z, not assumed.

## Model skill (`#428`) — what is MEASURED and what is not

- **`#428` IS FOUR MODELS, NOT SIX.** `live_projection_join` is a JOIN (its own
  docstring says so) and `game_board_contract` is a passthrough
  (`_first_present(...)`). Neither is backtestable; a harness for either is
  wasted work. Real targets: `soccer_projections`, `wnba_game_projections`,
  `wnba_projections`, `prop_projections`. `[from-code 08-14]`
- **MLB hitter props are MEASURED: BIASED, NOT BLIND.** 2,487 player-games
  (2026-08-01..08-14), joined on `batter_id` — which IS the MLB StatsAPI person
  id, an exact join. Every counting market carries real signal AND loses to a
  constant baseline by sitting too high; de-biasing flips 5 of 7 to beating it.
  `hits` r=0.16 +28.6%, `tb` r=0.15 +17.7%, `rbi` r=0.13 +30.5%,
  `runs` r=0.16 +25.9%, `2b`/`3b` ~no signal, `sb` the only one that beats the
  mean as published. `[measured 08-14]`
- **TWO stacked causes, and a playing-time fix ALONE will not fix it.**
  `pa_mean` +18.4% vs real plate appearances, `ab_mean` +17.2%; per-PA rates
  still +12.2% after normalising. Opportunity explains **55%** of the count
  bias. Fix opportunity first (upstream of every market), then RE-MEASURE.
  `[measured 08-14]`
- **"No measured skill" would have been the WRONG conclusion here** and would
  have suppressed a model that needs calibrating rather than retiring — the
  same shape as `#367`'s NFL totals. Always decompose bias before publishing a
  skill verdict. `[measured 08-14]`
- Written into `mlb_prop_calibration` and attached BY THE PRODUCER, so
  `projection_skill` stands aside for measured markets and still stamps
  `unmeasured` for the rest. `batter_hits_runs_rbis` is deliberately absent —
  it was the degenerate 0.0 through the whole window. **NOT DEPLOYED**
  (`aac18260` is committed and pushed only). `[code 08-14]`
- **WNBA game lines: NOT MEASURABLE YET, nothing broken.** `pred_margin` starts
  2026-08-02 — 47 files no column, 0 unpopulated, 14 fully populated. 9 of 361
  completed games carry one. n=30 due ~2026-08-26. `[measured 08-14]`
- **PRODUCTION HAS FAR MORE HISTORY THAN THE CHECKOUT: 81 WNBA dates vs "4
  files" locally.** The local `game_cards_*.csv` are 7-column stubs with no
  projection column at all. Never scope a backtest from the checkout.
  `[measured 08-14]`
- **UNKNOWN, and NOT zero:** `wnba_projections` and `soccer_projections`
  coverage. Both sweep readings were probe failures (wrong CSV shape; guessed
  path, no control) and are retracted as evidence. `[unverified 08-14]`

## NFL day-of-game and the projection column (`#377`, `#425`, `#429`)

All measured on production 2026-08-14 unless marked otherwise.

- **NFL game state is REAL on the board.** `by_state` went
  `{pregame:6, live:0}` -> `{live:5, pregame:1, final:0}` with real scores and
  clocks (`DET@CIN 3-10 Q2 0:07`). Cause was one missing join:
  `_NFLDataProvider.games()` handed `build_game_chips` week-scoped projection
  cards carrying no state at all, so `_game_flags` returned `(False, False)`
  for every NFL game forever. Fixed by stamping `live_state` in the card
  builder — the choke point `publication_adapter` and `game_chip_scoreboard`
  both already read. `[measured 08-13]`
- **The board's live/final counts LAG by up to one artifact rebuild (~15 min
  observed).** Not a defect; do not read a stale `live` as a state bug. A
  reading that disagrees with ESPN is expected inside that window.
  `[measured 08-13]`
- **`#377`'s constant is GONE and was never a model failure.** The board served
  one `margin 0.96 / total 44.38 / home_win 0.5267` for all 16 preseason games
  because `load_nfl_game_projections` deduped candidate files by NAME across
  source roots and read a copy generated where the nflverse pbp was absent.
  Now dedupes on resolved PATH, drops both-sides-neutral rows, newest
  `generated_at` wins. `projected` distinct **1 -> 6**, and the board and cards
  — which read the same filename and had disagreed — now agree **6/6** to
  three decimals. `[measured 08-13]`
- **A constant that reproduces EXACTLY from an empty input is a data outage,
  not a weak model.** Running the real generator with empty
  `prior_season_plays` reproduced `0.960 / 44.380 / 0.5267` on all four weeks.
  Use that test before touching any model. `[measured 08-13]`
- **`#425` gap 2 — degeneracy detection — LIVE on both services and VERIFIED.**
  Reports any `(kind, market, segment)` collapsed to one value across >=4
  distinct GAMES, for every sport, from a wrapper over
  `_attach_projections_by_sport` (13 return sites, 4 call sites, none touched).
  It found a real defect unprompted on its first live board. `[measured 08-14]`
- **`#425` gap 1 — skill declaration — LIVE on both services and VERIFIED.**
  Every projection carries `model_skill`; `unmeasured` is now a first-class
  value. `nfl 20 measured`, **`mlb 1631` / `wnba 209` / `soccer 12`
  unmeasured**. NFL alone could not have proven this — it is the only producer
  with real skill numbers and exercises only the normalize branch. Counts
  surface in the `projections` coverage block, **not** in `counts`.
  `[measured 08-14]`
- **THE SIX MODELS ARE STILL UNMEASURED — `unmeasured` is honest, not
  sufficient.** `#428` carries the backtests and is **blocked on DATA, not
  effort**: soccer results 0 files, MLB `feed_live` 1 date, WNBA game-cards 4
  files. Do not start it by backtesting what is on disk. `[measured 08-14]`
- **`#429` — `mlb batter_hits_runs_rbis` projected a constant `0.0` across 188
  games. FIXED BOTH ENDS.** HRR is Hits+Runs+RBIs, a SUM of three primitives
  the sim models separately, so the mean is derivable exactly by linearity of
  expectation (holds despite the three being heavily correlated; means only,
  never probabilities).
  - Read-time derivation live on both services, **VERIFIED**: distinct
    **1 -> 85**, range 1.363..3.833 against a 1.5 line, and cross-checked
    against the sim's OWN probabilities — `corr 0.9267` with a control of
    `0.1156` for the near-constant market line. `[measured 08-14]`
  - Producer fixed at source (`_inc_sum(pid, "H+R+RBI", hrr)`, **both** copies
    of the accumulation) and live on refresh-worker. `_stat` reads only what
    `_inc_sum` accumulated and this composite was never summed, so the mean was
    `0 / sims`. **CONFIRMED IN PRODUCTION 11:56 CDT**: board `derived == 0`
    with 90 rows still valued, and the production
    `daily_summary_2026_08_14.json` (generated 11:39:16) carries `hrr_mean`
    NONZERO on **1008 of 1008** topn rows, 233 distinct, against a `pa_mean`
    control of 1008/1008. Supersedes the "NOT YET PROVEN" line that stood here.
    `[measured 08-14]`
  - **The board's range is IDENTICAL across the handover** (`1.363..3.833`
    before and after `derived` fell 90 -> 0). The value did not move when its
    source changed, because both paths compute `h + r + rbi`. No transition
    artifact. `[measured 08-14]`
  - **An unscoped full-slate MLB sim is a known OOM cause** —
    `live_refresh_loop.py:2761` says so in its own comment, which is why the
    loop batches through `--only-game-pks`. Do not trigger one to force an
    artifact rebuild; read the artifact through `/api/ops/artifacts/stream`
    instead. `[from-code 08-14]`
  - **Discriminator needing no artifact access:** `projected_derived_from` is
    stamped only when the read-time path had to reconstruct. On the board,
    `derived == 0` with values present means the producer is fixed;
    `derived == 88` means it is still writing `0.0`. `[code 08-14]`
- **`SYNDICATE_TRACEMALLOC_DIAG` was `1` on refresh-worker while the commit
  wiring it says "default OFF".** Set to **`0`** 2026-08-14 (key kept, not
  deleted — the gate is `value in {1,true,yes,on}`, so absent and `0` are
  equally off, and a visible key shows it was disabled deliberately). Restore
  with `1` + a deploy. Its owning session is archived. `[measured 08-14]`
- **The NFL season-projection autorun fires at 21:00Z = 16:00 CDT, NOT 21:00
  CDT.** Seven ledger lines carried a UTC timestamp reported as local — a
  five-hour error that would have armed a watcher after the event. Render logs
  are UTC; this ledger is CDT. `[measured 08-14]`
- **`#389`'s follow-up is CONFIRMED WORKING** on the criterion it set in
  advance: a positive `artifact_path=` on the mounted disk with no `/src/`
  (21:02:06Z), plus `SEASON_PROJECTION_ARTIFACT_MISSING` 30 before that write
  and 0 after. Writer and staleness guard finally resolve the same root.
  `[measured 08-13]`
- **A closed lane is an ACTIVE LOCK, not a stale note.** `lane-guard` returned
  exit 2 for two files for hours after their work shipped and was verified.
  Close a lane when the measurement lands. `[measured 08-14]`

- Max concurrent open lanes: **3** `[policy]`
- Repo tip: local `main` `c506eb2a`, **25 ahead / 8 behind `origin/main`**
  (`461c0df0`). The two have diverged and both ends move every few minutes —
  re-read, do not reuse these. `[from-git 08-13 15:1x]`
- **CORRECTION: a push from this checkout does NOT carry a `render.yaml`
  change, and the previous warning here that it fires `blueprint_sync` was
  wrong.** The three commits it named (`d16950b9`, `1e09fa9b`, `7c60d0f8`)
  are **patch-equivalent to commits already on `origin`** — another session
  re-landed them as `d16950b9`/`1e09fa9b`/`7c60d0f8`. `git cherry origin/main
  main` marks all three `-`, and `git diff origin/main..main -- render.yaml`
  is **empty** (web block 52 keys on both sides). Verified immediately before
  pushing `461c0df0`. `[measured 08-13 15:1x]`
- Still true, and the reason the warning existed: **`git push` from this
  checkout is not scoped to your own commits.** Read
  `git log origin/main..HEAD` before pushing. When it carries other lanes'
  work, cherry-pick onto `origin/main` in a throwaway worktree instead —
  used three times on 08-13 (`f6fec4f1`, `03073270`, `461c0df0`), twice
  because another session had uncommitted files the merge would have
  clobbered. `[from-git 08-13]`
- Deployed SHA: **re-read 2026-08-13 23:28Z, and they are NOT all equal.**
  `[measured 08-13 23:28Z]`
  - `syndicate` (web) — **`d4bb29b5`**, live since **23:03:32Z**. Supersedes
    `936e2b47`; web is no longer the stale service.
  - `refresh-worker` — **`d4bb29b5`**, live since **22:59:14Z**. Supersedes
    `03073270`.
  - `live-odds-worker` — **still `95effcfa`.** Its `d4bb29b5` deploy has been
    `build_in_progress` since 22:55:27Z — 33+ minutes against a normal 4. The
    old instance keeps serving (Render does not swap until a build succeeds)
    and is healthy. **It does NOT have the `#417` memory fix.** Low impact: the
    guard has never fired on that service (all refusal tokens zero over ~6
    days).
  - **A fired deploy is not a landed deploy.** All three were reported deployed
    tonight on the strength of the POST responses; one was false for 33+
    minutes. Check `status=live` AND the commit, never the 201.

- These go stale in minutes, not days. live-odds-worker moved
  `2caa8eac` → `95effcfa` inside one 40-minute session. Re-read before use.
  `[measured 08-13]`
- **The web service is the stale one.** It has not been redeployed since
  last night, so any web-path `.py` fix committed today is on `main` and is
  **not running**. Do not read a web-route symptom as evidence about
  today's code without checking `936e2b47` first. `[measured 08-13]`
- **Web is 47 commits behind — do not quote that number.** Only **14** touch
  production `.py`; the rest are ledger, docs and tests. Real delta: **7 files,
  785 insertions**, of which `intelligence.py`, `home.py`,
  `live_projection_join.py` and `flask_frontend.py` are web-path. See `#422`.
  `[measured 08-13 14:44]`
- **"On origin" is not "in production."** Web's LIVE service carries **73**
  env vars; `render.yaml` on origin declares **52**. The web env-block audit
  is pushed and **not reflected on the live service**. Read
  `/v1/services/<id>/env-vars` before recording any config change as shipped.
  `[measured 08-13 14:44]`
- **SELF-CORRECTION to the line above, same session.** It originally read
  "a future sync carries a queued, unannounced 21-key reduction". **That is
  wrong** and contradicted the measured sync semantics recorded further down
  this file: a sync **upserts declared keys and leaves live-only keys alone**
  (2026-08-08, refresh-worker went 92 → 93 while the blueprint declared 84;
  a full replace would have driven it to 84). Removing a declaration
  therefore **never removes the live value** — it only reclassifies the key
  as undeclared. So the 21-key gap is not queued work; it is 21 live-only
  keys that no sync will ever clear. **The web env-block audit cannot take
  effect on a live service at all** unless someone deletes those keys through
  the env API. Anyone wanting the audit to mean something in production has
  to do that deliberately. `[measured 08-13 15:1x — see
  scripts/audit_blueprint_drift.py header]`
- **Web does not run the loops that call `memory_headroom_snapshot`.** Live env:
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`,
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`,
  `MLB_ENABLE_LIVE_LENS_LOOP=false`. So the `#417` guard change is inert there —
  which matters because web is a **2GB** container with an OOM history and the
  new formula is more permissive. Re-raise that concern if any flag flips.
  `[measured 08-13 14:44]`
- **`live-odds-worker` does NOT carry the `#417` fix and DOES run the guard**
  (odds-refresh and soccer/WNBA live-lens gates). The unstable `active_file`
  arithmetic is still live on that service. Its own deploy, its own
  measurement. `[measured 08-13 14:44]`
- Because `autoDeploy = no`, the repo tip is an upper bound on every
  service and never a reading of any of them. Re-read per service; do not
  reuse the SHAs above once a deploy fires. `[policy]`

## Ledger SHA references

- **69 references across four ledger files were rewritten 08-13 from local
  SHAs to their `origin/main` equivalents.** They named commits that existed
  only in one clone, because this repo's standard push path (cherry-pick onto
  `origin/main` in a throwaway worktree) mints a new SHA. After the pass: 168
  refs resolve on origin, 0 fabricated. `[measured 08-13]`
- **Local-only SHAs, in two kinds — the distinction matters.** `[measured 08-13]`
  - *Will never land, do not wait for them:* `3042c5bc` (checkpoint-guard
    log-witness — SUPERSEDED by the adopted transcript-witness design, and
    replaying it would regress `checkpoint-guard.py`); `a3f9ed97` (a merge
    whose content is already upstream — no patch to cherry-pick).
  - *Pending, blocked on a conflict needing their author's judgment:*
    `a0c5e7af` (collides in `docs/ai_context/todo.md`); `bd227fa3` (collides
    in `.syndicate/lanes.md`, and the change is an `OPEN`→`CLOSED` status
    flip — union-resolving it would stack contradictory headers and invent a
    phantom lane).
  - *Landed, and rewritten throughout this ledger to their origin SHAs:*
    bf8833e9→`8a0d49d8`, 841228d9→`d4bb29b5` (old SHAs deliberately
    unbackticked so this entry does not inflate the check). **Pushing does not make the
    old SHA resolve** — the cherry-pick mints a new one, so the reference has
    to be rewritten too. That step was missed the first time and is the whole
    reason this list exists.
- Short session ids are indistinguishable from short SHAs. Every one in the
  ledger is prefixed `session` — keep it that way. `[policy]`

## WHY 60s BECOMES ~7,300s FOR MLB — two multipliers, both measured `[measured 08-14 17:0xZ]`

**Odds-refresh LAUNCHES on refresh-worker, derived from `since_launch_s` resets
(2.5h window) — the launch is what captures quotes, ~20s later:**

    07:03:00  soccer
    13:08:30  mlb            gap 365.5 min   <-- carries MLB
    14:40:00  nfl,wnba       gap  91.5 min
    15:10:00  mlb,soccer     gap  30.0 min   <-- carries MLB
    15:40:30  wnba           gap  30.5 min
    16:20:00  mlb            gap  39.5 min   <-- carries MLB
    16:50:30  nfl            gap  30.5 min

1. **`SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS=60` is the TICK interval,
   never the launch interval.** The loop ticks; it launches far less often.
2. **MULTIPLIER 1 — the pregame relaunch cooldown, 1800s, and it is GLOBAL.**
   Measured launch gaps 30.0 / 30.5 / 39.5 / 30.5 min == the 1800s cooldown,
   dead on. Confirmed independently from the live tick state
   (`/api/ops/live-refresh/state`): `skipped=True, phase=pregame,
   error="pregame refresh relaunch blocked by cooldown"`. `_pregame_relaunch_blocked`
   reads ONE marker, `reports/live_refresh_loop/last_pregame_refresh_launch.json`,
   keyed by date only — **not by sport and not by service.** So a launch for ANY
   sport starts the 1800s clock for EVERY sport. 60s -> 1800s is a 30x.
3. **MULTIPLIER 2 — sports rotate across launches.** MLB rides only some of
   them: 13:08:30, 15:10:00, 16:20:00. Roughly every 2-4 launches, so
   1800s x ~4 = ~7,200s. That is the observed 121.6-minute capture cadence, and
   the MLB launch times match the capture bursts to within ~20-40s
   (13:08:30/13:09:08, 15:10:00/15:10:44, 16:20:00/16:20:38).
- **THE LEVERAGE, and it is a design fact rather than a tuning value: because
  the cooldown is global rather than per-sport, every sport added to the
  rotation dilutes every other sport's cadence.** Eight sports on one 1800s
  global cooldown cannot give any of them a fast refresh. A per-sport cooldown
  would decouple them; that is the change worth considering, not lowering 1800.
- Also true and separately worth knowing: `reports/live_refresh_loop/**` is
  **deliberately keyvalue-backed**, so that marker is shared by web and BOTH
  workers, and both workers run `live_refresh_loop` (refresh-worker emits
  `ODDS_SWEEP_OUTCOME`/`MLB_LIVE_PROBE`; live-odds-worker emits
  `PREGAME_RELAUNCH_COOLDOWN_SKIPPED`). Whether they contend for that one
  marker is NOT established here and would multiply again if they do.
- Gates that are NOT responsible, checked and excluded: the off-hours gate
  (`#15`) never printed `ODDS_REFRESH_OFF_HOURS_SKIPPED` once in the 13:08-15:12
  gap, and its ceilings are 900s game-day / 3600s dead-period, neither of which
  is 7,300s. `MLB_LIVE_PROBE live=False` throughout, so it COULD have fired and
  did not.
- **Owner: `syndicate/features/shared/live_refresh_loop.py` is claimed by the
  OPEN `mlb-props-regen` lane.** Diagnosis only; nothing changed. Any cadence
  increase also spends OddsAPI calls against the 5M cap.

## ANSWERED — MLB quote capture never stopped. It runs every ~2 hours. `[measured 08-14 16:3xZ]`

**Read from the artifact itself via `/api/ops/artifacts/stream`, not from logs.
Every distinct `captured_at` in `mlb_source/tracking/book_quotes/2026-08-14.jsonl`:**

    22:27:40 (prev day)  1,888 rows
    07:03:23             4,206      gap 515.7 min  (overnight)
    09:05:01             3,895      gap 121.6
    11:06:35             5,337      gap 121.6
    13:09:08             7,230      gap 122.5
    15:10:44             5,324      gap 121.6
    16:20:38             3,728      gap  69.9

- **Seven captures in 18h on a metronomic ~121.6-minute beat.** That is a
  schedule, not a fault. Nothing is broken: capture works, the direct streamed
  publish works, web has the file (14,514,368 bytes and growing), and
  refresh-worker's streamed pull works (MLB is absent from the
  `STREAM_PULL_ABSENT` 404 list; only out-of-season sports 404).
- **THE DRIVER: `refresh-worker`'s `live_refresh_loop`, not live-odds-worker.**
  `[live_refresh_loop] ODDS_SWEEP_OUTCOME sport=mlb ... since_launch_s=6597`
  (14:58:44Z) — `since_launch_s` IS the cadence. **live-odds-worker emits none
  of these lines and carries `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP='false'`.**
  The service named for odds is not doing the odds work; the 4GiB
  memory-pressured worker is. Same shape as the `which service runs the code`
  rule — loop ownership is an env flag that moves with no diff.
- **The configured intervals are NOT what is happening.**
  `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS=60` and
  `MLB_LIVE_ODDSAPI_REFRESH_INTERVAL_SECONDS=60`, against a measured 7,296s.
  A `PREGAME_RELAUNCH_COOLDOWN_SKIPPED cooldown_s=1800` gate is visible in the
  same loop and does not explain 7,296s either. **What turns 60s into 7,296s is
  NOT established** — do not assume it is the cooldown.
- **This is the real cause of "candidates that are no longer bettable."** The
  board's MLB prices are up to ~2 hours old by construction. It also fully
  explains the `board-ui` lane's independent reading: they sampled at 15:00Z and
  got a freshest row of **13:09:05Z** — that is the 13:09:08 burst. Their
  "1h51m stale" IS this cadence. So was the frozen `considered=14195`.
- **Owner note: `syndicate/features/shared/live_refresh_loop.py` is claimed by
  the OPEN `mlb-props-regen` lane.** This diagnosis is handed over, not acted
  on. Any cadence change also spends OddsAPI calls against the 5M cap, so it is
  a product decision, not a tuning tweak.
- **METHOD, three strikes in one session and all the same shape.** "Capture
  stopped at 15:10:44" came from ONE read of a bursty quantity taken inside a
  gap; ten minutes later the newest row was 16:20:38. Before that, the 12MB
  ceiling; before that, "the fetch is not running" from a log token whose
  emitter I had never seen produce a non-zero. **Every one was a single sample
  of something that moves, promoted to a conclusion.** The fix that finally
  worked was to stop reading logs and read the artifact's full distribution.

## RETRACTED — the 12MB publish ceiling is NOT the cause `[falsified 08-14 16:2xZ]`

**Everything in the section below this one was written as a root cause and is
WRONG. Read this first.**

- **THE FILE CROSSES FINE.** Fetched web's own copy through
  `/api/ops/artifacts/stream`: `mlb_source/tracking/book_quotes/2026-08-14.jsonl`
  is **12,800,063 bytes on WEB** — byte-identical to the size live-odds-worker
  reports. Worker -> web transport is WORKING.
- **Why the ceiling never mattered, and it was written in the code the whole
  time.** `artifact_publisher.py:1007` says it plainly: the ceiling lives in
  `_publish_skip_reason`, which is **sweep-only**, while **the direct path
  streams and never consults it** — verified there in production against
  book_grid at 12,855,903 bytes. And `append_book_quotes` takes
  `publish: bool = True` **by default**, with no call site overriding it, so
  every append already publishes through the direct streamed path. The
  `SWEEP_SKIPPED_DETAIL too_large=` lines are a NOISY DUPLICATE of a publish
  that already happened — real, measured, and not load-bearing.
- **What is actually measured now:** the newest `captured_at` anywhere in the
  shard is **2026-08-14T15:10:44.825256+00:00**, and 860 of the last 861 rows
  carry that same instant — one capture burst, then nothing for ~70 minutes.
  So the open question is why MLB capture stopped producing rows after
  15:10:44Z. **That is NOT established, and it is not a transport fault.**
- **How this went wrong, because the pattern is the point.** A real anomaly
  (`too_large` on a 12.8MB file, 12 occurrences) was promoted to root cause
  because it was surprising and fit the symptom. The falsifying fact — that the
  direct path bypasses the ceiling — was in a comment in the same file, twenty
  lines from the constant, and was read AFTER the conclusion was written. The
  ledger already carries this exact rule: *"the more a datum overturns the
  expected answer, the more it must be re-read at full width before being
  written down."* Also `#402`'s comment records THREE prior sessions misreading
  `{'too_large': N}` the same way. This is the fourth.
- **Standing correction for whoever reads a `too_large` line next: it does NOT
  mean the artifact failed to publish.** Check the direct path first. The
  sweep's refusal and the artifact's actual delivery are independent.



### SUPERSEDED BY THE RETRACTION ABOVE — kept for the reasoning trail

- **`_PUBLISH_MAX_BYTES = 12 * 1024 * 1024` = 12,582,912 bytes**
  (`artifact_publisher.py:956`). The MLB shard
  `mlb_source/tracking/book_quotes/2026-08-14.jsonl` is **12,800,063 bytes** —
  **over by 217,151 bytes, 1.7%.** `_publish_skip_reason` returns
  `too_large:12800063` and the sweep drops it, every cycle:
  `SWEEP_SKIPPED_DETAIL too_large=[mlb_source/tracking/book_quotes/2026-08-14.jsonl(12800063)]`
  on live-odds-worker, 12 occurrences in 3h.
- **So MLB quote capture is FINE and the TRANSPORT is what stopped.** The file
  is being written on live-odds-worker's disk; it simply never crosses to
  refresh-worker, whose Layer 2 has been reading a frozen copy ever since.
- **Positive control is in the data, by contrast:** `nfl_source/tracking/
  book_quotes/2026-08-14.state.json` (1,268,613 bytes) publishes normally at
  16:08:46. Sports under the ceiling cross; MLB, over it, does not. That is the
  mechanism confirmed by a working case, not by inference from a zero.
- **It explains the timestamp the `board-ui` lane measured independently.**
  They found the freshest MLB row `updated_at` = **13:09:05Z** against a
  1.6-min-old artifact. That is when the shard crossed 12MB. Two lanes, two
  instruments, one cause.
- **THIS RECURS DAILY.** The shard is an append-only per-date JSONL that grows
  all day, so every day it crosses 12MB at some hour and MLB odds transport
  dies from that moment until midnight. Today: ~13:09Z. It is not a one-off.
- **RETRACTION of this session's earlier framing: "the quote capture stopped"
  was WRONG, and so was "`append_book_quotes` was not called."** Both came from
  zero `[odds_book_quotes]` lines on live-odds-worker. That zero has a SECOND
  cause I had not read: `_append_mlb_book_quotes`
  (`scripts/fetch_mlb_oddsapi_local.py:1550`) returns early on `if not rows:`
  **before** calling `append_book_quotes`, and that early return prints
  nothing. The unconditional print at `odds_book_quotes.py:422` proves only
  that `append_book_quotes` was not REACHED — not that capture stopped. The
  actual fault was one layer further out, in the publisher.
- **DO NOT just raise `_PUBLISH_MAX_BYTES`.** Its own comment forbids it
  without a measured reason: the bound is what stops the sweep shipping 51MB
  odds_history shards every cycle, and the cost is bandwidth, disk churn and
  receiver time — the same egress that produced a month of overage billing
  (`learnings.md`, 2026-08-12 FORBIDDEN). A gzipped/compacted transport
  (`odds_book_quotes` already writes `.jsonl.gz` for older shards — the soccer
  cache evictions show `2026-08-09.jsonl.gz`) or a delta/chunked publish is the
  shape that does not reopen that.
- Sibling, same window, NOT the same file, do not conflate: refresh-worker also
  drops `mlb_source/source_artifacts/data/daily/ladders/daily_ladders_2026_08_14.json`
  (15,689,798 bytes) on the same rule.

## THE BOARD HAS TWO INDEPENDENT STALENESS CAUSES, and fixing one is not enough

- **Cause 1 — refusal rate.** See the section below. 96.7% of board cycles were
  refused pre-reboot. `[measured 08-14 14:39Z]`
- **Cause 2 — THE QUOTE INPUT IS NOT MOVING, and this one is live RIGHT NOW,
  after the reboot, on a worker that is rebuilding the board fine.**
  `[measured 08-14 15:1xZ]`
  - Post-reboot the shortlist rebuilds **12x in 1.5h** — healthy cadence — and
    `LAYER2_SHORTLIST` reports **`considered=14195` on every single one**
    (14:44:31, 14:46:53, 14:50:57, 15:04:29, 15:12:36; and 14167 on the two
    before that). The board is rebuilding off an input that does not change.
  - **live-odds-worker emitted ZERO `[odds_book_quotes]` lines in a 1h window**
    (positive control: 715 `PUBLISH_OK`/`LAYER2` lines in the same fetch, so
    the probe is live). `odds_book_quotes.py:422` prints **unconditionally** —
    every exit from the append function goes through it or the `FAILED` line —
    so zero means **that function was not called on that service at all.**
    It is the writer of the `book_quotes` shards `layer2_shortlist.py` reads
    via `read_book_quotes`.
  - Independently corroborated by the `board-ui-freshness-slip-books` lane from
    the other end: `/api/board/layer1?sport=mlb` at 15:00Z carried artifact
    `generated_at` 14:58:49Z (1.6 min) against a freshest row `updated_at` of
    **13:09:05Z — 1h51m**, with min `seen_age_seconds` 6576.8s agreeing. Two
    lanes, two instruments, two ends of the pipeline, same conclusion.
  - **METHOD WARNING on this measurement.** The first pass grepped
    `BOOK_QUOTES`/`BOOK_QUOTES_APPENDED`/`QUOTE_CAPTURE` and got 0 on both
    services. **Those tokens do not exist** — the emitter prints a bare JSON
    blob under `[odds_book_quotes]`. That zero was a broken probe and was
    within one step of being reported as "capture is dead". Run the positive
    control; verify the token against the emitter, not against memory.
  - Also seen, unrelated to the above but worth knowing: refresh-worker's
    `_BOOK_QUOTES_CACHE` is evicting **today's** WNBA shard
    (`wnba_source/tracking/book_quotes/2026-08-14.jsonl`) at its 500MB budget.
    Live data being evicted to stay under budget.
- **Consequence for any board-freshness work: rebuilding more often cannot fix
  cause 2.** A shortlist rebuilt every 5 minutes off a 2-hour-old quote shard
  is a board that LOOKS fresh and is not — strictly worse than one that is
  visibly stale, because nothing on it says so.

## `#387` CUTOVER IS WRITTEN AND TESTED — NOT DEPLOYED `[08-14 20:2xZ]`

- Branch **`memory/overview-sum-to-max`** now carries three commits, all
  origin SHAs (cherry-picks mint new ones — cite these):
  `c39569ef` pool retention -> `946d77e3` streaming mechanism ->
  **`086702ae` the cutover**. **None is on `main`. None is deployed.**
- `_build_candidate_pool` consumes each sport and releases it before the next
  hydrates. `preferences` moved above the stream. The rare thin/empty-pool
  fallbacks re-hydrate on demand (`collect_all_recommendations` rebuilds when
  handed `overview=None`), so they still work without every cycle carrying
  eight sports.
- **The list fallback is load-bearing.** A caller that ignores `consumer=` and
  returns the list would stream ZERO sports and build an EMPTY POOL — a total
  board outage presenting as "no candidates today". ~30 tests patch that
  function with a plain `return_value`. If nothing streamed but a list came
  back it is consumed, and `OVERVIEW_STREAM_FELL_BACK_TO_LIST` prints.
- **THE MEASUREMENT THAT WOULD MAKE IT OFFICIAL**, with a baseline that now
  exists because of tonight's kill: one hydrated pass, `OVERVIEW_SPORT_BEGIN
  mlb` -> peak. Before: 522MB -> dead at 4GiB in 25s. After: peak should track
  ONE sport and never approach it. Needs a deploy window with no intervening
  deploy — refresh-worker took one every ~20 min all evening.

## CORRECTION — `tests/test_intelligence_state.py` is NOT "GREEN 224" any more `[measured 08-14 20:2xZ]`

- It is **223 passed / 1 failed / 10 subtests**. The failure,
  `test_collect_candidates_with_fallback_merge_falls_back_on_empty_pool`,
  asserts `collect_all_recommendations(..., force_refresh=True, ...)` on a call
  site from which `#387` **removed that dead argument earlier today**.
- **Verified pre-existing** by stashing the cutover diff and re-running: it
  fails identically without it. So the standing rule "a failure in this file is
  now yours" is currently WRONG for this one test — it belongs to the
  `force_refresh` removal, and the test needs updating to match.

## OOM 2026-08-14 20:03:11Z — THE OVERVIEW TRANSIENT KILLED A WORKER THAT WAS AT 522MB `[measured 08-14 20:1xZ]`

**The single most direct evidence in this ledger that peak, not floor, is the
acute cause.**

    20:02:26  OVERVIEW_SPORT_BEGIN mlb  force_refresh=True skip_game_hydration=False
    20:02:26  anon  343MB      <- worker booted 19:49, 13 min earlier
    20:02:37  anon  393MB
    20:02:46  anon  522MB
    20:02:48  OVERVIEW_SPORT_BEGIN nba, wnba
    20:02:50  OVERVIEW_SPORT_BEGIN nfl
    20:02:55  OVERVIEW_SPORT_BEGIN ncaaf, ncaab, nhl
    20:02:57  OVERVIEW_SPORT_BEGIN soccer     <- all eight held at once
    20:03:11  server_failed  oomKilled memoryLimit 4Gi  instance -xnxxv

- **A 522MB worker died in 25 seconds inside ONE hydrated overview pass.** The
  ~1400-2000MB floor played no part — there had not been time to accumulate
  one. Peak = SUM across eight sports is sufficient on its own to cross 4GiB.
- Earlier peak sample the same cycle: **3719.9MB at 20:01:18**, stage
  `board_contract_games_normalized`.
- **This is exactly what the `#387` SUM -> MAX cutover addresses**, and it is
  the strongest argument yet for wiring it. Anything that only lowers the floor
  would NOT have prevented this kill.
- **Attribution, stated carefully:** `530fc5d8` (Layer 2 fast path) was live and
  had been for 4h20m including a measured 3h window with ZERO OOM events; it
  runs `skip_game_hydration=True` and never triggers a hydrated pass, so it is
  not on this path. `29ed6de1` deployed 14 min earlier (another session, +77
  lines of Layer 2 scoring) does not drive `board_contract` either. **One kill
  on one boot exonerates nothing** — but the 522MB floor means there was
  nothing for added periodic work to have accumulated.
- Recovered: 2 `BOOTED` lines, `anon` back to 1629MB. **One kill, not a loop.**
- OOMs predate today's changes (4 kills 03:20-04:04Z), so this is not a new
  regression — it is the standing defect firing again.

## IS THERE AN OFFICIAL MEMORY FIX? NO. `[measured 08-14 20:1xZ]`

Stated plainly so nobody inherits a false sense of closure.

- **`530fc5d8` IS official** — on origin, IN the live refresh-worker commit,
  verified on a 3h clean window, all five criteria met. **It fixes board
  FRESHNESS, not memory.**
- **The two memory commits are NOT official and were LOCAL-ONLY** until now:
  neither `100c9cb5` nor `0041a902` was on `origin/main` or in any deployed
  commit. Now pushed as branch **`memory/overview-sum-to-max`**
  (`c39569ef` = the pool retention, `946d77e3` = the streaming mechanism;
  cherry-picks mint new SHAs, so cite THESE, not the local ones).
- **`0041a902`/`946d77e3` is a MECHANISM, not a fix.**
  `_build_candidate_pool` still calls the list form, so production memory is
  byte-for-byte unchanged.
- **What "official" requires here, so the bar is not moved later:**
  1. wire `_build_candidate_pool` to the consumer (spec + answered decision
     gate in `handoff_overview_hydration.md`);
  2. tests green, including the existing equivalence and release pins;
  3. on origin AND in the live commit (check by SHA, not by "I pushed it");
  4. **the measurement that makes it a fix: the `board_contract` peak stops
     scaling with sport count.** Baseline to beat is the recorded excursion
     `post_pull 2223MB -> 4096.0MB -> 2091MB`. Peak per hydrated pass, before
     and after, on the same slate size.
- Until (4) exists, this is "cause identified, fix built, effect unmeasured" —
  which is exactly the state `#417` was in when it was briefly believed closed.

## GOAL #1 HAS TWO QUANTITIES. Do not let the unnamed one hide the named one.

- **PEAK (acute, IDENTIFIED, fix built and unwired).** OOM kills happen at the
  4GiB ceiling, and the ceiling is crossed by a TRANSIENT, not by the baseline:
  `post_pull 2223MB -> soccer board_contract 4096.0MB -> back to 2091MB`, a
  ~1873MB excursion. The cause is named and measured: the overview holds all
  eight sports' hydrated rows at once, so peak is the SUM (MLB alone +2.9GB).
  `0041a902` is the mechanism that turns it into MAX. **NOT WIRED.**
- **FLOOR (chronic, UNNAMED).** The persistent ~1400-2000MB `anon` base. Four
  candidates eliminated this session; leading hypothesis is large allocations
  neither gc-tracked nor in glibc arenas. Reducing this buys headroom; it is
  NOT what crosses the ceiling.
- **These want different fixes and should not be traded off against each
  other.** An earlier checkpoint in this file framed "name the floor" as the
  whole of goal #1, which under-states a peak cause that is already identified
  with a tested fix in hand. Corrected here so the next session does not
  inherit the wrong priority: **wire the cutover first — it addresses the
  quantity that actually kills the process.**

## `#387` SUM -> MAX: mechanism SHIPPED, cutover NOT DONE `[measured 08-14 20:0xZ]`

- **`build_intelligence_overview(consumer=...)` exists and is tested**
  (`0041a902`, committed, NOT deployed, **NOT WIRED**). Each sport's row is
  emitted and dropped before the next hydrates; the list path runs through the
  same `_emit`, so the modes cannot drift. `sports_done` is counted rather than
  `len(overview)` (streaming leaves that empty, and a guard fed a constant is
  not a guard), and `sport_row = None` after emit is mutation-pinned.
- **`_build_candidate_pool` STILL CALLS THE LIST FORM.** Nothing has changed in
  production. The saving is unquantified in MB.
- **The cutover's decision gate is ANSWERED:** the only whole-overview consumer
  left on the board path is the thin-pool merge, and
  `collect_all_recommendations:thin_pool_merge` shows **0 enters in 6h** against
  **39** live `collect_candidates` spans in the same window (positive control).
  It fires only at 1-19 candidates — **rare, not dead**. Plan: stream by
  default and RE-HYDRATE for that path, rather than gate it off.
- `pool["overview"]` no longer holds the hydrated rows (`100c9cb5`, committed,
  not deployed) — that was the last whole-list holder and it is what made the
  cutover possible at all. Its `by_sport` output is byte-identical to the
  hydrated path.
- **Deploy state: `530fc5d8` is live and verified. `100c9cb5` and `0041a902`
  ride the next refresh-worker deploy and have never run in production.**

## `#387` LAYER 2 FIX — VERIFIED ON A FULL 3h CLEAN WINDOW `[measured 08-14 19:24Z]`

- 16:16:56-19:24Z, 187.3 min, commit `294f9ca9` unchanged (verified by SHA, not
  timestamp): **37 refreshes = 11.9/hour** vs 1.7 baseline, **23 via the fast
  path**, longest gap **11.8 min** vs **104.7**, **96** `MEMORY_GUARD_ABORT`
  (guard still actively refusing, so not a boot-confounded quiet period),
  `LAYER2_GUARD_SKIP` **0** across all 96, zero failures, zero OOM.
  **All five criteria met; lane CLOSED-VERIFIED.**
- The span exceeds the 180-min baseline, which is what makes the max-gap
  comparison sound — at 103.9 min it was not.
- Residual confound, stated: abort rate 30.8/h vs 48.7/h baseline, so the 7x
  rate improvement is not wholly attributable. The 23 fast-path refreshes are.

## GOAL #1 — A NAMED, UNFIXED INSTANCE OF `#253` `[measured 08-14 18:5xZ]`

- **`#253`'s worker cache bound was applied to MLB ONLY.** MLB has
  `_MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES_WORKER = 2` and a `_cards_cache_limit()`
  that switches on `_render_web_dyno()`. **NBA and WNBA have no worker variant
  at all** — `_NBA_CARDS_CONTEXT_CACHE_MAX_ENTRIES = 32`,
  `_WNBA_CARDS_CONTEXT_CACHE_MAX_ENTRIES = 32`, assigned unconditionally.
  `_render_web_dyno()` exists in both files but gates OTHER decisions
  (date fallbacks), not the cache bound. Same for
  `_SOCCER_MARKET_BOARD_CACHE_MAX_ENTRIES = 32` and
  `_JSONL_ROWS_CACHE_MAX_ENTRIES = 32`.
- **And the 32-entry limit is never reached, so nothing is ever evicted.**
  Measured 5h: the HYDRATED overview ran **9 times** (72 `OVERVIEW_SPORT_BEGIN
  skip_game_hydration=False` / 8 sports = 9 each) against 736 cheap
  fingerprint passes. Nine builds against a 32-entry cache means **every
  context built is retained for the life of the process.** MLB's limit of 2 caps
  it; the others do not.
- **MAGNITUDE IS NOT ESTABLISHED, and this is the honest limit of it.** NBA,
  NCAAB and NHL are out of season so their contexts are near-empty; WNBA and
  soccer are live but small (WNBA had 1 game in an earlier sample). This is a
  named retention with a known mechanism, NOT a demonstrated large one. Do not
  quote it as MB until somebody sizes a context.
- **The instrument gap that blocks sizing it, stated so the next reader does not
  mistake silence for absence:** `_log_cards_context_memory` and the
  `[mlb_cards]` prints exist ONLY in `syndicate/features/mlb/cards.py`. NBA and
  WNBA cards emit nothing, so their cache behaviour is invisible in production
  logs. Zero `[wnba_cards]` lines is a fact about the emitter, not the cache.
- **The overview's own shape is unchanged and still the big one.** 9 hydrated
  passes in 5h, each hydrating ALL EIGHT sports including 4 out of season, with
  peak = SUM not MAX (`handoff_overview_hydration.md`). That remains the
  architectural fix and it is still unstarted.

## GOAL #1 (the memory plateau) — what is now ELIMINATED `[measured 08-14 18:3xZ]`

Nothing new is convicted. Four candidates are struck off, which narrows it.

- **The MLB cards-context cache EARNS its retention — 22.9% hit rate**
  (91 hits / 398 begins / 307 full builds over 5h; 91+307=398 exactly).
  `handoff_overview_hydration.md`'s "mathematically zero hit rate, safe to zero,
  ~60MB free" is **RETRACTED IN THAT FILE**. It carried `#253`'s correct finding
  about `_MLB_TODAY_CACHE` across to a different cache with a different key.
  **Do not zero it.**
- **glibc arenas are not holding it**: `MALLOC_ARENA` reports `in_use_mb 83.4`,
  `free_held_mb 298.3`, `system_current_mb 381.7`, `mmapped_mb 0.6` against
  `anon` ~1490MB. Confirms `#423` from a second instrument.
- **It is not in GC-tracked Python objects**: `HEAP_CENSUS` at
  `container_mb 2150.996` counts **325,653** gc-tracked objects total
  (dict 155,042 / list 72,799 / function 30,812). Millions would be needed to
  explain the plateau. This also sits badly with the `nframe=1` tracemalloc
  reading of "7.17M live objects from `json.loads`" — those two instruments
  disagree and the disagreement is itself unexplained.
- **The board build is not the retainer** (established earlier: it ran 5 times
  in 3h while `anon` stayed high).
- **What remains, and it is a hypothesis not a finding:** large allocations that
  are neither gc-tracked nor in glibc's arenas — NumPy/Monte Carlo buffers being
  the obvious candidate. `tracemalloc` is currently OFF
  (`SYNDICATE_TRACEMALLOC_DIAG='0'`, verified on the live service) and the
  `anon-allocation-site` lane's own next step (`nframe=3`) needs a deploy of
  instruments that were rolled back after four OOM kills followed them.
- **Cheap unexploited signal for whoever continues**: 307 full cards-context
  builds in 5h is one per ~59s, each with a measured ±500-650MB sawtooth. The
  churn is real even though the cache is not the leak.

## `#387` FIX IS DEPLOYED AND ITS CODE PATH IS PROVEN TO RUN `[measured 08-14 17:4xZ]`

- **`LAYER2_FAST_REFRESH date=` fired 6 times** since 15:42:29Z. That line is
  emitted on the SUCCESS path by design, so it is a liveness proof, not an
  inference. The Layer 2 fast path executes in production.
- **126-min window: 24 board refreshes, longest gap 19.6 min.** Baseline before
  the change: 5 refreshes / 180 min, longest gap **104.7 min**.
- **`MEMORY_GUARD_ABORT` = 28 in that same window** — the Layer 1 guard is
  refusing again (`anon` back at plateau) and the board refreshed anyway. That
  is the exact condition that used to produce the 104.7-min freeze.
- **`LAYER2_GUARD_SKIP` = 0** — the declared falsifier did not fire, so the
  600MB Layer 2 floor is not too tight. 0 tracebacks.
- **CONFOUND, stated: two further deploys landed inside the window**
  (`214f5151` 15:59:55Z, `294f9ca9` 16:16:56Z, neither mine). The 6
  `LAYER2_FAST_REFRESH` lines are direct evidence of this change; the aggregate
  24/19.6 figures are NOT cleanly attributable to it alone.
- Live refresh-worker commit is **`294f9ca9`**, and **`530fc5d8` IS an ancestor
  of it** (`git merge-base --is-ancestor`, checked this session) — so the fix is
  still running. `9ec20a06` (per-sport cooldown) is NOT in live, correctly.
- **Deployed SHAs moved THREE times in 35 minutes today** (15:42 / 15:59 /
  16:16). Re-read inside the step that uses one; never carry one across turns.

## Board freshness is a REFUSAL RATE, not a build duration (layer2-board-freshness)

- **96.7% of board cycles are refused before any work.** Measured
  11:39-14:39Z on refresh-worker (live commit `2e4e2544`, re-read in the same
  run): **146 `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` against 5
  completed builds.** Every other abort stage was 0.
  `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb` fired 3 times.
  `[measured 08-14 14:39Z]`
- **Longest stretch with NO Layer 2 rebuild: 104.7 minutes** (12:44:20 ->
  14:29:00Z). Gaps n=4: 2.1 / p50 7.8 / max 104.7 min. That gap IS the stale
  board — rows for games that had already started. `[measured 08-14]`
- **The guard doing the refusing protects a stage Layer 2 never runs.** It is
  `_MIN_SAFE_MEMORY_HEADROOM_BYTES` (1900MB), sized in its own comment for
  `build_intelligence_overview`. Production's own proof they are independent:
  on 3 of the 5 completed builds `CANDIDATE_POOL_READY count=0` while
  `LAYER2_SHORTLIST` returned `rows=256 considered=13665` on the SAME cycle.
  `[measured 08-14]`
- **The Layer 2 stage costs 14-27s and +27..181MB** (4 builds, 14:43-14:51Z,
  sports mlb/nfl/soccer/wnba; the 14:48 sample is 2 sports). Coverage stated
  because it is 4 builds in one 8-minute window on one boot — it does NOT
  cover a 7-sport October slate. `[measured 08-14]`
- Legacy `candidate_collection_with_fallback`: n=5, p50 0.00s, max 260.28s,
  **sum 498.7s / 3h**. The 0.00s builds are the ones with an empty overview.
  `[measured 08-14]`

## refresh-worker memory today: a PLATEAU, not a ratchet `[measured 08-14 14:15Z]`

- Over 11:45-14:15Z (2.5h, boot-segmented, 3,427 CONTAINER_MEMORY samples)
  `anon` went **2620.1 -> 2439.6MB**. It did not ratchet. It oscillates
  ~1400-2800MB. **The 08-13 growth regime is not what was running today** —
  do not carry 08-13's rate forward without re-measuring.
- The defect is the LEVEL: p50 ~2200-2800MB against the 2196MB the guard needs
  (4096 - 1900). The guard is therefore refusing roughly whenever it looks,
  which is the 96.7% above.
- Split at peak: container 3830.1MB / 93.5%, `accounted_rss` 2468.5MB over 6
  processes, **main worker pid 39 = 2236.98MB**, reclaimable file cache
  1428.0MB, unreclaimable 2402.7 ~= anon 2393.5.
- Loudest repeating allocator: MLB **`board_contract`** (1,022
  begin->games_normalized transitions in 2.5h, ~1 per 8.8s) and
  **`cards_context`** (127, ~1 per 71s), sawtoothing about +637MB against
  -555MB per cycle. A sawtooth is not by itself a retainer — **what holds the
  ~1400-2000MB FLOOR is still unnamed.**
- **The board build is NOT the retainer.** It ran 5 times in 3 hours while
  `anon` stayed high throughout.
- A deploy at **14:22:32Z (`2e4e2544`, trigger=api)** restarted the worker;
  `anon` fell to 244MB and builds resumed at ~2min cadence. Reboot, not fix.

## refresh-worker memory — `#417` CLOSED, `#423` OPEN

- **`#417`'s guard fix is VERIFIED and STAYS.** The live abort line carries
  `'basis': 'unreclaimable'` (proving the new path executes) with
  `active_file`/`inactive_file` credited as reclaimable. Do not revert it.
  `[measured 08-13 22:48Z]`
- **RESOLVED 2026-08-14 00:06Z: THE LEAK IS REAL.** The floor series (the
  trough of `anon`, not point samples) rose **1670 -> 2589MB in 45 min**, and
  the latest TROUGH now sits above the first window's PEAK (1877.9) — a
  comparison that distinguishes a ratchet from an oscillation, and one that
  point-sampling cannot make. Rate ~+1200 MB/hour. The board re-froze at
  T+1.13h after the 22:59 restart. **`#417`'s guard is behaving correctly
  throughout — it refuses because `anon` genuinely exceeds the floor. The
  defect is upstream of the guard.** `[measured 08-14 00:06Z]`
- The **300MB/hour figure** stays withdrawn as a NUMBER (it came from two point
  samples and is ~4x off); the PHENOMENON it described is confirmed. The
  supersession below is kept so the reasoning is auditable.
- **SUPERSEDED 23:33Z (kept for the record): "the ~300MB/hour anon leak is NOT
  established."** It came
  from two point samples (`anon` 1163 → 2603 over 18:05–22:48Z), and `anon` is
  now measured to swing **~1650 ↔ 3200MB within minutes**. Two points cannot
  distinguish a ratchet from two phases of that swing — the same error retracted
  the same evening for the v2 sampler. **Do not cite 300MB/hour.**
  `[retracted 08-13 23:33Z]`
- **What IS measured: `anon` oscillates hugely, and the guard samples one point
  of it.** Floor series post-restart: 980.6 → ~1650 in 20 min (warm-up) → 1670 /
  1652 / 1763 over the next 10 min, roughly flat. p50 1715 → 2176 → 2518, max to
  **3203.7**. The guard needs `anon < 2196`, so a cycle builds or aborts
  depending on where in the swing it reads. `[measured 08-13 23:19–23:29Z]`
- **Regime is INTERMITTENT, not frozen.** Post-restart: 8 `LAYER2_SHORTLIST`
  builds, 4 aborts. The 20:39–22:59 event was different in kind — 300
  consecutive aborts, zero builds. `[measured 08-13 23:33Z]`
- **Prediction falsified:** re-freeze was predicted at ~4–5h; aborts resumed at
  **34 minutes**. The linear-growth model is wrong. `[measured 08-13 23:33Z]`
- Open question, and the likely real defect: **`#417` fixed WHICH quantity the
  guard reads; it did not make ONE READING of that quantity sufficient.** A
  point-sampled guard against a 1550MB-swinging value gives an unstable
  verdict. Trough/median sampling or hysteresis is the shape of the fix — not
  another allocator hunt. `[from-measurement 08-13]`
- **Restarts clear it and prove nothing.** 14:56, 18:05, 22:59 — each dropped
  `anon` (2603 → 980.6MB at 22:59) and each destroyed the evidence window.
  **A recovered board is not a fixed system.** `[measured 08-13]`
- **Both allocator flushes are ALREADY deployed and already measured (`#285`).**
  `malloc_trim` returned 1109.6MB across 24 calls/46min (gc: −104.3MB);
  `configure_malloc_arenas(2)` runs at `run_refresh_worker.py:3156` before
  threads spawn. The trim **halved** the ratchet (~24 → ~11 MB/min) and did not
  stop it; at guard time it returns 0.0–2.9MB. **So the residual is NOT
  free-but-unreturned memory** — it is live objects or fragmentation.
  Do not propose "add a flush". `[measured 08-10, re-read 08-13]`
- **`_BOOK_QUOTES_RSS_PER_FILE_BYTE = 6.3` is CORRECT — EXONERATED.** Measured
  5.89–6.33× on four real shards, conservative at scale. The 500MB budget is
  not blind. `[measured 08-13 23:1xZ]`

## `#414` board-build cost — cause found, fix shipped, effect UNVERIFIED

- **The MLB board-build cost was the quote-join identity scan.** Eight
  production samples fit `19.86s per million rows walked` (R²=0.918) with
  ~83k rows walked per call, constant. `tail_s` 21–54s, `rows_s` 0.00 — the
  row loop is EXONERATED. `[measured 08-13]`
- Index shipped in `d4bb29b5`: **85.43 → 0.66 ms/call (130×)** locally at
  production shard size, equivalence proven over 30+ query shapes.
  **Production effect UNVERIFIED.** `[measured local 08-13]`
- **If the index works, `SLOW_SEGMENT_PROFILE` goes SILENT** (gated at 5s).
  Read its absence only against `LAYER2_SHORTLIST` still recurring and the
  pre-fix baseline of 8 lines in ~4 minutes. `[policy]`

## `render.yaml` env hygiene (`#96` family)

- The web `envVars:` list is anchored `&shared_render_env_vars` but the alias
  **is never referenced anywhere in the file** — nothing was ever shared, so
  worker-only keys accumulated on web for months. `[from-code 08-13]`
- Web block audited and cut **62 → 52 entries** (`606a2f28`, `d16950b9`,
  `1e09fa9b`, `7c60d0f8`). Every removed key was already declared on both
  workers and is unchanged there. `[from-code 08-13]`
- **Three duplicate declarations existed, one per service** (web and
  live-odds-worker: `SYNDICATE_WNBA_SOURCE_APP_FALLBACK`; refresh-worker:
  `SYNDICATE_BOOTSTRAP_ON_START`). All same-value, all deduped. Zero
  duplicates on any service now. `[measured 08-13]`
- A `blueprint_sync` **upserts declared keys and leaves live-only keys
  alone** — it does NOT replace the whole env block. So removing a
  declaration does not remove the live value; it reclassifies it as
  undeclared. This is narrower than CLAUDE.md's warning implies.
  `[measured — see scripts/audit_blueprint_drift.py header]`
- Blueprint drift: **0 values a sync would revert**, all three services.
  Snapshot only — one env-API change makes it non-zero. `[measured 08-13 11:52]`

## Both workers publish over the internal hostname

- `SYNDICATE_WEB_PUBLISH_URL='http://syndicate-an21:10000'` on refresh-worker
  and live-odds-worker; **not set on web**, correctly. Confirmed in config and
  in the running process — 20 `PUBLISH_OK` lines on live-odds-worker at
  11:17:11 CDT all carry the internal URL. This extends the closed cutover
  lane, which had evidence from refresh-worker only. `[measured 08-13]`

## Keyvalue store (`#324`)

- Instance is **256MB, `allkeys-lru`**, shared by web + both workers. Cannot be
  upgraded. `[measured 08-10]`
- `reports/migration_runs/**` no longer reaches the store: `_keyvalue_backed()`
  in `refresh_state_store.py` excludes it from all seven path-scoped IO
  functions. `refresh_status/` and `live_refresh_loop/` are DELIBERATELY still
  stored — `refresh_status/latest/` is read cross-service and both together were
  only 4.4MB. `[code 08-10]`
- Usage went **246MB / 96.1% → 39.87MB / 15.9%**, with `evicted_keys` frozen at
  38,865 across a 36-minute window. **Re-measure before relying on this: it is
  2–3 days old.** `[measured 08-10]`
- `/api/ops/keyvalue/usage` reports **allocator bytes** (`MEMORY USAGE`,
  jemalloc size classes), not logical length. Correct unit for "is the instance
  full"; deltas are block-quantised, so do not quote them to more precision than
  ~4KB. `[measured 08-10]`

## Board transport (`#317`, `#322`)

- Board snapshot and `query_state_cache` are **compacted (aliases) then
  zlib+base64 compressed** before the keyvalue write. 31.4MB → 812KB, 17.7× on
  real candidate data. Top-level scalars are left uncompressed on purpose so
  `_read_state_payload`'s freshness comparison still works. `[measured 08-10]`
- **Any reader of these artifacts must call `expand_persisted_state` first.** A
  raw read returns an envelope that still passes `isinstance(dict)`, so it
  degrades silently rather than raising. This has already bitten three ops
  diagnostics (`#320`) and one more (`#338`). `[code 08-11]`

## Services

- `syndicate` — web service. ~333 GB outbound in Aug, almost entirely HTTP
  responses; only 207 MB service-initiated. `[measured 08-12]`
- `live-odds-worker` — background worker, 1 CPU / 2 GB, 50 GB persistent
  disk. Publishes a single date, ~30–60 publishes/min. `[measured 08-12]`
- `refresh-worker` — background worker. Multi-date sweep, ~30–60
  publishes/min. `[measured 08-12]`
- **Soccer sims are ENABLED and running.** `SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN='true'`
  live; all three sim fixes are ancestors of the deployed commit; a 20m13s
  `build_soccer_artifacts` process was observed. Any belief that they are off is
  wrong. `[measured 08-10]`
- **One soccer sim job = one league-date** (`#282`, deployed). Verified by 8
  `SOCCER_UNIT_LAUNCHED` lines completing a full 4-unit rotation, `due`
  counting 4→3→2→1, spacing = `interval // unit_count`. `[measured 08-10]`
- **refresh-worker's active-job cap now actually fires** (`#311`, deployed) —
  `JOB_CAP_THROTTLED active=1 max=1 source=process_and_manifest`, the first time
  in this system's history. `SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS` is unset
  on both workers, so the cap is **1**; raising it weakens the bound
  proportionally and nothing at the point of change says so. `[measured 08-10]`

## Platform constraints

- Hosted on Render. `[fact]`
- Artifacts stored on **Render persistent disks**, not S3/GCS. This forces
  single-instance services and stop-then-start deploys with downtime.
  `[from-code 08-12]`
- Render April 2026 pricing: included bandwidth cut, $0.15/GB overage.
  `[fact]`
- Included pipeline/build minutes exceeded in Aug: 1,549 of 1,000.
  `[measured 08-12]`

## Session harness — what the hooks actually enforce

- **`lane-guard.py` (PreToolUse) enforces.** Blocks `Edit` and `Write` against
  a file claimed by another OPEN lane (exit 2, edit does not land); allows the
  same file when `.syndicate/.current-lane` names the claiming lane.
  `[measured 08-13, 4 probes through the harness]`
- **With `.current-lane` empty or missing it blocks your OWN lane's files**,
  reporting `Current lane: 'none'`. Correct by design, confusing symptom — a
  session that hand-edits `lanes.md` instead of running `/lane` locks itself
  out. **The marker did not exist at all before 08-13**, so `none` was the
  baseline, and it has already bitten once: session `ab30bcc8` was refused
  `tests/test_intelligence_state.py`, claimed by the very lane it was working
  (`intelligence-state-red-baseline`). `/lane close` empties the marker, which
  restores that state — only `/lane open` clears it. `[measured 08-13]`
- **`Bash` bypasses it entirely** — the matcher is `Edit|Write|MultiEdit|
  NotebookEdit`. The guard bounds the file tools, not the session.
  `[measured 08-13]`
- **`session-start.sh` delivers 1,243 B**, `exitCode=0`, no truncation marker,
  measured from the arriving `attachment` record (session `2e6476cd`, line 3).
  Inside the ~2KB cap that left v1 ~5% functional. `[measured 08-13]`
- **`checkpoint-guard.py` (Stop) can now pass — fixed in `5cdf45b6`.**
  Two independent causes, both measured. (1) `.syndicate/.last-checkpoint` did
  not exist until 08-13, so the pass branch was unreachable: **28 Stop
  deliveries, 5 sessions, exit 1 on all 28, zero exit 0** — while checkpoints
  were demonstrably being written. (2) After the marker appeared it STILL
  returned exit 1, because the denominator was the whole worktree: marker
  13:28:57 vs newest dirty file 13:30:17. It now counts only files this
  session edited, read from `transcript_path` on the hook payload. On the live
  repo: **exit 0 with 62 dirty files present**; before commit it named exactly
  the 2 that were this session's. Replaces `checkpoint-guard.sh`, deleted.
  `[measured 08-13]`
- **Its witness is now session-scoped too (uncommitted, working tree).** The
  marker's mtime is no longer read at all: `.last-checkpoint` is repo-global,
  so session A's checkpoint silenced session B's warning — a false PASS, the
  direction that loses work. The baseline is this session's own `/checkpoint`
  invocation or ledger write, taken from transcript timestamps. `.syndicate/**`
  no longer counts as work. 5/5 cases against the live file, including the
  falsification: no own signal + fresh foreign marker still warns.
  `[measured 08-13]`
- **RETRACTED — `lane-guard` DOES guard `memory-guard-reclaimable`.** A line
  here claimed its four files were unprotected because the status reads
  "DEPLOYED, MEASUREMENT OPEN". That was false and never held: `559d353d`
  ("match OPEN as a WORD in the status field, in both guards") had already
  replaced the one-word status match, and its comment names this very lane.
  The claim came from running an old copy of the regex, not the live file.
  Measured against the hook `settings.json` dispatches to, 5/5 cases:
  `memory_observability.py` and `pipeline/intelligence_state.py` both
  **exit 2 BLOCKED**, `mlb-props-regen`'s file blocked, a CLOSED lane's file
  and an unclaimed file both allowed. The digest and the enforcement AGREE.
  `[measured 08-13]`
- The digest's "1 lane header has no parseable status" is
  `### (superseded lane detail, kept for the file/line map)` — not a lane, and
  correctly unguarded. `559d353d` also stopped such a header inheriting the
  previous lane's open state. `[measured 08-13]`
- **Exit 1 on Stop is advisory.** Delivered stderr carries "Failed with
  non-blocking status code". `/checkpoint` is documented as an obligation and
  is enforced by a log line. A gate would need exit 2; the always-fires defect
  that made that unsafe is fixed (`5cdf45b6`), but raising it is a deliberate
  decision, not a follow-up cleanup. `[measured 08-13]`
- Its denominator is now **the files this session edited**, not the worktree.
  Known gap, deliberate: only `Edit|Write|MultiEdit|NotebookEdit` are counted,
  so a session writing purely through `Bash` redirection reads as clean — the
  same blind spot `lane-guard` has. `[measured 08-13]`
- **A lane's status is free text, and both guards treat it as a predicate — so
  a lane can sit under `## OPEN` and be enforced by nothing.** Live right now:
  `memory-guard-reclaimable` was relabelled
  `— DEPLOYED, MEASUREMENT OPEN —` by its own session. `lane-guard.py` reads
  the status as the first word (`DEPLOYED`) and returns **exit 0 for
  `memory_observability.py`** — its 4 claimed files are unprotected; and
  `session-start.sh` v3 requires literal `— OPEN`, so the digest reports **1
  open lane when the file lists 2**. v1's substring test had the opposite
  failure (it counted `NO LANE WAS EVER OPENED` as open). Neither strictness
  is right: the fix is `OPEN` against the status field only, which
  accepts `DEPLOYED, MEASUREMENT OPEN` and rejects `OPENED`/`REOPENED`.
  **FIXED in `559d353d`** — both hooks now take the field between the 1st
  and 2nd em-dash and match the WORD `OPEN` in it. Both agree on the same
  set, which they did not before. `[measured 08-13]`
- **`lane-guard` is blind to `.claude/**` by design** — `rel.startswith(".claude")`
  returns 0 before any lane is consulted, so the enforcement layer cannot
  protect the directory it lives in. Every real collision today happened
  there. **Three sessions worked `.claude/**` with no lane on 08-13** (ops-kit
  11:00, hooks-enforcement 12:18, hooks-test 14:5x), each deciding
  independently that harness work is exempt. The protocol does not say it is.
  `[measured 08-13]`
- **`.syndicate/.current-lane` is ONE file shared by every session.** It named
  `checkpoint-guard-scope` — another session's lane — during this session's
  run. So `lane-guard` identifies whoever opened a lane most recently, not
  you: it can block your own edits AND fail to block a foreign session,
  depending on who ran `/lane open` last. It cannot do its job with more than
  one session live, and 5 were. `[measured 08-13]`
- **A lane's guard state hangs on ONE header line in a hand-edited shared
  file, and its deletion is silent.** At 14:5x the `memory-guard-reclaimable`
  header was removed from `lanes.md` while its body stayed; the body was
  absorbed into the preceding `checkpoint-guard-scope — CLOSED-VOID` block and
  **all 4 of its claimed files went to exit 0** — the same hole `559d353d` had
  just closed, reopened by a different mechanism 40 minutes later. Repaired by
  restoring the header verbatim (committed in `c506eb2a`; pre-repair backup at
  `/tmp/lanes.pre-repair.bak`). Nothing detected this; it was found by reading
  a diff. `[measured 08-13]`
- **`checkpoint-guard.py`'s witness is this session's own transcript, and
  `.last-checkpoint`'s MTIME IS NEVER READ.** The baseline is the newest
  checkpoint signal in the session's transcript: a `/checkpoint` invocation, a
  file-tool write to `.syndicate/**`, or a shell command naming a ledger file
  (step 2 is a `cat >>` heredoc and leaves no file-tool record). The marker is
  repo-global, so its mtime answers "did somebody checkpoint", not "did I" —
  reading it let session A's checkpoint silence session B's warning, losing B's
  work silently. The `touch` still counts, as a signal in the transcript rather
  than a timestamp on disk. No signal of the session's own means no baseline,
  which warns. `.syndicate/**` is excluded from work-at-risk: it is the
  persistence, not the thing persisted. Design and implementation are the
  archived `hooks-test` session's, recovered from its uncommitted file.
  `[measured 08-13, origin `cf6de8f7`]`
- **Verified by `tests/test_checkpoint_guard_hook.py`, 7 two-actor cases**,
  each with a bystander session doing the right thing. It discriminates: 7/7 on
  this implementation, 5/7 on the superseded one, failing the two-actor case.
  **Supersedes an earlier claim here of "8 fixture cases including the
  false-pass one" — that was false.** All 8 were single-actor and none tested
  the false pass, which is why it survived. `[measured 08-13]`
- Known limitation: `touched` is every path the session ever wrote, so a file
  it wrote and another session later modified is still attributed to it. Errs
  toward false warn, never false pass. `[measured 08-13]`
- **The 3-lane cap in `## Config` is policy with no enforcement.** Four OPEN
  lanes ran this session unchallenged; `/lane open` checks file collisions
  only and never counts. `[measured 08-13]`

## Test baselines

- `tests/test_intelligence_state.py` is **GREEN: 224 passed, 10 subtests
  passed, 0 failed** on `bd227fa3`. It had carried a standing
  `4 failed, 220 passed` on a clean checkout; `#288` closed 2026-08-13, all
  four repaired in the test with **zero source changes**. **A failure in this
  file is now yours** — it is no longer safe to assume standing noise, which is
  the whole point of having fixed it. `[measured 08-13]`
- It costs **~15 minutes** (891s red, 902s green), so it is not a quick check.
  The four historically-broken tests run alone in ~35s and are the cheap
  smoke: `test_build_candidate_pool_does_not_embed_full_odds_history_payload`,
  `test_query_endpoint_default_unchanged_when_combined_flag_disabled`,
  `test_read_latest_response_syncs_shared_backend_state`,
  `test_background_loop_survives_board_window_watch_exception`.
  `[measured 08-13]`
- Two of those four are pinned against SOURCE by mutation, not just by green:
  re-embedding `odds_history` on the per-sport pool entry, or removing the
  sport-scoped `_latest_key` promotion skip, each turns the right test red.
  `[measured 08-13]`
- **Green here says nothing about `tests/test_intelligence.py`.** `#288`'s
  record notes two query failures and a blotter failure in other files; those
  were never in its scope and were **not re-measured** on 08-13.
  `[unverified 08-13]`

## Board live tier (layer1-live-tier lane)

- **The live prop join was matching 0 of 1385 rows** — keyed on `market`, which
  is a display GROUPING (`hitter_props` covered 4 markets). Fixed `#412`;
  control on one production snapshot + board: 0 -> 41 rows. `[measured 08-13]`
- **Board game state is stamped from the live-lens snapshot, not the cached raw
  feed** (`#413`). `_mlb_feed_live_payload` consults the cached feed for
  PRESENCE only, never freshness, so a game froze at whenever it was first
  captured. Override measured `rows_corrected 210, live->final 210`.
  `[measured 08-13]`
- **No live GAME-LINE projection exists.** `predictions.full` in the live-lens
  snapshot is the PREGAME sim — all 6 final games carried pregame win
  probabilities (0.489 on a completed game). Only PROPS have a live tier.
  `[measured 08-13]`
- **`liveModelProbOver` reaches the published snapshot's keyspace**, value null
  so far. Transport is not the break. `[measured 08-13]`
- **`rows_live_edged` is 0 on every build to date**, and the flat counter cannot
  be read while a slate is mostly final — final props come from a registry path
  that never computes a live probability. `e054e19f` splits by game state; the
  `live` bucket has **never been observed against a live slate**.
  `[unverified 08-13]`
- **Web's `/mlb/api/live-lens` cannot observe the live Monte Carlo**:
  `simContextAvailable: False` on all games, `gameLens source: ABSENT` on all
  lanes. Do not verify live-sim work through it. `[measured 08-13]`

### Sim execution and the board build

- **MLB board build: 688.7 / 719.0 / 852.5 / 1125.2 / 1157.3 s** over five
  builds at 102–206 candidates — **spread 1.68×, no code change**. Judge any
  future delta against this series, not against a single earlier build.
  Morning builds are ~4.4s at 16 candidates: the cost tracks time of day.
  `[measured 08-13]`
- **An orphaned MLB sim now records a CAUSE**, not just a death:
  `MLB_DAILY_SIM_ORPHANED state=killed_by_restart` observed `00:24:36` and
  `23:00:18`. Only the tick owner writes it. `[measured 08-13]`
- **NFL projections were written to the ephemeral checkout** — the generator
  used `/opt/render/project/src/data/...` while the guard read
  `/opt/render/project/data/...`, so ~90 completed sims/day were discarded.
  Guard and writer now share `nfl_artifact_output_root()`. `[measured 08-13]`
- **The deploy sim-gate refuses in flight, not only in theory**: three polls of
  `HOLD: 3 job(s) in flight`, then `CLEAR`, then deploy. `[measured 08-13]`
- **Where the board-build cost lives is NOT established.** The row loop is
  exonerated only as far as an instrument that could not distinguish rows from
  the tail — see `learnings.md`. Leading candidate is per-candidate scanning in
  the tail; unmeasured. `[unverified 08-13]`

## NFL day-of-game (nfl-day-of-game lane)

- **NFL games now carry real state on every surface.** `by_state` went
  `{pregame:6, live:0}` → `{live:5, pregame:1, final:0}` with real scores and
  clocks (`DET@CIN 3-10 Q2 0:07`). The game that had not kicked off stayed
  `pregame` with a real start time, so this is not a blanket relabel.
  Read on an artifact `generated_at 00:36:18Z`, **23 min after the deploy
  instant** — freshness checked, not assumed. `e29b807f` (web) +
  `98950c6d` (refresh-worker). `[measured 08-13 19:36]`
- **The cause was one missing field, not five broken surfaces.**
  `_NFLDataProvider.games()` fed `build_game_chips` week-scoped projection
  cards with no game state at all (`status` a plain STRING, no `live_state`),
  so `_game_flags` returned `(False, False)` for every NFL game forever. The
  fix sets `live_state`, which `publication_adapter._shared_game_state` and
  `game_chip_scoreboard._game_flags` both already read. `[from-code 08-13]`
- **`#377`'s constant is GONE and was never a model defect.** `distinct
  projected_raw` 1 → 6; board and cards now agree 6/6 to three decimals on
  tonight's games, having disagreed while reading the same FILENAME.
  `rows_with_projection` held at 75 — no row lost a projection.
  `[measured 08-13 19:36]`
- **It was file selection.** `load_nfl_game_projections` deduped candidates by
  NAME across source roots, so only the first root's copy was ever opened, and
  `data/nfl_source/tracking/` (the nflverse pbp) is **gitignored** — a
  generator run whose root resolved to the repo checkout rates every team
  `neutral_no_data` and writes identical rows. Now dedupes on resolved PATH,
  drops both-sides-neutral rows, newest `generated_at` wins. `[from-code 08-13]`
- **The WRITER is now guarded too (`c7cff28c`, refresh-worker, live
  `2026-08-14T01:35:38Z`).** Supersedes the line that stood here saying the
  root cause was unfixed. Two guards: zero plays loaded for both seasons fails
  BEFORE the sim; every-projection-degenerate writes NOTHING, so the last good
  artifact survives. Threshold is ALL-degenerate, not any — a partial still
  carries real information and the reader already drops bad rows. Proven
  end-to-end against the real program: no pbp -> exit 1 with the artifact
  byte-identical; control with real pbp -> exit 0, artifact rewritten.
  `[measured 08-13]`
- **That guard is INERT in production, and that was measured before shipping.**
  The worker CAN see `pbp_2025.csv`: its 21:00:11Z run printed
  `artifact_path=/opt/render/project/data/nfl_source/...` at 21:02:06Z and the
  resulting artifact carries a real rating on **16 of 16** games. Post-deploy,
  `DegenerateProjectionRun`/`Traceback` both 0 against a 20-row positive
  control. So it is a trap for a failure mode not currently occurring — if it
  ever fires, root resolution has moved. `[measured 08-13]`
- **`PBP_LOADED` CANNOT be used to answer "does the worker see the pbp".** The
  generators emit it through a `log()` that writes only to `--progress-log`,
  never stdout, so it never reaches Render's collector. A 0 there is a fact
  about the emitter. Use `artifact_path=` (printed) or the artifact's
  `rating_source`. `[from-code 08-13]`
- **`#389`'s follow-up is CONFIRMED WORKING**, on the criterion the ticket set
  in advance: a positive `artifact_path=` on the mounted disk with no `/src/`.
  Corroborating: `SEASON_PROJECTION_ARTIFACT_MISSING` 30 before that write, 0
  after, queried as its own window with a control. Writer and staleness guard
  finally resolve the same root — the defect that discarded ~90 NFL sims/day.
  `[measured 08-13]`
- **`#377` is CLOSED-VERIFIED**, and it had THREE parts. `projected` distinct
  **1 -> 6** on the same 34-card board it was filed against; its product
  decision was already answered by `7c854234` (41 rows carry
  `projection_unavailable_reason`, 75 carry `model_skill`). Its third part —
  `skill_note` covers **1 of 7** projection builders — was never worked and is
  now **`#425`, OPEN, UNOWNED**. `[measured 08-13]`
- **Two clubs were rated league-average all season.** Schedule spells them
  `LAR`/`WSH`, nflverse pbp spells them `LA`/`WAS`; production read
  `prior_season_fallback` on every club except exactly those two. Fixed in
  `team_rating` (the one function both generators share), deployed `111a5000`
  — **but NOT observable until the next season-projection autorun, due
  ~08-14 16:00 CDT (21:00Z). OWNER UNASSIGNED.** `[measured 08-13; effect unverified]`
- **NFL odds refresh is HEALTHY and was never the defect.** A 13-minute
  pregame→live transition lag was misread as a stoppage. The loop flips
  `phase=live` on its own and live games reached 117/99 quote rows at 1.3-min
  freshness. Do not re-investigate. `[measured 08-13]`
- **`PRESEASON_WEEK_LABELS` mapping internal week 2 → "Preseason Week 1" is
  CORRECT, not a bug.** Internal week 1 is the Hall of Fame game. A session
  nearly "fixed" it. `[from-code 08-13]`
- **The MLB sim ledger never records completion.** 34 of 34 runs on 08-13 and
  1 of 1 on 08-14 read `state=running, finished_at=null`, while soccer
  (187/187) and wnba (10/10) record `ok`. So "did the MLB sim finish" is
  **unanswerable from the ledger** — a deploy gate cannot be built on it.
  MLB-specific, uninvestigated. `[measured 08-13]`

## Open problems

- **Something allocates 493–878MB in-process on refresh-worker and nothing knows
  what (`#327` RESIDUAL).** Released within ~72s, arriving 11–42 min apart, peak
  observed at container **3459.1MB = 84% of a 4096MB cap**.
  `post_mlb_sim_tick` is a **BYSTANDER** — all five sub-features report
  `launched=false` at every peak, so the stage name marks the observer, not the
  allocator. Five causes eliminated. **Strongest lead:** both hot-artifact
  operations allocate 300–717MB while transferring *nothing* (`pub=0`,
  `pulled=0`), so the cost is in the export payload, not the transfer — but
  **only counts have been measured, never bytes.** `[measured 08-10]`
- **`#312`'s `sync: false` protection is on `main` and live on NOTHING**, and
  the `blueprint_sync` mechanism remains **untested** — the only deploy carrying
  it was cancelled, so the mechanism was never offered its input. That is the
  wrong experiment, not a null result. `[measured 08-10]`

- **The L2 board freezes silently and only a restart clears it (`#417`).**
  `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` fired 300 consecutive
  cycles `09:29:27Z–14:54:44Z`, aborting before the fingerprint, so no
  shortlist was built or written for **4h12m**. Not a leak: `anon` drifted
  **+18.9 MB** across all 300 samples. The guard
  (`_MIN_SAFE_MEMORY_HEADROOM_BYTES = 1900`) credits only `inactive_file`, so
  when the kernel promoted ~243 MB to `active_file` at ~11:02, effective
  headroom fell 1877 → 1643 **while total memory in use fell 3120 → 2705 MB**.
  Sibling of `#387`, different guard. `[measured 08-13]`
- **`#417` FIX IS DEPLOYED, NOT YET PROVEN.** `03073270` live on
  refresh-worker since 13:05 CDT. The guard now decides on
  `max - max(anon + shmem + slab_unreclaimable, current - reclaimable_file)`,
  with `active_file` counted as reclaimable. At T+23min: `LAYER2_SHORTLIST`
  **x3** vs 0 in the preceding 4h12m, `MEMORY_GUARD_ABORT` **0** vs ~300 in
  5.4h. `[measured 08-13 13:28]`
- **That is NOT yet evidence the fix holds.** The pre-fix code also rebuilt
  after the 14:56 restart (built 15:08) and re-froze ~3h later — it was
  aborting again by 18:00Z. The deploy has not survived that re-warm
  interval, so T+23min is consistent with "rebooted" as much as "fixed".
  **The 24h read settles it: due 2026-08-14 ~13:00 CDT, OWNER UNASSIGNED.**
  `[unverified 08-13]`
- **It is also unconfirmed that the new code PATH executed.** `basis`, the
  field meant to prove it, is emitted only inside the abort branch
  (`intelligence_state.py:3215`), so a working fix leaves it silent forever.
  Needs a success-path log — its own change and deploy. `[unverified 08-13]`
- `live-odds-worker` disk usage climbing steadily, ~20% → ~40% of 50 GB
  over two weeks. Something accumulates and is not cleaned up.
  **Not yet diagnosed.** `[measured 08-12]`
- Chronic instance restarts / failures across the fortnight, instance count
  dropping to 0. Pegged CPU, climbing memory. **Cause unconfirmed — may or
  may not be downstream of the egress issue.** `[from-logs 08-12]`

## Resolved

- Aug egress ~2.1 TB outbound vs 25 GB included; ~1.79 TB service-initiated.
  Root cause: `SYNDICATE_WEB_PUBLISH_URL` pointed at the web service's
  **public** URL, so workers POSTed every artifact out to the public
  internet and back in. `[from-code 08-12]`
- Secondary cause: a checksum was computed and sent but never compared, so
  unchanged artifacts re-uploaded in full every sweep. `[from-code 08-12]`
- **Cutover is live and durable.** Every `PUBLISH_OK` on refresh-worker at
  `14:54:11Z` carries `url=http://syndicate-an21:10000/...`, and `render.yaml`
  holds the internal hostname for both workers, so a `blueprint_sync`
  reinforces it rather than reverting it. `[measured 08-13]`
- `#401`'s maintenance runner is **not** broken: 15.62h elapsed against an
  86400s interval, the env override unset on both workers. Next run expected
  ~`23:38:06Z`. `[measured 08-13]`

## Soccer odds capture — VERIFIED 2026-08-14 18:4xZ

- **Soccer GAME odds have not been captured for ANY league since 08-10/08-11.**
  `[measured 08-14 18:4xZ]` The `book_quotes` shard split by `kind`:
  eredivisie `prop` 467 rows newest **2026-08-14T17:21:44**; eredivisie `game`
  77 rows newest **2026-08-10T20:54:06**; primeira_liga / belgian_pro_league /
  championship carry `game` rows ONLY, all 08-10/08-11.
  **Eredivisie looked healthy solely because prop rows from a different
  producer masked it.** Corroborated by mtime: all four
  `<league>/api/odds/game_odds_current.csv` bound to **48-96h old** via the
  export route's `since` filter, probe validated against a control first.
- **The vendor is NOT the cause.** `/api/ops/oddsapi/sports` (new, read-only):
  all ten soccer keys `listed=True, active=True` out of an 82-entry catalogue.
  `[measured 08-14 18:3xZ]`
- **SOCCER GAME ODDS HAVE EXACTLY ONE PRODUCER, and it is not refresh-worker.**
  `[measured 08-14 18:5xZ, /api/ops/odds-refresh/plan dry_run]`
  `phase=pregame` builds 50 steps including **10 odds steps**; `phase=live`
  builds 20 steps and **0 odds steps**. refresh-worker's soccer unit autorun
  runs `phase="live"`, so **it never fetches soccer odds at all** — by design
  since `#148`. Everything depends on
  `_launch_autorun_soccer_pregame_refresh` on live-odds-worker, 4h cadence.
  **Single point of failure; write this down before theorising again.**
- **The `#433` step reorder does NOT fix the outage.** `[measured 08-14 18:56Z]`
  A pregame autorun launched **18:13:14Z**, 31 min after `9a3a5bc6` went live,
  so odds ran at steps #11-20 instead of #21-30. 43 minutes later: still zero
  `game` rows for any league. Position was never the variable. The reorder is
  retained on its own merits (cheap captures should not queue behind ten sims)
  but must not be credited with fixing capture.
- **WHY the step fails, or the run exits, is STILL UNKNOWN.** `[unverified]`
  No error has been observed anywhere. `PROCESS_TREE_MEMORY child_count: 0` at
  18:21:34Z suggests the subprocess was gone ~8 min after launch, but that is
  one periodic sample and bounds the lifetime loosely — it is not proof.
- **The run's own logs are UNREADABLE FROM WEB — and this is now instrumented.**
  `[measured 08-14 18:5xZ]` `/api/ops/odds-refresh/logs` returns `exists=False`
  for both lanes with fresh stamps. That is the web/worker **disk split**, not
  an absence of logs; never read it as evidence. `launch_refresh_run` spawns
  the refresh `stdout=DEVNULL, stderr=DEVNULL` and the child's log files land
  on the WORKER's disk, while Render's collector captures only a service's own
  stdout — which is how four days of failure produced no visible error.
- **FIX SHIPPED (observability only, NOT a repair).** `[measured 08-14 19:24Z]`
  live-odds-worker `ccd10349` (= `9a3a5bc6` + one file) live **14:24:09 CDT**;
  post-deploy logs clean, **zero tracebacks**. It reads the artifact its own
  child wrote and prints `SOCCER_PREGAME_RUN_SUMMARY`, one line per `_odds`
  step, one line per failure, and `SOCCER_PREGAME_RUN_NO_ARTIFACT` when the
  child wrote nothing.
  - **Emits nothing until the next launch, BY DESIGN.** The on-disk status file
    predates the change and has no `artifactsDir`. Zero `SOCCER_PREGAME_RUN_`
    lines right after the deploy is correct, not a failure.
  - **First readable outcome ~17:28 CDT** (4h autorun ~17:13, reported one tick
    later). Until then the failure mode remains unnamed. `[unverified]`
- **Two hypotheses are DEAD; do not re-run them.** `[measured 08-14]`
  (1) Step truncation at #27 of 50 — falsified by a single-league scoped run
  (~6 steps) that captured nothing. (2) Three-specific-leagues — all ten are
  affected. The step reorder shipped against (1) is retained on its own merits
  but did NOT fix this.

## OddsAPI budget — VERIFIED 2026-08-14 17:2xZ

- **Projected 30-day burn 4,640,809 credits = 92.8% of the 5M cap.**
  `[measured 08-14 17:2xZ, /api/ops/oddsapi/quota]` `credits_per_hour` 6,445.6.
  Headroom ~360k/month. By sport: mlb **93.7%** of spend (8.72 cr/call), soccer
  4.2% (**1.46** cr/call — 6x cheaper than MLB), nfl 1.4%, wnba 0.7%.
  Pregame hours are cheap (10-18k/hr); live hours dominate (83-228k/hr).
- **MLB pregame sweep interval is now 3600s, and the effective gap is
  ~1h10m, not 1h.** `[measured 08-14 16:20Z]` Gap moved 7,289s -> **4,215s**.
  The loop wakes every 900s and sweeps whatever is past its interval, so the
  setting is a FLOOR the tick quantises — expect 3,600-4,500s. nfl/wnba remain
  7200s, soccer 28800s.
- Per-sweep MLB cost ~214 credits / 31 calls — **ONE interrupted sample,
  order-of-magnitude only.** `[unverified]`

## The published shortlist's edge numbers (lane `recommendation-lane-correctness`)

- **40% of the published board is ranked on a constant.** All 100 soccer rows on
  `/api/board/layer2-shortlist` are priced by `book_margin_model` with
  `books_quoting: 1`. That model is `fair = implied x (1 - hold)`, so `ev_pct`
  is identically `-assumed_hold_pct` — the book's own margin restated, carrying
  no information about the bet. Reproduced on **100 of 100 rows, 0 mismatches**;
  **3 distinct holds underlie 19 distinct `ev_pct` values** (the spread is 4-dp
  rounding of `fair`, not signal); **all 100 carry a negative `score`**. The
  value floor cannot reject them — soccer's floor is `-8.1425 = -1.25 x 6.514`
  and 6.514 is the same modelled hold. `[measured 08-14 18:26Z]`
- **The model-free half of the board is the longshot half.** Rows without
  `model_edge_pct`: median **+875**, 82.2% plus-money, p90 +4000. Rows with it:
  median **+113**, 63.2%. 174 of 250 published rows have negative `ev_pct`
  (median -6.54). `[measured 08-14 18:26Z]`
- **The audit's "0.5 coin-flip default" is FALSE as a production mechanism.**
  `_fair_probability`'s `0.5` terminal is unreachable: every
  `filter_candidates` call site is fed `_score_candidates` output and
  `score_candidate` always assigns `score`, so `score/100` fires first. That
  rung yields fair probabilities of 0.01-0.13 and so a large NEGATIVE edge —
  model-free candidates were silently REJECTED, not published. Removing only
  the `0.5` would have been an inert fix. `[measured + from-code 08-14]`
- The recommendation lane does **not** price the shortlist. Every published row
  carries `quote.fair_method` = `consensus` or `book_margin_model`. Fixes to
  `recommendation_engine` should NOT be expected to move the shortlist.
  `[measured 08-14]`
- Web service is **`https://syndicate-an21.onrender.com`**
  (`srv-d88ahvrbc2fs73eodu30`). `syndicate.onrender.com` 404s. `[measured 08-14]`

## A3 SHIPPED AND VERIFIED — the board no longer publishes hold-restatement rows

- **LIVE on both services 2026-08-14.** web `ea1d2ed6` (19:37:00Z, reader),
  refresh-worker `29ed6de1` (19:49:15Z, builder — this is the one that filters;
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=true` ONLY there).
  `[measured 08-14 19:58Z]`
- **Measured on the first post-deploy build (19:58:41Z), five predictions
  written BEFORE the deploy, all held:** `rows_uninformative_ev` null → **4003**;
  soccer selected **100 → 0** (absent from `per_sport`); `total_rows`
  **256 → 156** (exactly 256−100); `book_margin_model` served rows **100 → 0**;
  and the **CONTROL — mlb 84 / nfl 60 / wnba 12 — UNCHANGED to the row.**
  `fair_method` mix is now `{consensus: 156}`. `[measured 08-14]`
- **WHY that control held — the mechanism, not a coincidence `[measured 08-14
  21:2xZ]`.** NOT because MLB lacks modelled rows: the book-grid shows mlb
  carries **357 one-sided rows with a modelled fair** (wnba 42, nfl 0), so the
  rule CAN reach MLB. It held because mlb has `rows_with_model_edge = 2256` and
  the rule keeps any row carrying a model view. **The narrowness clause is what
  protects MLB.** A later reading of mlb 84 → 78 is 1.4h of SLATE DRIFT against
  a 19:58Z measurement, not the rule — `total_rows` 156→150 and
  `rows_uninformative_ev` 4003→3842 drift identically. Re-read the post-deploy
  measurement before attributing a later delta to the deploy.
- **RANKED FIXES #3 + #4 (audit §7) ARE LIVE on refresh-worker `79148d8e`
  (20:13Z). P1 VERIFIED ONLY.** `[measured 08-14 20:44Z]` A post-deploy cycle
  ran (`snapshot_generated_at` 20:29:31Z) and `recommendation_count` went
  145 → **148** — the lane did NOT empty, which was the revert trigger.
  The DIRECTION is unproven: the two readings are 3.9h apart and slate drift is
  unexcluded. **P3 (the `FILTER_CANDIDATES` instrument) remains UNMEASURED.**
- **The audit's `0.5`-fallback mechanism was BACKWARDS `[measured 08-14]`.** The
  `0.5` terminal is UNREACHABLE in production: every `filter_candidates` call
  site is fed `_score_candidates` output, so `score/100` always won first
  (score 4.05 → fair_prob 0.0405 → edge −0.36). Model-free candidates were not
  published as coin flips — they were silently REJECTED under
  `reason: "edge_below_threshold"`, a reason that claimed an edge had been
  measured when no model had run. Removing only the `0.5` would have changed
  nothing.
- **AUDIT §7 #7 IS SHIPPED. MLB PROP ROWS NOW SERVE MEASURED SKILL.**
  `[measured 08-15 00:35:56Z]` refresh-worker `098877e1`. 24 prop rows carry
  `model_skill` with `correlation` + `verdict` (batter_rbis 12, total_bases 6,
  hits 3, runs_scored 3), e.g. total_bases `corr 0.1523, n=2487, "biased high
  ~18%; real ranking signal, loses to the mean until de-biased"`.
  `batter_hits_runs_rbis` correctly stays **unmeasured** (`#429`'s degenerate
  0.0 — it must not inherit a neighbour's number). Label-only: no projection,
  mean or edge changed. **NFL's own skill notes (corr -0.047/0.269, seasons
  2023-2025) are unrelated and predate this** — do not read them as leakage.
- **CLV: THE OPENING HALF IS NOW RECORDED. THERE IS STILL NO VALID CLV NUMBER.**
  `[measured 08-14/15]`
  - Recorder live (`2b14fbeb`), wired in `build_layer2_shortlist` so both board
    paths hit it. **584 bytes/record vs the evaluation chunk ledger's 40,555.**
  - `book_prices` (every book's price for the side) on **150/150** served rows.
  - **`avg_clv_pct` is None and that is the honest answer.** An early
    `-5.215` over 25 same-book rows was RETRACTED: the line was never checked
    (comparing `home -5.0` to a `home -1.5` close) and **25 of 25 closes
    PRECEDED their openings**. Both are now refused by name
    (`line_mismatch`, `line_unverifiable`, `close_precedes_open`).
    `close_precedes_open` is a PRODUCTION condition — it fires whenever a
    market is first published after the last pregame observation of it.
  - The joiner is **library-only, no call site, NOT deployed**
    (`deploy/clv-joiner-guards-r2`, `2f596260`).
  - **First clean same-book measurement is 2026-08-15**, because production's
    08-14 openings only began at 18:32 CDT.
- **DATES IN THIS SYSTEM ARE CENTRAL, NOT UTC `[verified 08-14]`.**
  `central_today_iso()` (`syndicate/features/shared/timezone.py`) is the slate
  clock and the board reported `date: 2026-08-14` at 00:44Z. A UTC wall clock
  read cost a wrong "the date rolled over" call this session. An MLB slate
  spans two UTC dates; it does not span two Central ones.
- **The intelligence-state background loop IS RUNNING `[measured 08-14
  21:22Z]`** — `[intelligence_state] LAYER2_SHORTLIST rows=150
  considered=14062 sports=['mlb','nfl','wnba']`, with 140 `PUBLISH_OK` and 0
  publish failures. What is stale is only the `/api/intelligence/status`
  SNAPSHOT (`recommendation_count`), a different artifact from the layer2
  shortlist. **Do not diagnose "the loop is dead" from a stale snapshot.**
  The NFL season projection launches via `subprocess.Popen` (non-blocking) on
  its own thread and does NOT block the loop — hypothesis tested and FALSE.
- **Soccer now serves ZERO shortlist rows, and that is the intended state, not
  an outage.** Its whole shortlist presence was one-book longshot props
  (`player_shots`, `player_shots_on_target`, `player_to_receive_red_card`,
  `player_assists`) whose `ev_pct` was arithmetically `-assumed_hold_pct`.
  **Read `rows_uninformative_ev` before diagnosing soccer as broken** — soccer
  is ABSENT from `per_sport` rather than present at 0, so that counter is the
  only thing distinguishing "no slate" from "slate was all margin restatement".
- **This does NOT depend on soccer projections and never will.**
  `player_shots`/`player_shots_on_target` map to a MEAN and `soccer_projections`
  refuses by design to derive a probability from a mean; the rows are one-sided
  so `_no_vig_over_probability` returns None. Two independent rules each
  guarantee no `model_edge_pct`. The filter **self-heals**: it keys on
  `fair_method`, so if soccer ever gets two-sided quotes the fair becomes
  `consensus` and the rows return with a real EV, no code change.
  `[from-code 08-14]`
- **The two services are on DIVERGENT lines and no single branch fast-forwards
  both.** They diverge at `b98f5ed7`; web ran `8ff4e513` (deploy branch),
  refresh-worker `294f9ca9` (main). A branch cut for web is a **ROLLBACK** for
  refresh-worker — it would have dropped `#429`'s MLB HRR producer fix. Cut one
  deploy branch PER SERVICE from that service's own live SHA and check
  `git merge-base --is-ancestor` both ways before every deploy. `[measured 08-14]`
- **Deploys here go by explicit `commitId`.** Both services are configured
  `branch=main, autoDeploy=no` yet run off-branch commits, so a deploy needs no
  service-config change and touches no `render.yaml` → no `blueprint_sync`.
  `[measured 08-14]`
- **STILL UNDEPLOYED from this lane, deliberately:** A1/A2
  (`recommendation_engine.py`) and A3a (`opportunity_signals.py`, the
  `blended_score` monotonicity fix). Excluded so A3's effect stayed
  attributable. `[08-14]`

## ~~WORKER→WEB FILE-ARTIFACT PUBLISHING IS FAILING ON A DNS NAME~~ — **RETRACTED 2026-08-14 20:1xZ**

**THE SECTION BELOW IS WRONG ON ITS CENTRAL CLAIM. Kept only so the reasoning
error is visible; do not act on it.**

- **`syndicate-an21` RESOLVES FINE.** `[measured 08-14]` refresh-worker logged
  **PUBLISH_OK at 19:54:40Z and 20:03:16Z to that exact URL**, and
  live-odds-worker logged **14 / 18 / 13 PUBLISH_OK** across three windows
  including 19:50-20:10Z. The "internal hostname is the service name, so
  `syndicate-an21` is wrong" claim was an INFERENCE from Render's naming
  convention, I labelled it untested, and it is now **falsified**.
- **The failures were a TRANSIENT BURST, not a standing outage.** PUBLISH_OK at
  19:54:40 → 11 PUBLISH_FAILED at 19:59:36 → PUBLISH_OK at 20:03:16. Success
  brackets the burst on both sides.
- **So it does NOT explain "soccer odds frozen platform-wide."** That lead was
  over-reach and is withdrawn; a cross-lane note on `soccer-odds-coverage` has
  been retracted in place.
- **Was it caused by the A3 deploy? NOT PROVEN EITHER WAY, and probably not.**
  The worker published successfully 5 minutes AFTER going live and again 4
  minutes after the burst, so this is not a container-start effect. It is also
  not exonerated: I have no cause for it.
- **The method error that produced this, worth more than the finding:** I read
  "0 PUBLISH_FAILED before / 11 after" off windows that each returned exactly
  **100 lines — the API cap**. This logs API returns the TAIL of a window
  regardless of `startTime`, so a saturated window proves NOTHING about absence.
  I then stated "not caused by my deploy" as settled. The user challenged it,
  and the correct control — **live-odds-worker, same env var, never deployed by
  me** — took one query and was decisive. Reach for the untouched control first.

### (original, wrong, retained for the record)

**Found incidentally while health-checking the A3 deploy. NOT caused by it —
this is an env var, and A3 changed no env var and no publish code.**

- **Measured** `[08-14 19:59:36Z, refresh-worker logs]`:

      [artifact_publisher] PUBLISH_FAILED
        path=soccer_source/<league>/api/live_state/live_state_2026-08-14.json
        url=http://syndicate-an21:10000/api/ops/artifacts/publish
        error=<urlopen error [Errno -2] Name or service not known>

  11 such lines in one 6-minute window, across `mls`, `ligue_1`,
  `primeira_liga` and others.
- **`SYNDICATE_WEB_PUBLISH_URL = http://syndicate-an21:10000` on BOTH workers**
  (refresh-worker and live-odds-worker). `[measured 08-14]`
- **`render.yaml` names the web service `syndicate`.** Render's INTERNAL
  hostname is the SERVICE NAME; `syndicate-an21` is the PUBLIC subdomain prefix
  (`syndicate-an21.onrender.com`). So the publish URL names a host that does not
  exist on the private network — which is exactly what the DNS error says.
  - **Confidence split, deliberately:** that `syndicate-an21` does NOT resolve
    is **measured** (the error is the proof). That `syndicate` WOULD resolve is
    **inferred** from Render's naming convention and is **NOT tested**. Do not
    ship a hostname change on the strength of the second half — test it first.
- **This is plausibly the missing piece under the OPEN soccer lanes**
  (`soccer-odds-coverage`: "soccer game odds are frozen platform-wide";
  "soccer odds have ONE producer, and the reorder did not fix it"). If worker→web
  FILE publishing is dead, artifacts computed on the worker never reach the disk
  web reads, and a step-ordering fix could not possibly help. **Offered as a
  lead, not a diagnosis — not this lane's file set, and not measured end to end.**
- **Why it has stayed invisible:** keyvalue-backed state (`refresh_state_store`)
  publishes fine — the Layer 2 shortlist rebuilt normally at 19:58:41Z. Only
  FILE artifacts go through this HTTP path. So the board looks alive while
  file-backed per-sport artifacts go stale.
- **Suspect `internal-hostname-cutover` (CLOSED 2026-08-13, "verified in
  production").** If that cutover set the public subdomain prefix believing it
  was the internal name, it would have silently broken file publishing while
  passing whatever check closed it. Worth re-opening rather than trusting.
- **NOT FIXED HERE.** It is config, it needs a deploy to take effect
  (a restart does not re-inject env), and it belongs to the soccer/publish
  owners. Flagged only.

## Card UI — what is TRUE in production vs. what is fixed locally

- **Production still carries all of it. `[measured 08-14, prod, trusted
  Playwright]`** `scripts/ui_layout_probe.py --base-url
  https://syndicate-an21.onrender.com`: 28px horizontal overflow desktop on
  nfl/ncaaf/soccer/ncaab, **20-40px MOBILE (the audit reported desktop only)**,
  NCAAF's default `Game` tab targets a panel that does not exist (blank 187px
  card on a trusted click) with `identity` and `coverage` unreachable, every
  sport's mobile tab targets 28px against WCAG's 44, `font-variant-numeric:
  normal` on every numeric card class.
- **Fixed and measured LOCALLY, not deployed, not committed. `[measured
  08-14, local]`** Same probe: 0px overflow both widths, 0 orphan tabs, 0
  unreachable panels, every trusted tab click activates exactly one panel,
  0 tabs under 44px, tabular figures on. Lane `board-ui-visible-defects`.
- **The probe is the durable part.** It reproduces the 2026-08-14 audit's
  numbers on demand, and it was validated against production BEFORE the fix
  so its post-fix "OK" is a reading, not an assumption. Synthetic
  `el.click()` is not used anywhere in it — the audit had to retract a
  finding produced that way.
- **NBA / NHL / NCAAB serve 0 cards, in production and locally.** Their rows
  in the audit's divergence matrix are code-only. Re-measure in October.
  `[measured 08-14]`

- **Card UI defects are FIXED IN PRODUCTION as of 2026-08-14 21:42:56Z.
  `[measured 08-14 21:4xZ, prod, trusted Playwright]`** Supersedes the block
  above: web `aadcde77` (= `5382943c` + `cf066942`, pinned branch
  `deploy/board-ui-lane-e`). Horizontal overflow 28px desktop / 20-40px mobile
  -> **0 at both widths on nfl, ncaaf, soccer and ncaab**; NCAAF's default tab
  0 panels/187px -> 1 panel/556px; orphan tabs and unreachable panels -> 0;
  mobile tab targets under 44px 64/48/4 -> 0; numeric classes `normal` ->
  `tabular-nums`. Before/after JSON in `reports/ui_layout/`.
- **Deployed SHAs re-read 08-14 21:35Z, and ALL THREE had moved again since
  the 18:32Z line above** — web `5382943c` (now `aadcde77`), refresh-worker
  `7b1f3fdc`, live-odds-worker `ccd10349`. `[measured]` The rule stands: read
  them, never quote them.
- **`origin/main` is 28 commits ahead of what web runs, and the local tree was
  147 ahead / 119 behind `origin/main` at 21:0xZ. `[measured 08-14]`** Local
  `main` has not been pushed since the 08-13 12:11 split; this lane pushed via
  a throwaway worktree at `origin/main` rather than reconciling it. **Nobody
  should deploy main's tip to web without enumerating that 28-commit delta** —
  it carries four other lanes' production changes, including 440 deleted lines
  across the `ask_the_syndicate*` blueprints and `aac18260`, which state.md
  records as deliberately on neither service.

- **Lane `board-ui-visible-defects` shipped: `cf066942` (fix) and `ee590ed5`
  (the production reading) are on `origin/main`; web runs `aadcde77`.
  `[measured 08-14 21:4xZ]`** `scripts/ui_layout_probe.py` is the durable
  instrument — it reproduced the audit's before-numbers against the unchanged
  service, which is what makes its after-numbers a reading rather than a
  belief. Re-run it before trusting any future claim about card layout.

- **The `main` divergence is RESOLVED IN A COMMIT THAT IS NOT YET PUSHED.
  `[measured 08-14 22:0xZ]`** Local branch `reconcile/main-divergence` =
  `abe4355f`, a merge of local `main` (at `dac86ada`) into `origin/main` (at
  `ee590ed5`). Worktree `C:/tmp/wt-reconcile` still holds it. **The push was
  blocked by the session's permission layer, not by git** — one command
  finishes it:
  `git -C C:/tmp/wt-reconcile push origin HEAD:main`.
- **What the divergence actually WAS, measured not guessed:** of 148 local
  commits ahead, **102 were already upstream by patch-id** (cherry-pick copies
  made by every session's pinned-deploy workflow) and **45 were not** — real
  work, some of it running in production, that never reached `origin/main` in
  any form. Of 121 origin commits, only **19** were new to local, and they
  touch no `syndicate/` production code at all. `[measured 08-14]`
- **`render.yaml` is byte-identical on both branches**, so reconciling carries
  no config change and cannot fire a `blueprint_sync`. Check this FIRST on any
  future reconciliation; it is the one file where a push is a production
  change. `[measured 08-14]`
- **Two tests in `tests/test_intelligence_state.py` fail on BOTH branches** —
  `..._fallback_merge_falls_back_on_empty_pool` and
  `..._recomputes_when_cached_snapshot_is_stale` — verified by swapping each
  side's `pipeline/intelligence_state.py` + test file into one worktree and
  re-running. Pre-existing, not merge-induced. `bd227fa3` claimed this file
  was "224 green"; it is 222/2 today on both sides. `[measured 08-14]`

- **The board's win-probability bar shows a probability or nothing, in
  production, as of 2026-08-15 00:50Z (web `932a1f71`). `[measured]`** Seven
  fabrication sites in `game_board_contract.py` are gone: an absent
  probability renders as an explicit empty state, a genuine 0.0 survives
  instead of becoming 50/50, and a projected scoreline is never recast as a
  win split. Soccer's three-way markets carry a draw segment and the bar reads
  the SIM, so the card no longer shows the sim's 77.3% and the market's 81.1%
  under one label.
- **A 50/50 on the board now MEANS 50/50.** The one still served (NFL, Denver
  @ Kansas City) sits on a 0.4-point projected margin — the producer's own
  `home_win_rate`. Checked before being called a leftover. `[measured 08-15]`

- **Lane F is CLOSED-VERIFIED and live. `[measured 08-15 01:41Z]`** Board
  surfaces show a probability or an explicit empty state, never a fabricated
  neutral; soccer three-way markets carry a draw segment and the bar reads the
  sim; one null placeholder (`—`) platform-wide, with NCAAF's hyphen cells 48
  -> 0 and em dashes 0 -> 144 on production. Web `a86eb4ed`.
- **NCAAF kickoffs file on their CENTRAL day. `[measured 08-15]`** 28 of 157
  real 2026 kickoffs were previously filed under their UTC day; production's
  week-1 betting card no longer carries a spurious "Sunday, August 30" group.
  The platform's display timezone is Central everywhere — confirmed by the
  user this session, and now true of `ncaaf/betting_card.py` as well.
- **NOT FIXED, and it is upstream of every consumer-side guard:**
  `scripts/refresh_nba_oddsapi_props.py` and
  `scripts/refresh_wnba_oddsapi_props.py` carry ~10 sites EACH of
  `... or 0.5` on probabilities that feed EV and edge arithmetic. A literal
  0.5 from a producer cannot be told from a real one downstream. Handed to
  `recommendation-lane-correctness`. `[measured 08-15, from-code]`

- **Published prop/pick probabilities no longer fall back to 0.5 IN CODE, and
  the change is NOT yet on any worker. `[measured 08-15, local artifacts +
  from-code]`** `bd40056c` / `origin/main` `536dfcd0`. Local sizing: 6 of
  4,240 probability rows were price-missing and every one carried a
  fabricated 0.5; 67 further exact-0.5 rows have real -100/+100 prices and are
  legitimate. Production rate unmeasured. **Until a worker deploy carries it,
  production still fabricates.**

- **`origin/main` is `be5efcbf` and the shared tree has ZERO commits not
  upstream. `[measured 08-15 ~02:0xZ]`** Second reconciliation of the day:
  origin was 127 ahead / tree 14 ahead, 9 of them unpushed, all belonging to
  the `#435` watchdog and `#387` memory-cutover lanes — including code already
  live on refresh-worker. **This one was NOT a repeat of the first:** both
  sides had real work in `memory_observability.py` and `run_refresh_worker.py`
  (tree = `#435` watchdog, origin = `#423` tracemalloc/malloc_info, confirmed
  absent from the tree by patch-id), so taking either side wholesale would
  have silently dropped a lane. Git 3-way merged both files cleanly and the
  result was verified BY CONTENT — `tracemalloc`/`malloc_info` and
  `MEMORY_WATCHDOG`/`watchdog` markers all present, and the single line
  differing from origin read individually (a relocated `CONTAINER_MEMORY`
  print, reappearing in the wrapper `#435` split out).
- **The tree is now only BEHIND (128), never ahead.** Being behind is a
  read-your-own-staleness problem; being ahead is a lost-work problem. Only
  the second one strands anything.


---

# APPENDIX — content that existed ONLY in `origin/main`'s copy

The body above was captured from the SHARED WORKTREE, which is what every
session was actually reading. `origin/main` carried further lines the
worktree's copy did not, found by diffing the two before the collapse was
committed. All of it is superseded — a 2026-08-14 21:30Z handoff that the
00:36Z handoff explicitly replaces, and two 08-13 deployed-SHA blocks that
later readings overwrote. It is reproduced here so this archive is complete
against BOTH copies and nobody has to rediscover the divergence.

```
## >>> START HERE — HANDOFF FOR THE NEXT SESSION (2026-08-14 ~21:30Z) <<<
**`docs/ai_context/handoff_tier0_and_board_engine.md`** — self-contained, written
for a cold start. Then `.syndicate/plan_2026-08-14_program.md` for sequencing.
**Single next action: ship `086702ae` (branch `memory/overview-sum-to-max`).**
refresh-worker OOM-killed at 20:03:11Z and nothing is deployed to stop the next
one. A 522MB worker died in 25s inside one 8-sport hydrated pass. Gate: 223
passed, the one failure proven pre-existing. There is no idle window — poll the
deploy gate every 10s and fire the POST in the same step as the CLEAR.
Deployed and verified: `530fc5d8` only. Held on branches: `086702ae` (memory),
`9ec20a06` (odds cadence — needs `soccer-odds-coverage` sign-off and an OddsAPI
spend call). Local only: `0ddecded`.
## SESSION / LANE CENSUS `[measured 08-14 20:4xZ]`
  **SUPERSEDED AGAIN 08-14 21:0xZ — refresh-worker moved THREE more times.**
- Repo tip: local `main` `5cdf45b6`, **20 ahead / 6 behind `origin/main`**
  (`571f774b`). The two have diverged. **The `session-start.sh` clause here is
  now stale** — that file was committed in `0634e7bb` and the worktree is clean
  of it; it blocks nothing. What a push DOES carry is 3 unpushed `render.yaml`
  commits (`d16950b9`, `1e09fa9b`, `7c60d0f8`), which fire `blueprint_sync`.
  `git push` from this checkout is not scoped to your own commits — read
  `git log origin/main..HEAD` first. Hook work was landed by cherry-picking
  onto `origin/main` in a throwaway worktree to avoid carrying them
  (`f6fec4f1`). Supersedes the `478edd78` line. `[from-git 08-13 14:5x]`
- Deployed SHA: **three different commits, none of them the repo tip.**
  refresh-worker re-read at 08-13 **13:05** CDT; the other two at **11:56**.
  All `status=live`, `trigger=api`. `[measured 08-13]`
  - `syndicate` (web) — `936e2b47`, live since **08-12 21:44 CDT**.
  - `refresh-worker` — **`03073270`**, live since **08-13 13:05 CDT**
    (deploy `dep-d9v0b8bncjis73an78hg`). Carries the `#417`/`#387` memory
    guard fix. Supersedes `448e1816`.
  - `live-odds-worker` — `95effcfa`, live since **08-13 11:36 CDT**.
```
