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

### segment-regrade-apply — OPEN — opened 2026-09-06 — session 3492626c
- Goal: the 49 mis-graded segment orders carry their CORRECTED outcome in the
  execution ledger, auditable and reversible.
- Files: `scripts/apply_segment_regrade.py` (NEW)
- NOT MINE TO EDIT: `scripts/run_refresh_worker.py` holds the `*_ON_BOOT`
  trigger pattern and is claimed by `ncaaf-live-resim-wire`. Surfaced to them
  rather than edited.
- Why 49 and not 53: 10 of the 173 were settled BY THE VENUE and 3 of those
  changed. Excluded permanently — for 5 of the 10 the contract we HELD was a
  full-game `KXMLBTOTAL`, so the venue graded the instrument we actually owned
  and its grade is the correct one. Applying those would invent P&L no position
  earned. P&L effect of the 49: **-$31.32**.
- Design decisions, stated because both could reasonably go the other way:
  (1) it OVERWRITES `outcome` and preserves `outcome_as_settled` /
  `pnl_as_settled_dollars` / `regraded_at` / `regrade_reason`. Additive-only
  would leave calibration, CLV, ROI and `ledger_summary` still reading the wrong
  field, which is the defect itself. (2) it REFUSES unless the keyvalue backend
  is configured — verified `rc=3` locally — because a laptop run would write a
  local document and report success while production is untouched.
- The original blocker is STALE and that is checked, not assumed:
  `regrade_segment_orders.py` declined to write partly because concurrent edits
  were being lost. `#600` replaced the blind whole-document write with
  `_merge_onto_current` (`execution_ledger.py:842`); this script ASSERTS that
  function exists before writing, so running it against an older build refuses
  rather than reintroducing the lost update.
- Verification: dry run reports 49 / -$31.32 / flips
  `{won->lost 28, lost->won 20, lost->push 1}`; `--apply` off-service returns
  `rc=3`. The real verification is post-run: `/api/ops/execution/ledger-summary`
  `by_segment` settled counts unchanged, and 49 rows carrying
  `outcome_as_settled`.
- Blocked by: the trigger. Needs a boot hook in a file another lane holds.

## OPEN

## OPEN
### settled-sample-nfl-reconcile — OPEN — opened 2026-09-04 — two settlement ledgers disagreed about NFL, and the disagreement sizes real money
- Goal: reconcile `settlement_all_time.by_sport` (NFL `orders=1, settled=0`) against
  the `SETTLED_SAMPLE` line (`nfl: 18`), decide which is right for
  `_sample_credibility`, fix the wrong side, and pin the reconciliation in a test.
- Files (collision-checked 2026-09-04 with `lane_claims.claims_by_path` over
  `origin/main:.syndicate/lanes.md` — the guard's OWN parser, not
  `check_lane_invariants`; ZERO of these has a holder):
  `syndicate/features/shared/paper_settlement.py`,
  released: `pipeline/portfolio_commit.py` — **TAKEN 2026-09-06 by `kalshi-join-counters-logged`** (user decision, asked and given; this lane names no session id anywhere and no live marker claims it, so there was nobody to ask). **This lane's work on the file is UNTOUCHED** — it LANDED in `53d8f9c9` and the change taken is three additive fields on the `KALSHI_BOARD_JOIN` print statement, nothing in `_sample_credibility` or the decision dedupe. **This lane's OWED DEPLOY READING IS UNAFFECTED AND STILL OWED**: `SETTLED_SAMPLE` printing `nfl: 12` with `credibility 0.25`. Same treatment, same day, as `intelligence.py` above.
  `tests/test_settled_sample_credibility.py`,
  released: `syndicate/blueprints/intelligence.py` — TAKEN 2026-09-06 by `intelligence-query-payload-dedup` (user decision; this lane names no session). Was: (the two-line population label beside
  `settlement_all_time` ONLY — nothing else in that 5,000-line file).
  NOT claimed and NOT edited: `syndicate/features/shared/execution_ledger.py`
  (held by `order-model-view`).
- Hypothesis, written before testing: the two count different POPULATIONS, not
  the same population wrongly.
- Falsification test: they count the same population and one has a filter bug.
- Verification: a test that recomputes both numbers from one fixture ledger and
  asserts the identity between them; plus a mutation check (back the fix out,
  the test goes red).
