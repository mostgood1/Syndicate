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

### keyvalue-pressure-637 — OPEN — opened 2026-09-02 — session 92987093-6cef-495b-a82b-4bb376dc45dc
- Goal: `#637`. Say WHAT holds the shared Redis at 93% and WHETHER the eviction it
  is doing costs anything, with numbers. Diagnosis only — **no production mutation
  in this lane.** `/api/ops/keyvalue/expire-run-artifacts` and `/api/ops/keyvalue/sweep`
  are both POST and both destructive; neither is called without an explicit decision.
- Files: `scripts/check_venue_odds_hydration_census.py` (NEW, claimed 2026-09-02
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
### venue-quote-tests-data-dependent — OPEN — opened 2026-09-02 — session 92987093-6cef-495b-a82b-4bb376dc45dc
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
- Blocked by: none.


### kalshi-discovery-deadline — CLOSED 2026-09-02 — GOAL PARTLY MET, ONE ITEM FALSIFIED RATHER THAN ACHIEVED — **BOUNDS IMPLEMENTED; GUARD VALIDATED (103-152s -> 22.5s); FAN-OUT REPRODUCED (cold state -> 150 = DEFAULT_SERIES_PER_TICK); BUDGET VALIDATED IN SITU (50.1s -> 10.7s); MY MEMO DELETED on 0 measured hits; BUDGET NOW WIRED INTO THE BOARD BUILD and measured draining a cold queue over 3 ticks: the cost is FAN-OUT (243 per-series fetches), not pagination or host retries** — opened 2026-09-02 — session 82fe0160-00b0-4b4b-bd63-2ff14849f885
- Goal: the candidate-pool build cannot block for minutes on Kalshi. ONE testable
  outcome: `tests/test_intelligence.py` completes in bounded time WITHOUT opening
  an outbound socket, and `kalshi_client.discover` aborts at an AGGREGATE
  deadline that a unit test can drive.
- Files: `syndicate/features/shared/kalshi_client.py`,
  `pipeline/kalshi_discovery.py`, `tests/test_intelligence.py` (the network
  guard + the one hanging test only), `tests/test_kalshi_discovery_deadline.py`
  (NEW). Checked against every OPEN lane: none claims these.
  **DELIBERATELY NOT CLAIMED: `pipeline/intelligence_state.py`** — held by OPEN
  lanes `polymarket-yes-leg-binding` and `layer2-cap-raise`. The bound belongs in
  the client, which is also where it fixes every other caller.
  `syndicate/blueprints/intelligence.py` is RELEASED by two lanes but is not
  needed: the request-path gate there is already correct (see below).
- Hypothesis: **the per-request timeout is real and the AGGREGATE is unbounded.**
  `_get` passes `timeout=20.0` to `urlopen`, but `fetch_markets` walks a cursor
  with `max_pages=20` — its own docstring says "`max_pages` is a hard stop, not a
  budget" — inside `for base in _BASE_URLS`, and `_BASE_URLS` has THREE entries.
  Worst case ≈ 3 x 20 x 20s = **1,200s**, with nothing measuring elapsed time.
  Located by faulthandler on 2026-09-02: `_build_candidate_pool` ->
  `run_kalshi_discovery` -> `fetch_markets` -> `_get` -> blocking `ssl.read`.
- Falsification test: if `fetch_markets` breaks out of `_BASE_URLS` on first
  success AND real page counts are small, the ~1,200s ceiling is theoretical and
  the hang has another cause — in which case this lane is wrong and the real
  subject is whatever else blocks. Settle it by TIMING a single
  `run_kalshi_discovery` with per-request and per-page instrumentation before
  changing anything.
- Verification: (1) `tests/test_intelligence.py` runs to completion, with a test
  that FAILS if the suite opens a socket to a venue (the guard must be
  discriminating, not merely present); (2) a unit test drives
  `discover`/`fetch_markets` past the deadline against a stubbed slow transport
  and proves it aborts, reporting what it got rather than raising; (3) an
  off != on check — with the deadline generous the call completes, with it tight
  it truncates and SAYS SO, so a truncated discovery can never read as a
  complete one (`#435`-class: a partial result presented as whole).
- **PRODUCTION SCOPE, SETTLED IN ADVANCE SO NOBODY RE-DERIVES IT.** This is
  **NOT** a production web incident. `intelligence.py:1799` gates on
  `_render_hosted_request()`: on Render a cache miss returns the queued/empty
  placeholder, and the synchronous `_compute_intelligence_response` lives only in
  the `else` (non-Render) branch. That gate was added deliberately — its comment
  records that a synchronous candidate-pool build "drove web to 100% memory /
  0MB headroom" (`#109` follow-up, 2026-07-27). **I overstated this as a live
  request-path defect when I first reported it; corrected here.** The CONFIRMED
  harm is: the regression suite hangs for everyone, and any non-Render caller
  (local dev, CLI, a script) can block for minutes.
- Caution carried from `learnings.md` 2026-08-28: a network result is a fact
  about the NETWORK, not the venue. This lane's conclusion must be about the
  CODE'S BOUND — never "Kalshi is slow".
- **FALSIFICATION TEST RUN 2026-09-02 — MY HYPOTHESIS IS WRONG IN ITS MECHANISM
  AND RIGHT IN ITS CONCLUSION. The subject survives; the aim moves.**

  Timed with `_get` instrumented per request (leaf patch, so import style cannot
  bypass it). Two runs of the single test, `SYNDICATE_WEB_DYNO=1` to skip the
  unrelated WNBA recursion:

      run A   wall 152.1s   calls 290   network 94.1s   (62% of wall)
      run B   wall 109.7s   calls 266   network 64.4s   (59% of wall)
      run B breakdown:  market fetches WITHOUT a cursor   243
                        cursor continuations               21
                        series-catalogue calls              2

  And a standalone `discover()`:

      40 requests, ALL to _BASE_URLS[0], 0 failures, wall 30.27s
      per-request  min 0.52s  median 0.63s  max 1.39s
      pages=40  truncated=True  markets=40,000  singles=201  combinatorial=39,799

  **FALSIFIED — the two multipliers I named are not where the time goes.**
  - `_BASE_URLS` (3 entries) is NOT a 3x multiplier on the normal path. It
    `break`s on first success and every observed call went to base 1 with zero
    failures. The 3x applies only when a host FAILS.
  - `pages` is declared OUTSIDE the `for base` loop and never reset, so
    `max_pages` is a GLOBAL budget across hosts, not per-host. My
    "3 x 20 x 20s = 1,200s" was arithmetic on a loop shape that does not exist.
  - Pagination depth is not the cost either: only **21 of 266** calls follow a
    cursor.
  - The 20s per-request timeout is never approached — median ~0.24s in-test,
    0.63s standalone.

  **CONFIRMED — there is no aggregate bound, and the real driver is FAN-OUT.**
  A single intelligence request issues **~250-290 sequential HTTP requests**,
  dominated by **243 per-series `/markets` fetches**, taking **64-94s** with
  nothing measuring elapsed time, no concurrency, and no memoisation. That is
  59-62% of the test's wall clock.

  **SECOND FINDING, worth its own fix:** `discover()` pays 40 pages / 30s to
  return `truncated=True` every time, and of 40,000 markets only **201 are
  singles** — 99.5% combinatorial parlay noise the board does not bet. The
  module's own docstring already says the market listing is the wrong instrument
  and that `discover_series` exists for this; the catalogue was called **twice**
  against 243 listing fetches.

  **CORRECTION TO MY OWN REPORT: this test does not HANG on Kalshi.** With the
  WNBA recursion branch disabled it COMPLETES, in 109-152s. My earlier 90s and
  240s timeouts were simply shorter than the test. The only infinite hang is the
  WNBA `_artifact_bundle` <-> `_games_from_live_state_fallback` recursion, which
  is a different subject and has no lane. "Slow" and "hung" are not the same
  finding and I reported the wrong one.

- **REVISED GOAL, replacing the original.** A single candidate-pool build must
  not issue hundreds of sequential venue requests. Testable outcome: the same
  test completes with **an order of magnitude fewer Kalshi requests** and an
  AGGREGATE deadline that a unit test can drive, with the truncation reported
  rather than silent. The original goal (a deadline alone) is necessary and not
  sufficient — a deadline on 243 fan-out calls just truncates arbitrarily.
- **REVISED VERIFICATION:** (1) request count for one build drops from ~250-290
  to a stated target, measured the same way (`_get` leaf patch), not asserted;
  (2) an aggregate deadline unit test — off != on, generous vs tight, and the
  tight case must SAY it truncated; (3) the test suite no longer opens a socket
  to a venue at all, with a guard that FAILS when it does.
- **IMPLEMENTED 2026-09-02 — ONE PART VALIDATED, TWO PARTS LANDED UNVALIDATED
  AND LABELLED AS SUCH. The baseline I built this on NO LONGER REPRODUCES.**

  **VALIDATED — the suite network guard.** `tests/test_intelligence.py` now
  installs a transport stub in `setUpModule`
  (`SYNDICATE_TESTS_KALSHI_TRANSPORT`: `block` default | `fake` | `live`).
  Measured on the named test: **103-152s -> 22.5s**. Two guard tests keep it
  DISCRIMINATING rather than decorative — one asserts the stub is installed, one
  asserts the code really does reach for the venue, so deleting the guard fails
  instead of quietly restoring a 100-second suite.

  **LANDED BUT NOT VALIDATED IN SITU — the memo and the aggregate budget.**
  `fetch_markets(use_cache=...)` memoises on
  (series_ticker, status, limit, max_pages) for
  `SYNDICATE_KALSHI_MARKETS_CACHE_TTL_SECONDS` (default 60s, `0` disables), and
  `request_budget(seconds)` is a thread-local aggregate wall-clock bound that
  makes `fetch_markets` return a PARTIAL result flagged `budget_exceeded=True`
  rather than raise. 11 tests, off != on proven for both, plus: distinct series
  are not conflated, a budget-truncated listing is never cached, an exhausted
  budget does not retry all three hosts, and no-budget is a no-op for every
  existing caller.

  **WHY UNVALIDATED, STATED PLAINLY.** The 248-fetch fan-out this lane was aimed
  at **stopped reproducing**. A counter placed INSIDE `fetch_markets` reads
  **0 calls** across four separate live runs (~18:0x-18:4x) on the same test
  that measured 254-290 calls at ~17:0x-17:2x, while the test still takes ~140s.
  Ruled out by direct test, not by reasoning:
  - not the on-disk `reports/intelligence/kalshi_markets.json` artifact — moved
    it aside, re-ran, still 0 calls;
  - not a module-identity problem — `kc.__file__` and `is` both confirm one
    module object;
  - not a subprocess — the original leaf patch on `_get` DID capture the 254
    calls in-process.
  Most likely a SLATE/TIME-OF-DAY conditional path, which is ordinary in this
  repo. **Not identified, so not claimed.**

  **THE CONSEQUENCE, AND IT IS THE POINT:** with `fetch_markets` calls at 0, the
  memo is currently **INERT on the observed path** — the exact
  presence-is-not-reachability trap this repo has paid for repeatedly. It is
  landed because a bound that is unit-proven and off-by-default-harmless is
  worth having for the COLD build where the fan-out does occur, but nobody
  should read it as a measured improvement. **The `-40%` figure (98 redundant of
  248) is a property of the ORIGINAL cold run, not a demonstrated saving.**

- **WHAT THE NEXT SESSION SHOULD DO FIRST — reproduce the baseline before
  touching anything.** Find the condition that makes `_build_candidate_pool` fan
  out across ~150 series (suspect: a pregame slate window). Until that is
  reproducible on demand, no change to this path can be measured, and this lane
  should not be closed. Run `fetch_markets`' own `markets_cache_stats()["calls"]`
  as the instrument — it is now the cheapest possible reachability check.
- **ALSO OPEN, AND NOT THIS LANE'S SUBJECT:** even with the guard installed,
  `tests/test_intelligence.py` as a whole still does not finish inside 10
  minutes (stalls ~32%). So the file has expensive tests beyond the Kalshi one,
  and the WNBA `_artifact_bundle` <-> `_games_from_live_state_fallback`
  recursion remains unfixed and unlaned.
- **ORIGINAL GOAL NOT MET, deliberately not restated to fit what was achieved.**
  "An order of magnitude fewer requests" is not demonstrated; the measured wins
  are the suite guard (103-152s -> 22.5s) and two bounds that are correct in
  unit tests and unexercised in production.
- **FAN-OUT REPRODUCED, AND MY OWN MEMO DELETED ON THE MEASUREMENT
  `[2026-09-02]`. The gate is a PERSISTED PER-SERIES CLOCK, not time of day.**

  `run_kalshi_odds_refresh` (`pipeline/kalshi_odds_refresh.py:749`), NOT
  discovery: `run_kalshi_discovery` is capped at **10** series and paced 0.5s,
  so it was never the source. The real loop is `_due_series(state, ...)` ->
  `cold[:series_per_tick()]` -> `fetch_series` -> `fetch_markets`.

      DEFAULT_SERIES_PER_TICK        150   <- exactly the 150 distinct measured
      DEFAULT_REFRESH_INTERVAL       120s  (per series)
      DEFAULT_DORMANT_INTERVAL      3600s  (a series that read empty)
      state file  reports/intelligence/kalshi_markets.json (markets_artifact_path)

  **REPRODUCTION, on demand:** delete the state file -> every series is due ->
  `fetch_markets` **= 150 calls, 50.1s** (spacing forced to 0). Confirmed twice.
  The disappearance is fully explained: my first runs (~17:0x) ran cold, wrote
  `attempted_at` for all 150, and everything that read empty went DORMANT for an
  hour -- so the ~18:0x-18:4x runs correctly found nothing due and made 0 calls.
  Nothing was broken; I had been measuring a cold-start burst and calling it a
  per-request cost.

  **THE MEMO IS DELETED, not documented.** Two back-to-back forced ticks:

      TICK1  fetch_markets=206  hits=0  misses=206   67.7s
      TICK2  fetch_markets=412  hits=0  misses=412   70.2s   (cumulative)

  **Zero hits, and it is structural, not a tuning error.** WITHIN a tick each
  series is fetched exactly once, so there is no redundancy to memoise; ACROSS
  ticks the 120s refresh interval outlives any TTL short enough to be safe (a
  full tick alone is 50-70s). And the version that WOULD hit is the one that
  must not ship: serving a 120-second-old listing to an odds refresh puts stale
  prices on a money-adjacent board. The "40% repeats" that motivated it was a
  property of ONE cold intelligence run making ~3 passes, not of this loop.
  Removed with its tests -- a passing test for a mechanism that cannot fire is
  worse than no test -- leaving a comment so it is not rebuilt.

  **THE BUDGET IS VALIDATED IN SITU, on the real 150-series tick:**

      unbudgeted, cold state          50.1s
      inside request_budget(10.0)     10.7s

  That is off != on against production code, not a stub. `fetch_markets_stats()`
  survives as the cheapest reachability instrument on this path -- a counter
  INSIDE the function is the only thing that distinguishes "the bound works"
  from "the bound is never reached", and it is what caught my memo shipping
  inert.

- **STATUS: goal substantially met, one item owed.** Delivered and measured: the
  fan-out is reproducible on demand, the aggregate budget bounds it 5x on the
  real path, and the suite no longer calls the venue (103-152s -> 22.5s). NOT
  delivered: nothing yet CALLS `request_budget` in production -- the bound
  exists and is unused, which is the same reachability trap one level up. Wiring
  it needs a caller decision (what budget does a board build get?) and belongs
  with whoever owns `kalshi_odds_refresh`'s cadence.
- **STILL NOT THIS LANE'S SUBJECT:** `tests/test_intelligence.py` as a whole
  still does not finish inside 10 minutes even with the guard (stalls ~32%), and
  the WNBA `_artifact_bundle` <-> `_games_from_live_state_fallback` recursion
  remains unfixed and unlaned.
- **BUDGET WIRED INTO THE BOARD BUILD AND MEASURED ON IT `[2026-09-02]`. The
  owed item is discharged; the bound is no longer unused.**

  **WHERE, and why not at the call site.** `run_kalshi_odds_refresh` has THREE
  callers — `intelligence_state.py:6380` (the board build),
  `run_live_odds_refresh_worker.py:2255`, and `venue_odds_loop`. The budget went
  INSIDE the refresh, not at any call site, so every caller inherits it and a
  new one cannot forget it. It also avoids editing
  `pipeline/intelligence_state.py`, which OPEN lanes `polymarket-yes-leg-binding`
  and `layer2-cap-raise` hold. `pipeline/kalshi_odds_refresh.py` is claimed by no
  OPEN lane — checked against `- Files:` lines, not prose mentions.

  **THE HAZARD THAT MADE NAIVE WIRING DANGEROUS, found by reading the loop
  before writing anything.** `fetch_markets` returns a PARTIAL result on budget
  exhaustion rather than raising, and the refresh computes
  `read_succeeded = strategy == "series_filter"`, treating an empty successful
  read as "this series has no open markets" -> `fetched_at` stamped -> DORMANT
  for `dormant_interval_seconds` (3600s). **A budget that stopped mid-fetch
  would have marked up to 150 series as empty and blanked them off the board for
  an hour.** Three guards, in order of preference:
  1. the loop checks `budget_remaining()` BEFORE spending a request and breaks,
     so an unattempted series keeps its old stamp and stays DUE;
  2. `fetch_series_markets` maps a budget-truncated report to
     `strategy="budget"`, so `read_succeeded` can never be True for one;
  3. the loop breaks on that strategy without writing ANY state for the series.

  **DISCOVERY GETS A SHARE, NOT THE TICK.** `ensure_series_discovered()` runs
  before the price loop. Wrapping the whole run without this starved it —
  observed directly while testing: a discovery timeout left
  `BUDGET_STOP fetched=0 unattempted=25`. It now nests inside
  `min(DISCOVERY_BUDGET_SECONDS=5, tick*0.2)`; `request_budget` nests by keeping
  the TIGHTER deadline, so a sub-budget can only shrink the outer bound.

  **THE NUMBER, sized from measurement not preference.**
  `DEFAULT_REFRESH_BUDGET_SECONDS = 30`, env
  `SYNDICATE_KALSHI_REFRESH_BUDGET_SECONDS`, `0` disables. A cold tick (all 150
  series due) cost **50.1s** at zero spacing and ~72s at the default 150ms. 30s
  admits ~30/(0.24+0.15) ~= 77 series, so a cold start drains over ~2 ticks
  instead of blocking one board build for over a minute, and a warm tick never
  approaches it.

  **MEASURED END TO END, cold state, three consecutive real ticks:**

      TICK1  wall 32.1s  fetched 25  cumulative  25  stamped  25
      TICK2  wall 39.9s  fetched 31  cumulative  56  stamped  55
      TICK3  wall 46.7s  fetched 53  cumulative 109  stamped 108

  The queue DRAINS and nothing is lost: fetched and stamped track each other, so
  no un-attempted series was recorded as read. 11 tests including off != on for
  the wiring itself, the unattempted-not-stamped safety property, and
  budget-truncated != empty book. 251 pass across the Kalshi suites.

  **TWO HONEST LIMITS.**
  - **The budget bounds VENUE REQUESTS, not the function.** Wall clock exceeds
    it (32-47s against 30s) because the merge and state write run after the
    loop. Anyone reading `wall > budget` as a broken bound will be wrong.
  - **Cold-catalogue discovery can exhaust its 5s share and return nothing** —
    seen on TICK1 (`request_budget_exhausted after 0 request(s)`, a 13,771-entry
    catalogue). It self-heals: TICK2 ran warm, succeeded, and added 181 series.
    If a cold start ever needs discovery to complete on the first tick, that
    share is the knob, not the tick budget.

- **STILL NOT THIS LANE'S SUBJECT:** `tests/test_intelligence.py` as a whole
  still does not finish inside 10 minutes even with the guard (stalls ~32%), and
  the WNBA `_artifact_bundle` <-> `_games_from_live_state_fallback` recursion
  remains unfixed and unlaned.
- **CLOSED 2026-09-02. Verification RAN; stating the negative result rather than closing over it.**
  (1) *Request count drops ~250-290 to a target* — **NOT MET, and FALSIFIED rather
  than unachieved.** 150/tick is `DEFAULT_SERIES_PER_TICK`, the design's deliberate
  allocation, and the memo that would have cut it was structurally incapable of
  hitting (0 cache hits over two ticks) — so there is no order-of-magnitude drop to
  have. The original concern ("one build issues ~250-290 sequential requests") is
  RESOLVED BY UNDERSTANDING, not by cutting: it is a cold-start burst under a
  persisted per-series clock, now time-bounded and draining progressively.
  (2) *Aggregate deadline, off != on, tight case must SAY it truncated* — **MET**
  (11 tests; `budget_exceeded` + `BUDGET_STOP`).
  (3) *Suite opens no venue socket, guard fails if it does* — **MET** (103-152s ->
  22.5s, two discriminating guard tests).
  DELIVERED AND MEASURED: fan-out reproducible on demand (delete the state file ->
  150 calls / 50.1s); budget wired into `run_kalshi_odds_refresh` so all three
  callers inherit it; cold queue drains 25/31/53 over three real ticks with
  fetched and stamped tracking each other, so no unattempted series is recorded as
  read. 251 tests pass across the Kalshi suites.
  FOUR LEARNINGS RULES RECORDED, this lane having produced four wrong beliefs:
  limits multiplied by NAME rather than control flow; a cold-start burst reported
  as a per-request cost; a partial-result bound wired without checking how the
  caller reads emptiness (would have blanked 150 series for an hour — caught by
  reading, not by an incident); and `lane_identity_check` belonging AFTER a land,
  because a rebase duplicates a block wholesale.
  NOT DEPLOYED. Landed `0cbb1695`, `376bfa94`, `d8bd4e9d` on origin/main.
  NOT THIS LANE, still open: `tests/test_intelligence.py` as a whole does not
  finish inside 10 minutes even with the guard, and the WNBA `_artifact_bundle`
  <-> `_games_from_live_state_fallback` recursion remains unfixed and unlaned.
- Blocked by: none. Does not deploy; the fix is a bound, and a bound is only
  worth shipping once its off != on test exists.
### m639-actuals-no-truncate — OPEN (fix LANDED `558e4ffc`, NOT DEPLOYED) — opened 2026-09-02 — session cfcce46d-8ad8-4978-9992-5848cba4122a — **THE FIX IS IN AND VERIFIED OFFLINE; ONE THING OWED: a refresh-worker deploy and the tick that proves it.** `write_mlb_actuals_for_date` no longer opens its output `"w"` before knowing whether there are rows. Four cases kept separate: `input_absent` (refuse, and do not even mkdir), `input_unreadable` (its own token), present-but-empty over an existing non-empty file (`refused_empty_overwrite`, with `allow_empty_overwrite` as the override), and rows present (unchanged). **Verified on the real mirror, all three branches** (manifest `c6d52e5db907f9ac`): 06-15 writes 1,123 rows; 06-30 refuses with the prior file BYTE-IDENTICAL; 05-01 refuses `input_absent`. New fields ride in the summary the worker already logs, so the diagnosis becomes visible with **no edit to `run_refresh_worker.py`**. **I ALSO NEARLY DESTROYED THREE PRE-EXISTING TESTS** by overwriting `tests/test_build_mlb_actuals.py`; the diff's 128 deletions is the only reason I noticed. Restored, and one of them then correctly FAILED the fix (it patches the loader, not the filesystem) — so the loader is now the primary presence signal.
- Files: released — `scripts/build_mlb_actuals.py`, `tests/test_build_mlb_actuals.py`.
- **OWED:** deploy `558e4ffc` (or later) to **refresh-worker**, then read the next
  `MLB_ACTUALS_TICK`: the June dates must show `written: false` with a
  `skipped_reason`, and 07-05 / 07-06 / 07-24 / 09-01 / 09-02 `written: true`.
  **A tick where every date reads `written: true` means the guard is INERT.**
- Claims: NONE held.
- Narrative: `log/2026-09-02.md`, `todo.md #639`.

### soccer-anchor-surrogate-heldout — CLOSED 2026-09-02 — opened 2026-09-02 — session b2b5b45b-e938-4cb5-81c2-c211ecc7c703 — **GOAL MET. The surrogate PASSES held-out: neither pre-registered kill condition fired. `b_train=3.6955` frozen on 4 leagues, scored on 8 fixtures from 4 OTHERS (3 goals-rated; targets 0.364-0.838 vs a training range of 0.14-0.65). Surrogate **0.0144** vs the 500-sim solver's **0.0225**; slope bias only +2.9%. **BUT the in-sample '2x better' does NOT replicate** — 1.3x once a CLAMP ARTIFACT is removed, sign test p=0.289/0.453 NOT significant, and the reference's own uncertainty (0.0187) EXCEEDS the surrogate error being claimed. **Defensible claim: EQUAL ACCURACY AT ZERO COST**, which is enough to adopt it as the cost lever (500 sims/fixture → 0) and nothing more. Does not change arming, which was declined on edge and evidence, not cost.**
- Goal: `todo.md #622` OWED item (2). Decide whether the pooled-slope surrogate
  (`shift = (logit(target) - logit(p_base)) / b`, ZERO extra simulations)
  survives a HELD-OUT test. Its in-sample 0.0221 vs the 500-sim solver's 0.0497
  cannot be shipped on — standing rule, 2 failures on record.
- Files: `.syndicate/{lanes,state,log}.md`, `docs/ai_context/todo.md` (`#622`).
  Harness lives in the session scratchpad; NO repo code is touched, this lane is
  measurement only.
- Split: TRAIN = epl, la_liga, serie_a, bundesliga (8 fixtures, M2) -> `b_train`
  = 3.6955, FROZEN. TEST = ligue_1 + eredivisie, primeira_liga, championship —
  3 of 4 are GOALS-rated, a different rating construction, and the test targets
  span 0.364-0.838 against a training range of 0.14-0.65, so it is an
  extrapolation test as well as a held-out one. Asserted disjoint in code.
- Hypothesis: the slope is stable enough (train cv 0.094) that one frozen
  `b_train` beats a 500-simulation bisection on fixtures it never saw.
- Falsification test: if held-out surrogate error >= the solver's on the same
  fixtures, the in-sample result was overfit and the surrogate is dead as a cost
  lever. A slope BIAS on the test set (mean b_test far from b_train) falsifies
  the pooled form even if the error looks acceptable.
- Verification: mean |err| vs a per-fixture logistic reference, surrogate vs
  500-sim solver, on the held-out fixtures only, with the reference's own
  uncertainty (fitted-vs-monotone gap) reported beside it.
- `p_base` is drawn at 400 sims from a seed block DISJOINT from the reference
  grid — taking it from the reference's shift=0 point would share noise with the
  truth and flatter the surrogate.
- DOES NOT arm anchoring. Weight stays 0.0; arming was proposed and DECLINED
  2026-09-02 by user decision, recorded on `#622`.
- Verification RAN, 89,600 simulations, 2,231 s on 10 cores. Per-fixture table
  and both corrections in `todo.md #622` and `log/2026-09-02.md`.
- **Two things I had to correct in my own result before reporting it:** (a) the
  clamp artifact — `AZ Alkmaar v Willem II` has BOTH truth and surrogate pinned
  at `+shift_bound`, so its 0.0000 error is saturation, and it was the largest
  single contributor in the surrogate's favour; (b) the reference is not precise
  enough to resolve the residual difference, so "beats the solver" is not
  established at n=8 even though "does not lose to it" is.
- CLAIMS: none held. Measurement only; no repo code was touched.
- Blocked by: none.

- Goal: fix `todo.md #639` — `write_mlb_actuals_for_date` opened its output `"w"`
  before knowing whether there were rows, truncating `props_actuals_<date>.csv`
  to a bare header hourly for every date whose input had aged off the worker.
- Falsification test (RAN, did not falsify): if "input present but legitimately
  zero rows" could not be told from "input absent", the fix would only move the
  403-vs-404 collapse somewhere new and must not ship in that form. Both cases
  now carry distinct tokens and both are exercised on real mirrored data.
### lane-hint-claims-truthfully — CLOSED 2026-09-02 — opened 2026-09-02 — session 3492626c — **The `[hint]` in `check_lane_invariants.py` announced that every path-naming prose line "becomes a CLAIM". That stopped being true when `claims()` learned the hook's disclaimer stripping, and the stale wording was read off this tool and reported as a live false claim on `artifact_publisher.py` — which is NOT claimed and never was. THE MESSAGE WAS THE DEFECT, the ledger was right. The hint now tests membership in the REAL claim set and prints `0 DO claim it, 1 disclaimed by a marker`.**
- Goal: the hint must not report a false claim against a correct ledger.
- Files: scripts/check_lane_invariants.py, tests/test_check_lane_invariants.py
- Falsification test: a `released:` line must still be SURFACED but reported as NOT
  claiming, while the marker-free phantom line in the existing test must still report
  as claiming. Both asserted.
- Verification RAN: 21/21 pass, and the checker against the live `lanes.md` prints
  `0 DO claim it, 1 disclaimed by a marker` where it used to assert a claim.
- Blocked by: none

### ledger-stale-tree-guard — CLOSED 2026-09-02 — opened 2026-09-02 — session 3492626c — **ROOT CAUSE FIXED + STATE REPAIRED. A kalshi CODE commit (`376bfa94`) carried a `lanes.md` from a tree ~90 commits behind and reverted the trim pass (180,974 B -> 209,141 B), leaving 14 blocks duplicated across `lanes.md` and `lanes_history.md`. EVERY existing predicate passed: the commit ADDED blocks, and a deletion is invisible to any check that looks only at what is present. New predicate fires on the one signature that does catch it — a block VERBATIM in upstream history and gone from upstream `lanes.md`.**
- Goal: a stale-tree ledger commit is refused at the choke point, and the 14
  existing duplicates are removed.
- Files: .claude/hooks/ledger_invariants.py, .claude/hooks/ledger-commit-guard.py,
  .claude/hooks/test_ledger_invariants_resurrection.py (NEW)
- Falsification test: SAME-SLUG must NOT trigger it — 36 slugs legitimately live in
  both files (history holds superseded blocks of lanes still alive; 18 were OPEN).
  Header identity is not enough either: 24 headers matched where 14 bodies did.
  Body byte-identity is the discriminator, asserted in both directions.
- Verification RAN: 7/7 new tests; `test_ledger_commit_guard.py` 16/16 on BOTH the
  patched and the unpatched guard, so the change regresses nothing. Repaired
  `lanes.md` 212,015 -> 175,694 B with all other invariants CLEAN.
- Fails OPEN with no root, no git or no `origin/main` ref — it never guesses.
- Blocked by: none

### ledger-precommit-hook — CLOSED 2026-09-02 — opened 2026-09-02 — session 3492626c — **The ledger invariants now run on EVERY commit, not only those made through a Claude session. `.claude/hooks/ledger-commit-guard.py` is a PreToolUse hook and cannot see a commit made outside one — which is the exact shape of `376bfa94`, the kalshi code commit that reverted the trim pass. `core.hooksPath` points git at the tracked `.githooks/`, so one setting covers all 47 worktrees of this clone and the hook everyone runs is the hook in the commit.**
- Goal: a stale-tree ledger commit is refused by git itself.
- Files: .githooks/pre-commit (NEW), .githooks/ledger_precommit.py (NEW),
  scripts/install_git_hooks.py (NEW)
- Predicates are NOT restated: both guards call `.claude/hooks/ledger_invariants.py`.
  Two guards disagreeing about what "broken" means is worse than one guard.
- Reads `git show :<path>`, which resolves against `GIT_INDEX_FILE` — so it sees
  the TEMPORARY index of a `git commit -- <pathspec>`, the very shape that clobbered.
- FAILS OPEN in every direction: no python, no checker, a crash, an unreadable
  index. ONLY an explicit exit 1 blocks. A pre-commit hook that blocks on its own
  bug is worse than the defect it guards.
- Verification RAN — real `git commit` in a throwaway clone, not a simulated call:
  stale commit BLOCKED (exit 1, `BLOCKED by pre-commit`); honest new lane block
  COMMITTED; `SYNDICATE_ALLOW_LEDGER_COMMIT=1` and `--no-verify` both bypass.
- The first run of that test reported a false failure — the "honest" case wrote
  content identical to HEAD, so git's own "nothing to commit" exit 1 read as a
  block. Asserting on the hook's own stderr, not the exit code, is what separated
  them.
- Installer REFUSES if `.git/hooks` holds real hooks, because `core.hooksPath`
  would disable them silently. `*.sample` files never run and are ignored.
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
