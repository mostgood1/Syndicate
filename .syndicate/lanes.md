# Syndicate — Work Lanes

> Lanes are exclusive by file path. Two lanes may not claim the same file.
> Max concurrent OPEN lanes: 3 (see `state.md`).
> Managed by `/lane`. Do not hand-edit while a session is running.

> **History lives in `lanes_history.md`.** This file is read at the start of
> every session, so it carries each lane's CURRENT state plus one prior block --
> **plus any block that declares file claims**, which `lane-guard` reads from
> here and nowhere else. 36 superseded blocks (2,667 lines) were moved out
> verbatim on 2026-08-18. Nothing was summarised or deleted: if a lane's earlier
> reasoning matters, it is there under the same slug.

#### ORPHAN SWEEP 2026-08-18 ~21:4xZ — 8 lanes RELEASED, 32 claims dropped, contested-file invariant CLEARED

**Measured with `lane-guard.py`'s OWN `_claims()`**, not the simplified copy in
`check_lane_invariants.py` — the two disagree, and the difference decides
outcomes. The checker lacks the guard's `_is_disclaimer` / `_claimable_prefix`
handling, so it reported 70 claims / 12 OPEN lanes where the guard actually saw
**102 claims / 17 OPEN lanes**. Read the guard when the question is "is this
file guarded"; the checker answers a different, looser question.

    claims         102 -> 70          OPEN lanes holding claims  17 -> 9
    contested       1  -> 0           (live_gameline_join.py)
    OPEN-under-Archived  15 -> 7

**RELEASED (owner session archived or role retired, verified against the full
roster INCLUDING archived — `include_archived: false` hides exactly the
evidence this question needs):**

| lane | owning session | why released |
|---|---|---|
| `syndicate-coordinator` | `syndicate-coordinator` | role RETIRED by user decision; all 3 "Deploy and Document Coordinator" sessions archived |
| `clv-without-settlement` | `lane-cleanup` | = "Orphaned lanes cleanup", archived 08-16 01:14 |
| `layer2-board-quality` | `layer2-board-quality` | all 3 "Layer 2 board audit" sessions archived; the block itself said claims "can be released on request" |
| `wnba-live-tier` | `layer1-board-coverage` | all 6 "Layer 1 board coverage audit" forks archived — **this is what cleared the contested file** |
| `wnba-phase2-migration` | `layer1-board-coverage` | same family, all archived |
| `modelled-fair-edge` | `layer1-board-coverage` | same family, all archived |
| `odds-cadence-off-the-mlb-peak` | `sim-engine-track` | all 5 "Sim engine scheduling assessment" forks archived |
| `convergence-phase5-profile-seam` | `sim-scheduling` | same family, all archived |

**NOT RELEASED, DELIBERATELY — a live or plausibly-live owner exists.** Releasing
these would un-guard files a running session is editing, which is the exact
failure the lane system exists to prevent:

    basketball-model-owner    "Basketball model deep dive"   RUNNING
    nhl-model-owner           "NHL hockey model deep dive"   RUNNING
    soccer-model-dispersion   "Soccer Session (fork)"        RUNNING
    convergence-phase7-crps   "Modeling Session (fork 2)"    active today 21:40Z
    grading-blocker-settled-zero  "Betting settlement data"  RUNNING — plausible owner by SUBJECT, not by name; the header names `alt-line-shortlist-watch`. UNRESOLVED, left guarded.
    refresh-worker-oom-recurrence "Oom band full report"     flagged running (stale 40h)
    live-edge-basis           `ask-answer-substance`         no roster match; left guarded because it now SOLELY owns `live_gameline_join.py`
    repo-coordination         unmapped                       holds the global `.current-lane`; 9 claims
    ask-sport-coverage        `ask-sport-coverage`           owner family archived, but it sits correctly under `## OPEN` and is the digest's lead lane — flagged, not swept

**THE 7 REMAINING `OPEN`-UNDER-`## Archived lanes` ARE NOT MINE TO FIX.** Every
one belongs to a live or uncertain lane above, and the remedy is to MOVE the
block above the `## Archived lanes` marker — which is editing another lane's
block. Left for each owner. The hazard is real but latent: their claims work
today and would be dropped silently by a future archive pass.

**Method note for the next sweep.** `.syndicate/.current-lane.<uuid>` marker
filenames match archived `sessionId`s exactly (6 of 13 did), so a marker whose
id resolves to an ARCHIVED session is hard evidence the lane is orphaned. The
markers for running sessions did NOT match any roster id, so the mapping proves
death, never life — do not invert it.

## OPEN
### web-oom-arena-trend — OPEN — opened 2026-09-04 — session b2b5b45b-e938-4cb5-81c2-c211ecc7c703
- Goal: answer whether `#632`'s ~173 MB/h is FRAGMENTATION or RETENTION, by
  sampling pymalloc's `arena_mb` against `bytes_in_allocated_blocks_mb` over
  time. Four per-request explanations are already ruled out, and the last ruled
  itself out on the fact that reframes the question: **CPython frees to ARENAS,
  not to the OS**, so "which request freed it" is unanswerable in principle.
- Files: `syndicate/features/shared/memory_observability.py`,
  `tests/test_arena_trend.py` (NEW). Both unclaimed by any other OPEN lane.
- Opened AFTER `web-oom-thread-gating` closed — new work, and reopening a closed
  lane would hide that.
- Hypothesis: `arena_mb` climbs while `bytes_in_allocated_blocks_mb` stays flat,
  i.e. the growth is memory the OS has given us that Python cannot hand back.
- Falsification test: live bytes climb WITH the arenas — then it is genuine
  retention and the fragmentation story is wrong.
- Verification: `arena_trend` present in successive attribution emissions with a
  rising `fragmentation_mb`, or a flat one, over >= 30 min of one process life.
- Blocked by: none.

### web-oom-thread-gating — CLOSED 2026-09-04 — opened 2026-09-04 — **FALSIFICATION TEST ANSWERED, AND THE ANSWER WAS NO.** The gate is correct, tested and **INERT**: neither loop runs on web. Three further candidates were then measured — GC timing EXCLUDED (the sole gen-2-overlapping request read +32.344 MB while the non-overlapping group swung to -30.108 MB) and `LAST_RESULT` EXCLUDED (0.0 MB both halves). **The constraint that ends this line of attack: CPython frees to pymalloc ARENAS, not the OS, so an in-Python free cannot move `Anonymous:` at all** — a negative anon delta requires arena release, which belongs to no statement, request or thread. Rate separately re-measured at **+173 MB/h, down 66%**. NEXT: `malloc_info`/arena counts, not another attribution probe. — session b2b5b45b-e938-4cb5-81c2-c211ecc7c703
- Goal: close `#632`'s LAST contamination source so the attributed SHARE becomes
  recoverable. `inflight` proves no other REQUEST overlapped a window; it says
  nothing about this process's own background loops, and that residue was large
  enough to be the whole answer — one worker attributed **+395.8 MB against
  +225.9 MB of actual growth (175%)**, another 37%, and a route read **-49.46 MB
  across 252 solo requests**.
