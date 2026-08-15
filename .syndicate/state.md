# Syndicate — Verified System State

> **Overwrite lines here as facts change. Do not stack contradictions.**
> Every line carries an evidence tag and a date. Untagged lines are invalid.
>
> **COLLAPSED 2026-08-15 (2026-08-14 ~22:0x CDT), 120.8 KB → this.** The file
> had 51 sections and was stacking rather than overwriting — `#387` appeared in
> six with contradictory statuses. **Nothing was deleted:** the complete
> pre-collapse file is `.syndicate/state_archive_2026-08-15.md`. Grep it before
> concluding a fact was never measured; never cite it as current.
>
> **The rule that keeps this file useful:** when you learn something here is
> wrong, EDIT THE LINE. Do not append a newer section that contradicts it. The
> reasoning trail belongs in `deploys.md` (append-only measurement log), not here.

## HOW TO USE THIS FILE

Facts only, grouped by subject. If a subject has an owning lane, it is named.
`lanes.md` says who holds what; `learnings.md` carries the rules; `deploys.md`
carries every measurement with its working. Program sequencing is
`.syndicate/plan_2026-08-14_program.md`.

---

## LIVE SESSIONS AND LANES `[measured 2026-08-15 02:3xZ / 21:3x CDT]`

**Seven sessions are live in one shared worktree.** Census taken with
`list_sessions include_archived: true` — the default call HIDES archived
sessions, so "ended" and "never existed" look identical.

| session | plan / lane |
|---|---|
| Ship refresh-worker branch | program Tier 0/4 — `#435` OOM, `memory-watchdog-435`, `mlb-hydration-oom-435`, `mlb-oom-outlier-2003z` |
| Orphaned lanes cleanup | ledger hygiene + `ask-headline-from-board` |
| Audit 2026-08-14 models (fork) | model plan A–D — `recommendation-lane-correctness`, `clv-without-settlement` |
| UI plan Lane G | UI plan G (soccer card) + H (probe harness) |
| Ask deterministic coverage | ask plan K2/K3/K4/K5/K6/K9/K11 |
| Tier 3a probability substrate | program Tier 3a differential test |
| Tier 5 pre-work | program Tier 5 — the 16 `live`-named modules |
| Build the soccer model | `soccer-model-coverage` |

**`.current-lane` CANNOT REPRESENT PARALLEL SESSIONS — this is the root cause of
lane thrash.** One single-valued file, N sessions. `lane-guard` compares a slug
against it, so whichever session wrote last is the only one whose own edits are
permitted; every other session is blocked from ITS OWN lane. `[measured 08-13]`

**Commit through an ISOLATED index (`GIT_INDEX_FILE`), never `git add -A`, and
always `git diff --cached --stat` first.** A parallel session cleared the shared
index between one lane's `git add` and its `git diff --cached`. A complete revert
of shipped work once sat staged in the shared index with the working tree clean —
a bare `git commit` would have un-shipped it without touching a file.
**That specific revert is DISARMED** (`git diff --cached` empty, `HEAD`
`bd40056c`) `[measured 08-15 02:3xZ]`, but the mechanism is live.

---

## USER DECISIONS `[2026-08-14 ~21:5x CDT]`

Product decisions, not engineering ones. Do not re-take them.

1. **The LLM is NOT meant to be on.** `ANTHROPIC_API_KEY` stays absent. The
   deterministic snapshot path IS the product, not a degrade. Ask Lane N is VOID.
2. **CLV opening capture → (a):** record a compact opening snapshot going
   forward. **(b) REJECTED** — do not raise the 256 MB
   `SKIP_OVERSIZED_LEDGER_CHUNK` ceiling. **First real CLV number is ~24h out.**
3. **Soccer → BUILD THE MODEL.** Not "hide the EV", not "accept ~0 rows". A3's
   uninformative-EV rule stays as it is; the ~0-row state is the accepted
   INTERIM, not the destination.
4. **Layer 1 stays** — it is the known universe and the user's research surface.
   Layer 2 is the curation and the product core.

**Still owed by the user:** is the product pregame-first, or does live game-line
projection get built (program Tier 5)? And is a sharp reference price obtainable
(model Lane C)?

---

## DEPLOY DISCIPLINE — read before any deploy

- **`autoDeploy = no` on all three services, so pushing `.py` ships nothing.
  Pushing `render.yaml` DOES apply to production** via `blueprint_sync`, which
  bypasses it. A sync **upserts declared keys and leaves live-only keys alone**
  — it does NOT replace the whole block, so removing a declaration never removes
  the live value. `[measured — scripts/audit_blueprint_drift.py header]`
- **Deploys go by explicit `commitId`.** Both services are `branch=main,
  autoDeploy=no` yet run off-branch commits, so a deploy needs no service-config
  change and touches no `render.yaml`. `[measured 08-14]`
- **Cut every deploy branch from the TARGET SERVICE's own live SHA** and check
  `git merge-base --is-ancestor` both ways. The services sit on divergent lines;
  a branch cut for web has been a **rollback** for refresh-worker. `[measured 08-14]`
- **Deployed SHAs move constantly** — five times in one evening, twice inside 25
  minutes. Re-read per service inside the step that uses one; never carry one
  across turns. A stale read nearly shipped a rollback. `[measured 08-14]`
- **A fired deploy is not a landed deploy.** Check `status=live` AND the commit,
  never the 201. One deploy sat `build_in_progress` for 33+ minutes while being
  reported as shipped. `[measured 08-13]`
