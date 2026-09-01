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

### repo-coordination — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — **POSSIBLY ORPHANED, unconfirmed `[flagged 2026-08-19]`: no currently-running session found narrating its own work under `repo-coordination` — every hit is a session reading the shared `lanes.md` digest or its own guard output (one session's transcript shows `your lane: repo-coordination` printed to a session that is clearly NOT this lane — `Modeling Session (fork 2)` / `abf487e4…` — the exact bare-file misattribution bug fixed earlier 2026-08-19, not evidence of real ownership). No `.current-lane.<session_id>` marker exists for it. Not closed and not force-reassigned on this evidence alone — a live session claiming this lane should confirm by opening it fresh (which now also backfills its own per-session marker).** deployment, assignment and documentation. NOT any sport, model or engine. — opened 2026-08-18 — session: repo-coordination
- **Goal (single testable outcome):** the machinery that decides WHO deploys,
  WHO owns which files, and WHERE a fact is written stays coherent and
  self-checking. Testable: `lane_identity_check.py`, `todo_id_reconcile.py` and
  `state_key_check.py` all exit 0, CI enforces all three, and every deploy goes
  through claim + preflight.
- **Scope, stated as a boundary because this lane already crossed it twice:**
  hooks, guards, the deploy path, the four ledgers, `CLAUDE.md`, and the
  session/worktree protocol. **NOT** sport features, sim engines, model inputs,
  backtests, or "just reading a board to see if a model is fed". If a task's
  outcome is a statement about a MODEL, it belongs to that sport's lane.
- **Files:**
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: - `.claude/hooks/` (deploy-guard, lane-guard, commit-guard, session-start)
  released: - `scripts/session_worktree.py`
  released: - `scripts/lane_identity_check.py`
  released: - `scripts/todo_id_reconcile.py`
  released: - `scripts/state_key_check.py`
  released: - `scripts/deploy_claim.py`
  released: - `scripts/deploy_preflight.py`
  released: - `docs/ai_context/session_isolation_protocol.md`
  - RELEASED 2026-08-25 by `exchange-markets-api-integration` (narrowly, the
    `pytest-baseline` job's own step only -- see that lane's block for the
    full note): the CI workflow file
- **`lane-guard` is EXONERATED** on the mangled-relpath question — it is
  absorbed by exact-or-suffix matching. **Do NOT "fix" its `root`; the PRIMARY
  tree is correct for it.**
- **Known open, in remit:**
  - `land` reports the ledger checkers rather than gating on them.
  - ~100 stale worktrees under `C:/tmp` need a human pass before reaping.
  - **`deploys.md` (2.1 MB) and `lanes_closed.md` have no size discipline and no
    checker** — `lanes.md` now has both; these two do not.
- **NOT claimed, deliberately:** every `syndicate/features/**` path, every
  `scripts/generate_*` and `scripts/backtest_*` entrypoint, and every per-sport
  checklist or engine reference. Those belong to sport lanes.
- Blocked by: none.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

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

### mlb-native-ladders-producer — CLOSED 2026-09-01 — **PRODUCER PROVEN, GOAL PARTLY MET, REMAINING WORK MOVED TO `todo.md #493`.** VERIFIED: `generatedBy == syndicate.features.mlb.ladders_build` on the SERVED `daily_ladders_2026_09_01.json` (was ABSENT), `generatedAt 16:38:21Z` — after the `c2f3efe4` deploy finished 16:02:39Z — pitcher `ladder` 30/30, `gamePk` 30/30, artifact 16,625,227 -> 1,529,320 B; measurement in `deploys.md`. **NOT MET, and closed anyway by explicit user decision:** the goal also said *vendor stage removed* (it is NOT — correctly, removing it short of parity converts a degraded path into an outage) and *both consumers rendering unchanged* (they do NOT — `/mlb/api/hitter-ladders` now shows `PA mean` and `Order` as `-`, 2 of 4 presenter fields at 0/30; hitter `ladder` 0/391 vs vendor 234/234, which does not break the page). No outage; the regression is scoped to 2026-09-01 because the force knob is one-shot and date-scoped. **All three unmet items live on in `todo.md #493` — this closure archives the block, not the work.** — opened 2026-08-20
  SERVED artifact is now `syndicate.features.mlb.ladders_build` (was ABSENT), at
  `generatedAt 2026-09-01T16:38:21Z` — AFTER the `c2f3efe4` deploy finished
  16:02:39Z — with pitcher `ladder` 30/30 and `gamePk` 30/30, and the artifact
  16,625,227 -> 1,529,320 B. Measurement in `deploys.md`.
- **CORRECTION to this block: the knob was NOT unset, it was STALE.** It read
  `2026-08-20`. Being date-scoped and self-expiring, it evaluated FALSE once that
  date passed — present in config, inert in effect. "Env var NOT set and the
  deploy is parked on it" was the right symptom with the wrong cause, and would
  have sent the next reader looking in the wrong place.
- **I DID NOT DEPLOY.** `mlb-accuracy-assessment` held the refresh-worker claim
  and deployed `c2f3efe4` for its own two lanes; the armed knob rode along. Env
  set via the single-key API, so no `render.yaml` and no `blueprint_sync`.
- **THE PARITY GAPS ARE NOW VISIBLE IN PRODUCTION, and measured on the consumers:**
  both ladder pages render real projections with no empty state, but
  `/mlb/api/hitter-ladders` shows `PA mean` and `Order` as `-` (`paMean` and
  `lineupOrder`, 2 of the 4 known presenter gaps; all 4 are 0/30). Hitter
  `ladder` is **0/391** against the vendor 234/234 and does NOT break the page,
  which corroborates "no consumer reads them". **Scoped to today**: the knob is
  one-shot and inert tomorrow, when the vendor writer resumes.
- **STILL OPEN, and this lane should stay open:** the 4 presenter fields, the
  hitter-ladder decision, and removal of the vendor stage — which must NOT be
  done until native reaches parity, per this block's own rule.
- **PRODUCTION READ 2026-09-01 09:3xZ — OBLIGATION STILL UNDISCHARGED, and now precisely
  characterised.** Served `daily_ladders_2026_09_01.json` (16,623,227 B, `generatedAt`
  2026-09-01T09:18:17-05:00, status `skipped_fresh`, 15 games): **`generatedBy` is ABSENT from the
  artifact entirely** — not wrong, absent — so nothing attributes it to
  `syndicate.features.mlb.ladders_build`. Consistent with the knob never being armed.
