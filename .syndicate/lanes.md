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
### open-bet-live-status — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-26 — session syndicate-27 (749848)
- Goal: `/portfolio` is the live buying engine — merged book, editable caps,
  venue balances, venue settlement, live status on open bets. `[user 2026-08-26]`
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
- **STATUS 2026-08-27T21:45Z — 11 commits landed, 6 verified in production,
  5 shipped-but-unfired. Narrative and all 7 self-corrections in
  `log/2026-08-27.md`; measurements in `deploys.md`.**
- **OWED, all trigger-gated, none forceable:**
  1. `cle-laa` home row — grace expired 21:44:25Z, predict `lost / -2.76`.
  2. WNBA city codes (`31575179`) + soccer pair (`fde862aa`) need a
     refresh-worker deploy; live there is behind.
  3. paused-retry and balance-gate need an exchange pause / a cash floor.
- **DO NOT re-derive:** NCAAF projections cannot complete before **1 Sept**
  (monthly CFBD quota exhausted, `X-CallLimit-Remaining: 0`); it relaunches
  every ~38s and crashes on `429` until then. `source=artifact` IS confirmed —
  the profile loads; the RUN fails downstream.
- Claims: NONE held (web released 20:44Z, live-odds-worker expired).

### convergence-phase7-crps — OPEN, **UNOWNED** `[session abf487e4 ARCHIVED 2026-08-20T21:1xZ]` — **FIVE FINDINGS: FOUR DEFECTS FIXED AND MEASURED, ONE NOT A DEFECT.** Ladder over the 12MB publish ceiling (pitcher strikeouts 0/12 → 18/18 rows with market lines, verified on the served payload); conditional mix never CALLED from the roster build; season-artifact pull matching NOTHING (bare globs vs fnmatch on full paths) — all five inputs now present on the worker. NOT a defect: `vs_pitcher_*` is unfed by `FORWARD_BVP_MATCHUP_MODE=off`, a modelling decision; reclassified as `disabled` so nfail means "wrong". **THE ONE THING OWED: verify on 2026-08-21** — first `sim_input_report_2026-08-21.json` via `/api/ops/artifacts/export?pattern=*sim_input_report*` must show `nfail` **10 → 0**; still 10 on a fresh `generated_at` means the wiring is INERT and this reopens. Claims: NONE held. Still open, deliberately not fixed: ephemeral `vendor/*/data/` statcast caches; BVP left OFF by design. — opened 2026-08-17
- **Goal (single testable outcome):** a proper scoring rule runs over CONTINUOUS
  projections joined to realized outcomes, with **no dependency on settlement,
  grading, or a placed bet**. `#440` Part 4 Phase 7. **MET** — 12k observations
  across two windows where settlement has produced 0.
- **Files (all NEW — collision-checked 2026-08-17 against all 14 OPEN lane
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: blocks on `origin/main`; zero overlap):**
  released: - `syndicate/features/shared/projection_score.py` (NEW)
  released: - `tests/test_projection_score.py` (NEW)
  released: - `scripts/score_projections.py` (NEW)
- **THE ONE THING OWED:** first `sim_input_report_<date>.json` via
  `/api/ops/artifacts/export?pattern=*sim_input_report*` must show `nfail`
  **10 → 0**. Still 10 on a fresh `generated_at` means the wiring is INERT and
  this reopens.
- **FALSIFICATION RESULT: Phase 7 is a 2-sport instrument, not 7.** Only MLB and
  WNBA/NBA carry a joinable spread. NHL, soccer and NCAAF are **UNMEASURED, NOT
  ABSENT** — re-check against PRODUCTION before anyone writes "no spread".
- **DO NOT BUILD A NEW JOIN.** `scripts/backtest_mlb_props.py` already solves
  archive-replay, the `batter_id` join, per-market denominators, DNP exclusion
  and baseline comparison. Phase 7 is the distribution half of a harness that
  already works, not a second harness.
- **THE `outs` LEASH IS CONFIRMED, AND DO NOT RE-REPORT IT AS A DISCOVERY.** The
  team measured this bias by tier and partly fixed it. Sim P(outs<15) 0.1036 vs
  actual 0.2961; 27% of sim mass sits at exactly 5.0 IP, the
  `starter_min_innings = 5` boundary. The over-projection is concentrated in mid
  and back-end starters and **elite starters are slightly UNDER-projected**, so a
  single global shift would make aces worse.
- **DO NOT "re-enable" `starter_tto_quality_scaling`.** Its 0.0 is a deliberate,
  evidence-based revert — it made strikeout hit rate WORSE (55.78% → 54.65%).
  Read the OVERRIDES file, not code defaults; I made that error and corrected it.
- **NOT ESTABLISHED:** that `manager_tendencies.json` is absent IN PRODUCTION
  (absent from the repo, never read off the Render disk). Confirm before acting.
- **Blocked by:** none.
- Full working record (measurements, phase log, hypothesis/falsification detail) moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### soccer-model-dispersion — OPEN, UNOWNED (session `soccer-sport-owner` checkpointed and released 2026-08-20 ~13:3xZ) — TESTABLE OUTCOME NOT MET; DISPERSION FALSIFIED; DISCRIMINATION CONFIRMED AS THE REMAINING DEFECT; HOME-ADVANTAGE RE-FIT TRIED AND FAILED HELD-OUT VALIDATION
- Goal (unchanged, still NOT met): `backtest_soccer_h2h_calibration.py` reports
  model Brier **<= market** on at least one non-`belgian_pro_league` league.
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
- **DISPERSION IS FALSIFIED — this lane's own pre-registered outcome fired.**
  Model stdev rose 0.1575 → 0.1922, PAST market's 0.1859, and the Brier gap did
  not close: worse than market in 8 of 9 leagues. Recorded as an OVERTURNED
  belief in `learnings.md` 2026-08-20.
- **DISCRIMINATION is the remaining defect.** Per-league AUC gap is the map:
  **serie_a (-0.055) and especially bundesliga (-0.111)** have real, unaddressed
  ranking deficiencies. That is the next thread — everything tried so far
  targeted the 5 leagues where ranking was already fine.
- **DO NOT re-open the input-quality list without new evidence that a specific
  field is systematically BIASED**, not merely present or absent. Every field
  was sourced, tested and disposed with a stated reason; none closed the gap.
- **ANY future single-parameter fit MUST clear a held-out validation** on
  different matches than the fit. `championship`'s home-advantage boost was the
  most trustworthy-looking in-sample result and FAILED held-out (+0.0121 Brier
  worse, t=+1.19). REVERTED, NOT COMMITTED. None of the other 4 candidates
  should be trusted either — they looked LESS solid than the one that failed.
- **INHERITED, DO NOT RE-DERIVE:** a leak-free backtest ALREADY EXISTS
  (`5a94b134`); MLS cannot be backtested from its current source (undated season
  aggregates); do not publish `model_edge_pct` on a partial win — publishing is a
  separate decision from closing the Brier gap.
- Blocked by: none.
- Full working record (measurements, phase log, hypothesis/falsification detail) moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### wnba-live-odds-capture-gap — OPEN, NARROWED, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — **THE AUTORUN FIRED FOR REAL `[2026-08-21T00:07:24.782Z / 19:07 CT]`, observed by a third party (scheduled task `verify-wnba-live-scale-481`, session `1f76348c`) on IND@DAL. The "never fired" blocker is DISCHARGED. What replaces it: the autorun launches every ~4.3 min and refreshes the LIVE-LENS path, but `book_quotes/<date>.jsonl` advanced ONCE (00:07:49Z) and was still byte-identical 26 min later. The lane's literal testable outcome PASSES, but passing cannot be attributed to the autorun — see FINDINGS.** **ROOT CAUSE FOUND `[00:45Z]`: the autorun is fine; `refresh_wnba_oddsapi_props.py`'s REUSE GUARD sits upstream of it and returns `reused_artifact_bundle` every tick, so the child that appends `book_quotes` never spawns. The guard's staleness bound is the PREGAME sweep interval (2h) and its reuse key carries no phase term, so a 240s live autorun cannot outrun it. THE FIX BELONGS IN THE GUARD, NOT THE AUTORUN.** — opened 2026-08-20 — session 2bffd747-efb5-45d8-b4f3-ae067b645eb7
- Goal: WNBA's in-game (live-phase) odds capture actually refreshes once a game
  goes live, instead of freezing at its last pregame quote. **Testable outcome:**
  for a live WNBA game, `wnba_source/tracking/book_quotes/<date>.jsonl` carries a
  `captured_at` newer than kickoff.