- **Deploy races are real.** A deploy was CANCELED because another session
  triggered one 1 second earlier — Render cancels an in-flight deploy when a new
  one starts. Check for an in-flight deploy and HOLD. `[measured 08-15 00:08Z]`
- **A deploy kills an in-flight MLB sim, and there is no idle window** — MLB sims
  run near-continuously with ~60–90s lulls. **Method that worked 3/3 with ZERO
  jobs killed:** poll `deploy_preflight.py` every 10–12s, require TWO consecutive
  CLEARs, fire in the next step. ~30 min of HOLD is normal. `[measured 08-14]`
- **Every refresh-worker deploy resets every session's measurement window.** One
  3h window was lost to this. With many sessions shipping, prefer a train: name
  your commits and **the ONE metric that is yours**, then a 30-minute
  measurement freeze. Batching is safe only when no two riders can move the same
  metric. `[policy, 08-14]`
- **A closed lane is an ACTIVE LOCK, not a stale note.** Close the lane when the
  measurement lands. `[measured 08-14]`
- **`git push` from this checkout is not scoped to your own commits.** Read
  `git log origin/main..HEAD` first. `[from-git 08-13]`

**Repo state `[measured 08-15 02:3xZ]`:** `origin/main` is `be5efcbf`; the shared
tree has **ZERO commits not upstream** and is **128 BEHIND**. Being behind is a
read-your-own-staleness problem; being ahead is a lost-work problem. Anyone
reading local `git log` for lineage is reading a stale tree — `git fetch` and
read `origin/main`.

---

## MEMORY — refresh-worker `#435` / `#423`, OPEN

**Owner: session "Ship refresh-worker branch". Nobody else touches
refresh-worker memory, `pipeline/intelligence_state.py`, or the board-build loop.**

- **`#387` FIXED BOARD COVERAGE. IT DID NOT FIX THE OOM.** refresh-worker was
  OOM-killed **16 times on 2026-08-14**, the last 26 minutes after both halves
  were live. Source: `/v1/services/<id>/events`, **NOT the logs** — a killed
  process cannot log its own death, so a log grep for `oomKilled` is worthless
  for this question and produced a retracted "0 kills" claim. `[measured 08-15]`