- Files: `syndicate/features/shared/memory_observability.py` (unclaimed),
  `syndicate/features/shared/live_refresh_loop.py` (unclaimed; the only lane
  naming it is ORPHANED-CLAIMS-RELEASED), `pipeline/intelligence_state.py`
  (**~7776, the board-drain THREAD TARGET only** — `layer2-sim-disagrees` claims
  this file for *"the `confidence` backfill at ~1888 ONLY"*, so the two are
  disjoint by that lane's own stated scope; notice left in their block),
  `tests/test_background_thread_gating.py` (NEW).
- Opened AFTER `web-oom-profiler-steady` closed, because this is new work and
  reopening a closed lane would hide that.
- Hypothesis: excluding background-overlapped windows removes the >100% and the
  negative route totals, leaving an apportionment that can be believed.
- Falsification test: the share stays impossible (>100%, or routes going
  negative) after the gate ships — which would mean a THIRD source, not this one.
- Verification: emissions carrying `skipped_background > 0`, and a late-window
  share inside 0-100% with no negative route totals.
- Blocked by: none.

### open-bet-live-status — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-26 — session syndicate-27 (749848)
- Files: released: `blueprints/intelligence.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  RELEASED `[2026-08-28, session 29794bbe]`: `syndicate/templates/portfolio.html`
  released: `features/shared/execution_limits_settings.py`,
  released: `execution_guard.py`, `venue_balances.py`,
  released: `venue_settlement.py`, `paper_settlement.py`,
  released: ~~`polymarket_board_join.py`~~ **INSTRUMENTATION-ONLY CLAIM TRANSFERRED to
  `venue-refresh-decoupling` `[2026-08-28, session 3e5a9659]`** — an additive
  timing span around `join_polymarket_to_board`, NO behaviour change. Taken
  because this lane's session (`syndicate-27`) is NOT RUNNING (`list_sessions`
  shows every session `isRunning: false`) and the board build cannot attribute
  ~305s of CPU without it. **The SEMANTIC scope of this file stays yours** —
  side resolution, alias matching, the join's correctness. Take it back by
  striking this note.
  released: `scripts/run_live_odds_refresh_worker.py`, + tests.
  RELEASED `[2026-08-28, session d617eefd]`: `blueprints/ops.py`
  RELEASED `[2026-08-28, session d617eefd]`: `team_aliases.py`
  RELEASED `[2026-08-28, session d617eefd]`: `execution_ledger.py`
  RELEASED `[2026-08-28, session d617eefd]`: `polymarket_board_join.py` (its
  SEMANTIC scope; the instrumentation-only transfer struck above stands).
  A marker governs ONLY ITS OWN LINE -- `_claimable_prefix` cuts at the first
  marker and keeps everything before it, so a path that WRAPS onto an unmarked
  continuation line is claimed in full. That is why each path above repeats the
  word rather than sharing one lead-in. All three are now
  held in full by `venue-join-refusal-visibility`, which is fixing the
  Polymarket soccer league-bucketing gap and the ops slate reader that
  disagrees with the join about it. Taken because this lane's session is
  ARCHIVED and not running -- verified in that session, not assumed:
  `list_sessions(include_archived=true)` shows `local_f08f0df5` "Portfolio
  page consolidation", `isArchived: true`, `isRunning: false`, last activity
  2026-08-27T21:51:49Z. Take them back by striking this note.

### convergence-phase7-crps — OPEN, **UNOWNED** `[session abf487e4 ARCHIVED 2026-08-20T21:1xZ]` — **FIVE FINDINGS: FOUR DEFECTS FIXED AND MEASURED, ONE NOT A DEFECT.** Ladder over the 12MB publish ceiling (pitcher strikeouts 0/12 → 18/18 rows with market lines, verified on the served payload); conditional mix never CALLED from the roster build; season-artifact pull matching NOTHING (bare globs vs fnmatch on full paths) — all five inputs now present on the worker. NOT a defect: `vs_pitcher_*` is unfed by `FORWARD_BVP_MATCHUP_MODE=off`, a modelling decision; reclassified as `disabled` so nfail means "wrong". **THE ONE THING OWED: verify on 2026-08-21** — first `sim_input_report_2026-08-21.json` via `/api/ops/artifacts/export?pattern=*sim_input_report*` must show `nfail` **10 → 0**; still 10 on a fresh `generated_at` means the wiring is INERT and this reopens. Claims: NONE held. Still open, deliberately not fixed: ephemeral `vendor/*/data/` statcast caches; BVP left OFF by design. — opened 2026-08-17
- **Files (all NEW — collision-checked 2026-08-17 against all 14 OPEN lane
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: blocks on `origin/main`; zero overlap):**
  released: - `syndicate/features/shared/projection_score.py` (NEW)
  released: - `tests/test_projection_score.py` (NEW)
  released: - `scripts/score_projections.py` (NEW)
- **Blocked by:** none.

### soccer-model-dispersion — OPEN, UNOWNED (session `soccer-sport-owner` checkpointed and released 2026-08-20 ~13:3xZ) — TESTABLE OUTCOME NOT MET; DISPERSION FALSIFIED; DISCRIMINATION CONFIRMED AS THE REMAINING DEFECT; HOME-ADVANTAGE RE-FIT TRIED AND FAILED HELD-OUT VALIDATION
- Files: released: `scripts/backtest_soccer_h2h_calibration.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `scripts/build_soccer_artifacts.py`, `scripts/validate_soccer_vs_market.py`,
  released: `scripts/soccer_sim_input_checklist.py`, `syndicate/features/soccer/` (sim
  released: engine, adapters, ratings, `ingestion/espn_match_stats.py`),
  released: `tests/test_soccer_feature_loaders.py`, `tests/test_soccer_projections.py`,
  released: `tests/test_build_soccer_artifacts.py`, `tests/test_soccer_adapter.py`,
  released: `tests/test_soccer_advanced_input_reachability.py`,
  released: `tests/test_backtest_matches_production_rating_source.py`,
  released: `reports/soccer_backtest/`.
- Blocked by: none.

### wnba-live-odds-capture-gap — OPEN, NARROWED, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — **THE AUTORUN FIRED FOR REAL `[2026-08-21T00:07:24.782Z / 19:07 CT]`, observed by a third party (scheduled task `verify-wnba-live-scale-481`, session `1f76348c`) on IND@DAL. The "never fired" blocker is DISCHARGED. What replaces it: the autorun launches every ~4.3 min and refreshes the LIVE-LENS path, but `book_quotes/<date>.jsonl` advanced ONCE (00:07:49Z) and was still byte-identical 26 min later. The lane's literal testable outcome PASSES, but passing cannot be attributed to the autorun — see FINDINGS.** **ROOT CAUSE FOUND `[00:45Z]`: the autorun is fine; `refresh_wnba_oddsapi_props.py`'s REUSE GUARD sits upstream of it and returns `reused_artifact_bundle` every tick, so the child that appends `book_quotes` never spawns. The guard's staleness bound is the PREGAME sweep interval (2h) and its reuse key carries no phase term, so a 240s live autorun cannot outrun it. THE FIX BELONGS IN THE GUARD, NOT THE AUTORUN.** — opened 2026-08-20 — session 2bffd747-efb5-45d8-b4f3-ae067b645eb7
- Files:
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Blocked by: none.

### soccer-board-mlb-parity — OPEN, UNOWNED (session `f98be73b` checkpointed 2026-08-22 23:2xZ) — **TWO THINGS DEPLOYED TONIGHT. (1) `#518` FOTMOB MOMENTUM — live-odds-worker `94a16efe`, live 22:18:35Z: the event-signal sweep (momentum/xG/shot pressure) was killed by a null control, but a pooled 60-120s model IS real and DIRECTIONAL (which team scores next, dAUC +0.071), driven by FotMob's own momentum series; production's ESPN proxy carries NO signal at any half-life — retired. 5,552-match dataset committed. (2) COMPACT CARD REDESIGN — web `a1dc1e9a`, live 23:08:55Z, VERIFIED ON PRODUCTION HTML: pregame cards show sim-projected totals + BTTS/goals/corners/top-score; final cards RECONCILE those same facts against the real result (19 hit/62 miss on today's slate, spot-checked by hand).** OWED: (a) the FotMob join has never resolved a real fixture — MLS kickoff 2026-08-23T01:30Z is the first test; (b) the live-odds market-pricing pilot sits at 1.46 SE, n=106, needs ~2 more match-days. Full detail: `state.md [soccer-live-momentum]` + `[soccer-compact-cards]`, `log/2026-08-22.md` 22:0x-23:1xZ entries. — opened 2026-08-20 — session f98be73b-b686-42b7-bdf9-248ab97f65b7
- Files: released: `syndicate/features/shared/{board_enrichment,soccer_live_gameline_source,soccer_projections,layer2_board,publication_adapter,live_lens_loop}.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `syndicate/features/soccer/{features/live_lens.py,features/lineups.py,ingestion/fotmob_*.py}`,
  **the soccer cards builder was REMOVED FROM THE BRACE ABOVE
  `[2026-08-28, session 3e5a9659]`** —
  claim transferred to `soccer-overview-cost` for INSTRUMENTATION ONLY (two
  sub-marks inside `_build_cards_page_context_uncached`, no behaviour change,
  released: nothing near the FotMob/live-lens work this lane owns). Taken because this
  lane is UNOWNED — session `f98be73b` checkpointed 2026-08-22 and does not
  appear in `list_sessions` at all. REMOVED rather than struck through, and
  removed from INSIDE the brace: `check_lane_invariants` parses paths
  positionally and a brace expansion is a claim per member. To reclaim, put
  that filename back inside the brace.
  **AND THE FILENAME ITSELF HAD TO GO, not just its position in the brace**
  `[2026-08-29, session 6dc988f8, lane ncaaf-live-lens-state]` — this note
  said the claim was removed while still spelling the bare filename twice
  inside the `- Files:` block, so `_claims()` kept yielding it. `lane-guard`
  released: matches on path SUFFIX (`rel.endswith("/" + f)`, line 420), and a bare
  filename has no directory to disambiguate it, so this UNOWNED soccer lane
  was claiming **every sport's cards builder** — mlb, nba, nfl, ncaaf, wnba.
  It blocked an NCAAF edit on 2026-08-29 while the first game of the season
  was in progress. `check_lane_invariants` did NOT catch it: it checks that
  each claim has exactly one holder, and this claim did. Same basename
  released: collision `state.md` records for `live_lens` across eight sports. **A
  disclaimer next to a path does not unclaim it — only deleting the path
  text does.**
  released: `syndicate/templates/shared/_scoreboard_strip_soccer.html`, `syndicate/static/shared/dense_cards.css`,
  released: `scripts/{build_soccer_artifacts,backtest_soccer_live_totals,poll_soccer_live_state,soccer_*}.py`,
  released: `tests/test_soccer_*`, `tests/test_fotmob_*`.
- Blocked by: none.

### wnba-halftime-elapsed — **OPEN, UNOWNED** `[session 1f76348c ARCHIVED 2026-08-21 ~16:1xZ]` — **ONE READING OWED** — fix is LIVE on web (`2b9040df`, content-verified) and on the workers (`3b41696d` is an ancestor of refresh-worker's SHA). Unit-verified both directions: 3 break tests FAIL pre-fix, 2 narrowness tests PASS in both states. **THE BREAK BEHAVIOUR ITSELF IS UNOBSERVED IN PRODUCTION** — a 20-minute watcher caught no blank-clock state, and the one suggestive reading (a board row at 'End of 1st' keeping a live lane at model 0.2155 vs its 0.27 pregame baseline) was INDIRECT, via the board. Next WNBA break discharges it. — opened 2026-08-20 — session 1f76348c-062d-4075-a54b-a8b0eadabb2b
- Files:
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: - `syndicate/features/wnba/cards.py` — `_wnba_elapsed_minutes` and the
    released: `source`/`markets` fallback that keys off its None.
- Blocked by: none.

### wnba-live-props-data — **OPEN, UNOWNED** `[session 1f76348c 2026-08-21T17:4xZ]` — **PROPS CHAIN BUILT+DEPLOYED (UNPROVEN); `#499` TOTALS PRICING DEPLOYED (UNPROVEN).** Live on BOTH workers at `8d5d6edf` (refresh-worker 16:43:05Z, live-odds-worker 16:48:04Z) — totals scale `3.2` + `ANALYTIC_LIVE_STD_ERR_BY_MARKET {("wnba","totals"): 0.150}` + the fix for it shipping INERT. **TWO READINGS OWED, BOTH BLOCKED ON A LIVE SLATE, BOTH ARMED:** scheduled task `verify-wnba-totals-pricing-499` fires 19:15 CDT 2026-08-21 carrying both. (a) `#499` PASSES only if totals rows refuse as `prob_interval_swamps_edge` (per-row) NOT `analytic_estimator_never_backtested_for_this_market` (category-wide); at sigma=0.150 the bar is ~30pp so **priceable volume is a BUG signal, not success**. (b) `#498` props PASSES only on `WNBA_LIVE_BOX_CAPTURED` with players (live-odds-worker) AND `live_projections.rows_live_projected` > 0. Pre-tip both read 0 — **a zero is indistinguishable from an inert feature**; verifier `scripts/verify_wnba_totals_pricing.py` exits 3 rather than 0 for that reason. DO NOT report either as working. Narrative: `log/2026-08-21.md`. Claims: NONE held. — opened 2026-08-20 — session 1f76348c-062d-4075-a54b-a8b0eadabb2b
- Files:
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: - `scripts/capture_wnba_live_player_box.py` — the capture (new).
- Blocked by: none.

### portfolio-ledger-service-split — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-22 — session 74a0966a-a9fe-57cd-8320-f46f235aeed1
- Files: released: `syndicate/features/prediction_ledger.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `syndicate/features/shared/ledger_bridge.py`,
  RELEASED `[2026-08-24 to exchange-markets-api-integration]`: `scripts/run_refresh_worker.py`
  Reworded 2026-08-28 so the parser can SEE the release this lane already
  recorded in prose; a marker governs what FOLLOWS it on ITS OWN LINE, and the
  old wording put both the strikethrough and the word after the path. Session
  `74a0966a` archived 2026-08-22, `lane-guard` was blocking a narrow,
  released: additive, try/except-wrapped diagnostic hook on the strength of a dead
  session's claim; rest of this lane's file list untouched),
  released: `scripts/backfill_portfolio_settlement.py`,
  released: `tests/test_prediction_ledger_shared_store.py`,
  released: `tests/test_evaluation_settlement_autorun_ordering.py`,
  released: `tests/test_ledger_bridge_identity_join.py`,
  released: `tests/test_backfill_portfolio_settlement.py`
- Blocked by: none.

### render-web-request-path — **OPEN, UNOWNED, CLAIMS RELEASED** `[session 726ef4ff checkpointed and archived 2026-08-22 ~19:4xZ]` — **SHIPPED AND MEASURED; ONE ITEM OWED**
- Blocked by: none.

### portfolio-decision-and-execution — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-22 — session 9324a3e5-364e-5fb4-9b4a-b0568019e37f
- Files:
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `.syndicate/plan_2026-08-22_portfolio_execution.md`,
  released: `syndicate/features/shared/portfolio_settings.py`,
  released: `syndicate/features/shared/portfolio_commit.py`,
  RELEASED `[2026-08-28, session d617eefd]`: `syndicate/features/shared/execution_ledger.py`
  RELEASED `[2026-08-28, session d617eefd]`: `tests/test_execution_ledger.py`
  RELEASED, no longer claimed here: ~~`pipeline/portfolio_commit.py`~~ — a
  full claim is now held by `venue-join-refusal-visibility`
  `[2026-08-28, session d617eefd]`, which is fixing this line's own
  `KALSHI_BOARD_JOIN refusals=None` bug (it reads a key the join does not
  return). The path is struck from this Files list so the machine-readable
  claim agrees with the prose: the lane invariant checker does not read a
  strikethrough, and reported this as CONTESTED for that reason alone. Earlier note,
  still true: **INSTRUMENTATION-ONLY CLAIM TRANSFERRED
  to `venue-refresh-decoupling` `[2026-08-28, session 3e5a9659]`** — a timing
  span around the Polymarket join only, NO behaviour change and nothing near
  `_venue_price_resolver`, which this lane's block names as its own open work.
  Taken because this lane opened 2026-08-22 and its session
  (`9324a3e5`) does not appear in `list_sessions` at all. Take it back by
  striking this note.
  released: `scripts/portfolio_commit_input_checklist.py`,
  RELEASED `[2026-08-28, session 29794bbe]`: `syndicate/blueprints/intelligence.py`
  RELEASED `[2026-08-28, session 29794bbe]`: `syndicate/templates/portfolio.html`
  released: `syndicate/features/shared/opportunity_signals.py`,
  released: `scripts/score_sim_weight_impact.py`,
  released: `tests/test_layer2_blend_admission.py`,
  released: `tests/test_portfolio_settings.py`,
  released: `tests/test_opportunity_signals.py`,
  released: `syndicate/templates/portfolio_paper.html`,
  released: `syndicate/static/shared/paper_portfolio_pulse.js`,
  released: `tests/test_portfolio_paper_page.py`,
  released: `syndicate/features/shared/clv_position_join.py`,
  released: `syndicate/features/shared/position_marks.py`,
  released: `tests/test_clv_position_join.py`,
  released: `tests/test_position_marks.py`
- Blocked by: none for stages A-C.

### kalshi-line-aware-rungs — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — **CLAIMS RELEASED 2026-08-26 03:3xZ, session archived** — BLOCKED ON TWO MEASUREMENTS, do not resume the original goal first — opened 2026-08-25 — session 281da8c3-1df9-5c77-9e34-ee6f15f37b45 (GONE)
- **Files: released:** `tests/test_kalshi_odds_cadence.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `tests/test_kalshi_precap_cut_by_date.py` (NEW),
  released: `syndicate/features/shared/kalshi_board.py`, `tests/test_kalshi_board.py`,
  released: `syndicate/features/shared/kalshi_catalogue.py`,
  released: test_kalshi_side_vocabulary (transferred to
  `live-venue-order-placement` 2026-08-29, `#603`), test_kalshi_futures_eviction.
  Written without `.py` so the guard stops enforcing paths this lane released.

### kalshi-spread-join-sign — **OPEN (reopened 2026-08-26)** — session syndicate-43 (ENDED) — UNOWNED — six things verified; WNBA settlement is BUILT, LANDED and NOT DEPLOYED
- Files: released: `syndicate/features/shared/{kalshi_board_join,kalshi_orders,bet_status_wnba,bet_status_soccer,polymarket_us_orders,board_enrichment}.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `scripts/build_wnba_boxscores.py`,
  released: `syndicate/blueprints/wnba.py` and their tests. **ALL CLAIMS RELEASED.**
- Blocked by: none

### wnba-chip-live-token — OPEN, **UNOWNED** (session 3dcd0fb2-a129-4c6a-95f2-29b11ea0d272 checkpointed and ARCHIVED 2026-08-27) — opened 2026-08-27 — **CLOCK FIXED AND VERIFIED IN PRODUCTION (web `e3dceb68`): `LIVE` -> `Q3 20.5`, control and after on the same game against ESPN. TWO THINGS OWED — refresh-worker is not deployed, and the projection guard is UNIT-TESTED ONLY. `todo.md #586`.** **CHECKPOINT 2026-08-27T01:2xZ: refresh-worker reached `070f452a` and DOES carry the fix; the WNBA half is owed on a MISSING SUBJECT, not a missing deploy — `WNBA live=0` when the artifact landed. Next window TOR @ SEA `02:00Z`. Session archived; lane UNOWNED.**
- Files: released: `tests/test_home_wnba_live_state.py`
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
released: - **`syndicate/blueprints/home.py` IS NOT LISTED ABOVE ON PURPOSE `[2026-08-28,
  session 3e5a9659]`.** Its claim moved to `soccer-overview-cost` for
  INSTRUMENTATION ONLY — per-league timing inside the soccer games loop, no
  released: behaviour change, nothing near the WNBA chip/live-token work this lane owns.
  Taken because this lane is marked UNOWNED (session 3dcd0fb2 checkpointed and
  ARCHIVED 2026-08-27). To reclaim, put the path back on the `- Files:` line.
  **THE PATH IS REMOVED RATHER THAN STRUCK THROUGH** because
  released: `check_lane_invariants.py` parses paths POSITIONALLY and a `~~struck~~` path
  released: is still a live claim — that is a standing rule in `learnings.md` and I broke
  it here first, producing a false contest between two OPEN lanes.
  — RELEASED (see the note below) — `game_chip_scoreboard.py` was ADDED here
  after the first test run, because refusing to SET a fractional score in
  released: `home.py` was not enough: `_side_score` falls through to
  `live_state.<side>_pts` and picks the projection back up.
  — **RELEASED: `syndicate/features/shared/game_chip_scoreboard.py` IS NO
  LONGER LISTED ABOVE, ON PURPOSE `[2026-08-28, session 28195565, user
  authorised]`.** Its claim moved to `mlb-final-zero-placeholder` for the
  0-0 placeholder branch
  inside `build_game_chip` ONLY — the code that runs AFTER `_side_score`
  returns. **`_side_score` and its `live_state.<side>_pts` fallthrough — this
  lane's actual subject — are UNTOUCHED, as is everything WNBA.** Taken because
  this lane is UNOWNED (session 3dcd0fb2 ARCHIVED 2026-08-27) and an MLB
  scoring defect traced to that branch: a 0-0 schedule placeholder on a game
  whose status had advanced to FINAL was passed through as an observed result.
  **THE PATH IS REMOVED RATHER THAN STRUCK THROUGH**, for the same reason the
  released: `home.py` note above gives — a `~~struck~~` path is still a live claim to
  released: both `lane-guard.py` and `check_lane_invariants.py`, which read positionally.
  (Confirmed here: the guard's disclaimer vocabulary is a fixed list —
  `not claimed`, `released`, `held by`, `claimed by`, … — and "TRANSFERRED" is
  not in it, so a prose transfer note alone releases nothing.)
  **CONSEQUENCE, stated plainly: the guard now protects this file for NEITHER
  lane.** There is no way to express a per-branch claim to it. To reclaim, put
  the path back on the `- Files:` line.
- Blocked by: none. `wnba/cards.py` is claimed by `wnba-halftime-elapsed`.

### venue-quote-line-join — OPEN, **UNOWNED** (session 3515d143 archived 2026-08-27 ~21:45Z; ALL CLAIMS RELEASED, worktree clean, nothing uncommitted) — **SIX DEFECTS FIXED AND VERIFIED IN PRODUCTION; ONE CHANGE RECORDED AS UNPROVEN; TWO NAMED AND UNFIXED.** Verified: soccer unmatched **15,348 -> 4,006**, grid stamped **13.1% -> 66%**, prop keys now name their player (was a cross-sport WRONG-PLAYER match), kalshi quotes carry a price at all (`yes_bid` was never persisted) and both legs of a threshold market, NFL nicknames resolve (`clubs_unresolved` 64 -> 0), per-sport trim floor, and the venue poll on its own thread (kalshi ~1,250s -> ~120s, polymarket 428-828s -> ~120s). **UNPROVEN: the demand-weighted trim.** Allocation IS the binding constraint (`matched` tracks mlb slots: 794/27, 1620/208, 1741/218, 1706/221) but today's recovery came from MLB's slate approaching first pitch, NOT from the change -- the trim behind `matched=208` logged `demand=None`. **Its test is tomorrow MORNING CT, sustained; the morning was noisy (146/210/99 against a 5-27 baseline) so one good reading is not evidence.** I recorded 'supply not allocation' and had to RETRACT it -- see `deploys.md` 21:0xZ correction. **UNFIXED: a TOTALS key names no GAME** (672 polymarket soccer quotes -> SIX distinct keys, same class as the player-blind props); and the `842`-row builds match 0 on the COMPLETE set, never confirmed as a benign future-date board. Full narrative: `log/2026-08-27.md`.
- Blocked by: none.

### ncaaf-pace-block — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — NCAAF calibration re-fitted and PROMOTED (15.00% -> 7.24%, impossible drives 159 -> 0); NFL deliberately NOT re-fitted (best as shipped); production read of the profile still owed — opened 2026-08-27 — session de363735
- Files: released: `scripts/build_ncaaf_pace_snapshot.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `syndicate/features/ncaaf/feature_payload.py`,
  released: `syndicate/features/ncaaf/sources.py`,
  released: `tests/test_ncaaf_pace_payload.py`
- Blocked by: none.

### venue-candidate-key-token-guard — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-27 — session 764eca35-178c-4c29-afbd-ec621894aaf1
- Files: (none held)
- Blocked by: none.

### mlb-final-zero-placeholder — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-28 — session 28195565
- Files: NONE — **all claims RELEASED 2026-08-28 at checkpoint.** The code
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: work is landed on `origin/main` (`eca7e81b`, verified ancestor) and the one
  remaining criterion is READ-ONLY production verification, so holding
  released: `game_chip_scoreboard.py` would block other lanes for nothing. Paths are
  named in the commit if this lane needs another code change.
  released: **NOTE for whoever takes `game_chip_scoreboard.py` next:** the guard now
  protects it for NEITHER this lane nor `wnba-chip-live-token` — see the
  release note in that lane's block. Put the path back on a `- Files:` line to
  re-arm it.
- Blocked by: a deploy. Not urgent.

### mlb-resolver-write-side-effect — OPEN, **NARROWED — NOT A LIVE INCIDENT** — opened 2026-08-29 — session 6475567d-f806-45a7-880c-f633718f2411 — **UNOWNED, handed off**
- Files: released: `syndicate/features/mlb/sources.py`,
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `syndicate/features/shared/artifact_publisher.py`. **NOT CLAIMED.**
- Files: **NOT CLAIMED** — this lane is FINDING ONLY and changed nothing. The
  marker is moved to the FRONT of this line `[2026-08-31, lane
  soccer-shot-shrinkage]` so the PARSER agrees with what the lane already said:
  `_claimable_prefix` cuts at the first marker and keeps everything BEFORE it, so
  with the paths written first they were still being enforced as live claims, and
  the two paths it named read as contested against a lane that explicitly
  disclaims them. Nothing is taken from this lane. The paths are deliberately
  NOT repeated here: any path-like token inside a Files block becomes a CLAIM,
  which is the same trap, and writing them again would recreate it.
- Blocked by: none.

### polymarket-yes-leg-binding — OPEN, **UNOWNED** `[session 5611932c ARCHIVED 2026-09-01 ~01:4xZ]` — opened 2026-08-30 — **SHIPPED + DEPLOYED; THE LEG CHOICE IS STILL UNVALIDATED; ONE LIVE-MONEY RISK OPEN AND IT IS NOT MINE TO DEPLOY**
- Files: released: syndicate/features/shared/polymarket_us_orders.py
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: pipeline/execute_portfolio.py
  released: tests/test_polymarket_yes_leg_binding.py
  released: syndicate/features/shared/execution_ledger.py
  released: tests/test_reconcile_not_found_recovery.py
  released: syndicate/features/shared/portfolio_commit.py
  released: tests/test_position_carries_commence_time.py
  released: tests/test_soccer_yes_no_h2h_order.py
  released: pipeline/intelligence_state.py **[2026-08-31 ~19:2xZ — REASSIGNED to lane
  `layer2-cap-raise`, same session. This lane's work in that file is SHIPPED AND
  DEPLOYED; the board-shard rollback fix is a different change in a different
  function and belongs to the sharding lane. Reclaim by striking `released:` if
  this lane needs the file again.]** `[2026-08-31, USER OVERRIDE: "take the override
- Files: released: syndicate/features/shared/polymarket_us_orders.py
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: pipeline/execute_portfolio.py
  released: tests/test_polymarket_yes_leg_binding.py
  released: syndicate/features/shared/execution_ledger.py
  released: tests/test_reconcile_not_found_recovery.py
  released: syndicate/features/shared/portfolio_commit.py
  released: tests/test_position_carries_commence_time.py
  released: tests/test_soccer_yes_no_h2h_order.py
  released: pipeline/intelligence_state.py `[2026-08-31, USER OVERRIDE: "take the override
    and build it now"]` — held by OPEN lane `soccer-overview-cost` (session
    3e5a9659, last checkpoint 08-29, no marker, not in the running list).
    Surfaced to the user BEFORE the override. Narrow scope: only the two board
    functions named `write_layer2_shortlist` and `read_layer2_shortlist`, plus
    the new shard helpers; nothing in the soccer cost path that lane worked on.
    (Reworded 2026-08-31 -- the previous wording carried a slash-separated
    phrase that `lane-guard._claims` parsed as a FILE PATH, so this lane held a
    PHANTOM claim on a path that does not exist. Flagged by session 1c88bcca.)
  released: tests/test_layer2_shard_by_sport.py
  released: syndicate/features/shared/layer2_board.py
  released: tests/test_layer2_model_value_term.py
  released: tests/test_layer2_shard_by_sport.py
  released: syndicate/features/shared/layer2_board.py
  released: tests/test_layer2_model_value_term.py
- Blocked by: none.

### layer1-model-edge-join — OPEN — opened 2026-08-30 — session 1c88bcca-be25-4164-a288-3a27d7e9dd57 — **UNOWNED, session 1c88bcca archived 2026-08-31.** Scorer released to lane `layer2-board-opportunities`, whose change is live and verified. Owed: MLB/WNBA/NCAAF coverage is UNREAD not flat — run `py -3 scripts/measure_model_edge_coverage.py` on the first build with a PREGAME slate.
- Files: released: syndicate/features/shared/board_enrichment.py
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  RELEASED to lane layer2-board-opportunities 2026-08-31: the layer2 board scorer module
  released: syndicate/features/shared/wnba_game_projections.py
  released: syndicate/features/shared/wnba_projections.py
  released: syndicate/features/shared/nfl_game_projections.py
  released: syndicate/features/shared/prop_projections.py
  released: scripts/audit_layer1_completeness.py
  released: tests/test_modelled_fair_edge_reachability.py
  released: tests/test_wnba_game_projections.py tests/test_nfl_game_projections.py
- Files: released: syndicate/features/shared/board_enrichment.py
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  RELEASED to lane layer2-board-opportunities 2026-08-31: the layer2 board scorer module
  released: syndicate/features/shared/wnba_game_projections.py
  released: syndicate/features/shared/wnba_projections.py
  released: syndicate/features/shared/nfl_game_projections.py
  released: syndicate/features/shared/prop_projections.py
  released: scripts/audit_layer1_completeness.py
  released: tests/test_modelled_fair_edge_reachability.py
  released: tests/test_wnba_game_projections.py tests/test_nfl_game_projections.py
- Blocked by: none

### mlb-live-prop-prob-merge — OPEN — opened 2026-08-31 — session 1c88bcca-be25-4164-a288-3a27d7e9dd57 — **UNOWNED, session 1c88bcca archived 2026-08-31.** Fix deployed, unverified. Owed on the first live MLB game: `snapshot_live_prob_seen > 0` and `[live_lens] LIVE_PROB_CARRIED ... carried=N`. Watch for `carried=0` with `mc_rows_with_prob>0` — a key mismatch reads as success.
- Files: released: syndicate/features/mlb/live_lens.py, tests/test_mlb_live_prop_prob_merge.py (new)
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Blocked by: none

### layer2-cap-raise — OPEN, **UNOWNED** `[session 5611932c ARCHIVED 2026-09-01 ~01:4xZ]` — opened 2026-08-31 — **GOAL MET; ALL THREE INCIDENT DEFECTS CLOSED + VERIFIED IN PRODUCTION. ONE THING OWED: the 2000-cap raise is STAGED AND UNVERIFIED.**
- Files: released: `pipeline/intelligence_state.py` **[claim REASSIGNED from `polymarket-yes-leg-binding`, same session]**; Render ENV on refresh-worker via the single-key API — never `render.yaml`. **NOW ALSO CLAIMS CODE:** `pipeline/intelligence_state.py`, `tests/test_layer2_shard_index_stale.py`, `tests/test_layer2_cards_shards.py`, `tests/test_shortlist_persist_ceiling_guard.py` — the last MOVED here from `polymarket-yes-leg-binding`, which had misfiled it. Same session owns both lanes; the file is the layer2 size instrument, not a venue file.
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**

### polymarket-pregame-price-gate — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-31 — session 6475567d-f806-45a7-880c-f633718f2411
- Files: released: tests/test_execute_portfolio.py, tests/test_polymarket_board_join.py
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Blocked by: none

### layer2-accuracy-audit — OPEN, UNOWNED, SESSION ARCHIVED 2026-08-31 ~23:5xZ — **CLAIMS: NONE HELD, all four services free.** Handoff armed: scheduled task `check-mlb-pregame-freeze-611` fires 2026-09-01 08:30 CT (needs a manual Run-now for tool approval). **`#611`'s deployed log line is UNREADABLE — do not plan around it; read the artifact + run history instead.** 7-day board accuracy DELIVERED; MLB game-line join FIXED, DEPLOYED and VERIFIED (`13 -> 0` misses, `(pregame-freeze, 14 games)`, 20:33:17Z) — but it did NOT raise graded rows, which falsified my own causal claim. Two follow-ups opened as `todo #610` (caps: ml 12 candidates -> cap 1) and `todo #611` (prop seal dead since 08-16; cadence is the lead). **ONE THING OWED: `5be4381d` is on main and NOT DEPLOYED** — preflight HOLD, 3 jobs in flight on live-odds-worker. **AT RISK: 18 local commits incl. all ledger writes are NOT on origin/main.** — opened 2026-08-31 — session ef7e22fc-d592-43f7-b326-31ddea9258ef
- Files: released: **CLAIMED 2026-08-31 ~18:3xZ, user asked for the MLB join fix:** `vendor/mlb_bettingv2/tools/eval/build_season_betting_cards_manifest.py` (`_odds_paths` + helpers only), `tests/test_season_betting_cards_odds_paths.py`. **EXTENDED ~18:4xZ, user asked for the backlog regrade:** `scripts/run_refresh_worker.py` (`_mlb_betting_day_backfill_*` only — NOT `_season_projection_should_launch`, which lanes.md flags as contended), `tests/test_refresh_worker.py`. Every OPEN-lane reference to `run_refresh_worker.py` is RELEASED; checked. Checked against every OPEN lane: no lane holds either. Still NOT editing `graded_outcomes.py`, `evaluation_settlement.py`, `layer2_shortlist.py`, `layer2_board.py`, `refresh_mlb_oddsapi.py`.
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Files: released: **CLAIMED 2026-08-31 ~18:3xZ, user asked for the MLB join fix:** `vendor/mlb_bettingv2/tools/eval/build_season_betting_cards_manifest.py` (`_odds_paths` + helpers only), `tests/test_season_betting_cards_odds_paths.py`. **EXTENDED ~18:4xZ, user asked for the backlog regrade:** `scripts/run_refresh_worker.py` (`_mlb_betting_day_backfill_*` only — NOT `_season_projection_should_launch`, which lanes.md flags as contended), `tests/test_refresh_worker.py`. Every OPEN-lane reference to `run_refresh_worker.py` is RELEASED; checked. Checked against every OPEN lane: no lane holds either. Still NOT editing `graded_outcomes.py`, `evaluation_settlement.py`, `layer2_shortlist.py`, `layer2_board.py`, `refresh_mlb_oddsapi.py`.
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Blocked by: none. Adjacent, not conflicting: `ncaaf-settlement-resolver` (764eca35) touches NCAAF settlement — will notify rather than edit.

**FINDINGS 2026-08-31 ~17:5xZ — hypothesis CONFIRMED on all three limbs, and the headline is a different number than the one I went looking for.**

**The measurable answer exists after all, and it is NOT the evaluation ledger.** The paper/live PORTFOLIO book is committed straight off `read_layer2_shortlist` (`pipeline/portfolio_commit.py:357`), so `/api/portfolio/paper?date=` and `/api/portfolio/live` ARE a Layer 2 accuracy surface. 7 days, 2026-08-24..08-30:

### wnba-accuracy-assessment — OPEN, GOAL MET; EXCHANGE PRICES REACH A BOARD (VERIFIED); **NO DEPLOY OWED — that claim was STALE, corrected 2026-09-01**; ONE OWED ITEM DISCHARGED, ONE BOUNDED, ONE BLOCKED UNTIL 2026-09-17 — opened 2026-08-31 — session e542848e-6451-41a1-9e60-fd5a5675665d
- Files (all landed on `origin/main`, nothing held): **ALL RELEASED -- this list is a RECORD of what the lane touched, not a claim; nothing here is held.** `syndicate/features/shared/{live_lens_paths,wnba_card_provenance}.py` NEW, `{live_lens_local,basketball_live_artifacts,artifact_publisher}.py`; `syndicate/features/wnba/{cards,live_lens_daily_accuracy,live_game_accuracy,live_prop_accuracy,live_prop_audit}.py`; `scripts/{build_wnba_recon,verify_wnba_settlement_gate,assess_wnba_accuracy}.py` NEW, `scripts/{run_refresh_worker,refresh_wnba_oddsapi_props}.py`; 6 new test files.
- Blocked by: none. Next: **`#623`** (the 09-17 sprint + pre-registered gates + parked `#614`/`#616` reads) and **`#626`(d)(e)** (reuse-guard/live-capture, klass-hole). **`#622`** owns the ranking-key question — per `#615` T2-1 is ANSWERED (no sim-derived key exists; do NOT keep re-looking at the 656-row sample, ~30 looks are already on record). `scripts/prereg_wnba_favourite_lean.py` is frozen and waiting for the sprint.

### ncaaf-games-cache-refresh — OPEN — opened 2026-09-01 — session b85e895e-dde2-4066-8336-dc6c1d4c3c61 — **DEPLOYED `cc1feccc` to BOTH services (web 21:21:43Z, refresh-worker 21:56:06Z). Web half VERIFIED discriminatingly (200 vs 403 allowlist probe). Producer half LIVE BUT UNPROVEN — the daily gate does not fire until ~00:26Z. Two verifications ARMED as scheduled tasks.**
- Files: syndicate/features/football/sim_engine/smartsim2/historical_truth/ncaaf_historical_loader.py,
  scripts/generate_smartsim2_ncaaf_projections.py,
  syndicate/features/ncaaf/week_state.py (NEW),
  syndicate/features/ncaaf/sources.py,
  released: syndicate/features/shared/artifact_publisher.py (CONTESTED — see below) **[RELEASED 2026-09-02 by lane `soccer-players-csv-allowlist`. This lane's OWN body, three bullets down, already records the edit as "finished and landed" and the file as "claimed by NOBODY and is FREE TO TAKE" under a user override — it only ever registered as a claim because the path sits inside a `Files:` block, which the parser reads as a claim regardless of the prose beside it. Owning session `b85e895e` is absent from the session roster. Nothing else in this lane is touched; its other claims stand.]**,
  tests/test_ncaaf_games_cache_refresh.py (NEW),
  tests/test_ncaaf_week_state.py (NEW),
  tests/test_ncaaf_sp_ratings_cache.py (docstring only: it carried the same
  wrong "weeks 1-6" belief; the real file is weeks 1-13 and 15)
  RECLAIMED from `ncaaf-cfbd-quota-latch` / `ncaaf-no-orders` (both UNOWNED,
  phantom-swept) for the generator; `ncaaf/sources.py` was `released:`.
- Blocked by: none (the contested file needs a decision, not a blocker).

### board-window-floor-raise — CLOSED 2026-09-04 — opened 2026-09-03 — session 3492626c — **GOAL MET, TUNED, AND THE PRE-REGISTERED PREDICTION IS CONFIRMED. NOTHING OWED.** Floor `600` -> `1800` -> `1200` (`c4ce0502` / `dep-dacof4rl550s73eajb4g`, live ~2026-09-03T14:5xZ). Measured at 1200 over 2026-09-03T15:09:31Z -> 2026-09-04T13:20:31Z (22.2 h, 290 lines, gate `floor_s seen {'1200': 290}` — one floor only): **non-today clip rate 85/145 = 59%**, against ~59% predicted BEFORE the deploy and a CONFIRM band of 50-70%. Non-today build-gap median 2,096.7 s -> **1,704.8 s** (n=41), the second half of the prediction. **COST SIDE, STATED:** today's build-gap median ROSE 665.7 s -> **1,163.5 s** (n=70) — the prediction named that mechanism but did not quantify it, and the rise is larger than the non-today fall; different windows and slates, so not a net-negative verdict, but 1200 is NOT free for today. Whether 1200 is the right POINT is a different question from whether the floor is the LEVER, and only the second is answered. Full row in `deploys.md` 2026-09-04. HISTORY: env `600`->`1800` injected by a SAME-SHA redeploy (`f84eb21b`, live 03:08:48Z, no code), then `33b181ee` (live 04:20:45Z) made the floor OBSERVABLE — the queue path had emitted NOTHING, so the verification originally written in this block was not satisfiable; 1800 clipped 87% (130/149), correct by the mechanism and too blunt, hence the tune.
- Files: none — no code change. Env + deploy only. Ledger rows only.
- Blocked by: none

### accuracy-autorun-rearm — **CLOSED 2026-09-04 — `#626`(h) RAN IN PRODUCTION AND PASSED.** `AUTORUN_DONE sports=8 elapsed_s=669.389 error=none` at 14:34:27Z; peak `memory_anon_mb` **1481.6** against a 4096 ceiling (2614 MiB spare), BELOW the ~1877 baseline and 2386 MiB below the 09-02 OOM peak of 3868; zero `oomKilled` since 2026-09-02T15:32:56Z. — opened 2026-09-03 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885
- Outcome: five attempts, one deploy (`7f44f5eb`, live 14:20:32Z), first ever production run of the accuracy autorun. Full measurement: `deploys.md` 2026-09-04.
- **Verification, 3 of 4 items DIRECTLY MEASURED:** (1) `AUTORUN_DONE ... error=none` YES; (2) `LEDGER_CHUNKS_ACCEPTED count=8 bytes=1999970055 budget=2000000000 records=46944 dates=8 truncated=1 skipped_budget=24` YES; (3) peak anon 1481.6 vs 4096/1877 YES. **(4) NOT DIRECTLY READ:** that the PUBLISHED artifact carries `ledger_coverage`. Confirmed only at code level — `run_refresh_worker.py:2220` writes it and the symbol is present on the deployed tree — but nobody has read the artifact back. **That is the one owed reading.**
- **FOLLOW-UP OWED ON `#626`(h), and it is the opposite of the original worry: the BUDGET is now binding, not memory.** `bytes` came in at **99.9985% of the 2 GB cap with 24 chunks SKIPPED**, so the summary rests on 8 dates rather than full history — while peak memory used only 1481.6 of 4096 MiB. The cap was raised on 09-02 on the argument that "at 0.053 bytes/byte the cap only costs coverage"; that is now literally true and it is costing it. Raising the budget is a coverage decision with ~2.6 GB of measured headroom underneath it.
- **WHY FOUR ATTEMPTS FAILED AND THE FIFTH DID NOT — it was not a quieter worker.** Preflight's CLEAR verdict stays VALID FOR 15 MINUTES once written, so it only has to be CAUGHT once and need not coincide with the deploy. Windows are under 25 seconds; the earlier attempts polled far too slowly to catch one. **Tight polling (12s) found CLEAR on the 4th poll.** The other half was the 25-minute deploy-spacing lockout (`#563`): the worker was genuinely idle DURING the lockout and had picked up 3 jobs by the time it lifted, which is why "wait for quiet, then deploy" kept losing.
- Deploy claim: held for the deploy, then lapsed at its 45-min TTL; `mlb-rate-refit` legitimately holds it now. Not forced.
### order-model-view — OPEN — opened 2026-09-03 — session 3492626c — **LIVE ON BOTH ORDER SERVICES (`04187cdf`); VERIFY STILL OWED after 100 min of polling produced ZERO orders written past 19:54:36Z — a null result about the board's PLACEMENT RATE, not evidence about the change. Ambiguous window 8.9 min.**
- Files: `syndicate/features/shared/execution_ledger.py`,
  `pipeline/execute_portfolio.py`, `tests/test_execute_portfolio.py`.
  **RETURNED IN FULL 2026-09-04 00:0xZ by lane `order-sim-view` on closing.**
  That lane borrowed the first two on 2026-09-03 ~22:0xZ, shipped its change,
  and hands them back unchanged in claim terms.

### prop-join-yield — CLOSED 2026-09-04 04:0xZ — opened 2026-09-03 — session 3492626c — **TWELVE COMMITS, ALL DEPLOYED AND MEASURED.** MLB prop cause split (13.4% name misses), soccer joined ONCE (6.9x, 19->57% coverage), NCAAF chips 4->11 + live lanes (184 stuck -> 0), NCAAF cadence 12,948s->640s, `sim_view: unpriced` (3,306) + corners wired (0->108), full order attribution on both order services, six stale `_SCORE_SIM_WEIGHT=0.0` comments, `learnings.md` compacted under budget. `#645(b)` DISCHARGED. **NEXT: `#624` Phase 1 — 191 of 1,423 MLB prop rows (13.4%) blank on a NAME MISS.** Prior: SESSION ENDED 2026-09-04 02:2xZ. ELEVEN COMMITS, ALL DEPLOYED. Order attribution COMPLETE on both order services (`ab42b221`, 4.5-min ambiguous window) — and the dataset is EMPTY: no order since 15:27:33Z because both venue plans size ZERO. NEXT SESSION: the binding constraint is the BUY FUNNEL, not the instrument.** NCAAF LIVE LANES FIXED AND VERIFIED (`9d106d11`, web `3ecc5d9f`): (live,pregame) 184 -> 0, (live,live) 0 -> 236; MLB 104 -> 1,272. `_refresh_layer2_live_state` runs on WEB, not a worker. BUY FUNNEL DIAGNOSED: kalshi/polymarket size 0 positions, every row refused by market_family_excluded or no_model_edge_pct, NCAAF structurally unbuyable. OVERTURNED: `_SCORE_SIM_WEIGHT` is 0.125 not 0.0 -- two comments are wrong and `side_picked_by`'s reasoning rests on them.** SESSION CLOSED 2026-09-04 00:3xZ. EIGHT COMMITS LIVE, FIVE VERIFIED ON PRODUCTION: MLB prop cause split (13.4% name misses), soccer joined ONCE (6.9x, 19.0%->57.0%), `sim_view: unpriced` (3,306), NCAAF chips 4->11, NCAAF cadence 12,948s->640s (20x, spread 506s = a real loop). OWED: `04187cdf`'s order-record hop (zero orders in 4.5h) and `d5c1c0fa` (blocked until 2026-09-17) — both filed as `#645`.** THREE CHANGES VERIFIED IN PRODUCTION: MLB prop cause split (191/1423 name misses, 13.4%), soccer joined ONCE (`ac735931` — 6.9x inflation removed, coverage 19.0% -> 57.0%, unmatched_match 67.4% -> 0.6%), and `sim_view: unpriced` (`36161e83` — 3,306 rows). NCAAF pregame cadence `a9247011` shipped + enabled, reading OWED.** GOAL MET AND MEASURED ON PRODUCTION. `c5e78549` live on refresh-worker + web; artifact 20:48:16Z reads `player_unmatched_name 191` of `player_rows_considered 1423` = 13.4%, `player_no_projection 43`, accounting closes to 0. 82% of unprojected MLB player rows are a NAME MISS, not an honest blank. OWED: soccer's windowed counts are inflated (`ac735931` NOT deployed).**
- Files: `syndicate/features/shared/prop_projections.py`,
  `pipeline/layer2_shortlist.py`, `tests/test_prop_join_yield.py`,
  `tests/test_layer2_projection_window.py`.

### web-oom-profiler-steady — CLOSED 2026-09-04 — opened 2026-09-03 — **`#632` ANSWERED AND VERIFIED IN PRODUCTION AT EVERY STEP.** Excursion: merge children are it (corr +0.997), capped and made cheaper — largest child **281.8 -> 128.1 MB**, peak summed 400.6 -> 163.3 MB, merge output byte-identical. Instrument: attribution moved to THIS PROCESS, which retired `publish` as a false culprit (211 MB container-scoped vs **1.15 MB** per-process) and named `/api/intelligence/query` (~82 MB/call). Payload: **~74% smaller** (self-mirror 50.0% + opt-in alias slimming 47.9%, same-slate live A/B). Rate: **+503 -> +173 MB/h** (R^2 0.90, n=81), moving time-to-limit 2.0 h -> 5.7 h — past the 2.45-3.13 h uptimes at which this service was being OOM-killed. **STILL OPEN, one item:** the exact attributed SHARE, blocked because `app.py` runs background loops IN-PROCESS and `inflight` guarantees no other REQUEST, not no other THREAD — so the route RANKING is trustworthy and the share is not.**
- **`syndicate/templates/intelligence.html` CLAIM TAKEN from `layer2-sim-disagrees` `[2026-09-04, checked line-by-line first]`.** Its work on that file is LANDED; its
  edits are the row-badge renderer (`sim_view` tags ~3168-3258 across
  `939a8c00`/`9987c545`/`36161e83`) plus ~114-135 and ~2182-2224. Mine are
  `rehydrateAliases` ~716, `intelligenceQueryPayload` ~3657, the fetch handler ~3697
  — **disjoint by function**, the same standard that lane applied when it took
  `layer2_board.py`. Their `board_sim_view_display` JS test passes. Notice left in
  their block.
- Files: `docs/ai_context/todo.md`
  (`#632`), `syndicate/blueprints/ops.py`,
  `syndicate/features/shared/artifact_merge.py`,
  `tests/test_artifact_merge_child_cap.py` and
  `tests/test_artifact_merge_string_pool.py` [claimed 2026-09-03T20:1xZ and
  21:0xZ, user directives "cap the merge children" then "make the merge
  cheaper"]. All LANDED on main and live on web.
  **NOT claimed, listed for the record:** this lane also writes the
  ledger files under .syndicate (lanes, state, deploys, log). They are EXEMPT
  from lane-guard -- every session writes them -- so naming them as claims
  guards nothing, and naming them as PATHS makes them read as CONTESTED
  against every other lane that lists them. Written as a shell brace list
  until 2026-09-03, which the parser read as one broken token.
- Blocked by: none.

### ncaaf-chip-compact — OPEN — opened 2026-09-03 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **DIAGNOSED, FIXED, LANDED. NOT DEPLOYED. The reported symptom is a JOIN failure, not a missing abbreviation — the chip already carried `MAS`/`RUT`.**
- Files: `syndicate/features/shared/team_aliases.py`,
  `syndicate/features/shared/game_chip_scoreboard.py`,
  RELEASED `[2026-09-03, lane layer2-sim-disagrees, SAME session 3492626c]`: the
  layer2 board module. Narrow and disjoint by function: that lane edits
  `_projection_side_in_row_frame` / `_model_edge_for` / `_model_prob_for_side` /
  `_publication_columns`; YOUR chip-join work (`away_key` / `home_key` stamping)
  is untouched and is already LANDED per this block's own header. Checked
  line-by-line before taking it. Take it back by striking this note and
  restoring the path on its own line.
  `tests/test_ncaaf_chip_join_key.py` (NEW).
- Blocked by: nothing. **Deploy deliberately NOT taken** — handed to the
  coordinating lane `order-model-view`.

### layer2-sim-disagrees — OPEN — opened 2026-09-03 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **ANSWERED, FIXED, LANDED, NOT DEPLOYED. The tag's RULE is fine; its INPUT is null on 100% of NCAAF rows. Two further defects found on the same served payload, both of which make the board state a number it does not have.**
- **NOTICE from `web-oom-thread-gating` `[2026-09-04]`: I edited `pipeline/intelligence_state.py` at ~7776** (the board-drain THREAD TARGET, so
  `#632`'s per-request attribution can exclude the build that runs on it). Your
  block scopes this file to *"the `confidence` backfill at ~1888 ONLY"*, so we are
  disjoint by your own definition — I changed no line near 1888. Say so if you
  disagree and I will back it out.
- **NOTICE from `web-oom-profiler-steady` `[2026-09-04]`: I TOOK THE CLAIM ON `syndicate/templates/intelligence.html`.** `#632` needed the alias-rebuild helper and
  the query fetch payload; your edits there are the row-badge renderer and are LANDED.
  Ranges checked line-by-line first — yours ~114-135, ~2182-2224, ~3168-3258; mine
  ~716, ~3657, ~3697. Disjoint by function. Your `board_sim_view_display` JS test
  passes. If you still need the file, say so and I will coordinate rather than assume.
- Files: `syndicate/features/shared/layer2_board.py`
  (**`_projection_side_in_row_frame` / `_model_edge_for` / `_model_prob_for_side`
  / `_publication_columns` ONLY** — the OPEN lane `ncaaf-chip-compact` lists this
  file for the CHIP JOIN (`away_key` / `home_key` stamping) and is the SAME session
  id, `3492626c`; the two edits are disjoint by function and were checked
  line-by-line before taking this),
  `pipeline/intelligence_state.py` (**the `confidence` backfill at ~1888 ONLY**;
  `layer2-cap-raise` marks the file `released:`),
  `syndicate/templates/intelligence.html` (unclaimed; `chipForGame` is the other
  lane's area and is untouched),
  `tests/test_layer2_sim_view.py` (NEW).
- Blocked by: none.

### ncaaf-live-cadence — OPEN — opened 2026-09-03 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **DIAGNOSED, BUILT, LANDED ON `origin/main` AS `a9247011`. NOT DEPLOYED; THE CADENCE IMPROVEMENT IS UNMEASURED AND THIS LANE CANNOT MEASURE IT.**
- Files: `scripts/run_live_odds_refresh_worker.py`,
  `scripts/refresh_odds_sources.py` (mode-scoped step filter only),
  `tests/test_ncaaf_lines_autorun.py` (NEW),
  `tests/test_refresh_step_modes.py` (NEW).
  Render ENV on **live-odds-worker** via the single-key API only. The Render
  blueprint file is deliberately NOT named as a path here and is NOT claimed —
  `lane-guard` reads any backticked path inside a `- Files:` block as a CLAIM,
  and spelling it even to forbid it made this lane contest it with
  `accuracy-autorun-rearm` (caught by `check_lane_invariants.py`). See the ENV
  bullet below for why that file must not be pushed for this change.
  Render ENV on **live-odds-worker** via the single-key API — **never `render.yaml`**
  (pushing it fires `blueprint_sync`, which rewrites every key on all three
  services).
  Collision-checked 2026-09-03 against every OPEN lane: no OPEN lane claims any
  of these. `run_live_odds_refresh_worker.py` is `released:` in
  `open-bet-live-status` and explicitly "Not claimed, read-only reference" in
  `wnba-live-odds-capture-gap`; `refresh_odds_sources.py` is claimed only by
  the ARCHIVED `soccer-odds-coverage`, whose claims were released 2026-08-15.
- Blocked by: deploy is owned by lane `prop-join-yield`; this lane lands on
  `origin/main` and hands over the env keys.

### worker-catchup-round9 — CLOSED 2026-09-04 — **BOTH WORKERS to `442f82fe`** (00:19:35Z / 00:33:09Z), verified by content (`_process_anon_mb` 0→4, absent from the prior SHA), `#643` re-checked, 200 log lines, 0 errors. **Web excluded by design** — its owner held the claim and web was 24 min from boot, one minute short of the 25-min late-emission window their measurement needs; `442f82fe` is their own commit. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Files: NONE — deploy only. Does not claim the shared ledger.
- Blocked by: none for the workers; web is owner-held by design.

### claim-check-severity-split — CLOSED 2026-09-03 — FAIL only on what can never resolve; a typo still fails, a not-yet-written file only reports — session f97ad5ab
- Files (exclusive): `scripts/check_lane_claims.py`,
  `.claude/hooks/test_lane_claims_parser.py`. Collision check RUN 2026-09-03 via
  `lane_claims._claims()`: CLEAR on both.
- Blocked by: none.

### refresh-catchup-round10 — CLOSED 2026-09-04 — **NO DEPLOY TAKEN: the owning lane shipped it while I was checking.** `prop-join-yield` held refresh-worker's claim with a deploy in flight; `dbe0f3b4` carries the NCAAF fix by content (`chip_join_key` x3, `9d106d11` an ancestor) and went live 00:50:28Z. live-odds-worker's only pending commit is inert lane-guard tooling; web was already 0 pending. No claim taken, none forced. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Files: NONE — deploy only. Does not claim the shared ledger.
- Blocked by: none.

### ledger-coverage-declared — CLOSED 2026-09-03, **NOT A DEFECT — the gap does not exist and I nearly built machinery for it** — session f97ad5ab
- Files (exclusive): `.claude/hooks/ledger_invariants.py`,
  `.claude/hooks/test_ledger_invariants_resurrection.py`. Collision check RUN
  2026-09-03 via `lane_claims._claims()`: CLEAR on both.
- Blocked by: none.

### ledger-cap-single-source — CLOSED 2026-09-03 — the ledger cap now has ONE source, the enforcer, and a drift test keeps it that way — session f97ad5ab
- Files: `.claude/hooks/ledger_caps.py` (new),
  `.claude/hooks/test_ledger_caps.py` (new), `scripts/trim_lane_blocks.py`,
  `scripts/archive_released_lanes.py`. Collision check RUN via
  `lane_claims._claims()`: CLEAR on all four.
- Blocked by: none.

### pending-deploys-runtime-classifier — CLOSED 2026-09-04 — **BUILT AND VERIFIED.** `pending_deploys.py` now computes script reachability transitively: 152 of 328 scripts are named by runtime code, 176 are tooling and excluded, and a VERDICT line answers "is a deploy warranted" directly. All six scripts observed running in production classify RUNTIME. 8 tests, CI OK. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: decide a catch-up round mechanically instead of hand-reading the file
  list, which is what rounds 8-11 each did. **Met.**
- Files: `scripts/pending_deploys.py`,
  `tests/test_pending_deploys_runtime.py` (NEW).
- **CONSERVATIVE BY CONSTRUCTION**, same asymmetry as `check_lane_invariants`:
  a false RUNTIME is noise, a false INERT hides a needed deploy. A script is
  demoted only on proof that no runtime file names it; the closure returns
  `None` ("treat all as executed") when the tree cannot be read.
- Verification (done): all six scripts seen in `deploy_preflight`'s live job
  listing — `refresh_odds_sources`, `build_soccer_artifacts`,
  `run_mlb_daily_sim_job`, `run_refresh_worker`, `run_live_odds_refresh_worker`,
  `run_refresh_odds_job` — classify RUNTIME. `f31a6db9` (`check_lane_claims.py`)
  dropped out of all three services' pending lists, which is the round-11 result
  reproduced mechanically.
- Residual, deliberate: five tooling scripts still read RUNTIME because runtime
  STRING literals name them. Noise in the safe direction; tightening further
  would risk false INERT, so it is left and documented.
- Blocked by: none.


### lanes-whole-file-staleness — CLOSED 2026-09-04 — a compaction revert is now refused; the guard's path match no longer reads the commit MESSAGE — session f97ad5ab
- Files: `.claude/hooks/ledger_invariants.py`,
  `.claude/hooks/test_ledger_invariants_resurrection.py`,
  `.claude/hooks/ledger-commit-guard.py`.
- Blocked by: none.
- Also, from the same thread: `.claude/hooks/discard-guard.py` (new) +
  `.claude/hooks/test_discard_guard.py` (new) + `.claude/settings.json`.

### worker-deploy-3777397d — CLOSED 2026-09-04 — **BOTH WORKERS to `ab42b221`** (02:12:41Z / 02:17:12Z). Shipped the tip because `3777397d` is docstring-only; `ab42b221` contains it plus `008aca69`. Verified by content on both halves (`price_shopping` 0→2, `attribution` 0→7) with `#643` re-checked for survival; 0 errors. Web excluded — owner-held, and its pending commit is that lane's own. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Files: NONE — deploy only. Does not claim the shared ledger.
- Verification: BY CONTENT on the deployed SHA, tokens confirmed absent from the
  previously-live `442f82fe` first. Measurements in `.syndicate/deploys.md`.
- Blocked by: none.


### hook-missing-file-tolerant — CLOSED 2026-09-04 — all 11 hook invocations warn-and-continue when their file is absent, and still block when it is present — session f97ad5ab
- Files: `.claude/settings.json`.
- Blocked by: none.

### resurrection-real-corpus — CLOSED 2026-09-04 — the compaction commit pinned as a permanent fixture; the check was proven only against inputs built to trip it — session f97ad5ab
- Files: `.claude/hooks/test_ledger_invariants_resurrection.py`.
- Blocked by: none.

### live-odds-deploy-4ead66c3 — CLOSED 2026-09-04 — **live-odds-worker `ab42b221`→`e713939f`, live 03:23:55Z.** Verified by content (`corners_mean` 0→1, `alternate_totals_corners` 0→3, `away_corners` 0→2) with `#643` and `008aca69` re-checked for survival; 0 errors. refresh-worker already had it; **web excluded — owner mid memory-remeasure**, and remains 1 behind by design. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: live-odds-worker off `ab42b221` onto `e713939f` `[user: "deploy
  4ead66c3"]`. `4ead66c3` (soccer corners get a model view from the CORNERS
  mean) is genuinely behavioural — 53 added lines of real code, not docstrings —
  and `e713939f` contains it while adding nothing else a service executes.
- Files: NONE — deploy only. Does not claim the shared ledger.
- **refresh-worker ALREADY ON `4ead66c3`** (a peer shipped it; 0 pending).
- **WEB EXCLUDED.** `web-oom-rate-remeasure` has held its claim 25 min and is
  re-measuring web memory; a deploy reboots the process and resets the
  accumulator its method depends on. Same call as round 9. Not forced.
- Verification: BY CONTENT on the deployed SHA — `corners_mean` and
  `alternate_totals_corners` in `soccer_projections.py`, both confirmed ABSENT
  from the currently-live `ab42b221`; plus 0 tracebacks.
- Blocked by: none.


### web-deploy-4ead66c3 — CLOSED 2026-09-04 — **web `b3966bf1`→`906f9537`, live 03:44:48Z; FLEET NOW 0 PENDING ON ALL THREE.** Verified by content (`corners_mean` 0→1) with `#643` re-checked; 9 MLB cards, portfolio 1458/1457/1, 0 errors. The withheld-last-round concern was re-checked not assumed: claim released, no build in flight, 85 min uptime. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: web off `b3966bf1` onto `906f9537` `[user: "deploy web too", after I
  flagged the tradeoff and they reaffirmed]`. Carries `4ead66c3` (soccer corners
  model view), the same behavioural commit the workers already run.
- Files: NONE — deploy only. Does not claim the shared ledger.
- **THE CONCERN I RAISED, AND ITS RESOLUTION.** I withheld web last round because
  `web-oom-rate-remeasure` held the claim and a reboot resets the memory
  accumulator its method depends on. Since then: that claim is RELEASED, no build
  is in flight, and web has been up **85 minutes** — well past the 25-min window
  the method needs. The user reaffirmed after the tradeoff was stated.
- Verification: BY CONTENT on the deployed SHA — `corners_mean` in
  `soccer_projections.py`, confirmed ABSENT from the currently-live `b3966bf1`;
  plus web serving MLB cards and `/api/portfolio/summary`; plus 0 tracebacks.
- Blocked by: none.

### mlb-prop-phase1 — OPEN — opened 2026-09-03 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **`#624` STEP 1 COMPLETE AND VERIFIED ON EVERY SPORT (`5af2c517`, all 3 services).** Platform EXACT 0.0/1.0 = 0/0 (was 24/1); 23 rows labelled refused; near-zero bands SURVIVED (182 soccer, 70 mlb), proving the rule is EXACT not a band; MLB coverage ROSE 77.7%->84.5%. All 9 MLB refusals are `hr_2plus` — the producer `f1508e78` could not see, which is why that first fix covered 1 OF 17. Step 3's MECHANISM also verified in production: starter `ab_mean` -4.41% vs a predicted -4.43%. **NEXT: step 3's ESTIMATOR half — the rate re-fit, compute-heavy, own lane.**
- Goal: `#624` Phase 1 on MLB props, step by step, each one measured on the served board before the next is started.
- Step 1 (calibration) shipped 2026-09-01 as `f03ef38a`. **Its other half — "hard refusal of p in {0.0, 1.0}" — had never shipped**, and this lane landed it: `f1508e78`, `_dist_prob_over` returns None on an exact certainty instead of publishing it.
- Files: syndicate/features/shared/prop_projections.py
  tests/test_prop_certainty_refusal.py
  (claim released by lane `layer1-model-edge-join` on 2026-08-31 — phantom sweep, owning session gone; no live lane holds either path)
- Hypothesis: n/a for the refusal (it is a contract change, not a diagnosis). For step 3: `position_substitutions=False` inflates `pa_mean` by +19.7%, so turning substitution ON requires a JOINT REFIT rather than a flag flip — a mechanism added to a calibrated engine displaces the rates that were absorbing it.
- Falsification test: the refusal is wrong if a legitimate probability disappears from the board. It refuses EXACTLY 0.0 and 1.0 and nothing else — 0.9 from a real distribution is untouched — so the falsifier is a drop in `model_prob_over` coverage larger than the certainty count (1 of 872 on the 09-04Z board).
- Verification: on the first refresh-worker build carrying `f1508e78`, the served MLB prop rows contain **zero** `model_prob_over` at exactly 0.0 or 1.0, and total `model_prob_over` coverage falls by AT MOST the number of certainties that were there. **A ZERO COUNT IS NOT SELF-EVIDENT** — the pre-deploy board had exactly one, so this reading needs the coverage denominator beside it or it is indistinguishable from a board that lost the field entirely.
- Blocked by: none. (Deploy target is refresh-worker — the ARTIFACT WRITER. Web reads the precomputed board artifact; the inline join is fallback only, so deploying web alone would not move this.)

### catchup-624-certainty — CLOSED 2026-09-04 — **web + live-odds-worker to `5af2c517`** (05:11:33Z / 05:11:31Z), `#624` certainty refusal. Verified by content (`refuse_published_certainty` 0→6, `probability_refusal` 0→1) with `#643` and `4ead66c3` re-checked for survival; 16 MLB cards, 0 errors. refresh-worker excluded — `mlb-prop-phase1` holds it and the work is that lane's own. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: web and live-odds-worker onto `5af2c517`. Behavioural: `#624`'s certainty
  refusal — refuse an exact 0.0/1.0 probability at the producer and at the choke
  point, on EVERY sport rather than MLB props only (`prop_projections.py`,
  `intelligence_contracts.py`, `layer2_board.py`, `live_gameline_join.py`,
  `ncaaf/game_projections.py`, wnba projections; 13 files, +349).
- Files: NONE — deploy only. Does not claim the shared ledger.
- **refresh-worker EXCLUDED.** `mlb-prop-phase1` has held its claim 41 min and is
  already on `99479bd4`; the `#624` prop work is that lane's own. Theirs to ship.
- Verification: BY CONTENT on the deployed SHA — `refuse_published_certainty` in
  `prop_projections.py`, confirmed ABSENT from the currently-live `e713939f`
  (live=0, target=6); plus web serving cards; plus 0 tracebacks per service.
- Blocked by: none.

### mlb-rate-refit — OPEN — opened 2026-09-04 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **`#624` step 3's ESTIMATOR half. THE HARNESS COMPARES TWO DIFFERENT POPULATIONS AND MUST BE FIXED BEFORE IT IS RUN.**
- Goal: derive rate corrections for the sim's `hr_rate` / `inplay_hit_rate` / `k_rate` / `bb_rate` that are valid for the input set they were fitted against, and ship them only if the residual shrinks on all four.
- Why now: `e3bdbc8b` turned position substitution ON and it is verified in production (starter `ab_mean` -4.41% vs a predicted -4.43%). That is the MECHANISM. Per the model-engine standard §4.4 a mechanism added to a calibrated engine displaces the rates that were absorbing it, so the ESTIMATOR must follow. Substitution UNDER-corrects (opportunity bias still ~+4.4%), so it cannot overshoot what the rates absorbed — but the ~12% per-PA RATE bias is untouched and is what this lane is for.
- Files: scripts/refit_mlb_rates.py
  tests/test_refit_mlb_rates.py (new)
  (no OPEN lane claims either path, nor `vendor/mlb_bettingv2/sim_engine/models.py`, checked against origin/main)
- Hypothesis, MEASURED BEFORE ANY RUN and the reason this lane opens with a fix rather than a sweep: **`load_actual_rates()` reads the WHOLE `mlb_batter_game_log.csv` with no date filter while the sim runs over whichever `roster_objs` exist.** Coverage on this checkout:

      simulated side  roster_objs/          13 dates, 186 games   2026-06-15 .. 06-27
      actual side     mlb_batter_game_log   47 dates, 12,185 rows 2026-05-28 .. 07-14

  and `--games 30` (the documented usage) takes the FIRST 30 jobs in sort order — about **three dates**. So `correction = actual / simulated` would be 47 dates of real outcomes over ~3 dates of simulated ones, and would absorb the difference between two POPULATIONS as if it were mechanism bias. This is `CLAUDE.md`'s named trap: an analysis that joins across artifact families silently collapses to their intersection, and looks like it ran on months of data.
- Falsification test: if the date windows are already equivalent, matching them changes the corrections by ~nothing and the hypothesis is wrong. Run it BOTH ways and report both sets — a matched-window correction that equals the unmatched one costs nothing and settles it.
- Verification: (1) actual and simulated cover the SAME dates, printed, with the game count the result rests on; (2) `residual shrank on 4 of 4` in PASS 2, which the script already gates on and refuses to recommend below 4; (3) the corrections are held OUT of the engine until (1) and (2) both hold — the script only writes a JSON report, so shipping is a separate, deliberate step and is NOT part of this lane's goal.
- Blocked by: none. Compute-heavy and LOCAL — nothing here deploys, and the mirror is not evidence about production, so no claim from this lane may be stated as a production fact.

### live-lens-date-gate — OPEN, **UNOWNED** (session b9013cf2 ended 2026-09-04) — **LANDED `main` (`d77695ef`), NOT DEPLOYED. Unit-verified only; owed a production reading.** — opened 2026-09-04 — session b9013cf2-9ea8-431f-9700-f4aac4794582 — checkpointed 2026-09-04 (see `log/2026-09-04.md`)
- Goal: `attach_live_game_state_from_lens` must REFUSE to overlay when the live-lens snapshot's own slate date differs from the `selected_date` being served, and must say so in `live_game_state.reason` rather than silently correcting 0 rows.
- Files: `syndicate/features/shared/board_enrichment.py`, `tests/test_board_enrichment_lens_date_gate.py` (new).
- Hypothesis: for every sport except soccer the function reads ONE current-day snapshot (`data_root()/live/<sport>_live_lens.json`) and joins it to the grid by TEAM PAIR only; `selected_date` is a parameter but is used only in a log line (board_enrichment.py:572). So serving a PAST date applies TODAY's states to yesterday's rows.
- Falsification test: if `selected_date` were already gated, a past-date board would report `rows_corrected: 0` with a date reason. MEASURED 2026-09-03 board: `lens_games: 16` (the 09-04 slate), `rows_corrected: 187`, `transitions: {"live->pregame": 187}` — 187 = exactly the ATH@SEA row count, and ATH@SEA is the one 09-03 matchup that repeats on 09-04. Hypothesis NOT falsified.
- Verification: (a) unit test — a lens dated D+1 against a grid for D corrects 0 rows and reports a date-mismatch reason, while a same-date lens still corrects; (b) served payload — `/api/board/book-grid?sport=mlb&date=<past>` returns `live_game_state.rows_corrected: 0` with the reason, and no row's `game.state` regresses from `final`/`live` to `pregame`.
- Cost of the bug (measured): 2026-09-03 had 9 MLB games, all 9 Final (StatsAPI). ATH@SEA had been Final 7-4 for 28 min and was PUBLISHED as `pregame 0-0`. `live_edge_policy` reads `game.state`, so that re-opens edges on a settled market.
- **SCOPE CORRECTION, found while verifying — the gate does NOT recover the two missing finals.** I first attributed `games_with_outcome: 7` to this overlay. The transition key says otherwise: `live->pregame` means the before-state was `live`, and `build_finals_index` (`live_gameline_score.py:307`) requires `state == "final"`, so that game was skipped either way. Order confirmed: overlay at `book_grid_artifact.py:287`, scorer at `:347`.
- SECOND, SEPARATE CAUSE — still open, not fixed here: neither ATH@SEA nor STL@LAD was EVER marked `final` in the grid, though both finished ~25 min before the build (05:05Z / 05:09Z vs a 05:33:14Z build). That is the frozen `_mlb_feed_live_payload` chip this overlay exists to paper over ("it reads the cached file and returns it if it EXISTS, consulting the live API only when the file is absent") — and for a PAST date the overlay can never repair it, because the only lens that exists is today's. The overlay's own docstring already names the deeper fix and defers it.
- NOT IN SCOPE, and deliberately: dating the lens snapshot. `learnings.md:3722` prices that at ~5.76 GB/day for MLB alone into a 256 MB keyvalue store at 86.8% full, and a dated path silently takes a TTL under `volatile-lru`. The snapshot ALREADY carries `date` (`mlb/live_lens.py:1873`, inside `page_context`), so the gate is a pure read-side check at zero storage cost.
- Blocked by: none.

### catchup-632-thread-gating — CLOSED 2026-09-04 — **refresh-worker + live-odds-worker to `b24c89b0`** (13:48:20Z / 13:35:53Z). Verified by content (`background_work` 0→5, `background_seq` 0→4) with `#624` and `#643` re-checked for survival; 0 errors. Web untouched — it was MID-BUILD on this exact commit under the lane that authored it, and finished on its own. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: refresh-worker `[user: "deploy refresh-worker too"]` and live-odds-worker
  onto `b24c89b0` (`#632` — exclude this process's own background threads from
  per-request memory attribution; `memory_observability.py`, +327).
- **Scope note, stated not quietly widened:** only refresh-worker was asked for.
  live-odds-worker is behind on the SAME single commit and its claim is free, so
  it is included to avoid leaving an identical gap for another round.
- Files: NONE — deploy only. Does not claim the shared ledger.
- **WEB EXCLUDED — it is MID-BUILD on this very commit** (`build_in_progress
  b24c89b0`) under `web-oom-thread-gating`, whose own `#632` work this is.
  Deploying it would cancel their build; that is the 2026-08-15 incident and was
  done to me on 09-03.
- Verification: BY CONTENT on the deployed SHA — `background_work` in
  `memory_observability.py`, confirmed ABSENT from the currently-live `5af2c517`
  (live=0, target=5); plus 0 tracebacks per service.
- Blocked by: none.


### catchup-live-odds-slate-lens — CLOSED 2026-09-04 — **live-odds-worker `b24c89b0`→`4597077d`, live 14:34:59Z.** Verified by content, one token per commit (`requested_date` 0→2, `_collections_total` 0→1), with `#624`/`#643`/`#632` all re-checked for survival; 0 errors. Only this service was behind. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: live-odds-worker off `b24c89b0` onto `4597077d`. Two commits it executes:
  `2248ed78` (live-lens — a lens built for ANOTHER slate must not correct this
  one; `board_enrichment.py`) and `3ee5e4b0` (`#632` GC instrumentation,
  explicitly NOT a gate; `memory_observability.py`).
- **ONLY live-odds-worker.** refresh-worker (`7f44f5eb`) and web (`3ee5e4b0`)
  both read 0 pending — peers already carried them.
- Files: NONE — deploy only. Does not claim the shared ledger.
- Verification: BY CONTENT on the deployed SHA, one token per commit, each
  confirmed ABSENT from the currently-live `b24c89b0`: `requested_date` in
  `board_enrichment.py` (0→2) and `_collections_total` in
  `memory_observability.py` (0→1); plus 0 tracebacks.
- Blocked by: none.


### mlb-feed-live-terminal-refresh — OPEN, **UNOWNED** (session b9013cf2 ended 2026-09-04) — **LANDED `main` (`20221619`), NOT DEPLOYED. Unit-verified only. OWED: `games_with_outcome` == real finals count on `?date=<yesterday>` after the first post-roll build.** — opened 2026-09-04 — session b9013cf2-9ea8-431f-9700-f4aac4794582 — checkpointed 2026-09-04 (see `log/2026-09-04.md`)
- Goal: a cached `feed_live` payload that is NOT final must be refreshed rather than reused, and that refresh must remain reachable for a slate that ended after the Central date roll — so a game final at 05:05Z is marked `final` by a 05:33Z build.
- Files: `syndicate/features/mlb/cards.py`, `syndicate/blueprints/home.py`, `tests/test_mlb_feed_live_terminal_refresh.py` (new).
- Hypothesis: TWO defects compose. (1) INVERTED PREDICATE — `cards.py:2345` refetches when `not _actual_payload_is_live(payload)`, so a cached PREGAME or FINAL payload is refreshed while a cached LIVE one never is; live->final is exactly the transition that is never picked up. `home.py:_mlb_feed_live_payload` has no freshness rule at all — it returns the file whenever it EXISTS. (2) WINDOW — both refetches are gated `selected_date == today_iso`, and a game that ends after the Central roll can only be recorded by a build for YESTERDAY's slate, which that gate refuses.
- Falsification test: if the chip state were not coming from a frozen cached payload, the 09-03 grid could not have carried a mid-game SCORE. It carried STL@LAD `live 2-1` (actual final 2-3) — a real in-progress snapshot, which only a cached feed payload supplies. Hypothesis NOT falsified.
- Verification: (a) unit — a cached LIVE payload triggers a refetch and a cached FINAL one does not (the inversion, both directions); a yesterday-slate build still refetches while an older date does not; (b) served payload — on the next post-roll build, `/api/board/book-grid?sport=mlb&date=<yesterday>` shows `games_with_outcome` equal to the real finals count, and no game reads `live` with a stale score.
- Cost of the bug (measured): 2026-09-03, ATH@SEA final 05:05Z and STL@LAD final 05:09Z, artifact built 05:33:14Z — 24-28 min later — and BOTH were still `live`/`pregame`. `live_gameline_score` scored 7 of 9. The 09-03 artifact has not been rebuilt since, so the loss is permanent for that date.
- WEB MUST NOT GAIN NETWORK. `home.py`'s reader is on the request path, where the feed_live file always misses (it matches no `HOT_ARTIFACT_PATTERNS`) and every miss is an HTTPS call — the measured cause of `/healthz` timing out and gunicorn being SIGTERM'd three times in five minutes. The widened window is therefore worker-only, gated on the existing `_render_web_dyno()`.
- Blocked by: none. Follow-on from `live-lens-date-gate` (that lane stops the wrong-day OVERWRITE; this one is why the finals were missing in the first place).
- OUTCOME: fix landed on `main` (`20221619`, tests `f3f4c13c`). NOT DEPLOYED -- `.py` only, `autoDeploy = no`.
- **RETRACTED 2026-09-04: THE "REACHABILITY TRAP" I CLAIMED HERE DOES NOT EXIST.** I wrote that `_render_web_dyno()` would have been INERT on refresh-worker because `SYNDICATE_WEB_DYNO` was ABSENT there. It is not absent — my read was ONE `limit=100` page of that service's **153** keys, the exact pagination trap `CLAIMS.md`/`CLAUDE.md` warns about. Live values are web `true`, both workers `false`, matching `render.yaml`. Confirmed positively, not just retracted: `[mlb_cards] FEED_LIVE_PRUNE` sits behind `not _render_web_dyno()` and emits on refresh-worker every build. `has_request_context()` is KEPT — on the merits, because the constraint is about the REQUEST PATH and `_mlb_feed_live_payload` is called from both web requests and worker code — not because the alternative was broken.
- SIDE FINDING **WITHDRAWN** with the line above: there is no drift, so the other `not _render_web_dyno()` gates in `mlb/cards.py` are NOT inert. They are emitting on refresh-worker right now.
- Tests: 24 new (`tests/test_mlb_feed_live_terminal_refresh.py`); 3 of the 6 reader tests fail against unmodified code (off != on). `tests/test_mlb_cards_worker_hydration_cost.py` was pinned outside the window -- its "today" was one day off its slate, so under the new window it made a REAL statsapi call and graded a live 79-play document against a 500-play fixture.
- Regression: 256 + 213 passed across the directly-affected files. `tests/test_archives.py` shows 31 failed / 350 passed -- IDENTICAL on unmodified code (this worktree has no `data/`), so none are from this change.

### render-events-nondict-reason — CLOSED-VERIFIED 2026-09-04 — `scripts/render_events.py` no longer dies mid-listing on a non-dict `details.reason`, and a truncated run can no longer pass for a complete one. Landed `ea4e3881` on `origin/main`. Local tooling — no deploy.
- Goal: the OOM-census instrument completes a full-window read on all three
  services, AND a run that dies says so on STDOUT.
- Files: `scripts/render_events.py`, `tests/test_render_events.py`.
- Verification (RAN): falsification — the 7 new shape/completeness tests **fail
  against the pre-fix file** swapped into the same worktree (20 existing pass),
  **28/28 pass** after. Repro `--service refresh-worker` was exit 1 / 289 stdout
  lines / dead at row 290; now **exit 0, 7,525 rows, stderr 0 bytes**, ending
  `OUTPUT COMPLETE`. `web` 10,000 rows, `live-odds-worker` 8,098 rows. Abort
  banner fires on **stdout** with exit 3 under an injected `_get` failure.
- Handoff, as a READING not a diagnosis: 2026-08-21 → 2026-09-04, fully paged —
  refresh-worker **1 oomKilled** (`2026-09-02T15:32:56Z`, `memoryLimit=4Gi`) + 4
  unknown; web **7 oomKilled** + 39 unhealthy; live-odds-worker 25 earlyExit + 6
  unknown. All 10 `failed:unknown` are `{"evicted": false, "nonZeroExit": 1}` —
  an unbucketed reason, now printed raw. Full working: `log/2026-09-04.md`.
- Blocked by: none.
- BODY RESTORED BY THE OWNER 2026-09-04. Session b9013cf2 dropped this block
  while rebuilding `lanes.md` from `origin/main` (it existed only as an
  uncommitted edit in the primary tree) and left an honest stub saying so; the
  stub's own account is preserved verbatim in `lanes_history.md`. The claim
  marker survived, so lane-guard never stopped enforcing the two file claims.
  Nothing of this lane's WORK was at risk — it was already committed and pushed.

### accuracy-ledger-budget-raise — OPEN — opened 2026-09-04 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885
- Goal: `build_accuracy_summary` stops truncating its ledger read. ONE testable outcome: the next autorun logs `LEDGER_CHUNKS_ACCEPTED ... skipped_budget=0 truncated=0` with `dates` materially above 8, and peak `memory_anon_mb` stays under 2,600 MiB.
- Files: `syndicate/features/shared/intelligence_evaluation.py`, `tests/test_accuracy_summary_ledger_budget.py`, `docs/ai_context/todo.md`, `.syndicate/*`.
- Hypothesis: the 2 GB budget, not memory, is what caps coverage. **Measured 2026-09-04, not assumed:** `bytes=1999970055` against `budget=2000000000` (99.9985% of cap), `skipped_budget=24`, `truncated=1`, `dates=8` — while peak anon was **1481.6 MiB of a 4096 ceiling**, i.e. ~2,614 MiB unused.
- Falsification test: if raising the budget does NOT reduce `skipped_budget`, the cap was not the binding constraint and something else (the 256 MB per-chunk ceiling, or chunk count) is. If peak anon rises faster than ~0.18 MiB per accepted MB, the projection ratio has drifted and the raise must be reverted.
- Verification: tomorrow's autorun (the job is once-per-Central-day, so THIS CANNOT BE VERIFIED TODAY) — read `LEDGER_CHUNKS_ACCEPTED` for `skipped_budget`/`dates` and the peak `memory_anon_mb` over the run window, both against the 09-04 baseline above.
- **STAGED ON PURPOSE: 2 GB -> 4 GB, not straight to full coverage.** Full history is ~32 chunks; admitting all of them at the 256 MB per-chunk ceiling would need ~8.2 GB. The marginal cost measured today is at most 350.6 MiB per 2 GB accepted (peak 1481.6 minus min 1131.0 over the run window, and that spread still includes concurrent work, so it is an UPPER bound). At that rate 8.2 GB projects to ~1,131 + 1,435 = ~2,566 MiB, which lands too close to the ceiling if it ever coincides with the ~1,877 MiB baseline cycle peak. 4 GB projects to ~1,832 MiB. One step, measured, then decide — the repo's own "one change per deploy when diagnosing" rule.
- Blocked by: none

- **CODE IS ON `main` AT `b55fa165` (2 GB -> 4 GB) BUT IS NOT IN PRODUCTION — A DEPLOY IS OWED.** `autoDeploy` is off, so refresh-worker keeps running the 2 GB default until some refresh-worker deploy carries this commit. **Not deployed deliberately:** the autorun is once per Central day and already ran today at 14:34Z, so nothing can exercise this before ~07:00 CT tomorrow, and forcing a deploy now would kill in-flight jobs to ship a change nothing will read for 17 hours. Peers deploy this service several times a day; any of those carries it. **This is safe to let ride ONLY because it is CODE.** The same reasoning would be wrong for an env key that arms behaviour — that is the 09-03 landmine, where a key set `true` waits for someone else's unrelated deploy to fire it.
- **BEFORE TRUSTING TOMORROW'S RESULT, CHECK THE DEPLOYED SHA CONTAINS THE RAISE** — by CONTENT, not ancestry: `git show <live-sha>:syndicate/features/shared/intelligence_evaluation.py | grep "DEFAULT_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES = "` must read `4_000_000_000`. If it still reads `2_000_000_000`, tomorrow's `skipped_budget` measures the OLD budget and says nothing about this change.
- **DEPLOY OWED IS DISCHARGED — THE RAISE IS LIVE AS OF 2026-09-04T15:00:12Z.** Live commit `2332b47b` carries `DEFAULT_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES = 4_000_000_000`, verified BY CONTENT on the deployed tree. It shipped on lane `mlb-rate-refit`'s deploy of the `origin/main` tip about five minutes after I pushed it — the "peers deploy this several times a day" prediction, paid out. I acquired a claim intending to deploy, found it already live, and released the claim with its token instead of deploying redundantly. **Reachability re-confirmed:** the env override is absent across all 153 keys (paginated) and absent from `render.yaml`.
- **STILL UNVERIFIED, AND THAT IS THE WHOLE POINT OF THIS LANE.** The autorun already ran today at 14:34Z under the OLD 2 GB budget, so nothing has yet exercised 4 GB. First read is the autorun at >= 07:00 CT on 2026-09-05. Until then the standing measurement remains `skipped_budget=24 dates=8 truncated=1`. **Do not close this lane on "it is deployed" — deployed is not exercised.**
- **PRE-REGISTERED INTERPRETATION OF TOMORROW'S `skipped_budget`, written BEFORE the data exists `[from lane mlb-rate-refit, session 3492626c]`.** Baseline to beat: `skipped_budget=24 dates=8` at 2 GB. On the first 4 GB run — **0 = the cap is no longer binding and there is headroom to spare; ~12 = the byte budget is no longer the right instrument** and the next step is a CHUNK-COUNT bound rather than another byte doubling, because ~32 chunks near the 256 MB per-chunk ceiling means bytes and chunks stop being interchangeable. Anything between is a partial win: report the number, do not round it to "better". **The point of writing this down now is that any of those outcomes can be narrated as success afterwards.**
- **CONFOUND TO NAME IN TOMORROW'S READING, not mine and not a defect:** the same live build (`2332b47b`) also carries `848bcab9`, which WIRED `settled_sample_size_by_sport` into `_sample_credibility` — that had been pinned at its 0.25 floor, making every stake `full_kelly * 0.25 * 0.25` = 1/16 Kelly. Staked dollars were PREDICTED to rise ~3.5-4x and MEASURED at 6.2x -- see the correction below (capped at 3.5% of bankroll per bet; day caps deliberately held at $150.01 so the two effects stay attributable). It is a different subsystem from the accuracy summary, so it should not touch `skipped_budget` — **but it changes what the worker is doing during the run window, so peak `memory_anon_mb` is no longer measured against an unchanged worker.** Compare tomorrow's peak to 1,481.6 with that stated, not silently.
- **CONFOUND NUMBER CORRECTED BY MEASUREMENT: it is 6.2x, NOT the 3.5-4x predicted `[lane mlb-rate-refit, first post-deploy run]`.** `vs_unrestricted_staked` **$19.64 -> $121.85**, and `vs_unrestricted_positions` **4 -> 8**. The under-prediction was structural, not arithmetic: credibility was reasoned about as stake SIZE only, but it also lifts marginal candidates over the `below_min_stake` floor, so the position COUNT doubled as well as each position growing. Per venue: kalshi 1/$4.76 -> 3/$22.09, polymarket 3/$5.38 -> 4/$23.58, novig 1/$6.58 -> 3/$33.65, prophetx 1/$3.86 -> 4/$77.78. Credibility by sport is `{mlb 1.0 (865 settled), wnba 1.0 (66), soccer 0.56 (28), nfl 0.36 (18)}` — the ramp varying by sport's own evidence, not one sport carrying it.
- **THE CONFOUND IS THEREFORE STRONGER THAN I WROTE, AND IT IS NO LONGER ONLY ABOUT TOMORROW'S MEMORY PEAK.** Twice the positions committed at 6.2x the dollars means plan-commit and execution genuinely do more work in the same window, so a higher peak `memory_anon_mb` tomorrow has `848bcab9` as a LIVE candidate cause, not a formality.
- **[RETRACTED 2026-09-04 — see the retraction below; this bullet's causal claim is FALSE and is kept only so the correction has something to point at.]** **AND A SECOND-ORDER EFFECT NEITHER LANE HAD CONNECTED: DOUBLING POSITIONS DOUBLES THE RATE THE EVALUATION LEDGER GROWS, AND THAT LEDGER IS EXACTLY WHAT THE 4 GB BUDGET BOUNDS.** The budget is spent on recommendation records; ~2x positions per cycle means ~2x records per day from here, so the headroom bought by 2 GB -> 4 GB erodes at roughly twice the rate it would have. It does NOT affect tomorrow's reading — tomorrow measures a ledger written mostly under the old 1/16-Kelly regime — but it means `skipped_budget=0` tomorrow is **not** a durable all-clear. **Re-read `skipped_budget` a week out, not just once.** If the pre-registered rule lands at 0 tomorrow and creeps back toward 24 over subsequent days, the cause is this, not a regression in the projection.
- **RETRACTED: THE "2x RECORDS PER DAY" CLAIM ABOVE IS WRONG. `[challenged by lane mlb-rate-refit, settled by reading the code 2026-09-04]`** Their arithmetic was the tell: `records=46944 / dates=8` = **5,868 records per date** against **4 committed positions per date** — ~1,470 records per position, so records plainly do not track positions. **The code confirms it.** The dominant writer is `maybe_record_board_state_to_evaluation_ledger` (`pipeline/intelligence_state.py:3023`), which persists a board-state response's RECOMMENDATIONS — `ranked_all` / `recommendations` / `top_opportunities` — gated on `source_fingerprint` changing. So a record is **one per board recommendation per fingerprint change**, and the board population (~2,027 rows at 15:11Z) is what `848bcab9` did NOT touch. 5,868/2,027 = ~2.9 recordings per row per day.
- **AND THE NEGATIVE THEY WERE UNSURE OF IS CONFIRMED: THERE IS NO PER-ORDER COMPONENT AT ALL.** They allowed that a per-ORDER or per-FILL record would genuinely double, but be ~8 of 5,868 rather than the driver. It is not even that: **[FALSE - CORRECTED BELOW]** ~~`record_recommendation` and `record_portfolio_event` have ZERO production callers~~ — the only caller outside `intelligence_evaluation.py` is `record_prediction`, from `syndicate/blueprints/intelligence.py:2342`. Nothing writes a ledger record per order or per fill, so the component is zero, not small.
- **WHAT THIS MEANS FOR THE PRE-REGISTRATION — the correction matters more than the original claim did.** A wrong cause sitting in a pre-registration is worse than no pre-registration, because it is the first explanation anyone reaches for. So: **if `skipped_budget` creeps back toward 24 over the coming week, `848bcab9` is NOT the explanation.** Look at board row count and at how often `source_fingerprint` changes per day — those two set ledger growth. The week-out re-read is still worth doing; only its expected cause was wrong.
- **CORRECTION TO MY OWN RETRACTION, 2026-09-04: "ZERO PRODUCTION CALLERS" WAS FALSE. I asserted it to a peer and wrote it into `learnings.md` before checking it at the scope I claimed it.** The grep behind it was `grep -v intelligence_evaluation.py`, which excluded the DEFINING FILE and therefore its own internal callers. `build_intelligence_evaluation_bundle` — the exact function `maybe_record_board_state_to_evaluation_ledger` calls with `persist=True` — calls **`record_recommendation` once per recommendation row (`intelligence_evaluation.py:2542`)** and `record_portfolio_event` once per `response["portfolio_events"]` entry (`:2553`). So `record_recommendation` is not uncalled; **it is the PRIMARY writer**, which is what actually produces the 5,868 records/date.
- **THE HEADLINE CONCLUSION SURVIVES AND IS BETTER FOUNDED: a record is one per BOARD RECOMMENDATION per fingerprint change.** 5,868/date over ~2,027 board rows is ~2.9 recordings per row per day. Positions 4 -> 8 still contributes nothing. The peer's arithmetic was right and my retraction of the "2x" claim stands.
- **BUT THE PER-ORDER COMPONENT IS ZERO FOR A FRAGILE REASON, NOT A STRUCTURAL ONE — and the peer's hedge was closer to correct than my confident negative.** They said a per-ORDER record "would be ~8 of 5,868 rather than the driver"; I said it was absent because nothing called the function. The truth is that `record_portfolio_event` IS called, and writes zero rows only because the board-state caller passes `response={"recommendations": ..., "selected_date": ...}` **with no `portfolio_events` key at all** (`pipeline/intelligence_state.py:3073`). **Any caller that ever supplies `portfolio_events` makes the per-order component real.** That is a payload accident, not an architectural guarantee, and it should not be relied on as one.
### catchup-feed-live-terminal — CLOSED 2026-09-04 — **web + live-odds-worker to `f3f4c13c`** (14:56:54Z / 14:56:48Z), mlb feed_live terminal-state fix. Verified by content (`mlb_feed_live_is_refreshable` 0→1) with three earlier fixes re-checked; 16 MLB cards, 0 errors. refresh-worker was owner-held; the money-relevant Kelly stake fix `848bcab9` SHIPPED under that lane and is verified live on `2332b47b`. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: web and live-odds-worker onto `f3f4c13c`. Content they execute:
  `20221619` (mlb feed_live — final is terminal, everything else must be
  refreshed; `cards.py`, `game_state.py`, `home.py`) and `d525a80c` (`#632`
  LAST_RESULT instrumentation).
- **refresh-worker EXCLUDED** — claimed by `mlb-rate-refit` (12 min). Its
  extra commit `848bcab9` ("every stake was 1/16 Kelly, not 1/4") touches
  `pipeline/portfolio_commit.py`, which ONLY refresh-worker runs, and is
  plausibly that lane's own work. **Named because it is money-relevant: the
  stake-sizing correction cannot reach production until that lane ships or
  releases.**
- Files: NONE — deploy only. Does not claim the shared ledger.
- Verification: BY CONTENT on the deployed SHA — `mlb_feed_live_is_refreshable`
  in `game_state.py`, confirmed ABSENT from the currently-live `4597077d`
  (live=0, target=1); plus web serving cards; plus 0 tracebacks.
- Blocked by: none for web/live-odds.


### render-events-truncation-audit — CLOSED-VERIFIED 2026-09-04 — **NO ledger conclusion was drawn from a truncated `render_events.py` run.** One citation is not reproducible as written; its finding re-derives exactly. Two unrelated defects surfaced and are fixed/recorded. Read-only audit — no code changed.
- Goal: answer, with a measurement rather than an argument, whether the
  mid-listing crash fixed in `ea4e3881` had already corrupted anything on record.
- Files: `.syndicate/findings_2026-09-04_render_events_truncation_audit.md` (NEW),
  `.syndicate/state_worker.md` (one stale line), `.syndicate/log/2026-09-04.md`.
- Hypothesis (recorded on completion, not before — the audit is read-only and
  claimed no files while it ran): the crash could only truncate a run whose
  window reached the poison events, so the exposure is bounded and probably empty.
- Falsification test: it would have been WRONG if any cited invocation were bare
  unfiltered text over a July-reaching window AND its conclusion rested on the
  row listing. 17 conclusion-bearing citations checked; that combination occurs
  zero times.
- Verification (RAN, against the PRE-FIX binary, not from source): poison set is
  38 events on all 3 services, last `2026-07-17T19:52:29Z`, tool shipped 08-16.
  `--failures-only` exit 0 / `--type` exit 0 / `--tail 20|500` exit 0 / `--json`
  exit 1 with **no stdout at all** / bare text exit 1 after 288 rows. Crashed
  run's first 25 lines `diff`-identical to the fixed tool's. `log/2026-08-27.md`
  re-derived: 56 kills, both endpoints to the microsecond.
- Blocked by: none.

### catchup-kalshi-doubleheader — CLOSED 2026-09-04 — **live-odds-worker `f3f4c13c`→`de53e367`, live 15:35:10Z.** Verified by content (`_split_doubleheader` 0→2, `event_start_from_ticker` 0→2, budget `4_000_000_000`) with `#624`/`#643` re-checked; 0 errors. **OWED: presence ≠ reachability — `e00c4cbb` exists because `e61600ff` shipped INERT, so a real doubleheader must be read before calling it verified.** refresh-worker owner-held. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: live-odds-worker off `f3f4c13c` onto `de53e367`. **Order-path content on
  the service that TRADES:** `e61600ff` (both halves of every doubleheader were
  invisible to the order path) and `e00c4cbb` (that first fix shipped INERT —
  separate the halves on commence time). Also `b55fa165` (accuracy-summary ledger
  budget 2GB→4GB) and `18bb3031` (`#632` arena time series).
- **refresh-worker EXCLUDED** — claimed by `mlb-rate-refit` (9.5 min). It needs
  `e00c4cbb`/`18bb3031` and stays 2 behind; named, not skipped silently.
  web is current (`25fdd659`, 0 pending).
- Files: NONE — deploy only. Does not claim the shared ledger.
- Verification: BY CONTENT on the deployed SHA — `_split_doubleheader` in
  `kalshi_catalogue.py`, confirmed ABSENT from the currently-live `f3f4c13c`
  (live=0, target=2); plus 0 tracebacks. **Content proves PRESENCE, not
  reachability** — and `e61600ff` shipping inert is precisely why that
  distinction is being written down rather than assumed away.
- Blocked by: none for live-odds-worker.

### render-events-nonzeroexit-bucket — CLOSED-VERIFIED 2026-09-04 — `classify()` names `nonZeroExit` and the row carries the EXIT CODE; 34/34 tests pass, 4 of 6 new ones fail against the prior file (the other 2 are precedence locks, green either way). Local tooling — no deploy. — opened 2026-09-04 — session c4287631-e9e4-4031-a339-70ab087aeabd
- Goal: `classify()` names `nonZeroExit` instead of dropping it in
  `failed:unknown`, and the EXIT CODE is visible on the row. `[user decision
  2026-09-04 — this overrides the "left for the OOM lanes" note in
  findings_2026-09-04_render_events_truncation_audit.md]`
- Files: `scripts/render_events.py`, `tests/test_render_events.py`,
  `.syndicate/findings_2026-09-04_render_events_truncation_audit.md`.
- Measured BEFORE writing the code, full unfiltered reads of all three services:
  **67 events carry `reason.nonZeroExit`** — refresh-worker 12, web 38,
  live-odds-worker 17. It **never** co-occurs with `oomKilled` / `evicted:true`
  / `unhealthy` / `earlyExit` (67/67 pair with `evicted: false` and nothing
  else), so bucket ORDER cannot silently decide which name is shown.
- **Two values, and they are not the same event.** `1` x29 (refresh-worker
  2026-07-24..08-22, live-odds-worker 07-31..08-27) and **`137` x38 (web ONLY,
  2026-06-15..07-09)**. 137 = 128+9 = **SIGKILL**. A single flat bucket would
  bury that, which is the exact failure this file's docstring exists to prevent
  — hence the code goes in the DETAIL, annotated.
- **66 of the 67 are `server_failed`; one is a `job_run_ended`**
  (2026-07-31T01:03:05.175631Z, `job-d9lv7vu417fc73dm37ng`). `classify()`
  returns early for non-`server_failed` and must keep doing so — but its exit
  code is invisible today, so the DETAIL branch is deliberately type-agnostic.
- Falsification test: the new bucket must NOT swallow a genuinely unrecognised
  reason — a `{"someFutureReason": true}` must still be `failed:unknown`, and
  `oomKilled` must still win over a co-occurring `nonZeroExit`.
- Verification (RAN): **34/34 pass**; against the prior file 4 of the 6 new
  tests FAIL (`nonZeroExit` naming, the 137 annotation, the `0` case, the
  `job_run_ended` code) and 2 pass by design — they lock precedence
  (`oomKilled` outranks a co-occurring `nonZeroExit`) and guard that the new
  bucket does not swallow `failed:unknown`. Live: refresh-worker's four
  2026-08-22 rows now read `nonZeroExit  nonZeroExit=1` where they read
  `failed:unknown  raw reason: {...}`; web's cohort renders 38/38 as
  `nonZeroExit=137 (128+9 = SIGKILL)`; the `job_run_ended` keeps its type and
  now shows `nonZeroExit=1`.
- Blocked by: none. Local tooling — no deploy.

### web-sigkill-137-cohort — CLOSED-VERIFIED 2026-09-04 — **the 38 are a bounded CRASH LOOP: not a deploy artifact, not a relabelling, not a restart — all three hypotheses tested and KILLED. web's kill count for 2026-06-15..07-09 was UNDERCOUNTED BY 38 (202, not 164 — 19% low). That they were OOMs is NOT established, and logs cannot settle it (~30d retention).** — opened 2026-09-04 — session c4287631-e9e4-4031-a339-70ab087aeabd
- Goal: say what web's 38 `nonZeroExit=137` events ARE, with a measurement, and
  say plainly if the answer is "not determinable from the events API".
- Files: read-only investigation. `.syndicate/*` for the write-up.
- The observation, from lane `render-events-nonzeroexit-bucket`: web carries 38
  `server_failed` with `reason.nonZeroExit = 137` (128+9 = SIGKILL), ALL between
  2026-06-15T20:09:10Z and 2026-07-09T03:48:19Z, and web's value is ONLY ever
  137 while both workers' is ONLY ever 1. Render did not label any of them
  `oomKilled`, and web's recent kills (4 since 2026-09-02) ARE so labelled, at
  `memoryLimit=2Gi`.
- **HYPOTHESES, written before testing (H1 and H2 are not exclusive):**
  - **H1 — deploy shutdown.** 137 is the old instance being SIGKILLed after it
    failed to exit within the grace period following a deploy. Predicts: each
    137 sits a short, TIGHTLY CLUSTERED interval after a `deploy_started`, and
    the distribution of that delta is much narrower than chance.
  - **H2 — a labelling change.** Render began classifying the same underlying
    kill as `oomKilled` at some point. Predicts: a clean changeover date, with
    137s stopping as `oomKilled` starts, and NO overlap.
  - **H3 — a genuine OOM the platform did not attribute.** Predicts: no deploy
    correlation, and interleaving with `unhealthy` in the way a memory-pressure
    regime does.
- **Falsification, stated per hypothesis:** H1 dies if the 137→preceding-deploy
  deltas are broad or absent. H2 dies if web has `oomKilled` events INSIDE the
  137 window, or 137s after the first `oomKilled`. H3 dies if H1 holds.
- **RESULTS.** H1 DEAD: 13% within 120s, median 1,381s — and the `unhealthy`
  control clusters TIGHTER (31%, median 205s). H2 DEAD: web's first `oomKilled`
  is 2026-06-10, five days BEFORE the first 137, and **77 `oomKilled` sit inside
  the window**; on 2026-07-03 a 137 at 03:33:05Z is followed by `oomKilled` at
  04:05:34Z. H5 (added mid-investigation — the 75 user restarts) DEAD: **0 of
  38** within 300s, median gap 26 hours. What survives is a boot-kill signature:
  70..830s uptime, median 162s, 97% under 10 min, **none over 14 minutes** —
  near-identical to `earlyExit`, unlike `oomKilled` (median 489s, tail 7.9 days).
  Live-commit mapping over 1,900 deploys (19 pages, fully paged): 9 of the 38 ran
  under "compute intelligence … on empty cache" / "surface intelligence
  candidates synchronously", 2 under "Reduce Render Gunicorn concurrency". The
  cohort ends **92s before** `9d259f857 Move intelligence publication to shared
  state` went live. Cause remains INFERRED — logs aged out (~30d; bisected 08-21
  covered / 08-05 HTTP 400, which is a READER failure, not an absence).
  Write-up: `findings_2026-09-04_web_sigkill_137_cohort.md`.
- **METHOD NOTE, load-bearing:** web's unfiltered read HIT THE 100-PAGE CAP
  (10,000 events, oldest 2026-06-05), so "38" and "first 2026-06-15" are LOWER
  BOUNDS until older windows are read explicitly with `--end`. Do that first.
- Blocked by: none. Read-only — no deploy.
### catchup-doubleheader-selfverify — CLOSED 2026-09-04 — **web + live-odds-worker to `60afda80`** (16:10:35Z / 16:13:40Z), verified by content with a token proven to discriminate (`doubleheader_resolved` 0→4). **THE OWED ITEM IS NOT DISCHARGED AND THIS DEPLOY COULD NOT DISCHARGE IT:** the counter is printed at exactly one place, `pipeline/portfolio_commit.py:665`, and `pipeline/` runs on refresh-worker ALONE — which is on `8518a662` and claim-held. web/live-odds compute it and discard it. — opened 2026-09-04 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: web and live-odds-worker onto `60afda80`. **This discharges the OWED item
  I recorded in `catchup-kalshi-doubleheader`**: `60afda80` makes the
  doubleheader fix SELF-VERIFYING rather than watched, so reachability stops
  depending on a human catching a real doubleheader on the board. Also
  `e08a3a0f` (RETRACT the `SYNDICATE_WEB_DYNO` drift — it was an unpaginated
  read).
- **refresh-worker EXCLUDED** — `mlb-rate-refit` has held the claim 44 min. It is
  on `8518a662` and still lacks BOTH the doubleheader fixes and this one; named,
  not skipped silently.
- Files: NONE — deploy only. Does not claim the shared ledger.
- Verification: BY CONTENT with the token taken FROM THE DIFF and PROVEN to
  discriminate (yesterday's rule): `doubleheader_resolved` = 0 on both live SHAs
  (`de53e367`, `25fdd659`), 4 on the target. `unmatched_events` was REJECTED as a
  token — 1 on live, 2 on target, so a pass would have meant nothing.
  Then the real prize: **look for the self-verifying emission in the log stream**,
  which is the reachability reading `catchup-kalshi-doubleheader` said was owed.
- Blocked by: none for web/live-odds.


## Archived lanes (full bodies in `lanes_closed.md`)

> Moved 2026-08-15 to bring this file back under the digest budget.
> Nothing was deleted. Each line points at a full body — including the
> file/line maps and the ORPHANED lanes' resume notes.

- `mlb-prop-oos-calibration` — mlb-prop-oos-calibration — CLOSED-VERIFIED 2026-08-15 — D4 CLOSED: the split ran on production, `batter_hits` is the one verdict that did NOT survive  → `lanes_closed.md`.
- `probability-clamp-removal` — probability-clamp-removal — CLOSED-VERIFIED 2026-08-15 — WNBA site fixed, scored 5/5, shipped as `de0c367f`; the other TWO sites are held by other OPE → `lanes_closed.md`.
- `probability-differential-test` — probability-differential-test — CLOSED-VERIFIED 2026-08-15 — harness + table + owners shipped as `d448a100`; ONE live misprice CONFIRMED in production → `lanes_closed.md`.
- `soccer-backtest-leakage` — soccer-backtest-leakage — CLOSED-VERIFIED 2026-08-14 — **ARCHIVED to `lanes_closed.md`**. Audit §7 #6. HEAD `2dcca4fe`; `50fd7fe2` ALONE IS UNSAFE TO  → `lanes_closed.md`.
- `ask-headline-from-board` — ask-headline-from-board — CLOSED-VERIFIED 2026-08-15 — web `c774fe1a` live 03:29:56Z; B01 delta 0.000 and refusal 4/8 matching its control, both measu → `lanes_closed.md`.
- `recommendation-lane-correctness` — recommendation-lane-correctness — CLOSED-VERIFIED 2026-08-14 — 4 shipped+measured; A3a (`28291eb6`) HELD BACK BY CHOICE, not by doubt — opened 2026-08 → `lanes_closed.md`.
- `soccer-odds-coverage` — soccer-odds-coverage — ORPHANED-CLAIMS-RELEASED 2026-08-15 — claims on `refresh_odds_sources.py` released; the per-league cadence is NOT fixed — opene → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-projection-gap` — soccer-projection-gap — ORPHANED-CLAIMS-RELEASED 2026-08-15 — it claimed NO files; the 30% projection coverage is unchanged — opened 2026-08-14 — sess → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `odds-capture-stall` — odds-capture-stall — CLOSED 2026-08-14 — NOT A DEFECT: the 2h gap IS the configured pregame cadence → `lanes_closed.md`.
- `board-ui-freshness-slip-books` — board-ui-freshness-slip-books — CLOSED 2026-08-14 — all three shipped and verified → `lanes_closed.md`.
- `build-time-estimate` — build-time-estimate — CLOSED 2026-08-14 — board build timed at ~2-4 min on current code; estimator can no longer collapse to ~0 — opened 2026-08-14 —  → `lanes_closed.md`.
- `layer2-board-freshness` — layer2-board-freshness — CLOSED-VERIFIED 2026-08-14 (memory follow-on lives on branch `memory/overview-sum-to-max`, undeployed) — 3h clean window, all → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `anon-allocation-site` — anon-allocation-site — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the lane's OWN FINDINGS ARE NOT CLOSED — opened → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `refresh-worker-anon-leak` — refresh-worker-anon-leak — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the leak itself IS STILL UNEXPLAINED — open → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `quote-join-enrich-cost` — quote-join-enrich-cost — CLOSED 2026-08-14 — all three verification criteria MET → `lanes_closed.md`.
- `checkpoint-witness` — checkpoint-witness — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `checkpoint-guard-scope` — checkpoint-guard-scope — CLOSED-VOID 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `memory-guard-reclaimable` — memory-guard-reclaimable — CLOSED 2026-08-13 — fix VERIFIED, and it uncovered a leak → `lanes_closed.md`.
- `mlb-props-regen` — mlb-props-regen — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `live_refresh_loop.py` released; the props-regen fixes are NOT confirmed shipped — opened 2026 → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `hooks-enforcement-test` — hooks-enforcement-test — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `intelligence-state-red-baseline` — intelligence-state-red-baseline — CLOSED 2026-08-13 — opened 2026-08-13 — session: intel-state-baseline → `lanes_closed.md`.
- `board-transport` — board-transport — CLOSED 2026-08-13 (work measured 08-10/11) → `lanes_closed.md`.
- `sim-execution-observability` — sim-execution-observability — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `soccer-sim-grouping` — soccer-sim-grouping — CLOSED 2026-08-10 — shipped and verified, one thread handed on → `lanes_closed.md`.
- `layer1-live-tier` — layer1-live-tier — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED 2026-08-13 — verified in production → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED — opened 2026-08-13 — session: <name> → `lanes_closed.md`.
- `ask-refusal-gate` — ask-refusal-gate — CLOSED-VERIFIED 2026-08-14 — refusal 3/8 -> 6/8 in production, zero regressions — opened 2026-08-14 — session: ask-audit → `lanes_closed.md`.
- `ask-board-candidates` — ask-board-candidates — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `ask_the_syndicate_data.py` released; M1 SHIPPED but a REVERT OF IT IS STAGED IN GIT — op → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `board-ui-visible-defects` — board-ui-visible-defects — CLOSED-VERIFIED 2026-08-14 — deployed as web `aadcde77`, every criterion measured in production — opened 2026-08-14 — sessi → `lanes_closed.md`.
- `memory-cutover-ship` — memory-cutover-ship — CLOSED-VERIFIED 2026-08-15 — `#387` shipped in TWO halves (`cfee9c6e` + `705eeefc`), sports=8 restored, peak 34.3% of ceiling —  → `lanes_closed.md`.
- `board-contract-absent-not-neutral` — board-contract-absent-not-neutral — ORPHANED-CLAIMS-RELEASED 2026-08-15 — 6 claims released incl. `game_board_contract.py`; partial work IS committed  → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `mlb-oom-outlier-2003z` — mlb-oom-outlier-2003z — CLOSED 2026-08-15 — QUESTION WAS MALFORMED: no outlier, 16 kills that day; H1 falsified — opened 2026-08-15 — session: memory- → `lanes_closed.md`.
- `mlb-hydration-oom-435` — mlb-hydration-oom-435 — CLOSED 2026-08-15 — `build_cards_page_context` is 2 of 6 kills, NOT the common factor — opened 2026-08-15 — session: memory-cu → `lanes_closed.md`.
- `memory-watchdog-435` — memory-watchdog-435 — CLOSED-VERIFIED 2026-08-15 — watchdog + 3 censuses live; ROOT CAUSE FOUND: append-only quote shard, 92.4% superseded, 6.3x read  → `lanes_closed.md`.
- `odds-props-fabricated-probability` — odds-props-fabricated-probability — ORPHANED-CLAIMS-RELEASED 2026-08-15 — the two prop-refresh scripts released; work committed, artifact effect UNMEA → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-card-end-to-end` — soccer-card-end-to-end — CLOSED-VERIFIED 2026-08-15 — deployed as web `7e334509`, every criterion measured in production — opened 2026-08-15 — session → `lanes_closed.md`.
- `model-audit-devig-and-hygiene` — model-audit-devig-and-hygiene — CLOSED-VERIFIED 2026-08-15 — #5 falsified then collapsed for real + D5 done (`2ac3c6bc`, committed, NOT deployed, cons → `lanes_closed.md`.

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

## 2026-08-17 - THE LEDGER IS A RECORD, NOT EVIDENCE (the inverse of the same day's other lesson)

I relayed *"two uncommitted soccer fixes at risk of being lost"* to the
coordinator as an action item. **It came from a lane entry, not from a
measurement.** `git status` was empty and fix #1 was already on main.

**This is the exact inverse of the three errors recorded above it today.** There
I called healthy things BROKEN from a null lookup. Here I called a committed
thing AT RISK from a written claim I never checked. **Same root cause: treating
a statement as a reading.**

`.syndicate/**` records what was true WHEN WRITTEN. This lane was last touched
two days before I quoted it. **Before acting on or forwarding a ledger claim
about the state of the working tree - uncommitted work, missing files, a broken
service - re-measure it.** The cost here was small (a wrong action item, since
retracted). The cost of the reverse - deleting or "rescuing" files on a stale
claim - would not have been.

## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.

## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.



## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.

#### LANE RELEASE — session `bd97b64e` / `7c041356`, 2026-08-18 ~01:4xZ. **ALL HOLDS RELEASED. No file in this repo is claimed by this session any more.**

Released, with status:
- **`wnba-fixture-identity` — CLOSED.** Identity module + 40 tests shipped and on
  `main`. `game_cards` coverage fix proven on the real artifact (1 row → 3).
- **`wnba-phase2-migration` — CLOSED, code shipped, NOT ENABLED.** Autorun
  (`e65a5531`) + tests (`c7494c6c`). Its env keys are live on live-odds-worker
  and **inert until the code deploys**; it then goes hot on the FIRST tick,
  because the flag is already on and `last_epoch=0`.
- **`modelled-fair-edge` — CLOSED.** `edge_vs_modelled_fair_pct` shipped; 228 of
  258 both-terms MLB rows priced on the real payload. **NOT deployed.**
- **`soccer-projection-collapse` — CLOSED, root cause fixed, NOT deployed.**
  `#379`'s widening was inert; its only caller never passed `window_dates`.
- **`wnba-live-tier` — HOLD RELEASED.** I edited exactly ONE file under it,
  `board_enrichment.py`, one call site, on explicit user instruction ("no one has
  it"). **Everything else in that lane is untouched and its other claims stand.**
- **`export-force-refresh-escape` — CLOSED EARLIER BY OVERRIDE** (unattended
  holder, user-authorized). **Its effect measurement is still OWED and was NOT
  discharged by that close.**

**Session markers `.current-lane.7c041356-…` and `.current-lane.bd97b64e-…`
DELETED.** The other markers in that directory belong to other sessions —
including the coordinator's `9ed7fd89` — and were **not touched**.

**WHAT THE NEXT SESSION SHOULD NOT REDO:** everything above is on `main` with
tests. The remaining work is DEPLOY-GATED, not code-gated. Two requests sit with
the coordinator: **Phase 2 WNBA** and the **soccer projection window** (largest
measured effect, and it unblocks ~1,131 of the 1,416 rows the `book_margin_model`
decision was about).



## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.

## Archived lanes (full bodies in `lanes_closed.md`)
- `live-edge-basis` — live-edge-basis — CLOSED-VERIFIED 2026-08-17 — **SHIPPED AND MEASURED. `edge_basis` observed on served rows (refresh-worker `b20072cd`, build 17:44:30 → `lanes_closed.md`.
- `nfl-pbp-root-resolution` — nfl-pbp-root-resolution — **CLOSED 2026-08-16 — resolution mechanism PROVEN CORRECT and the hypothesis FALSIFIED in the same reading. `#441` root caus → `lanes_closed.md`.
- `render-events-reader` — render-events-reader — CLOSED-VERIFIED 2026-08-16 — **`scripts/render_events.py` + `tests/test_render_events.py` SHIPPED TO THE TREE (no deploy — this → `lanes_closed.md`.
- `ui-probe-settle-plateau` — ui-probe-settle-plateau — CLOSED 2026-08-16 — the settle now needs 2400ms of stillness, and a verdict resting on absence says so — opened 2026-08-16 — → `lanes_closed.md`.
- `ui-probe-desktop-height-model` — ui-probe-desktop-height-model — CLOSED 2026-08-16 — desktop is UNFITTABLE, not mis-tuned; measured the floor instead of tuning the threshold — opened  → `lanes_closed.md`.
- `ui-probe-tie-floor-tracking` — ui-probe-tie-floor-tracking — CLOSED 2026-08-16 — floor collected on every row; 5 of 6 stable, mlb mobile fires the rule at 2.06x — opened 2026-08-16  → `lanes_closed.md`.
- `ui-probe-tie-statistic` — ui-probe-tie-statistic — CLOSED 2026-08-16 — implemented as decided; the statistic did NOT help and the instability is the SLATE — opened 2026-08-16 — → `lanes_closed.md`.
- `ui-probe-tracked-statistic-revert` — ui-probe-tracked-statistic-revert — CLOSED 2026-08-16 — reverted to worstGroupPx; exposed and fixed two false alarms that were failing a healthy board → `lanes_closed.md`.
- `branch-overlap-baseline-instrumentation` — branch-overlap-baseline-instrumentation — CLOSED 2026-08-16 — the baseline was sampling hours where the failure does not happen — session: `branch-ove → `lanes_closed.md`.
- `ui-probe-baseline-nfl-ncaaf` — ui-probe-baseline-nfl-ncaaf — CLOSED 2026-08-16 — armed for nfl/ncaaf only; mlb stays watch-only — opened 2026-08-16 — session: ui-probe-rerun-compare → `lanes_closed.md`.
- `mlb-mobile-live-residual` — mlb-mobile-live-residual — CLOSED 2026-08-16 — HYPOTHESIS FALSIFIED; it is a false alarm, the Live fit is convex and `fitRatio` cannot see curvature — → `lanes_closed.md`.
- `branch-overlap-manual-run-marker` — branch-overlap-manual-run-marker — CLOSED — opened 2026-08-16 — session: `branch-overlap-baseline-watch` — verified in production 2026-08-16T19:52:23+ → `lanes_closed.md`.
- `ui-probe-peer-deviation-gate` — ui-probe-peer-deviation-gate — CLOSED 2026-08-16 — one model-free height rule; production green, coverage gap printed — opened 2026-08-16 — session: u → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — UPDATE 2026-08-16 17:5xZ — **DEPLOYED AND FALSIFICATION TEST PASSED. Supersedes this lane's "UNDEPLOYED" line above.** → `lanes_closed.md`.
- `ui-probe-curvature-detection` — ui-probe-curvature-detection — CLOSED 2026-08-16 — `curved` forces `reliable:false`; Preview (the falsification case) is not flagged — opened 2026-08- → `lanes_closed.md`.
- `ui-probe-proportional-budget` — ui-probe-proportional-budget — CLOSED 2026-08-16 — shipped; falsification test FIRED (proportional does not tighten the spread) but it fixes the width → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — **CLOSE REFUSED 2026-08-16 18:0xZ.** Verification is not met, and a NEW production defect was found in this lane's own scope w → `lanes_closed.md`.
- `soccer-live-game-state` — soccer-live-game-state — CLOSED-VERIFIED 2026-08-16 18:56Z — a kicked-off match is no longer `pregame`, and no finished match carries an edge → `lanes_closed.md`.
- `ui-probe-tab-click-race` — ui-probe-tab-click-race — CLOSED 2026-08-16 — cause UNPROVEN and not reproduced; the blindness that made it undiagnosable is fixed — opened 2026-08-16 → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — SCOPE ADDED 2026-08-16 20:0xZ — the HR threshold ladder → `lanes_closed.md`.
- `ui-probe-peer-min-group` — ui-probe-peer-min-group — CLOSED 2026-08-16 — verdicts need n>=3; thin groups reported, never dropped — opened 2026-08-16 — session: ui-probe-rerun-co → `lanes_closed.md`.
- `sim-scheduling` — sim-scheduling — **DEPLOYED AND MEASURED 2026-08-16 21:2xZ.** `#441` verified live; `#445` shipped but unverifiable today; layer2 (both halves) shippe → `lanes_closed.md`.
- `game-shape-capture` — game-shape-capture — UPDATE 2026-08-16 ~23:0xZ (checkpoint) — **PRIMITIVE COMMITTED `af3017e6`; EMIT STILL BLOCKED; HANDOFF SENT** → `lanes_closed.md`.
- `ncaaf-schedule-fallback` — ncaaf-schedule-fallback — **CLOSED-VERIFIED 2026-08-16 — `#445` fixed in `483bb9dd`, on `origin/main`. NOT DEPLOYED (NCAAF opens 08-29)** — opened 202 → `lanes_closed.md`.
- `nfl-pbp-fetcher` — nfl-pbp-fetcher — **CLOSED-VERIFIED 2026-08-16 18:31:15Z — pbp_2025.csv written on the mounted disk (97,951,481 bytes, 46,452 REG plays) and the guard → `lanes_closed.md`.
- `closing-stamp-is-detection-time` — closing-stamp-is-detection-time — CLOSED-VERIFIED — **OUTPUT MEASURED 2026-08-15 22:06 CDT / 2026-08-16 03:06Z. 21/21 new-code stamps precede first pi → `lanes_closed.md`.
- `spread-line-sign-convention` — spread-line-sign-convention — CLOSED-VERIFIED 2026-08-16 — **ARTIFACT OUTPUT NOW MEASURED: 12 of 12 MLB spreads rows correct on the served shortlist ( → `lanes_closed.md`.
- `commit-guard-reads-wrong-index` — commit-guard-reads-wrong-index — CLOSED 2026-08-16 — the guard read the MAIN worktree's index while the commit used another one — session: `live-gamel → `lanes_closed.md`.
- `ask-answer-substance` — ask-answer-substance — **CLOSED-VERIFIED 2026-08-16 — 8 deploys, all measured, live web `9f617f34`. The inline quick ask names a bet a human can place → `lanes_closed.md`.

> Moved 2026-08-15 to bring this file back under the digest budget.
> Nothing was deleted. Each line points at a full body — including the
> file/line maps and the ORPHANED lanes' resume notes.

- `mlb-prop-oos-calibration` — mlb-prop-oos-calibration — CLOSED-VERIFIED 2026-08-15 — D4 CLOSED: the split ran on production, `batter_hits` is the one verdict that did NOT survive  → `lanes_closed.md`.
- `probability-clamp-removal` — probability-clamp-removal — CLOSED-VERIFIED 2026-08-15 — WNBA site fixed, scored 5/5, shipped as `de0c367f`; the other TWO sites are held by other OPE → `lanes_closed.md`.
- `probability-differential-test` — probability-differential-test — CLOSED-VERIFIED 2026-08-15 — harness + table + owners shipped as `d448a100`; ONE live misprice CONFIRMED in production → `lanes_closed.md`.
- `soccer-backtest-leakage` — soccer-backtest-leakage — CLOSED-VERIFIED 2026-08-14 — **ARCHIVED to `lanes_closed.md`**. Audit §7 #6. HEAD `2dcca4fe`; `50fd7fe2` ALONE IS UNSAFE TO  → `lanes_closed.md`.
- `ask-headline-from-board` — ask-headline-from-board — CLOSED-VERIFIED 2026-08-15 — web `c774fe1a` live 03:29:56Z; B01 delta 0.000 and refusal 4/8 matching its control, both measu → `lanes_closed.md`.
- `recommendation-lane-correctness` — recommendation-lane-correctness — CLOSED-VERIFIED 2026-08-14 — 4 shipped+measured; A3a (`28291eb6`) HELD BACK BY CHOICE, not by doubt — opened 2026-08 → `lanes_closed.md`.
- `soccer-odds-coverage` — soccer-odds-coverage — ORPHANED-CLAIMS-RELEASED 2026-08-15 — claims on `refresh_odds_sources.py` released; the per-league cadence is NOT fixed — opene → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-projection-gap` — soccer-projection-gap — ORPHANED-CLAIMS-RELEASED 2026-08-15 — it claimed NO files; the 30% projection coverage is unchanged — opened 2026-08-14 — sess → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `odds-capture-stall` — odds-capture-stall — CLOSED 2026-08-14 — NOT A DEFECT: the 2h gap IS the configured pregame cadence → `lanes_closed.md`.
- `board-ui-freshness-slip-books` — board-ui-freshness-slip-books — CLOSED 2026-08-14 — all three shipped and verified → `lanes_closed.md`.
- `build-time-estimate` — build-time-estimate — CLOSED 2026-08-14 — board build timed at ~2-4 min on current code; estimator can no longer collapse to ~0 — opened 2026-08-14 —  → `lanes_closed.md`.
- `layer2-board-freshness` — layer2-board-freshness — CLOSED-VERIFIED 2026-08-14 (memory follow-on lives on branch `memory/overview-sum-to-max`, undeployed) — 3h clean window, all → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `anon-allocation-site` — anon-allocation-site — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the lane's OWN FINDINGS ARE NOT CLOSED — opened → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `refresh-worker-anon-leak` — refresh-worker-anon-leak — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the leak itself IS STILL UNEXPLAINED — open → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `quote-join-enrich-cost` — quote-join-enrich-cost — CLOSED 2026-08-14 — all three verification criteria MET → `lanes_closed.md`.
- `checkpoint-witness` — checkpoint-witness — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `checkpoint-guard-scope` — checkpoint-guard-scope — CLOSED-VOID 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `memory-guard-reclaimable` — memory-guard-reclaimable — CLOSED 2026-08-13 — fix VERIFIED, and it uncovered a leak → `lanes_closed.md`.
- `mlb-props-regen` — mlb-props-regen — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `live_refresh_loop.py` released; the props-regen fixes are NOT confirmed shipped — opened 2026 → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `hooks-enforcement-test` — hooks-enforcement-test — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `intelligence-state-red-baseline` — intelligence-state-red-baseline — CLOSED 2026-08-13 — opened 2026-08-13 — session: intel-state-baseline → `lanes_closed.md`.
- `board-transport` — board-transport — CLOSED 2026-08-13 (work measured 08-10/11) → `lanes_closed.md`.
- `sim-execution-observability` — sim-execution-observability — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `soccer-sim-grouping` — soccer-sim-grouping — CLOSED 2026-08-10 — shipped and verified, one thread handed on → `lanes_closed.md`.
- `layer1-live-tier` — layer1-live-tier — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED 2026-08-13 — verified in production → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED — opened 2026-08-13 — session: <name> → `lanes_closed.md`.
- `ask-refusal-gate` — ask-refusal-gate — CLOSED-VERIFIED 2026-08-14 — refusal 3/8 -> 6/8 in production, zero regressions — opened 2026-08-14 — session: ask-audit → `lanes_closed.md`.
- `ask-board-candidates` — ask-board-candidates — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `ask_the_syndicate_data.py` released; M1 SHIPPED but a REVERT OF IT IS STAGED IN GIT — op → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `board-ui-visible-defects` — board-ui-visible-defects — CLOSED-VERIFIED 2026-08-14 — deployed as web `aadcde77`, every criterion measured in production — opened 2026-08-14 — sessi → `lanes_closed.md`.
- `memory-cutover-ship` — memory-cutover-ship — CLOSED-VERIFIED 2026-08-15 — `#387` shipped in TWO halves (`cfee9c6e` + `705eeefc`), sports=8 restored, peak 34.3% of ceiling —  → `lanes_closed.md`.
- `board-contract-absent-not-neutral` — board-contract-absent-not-neutral — ORPHANED-CLAIMS-RELEASED 2026-08-15 — 6 claims released incl. `game_board_contract.py`; partial work IS committed  → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `mlb-oom-outlier-2003z` — mlb-oom-outlier-2003z — CLOSED 2026-08-15 — QUESTION WAS MALFORMED: no outlier, 16 kills that day; H1 falsified — opened 2026-08-15 — session: memory- → `lanes_closed.md`.
- `mlb-hydration-oom-435` — mlb-hydration-oom-435 — CLOSED 2026-08-15 — `build_cards_page_context` is 2 of 6 kills, NOT the common factor — opened 2026-08-15 — session: memory-cu → `lanes_closed.md`.
- `memory-watchdog-435` — memory-watchdog-435 — CLOSED-VERIFIED 2026-08-15 — watchdog + 3 censuses live; ROOT CAUSE FOUND: append-only quote shard, 92.4% superseded, 6.3x read  → `lanes_closed.md`.
- `odds-props-fabricated-probability` — odds-props-fabricated-probability — ORPHANED-CLAIMS-RELEASED 2026-08-15 — the two prop-refresh scripts released; work committed, artifact effect UNMEA → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-card-end-to-end` — soccer-card-end-to-end — CLOSED-VERIFIED 2026-08-15 — deployed as web `7e334509`, every criterion measured in production — opened 2026-08-15 — session → `lanes_closed.md`.
- `model-audit-devig-and-hygiene` — model-audit-devig-and-hygiene — CLOSED-VERIFIED 2026-08-15 — #5 falsified then collapsed for real + D5 done (`2ac3c6bc`, committed, NOT deployed, cons → `lanes_closed.md`.
- `nfl-fantasy-projections` — CLOSED-VERIFIED 2026-08-21 — `/nfl/fantasy` live: ESPN-scoring 2026 season+weekly projections, VOR board, and a news layer that captures, accumulates and renders (web `003a5866`)  → `lanes_closed.md`.