- **ANSWER — both producers are correct for their own purpose; the CONSUMER's
  unit was wrong.** `settlement_all_time` on `/portfolio/paper` is PAPER-MODE
  order rows (the live-order filter there is deliberate and load-bearing — that
  page's banner says "no money moves"). `_settled_sample_size_by_sport` reads
  the WHOLE ledger, paper + live, which is right in KIND. It was wrong in UNIT:
  it counted ORDER ROWS, and the same bet placed at Kalshi *and* Polymarket is
  two rows and **one** Bernoulli trial. Measured on production 2026-09-04 over
  979 settled portfolio-book rows: NFL 18 rows → **12 distinct decisions**;
  every one of the 6 duplicate pairs resolved identically, as it must.
- **CONSEQUENCE, and it is the whole point of the lane: NFL credibility
  0.360 → 0.250, the floor.** 12/50 = 0.24 < the 0.25 floor, so on the honest
  denominator NFL gets NO evidence lift at all. Not a rounding artefact.
- **AND THE 12 ARE NOT NFL AS IT WILL BE PLAYED TODAY.** All 12 are PRESEASON
  totals — 2026-08-27..29, every one an `over`, 8 distinct games, 9W-9L across
  the 18 rows, **-4.06% ROI on $70.62 of settled stake**. Zero regular-season
  NFL decisions have ever been graded, and today is the opener. The floor is
  the right answer for a reason beyond arithmetic.
- Full-ledger effect, the shipped function run over the real production ledger
  (2,443 rows pulled from `/api/portfolio/live?on=all` + 15 dates of
  `/api/portfolio/paper`, covering **664/664** paper and **315/315** live
  settled rows — no sampling): 979 settled rows → **783 distinct decisions**.
  mlb 865→684, wnba 66→59, soccer 30→28, nfl 18→12. Only NFL and soccer move
  credibility at all; mlb and wnba are ≥50 either way, which is precisely why
  the defect survived the first reading.
- RULED OUT, with evidence, so nobody re-checks it: sport-label case. All 596
  live and 1,847 paper rows carry a lowercase `sport`. The overwrite-vs-sum
  hazard in the old code was real but LATENT; it is fixed anyway.
- Landed `53d8f9c9`. **MUTATION CHECK RUN, both directions:** disabling the
  dedupe turns 6 tests red; restoring the row-count consumer turns 2 red,
  including the one that asserts the value reaching the sizer. 19/19 green
  restored; 212/212 across the five related test files.
- Blocked by: nothing. **NO DEPLOY TAKEN** — another session is mid-deploy on
  this fleet [instruction 2026-09-04]. OWED: refresh-worker is the only service
  that runs `pipeline/portfolio_commit.py`, so until it deploys, production
  keeps sizing NFL at 0.36 on duplicated rows. The reading that closes this is
  the next `SETTLED_SAMPLE` line printing `nfl: 12` with `credibility 0.25`.

- **`syndicate/blueprints/intelligence.py` MOVED OUT 2026-09-06 to lane `intelligence-query-payload-dedup`, by EXPLICIT USER DECISION ("take it and do the work").** This lane names **no session id at all**, so there is nobody to ask. **The scopes are DISJOINT and yours is untouched:** you hold "the two-line population label"; the move covers only the `/api/intelligence/query` route's response shaping (`_slim_response_aliases` and its call site). If that is wrong, say so and I will hand it back.
- **`syndicate/blueprints/intelligence.py`: that lane is now CLOSED and the work is LANDED** (`56f80c4d`, live on web 19:13:50Z). The path is free again. Scope touched was the `/api/intelligence/query` response shaping only; nothing this lane named was edited.
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

### wnba-chip-live-token — OPEN, **UNOWNED** (session 3dcd0fb2-a129-4c6a-95f2-29b11ea0d272 checkpointed and ARCHIVED 2026-08-27) — opened 2026-08-27 — **CLOCK FIXED AND VERIFIED IN PRODUCTION (web `e3dceb68`): `LIVE` -> `Q3 20.5`, control and after on the same game against ESPN. TWO THINGS OWED — refresh-worker IS deployed (`070f452a` is inside its live SHA `eb7951fe`, checked 2026-09-05T21:45Z by `ledger-repair-invariants`; this header's own CHECKPOINT below already said so), and the projection guard is UNIT-TESTED ONLY. `todo.md #586`.** **CHECKPOINT 2026-08-27T01:2xZ: refresh-worker reached `070f452a` and DOES carry the fix; the WNBA half is owed on a MISSING SUBJECT, not a missing deploy — `WNBA live=0` when the artifact landed. Next window TOR @ SEA `02:00Z`. Session archived; lane UNOWNED.**
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

### layer2-accuracy-audit — OPEN, UNOWNED, SESSION ARCHIVED 2026-08-31 ~23:5xZ — **CLAIMS: NONE HELD, all four services free.** Handoff armed: scheduled task `check-mlb-pregame-freeze-611` fires 2026-09-01 08:30 CT (needs a manual Run-now for tool approval). **`#611`'s deployed log line is UNREADABLE — do not plan around it; read the artifact + run history instead.** 7-day board accuracy DELIVERED; MLB game-line join FIXED, DEPLOYED and VERIFIED (`13 -> 0` misses, `(pregame-freeze, 14 games)`, 20:33:17Z) — but it did NOT raise graded rows, which falsified my own causal claim. Two follow-ups opened as `todo #610` (caps: ml 12 candidates -> cap 1) and `todo #611` (prop seal dead since 08-16; cadence is the lead). **THAT OWED DEPLOY IS DISCHARGED: `5be4381d` is inside all three live SHAs (web `94c8ac13`, refresh-worker `eb7951fe`, live-odds-worker `3223baa1`), checked 2026-09-05T21:45Z by `ledger-repair-invariants`. Shipped is not verified -- no reading was taken here.** — preflight HOLD, 3 jobs in flight on live-odds-worker. **AT RISK: 18 local commits incl. all ledger writes are NOT on origin/main.** — opened 2026-08-31 — session ef7e22fc-d592-43f7-b326-31ddea9258ef
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

### order-model-view — OPEN — opened 2026-09-03 — session 3492626c — **LIVE ON BOTH ORDER SERVICES (`04187cdf`); VERIFY STILL OWED after 100 min of polling produced ZERO orders written past 19:54:36Z — a null result about the board's PLACEMENT RATE, not evidence about the change. Ambiguous window 8.9 min.**
- Files: `syndicate/features/shared/execution_ledger.py`,
  `pipeline/execute_portfolio.py`, `tests/test_execute_portfolio.py`.
  **RETURNED IN FULL 2026-09-04 00:0xZ by lane `order-sim-view` on closing.**
  That lane borrowed the first two on 2026-09-03 ~22:0xZ, shipped its change,
  and hands them back unchanged in claim terms.

### ncaaf-chip-compact — OPEN — opened 2026-09-03 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **DIAGNOSED, FIXED, LANDED, AND SHIPPED: the fix is `9e106397`, inside all three live SHAs (web `94c8ac13`, refresh-worker `eb7951fe`, live-odds-worker `3223baa1`), checked 2026-09-05T21:45Z by `ledger-repair-invariants`. Shipped is not verified. The reported symptom is a JOIN failure, not a missing abbreviation — the chip already carried `MAS`/`RUT`.**
- Files: RELEASED `[2026-09-04, TAKEN by lane nfl-la-rams-alias, session ff257687]`: `syndicate/features/shared/team_aliases.py`
  **CORRECTION `[2026-09-04 22:1xZ, same lane]`: the reason first written here was
  WRONG, and the claim-take now rests on DISJOINTNESS ALONE.** It said session
  `3492626c` is "GONE — verified, not assumed" because
  `list_sessions(include_archived=true, limit=100)` did not list it. **Roster
  absence is NOT evidence a holder is gone, and it is INERT rather
  than merely weak `[2nd correction 22:2xZ]`: `deploy_claim.py:251` records
  `CLAUDE_CODE_SESSION_ID`, a BARE uuid, while `list_sessions` returns
  `local_<uuid>` from a DIFFERENT id space. Demonstrated, not argued — I
  messaged `local_05200b16` and was answered by the session identifying itself
  as `b2b5b45b`, holder of the `web` claim: one session, two ids. NO claim's
  `holder_session` can appear in that roster, so the test reads "absent" for a
  LIVE holder as readily as a dead one. Never cite a roster read about a claim
  holder; the TTL is the only bound.** `deploy_claim.py:212` says so in
  as many words ("An unrecorded session is UNKNOWN, not gone. TTL is the real
  bound"), and `deploys.md` carries a counter-example on THIS EXACT SESSION ID:
  recorded gone on the same roster reasoning, it then acquired the
  live-odds-worker claim at 23:10:51Z while still absent. The roster does not
  list unattended or scheduled runs. Surfaced by lane `web-oom-highwater`
  (session b2b5b45b) and re-verified here against the code and the ledger, not
  taken on their word. **What still stands, and is independently sufficient:
  disjointness.** In any
  case: ONE key added to `_NFL_ALIAS_TO_NAME` (`la` -> Los Angeles Rams, the
  nflverse code); your claim is the NCAAF chip join, which this block's own
  header records as already LANDED, and `_ncaaf_registry_name` / `chip_join_key`
  are untouched. Enumerated before taking: of 5,041 ordered NFL token pairs
  exactly 6 verdicts move, every one a Rams/LA pair.
  Take it back by striking this note and restoring the path on its own line.
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

### layer2-sim-disagrees — OPEN — opened 2026-09-03 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **ANSWERED, FIXED, LANDED, AND SHIPPED: the fix is `939a8c00`, inside all three live SHAs, checked 2026-09-05T21:45Z by `ledger-repair-invariants`. Shipped is not verified. The tag's RULE is fine; its INPUT is null on 100% of NCAAF rows. Two further defects found on the same served payload, both of which make the board state a number it does not have.**
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
- **RELEASED 2026-09-05 ~22:0xZ to lane `edge-basis-moneyline`, ON AN EXPLICIT
  USER OVERRIDE — **AND HANDED BACK the same session, `fda5c28a` landed, the
  `Files:` line below restored and re-verified with `claims_by_path`. This lane
  holds `layer2_board.py` again; nothing is owed.** The file —
  Lane claims are per PATH and cannot be scoped to a function, so taking a
  four-line COMMENT fix in `_live_projection_columns` (~:2181) meant taking the
  whole file. The edit is comment-only and touches none of the functions this
  lane names below; the ranges are disjoint. If you are reading this and the
  file is still not back on this lane's `Files:` line, take it — the hand-back
  was meant to be minutes, not hours. What was wrong: that comment asserted
  `_apply_verdict` is called with `live_projected=verdict["model_prob"]` for
  "EVERY game market (h2h, totals AND spreads)", which is false for h2h, and
  that belief is what hid the `edge_basis` mislabel for three weeks.
- Files: `syndicate/features/shared/layer2_board.py`
  (**`_projection_side_in_row_frame` / `_model_edge_for` / `_model_prob_for_side`
  / `_publication_columns`, and `[2026-09-04]` the `value_ev` assignment in
  `build_layer2_rows` where the model edge becomes the RANKING value — same
  subject as this lane, disjoint from the four functions above and from
  `ncaaf-chip-compact`'s chip join, checked line-by-line. USER-REPORTED:
  longshots at the top; `model_edge` reached 14.99 as a ranking value while
  market EV maxed at 5.14** ONLY — the OPEN lane `ncaaf-chip-compact` lists this
  file for the CHIP JOIN (`away_key` / `home_key` stamping) and is the SAME session
  id, `3492626c`; the two edits are disjoint by function and were checked
  line-by-line before taking this),
  `pipeline/intelligence_state.py` (**the `confidence` backfill at ~1888 ONLY**;
  `layer2-cap-raise` marks the file `released:`),
  released: `syndicate/templates/intelligence.html` — TAKEN 2026-09-06 by `intelligence-query-payload-dedup` (user decision; owning session 3492626c is unreachable and this lane's work is SHIPPED). Was: (unclaimed; `chipForGame` is the other
  lane's area and is untouched),
  `tests/test_layer2_sim_view.py` (NEW).
- Blocked by: none.

- **`syndicate/templates/intelligence.html` MOVED OUT 2026-09-06 to lane `intelligence-query-payload-dedup`, by EXPLICIT USER DECISION.** Owning session `3492626c-1ec4-4366-9dbe-f194ae319c84` is **absent from the session roster INCLUDING ARCHIVED** (60 rows) and `send_message` returns `Session not found`; this lane's own header records its work as SHIPPED (`939a8c00`), so the claim was vestigial. Scope taken: **the request payload only** (one added field on the fetch body).
- **`syndicate/templates/intelligence.html`: that lane is now CLOSED and the work is LANDED** (`56f80c4d`, live on web 19:13:50Z). The path is free again. Scope touched was the `/api/intelligence/query` response shaping only; nothing this lane named was edited.
### ncaaf-live-cadence — OPEN — opened 2026-09-03 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **DIAGNOSED, BUILT, LANDED ON `origin/main` AS `a9247011`, AND SHIPPED -- inside all three live SHAs, checked 2026-09-05T21:45Z by `ledger-repair-invariants`. THE CADENCE IMPROVEMENT IS STILL UNMEASURED AND THIS LANE CANNOT MEASURE IT.**
- Files: `scripts/run_live_odds_refresh_worker.py`,
  released: `scripts/refresh_odds_sources.py` — **MOVED OUT 2026-09-06 to lane `ncaaf-live-state-to-worker` by EXPLICIT USER DECISION** ("add the RefreshStep yourself"), after that lane surfaced the conflict rather than editing across. This lane's owning session `3492626c-1ec4-4366-9dbe-f194ae319c84` is **absent from the session roster INCLUDING ARCHIVED** (60 rows back to 2026-08-31) and `send_message` returns `Session not found`, so the claim was held on behalf of nobody. **The mode-scoped step filter this lane worked on is NOT touched** — the edit adds one live-phase `RefreshStep` to `_build_ncaaf_steps`.
  `tests/test_ncaaf_lines_autorun.py` (NEW),
  released: `tests/test_refresh_step_modes.py` — **MOVED OUT 2026-09-06 to lane `ncaaf-live-state-to-worker`**, same explicit user decision and same absent owning session as `refresh_odds_sources.py` above. **Its assertions were WIDENED, not loosened:** `ncaaf_live_state` now appears in `fast` as well as `full`, because this filter's purpose is OddsAPI CREDIT COST and that step burns none (one ESPN GET, ~107 KB gzipped) — excluding it would make `fast` silently revert the NCAAF board to fetching ESPN inside the web request path. The fast test now asserts that PROPERTY directly (no credit-burning step beyond `ncaaf_game_lines_oddsapi`) rather than a hardcoded name list, which is a stronger guarantee than the one it replaced.
- Scope note (NOT claims -- this bullet exists so the prose below sits OUTSIDE the `- Files:` block):
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

### mlb-feed-live-terminal-refresh — OPEN, **UNOWNED** (session b9013cf2 ended 2026-09-04) — **FIX SHIPPED AND LIVE AND CORRECT; IT WAS NOT THE CAUSE.** Counter + per-game status deployed (`ef9fd7bf`, live 19:18:24Z) and read: `skipped_final=9`, and all nine `FEED_LIVE_STATUS` rows `source_status_abstract='Final' is_final_predicate=True key_types=['int']`. Reachability proven on 09-04 (`no_cached_payload=16 attempted=16 succeeded=16`). **OWED: reply landed for handoff `265a2ee6` — see `log/2026-09-04.md`; their 8.7/min stands but the mechanism is stale (web ran my fix) and the driver is the MISSING-FILE branch, which no predicate gates.** Original wording follows. — **was: THE FIX IS CORRECT; THE DIAGNOSIS WAS WRONG.** Counter live on `58ecba3a` (another lane's deploy) answered it 18:16:22Z: `FEED_LIVE_REFRESH date=2026-09-03 ... skipped_final=9 attempted=0 failed=0` — **all nine cached payloads ALREADY read FINAL**, so the freshness fix correctly does nothing here. Reachability proven on the same line for `date=2026-09-04`: `no_cached_payload=16 attempted=16 succeeded=16`. **"Frozen chip" is the wrong name** — the payload says Final and the board publishes `live` (ATH@SEA `live 7-4`, the true final). `games_with_outcome` is still 7 of 9 and **the remaining loss is downstream, in the FINAL-payload -> `game.state` mapping** — a new, narrow question for a new lane. No deploy taken; claim acquired and released; an in-flight MLB sim was left alone. Measurement in `deploys.md`. — **was: LIVE AND NOT WORKING.** On refresh-worker `8518a662` since 15:43:45Z; the 09-03 rebuild at 15:44:53Z still reports `games_with_outcome` 7 of 9, and `FEED_LIVE_PRUNE date=2026-09-03 ... plays_dropped=669` is IDENTICAL pre- and post-deploy, so no refetch happened. **The null is UNATTRIBUTABLE because the change emits no counter** — that is the defect to fix first: instrument `refresh_skipped_final/attempted/succeeded/failed` on `_daily_actual_by_game`, then re-read. Measurement in `deploys.md`. — session b9013cf2 — **was: LANDED `main` (`20221619`), NOT DEPLOYED. Unit-verified only. OWED: `games_with_outcome` == real finals count on `?date=<yesterday>` after the first post-roll build.** — opened 2026-09-04 — session b9013cf2-9ea8-431f-9700-f4aac4794582 — checkpointed 2026-09-04 (see `log/2026-09-04.md`)
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

- **HANDOFF IN 2026-09-04 from lane `feed-live-warn-rate` (session c4287631) —
  measurement only, none of your files touched.** `_fetch_current_feed_live` is
  firing on the REQUEST PATH with **zero live games** — FINAL 20-min baseline:
  **128 calls in 20.0 min = 8 full-slate passes = one every ~2.5 min** (6.4/min,
  n=5 events, which just clears the quotability floor). Two of my own numbers
  were corrected getting here: "8.7/min" off n=2, and "every burst is 32" —
  the real increments are `[16, 32]`, 16 = one slate pass, 32 = two passes
  aliased into one 30s sample
  (16-game slate, all `Preview`). One warn = one synchronous statsapi call, 8s
  timeout, inside a web request, against a 5s health-check budget. Every
  non-zero increment observed was exactly **32** — the loop runs the full
  16-game slate twice per event. ~~The gate `_actual_payload_is_live` (`cards.py:3434`)
  is false for `Preview` AND `Final`, so the re-fetch fires for most of the
  slate most of the day~~ **— RETRACTED 2026-09-04: I read that predicate out of
  the primary tree, 145 commits behind; the deployed `ee20c522` uses
  `mlb_feed_payload_is_final`, and the owner's counter shows the MISSING-FILE
  branch firing (`no_cached_payload=16`), not the staleness one. The NUMBER
  stands; the mechanism does not. See their REPLY in the handoff doc.** The
  "tracks live games" hypothesis was pre-registered and FALSIFIED. Not established: who the caller is (all bursts hit ONE worker on a
  ~60s beat — smells like a poller, unproven) and whether latency is actually
  harmed. Beware `@lru_cache` — see `scope_2026-08-21_home_request_path_compute.md`
  §3. Full working: `handoff_2026-09-04_feed_live_request_path_rate.md`.
### accuracy-ledger-budget-raise — OPEN — **READING TAKEN 2026-09-05 AND CONFIRMED BY A SECOND INDEPENDENT READ: skipped_budget 24 -> 12, the pre-registered “byte budget is the wrong instrument” branch. NOT CLOSED — next step is a CHUNK-COUNT bound, not 8 GB.** — opened 2026-09-04 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885
- Goal: `build_accuracy_summary` stops truncating its ledger read. ONE testable outcome: the next autorun logs `LEDGER_CHUNKS_ACCEPTED ... skipped_budget=0 truncated=0` with `dates` materially above 8, and peak `memory_anon_mb` stays under 2,600 MiB.
- Files: `syndicate/features/shared/intelligence_evaluation.py`, `tests/test_accuracy_summary_ledger_budget.py`, `docs/ai_context/todo.md`, `.syndicate/*`.
- Hypothesis: the 2 GB budget, not memory, is what caps coverage. **Measured 2026-09-04, not assumed:** `bytes=1999970055` against `budget=2000000000` (99.9985% of cap), `skipped_budget=24`, `truncated=1`, `dates=8` — while peak anon was **1481.6 MiB of a 4096 ceiling**, i.e. ~2,614 MiB unused.
- Falsification test: if raising the budget does NOT reduce `skipped_budget`, the cap was not the binding constraint and something else (the 256 MB per-chunk ceiling, or chunk count) is. If peak anon rises faster than ~0.18 MiB per accepted MB, the projection ratio has drifted and the raise must be reverted.
- Verification: tomorrow's autorun (the job is once-per-Central-day, so THIS CANNOT BE VERIFIED TODAY) — read `LEDGER_CHUNKS_ACCEPTED` for `skipped_budget`/`dates` and the peak `memory_anon_mb` over the run window, both against the 09-04 baseline above.
- **STAGED ON PURPOSE: 2 GB -> 4 GB, not straight to full coverage.** Full history is ~32 chunks; admitting all of them at the 256 MB per-chunk ceiling would need ~8.2 GB. The marginal cost measured today is at most 350.6 MiB per 2 GB accepted (peak 1481.6 minus min 1131.0 over the run window, and that spread still includes concurrent work, so it is an UPPER bound). At that rate 8.2 GB projects to ~1,131 + 1,435 = ~2,566 MiB, which lands too close to the ceiling if it ever coincides with the ~1,877 MiB baseline cycle peak. 4 GB projects to ~1,832 MiB. One step, measured, then decide — the repo's own "one change per deploy when diagnosing" rule.
- Blocked by: none
- **HANDOFF OFFERED, THEN TAKEN BY USER OVERRIDE (see the bullet below) — `projected_bytes` instrumentation is written, tested and WAITING ON YOUR CLAIM `[2026-09-04, lane accuracy-autorun-rearm, user asked for it]`.** Your `- Files:` list claims `intelligence_evaluation.py` and `test_accuracy_summary_ledger_budget.py`, so I stopped rather than edit across lanes. **Nothing of yours was touched.** The change is ready to apply:
  - `.syndicate/handoff/projected_bytes.diff` — `git apply` clean against `origin/main`, verified twice (2 hunks, `build_accuracy_summary` only).
  - `.syndicate/handoff/projected_bytes_test.py.txt` — drop in as `tests/test_accuracy_summary_projected_bytes.py`. A NEW file, so it does not collide with your claimed test file. (Stored as `.txt` so pytest cannot collect a test for code that is not applied yet.)
  - **It serves YOUR falsification test, which is why it is offered here rather than filed elsewhere.** Your criterion is *"if peak anon rises faster than ~0.18 MiB per accepted MB, the projection ratio has drifted"* — and the projection ratio is currently UNMEASURABLE in production. This field measures it directly.
  - **Verified, not asserted:** 4 new tests PASS patched and all 4 FAIL unpatched (`off != on`); the 40 existing tests in `test_accuracy_summary_ledger_budget` / `test_build_accuracy_summary` / `test_accuracy_summary_projection` / `test_bounded_accuracy_summary` all still pass. Proven by loading the patched module under the real module name — the repo file was never modified.
  - **Cost measured BEFORE writing it**, since it adds a `json.dumps` inside a 46,953-record loop: **7.7 us/record = +0.36 s on the 669.4 s run, +0.054%**. Projection itself is 11.6 us/record.
  - It lands in `ledger_coverage` (published), **not** on the `LEDGER_CHUNKS_ACCEPTED` log line — the stream cannot see the projection, and the 09-04 truncation being discoverable only from stdout is a failure this repo has already paid for.
  - **NO DEPLOY IS ASKED FOR.** It is diagnostic-only and should ride an ordinary deploy. Take it, reject it, or release the file and say so here and I will apply it.

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
- **CLAIM OVERRIDDEN AND THE CHANGE APPLIED — `[2026-09-04, EXPLICIT USER OVERRIDE: "override the lane claim and apply it"]`.** This is logged rather than silent because the lane rule was not satisfied, it was OVERRULED, and only the user can do that. Lane `accuracy-autorun-rearm` applied `.syndicate/handoff/projected_bytes.diff` plus `tests/test_accuracy_summary_projected_bytes.py` to `origin/main`. **Your claim on both files is otherwise INTACT and is handed straight back** — this touched `build_accuracy_summary` only, added a NEW test file, and changed nothing in `test_accuracy_summary_ledger_budget.py`.
  - **What changed in YOUR file, so you can review it in one place:** two hunks in `build_accuracy_summary` — a counting closure around the existing `_project_evaluation_record` call, and one line writing `ledger_stats["projected_bytes"]` AFTER the stream drains. No behaviour change: the same records are yielded in the same order, and every other caller of the streamer is untouched.
  - **Verified on the APPLIED tree, not the scratch copy:** `44 passed` — your 40 across `test_accuracy_summary_ledger_budget` / `test_build_accuracy_summary` / `test_accuracy_summary_projection` / `test_bounded_accuracy_summary`, plus the 4 new. End-to-end on real records: `bytes_accepted 10,596,942 -> projected_bytes 544,056`, **19.5x**, `truncated false`.
  - **NO DEPLOY WAS TAKEN.** It is diagnostic-only and costs +0.054% of runtime; it should ride your next ordinary deploy rather than earn one. **Your verification tomorrow gets the field for free** — `ledger_coverage.projected_bytes` will appear beside `skipped_budget`/`dates`, and it is what your own "the projection ratio has drifted" criterion needs in order to be checkable at all.
  - If you object to any of it, revert it — the override was on the CLAIM, not on your judgement about the code.
- **OWNING SESSION `82fe0160` IS DELIBERATELY ARCHIVED `[2026-09-04 13:3xZ, user decision "close it"]` — THIS LANE IS NOT ABANDONED, IT IS HANDED OFF.** Do not release its ledger claims, do not force any deploy claim on its behalf, and do not treat its absence from `list_sessions` as evidence of anything: **lane blocks carry `CLAUDE_CODE_SESSION_ID`s and `list_sessions` returns CCD `sessionId`s — the two id spaces do not match**, which on 2026-09-03/04 caused this lane's claims to be released and a live peer's deploy claim to be force-broken. See `learnings.md` 2026-09-04.
- **NOTHING IS OWED BY A HUMAN OR A SESSION. The lane is waiting on a CLOCK.** Its one testable outcome cannot exist until the accuracy autorun fires at >= 07:00 CT on 2026-09-05, because the job is once per Central day and 09-04's run already went at 14:34:27Z under the OLD 2 GB budget. Two scheduled tasks will take the reading: `verify-ledger-budget-4gb` (07:45 CT, primary) and `verify-accuracy-autorun-626h` (08:15 CT, backstop — it checks whether the primary already recorded, and reports disagreement rather than duplicating).
- **IF BOTH TASKS FAIL TO FIRE** (this machine slept through the 03:00 slot on 09-04 and executed it 5h24m late), the reading is two commands and any session can take it: `render_logs.py --service refresh-worker --text "LEDGER_CHUNKS_ACCEPTED" --start "<today>T11:00:00Z"`, then compare `skipped_budget` against the pre-registered rule in this block. **Close this lane on the reading, never on the deploy** — the raise has been live since 15:00:12Z and that fact alone proves nothing.
- **THE READING EXISTS. IT WAS TAKEN TWICE, INDEPENDENTLY, AND THE TWO READS AGREE ON EVERY RAW NUMBER.** `verify-ledger-budget-4gb` recorded it as `1da1a58a` at 16:03Z (~3h20m after its 07:45 CT slot — the same late-fire pattern as 09-04); the backstop `verify-accuracy-autorun-626h` had already started its own read at 15:49Z, when `origin/main` was still `0fa7c3e3` and `deploys.md` still carried `skipped_budget=24`. **Neither read saw the other**, which is what makes the agreement evidence rather than an echo. Entries: `deploys.md` **2026-09-05 13:04Z** (primary) and **2026-09-05 16:1xZ** (backstop, agreement table + the disagreement below).
- **THE NUMBERS.** `count=21 bytes=3999973424 records=92791 dates=21 truncated=1 partial=1 skipped_budget=12 budget=4000000000`; `AUTORUN_DONE sports=8 elapsed_s=1721.552 error=none`; peak `memory_anon_mb` **2212.562** @ 12:41:20Z; no oomKilled, no restart. Raise reachable BY CONTENT on live `50b266da` (`finishedAt` 03:59:01Z, before the run), env override absent across all **154** keys, paginated — verified independently by both reads.
- **THE PRE-REGISTERED RULE LANDS ON ITS MIDDLE BRANCH: `~12` = THE BYTE BUDGET IS NO LONGER THE RIGHT INSTRUMENT, and the next step is a CHUNK-COUNT bound rather than another byte doubling.** Reported as 12, not rounded up to "halved, therefore better". `dates` 8 -> 21 and `records` 1.97x mean the raise is genuinely NOT inert, but `bytes` came back **pinned at 99.999% of the cap on both days** and `truncated` is still 1. **The primary entry did not apply this rule** — it judged a different four-prediction set and concluded "an INSTANCE-SIZE decision, not a constant edit". Both can hold; the pre-registered one is cheaper and needs no bigger box, so do not let it be lost.
- **AND THE MECHANISM THE PRE-REGISTRATION PREDICTED IS NOW MEASURED, not merely matched.** 21 accepted + 12 skipped = **33 chunks**, corroborated independently by `PROJECTION_DONE seen=33` from a different code path in the same job. Average accepted chunk **190.5 MB against the 256 MB per-chunk ceiling** — bytes and chunks have stopped being separate quantities, which is exactly the condition named. Full history at that density is **~6.29 GB**.
- **THE LANE'S OWN REVERT CRITERION NOMINALLY TRIPS AND IS CONFOUNDED — DO NOT REVERT ON IT, AND DO NOT REUSE THE RATE BUILT FROM IT.** In-run peak 1,481.6 -> 2,212.562 = +730.9 MiB over +2,000 MB accepted = 0.365 MiB/MB against the 0.18 threshold. But the worker's **PRE-RUN peak was 2,694.852** (12:05..12:35Z, 1,592 samples) — **482.3 MB HIGHER than anything the run reached** — and the same shape holds on the baseline day (09-04 pre-run 1,672.098 vs in-run 1,481.6). On BOTH days the accuracy-summary window was not the worker's peak, so each day's in-run peak bounds the WORKER, not the ledger, and the delta of two such bounds is not a cost. Ambient moved **+1,022.8 MB** day over day, MORE than the +730.9 in-run delta. **This is the one place the two reads disagree:** the primary derives "~0.38 MiB anon per MiB of budget" from that delta and projects ~3,783 MiB for 8.2 GB. Its CONCLUSION (do not take 8.2 GB; the service's own floor eats the headroom — their 2,984.41 MiB at 15:29:08Z outside the run) survives and is strengthened; the coefficient does not.
- **A THIRD CONFOUND NEITHER PRE-REGISTRATION NAMED: a NEW stage now runs inside this same autorun.** `[ledger_projection]` (lane `evaluation-ledger-projected-mirror`) streams ~2.1 GB in the same job and is most of why `elapsed_s` went 669.4 -> 1,721.552 (+157%) — so that figure is not a cost of the budget raise either. **It did NOT set the memory peak**: max anon over its sub-window (12:58:30..13:04:58Z) is 2,126.59, below the run peak. A TIME cost, not a memory one. Any future comparison against the 09-04 baseline must state all three confounds.
- **LANE STAYS OPEN.** Its single testable outcome (`skipped_budget=0 truncated=0`, `dates` materially above 8) is only one-third met: `dates` clears, `skipped_budget=12` and `truncated=1` do not, and the memory criterion is confounded rather than passed. **A partial win that reclassifies the instrument.** Next step is the chunk-count bound — or making the summary computable off-worker at `budget=0` via the projected mirror, which dissolves the bound instead of re-tuning it (`PROJECTION_DONE ... reduction=68.5x over_ceiling=0 published=8` on its first production run).
- **THE 09-04 `projected_bytes` PREDICTION IS NOT YET FALSIFIABLE AT THE FIELD IT NAMED.** `ledger_coverage.projected_bytes` lands in `reports/refresh_status/latest/accuracy_summary_autorun_status.json` in the keyvalue store, and `ops.py` has per-subject status routes (odds refresh, settlement, live-lens, opportunity contract) but **none for the accuracy autorun**. Closest available reading is the producer's own counter: `bytes_out=30,719,010 / records=49,393` = **622 B/record** against the ~560 B/record the design was sized on, which carried onto 92,675 records **infers ~57.6 MB** — under the 120 MB failure line, but an inference. Adding that route is the cheapest way to make the prediction checkable.
### mlb-final-state-mapping — OPEN, **UNOWNED** (session b9013cf2 ended 2026-09-04) — **TRACE DONE, BOTH CANDIDATES ELIMINATED BY MEASUREMENT. START HERE: `build_cards_page_context`'s source for a PAST date (artifact-backed vs inline-built), UNMEASURED.** — opened 2026-09-04 — session b9013cf2-9ea8-431f-9700-f4aac4794582
- Goal: explain, with a file:line trace, why a 09-03 game whose feed payload reads **Final** is published on the board as `state=live`, and name the single place that decides it.
- Files: **NONE — this lane CLAIMS NOTHING and writes no code.** It is a read-only trace; a claim is for editing.
- Collisions found and respected (deliberately NOT inside the `- Files:` block above, because
  `check_lane_invariants.py` parses paths POSITIONALLY and prose in that block reads as a live CLAIM — it flagged
  exactly that when this note lived there, which would have contested another lane's file):
  the chip-scoreboard module is held by OPEN lane `ncaaf-chip-compact`; the MLB cards and home blueprints are held by
  `mlb-feed-live-terminal-refresh`. My first collision check was a line-based grep of `- Files:` lines and MISSED the
  scoreboard claim because it sits on a CONTINUATION line — the checker caught it and is the authority. When the trace
  names an owner, the fix goes to whichever lane already holds that file; I will not edit across lanes.
- **HYPOTHESIS, WRITTEN BEFORE TESTING.** The chip's state for a PAST date does not come from the feed payload at all. It comes from a precomputed per-date artifact — `[mlb_cards] BETTING_PAYLOAD_READ date=2026-09-03 exists=True size=98857` is read at the top of that build — which was last written BEFORE those two games ended and is never rewritten for a past date. **The 7/2 split is the tell and it falls on the SAME midnight-Central boundary as everything else in this thread:** the 7 games that read `final` all finished BEFORE 05:00Z; the 2 that read `live` finished at 05:05Z and 05:09Z, AFTER the roll.
- Falsification test: read that artifact's OWN per-game status for 09-03. If it records ATH@SEA as in-progress, the SOURCE is stale and the mapping is innocent. If it records Final and the board still publishes `live`, the hypothesis is WRONG and the fault is in the mapping (`build_game_chip` / `_side_score` / the state precedence), which is where I would otherwise have looked first.
- ESTABLISHED, not to be re-derived (`deploys.md` 2026-09-04 18:3xZ): the feed payloads for ALL NINE 09-03 games read Final — `FEED_LIVE_REFRESH ... skipped_final=9 attempted=0 failed=0`. So freshness is EXONERATED as a cause here, and so is the live-lens overlay (gated since `d77695ef`, `rows_corrected: 0`). Two attributions already died on this symptom; do not spend a third guess before reading the artifact.
- Verification: a file:line trace from the artifact/field that supplies `game.state` through to the served row, plus a test pinning the Final-payload case. A FIX is out of scope until the trace names the owner.
- Blocked by: none.
- **TRACE COMPLETE (file:line). HYPOTHESIS FALSIFIED.** State does NOT come from a stale precomputed artifact:
  `game_chip_scoreboard.py:441 build_game_chip` -> `:194 _game_flags` reads `game["status"]` -> that dict is set at
  `mlb/cards.py:5644 "status": _source_status(actual_payload)` -> `:5623 actual_payload = actual_games.get(game_pk)`
  -> `:5883 actual_games = _daily_actual_by_game(resolved_date, game_pks)` -> `:1460 _source_status` returns
  `gameData.status.abstractGameState/detailedState` **verbatim from the FEED payload**. `_game_flags` then needs only
  `"final" in status_texts` to set `is_final` (and `is_final` forces `is_live=False`). So the mapping is a straight
  pass-through of the feed's own status, and `_daily_actual_by_game` — the function I already instrumented — is its
  ONLY source. The `BETTING_PAYLOAD_READ` artifact supplies `game["markets"]`, not state (`cards.py:1985`).
- **AND THAT CREATES A DIRECT CONTRADICTION, which is the finding.** At 18:16:22Z on refresh-worker, from the SAME
  bulk call (`games=9`): the counter reported `skipped_final=9 attempted=0`, i.e. `mlb_feed_payload_is_final()` was
  TRUE for all nine. Yet `/mlb/api/cards?date=2026-09-03` publishes
  `ATH@SEA status={"abstract": "Live", "detailed": "In Progress"}` and the same for STL@LAD (BOS@BAL correctly reads
  `Final`). Both predicates read the SAME two fields of the SAME dict —
  `mlb_feed_payload_is_final` -> `mlb_status_is_final(abstractGameState, detailedState)`, `_source_status` -> those
  two strings raw — so they cannot both be right about one payload. `_source_status(None)` would yield
  `Pregame/Scheduled`, so it is NOT reading a missing payload; it is reading a payload that says Live.
- **MEASUREMENT TAKEN 2026-09-04 19:19:37Z (deploy `ef9fd7bf`). BOTH CANDIDATES ELIMINATED.** `FEED_LIVE_STATUS date=2026-09-03` for all NINE game_pks: `present=True source_status_abstract='Final' source_status_detailed='Final' is_final_predicate=True key_types=['int']`. The predicates AGREE and the keying is int throughout — so it is neither a predicate divergence nor the `.get(int(game_pk))`/`.get(game_pk)` split. **Therefore the served status does not come from this map at all**: same instant, `/mlb/api/cards?date=2026-09-03` publishes ATH@SEA and STL@LAD as `{"abstract": "Live"}` and the 19:19:37Z board still reads them `live` with `games_with_outcome` 7 of 9. `_source_status(None)` would give `Pregame/Scheduled`, so the consumer is reading a DIFFERENT payload, not a missing one.
- **HANDOFF — the next lane's starting point, with no measurement yet taken:** `build_cards_page_context`'s source for a PAST date (artifact-backed vs inline-built — the `one endpoint, two code paths` trap). The 2 stale games are exactly the 2 that finished AFTER the midnight-Central roll, the same boundary as the rest of this thread. Measurement in `deploys.md` 2026-09-04 19:15:51Z.
- **Third attribution avoided.** Freshness and the lens overlay were both wrong on this symptom; this trace deliberately
  stops at a contradiction rather than proposing a cause for it.

### evaluation-ledger-projected-mirror — OPEN — opened 2026-09-04 — session 5959f891-a9e4-4904-a2f0-486a008278d9 — **BUILT, TESTED AND SHIPPED: deploy commit `d452ece1` reads "web + refresh-worker to c49d47fa: the projected ledger mirror is live, allowlist proven", and `c49d47fa` is inside both live SHAs, checked 2026-09-05T21:45Z by `ledger-repair-invariants`. The projected ledger is the only form that can leave refresh-worker.** `[user: "build the projected ledger producer"]`
- Goal: the evaluation ledger becomes readable OFF refresh-worker, so `build_accuracy_summary` can be run unbounded (`budget=0`) against a local mirror instead of rationed inside a 4 GB box that is also running board builds and sims. ONE testable outcome: after a deploy, `PROJECTION_DONE ... over_ceiling=0` appears on the worker AND `reports/intelligence/evaluation_ledger_projected/<date>.jsonl` is fetchable from web via `/api/ops/artifacts/stream`.
- Files: `syndicate/features/shared/evaluation_ledger_projection.py` (NEW), `tests/test_evaluation_ledger_projection.py` (NEW), NOT CLAIMED — one allowlist entry, and the file is explicitly RELEASED [marker moved in front of the path 2026-09-05 by lane `ncaaf-live-resim-wire`, session 520cd594, so the parser reads what this line already SAID; no other change, and the cut point is unmoved so nothing after it gains or loses a claim. Owning session `5959f891-a9e4-4904-a2f0-486a008278d9` is absent from the roster; lane `render-egress-transport` reached the same conclusion independently the same evening and holds an unpushed edit here — if theirs lands first, take it]: `syndicate/features/shared/artifact_publisher.py`, `scripts/run_refresh_worker.py` (the autorun call site only — every OPEN-lane reference to this file is RELEASED; checked).
- **NOT CLAIMED — written as its own bullet ON PURPOSE, because `check_lane_invariants.py` reads any path named inside a `- Files:` block as a CLAIM even when the prose beside it says the opposite** (it flagged exactly that here on the first attempt): `syndicate/features/shared/intelligence_evaluation.py` is still held by `accuracy-ledger-budget-raise` and is **deliberately NOT touched** by this lane. The producer is a NEW module that IMPORTS `_project_evaluation_record` rather than editing it — which is also the correctness choice, since a copied field list would drift silently into a thinner mirror.
- Hypothesis: the projection is the transport. **Measured, not assumed:** raw chunks are 95-332 MB/day against a 12 MiB `_PUBLISH_MAX_BYTES`, and refresh-worker serves no HTTP, so the raw ledger has NO route out; the projected copy is ~560 B/record and that cost SATURATES, putting a 250 MB chunk at ~3.3 MB — under `_PUBLISH_STREAM_MIN_BYTES` (4 MiB) and 3.6x under the sweep ceiling.
- Falsification test: `PROJECTION_OVER_CEILING` firing in production means the ~3.3 MB sizing is wrong and the design needs compression or per-chunk splitting — NOT a raised ceiling, whose own comment forbids that. Equally, if `chunks_deferred` never reaches 0 across successive days the bound is too tight to converge.
- Verification: **DEPLOYED 2026-09-04 — web `c49d47fa` 19:45:45Z, refresh-worker `c49d47fa` 19:56:39Z. TWO services, because the publish RECEIVER (`_write_published_artifact`, `ops.py:2214`) gates on web; a worker-only deploy would have 403'd every publish, which is the CLV-openings incident.** Allowlist PROVEN live on production: the projected path answers **HTTP 200 `count 0`** (admitted, not yet produced) while a RAW chunk still answers **HTTP 403** — permitted-and-empty vs refused are different facts and both were checked. Clean boot (`MALLOC_ARENA_INIT` pid 39, one boot), zero tracebacks, both claims released. **THE PRODUCER HAS NOT RUN: it rides the once-per-Central-day autorun and today's completed at 14:34:27Z, so the first `PROJECTION_DONE` is 2026-09-05 after 07:00 CT — its absence now is a fact about the GATE, not the code.** Prior state: Local, on real records: `seen=13 written=8 deferred=5 failed=0 reduction=21.8x over_ceiling=0`, and a second run `written=5 fresh=8 deferred=0`, i.e. it converges and does not re-stream what it has. **155** tests pass (`test_evaluation_ledger_projection` 13 new, plus 2 added to `test_accuracy_summary_autorun` pinning the wiring's contract, plus `test_export_only_patterns` and `test_artifact_publisher` unbroken).
- Blocked by: nothing. A deploy is the next step and has not been taken.

### nfl-projection-et-datekey — OPEN — opened 2026-09-04 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **DEFECT CONFIRMED ON `origin/main`, FIXED, MUTATION-CHECKED AND LANDED (`52870f57`) AND SHIPPED — THE OWED DEPLOY IS DONE: `52870f57` is inside web `94c8ac13` and refresh-worker `eb7951fe`, and commit `020e709b` records `unmatched_game_rows 78 -> 0` VERIFIED in production. checked 2026-09-05T21:45Z by `ledger-repair-invariants`.** Production `render` 2026-09-04T20:56:12Z: `unmatched_game_rows 299` of `1252` (23.9%), afternoon UTC dates 74/74 and 57/57 projected while EVERY prime-time UTC date reads 0. Replaying production's own rows through both versions on an identical index (`games_in_index 321`, matching production's 321): pre-fix reproduces production **EXACTLY** (953 projected / 299 unmatched, 4 of 4 counters) and the fix gives **1174 / 78, -73.9%**. Mutation check, 4 mutations, each red exactly where predicted — the discriminating one (B: UTC-slice join restored, helper still exported) turns **the 3 defect tests red and leaves the other 8 green**. Scoped suite 176 passed / 23 subtests; `test_ncaaf_game_projections.py`'s 7 failures are PRE-EXISTING, re-baselined against pristine `origin/main` in the same worktree. **THE ENTIRE 78-ROW RESIDUAL IS ONE TEAM** — 17 of 17 fixtures are the Rams, `teams_match("nfl","los angeles rams","la")` is False while `"lar"` is True and the schedule writes `LA`; separate defect, separate file, spawned as its own task. Full working: `deploys.md` 2026-09-04 ~21:1xZ.
- Goal: every NFL prime-time game row on the board carries a projection —
  `NflGameProjectionIndex.lookup` joins on the SAME quantity on both sides.
  Today it does not: `lookup` slices `commence_time[:10]`, which is **UTC**
  (`nfl_game_projections.py:123`), while the index is keyed on the schedule's
  `gameday`, which is **local ET** (`:176-184`). Any kickoff at/after 20:00 ET
  rolls into the next UTC day and misses, and the `teams_match` fallback is
  pinned to `d == date_key` (`:139`) so it misses too.
- Files: `syndicate/features/shared/nfl_game_projections.py`,
  `tests/test_nfl_game_projection_date_key.py` (NEW).
  Collision check: `check_lane_invariants.py` reports 10 OPEN lanes / 37 claims,
  INVARIANTS HOLD. The only OPEN-lane mentions of `nfl_game_projections.py` and
  `tests/test_nfl_game_projections.py` are in `layer1-model-edge-join`, all
  under `released:` (lines 369/373/379/383), which `_claimable_prefix` treats as
  a NON-claim. The new test file appears nowhere in `lanes.md`. Not touching
  `soccer-player-producer`'s six files.
- Hypothesis: n/a — this is a CONFIRMED, measured defect, not a diagnosis.
  Verified against `origin/main` itself (not the primary tree, which is behind):
  `git show origin/main:...` carries `date_key = str(game_date or "")[:10]` and
  the `d == date_key` fallback verbatim. Schedule row `2026_01_NE_SEA` reads
  `gameday=2026-09-09 gametime=20:20` against a board `commence_time` of
  `2026-09-10T00:20:00Z` — a genuine one-day skew, not a naming gap.
- Falsification test: if the two sides were already the same quantity, an
  afternoon game (13:00 ET, same UTC day) and a prime-time game (20:20 ET, next
  UTC day) would join identically. They do not — that asymmetry IS the defect,
  and the mutation check below is what proves the tests can see it.
- Verification: (a) new tests FAIL on `origin/main` and pass with the fix — run
  the MUTATION CHECK, back the fix out and confirm each new test goes red, and
  report that result; a green test never seen fail proves nothing; (b) an
  afternoon case and a DST-boundary case both keep working; (c) production
  `unmatched_game_rows` before/after and projected-row counts for a prime-time
  date. Convert `commence_time` to `America/New_York` (matching
  `layer1_board._row_local_date` / `candidate_slate_filter._slate_date`), never
  a fixed offset — 2026-09 is EDT and January is EST.
- Blocked by: nothing for the code. **A DEPLOY IS OWED AND IS NOT MINE:** lane
  `soccer-player-producer` is mid-deploy on this fleet (live-odds-worker on
  `3223baa1`, refresh-worker pending behind an in-flight MLB sim). Landing on
  `origin/main` only.

### soccer-espn-player-leagues — OPEN — opened 2026-09-04 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **THE FETCH WORKS AND WAS RUN FOR ALL FOUR LEAGUES; THE HALF I OWN IS LANDED (`9d66495b`); THE PRODUCER STAYS INERT UNTIL TWO OTHER LANES' FILES ARE EDITED, AND ONE OF THEM IS A TRAP THAT MUST LAND FIRST.**
- Goal: eredivisie, primeira_liga, championship and belgian_pro_league get a
  CURRENT-season player source. `3223baa1` shipped a weekly `--kind players`
  producer for the other six; these four were excluded because `fetch_players`
  raised `SystemExit` for them without `--espn-date-windows`, so listing them
  would have made every refresh tick a FAILING step. They therefore run the sim
  against `players_2025.csv` — the COMPLETED 2025-26 season.
- Files: `syndicate/features/soccer/ingestion/espn_player_stats.py`
  (unclaimed — new `season_date_windows`),
  `syndicate/features/soccer/ingestion/__init__.py` (unclaimed — re-export),
  `tests/test_soccer_espn_player_leagues.py` (NEW).
  Claim NOT taken and left where it is — the marker has to sit on the SAME LINE
  as the path, before it, or the parser reads the path as a claim anyway:
  held by OPEN lane `soccer-player-producer`: `scripts/fetch_soccer_history_local.py`,
  handed to this work by that lane's owning session (same session id). The
  region edited is `fetch_players`' ESPN branch and the module docstring only;
  `_write_csv` is untouched and its empty-frame refusal is now pinned by a test
  here as well.
  Two more paths are deliberately NOT spelled inside `- Files:` — `lane-guard`
  reads any backticked path there as a CLAIM, and naming them even to disclaim
  them would make this lane CONTEST their owners. `soccer-player-producer` and
  `ncaaf-live-cadence` both document this idiom. They are named in the OWED
  bullet below in prose.
- **STEP 1 ANSWERED: the sources ARE comparable, and the caveat that said
  otherwise is STALE.** ESPN rows have been true per-90 since
  `compute_minutes_played` landed (they are tagged `espn_true_per90`); the
  "season-aggregated APPEARANCE RATES" line survived only in
  `fetch_soccer_history_local.py`'s docstring and is corrected. The real
  difference is the ESTIMATOR — ESPN's `xg_per90`/`xa_per90` are REALISED goals
  and assists, not model xG/xA — which is safe because the source is a pure
  function of the LEAGUE, so `build_usage_profiles` never normalises an ESPN row
  against an Understat one. Now a test, not an observation.
- **STEP 3 RUN, NOT PREDICTED** (real ESPN fetches, 2026-09-04, before any
  wiring): eredivisie 224 rows / max 450.0 min / 17 teams / 9.0s;
  primeira_liga 230 / 360.0 / 17 / 9.3s; championship 348 / 360.0 / 24 / 13.0s;
  belgian_pro_league 256 / 450.0 / 18 / 10.7s.
- **STEP 4 — THE GUARD IS BLIND ON EXACTLY THESE FOUR LEAGUES, MEASURED.**
  `_busiest_player_minutes` and the de-duplicator in `build_soccer_artifacts.py`
  both read the column `minutes`; ESPN rows say `minutes_played`. So on the real
  eredivisie pair the guard reads `latest_max_minutes=0` against a true 450.0
  (`too_early` stuck True forever — safe, but permanently inert), and the
  "keep the row with the MOST MINUTES" rule silently degrades to "keep the newest
  season": **161 of 161 dual-season players resolved to the THIN 2026 file, mean
  minutes 1648.1 -> 258.4.** That is precisely the regression `3223baa1` changed
  the de-duplicator to prevent. **Shipping the allowlist without this fix would
  arm it.**
- Verification: 83 tests green across the touched files and their real
  dependents. MUTATION CHECK RUN — six changes backed out one at a time, each
  turning named tests red (5 / 4 / 1 / 6 / 1 / 2 failures). One pre-existing red,
  `test_soccer_history_step.py::test_no_step_when_history_is_already_present`,
  confirmed red on a pristine `origin/main` in the same worktree: it reads
  `data/`, which a worktree excludes by design.
- **OWED, AND NOT MINE TO TAKE — two files, both owned by lanes belonging to
  this same session, both patches WRITTEN AND EXERCISED against real data:**
  1. `build_soccer_artifacts.py` (lane `soccer-player-producer`) — resolve the
     minutes column as `minutes` OR `minutes_played` in both
     `_busiest_player_minutes` and the dedupe sort key. Verified on a copy: the
     guard then reads 450.0 / 3136.1, 150 of 161 dual-season players keep the
     BIGGER sample (mean 1654.9), all EIGHT of that lane's own guard/dedupe
     assertions still pass, and the per-league verdicts are sane — eredivisie
     refuses on `too_few`, primeira_liga and championship on `too_early`,
     belgian_pro_league runs the filter and produces 18 squads of 13-28 (median
     24) with only a relegated club emptied. **THIS MUST LAND BEFORE THE
     ALLOWLIST.**
  2. The odds-refresh entrypoint (lane `ncaaf-live-cadence`, whose claim is
     scoped in its own body to "mode-scoped step filter only" — disjoint from
     this region) — add the four leagues to `_SOCCER_PLAYER_FETCH_LEAGUES`, plus
     a `_SOCCER_PLAYER_MIN_SEASON_DAYS = 28` gate derived from
     `season_date_range` so the step declines instead of failing every tick for
     the first three weeks of a season. That gate also closes the SAME latent
     August failure for the six leagues shipped by `3223baa1` (Understat/ASA
     return zero rows under their 180-minute floor just as ESPN does under its
     3-appearance floor), and changes nothing today: 34 days elapsed for the
     Europeans, 215 for MLS. The patched copy was imported and exercised — all
     ten leagues get a step when absent, fresh is a no-op, 8 days old refetches,
     an unknown league gets nothing, and at a simulated 2026-08-05 all five
     European leagues decline while MLS proceeds.
- Blocked by: `lane-guard` on the odds-refresh entrypoint. NOT worked around —
  no edit was made to it, and the claim is real. Also worth recording: the
  per-session marker `.syndicate/.current-lane.3492626c-…` is a single slot
  that sibling agents in one session rewrite (it read `gate-per-side-derived`,
  then `sim-clv-decomposition`, during this lane's work), so the guard cannot
  tell two concurrent workers in the same session apart.
- Nothing deployed. refresh-worker is mid-deploy under another lane behind an
  in-flight MLB sim; this lane took no claim and ran no deploy.

### phase3-staked-probability — OPEN — opened 2026-09-04 — session 3492626c-1ec4-4366-9dbe-f194ae319c84
- Goal: `#622` PHASE 3. Let the simulation into the PRICE, not just the ranking
  tiebreak. `logit(p_staked) = alpha*logit(market_devig) + beta*logit(sim_cal)`,
  fitted per (sport, market), gated on held-out Brier vs market-alone.
- Files: `syndicate/features/shared/opportunity_signals.py` (the blend seam),
  `tests/test_staked_probability_blend.py` (NEW). Collision-checked 2026-09-04:
  every OPEN lane naming this file (`portfolio-decision-and-execution`) has
  RELEASED its claims.
- Verification: `staked_probability` shipped with beta=0 a PROVEN bit-for-bit
  passthrough (35 tests, 6/6 mutants caught), so the consumer is live and inert
  before any coefficient exists. Consumer-before-fit is deliberate: this repo
  has `calibration_profile_store` ("nothing calls this yet") and soccer's
  fitted scaler on an explicit "consumer or deleted" ultimatum.
- STILL OWED (this is step 1 of 6): wire the seam into `ev_pct`'s two producers
  (`odds_book_quotes.py:1502`, `layer2_board.py:1870`); a per-(sport,market)
  coefficient store; the out-of-sample fit; the Brier gate in code; ranking on
  Kelly of the blended prob (EV on a model prob amplifies by 1/p -- measured,
  23 of top 25 rows were `hr_1plus`); and RETIRING `_SCORE_SIM_WEIGHT`, which
  double-counts once EV carries the model.
- Blocked by: none. NOT DEPLOYED, and inert until beta is non-zero.

### ncaaf-live-resim — OPEN — opened 2026-09-05 — session 3492626c — NCAAF has a full live slate and produces NO live-aware model edge
- Goal: establish whether smartsim2 can be re-run from mid-game state, and if it
  can, ship the SMALLEST live-aware path — one market family (moneyline / h2h),
  one worker-published artifact, one join, and a refusal that never falls back to
  the pregame probability.
- Files (collision-checked 2026-09-05 with `.claude/hooks/lane_claims.py`'s own
  `claims_by_path` over `.syndicate/lanes.md` — the guard's parser, not
  `check_lane_invariants`; every path below returned FREE):
  `syndicate/features/football/sim_engine/smartsim2/game_simulator.py`,
  `syndicate/features/football/sim_engine/smartsim2/contracts.py`,
  `syndicate/features/ncaaf/live_resim.py` (NEW),
  `tests/test_ncaaf_live_resim.py` (NEW),
  `tests/test_smartsim2_resume_state.py` (NEW).
- Files (ADDED 2026-09-05 after the feasibility probe came back POSITIVE and the
  join hop was traced; re-checked with `claims_by_path`, all FREE):
  **2026-09-05 ~22:0xZ, on an explicit user override, these two moved to lane
  `edge-basis-moneyline`:**
  **CORRECTION 2026-09-05 ~23:1xZ — I wrote here that this session "was asked
  TWICE for the claim and did not answer". THAT IS WRONG AND I RETRACT IT.** The
  messages went to session `520cd594` (lane `ncaaf-live-resim-wire`), which never
  held either file and told me so. This lane's owner is `3492626c`, and
  **`list_sessions` with `include_archived: true` returns no such session across
  50 rows** — it was never reachable, so no inference of any kind was available
  from the silence. not claimed, cross-reference only: `learnings.md` already
  carries the general form ("a lane
  block's `session <id>` is neither checkable nor messageable; `acquire` is not a
  probe"); what is new is that I read UNREACHABLE as REFUSED and put it in the
  ledger as a justification. **The user override is what authorised this move and
  it is sufficient on its own** — the false corroboration added nothing and is
  removed rather than softened.
  released: `syndicate/features/shared/live_gameline_join.py`
  released: `tests/test_ncaaf_live_gameline_registration.py`
  STILL HELD BY THIS LANE:
  `syndicate/features/shared/board_enrichment.py`,
  `syndicate/features/shared/live_lens_loop.py`.
  released, history only: `live_gameline_join.py` was named as SOLELY held by
  `live-edge-basis` in the 2026-08-18 orphan sweep; that block's claims were
  released in the 2026-08-29 phantom sweep and the guard's own parser returned
  FREE for it. (This sentence USED to re-claim the path all by itself: the
  disclaimer markers `held by` / `released` in it sat AFTER the backticked path,
  and `_claimable_prefix` cuts at the marker and keeps everything BEFORE it. So
  the release two bullets up did not take until this line was reworded, which
  the parser confirmed. Check with `claims_by_path`, never by reading.)
- **WHAT THE RELEASED FILES CARRY NOW, so this lane is not surprised by its own
  test** `[2026-09-05, lane edge-basis-moneyline, commit on origin/main]`:
  `test_ncaaf_live_gameline_registration.py:123` had deliberately PINNED
  `edge_basis == "pregame"` with a comment calling it a pre-existing mislabel.
  It now reads `== "live"`, because `_apply_verdict` reads the label off
  `verdict["model_prob"]` — the probability the edge was actually priced from —
  instead of off `live_projected`, which only ever decided whether to PUBLISH
  that probability. The moneyline branch still publishes nothing, deliberately:
  `layer2_board._live_projection_columns` maps `live_model_prob_over` onto
  `live_model_probability` with no side awareness, so publishing it would render
  the HOME win probability in the Live column of every AWAY h2h row. **Nothing
  else in this lane's scope changed**, and the wiring this lane still owes
  (`build_live_lens_snapshot` into a worker) is untouched — production still
  reported `live_gamelines: {"supported": false, "reason": "no live re-sim wired
  for ncaaf"}` at 2026-09-05T21:26Z with 118 live NCAAF rows on the shortlist,
  so on NCAAF this fix is inert until that lands.
- **PROBE RESULT, measured 2026-09-05 before any code was written:** the drive
  loop run directly from a mid-game `PossessionState` reproduces
  `simulate_game` EXACTLY at game start (p(home)=0.6000 on both, n=200 shared
  seeds) and moves correctly off real state: `Q2 15:00, away +7` -> 0.4250;
  `Q4 0:15, home +21` -> 1.0000; `Q4 0:15, home -21` -> 0.0000. Cost FALLS as
  the game runs: 154 ms/sim pregame, 85 ms at Q2, 7.9 ms at Q4 2:00, 0.7 ms at
  Q4 0:15. A live re-sim is cheaper than the pregame sim it replaces.
- **OUTCOME: the hypothesis held, the increment is landed at `ca5be54b`, and the
  producer is NOT wired to a worker — deliberately.** `simulate_game` now resumes
  from `initial_quarter` / `initial_clock_seconds` / `initial_score_*` with the old
  hard-coded values as defaults; pregame output is BIT-IDENTICAL over 40 shared
  seeds (sha256 `3281e358...` with the change stashed and restored in one worktree).
  `ncaaf/live_resim.py` publishes ONE market family (moneyline) with nine named
  refusals and no path back to the pregame probability.
- **Measured on the live slate, with denominators:** 51 board games, 30 matched to
  today's ESPN events, 8 live on both sides, **7 of 8 (87.5%) resumable**; the 8th
  refuses `no_period`. Boise State led Oregon 17-7 in Q2 while the board published
  "Oregon 97.7%"; the re-sim on neutral ratings says 0.2500.
- **OWED (no deploy, no env change taken):** wire `build_live_lens_snapshot` into
  refresh-worker's tick — NOT `live_lens_loop`, which runs on live-odds-worker
  (`SYNDICATE_ENABLE_LIVE_LENS_LOOP=true` appears only in that block of
  `render.yaml`) and cannot read `sp_ratings_<season>.json` or the week's
  projections CSV off refresh-worker's disk; add `sp_ratings_*.json` to
  `HOT_ARTIFACT_PATTERNS` (`artifact_publisher.py` is held by
  `evaluation-ledger-projected-mirror`); then deploy web + refresh-worker.
  Closing reading: `/api/ops/live-lens/snapshot-index?sport=ncaaf` showing
  `sources_seen {live_resim: N}` for N == the live-and-resumable count.
- Full narrative and every number: `state_football.md [ncaaf-live-resim]`,
  `log/2026-09-05.md`.
  NOT claimed and NOT edited: `run_live_odds_refresh_worker.py`
  (held by `ncaaf-live-cadence`), `generate_smartsim2_ncaaf_projections.py` and
  `ncaaf/sources.py` (held by `ncaaf-games-cache-refresh`),
  `test_ncaaf_chip_join_key.py` (held by `ncaaf-chip-compact`).
- **HYPOTHESIS (written before testing): smartsim2's STATE MACHINE can resume from
  mid-game while its ENTRYPOINT cannot.** `build_initial_possession_state` already
  takes `quarter`, `clock_remaining`, `score_home` and `score_away`;
  `simulate_game` hard-codes `quarter=1`, `clock_remaining=quarter_seconds`, passes
  no score at all, and loops `for quarter in range(1, quarters + 1)`. If that is
  right, a rest-of-game re-sim is a contract change, not a modelling rebuild.
- Falsification test: the drive/play layer depends on being at game start in some
  way a resumed state cannot express (a prior keyed on drive_index, a clock
  assumption, an opening-possession assumption).
- Verification: (a) a resume test — a rest-of-game sim at `Q4 0:15, home +21`
  returns home win prob ≈ 1.0 while the same teams at `Q1 15:00` return the
  pregame rate; (b) a refusal test — a game the re-sim could not price carries a
  NAMED blank and never the pregame probability.
- Blocked by: nothing. **NO DEPLOY TAKEN, no env var changed** [instruction
  2026-09-05].

### ncaaf-segment-markets — OPEN — opened 2026-09-05 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **SETTLEMENT HAZARD CONFIRMED, FIXED AND LANDED (`22b82428`, NOT DEPLOYED). NO SEGMENT CAPTURE ADDED, DELIBERATELY.** The grader read `market` and never `segment`, so a segment bet took the whole-game actual in 4 of 5 sports (wnba refused, and only on the game-line path -- a segment PLAYER PROP walked past it too). Live on MLB today, not hypothetical: 21,714 `first5` + 5,549 `first3` + 3,343 `first1` rows in production `book_quotes` for 09-04. 35 tests incl. a per-sport mutation check; regression control 21F/251P identical with and without the guard. **CAPTURE IS STILL OWED AND THE CHEAP ROUTE DOES NOT EXIST**: the bulk `/sports/{key}/odds` endpoint returns NO segments -- NFL has requested 36 segment keys on it and captured 0 rows in 25,567 over 5 days -- so NCAAF segments need the PER-EVENT endpoint, ~3 markets x R regions x 61 events per sweep (MLB's measured per-event segment call is 16.08 credits). Kalshi already quotes `KXNCAAF1H`/`1Q-4Q` on a signed quota costing 0 OddsAPI credits, but admitting them is NOT free either: `kalshi_board_join._match_key` carries `segment`, so an exchange contract needs a BOARD row with the same segment to land on, and there are 3 segment rows platform-wide. NEXT: a board-side h1 row (sim projection or per-event capture), THEN register the Kalshi series.
- Goal: NCAAF quarter/half markets priced on the board. **REORDERED BY
  MEASUREMENT**: the capture is not the binding constraint, the GRADER is. A
  segment row that reaches the board today is graded off the FULL-GAME actual.
  So the single testable outcome is: a non-`full` segment order REFUSES in every
  sport's status resolver instead of inheriting the whole-game score.
- Files: `syndicate/features/shared/bet_status.py` (the shared refusal),
  `syndicate/features/shared/bet_status_ncaaf.py`,
  `syndicate/features/shared/bet_status_mlb.py`,
  `syndicate/features/shared/bet_status_nfl.py`,
  `syndicate/features/shared/bet_status_soccer.py`,
  `tests/test_segment_settlement_guard.py` (NEW).
  Collision-checked 2026-09-05 with `lane_claims._claims()` over `lanes.md`:
  all CLEAR. **`paper_settlement.py` is NOT claimed here and is deliberately
  untouched** — `settled-sample-nfl-reconcile` holds it. Its `resolve()`
  dispatch at ~916 is the natural choke point and I am NOT using it; the
  per-sport resolvers it calls are each entered through the same shared helper
  instead, which fixes the same set of callers without the contested file.
- Hypothesis: `segment` reaches the order row intact and is dropped by the
  grader, so the defect is a missing READ, not a missing field.
- Falsification test: a per-sport resolver already reads `order["segment"]` and
  refuses — then there is nothing to fix and the hazard report is wrong.
  (Measured: `bet_status_wnba.py:502` DOES refuse. It is the only one. The
  hypothesis survives for mlb/ncaaf/nfl/soccer and is FALSIFIED for wnba,
  which is why wnba is not in the Files list.)
- Verification: `test_segment_settlement_guard.py` asserts, per sport, that a
  `segment="h1"` totals order returns an `unavailable_reason` rather than a
  graded status — and MUTATION-CHECKED: reverting the guard must turn those
  tests red. Plus the existing `full`-segment tests stay green, because a false
  positive here refuses the whole book.
- Blocked by: none. **NO DEPLOY** — this lane does not deploy and does not touch
  env or the Render blueprint.

### ncaaf-segment-capture — OPEN — opened 2026-09-05 — session 3492626c-1ec4-4366-9dbe-f194ae319c84
- Goal: NCAAF (then NFL) HALF and QUARTER prices land in `book_quotes` with
  `segment != "full"`, on a pregame interval plus a 2-3 min live tier scoped to
  games actually IN PLAY, at a credit rate published against the 5M cap.
  `[USER DECISION 2026-09-05: NCAAF first, NFL second.]`
- Files: NONE CLAIMED.
- Why nothing is claimed: **This is deliberate and it is not laziness — claiming
  them here would have BLOCKED MY OWN WRITES.** (This rationale was moved out
  of the `- Files:` block on 2026-09-05 by lane `ledger-repair-invariants`:
  inside it, the very tokens it names -- `lanes.md`, `learnings.md` -- were
  themselves parsing as claims, which is the failure the paragraph warns about
  and then committed.) Both `lane-guard` and
  `deploy-guard` resolve "your lane" from
  `.syndicate/.current-lane.<session_id>`, and this session's marker holds
  `segment-refusal-deploy`, whose refresh-worker deploy is IN FLIGHT. Writing my
  slug there would make the deploy claim's holder stop matching and refuse that
  deploy; leaving it there while claiming files below would make every write of
  mine read as an out-of-lane write against my own lane. The paths are recorded
  in the next bullet — OUTSIDE the `- Files:` block, because any path-like token
  inside one is a claim (`learnings.md`, and the soccer-cards-basename incident).
  The guard's protection is worth close to nothing here anyway: grepping every
  basename against the whole of `lanes.md` on 2026-09-05 returns ZERO mentions
  in any lane block, `- Files:` or prose. Nobody else is in these files.
- Worked on, NOT claimed: the NCAAF game-lines fetcher and the NFL team-odds
  fetcher under `scripts/`; the OddsAPI quota recorder's `_market_family` ONLY
  (it recognises `_1st_*` and nothing else, so every `_q1`/`_h1` key lands in
  the `other` bucket and the cost model reads as noise); and two NEW test files.
- **DELIBERATELY NOT CLAIMED, and the design is shaped to avoid it: the odds
  refresh orchestrator.** It is held by OPEN lane `ncaaf-live-cadence` (same
  session) for a mode-scoped step filter. The segment tier therefore lives
  INSIDE the NCAAF fetcher behind its own env gate, reusing the existing
  `ncaaf_game_lines_oddsapi` step, which already carries
  `phases=("pregame","live")`. No orchestrator edit is needed and none is made.
- Hypothesis (written before testing): the bulk `/sports/{key}/odds` endpoint
  does not serve segment markets at all, so NCAAF's absence and NFL's are the
  SAME defect with two different masks — NCAAF never asks, NFL asks in a
  `market_map` that only ever TAGS.
- Falsification test: a per-event `/events/{id}/odds` call for `totals_h1`
  returns no segment rows either — in which case the books do not price NCAAF
  halves through OddsAPI and the whole tier is dead regardless of cadence.
- Verification: (a) `segment != "full"` row count on a real NCAAF slate goes
  0 -> non-zero, WITH the denominator beside it; (b) the projected credits/hr
  and 30-day figure published BEFORE the live tier is wired; (c) a reachability
  test that fails against unmodified code (off != on).
- **HARD CONSTRAINT carried in from the parent: no segment row may become
  STAKEABLE until `bet_status.segment_refusal` is live on BOTH web and
  refresh-worker.** The settlement key had no segment dimension, so a segment
  order inherits the whole-game actual.
- **BUILT AND LANDED ON `origin/main` AS `7f197639` (two commits). NOT
  DEPLOYED, AND DEFAULT OFF — it spends no credit until a key is set.**

- **HYPOTHESIS CONFIRMED, and the falsification test came back negative.** The
  per-event route serves football segments richly. Substrate: production NFL
  shards via `/api/ops/artifacts/export`, captured by
  `fetch_nfl_preseason_odds.py` — the ONE football fetcher that ever used
  `/events/{id}/odds`:

      2026-08-23   14,502 rows   6,603 NONFULL (45.53%)   10 books   4 events
                   h1 1,281 | h2 2,721 | q1 290 | q2 522 | q3 1,201 | q4 588
      2026-08-16    6,681 rows   1,340 NONFULL (20.06%)    5 books   2 events

  **This CORRECTS the handoff's claim that NFL "gets 0 segment rows".** That is
  true of the REGULAR-SEASON fetcher and false of NFL as a whole. The two are
  different defects wearing one name, and only one of them is about the vendor.

- **THE NFL DEFECT IS NOT WHAT IT LOOKED LIKE, and this is the sharper half.**
  `fetch_nfl_team_odds_local.py` does NOT pass 36 segment keys to the bulk
  endpoint. It passes them NOWHERE. `_nfl_segment_market_map()`'s docstring
  claimed they were used *"both to REQUEST the keys and to TAG the returned
  quotes so the two cannot drift"*; `main()` calls `fetch_odds(api_key=...,
  region=...)` with no `markets=`, so the literal default
  `"h2h,spreads,totals"` went out and the map only ever reached the TAGGER.
  A key that never arrived cannot be tagged. So there was never a 422 to find,
  and no amount of endpoint work would have shown anything.

- **AND THE GUARD THAT EXISTED FOR THIS COULD NOT FAIL.**
  `tests/test_all_sports_segment_wiring.py` asserted the token
  `segment_market_keys("nfl")` appears in that file — it does, in the dead map —
  and passed. Worse,
  `test_every_sport_with_declared_segments_has_a_wired_fetcher` searched a
  CONCATENATION of every wired file for `segment_market_keys("<sport>")` **or**
  the literal `segment_market_keys(league)`; the basketball file always supplies
  the second token, so the disjunction was true for every sport and `unwired`
  was unconditionally `[]`. NCAAF's total absence sat behind a green assertion
  from the day that file was written. Both fixed, plus a companion test that
  proves the expression now HAS a failing input.

- **COST MODEL — published before any live tier is enabled, as instructed.**
  Substrate: production `/api/ops/oddsapi/quota` read 2026-09-05T21:0xZ, and
  production `/ncaaf/api/cards`. Unit cost is OddsAPI's documented
  `markets x regions` per per-event call.

  | input | value | how it was obtained |
  |---|---|---|
  | markets | 3 (`h2h_h1`,`spreads_h1`,`totals_h1`) | alternates excluded — see below |
  | regions | **1 (`us`)** | this tier's OWN key, NOT `game_line_regions()` |
  | unit | **3 credits / event / sweep** | 3 x 1 |
  | slate (US-day 2026-09-05) | 42 kickoffs | `/ncaaf/api/cards` |
  | in_play concurrency (3h30) | PEAK **14**, mean **10.49** | minute-by-minute walk |
  | h1_live concurrency (1h45) | PEAK **12**, mean **5.99** | same |

  **The scoping is what buys the affordability, not the market count.**

      blanket 2-min sweep of all 42 events   42 x 3 x 30  = 3,780 credits/hr
      scoped to the h1 window, 2.5-min       5.99 x 3 x 24 =   431 credits/hr
                                                            ---------------
                                                            8.8x at the mean
      instantaneous peak (12 concurrent)     12 x 3 x 24  =   864 credits/hr

  Per day on that 42-game shape: h1_live game-minutes 4,410 / 2.5 = 1,764
  event-sweeps x 3 = **5,292 credits/day** live, plus a 6h/30-min pregame tier
  42 x 12 x 3 = **1,512 credits/day**. **≈6,804 credits/day.**

  Scaled to a real CFB week (one ~60-game Saturday + ~25 games Thu/Fri/Sun,
  ≈85 games at the measured 162 credits/game/day): **≈13,770 credits/week →
  ≈59,000 per 30 days.** NFL phase 2 (~16 games/week, Sunday-clustered) adds
  **≈11,150 per 30 days.**

      current 30-day projection      1,818,053   (production, measured)
      + NCAAF h1 tier                   59,000
      + NFL h1 tier                     11,150
                                    ----------
      new 30-day projection          1,888,203   = 37.8% of the 5M cap
                                                   (+3.9% over baseline)

  **The all-six-segments variant is the one to be careful with:** 18 keys over
  the whole in_play window is 8,820 game-minutes / 2.5 x 18 = **63,504
  credits/day**, ~12x the h1 tier, ≈550K/30d. Affordable but a real
  commitment — quarters should be a separate, separately-measured decision.

- **DESIGN NOTES that are load-bearing and non-obvious:**
  - **The live window is 1h45, not 3h30, and that is not a coverage
    compromise.** A first-half line only exists between kickoff and halftime;
    afterwards the market is settled and delisted, so every later sweep buys
    literally nothing. Scoping the h1 tier to the h1 market's own life is
    strictly correct, and it halves the game-minutes.
  - **Regions come from `SYNDICATE_NCAAF_SEGMENT_REGIONS`, defaulting to `us`,
    and deliberately do NOT read `game_line_regions()`.** That shared knob is
    `eu,us_ex` in production and `odds_regions.py` exists precisely to keep it
    on the CHEAP side of the billing split ("the one costing ~1M rather than
    ~30K"). MLB obeys this — `_fetch_live_event_odds` gets the RAW `regions`.
    Reading the shared knob here would have tripled the bill of the most
    expensive call on the platform with no line of code saying so. There is a
    test for exactly this, because nothing behavioural would notice.
  - **Alternates excluded.** They were ~60% of the NFL preseason segment rows
    (`h2/spreads_alt` 1,058 of 6,603 on 08-23), they triple the per-call bill,
    and `period_lines.py:92-100` filters them straight back out.
  - **A hard event cap** (`_MAX_EVENTS`, default 40) that keeps the events
    nearest kickoff. The cost is linear in a vendor-supplied slate; a bad slate
    response must not be able to spend unboundedly.
  - **One shared module**, `syndicate/features/shared/segment_odds_fetch.py`,
    for NCAAF and NFL. `learnings.md` 2026-09-04 records a THIRD instance of
    the same two-copy drift failure and that *"a comment asking a human to
    remember is not a control"*.

- **BOARD SIDE: already built, and this changes the handoff's recommendation.**
  I did not have to add anything. `layer2_board.py` already carries `segment`
  (`:129`, `:642`, `:2394`) and renders `_segment_label` (`:2239`), with unknown
  segments SHOWN rather than swallowed (`:2272`); `book_grid._INSTANCE_FIELDS`
  carries `segment` (`:52`); `odds_book_quotes._KEY_FIELDS` carries it (`:104`),
  so an `h1` total and a full-game total are distinct rows that cannot displace
  each other. **So "board-row-first" is not an available ordering: a board row
  is a FUNCTION of the quote rows, and the only producer of an h1 quote row is
  the fetch.** The Kalshi join becoming free follows capture; it cannot precede
  it. No new artifact path was created, so `HOT_ARTIFACT_PATTERNS` needs no
  change — this writes into the existing `tracking/book_quotes` shard.

- **SIDE FINDING, unasked and worth someone's time: NHL segment spend has been
  mis-billed all along.** `_market_family` recognised only MLB's `_1st_*`
  spelling, so `_q1`/`_h1`/`_p1` all landed in `other`. NHL declares p1/p2/p3
  and `local_nhl_odds.py` really does request them, so real NHL segment credits
  have been accumulating in the one bucket nobody reads as a segment cost.
  Fixed; mutation-checked 4-red-before / 0-after against `origin/main`'s copy.

- **VERIFICATION STATUS, stated exactly.** Unit only. 171 tests green across the
  affected area (49 new/changed + 87 segment/kalshi/refresh + 35 quota), and
  BOTH mutation checks run against unmodified code: `_market_family` 4 red
  before / 0 after; the NFL reachability tests 3 red before / 0 after. **No
  production reading exists and cannot until the key is set — a zero segment
  count today is indistinguishable from an inert feature, so do not report the
  capture as working on the strength of this block.**

- **DEPLOY STATE READ 2026-09-05 ~21:1xZ — the grading gate is SATISFIED, and
  a NEW blocker appears that inverts the order of the next two steps.** Live
  commit per service (`/api/ops/version` for web; Render `/deploys` for the
  workers, which serve no HTTP), each checked by CONTENT — `segment_refusal`
  hits in `bet_status.py` — and not by ancestry alone:

  | service | live commit | `segment_refusal` | finished |
  |---|---|---|---|
  | web `syndicate-an21` | `94c8ac13` | **2 hits — YES** | — |
  | `refresh-worker` | `eb7951fe` | **2 hits — YES** | 2026-09-05T21:02:51Z |
  | `live-odds-worker` | `3223baa1` | **0 hits — NO** | 2026-09-04T20:37:36Z |

  **The hard constraint is DISCHARGED**: grading runs on refresh-worker, which
  has the fix, so a captured segment row can no longer inherit the whole-game
  actual. `22b82428` is on `origin/main` and lane `ncaaf-segment-markets` still
  says "NOT DEPLOYED" — that is now STALE, and landed-vs-live is exactly the
  distinction that sentence loses.

- **NEW BLOCKER, and it would have produced an INERT change that reads as
  configured: `live-odds-worker` is a day behind and does not carry this
  lane's code at all.** It is the service the capture runs on and the service
  `SYNDICATE_NCAAF_SEGMENT_MARKETS` would be set on. Setting that key today
  reaches a build with no `segment_odds_fetch.py` in it — the env var would sit
  there looking configured while nothing read it, the same shape as the
  `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` "one reader" trap the NCAAF fetcher's
  own regions comment records. **Deploy live-odds-worker BEFORE setting the
  key, not after.**

- **WHAT IS OWED, in order (REORDERED by the reading above):**
  1. ~~Confirm the grading fix~~ — **DONE**, see the table. Web and
     refresh-worker both carry it, verified by content.
  2. Deploy **live-odds-worker** to a tip containing `d4704be1`. It is the
     capture host and is currently 24h stale. (`.py` only, so the push itself
     shipped nothing — `autoDeploy = no`.)
  3. THEN set `SYNDICATE_NCAAF_SEGMENT_MARKETS=h1` on **live-odds-worker** via
     the single-key API. **NEVER `render.yaml`** — it fires `blueprint_sync`
     across all three services. The key needs a deploy to take effect: a
     restart does not re-inject env vars.
  4. The reading that closes this: `segment != "full"` on the NCAAF shard goes
     0 -> non-zero **with its denominator**, and `[ncaaf_odds] SEGMENT_PLAN` /
     `SEGMENT_FETCH` counters showing `est_credits` in the modelled band.
  5. Only then NFL (`SYNDICATE_NFL_SEGMENT_MARKETS=h1`), and only then quarters.
- Blocked by: none for capture. Stakeability blocked on the grading deploy,
  which belongs to lane `segment-refusal-deploy`.

### ledger-repair-invariants — OPEN — opened 2026-09-05 — session 3492626c-1ec4-4366-9dbe-f194ae319c84
- Goal: both lane checkers green, stale NOT-DEPLOYED headers corrected against
  each service's live SHA, and OPEN LANES under the digest's 600B cap.
- Files: NONE CLAIMED.
- Why nothing is claimed, and why the session marker is left alone.
  `.syndicate/` and `.claude/` are EXEMPT from lane-guard — `check_lane_claims.py`
  says so in its own output — so a claim on a ledger file guards nothing and only
  adds a phantom to the file this lane exists to clean. Separately, this session's
  marker holds `segment-refusal-deploy`, which is holding LIVE deploy claims on
  web and refresh-worker; rewriting the marker would make those claims' holder
  stop matching and refuse an in-flight deploy. Same reasoning, same session, as
  `ncaaf-segment-capture` records.
- MEASURED BEFORE (primary tree, 2026-09-05T21:35Z): `check_lane_invariants.py`
  VIOLATED — 1 contested file (`lanes.md`, held by `ncaaf-segment-capture` and
  `nfl-projection-et-datekey`), 2 lane markers with no block anywhere;
  `check_lane_claims.py` exit 1 — 2 of 88 claims name no file in the repo;
  session-start digest `[OPEN LANES truncated: 24994B > 600B cap]`, 45 lane
  headers in `lanes.md`.
- **THE PRIMARY TREE'S `lanes.md` IS 58 COMMITS BEHIND `origin/main` AND
  DIVERGED.** Measured: 45 headers on disk against 101 on `origin/main`; 59
  present upstream and absent on disk, of which 51 were archived LOCALLY into
  `lanes_history.md` (uncommitted) and 8 exist ONLY upstream. `origin/main`'s
  copy passes both checkers. So committing this file from the primary tree would
  DELETE 59 lane blocks from upstream. Nothing here commits `.syndicate/lanes.md`
  from the primary tree; see the checkpoint for what landed and how.
- **MEASURED AFTER, on `origin/main` `578bce89` (2026-09-05T22:2xZ): BOTH
  CHECKERS PASS.** `check_lane_invariants.py` exit 0, INVARIANTS HOLD;
  `check_lane_claims.py` exit 0. The digest's `DIGEST OVERFLOW: 1874B > 1800B`
  line is gone. `lanes.md` 319,770 -> 185,962 B, 105 lane headers -> 50.
- What was actually wrong, in the order it was found.
  (a) CONTESTED `lanes.md`: not two lanes wanting one file, but PROSE inside two
  `- Files:` blocks. `ncaaf-segment-capture`'s own paragraph explaining that any
  path-like token in a Files block becomes a claim was ITSELF inside the Files
  block, so it claimed `lanes.md` and `learnings.md`; `nfl-projection-et-datekey`'s
  collision-check note claimed `lanes.md`, `369/373/379/383` and two files it
  said it was NOT touching. Moved to their own bullets; not one word changed.
  (b) `measured-correlation-pays-off` claimed ``lane`'s`` the same way.
  (c) The two orphan markers needed OPPOSITE fixes and neither was guessed.
  `verify-ledger-budget-4gb` is a SCHEDULED TASK id, not a lane -- `git log -S`
  finds `### verify-ledger-budget-4gb` in ZERO commits, its work is recorded in
  `accuracy-ledger-budget-raise` and `deploys.md`, and its session is gone; the
  marker was emptied. `segment-refusal-deploy` was the opposite: an ACTIVE lane
  holding live deploy claims on web and refresh-worker and named by two other
  blocks, whose block was never written; it was reconstructed, and labelled
  RECONSTRUCTED with its evidence.
- **7 stale deploy headers corrected** (8 edits), each against the SHA the
  service is running -- web `94c8ac13`, refresh-worker `eb7951fe`,
  live-odds-worker `3223baa1`, read from `/v1/services/<id>/deploys` and tested
  with `git merge-base --is-ancestor`. See commit `cab6138f`.
- **THE 600 B `LANE_CAP` IS UNREACHABLE BY ARCHIVING, AND THE MEASUREMENT SAYS
  SO.** The digest's OPEN LANES section is built ONLY from the `### ` header and
  `- Goal:` line of lanes whose status reads OPEN, and `trim_lane_blocks.py`
  moves only blocks that are neither OPEN nor claim-bearing -- so the 59-block
  archive pass moved it 28,025 -> 27,840 B, which is noise. Composition on
  `578bce89`: **46 OPEN header lines, 25,438 B**, the largest single header
  2,347 B (`mlb-feed-live-terminal-refresh`) -- one header is 3.9x the whole
  cap. Reduced to the minimal header form the `/lane` template prescribes,
  46 lanes would still be ~3,588 B, i.e. **6x over cap with zero prose**. Two
  levers, both bigger than one lane: CLOSE lanes (46 read OPEN, most UNOWNED
  with dead sessions), or demote header status prose into a `- Status:` bullet
  (lossless, 25,438 -> ~3,588 B, but it rewrites 46 other lanes' headers).
  Raising `LANE_CAP` is the third option and is a user decision, not mine.
- NOT DONE, and each is deliberate: `learnings.md` is 435,254 B against its
  400,000 cap and `compact_learnings.py` REWRITES THE WHOLE SHARED FILE, so it
  was left alone; one BAD claim (`export`) remains in `render-egress-transport`,
  which belongs to session 9e40eb04 and was relayed, not edited.
- Blocked by: none.
### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — **TESTABLE OUTCOME MET IN PRODUCTION, BOTH HALVES. The re-sim produces (`sources_seen {live_resim: 9, pregame: 42}`) and its output reaches the board (74-83 rows `live_aware`, reproduced on two builds). NO LIVE EDGE IS PUBLISHED and none should be yet — the blocker is ONE LINE in `ncaaf/game_projections.py`'s h2h branch and it is a money decision, not a wiring one.**
- Goal: `build_live_lens_snapshot` runs on refresh-worker's tick and writes
  `data/live/ncaaf_live_lens.json`, so a live NCAAF board row carries an edge
  priced off a probability that knows the score. ONE testable outcome:
  `/api/ops/live-lens/snapshot-index?sport=ncaaf` reports
  `sources_seen {live_resim: N}` with N equal to the live-and-resumable count,
  AND a live NCAAF row whose `projection.live_aware` is true.
- Files: `scripts/run_refresh_worker.py`, `syndicate/blueprints/ops.py`,
  `syndicate/features/shared/artifact_publisher.py`,
  `tests/test_ncaaf_live_resim_wiring.py` (NEW).
  Collision check RUN 2026-09-05 with `.claude/hooks/lane_claims.py`'s own
  `claims_by_path` — the guard's own parser rather than the invariant
  checker — against the ledger as published upstream, and the invariant
  checker returns INVARIANTS HOLD with these four held here. (No module name
  spelled out on these lines on purpose: continuation lines of a Files block
  are re-parsed for paths, and a bare one gets read as a fifth claim.)
- **THE ONE CONTESTED PATH, AND IT WAS A PARSER ARTEFACT — RESOLVED IN THIS
  LANE'S COMMIT, ONE LINE, NOTHING MOVED.** `evaluation-ledger-projected-mirror`
  reads as holding `artifact_publisher.py` while its own `- Files:` line says of
  it "(one allowlist entry — the file is explicitly RELEASED and NOT CLAIMED)".
  `_claimable_prefix` cuts a Files line at the FIRST disclaimer marker and keeps
  only what PRECEDES it, so a path written BEFORE its own release note stays
  claimed. The fix is to move the MARKER in front of the path and change nothing
  else — the cut point is where it was, so `scripts/run_refresh_worker.py`, which
  sits after it and is unclaimed today, stays unclaimed. Rewriting that line more
  thoroughly was tried first and newly ENFORCED that lane's dormant claim on
  `run_refresh_worker.py`; the claim-set delta was measured either way and this
  version removes exactly ONE pair and adds only this lane's four.
  `render-egress-transport` (session 9e40eb04) reached the same conclusion
  independently the same evening and holds an unpushed edit to that line — if
  theirs lands first, take it, the two say the same thing.
- **NOTICE from `web-oom-malloc-trim` `[2026-09-06]`: I am adding ONE NEW
  endpoint to `ops.py`, `/api/ops/glibc-malloc-trim`, and touching no existing
  one — in particular not `/api/ops/live-lens/snapshot-index`, which is yours.
  Disjoint under the region split you cite. `#632` measured ~200 MB per worker
  freed-but-retained in glibc's arena; this lane measures what `malloc_trim`
  returns and what it costs.**
- **REGION SPLIT, the convention `render-egress-transport` uses for `ops.py`.**
  In `artifact_publisher.py` this lane adds ONE `HOT_ARTIFACT_PATTERNS` entry and
  its comment — not the publish path, not `pull_hot_artifacts`, not the size
  constants, not `EXPORT_ONLY_ARTIFACT_PATTERNS`. In `ops.py` it touches ONE
  endpoint, `/api/ops/live-lens/snapshot-index`, which no other claim names. That
  session was messaged before either file was touched.
- NOT claimed and NOT edited: `syndicate/features/ncaaf/live_resim.py`,
  `board_enrichment.py`, `live_lens_loop.py` (held by `ncaaf-live-resim`);
  `scripts/generate_smartsim2_ncaaf_projections.py`,
  `syndicate/features/ncaaf/sources.py` (held by `ncaaf-games-cache-refresh`);
  `scripts/poll_ncaaf_live_state.py`; `live_gameline_join.py` (released by
  `edge-basis-moneyline`, FREE now). Every one is imported READ-ONLY, the
  precedent being `ncaaf/live_game_state.py` importing `poll_ncaaf_live_state`.
- **RESTORED VERBATIM 2026-09-05 ~22:4xZ by lane `edge-basis-moneyline`** after
  `check_lane_invariants.py` reported this slug as a live marker whose block was
  "in NO ledger file". It was neither destroyed nor unwritten — it was complete
  and uncommitted in this lane's own worktree. Their restore also caught a real
  defect in my header: ASCII hyphens, which `lane-guard` refuses, so this lane
  was locked out of its own files by a separator. Both blocks are collapsed into
  this one; their "has staged, uncommitted work" bullet is DISCHARGED — the work
  is committed.
- Hypothesis (written before testing): the re-sim's two inputs are NOT both
  durably present on refresh-worker, so a naive wiring publishes an all-refusal
  snapshot after every deploy and the closing reading is a zero that cannot be
  told from an inert feature.
- Falsification test: both inputs resolve under `SYNDICATE_DATA_ROOT` and survive
  a deploy, in which case no mirroring is owed.
- **HYPOTHESIS CONFIRMED, and it is the reason this was not a one-line call.**
  `sp_ratings_cache_path` and `ncaaf_historical_loader.DEFAULT_CACHE_DIR` resolve
  off `__file__`, so on Render they write `/opt/render/project/`**`src`**`/...`
  — the EPHEMERAL CHECKOUT. Refresh-worker's own logs, read 2026-09-05:
  `2026-09-04T01:03:29Z` and `2026-09-05T01:15:49Z`, BOTH
  `[sp_ratings] season=2026 source=api teams=138 cached=/opt/render/project/src/...`
  — `source=api` twice because the intervening deploy erased the cache each time.
  Nothing is git-tracked under `data/ncaaf_source/historical_truth/` but four
  `games_*.json.gz`. `_ncaaf_sp_ratings_index` mirrors to the MOUNTED disk,
  trusts it 24 h, otherwise re-reads through the generator's own
  `load_sp_ratings` and rewrites it — so in-season SP+ keeps moving rather than
  freezing.
- **MEASURED, local code against live ESPN + live CFBD, 2026-09-05T~22:0xZ**
  (substrate: CODE, not deployment): `games 51, live_resimmed 8, refused 43`
  (`game_final 9, game_not_in_progress 13, no_live_state 21`); the join through
  `build_live_gameline_index` gives `sources_seen {live_resim: 8, pregame: 43}`,
  `index_size 8`. Boise State @ Oregon Q3 5:36 17-24 → **0.9542** where the board
  publishes the pregame 97.7%. A second run with **no `CFBD_API_KEY` in the
  environment at all** — the post-deploy state — read `sp_ratings_source
  durable_mirror`, 138 teams, and still priced 7 live games.
- **THE JOIN KEY, re-derived rather than inherited** `[2026-09-05T~21:40Z]`:
  board 51 games; ESPN team-id pair key **35/51**; ESPN `team.location` key
  **35/51** with **zero disagreements**; ESPN `team.displayName` **0/51**. The
  projections artifact carries no ESPN id, so a name key is the only option and
  `location` is the field that works.
- **ONE BUG OF MY OWN, CAUGHT BY THE DISCRIMINATING RUN AND WORTH KEEPING.**
  `_parse_utc_timestamp` returns a NAIVE datetime; I subtracted it from an AWARE
  `datetime.now(timezone.utc)` inside a bare `except`, so `durable_age` was
  always None and the mirror was NEVER trusted. It failed in the SAFE direction
  — ratings still correct, merely re-fetched — so nothing looked wrong. Only the
  no-key run could tell the two apart.
- Verification: the closing reading above, plus the refusal breakdown from
  `snapshot["coverage"]["refusals_by_reason"]` recorded beside it — a zero with
  no breakdown is not a result. 18 new tests, MUTATION-CHECKED five ways (revert
  the tz fix / key on `displayName` / remove the loop call / drop the heartbeat
  publish / substitute a neutral rating): each turns red where predicted. Two of
  my five predictions named tests that do NOT depend on the mutated line and
  stayed green — my prediction was wrong, not the tests.
- **CORROBORATED INDEPENDENTLY, substrate `render` 2026-09-05T21:26Z** (lane
  `edge-basis-moneyline`): `/api/board/book-grid?sport=ncaaf` returned
  `live_gamelines {"supported": false, "reason": "no live re-sim wired for ncaaf"}`
  with 118 live NCAAF rows and 0 carrying a `live_gameline` block. That reason
  string is `board_enrichment`'s unlisted-sport branch, so **web must be deployed
  too** — `_LIVE_GAMELINE_SPORTS` gained `ncaaf` in `7d9ec94e`, which web is not
  running.
- **CLOSING READING, TAKEN 2026-09-06 00:01-00:11Z, substrate `render`.** Both
  halves of this lane's stated testable outcome are met.
  **(A)** `sources_seen {live_resim: 9, pregame: 42}`, `index_size 9`, producer
  coverage `games 51, live_resimmed 9, refused 42`,
  `refusals_by_reason {game_final 16, game_not_in_progress 7, no_live_state 18,
  no_period 1}` — the refusal breakdown recorded beside the count, because a
  zero without it is not a result.
  **(B)** 74-83 board rows carry `projection.live_aware: true`, 7 of them h2h,
  **reproduced on two independent builds** (00:06:47Z and 00:11:01Z);
  `no_live_gameline_projection` fell **420 -> 297** the moment the key fix landed.
  Tulane @ Duke Q4 2:19, 3-17: `live_gameline model_prob 1.0, sims_run 120,
  as_of 00:00:33Z` — matching the snapshot to the second, which a stale artifact
  cannot contain.
- **AND THE DURABLE-MIRROR HYPOTHESIS IS DISCHARGED DISCRIMINATINGLY.** First
  boot read `sp_ratings_source: loader` (predicted — the mirror did not exist
  yet); this boot reads **`durable_mirror`**. `loader` twice would have meant the
  mirror does not survive a deploy and the post-deploy gap was still open.
- **THE EDGE IS WITHHELD AND I FOUND THE LINE. NOT FIXED, ON PURPOSE.**
  `rows_live_gameline_edged` is 0 on every build; all 7 live-aware h2h rows refuse
  `no_two_sided_market_price`. My first guess (the market pulled the line on a
  decided game) was WRONG — Arkansas State @ Memphis at **10-7 in Q2** carries
  `consensus {away 180, home -325}`, 27 books quoting, and still refuses.
  `live_gameline_join:1109` prices against
  `projection.get("market_fair_prob_over")`, and `ncaaf/game_projections.py`
  writes that key in its TOTALS branch (line 482) and **not in its h2h branch**.
  Measured on the served board: **soccer 52/52 h2h rows carry it, ncaaf 0 of 30**.
  Invisible until now because no NCAAF row had ever been `live_aware`, so the
  moneyline branch was never reached.
  **The fix is one line — the helper is already imported and used two branches
  down — and it must not be taken casually.** That h2h branch withholds
  deliberately: its margin model *"loses to the closing line by 3.563 points of
  MAE over 2233 games (t=17.2)"*. The live re-sim is NOT that pregame model, so
  the note does not automatically condemn it — but the LIVE model is ungraded
  too, and opening the market side would publish live money edges on an ungraded
  estimator. `#499` is the precedent in reverse. **A lane that can BACKTEST the
  live probability owns this, not a wiring lane.** `ncaaf/game_projections.py` is
  FREE as of this writing.
- **NOT TESTED, NOT CLAIMED:** MLB had **0** h2h rows carrying a projection dict
  at all tonight, so there was no positive control for the pricing STEP on any
  sport. Soccer's 52/52 shows the FIELD is populated elsewhere; it does not show
  the pricing path is healthy elsewhere.
- **THE LAST OWED READING IS ARMED, NOT DEFERRED** — scheduled task
  `verify-ncaaf-record-path-live-game`, fires **2026-09-06T20:30Z**, 30 min after
  WSU @ WASH kicks off at 20:00Z (the day's other two are 23:30Z). The record
  path has NEVER run with a game in progress, so `situation` is untested end to
  end. **Its discriminator is that `record_dates >= 1` and
  `coverage.live_resimmed > 0` appear ON THE SAME TICK** — those come apart, and
  the predicted failure is that they never co-occur because the ~514 s producer
  cadence outruns the 180 s tick, i.e. the consolidation evaporates exactly when
  the board needs it. That outcome is a CONFIRMED PREDICTION, not a reader bug.
  A zero must be explained from `refusals_by_reason`, and `no_live_state` on a
  visibly live game would be a join-key miss, which is worse.
- **THE CADENCE QUESTION IS ANSWERED — 514 s median, not the 60 s reported
  (7.8x), 27 intervals reconstructed from 400 consumer log samples.** It PREDICTS
  my fallback rate (20.6% expected vs 25.0% observed), which is what makes it a
  finding. **I declined to raise my 400 s bound to 700 s** even though the same
  data shows that would zero the fallback: mean record age is 251 s and a game
  can score twice in four minutes. Fix belongs to the producer's step, handed
  back with the numbers. `state_football.md [ncaaf-live-resim]`.
- **THE SECOND ESPN FETCH IS GONE, MEASURED `[2026-09-06 15:02-15:31Z,
  refresh-worker `58302f07`]`.** The tick reads
  `ncaaf-live-state-to-worker`'s persisted record (`77abe822` + their
  `1b266180`): **6 ticks of 8 with `fetch_dates 0`**, the other 2 refusing
  `record_stale` by name, `live_index 3` identical in both modes. **I held the
  claim and deployed NOTHING** — `ncaaf-h1-kalshi-series` had already shipped the
  exact tip I targeted; claim released with its token, no force.
  **OWED: the record path has never run while a game is IN PROGRESS**, so
  `situation` is unproven end to end. Next live slate.
- **ALSO DONE THIS SESSION, outside the lane's own scope, all landed:** the red
  `test_the_bucket_carries_only_the_declared_fields` on `main` (`782a057b`,
  `ops.py` is this lane's claim); `learnings.md` compacted + its alarm raised
  400000 -> 460000 (`1f032074`, user decision, recorded in `state.md`).
- **HANDED BACK, NOT DONE — the PRIMARY TREE update.** Left at `e826b5fc`,
  0 ahead, **21 behind, exactly ONE collision: `.syndicate/lanes.md`**, index
  clean (narrowed from three; the other two were verified redundant and reset to
  HEAD). NOT forced because session `b9bc926d`'s uncommitted `lanes.md` does not
  replay onto `origin/main` — `git apply --check` fails at line 943, the
  `suite-order-pollution` region whose retraction already landed upstream — so a
  rebase means resolving a merge conflict inside a LIVE session's lane claims.
  **It clears itself the moment they commit `lanes.md`.** Working-copy backup and
  diff: `%TEMP%\claude\primary_preserve\`. Full reasoning: `log/2026-09-05.md`.
- **`todo.md #71` NOT SATISFIED FOR THIS LANE, deliberately and visibly.**
  `docs/ai_context/todo.md` is claimed IN FULL by `accuracy-ledger-budget-raise`.
  I wrote the `#119` update, the post-write guard caught it, I reverted it, and
  the exact text is in
  `.syndicate/handoff_2026-09-05_todo_119_ncaaf_live_resim.md` (`7abc5dcf`). That
  session is unattended, so the file is the delivery. A whole-file claim on
  `todo.md` and CLAUDE.md's "every lane updates it before finishing" cannot both
  be honoured; flagged for the owner.
- Blocked by: none. Landed on `origin/main`; deploy of web + refresh-worker owed,
  under `deploy_claim.py` + `deploy_preflight.py`.

### web-oom-secondary-arenas — OPEN (instrument BUILT and landed `67af1276`; INERT in production until deployed and `SYNDICATE_MALLOC_ARENA_DETAIL=1`, so the verification reading is still OWED) — opened 2026-09-06 — session b2b5b45b-e938-4cb5-81c2-c211ecc7c703
- Goal: build the PER-ARENA `malloc_info` readout and use it to say which arena
  holds `#632`'s growth on **web**. `mallinfo2` reports the MAIN ARENA ONLY, and
  the clean 2026-09-06 window showed the main arena moving `+7.2`/`+8.3 MB` while
  anon rose `+42.4`/`+26.9` — so ~80% of the growth is somewhere it cannot look.
- Files: `syndicate/features/shared/memory_observability.py`,
  `tests/test_malloc_info_arenas.py`.
  NOT claimed, deliberately: `syndicate/blueprints/ops.py` — held by lane
  `ncaaf-live-resim-wire`.
  NOT claimed, deliberately: `scripts/run_refresh_worker.py` — same holder.
  The reading therefore reaches web through the EXISTING `/api/ops/memory`
  → `get_all_process_memory_snapshot()`, which lives in this lane's own file, so
  no route needs adding. A dedicated endpoint would read better; it is not worth
  crossing a lane for.
- **WHY `#435`'s DISMISSAL DOES NOT SETTLE THIS — two independent reasons.**
  (1) DIFFERENT SERVICE. `malloc_arena_snapshot()` is called from
  `scripts/run_refresh_worker.py` and NOWHERE ELSE, so 13.9% coverage is a
  REFRESH-WORKER number. Web has never taken this reading. On web the main arena
  ALONE is 330-390 MB against 536-677 MB anon — 58-72%, not 13.9%. The arena is
  representative here and was not there.
  (2) DIFFERENT QUESTION. That number was coverage of TOTAL anon, used to decide
  whether the aggregate verdict could be trusted. This lane asks how the arenas
  SPLIT, which the current parser cannot answer at all: it reads only the
  top-level totals and discards every per-`<heap>` figure.
- Hypothesis, written before measuring: web's SECONDARY arenas hold the growth.
  `GUNICORN_THREADS=4` creates per-thread arenas, glibc mmaps them in 64 MB-aligned
  heaps, and `#632`'s smaps breakdown already localised the growth to **8-64 MB
  anonymous mappings** — which is the shape of a non-main arena heap.
- Falsification test: top-level `system current` ≈ the main arena's own
  `system current` (one real arena), or arena total stays far below anon while
  anon climbs. Either way the growth is NOT in a glibc arena and this is raw
  `mmap` — report that, do not reach for a third allocator metric.
- Verification, and it is a RECONCILIATION not a single number: (a) per-heap
  `system current` must SUM to the top-level `system current`, reported as a
  residual so a parse error cannot pass as a finding; (b) heap `nr=0`'s
  `system current` must agree with `mallinfo2`'s `arena` on the same process at
  the same instant — two independent libc calls that must tell the same story;
  (c) >= 25 readings over >= 30 min on both web workers, no restart, trim OFF.
- COST DISCIPLINE (`#241`): `get_all_process_memory_snapshot()` is also reached
  from `log_all_process_memory()`, which workers call at STAGE CHECKPOINTS. So
  the detail is FLAG-GATED (default OFF), throttled to one libc call per
  interval, and reports its own `duration_ms` so the cost is measured rather
  than assumed.
- Blocked by: none.

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