- **`#387` shipped in TWO halves** — `cfee9c6e` (streaming cutover) +
  `705eeefc` (the guard's floor becomes two floors). Without the second, the
  first truncated the board to ONE sport for 80 minutes. Verified on
  `098877e1`: `BOARD_OVERVIEW_READY sports=8` on 1 build against **5 consecutive
  `sports=1`** before; `OVERVIEW_STOPPED_FOR_MEMORY` 0; peak anon 1404.5 MB =
  34.3% of ceiling. **One post-fix build is a result, not yet a rate.** `[measured 08-15 00:28Z]`
- **THE KILL IS MLB GAME HYDRATION, NOT THE OVERVIEW.** At 00:41:16 the main
  worker went 1612 MB → 3079 MB in 28s with children small and payloads tagged
  `game_count: 15`. At the canonical 20:03:11 kill the container was at 28.8%
  twelve seconds prior, `stage=post_build_overview` — the overview had already
  finished. The real work is `build_cards_page_context` running HYDRATED on the
  worker. `[measured 08-15]`
- **Leave the 3000 MB floor in front of MLB alone.** It guards the wrong stage,
  but lowering it only admits more work to a process dying elsewhere.
- **THE 20:03:11Z KILL IS UNEXPLAINED** and the diagnosis that explained it is
  FALSIFIED: "eight hydrated sports cannot fit in 4 GiB" — the same 8-sport pass
  ran twice that evening at 613 MB and 804 MB. Streaming caps the transient; it
  did not explain the outlier. `[learnings.md 08-15 EXONERATED]`
- **GOAL #1 HAS TWO QUANTITIES; do not trade them off.** **PEAK** (acute) is what
  crosses the 4 GiB ceiling — a ~1873 MB excursion, cause named and now
  streamed. **FLOOR** (chronic, ~1400–2000 MB `anon`) is UNNAMED; reducing it
  buys headroom but is not what kills the process.
- **`#423` — the leak is NOT glibc arena fragmentation.** Ten readings at `anon`
  ~2031 MB: arena coverage 11.0–24.4%, `system_current` **plateaus at ~393 MB
  while `anon` climbs**. **Stop tuning the allocator.** Both flushes are already
  deployed and measured; `malloc_trim` returns 0.0–2.9 MB at guard time, so the
  residual is live objects, not free-but-unreturned. **Do not propose "add a
  flush".** `[measured 08-14 02:18Z]`
- **It is not in GC-tracked Python objects either** — `HEAP_CENSUS` at
  `container_mb 2150` counts 325,653 gc-tracked objects; millions would be
  needed. Remaining hypothesis, NOT a finding: large allocations neither
  gc-tracked nor in glibc arenas (NumPy/Monte Carlo buffers). `[measured 08-14]`
- **`tracemalloc` made production MEASURABLY WORSE and is OFF
  (`SYNDICATE_TRACEMALLOC_DIAG=0`).** With tracing on, the sampler emitted
  **zero** samples and kill cadence went 16–22 min → 3–10 min:
  `take_snapshot()` walks every live traced allocation holding the GIL and
  blocked the sampler thread. Production was also tracing at **nframe=1**, which
  names `decoder.py` — the allocator, not the caller — so even a successful dump
  would have produced a known-worthless answer. `[measured 08-15 02:1xZ]`
- **`#253`'s worker cache bound was applied to MLB ONLY.** NBA/WNBA/soccer have
  no worker variant (`= 32` unconditional) and the 32-entry limit is never
  reached, so **every context built is retained for the life of the process**.
  Magnitude NOT established — those sports are out of season or small. Do not
  quote it as MB until somebody sizes a context. `[measured 08-14 18:5xZ]`
- **The MLB cards-context cache EARNS its retention — 22.9% hit rate. Do not
  zero it.** The "mathematically zero hit rate, safe to zero" claim is retracted
  at source. `[measured 08-14]`
- **Instrument gap:** `_log_cards_context_memory` exists ONLY in MLB's cards
  module. Zero `[wnba_cards]` lines is a fact about the emitter, not the cache.

---

## BOARD FRESHNESS AND STALENESS

**THE BOARD HAS TWO INDEPENDENT CAUSES, and fixing one is not enough.**

- **Cause 1 — refusal rate.** 96.7% of board cycles were refused before any work:
  146 `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` against 5 completed
  builds. **The guard doing the refusing protects a stage Layer 2 never runs**
  (`_MIN_SAFE_MEMORY_HEADROOM_BYTES`, sized for `build_intelligence_overview`).
  Production's own proof they are independent: on 3 of 5 builds
  `CANDIDATE_POOL_READY count=0` while `LAYER2_SHORTLIST` returned `rows=256` on
  the SAME cycle. `[measured 08-14 14:39Z]`
- **`#387`'s Layer 2 fix is CLOSED-VERIFIED on a full 3h clean window** —
  37 refreshes = 11.9/hour vs 1.7 baseline, longest gap 11.8 min vs 104.7,
  96 `MEMORY_GUARD_ABORT` (so not a boot-confounded quiet period),
  `LAYER2_GUARD_SKIP` 0, zero OOM. All five criteria met. Residual confound
  stated: abort rate 30.8/h vs 48.7/h baseline. `[measured 08-14 19:24Z]`
- **Cause 2 — THE QUOTE INPUT IS NOT MOVING.** A shortlist rebuilt every 5
  minutes off a 2-hour-old quote shard is a board that LOOKS fresh and is not —
  **strictly worse than one that is visibly stale, because nothing on it says
  so.** Rebuilding more often cannot fix this. `[measured 08-14 15:1xZ]`
- **Layer 1 is dark on ~3 of 5 builds** (`count=0`). On the stated hierarchy that
  is an outage on the research surface, not a deletion argument. Program Tier 4.
- **The candidate-pool path serves NEITHER board** and is the real deletion
  candidate. Layer 1 and Layer 2 are **siblings off the shared grid**, not
  sequential — which is the mechanism by which L1 can fail without L2 noticing.

---

## ODDS CADENCE AND CAPTURE

- **MLB quote capture never stopped. It runs on a metronomic ~121.6-minute
  beat** — seven captures in 18h, read from the artifact's full distribution via
  `/api/ops/artifacts/stream`, not from logs. `[measured 08-14 16:3xZ]`
- **WHY 60s BECOMES ~7,300s, two multipliers, both measured `[08-14 17:0xZ]`:**
  1. `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS=60` is the TICK interval,
     never the launch interval.
  2. **The pregame relaunch cooldown is 1800s and GLOBAL** —
     `_pregame_relaunch_blocked` reads ONE marker keyed by **date only, not by
     sport and not by service**, so a launch for ANY sport starts the clock for
     EVERY sport. 30×.
  3. **Sports rotate across launches**, so MLB rides roughly 1 in 4. ~4×.
  **The leverage is a design fact, not a tuning value: because the cooldown is
  global, every sport added dilutes every other sport's cadence.** A per-sport
  cooldown decouples them; that is the change worth considering, not lowering 1800.
- **The driver is `refresh-worker`'s `live_refresh_loop`, not live-odds-worker** —
  the service named for odds carries `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`.
  Loop ownership is an env flag that moves with no diff. `[measured 08-14]`
- **This is the real cause of "candidates that are no longer bettable"** — the
  board's MLB prices are up to ~2 hours old by construction.
- **Consequence for the whole movement family:** 23 movement implementations,
  `movement_velocity` and the steam detector are computing on a signal sampled
  roughly every two hours. Nothing there should be trusted or extended until the
  real sampling interval is known.
- **A `too_large` line does NOT mean the artifact failed to publish.** The
  ceiling lives in `_publish_skip_reason`, which is **sweep-only**; the direct
  path streams and never consults it. Verified byte-identical on web. Four
  sessions have now misread this. `[measured 08-14 16:2xZ]`

### OddsAPI budget `[measured 08-14 17:2xZ]`

- **Projected 30-day burn 4,640,809 credits = 92.8% of the 5M cap.** Headroom
  ~360k/month. MLB is **93.7%** of spend (8.72 cr/call); soccer 4.2% (1.46
  cr/call, 6× cheaper); nfl 1.4%; wnba 0.7%. Live hours dominate (83–228k/hr)
  against pregame's 10–18k/hr.
- MLB pregame sweep interval is 3600s with an effective gap of **~1h10m**
  (7,289s → 4,215s). The loop wakes every 900s and sweeps whatever is past its
  interval, so the setting is a FLOOR the tick quantises.
- **Any cadence increase spends against the cap — it is a product decision, not
  a tuning tweak.**

---

## THE PUBLISHED SHORTLIST — edges, EV, CLV

**Owner: `recommendation-lane-correctness` (model-audit session).**

- **The audit's "0.5 coin-flip default" was BACKWARDS as a production
  mechanism.** `_fair_probability`'s `0.5` terminal is UNREACHABLE: every
  `filter_candidates` call site is fed `_score_candidates` output, so `score/100`
  always won first (score 4.05 → fair 0.0405 → edge −0.36). Model-free
  candidates were not published as coin flips — they were **silently REJECTED**
  under `reason: "edge_below_threshold"`, a reason claiming an edge had been
  measured when no model had run. **Removing only the `0.5` would have been an
  inert fix.** `[measured + from-code 08-14]`
- **A1's exclusion IS INERT in production** — `FILTER_CANDIDATES sport=all
  in=476 out=377 rejected={"edge_below_threshold": 99}`, with
  `no_model_probability` absent (0 of 476). What changed is that the 99
  rejections are now honest. **Do not credit A1 with an effect it does not have.**
  `[measured 08-15 23:01:39Z]`
- **A3 is SHIPPED AND VERIFIED** (web `ea1d2ed6` + refresh-worker `29ed6de1`).
  Five predictions written BEFORE the deploy all held: `rows_uninformative_ev`
  null → 4003, soccer selected 100 → 0, `total_rows` 256 → 156 (exactly 256−100),
  `book_margin_model` served rows 100 → 0, and **the control mlb 84 / nfl 60 /
  wnba 12 unchanged to the row.** `[measured 08-14 19:58Z]`
- **Why the control held is a mechanism, not a coincidence:** MLB carries 357
  one-sided rows with a modelled fair, so the rule CAN reach it — it held because
  mlb has `rows_with_model_edge = 2256` and the rule keeps any row carrying a
  model view. **The narrowness clause is what protects MLB.** A later mlb 84 → 78
  is 1.4h of SLATE DRIFT, not the rule. `[measured 08-14 21:2xZ]`
- **Ranked #3 + #4 are LIVE (`79148d8e`), P1 VERIFIED ONLY.**
  `recommendation_count` 145 → 148 on a post-deploy cycle; the lane did not
  empty, which was the revert trigger. **P3 UNMEASURED** — getting a
  `FILTER_CANDIDATES` line is the only thing blocking closure, and the instrument
  is already live. Poll **narrow** (~90s) Render log windows; a wide window
  saturates at the 100-line cap and returns the TAIL, so a zero means nothing.
- **A3a score monotonicity is COMMITTED AND DELIBERATELY NOT DEPLOYED**
  (`28291eb6`; corr(reliability, score) = −0.8312 on 156 negative-value rows vs
  +0.8560 control). **Do not deploy without a pool-side counter** — its effect is
  on SELECTION and is invisible in a shortlist that returns survivors only.
- **CLV: the opening half is recorded; THERE IS STILL NO VALID CLV NUMBER.**
  Recorder live (`2b14fbeb`), 584 bytes/record vs the evaluation chunk ledger's
  40,555; `book_prices` on 150/150 served rows. **`avg_clv_pct` is None and that
  is the honest answer.** An early `-5.215` was RETRACTED — the line was never
  checked (`home -5.0` vs a `home -1.5` close) and **25 of 25 closes PRECEDED
  their openings**. All three now refused by name (`line_mismatch`,
  `line_unverifiable`, `close_precedes_open`). `close_precedes_open` is a
  PRODUCTION condition. The joiner is library-only, no call site, NOT deployed.
- **The recommendation lane does not price the shortlist.** Every published row
  carries `quote.fair_method` = `consensus` or `book_margin_model`. Fixes to
  `recommendation_engine` should NOT be expected to move the shortlist.
- **Per program Tier 1, stamp fetch cadence / quote age on every CLV record**
  alongside the pricing-version stamp — an "opening" price can be up to two
  hours off the real open.

---

## MODEL SKILL (`#428`) — measured vs not

- **`#428` IS FOUR MODELS, NOT SIX.** `live_projection_join` is a JOIN and
  `game_board_contract` is a passthrough; neither is backtestable. Real targets:
  `soccer_projections`, `wnba_game_projections`, `wnba_projections`,
  `prop_projections`. `[from-code 08-14]`
- **MLB hitter props are MEASURED: BIASED, NOT BLIND.** 2,487 player-games,
  joined on `batter_id` (an exact join). Every counting market carries real
  signal AND loses to a constant baseline by sitting too high; de-biasing flips
  5 of 7 to beating it. `hits` r=0.16 +28.6%, `tb` r=0.15 +17.7%, `rbi` r=0.13
  +30.5%, `runs` r=0.16 +25.9%. `[measured 08-14]`
- **TWO stacked causes; a playing-time fix ALONE will not fix it.** `pa_mean`
  +18.4%, `ab_mean` +17.2%; per-PA rates still +12.2% after normalising.
  Opportunity explains **55%** of the count bias. Fix opportunity first, then
  RE-MEASURE. `[measured 08-14]`
- **"No measured skill" would have been the WRONG conclusion** and would have
  suppressed a model that needs calibrating rather than retiring. **Always
  decompose bias before publishing a skill verdict.**
- **SHIPPED:** refresh-worker `9972977f` / `098877e1` serves 24 MLB prop rows
  carrying `model_skill` with correlation and verdict. `batter_hits_runs_rbis`
  correctly stays `unmeasured` — it must not inherit a neighbour's number.
  Label-only: no projection, mean or edge changed. `[measured 08-15 00:35Z]`
- **`#425` skill declaration is LIVE on both services** — every projection
  carries `model_skill`, `unmeasured` is first-class: `nfl 20 measured`, **mlb
  1631 / wnba 209 / soccer 12 unmeasured**. Counts surface in the `projections`
  coverage block, **not** in `counts`. `[measured 08-14]`
- **`#425` degeneracy detection is LIVE and VERIFIED** — reports any
  `(kind, market, segment)` collapsed to one value across ≥4 distinct GAMES, all
  sports. It found a real defect unprompted on its first live board.
- **WNBA game lines: NOT MEASURABLE YET, nothing broken.** `pred_margin` starts
  2026-08-02; 9 of 361 completed games carry one; n=30 due ~2026-08-26.
- **PRODUCTION HAS FAR MORE HISTORY THAN THE CHECKOUT** — 81 WNBA dates vs "4
  files" locally, and the local files are 7-column stubs with no projection
  column. **Never scope a backtest from the checkout.** `[measured 08-14]`
- **Freeze breadth:** 69 sport × market pairs ship predictions; 2 have a
  backtest. No new pair ships without archive-replay coverage. `[policy]`

---

## SOCCER

**Owner: `soccer-model-coverage` (new) for the model; UI Lane G for the card.**

- **Soccer serves ZERO shortlist rows and that is the INTENDED interim state,
  not an outage.** Its whole presence was one-book longshot props whose `ev_pct`
  was arithmetically `-assumed_hold_pct`. **Read `rows_uninformative_ev` before
  diagnosing soccer as broken** — soccer is ABSENT from `per_sport` rather than
  present at 0.
- **The A3 filter SELF-HEALS.** It keys on `fair_method`, so if soccer ever gets
  two-sided quotes the fair becomes `consensus` and the rows return with a real
  EV — no code change. `[from-code 08-14]`
- **Two endpoints disagree about projection coverage by 250×, same sport, same
  date, 45 seconds apart `[measured 08-14 19:1xZ]`:**
  `/api/board/layer1?sport=soccer` → 8,456 rows, 2,504 projected = **29.6%**;
  `/api/board/layer2-shortlist` → 8,512 rows, 12 projected = **0.1%**, with
  `rows_with_model_edge: 0`, `matches_in_source: 4`, `unmatched_match_rows:
  8,393`. **These are two different joins and at most one describes the board a
  user sees.** Settle this before raising coverage.
- **SOCCER GAME ODDS HAVE NOT BEEN CAPTURED FOR ANY LEAGUE SINCE 08-10/08-11.**
  Eredivisie looked healthy solely because `prop` rows from a different producer
  masked it. **The vendor is NOT the cause** — all ten soccer keys
  `listed=True, active=True`. `[measured 08-14 18:4xZ]`
- **THERE IS EXACTLY ONE PRODUCER and it is not refresh-worker.** `phase=pregame`
  builds 50 steps including 10 odds steps; `phase=live` builds 20 steps and **0
  odds steps** — and refresh-worker's soccer autorun runs `phase="live"`, so it
  never fetches soccer odds at all, by design since `#148`. Everything depends on
  `_launch_autorun_soccer_pregame_refresh` on live-odds-worker, 4h cadence.
  **Single point of failure.** `[measured 08-14 18:5xZ]`
- **WHY the step fails is STILL UNKNOWN.** No error has been observed anywhere.
  **Two hypotheses are DEAD — do not re-run them:** step truncation at #27 of 50
  (falsified by a ~6-step scoped run that captured nothing), and
  three-specific-leagues (all ten are affected). The `#433` step reorder is
  retained on its own merits but **must not be credited with fixing capture**.
- **The run's own logs are UNREADABLE FROM WEB** — `launch_refresh_run` spawns
  the child `stdout=DEVNULL, stderr=DEVNULL` onto the WORKER's disk, and Render's
  collector captures only a service's own stdout. That is the disk split, not an
  absence of logs, and it is how four days of failure produced no visible error.
- **The sim reports its own input is missing:** `SOCCER_PLAYER_ROWS_MISSING` on
  eredivisie, primeira_liga, championship. Observed once while looking at
  something else — **a lead, not a finding.** `[observed 08-14 19:25Z]`
- **Some markets can never carry an edge however good the model gets.**
  `player_shots` / `player_shots_on_target` map to a MEAN and `soccer_projections`
  refuses by design to derive a probability from a mean; the rows are one-sided
  so `_no_vig_over_probability` returns None. `player_to_receive_red_card` and
  `player_assists` are not in the market map at all.
- **MLS cannot be backtested from its current source at all.**
  `fetch_asa_mls_team_history` returns undated **season aggregates**, so a season
  average already contains the whole season and no `as_of` filter can repair it.
  The backtest returns `{}` for MLS with `AS_OF_DROPPED_UNDATED`. `[measured 08-14]`
- **`data/soccer_source/*/validation/*_backtest_*.csv` is NOT CITABLE** (leakage).
  Report soccer backtest accuracy as **unmeasured**. Production is unaffected —
  `build_soccer_artifacts` predicts forward.
- Soccer sims are ENABLED and running; one sim job = one league-date (`#282`).

---

## NFL (`#377`, `#425`, `#429`) — closed, kept because the rules generalise

- **NFL game state is REAL on every surface.** `by_state` went
  `{pregame:6, live:0}` → `{live:5, pregame:1, final:0}` with real scores and
  clocks. **The cause was ONE missing field, not five broken surfaces** —
  `_NFLDataProvider.games()` fed `build_game_chips` cards with no game state, so
  `_game_flags` returned `(False, False)` for every NFL game forever.
- **The board's live/final counts LAG by up to one artifact rebuild (~15 min).**
  Not a defect; a reading that disagrees with ESPN inside that window is expected.
- **`#377`'s constant was a DATA OUTAGE, never a model failure.**
  `load_nfl_game_projections` deduped candidates by NAME across source roots and
  read a copy generated where the nflverse pbp was absent. Now dedupes on
  resolved PATH. `projected` distinct **1 → 6**. **A constant that reproduces
  EXACTLY from an empty input is a data outage, not a weak model — use that test
  before touching any model.**
- **`#429` HRR fixed at BOTH ends.** Read-time derivation (distinct 1 → 85,
  corr 0.9267 against the sim's own probabilities vs a 0.1156 control) and the
  producer (`_inc_sum(pid, "H+R+RBI", hrr)`, both copies). Confirmed in
  production: `derived == 0` with 1008/1008 topn rows carrying a nonzero
  `hrr_mean`. **Discriminator needing no artifact access:**
  `projected_derived_from` is stamped only when the read-time path had to
  reconstruct.
- **An unscoped full-slate MLB sim is a known OOM cause** — the loop batches
  through `--only-game-pks` for that reason. Do not trigger one to force an
  artifact rebuild; read through `/api/ops/artifacts/stream`.
- **`PBP_LOADED` cannot answer "does the worker see the pbp"** — it is emitted
  through a `log()` that writes only to `--progress-log` and never reaches
  Render's collector. A 0 there is a fact about the emitter. Use `artifact_path=`.
- **`PRESEASON_WEEK_LABELS` mapping internal week 2 → "Preseason Week 1" is
  CORRECT.** Internal week 1 is the Hall of Fame game; a session nearly "fixed" it.
- **The MLB sim ledger never records completion** — 34/34 runs read
  `state=running, finished_at=null` while soccer and wnba record `ok`. "Did the
  MLB sim finish" is unanswerable from the ledger. MLB-specific, uninvestigated.
- **The NFL season-projection autorun fires at 21:00Z = 16:00 CDT.** Seven ledger
  lines once carried a UTC timestamp reported as local — a five-hour error.
  **Render logs are UTC; this ledger is CDT.**

---

## UI / BOARD CARDS

- **Lane E is CLOSED-VERIFIED in production** (web `aadcde77`, live 21:42:56Z):
  horizontal overflow 28px desktop / 20–40px mobile → **0 at both widths** on
  nfl, ncaaf, soccer, ncaab; NCAAF default tab 0 panels/187px → 1 panel/556px;
  orphan tabs and unreachable panels → 0; mobile tab targets under 44px 64/48/4
  → 0; numeric classes `normal` → `tabular-nums`. `[measured 08-14 21:4xZ]`
- **Lane F is CLOSED-VERIFIED and live** (web `932a1f71`, then `a86eb4ed`):
  seven fabrication sites in `game_board_contract.py` are gone — an absent
  probability renders as an explicit empty state, a genuine 0.0 survives instead
  of becoming 50/50, and a projected scoreline is never recast as a win split.
  Soccer three-way markets carry a draw segment. One null placeholder (`—`)
  platform-wide: NCAAF hyphen cells 48 → 0, em dashes 0 → 144. `[measured 08-15 01:41Z]`
- **A 50/50 on the board now MEANS 50/50.** The one still served (NFL, DEN@KC)
  sits on a 0.4-point projected margin — the producer's own `home_win_rate`.
- **NCAAF kickoffs file on their CENTRAL day** — 28 of 157 real 2026 kickoffs
  were previously filed under their UTC day. **The platform's display timezone is
  Central everywhere**; `central_today_iso()` is the slate clock. An MLB slate
  spans two UTC dates; it does not span two Central ones.
- **`scripts/ui_layout_probe.py` is the durable instrument.** It reproduced the
  audit's before-numbers against the unchanged service, which is what makes its
  after-numbers a reading rather than a belief. **Synthetic `el.click()` is not
  used anywhere in it — the audit had to retract a finding produced that way.**
- **NBA / NHL / NCAAB serve 0 cards** in production and locally. Their rows in
  the divergence matrix are code-only. **Re-measure in October.**
- **Carried, not fixed:** the desktop strip still breaks long names mid-word in a
  ~52px box — a design decision that CONTRADICTS Lane G1's "raise soccer's 13px
  names to 16px", since 13px + ellipsis is the documented fix for that problem.
- **The prop-producer 0.5 fix is COMMITTED AND NOT ON ANY WORKER**
  (`bd40056c` / origin `536dfcd0`). Local sizing: 6 of 4,240 probability rows
  were price-missing and every one carried a fabricated 0.5; **67 further exact-
  0.5 rows have real ±100 prices and are legitimate** — a blanket "no 0.5
  anywhere" rule would have destroyed real data. Production rate UNMEASURED.
  **Until a worker deploy carries it, production still fabricates.**

---

## ASK THE SYNDICATE

**The LLM is off by decision. The deterministic snapshot path is the product.**

- **Baseline: 23/52** (advice 4/5, entity 2/10, explain 4/6, history 1/5,
  lookup 2/8, ranking 4/10, refusal 6/8), measured 20:45Z, in
  `reports/ask_regression/post_m1_fixed_2026_08_14.json`. `answer_source:
  snapshot` 52/52 is now the EXPECTED source, not a finding.
- **K1 SHIPPED AND VERIFIED** (`bef782cb`, live 20:01:18Z): 20/52 → 23/52,
  `refusal` 3/8 → 6/8, every other class byte-identical, declined-question
  latency 10.9s → 0.19s. **A refusal gate must be tested on what it must NOT
  refuse** — two regressions were caught only by testing the answer direction.
- **M1 SHIPPED** (`b16eb1f7`) but **SUPPLEMENTS rather than REPLACES**: it adds
  `visuals.tables` while `structured_response` survives, so both pools disagree
  (23.81 vs 14.09). Successor lane `ask-headline-from-board`.
- **MLB proves the deterministic path can be genuinely good and seven sports get
  almost none of it** — mlb 4/4 questions producing evidence (14 tables, 4
  charts), ncaaf 2/2, nba 1/1, and **nfl / wnba / soccer / nhl / ncaab 0/9**,
  including with an explicit sport context. Three distinct causes: soccer and
  ncaab have **no branch at all**; NFL's matcher requires the **full** team name
  (`"Patriots vs Seahawks"` → `[]`); wnba/nhl/nba have **entity-only fetchers**
  and a ranking question names no entity. `[measured 08-14]`
- **Chat reads the shortlist ARTIFACT directly**, so chat staleness IS artifact
  age. `[from-code]`
- **The system prompt's rules 5–8 (surface uncertainty, distinguish fact from
  projection, never fabricate, flag staleness) are now PERMANENTLY UNENFORCED.**
  They were the only place those rules existed; the deterministic path needs its
  own. That is a consequence of the decision, not a pre-existing defect.

---

## BOARD / INTELLIGENCE ENGINE — structural facts `[measured 08-14 21:xxZ]`

Read `.syndicate/audit_2026-08-14_board_engine_SYNTHESIS.md` first.

- Board path: **506 files / 238,071 lines**, 43 over 1,000 lines.
- **24 import cycles; 24 hub modules >10 importers** — `rank_board` (29) and
  `game_board_contract` (28). Seven of the cycles are the same shape once per
  sport and one dependency inversion fixes all seven.
- **164 of 390 modules statically unreachable** — **A SHORTLIST, NOT A DELETION
  LIST.** Thread targets and registries are not followed. The env-key twin of
  this list contains `MLB_LIVE_LENS_DIR`, whose only reader is a vendored module
  called at import scope; deleting it would have broken MLB live-lens.
- **42 sites define or convert a probability** (18 prob↔odds, 9
  `implied_probability`, 11 `confidence`, 4 `fair_probability`). Program Tier 3a
  differential-tests the pure ones over one price grid; **any disagreement is a
  live pricing bug.**
- **The "40 sites substituting 0.5" figure is OVER-COUNTED.**
  `(success_rate or 0.5) - 0.5` is a centered prior; `faceoff_win_pct = 0.5` is a
  legitimate sim-contract default; `0.5 * (1.0 + math.erf(...))` is the normal
  CDF. **Triage before enforcing** — indiscriminate enforcement breaks sim engines.
- The **240 bare `except: pass`** are a hygiene backlog, not a board correctness
  finding. Keep them out of the probability invariant.
- **`model_skill` and `min_value_pct` have ZERO defining functions.**
- **19 freshness / 23 market-movement / 18 prob↔odds implementations.**
- **91 of 390 modules branch on liveness; there is no single pregame/live
  boundary** — it is a cross-cutting conditional, not a seam. 16 modules are
  named `live` against **zero live edges ever published**.
- **No live GAME-LINE projection exists.** `predictions.full` is the PREGAME sim
  — all 6 final games carried pregame win probabilities. Only PROPS have a live
  tier, and `rows_live_edged` is 0 on every build to date.
- **Web's `/mlb/api/live-lens` cannot observe the live Monte Carlo**
  (`simContextAvailable: False` on all games). Do not verify live-sim work
  through it.
- **Three of the audit brief's own "known" inputs were wrong** — `static/mlb/board.js`
  does not exist (cited twice), the devig count is not settled at 5, and
  `.claude/worktrees/` holds full repo copies that triple-count any unscoped grep.
  **Spend the first ten minutes of any audit re-verifying the inputs it tells you
  not to re-derive.**

---

## SERVICES, CONFIG, PLATFORM

- Web is **`https://syndicate-an21.onrender.com`** (`srv-d88ahvrbc2fs73eodu30`).
  `syndicate.onrender.com` 404s.
- `refresh-worker` `srv-d91dpertqb8s73co8ls0` (4 GB) — sim/board.
  `live-odds-worker` `srv-d91dpertqb8s73co8lt0` (1 CPU / 2 GB / 50 GB disk) —
  odds. Web (2 GB) — display only.
- **`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `true` on
  refresh-worker ONLY** (`false` on web and live-odds-worker);
  `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS = 60` on all three.
- **Web does not run the loops that call `memory_headroom_snapshot`**, so guard
  changes are inert there — which matters because web is a 2 GB container with an
  OOM history. Re-raise if any flag flips.
- **Both workers publish over the internal hostname**
  (`http://syndicate-an21:10000`), not set on web, correctly. **`syndicate-an21`
  RESOLVES FINE** — the "it names a host that does not exist" claim was an
  inference from Render's naming convention and is FALSIFIED.
- **Keyvalue store is 256 MB, `allkeys-lru`, shared by web + both workers, and
  cannot be upgraded.** `/api/ops/keyvalue/usage` reports allocator bytes;
  deltas are block-quantised. `reports/live_refresh_loop/**` is deliberately
  keyvalue-backed and therefore shared across all three services.
- **Board snapshot and `query_state_cache` are compacted then zlib+base64
  compressed** (31.4 MB → 812 KB). **Any reader must call
  `expand_persisted_state` first** — a raw read returns an envelope that still
  passes `isinstance(dict)`, so it degrades silently rather than raising. This
  has bitten four ops diagnostics.
- **`render.yaml`'s web `envVars:` anchor is never referenced anywhere**, so
  nothing was ever shared and worker-only keys accumulated on web for months.
  Web block cut 62 → 52. Blueprint drift: 0 values a sync would revert — a
  snapshot only.
- **"On origin" is not "in production."** Web's live service carries 73 env vars
  against 52 declared. Read `/v1/services/<id>/env-vars` before recording any
  config change as shipped (paginate — `limit` > 100 returns HTTP 400).
- **Absent ≠ off.** Check the code's default for any key added or removed.
- Artifacts are on **Render persistent disks**, forcing single-instance services
  and stop-then-start deploys with downtime. Cross-disk access is a hard
  requirement; web and worker disks cannot be shared.
- **live-odds-worker disk usage climbing ~20% → ~40% of 50 GB over two weeks.
  Not yet diagnosed.**
- Egress was fixed at root (public → internal publish URL); Aug overage was
  ~2.1 TB against 25 GB included. **Never point a worker publish URL at a public
  hostname.**
- **Odds capture is 65.7% of platform bytes and ~97% MLB** — one day of
  `mlb_source/tracking/book_quotes` is 329.5 MB. It is also the ONLY record of
  line movement. The tradeoff between cutting bytes and keeping movement history
  is mostly false: full-state snapshots at 60s re-record unchanged quotes, so
  delta/columnar storage cuts it by a large multiple while preserving movement.

---

## SESSION HARNESS — what the hooks actually enforce

- **`lane-guard.py` (PreToolUse) enforces.** Blocks `Edit`/`Write` against a file
  claimed by another OPEN lane (exit 2); allows it when `.syndicate/.current-lane`
  names the claiming lane. **With the marker empty it blocks your OWN lane's
  files**, reporting `Current lane: 'none'` — so a session that hand-edits
  `lanes.md` instead of running `/lane` locks itself out.
- **`Bash` bypasses it entirely** — the matcher is
  `Edit|Write|MultiEdit|NotebookEdit`. The guard bounds the file tools, not the
  session.
- **`lane-guard` is blind to `.claude/**` by design**, so the enforcement layer
  cannot protect the directory it lives in — and every real collision has
  happened there.
- **A lane's guard state hangs on ONE header line in a hand-edited shared file,
  and its deletion is silent.** A header once vanished while its body stayed, and
  all 4 of that lane's claimed files went to exit 0. Nothing detected it; it was
  found by reading a diff. Both hooks now take the field between the 1st and 2nd
  em-dash and match the WORD `OPEN` in it.
- **`checkpoint-guard.py`'s witness is this session's OWN transcript;
  `.last-checkpoint`'s mtime is never read.** The marker is repo-global, so its
  mtime answers "did somebody checkpoint", not "did I" — reading it let session
  A's checkpoint silence session B's warning, losing B's work silently.
  `.syndicate/**` is excluded from work-at-risk: it is the persistence, not the
  thing persisted. **Exit 1 on Stop is advisory**, not a gate.
- **The 3-lane cap in policy has no enforcement** — `/lane open` checks file
  collisions only and never counts. Eight lanes are open today.

---

## TEST BASELINES

- **`tests/test_intelligence_state.py` is NOT "224 green" — that line was wrong
  and is corrected here.** It carries **2 pre-existing failures on BOTH sides of
  the reconcile** (`..._fallback_merge_falls_back_on_empty_pool`,
  `..._recomputes_when_cached_snapshot_is_stale`), verified by swapping each
  side's source + test file into one worktree. On the **deployed lineage** it is
  **218 passed / 6 failed** (measured at `2b14fbeb`). **Gate against the lineage
  you are shipping, not against `main`.** `[measured 08-14/15]`
- It costs **~15 minutes**, so it is not a quick check.
- Full suite: **526 passed, 0 failed** after the soccer `as_of` fix `[08-15]`.
- `tests.test_archives` (what CI runs) — 383 pass.

---

## OPEN PROBLEMS

- **The refresh-worker anon floor is UNNAMED** (`#423`). Allocator, GC-tracked
  objects, the board build and the MLB cards cache are all eliminated.
- **The 20:03:11Z OOM is UNEXPLAINED**, and the 3000 MB floor in front of MLB
  stays until it is.
- **Why the soccer pregame odds step fails is UNKNOWN.** No error observed.
- **Something allocates 493–878 MB in-process on refresh-worker and nothing knows
  what** (`#327` residual). Released within ~72s, arriving 11–42 min apart.
  `post_mlb_sim_tick` is a BYSTANDER. **Only counts have been measured, never
  bytes.**
- **`#312`'s `sync: false` protection is on `main` and live on NOTHING**, and the
  `blueprint_sync` mechanism remains untested — the only deploy carrying it was
  cancelled. That is the wrong experiment, not a null result.
- **Chronic instance restarts across the fortnight**, instance count dropping to
  0, pegged CPU. Cause unconfirmed.
- **MLB sim model-side as-of-ness is UNKNOWN.** The backtest is PIT-safe by
  replay, which says nothing about the model's own inputs.
- **NBA / NHL / NCAAB feature point-in-time status UNKNOWN** — no harness reaches
  them.
- **NHL and soccer market anchoring** make those engines' market-relative
  evaluation partly circular. Quantify before believing any CLV number for them.