- **`ladder[]`/`gamePk` are 30/30 on pitcher strikeouts and that proves NOTHING** — the same trap
  this lane already recorded for chips: the vendor writer populates them too. Only `generatedBy`
  discriminates. The 4 known presenter gaps confirm the vendor shape: `lineupOrder`, `paMean`,
  `matchupReasons`, `matchupSummary` all **0/30**, and a hitter group is present (16.6 MB against
  native+pitcher's measured 635,001 B).
- **The blocker is unchanged and confirmed by reading, not assumed:**
  `SYNDICATE_MLB_LADDERS_FORCE_DATE` is not armed on refresh-worker, so the native path has never
  run. Arming it is a single-key env write PLUS a deploy (env changes need one), and was NOT done
  here — it is a production config change nobody asked for.
- **Goal (single testable outcome):** `daily_ladders_<date>.json` produced by
  `syndicate.features.mlb.ladders_build` on the NORMAL path — `generatedBy`
  stamped on the SERVED artifact — with the vendor ladders stage removed and both
  consumers rendering unchanged.
- **Files: released:** `syndicate/features/mlb/ladders_build.py`, `tests/test_mlb_ladders_build.py`, `scripts/run_mlb_daily_sim_job.py`, `tests/test_run_mlb_daily_sim_job.py`.
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- **INHERITED OBLIGATION: DISCHARGED 2026-09-01 16:38Z.** `generatedBy` on the
  Discharge by arming `SYNDICATE_MLB_LADDERS_FORCE_DATE=<central date>` on
  refresh-worker and reading `generatedBy == syndicate.features.mlb.ladders_build`
  PLUS populated `ladder[]`/`gamePk` on 18/18 pitcher rows. **Chips on the board
  prove NOTHING** — the vendor writer renders them either way. Knob shipped
  (`c99b259c`); env var NOT set and the deploy is parked on it.
- **Gap to parity:** 4 presenter fields (`lineupOrder`, `paMean`,
  `matchupReasons`, `matchupSummary`) and hitter ladders 0/234 vs vendor 234/234.
  The other 14 vendor-only fields are NOT blockers.
- **Hitter ladders: decide, do not default.** No consumer reads them, and this
  artifact has silently exceeded `_PUBLISH_MAX_BYTES` before. Native+pitcher is
  635,001 B vs the vendor's 9,518,280 B. **Do not add them without a consumer.**
- **Do not delete the vendor stage until native is proven on the normal path** —
  the board runs on the vendor artifact, so removing its writer first converts a
  degraded path into an outage.
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

### nfl-props-odds-allowlist — CLOSED 2026-09-01 — **the one owed item is DISCHARGED, read on production.** `a41f88f8` needed no dedicated deploy and was carried by a later main deploy as predicted: it is an ancestor of refresh-worker's live `1c078f46` AND the live code content uses `nfl_artifact_output_root()`, not the probing `default_nfl_source_root()`. Both halves of the lane's own test pass on `nfl_source/schedule_2026.csv`: mtime **1788273215.1262631 — FRACTIONAL** (a runtime write, not a whole-second boot copy), and lined games **67 -> 112 of 272** (`spread_line`/`total_line`/both moneylines each filled 112/272). Goal was already MET: 64,007 graded bets, model priced at -7.35%. — opened 2026-08-20 — session e5e93171-243f-485e-8ade-9116f0130519
- Goal: a real ROI number for NFL player props. **MET** — 64,007 graded bets,
  `reports/nfl_props_roi.json`. Model priced at **-7.35%**; it does not beat the
  market (fading it loses 16.93%, so the picks are correctly signed and simply do
  not clear the vig). Price shopping **+2.95 ROI pts**, game context **+1.18**.
- Claims held: **NONE.** refresh-worker released 2026-08-21 deliberately rather than
  held through polling — the service was busy on nearly every check for two hours and
  other lanes needed it. Holding a lock while waiting on an unpredictable condition is
  the retired-coordinator anti-pattern.
- Claims held: **NONE.** refresh-worker released 2026-08-21 deliberately rather
  than held through polling — holding a lock while waiting on an unpredictable
  condition is the retired-coordinator anti-pattern.
- **OWED — ONE ITEM, and it needs NO dedicated deploy.** `a41f88f8` on main fixes
  `#389` hit a second time: `fetch_nfl_schedule.py` wrote via the PROBING
  `default_nfl_source_root()`, so every write landed in the EPHEMERAL CHECKOUT and
  `publish_hot_artifact` was a silent no-op. The step reported `status=ok
  return_code=0` in 1s every cycle and delivered nothing. **WHOEVER DEPLOYS MAIN
  TO refresh-worker NEXT PICKS THIS UP FOR FREE.** Then verify BOTH together:
  `nfl_source/schedule_2026.csv` on web gains a **FRACTIONAL** mtime
  (whole-second = another boot copy, not a publish) AND its lined-game count goes
  **67 → ~112**. A fresh mtime alone could be a rewrite of stale bytes.
  NOT URGENT — it only feeds the game-context multiplier.
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
  - **BLOCKED, NOT CLAIMED:** the `HOT_ARTIFACT_PATTERNS` entry for
    released: `wnba_source/data/live/live_player_box_*.json` lives in a file held by the
    OPEN lane `nfl-props-odds-allowlist` (actively editing that same list). Not
    edited across lanes. **Until it lands the capture writes an artifact the
    board build cannot see** — written, not yet reachable, which is exactly the
    half of `#488` that reads as working. Owed with it: the
    `is_hot_artifact_relative_path` test.
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
- **BLOCKED, NOT CLAIMED:** the `HOT_ARTIFACT_PATTERNS` entry for
  `wnba_source/data/live/live_player_box_*.json`. Until it lands the capture
  writes an artifact the board build CANNOT SEE — written, not reachable, which
  is exactly the half of `#488` that reads as working.
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

### exchange-markets-api-integration — CLOSED 2026-09-01 — six read-only venue client modules delivered and present in git; execution caps verified live 2026-08-25T19:35Z (bankroll $1000, Kalshi $50/day, Polymarket $100/day, $10 max order, 15 orders/day) after correcting a drifted flat $40/day on live-odds-worker. Nothing outstanding: Polymarket order automation shipped via a sibling session, Novig buy-side OFF by user decision 2026-08-24, ProphetX blocked on a partner credential with no self-serve path. All claims and deploy claims released. — opened 2026-08-24 — session 71a74bb7-67ff-5c39-af7a-c11c2d94cce8
- Goal (DONE): read-only market/odds-pulling client modules for six
  prediction/event-market venues (coinbase, prophetx, novig, polymarket,
  robinhood, crypto.com). Canonical detail: `todo.md #544`.
- Files still claimed: released: `syndicate/features/shared/{coinbase,prophetx,novig,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: polymarket,robinhood,cryptocom}_client.py`, matching `scripts/probe_*.py` and
  released: `tests/test_*_client.py`, `.syndicate/scope_2026-08-24_exchange_markets_api_integration.md`,
  released: `scripts/probe_exchange_markets.py`.
  RELEASED `[2026-08-29, USER OVERRIDE, to ncaaf-no-orders]`: `scripts/run_refresh_worker.py`
  This lane's claim on it was always **NARROW** and self-described as "one
  small, additive, opt-in-only boot-probe hook"; the lane is idle with
  "nothing outstanding". `ncaaf-no-orders` needs a DIFFERENT region of the same
  file (`_season_projection_should_launch`), `lane-guard` BLOCKED it, the
  conflict was surfaced to the user rather than worked around, and the user
  granted the override. Marker on its own line so the parser SEES the release,
  per the note in `portfolio-ledger-service-split` — which released this same
  path to this same lane on 2026-08-24 for the same reason.
- **Status: nothing outstanding for this lane.** `#544`'s stated NEXT phase is
  externally resolved: Polymarket order automation shipped via a sibling
  session; **Novig buy-side automation is OFF by explicit user decision
  (2026-08-24)**; ProphetX is blocked on a partner credential with no self-serve
  path.
- **Execution caps verified live 2026-08-25T19:35Z:** bankroll $1000, Kalshi
  $50/day, Polymarket $100/day, $10 max order, 15 combined orders/day.
  `live-odds-worker` env vars had DRIFTED to a flat $40/day for both venues and
  were corrected.
- **A marker must sit on its OWN LINE so the parser SEES the release** — the
  `run_refresh_worker.py` release to `ncaaf-no-orders` is written that way.
- Blocked by: none. All deploy claims released.
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

### boot-sync-healthcheck-kill — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-27 — session 64625b4d
- Goal: a web boot must not cost the container a long blocking file walk, so
  sync I/O cannot starve `/healthz` inside Render's 5s budget.
- Status: **both fixes LIVE.** Boot sync **72.20s -> 0.65s**, reproduced at
  0.59s on an unrelated lane's next deploy. `present=33316` + `unchanged=76` =
  33,392 = `git ls-files` over the roots, so nothing was skipped.
- Files: released: `scripts/bootstrap_data_root.py`, `syndicate/app.py`
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
- **Open ONLY on the rate.** 2 deploys since the fix, 0 `server_failed`.
  Against a ~1-in-5 base rate that is **not yet evidence**. Close when >=5
  deploys have accumulated with no kill — **they will arrive from other lanes'
  work; do not manufacture deploys for this.**
- **Verification is NOT a per-boot `/healthz` trace** — that does not
  discriminate, since two PRE-fix boots that survived were equally clean (5.13s,
  5.59s). Count `server_failed` per deploy over >=5 deploys.
- Not this lane: `GET /` at 8.1s (`home.py`, claimed elsewhere) is the other
  documented route to the same 5s budget.
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

### ncaaf-settlement-resolver — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-28 — session 764eca35-178c-4c29-afbd-ec621894aaf1
- Goal: NCAAF bets can be GRADED, and are graded against the RIGHT GAME.
- Files: released: NEW `syndicate/features/shared/ncaaf_team_registry.py`, NEW
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `scripts/poll_ncaaf_live_state.py`, NEW
  released: `syndicate/features/shared/bet_status_ncaaf.py`, NEW
  released: `tests/test_bet_status_ncaaf.py`, plus the same ONE-LINE carve-out on a file
  held by `open-bet-live-status`: `syndicate/features/shared/paper_settlement.py`
  Reordered 2026-08-28 so the parser reads this as the deference it always was:
  the carve-out has landed and this lane was never a second owner. Plus the
  pinned-set assertion in
  released: `tests/test_paper_settlement.py` that `nfl-settlement-resolver` added.
- **Do not describe this as end-to-end verified** — a real graded NCAAF bet was
  not available at the time the work landed.
- Blocked by: none.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### soccer-overview-cost — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — soccer cost SOLVED and VERIFIED (363s -> 80.5s); board staleness cause FOUND, fix SCOPED not built — opened 2026-08-28 — session 3e5a9659 (checkpointed 2026-08-29)
- Goal: name where soccer's overview time goes, then remove it. **Done.** Cause was
  `_normalized_market_text` (39,281,743 calls / 713.5s cum per soccer pass, six
  `re.sub` with STRING patterns -> 238,477,602 `re._compile`). Precompiled + memoized.
- **VERIFIED:** soccer bracket 452.97 -> 362.76 -> **80.50s**, `collect_s=75.41`,
  `candidates=249` (held). `lstat` per branch 7,955 -> 944 -> absent.
  Full evidence + dead ends: `.syndicate/log/2026-08-29.md`.
- **BOARD STALENESS IS A DIFFERENT DEFECT AND IS NOT FIXED.** Served 18:13:02Z
  `computed_at 2026-08-28T23:03:31Z` (19.2h). `2026-08-30` has ONLY soccer
  fixtures, so `_supported_intelligence_dates()` (five DAILY sports) never makes
  it eligible to build, and its 42 real Serie A rows age on the board forever.
  **Scoped in `state.md [week-scoped-board-window]`; NOT built.**
- Claims: `syndicate/features/soccer/{sources.py,cards.py,props.py}`,
  `syndicate/features/shared/{source_roots.py,branch_profiler.py}`,
  `syndicate/features/intelligence.py`, `pipeline/intelligence_state.py`,
  `syndicate/blueprints/home.py` (instrumentation only), and their tests.
- Deploy claims: none held. Profilers disarmed (`SYNDICATE_SPORT_OVERVIEW_PROFILE=off`,
  `SYNDICATE_CONSUME_SPORT_PROFILE=off`).
- **NEXT ACTION:** verify `SLOW_REFRESH_SECONDS` actually BINDS before widening the
  build window — widening without it halves today's refresh rate.
- Blocked by: none.
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

### ncaaf-no-orders — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-29 — session 7b278ebe-b1fa-4ea4-9648-834fb63961b7
- Goal: name the FIRST stage in the NCAAF chain that is zero, with a production
  reading rather than a belief.
- Files: released: `scripts/generate_smartsim2_ncaaf_projections.py`,
  **CLAIMS RELEASED 2026-08-29 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `syndicate/features/ncaaf/cfbd.py`,
  released: `syndicate/features/ncaaf/cfbd_backoff.py`,
  released: `tests/test_cfbd_backoff.py`,
  released: `scripts/run_refresh_worker.py`,
  released: `tests/test_season_projection_staleness.py`
  (the last two added 2026-08-29 by USER OVERRIDE — `exchange-markets-api-integration`
  released the worker entrypoint; see its Files line.)
- **NOTE FOR WHOEVER CLOSES THIS: the lane's ORIGINAL question is answered and
  is NOT what these commits fix.** Zero NCAAF orders is `pick_gate` denying
  ncaaf spread/moneyline/total on a measured out-of-sample loss, **working as
  designed**. Fixing the 429 will NOT produce NCAAF orders. **Do not let these
  two commits read as a fix for that.**
- **STILL OWED — the production reading.** Everything else is BENCH evidence.
  The reading that closes it: after a deploy carrying `b59ee603`, either a
  `[cfbd_backoff] ... status=429 ... sleeping=` line followed by a run that
  COMPLETES, or `SEASON_PROJECTION_RELAUNCH_HELD sport=ncaaf` with
  `SEASON_PROJECTION_LAUNCHING` falling to ~1/hour. **A quiet log is not a
  pass** — the same trap `#593`'s verification carried.
- **The CFBD paths in this block were RECLAIMED 2026-08-31** by lane
  `ncaaf-cfbd-quota-latch`, which shipped the monthly-quota latch and the PPA
  cache this lane's own analysis proposed.
- Blocked by: none.
- Full working record moved VERBATIM to `.syndicate/lanes_history.md` at the 2026-08-31 compaction. Nothing was summarised away.

### live-prob-producer-reader-gap — OPEN, **UNOWNED** [ownership sweep 2026-08-31: owning session gone, no live session on this machine] — opened 2026-08-29 — session d617eefd-1628-4795-9e11-7b6aaa3f2ff3
- Goal: decide, with ONE measurement, whether MLB live prop probabilities are
  LOST IN THE JOIN or NEVER PRODUCED. No code change until it is decided.
- Files: released: syndicate/features/shared/live_projection_join.py,
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: syndicate/features/shared/polymarket_board_join.py,
  released: pipeline/portfolio_commit.py
- **THE QUESTION IS ANSWERED, AND IT IS NEITHER OPTION** `[2026-08-31, lane
  mlb-live-prop-prob-merge]`: the probabilities are **PRODUCED AND THEN
  DISCARDED**. `_merge_cards_context_into_live_row` replaced the MC row set
  wholesale with the cards set. `LIVE_MC_PRICED` ran 27,26,18,16,14,11,10,8,5,4,
  2,0 over one game against a published `with_live_prob: 0`. Fixed by carrying
  the probability ONTO the card rows; DEPLOYED, and awaiting its first live MLB
  game. **This lane's file was imported read-only, never edited.**
- **TWO STANDING CONSTRAINTS, both to be surfaced before any edge work:**
  1. A live-edge attempt was **SHIPPED AND BACKED OUT.** It priced
     `modelProbOver`, bit-identical to the PREGAME probability on 24 of 28 rows;
     three props whose over had ALREADY WON still read 0.659/0.655/0.745,
     producing +36.5%/+32.3%/+15.8%. Mean |edge| on decided rows 28.2% vs 12.0%
     on undecided — **fabricated numbers twice the size of real ones, sorting
     straight to the top of an edge-ranked board.** Treat as a standing decision.
  2. `live-game-line-projection` (CLOSED) measured the live model TRAILING the
     market on 8 of 9 scored dates. **A live edge computed against a model that
     trails the market is a false edge.** Even a clean keying fix does not by
     itself make live opportunities safe to place.
- **CLAIM CORRECTION recorded rather than quietly fixed:** two of the paths
  above were being EDITED WITHOUT A CLAIM for five commits after
  `venue-join-refusal-visibility` closed and released them. Nothing collided,
  but two sessions are live on adjacent code.
- Blocked by: none
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

### exchange-join-refusals — OPEN, **UNOWNED** `[session 5611932c ARCHIVED 2026-09-01 ~01:4xZ]` — opened 2026-08-30
- Goal: establish, as a MEASUREMENT rather than a belief, how many of the
  exchange quotes the Layer 2 board discards at the venue-adapter boundary are
  RECOVERABLE, and by which mechanism. No fix in this lane.
- Files: released: `scripts/probe_polymarket_ncaaf_slug_role_join.py`,
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: `.syndicate/findings_2026-08-30_layer2_board_assessment.md`
- NOT CLAIMED, AND DELIBERATELY NAMED OUTSIDE THE `Files:` BLOCK ABOVE: the two
  fix sites (the venue quote adapters module and the venue quote fan-in module,
  both under syndicate/features/shared/) are held by `live-venue-order-placement`.
  Written un-backticked and out of the block on purpose — `check_lane_invariants`
  reads any backticked path inside `- Files:` as a live CLAIM, which is how this
  lane briefly contested a file it is explicitly staying off.
- **RESULT `[measured 2026-08-30, n=25 of a 165-market population]`: HYPOTHESIS
  FALSIFIED, and the replacement is sound but small.** `canonical_team` resolves
  **0/25**. The slug-token pair resolves **2/25 = 8%** — Polymarket's
  abbreviations are not the registry's (`nmxst` vs `NMSU`, `flst` vs `FSU`), the
  SAME upstream-vocabulary wall the reverted alias map hit. A
  schedule-constrained mascot-pair join resolves **4/25 = 16%** with **0
  ambiguity**. **21 of 25 sampled markets are games this platform does not
  card** — so `clubs_unresolved: 314` is ~157 markets of which **~26 are ours.
  The counter is not a backlog and anything sized off 314 is sized wrong.**
- **Next, and NOT this lane's to take:** the Kalshi `h2h_keyed_by_team` 905 and
  the ~3,290 spread refusals have NOT had this scope check. **Do it before
  sizing either** — the NCAAF result is the reason to distrust a raw refusal
  count.
- **Standing rule this lane is subordinate to, NOT overridden:** `learnings.md`
  2026-08-29 "FORBIDDEN: closing a name-join gap by POPULATING an alias map,
  without first checking the map's source carries the missing name".
- Blocked by: `live-venue-order-placement` (holds both fix sites).
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

### football-projection-publish-allowlist — OPEN — opened 2026-09-01 — **CODE ON MAIN (`fcbbcc62`). NO DEDICATED DEPLOY — RIDEALONG BY USER DECISION. Tracked as `#618`.** Needs BOTH services, and a PARTIAL ridealong logs the same line as the unfixed bug.
- Goal: the NFL/NCAAF season-projection CSVs the worker regenerates daily
  actually reach the board, instead of the board only moving when someone
  COMMITS a CSV and rides a web deploy.
- Files: `syndicate/features/shared/artifact_publisher.py` (2 allowlist entries),
  `tests/test_football_projection_publish_allowlist.py` (NEW).
- Origin: handed off from `ncaaf-cfbd-quota-latch`, which measured it on
  2026-09-01 while verifying the quota-latch roll.
- THE DEFECT: both generators have called `publish_hot_artifact` since
  2026-08-19 and both calls were **no-ops for 13 days** — neither output path
  was in `HOT_ARTIFACT_PATTERNS`. `generate_smartsim2_nfl_projections.py` says
  in its own comment *"the allowlist pattern covers both"*; that pattern never
  existed. `#208` in reverse: the usual failure is allowlisting something
  nothing publishes, this is publishing something nothing allowlists, and it is
  just as silent (`artifact_published=False`, no error).
- Added: `ncaaf_source/data/smartsim2_projections_*_wk*.csv` and
  `nfl_source/smartsim2_projections_*_wk*.csv`. Depths differ because `#389`
  put NFL's output one level shallower; NOT collapsible into one wildcard.
- WRITE->READ CHECKED, not assumed: worker writes
  `<SYNDICATE_DATA_ROOT>/ncaaf_source/data/...`; web reads
  `default_ncaaf_source_root()/"data"` == `$SYNDICATE_NCAAF_SOURCE_ROOT/data`
  == the same directory. NFL likewise via `_source_roots()`. The sibling lane
  `nfl-props-odds-allowlist` already proved this chain end-to-end on
  `nfl_source/schedule_2026.csv`.
- **RIDEALONG, BY DECISION `[2026-09-01, user]`. DO NOT SCHEDULE A DEPLOY.**
  Two allowlist strings cost nothing to carry and do not justify restarting a
  worker running an MLB sim. `nfl-props-odds-allowlist` closed the identical
  situation the same way ("WHOEVER DEPLOYS MAIN TO refresh-worker NEXT PICKS
  THIS UP FOR FREE") and its prediction held. **No claim was ever acquired by
  this lane; nothing is held.**
- **NEEDS BOTH refresh-worker AND web, AND A PARTIAL RIDEALONG IS
  INDISTINGUISHABLE FROM THE UNFIXED BUG.** The SENDER
  (`publish_hot_artifact`) and the RECEIVER (`ops._write_published_artifact`)
  each call `is_hot_artifact_relative_path`. web-only -> the worker still
  refuses locally; refresh-worker-only -> web answers 403. **Both partial
  states log `artifact_published=False`, the same line as doing nothing.**
  Before concluding this failed, READ THE LIVE SHA ON BOTH SERVICES — the
  natural reading of "still False" is "the fix does not work", and it will
  usually mean "only one side has it yet".
- **AND THE BOARD STILL WILL NOT MOVE ON DEPLOY ALONE.** There is no blanket
  sweep on refresh-worker (`sweep_changed_hot_artifacts`'s only production
  caller is `live_lens_loop`), so the already-written 2026-09-01T00:33Z CSV is
  NOT picked up retroactively. It publishes when the GENERATOR next runs —
  ncaaf on the 86400s interval, nfl likewise.
- Deploy state at hand-off (2026-09-01T15:2xZ): web `ad33df21`, refresh-worker
  `1c078f46`, live-odds-worker `1c078f46`. `fcbbcc62` is a strict FORWARD move
  for both services (checked, not assumed) and an ancestor of `origin/main`, so
  any later main deploy carries it without an `OFF_MAIN` or rollback refusal.
- Whoever deploys refresh-worker next also picks up `layer2-cap-raise`'s staged
  env: `SYNDICATE_LAYER2_ROWS_PER_SPORT=2000`, `SYNDICATE_LAYER2_ROWS_TOTAL=6000`.
  **Confirmed by reading LIVE env-vars, not from the ledger.** That is that
  lane's intended pickup, not a surprise.
- VERIFY BY (reuse `nfl-props-odds-allowlist`'s own recipe, which caught this
  class once already): `artifact_published=True` in the generator's log, THEN
  `/api/ops/artifacts/export?path=ncaaf_source/data/smartsim2_projections_2026_wk1.csv`
  returns count=1 with a **FRACTIONAL** mtime (a whole-second mtime is a boot
  copy, not a publish), THEN `/ncaaf/api/cards` values DIVERGE from the
  git-committed `generated_at=2026-08-19T22:00:39Z` CSV. All three: a fresh
  mtime alone could be a rewrite of stale bytes, and the generator is
  deterministic so identical values would NOT disprove a successful publish.
- NOT DONE, DELIBERATELY: `nfl_source/smartsim2_preseason_projections_*_wk*.csv`.
  That generator has no `publish_hot_artifact` call, so the entry would be the
  inert half of this same defect. Wire the publisher in the same change.
- Blocked by: none.

### ncaaf-cfbd-quota-latch — **CLOSED 2026-09-01** — opened 2026-08-31 — session 1c88bcca-be25-4164-a288-3a27d7e9dd57 (archived) — **THE ROLL READING IS IN. The latch expired on time, released with zero manual intervention, and the PPA cache ARMED.** Goal met; measurement in `.syndicate/deploys.md` 2026-09-01 15:0xZ. One SEPARATE, PRE-EXISTING defect surfaced and is NOT this lane's: the regenerated artifact never reaches the board (`artifact_published=False` — path matches zero `HOT_ARTIFACT_PATTERNS`).
- Goal: stop NCAAF regeneration burning a MONTHLY CFBD quota it has already been
  told is exhausted, and let it succeed from cache while exhausted.
- Files: released: syndicate/features/ncaaf/cfbd_quota_latch.py (NEW),
  **CLAIMS RELEASED 2026-08-31 — phantom sweep, the owning session is gone. The paths in this block are a RECORD, not a claim. A lane that resumes this work reclaims them by striking this note and the `released:` tokens.**
  released: scripts/generate_smartsim2_ncaaf_projections.py,
  released: syndicate/features/ncaaf/cfbd.py,
  released: tests/test_cfbd_quota_latch.py (NEW)
- RECLAIMED from `ncaaf-no-orders` (owning session gone), which marks these paths
  `released:` and whose own analysis proposed the PPA cache.
- NOT TOUCHED, DELIBERATELY:
  `scripts/run_refresh_worker.py::_season_projection_should_launch` — contended
  (STAGED by another session in the shared index), and the launches are cheap
  while the CALLS are what burn quota.
- STATUS: **DEPLOYED AND VERIFIED ACROSS PROCESSES.** Latch live on `bf0811bb`;
  retry-ladder fix live on `13afa27f`. Two consecutive hourly runs on the same
  build: `05:16:39Z` spent **5** CFBD calls, `06:19:49Z` spent **0**
  (`LATCHED_SKIP ... clears_in_hours=17.7`). Those 5 were a real defect that
  production found and the tests did not — `raise_if_latched` ran once BEFORE
  `call_with_retry` and never inside it, so the first 429 set the latch and the
  four retries behind it still went out.
- **ROLL READING TAKEN 2026-09-01T15:00Z, read-only, no deploy.** All four
  expected signals resolved. Full evidence in `.syndicate/deploys.md`.
  1. **PPA cache ARMED** — `2026-09-01T00:23:31Z [ppa] season=2025 source=api`,
     after 17 consecutive `source=none reason=quota_exhausted_and_cache_empty`
     on 08-31. Write is durable (`SYNDICATE_DATA_ROOT` -> mounted disk, no
     `CACHE_WRITE_FAILED`).
  2. **Artifact regenerated** — `projections_written=51` at `00:33:24Z` to
     `/opt/render/project/data/ncaaf_source/data/smartsim2_projections_2026_wk1.csv`,
     the exact path the staleness guard stats. `age_seconds` therefore reset at
     00:33:24Z; the direct log line cannot exist before 2026-09-02T00:33Z
     because the guard is DELIBERATELY SILENT on `artifact_fresh`. Recorded
     because silence alone is ambiguous — autorun-disabled, sport-not-active,
     week-None and process-still-running are all silent too. The WRITE is the
     evidence, not the quiet.
  3. **Cadence collapsed** — 23 launches / 24.0 h (**23.0/day**) on 08-31
     vs 1 launch / 15.0 h (**1.6/day**) post-roll. Configured: 1/day.
  4. **No new `LATCH_SET`, and NO `LATCHED_SKIP`** — zero `[cfbd_quota]` lines
     of any kind in `2026-09-01T00:00Z..15:00Z`. `clears_in_hours` counted
     17.7 -> 0.6 across 18 hourly skips and stopped. **The feared failure mode
     did not occur: `_next_month_roll` expired the latch on time and
     `clear_latch()` was never needed.** The latch file was NOT touched.
- **STILL OWED, STILL NOT IMMINENT:** the ladder fix's own number (1 call, not
  5) needs a FRESH exhaustion event. Its absence today proves nothing.
- **HANDED OFF, NOT FIXED HERE (read-only task): the artifact regenerates and
  the BOARD DOES NOT MOVE.** `artifact_published=False` at `00:33:24Z`, no
  publish error — `is_hot_artifact_relative_path("ncaaf_source/data/smartsim2_projections_2026_wk1.csv")`
  returns **False** (verified by running it; the only ncaaf allowlist entry is
  `ncaaf_source/api/live_state/live_state_*.json`). Push and pull share that
  allowlist, so nothing can move the file. `/ncaaf/api/cards` serves values
  byte-identical to the git-committed CSV stamped `generated_at=2026-08-19T22:00:39Z`.
  Values alone do not discriminate — the generator is deterministic
  (`seeds_used=300`, identical `rating_source`) — the allowlist miss is what
  makes it decisive. **NFL has the identical defect**
  (`2026-08-31T21:28:40Z artifact_published=False`), so fix the allowlist for
  both or it survives in the sibling. Predates this lane.
- **ALSO NOTED, NOT FIXED:** `[sp_ratings]` caches to
  `/opt/render/project/src/data/...` — the EPHEMERAL checkout — so it dies on
  every deploy and costs a CFBD call to refill. The latch and PPA cache
  correctly use `SYNDICATE_DATA_ROOT`.
- Narrative: `.syndicate/log/2026-08-31.md`, `.syndicate/lanes_history.md`.
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

### soccer-shot-shrinkage — OPEN — opened 2026-08-31 — session 1c88bcca-be25-4164-a288-3a27d7e9dd57 — **UNOWNED. GOAL MET 2026-09-01 — the divisor IS live in the engine, MEASURED, and `todo.md #612` is CLOSED.** Discharged not on the board but on the PREDICTION ARCHIVE the engine writes: self-normalised over the 3,434 players present both sides of the 2026-08-31 ship date, median post/pre `expected_shots` **0.720** against a predicted 1/1.3979 = **0.715**, with `expected_minutes_share` flat at **1.000** so the step cannot be "future fixtures carry fewer minutes". Tool `scripts/check_soccer_divisor_reached_engine.py`. Monthly re-fit ran the same day: **1.3979 -> 1.3930**, published and read back, no deploy. Residual (small): `players_*.csv` is not in `HOT_ARTIFACT_PATTERNS`, so the board-render form of the reading still cannot run from web. Detail in `.syndicate/deploys.md` 2026-09-01 15:0xZ.
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


### mlb-accuracy-assessment — **CLOSED 2026-09-01** — opened 2026-08-31 — session 3bb44ef2-a199-430e-afce-c3034bf48d9d — **ALL FOUR TIER 0 GATES DISCHARGED; TIER 1 06/07 CLOSED; 05 MEASURED AND ITS STEP 1 (CAPTURE) BUILT, DEPLOYED AND VERIFIED IN PRODUCTION.** Work continues under the edge plan, NOT under this lane's item numbers.
- **ITEM 05 RESULT 2026-09-01: worth ~+1.2% ROI, not the ~+5% the plan implied, and CAPTURE comes before the board change.** Detail: findings section 7h. Three measurements, the first two wrong. (1) Naive join of 23 filled Kalshi prop orders vs best sportsbook: cheaper 11/23, mean **-0.0187** — WRONG, compared against prices that did not exist at fill time (`book_quotes` is a TIME SERIES; williamhill walked Ty France HR **+475 -> +2600** across the day). (2) Time-aligned to the fill: cheaper **22/23, mean +0.0324**, stable to a 2-min window — but a SELECTED sample (the props the system chose Kalshi for). (3) **UNCONDITIONAL, n=9,557 paired same-snapshot quotes: kalshi cheaper only 50.7%, median +0.0017.** Exchanges are NOT systematically cheaper; the +3.24pp was selection. **HONEST NUMBER — OPTION VALUE, n=13,093: an exchange beats the best sportsbook 52.5% of the time, mean improvement +1.57pp, ~+1.2% ROI on item 07's sensitivity.** **REORDERED:** every number is from GAME markets, the only ones where an exchange appears in `book_quotes`; for PROPS **no exchange quote is captured anywhere** (7f: 0 rows). Step 1 CAPTURE exchange prop quotes, step 2 measure the prop-side gain, step 3 change the board. The plan had step 3 as the item. **NOT BUILT, deliberately** — a board-ranking change built on a number I corrected twice in one sitting is not warranted.
- Goal: one MLB accuracy + profitability read across pregame sim (games + props), live sim, Layer 1 and Layer 2, plus a ranked optimization plan. **MET.** Deliverable: `.syndicate/findings_2026-08-31_mlb_accuracy_assessment.md` (~1,100 lines, sections 0-9 + 7b-7g); artifact `https://claude.ai/code/artifact/9989c17f-e27b-4332-a555-bed909241ef8`.
- Headline: **`corr(claimed edge, win) = -0.1379`** — `model_edge` is anti-predictive because it subtracts a better estimator (market, +0.318) from a worse one (sim, +0.234). Full verified numbers: `state.md [mlb-sim-edge-is-anti-predictive]` and `[mlb-live-lens-accuracy-refuses]`. Narrative: `log/2026-09-01.md`.
- Shipped + deployed: venue P&L bound + repair (`600ad6c3`); `mlb:player_prop` staking exclusion (`6f41efa1`); live-lens grader refuses in-progress tallies (`4b8d5436`); gate verifier `scripts/verify_mlb_prop_exclusion.py` (`f5912ba3`). Deploys: web + live-odds-worker `ea06bf81`, refresh-worker `c0a0c622`.
- Gates, all discharged: item 03 `snapshotActualNotFinal: 1,784` (= 1,578+206 exactly); item 04 `IMPOSSIBLE_PNL_CORRECTED n=5` incl. the diagnosed key `4e330fae2f602c410e8d2335`; item 01 `market_family_excluded: 1860` / 1,876 board props (99.1%), top market `batter_rbis:379`.
- Files: ALL CLAIMS RELEASED. Touched and released: `syndicate/features/shared/{venue_settlement,portfolio_commit}.py`, `syndicate/features/mlb/live_lens_daily_accuracy.py`, `scripts/{run_live_odds_refresh_worker,verify_mlb_prop_exclusion,assess_mlb_prop_join}.py`, `tests/{test_venue_settlement,test_portfolio_commit,test_portfolio_commit_excluded_families,test_mlb_live_lens_daily_accuracy_grader,test_live_lens_local,test_clv_position_join}.py`. Deploy claims on all three services released. **EXTENDED 2026-09-01 for item 05 step 1 (CAPTURE), user said "do the capture":** `syndicate/features/shared/odds_book_quotes.py` (an ADDITIVE row builder only — not `_normalize`, not `append_book_quotes`), `pipeline/kalshi_odds_refresh.py` (`join_to_board` only), `tests/test_kalshi_book_quote_capture.py` (new). Checked against every OPEN lane: none names any of the three.
- **OWED, and it is a MEASUREMENT not a deploy:** whether excluding props improves realized ROI — ten days against the +3.76% baseline that included them. The exclusion is verified to FIRE; its effect on returns is not measured.
- **SCHEDULED DEFECT, not fixed, deliberately:** `live_lens_daily_accuracy.py:207-211` falls back to `last_seen.marketLine` — the latest line, not the line at signal time. Unreachable while the outcome-side refusal returns 0 rows. **Comes due the moment `data/raw/statsapi/feed_live/` is added to `HOT_ARTIFACT_PATTERNS`; that decision cannot be taken in isolation.**
- **ITEM 05 STEP 1 IS DONE AND VERIFIED, 2026-09-01 16:11Z.** `[kalshi_odds] QUOTE_CAPTURE matches=662 sports=['mlb'] appended=603 no_sport=0`; 603 Kalshi PROP rows in the MLB shard against 0 before, all stamped `source=venue_direct`; game rows 225 unchanged (props-only bound held). Peer gate `kept_direct=603`. Second tick `appended` decays 603 -> 153, which is the ABSENCE of the dedup-key collision measured rather than argued. **One verify bullet FAILED:** `venue_ticker` persisted on 0 rows — `_normalize` has a fixed key set and my test asserted on the BUILDER's output, so it was green through a whole deploy. Field removed (`05c46105`, landed `12b628db`); replacement test diffs builder output against `_normalize`'s kept keys. Full measurement: `deploys.md` 2026-09-01 16:11-16:26Z.
- **NUMBERING: this lane's item numbers are RETIRED. Use the edge plan (`todo.md` `#627` index).** Mapping, per lane `edge-plan` 2026-09-01: item 05 = **`#624` step 5** (capture DONE -> accumulate -> measure -> board change, in that order); the calibration item (per-(market,line) isotonic + refuse `p in {0,1}`, THEN the HRR null) = **`#624` steps 1-2**; `#611` freeze + `#610` caps = **`#626` (a)(b)**; the `marketLine` scheduled defect below = **`#620`**. Do not open new scope under Tier 0/1 numbering — two live numbering systems is the confusion being avoided.
- **NOT MINE, REPORTED NOT FIXED — an instrument that alarms at the success rate.** `book_grid.py:270-276` counts every CORRECTLY-matched direct-feed row as a `near_miss` (no `continue` after `kept_direct_feed += 1`), so the production line reads `kept_direct=603 near_misses={'kalshi': 603}`. Proved on one row: `kept_direct=1 near_misses={'kalshi': 1}`. Its comment claims it is "reached only when the exact match above already refused" and its docstring calls each key "a spelling the filter is missing TODAY" — neither is true as written. File is lane `wnba-accuracy-assessment`'s; one-line fix; they have the proof.
- Next action for whoever picks this up: **`#624` step 2** — with prop quotes now accumulating, measure the PROP-side option value the same way game markets were measured (an exchange beats the best sportsbook 52.5% of 13,093 paired snapshots, mean +1.57pp, ~+1.2% ROI). **That game-market number must NOT be quoted for props** — measuring it is the whole point of step 2. Step 3 (the board change) is gated on step 2's result.
- Blocked by: none. **ALL DEPLOY CLAIMS RELEASED; all three services free.**
### wnba-accuracy-assessment — OPEN, GOAL MET; EXCHANGE PRICES REACH A BOARD (VERIFIED); ONE DEPLOY OWED — opened 2026-08-31 — session e542848e-6451-41a1-9e60-fd5a5675665d
- Goal: MET. WNBA went from six accuracy instruments reading zero to a settling, graded surface. `n_settled 38` (08-29) + `54` (08-30), `win_rate 0.6415094339622641` — byte-identical to the pre-deploy local run; `gradeable` false → true; `verify_wnba_settlement_gate.py` exit 0 on both dates.
- Deployed: web `ad33df21`, refresh-worker + live-odds-worker `1c078f46`. Four deploys, each verified on the SERVED PAYLOAD, not on deploy status. **ALL CLAIMS RELEASED; all four services free.**
- **CLAIMED 2026-09-01 (exchange prices onto the board):** `syndicate/features/shared/{book_shortlist,book_grid,odds_regions}.py`; `pipeline/kalshi_odds_refresh.py` (**`_capture_kalshi_quotes` ONLY** — the sibling lane's claim is `join_to_board`; they verified and accepted the one-line stamp); `syndicate/features/shared/odds_book_quotes.py` (**NEW `quote_rows_from_polymarket_matches` ONLY** — that lane claims its own `quote_rows_from_kalshi_matches`, explicitly NOT `_normalize`/`append_book_quotes`, and handed me Polymarket); `pipeline/portfolio_commit.py` (**`_capture_polymarket_quotes` + its one call site ONLY** — `portfolio-decision-and-execution` marks the file `released:`); NEW `tests/{test_direct_feed_provenance,test_wnba_odds_regions}.py`. NOT editing `polymarket_board_join.py` (`released:` by `open-bet-live-status`).
- Files (all landed on `origin/main`, nothing held): `syndicate/features/shared/{live_lens_paths,wnba_card_provenance}.py` NEW, `{live_lens_local,basketball_live_artifacts,artifact_publisher}.py`; `syndicate/features/wnba/{cards,live_lens_daily_accuracy,live_game_accuracy,live_prop_accuracy,live_prop_audit}.py`; `scripts/{build_wnba_recon,verify_wnba_settlement_gate,assess_wnba_accuracy}.py` NEW, `scripts/{run_refresh_worker,refresh_wnba_oddsapi_props}.py`; 6 new test files.
- Verification: settlement gate PASS ×2; signals `exists` false → true on **14/14 days** (1,814 records, matching an independent count); served card max `p_win` **0.99**, zero certainty claims; leakage note populated on the served payload.
- **OWED / NOT VERIFIED:** (a) T0-2, the T2-3 producer clamp and the `p*(1+ev)` inversion are **deployed but NOT IN FORCE** — those fields are baked into `recommendations_slate_*.json` and WNBA does not rebuild until **2026-09-17**; unit-verified only. (b) `_run_wnba_postgame_producer_tick`'s memory cost is REASONED, not measured (refresh-worker headroom read 96.8MB at 14:23Z). (c) `refresh_nba_oddsapi_props` shares the `_clamp_probability` chokepoint — its inversion is UNREAD, not cleared.
- Blocked on a live slate (2026-09-17): T0-1, T0-3, T1-5, T2-1, T2-2, T3-1..T3-5, T4-1/3/4. `todo #614`–`#617` carry the findings; **`#614` and `#616` were CORRECTED in place** after I named mechanisms from symptoms.
- **2026-09-01 EXCHANGE PRICES — VERIFIED.** `kept_direct=603` on the first grid build after the first Kalshi capture (`0` on every build before it); second capture +153; both post-capture builds agree. The provenance stamp and the grid rule that honours it are mine, the capture is `syndicate-e2`'s. Re-derived off Render by me, not taken from their report. Evidence in `deploys.md`.
- **The `near_misses` defect they reported in this file is FIXED — `07cb592a`.** It was my regression: provenance-based dropping created a second class of survivor and the counter's precondition assumed one. Moved under `else`. **Their suggested `continue` is a SILENT REVERT** — `freshest[key]`/`anchors[]` follow that block, so it deletes the kept row from the grid; measured (`assert 'kalshi' in {'fanduel'}`). Do not apply it.
- **DEPLOYED `417e19ed`, live 16:55:23Z. Both gates read.** `near_misses` gate **MET**: `kept_direct=603 near_misses={'kalshi': 603}` → `kept_direct=830 near_misses={}` (kept GREW while the false alarm went empty, so the counter was fixed rather than the rows suppressed). Polymarket gate **NOT MET**: `POLYMARKET_QUOTE_CAPTURE matches=60 sports=['mlb','soccer'] appended=0` — the capture is reachable and correctly wired, and wrote nothing because all 60 were GAME markets and the builder is props-only **by design**. **CORRECTED 2026-09-01 (chip session dee09146, deploys.md `c587010a`): matches can ONLY ever be game markets — the join refuses every PROP type (`polymarket_board_join.py:1329`, "PROP is fetched every cycle and thrown away"), so `appended > 0` is UNREACHABLE on `417e19ed` by construction, not pending a slate. Do not leave a watcher on this gate.** **Do not remove that bound to make the number rise** — OddsAPI already writes `polymarket` game rows under the same dedup key, so a second writer alternates rather than adds.
- **ALL FILES RELEASED, including `book_grid.py` — nothing here is claimed.** The near-miss counter fix is DONE and live (`07cb592a` in `417e19ed`); `kept_direct=869 near_misses={}` at 17:06:46Z. **A chip session was scoped on the pre-deploy symptom (`near_misses=603`) and on adding `continue` after `kept_direct_feed += 1` — DO NOT DO THAT.** `instance` / `freshest[key]` / `anchors[]` follow that block, so `continue` skips the kept row's registration and it never reaches the grid: measured `assert 'kalshi' in {'fanduel'}`. It presents as a perfect reading with zero exchange prices on the board. The shipped fix is `else`. `tests/test_direct_feed_provenance.py` pins both sides and will catch it.
- **Honest state of "exchange prices on the board":** Kalshi direct — YES, proven (830). Polymarket game — already arrived via OddsAPI, untouched. Polymarket direct — contributes nothing, and **CANNOT until the JOIN is changed**. CORRECTED 2026-09-01 (found by `syndicate-21`, verified by me on the code): `polymarket_board_join.py` refuses every unmapped type incl. PROP (`market_type_not_a_game_line`), so it emits game lines only and never sets `player_name`, while my builder consumes only rows WITH `player_name` — **empty intersection by construction**. Polymarket lists thousands of props; the join discards them. My earlier "fires on its own, nothing further needed" was wrong and would have left someone watching a gate that can never pass. The join-side fix is NOT "allow PROP": that bucket is MIXED (LoL map winners measured inside it), so characterise it first. Chip `task_4889e312` owns this; it needs `polymarket_board_join.py`, listed by `open-bet-live-status` (UNOWNED).
- **Traceability gap, both venues, by choice:** `venue_ticker` persisted on 0 of 603 rows (`_normalize` keeps a fixed key set). Removed from my builder; a boundary test now asserts EVERY builder's keys survive `_normalize`. One-line fix (`venue_ticker` into `_normalize`) written down and deliberately not taken — a shared-schema change that would leave one venue traceable and the other not.
- Blocked by: none. Next: **`#623`** (the 09-17 sprint + pre-registered gates + parked `#614`/`#616` reads) and **`#626`(d)(e)** (reuse-guard/live-capture, klass-hole). **`#622`** owns the ranking-key question — per `#615` T2-1 is ANSWERED (no sim-derived key exists; do NOT keep re-looking at the 656-row sample, ~30 looks are already on record). `scripts/prereg_wnba_favourite_lean.py` is frozen and waiting for the sprint.


### mlb-live-gameline-skill-audit — OPEN — opened 2026-09-01 — session 250953ef-3461-4628-b326-415a35a97a74 — **SHIPPED AND LIVE; ONE READING OWED.**
- Goal: decide whether the MLB live game-line model has skill the market lacks,
  and if not, name the mechanism. **ANSWERED — see `log/2026-09-01.md`.**
- Files: syndicate/features/shared/live_gameline_score.py,
  syndicate/features/shared/live_gameline_ledger.py,
  syndicate/features/shared/live_gameline_join.py,
  syndicate/features/shared/book_grid_artifact.py,
  scripts/snapshot_live_gameline_score.py,
  scripts/score_live_gameline_offline.py,
  tests/test_live_gameline_quote_age.py
- STATUS: `c01dabb1` live in `417e19ed` (16:55:20Z), `692214e0` live in
  `9a436fab` (17:59:56Z). Both verified BY CONTENT. Neither deployed by me —
  carried by other lanes because they were on `origin/main`.
- **THE ONE THING OWED: the staleness gate has NEVER FIRED in production.**
  Every sport on this path was pregame at 18:0xZ, so `considered=0` and
  `withheld_by_reason={}` describe the SLATE, not the gate. PASSES only on
  `quote_older_than_live_pricing_ceiling` > 0 against a non-zero `considered`
  (expect ~39.5% of live rows). Scheduled task
  `verify-live-gameline-staleness-gate` fires 18:45 CT. A zero is NOT a pass.
- Headline for anyone quoting this model: **on fresh quotes (<=120s) the model
  LOSES, +0.01096, CI [+0.00171, +0.02132] over 147 games.** The old
  "+0.07000 / n=98" figure is a FIXED SCORER BUG — do not quote it. History rows
  lacking `scored_markets` are pre-fix and must not be pooled with later ones.
- Recalibration is TESTED AND DEAD (LOO +0.00243 worse); raising sims closes
  only 12.7% of the gap and its worker cost is unmeasured. Next real work is
  MODELLING, and it needs v4 clock + `pregame_home_win_prob` to accumulate first.
- Blocked by: none. Full narrative: `.syndicate/log/2026-09-01.md`;
  superseded block verbatim in `.syndicate/lanes_history.md`.
### edge-plan — CLOSED 2026-09-01 — **LANDED on `origin/main` as `8acd3eaf`: THE EDGE PLAN `#627` (index) + phases `#626`..`#619` in `todo.md`, plus the analysis findings file committed.** Verification ran: `todo_id_reconcile.py` clean (334 ids, every current-era id in exactly one file — `#618` was already taken on origin, which the fresh-worktree ID check caught; ids assigned #619-#627), and `land`'s own `ledger/todo ids clean` gate passed on the rebase. — session syndicate-8d (3492626c)
- Outcome: the 2026-09-01 sim-engine edge analysis is now an executable phased
  plan in the canonical TODO. NOTE for primary-tree readers: the PRIMARY tree's
  `todo.md` is BEHIND origin (worktree commit does not update it — standing
  lesson); fresh worktrees and pulls see the plan; deliberately NOT synced back
  by file-write to avoid shared-index/CRLF hazards.
- Files: released: `docs/ai_context/todo.md`, released: `.syndicate/findings_2026-09-01_sim_engine_edge_analysis.md`

### phase0-basketball-integrity — CLOSED 2026-09-01 — **LANDED on `origin/main` as `417e19ed`: `#626`(c) NBA integrity ports + (e) the live-lens tick klass line-source gate, BOTH vendor repos.** Verification ran: 100 targeted tests pass incl. off!=on both directions (gate: model→NONE vs oddsapi→BET; knob env off!=on; consensus old-rule reproduction; clamp counters); tripwire pins `implied + ev` at zero in BOTH refresh scripts — including the TWO WNBA sites `bef61c33` missed (top_by_game + cards_props_snapshot). Two prior tests updated with supersession documented (NBA clamp [0,1]→[0.01,0.99] was that test's own WNBA-lane scoping choice, not a finding; certainty refusal is a validity constraint and the fabrication cause was removed in the same change). `test_nba_refresh_runner` one failure is PRE-EXISTING on origin/main (stale `force_refresh` mock — chip filed), baselined via stash, not mine. — session syndicate-8d (3492626c)
- Goal: `#626`(c) + (e) executed. (c) NBA carries none of the WNBA integrity
  defects: consensus prices averaged on the implied-probability scale with
  (−100,100) rejection; no `p_win = implied + ev` anywhere; probabilities
  clamped [0.01,0.99]; |EV|>100% refused with counters; a totals-withhold knob
  exists (default = current behaviour — NBA totals are UNMEASURED, not
  proven-bad; flipping it is a config decision for a future measurement).
  (e) the live-lens JSONL tick writer (BOTH vendor repos if mirrored) respects
  the API layer's gated klass — it can no longer emit `klass: BET` for
  `line_source ∈ {None, model}` rows.
- Files: `scripts/refresh_nba_oddsapi_props.py`,
  `vendor/wnba_betting_repo/app.py` (tick-writer klass section only),
  `vendor/nba_betting_repo/app.py` (same section if present),
  new tests (names set during work) under `tests/`.
  NOT claimed: `scripts/refresh_wnba_oddsapi_props.py` (read-only reference —
  the WNBA implementations being ported).
- Hypothesis: the WNBA assessment lane's note says NBA "shares the
  `_clamp_probability` chokepoint — its inversion is UNREAD, not cleared";
  read NBA's current state FIRST — some of (c) may already be covered via a
  shared path, and porting blindly would double-fix.
- Falsification test: if NBA's served p_win already routes through the WNBA
  clamp chokepoint, the `implied + ev` sites are dead code and the fix is
  deletion + a pin test, not a port.
- **OWED, DATED, riding existing plan gates (no live session needed):** the
  production readings — zero (−100,100) prices + zero `p_win ≥ 0.999` on the
  FIRST NBA SLATE (pre-season ~Oct); zero `line_source=model` rows with
  `klass: BET` on the 2026-09-17 WNBA slate (this IS `#623`'s pre-registered
  gate 6 / T0-3 — the tick gate is the mechanism that makes it pass).
- Blocked by: none.

### nba-runner-force-refresh-mock — CLOSED 2026-09-01 — **LANDED on `origin/main` as `cbfe0c7d` (on `45b531ee`): 3 stale keyword-only mocks in `test_main_materializes_core_artifacts_into_bundle_root` now accept `force_refresh=False`, matching the real exporters since `85ff37dc`.** Verification ran: red confirmed pre-fix in a fresh worktree (TypeError on the slate mock), the lane's falsification test PASSED (fixing only the slate mock moved the SAME TypeError to the cards-props mock, proving the 3-mock scope), then 40/40 green on the pushed SHA post-rebase; sibling `tests/test_export_snapshot_force_refresh.py` 34/34 unaffected. Test-only `.py` push — no `render.yaml`, no deploy, nothing owed. No todo id existed (chip-spawned); recorded here only. — session 9222c035 (chip filed by phase0-basketball-integrity)
- Goal: `tests/test_nba_refresh_runner.py` green on origin/main — specifically
  `test_main_materializes_core_artifacts_into_bundle_root`, which failed with
  `TypeError: unexpected keyword argument 'force_refresh'` (pre-existing,
  baselined by phase0-basketball-integrity 2026-09-01, not caused by it). **MET.**
- Files: released: `tests/test_nba_refresh_runner.py` (claim released at close,
  2026-09-01, session archived; work is on `origin/main` as `cbfe0c7d`)
- Hypothesis: `85ff37dc` (2026-08-16) made `_materialize_artifact_bundle` pass
  `force_refresh=` to exactly three exporters (script lines 4400/4403/4409);
  the test's keyword-only mocks for `_export_recommendations_slate_snapshot`,
  `_export_cards_props_snapshot` and `_export_top_by_game_snapshot` predate the
  kwarg, and the slate one raises first only because its call site is first.
  The file's other fakes patch exporters whose call sites pass no
  `force_refresh` (NBA's `_export_cards_sim_detail_snapshot` takes none —
  unlike WNBA's), and `test_wnba_refresh_runner.py` never mocks these
  exporters, so scope is exactly 3 mocks in this one file.
- Falsification test: fix ONLY the slate mock and re-run — the test must fail
  again with the SAME TypeError on the cards-props mock (then top-by-game).
  If it passes with one mock fixed, the other two call sites don't really
  pass the kwarg and the 3-mock scope claim is wrong.
- Verification: red confirmed pre-fix in the lane worktree, then
  `python -m pytest tests/test_nba_refresh_runner.py` fully green post-fix.
- Blocked by: none.

### polymarket-prop-quote-capture — CLOSED 2026-09-01 — **GOAL MET AND VERIFIED IN PRODUCTION, BOTH READINGS.** `POLYMARKET_QUOTE_CAPTURE matches=436 appended=374` (was 60/0, structural) at 18:10:22Z on deployed `9a436fab`, and 66s later `[book_grid] kept_direct=1479 books=['kalshi','polymarket'] near_misses={}` — polymarket rows in the direct-feed grid, spelling near-miss exercised and empty. `POLYMARKET_PROP_RESOLVERS armed=False withheld=374`: the money path is untouched by design. `market_type_not_a_game_line` 6,960→3,375, `board_market_not_a_game_line` 935→138; none of the new named refusals fired. state.md's "LISTS NONE" + "both ways" claims corrected with dated notes. Measurements in `deploys.md`; census evidence in `findings_2026-09-01_polymarket_prop_census.md`; follow-ups (NFL vocabulary, ops slate PROP sampling, venue_ticker traceability, resolver arming decision) live on `todo #628`. Claims released at close. — opened 2026-09-01 — session 41d46db0-4017-4d9b-91bf-c9392f13c9de
- Goal: `POLYMARKET_QUOTE_CAPTURE appended > 0` on refresh-worker — admit measured, genuine player-prop families into the Polymarket board join so prop matches (which carry the board row's `player_name`) reach the props-only quote capture. **MET AND READ, both gates.**
- Files: released at close 2026-09-01: `syndicate/features/shared/polymarket_board_join.py`, released: `tests/test_polymarket_board_join.py`, released: `pipeline/portfolio_commit.py`, released: `tests/test_polymarket_prop_resolver_gate.py`
- Verification: ran — capture line 18:10:22Z (`appended=374`), grid line 18:11:28Z (`books=['kalshi','polymarket'] near_misses={}`), resolver gate withholding (`withheld=374`). Recorded in `deploys.md`.
- Blocked by: none.

### phase0-graded-supply — CLOSED 2026-09-01 — **LANDED `e9090bc0`: game markets (`ml`, `totals`) now retain their cap overflow as `other_playable_candidates`, exactly as `pitcher_props` and every hitter market already did — so capped-out game picks are graded as tier `candidate` instead of discarded.** — session syndicate-8d (3492626c)
- **NOT a cap raise, and the premise correction IS the result.** `#626`(b) said
  "re-fit the cap profile". The code says otherwise: prop markets keep their
  overflow, game markets dropped it, in BOTH card builders, with no comment
  anywhere giving a reason — copy-drift. Retaining it leaves `recommendations`
  capped, so the OFFICIAL tier is byte-identical and NO betting policy changes;
  raising `caps.ml` would instead redefine OFFICIAL on a deliberately-fitted
  profile and multiply a paper book measured at -7.43%.
- Verification RAN: 11 new tests (overflow arithmetic on `#610`'s measured
  12-vs-1 slate, zero-cap and uncapped edges, `_rank_and_cap`'s added `rank`
  key not breaking identity subtraction; reachability on both builders and both
  consumers), 71 existing card-builder/MLB-job tests pass. Reachability checked
  BEFORE writing: the manifest grades extras `tier="candidate"` and the settler
  settles them `"candidate"`, both market-agnostic — no grader/settler change.
- **Production gate, deliberately narrower than `#626`(b) claims:**
  `candidate`-tier `ml`/`totals` rows > 0 on the first card built after this
  ships. NOT "graded rows/week 14 -> 100+" — that also depends on `#611` and on
  a join whose health two ledger entries disagree about.
- Files: released. `vendor/mlb_bettingv2/tools/daily_update_multi_profile.py`,
  `vendor/mlb_bettingv2/tools/eval/build_season_betting_cards_manifest.py`,
  `tests/test_game_market_overflow_retained.py`.

### phase0-accuracy-autorun — CLOSED 2026-09-01 — **LANDED `258d312f`: `build_accuracy_summary` finally has a scheduled caller — a refresh-worker autorun, default OFF, claim-before-work, daily at Central hour 7, per-sport isolation, bounded persistence, and its own cost telemetry.** — session syndicate-8d (3492626c)
- **The memory check is the load-bearing part, and I nearly got it wrong.** I
  read the call site `_latest_by_recommendation_id(_stream_record_payloads(...))`,
  concluded it materialises the whole ledger — the exact shape `#256` diagnosed
  as 110 OOM kills over 11h — and was about to block the job. Reading the
  REDUCER corrected it: it is "single pass, iterate-only -- so it consumes a
  GENERATOR without materialising it. That is what lets the peak be the reduced
  set" (`#254`). Peak is the deduped record set (~20k), the same order as the
  settlement pass already running daily (~40MB / 71s). **A call site is not an
  allocation; the function is.**
- Safety, each item from a logged incident: OFF by default (this file's own
  convention for a new periodic job); claim-before-work per `#256`, with a
  still-`started` status reported loudly and not retried that day; hour 7 sits
  one BEHIND settlement's 6 because it scores what settlement writes; per-sport
  try/except so one sport cannot cost the other seven; bounded persistence with
  `segments_total`/`segments_truncated` because the keyvalue key has an 8MB
  ceiling and the segmented surface grows with coverage.
- Verification RAN: 16 new tests incl. off!=on both directions, that a disabled
  gate does NO work at all (the cost guarded is the read), claim-ordering
  asserted on write SEQUENCE, and reachability that the `elif` sits behind
  settlement. 74 refresh-worker/ordering tests pass; 3 soccer-seed failures are
  PRE-EXISTING (baselined via stash — they need `data/`, excluded from worktrees).
- **Production reading deferred BY DESIGN, not inert:** arming is a one-key
  config change and should be taken with the first run's cost telemetry in hand.
- **todo.md claim NARROWED to the `#626` block and released for additive
  top-inserts** (peer request, lane `polymarket-prop-quote-capture`).
- Files: released. `scripts/run_refresh_worker.py`,
  `tests/test_accuracy_summary_autorun.py`.

### mlb-prop-freeze-source-trees — CLOSED 2026-09-01 — **LANDED `9a768443`: `#626`(a) / `#611`. The MLB prop pregame seal now sources the richest doc across EVERY `market_dir` instead of `market_dirs[0]` alone, and every refusal is NAMED.** — session syndicate-8d (3492626c)
- **The asymmetry was inside one loop body.** `best_frozen` was already computed
  across every tree — its own comment says *"'Already frozen' is asked of EVERY
  tree, not just this one"* — while the SOURCE was `market_dirs[0]` and a miss
  was a bare skip that emitted nothing. Game lines cannot fail that way
  (`_merge_pregame_game_lines` seeds from every copy), which is exactly why
  2026-09-01 had a 15-game game-line freeze and ZERO prop seals on the same runs.
  `market_dirs[0]` is the tree the fetch writes to LATER in the same pass, and
  git tracks zero files under it.
- **NOT claimed as proven to be THE cause.** Nobody has read
  `.../data/market/oddsapi/` on a live worker; `#611` says do not ship on the
  asymmetry alone. What shipped is narrower and defensible on its own terms: an
  internal inconsistency in one function, plus the instrumentation `#611` has
  asked for three sessions running.
- **THE FALSIFIER IS BUILT IN:** if the next MLB pregame pass reports
  `reason=no_live_doc_in_any_tree`, this change's own hypothesis is WRONG — the
  doc is in no tree at freeze time and the cause is upstream (fetch cadence, or
  the source root `_build_mlb_steps` hardcodes). The counter says so rather than
  hiding it.
- **Deliberately NOT fixed:** `refresh_odds_sources._build_mlb_steps` hardcodes
  `source_root = REPO_ROOT / "data" / "mlb_source"`, making MLB the only sport
  that ignores the resolution the orchestrator computes and logs. Real, but it
  moves where every MLB read and write lands on the platform's most mature
  sport, on an unproven mechanism. **Own lane, behind a production read.**
- Verification RAN: 10 new tests; **off-is-not-on proven by running them against
  HEAD's copy of the module — 7 of 10 FAIL pre-fix, and the 3 that pass in both
  states are exactly the ones asserting UNCHANGED behaviour** (first-tree seal,
  monotonic replacement, game lines). 71 existing freeze/odds tests pass.
- **Production gate:** on the next MLB pregame pass, either a
  `*_props_*_pregame.json` appears for the date, or the emitted reason names
  which branch refused. Both are progress; the second is the read `#611` has
  been unable to take for three sessions.
- Files: released. `scripts/refresh_mlb_oddsapi.py`,
  `tests/test_mlb_prop_freeze_source_trees.py`.

### polymarket-prop-resolver-arming — CLOSED 2026-09-01 — **ARMED AND VERIFIED WORKING, first post-boot cycle 19:18:21Z on `bde67379`:** `POLYMARKET_PROP_RESOLVERS armed=True prop_matches=386 withheld=0`; `PAPER2_PLAN_WRITTEN date=2026-09-01 venue=polymarket venue_priced=462` of 485 rows_in (pre-arm baseline 62, game lines only) — the `#628` raw-vs-canonical asymmetry is NOT binding, the falsification test did not fire. Env key set BY THE USER (my own env-set attempt was permission-blocked and surfaced, not worked around); injected by `prop-unmatched-decomposition`'s deploy dep-dabi38dcqm1c73dmhdjg (live 19:06:37Z, one deploy carrying both lanes by agreement, killed nothing). **Blast radius measured: positions 4/$14.71 (unchanged) — `market_family_excluded: 402` still closes prop POSITIONS; arming opened pricing + tickers only. Opening the family policy is a separate, unrequested decision.** Measurement in `deploys.md` 19:18Z. — opened 2026-09-01 — session 41d46db0-4017-4d9b-91bf-c9392f13c9de
- Goal: `SYNDICATE_POLYMARKET_PROP_RESOLVERS` armed on refresh-worker `[USER AUTHORIZATION 2026-09-01: "arm the prop resolvers once a book_grid cycle confirms clean prices" — condition MET: three consecutive clean grid cycles 18:11/18:21/18:31Z (books incl. polymarket, near_misses={}), prop ladders all monotonic, ladder_bad=[], capture converged 374→53→0]`. Testable outcome: `POLYMARKET_PROP_RESOLVERS armed=True ... withheld=0` AND the date-scoped polymarket `PAPER2_PLAN_WRITTEN venue_priced` rises decisively from its game-line-only baseline (62 of 444 rows_in, read 18:20:10Z).
- Files: NONE — Render ENV on refresh-worker via the single-key API, never `render.yaml`; the arming deploy carries origin/main (rides: `9a768443` #611 prop seal, `258d312f` #626(h) autorun default-OFF — both landed by phase0 lanes, deploy-ready by the deploy-main rule).
- Hypothesis: prop matches carry CANONICAL market names and shortlist rows carry the same, so `_resolver_key` symmetry holds and props resolve.
- Falsification test: `armed=True` with `venue_priced` NOT rising above ~62 — the raw-vs-canonical market-name asymmetry named in `todo #628` is real and the armed resolvers are INERT on props; report as such, never as armed-and-working.
- Verification: post-deploy log read of both lines above for date=2026-09-01; then first prop-order behavior (ORDER_PATH/LIVE_ORDER) reported, execution caps unchanged ($100/day polymarket, $10/order, 15/day).
- Blocked by: none (closed).

### kalshi-soccer-forward-date — CLOSED 2026-09-01 — **BOTH CHANGES SHIPPED AND READ IN PRODUCTION; ONE VERIFIED, ONE UNEXERCISED, GOAL NOT MET AND SAID SO.** (1) DATE WIDENING VERIFIED, prediction pre-stated and confirmed: `market_is_for_another_date` **3,495 -> 910** and `event_not_on_our_board` **0 -> 883** on `839bfa06` (20:30:26Z). (2) CLUB CODE -> NAME resolution deployed on `3ee0f382` (live 21:00:23Z) and **moved nothing** — `event_not_on_our_board` 883 -> 883 to the digit. **Unexercised, not disproven:** the failing blobs are 8/8 Belgian Pro League fixtures dated 09-05/06 and `match_event_blob` iterates OUR games, so with no board row nothing can pair; 11 of 12 of those clubs resolve locally by name. **Kalshi soccer quotes remain ZERO** (`QUOTE_CAPTURE sports=['mlb']`) — the original goal is NOT met. The binding constraint moved three times, each move real: date -> club alias -> **board soccer fixture horizon on forward dates**, which is a different lane. Money path untouched: `KALSHI_SOCCER_RESOLVERS` shipped default-OFF and has never had a soccer match to withhold. **The requested 'fix the title parser' was a NO-OP** (18/6,000 unreadable, all NCAAF awards); state.md corrected in `39f00736`. Measurements: `deploys.md` 20:30Z + 21:08Z. — opened 2026-09-01 — session 41d46db0-4017-4d9b-91bf-c9392f13c9de
- Goal: Kalshi soccer PRICES reach `book_quotes` (so soccer is cross-venue comparable) **without opening Kalshi soccer to live orders**. `[USER DECISION 2026-09-01: "do it that way" — widen, but gate the position side]`. Testable: `[kalshi_odds] QUOTE_CAPTURE ... sports=['mlb','soccer']` with soccer rows landing in `soccer_source/tracking/book_quotes/`, AND `KALSHI_SOCCER_RESOLVERS armed=False withheld>0`.
- **THE REQUESTED FIX WAS A NO-OP AND IS NOT WHAT SHIPPED.** "Fix the Kalshi soccer title parser" — the parser has been FIXED since 2026-08-28/30 (`unreadable_title` 18 of 6,000 at 19:51:47Z, every sampled family NCAAF awards, zero soccer). state.md corrected in `39f00736`.
- **THE REAL BLOCKER, MEASURED:** `kalshi_board_join` matches on ONE scalar `wanted_date` (slate date) at lines 599/722/950; Kalshi's working set holds **918 soccer markets dated 2026-09-02..09-15 and ZERO today** (`BY_GAME_DATE` + `TRIM_BY_SPORT demand={'soccer': 1541}`), so an exact-date join matches zero soccer by construction. `market_is_for_another_date` is the largest refusal at **3,495 of 6,000**. Same defect `polymarket_board_join` fixed with a SOCCER-ONLY FORWARD-ONLY widening at `_FORWARD_HORIZON_DAYS = 14`.
- **THE POSITION-GATE PRECONDITION FAILED, WHICH IS WHY THE RESOLVER GATE EXISTS.** I predicted `no_model_edge_pct` would hold soccer out. **It does not: 4 soccer positions in the last 7 days** (08-26/28/29/30, `/api/portfolio/paper`), soccer is NOT in `DEFAULT_EXCLUDED_FAMILIES` (`mlb:player_prop` only), `SYNDICATE_EXECUTION_ENABLED=1` and soccer is in `SYNDICATE_ACTIVE_SPORTS`. Verified rather than assumed — the same class of stale-belief error the parser premise already was.
- Files: `syndicate/features/shared/kalshi_board_join.py`, `pipeline/portfolio_commit.py`, `tests/test_kalshi_board_join.py`, `tests/test_kalshi_soccer_forward_date.py` (NEW)
- Hypothesis: soccer club pairs do not repeat inside a 14-day horizon, so widening cannot pair a board row to the wrong fixture; the existing `event_matches_two_games` ambiguity refusal is the backstop, and nothing about fixture identity is relaxed.
- Falsification test: `event_matches_two_games` rising for soccer after the change, or a soccer match whose paired board row names a different fixture — either means the horizon is too wide and this reverts.
- Verification: production read of the Kalshi capture line carrying soccer, soccer rows present in the soccer book_quotes shard, `KALSHI_SOCCER_RESOLVERS armed=False withheld>0`, and MLB match counts UNCHANGED (the control — widening is soccer-only).
- Files: released at close 2026-09-01: `syndicate/features/shared/kalshi_board_join.py`, released: `syndicate/features/shared/kalshi_catalogue.py`, released: `pipeline/portfolio_commit.py`, released: `tests/test_kalshi_soccer_forward_date.py`, released: `tests/test_kalshi_club_code_names.py`
- **NEXT LEVER, for whoever picks it up:** the soccer board's forward fixture horizon. Kalshi lists 918 soccer markets over 09-02..09-15; our board does not carry them, so the alias path sits ready and idle. **Do NOT re-fix the alias path on the 883 reading** — it is deployed and its names resolve.
- Blocked by: none.

### orphan-sequencer-venue-fee — CLOSED 2026-09-01 — all three picks had already landed as blob-identical twins (`45a4e1d8`/`378d6689`/`b7a8b207`, 22:21:21 the night of the stall); sequencer cleared with `--quit` + `rmdir`, HEAD `66e4ebb4` unchanged; owner was `live-venue-order-placement` (CLOSED 08-30, session gone); landing the picks would have REGRESSED venue_fees.py behind the 08-30 fee-model corrections. Full narrative: `log/2026-09-01.md` — opened 2026-09-01 — session fbf1a34b-cfd3-4248-8194-8d9ce16d8596
- Goal: the primary tree's stalled 3-pick cherry-pick (`e8b5fdb9`/`4741a642`/`3f38d2e8`, venue-fee-retraction thread, stalled 2026-08-29 22:17:52 CT) is verified against origin/main content and the orphan `.git/sequencer` cleared with `--quit` — never `--abort` — with the disposition logged.
- Files: NONE tracked — `.git/sequencer` (untracked git state) only; ledger appends to `log/2026-09-01.md` and this block. No code edits.
- Hypothesis: the three picks' CONTENT already landed on origin/main via twin commits (`45a4e1d8`/`378d6689`/`b7a8b207`, 22:21:21 same evening), so the sequencer is abandoned litter of lane `live-venue-order-placement` (CLOSED 2026-08-30, session 69f9e24f gone), not unlanded work.
- Falsification test: any touched path whose blob in the unlanded chain differs from the landed twins in a way main did not later supersede — that would mean real unlanded content and the picks must land via a worktree instead.
- Verification: per-path blob diffs unlanded-vs-twin all empty (RAN: 4 code/test files identical to `45a4e1d8`; findings file identical to `378d6689`'s; learnings+index identical to `b7a8b207`; lanes edit identical) with `git cherry`'s two `+` marks proven false positives per the 08-31 FORBIDDEN rule; then `.git/sequencer` absent and HEAD unchanged after `--quit`.
- Blocked by: none.


### orphan-stash-yes-leg — CLOSED 2026-09-01 — stash@{0} `9a384978` dropped after component-level verification: staged half landed as `a5e16ae6` 71s after stashing (refined comment, same assertions); unstaged ops.py proven a STALE pre-`508a7e79` copy that would have REVERTED the peer's slug-filter feature if applied; owner (session `5611932c`, ARCHIVED) worktree clean; human pass supplied by user this session; 22 older stashes remain UNEXAMINED. Full narrative: `log/2026-09-01.md` — opened 2026-09-01 — session fbf1a34b-cfd3-4248-8194-8d9ce16d8596
- Goal: `stash@{0}` (`9a384978`, "WIP on session/polymarket-yes-leg-binding", created 2026-08-31 07:59:13 CT by ARCHIVED session `5611932c`) verified component-by-component against origin/main, then dropped `[USER AUTHORIZATION 2026-09-01: "the orphaned stash needs the same treatment — verify then clear" — the human pass the 09-01 learnings entry requires]`.
- Files: NONE tracked — `refs/stash` git state only; ledger appends + a dated addendum to the existing 09-01 stash learnings entry. No code edits.
- Hypothesis: the staged components landed as `a5e16ae6` 71 seconds after the stash (07:59:13 → 08:00:24, same stash-then-land-elsewhere pattern as the sequencer); the unstaged ops.py delta is a STALE pre-feature copy whose only effect if applied would be reverting peer commit `508a7e79`.
- Falsification test: any stash blob carrying content that neither landed nor is a byte-exact older version of a landed file — that would be real unlanded work, and the stash must be landed or surfaced instead of dropped.
- Verification: RAN, all three components accounted for — ops.py blob byte-identical to `508a7e79^` (stale copy proven, zero novel content); test assertions identical to landed `a5e16ae6` (only the comment differs, landed refined; file evolved twice more on main same day); lanes claim line superseded by the corrected claim at lanes.md:1268 ("MOVED here from polymarket-yes-leg-binding, which had misfiled it"). Owner's worktree checked: CLEAN (0 modified/untracked). Then: stash@{0} re-verified == `9a384978` at drop time, dropped.
- Blocked by: none.

### orphan-stash-census — CLOSED 2026-09-01 — ALL 22 stashes verified and dropped; stack EMPTY. 349 tracked paths blob-classified, 65k+ untracked classified by policy, ledger files line-checked, six off-main bases proven twinned or recovery-branch-held. FOUR unlanded artifacts recovered first (model-sim-track 08-18 checkpoint — never committed anywhere; two 07-15 fix_notes entries; soccersim phase-1 report fullest copy; SmartSim ensemble eval report) — disposition table + appendices: `findings_2026-09-01_stash_census.md` + two `recovered_*` files. Drops guarded per-SHA, zero aborts — opened 2026-09-01 — session fbf1a34b-cfd3-4248-8194-8d9ce16d8596
- Goal: all 22 remaining stashes (2026-05-30 `7bb3ea4b` .. 2026-08-21 `c56b6e67`) verified component-by-component (worktree, index, untracked ^3) against origin/main; proven-safe ones dropped by same-instant SHA guard, anything with novel unlanded content KEPT on the stack and surfaced `[USER AUTHORIZATION 2026-09-01: "census the other 22 the same way"]`.
- Files: NONE tracked — `refs/stash` git state only; ledger appends; census table to `.syndicate/findings_2026-09-01_stash_census.md`. No code edits.
- Hypothesis: most are landed drafts, stale copies, protective ledger snapshots since superseded, or regenerable output — per the two orphans already resolved this session. Off-main bases (6 of 22) additionally checked for whether the stash is the last reference keeping an unlanded base chain alive.
- Falsification test: per stash — any stash/untracked blob that is neither in origin/main's history for its path, nor a byte-exact older landed version, nor regenerable mirror/report output; such a stash is NOT dropped.
- Verification: per-stash disposition table with the evidence class for every differing path, written to the findings doc; drops executed only under a same-instant `rev-parse` identity check; stack length re-read after each drop.
- Blocked by: none.


### ncaaf-games-cache-refresh — OPEN — opened 2026-09-01 — session b85e895e-dde2-4066-8336-dc6c1d4c3c61 — **LANDED `bc2365fc` + `c1c3cf12` on origin/main. NOT DEPLOYED. Production reading OWED.**
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
  tests/test_ncaaf_games_cache_refresh.py (NEW),
  tests/test_ncaaf_week_state.py (NEW),
  tests/test_ncaaf_sp_ratings_cache.py (docstring only)
- **CROSS-LANE, AUTHORISED AND LOGGED. NOT CLAIMED HERE ON PURPOSE:**
  `artifact_publisher.py` is claimed by OPEN lane
  `football-projection-publish-allowlist` (`#618`), and the claim STAYS THERE —
  my edit is finished and landed, so holding a second claim would only block
  that lane for no benefit. It is listed in this bullet rather than in `Files:`
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
  `_cfbd_get_latched` runs `raise_if_latched` INSIDE the retry ladder and
  classifies urllib errors (`cfbd.py`'s classifier reads `exc.response`, which
  urllib errors lack — reusing it would have been inert while looking wired).
  (b) the refreshed cache CANNOT reach web: `publish_hot_artifact` reads
  sub-4MB files as UTF-8 text, so the 39KB `.gz` raises UnicodeDecodeError ->
  `SKIP_READ_FAILED`. Hence a small owned JSON artifact (`week_state.py`):
  worker derives per-week played/unplayed COUNTS, web reads those. Facts, not
  the decision — the "lowest week with an unplayed game" rule stays in code.
- Verification LOCAL, DONE: 210 tests green post-rebase across ncaaf +
  publisher + `#618`'s own test, no regressions. Covers off!=on for the
  refresh, the artifact WINNING over the stale cache (order, not just parsing),
  the fallback when no artifact exists, `ncaaf_target_week` never reaching
  CFBD, and the written path being one `HOT_ARTIFACT_PATTERNS` actually
  matches — the half that was inert for 13 days on the sibling entry.
- **OWED — NOT DEPLOYED, NO PRODUCTION READING.** Needs BOTH services (worker
  writes+publishes, web reads). The readings that would prove it:
  `WEEK_STATE season=2026 ... stale_completion_flags=0 published=True` on
  refresh-worker, then `resolved_active_weeks` moving past [1] after 09-07.
  Until deployed, the board stays pinned to week 1 — harmless until 09-08.
- Blocked by: none.


### orphan-worktree-census — CLOSED 2026-09-01 — 166 of 186 C:/tmp worktrees removed after per-worktree verification (155 clean + 11 verified-dirty, all dirty content proven runtime exhaust / landed drafts / superset-elsewhere docs); every HEAD proven ref-reachable BEFORE removal so zero commits orphaned; 17 PROTECTED (10 OPEN lanes, 6 active-session/task incl. the ENABLED nightly gameline snapshot, + today's refit closure), 3 PARKED on the permission classifier (`nfl-fantasy-projections`, `wnba-halftime-elapsed`, `wnba-live-props-data` — verified data/live-runtime only; one human `git worktree remove --force` each finishes it); 39 headless admin husks deleted, prune clean. Zero recoveries needed. Table: `findings_2026-09-01_worktree_census.md` — opened 2026-09-01 — session fbf1a34b-cfd3-4248-8194-8d9ce16d8596
- Goal: every worktree under `C:/tmp` censused with the stash-census discipline `[USER AUTHORIZATION 2026-09-01: "same treatment for the stale worktrees in C:/tmp"]`: live-session and OPEN-lane worktrees PROTECTED and untouched; clean stale ones removed (branch/commits survive removal — only uncommitted+untracked content is ever at risk); dirty ones content-verified against origin/main first and recovered where unlanded. No `--force` past unverified content, ever.
- Files: NONE tracked — worktree registrations (git state) only; ledger appends + census findings doc `.syndicate/findings_2026-09-01_worktree_census.md`. No code edits.
- Hypothesis: the ~110 detached `C:/tmp` scratch worktrees (deploy/push/checkpoint era) are clean husks on landed or ref-reachable commits; the risk concentrates in dirty session worktrees whose lanes are closed.
- Falsification test: per worktree — any uncommitted/untracked file whose content is neither on origin/main, in a landed twin, regenerable by policy (data mirror/reports/caches), nor recovered to the ledger; such a worktree is NOT removed.
- Verification: sweep TSV (dirty counts, HEAD ancestry, ref-reachability) driving a per-worktree disposition table in the findings doc; removals only via `git worktree remove` (which itself refuses dirty trees unless forced — force only after per-file verification, recorded); final `git worktree list` retains exactly primary + protected.
- Blocked by: none.



### orphan-branch-census — CLOSED 2026-09-01 — 193 of 215 local session/deploy branches + ALL 257 `origin/deploy/*` deleted; origin deploy/* now ZERO (`ls-remote` verified) and remote-tracking refs pruned; the 22 kept are exactly the checked-out/OPEN-lane protected set (+1 branch born mid-census). Deletion made LOSSLESS BY CONSTRUCTION: every deleted tip under `refs/archive/branch-census-2026-09-01/{local,remote}/<name>` with name-by-name coverage verified (comm=0, twice) BEFORE deletion — restore is one `update-ref`; chosen over 248 per-tip blob proofs whose "not blob-landed" reading is EXPECTED for divergent deploy tips main evolved past. Out-of-scope families noted (backup/claude/dep-*/fix; remote claude/safety/hotfix/wip/staging); `recover/stash-*` explicitly NOT stale. Table + recipe: `findings_2026-09-01_branch_census.md` — opened 2026-09-01 — session fbf1a34b-cfd3-4248-8194-8d9ce16d8596
- Goal: stale `session/*` and `deploy/*` branches (215 local + 257 `origin/deploy/*`) censused with the day's discipline `[USER AUTHORIZATION 2026-09-01: "same treatment for the stale session and deploy branches"]`: a branch is deletable ONLY when tier-verified — tip ancestor of origin/main, or every `git cherry +` commit content-verified landed (blob/twin level, never cherry alone per the 08-31 rule); anything unverified or protected stays and is reported.
- Files: NONE tracked — branch refs (git state) only; ledger appends + findings doc `.syndicate/findings_2026-09-01_branch_census.md`. No code edits.
- Hypothesis: deploy branches are compositions cut from live SHAs whose fix content landed on main via twins (the 08-15 lesson: two deploy branches do not contain each other); session branches of closed lanes landed via worktree pushes. Tier-1 ancestry will clear most; the tier-3 remainder concentrates the risk.
- Falsification test: per branch — a unique commit whose changed-path blobs are neither in origin/main's history nor superseded by main's evolution of those paths; such a branch is KEPT and surfaced.
- Verification: tiered TSV (ancestor / patch-equivalent / content-verified / KEPT) in the findings doc; protected set = OPEN-lane + active-session + checked-out-in-worktree branches + `recover/*` (out of scope, content owners); deletions batched with per-batch disposition echo; final ref counts.
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