- Files:
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  - **CLAIM RELEASED 2026-08-20 to `wnba-live-reuse-bound`** (session
    `1f76348c`), narrowly and by this lane's own instruction below. The defect
    location IS now confirmed and it is not in this file — only `_build_wnba_steps`
    needs one line to pass the phase to the child. This lane is UNOWNED (session
    `2bffd747` absent from the roster including archived), so holding a
    read-only reference here would block the fix this lane exists to enable.
    Path deliberately NOT written as a path on this line, because
    released: `check_lane_invariants.py` parses any backticked path inside a `- Files:`
    block as a live CLAIM and would keep reporting the file as contested.
    Formerly: the WNBA step builder, read-only reference, "do not edit without
    re-claiming narrowly, same convention the soccer lane used for this same
    file" — which is exactly what was done.
  - Not claimed, read-only reference: `scripts/run_live_odds_refresh_worker.py`
    — likely relevant (soccer's autorun equivalent lived here), not yet
    confirmed WNBA has an analogous live-phase launcher at all.
- **ROOT CAUSE FOUND, AND THE FIX IS NOT IN THE AUTORUN.** The autorun fires
  correctly (`WNBA_LIVE_AUTORUN_LAUNCHED` on a clean ~4.3 min cadence against a
  REAL live game, zero errors). `refresh_wnba_oddsapi_props.py`'s REUSE GUARD
  sits upstream and returns `reused_artifact_bundle` every tick, so the child
  that appends `book_quotes` never spawns. Its staleness bound is the PREGAME
  sweep interval (2h) and its reuse key `(artifact_root, date, do_edges,
  do_export)` carries **no phase and no time term**, so a 240s live tick is
  indistinguishable from a pregame one. **THE FIX BELONGS IN THE GUARD.**
- **Do NOT touch the autorun; it works.** The combined-sweep / MLB-starvation
  suspicion was traced and is EXONERATED for this symptom.
- **Re-verify with the last-seen slot and `/api/ops/wnba/refresh-decision`, NOT
  with `.jsonl` row counts.** `append_book_quotes` is a CHANGE log, so a flat
  file proves nothing on its own; the state file's last-seen slot is what
  separates "prices stable" from "nothing observed". All 5,489 keys read
  36+ min cold — nothing was observed.
- **The testable outcome PASSED but does not prove the mechanism** — batch
  spacing of 84-162 min produces a post-kickoff batch with no autorun at all.
  The 25s gap between launch and capture is suggestive, NOT probative.
  **Do not close on it.**
- **UNVERIFIED:** the 2h bound is the CODE DEFAULT with no `render.yaml`
  override; live service env-vars were never read, so a service-level override
  is still possible.
- **Adjacent, not this lane's:** live-odds-worker hit **97.2% of its 2GB cap
  (43.6MB headroom)** with three live games.
- **A line in this block's history belongs to a DIFFERENT lane** — an
  "Outcome:" about Polymarket `tsc-mlb-lad-det` quote pricing. Preserved
  verbatim in `lanes_history.md`; it is not this lane's finding.
- Blocked by: none.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### soccer-board-mlb-parity — OPEN, UNOWNED (session `f98be73b` checkpointed 2026-08-22 23:2xZ) — **TWO THINGS DEPLOYED TONIGHT. (1) `#518` FOTMOB MOMENTUM — live-odds-worker `94a16efe`, live 22:18:35Z: the event-signal sweep (momentum/xG/shot pressure) was killed by a null control, but a pooled 60-120s model IS real and DIRECTIONAL (which team scores next, dAUC +0.071), driven by FotMob's own momentum series; production's ESPN proxy carries NO signal at any half-life — retired. 5,552-match dataset committed. (2) COMPACT CARD REDESIGN — web `a1dc1e9a`, live 23:08:55Z, VERIFIED ON PRODUCTION HTML: pregame cards show sim-projected totals + BTTS/goals/corners/top-score; final cards RECONCILE those same facts against the real result (19 hit/62 miss on today's slate, spot-checked by hand).** OWED: (a) the FotMob join has never resolved a real fixture — MLS kickoff 2026-08-23T01:30Z is the first test; (b) the live-odds market-pricing pilot sits at 1.46 SE, n=106, needs ~2 more match-days. Full detail: `state.md [soccer-live-momentum]` + `[soccer-compact-cards]`, `log/2026-08-22.md` 22:0x-23:1xZ entries. — opened 2026-08-20 — session f98be73b-b686-42b7-bdf9-248ab97f65b7
- Goal (unchanged): `/soccer` serves a date-scoped board whose cards carry the
  same information classes MLB's do, and whose live tier updates during a match.
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
- **OWED, and not claimed as done:**
  1. **The FotMob join has never resolved a real fixture.**
  2. **Gate 3 has never been observed PRICING a live edge** — only withholding by
     name. Needs a live soccer market quoted two-sided.
  3. **The live totals lens is unproven** — harness ran n=1 with NEUTRAL ratings.
  4. **Two fair bases on one market**: home rows use `soccer_projections`' de-vig,
     away/draw use layer2's `quote.fair_probability`. Residual median 0.47 /
     max 1.38 pts.
  5. Five of six ESPN-join collision pairs (incl. Manchester City ↔ Manchester
     United, 0.812) fixed BY CONSTRUCTION and never rebuilt in production.
  6. The live-odds market-pricing pilot sits at 1.46 SE, n=106 — needs ~2 more
     match-days.
- **`board_enrichment._side_matches` WAS FIXED BY ANOTHER LANE** `[2026-08-29,
  lane ncaaf-chip-grid-join]` — arguments were inverted; 0/8 as called, 8/8
  reversed. Soccer gains 5 matched rows (285 → 290); no sport loses a match.
- **A DISCLAIMER NEXT TO A PATH DOES NOT UNCLAIM IT — only deleting the path text
  does.** This lane's bare `cards.py` filename claimed EVERY sport's cards
  builder (`lane-guard` matches on path SUFFIX) and blocked an NCAAF edit during
  the first game of the season. `check_lane_invariants` did not catch it: the
  claim had exactly one holder.
- **NOT IN THIS LANE:** `syndicate/features/soccer/sim_engine/`, adapters,
  ratings — held by `soccer-model-dispersion`.
- Blocked by: none.
- Full working record (measurements, phase log, hypothesis/falsification detail) moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### wnba-halftime-elapsed — **OPEN, UNOWNED** `[session 1f76348c ARCHIVED 2026-08-21 ~16:1xZ]` — **ONE READING OWED** — fix is LIVE on web (`2b9040df`, content-verified) and on the workers (`3b41696d` is an ancestor of refresh-worker's SHA). Unit-verified both directions: 3 break tests FAIL pre-fix, 2 narrowness tests PASS in both states. **THE BREAK BEHAVIOUR ITSELF IS UNOBSERVED IN PRODUCTION** — a 20-minute watcher caught no blank-clock state, and the one suggestive reading (a board row at 'End of 1st' keeping a live lane at model 0.2155 vs its 0.27 pregame baseline) was INDIRECT, via the board. Next WNBA break discharges it. — opened 2026-08-20 — session 1f76348c-062d-4075-a54b-a8b0eadabb2b
- Goal: the live win/cover probability must keep using the live margin during a
  BETWEEN-PERIODS break instead of silently reverting to the pregame number.
  **Testable outcome:** with period=2 and a blank clock, a +12 and a -12 home
  margin produce DIFFERENT probabilities (today both return the pregame anchor).
- Files:
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: - `syndicate/features/wnba/cards.py` — `_wnba_elapsed_minutes` and the
    released: `source`/`markets` fallback that keys off its None.
- **ONE READING OWED — the break behaviour itself is UNOBSERVED IN PRODUCTION.**
  A 20-minute watcher caught no blank-clock state; the one suggestive reading was
  INDIRECT, via the board. Next WNBA break discharges it.
- **Falsification test that still matters:** if a blank clock ALSO occurs at a
  period's START, then "blank clock = period complete" overstates elapsed by a
  full period and this fix is WRONG in that state. The narrow fix was chosen for
  exactly this reason — confirm against a real captured halftime payload before
  generalising.
- Blocked by: none.
- Full working record (measurements, phase log, hypothesis/falsification detail) moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### wnba-live-props-data — **OPEN, UNOWNED** `[session 1f76348c 2026-08-21T17:4xZ]` — **PROPS CHAIN BUILT+DEPLOYED (UNPROVEN); `#499` TOTALS PRICING DEPLOYED (UNPROVEN).** Live on BOTH workers at `8d5d6edf` (refresh-worker 16:43:05Z, live-odds-worker 16:48:04Z) — totals scale `3.2` + `ANALYTIC_LIVE_STD_ERR_BY_MARKET {("wnba","totals"): 0.150}` + the fix for it shipping INERT. **TWO READINGS OWED, BOTH BLOCKED ON A LIVE SLATE, BOTH ARMED:** scheduled task `verify-wnba-totals-pricing-499` fires 19:15 CDT 2026-08-21 carrying both. (a) `#499` PASSES only if totals rows refuse as `prob_interval_swamps_edge` (per-row) NOT `analytic_estimator_never_backtested_for_this_market` (category-wide); at sigma=0.150 the bar is ~30pp so **priceable volume is a BUG signal, not success**. (b) `#498` props PASSES only on `WNBA_LIVE_BOX_CAPTURED` with players (live-odds-worker) AND `live_projections.rows_live_projected` > 0. Pre-tip both read 0 — **a zero is indistinguishable from an inert feature**; verifier `scripts/verify_wnba_totals_pricing.py` exits 3 rather than 0 for that reason. DO NOT report either as working. Narrative: `log/2026-08-21.md`. Claims: NONE held. — opened 2026-08-20 — session 1f76348c-062d-4075-a54b-a8b0eadabb2b
- Goal: live WNBA props. **Phase 1 (THIS LANE): persist the live per-player stat
  lines so a worker can read them.** The data was never missing —
  `/wnba/api/live_player_boxscore` serves it and always has, but it is fetched in
  the REQUEST PATH on web while the prop join runs on a WORKER, so there is no
  artifact to read. **Capture VERIFIED 2026-08-21 03:37Z: `games=2
  players_with_stats=39`.**
- Files:
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: - `scripts/capture_wnba_live_player_box.py` — the capture (new).
  - ~~**BLOCKED, NOT CLAIMED:** the `HOT_ARTIFACT_PATTERNS` entry for
    `wnba_source/data/live/live_player_box_*.json` lives in a file held by the
    OPEN lane `nfl-props-odds-allowlist`.~~
    **RETIRED 2026-09-02 — THIS BLOCKER IS NOT REAL, AND THE FIX IT ASKS FOR IS
    FORBIDDEN.** See the RETIRED note at the bottom of this lane for the
    evidence. Short version: the artifact is KEYVALUE-backed, so it already
    crosses services and an allowlist entry would be inert.
- **TWO READINGS OWED, BOTH BLOCKED ON A LIVE SLATE. DO NOT report either as
  working.**
  (a) `#499` totals PASSES only if rows refuse as `prob_interval_swamps_edge`
  (per-row), NOT `analytic_estimator_never_backtested_for_this_market`
  (category-wide). At sigma=0.150 the bar is ~30pp, so **priceable volume is a
  BUG signal, not success.**
  (b) `#498` props PASSES only on `WNBA_LIVE_BOX_CAPTURED` with players
  (live-odds-worker) AND `live_projections.rows_live_projected > 0`.
- **PRE-TIP BOTH READ 0, AND A ZERO IS INDISTINGUISHABLE FROM AN INERT FEATURE.**
  `scripts/verify_wnba_totals_pricing.py` exits **3** rather than 0 for that
  reason — treat exit 3 as "not measured", never as a pass.
- **STILL NEVER RUN END TO END.** Every hop is wired and unit-tested; the chain
  has never executed against a live slate.
- ~~**BLOCKED, NOT CLAIMED:** the `HOT_ARTIFACT_PATTERNS` entry for
  `wnba_source/data/live/live_player_box_*.json`. Until it lands the capture
  writes an artifact the board build CANNOT SEE.~~
- **RETIRED 2026-09-02 `[lane soccer-players-csv-allowlist, asked to "fix the
  wnba one too" after the soccer allowlist entry shipped]`. THE BLOCKER IS NOT
  REAL AND THE FIX IT NAMES IS THE ONE THIS REPO FORBIDS.** No entry was added
  and no deploy was run. Traced end to end, in code:
  - **WRITER** is not the standalone script any more. `live_lens_loop.py:625`
    writes the capture through `refresh_state_store.write_json_file`. That
    function returns **before ever touching disk** when the path is
    keyvalue-backed — an exclusive branch, not a dual write.
  - **BOTH READERS** use `refresh_state_store.read_json_file`:
    `bet_status_wnba.py:666` and `wnba/live_lens.py:370`. Neither consults disk.
  - **THE PATH IS KEYVALUE-BACKED.** `_keyvalue_backed()` excludes exactly one
    marker, `migration_runs/`, and all three services carry
    `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` in `render.yaml`. Its docstring
    says read and write route through one predicate specifically so they cannot
    disagree.
  - **KEYVALUE IS THE SHARED REDIS**, so the artifact ALREADY crosses services.
    Measured on web 2026-09-02: `/api/ops/keyvalue/diagnostics` returns real
    Redis stats (not the "not keyvalue on this service" refusal), and
    `/api/ops/keyvalue/usage` shows a **`wnba_source/data` bucket, 55 keys,
    322,752 bytes**. TTL is 10 days for a date-tokened path.
  - So an allowlist entry would let `publish` accept the path while
    `sweep_changed_hot_artifacts` globs a DISK that never holds the file, and
    `/api/ops/artifacts/export` (also a disk read) would return `count=0`. That
    is the **2026-08-27 FORBIDDEN** rule verbatim: *allowlisting a keyvalue-backed
    path turns a 403 into an empty result and looks like a fix.*
  - `artifact_publisher.py` already says so in its own `board_snapshot` note:
    **"Allowlisting PERMITS a transfer; it does not make a reader. Add the entry
    with a disk-consulting read, not before."**
  - The deferral target is also gone: lane `nfl-props-odds-allowlist` no longer
    exists in `lanes.md`.
  **What was never in question:** this does NOT show the props chain works. The
  "STILL NEVER RUN END TO END" bullet above stands untouched — the transport was
  never the missing piece, so removing a non-blocker discharges nothing.
  **The real risk to this artifact is eviction, not reachability** — see
  `todo.md #637`.
- Blocked by: none.
- Full working record (measurements, phase log, hypothesis/falsification detail) moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### portfolio-ledger-service-split — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-22 — session 74a0966a-a9fe-57cd-8320-f46f235aeed1
- Goal: a bet logged on WEB can be settled by the autorun on REFRESH-WORKER, so
  `/portfolio` stops reading every position as pending.
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
- **Status: three defects found, all FIXED AND DEPLOYED. The goal is NOT met —
  nothing has settled yet.** `#502` ledger crosses the service boundary
  (`2aa1df54`); `#504` settlement 13th -> 2nd in the chain (`4eeffb5c`, verified
  1.3ms); `#505` join on a stable identity (`a1e89ff3`, refresh-worker only).
- **Unverified and load-bearing:** `#505`'s `entity` field mapping was never
  measured against real evaluation records (worker-local, not in
  `HOT_ARTIFACT_PATTERNS`).
- **The backfill tool is BUILT and NOT RUN against production.** Its in-session
  preview proved the TOOL works and nothing about production.
- **Verification owed, and it GATES the backfill:** the next `[ledger_bridge]`
  line. `matched_by_identity > 0` = the join works; `by_identity` large with
  `matched_by_identity: 0` = the entity mapping is wrong. **Do not run the
  backfill with `--commit` before that reading.**
- **NOTE for whoever owns `refresh-worker-oom-recurrence`:** this lane edited
  `scripts/run_refresh_worker.py`, which your lane nominally holds, and the
  change moves an expensive job EARLIER in the tick chain.
- Blocked by: none.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### render-web-request-path — **OPEN, UNOWNED, CLAIMS RELEASED** `[session 726ef4ff checkpointed and archived 2026-08-22 ~19:4xZ]` — **SHIPPED AND MEASURED; ONE ITEM OWED**
- Goal: web stops being SIGTERM'd during live MLB slates. **Changes 1 and 2 MET**
  (web `8149e51d`, still live under peer `3ada3512`).
- **Claims: NONE held.** Released deliberately at archive time.
- **OWED, THE ONLY OPEN ITEM:** the card-cache idle bound is **NOT** verified.
- **DO NOT allowlist `raw/statsapi/feed_live`** — it freezes live scores (`#413`).
- Next bottleneck, now visible: `build_cards_page_context` 1803-2402ms on a miss.
- Blocked by: none.
- Full working record (measurements, phase log, hypothesis/falsification detail) moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### portfolio-decision-and-execution — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-22 — session 9324a3e5-364e-5fb4-9b4a-b0568019e37f
- Goal: a staged, gated path from the Layer 2 shortlist to a COMMITTED
  position, with every stage measurable before the next opens.
  Plan: `.syndicate/plan_2026-08-22_portfolio_execution.md` (stages A-D).
- **BANKROLL = $1,000** `[user decision 2026-08-22]`, user-editable.
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
- **Verification OWED, and it is a one-read production check.** Stage A's
  input checklist passes 4/4 fields POPULATED **LOCALLY ONLY** — that is not
  production evidence.
- **DO NOT repeat "the board is running at 0% sim."** `[user-flagged
  2026-08-22]` It came from a SYNTHETIC row in undeployed code and describes
  nothing running. The sim's real role was measured and the premise needed
  correcting.
- **Two INERT-FEATURE defects were caught here by the input checklist** — the
  pattern to keep applying, not a one-off.
- **Stage D is BLOCKED** on a real venue/credential decision; stages A-C are not.
- **There is nowhere durable to put a money ledger** without the storage
  decision recorded in this block's history — checked, not assumed.
- Blocked by: none for stages A-C.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### kalshi-line-aware-rungs — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — **CLAIMS RELEASED 2026-08-26 03:3xZ, session archived** — BLOCKED ON TWO MEASUREMENTS, do not resume the original goal first — opened 2026-08-25 — session 281da8c3-1df9-5c77-9e34-ee6f15f37b45 (GONE)
- Goal: line-aware Kalshi rungs. **DO NOT RESUME THE ORIGINAL GOAL FIRST** —
  it is currently unjustified and blocked on two measurements below.
- **CLAIMS RELEASED. The files below are FREE to take.** The lane stays OPEN
  because real work remains, but no live session holds it. Nothing is
  uncommitted: tree clean at `d2d44dbaf`, all shipped code live under `34717822`.
- **Files: released:** `tests/test_kalshi_odds_cadence.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `tests/test_kalshi_precap_cut_by_date.py` (NEW),
  released: `syndicate/features/shared/kalshi_board.py`, `tests/test_kalshi_board.py`,
  released: `syndicate/features/shared/kalshi_catalogue.py`,
  released: test_kalshi_side_vocabulary (transferred to
  `live-venue-order-placement` 2026-08-29, `#603`), test_kalshi_futures_eviction.
  Written without `.py` so the guard stops enforcing paths this lane released.
- **RE-CLAIM NOTE, and it MUST stay OUTSIDE the `Files:` block:**
  venue_quote_adapters, venue_quote_fanin and kalshi_odds_refresh were
  re-claimed by `venue-quote-line-join` on 2026-08-27. Naming them INSIDE
  `Files:` turned them back into claims and this lane — session GONE, claims
  RELEASED — went on blocking edits to files it had given up. Filenames are
  written without `.py` on purpose.
- **BLOCKED ON, in order. Do NOT write an eviction change before both:**
  1. `PRECAP_CUT_BY_DATE` taken **during a live slate**. The `03:11Z` reading is
     post-slate and systematically understates it (`KXMLBHRR` cut 747 at 01:49Z,
     132 at 03:11Z). Code is live; this needs only a reading.
  2. The **outer `MAX_STORED_MARKETS` trim dated the same way**.
     `cut_total=3940` vs `TICK trimmed=8744` — ~4,800 markets cut by a second
     date-blind bound that nothing dates.
- **FOUR HYPOTHESES KILLED, none by argument** — including "eviction
  re-prioritisation recovers ~1,600 markets", measured at **133**. One is now
  STALE: NCAAF DOES reach the board side since `5e6ef685`; **a successor must
  re-measure rather than inherit these numbers.**
- **Largest addressable bucket is now `no_matching_board_row=1838`**, not the
  date bucket. Start there.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### kalshi-spread-join-sign — **OPEN (reopened 2026-08-26)** — session syndicate-43 (ENDED) — UNOWNED — six things verified; WNBA settlement is BUILT, LANDED and NOT DEPLOYED
- Goal: Kalshi spread join sign, and WNBA/soccer settlement. Six things
  verified; WNBA settlement is BUILT, LANDED and NOT DEPLOYED.
- Note: this lane was CLOSED earlier on 2026-08-26 and its block moved to
  `lanes_history.md`. Work continued after that close, so this is a fresh block
  for what is still OWED — the history entry stays as the record.
- Files: released: `syndicate/features/shared/{kalshi_board_join,kalshi_orders,bet_status_wnba,bet_status_soccer,polymarket_us_orders,board_enrichment}.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `scripts/build_wnba_boxscores.py`,
  released: `syndicate/blueprints/wnba.py` and their tests. **ALL CLAIMS RELEASED.**
- **OWED, in priority order:**
  1. **DEPLOY refresh-worker, THEN read `SETTLED date=2026-08-25`.** PASSES only
     if `not_decided_yet` falls below 6 and Citron (1 reb vs over 3.5) / Amoore
     (3 ast vs over 3.5) grade **LOST**. **DO NOT REPORT WNBA SETTLEMENT AS
     FIXED BEFORE THAT READING** — and treat its all-time `win 100%` as
     wins-only BY CONSTRUCTION until a loss can settle.
  2. **Re-do the 2026-05-25..08-26 backfill through the KEYVALUE store.** The 84
     files published via `/api/ops/artifacts/publish` sit on WEB'S FILESYSTEM
     while the consumer reads keyvalue on refresh-worker.
  3. **Soccer: still 0 settled all-time.** The read is fixed; needs an order
     whose match finished with finals captured after 2026-08-26T16:11Z.
  4. **Polymarket side resolution UNRESOLVED.** `over`->YES/`under`->NO is a
     fixed constant while the price comes from the name-matched index, and the
     `outcomes` array orientation VARIES per market. A cross-check guard was
     built and **REVERTED** — it silently enthroned the positional reading, the
     disputed question. `FILL_ABOVE_LIMIT` ships as detection only.
  5. **33 pre-existing test failures** in soccer/board selection, confirmed NOT
     caused by this lane (identical counts with and without the change).
- Blocked by: none
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### wnba-chip-live-token — OPEN, **UNOWNED** (session 3dcd0fb2-a129-4c6a-95f2-29b11ea0d272 checkpointed and ARCHIVED 2026-08-27) — opened 2026-08-27 — **CLOCK FIXED AND VERIFIED IN PRODUCTION (web `e3dceb68`): `LIVE` -> `Q3 20.5`, control and after on the same game against ESPN. TWO THINGS OWED — refresh-worker is not deployed, and the projection guard is UNIT-TESTED ONLY. `todo.md #586`.** **CHECKPOINT 2026-08-27T01:2xZ: refresh-worker reached `070f452a` and DOES carry the fix; the WNBA half is owed on a MISSING SUBJECT, not a missing deploy — `WNBA live=0` when the artifact landed. Next window TOR @ SEA `02:00Z`. Session archived; lane UNOWNED.**
- Goal: a live WNBA game chip carries its QUARTER AND CLOCK (`Q3 5:23`) instead
  of a bare `LIVE` token. **Clock FIXED AND VERIFIED IN PRODUCTION** (web
  `e3dceb68`): `LIVE` → `Q3 20.5`, control and after on the same game against
  ESPN.
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
- **OWED 1 — the WNBA half is owed on a MISSING SUBJECT, not a missing deploy.**
  refresh-worker reached `070f452a` and DOES carry the fix; `WNBA live=0` when
  the artifact landed. Discharge on a live WNBA slate:
  `/api/board/game-chips?sports=wnba` must return a period-and-clock token.
- **OWED 2 — the projection guard is UNIT-TESTED ONLY** and must not be recorded
  as verified.
- **MY OWN VERIFIER RETURNED A FALSE NEGATIVE ON THE PASSING RUN** — do not trust
  a red from it without reading the assertion.
- **A `~~struck~~` PATH IS STILL A LIVE CLAIM** to both `lane-guard.py` and
  `check_lane_invariants.py`, which read positionally. Striking a path does not
  release it; deleting the text does. This is a standing rule in `learnings.md`
  and this lane broke it.
- Blocked by: none. `wnba/cards.py` is claimed by `wnba-halftime-elapsed`.
- Full working record (measurements, phase log, hypothesis/falsification detail) moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### venue-quote-line-join — OPEN, **UNOWNED** (session 3515d143 archived 2026-08-27 ~21:45Z; ALL CLAIMS RELEASED, worktree clean, nothing uncommitted) — **SIX DEFECTS FIXED AND VERIFIED IN PRODUCTION; ONE CHANGE RECORDED AS UNPROVEN; TWO NAMED AND UNFIXED.** Verified: soccer unmatched **15,348 -> 4,006**, grid stamped **13.1% -> 66%**, prop keys now name their player (was a cross-sport WRONG-PLAYER match), kalshi quotes carry a price at all (`yes_bid` was never persisted) and both legs of a threshold market, NFL nicknames resolve (`clubs_unresolved` 64 -> 0), per-sport trim floor, and the venue poll on its own thread (kalshi ~1,250s -> ~120s, polymarket 428-828s -> ~120s). **UNPROVEN: the demand-weighted trim.** Allocation IS the binding constraint (`matched` tracks mlb slots: 794/27, 1620/208, 1741/218, 1706/221) but today's recovery came from MLB's slate approaching first pitch, NOT from the change -- the trim behind `matched=208` logged `demand=None`. **Its test is tomorrow MORNING CT, sustained; the morning was noisy (146/210/99 against a 5-27 baseline) so one good reading is not evidence.** I recorded 'supply not allocation' and had to RETRACT it -- see `deploys.md` 21:0xZ correction. **UNFIXED: a TOTALS key names no GAME** (672 polymarket soccer quotes -> SIX distinct keys, same class as the player-blind props); and the `842`-row builds match 0 on the COMPLETE set, never confirmed as a benign future-date board. Full narrative: `log/2026-08-27.md`.
- Goal: reduce `VENUE_REPRICE_KEYS unmatched_by_sport` for nfl/soccer/ncaaf.
  **SIX DEFECTS FIXED AND VERIFIED IN PRODUCTION:** soccer unmatched **15,348 →
  4,006**, grid stamped **13.1% → 66%**, prop keys now name their player (was a
  cross-sport WRONG-PLAYER match), kalshi quotes carry a price at all (`yes_bid`
  was never persisted) and both legs of a threshold market, NFL nicknames resolve
  (`clubs_unresolved` 64 → 0), per-sport trim floor, and the venue poll on its own
  thread (kalshi ~1,250s → ~120s, polymarket 428-828s → ~120s).
- **CLAIMS RELEASED 2026-08-27 at session archive** — every file this lane held
  is free, including the live-odds worker entrypoint. The paths named in the
  history block are a RECORD, not a claim.
- **UNPROVEN: the demand-weighted trim.** Allocation IS the binding constraint,
  but the recovery came from MLB's slate approaching first pitch, NOT from the
  change — the trim behind `matched=208` logged `demand=None`. **Its test is a
  sustained MORNING CT reading; the morning was noisy (146/210/99 against a 5-27
  baseline) so one good reading is not evidence.**
- **I recorded "supply not allocation" and had to RETRACT it** — see `deploys.md`
  21:0xZ correction.
- **UNFIXED, TWO:** (1) a TOTALS key names no GAME — 672 polymarket soccer quotes
  collapse to SIX distinct keys, the same class as the player-blind props;
  (2) the `842`-row builds match 0 on the COMPLETE set, never confirmed as a
  benign future-date board.
- **Deliberately NOT done:** aliasing Kalshi's `totals_q1`/`totals_h1` onto
  full-game totals.
- **SAFETY property to preserve:** the line-join fix cannot create a wrong-line
  match — those keys match NOTHING today.
- **`[2026-08-27, USER DECISION]` Kalshi and Polymarket are the foundation of the
  venue work** — see `lanes_history.md` for the full statement.
- Blocked by: none.
- Full working record (measurements, phase log, hypothesis/falsification detail) moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### ncaaf-pace-block — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — NCAAF calibration re-fitted and PROMOTED (15.00% -> 7.24%, impossible drives 159 -> 0); NFL deliberately NOT re-fitted (best as shipped); production read of the profile still owed — opened 2026-08-27 — session de363735
- **The NCAAF sources module WAS EDITED OUT FROM UNDER THIS LANE ON EXPLICIT
  USER OVERRIDE** `[2026-08-29, lane ncaaf-compact-card-state]`, scoped to
  `ncaaf_week_and_card_keys_for_date` ONLY -- it depended on `cfbd_lines_*.json`,
  which has no producer on any service, so NCAAF served **0 game chips on every
  service on every date**. The calibration and pace work this lane owns is
  elsewhere in that file. Module named WITHOUT a path here on purpose: this
  bullet sits above `- Files:` precisely so it cannot be read as a claim.
- Goal: the NCAAF `pace` block carries a REAL per-team seconds-per-play, so the
  engine stops running every game on the hardcoded 24.0 (`pace_index +0.400`).
  Calibration re-fitted and PROMOTED (15.00% -> 7.24%, impossible drives
  159 -> 0); NFL deliberately NOT re-fitted (best as shipped).
- Files: released: `scripts/build_ncaaf_pace_snapshot.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `syndicate/features/ncaaf/feature_payload.py`,
  released: `syndicate/features/ncaaf/sources.py`,
  released: `tests/test_ncaaf_pace_payload.py`
- **Ships DEFAULT-OFF, and that is load-bearing:** the profile was calibrated
  with `pace_index` pinned at +0.4, so turning this on is **a MECHANISM added to
  a CALIBRATED engine and owes a re-fit before any deploy**.
- **Pace is being tried because it targets a surface the model is KNOWN to get
  wrong, not because an edge is expected** — the correlation study showed these
  payload features carry NO information the market misses on margin
  (residual |r| <= 0.021, n=690).
- **Falsification test still standing:** if a re-fit with pace ON does not
  reduce TOTAL error against the market, pace is not the driver and the block
  stays off.
- **NOT verifiable in production:** `_EngineRowProjection` (the cards route
  takes a WEEK only; 2026 has no engine rows).
- Blocked by: none.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### venue-candidate-key-token-guard — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-27 — session 764eca35-178c-4c29-afbd-ec621894aaf1
- Goal: `_candidate_keys` stops emitting city/nickname token keys built from a
  team name alone, which matched unrelated games — e.g. `over 7.5 @ -400` shared
  across four games at once.
- Files: (none held)
- **WHAT IS OWED AND IS NOT DISCHARGED: the production volume reading.**
- **A SECOND READING IS OWED AND IS NOT THE SAME AS THE FIRST** — the soccer
  case is distinct from the volume check; discharging one does not discharge the
  other.
- Blocked by: none.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### mlb-final-zero-placeholder — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-28 — session 28195565
- Goal: a 0-0 "FINAL" in a sport that cannot end level is treated as the
  placeholder it is, rather than published as a real result.
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
- **THE OWED READING IS DISCHARGED — AND NOT FROM 08-26** `[2026-08-29]`.
- **DO NOT REBUILD 08-26 TO GET THE ORIGINAL READING.** It cannot produce it.
- **DO NOT re-derive: this recovers NO games.** 08-27 stays capped at 4 of ~15.
  The defect is MISREPORTING, not data loss.
- **RIDES ALONG — DO NOT FIRE A SEPARATE refresh-worker DEPLOY FOR THIS.**
- **NOTE for whoever takes `game_chip_scoreboard.py` next:** the guard added
  here changes its behaviour; read the history block before editing.
- Blocked by: a deploy. Not urgent.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### mlb-resolver-write-side-effect — OPEN, **NARROWED — NOT A LIVE INCIDENT** — opened 2026-08-29 — session 6475567d-f806-45a7-880c-f633718f2411 — **UNOWNED, handed off**
- **NARROWED — NOT A LIVE INCIDENT. The falsification test this lane asked for
  HAS RUN: `should_copy` does NOT fire on the daily path in production.**
  Priority LOW. The defect is real; the blast radius is much smaller than this
  block first said.
- THE DEFECT, unchanged: `artifact_publisher._required_daily_artifact_paths` —
  which only asks WHICH artifacts are required — reaches
  `mlb.sources.daily_artifact_path` -> `_resolve_data_path_with_reconcile` ->
  `shutil.copy2` (`mlb/sources.py:116`). The copy then looks present, so
  `_missing_required_artifact_relative_paths` does not request it.
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
- **THE TRIGGER IS WORSE THAN "AN MTIME RACE", WHICH THIS BLOCK GOT WRONG.**
  `if target_stat is None: should_copy = True` — a MISSING target copies
  unconditionally, which is exactly the case the repair exists for.
- **WHY IT IS STILL NOT LIVE:** on Render the candidate root holds only
  GIT-TRACKED files and that mirror stops at 2026-07-12. Measured 2026-08-30:
  `daily_summary_2026_08_28` and `_2026_08_29` are both git-tracked=NO and both
  served 200 — production's own artifacts, no mirror involved.
- **WHAT REMAINS, and it is the part worth fixing:** any BACKFILL or EVALUATION
  over **2026-05-28 -> 2026-07-12** silently gets the git mirror's copy instead
  of production's. That is precisely the window CLAUDE.md warns backtests run
  on, so the failure mode is **a backtest that believes it read production and
  did not.**
- **A CHECK THAT PROVED NOTHING, recorded so nobody repeats it:** production's
  `daily_summary_2026_07_12.json` is byte-identical to the git copy. That is NOT
  evidence the reconcile copy won — `refresh_mlb_source_mirror.ps1` refreshes
  the mirror FROM production, so identity is expected whichever direction it
  flowed. The reading cannot discriminate the two hypotheses.
- **Discriminator if anyone wants certainty:** one `print` at `sources.py:116`
  and read a worker tick, or compare the mounted disk's mtime against deploy
  time for a tracked-window date.
- **ALSO OPEN, same family, NOT fixed:** `test_deploy_preflight.
  TooSoonVerdictTests` (6 tests) read the LIVE shared deploy claim and fail
  whenever any session holds one. **Mocking it to None made it WORSE (6 -> 8)
  and was reverted.**
- Status: FINDING ONLY. Nothing on the data path was changed.
- Blocked by: none.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### polymarket-yes-leg-binding — OPEN, **UNOWNED** `[session 5611932c ARCHIVED 2026-09-01 ~01:4xZ]` — opened 2026-08-30 — **SHIPPED + DEPLOYED; THE LEG CHOICE IS STILL UNVALIDATED; ONE LIVE-MONEY RISK OPEN AND IT IS NOT MINE TO DEPLOY**
- Goal: a Polymarket moneyline resolves its YES/NO leg from the VENUE's own
  `yesLegIndex` instead of being refused, and refuses BY NAME where the venue
  did not state it.
- **`layer2_board.py` WAS RELEASED TO ME, NOT OVERRIDDEN** `[2026-08-31]`, by
  lane `layer1-model-edge-join` (session 1c88bcca), who struck it from their own
  `Files:` block after reproducing my diagnosis independently and adding the
  decisive argument against their own work.
- **THIS PROSE SITS ABOVE THE `Files:` LINE ON PURPOSE.** `lane-guard._paths_in`
  treats ANY token containing a slash or a dot as a claimed path, and
  `_claimable_prefix` only strips text after a disclaimer marker -- so an
  explanation written INSIDE the block turns words into claims. My previous
  wording put "layer1-model-edge-join / session" in the continuation and had
  this lane claiming a bare `/`. The same cause gave 1c88bcca three phantoms
  (`1/p`, `15.0`, `85.13`) live on main for one commit, and
  `check_lane_invariants` still reported INVARIANTS HOLD because each phantom
  had exactly one holder -- so diff the claim SET, do not trust a green checker.
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
- Claims taken under `[2026-08-30, USER OVERRIDE]` x3 ("take it to the
  user-override route", "take it and fix it"). Conflicts were surfaced to the
  user BEFORE each override and the holders were messaged. Deploy claim on
  live-odds-worker taken 20:18:42Z and RELEASED. Holding no locks.
- **LANDED (all on `origin/main`):** `8b0d27df` yes-leg binding + corroboration
  gate; `dd33c865` the `not_found` per-order recovery; `bf1dd290` a peer's
  `leavesQuantity` instrument cherry-picked with authorship intact; ledger
  `17a0ac2f` `13efd528` `466968e0` `69eba57f`.
- **DEPLOYED:** live-odds-worker `bf1dd290`, 20:38:53Z, fired by me, preflight
  CLEAR (the HOLD cleared on its own; no guard bypass was used or needed).
- **VERIFIED:** h2h `market_unresolved` x5 -> `would_build` at 19:54:08 with
  `yes_leg_index=0 away_index=0 agree=True`; live execution recovered after 55
  min (`EXECUTION status=ok placed=2`, 5 orders by 20:55, `BLOCKED` 0).
- **OWED — THE LEG CHOICE IS NOT VALIDATED.** Every reading is
  `yes_leg_index=0`, which IS `outcomes[0]`, so the OLD positional rule agrees
  and none of them discriminates. Needs a `yes_leg_index=1` market (4 wnba + 1
  boxing carry that shape). `agree=False` has never fired; the gate's refusal
  path is unit-tested only. NO moneyline has ever been SUBMITTED.
- **OPEN LIVE-MONEY RISK, NOT MINE, SURFACED `[2026-08-30 ~21:0xZ]`:**
  live-odds-worker runs `bf1dd290`, which CONTAINS `63661af1` (a peer's
  `never_sent` auto-reject) and does NOT contain `ef0d2d47` (their own REVERT of
  it as unsafe). Their reasoning is correct and I verified it: an order that
  FILLED after a LOST SUBMIT RESPONSE has no venue id, does not match by client
  id, and is absent from the OPEN book — exactly that branch's conditions — so
  it would be marked `rejected`, deleting a real position from the money record.
  It also ran immediately AFTER my three deliberate refusals and converted each
  into a silent write. **THE REVERT NEEDS A DEPLOY.**
  **DEPLOY ATTEMPTED AND BLOCKED `[2026-08-31 01:39-02:21Z]`.** Target
  `ef0d2d47` — the NARROW two commits past live, not tip (tip is +20 and full of
  other lanes' NCAAF work). It is READ, and TESTED at that exact SHA: 271 pass;
  the revert keeps their `stamped OR changed` persistence fix and leaves my
  three refusal paths intact; it is a descendant of live, not a rollback; and
  `3243b1c9` stays resolved because that ledger write PERSISTED, so shipping it
  does not re-open the outage. **40 consecutive preflights over 41 minutes ALL
  returned HOLD, minimum 3 jobs, never idle** — live-odds-worker is
  continuously busy in-season, unlike the 20:35Z window that let the last deploy
  through. The guard cannot be satisfied and `SYNDICATE_DEPLOY_GUARD=off` as an
  inline prefix does NOT work (it is a PreToolUse hook that reads the command
  before it runs — confirmed twice). **CLAIM RELEASED** rather than held, so it
  does not block the owning lane from shipping their own revert.
  **MEASURED EXPOSURE WHILE IT WAITS: ONE auto-reject in five hours**
  (20:39:51, the genuinely never-sent order, where the outcome was correct)
  against 98 healthy execution ticks. Real, rare, and cheap to wait on.
- Narrative: `log/2026-08-30.md`. Evidence:
  `findings_2026-08-30_polymarket_yes_leg_evidence.md`.
- Blocked by: none.

### layer1-model-edge-join — OPEN — opened 2026-08-30 — session 1c88bcca-be25-4164-a288-3a27d7e9dd57 — **UNOWNED, session 1c88bcca archived 2026-08-31.** Scorer released to lane `layer2-board-opportunities`, whose change is live and verified. Owed: MLB/WNBA/NCAAF coverage is UNREAD not flat — run `py -3 scripts/measure_model_edge_coverage.py` on the first build with a PREGAME slate.
- Goal: Layer 1 must join a MODEL edge on every sport/market, so Layer 2 /
  Kalshi / Polymarket rank on the sim's disagreement rather than on book hold.
- **SCOPE REQUEST GRANTED 2026-08-31 — the layer2 board scorer goes to lane
  `layer2-board-opportunities` (session 4465737c), which asked before touching
  it.** They measured the board this lane's fix produced: top 25 was 24
  `batter_home_runs` plus one totals, all 25 one-sided, top row model EV 85
  points against the best market-basis EV anywhere of about 5. Cause: model EV
  is edge divided by the fair probability, so it multiplies edge by the
  reciprocal of p and ranks a smaller edge on a longer shot above a bigger edge
  on a shorter one. I reproduced that reading myself before granting.
  **THE DECIDING ARGUMENT IS MINE AND IT IS A FLAW IN THIS LANE'S OWN WORK:**
  `blended_score` caps the model at fifteen points when it arrives as
  `model_edge`, and I routed the same information through `value_ev`, which has
  no cap at all. **Their flag must DEFAULT TO CURRENT until the user rules** —
  "price EV vs the model everywhere" is a user decision of 2026-08-30, and two
  sessions agreeing does not reverse one.
  This bullet sits ABOVE `- Files:` deliberately: prose placed inside or just
  after that block is parsed as a CLAIM, and doing it here is how this lane
  briefly claimed the tokens `1` over `p`, `15` point `0` and `85` point `13`.
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
- NOT CLAIMED, DELIBERATELY: `syndicate/features/shared/live_projection_join.py`
  is held by OPEN lane `live-prob-producer-reader-gap`. Imported read-only.
- STATUS: **DEPLOYED AND MEASURED** (`0fc174c6`, all three services). Seven
  defects found and fixed; soccer 2.2% -> 12.4%, nfl 27.0% -> 39.6%,
  `mfair_priced` 0 -> 3159, served top-200 rows with a model edge **1 -> 130**,
  `rows_uninformative_ev` **1269 -> 138**. EV is now priced against the model
  where a modelled fair exists (`ev_basis`), per user decision.
- **THE MODEL-EDGE WORK IS NOW MEASURED END TO END `[2026-08-31 17:00:33Z]`.**
  The scorer was released to lane `layer2-board-opportunities` on a scope
  request; their change is live on `cffbbd89` and verified: the ranking identity
  inverted exactly (`value_pct==model_ev` 50/50 -> 0/52, `==model_edge` 0/50 ->
  52/52), scores compressed 5x, top-25 market rows 3 -> 14. **The intended
  outcome is NOT achieved** — the top nine are still model-basis, best market
  row at rank 10, because edge is in probability points and market EV is in
  percent. `deploys.md` 16:48Z carries the working; the units question is
  UNSETTLED and is not this lane's to settle.
- **STILL OWED — the only reason this lane is OPEN:** MLB, WNBA and NCAAF are
  **UNREAD, NOT FLAT** (zero PREGAME games at every reading; `mfair_priced: 0`
  there is the sweep declining settled rows, not the sweep missing). WNBA's
  spread-frame fix has never fired in production — `rows_at_sim_market_line`
  still 0. Read it off the first build with a pregame slate:
  `py -3 scripts/measure_model_edge_coverage.py`; compare the PREGAME row.
- Narrative + evidence: `.syndicate/log/2026-08-31.md`,
  `.syndicate/findings_2026-08-30_layer1_model_edge_join.md`, and the full
  superseded block in `.syndicate/lanes_history.md`.
- Blocked by: none

### mlb-live-prop-prob-merge — OPEN — opened 2026-08-31 — session 1c88bcca-be25-4164-a288-3a27d7e9dd57 — **UNOWNED, session 1c88bcca archived 2026-08-31.** Fix deployed, unverified. Owed on the first live MLB game: `snapshot_live_prob_seen > 0` and `[live_lens] LIVE_PROB_CARRIED ... carried=N`. Watch for `carried=0` with `mc_rows_with_prob>0` — a key mismatch reads as success.
- Goal: get MLB's live prop probability onto the board. The producer emits it and
  a merge threw it away. `rows_live_edged` must become non-zero on a live game.
- Files: released: syndicate/features/mlb/live_lens.py, tests/test_mlb_live_prop_prob_merge.py (new)
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- NOT CLAIMED, DELIBERATELY: `syndicate/features/shared/live_projection_join.py`
  is held by `live-prob-producer-reader-gap`. That lane's open question — LOST IN
  THE JOIN vs NEVER PRODUCED — is ANSWERED here: **produced, then discarded**,
  which is neither of its two options.
- STATUS: **DEPLOYED (`0fc174c6`) AND UNVERIFIED.** `_carry_live_probability`
  stamps the MC row's `liveModelProbOver` onto the matching card row before the
  cards set replaces the MC set, keyed with `live_projection_join`'s own rule
  (imported, not re-derived). Producer emitted up to 27 rows against a published
  `with_live_prob` of **0**. Loop health confirmed on the new code.
- CONSTRAINTS THAT SURVIVE THIS LANE: (1) `#414` — price `liveModelProbOver` and
  NOTHING else; the `modelProbOver` fallback was shipped and BACKED OUT, do not
  reintroduce it. (2) `#124 follow-up (a)` — cards stay the primary ROW source;
  carry the probability ONTO them. (3) live PROP skill has never been measured;
  publishing an edge is not a claim that it is safe to bet.
- **VERIFICATION OWED — FIRST LIVE MLB GAME.** `snapshot_live_prob_seen > 0` and
  `rows_live_edged > 0` from `per_sport_ingest.mlb.enrichment.live_projections`,
  plus `[live_lens] LIVE_PROB_CARRIED gamePk=... carried=N` on refresh-worker.
  **Watch for `carried=0` with `mc_rows_with_prob>0`** — a key mismatch, which
  reads as success rather than as a crash. On a finished slate the line's
  absence is evidence of NOTHING.
- Narrative + the full `LIVE_MC_PRICED` series: `.syndicate/log/2026-08-31.md`,
  `.syndicate/lanes_history.md`.
- Blocked by: none

### layer2-cap-raise — OPEN, **UNOWNED** `[session 5611932c ARCHIVED 2026-09-01 ~01:4xZ]` — opened 2026-08-31 — **GOAL MET; ALL THREE INCIDENT DEFECTS CLOSED + VERIFIED IN PRODUCTION. ONE THING OWED: the 2000-cap raise is STAGED AND UNVERIFIED.**
- Goal: board carries >400 rows for a sport. **MET** at 1000 (932 → 1634 rows, no sport lost).
- Files: released: `pipeline/intelligence_state.py` **[claim REASSIGNED from `polymarket-yes-leg-binding`, same session]**; Render ENV on refresh-worker via the single-key API — never `render.yaml`. **NOW ALSO CLAIMS CODE:** `pipeline/intelligence_state.py`, `tests/test_layer2_shard_index_stale.py`, `tests/test_layer2_cards_shards.py`, `tests/test_shortlist_persist_ceiling_guard.py` — the last MOVED here from `polymarket-yes-leg-binding`, which had misfiled it. Same session owns both lanes; the file is the layer2 size instrument, not a venue file.
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Env live: `ROWS_PER_SPORT=1000`, `ROWS_TOTAL=3000`, `COMBINED_ROWS=0` (refresh-worker only; other two services clean).
- **DO NOT RAISE THE CAP AGAIN AS A CONFIG CHANGE.** The ceiling is the COMBINED key (~2,200 B/row even with `rows: []`) ⇒ ~3,600 TOTAL rows. Shard headroom is not evidence about it.
- **NEXT ACTION (owed, for whoever picks this up): the 2000/sport cap and ROWS_TOTAL=6000 are STAGED on refresh-worker but UNDEPLOYED, and the 75% warn threshold `c461693e` is on main and undeployed. Both ride the next refresh-worker deploy. They are UNTESTABLE until a full multi-sport slate — tonight the board is MLB-ONLY at ~547 rows, below even the old 1000 cap. VERIFY BY: a sport actually reaching >1000 rows; if none does, the raise stays untested however long it sits deployed.** Measured safe against REAL production rows (combined 220 B, worst shard 50.6–55.2%). Two caveats: the percentage is SLATE-DEPENDENT, and 3000/sport reads 74.6% — under the 75% line, so the warning is NOT a guard against a 3000 raise. REVERT of the cards flip remains one step: `SYNDICATE_LAYER2_CARDS_INLINE=1` + redeploy.
### polymarket-pregame-price-gate — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-31 — session 6475567d-f806-45a7-880c-f633718f2411
- Rationale: opened retroactively at the midday checkpoint; the two earlier
  deploys that day went out under the holder `ncaaf-totals-dispersion`, a BLOCKED
  NCAAF lane. Later deploys used this name. The engine files
  (`pipeline/execute_portfolio.py`, `syndicate/features/shared/polymarket_board_join.py`)
  are claimed by `polymarket-yes-leg-binding` and are DELIBERATELY NOT listed
  below: every edit was cross-lane with explicit user authorisation, and claiming
  them here contests a lane that owns them.
- Goal: a Polymarket order buys the side we chose, at a price the venue receives,
  or it is refused by name.
- Files: released: tests/test_execute_portfolio.py, tests/test_polymarket_board_join.py
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Hypothesis: pregame only CHEAP sides fill; once live everything fills.
- Falsification test: an explored order filling above 0.410 PREGAME. NEITHER
  probe did — pregame half SOLID (2 probes, 2 sports, ~20 reads each, 0 fills).
  LIVE half NOT replicating: `ast-ars` filled kick+17m47s, `bal-col` still
  resting at pitch+35m. The rule is PARTLY confirmed; see state.md.
- Verification: DONE — submit-price gate (`submit_price=` 15:53:26Z), band edge
  (`EXPLORE ... 0.450` 16:03:16Z), EV stamping (6/6 positive, 17:32Z), fill rule
  (`avgPx=0.4500 lastTransact=19:20:09Z`), wrong-side fix deployed both services
  (live-odds-worker d04d9f49 21:02:07Z, refresh-worker 8876b823 21:20:36Z, no
  regression 21:06Z). NOT DONE — the POSITIVE soccer case: no soccer h2h has
  resolved since the fix, so a CORRECT leg being selected has never been observed.
- Blocked by: none
- OPEN, NOT FIXABLE BY DEPLOY: `atc-sea-ata-bol` is a live position on the WRONG
  side (Bologna, not Atalanta). Manual close on the venue.
- NO WATCHER RUNNING. `btb81lzt8` died with the session at ~01:2xZ; reads from
  pitch+40m to +80m were never captured. Re-read `ORDER_STATE` for
  `aec-mlb-bal-col-2026-08-31` directly; do not assume a reading is coming.
- `gameStartTime` is ABSENT on all 10 `bal-col` slate rows, so liveness cannot be
  confirmed from the venue — only from the board's `commence_time`.

### soccer-shot-shrinkage — CLOSED 2026-09-02 — opened 2026-08-31 — session 1c88bcca-be25-4164-a288-3a27d7e9dd57 — **UNOWNED. GOAL MET 2026-09-01 — the divisor IS live in the engine, MEASURED, and `todo.md #612` is CLOSED.** Discharged not on the board but on the PREDICTION ARCHIVE the engine writes: self-normalised over the 3,434 players present both sides of the 2026-08-31 ship date, median post/pre `expected_shots` **0.720** against a predicted 1/1.3979 = **0.715**, with `expected_minutes_share` flat at **1.000** so the step cannot be "future fixtures carry fewer minutes". Tool `scripts/check_soccer_divisor_reached_engine.py`. Monthly re-fit ran the same day: **1.3979 -> 1.3930**, published and read back, no deploy. Residual (small): `players_*.csv` is not in `HOT_ARTIFACT_PATTERNS`, so the board-render form of the reading still cannot run from web. Detail in `.syndicate/deploys.md` 2026-09-01 15:0xZ. **CLOSED 2026-09-02:** goal met and measured; monthly re-fit automated as scheduled task `refit-soccer-shot-shrinkage`; re-checked one day on — the new dated file did not break resolution (shots/minute 0.726 vs 1.00-if-absent, n=3,428). The ONE residual is carried as `todo.md #636`, not by this lane.
- Goal: the soccer shots model stops over-predicting by ~1.4x. Ship the
  held-out-validated divisor as a DISK-BACKED, RE-FITTABLE calibration artifact,
  never a hard-coded constant. Testable: the served board's shot-prop
  probabilities fall, and `expected_shots` bias on the next backtest run moves
  toward 0 from +0.166.
- Files: released: syndicate/features/soccer/sim_engine/soccersim/player_props.py
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: syndicate/features/soccer/sim_engine/soccersim/shot_calibration.py
  released: syndicate/features/shared/artifact_publisher.py
  released: scripts/fit_soccer_shot_shrinkage.py
  released: tests/test_soccer_shot_shrinkage.py
- Evidence this rests on (all in `state.md [soccer-shots-prop-skill]`): n=9,840
  pairs / 247 matches / 9 leagues from production; ratio 1.398; held-out SCALAR
  MAE 0.5551 vs raw 0.6251 vs baseline 0.6278; SCALAR beats AFFINE in all 9
  leagues and all 4 splits. On-target RATE is already correct (model 0.345 vs
  actual 0.342, ratio 1.007), so one divisor at the `expected_shots` choke point
  fixes shots AND shots-on-target without a second constant.
- Hypothesis: correcting the MEAN is sufficient; the Poisson FORM needs no change
  (dispersion 1.07, P(>=2) bias -0.0001 over 597 players / 759 matches).
- Falsification test: if the served shot-prop probabilities do not fall after
  deploy, the artifact is not reaching the engine and the change is INERT --
  which is this repo's most common failure and the reason for the reachability
  test below.
- Verification: reachability FIRST (divisor 1.0 vs 1.4 produce different
  probabilities, driving the real shipped function), then a PRODUCTION read of
  the served board, then a re-run of
  `scripts/backtest_soccer_shot_props_production.py` on dates AFTER the deploy.
- SAFETY: absent/unreadable/out-of-range artifact -> divisor 1.0, i.e. exactly
  today's behaviour. Clamped to [1.0, 2.0] so a corrupt fit cannot zero the board.
- STATUS: **SHIPPED TO ALL THREE SERVICES, NOT YET OBSERVED WORKING.** web
  `132559e1` (allowlist), both workers `a35591dc` (wiring + dated resolver), all
  content-verified on the deployed blob. Artifact published 200 and READ BACK:
  `divisor=1.3979, n=9840, matches=247`. Divisor measured at 1.398x
  over-prediction; a SCALAR beat an AFFINE fit held out in all 9 leagues and all
  4 date splits.
- **THE VERIFICATION IS OWED AND CANNOT BE FORCED.** At publish time the board
  carried ZERO soccer shot-prop rows, and the soccer sim runs every FOUR HOURS
  (`SYNDICATE_SOCCER_PREGAME_REFRESH_INTERVAL_SECONDS=14400`). **Nothing is
  confirmed to have reached live-odds-worker.** The closing reading is
  composition-invariant: implied Poisson mean divided by that player's own
  season `shots_per90`, which was **1.19** before and must land near **0.85**.
  A median still near 1.19 WITH rows present means the artifact reached web but
  not the worker — that is the failure mode, not absence of rows.
- Blocked by: none. The soccer engine was unclaimed at open (verified with
  `lane_claim_audit.py`).

### layer2-accuracy-audit — OPEN, UNOWNED, SESSION ARCHIVED 2026-08-31 ~23:5xZ — **CLAIMS: NONE HELD, all four services free.** Handoff armed: scheduled task `check-mlb-pregame-freeze-611` fires 2026-09-01 08:30 CT (needs a manual Run-now for tool approval). **`#611`'s deployed log line is UNREADABLE — do not plan around it; read the artifact + run history instead.** 7-day board accuracy DELIVERED; MLB game-line join FIXED, DEPLOYED and VERIFIED (`13 -> 0` misses, `(pregame-freeze, 14 games)`, 20:33:17Z) — but it did NOT raise graded rows, which falsified my own causal claim. Two follow-ups opened as `todo #610` (caps: ml 12 candidates -> cap 1) and `todo #611` (prop seal dead since 08-16; cadence is the lead). **ONE THING OWED: `5be4381d` is on main and NOT DEPLOYED** — preflight HOLD, 3 jobs in flight on live-odds-worker. **AT RISK: 18 local commits incl. all ledger writes are NOT on origin/main.** — opened 2026-08-31 — session ef7e22fc-d592-43f7-b326-31ddea9258ef
- Goal: a per-sport x per-bet-type accuracy read on the Layer 2 board for the last 7 days, with an explicit statement of how many days and rows it actually rests on, plus ranked optimizations.
- Files: released: **CLAIMED 2026-08-31 ~18:3xZ, user asked for the MLB join fix:** `vendor/mlb_bettingv2/tools/eval/build_season_betting_cards_manifest.py` (`_odds_paths` + helpers only), `tests/test_season_betting_cards_odds_paths.py`. **EXTENDED ~18:4xZ, user asked for the backlog regrade:** `scripts/run_refresh_worker.py` (`_mlb_betting_day_backfill_*` only — NOT `_season_projection_should_launch`, which lanes.md flags as contended), `tests/test_refresh_worker.py`. Every OPEN-lane reference to `run_refresh_worker.py` is RELEASED; checked. Checked against every OPEN lane: no lane holds either. Still NOT editing `graded_outcomes.py`, `evaluation_settlement.py`, `layer2_shortlist.py`, `layer2_board.py`, `refresh_mlb_oddsapi.py`.
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Files: released: **CLAIMED 2026-08-31 ~18:3xZ, user asked for the MLB join fix:** `vendor/mlb_bettingv2/tools/eval/build_season_betting_cards_manifest.py` (`_odds_paths` + helpers only), `tests/test_season_betting_cards_odds_paths.py`. **EXTENDED ~18:4xZ, user asked for the backlog regrade:** `scripts/run_refresh_worker.py` (`_mlb_betting_day_backfill_*` only — NOT `_season_projection_should_launch`, which lanes.md flags as contended), `tests/test_refresh_worker.py`. Every OPEN-lane reference to `run_refresh_worker.py` is RELEASED; checked. Checked against every OPEN lane: no lane holds either. Still NOT editing `graded_outcomes.py`, `evaluation_settlement.py`, `layer2_shortlist.py`, `layer2_board.py`, `refresh_mlb_oddsapi.py`.
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- Hypothesis: Layer 2 accuracy is NOT measurable end-to-end today. Specifically (a) shortlist artifacts are retained only ~4 days, not 7; (b) the evaluation ledger settles 0.2% of settleable records because the GRADED-ROW SUPPLY is near-zero (mlb=1/day vs a documented ~700-2400), not because the matcher is broken; (c) NCAAF, the largest board sport by row count, has no grader at all.
- Falsification test: if `graded_rows_for_date('mlb', d)` returns hundreds of rows in production for a recent finished date, (b) is wrong and the defect is in the matcher. If dated shortlist artifacts exist for 2026-08-25..27 under any other read path, (a) is wrong.
- Verification: a written per-sport/per-bet-type table with denominators, or an explicit statement of which cells are unmeasurable and why, each backed by a production reading recorded here.
- Blocked by: none. Adjacent, not conflicting: `ncaaf-settlement-resolver` (764eca35) touches NCAAF settlement — will notify rather than edit.

**FINDINGS 2026-08-31 ~17:5xZ — hypothesis CONFIRMED on all three limbs, and the headline is a different number than the one I went looking for.**

**The measurable answer exists after all, and it is NOT the evaluation ledger.** The paper/live PORTFOLIO book is committed straight off `read_layer2_shortlist` (`pipeline/portfolio_commit.py:357`), so `/api/portfolio/paper?date=` and `/api/portfolio/live` ARE a Layer 2 accuracy surface. 7 days, 2026-08-24..08-30:

- **PAPER (our own grading, `settled_by=inferred` on 402/402): 47.9% win, +9.4% ROI, +$156.32 / $1,656.80 staked.**
- **LIVE (real money, kalshi+polymarket, 239 settled): 42.3% win, −5.5% ROI, −$40.31 / $733.31 staked.**
- Controlled-ish per venue: `paper:kalshi` **+1.1%** (364 settled) vs LIVE kalshi **−7.6%** (159 orders); `paper:polymarket` **+28.5%** (165) vs LIVE polymarket **−1.3%** (83). Same sign both times; bet sets are NOT identical (venue availability + gate/fill), so this is a flag, not an attribution.
- The ledger already carried this shape once: 2026-08-26, venue 3 bets −11.88% vs inferred 12 bets +51.07% (`paper_settlement.py:1224`).

By bet type (paper, 7d): game_line 56.7% / **+25.3% ROI [95% CI +7.2..+43.4]**, n=141 — the ONLY bucket whose CI excludes zero. game_total 47.5% / +9.8% [−9.3..+29.0] n=141. player_prop 37.8% / **−13.5%** [−33.5..+6.5] n=119. Real money inverts game_line: h2h+spreads 12W/23L = 34.3%, −23.9%.

By sport (paper, 7d): mlb 375 settled (94%), wnba 22, soccer 5, ncaaf **0**, nfl 0. Real money: mlb −6.8% (182), wnba +3.3% (31), nfl −4.1% (18), soccer −23.2% (8), ncaaf 0.

**Limb (a) CONFIRMED** — `/api/board/layer2-shortlist` returns `no_shortlist_artifact` for 08-25/26/27; only 08-28..08-31 exist. 4 dated snapshots, 2,623 rows.
**[CORRECTED 2026-08-31 ~18:2xZ] The MLB join cause is NARROWED BY CONTENT, and my first mechanism was wrong.** Read both `daily/snapshots` copies for 08-30: the pregame freeze holds **all 14 games**, names matching the warning strings verbatim, including CIN@CHC — the one game that DID grade. The live copy holds **0 games** (`retrieved_at` 08-31T04:52Z, post-slate). The builder graded 1 and warned 13, so it read a THIRD copy holding exactly one game, necessarily under `market/oddsapi/` — the tree `_odds_paths` resolves and the export endpoint cannot see. That is the **2026-08-16** failure shape (freeze written where the reader does not look; `refresh_mlb_oddsapi.py:646`), not the `_odds_paths` root-loop break I named first. **This is the THIRD occurrence of this symptom with the THIRD candidate cause — do not assume either prior fix.** Still not proven; needs a disk read of `market/oddsapi/`.

**Limb (b) CONFIRMED, and the cause is upstream of the matcher.** Settlement: 19,692 settleable, 35 settled (0.2%). `graded_rows_available` mlb = 1,2,1,1,1,7,0 per day. Independently reproduced on the WEB service from a different code path: `/mlb/api/market-accuracy?date=` returns `rows.all` = 1, 1, 7 for 08-28/29/30, with **12, 12, 13 `Missing game-line match for <game>` warnings** — i.e. ~1 of 13-14 MLB games joins. This is the SAME symptom `build_season_betting_cards_manifest.py:757` says was measured and fixed on 2026-08-07 ("13 of 14 games lost, one graded row for the whole day"). The sealed pregame freeze IS present and full-slate (`oddsapi_game_lines_2026_08_30_pregame.json` 76,872B vs live 1,105B), so the freeze is not the missing piece — `_odds_paths` breaks out of its ROOT loop on the first root that has EITHER file, so a root holding only the thin live copy wins over a later root holding the freeze. NOT VERIFIED — I could not read `market/oddsapi/` (not in `HOT_ARTIFACT_PATTERNS`, so `artifacts/export` is blind to it; absence there is NOT absence on disk).
**Limb (c) CONFIRMED** — ncaaf grader reads `cfbd_lines_*.json`; 0 such files in the hot-artifact set; 0 graded rows; 0 orders ever.

**The funnel, which is the real optimization target.** Refusals 08-24..08-31: **`no_model_edge_pct` 2,506**, `below_min_ev_pct` 1,567, below_min_stake 46, zero_kelly 37 — ~4,150 refusals against ~425 orders. Board-side this reconciles exactly: **`model_edge_pct` is numeric on only 902 of 2,623 rows (34.4%)**; `model_ev_pct` numeric on 201. `ev_basis` = market_fair 1,451 / model_edge 184 / model_probability 17 / unset 971. `model_skill.status`: measured 625, unmeasured 882, no projection block 1,116.
Quote quality: **books_quoting <= 1 on 1,511 rows (57.6%)**; book_age median 4,498s, p90 36,816s, 21.3% over 6h, 8.8% `suspect_stale`; movement not tracked 42.1%. ev_pct > 0 on only 444 rows (16.9%), median −2.35%.

**Corrected mid-audit:** I first read per-market medians of `model_edge_pct` as 0.00 and nearly reported "no model edge on 1,609 rows". The field is NULL on those rows, not zero — 0 rows carry a numeric 0.00. Same conclusion, different mechanism, and the wrong one would have sent the fix at the wrong function.

**NOT MEASURED, and it is the thing I most wanted:** whether the board's own `ev_pct`/`model_edge_pct`/`score` PREDICT the outcome. The portfolio endpoints expose settlement marginals only (`by_sport`, `by_market_family`, `by_venue_family`), not per-order rows, so no edge-bucket calibration curve was computed. That needs the refresh-worker-side order ledger.


### wnba-accuracy-assessment — OPEN, GOAL MET; EXCHANGE PRICES REACH A BOARD (VERIFIED); **NO DEPLOY OWED — that claim was STALE, corrected 2026-09-01**; ONE OWED ITEM DISCHARGED, ONE BOUNDED, ONE BLOCKED UNTIL 2026-09-17 — opened 2026-08-31 — session e542848e-6451-41a1-9e60-fd5a5675665d
- Goal: MET. WNBA went from six accuracy instruments reading zero to a settling, graded surface. `n_settled 38` (08-29) + `54` (08-30), `win_rate 0.6415094339622641` — byte-identical to the pre-deploy local run; `gradeable` false → true; `verify_wnba_settlement_gate.py` exit 0 on both dates.
- Deployed: web `ad33df21`, refresh-worker + live-odds-worker `1c078f46`. Four deploys, each verified on the SERVED PAYLOAD, not on deploy status. **ALL CLAIMS RELEASED; all four services free.**
- **CLAIMED 2026-09-01 (exchange prices onto the board):** `syndicate/features/shared/{book_shortlist,book_grid,odds_regions}.py`; `pipeline/kalshi_odds_refresh.py` (**`_capture_kalshi_quotes` ONLY** — the sibling lane's claim is `join_to_board`; they verified and accepted the one-line stamp); `syndicate/features/shared/odds_book_quotes.py` (**NEW `quote_rows_from_polymarket_matches` ONLY** — that lane claims its own `quote_rows_from_kalshi_matches`, explicitly NOT `_normalize`/`append_book_quotes`, and handed me Polymarket); `pipeline/portfolio_commit.py` (**`_capture_polymarket_quotes` + its one call site ONLY** — `portfolio-decision-and-execution` marks the file `released:`); NEW `tests/{test_direct_feed_provenance,test_wnba_odds_regions}.py`. NOT editing `polymarket_board_join.py` (`released:` by `open-bet-live-status`).
- Files (all landed on `origin/main`, nothing held): `syndicate/features/shared/{live_lens_paths,wnba_card_provenance}.py` NEW, `{live_lens_local,basketball_live_artifacts,artifact_publisher}.py`; `syndicate/features/wnba/{cards,live_lens_daily_accuracy,live_game_accuracy,live_prop_accuracy,live_prop_audit}.py`; `scripts/{build_wnba_recon,verify_wnba_settlement_gate,assess_wnba_accuracy}.py` NEW, `scripts/{run_refresh_worker,refresh_wnba_oddsapi_props}.py`; 6 new test files.
- Verification: settlement gate PASS ×2; signals `exists` false → true on **14/14 days** (1,814 records, matching an independent count); served card max `p_win` **0.99**, zero certainty claims; leakage note populated on the served payload.
- **OWED LIST RE-READ AGAINST THE SYSTEM `[2026-09-01, lane game-market-entry-roi-curve]`. Of the three, ONE IS DISCHARGED, ONE IS BOUNDED, ONE IS GENUINELY BLOCKED. The header's "ONE DEPLOY OWED" was STALE.**
  **(c) DISCHARGED — `refresh_nba_oddsapi_props`'s inversion is READ AND CLEAR.** It is not merely sharing the chokepoint; it carries the whole ported fix. Identical `_CERTAINTY_FLOOR/CEILING = 0.01, 0.99`, identical `certainty_clamped` counter, identical `_plausible_ev_pct` at `_MAX_PLAUSIBLE_EV_PCT = 100.0`, and at `refresh_nba_oddsapi_props.py:1246` the corrected `implied_prob * (1.0 + (ev or 0.0))` under a comment that names the source: *"THE INVERSION WAS DIMENSIONALLY WRONG (ported fix, WNBA `bef61c33`) ... EV per unit staked is q/p - 1, so the inversion is q = p * (1 + ev), NOT p + ev."* Dimensions check: `ev` is a fraction there (`ev_pct = ev * 100.0` one line above), so the expression is sound. **Nothing owed.**
  **(b) BOUNDED, NOT MEASURED, and it is NOT slate-blocked.** `_run_wnba_postgame_producer_tick` **is running now** — `WNBA_POSTGAME_PRODUCER` hourly at 19:08 / 20:09 / 21:10Z on 2026-09-01, backfilling 2026-08-16 / 08-15 / 08-14 with `boxscores rows 63 / 55 / 41 status=ok`. So its cost is measurable today rather than on 09-17. **The bound: refresh-worker shows `server_failed = 0` across 26 `deploy_ended` events, 2026-08-31T15:10Z..09-02T00:48Z** — the tick has not destabilised the worker. **That is evidence it is not fatal and is NOT a measurement of its cost**; container headroom cannot supply one (page-cache confound, `state.md [memory.current is page cache]`). Still owed as a real reading.
  **(a) GENUINELY BLOCKED until 2026-09-17**, exactly as written — the fields are baked into `recommendations_slate_*.json` and WNBA does not rebuild until the sprint. Carried by `#623`. Nothing to do before then.
  **DEPLOY: NONE OWED.** Web is live on `dd049490`, and both `417e19ed` and `07cb592a` are ancestors of it. The header said otherwise and was wrong.
  **ADJACENT — CHARACTERISED 2026-09-01 AND BENIGN, no action:** those 3 `live-odds-worker` `server_failed` events are `reason.earlyExit` because the worker **recycles itself every 6 hours on purpose** (`SYNDICATE_LIVE_ODDS_WORKER_MAX_UPTIME_SECONDS` default 21600; observed uptimes 22,712s and 23,606s, and its own `RECYCLING ... to reset accumulated page cache` line with `stage: before_exit`). Render labels a voluntary exit `server_failed`. **Not a defect, nothing owed.** Rule in `learnings.md`. Original note kept below:
  **ADJACENT, UNOWNED, UNCHARACTERISED — not this lane's and not filed:** `live-odds-worker` shows **3 `server_failed` in the same window, all `reason.earlyExit` (not oomKilled, not evicted)** — 2026-08-31T12:30Z, 09-01T09:53Z, 09-01T22:03Z. Could be a clean finish or a crash-loop; **the reason field does not say and I did not characterise it.** Distinct from `#632`, which is web and OOM.
- **OWED / NOT VERIFIED:** (a) T0-2, the T2-3 producer clamp and the `p*(1+ev)` inversion are **deployed but NOT IN FORCE** — those fields are baked into `recommendations_slate_*.json` and WNBA does not rebuild until **2026-09-17**; unit-verified only. (b) `_run_wnba_postgame_producer_tick`'s memory cost is REASONED, not measured (refresh-worker headroom read 96.8MB at 14:23Z). (c) `refresh_nba_oddsapi_props` shares the `_clamp_probability` chokepoint — its inversion is UNREAD, not cleared.
- Blocked on a live slate (2026-09-17): T0-1, T0-3, T1-5, T2-1, T2-2, T3-1..T3-5, T4-1/3/4. `todo #614`–`#617` carry the findings; **`#614` and `#616` were CORRECTED in place** after I named mechanisms from symptoms.
- **2026-09-01 EXCHANGE PRICES — VERIFIED.** `kept_direct=603` on the first grid build after the first Kalshi capture (`0` on every build before it); second capture +153; both post-capture builds agree. The provenance stamp and the grid rule that honours it are mine, the capture is `syndicate-e2`'s. Re-derived off Render by me, not taken from their report. Evidence in `deploys.md`.
- **The `near_misses` defect they reported in this file is FIXED — `07cb592a`.** It was my regression: provenance-based dropping created a second class of survivor and the counter's precondition assumed one. Moved under `else`. **Their suggested `continue` is a SILENT REVERT** — `freshest[key]`/`anchors[]` follow that block, so it deletes the kept row from the grid; measured (`assert 'kalshi' in {'fanduel'}`). Do not apply it.
- **DEPLOYED `417e19ed`, live 16:55:23Z. Both gates read.** `near_misses` gate **MET**: `kept_direct=603 near_misses={'kalshi': 603}` → `kept_direct=830 near_misses={}` (kept GREW while the false alarm went empty, so the counter was fixed rather than the rows suppressed). Polymarket gate **NOT MET**: `POLYMARKET_QUOTE_CAPTURE matches=60 sports=['mlb','soccer'] appended=0` — the capture is reachable and correctly wired, and wrote nothing because all 60 were GAME markets and the builder is props-only **by design**. **CORRECTED 2026-09-01 (chip session dee09146, deploys.md `c587010a`): matches can ONLY ever be game markets — the join refuses every PROP type (`polymarket_board_join.py:1329`, "PROP is fetched every cycle and thrown away"), so `appended > 0` is UNREACHABLE on `417e19ed` by construction, not pending a slate. Do not leave a watcher on this gate.** **Do not remove that bound to make the number rise** — OddsAPI already writes `polymarket` game rows under the same dedup key, so a second writer alternates rather than adds.
- **ALL FILES RELEASED, including `book_grid.py` — nothing here is claimed.** The near-miss counter fix is DONE and live (`07cb592a` in `417e19ed`); `kept_direct=869 near_misses={}` at 17:06:46Z. **A chip session was scoped on the pre-deploy symptom (`near_misses=603`) and on adding `continue` after `kept_direct_feed += 1` — DO NOT DO THAT.** `instance` / `freshest[key]` / `anchors[]` follow that block, so `continue` skips the kept row's registration and it never reaches the grid: measured `assert 'kalshi' in {'fanduel'}`. It presents as a perfect reading with zero exchange prices on the board. The shipped fix is `else`. `tests/test_direct_feed_provenance.py` pins both sides and will catch it.
- **Honest state of "exchange prices on the board":** Kalshi direct — YES, proven (830). Polymarket game — already arrived via OddsAPI, untouched. Polymarket direct — contributes nothing, and **CANNOT until the JOIN is changed**. CORRECTED 2026-09-01 (found by `syndicate-21`, verified by me on the code): `polymarket_board_join.py` refuses every unmapped type incl. PROP (`market_type_not_a_game_line`), so it emits game lines only and never sets `player_name`, while my builder consumes only rows WITH `player_name` — **empty intersection by construction**. Polymarket lists thousands of props; the join discards them. My earlier "fires on its own, nothing further needed" was wrong and would have left someone watching a gate that can never pass. The join-side fix is NOT "allow PROP": that bucket is MIXED (LoL map winners measured inside it), so characterise it first. Chip `task_4889e312` owns this; it needs `polymarket_board_join.py`, listed by `open-bet-live-status` (UNOWNED).
- **Traceability gap, both venues, by choice:** `venue_ticker` persisted on 0 of 603 rows (`_normalize` keeps a fixed key set). Removed from my builder; a boundary test now asserts EVERY builder's keys survive `_normalize`. One-line fix (`venue_ticker` into `_normalize`) written down and deliberately not taken — a shared-schema change that would leave one venue traceable and the other not.
- Blocked by: none. Next: **`#623`** (the 09-17 sprint + pre-registered gates + parked `#614`/`#616` reads) and **`#626`(d)(e)** (reuse-guard/live-capture, klass-hole). **`#622`** owns the ranking-key question — per `#615` T2-1 is ANSWERED (no sim-derived key exists; do NOT keep re-looking at the 656-row sample, ~30 looks are already on record). `scripts/prereg_wnba_favourite_lean.py` is frozen and waiting for the sprint.



### ncaaf-games-cache-refresh — OPEN — opened 2026-09-01 — session b85e895e-dde2-4066-8336-dc6c1d4c3c61 — **DEPLOYED `cc1feccc` to BOTH services (web 21:21:43Z, refresh-worker 21:56:06Z). Web half VERIFIED discriminatingly (200 vs 403 allowlist probe). Producer half LIVE BUT UNPROVEN — the daily gate does not fire until ~00:26Z. Two verifications ARMED as scheduled tasks.**
- Goal: `ncaaf_target_week` returns the real current week instead of a permanent
  1, on BOTH services, without web ever calling CFBD.
- THE DEFECT: `ensure_games_cached` returns early on `path.exists()`, so
  `games_2026.json.gz` (written 2026-07-21, one commit `5da1dd21`) was never
  re-fetched. 888 games, `completed: False` on **888 of 888**, so
  `min(week with an unplayed game)` is 1 forever.
  `/ncaaf/api/cards?week=2` and `?week=3` both served `"2026 Week 1"` with nav
  `next=prev="1"`; ops `season-weeks` reported artifacts for weeks [1-13, 15]
  and `resolved_active_weeks: [1]`.
- NOT WRONG YET, COMES DUE 2026-09-08: week 1 spans 08-29..09-07, so target=1 is
  correct today by accident. Week 2 kicks off 09-11. Verified against the real
  file that an honest refresh does NOT advance the week early (8 games past
  kickoff, matching the board's own `Final: 8` from a different code path).
- NOT the cause of the 0-NCAAF-orders gap — the Layer 2 / book-grid path
  resolves the week from the schedule BY DATE
  (`game_projections.py::load_ncaaf_game_projections`) and bypasses this gate.
  That gap is `edge_vs_market_pct = None` on all three NCAAF markets, deliberate
  and documented in `ncaaf/game_projections.py`.
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
- **CONTESTED, SURFACED NOT MERGED: `syndicate/features/shared/artifact_publisher.py`
  is claimed by OPEN lane `football-projection-publish-allowlist` (`#618`),
  which opened AFTER this work began. **That lane is on `origin/main` and is
  NOT in this tree's copy of `lanes.md` (local `main` is behind), so
  `check_lane_invariants.py` reports INVARIANTS HOLD here — a healthy reading
  for the wrong reason. The contest is real and will appear on the rebase this
  branch has to do before it can land.** My edit is purely additive — one pattern
  plus its note, appended after that lane's two entries, changing nothing about
  them — and the allowlist is the only mechanism that can permit the transfer,
  so there is no alternative route. Committed on the session branch only.
  DO NOT LAND until that lane's owner or the user agrees.**
  tests/test_ncaaf_games_cache_refresh.py (NEW),
  tests/test_ncaaf_week_state.py (NEW),
  tests/test_ncaaf_sp_ratings_cache.py (docstring only)
- **CROSS-LANE, AUTHORISED AND LOGGED. NOT CLAIMED HERE ON PURPOSE:**
  `artifact_publisher.py` **WAS** claimed by OPEN lane
  `football-projection-publish-allowlist` (`#618`), and the claim STAYS THERE —
  my edit is finished and landed, so holding a second claim would only block
  that lane for no benefit. **`[2026-09-01, ownership pass: THAT LANE IS NOW
  CLOSED — goal met and verified on the served artifact — and its block moved to
  `lanes_history.md`. `artifact_publisher.py` is therefore claimed by NOBODY and
  is FREE TO TAKE. This bullet's deference no longer points at anything; it is
  kept because it records why this lane chose not to claim, not because the
  other lane still exists.]`** It is listed in this bullet rather than in `Files:`
  for exactly that reason; the edit is recorded, the lock is not taken. **USER OVERRIDE
  2026-09-01: "go ahead and land it, the allowlist edit is additive."** It is
  one pattern plus its note, appended after that lane's two entries; both of
  theirs verified intact on origin/main after the rebase, and THEIR OWN test
  (`tests/test_football_projection_publish_allowlist.py`) passes against the
  landed tree. No alternative route existed — the allowlist is the only
  mechanism that can permit the transfer.
- TWO CONSTRAINTS THAT SHAPED THE FIX, both measured:
  (a) this loader's `_cfbd_get` is raw urllib with NO `cfbd_backoff` and NO
  `cfbd_quota_latch` — a refresh added naively here rebuilds the hourly hammer
  `ncaaf-cfbd-quota-latch` shipped to stop, on a path the latch cannot see.
  (b) the refreshed cache CANNOT reach web: `publish_hot_artifact` reads
  sub-4MB files as UTF-8 text, so the 39KB `.gz` raises UnicodeDecodeError ->
  `SKIP_READ_FAILED`. Hence a small owned JSON artifact (`week_state.py`)
  rather than a web-side CFBD call: web reads counts the worker derived.
- Verification: DONE LOCALLY. 276 tests green (153 ncaaf + 123 publisher), no
  regressions. Covers off!=on for the refresh, the artifact WINNING over the
  stale cache (order, not just parsing), the fallback when no artifact exists,
  `ncaaf_target_week` never reaching CFBD, and the written path being one
  `HOT_ARTIFACT_PATTERNS` actually matches — that last is the half that was
  inert for 13 days on the sibling entry.
- ~~**OWED: no production reading. NOT DEPLOYED, NOT PUSHED.**~~ **PAID
  2026-09-01 21:05-21:15 CDT (scheduled verification run). THE FIX IS PROVEN
  IN PRODUCTION.** Full measurement: `deploys.md` -> `## 2026-09-02 --
  refresh-worker/web cc1feccc -- NCAAF week_state producer`.
  - Shipped as `bc2365fc` + `c1c3cf12` -> `cc1feccc` (this block's `cf41d1a9` /
    `5a88f20b` are the PRE-REBASE session-branch SHAs; the landed pair differs).
    Both services have since moved on -- refresh-worker `ad1de331`, web
    `dd049490` -- and all three SHAs are ancestors of BOTH, so the fix is on
    what is actually running (checked by ancestry, not assumed).
  - Producer ran: `SEASON_PROJECTION_LAUNCHING sport=ncaaf ... reason=artifact_stale
    age_seconds=86537` at 19:35:41 CDT. Daily gate fired as predicted.
  - **DECISIVE: the artifact crossed to web.** `/api/ops/artifacts/export` ->
    HTTP 200 `count:1`, `stale_completion_flags 0`, **week 1 completed 8 /
    unplayed 91** against the write-once file's **0 of 888** (re-verified on the
    2026-07-21 copy today). Allowlist CONTROL returned 403, so the 200 counts.
    8 is corroborated by the kickoff distribution -- only 8 week-1 games had
    kicked off (7 on 08-29, 1 on 08-30, none until 09-03).
  - `resolved_active_weeks [1]` -- CORRECT today, not a regression; week 1 runs
    08-29..09-07. The advance remains the 2026-09-08 check.
- **INSTRUMENT DEFECT FOUND, NOT FIXED (read-only run):** the prescribed log
  readings `GAMES_CACHE_REFRESH` / `WEEK_STATE` CANNOT EVER REACH Render.
  `log()` at `scripts/generate_smartsim2_ncaaf_projections.py:796` writes only to
  the `--progress-log` FILE, never stdout -- so every `log(...)` in that script is
  invisible to the collector. A `BOARD_HEALTH sport=ncaaf` control over the same
  window returned 24 hits, so the logs API was healthy and the absence is the
  emitter's. Fix would be one `print(message, flush=True)`; nothing else in the
  lane depends on it. **The lane's own stated proof was unattainable by
  construction** -- the artifact read replaced it.
- Commits (session branch `session/ncaaf-games-cache-refresh`, LANDED as
  `bc2365fc` + `c1c3cf12`): `cf41d1a9` refresh producer, `5a88f20b` week-state
  artifact.
- Blocked by: none (the contested file needs a decision, not a blocker).

### keyvalue-pressure-637 — CLOSED 2026-09-03 — **USER DECISION: leave the reclaim to the TTL** — opened 2026-09-02 — session 92987093-6cef-495b-a82b-4bb376dc45dc
- **STATUS 2026-09-02.** Diagnosis DONE and the fix SHIPPED and MEASURED on both
  workers (`#638` `21de4a9e`, `#637` `e4a471c0`) — see `state.md
  [venue-odds-storage]` and `log/2026-09-02.md`. **This lane stays OPEN for ONE
  thing only: the ~115 MB is NOT reclaimed.**
- **CENSUS RE-RUN TWICE 2026-09-02 (22:19 and ~23:0x CDT) — IDENTICAL, exit 2.**
  42 keys / 100.3 MB, SAFE 27 / PENDING 15. Nothing expired.
- **CORRECTED 2026-09-03 — I HAD THE BLOCKER WRONG, in this file, in the log, and
  in the scheduled task's prompt.** I said repeatedly that the hold-up was
  "refresh-worker has not written polymarket, and doing so clears ~13 of the 15".
  **That was never true.** The census already knows refresh-worker does not write
  that venue: every `polymarket__*` row lists `live-odds-worker` ALONE as expected
  to hydrate. Refresh-worker was never owed those keys. Confirmed in the logs —
  `venue_odds_loop` on refresh-worker DOES reach polymarket
  (`REFRESH venue=polymarket status=ok count=2000`), but that refreshes the venue
  CATALOGUE; the daily book is written by `run_live_odds_refresh_worker.py`, which
  runs only on live-odds-worker. **Zero `POLYMARKET_DAILY_BOOK` on refresh-worker
  since go-live, and that is correct behaviour, not a stall.**
- **WHAT THE 15 PENDING KEYS ACTUALLY ARE `[2026-09-03]`:**
  - **7 are PAST GAME DATES** — `kalshi mlb 08-31/09-01`, `kalshi nfl 08-29`,
    `kalshi soccer 08-30/08-31`, `polymarket mlb 09-01`, `polymarket wnba 08-30`.
    Nothing writes those dates again, so they can **NEVER** hydrate. TTL only.
  - **8 are FUTURE dates not in a current slate** — `polymarket ncaaf
    09-06/09-11/09-12`, `polymarket nfl 09-09/09-10/09-13/09-14`,
    `polymarket soccer 09-07`. These clear only if the fixture enters a slate
    before the TTL expires.
  **So the reclaim is NOT "pending, clearing shortly" — at least 7 of 15 are
  permanently blocked and the 10-day TTL is the actual mechanism, not a
  fallback.** Waiting adds nothing.
- **A third reading is ARMED (its prompt has been corrected too):**
  scheduled task `check-venue-odds-hydration-census`, one-shot
  2026-09-03T04:19:00Z, report-only, expiry forbidden in its prompt.
  **That task lives OUTSIDE the repo** (`~/.claude/scheduled-tasks/...`) and is
  captured by no commit. **Its first fallback was wrong and is fixed** — it had
  pointed at the primary tree, which does NOT contain the script.
  **The script exists only in this session's worktree and on `origin/main`;
  worktrees are session-scoped**, so if it is closed before the fire time the
  task stops and the reading is owed to a human.
- **CLOSED 2026-09-03 `[user decision: "leave it, ttl is working"]`.** Nothing is
  owed. The reclaim happens by itself: the store went **42 keys -> 40 overnight**
  with no intervention, and all six UNREACHABLE keys are past-date and clear
  within days. Scheduled task `check-venue-odds-hydration-census` DISABLED — a
  further reading cannot change a decision that has been made.
- **FINDING, and it is the reason the decision was easy: NO EXISTING OPS ENDPOINT
  CAN EXPIRE A `venue_odds` KEY.** Established by DRY RUN against production, not
  by reading code alone:
  `POST /api/ops/keyvalue/expire-run-artifacts?path_contains=venue_odds&dry_run=1`
  -> **`matched_keys=69, expired_keys=0, skipped_no_run_stamp=69,
  estimated_reclaimed_mb=0.0`**. It selects on a `_YYYYMMDD_HHMMSS` RUN STAMP
  (`run_20260903_051200`); a venue_odds key is `kalshi__mlb__2026_09_01.json` —
  `YYYY_MM_DD`, no time component — so every one is skipped by design rather than
  guessed at. `/api/ops/keyvalue/sweep` cannot touch them either: it targets
  currently-TTL-LESS keys, and these all carry the 10-day date-scoped TTL.
  **Expiring them would require NEW code (targeted expire-by-key), i.e. a new
  production-mutating capability on the shared Redis, for 26 MB. Not written.**
- **A TRAP FOR WHOEVER DOES WRITE THAT:** `path_contains=venue_odds` matched
  **69** keys, not the 40 the census enumerates — it is a substring match over the
  whole namespace. A targeted tool must select on the EXACT key set, or its blast
  radius will exceed what was authorised.
- ~~**THE ONLY REMAINING ACTION, and it is gated, not free.** Run~~ (superseded by
  the decision above; the census remains the gate if anyone revisits this) Run
  `py -3 scripts/check_venue_odds_hydration_census.py`. It exits 0 only when every
  censused key is SAFE and the key listing was not truncated. First run:
  **27 SAFE / 15 PENDING / exit 2 — NOT safe to expire.** Expiring a key a service
  has not yet hydrated makes that file start empty, and an accumulator that starts
  empty **re-dates every `opened_at` to the expiry moment** — wrong data,
  permanently, with no way back. The 10-day TTL reclaims it at zero risk.
- **What moves it to SAFE:** refresh-worker writing polymarket at least once
  (should clear ~13 of the 15). Two `kalshi__mlb__2026-08-3x` keys will never
  hydrate — those game dates have passed and nothing writes them — so they clear
  only via TTL.
- Claims: `.gitignore` and `scripts/check_venue_odds_hydration_census.py`.
- Also owed from this lane's work: **refresh-worker's `#638` trim path has never
  executed in production** (its rejections stopped 50 min before its own deploy,
  the other worker's trim having shrunk the shared key). It verifies itself the
  next time that service is first to push a file past the budget.
- Goal: `#637`. Say WHAT holds the shared Redis at 93% and WHETHER the eviction it
  is doing costs anything, with numbers. Diagnosis only — **no production mutation
  in this lane.** `/api/ops/keyvalue/expire-run-artifacts` and `/api/ops/keyvalue/sweep`
  are both POST and both destructive; neither is called without an explicit decision.
- Files: `.gitignore` (claimed 2026-09-02 ~21:0xZ — the `venue_odds` runtime-output
  entry; it is fallout of THIS lane's own move to disk, so it belongs here),
  `scripts/check_venue_odds_hydration_census.py` (NEW, claimed 2026-09-02
  ~19:5xZ — the gate on the Redis reclaim; read-only against production, performs
  no expiry). Otherwise read-only investigation. If it produces a code change
  the fix gets its own lane and its own claim.
- Hypothesis (written BEFORE the reader trace): `reports/intelligence/venue_odds/`
  is the dominant consumer, and a material slice of it is DEAD — files keyed to
  game dates already in the past, kept alive only by the blanket 10-day
  date-token TTL, long after the CLV comparison they exist for could be made.
- Falsification test: a reader that legitimately needs past-date venue_odds files
  for the full 10 days falsifies "dead". Then the pressure is real load, not
  waste, and the answer is a smaller retained payload or a bigger instance — not
  expiry.
- MEASURED SO FAR (web, 2026-09-02, `/api/ops/keyvalue/{usage,diagnostics}`):
  - store **2,650 keys / 224.3 MB estimated**; Redis `used_memory` **250,937,536**
    of `maxmemory` **268,435,456** (~93%), policy `volatile-lru`,
    `evicted_keys` **11,852** over an uptime of 936,662s (~10.8 days, so ~1,100/day
    against 2,650 resident keys), `keyspace_misses` 13.27M vs `keyspace_hits` 9.85M.
  - **`reports/intelligence` is 194.92 MB — 87% of the store.** Everything else
    combined is ~30 MB.
  - Inside it, **41 `venue_odds` keys hold 114.9 MB — 51% of the whole store.**
    By sport: ncaaf 48.0, mlb 43.7, soccer 12.3, nfl 8.9, wnba 2.0 MB.
  - Game dates span **2026-08-29 .. 2026-09-14**. The three dates already in the
    PAST hold **29.4 MB** (08-29 9.0, 08-30 2.9, 08-31 17.5). A single future
    date, 09-05, is already at **22.5 MB** three days out.
  - Mechanism: `venue_daily_odds.record_daily_odds` is an ACCUMULATOR — it reads
    the existing state, appends a price point per market per tick, and writes
    back. `MAX_POINTS_PER_MARKET = 48` caps per market, so growth is in the
    market COUNT, and a lookahead market opens days before its game.
- Verification: a reader trace for `daily_odds_path`, stating which consumers read
  a PAST-date file and over what horizon; plus whether these are duplicated to
  disk via `HOT_ARTIFACT_PATTERNS`.
- **HYPOTHESIS CONFIRMED, AND THE REAL DEFECT IS BIGGER AND DIFFERENT FROM
  MEMORY PRESSURE.** Two findings, in order of what matters:

  **(1) `venue_odds` WRITES ARE FAILING IN PRODUCTION RIGHT NOW — 2,203 rejected
  writes on live-odds-worker between 2026-09-01T00:00Z and 2026-09-02T16:04Z.**
  Found by predicting it from the sizes rather than by reading logs at random:
  keys sitting exactly on the 8 MiB allocator bucket should be hitting
  `_guard_keyvalue_payload_size`, and they are.

  | key | rejections |
  |---|---|
  | `kalshi__ncaaf__2026_09_05.json` | **964** |
  | `polymarket__ncaaf__2026_09_05.json` | **688** |
  | `kalshi__mlb__2026_09_01.json` | 162 |
  | `kalshi__mlb__2026_08_31.json` | 137 |
  | `polymarket__mlb__2026_09_01.json` | 136 |
  | `polymarket__mlb__2026_08_31.json` | 116 |

  Sample: `size_bytes=8789596 max_bytes=8388608 caller=venue_daily_odds.py:293`.
  **NOTHING outside `venue_odds` is being rejected** — the whole 2,203 is this
  one artifact class. Each rejection means that tick's price points were
  DISCARDED: the file froze at its last sub-ceiling write and every subsequent
  move is lost. NCAAF 09-05 has been frozen for ~40 hours and counting.

  **Blast radius is contained, checked not assumed:** `record_daily_odds` catches
  the write and returns `{"status": "error"}`, and `record_venue_book` loops over
  every `(sport, game_date)` group, so one oversized file does NOT abort the
  others. It is counted in `errors` and logged — and nothing acts on either.

  **ROOT CAUSE: the trim caps are dimensionally wrong.** `MAX_POINTS_PER_MARKET
  = 48` and `MAX_MARKETS_PER_FILE = 8000` bound COUNTS, while the constraint
  that actually fires is BYTES. 8,000 markets cannot fit in 8 MiB at any
  plausible per-market size, so the cap can never be the thing that keeps the
  file writable. The module's own docstring says the per-(sport, date) split
  exists *because* "the keyvalue store refuses at 8MB" — the split is simply not
  fine enough for an NCAAF slate.

  **(2) THE 114.9 MB HAS NO READER AT ALL — not "no past-date reader".** Full
  trace: `venue_odds` appears in exactly three modules. `venue_daily_odds.py`
  (defines the path; the only read is `record_daily_odds`'s own
  read-modify-write of the file it is about to write), `venue_odds_loop.py`
  (drives the writes), and `intelligence_state.py` (comments + starting the
  loop). Both external importers — `kalshi_odds_refresh.py:1190` and
  `run_live_odds_refresh_worker.py:903` — import only `record_venue_book` and
  `*_daily_rows`, i.e. WRITE paths. Nothing consumes the record.
### venue-quote-tests-data-dependent — CLOSED 2026-09-02 — opened 2026-09-02 — session 92987093-6cef-495b-a82b-4bb376dc45dc
- Goal: `tests/test_venue_quote_adapters.py` passes in a SESSION WORKTREE, which
  excludes `data/`. It currently fails 3 of 6 there and passes 6 of 6 in a
  checkout that has `data/` — so every session sees red tests by default in the
  tree the protocol tells it to work in.
- Files: `tests/test_venue_quote_adapters.py`. Checked against every OPEN lane:
  not claimed. **No production code changed** — this was never a code defect.
- Hypothesis: the failures are ENVIRONMENTAL, not a regression.
  `canonical_team("soccer", ...)` resolves through `_soccer_alias_to_name`, which
  is derived at runtime from `data/soccer_source/**` team artifacts.
- **MEASURED, both directions:** alias map is **0** entries in the worktree and
  **508** in the primary tree; `canonical_team("soccer","ars")` -> `None` vs
  `'arsenal'`. Tests: **3 failed / 3 passed** without `data/`, **6 passed** with.
- **NEARLY MISREPORTED AS A PRODUCTION DEFECT.** The failures surface as
  `status='no_rows'`, and the tests' own docstrings name the live symptom
  `no_polymarket_row_for_league_soccer`. Both fixes those tests guard ARE
  present in the code (`SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME -> h2h`, and the
  `_effective_league` indirection). Checked before concluding.
- **THE WORSE HALF, and why the fix is a fixture rather than a skip:**
  `test_an_unresolvable_pair_is_not_relabelled_as_soccer` PASSED without `data/`
  — vacuously. With an empty alias map every pair is unresolvable, so it could
  not fail and could not detect what it exists to detect.
- Falsification test: if the stub made the tests vacuous, poisoning its map so
  the bogus clubs resolve would NOT flip the result. **Ran it: the mutation
  turned the unresolvable-pair result to `ok` and the test FAILED**, so it is
  discriminating where it previously was not.
- Verification: 6/6 pass with `data/` absent AND with `SYNDICATE_DATA_ROOT`
  pointed at a real `data/` (508 aliases loaded). Both run.
- **CLOSED 2026-09-02. The named file is FIXED AND LANDED (`30baa584`, 6/6 green with
  and without `data/`, mutation-tested). The SUITE-WIDE SWEEP that followed is a
  MEASUREMENT recorded here, not work delivered — nothing else was changed.**
- **THE SWEEP.** Differential over 87 files / 2,672 tests. PASS 1 without `data/`:
  **118 failed / 2,482 passed / 72 skipped** (1:14:41). Buckets: A data-dependent,
  **B fails-in-both 15**, **C passes-without-fails-WITH 5** — all
  `test_ops.py::...build_refresh_plan_uses_*_syndicate_runner_in_source_mode`,
  which pass only when the mirror is ABSENT. That is its own defect and is NOT fixed here.
- **BUCKET A, AFTER A CONFOUND WAS FOUND AND REMOVED:**
  | | count |
  |---|---|
  | genuinely data-dependent (fail ISOLATED, no `data/`) | **92** |
  | NOT data-dependent — pass isolated, failed only at 2,672-test scope | **2** (`test_kalshi_catalogue`) |
  | unmeasured — batch returned `rc=4` | **9** (`test_team_aliases`) |
  **The first reading was wrong: PASS 2 changed SCOPE as well as data** (24 files,
  not 87), and pollution at the larger scope is indistinguishable from
  data-dependence in that comparison. Standing rule written to `learnings.md`.
- **WORKING SET: 252 files / ~33 MB** against `--with-data`'s **34,690 files /
  3.55 GB** — ~**0.9%**. `test_archives.py`, the only module reaching
  `mlb_source`, needs **26 of its 31,857** files. A targeted sparse-include is viable.
  **A FLOOR, NOT A BOUND:** 4 modules / 40 tests fail without `data/` while opening
  NOTHING — they check EXISTENCE (`TEAM_REGISTRY_RELATIVE_PATH`), and
  `Path.exists()` raises no `open` audit event. Date-stamped paths also force any
  pattern to be directory-level, so the 26 drifts with the mirror.
- **NO FIXTURE WAS ADDED FOR THE 92, deliberately.** Both readings make it worse and
  the tests say so: `test_ncaaf_team_registry_reachability` — *"A value assertion
  over a fixture cannot catch either — the fixture is the thing that lied"*; and
  module-level skips would drop **601 passing tests**, 353 in `test_archives.py`,
  the file CI runs. The tests are right; the ENVIRONMENT is wrong.
- ~~**ALSO OBSERVED, not chased:** the suite MUTATES tracked files —
  `data/mlb_source/.../live_lens_2026_06_02.jsonl`,
  `reports/intelligence/kalshi_markets.json`, and
  `vendor/wnba_betting_repo/data/processed/schedule_2026.{csv,json}` were dirty
  after these runs and had to be restored before committing.~~
- **RETRACTED 2026-09-02, SAME SESSION. THE SUITE DOES NOT DIRTY TRACKED FILES,
  AND I ALSO MISDIAGNOSED THE CAUSE ON TOP OF THE WRONG OBSERVATION.**
  - **Each of the 24 modules run ALONE: tree clean.** All 24 run TOGETHER
    (1,031 tests, 115 failed / 911 passed): **tree clean.** Restored baseline
    before each. The claim does not reproduce under any configuration I ran.
  - **Two of the three tracked files were ALREADY MODIFIED AT SESSION START** —
    `live_lens_2026_06_02.jsonl` and both `schedule_2026.{csv,json}` appear in
    this session's opening `git status` snapshot, before I ran anything. I
    attributed pre-existing dirt to my own test runs.
  - **The likely real cause of what I saw is MY OWN HARNESS:** several passes
    ran with `SYNDICATE_DATA_ROOT` pointed at the primary tree's real `data/`,
    which is exactly the override the isolation fixture documents as taking
    precedence. Setting a real root disables the isolation for anything
    resolving through it. Not proven — I declined to prove it, because proving
    it means deliberately dirtying the SHARED primary tree.
  - **AND THE FOLLOW-UP DIAGNOSIS WAS ALSO WRONG.** I called this a "conftest
    subprocess leak". There is no leak: `_isolate_reports_root` uses
    `monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", ...)`, and **subprocesses
    inherit environment variables**. I named a mechanism from a symptom —
    saw dirty files, saw a `patch.object` in a nearby fixture, assembled a
    story — which `learnings.md` already forbids by name.
  - **NOTHING WAS CHANGED IN `conftest.py`.** There was no defect to fix. The
    fixture is correct as written.
  - The one thing here that IS true and unaddressed: the suite-wide isolation
    covers `reports_root()` only. `data_root()` and `vendor/` have no
    equivalent seam, so a test that resolves through those CAN reach tracked
    files. That is a gap in coverage, not an observed failure, and no test I
    ran exercised it.
- Blocked by: none.


### wnba-cards-fallback-recursion — CLOSED 2026-09-02 — GOAL MET, ON A PREMISE THAT WAS WRONG — **PREMISE FALSIFIED: recursion is REAL (depth 234, 700 calls) but costs +5.7s, not minutes; the stall was KALSHI. CONTROL DONE: the cycle fires ONLY on an empty artifact (one CSV row -> depth 1), so it is COLD/DEV-ONLY and LOW severity; the real defect is the SWALLOWED RecursionError. **FIXED: depth 247 -> 1, bundle calls 701 -> 2, and the failure is now NAMED**** — opened 2026-09-02 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885
- Goal: `syndicate/features/wnba/cards.py` cannot re-enter itself. ONE testable
  outcome: with the recursion path ENABLED (no `SYNDICATE_WEB_DYNO`, date ==
  today), `tests/test_intelligence.py::IntelligenceBlueprintTests::test_intelligence_query_api_resolves_preview_date_and_preserves_contract`
  completes in the same order of time as with it disabled (~22s), and a test
  proves the cycle cannot recur.
- Files: `syndicate/features/wnba/cards.py` (`_artifact_bundle` +
  `_games_from_live_state_fallback` only), `tests/test_wnba_cards_fallback_recursion.py` (NEW).
- Hypothesis: **mutual recursion, bounded by Python's recursion limit rather
  than by design, and SILENT.** `_artifact_bundle:1686` calls
  `_games_from_live_state_fallback(selected_date)`; `:3078` calls
  `_artifact_bundle(selected_date)` straight back. `_artifact_bundle` is NOT
  memoised (checked), so nothing breaks the cycle. It fires only when
  `not rows and selected_date == central_today_iso() and not _render_web_dyno()`
  -- date-triggered, which is why it is not a standing red. Each level does
  artifact path checks and JSON loads, so ~500 nested pairs is the cost.
- **NOT "an infinite hang", and I will not repeat that framing.** I called it
  one earlier today and was wrong twice about this same test (see
  `learnings.md` 2026-09-02, "slow and hung are not the same finding"). The
  recursive call sits inside `try: ... except Exception: rows = []`, and
  `RecursionError` subclasses `Exception` -- so it is most likely CAUGHT, making
  this pathologically slow AND silent rather than fatal. Unverified: I have
  never let this run to completion without `SYNDICATE_WEB_DYNO=1`.
- Falsification test: if the same test completes in normal time with the guard
  path enabled, the recursion is not the cost and this lane is wrong. Equally,
  if the recursion does NOT terminate (no `RecursionError`, no completion), the
  "bounded and caught" half is wrong and the fix must differ.
- Verification: (1) TIME the test with the recursion path enabled, before any
  change -- the baseline this lane rests on does not exist yet; (2) a test that
  drives `_artifact_bundle` down the fallback branch and FAILS if
  `_games_from_live_state_fallback` re-enters it (assert on call depth, not on
  wall clock, so it cannot pass by being fast on a quiet machine); (3) off != on
  -- the fallback must still return its rows when reached legitimately, or the
  fix is a silent feature removal.
- Note: the `except Exception` swallowing a `RecursionError` is a finding in its
  own right whatever the timing shows -- an expensive pathological path that
  reports nothing is how this survived unnoticed.
- Claims checked against `lane-guard`'s OWN parser, not by reading: it reports
  NO holder for `cards.py`. Two lanes (`wnba-chip-live-token`,
  `wnba-halftime-elapsed`) list it under "CLAIMS RELEASED 2026-08-29 -- phantom
  sweep", and `wnba-accuracy-assessment`'s brace path sits on a line that says
  "nothing held". The parser also MANGLES that brace form
  (`syndicate/features/wnba/{cards`), so it enforces nothing there -- worth
  knowing before anyone relies on it.
- **TIMED 2026-09-02. THE RECURSION IS REAL AND IT IS CHEAP — my premise is
  FALSIFIED by my own falsification test, which said so in advance.**

      CONTROL  (SYNDICATE_WEB_DYNO=1, path off)  wall 27.9s
               _artifact_bundle calls 2, max depth 1, fallback calls 0
      ENABLED  (unset, path live)                wall 33.6s
               _artifact_bundle calls 701, MAX DEPTH 234, fallback calls 700,
               RecursionError raised 3x, test PASSED

  **+5.7s, +20%.** The lane's stated goal — "completes in the same order of time
  as with it disabled" — is ALREADY MET with no change made. The recursion costs
  seconds, not minutes.

  **CONFIRMED, and worth keeping:**
  - the cycle fires for real: **234 frames deep, 700 redundant
    `_artifact_bundle` entries for ONE request**, each re-doing artifact path
    checks and JSON loads;
  - `RecursionError` IS raised and IS swallowed by
    `except Exception: rows = []` at `:1686` — the "bounded and silent" half of
    the hypothesis holds. Nothing is logged. An expensive pathological path that
    reports nothing is how this survived unnoticed.

  **RETRACTED: the multi-minute stall was never this.** I attributed it to this
  recursion when opening the lane. It was KALSHI — the same test ran 103-152s
  before `kalshi-discovery-deadline` added the suite transport guard, and 27.9s
  after. With the guard in place the recursion adds 5.7s to a 28s test. Third
  time today I have mis-attributed a cost on this one test; the rule already
  recorded (`learnings.md` 2026-09-02) is the one I should have applied sooner.

- **A SECOND READING WAS TAKEN AND IS CONFOUNDED — do not cite it.** Instrumenting
  the fallback's return showed **933 calls, 0 returning rows**. That looks like
  "the fallback never delivers", and it is NOT evidence: `processed_root()`
  resolves to `data/wnba_source/source_artifacts/data/processed`, and
  `session_worktree.py open` EXCLUDES `data/` by design (34,690 files). The path
  does not exist in this tree, so an empty read is the expected result of the
  measurement environment, not a property of the code.
  **It also raises the more interesting possibility:** the guard is
  `if not rows and ...`, so the recursion may only fire BECAUSE the artifact is
  empty here. With data present, `rows` may be non-empty and the cycle may never
  start — which would make this a cold/dev-only path, not a production one.

- **NEXT STEP, and it is a control rather than a fix:** re-run both harnesses in
  a tree that HAS `data/` (`session_worktree.py open --with-data`, or widen this
  worktree's sparse-checkout). Two questions, both currently unanswered:
  (a) does the cycle fire at all when the artifact has rows? (b) does the
  fallback return rows when its inputs exist? Building a fix before that would
  be fixing a path whose trigger condition is not established.
- **REVISED SCOPE, pending that control.** The defensible defect today is the
  SILENT `RecursionError`, not the runtime: a fallback that blows the stack and
  reports nothing should at minimum be self-limiting and say so. The 700
  redundant loads are wasteful but cost 5.7s, so they do not justify a risky
  edit to a file three other lanes have historically touched.
- **CONTROL RUN 2026-09-02. THE TRIGGER IS AN EMPTY ARTIFACT, and the severity
  question is settled: this is a COLD/DEV path, not a production one.**

  The control as originally planned — "re-run in a tree that HAS `data/`" —
  **would have proved nothing, and was not run.** The git mirror's newest
  WNBA `live_state_*.jsonl` is **2026-07-15**, and the recursion guard requires
  `selected_date == central_today_iso()` (2026-09-02). Checking out 34,690 files
  would have returned the same empty read for a reason having nothing to do with
  the code. `CLAUDE.md`'s lossy-mirror rule, met head on.

  Instead the trigger condition was MANIPULATED DIRECTLY — `rows` comes from
  `game_cards_<date>.csv` (`_artifact_bundle:1639`), so writing one is the
  control. Probe calls `_artifact_bundle(today)` with a depth spy; no pytest:

      no cards CSV        bundle 247  depth 247  fallback 247  RecursionError 2  0.79s  games 0
      WITH one CSV row    bundle   1  depth   1  fallback   0  RecursionError 0  0.00s  games 1
      CSV removed again   bundle 247  depth 247  fallback 247  RecursionError 2  0.61s  games 0

  The third row is a BACK-CONTROL: the behaviour returns when the fixture is
  removed, so the fixture is what changed and not run-to-run variance.

  **ANSWERS to the two questions this lane could not answer before:**
  (a) *Does the cycle fire when the artifact has rows?* **NO.** One row is
      enough — depth 1, fallback never called.
  (b) *Does the fallback return rows when its inputs exist?* **STILL UNANSWERED,
      and now uninteresting**: it is only ever reached when the artifact is
      empty, and on Render the whole branch is disabled by `_render_web_dyno()`.

  **SEVERITY, stated plainly: LOW.** Fires only on an empty/missing
  `game_cards_<today>.csv`, only off-Render, costs 0.6-0.8s standalone. The
  earlier "multi-minute hang" attribution was wrong and is retracted above.

- **WHAT IS STILL A REAL DEFECT, and it is the one worth fixing: the SILENCE.**
  `except Exception: rows = []` at `:1686` swallows the `RecursionError`, so
  "WNBA has no cards today" and "the fallback blew the stack 247 frames deep"
  are the SAME observable. Nothing is logged. That is how a 247-deep mutual
  recursion lived in a request path unnoticed, and it is what made three
  separate mis-attributions possible today.
- **RECOMMENDED SCOPE, small and contained to this lane's two functions:** make
  the re-entry impossible (a `_allow_fallback=False` argument or a thread-local
  guard so `_games_from_live_state_fallback` cannot re-enter `_artifact_bundle`),
  and LOG when the fallback bails. Not a performance fix — a
  make-it-diagnosable fix. The 247 redundant loads then disappear as a
  by-product.
- **EXPLICITLY NOT RECOMMENDED:** widening the artifact search, "fixing" the
  fallback to return rows, or touching `_render_web_dyno`. The fallback returning
  nothing here is a data-absence fact, not a code fact, and this lane has no
  evidence about its behaviour when its inputs exist.
- **FIXED AND MEASURED 2026-09-02. The cycle is closed and the silence is gone.**

  `_artifact_bundle(selected_date, *, allow_fallback: bool = True)`. The
  fallback's call back in at `:3078` now passes `allow_fallback=False`, which
  closes the cycle at the one place it can form; and the `except` branch prints
  `[wnba_cards] LIVE_STATE_FALLBACK_FAILED date=... error=<Type>: <msg>` instead
  of swallowing. Keyword-only with a True default, so all five ordinary callers
  are untouched.

      probe, no cards CSV        before: bundle 247 depth 247 RecursionError 2  0.79s
                                  after: bundle   1 depth   1 RecursionError 0  0.01s

      intelligence test, path LIVE
                                 before: wall 33.6s bundle 701 depth 234 fallback 700 RecErr 3
                                  after: wall 26.6s bundle   2 depth   1 fallback   3 RecErr 0
                                control: wall 27.9s bundle   2 depth   1 fallback   0 RecErr 0

  **The enabled path now matches the disabled control** (26.6s vs 27.9s, within
  noise) and the fallback is STILL REACHED (3 calls) — fixed, not disabled.

  6 tests. **4 of them fail against the pre-fix `cards.py` extracted from
  `origin/main`** — depth 247 vs the `<= 2` assertion, the missing
  `allow_fallback` parameter, and the absent log marker. The other 2 pass in
  both states BY DESIGN: one is a no-regression check (a failed fallback still
  degrades to an empty slate) and one pins the pre-existing trigger condition
  (one CSV row means the fallback is never reached). Depth is asserted rather
  than wall clock, because a timing assertion passes on a fast machine while the
  recursion is still there — which is how this survived.

  **REGRESSION: 809 pass across the WNBA suites. 2 fail in
  `test_wnba_refresh_runner.py` and they are NOT mine** — the same two fail
  identically with the pre-fix `cards.py` swapped in from `origin/main`.
  Pre-existing, unrelated, untouched.

- **STATUS: goal met, and it was not the goal this lane opened with.** The lane
  opened believing this recursion was a multi-minute hang; it was ~5.7s, and the
  real hang was Kalshi. What was fixed is what the evidence supported: a 247-deep
  mutual recursion that reported nothing. No deploy — this path is disabled on
  Render by `_render_web_dyno()`.
- **CLOSED 2026-09-02. Verification RAN, all three items.**
  (1) *Time it before changing anything* — RAN: 33.6s with the path live vs
  27.9s control, which is what FALSIFIED the lane's own premise.
  (2) *A test that fails if the fallback re-enters, asserting on DEPTH not wall
  clock* — MET: `test_fallback_cannot_reenter_artifact_bundle`, `<= 2` against a
  pre-fix 247.
  (3) *off != on, the fallback must still work when legitimately reached* — MET:
  0 calls with `allow_fallback=False`, >=1 by default, 3 end-to-end. Fixed, not
  disabled.
  OUTCOME: depth 247 -> 1, bundle calls 701 -> 2, RecursionError 3 -> 0, and the
  failure is now NAMED (`LIVE_STATE_FALLBACK_FAILED`). The enabled path matches
  the disabled control (26.6s vs 27.9s). 6 tests, 4 failing pre-fix; 809 WNBA
  tests pass, the 2 that fail are pre-existing and proven so by swapping the
  pre-fix file back in. No deploy — disabled on Render by `_render_web_dyno()`.
  **THE PREMISE WAS WRONG AND THE LANE STILL PAID OFF.** It opened believing
  this was a multi-minute hang; it was ~5.7s and the hang was Kalshi, fixed in
  `kalshi-discovery-deadline`. The falsification test written at open called
  that outcome in advance, which is the part of the process that worked. What
  shipped is what the evidence supported: a 247-deep recursion that reported
  nothing.
  ONE RULE RECORDED: FORBIDDEN to pay for an expensive control without first
  checking its inputs can produce the signal — the planned `--with-data`
  re-run (34,690 files) could not have answered, the mirror's newest WNBA
  live-state being 2026-07-15 against a today-only trigger. Manufacturing the
  trigger instead (one CSV row) cost 0.01s and answered it exactly.
- Blocked by: none. No deploy: `cards.py` runs on web, and this path is disabled
  on Render by `_render_web_dyno()`, so the fix is not urgent in production.

### soccer-date-index-staleness — CLOSED 2026-09-02 — opened 2026-09-02 — session 3492626c — **`#631` RISK 2 DISCHARGED: THE INDEX IS NOT STALE, IT LEADS BY UP TO 7 DAYS. My hypothesis was REFUTED — I predicted it could only ever hold dates already BUILT, making the widening inert; in fact the soccer autorun runs a 7-DAY HORIZON every 4h (`SYNDICATE_SOCCER_SIM_HORIZON_DAYS=7`, `..._INTERVAL_SECONDS=14400`, autorun `true`), so 9 of 10 leagues carry a future date and none is behind today. The widening has real input. SEPARATELY: the live board-window floor is `600`, not the `1800` the risk-1 throttle analysis assumed — that conclusion's MECHANISM needs re-measuring.**
- Goal: discharge `#631` risk 2 — *"`display_prediction_dates.json` staleness;
  WHO WRITES IT AND HOW OFTEN IS UNVERIFIED"* (`state.md [week-scoped-board-window]`).
  Answer both halves with a production measurement, and say whether the proposed
  `_week_scoped_supported_dates()` widening would work, be inert, or regress.
- Files: none claimed — READ-ONLY diagnosis. Ledger files follow the convention
  used by `soccer-anchor-cost` and are deliberately not claimed.
- WHO WRITES IT, read from the deployed code before testing:
  `scripts/build_soccer_artifacts.py:696` calls `_update_date_index(api_root,
  iso_date)` at the END of a league+date build, immediately after the
  recommendations file is written. It is ACCUMULATE-ONLY: read existing `dates`,
  `dates.add(iso_date)`, write sorted + `latest`. Nothing ever removes a date.
- **HYPOTHESIS (written before testing): the index records dates that were BUILT,
  not dates that are AVAILABLE.** A date can only appear once a build for that
  date has COMPLETED. So if production builds only today, `available_dates()`
  can never contain tomorrow, and `#631`'s union
  `_week_scoped_supported_dates()` would contribute NOTHING to the board window.
  The widening would then be INERT for soccer rather than harmful — a different
  failure from the one risk 2 anticipated ("if that artifact lags, the same class
  of bug recurs one level down").
- Falsification test: read the LIVE per-league `display_prediction_dates.json`
  from production. If `max(dates) > today` for any league, the index does carry
  future dates, the hypothesis is WRONG, and the widening has real input.
  Also compare each league's `latest` against today to size any lag.
- Verification: a per-league table of `max(dates)` vs today, read from production
  (not the local mirror — `data/` in git is a lossy mirror), plus a statement of
  which of {works, inert, regresses} the widening falls into.
- Falsification test RAN and REFUTED the hypothesis: `max(dates) > today` for 9 of
  10 leagues (out to +7 days), 0 leagues behind today. Read from production disk,
  `count=10 truncated=False` — all ten leagues, nothing elided.
- Per-day membership (not just max, because these are MATCH dates and not a
  contiguous range): today 2 leagues, +1 3, +2/+3/+4 7 each, +5 3, +6 1, +7 3.
  A 2-day window yields both today and tomorrow. TODAY IS THE THIN DAY.
- Verification MET: per-league table vs today, from production, plus the verdict —
  the widening WORKS (real input), it is neither inert nor a regression on this axis.
- Blocked by: none

### m638-roster-objs-comment — CLOSED 2026-09-03 — opened 2026-09-03 — session cfcce46d-8ad8-4978-9992-5848cba4122a — **GOAL MET. NO DEPLOY (comment + tests; the predicate is deliberately unchanged).** The `roster_objs` note was wrong on THREE counts, each now measured in place: (1) they ARE allowlisted, because fnmatch `*` crosses `/`; (2) production writes rosters FLAT as `snapshots/<date>/roster_*.json`, never into `roster_objs/` — **0 of 2,552 snapshot files on web are deeper than one level**; (3) the feared cost is **1,348 files / 99.4 MB over 89 dates = 15 files and 1.12 MB per date, mean 72 KB**, not "hundreds of large files per date". **THE GLOB IS LEFT BROAD, and that is a CONSTRAINT not a preference: fnmatch cannot express "one level"** — the obvious `snapshots/*/[!/]*.json` still matches the deep path, verified, because the trailing `*` crosses `/` regardless. Narrowing means abandoning fnmatch for a load-bearing predicate to remove a risk that has never materialised.
- Files: released — `syndicate/features/shared/artifact_publisher.py`,
  `tests/test_export_only_patterns.py`.
- Verification: the tripwire was SHOWN TO FIRE, not assumed — the stale phrase is
  present in the pre-fix blob and absent after, and the two glob assertions pin
  both halves (flat rosters must stay hot or the mirror silently loses 1,348
  files; the deep match is pinned with its reason so a tidy-up cannot hit it
  quietly). 121 publisher-suite tests pass.
- Falsification test: RAN, did not falsify — 0 of 2,552 production snapshot
  paths are deeper than `snapshots/<date>/<file>`, so the breadth is incidental
  rather than load-bearing.
- Claims: NONE held. No deploy.
### board-throttle-600s-remeasure — CLOSED 2026-09-03 — opened 2026-09-03 — session 3492626c — **HYPOTHESIS CONFIRMED: THE 600 s FLOOR DOES NOT BIND. 0 of 5 non-today gaps below it, 0 in [600,750) s, smallest 1,331.2 s = 2.2x the floor; spacing is set by SERIALISATION (today's median 940.8 s vs a ~1005 s build = 0.94, back-to-back). The earlier "IT BINDS" finding is WRONG on both its premise and its inference — and the 1800 s floor it assumed was demonstrably never in effect, since a 22.2-min gap cannot exist under a 30-min floor. `#631` risk 1 is STILL LIVE; raise the floor before widening.**
- Goal: re-decide `#631` risk 1 against the REAL floor. `board-window-throttle-binds`
  concluded "the throttle BINDS" from tomorrow's 38.8-min median vs a 30-min floor,
  but the code is `max(30, _env_int(KEY, 1800))` and the LIVE value on refresh-worker
  is **`600`** (read from the Render API 2026-09-03T02:2xZ; the running process
  booted 01:10:00Z on `f84eb21b`, so 600 is what it holds).
- Files: none claimed — READ-ONLY measurement from production logs.
- **HYPOTHESIS (written before testing): the 600 s floor does NOT bind.** Non-today
  build spacing is set by SERIALISATION, not the throttle — a full board build was
  measured at ~1005 s and builds run serially, so today alone (15.8-min median)
  nearly saturates the loop and tomorrow takes whatever turns are left.
- Prediction if true: the MINIMUM non-today gap is far above 600 s and there is NO
  clustering just above 600 s. The floor would then never be the active constraint.
- Falsification test: if a meaningful share of non-today gaps sit in [600, ~750] s
  — i.e. clipped to the floor — the throttle IS binding and the hypothesis is wrong.
  A single gap below 600 s would instead mean the floor is not applied at all.
- Verification: per-date gap distribution (n, min, p25, median, max) from
  `BUILD_SPAN_ENTER` on refresh-worker, segmented at the 01:10Z deploy boundary so
  the window where the 600 floor is CONFIRMED is reported separately from the
  earlier window where the env value is not established.
- Falsification test RAN and did NOT fire: a pile of non-today gaps in [600,750) s
  would have proved binding. There were ZERO, and zero below the floor either.
- Verification MET: per-date gap distribution from `BUILD_SPAN_ENTER
  stage=pull_hot_artifacts`, refresh-worker, COVERED window 2026-09-02T12:42:56Z ->
  2026-09-03T02:16:34Z (13.6 h), 341 lines / 5 pages. today n=46 med=940.8 s;
  non-today n=5 med=3,854.1 s min=1,331.2 s.
- The deploy-boundary segmentation turned out NOT to be needed: an 1800 s floor
  forbids the observed 1,331.2 s gap, so the floor was <=1,331 s across the whole
  window regardless of when the env value was set. Post-deploy alone is n=0
  non-today and could not have decided it.
- Corroborates the superseded block on the half that survives: today 15.7 min
  median here vs 15.8 min there, two independent windows.
- Blocked by: none

### mlens-snapshot-dating — CLOSED 2026-09-03 — opened 2026-09-03 — session cfcce46d-8ad8-4978-9992-5848cba4122a — **THE ASK WAS MEASURED AND REJECTED, and a bounded substitute shipped instead.** Dating `live/<sport>_live_lens.json` must NOT be built: it is not a file — `live/` is KEYVALUE-backed (`_KEYVALUE_EXCLUDED_PATH_MARKERS` is only `migration_runs/`), which is also why `artifacts/export` reports 0 files under `live/*` while the pattern IS allowlisted. **One key = 4,194,400 bytes, written every 60s, five sports, against a store at 222.28 MB of 256 MB (86.8%) with 12,203 keys already evicted — ~5.76 GB/day for MLB alone, ~22x the whole store.** And a dated path auto-takes a TTL, which under `volatile-lru` makes the archive the FIRST thing evicted: ruinous AND unreliable. **SHIPPED INSTEAD: a `lens_fingerprint` in the board artifact's `live_game_state` block** — sha256 of the NORMALISED games plus counts and age, **98 bytes**, on an artifact that IS dated, disk-backed and mirrorable. It does not make the correction reproducible; it makes a divergence ATTRIBUTABLE.
- Files: released — `syndicate/features/shared/board_enrichment.py`,
  `tests/test_lens_fingerprint.py`, `scripts/replay_diff_gate.py` (exclusion
  reason updated to point at the fingerprint).
- Falsification test: FIRED, and it is the lane's main output — the hypothesis
  "dating is a one-line change" was wrong in kind, not in degree.
- Verification: the fingerprint is stable on a repeat, changes on a changed
  score or state, does NOT change on age alone (so "the lens stopped moving"
  stays distinguishable from "the board changed"), and stays under 400 bytes on
  a 30-game slate. 6 new tests; 27 board-grid tests pass.
- **OWED: a refresh-worker deploy, and DELIBERATELY ABANDONED after three tries.**
  `eb11b956` is on `origin/main`, so **any** future refresh-worker deploy from
  main carries it. Attempts blocked by, in order: an MLB sim in flight (`HOLD`),
  another lane's live claim (`CLAIMED`), the 25-min spacing after that lane's
  own deploy (`TOO_SOON`, `#563`), and then jobs again. Claim acquired and
  RELEASED each time; nothing forced. Full table: `deploys.md` 2026-09-03.
- Verification when it ships: the next book-grid tick (~10 min) must write a
  `live_game_state.lens_fingerprint` with a non-empty `sha256_12`. **Its ABSENCE
  on a fresh `generated_at` means the field is inert**, not that the lens was
  empty — the fingerprint is emitted even for an empty lens, by test.
- Claims: NONE held.
### board-window-floor-raise — OPEN, **GOAL MET AND INJECTED; ONLY THE RATE IS OWED** — opened 2026-09-03 — session 3492626c — **Env `600`->`1800` injected by a SAME-SHA redeploy (`f84eb21b`, live 03:08:48Z, no code shipped), then `33b181ee` (live 04:20:45Z) made the floor OBSERVABLE — the queue path had emitted NOTHING, so the verification originally written here was not satisfiable. `floor_s=1800` in the served line proves the injection reached the process. MECHANISM shown: an enqueue GATED at `elapsed_s=725` that the old 600 floor would have ADMITTED. n=2 is NOT a rate — measurement scheduled 08:00 local, and a clip rate of 0 is a legitimate result.**
- Goal: make the board-window throttle capable of binding. ENV-ONLY change,
  `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS` `600` -> `1800` on
  refresh-worker (SET 2026-09-03, single-key endpoint; the key is ABSENT from
  `render.yaml`, so no `blueprint_sync` will revert it). Deploy to inject it.
- Files: none — no code change. Env + deploy only.
- Why 1800: above the ~1005 s serialisation period AND above the observed
  1,331 s minimum non-today BUILD gap, so it can actually clip; `600` is below
  both, which is the likely reason three prior tunings of this knob "did
  nothing". It is also the code default and the value the comment at
  `intelligence_state.py:6863-6875` justifies against `QUOTE_AGE_SERVED` p50
  4,285 s. Conservative and reversible; `3600` remains available.
- **THE PREDICATE IS ENQUEUES, NOT BUILDS.** `_board_window_last_queued_at` is
  stamped at QUEUE time (`intelligence_state.py:6886`), so this floor gates how
  often a non-today date is ENQUEUED. The prior lane measured BUILD spans, which
  cannot see enqueue clipping when the queue is saturated. Do not repeat that.
- Verification (BEFORE deploying, so it cannot be rationalised after):
  (a) the live env value reads `1800` AND the deployed process is newer than the
      set — an env change alone never reaches a running process;
  (b) re-measure `BUILD_SPAN_ENTER stage=pull_hot_artifacts` per date over a
      window of >= 4 h and compare non-today's build COUNT and median gap against
      the pre-change baseline: today n=46 med=940.8 s; non-today n=5 med=3,854.1 s,
      min=1,331.2 s (covered 2026-09-02T12:42:56Z -> 2026-09-03T02:16:34Z);
  (c) the honest null result is allowed: if non-today's share does NOT fall, say
      so — that would mean the queue coalesces and the floor is the wrong lever.
- **STEP 2, `1800` -> `1200` `[user decision 2026-09-03]`.** 87% was more
  aggressive than wanted: non-today sat at a 2,096.7 s median build gap. Env SET
  14:4xZ (single-key endpoint); injection needs a SAME-SHA redeploy of the live
  `c4ce0502`.
- **PRE-REGISTERED PREDICTION, written BEFORE the deploy so the re-measure is a
  TEST and not a description.** Derived from the observed gated `elapsed_s`
  distribution under the 1800 floor (n=131, date=2026-09-04):

        elapsed_s  min=66  p25=513  med=983  p75=1384  max=1795

  At a 1200 s floor every attempt with `elapsed_s >= 1200` FLIPS to admitted:
  **42 flip, 89 stay gated**, so

        predicted clip rate ~= 89/150 = 59%      (was 131/150 = 87%)
        predicted non-today build gap: BELOW the 2,096.7 s median

  **FALSIFIED IF** the clip rate stays near 87%, or rises, or the non-today
  build gap does not fall — any of which would mean the floor is not the thing
  setting non-today's cadence and the 87% reading was coincidental.
- **The approximation is NAMED: admitting 42 more non-today builds consumes
  worker capacity and will itself shift the timing.** So 59% is a point estimate
  under an unchanged attempt pattern, not an identity. A result of 50-70% should
  be read as CONFIRMING; the discriminating question is direction and magnitude,
  not the second digit.
- Blocked by: none

### intelligence-suite-runtime — CLOSED 2026-09-03 — QUESTION ANSWERED (not a stall); MOST OF THE LANE RETRACTED — **NOT A STALL: 221 pass in 586s (9:46). Top 25 = 66%, all `test_intelligence_query*`. AND ISOLATING THEM MAKES THEM SLOWER — the durations do not decompose. **THE WARM EFFECT IS RETRACTED — 3 paired replications show cold 31.32s vs warm 31.45s, and the founding 52.74s reading does not reproduce.** What stands: 221 pass in 586s, not a stall** — opened 2026-09-02 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885
- Goal: `tests/test_intelligence.py` (221 tests) completes in a STATED, bounded
  time. One testable outcome: a full run finishes and its total is recorded, and
  whatever dominates it is either fixed or documented as irreducible with the
  per-test cost named.
- Files: `tests/test_intelligence.py`. **No source file is claimed yet, on
  purpose** — the cost has not been attributed, and claiming files before the
  measurement names them is how the last three lanes got aimed at the wrong
  mechanism. Whatever `--durations` implicates gets claimed then, in an edit to
  this block.
- Hypothesis: **NOT a stall — a cluster of individually-expensive integration
  tests.** ~12 `test_intelligence_query_api_*` tests each drive a real
  candidate-pool build; one of them (`resolves_preview_date_and_preserves_contract`)
  is MEASURED at 26.6s alone. 12 x ~25s is ~5 minutes from that cluster before
  the other 209 tests are counted. Collection order puts them around index
  60-75, which is where the run visibly crawls (~1 test/minute observed).
- Falsification test: if `--durations` shows ONE test dominating, or a test that
  never returns, then "many slow tests" is wrong and it IS a stall — a different
  defect with a different fix. Equally, if the slowest tests are NOT the
  `query_api` cluster, the hypothesis is wrong about which tests.
- Verification: (1) a completed run with the TOTAL recorded — this does not
  exist yet and is the first step; (2) `--durations=25` naming the per-test
  cost, so the claim "N tests cost M seconds" is a reading rather than an
  inference; (3) after any change, the same two numbers re-measured, and the
  suite must still pass 221/221 (a faster suite that tests less is not a fix).
- **BASELINE DOES NOT EXIST YET, and the lane says so rather than quoting the
  old one.** The previously observed ">10 minutes, stalled ~32%" was measured
  BEFORE `kalshi-discovery-deadline` (venue guard) and `wnba-cards-fallback-recursion`
  (247-deep recursion) both landed. A re-run on current `origin/main` was started
  and deliberately KILLED at 32% because a plain run can only produce a total,
  while `--durations` produces the total AND the attribution for the same cost.
  Quoting the pre-fix figure as this lane's baseline would be citing a number
  from a system that no longer exists (`learnings.md`: re-baseline before
  judging).
- Note for whoever runs it: this suite MUTATES TRACKED FILES (`learnings.md`
  2026-08-22 — `reports/manifests/*.json`, `reports/refresh_state.json`,
  `reports/intelligence/intelligence_state.json` and more), so check
  `git status` before committing and never `git add -A`.
- **MEASURED 2026-09-02. IT IS NOT A STALL. Hypothesis CONFIRMED by the
  falsification test as written.**

      221 passed in 586.00s (9:46)   -- it COMPLETES; faulthandler never fired
      slowest single test   28.94s = 4.9% of the run   -> nothing dominates
      top 25 durations     387.6s = 66.2% of the run
      remaining 196 tests  198.4s = 33.8%
      25th slowest          12.54s -> the band extends well past 25

  The falsification test said: *if `--durations` shows ONE test dominating, or
  one that never returns, it IS a stall.* The worst test is 4.9% and everything
  returns. **All 25 of the slowest are
  `IntelligenceBlueprintTests::test_intelligence_query*`.**

  **THE EARLIER ">10 MINUTES, STALLED AT 32%" IS EXPLAINED AND RETRACTED AS A
  STALL.** 9:46 against a 10-minute timeout is a suite that finishes just past
  the wall — the "stall at 32%" was the timeout landing mid-run, not a hang. The
  percentage was stable across observations because pytest prints it per output
  line, not because progress stopped. Two of this session's fixes
  (`kalshi-discovery-deadline`'s venue guard, `wnba-cards-fallback-recursion`)
  also removed real time from this file, so the pre-fix figure was never a valid
  baseline for it either.

- **THE SHAPE OF THE COST, and it rules out the obvious fix.**
  `IntelligenceBlueprintTests` holds **182 tests, 49 of them
  `test_intelligence_query*`**, each driving a real candidate-pool build. There
  is **no `setUp`/`setUpClass` doing the heavy work** — each test constructs its
  own scenario inline, so a class-scoped fixture is NOT a drop-in and would mean
  rewriting 49 tests' arrangement. Anyone reaching for "just share the setup"
  should read that first.
- **FILES: still only `tests/test_intelligence.py`.** The measurement implicates
  test-side arrangement, not a production module, so no source file is claimed
  and none should be until something names one.
- **OWED, and running:** the cluster's share of the 586s, measured directly
  (`-k intelligence_query`) rather than extrapolated from the top-25 sum. That
  number decides whether the cluster is worth restructuring at all — the top 25
  are 66%, but 24 more query tests sit in the untimed remainder.

- **THE OBVIOUS REMEDY BACKFIRES, and this is the finding that matters.**
  Isolating the cluster to measure its share made it SLOWER, not faster:

      in the full run   51 query tests inside 221, whole file 586s,
                        the 25 slowest averaging 15.5s each
      isolated (-k)     34 tests in >1200s before the timeout killed it
                        -> >35s each, at least 2.3x their in-situ cost

  **So the per-test durations do NOT decompose.** "The top 25 are 66% of the
  run" is true of that run in that order; it does NOT license "removing or
  splitting them saves 387s". Something earlier in the file warms state these
  tests reuse — on-disk artifacts under `reports/`, module-level caches, or
  both — and a cold cluster pays for it individually.
  **Anyone who reacts to the 66% figure by splitting the slow tests into their
  own job will make the total worse.** That was measured, not predicted.

  Also measured and not free: **collection alone is 43-75s** for this file
  (182-test class: 42.87s; `-k` selection over 221: 74.86s), before a single
  test body runs.

- **NEXT STEP — identify what warms, not what is slow.** The lever is the shared
  state, and it is not yet named. Concretely: run the file with the cluster
  FIRST versus LAST and compare the same tests' durations; whatever moves is the
  warm dependency. Only then is there a fix worth designing.
- **DO NOT, on current evidence:** split the slow tests into a separate job,
  add a class-scoped fixture (there is no `setUp` to hoist — each of the 182
  tests arranges its own scenario inline), or mark them slow and skip them by
  default. The first is measured to backfire; the second is a 49-test rewrite;
  the third trades runtime for coverage on the only tests that exercise the
  candidate-pool build end to end.
- **WARM-STATE DIAGNOSTIC RUN 2026-09-03. The effect is REAL, QUANTIFIED and
  REPRODUCIBLE. Its MECHANISM is NOT FOUND, and four candidates are ruled out
  with evidence.**

  Within-subject, same six tests, only their position changing:

      test                                      cold(6 alone)  after 20  full run
      query_api_respects_explicit_filters        52.74s        32.76s    28.94s
      query_supports_round_robin_parlays         50.83s        23.31s    21.32s
      query_supports_cross_sport_parlays         33.87s        22.12s    19.74s
      query_api_resolves_preview_date            29.96s        21.91s    20.02s
      query_builds_generic_multi_sport_board     25.78s        16.91s    17.62s
      query_api_reflects_model_reliability       23.19s        14.39s    18.41s
      SUM                                       216.4s        131.4s    126.1s

  **~8s of earlier tests buys ~85s.** The 20 warming tests cost only 6.3-9.7s
  themselves, and 20 of them recover ~94% of the benefit the full 215-test
  prefix gives. Cold is repeatable: three consecutive 6-test runs at 221.7 /
  208.7 / 211.1s.

  **RULED OUT, each by measurement rather than reasoning:**
  1. **`lru_cache`.** Miss counts are IDENTICAL cold vs warm across all 19 active
     cached functions (`_normalized_market_text_cached` 170 vs 173 misses;
     `_preferred_source_roots_cached` 28 vs 26 — warm is LOWER, not pre-paid).
  2. **Module-level dict/set caches.** Every non-dunder module container is a
     STATIC constant — alias tables, stopwords, `market_keys`. Nothing grows.
  3. **OS filesystem page cache.** Three consecutive cold runs in separate
     processes are within noise of each other (221.7/208.7/211.1s). A page-cache
     effect would have made run 2 and 3 fast.
  4. **The `_INTELLIGENCE_STATE_SERVICE` singleton.** Its `_candidate_pools` and
     `_source_fingerprints` are **0 and 0** both after zero tests AND after the
     20 warming tests. It is not caching anything here.

  **THE MEASUREMENT THAT FAILED, recorded so it is not repeated.** A cProfile
  cold-vs-warm diff was attempted and is INCONCLUSIVE BY CONSTRUCTION, not
  negative: the "warm" profile necessarily contains the 20 extra tests, so it
  compared a 1-test profile against a 21-test profile. It showed 0.7s of
  difference, which means nothing. cProfile around `pytest.main` cannot isolate
  one test's cold-vs-warm cost; the next attempt needs per-test profiling
  (a `pytest_runtest_call` hook profiling ONLY the test under study) or the
  profile must be taken on identical test sets.

- **WHAT THIS ALREADY SETTLES, regardless of the unfound mechanism:** the suite
  is NOT stalled (221 pass in 586s), the durations do NOT decompose, and
  **splitting the slow tests into their own job makes them ~1.7x slower** —
  measured twice now. That guidance stands on the numbers alone.
- **NEXT PROBE, precisely specified:** profile ONE test under a
  `pytest_runtest_call` hook so the profile covers that test and nothing else,
  run it cold and warm, and diff cumulative time by function. That is the
  instrument that names the dependency; everything cheaper has now been tried
  and eliminated.
- **RETRACTED 2026-09-03: THE "WARM STATE" EFFECT DOES NOT EXIST. It was built on
  single unreplicated runs with an outlier, and paired replication killed it.**

  The properly-isolated probe (a `pytest_runtest_call` hookwrapper profiling ONLY
  the target test's call phase, so cold and warm cover identical work) showed
  **cold 49.9s vs warm 49.1s** with identical call counts — no difference. That
  contradicted the unprofiled durations, so the durations were replicated,
  3 paired runs, no profiler:

      rep1  cold=32.48s  warm=30.82s
      rep2  cold=31.34s  warm=32.28s
      rep3  cold=30.13s  warm=31.24s
      ---------------------------------
      cold mean 31.32s   warm mean 31.45s      -> warm is marginally SLOWER

  **The founding number does not replicate.** This test measured **52.74s** in
  the first isolated run; it measures **~31s** now, cold, three times. The whole
  216.4s-vs-131.4s story rested on that run.

- **WHAT IS WITHDRAWN, explicitly:**
  - "isolating the cluster makes it ~1.7x slower" — NOT ESTABLISHED. The one
    test that could be replicated properly shows no penalty at all.
  - "~8s of earlier tests buys ~85s" — WITHDRAWN, same cause.
  - "the durations do not decompose" — UNPROVEN. It may still be true; nothing
    here shows it.
  - The four "ruled out" mechanisms (lru_cache, module containers, OS page
    cache, the service singleton) were ruled out against an effect that is not
    real. Those readings stand as facts about the caches; they explain nothing,
    because there was nothing to explain.
  - **The "DO NOT split the slow tests into their own job" guidance rests on
    nothing measured and must not be cited.** It may still be wise; it is not
    evidenced.

- **WHAT SURVIVES, and it is the part that was measured once and cleanly:**
  `tests/test_intelligence.py` is **NOT stalled — 221 pass in 586.00s (9:46)**,
  the armed faulthandler never fired, no single test exceeds 4.9% of the run,
  and the 25 slowest are all `test_intelligence_query*` at 12.5-28.9s each.
  Collection alone is 43-75s. The suite is simply a large integration suite
  where ~50 tests each drive a real candidate-pool build at ~20-30s. That is the
  finding.
- **NEXT, if anyone continues:** the only question left is whether ~50 tests
  each paying a full candidate-pool build is reducible at all. Answering it
  needs a paired, replicated design from the start — n>=3 per condition, and no
  comparative claim from single runs. This lane spent most of its effort
  chasing an effect that three replications erased.
- **CLOSED 2026-09-03. Verification RAN.**
  (1) *a completed run with the TOTAL recorded* — RAN: **221 pass in 586.00s
  (9:46)**, faulthandler never fired.
  (2) *`--durations=25` naming the per-test cost* — RAN: top 25 = 387.6s, all
  `test_intelligence_query*`, 12.5-28.9s each; collection alone 43-75s.
  (3) *re-measure after a change* — VACUOUS: no change was made, and none is
  proposed on current evidence.
  **GOAL MET on its documentation branch:** the suite completes in a stated
  time, and what dominates it is named with per-test costs — ~50 tests each
  driving a real candidate-pool build at 20-30s. Nothing is 'fixed' because
  nothing was shown to be broken.
  **THE ORIGINAL PREMISE WAS FALSE.** This lane opened on a '>10 minutes,
  stalled at 32%' observation. That was a 10-minute timeout landing mid-run on
  a suite that finishes at 9:46; the frozen percentage was pytest printing per
  output line. There was never a stall.
  **AND MOST OF WHAT THE LANE THEN PRODUCED IS RETRACTED** — see the retraction
  above. The 'warm state' effect, the 1.7x isolation penalty, the four
  mechanism exonerations and the 'do not split the cluster' guidance all rested
  on one unreplicated comparison with an outlier cold reading. Three paired
  replications erased it (cold 31.32s vs warm 31.45s). **Do not cite any of
  them.** The only durable outputs are the 586s/221-pass measurement and the
  learnings rule.
  POSTMORTEM: landed as `learnings.md` 2026-09-03 — *FORBIDDEN: a comparative
  claim from ONE run per condition*. Also a REPEAT of the 2026-08-29 rule on
  validating a profiler's SCOPE: the first cProfile attempt wrapped
  `pytest.main`, so the warm profile contained 20 extra tests and compared a
  1-test profile against a 21-test one. Same rule, second instance, five days
  apart.
  No deploy; no source file was ever claimed or changed.
- Blocked by: none. No deploy — this is test-suite runtime, not production
  behaviour.

### worker-artifact-transport — CLOSED 2026-09-03 — opened 2026-09-03 — session cfcce46d-8ad8-4978-9992-5848cba4122a — **THERE IS NO TRANSPORT GAP FOR THIS FAMILY. I PUT IT ON THE WRONG LIST, and the fix is a one-line move.** `#625`(2) placed `*_source/reconciliation/*` on the READ-only list arguing "nothing on web serves these". True, and the WRONG TEST — export-only makes a family readable IF PRESENT, and nothing published these, so the entry did nothing. The question is **"is there a serving HAZARD"**, and there is none: `RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN` is **false on web**, and `reconcile_prediction_results_for_date` defaults `result_roots` to **`_repo_root()/data`** (`prediction_reconciliation.py:349`) — the CHECKOUT, not `data_root()` — so presence on web changes nothing. **COST MEASURED: a real `props_actuals` is 56,564 bytes for 1,123 rows; the whole 12-date window is ~663 KB, published ONCE each** (the sweep only sends changed files), against a `book_grid` of 12.7 MB/day that already publishes. Moved to `HOT_ARTIFACT_PATTERNS`. **`feed_live` STAYS export-only forever** — there PRESENCE is the trigger (`_mlb_feed_live_payload` returns the cached file if it exists), which is the discriminating pair a new test pins.
- Files: released — `syndicate/features/shared/artifact_publisher.py`,
  `tests/test_export_only_patterns.py`.
- Falsification test: FIRED, and usefully — the hypothesis was that a bounded
  request-channel transport had to be BUILT. It did not: the existing publish
  sweep is the transport, and the family was excluded from it by my own
  reasoning error. Nothing new was built.
- The saturation constraint still held and shaped the answer: ~663 KB one-time
  is affordable on services at 91-97% where a standing flow would not be.
- **DEPLOYED AND VERIFIED 2026-09-03.** web `c4ce0502` 05:32Z, refresh-worker
  `c4ce0502` 05:36Z (web FIRST, because its publish endpoint gates on the
  list). **PASS on bytes:** 0 files at baseline; at 06:03:12Z
  `props_actuals_2026-09-02.csv` (8,162 B) and `_2026-09-03.csv` (42 B, today's,
  header-only) appeared, and the first pulled back as **133 lines = header +
  132 graded rows**. A family unreachable for this system's whole life is now
  readable. Full measurement: `deploys.md` 2026-09-03 05:32Z.
- **THE PREDICTED LIMIT HELD, stated before the reading:** only dates that WRITE
  cross. The seven June dates refuse (`input_absent`, `#639`) so they never
  become "changed" and the sweep never sends them — **`#639`'s residual stays
  unanswerable**, and the only fix (a full-sweep republish) is not justified
  against services at 91-97%.
- Claims: NONE held.

### soccer-anchor-harness-land — CLOSED 2026-09-03 — opened 2026-09-03 — session b2b5b45b-e938-4cb5-81c2-c211ecc7c703
- Goal: land the measurement harness that answered `todo.md #622`(1)(2)(3) into
  `scripts/`, so the next mechanism-vs-outcome question does not pay for it
  again. It exists ONLY in a session scratchpad and dies with the session.
  `[user instruction 2026-09-03: "land the harness to scripts/"]`
- Files: scripts/backtest_soccer_anchor_vs_outcomes.py (NEW),
  scripts/validate_soccer_anchor_shift.py (NEW),
  scripts/fetch_prod_artifacts_paced.py (NEW),
  tests/test_soccer_anchor_backtest.py (NEW).
- Hypothesis: n/a (preserving a proven tool).
- Falsification test: if the landed scripts cannot reproduce the recorded
  numbers — base MAE 0.52126 / anchored 0.52163 over 6,486 rows, and the
  held-out surrogate 0.0144 vs 0.0225 — then what landed is not what ran, and
  the ledger's evidence has no reproducible source.
- Verification RAN, and it PARTLY passed — recording the split rather than the
  headline. **VERIFIED:** all three scripts `--help` from this checkout; **no
  machine-specific path in any of the four files**; 10/10 tests pass; job
  assembly reproduces the original **3 units / 6 fixtures** exactly; and a
  2-unit end-to-end run graded **300 of 300 paired rows with 0 dropped**, which
  is the population fix live (the old filter kept only `realized >= 1`), with
  5/5 ESPN actuals and match-clustering reported apart from the labelled
  player-level figure.
  **SUPERSEDED 2026-09-03: THE FULL RUN WAS REDONE THROUGH THE LANDED SCRIPT AND
  IT REPRODUCES.** 56 units / 113 anchored fixtures and **6,595 paired
  projection rows — IDENTICAL**, so the simulation half is deterministic and
  reproduced exactly. Headline unchanged to 4 dp: **+0.00038 shots (+0.072%)**,
  **t = −1.06**, median **+0.00000**, anchored better in **41** matches. The only
  drift is the ACTUALS JOIN — the original fetched 138/139 matches, the rerun
  139/139 — which adds 1 match and 18 gradeable rows (6,486 → 6,504; 136 → 137)
  and moves the MAEs in the 4th decimal (0.52126 → 0.52135 base, 0.52163 →
  0.52173 anchored). **The recorded evidence now has a reproducible source.**
  The earlier note below stands as written, because the reasoning was right:
  **NOT VERIFIED AT THE TIME, and my falsification test was written at the wrong scope:**
  the recorded aggregate (base 0.52126 / anchored 0.52163 over 136 matches) is
  NOT reproduced, because a 2-unit subset cannot reproduce a 136-match
  aggregate. The subset read anchored BETTER by 0.385% over 5 matches at
  **p=1.0000**; the full run read anchored WORSE by 0.072% over 136. Those do
  not conflict — the effect is ~0.001 shots against a per-match sd of 0.011, so
  5 matches cannot resolve it, and the harness correctly declined to claim
  anything. MAE LEVELS also differ by construction (0.359 vs 0.521) because
  leagues have different shot distributions. **Re-verifying the aggregate needs
  the full ~2 h run and has not been done.**
- **THE TWO DEFECTS THAT MUST BE LOCKED IN BY TEST, because both produced a
  plausible wrong answer before being caught:** (a) the grading population must
  include every predicted player with `realized = 0` when absent — filtering
  zero-outcome rows kept 42 of 197 and selected on the dependent variable;
  (b) statistics must be MATCH-CLUSTERED — player rows in a match share one
  anchor shift, and the player-level sign test read p=0.0027 against its own
  t of -1.28.
- Scratchpad scripts carry absolute paths (`C:	mp\syndicate-sessions\...`,
  a hardcoded `.env`) and `m2/m6/m7` names; they must be made
  `REPO_ROOT`-relative and renamed to the `backtest_/validate_/fetch_` convention
  before landing. A copy-paste would be unrunnable for anyone else.
- Blocked by: none. No OPEN lane claims these paths.

### m639-residual-was-anything-destroyed — CLOSED 2026-09-03 — opened 2026-09-03 — session cfcce46d-8ad8-4978-9992-5848cba4122a — **ANSWER: UNKNOWABLE FROM OUTSIDE, and the falsification test named this outcome in advance. Two BETTER findings came out of it, one of which corrects a number I published yesterday.**
- **The residual is not answerable.** Three witnesses, all closed: (1) the files
  themselves — HOT-allowlisted since `#641` but the sweep is watermark-driven
  and those dates REFUSE to write, so they never become "changed" and never
  cross; (2) git — 0 reconciliation files tracked, ever; (3) the consumer — see
  below, its signal is self-contradictory. **Recorded as unknowable rather than
  softened into "probably nothing was lost".**
- MEASURED, and it bounds the window only: **327 parseable `MLB_ACTUALS_TICK`
  payloads over 13 days back to 2026-08-20 — ZERO June dates with
  `top_props_rows > 0`.** So nothing was destroyed in those 13 days; the
  truncation was writing a header over a header. **13 days is not "ever"** and
  the June dates are ~80 days old.
- INFERENCE, labelled as such and NOT a measurement: replaying production's own
  June bytes produced **1,123 resolved rows for 2026-06-15**, so when the input
  was fresh the writer almost certainly did produce ~1,100 rows/date. On that
  reasoning the pre-fix truncation likely destroyed **~7,800 graded rows across
  the seven dates**. Mechanism, not evidence.
- **FINDING 1, and it corrects `#640`: `/api/ops/keyvalue/usage` reports
  ALLOCATOR-ROUNDED memory, not payload bytes.** Both single-key buckets sit
  exactly **+96 bytes above a power of two** (`prediction_ledger.json`
  2,097,248 = 2 MiB+96; `live/mlb_live_lens.json` 4,194,400 = 4 MiB+96) while
  multi-key buckets have arbitrary gaps — jemalloc rounds large values to
  powers of two. So the live-lens snapshot OCCUPIES ~4 MiB; its payload is
  somewhere in (2 MiB, 4 MiB]. **`#640`'s decision is unchanged** — even at the
  2 MiB lower bound, 1,440 ticks/day is ~2.9 GB/day against a 256 MB store,
  ~11x capacity — but the figure I published was overstated by up to 2x and is
  now labelled.
- **FINDING 2, filed as `#642`, not mine to fix:** `/api/portfolio/summary`
  reads `total_tracked: 0, settled_count: 0, positions: []` while the
  `prediction_ledger.json` keyvalue key occupies ~2 MiB with 1 key. A 2 MiB
  ledger and a reader that sees nothing in it is the same class as the
  documented cross-disk defect in `prediction_ledger.py:80-95`.
- Claims: NONE held. NO DEPLOY — read-only throughout.
### m642-ledger-read-silence — CLOSED 2026-09-03 — **HYPOTHESIS FALSIFIED BY ITS OWN TEST; NOT A DATA OR READER DEFECT.** The reader works: 1,457 rows read, all 1,457 excluded by the documented stake filter, so `total_tracked: 0` is CORRECT (zero bets ever placed via the bet slip). The real defect was one layer up and is fixed: the payload rendered "read returned nothing" (an incident) identically to "returned rows, none user-placed" (a normal empty portfolio). — opened 2026-09-03 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: `todo.md #642` — make the two possibilities DISTINGUISHABLE and thereby
  answer which it is. **Met**, though not where the goal assumed.
- Files: `syndicate/features/portfolio_summary.py`,
  `syndicate/features/prediction_ledger.py`,
  `tests/test_prediction_ledger_read_silence.py` (NEW, 12 tests).
- Verification: `/api/portfolio/summary` on web `b7c2b220`, 2026-09-03T15:39:13Z
  — `ledger_rows_total=1457`, `excluded_auto_tracked=1457`, `total_tracked=0`.
  Cross-check: 1,457 rows against the ~2 MiB key is ~1.4 KB/row, the size a
  prediction row with `recommendation`/`query`/`response` has. The byte count
  and the payload count were never in conflict.
- Falsification test FIRED as written ("the read is confirmed to SUCCEED and
  still yields 0" → hypothesis wrong). Its named follow-on — "nothing is
  recording bets" — is ALSO ruled out: 1,457 rows are recorded; they are legacy
  stakeless auto-tracked rows whose writer `#72` deleted 2026-07-27.
- Cost: FOUR web deploys, three of them spent instrumenting the reader.
  See `learnings.md` 09-03 (instrument the join) and `log/2026-09-03.md`.
- Blocked by: none.

### accuracy-autorun-rearm — OPEN — opened 2026-09-03 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885
- Goal: `#626`(h) runs in production for the first time WITHOUT killing the
  worker. ONE testable outcome: `[accuracy_summary] AUTORUN_DONE ... error=none`
  in refresh-worker logs, with the peak `memory_anon_mb` during that window
  recorded against the 4,096 MiB ceiling.
- Files: `.syndicate/deploys.md`, `.syndicate/lanes.md`, `.syndicate/state.md`.
  Render ENV on refresh-worker via the single-key API — **never `render.yaml`**,
  which fires `blueprint_sync` and rewrites every key on all three services.
  **No code file is touched: the fixes are ALREADY LIVE.**
- **THE CODE IS ALREADY DEPLOYED — this is an ENV-ONLY change.** refresh-worker
  runs `c4ce0502`, verified BY CONTENT (not ancestry): that tree carries
  `_project_evaluation_record` x4, `_accuracy_summary_ledger_budget_bytes` x6,
  and `ledger_coverage` in `run_refresh_worker.py` x2. The deploy exists solely
  to inject the env key, since a Render restart does not re-inject one.
  Deploying `c4ce0502` again therefore changes NO code and deliberately does not
  pick up the 4 pending commits from other lanes.
- Hypothesis: n/a (arming a bound that was measured before it was built).
- Falsification test: if the first armed run OOM-kills the worker, or
  `AUTORUN_DONE` is absent while the process restarts, the bound did not hold in
  production and the key goes back to `false` immediately. `#256`'s
  claim-before-work means a death costs exactly one run per day, not a loop.
- Verification: (1) `AUTORUN_DONE sports=8 ... error=none`; (2)
  `LEDGER_CHUNKS_ACCEPTED ... budget=2000000000 ...` naming bytes and dates, so
  the sample the summary rests on is a READING not an assumption; (3) peak
  `memory_anon_mb` in the run window, stated against 4,096 and against the
  1,877 MiB baseline cycle peak; (4) the published artifact carries
  `ledger_coverage` — if it does not, `_bounded_accuracy_summary` is dropping it
  and the sample size is invisible again.
- **IT WILL FIRE ALMOST IMMEDIATELY, not tomorrow.** Gate read, not assumed:
  `hour >= 7 CT` (it is 10:2x) and `last_run_date (2026-09-02) < today`, so the
  first tick after the deploy runs it. That is the point — it is observed today
  — but it is why the sim/board-build wait matters.
- **EXPECT A MISLEADING LINE ON THE FIRST RUN.**
  `PREVIOUS_RUN_NEVER_COMPLETED ... Not retrying today (see #256)` will print,
  because 09-02's death left `state: "started"`. **The code does NOT return
  after printing it** — it proceeds to claim and run. Do not read that line as
  "the run was skipped".
- Blocked by: none once `check_deploy_safety` is CLEAR. Polling; an MLB sim and
  a board build were in flight at 10:20 CT.
### book-quotes-publish-clobber — CLOSED 2026-09-02 — opened 2026-09-01 — session 3492626c — **`#630` DONE: three artifact families merge on receive, all out of process, verified in production. Full block (incl. a peer's `#635` answer and `#632` corrections) moved VERBATIM to `lanes_history.md`.**
- **OWNERSHIP CORRECTION.** An ownership pass recorded that session `3492626c`
  "DOES NOT EXIST in a 200-session roster" and inferred the live worker was
  `local_ea1e4863`. **The session exists and did this work** — `list_sessions`
  omits ARCHIVED sessions by default, so a roster miss is not absence (standing
  rule: *session roster hides archived*). The pass was right to treat this lane
  as a counterexample and close nothing on ownership grounds.
- **`#630` todo item is NOT owed** — the header said so and it is stale. `#630`
  exists in `todo.md` with all five commits and three follow-ups listed.
- Landed + live: `e78aee52` `bfaa5ecc` `cf569731` `8db62f85` `f027fda6`, plus the
  `.state.json` sidecar merge in `f086691e`.
- Verified: superset 0 lost / 7,104 gained (was 1,318 lost / 0 gained); prefix
  invariant 10/10 windows; 44 markets preserved; `kept_existing_newer=2734`;
  zombies bounded 118/121 reaped; 1,701 merges cost +97 MB (0.057 MB each) vs
  3.87 MB each before the subprocess move.
- Handed off: `#634` (39 contested paths, 38 unmerged, coverage map recorded),
  `#635` (peer-owned), `#632` (peer-owned, rate agreed at ~32-75 MB/h).
- Blocked by: none.

### maxmun-pregame-read — CLOSED 2026-09-02 — opened 2026-09-02 — session ae526656-29ed-4bb4-bee5-e3c9e4e0a583 (scheduled task `todo-628-maxmun-pregame-read`) — **GOAL MET, PASS.** `token: 'maxmun'` on a `POLYMARKET_UNMATCHED` sample for `'player': 'Max Muncy (2002)'`, refresh-worker `ad1de331`, `2026-09-02T13:46:18.027633152Z`, against a served board row for that name in `game.state = "pregame"`. The strip is EFFECTIVE in production, not merely present — `#628`'s pending read is discharged (`51f16af6`), measurement in `deploys.md` 2026-09-02 13:46:18Z (`9960572e`). `prop_same_name_collision_at_venue` = 0 on a demonstrably live instrument. No deploy: read-only.
- Goal: discharge `todo #628`'s PENDING PRODUCTION READ — one production log line
  showing a board name carrying a parenthetical disambiguator deriving its plain
  3+3 token (`maxmun`-style, never `max200`-style), taken on a PREGAME board.
- Files: .syndicate/deploys.md, .syndicate/lanes.md
- Note: the todo item's own file is deliberately NOT claimed here. The `#628`
  paragraph edit is already LANDED as `51f16af6` via the worktree flow, and
  `book-quotes-publish-clobber`'s own heading records that it RELEASED that file
  on 2026-09-01. Claiming it would manufacture a contest over a file this lane
  no longer writes.
- Hypothesis: `38dd9f41`'s parenthetical/pure-digit strip in
  `_player_name_words` is live and effective in production, not merely present.
- Falsification test: a `POLYMARKET_UNMATCHED` sample naming a disambiguated
  board player whose `token` is digit-bearing (`max200`-class) FALSIFIES it.
- Verification: the log line quoted verbatim in `.syndicate/deploys.md`, with
  the deployed refresh-worker SHA named and the token derived by executing THAT
  SHA's own tree.
- Blocked by: none

### soccer-players-csv-allowlist — CLOSED 2026-09-02 — opened 2026-09-02 — session 92987093-6cef-495b-a82b-4bb376dc45dc — **GOAL MET, VERIFIED ON BYTES.** web `2114d5c6` live; `?pattern=soccer_source/*/players/players_*.csv` returns **15 files / 879,401 bytes**, matching the local tree file for file. The reading it gates RUNS: pre-divisor **0.925** (n=9,731) → post **0.631** (n=4,546), ratio **0.682** vs **1/1.393 = 0.718** predicted — a second confirmation of the divisor sharing no denominator with the archive check that closed `#612`. **The lane-inherited `1.19 → 0.85` target is NOT reproducible by this construction (it reads the pre-divisor window at 0.925) and must not be quoted again; only the before/after on ONE instrument is valid.** Claim on web released. Detail: `deploys.md` 2026-09-02 15:0xZ.
- Goal: `#636`. `GET /api/ops/artifacts/export?path=soccer_source/<lg>/players/players_2026.csv`
  returns the CSV body instead of 403, so the board-render form of the soccer
  shot-divisor reading can run from web. One allowlist entry; deploy web.
- Files: `syndicate/features/shared/artifact_publisher.py` (HOT_ARTIFACT_PATTERNS
  entry + its note ONLY), `tests/test_artifact_publisher.py`.
  **CLAIM CHECKED against every OPEN lane.** `artifact_publisher.py` is recorded
  in `ncaaf-week-state` as "claimed by NOBODY and is FREE TO TAKE" after
  `football-projection-publish-allowlist` (`#618`) closed on 2026-09-01. Taken here.
- Hypothesis: the allowlist is the ONLY thing blocking the read — the file is
  already on web's disk.
- **ALREADY TESTED, BEFORE ANY EDIT (this is not an assumption).**
  `soccer_source/epl/api/schedule/schedule_2026.json` is the exact analog —
  season-suffixed, git-tracked, same tree, already allowlisted — and returns
  **200, count=1, 113,410 bytes**. The target returns **403 "path is not an
  allowed hot artifact"**, which is the allowlist branch, NOT `count=0`. So web
  has the tree and the guard is the block.
- Falsification test: after deploy the path returns `count=0` instead of a body.
  That would mean the file is NOT on web's disk and an allowlist entry was the
  wrong fix — the exact shape of the 2026-08-27 FORBIDDEN rule (allowlisting a
  KEYVALUE-backed path and calling it readable turns a 403 into an empty result).
  Which is why the verification below reads BYTES, never a status code.
- Verification: (1) deployed SHA carries the pattern; (2) `?path=` returns a body
  with a `shots_per90` column; (3) the reading `#636` exists for actually RUNS —
  implied Poisson mean over that player's own season shots_per90 — and its value
  is reported. A 200 with no parse is not a pass.
- Blocked by: none.


### soccer-anchor-odds-feed — CLOSED 2026-09-02 (step 1 of 2 done) — opened 2026-09-02 — session 3492626c — **LANDED `5c99c153`. The de-vigged odds feed exists and is VERIFIED ON REAL PRODUCTION DATA: 84 priced events from 2,939 rows across 4 leagues, overround 1.048-1.105 (a real 5-10% three-way vig), P(home) 0.069-0.827, 0 refused. Anchoring is still OFF and still unwired into the builder -- that is step 2 and needs a weight knob, an off!=on test, and the mechanism-vs-estimator re-fit.**
- Goal: make soccer market-anchoring REACHABLE. Production fixtures carry only
  {match_id, home_team, away_team}, so `anchor_ratings_to_market` would skip every
  fixture and be a silent no-op. Feed de-vigged home-win probabilities from
  `<league>/api/odds/game_odds_current.csv` and publish anchored/skipped counts.
- Files: syndicate/features/soccer/features/market_odds.py (NEW),
  tests/test_soccer_market_odds.py (NEW), scripts/build_soccer_artifacts.py
- Hypothesis: n/a (making a validated-but-dead mechanism reachable)
- Falsification test: if the anchored count is 0 on a real matchday, the feed
  does not work and the mechanism is still inert.
- Verification: anchored/skipped counts published per league-date; a fixture's
  home_win_probability matches a hand-computed de-vig of its book rows.
- Blocked by: none. NOTE the mechanism itself stays OFF until (2) — wiring the
  feed does not turn anchoring on.


### accuracy-autorun-decline-telemetry — CLOSED 2026-09-02 — opened 2026-09-02 — session 3492626c — **LANDED `24efb82b`, DEPLOYED, AND IT VERIFIED ITS OWN FIX.** The autorun declined silently on both paths, so "disabled", "gate refused" and "never reached" were one indistinguishable silence — which cost a 100-minute watch that taught nothing. Now emits `ACCURACY_SUMMARY_AUTORUN_GATED reason=...` with `never_run=yes|no`.
- Goal: `_launch_autorun_accuracy_summary` returns False SILENTLY on both decline
  paths, so "flag off", "gate refused" and "never reached" are indistinguishable.
  100 minutes of silence taught nothing. Mirror `RECONCILIATION_AUTORUN_GATED`.
- Files: scripts/run_refresh_worker.py, tests/test_accuracy_summary_autorun.py
- Hypothesis: n/a (fixing an instrument I built blind)
- Verification: an `ACCURACY_SUMMARY_AUTORUN_GATED reason=...` line in
  refresh-worker logs that names WHY it declined.
- Verification RAN, and the line proved a SECOND thing hours later: when the
  autorun was disarmed after OOM-killing the worker, `reason` flipped
  `daily_gate` -> `disabled` at 19:32:27Z. That is direct proof the process read
  the new env value, rather than inferring it from deploy ordering.
- The pattern was already one function above (`RECONCILIATION_AUTORUN_GATED`,
  `#341`), with a comment stating this exact lesson. It shipped without it.
- Blocked by: none (needs a refresh-worker deploy, preflight for in-flight sims)


### soccer-anchor-wiring — CLOSED 2026-09-02 — opened 2026-09-02 — session 3492626c — **LANDED `3cdbcf4c` and DEPLOYED. Anchoring is reachable, instrumented, and OFF (weight 0.0). THE FINDING IS THE COST: 40.9s per fixture — 57 min/cycle at today's 84 priced events, ~136 min at ten leagues — so it cannot run on the refresh cycle as written. That supersedes the mechanism-vs-estimator re-fit as the blocker.** This lane also carried the accuracy-autorun OOM to resolution (disarmed, verified `reason=disabled` 19:32Z).
- Goal: wire `anchor_ratings_to_market` into `build_soccer_artifacts.py` behind a
  WEIGHT knob defaulting to 0.0 (off), publishing attached/skipped/anchored counts
  so an inert anchor is visible. Step 2 of 2; step 1 (`ed48c2e7`) built the feed.
- Files: scripts/build_soccer_artifacts.py, tests/test_soccer_anchor_wiring.py (NEW)
- Hypothesis: n/a (making a validated mechanism reachable)
- Falsification test: off != on -- with weight 0 the ratings must be UNCHANGED;
  with weight > 0 they must differ. If they match either way, the wiring is inert.
- Verification: anchored count > 0 on a real matchday with weight > 0, and the
  counts published even when weight is 0.
- DOES NOT turn anchoring on. Default stays 0.0 pending the mechanism-vs-estimator
  re-fit the standard requires (measured negative interaction 4/4 markets).
- Verification RAN: off!=on asserted before any correctness claim (weight 0
  leaves ratings identical; weight 0.35 moves them). Odds counts publish even
  when off, so the feed's health and the mechanism's arming stay separable.
- Handed to a delegated session: the three cost paths (cut solver sims / anchor
  only board-relevant fixtures / move off the refresh cycle), with the caution
  that better h2h MAE from anchoring is EXPECTED and is not evidence of edge —
  measure anchored-vs-base on PROP markets.
- Blocked by: none

### accuracy-summary-alloc-profile — CLOSED 2026-09-02 — opened 2026-09-02 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885 — **GOAL MET. The allocator is ONE SITE and the scaling is PROPORTIONAL.** 100% of resident bytes at `intelligence_evaluation.py:711` (`json.loads` in `_stream_chunked_ledger_records`); peak = **4.01-4.41 x accepted chunk bytes, intercept ZERO, R2 0.999998** over 9 corpora of real records; materialisation is 98.8-99.9% of peak, so no output-side cap can bound it. Production projection **3,178-3,493 MiB** on top of anon 1,833 -> the kill was CERTAIN, ~915 MiB short at best. Two independent corroborations (64% of the projection consumed at death; 155 MiB/s local vs 146.9 MB/s production climb). **HYPOTHESIS PARTLY FALSIFIED:** the repeated `dict(item)` copies are SHALLOW and cost ~nothing — the peak is one materialisation, not three. **SECOND DEFECT FOUND, NOT MINE TO FIX:** `_bounded_accuracy_summary` truncates the wrong container (`segments_total`=3 vs `len(segments)`=7, `segments_truncated` pinned False, bounded payload LARGER than raw) so the 8MB keyvalue ceiling is unprotected — owner is lane `accuracy-autorun-decline-telemetry`. Bound proposed and measured: cumulative 90,000,000 B budget -> peak 344-378 MiB, worker worst case 55.1% of ceiling. **NOT RE-ARMED; no deploy; no production touched.** Record: `todo.md #626`(h) + `state.md [accuracy-autorun-OOM-2026-09-02]`.
- Goal: a MEASURED allocation profile of `build_accuracy_summary` (peak + top
  allocating sites), a scaling relationship against ledger chunk bytes, and a
  proposed bound stated as an implied peak against the 4,096 MB container whose
  baseline cycle already peaks at anon ~1,877 MB. Recorded on `#626`(h).
- Files: docs/ai_context/todo.md, .syndicate/lanes.md, .syndicate/state.md,
  .syndicate/deploys.md (measurement record only).
  READ-ONLY on `syndicate/features/shared/intelligence_evaluation.py` and
  `scripts/run_refresh_worker.py` — the latter is held by OPEN lane
  `accuracy-autorun-decline-telemetry`; this lane proposes, it does not edit.
  Profiling harness lives in the session scratchpad, not the repo.
- Hypothesis: peak is driven by FULL MATERIALISATION of the deduped record set
  plus REPEATED SHALLOW COPIES of it — `_stream_record_payloads` does
  `yield dict(item)` for an in-memory sequence, and `build_accuracy_summary`
  passes its own `record_rows` back through it TWICE (`compute_metrics` and
  `build_segmented_reliability_profile`). Peak should therefore be ~linear in
  accepted-chunk bytes with a multiplier >1x the single reduced set, and the
  50-segment cap cannot touch it because it truncates OUTPUT after the working
  set has already been built.
- Falsification test: if peak is FLAT in input bytes, or if the top allocating
  sites are not the record materialisation, the hypothesis is wrong and the fix
  is not streaming/chunking.
- Verification: tracemalloc peak AND process RSS delta reported together for
  the same run (the OOM metric is anon RSS, not Python-object bytes — the
  2026-08-29 profiler-scope rule), across >=3 input sizes, with the fitted
  slope stated in MB resident per MB of chunk file.
- Blocked by: none. DOES NOT re-arm `ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN`
  and does not touch production.


### m625-replay-diff-gate — OPEN — opened 2026-09-02 — session cfcce46d-8ad8-4978-9992-5848cba4122a
- Goal: `todo.md #625` build item (5). ONE mirrored production day is replayed
  through the REAL producer entrypoints with fetching disabled, and the
  artifacts it regenerates are diffed against production's OWN recorded outputs
  for that date, tolerance-aware — then wired into `scripts/migration_gate.py`.
  Testable outcome: `py -3 scripts/replay_diff_gate.py --date <D>` exits 0 on a
  day production actually produced, exits non-zero when an input is perturbed,
  and `migration_gate.py` reports its status rather than silently passing.
- Files: `scripts/replay_diff_gate.py` (NEW), `scripts/migration_gate.py`,
  `tests/test_replay_diff_gate.py` (NEW), `scripts/mirror_manifest.py` (NEW).
- NOT CLAIMED, deliberately — both are held by other OPEN lanes and I will not
  edit across them:
  - `syndicate/features/shared/artifact_publisher.py` (`HOT_ARTIFACT_PATTERNS`)
    is held by `book-quotes-publish-clobber`. That blocks `#625` build item (2),
    the EXPORT-ONLY pattern list, which is therefore NOT in this lane's scope.
  - `docs/ai_context/todo.md` is CONTESTED between `accuracy-summary-alloc-profile`
    and `book-quotes-publish-clobber` (`check_lane_invariants.py` FAILs on it
    today). I will record `#625` progress there as a single additive edit to the
    `#625` section only, and say so here rather than claiming the file.
- Hypothesis: the four defects found on 2026-09-02 (evaluation autorun never
  ran; `odds_history` merge cap sized on a 39MB shard against a 109MB pair; the
  autorun's silent False decline; the autorun's OOM) are all
  DEPLOYED-INERT-class, and every one is observable OFFLINE from a mirrored day
  plus a production env snapshot — no deploy, no production time.
- Falsification test: if the first replay target's output cannot be reproduced
  from mirrored inputs alone — i.e. it depends on a fetch, on wall-clock, or on
  state that is not in any artifact — then a replay-diff gate cannot be built
  for it and the target is wrong. Record which, and pick another.
- Verification: (a) one date replayed, diff PASS, with the tolerance stated and
  its justification recorded; (b) a deliberate perturbation of one input makes
  the same command FAIL (off != on — a gate that has never been seen to fail
  proves nothing); (c) `migration_gate.py --json` carries a `replay_diff` block
  whose absent case is reported as UNKNOWN, not folded into `ok`.
- Blocked by: none. Needs NO deploy — it never contends for the deploy queue.

### accuracy-summary-ledger-budget — OPEN, GOAL MET, **BOTH PUBLISHING BLOCKERS FIXED (cross-lane, user-authorised)** — opened 2026-09-02 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885 — **BUILT AND RE-MEASURED OFF vs ON AT PRODUCTION SCALE.** Corpus 831,038,410 B / 8 chunks: budget OFF peak **3,181.1 MiB** (41.2 s), budget ON (90,000,000) peak **344.4 MiB** (7.3 s), accepted 89,967,617 <= budget, coefficient **4.014 in BOTH** — 9.24x reduction, 2,836.7 MiB saved. **The prior extrapolation (3,178 MiB) is now a direct measurement (3,181.1), 0.1% apart.** OFF = 5,014.1 MiB vs a 4,096 ceiling (OOM by 918); ON = 2,221.4 MiB = 54.2% of ceiling. Falsification test PASSED: off != on. 10 new tests, 66 pass across the ledger/summary suites, all 8 pre-existing callers unchanged (budget defaults to None). **DEFECT CAUGHT BY ITS OWN TEST:** the first cut checked the byte limit AFTER consuming the line and read 5,005,916 against a 5,000,000 budget; the bound is now exact. **BOTH BLOCKERS FIXED IN THE SAME SESSION `[user decision: cross-lane edit authorised]`:** `_bounded_accuracy_summary` now publishes `ledger_coverage` and truncates the `segments` LIST (not the mapping's 3 fixed keys), keeping the largest-sample segments. 10 more tests, and all four key assertions VERIFIED TO FAIL against the pre-fix function extracted from HEAD (segments_total 3, truncated False, payload ratio 0.996, coverage None). **NOT RE-ARMED, NOT DEPLOYED.** Record: `todo.md #626`(h) + `state.md [accuracy-autorun-OOM-2026-09-02]`.
- Goal: implement the CUMULATIVE byte budget measured by lane
  `accuracy-summary-alloc-profile` and re-measure peak WITH IT ENFORCED, at
  production scale, off vs on. Peak must land in the predicted 344-378 MiB band.
- Files: syndicate/features/shared/intelligence_evaluation.py,
  tests/test_accuracy_summary_ledger_budget.py (NEW), docs/ai_context/todo.md,
  .syndicate/lanes.md, .syndicate/state.md, .syndicate/log/2026-09-02.md.
  NOT `scripts/run_refresh_worker.py` -- held by OPEN lane
  `accuracy-autorun-decline-telemetry`. Checked: no OPEN lane claims
  `intelligence_evaluation.py`.
- Hypothesis: n/a (building a bound that was measured before it was designed).
- Falsification test: OFF != ON. With the budget unlimited the load must accept
  the whole corpus and peak at ~4.0x its bytes; with the budget set it must
  accept <= budget and peak in the predicted band. If peak is the same either
  way the budget is INERT and this fails.
- Verification: (1) `LEDGER_CHUNKS_ACCEPTED` carries budget/accepted/truncated
  and the accepted sum is <= budget; (2) measured peak at production-scale
  corpus, budget off vs on, both reported; (3) the summary payload itself
  publishes what it covered, so a narrowed sample cannot be read as a full one.
- DOES NOT re-arm `ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN` and does not
  deploy. Local only.
- Blocked by: none



### ledger-land-2026-09-02 — CLOSED 2026-09-02 — opened 2026-09-02 — session 3492626c — **LANDED `27299be6`. The two FORBIDDEN rules, both state blocks and the session checkpoint are on origin/main, verified by grep. Applied from a worktree cut fresh from origin/main because the primary tree was 48 commits BEHIND and pushing it would have reverted peers' ledger work.**
- Goal: land this session's ledger content, which is committed LOCALLY only
  (`adf0d3b9`) in a primary tree 48 commits behind origin/main. Pushing that tree
  would revert 48 commits of peers' ledger work.
- Files: .syndicate/{learnings,state,deploys}.md, .syndicate/log/2026-09-02.md
- Verification: the two new FORBIDDEN rules and the OOM state block are greppable
  on origin/main.
- **CROSS-LANE EDIT AUTHORISED `[user decision 2026-09-02]`.** This lane now
  also edits `scripts/run_refresh_worker.py` (`_bounded_accuracy_summary` ONLY)
  and `tests/test_accuracy_summary_autorun.py`, both nominally held by OPEN lane
  `accuracy-autorun-decline-telemetry`. Surfaced as a conflict and the user
  chose "I take both fixes now". Scope is strictly the two measured defects --
  `ledger_coverage` dropped by the field whitelist, and the truncation aimed at
  the wrong container. **NOT touching `_launch_autorun_accuracy_summary`, the
  decline telemetry, or the enable flag**, which are that lane's actual subject.
- Blocked by: none

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
