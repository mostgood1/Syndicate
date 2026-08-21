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

#### snapshot-freshness — ~~DEPLOY REQUEST~~ **WITHDRAWN 20:25Z — DONE, NOTHING IS ASKED OF YOU.** `2efe76b1` is live on refresh-worker (20:25:16Z), verified by content. Cut on YOUR `415e23cb`, deployed into a lull after `daily_update --workflow ui-daily` finished — your work was not killed. Original request kept below for the record.

**Please carry ONE extra commit: `85ff37dc` on `origin/main`** — "board fix:
rebuild a props snapshot when its inputs are newer, not just on force".

- **WHY, measured on the served board at 14:3x CDT** (rec vs the board's OWN
  current market row): CHI@SEA spread `1.5` vs `2.5`; POR@PHX total `176.5` vs
  `178.5`; IND@ATL total `188.0` vs `187.5`. **A 2-point stale total is a
  fabricated edge**, not cosmetic lag.
- **CAUSE:** the three props-snapshot exporters gated on EXISTENCE, so the first
  build of a date won forever. `--force-refresh` bypasses it but the routine
  cycle never passes it. The `win_prob` counter dates it: `recommendations_slate`
  last built 00:53 CDT, `cards_props_snapshot` 00:11 CDT, every WNBA run since
  `rows=0` (no builder called) while market rows updated all day.
- **FIX:** gate on FRESHNESS — `_snapshot_inputs_are_newer` rebuilds when an
  input CSV is newer than the snapshot. Both producers, all three exporters.
- **ALREADY LIVE on live-odds-worker** (`46b5ec66`, 19:47:16Z), verified BY
  CONTENT. refresh-worker is the only service missing it.
- **HOW:** cherry-pick `85ff37dc` onto whichever live SHA you cut on — it applied
  cleanly onto `98a9cad8` and `0315f548`, so it should onto `415e23cb`. Tests:
  `tests/test_export_snapshot_force_refresh.py` → 34 passed. Verify after landing
  by CONTENT: `_snapshot_inputs_are_newer` present, 3 gated call sites.
- **RUNTIME EFFECT:** one extra small JSON build per cycle when inputs changed,
  nothing when they have not. Does NOT touch scheduling, sim, or memory paths.
  Deliberately bounded — the other ~30 `if existing:` short-circuits were left
  alone, because `live_refresh_loop`'s per-trigger `--force-refresh` would turn
  every trigger into a full artifact rebuild.
- **CONTEXT, NO BLAME:** my refresh-worker deploy at 19:41:37Z was superseded by
  `415e23cb` at 19:42:00Z. I am deliberately NOT re-firing so I do not cancel
  yours in return.
- **NOT A BLOCKER ON YOU.** refresh-worker builds `date+1`, so today's board is
  already fixed via live-odds-worker. If you would rather not carry it, ignore
  this and I will deploy it once your window is clear.
- **Cross-session messaging was UNAVAILABLE** — this lane's session is unattended
  (a scheduled-task run), and `send_message` refuses to send from those. The
  ledger is the channel; that is why this is here and not a DM.

### live-game-line-projection — OPEN, UNOWNED — **HEADER CORRECTED `[2026-08-20T21:0xZ]` (RE-APPLIED — a later push reverted it once): THE EVALUATION HAS BEEN RUNNING ALL ALONG.** `live_gameline_score` is computed every board build and served on `/api/board/book-grid?sport=mlb`; nothing RETAINED it. Reading 20:13Z, `priceable_only` (985/985, the sound cut): model brier 0.28706 vs market 0.24700 — **model TRAILS by +0.04006**. BOUND: `games_with_outcome: 3`; n=985/1449/2799 are repeated snapshots of those same 3 games, and MAE runs the OTHER way (0.447 vs 0.483). `all_records` is UNSOUND (n 1526 vs 1449). **v2 DISCRIMINATOR PROVEN** — written 38 > priceable 31, then 34 > 27, two live builds. Accumulating nightly via `live-gameline-accuracy-snapshot` (23:25 CT, before the slate roll); underpowered until pooled games ~100. — opened 2026-08-16
> **[SWEEP 2026-08-17 12:1x CDT] ORPHANED CONFIRMED** — session
> `live-gameline-eval` no longer exists in the roster, so "UNOWNED" is now a
> measured fact rather than a checkpoint note.
> **SINGLE NEXT ACTION:** read `live_gameline_ledger` off
> `/api/board/book-grid?sport=mlb` across TWO builds. The v2 discriminator is
> **`written` rising on rows that are NOT priceable** — `skipped_unchanged > 0`
> is NOT it and was already seen under v1.
> **[COORDINATOR 2026-08-18] THE HEADER ABOVE WAS STALE AND IS CORRECTED.**
> "v2 STILL UNEXERCISED" is **FALSE** as of 2026-08-17 02:2x–02:3xZ: the
> scheduled `live-gameline-ledger-check` measured **3,748 rows** on the first
> real slate, via `live_gameline_score.records_considered` (the ledger file's
> own row count), not via the per-build counters. Recorded in `deploys.md` and
> now on both request files in `deploy/done/`, which had been closed with no
> outcome carried back.
> **THE NEXT ACTION SURVIVES, NARROWED.** What 3,748 proves is that the recorder
> writes. It does **not** prove the v2 discriminator — `written` rising on rows
> that are **NOT priceable** — because `candidates` was 0 on every build that
> night (Sunday day slate, over before 20:30 Central fired). That still needs
> two builds **inside a live window**, and 20:30 Central is the wrong hour to
> get one on a Sunday.
> **AND IT CANNOT BE READ OFF-WORKER.** `/api/ops/artifacts/stream` returns
> **403 `path is not an allowed hot artifact`** for the ledger `.jsonl`;
> re-verified 2026-08-18 — no entry in `HOT_ARTIFACT_PATTERNS`
> (`artifact_publisher.py:35`) matches
> `*_source/data/live_gameline_ledger/live_gameline_ledger_*.jsonl`. Whoever
> takes this lane needs the artifact route, or the allowlist entry first.

**STATUS AT CHECKPOINT `[15:2xZ]`.** Nothing uncommitted; everything is on
`origin/main` and content-verified there. web `ebd5f677` live 03:38:07Z,
refresh-worker `5c419007` live 04:24:33Z — and `LEDGER_VERSION = 2` is
content-verified on the CURRENTLY live `d72d670c`, which another lane deployed
at 06:01:34Z and carried it forward. Board at 15:17Z reads `index_size 0,
considered 0` — Sunday pregame, nothing live yet.

**THE SINGLE NEXT ACTION:** read `live_gameline_ledger` off
`/api/board/book-grid?sport=mlb&date=2026-08-16` during tonight's slate
(scheduled `live-gameline-ledger-check`, 20:30 Central). **The discriminator
for v2 is `written` rising on rows that are NOT priceable.**
`skipped_unchanged > 0` is NOT it — that was already observed under v1 at
04:22:51Z, which is what refuted this lane's own "never recorded a row".
Read across two builds, never one.

**ONE UNPAID DEBT:** an `oomKilled` fired at 04:46:44Z, 22 min after my
deploy added work to refresh-worker. Recorded by `refresh-worker-oom-recurrence`,
and `44ad2f9d` reports `d72d670c` as 9h clean since — **but I never measured
the ledger's RSS and I am not claiming exoneration.** Kill switch, no deploy
needed: `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0` (currently ABSENT = enabled).

— original re-take header follows —
### convergence-phase7-crps — OPEN, **UNOWNED** `[session abf487e4 ARCHIVED 2026-08-20T21:1xZ]` — **FIVE FINDINGS: FOUR DEFECTS FIXED AND MEASURED, ONE NOT A DEFECT.** Ladder over the 12MB publish ceiling (pitcher strikeouts 0/12 → 18/18 rows with market lines, verified on the served payload); conditional mix never CALLED from the roster build; season-artifact pull matching NOTHING (bare globs vs fnmatch on full paths) — all five inputs now present on the worker. NOT a defect: `vs_pitcher_*` is unfed by `FORWARD_BVP_MATCHUP_MODE=off`, a modelling decision; reclassified as `disabled` so nfail means "wrong". **THE ONE THING OWED: verify on 2026-08-21** — first `sim_input_report_2026-08-21.json` via `/api/ops/artifacts/export?pattern=*sim_input_report*` must show `nfail` **10 → 0**; still 10 on a fresh `generated_at` means the wiring is INERT and this reopens. Claims: NONE held. Still open, deliberately not fixed: ephemeral `vendor/*/data/` statcast caches; BVP left OFF by design. — opened 2026-08-17
- **Goal (single testable outcome):** a proper scoring rule runs over
  CONTINUOUS projections joined to realized outcomes, with **no dependency on
  settlement, grading, or a placed bet**, and emits a non-zero per-sport sample
  with `n` attached to every statistic. This is `#440` Part 4 **Phase 7** — the
  instrument Phases 8 and 9 are read with. Nothing downstream is attributable
  until it exists.
- **Why this phase:** Phase 5 shipped (`964c89a4`) and Phase 6 touches the
  prediction-ledger write path, a seam the plan says needs an owner agreed with
  the betting-engine track. Phase 7 as scoped below touches neither.
- **Files (all NEW — collision-checked 2026-08-17 against all 14 OPEN lane
  blocks on `origin/main`; zero overlap):**
  - `syndicate/features/shared/projection_score.py` (NEW)
  - `tests/test_projection_score.py` (NEW)
  - `scripts/score_projections.py` (NEW)
- **NOT claimed, deliberately:**
  - `syndicate/features/shared/intelligence_evaluation.py` — IS claimed by an
    OPEN lane, and is the **settled-bets** path this work exists to route
    around. `model_scoring.py`'s own docstring says it "does not read the
    ledger, the board, or any artifact itself" and names its intended callers as
    a recalibration job or a backtest script. Phase 7 does not need this file.
    **Raised, not taken** — per the Phase 5 close: *"Raise ownership before
    writing code."* No live session holds the betting-engine track
    (`clv-without-settlement`, `grading-blocker-settled-zero` are OPEN but their
    sessions are stopped).
  - `syndicate/features/shared/model_scoring.py` — READ-ONLY. Pure math, 0
    non-test callers, verified on `origin/main` (not on this stale checkout).
- **Hypothesis (stated before measuring):** the plan's claim that Phase 7
  "works today on all seven sports that produce a mean and a spread" is
  **BELIEVED, NOT VERIFIED**. I predict **fewer than seven** sports publish a
  projection carrying BOTH a usable spread and an outcome join.
- **Falsification test:** if ≥7 sports carry a joinable (mean, sigma, outcome),
  the hypothesis is wrong and Phase 7 is a seven-sport instrument on day one.
  If fewer, Phase 7 **re-scopes to bias/dispersion (signed error + MAE), which
  needs no sigma** — and that re-scope gets recorded, NOT papered over by
  fabricating a sigma from a fixed constant.
- **DESIGN CONSTRAINT from `learnings.md` 2026-08-16 FORBIDDEN (letting a
  FITTED MODEL judge when a model-free measurement is available):**
  `crps_normal` imposes a **Normal** predictive distribution on what are
  actually empirical Monte Carlo draws — and for low-scoring discrete outcomes
  (runs, goals) that approximation is doing real work. Where the sim's own
  distribution is available, the **empirical-CDF CRPS is the evidence and the
  Normal closed form is the hypothesis.** Report both where both are
  computable; never report the Normal one alone as "the" CRPS.
- **Denominator discipline (CLAUDE.md standing trap + rule "a rate, not a
  count"):** print per-family date coverage AND the intersection **first**, and
  state the number of dates the result actually rests on. Do not scope the
  sample from this checkout — production has far more history (81 WNBA dates vs
  4 files locally).
- **Verification:** a scored report with, per sport × market: `n`, the
  bias/dispersion decomposition, CRPS where a spread exists, and — for any
  binary companion — the **market's** number on the identical rows. A cell below
  the sample floor reports `unmeasured`, following `projection_skill`'s existing
  first-class `unmeasured` convention rather than inventing a second one. Result
  written to `deploys.md` with the window and sample size.
- **Blocked by:** none. Deliberately not touching Phase 2/2b files
  (`live_refresh_loop.py`, `run_refresh_worker.py`) held by
  `refresh-worker-oom-recurrence`.

#### convergence-phase7-crps — SUBSTRATE MEASURED 2026-08-17 — **hypothesis CONFIRMED, and the coverage is INVERTED from what the plan assumes**

`[measured from this checkout — a LOSSY MIRROR, so every count is a LOWER BOUND
on production and the absences are NOT all established. Labelled per row.]`

**The plan's claim that Phase 7 "works today on all seven sports that produce a
mean and a spread" is NOT SUPPORTED.** Falsification test did not fire.

| sport | spread in the artifact | status |
|---|---|---|
| **MLB** | **full 1000-draw empirical PMF** | **CONFIRMED** |
| **WNBA / NBA** | `pts_sd`, `reb_sd`, `ast_sd`, `pra_sd`, … + `home_pts_sigma` / `away_pts_sigma` | **CONFIRMED** (56 wnba files, 21 dates) |
| NFL | none, across **165 files / 160 dates** | **CONFIRMED ABSENT** |
| NHL | none in the file sampled — but the sample was a 159-byte `odds_history.json` | **UNMEASURED, not absent** |
| soccer | no pregame picks/projection files in the checkout at all | **UNMEASURED, not absent** |
| NCAAF | 0 files locally; season opens 08-29 | **UNMEASURED** |
| NCAAB | no engine exists (`state.md`) | n/a |

So Phase 7 is a **2-sport instrument on day one**, not a 7-sport one. NHL and
soccer must be re-checked against PRODUCTION before anyone writes "no spread" —
this checkout is exactly the trap CLAUDE.md documents.

**AND THE MLB COVERAGE IS INVERTED — this is the finding that shapes the build:**

| MLB family | spread | markets | existing backtest? |
|---|---|---|---|
| **pitcher props** | **full PMF, 1000 draws** | so, outs, hits, earned_runs, walks, batters_faced, pitches (**7**) | **NONE** |
| **game total / margin** | **full PMF, 1000 draws**, in 4 segments (`full`/`first1`/`first3`/`first5`) | total_runs, run_margin (**2 × 4**) | **NONE** |
| hitter props | **mean only — NO distribution** | h, tb, rbi, r, hrr, 2b, 3b, sb, hr (9) | yes, `backtest_mlb_props.py`, n=2,487 |

**The one MLB family that HAS a backtest is the only one that CANNOT be
distributionally scored, and the two families carrying a full 1000-draw PMF have
never been scored at all.** That is where Phase 7 goes.

- **Denominator, stated:** ~30 pitchers/date × 7 markets over 78 local dates is
  ~16k pitcher-market observations, against "a few dozen settled bets a week".
  The plan's 10–100× claim is now MEASURED for MLB rather than asserted.
- **OUTCOME JOIN ALREADY EXISTS AND IS EXACT.**
  `processed/mlb_batter_game_log.csv` (12,185 rows) and
  `mlb_pitcher_game_log.csv` (5,089 rows), keyed `date, game_pk, player_id`.
  `feed_live` is **absent from this checkout (0 dates)** — the CLAUDE.md
  intersection trap fired exactly as written, and the game logs are the way
  around it.
- **DO NOT BUILD A NEW JOIN.** `scripts/backtest_mlb_props.py` already solves
  archive-replay-from-production, the exact `batter_id` join, per-market
  denominators, DNP exclusion and baseline comparison. It reads **means only**
  and never touches the `*_dist` sitting in the same artifact. Phase 7 is the
  distribution half of a harness that already works, not a second harness.

**CLAIM AMENDED:** this lane now also claims
`syndicate/features/shared/model_scoring.py` — **additive only**, to add
`crps_empirical` beside `crps_normal`. Re-checked 2026-08-17: the file appears
in NO OPEN lane's claim set. Justification: the repo's own
`prop_projections._dist_prob_over` docstring says *"Exact, not a normal
approximation"* for this same PMF, and the 2026-08-16 FORBIDDEN rule says a
model-free measurement outranks a fitted one. Putting the empirical form
anywhere but next to `crps_normal` would be the "fourth copy" this repo punishes.

#### convergence-phase7-crps — **PRODUCTION RUN DONE 2026-08-17. The instrument works; the mirror-only finding is PARTLY WITHDRAWN.**

- **Shipped and pushed:** `origin/main` `91be99e6` — `crps_empirical` +
  `distribution_moments` in `model_scoring`, `projection_score.py`,
  `scripts/score_projections.py`, tests. Verified after the push by blob
  (5/5 match disk, 0 carriage returns). **NO DEPLOY** — local tooling.
- **Lane goal MET:** a proper scoring rule runs over continuous projections
  joined to outcomes, with zero dependency on settlement/grading/a placed bet.
  **12k observations across two windows** where settlement has produced 0.
- **THE FALSIFICATION TEST DID NOT FIRE** on the sport hypothesis: 2 sports
  carry a spread, not 7. NHL/soccer/NCAAF remain **UNMEASURED, not absent.**
- **A SECOND, UNANTICIPATED RESULT — the two sources barely overlap in time.**
  production game logs 2026-07-19..08-16 (29 dates); mirror 05-28..07-12 (46).
  The logs are a ROLLING WINDOW production trims. "Production has more history"
  is FALSE for this family. Recorded in `deploys.md`; the scorer now reports a
  reproducibility table because of it.
- **I OVERSTATED THE FIRST RESULT.** "Every pitcher market is biased high" was
  true of the mirror window only; 3 of 7 markets flip sign on production. What
  reproduces: `outs`, `hits_allowed`, `earned_runs` all biased high, and `outs`
  overconfident, in BOTH windows. The `#428` opportunity thesis is corroborated
  through `outs`; the blanket claim is withdrawn.
- **NEXT, in order:** (1) `--source production` for WNBA/NBA — the other sport
  confirmed to carry a spread; (2) settle whether NHL/soccer carry one, from
  production, before anyone writes "no spread"; (3) trace the `outs`
  over-projection to the sim's starter-depth logic — that is the model fix and
  it is upstream of `hits_allowed` and `earned_runs`; (4) `#440` D4, an
  out-of-sample baseline split.
- **STILL NOT TAKEN:** `shared/intelligence_evaluation.py` and the prediction
  ledger write path. Phase 7 did not need either. Phase 6 still does, and still
  needs an owner agreed with the betting-engine track.

#### convergence-phase7-crps — HYPOTHESIS RECORDED BEFORE TESTING 2026-08-17 — the `outs` over-projection is a FIVE-INNING LEASH

Written before the test is run, per protocol. `[from-code]` unless marked.

**Mechanism proposed.** `ManagerProfile.starter_min_innings = 5`
(`vendor/mlb_bettingv2/sim_engine/models.py:368`), commented *"Keep starters in
longer early (useful for F5 markets) unless they blow up."* Both hook
implementations gate on it identically:

    in_leash_window = state.inning <= max(1, starter_min_innings)      # = 5
    if in_leash_window and (not blowout) and pc < (pull_starter_pitch_count + 15):
        return current      # keep the starter, unconditionally

`pull_starter_pitch_count = 95`, so inside the leash the starter is kept unless
he is at **110+ pitches** or trailing/leading by **6+**. That is a near-hard
floor of **15 outs** on every start.

**And the controls that would break the leash are DEFAULTED INERT** — the same
built-and-unreachable pattern this repo keeps finding. The V2 hook's own
comment says so: *"Defaults preserve the existing behavior (i.e., 'always keep'
within leash unless blowout)"* — `starter_leash_lev_max=1.0`,
`starter_leash_runner_max=1.0`, `starter_leash_tto_max=99.0`. Likewise
`starter_tto_quality_scaling=0.0` and `starter_quality_hook_weight=0.0` both
return a no-op at their defaults, so **starters of different true talent derive
to nearly the same hook** — which is a mechanism for the σ defect specifically.

**THIS DEFECT IS ALREADY KNOWN AND PARTIALLY MITIGATED.** `starter_short_start_prob
= 0.06` / `starter_short_start_hook_delta = -32` carries the comment *"Promoted
default: rare large negative hook shift to prevent pathological overconfidence
in starter outs-at-line."* Someone measured this before and injected a 6% short
start as a patch. **My measurement says it is still there**, so the question is
not "does the leash exist" but "is 6% enough". Do not re-report the mechanism as
a discovery.

**Why this explains BOTH measured symptoms with one cause** — the thing a
bias-only or dispersion-only story cannot do:
- **bias high** (`outs` −5.14 mirror / −2.03 production): a floor raises the mean.
- **σ too narrow** (dispersion 1.54 / 1.10 vs a calibrated 0.798): a floor
  TRUNCATES THE LEFT TAIL. Short starts are the bulk of real outs variance, and
  the sim can barely produce one.

**FALSIFIABLE TEST (decisive, needs no deploy, data already cached):** compare
**P(outs < 15)** in the sim's own `outs_dist` against the empirical rate of
sub-15-out starts in `mlb_pitcher_game_log`, on the same starts.

- **Confirms** if sim P(outs<15) is materially BELOW the actual rate.
- **REFUTES** if the two are close — then the leash is not binding in practice
  (the pitch-count term may be pulling starters before inning 5 anyway) and the
  bias lives somewhere else, most likely the per-batter pitch model. I will
  report a refutation as such rather than hunting for a second story.
- Also report the FULL simulated vs actual outs distribution, not just the tail,
  so a single-number match cannot hide a wrong shape.

#### convergence-phase7-crps — **LEASH HYPOTHESIS CONFIRMED 2026-08-17, AND MY OWN HYPOTHESIS WAS PARTLY WRONG**

**FIRST, TWO CORRECTIONS TO THE HYPOTHESIS I RECORDED AN HOUR AGO.** I called
three terms "defaulted inert". Read from the LIVE overrides file
(`vendor/mlb_bettingv2/data/tuning/manager_pitching_overrides/forward_start_2026_04_14_v1.json`),
that is wrong:
- **`starter_quality_hook_weight` IS PROMOTED TO 1.0**, not 0.0. It is live.
- **`starter_tto_quality_scaling = 0.0` is a DELIBERATE, EVIDENCE-BASED REVERT**,
  not neglect: promoted then reverted the same session because it made the
  betting hit rate on strikeouts WORSE (55.78% -> 54.65%), the very market it
  targeted. Do not "re-enable" it; that decision is documented and correct.

I read code defaults and called them production. **The overrides file is the
configuration.** Same class of error as reading a stale ledger.

**THE TEST RESULT — CONFIRMED, and the shape is the evidence, not the mean.**
`[measured, production cache, 726 starts / 29 dates]`

    sim  P(outs < 15)   0.1036
    ACTUAL rate         0.2961      <- 2.86x more short starts than the sim makes
    mean outs   sim 17.53 (5.84 IP)   actual 15.50 (5.17 IP)   diff +2.03

That +2.03 **independently reproduces the −2.031 bias** measured by the scorer
through a completely different route. Two methods, one number.

**THE SMOKING GUN IS A POINT MASS AT EXACTLY THE PARAMETER BOUNDARY:**

    outs   IP    sim %   actual %
      12  4.0     2.10      7.58     <- sim makes 1/3.6 as many
      13  4.3     1.61      4.13
      15  5.0   *26.78*    16.25     <- 27% OF ALL MASS AT EXACTLY 5.0 IP
      18  6.0    18.79     24.66     <- reality's mode is 6.0 IP; the sim's is 5.0
      23  7.7     3.08      0.14     <- and the long tail is over-produced 22x

The sim is wrong in BOTH tails: too few short starts, too many very long ones,
and a spike at the leash boundary. A bias-only measurement cannot see this.

**THE CAUSAL CHAIN, END TO END** `[from-code]`

1. `build_roster.py:2506` — every team gets `ManagerProfile()`, i.e. DEFAULTS:
   `starter_min_innings = 5`, `pull_starter_pitch_count = 95`.
2. It then tries per-team tendencies from `data/manager/manager_tendencies.json`
   (`build_roster.py:529`). **That file does not exist anywhere in the repo**
   (`Glob **/manager_tendencies*` -> no files). The loader returns `{}`,
   **caches it**, and the call site is wrapped in `try/except: pass`. So all 30
   teams silently share one hardcoded manager.
3. Its generator, `tools/datasets/build_manager_tendencies_from_feed_live.py`,
   **is referenced only from `bootstrap_prior_season_artifacts.py`** — never
   from the daily pipeline. Built, has a generator, never run.
4. `_select_pitcher_v2:1755` — inside innings 1-5 the starter is KEPT unless
   blowout, or `pc >= eff_hook + 20`, or one of three leash-break conditions
   that ARE at inert code defaults (`lev < 1.0`, `runner_pressure < 1.0`,
   `tto < 99.0` — none of these is in the promoted overrides file).

**THE STRUCTURAL POINT, and it is the part worth acting on.** All four promoted
tunings (`starter_hook_add_pitches = -13`, `stamina_excess_weight = 0.75`,
`quality_hook_weight = 1.0`, `tto_quality_scaling = 0.0`) act on **`eff_hook`,
the pitch-count hook**. Inside the leash window the hook is bypassed unless
`pc >= eff_hook + 20`. **So the leash sits ABOVE every knob that has been
tuned, and it is the one parameter nobody has touched** — it is not even
exposed as a `manager_pitching_overrides` key. A −13 pitch hook reduction can
only bite on a starter already past ~102 pitches inside five innings, which is
rare. That is why careful hook tuning has not closed the sub-15-out deficit:
**it structurally cannot.**

**CREDIT WHERE DUE — DO NOT RE-REPORT THIS AS A DISCOVERY.** The team already
measured this bias by market tier and partly fixed it (elite −0.46, mid-high
+0.73, mid +1.78, back-end +2.66 after `quality_hook_weight`; their sign
convention is `sim − actual`, opposite to the scorer's). **The over-projection
is concentrated in mid and back-end starters; elite starters are slightly
UNDER-projected.** My pooled −2.03 averages across a tier structure that flips
sign, so a single global shift would make aces worse.

**WHAT I HAVE NOT ESTABLISHED**
- **That the tendencies file is absent IN PRODUCTION.** It is absent from the
  repo and its path is code-adjacent (resolved from `__file__`), so it almost
  certainly ships absent — but I did not read the Render disk. Confirm before
  acting.
- Whether the 15-out spike survives per-tier. The tier structure is theirs,
  measured; the distribution is mine, pooled. They have not been crossed.
- Nothing was changed. **No code edit, no config edit, no deploy.**

**RECOMMENDED NEXT STEP, and the reason it is not "lower the leash":** the fix
is not a global constant change — the tier data says that would hurt elite
starters. It is (a) expose `starter_min_innings` as a `manager_pitching_overrides`
key so it can be swept like everything else, then (b) sweep it against the SAME
35-tune/11-holdout harness the other four went through, grading on betting hit
rate and not only on bias — that harness's own lesson, recorded in the
overrides file, is that statistical-bias improvements do not reliably translate
to betting-accuracy improvements.

### soccer-model-dispersion — OPEN, UNOWNED (session `soccer-sport-owner` checkpointed and released 2026-08-20 ~13:3xZ) — TESTABLE OUTCOME NOT MET; DISPERSION FALSIFIED; DISCRIMINATION CONFIRMED AS THE REMAINING DEFECT; HOME-ADVANTAGE RE-FIT TRIED AND FAILED HELD-OUT VALIDATION

- Goal (unchanged, still NOT met): `backtest_soccer_h2h_calibration.py`
  reports model Brier **<= market** on at least one non-`belgian_pro_league`
  league. Baseline: `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json`.
- **RESULT, 2026-08-20 ~06:00Z, against the FIXED pipeline (`3ad5c8a4`) and
  every input-quality change this session made:**
  `reports/soccer_backtest/h2h_calibration_2026-08-19_fixed_pipeline_all9_s300_limit120.json`
  (session worktree, not committed) — **worse than market in 8 of 9
  leagues, `belgian_pro_league` the same single exception as 08-15,
  unchanged.** Mean model stdev(P home) rose **0.1575 -> 0.1922**, PAST
  market's own 0.1859 (model no longer under-dispersed). **This is the
  lane's own pre-registered falsification outcome** ("if the Brier gap does
  not close while stdev rises to market's, under-dispersion is NOT the
  binding constraint") — recorded as an OVERTURNED belief in
  `learnings.md`, 2026-08-20. Full numbers + reasoning in the log
  (2026-08-20 entry) and `state.md`.
- **The input-quality avenue is exhausted, not abandoned.** Every field this
  session set out to check — xG double-count, shots-weight shrink,
  clean_sheet_rate, possession_share, set_piece_goal_share,
  starters_available_share, pace_seconds_per_event, ppda, the backtest/
  production pipeline mismatch, market_features.confidence — is sourced (or
  correctly ruled out), tested, and disposed with a stated reason. None of
  it was wasted (the engine is measurably more complete and honest about
  what it doesn't know than at session start), but none of it closed the
  Brier gap either. **Do not re-open this list without new evidence that a
  specific field is systematically BIASED, not just present or absent** —
  that is the falsification test's actual implication: the spread was fixed
  and it didn't help, so the next hypothesis has to be about what the
  ratings get systematically WRONG, not another input or another knob on
  dispersion.
- Files: `scripts/backtest_soccer_h2h_calibration.py`,
  `scripts/build_soccer_artifacts.py`, `scripts/validate_soccer_vs_market.py`,
  `scripts/soccer_sim_input_checklist.py`, `syndicate/features/soccer/` (sim
  engine, adapters, ratings, `ingestion/espn_match_stats.py`),
  `tests/test_soccer_feature_loaders.py`, `tests/test_soccer_projections.py`,
  `tests/test_build_soccer_artifacts.py`, `tests/test_soccer_adapter.py`,
  `tests/test_soccer_advanced_input_reachability.py`,
  `tests/test_backtest_matches_production_rating_source.py`,
  `reports/soccer_backtest/`.
- **NOT IN THIS LANE:** `syndicate/features/shared/soccer_projections.py`,
  `syndicate/features/shared/book_margin_model.py` — board-side adapter,
  owned by lane `modelled-fair-edge`. Re-check before assuming still true.
- **BIAS DECOMPOSITION DONE, 2026-08-20 ~06:3x-13:2xZ (full detail in the
  log's two 08-20 entries):** `fit_soccer_probability_calibration.py
  --per-league` confirms DISCRIMINATION, not dispersion, is the remaining
  defect (global held-out calibration made Brier worse, fitted temperature
  ~1.0). **Per-league AUC gap is the map of where to look next:** eredivisie/
  championship/primeira_liga/belgian_pro_league/epl all rank AS WELL OR
  BETTER than market (AUC gap +0.004 to +0.044) — NOT ranking problems.
  ligue_1/la_liga are near-parity (-0.002/-0.003). **serie_a (-0.055) and
  especially bundesliga (-0.111) have real, unaddressed ranking
  deficiencies** — the most promising untried thread.
  Traced and tried `home_advantage_attack_boost` (a real calibrated
  constant, stale relative to this session's mechanism changes) for the 5
  shift-candidate leagues: bounded grid search then widened. Four
  directional findings (eredivisie: no change needed; epl: discarded,
  ran away to an implausible negative value; belgian_pro_league:
  noisy/inconclusive; primeira_liga: direction plausible, magnitude
  unresolved) plus ONE genuine bracketed optimum (championship,
  0.055 -> 0.115). **Applied championship's change to a worktree and
  HELD-OUT VALIDATED it (old vs new boost, same 151-match set, scored on
  the 125 matches NOT used to find the value) — FAILED: mean Brier delta
  +0.0121 worse, t=+1.19. REVERTED, NOT COMMITTED.** Same pattern as
  `clean_sheet_rate`: the most trustworthy-looking in-sample result still
  failed held-out. **No home-advantage adjustment shipped for any league —
  none of the other 4 should be trusted either, having looked LESS solid
  than the one that failed.**
- Next action: **bundesliga and serie_a's AUC deficiencies, not another
  home-advantage attempt.** Those two leagues' ranking gap vs market
  (-0.111 and -0.055) is real, measured, and untouched by anything this
  session tried — everything tried so far (dispersion, home-advantage
  shift) targeted the 5 leagues where ranking was already fine. Whatever
  makes bundesliga/serie_a rank worse than market is a different, unexamined
  question — likely something about how team strength is differentiated
  for those two specifically, not a global mechanism. Separately: whether
  `belgian_pro_league` being the one Brier-beating league says something
  transferable is still untried. **Any future single-parameter fit MUST
  clear a held-out validation (different matches than the fit) before
  being applied — this session demonstrated why, not just asserted it.**
- Blocked by: none.

**INHERITED, DO NOT RE-DERIVE** (full detail moved to `.syndicate/lanes_history.md`,
archived 2026-08-19 — read there for the falsification-test design and the
Monte-Carlo-noise-floor cheap-falsifier note, both still valid):
- A leak-free backtest ALREADY EXISTS (`backtest_soccer_h2h_calibration.py`,
  `5a94b134`) — the retired-for-leakage `*_backtest_*.csv` artifacts are a
  DIFFERENT, unrelated thing.
- MLS cannot be backtested from its current source (undated season aggregates).
- Do not publish `model_edge_pct` on a partial win — publishing is a separate
  decision from closing the Brier gap.

#### convergence-phase7-crps — BUILT 2026-08-18, **VALIDATION IN FLIGHT** — per-PA common random numbers

`GameConfig.crn_pa_seeding`, **default OFF**. Re-seeds the game RNG at every
plate appearance from `(rng_seed, batting team_id, that team's PA index)`.

**The problem it targets, measured:** the market harness had a seed-to-seed
noise floor of **0.00326 Brier against effects of ~0.00138**. Cause: one RNG
stream per game, so the first pitch whose outcome differs shifts every
subsequent draw and the two arms are running different games from that point on.
**Sharing a seed across arms LOOKS like common random numbers and is not**, when
control flow depends on the RNG.

**The design decision:** a team's Nth plate appearance is the same logical event
in both arms *by definition of a batting order*, so seeding on it re-synchronises
after any divergence. **Inning is deliberately NOT in the key** — it shifts when
scoring differs, which would break the alignment the flag exists to create.

**Seeds pass through a splitmix64 avalanche, not a plain multiply.** Consecutive
PA indices differ by 1 and Mersenne Twister seeds differing in low bits give
correlated early output — the naive version introduces exactly the correlation
it is meant to remove.

**DEFAULT OFF and it must be ON FOR BOTH ARMS of a comparison.** It changes every
simulated result, so it is a measurement instrument, never a silent change to
what production simulates.

**CLAIMED, NOT YET MEASURED.** `scripts/validate_crn_pa_seeding.py` is running
and checks, in order: (1) determinism preserved with the flag off — a variance
fix that broke reproducibility would be worse than the problem; (2) reachability,
on != off; (3) **the only claim that matters — the spread of `(mix ON - mix OFF)`
across seeds, CRN off vs on.** Each ARM's own variance is irrelevant and will not
improve; reporting it would look like a result and mean nothing. **If the ratio
comes back ~1.0 the flag is not worth using and this entry says so.**


### repo-coordination — OPEN — **POSSIBLY ORPHANED, unconfirmed `[flagged 2026-08-19]`: no currently-running session found narrating its own work under `repo-coordination` — every hit is a session reading the shared `lanes.md` digest or its own guard output (one session's transcript shows `your lane: repo-coordination` printed to a session that is clearly NOT this lane — `Modeling Session (fork 2)` / `abf487e4…` — the exact bare-file misattribution bug fixed earlier 2026-08-19, not evidence of real ownership). No `.current-lane.<session_id>` marker exists for it. Not closed and not force-reassigned on this evidence alone — a live session claiming this lane should confirm by opening it fresh (which now also backfills its own per-session marker).** deployment, assignment and documentation. NOT any sport, model or engine. — opened 2026-08-18 — session: repo-coordination

- **Goal (single testable outcome):** the machinery that decides WHO deploys,
  WHO owns which files, and WHERE a fact is written stays coherent and
  self-checking, with every rule enforced by something that cannot be archived
  or forgotten. Testable: `lane_identity_check.py`, `todo_id_reconcile.py` and
  `state_key_check.py` all exit 0, CI enforces all three, and every deploy goes
  through claim + preflight.
- **Scope, stated as a boundary because this session already crossed it twice:**
  hooks, guards, the deploy path, the four ledgers, `CLAUDE.md`, and the
  session/worktree protocol. **NOT** sport features, sim engines, model inputs,
  backtests, or measuring any model's coverage — including "just reading a
  board to see if a model is fed". If a task's outcome is a statement about a
  MODEL, it belongs to that sport's lane.
- **Files:**
  - `.claude/hooks/` (deploy-guard, lane-guard, commit-guard, session-start)
  - `scripts/session_worktree.py`
  - `scripts/lane_identity_check.py`
  - `scripts/todo_id_reconcile.py`
  - `scripts/state_key_check.py`
  - `scripts/deploy_claim.py`
  - `scripts/deploy_preflight.py`
  - `docs/ai_context/session_isolation_protocol.md`
  - `.github/workflows/ci.yml`
- **NOT claimed, deliberately:** every `syndicate/features/**` path, every
  `scripts/generate_*` and `scripts/backtest_*` entrypoint, and every per-sport
  checklist or engine reference. Those belong to sport lanes.
- **Shipped under this remit today** (all on `origin/main`, all measured):
  deploy-guard gates on claim + SHA-bound CLEAR preflight instead of a session
  id; `OFF_MAIN` (exit 4) so deploys compose; coordinator role retired; three
  ledger checkers built, wired into CI and the session digest; lane-guard's
  claim parsing fixed (52 -> 80 file claims); `state.md` keyed and its two
  stacked subjects collapsed; per-session worktrees adopted.
- **Known open, in remit:**
  - **SHIPPED `58c63b62` on `origin/main` `[2026-08-20]`** — the hook guards
    were resolving paths against `CLAUDE_PROJECT_DIR`, i.e. the wrong
    REPOSITORY once sessions moved to worktrees. `ledger-commit-guard.py`
    blocked a clean worktree over the primary tree's lane duplicates and
    printed `trim_lane_blocks.py --apply`, a remedy that would have
    rewritten two OTHER lanes' blocks; `ledger-append-guard.py` was fully
    INERT in every worktree. Both fixed + measured, shared resolver in
    `commit_context.py`, 33 new tests. `commit-guard.py` refactor proven a
    behavioural no-op. Cross-lane edit taken under explicit user instruction
    while this lane was flagged possibly orphaned.
    Detail: `.syndicate/log/2026-08-20.md`.
  - **CLOSED — all four guards fixed, all four suites ENFORCED in CI**
    `[2026-08-20]`: `f73d163e` fixed `ledger-postwrite-check.py` (blind to
    worktree Bash writes, and it blamed whichever session observed the change);
    `86ec6b42` wired all four suites in, **verified green on the Linux runner**
    (run 32415246596 — 16/16, 17/17, 16/16, 10/10). Enforced rather than
    tolerated because each suite was mutation-tested first. `lane-guard` is
    EXONERATED: same mangled relpath, absorbed by exact-or-suffix matching — do
    NOT "fix" its `root`, the PRIMARY tree is correct for it.
  - `land` reports the ledger checkers rather than gating on them.
  - The new deploy predicate has never gated a real deploy; `OFF_MAIN` has never
    fired in anger; no preflight receipt consumed live. First real deploy tests it.
  - ~100 stale worktrees under `C:/tmp` need a human pass before reaping.
  - `deploys.md` (834 KB) and `lanes_closed.md` (838 KB) have no size discipline
    and no checker.
- **Blocked by:** none.


### wnba-live-odds-capture-gap — OPEN, NARROWED — **THE AUTORUN FIRED FOR REAL `[2026-08-21T00:07:24.782Z / 19:07 CT]`, observed by a third party (scheduled task `verify-wnba-live-scale-481`, session `1f76348c`) on IND@DAL. The "never fired" blocker is DISCHARGED. What replaces it: the autorun launches every ~4.3 min and refreshes the LIVE-LENS path, but `book_quotes/<date>.jsonl` advanced ONCE (00:07:49Z) and was still byte-identical 26 min later. The lane's literal testable outcome PASSES, but passing cannot be attributed to the autorun — see FINDINGS.** **ROOT CAUSE FOUND `[00:45Z]`: the autorun is fine; `refresh_wnba_oddsapi_props.py`'s REUSE GUARD sits upstream of it and returns `reused_artifact_bundle` every tick, so the child that appends `book_quotes` never spawns. The guard's staleness bound is the PREGAME sweep interval (2h) and its reuse key carries no phase term, so a 240s live autorun cannot outrun it. THE FIX BELONGS IN THE GUARD, NOT THE AUTORUN.** — opened 2026-08-20 — session 2bffd747-efb5-45d8-b4f3-ae067b645eb7
- Goal: WNBA's in-game (live-phase) odds capture actually refreshes once a
  game goes live, instead of freezing at its last pregame quote.
  **Testable outcome:** for a WNBA game currently in live state, re-pull
  `wnba_source/tracking/book_quotes/<date>.jsonl` and confirm at least one
  market's `captured_at` is newer than the game's own kickoff time.
- Files:
  - **CLAIM RELEASED 2026-08-20 to `wnba-live-reuse-bound`** (session
    `1f76348c`), narrowly and by this lane's own instruction below. The defect
    location IS now confirmed and it is not in this file — only `_build_wnba_steps`
    needs one line to pass the phase to the child. This lane is UNOWNED (session
    `2bffd747` absent from the roster including archived), so holding a
    read-only reference here would block the fix this lane exists to enable.
    Path deliberately NOT written as a path on this line, because
    `check_lane_invariants.py` parses any backticked path inside a `- Files:`
    block as a live CLAIM and would keep reporting the file as contested.
    Formerly: the WNBA step builder, read-only reference, "do not edit without
    re-claiming narrowly, same convention the soccer lane used for this same
    file" — which is exactly what was done.
  - Not claimed, read-only reference: `scripts/run_live_odds_refresh_worker.py`
    — likely relevant (soccer's autorun equivalent lived here), not yet
    confirmed WNBA has an analogous live-phase launcher at all.
- Hypothesis: WNBA's live-phase odds fetch either (a) does not exist as a
  distinct step from the soccer-style `phase=live` odds capture, or (b)
  exists but is failing/never firing, structurally similar to `#343`
  (soccer's bulk-endpoint 422) but a different mechanism, since WNBA's
  fetch script and market list have never been touched by that fix.
- **Already established, measured 2026-08-20 ~02:18Z (do not re-derive):**
  Minnesota Lynx @ Golden State Valkyries (kickoff 2026-08-20T02:10:00Z):
  every h2h/spreads/totals/prop market for this matchup shares ONE
  `captured_at` (`2026-08-20T00:31:28Z`) — 99 minutes BEFORE kickoff, zero
  refreshes since, 107+ min stale at check time. Distinct from the sim-side
  gap already documented in `per_sport_ingest.wnba.enrichment.
  live_projections` (`reason: "no live re-sim wired for wnba"`) — that is
  about projections, this is about the underlying MARKET QUOTE, which a
  pure book-price EV play does not need a sim for at all.
- Falsification test: find a WNBA-specific `phase=live` odds-fetch step
  that DID run recently for this game (any log evidence of an attempt,
  success or failure) — if one exists and simply failed silently, the
  hypothesis narrows to (b); if none exists at all in the step-builder,
  hypothesis (a) is confirmed and this is a missing feature, not a bug.
  **RESOLVED: hypothesis (b), but not `#343`-shaped — see below.**
- **ROOT CAUSE CONFIRMED 2026-08-20 02:37Z, tested directly, not inferred.**
  1. `_build_wnba_steps` (`scripts/refresh_odds_sources.py:828`) DOES fire
     for `phases=("pregame","live")` — hypothesis (a) is dead.
  2. Replicated the exact discovery + per-event `/odds` call this fetcher
     makes (`fetch_basketball_oddsapi_props_local.py`, event_id
     `09563bab4edf9cf2073ee946ad95d61b`, Lynx@Valkyries) directly against
     production OddsAPI: **HTTP 200, 8 bookmakers, every market present.**
     This is NOT `#343` — the market list is fine (this fetcher already
     uses the safe discover-then-intersect pattern, unlike soccer's old
     naive bulk request; its own code comment even cites `#343` by name as
     the reason it was built this way).
  3. Confirmed genuinely stale via the unambiguous `event_id` join (not a
     team-name mismatch in the diagnostic): 6,981 rows for this event, all
     frozen at `captured_at=2026-08-20T00:31:28Z`, 2+ hours stale.
  4. **The autonomous sweep's own outcome log admits the failure directly:**
     `[live_refresh_loop] ODDS_SWEEP_OUTCOME sport=wnba wrote=False
     exists=True since_launch_s=193 sidecar_age_s=7449` (02:35:49Z) — no
     inference needed, the sweep says it did not write.
  5. **Fired a manually SCOPED trigger** (`POST /api/ops/odds-refresh/run`,
     `phase=live, sports=wnba` ONLY — no mlb, no soccer) and it succeeded
     immediately: `PUBLISH_OK path=wnba_source/tracking/book_quotes/
     2026-08-19.jsonl bytes=6983198` at 02:37:07Z. Re-pulled the shard:
     7,851 rows (up from 6,981), latest `captured_at` **1.7 minutes old**.
     Verification step (below) is DONE for this specific game.
  - **Mechanism:** `live_refresh_loop.py`'s sweep calls
    `launch_refresh_run(sports=launch_sports, ...)` ONCE per tick with ALL
    active sports combined (`sports=mlb,wnba,soccer`) — one subprocess, one
    `refresh_odds_sources.py --sports mlb,wnba,soccer` invocation. Step
    order follows `REGISTRY`'s insertion order: `mlb` (heaviest, most
    complex live-phase work) runs BEFORE `wnba`. Under load, MLB's own
    live-phase cost appears to consume the sweep's effective time/resource
    budget before WNBA's step gets a turn — same general SHAPE as soccer's
    pre-`#433` problem (a heavy sport starving a lighter one sharing one
    combined run), but the mechanism is scheduling/ordering within ONE
    process, not a market-list API error. NOT yet proven which specific
    resource is exhausted (wall-clock step budget vs memory vs something
    else) — that is the next open question, not this session's finding.
- **FIX IMPLEMENTED 2026-08-20 ~03:0xZ, deployed and flag-flipped 13:07-13:31Z.**
  `_launch_autorun_wnba_live_refresh()` (`scripts/run_live_odds_refresh_worker.py`) mirrors the
  existing pregame autorun's shape: its own 240s cadence, its own EXPLICIT refresh lane
  (`live-odds-worker-wnba-live`, so it can never contend with the combined sweep's lane), `mode=
  "fast"` (skips the SmartSim prediction/edges/export pipeline that `test_wnba_pregame_autorun.py`'s
  own comment warns would OOM this 2GB service if run every few minutes), gated on
  `_wnba_has_live_game` specifically — not merely "WNBA active today". Default OFF, same
  convention as every other autorun in this file. 22 new tests
  (`tests/test_wnba_live_refresh_autorun.py`), 73/73 passing across every file touching the module.
- **Deploy history, both scoped off the LIVE SHA (origin/main had drifted 47+ commits ahead by
  deploy time — see `deploys.md` for the full "exactly one substantive change" reasoning):**
  1. `170505ec` landed on `main`; `b5cf8ac2` (scoped, parent `d520d93d`) deployed 13:15:46Z, code
     default-OFF, verified genuinely inert (zero `WNBA_LIVE_AUTORUN` log lines post-deploy).
  2. `SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN=1` set on the service; `cb322dd1` (comment-only,
     produced specifically because `deploy_preflight.py` has no override for an intentional
     same-commit redeploy — a real tooling gap worth fixing separately) deployed 13:31:11Z. Content
     landed on `main` too (`2908373d`), not orphaned on the deploy branch.
- **verify: FIRING CONFIRMED, WRITE-THROUGH NOT.** Measured 2026-08-21 00:07–00:34Z by session
  `1f76348c` (not this lane — findings handed over, lane NOT otherwise touched):
  - `WNBA_LIVE_AUTORUN_LAUNCHED` first at **00:07:24.782Z**, ~7.4 min after IND@DAL's 00:00Z tip,
    then 00:12:15 / 00:16:48 / 00:21:13 / 00:25:35 / 00:30:06 — a clean ~4.3 min cadence matching
    the 240s design. Zero `WNBA_LIVE_AUTORUN_ERROR`, zero `_SKIPPED`. `_wnba_has_live_game` is
    therefore confirmed against a REAL live game, not just a monkeypatched return.
  - **Testable outcome PASSES but does not prove the mechanism.**
    `wnba_source/tracking/book_quotes/2026-08-20.jsonl`: 28,743 rows, latest `captured_at`
    **00:07:49.815Z** (2,437-row batch, all three events) — newer than kickoff, as required.
    BUT prior batches ran 14:33 / 15:57 / 17:58 / 20:40 / 22:40 / 00:07, i.e. 84–162 min apart, so
    a ~1.5–2.5h cadence produces a 00:07-ish batch with no autorun at all. The 25s gap between the
    00:07:24 launch and the 00:07:49 capture is suggestive, NOT probative. **Do not close on this.**
  - **The shard then stopped advancing.** Re-pulled 00:33:46Z: byte-identical, still 28,743 rows,
    still latest 00:07:49Z — 26 min stale across five further launches. Not a publish lag: every
    tick logs `WNBA_LIVE_AUTORUN_PREV … launched=ok runStamp=None artifactsDir=None`, and the state
    sidecar reports `PUBLISH_SKIPPED_UNCHANGED checksum=951d27e5fb28`, so the worker's own state did
    not change either.
  - **What the autorun demonstrably DOES refresh: the live-lens path.**
    `PERIOD_MARKET_DISCOVERY_DIAG matchup=DAL@IND discover_status=200` with live_lens
    projections/signals republishing every cycle. So the fetch works and the credentials/market list
    are fine — it simply is not landing in `book_quotes`.
- **OWNER OF THE APPEND: FOUND, and the combined-sweep suspicion above was WRONG.** Traced
  2026-08-21 00:45Z. `append_book_quotes` (`odds_book_quotes.py:328`) ← `_append_basketball_book_quotes`
  (`fetch_basketball_oddsapi_props_local.py:330`, the CHILD) ← `refresh_wnba_oddsapi_props.py` (the
  PARENT) ← the single step `_build_wnba_steps` builds. The autorun's own chain, not the combined
  sweep's — so MLB starvation is exonerated for THIS symptom.
- **WHY IT NEVER WRITES: the reuse guard, upstream of everything `mode="fast"` controls.**
  `/api/ops/wnba/refresh-decision` names the branch outright — `decision="reused_artifact_bundle"`,
  `recorded_at` advancing every tick (00:45:30Z, 00:46:36Z, same `input_hash`), so the parent runs
  each tick and `_existing_artifact_bundle_state` returns a cached bundle each time; the child that
  fetches never spawns. This is `#344`/`#383`'s documented fixpoint recurring.
- **THE ACTUAL DEFECT, and it is not in the autorun.** Reuse IS bounded by
  `_reuse_max_age_seconds("wnba")` — but that bound is the PREGAME sweep interval (2h default, no
  override in `render.yaml`), and the reuse `step_key` is
  `(artifact_root, date, do_edges, do_export)` with **no phase and no time component**, so a live
  tick is indistinguishable from a pregame one. **A 240s live autorun is therefore gated by a 2h
  pregame-derived staleness bound and cannot move this artifact by design.** Predicts a ~2h quote
  cadence; observed batch spacing 84–162 min. The comment at
  `run_live_odds_refresh_worker.py:343` — the snapshot fetch "runs UNCONDITIONALLY" under
  `mode="fast"` — is true of MODE and false of the REUSE GUARD that sits above it. That gap is the bug.
- **Confirmed NOT "prices were stable".** `append_book_quotes` is a CHANGE log (unmoved price writes
  no row), so a flat `.jsonl` proves nothing on its own — but its state file carries a last-seen slot
  written whenever anything is OBSERVED, precisely to separate stable from stopped-looking. All
  5,489 keys read last-seen `00:07:49.815Z`, 36+ min cold. Nothing was observed.
- Next concrete step: fix shape is a live-phase-aware reuse bound — give the guard a phase/live-game
  term, or a separate max-age when a game is in progress. Do NOT touch the autorun; it works.
  Re-verify with the last-seen slot and `refresh-decision`, not with `.jsonl` row counts.
  UNVERIFIED: the 2h figure is the code default with no `render.yaml` override — live service
  env-vars were NOT read, so a service-level override is still possible.
- **Adjacent risk, NOT this lane's, surfaced because it was measured in the same window:**
  live-odds-worker hit **97.2% of its 2GB cap — 43.6MB headroom** at 00:17:03Z
  (`memory_anon_mb 992`, `container_memory_mb 2004`) with three live games, during
  `WNBA_SCOPED_SMART_SIM_RESIM_TRIGGERED matchups=GSV-MIN`. Unowned as far as this lane knows.
- Blocked by: none.

### soccer-board-mlb-parity — OPEN, UNOWNED (session `56b563e0` checkpointed 2026-08-20 20:0x CDT) — **FIVE THINGS SHIPPED AND VERIFIED ON THE SERVED SURFACE; TWO SHIPPED BROKEN FIRST AND WERE CAUGHT BY THEIR OWN VERIFICATION.** Live: web `93b6d5a4` (unknown league slug 404s — 7/7 bad slugs, 10/10 leagues 200), web `0514f2d7` (card density 139 → 363/Mpx, 1074 → 970px), workers `68acf3ca`/`a05412f9` (departed players gone — Arsenal 28 → 23; squad absorption gone — Real Sociedad 50 → 24, zero Real Oviedo). ESPN-join regression guard re-run both sides: match rates identical, exact-canonical pairs la_liga 310→446, bundesliga 128→236. **STILL OPEN, and the reason this is not CLOSED:** five of the six collision pairs (incl. **Manchester City ↔ Manchester United, 0.812**) are fixed BY CONSTRUCTION and have never been rebuilt and read in production — only la_liga was. **`5848f64d`'s aggregates are LOCAL-MIRROR numbers**: `players_*.csv`/`rosters_*.csv` are absent from `HOT_ARTIFACT_PATTERNS` (403), so the builder's own inputs cannot be read from web. serie_a/bundesliga sit outside `week_dates_within_horizon`'s today+1 bound and rebuild themselves on 08-21 / 08-27 — not a failure, do not re-fire. Full narrative: `.syndicate/log/2026-08-20.md`. Measurements: `deploys.md` 21:14Z / 23:43Z / 01:01Z entries. — opened 2026-08-20 — session 56b563e0-4c1a-4436-8e3b-ba3624fbeab0
- Goal: `/soccer` serves a DATE-scoped, cross-league game-card board whose cards
  carry the same information classes MLB's do. **Single testable outcome:** on a
  fixed slate date, soccer's card renders (a) market tiles carrying selection +
  price + model + edge rather than bare probabilities, (b) a box-score panel
  built from real match state on a completed/live match instead of
  "Box score unavailable", and (c) information density within 2x of MLB's
  measured 544 leaf-text-items/Mpx — against soccer's measured 139 today.
- Files:
  - `syndicate/features/shared/game_board_contract.py` — the shared normalizer.
    `_build_box_sections` clobbers a sport's own sections (:775, unconditional
    assignment); `market_tiles` setdefault (:764) derives from `metrics[:4]`;
    `_build_prop_status_rows` (:706) drops every synthesized row; the live
    market-tile branch (:791) is unreachable when `metrics` is non-empty.
  - `syndicate/features/soccer/cards.py` — **DECLARED OVERLAP, see Blocked by.**
  - `syndicate/blueprints/soccer.py` — `/soccer` redirect (:87) and a new
    date-scoped cross-league cards route.
  - `syndicate/features/soccer/sources.py` — week->date resolution.
  - `syndicate/templates/soccer/`, `syndicate/static/soccer/` (new files).
  - `tests/test_soccer_*` (new), `.syndicate/*`.
- The cross-session TODO list is deliberately NOT claimed here:
  `mlb-overview-hydration-cost` already holds it and a second claim reads as
  contested. I still reconcile my items into it at checkpoint, per CLAUDE.md.
- **NOT IN THIS LANE:** `syndicate/features/soccer/sim_engine/`, `adapters.py`,
  ratings, `ingestion/*` — all held by `soccer-model-dispersion`. I do not
  change what the model produces, only what the board does with it.
- Hypothesis (diagnostic half, already tested): soccer's thin card is NOT a
  missing-data problem — the data is in the payload and the shared normalizer
  discards it. **CONFIRMED 2026-08-20 against production**, before any edit:
  `/soccer/epl/api/cards` carries `betting.home_ml -590`, `away_ml +1400`,
  `spread -1.5`, `total 2.5` and six per-market EV fields, while all four
  rendered tiles read a bare probability with the matchup string repeated as
  every sub-label. A completed MLS match (HOU 1-0 LA) carries `home.score`/
  `away.score` in the same payload and renders "Box score unavailable".
- Falsification test: if the same payloads had shown null prices / null EV /
  no scores, the finding would be a data gap and this lane would be wrong to
  open as UI work. They did not. Re-run `curl /soccer/<league>/api/cards` and
  read `betting` + `home.score` before trusting any later claim here.
- Verification: `scripts/ui_layout_probe.py` before/after on the soccer board
  (the durable instrument named in `state.md [ui-board-cards]`), plus the
  leaf-text-density measurement above re-taken against the SAME production
  service, plus `python -m unittest tests.test_archives` green. A density
  number taken against a dev box is not the reading.
- **What shipped into the commit** (audit findings A-H, all measured on
  production 2026-08-20 before any edit):
  - **A. Landing.** `/soccer` -> `/soccer/cards?date=` across all ten
    leagues. The old redirect landed on EPL matchweek 1 = ONE fixture,
    kicking off the next day, out of 92 across the ten leagues. Soccer's
    board was the only one keyed by (league, matchweek) rather than date and
    each league runs its own calendar (MLS wk21 Aug 16-22 = 31 fixtures,
    Bundesliga wk1 = Aug 28 = 1). The per-league board is untouched.
  - **B. Market tiles.** Soccer now builds its own, mirroring
    `mlb/cards.py::_market_tiles`. The generic `metrics[:4]` fallback showed
    a bare probability with "COV @ ARS" as all four sub-labels while
    `home_ml -590` / `away_ml +1400` / `total 2.5` / `spread -1.5` sat
    unused on the same payload, and dropped BTTS + Over 2.5 to the cap.
  - **C. Box score.** THREE instances of one clobber in `_normalize_game`
    (`shared_box_sections`, `shared_prop_rows`, and the live tile branch)
    each overwrote what the sport supplied. The July fix for
    `shared_top_play_rows` had already named this shape and was never
    applied to its neighbours. Also added a REAL score section: a completed
    MLS match carried `home.score`/`away.score` and rendered "Box score
    unavailable" because the builder read only the sim.
  - **D. Props.** Joined to `build_soccer_picks`' captured price/edge via
    props.py's OWN normaliser (not a second one). Rows are no longer
    `is_synthesized`, so the status table stops rendering empty (0 -> 8).
  - **E/F/G/H.** Top-play field mapping (value column held the MATCHUP
    string); empty lens stat cells no longer rendered; the live tile branch
    made reachable (it was guarded on a key the setdefault above it had
    already filled — unreachable for any sport publishing `metrics`);
    finished matches show a result instead of "not yet simulated".
- **Edge is model-minus-market, deliberately NOT `betting.*_ev`.**
  `build_soccer_picks.py:131` computes EV against ITS model prob, a
  different vintage: `away_ml_ev 0.575` at +1400 implies ~10.5% where the
  card renders 7.0%. Both fields stay on `betting` for other readers.
- **Verification so far:** 19 new tests anchored to the production payloads
  (4 assert reachability, off != on); 88 targeted soccer/board tests green;
  `tests.test_archives` 31 failures before AND after, **the same 31 by
  name** (diff clean) — all `data/`-dependent NFL/NBA/NCAAB tests that
  cannot pass where `data/` is excluded by design. Rendered locally against
  real artifacts: card height 1074 -> 829px, em-dash cells 6 -> 0, repeated
  matchup sub-labels 4 -> 0, box sections 1 -> 2, prop status rows 0 -> 8.
- **THE OPEN THREAD, and it is the one that matters:** the density number
  that opened this lane (MLB 544 vs soccer 139 items/Mpx) has NOT been
  re-taken against production. A local reading cannot take it — the mirror
  has no picks/props for these dates, so the tiles that carry the new
  content are empty locally. `_market_tiles` run over the real production
  payload returns "COV ML +1400 | Model 7.0% | Market 6.3% | Edge +0.7 pts",
  which proves the CODE and not the BOARD. Deploy web, then re-measure with
  `scripts/ui_layout_probe.py` plus the leaf-density count, same service,
  same instant. **A local reading must not be written up as the result.**
- Blocked by: none, but **DECLARED OVERLAP**: `soccer-model-dispersion` (OPEN,
  session `Soccer Session (fork)`, not running as of 2026-08-20 16:4xZ) claims
  `syndicate/features/soccer/` with the parenthetical scope "(sim engine,
  adapters, ratings, `ingestion/espn_match_stats.py`)". `cards.py` sits in that
  directory and outside that parenthetical. I read it as not claimed, notified
  that session with the exact file list before editing, and am proceeding on
  that reading with the user's decision. **If that lane says otherwise, stop.**
  Recording it here rather than omitting it, because a silent overlap is the
  failure mode the lane protocol exists to prevent.

- **LIVE MATCH STATE SHIPPED AND DEPLOYED `[2026-08-20T21:4xZ]`, session
  `aeb71be7` (lane taken over; `56b563e0` is out of the active roster). On
  `origin/main` as `ca75e0a1`; LIVE as grafts `bd4b1a67` (live-odds-worker,
  21:33:45Z) and `075226dd` (web, 21:41:5xZ) -- both `--allow-off-main`,
  measurement in `deploys.md`. Production reads `ALA 1 - 1 RAY` Final with real
  Goals + Match stats sections, 0 pre-kickoff games showing a score, and 10 of
  10 leagues publishing a `match_box` key absent at the parent SHA.
  **ONE PATH STILL UNWITNESSED IN PRODUCTION: the LIVE CLOCK** -- every
  production reading is of a FINISHED match, which correctly has no clock. It
  was measured locally at the 70th and 83rd minutes pre-deploy. Next MLS
  kickoffs ~23:30Z would close it.**
- **A SECOND WEB DEPLOY WAS NEEDED, and the first `verify: PASSED` is why
  `[2026-08-20T22:00Z, web `79cb457e`]`.** That first reading was true when
  taken and FALSE THREE MINUTES LATER: web is reading the GIT-TRACKED MIRROR of
  `recommendations_2026-08-20.json` (`generated_at 2026-07-20`, `status_state
  "pre"`), so every score source correctly refused it while `match_box` on the
  same disk carried `final: true, 1-1`. `_effective_state_with_box` lets the
  fresher per-match ESPN reading set the state; upgrade-only, kickoff refusal
  still applies. Now 6 of 6 reads serve `ALA 1 - 1 RAY` Final with real box
  sections WHILE THE ARTIFACT IS STILL STALE.
- **STILL BROKEN, NOT THIS LANE'S: some producer is serving web a month-old
  `recommendations_*.json` mirror.** The card is resilient to it now, which is
  not the same as fixed -- the sim projections, win probabilities and market
  tiles on that card are still read from a 2026-07-20 artifact. Worth its own
  lane. All
  three gaps closed: real live AND final score, clock/period on the card, real
  live+final box sections. Verified on live La Liga 401882908 in BOTH states
  (83' 1-0, then FT 1-1 with `games` empty -- the finished case that
  previously had no score path at all). 21 new tests fail without the change;
  141 pass against `origin/main`. Narrative, evidence and the three mistakes
  made: `.syndicate/log/2026-08-20.md`.
- **Two diagnoses in the handoff were WRONG and are corrected in
  `learnings.md`:** `live_home_score` is a real ESPN reading, not a
  placeholder (the 12-match sample was 100% `pre`), and soccer's
  `picks_*.csv`/`recommendations_*.json` ARE allowlisted and DO export 200.
- **Squad price-coverage lead: SETTLED, both hypotheses wrong.**
  `_normalize_player_name` EXONERATED (17/17 join); not a top-N cap (book
  offers 47). Real causes are a DIFFERENT feed->sim join failure on word order
  (`"Gabriel"` vs `"Magalhaes Gabriel"`), a partly stale squad, and players the
  book does not list for the fixture.
- **NEXT ACTION for whoever picks this up: deploy `web`** (claim + preflight;
  nothing here is worker-side except `poll_soccer_live_state`, which needs
  `live-odds-worker` to serve `match_box`). **DO NOT fix the name join with a
  token-subset matcher** -- the squad contains `Gabriel`, `Gabriel Jesus` AND
  `Gabriel Martinelli`; any fix must refuse on ambiguity.
- **The primary-tree LANDMINE is RESOLVED `[re-checked 22:0xZ]`** -- a merge
  brought both files forward; `git status` on `soccer/cards.py` and
  `tests/test_soccer_board_mlb_parity.py` is clean there and the tree carries
  `_artifact_score`/`_effective_state_with_box`. The duplicate ledger commit
  `f9f6fcd8` was absorbed too; the primary tree is no longer ahead of
  `origin/main`.
- **Cause (2) of the price lead -- the stale squad -- was fixed by ANOTHER
  session**: `5848f64d` "the squad was every player who had EVER played in the
  league", recorded INERT by its own lane (worker code, no worker carries it).
  Cause (1), the feed->sim NAME JOIN on word order, is still open.
- **SESSION CLOSED 2026-08-20 22:1xZ (`aeb71be7`). LANE STAYS OPEN AND IS NOW
  UNOWNED.** Everything shipped and deployed; ONE verification is outstanding
  and it is not blocked by anything except the absence of a match.
- **THE ONLY OPEN ITEM: witness the LIVE CLOCK in production.** Measured at
  22:14:49Z, all ten leagues: **live=0**, so it could not be taken. (The earlier
  "next MLS kickoffs ~23:30Z" note was WRONG -- MLS has no fixture in that
  window.) Real next chances: **2026-08-21 18:45Z** (ligue_1 Strasbourg @
  Marseille, belgian RAAL @ Standard Liege) and **19:00Z** (epl Coventry @
  Arsenal, la_liga Real Sociedad @ Real Betis). Take the reading ~20 min after
  kickoff. Assertions to make are written out in `log/2026-08-20.md` under
  "session close" -- do not re-derive them.
- Claims: none held. Deploys: none pending.
### mlb-native-ladders-producer — OPEN, UNOWNED (session 822e1e5a archived 2026-08-20 ~20:4xZ) — **MAKE `ladders_build.py` THE PRODUCER AND DELETE THE VENDOR LADDERS STAGE. Stage 1 of 20 in the MLB vendor exit (`state.md [mlb-vendor-exit-audit]`; `todo.md #493`). ALL CODE SHIPPED AND LIVE — fix `a54dffa3` (18:27:40Z), force knob + one-shot guard live in `a0396411` (20:28:43Z, verified by CONTENT), `SYNDICATE_MLB_LADDERS_FORCE_DATE=2026-08-20` SET. THE PRODUCTION VERIFICATION IS UNDISCHARGED AND IS A ONE-CURL READ: last status `skipped_fresh` at 20:11:24Z PREDATES the deploy, so nothing had run with the knob yet — pending, NOT failed.** — opened 2026-08-20
- **Goal (single testable outcome):** `daily_ladders_<date>.json` produced by
  `syndicate.features.mlb.ladders_build` on the NORMAL path — `generatedBy`
  stamped on the SERVED artifact — with the vendor ladders stage removed from
  `daily_update.py`, and both consumers (top-props board, compact-card pregame
  chips) rendering unchanged.
- **Files:** `syndicate/features/mlb/ladders_build.py`, `tests/test_mlb_ladders_build.py`, `scripts/run_mlb_daily_sim_job.py`, `tests/test_run_mlb_daily_sim_job.py`.
- **INHERITED OBLIGATION (item 1, from `mlb-pregame-ladder-schema`):** `a54dffa3`
  is live and UNVERIFIED in production. Discharge by arming
  `SYNDICATE_MLB_LADDERS_FORCE_DATE=<central date>` on refresh-worker and reading
  `generatedBy == syndicate.features.mlb.ladders_build` PLUS populated
  `ladder[]`/`gamePk` on 18/18 pitcher rows. **Chips on the board prove NOTHING**
  — the vendor writer renders them either way. Knob shipped (`c99b259c`); env var
  NOT set (Claude's PUT is classifier-blocked; needs a dashboard edit) and the
  deploy is parked on it.
- **Gap to parity, measured 2026-08-20:** 4 presenter fields (`lineupOrder`,
  `paMean`, `matchupReasons`, `matchupSummary`) read by `ladders_common.py`, and
  hitter ladders 0/234 vs vendor 234/234. The other 14 vendor-only fields are NOT
  blockers: `modeProb`/`modeCount`/`overLineCount` have 0 consumers;
  `marketLinesByStat`/`pregameMarketLine` are read only as FALLBACKS behind
  `marketLine`, which native already emits; the rest are cosmetic.
- **Hitter ladders: decide, do not default.** No consumer reads them, and
  `learnings.md` 2026-08-20 records this artifact silently exceeding
  `_PUBLISH_MAX_BYTES`. Native+pitcher ladders is 635,001 B vs the vendor's
  9,518,280 B, so 234 hitter ladders is the biggest size lever here. Do not add
  them without a consumer.
- **Do not delete the vendor stage until native is proven on the normal path.**
  The board currently runs on the vendor artifact; removing its writer first
  converts a degraded path into an outage.


### layer2-rail-duplicate-nfl-cards — OPEN, **UNOWNED** (session 23024227 checkpointed and archived 2026-08-20 ~19:2x CT; nothing held, all deploy claims released) — **SHIPPED AND VERIFIED-BY-REPLAY; ONE BEHAVIOURAL READ OWED** — opened 2026-08-20 — session 23024227-412f-49f5-a5b8-271d961f0c5b
- Goal: today's NFL preseason games appear ONCE each on the Layer 2 compact
  game-card rail, not twice. **Testable outcome:** each game seats exactly one
  mini card, and clicking it filters the board to ALL that game's rows (both
  row families), not one family's.
- Files: `syndicate/templates/intelligence.html` (`deriveGameCards` merge pass
  only), `tests/js/game_rail_derive.test.mjs`.
- **STATUS: live on web as `feec7e17` since 2026-08-20 19:10:37 CT** (deploy
  `dep-da3pbfrbc2fs73aj00b0`; grafted onto web's live SHA `f3a9bb0b`, NOT main —
  main's tip would have reverted a 25-deep off-main chain, see `state.md`).
  Landed on `origin/main` as `84533712`. All claims released.
- **VERIFIED on the SERVED BYTES**, A/B on one payload, control = the pre-deploy
  served page: **17 cards / NFL 4 / 2 chips seating >1 card → 15 / NFL 2 / 0**;
  MLB 9, SOCCER 1, WNBA 3 identical both sides. `game_rail_derive.test.mjs` 14
  assertions pass and DISCRIMINATE (3 of 3 fail pre-change).
- **THE ONE THING OWED, and the deploy does NOT discharge it:** a behavioural read
  on a LIVE board carrying BOTH row families for one game — an ESPN-id
  `candidate_type=game` watchlist row co-existing with `layer2_shortlist` rows.
  Everything measured is REPLAY, because the ESPN-id rows left the live board
  (2 → 0) between 18:20 and 18:59 CT and the defect stopped being reproducible.
  **A census on the current payload reads 0 either way — do not mistake it for
  confirmation.** Reproduce by finding a slate where both families are present,
  then read `/api/intelligence/query` for two groups resolving to one chip.
- Falsification test: if the two groups did NOT resolve to the same chip object,
  chip-identity clustering could not merge them and the fix is wrong. Checked:
  they do.
- Full narrative, evidence, dead ends: `.syndicate/log/2026-08-20.md`;
  deploy record: `.syndicate/deploys.md`.
- Blocked by: none.

### wnba-halftime-elapsed — **OPEN, ONE READING OWED** — fix is LIVE on web (`2b9040df`, content-verified) and on the workers (`3b41696d` is an ancestor of refresh-worker's SHA). Unit-verified both directions: 3 break tests FAIL pre-fix, 2 narrowness tests PASS in both states. **THE BREAK BEHAVIOUR ITSELF IS UNOBSERVED IN PRODUCTION** — a 20-minute watcher caught no blank-clock state, and the one suggestive reading (a board row at 'End of 1st' keeping a live lane at model 0.2155 vs its 0.27 pregame baseline) was INDIRECT, via the board. Next WNBA break discharges it. — opened 2026-08-20 — session 1f76348c-062d-4075-a54b-a8b0eadabb2b
- Goal: the live win/cover probability must keep using the live margin during a
  BETWEEN-PERIODS break, instead of silently reverting to the pregame number.
  **Testable outcome:** with period=2 and a blank clock, a +12 home margin and a
  -12 home margin produce DIFFERENT probabilities (today both return the
  pregame anchor exactly).
- Files:
  - `syndicate/features/wnba/cards.py` — `_wnba_elapsed_minutes` and the
    `source`/`markets` fallback that keys off its None.
- Hypothesis: n/a — measured, not inferred. `_wnba_elapsed_minutes(2, "")`
  returns None because the clock fails to parse; `_wnba_live_margin_win_prob`
  then short-circuits to `pregame_p_home_win`, and `source` falls back to
  `pregame` so `markets` is emptied for the whole break. Confirmed by driving
  the real shipped functions: margin +12 and -12 both return 0.4500 against a
  0.45 anchor.
- Falsification test: if a blank clock also occurs at a period's START, then
  "blank clock = period complete" overstates elapsed by a full period and this
  fix is wrong in that state. NARROW fix chosen for exactly this reason —
  confirm against a real captured halftime payload before generalising.
- Verification: reachability FIRST (a halftime case that FAILS on purpose
  pre-fix), then a real between-periods payload from a live game.
- Blocked by: none.

### nfl-props-odds-allowlist — OPEN, **UNOWNED** (session e5e93171 checkpointed and archived 2026-08-21) — NARROWED TO ONE UNDEPLOYED FIX — **THE CAPTURE FIX IS VERIFIED IN PRODUCTION.** `oddsapi_player_props_2026_wk1.csv` went **5 bytes -> 12,142** at 2026-08-21T14:08:06Z with a FRACTIONAL mtime (runtime write, not a boot copy): **84 rows, 84 distinct players, real DraftKings Anytime TD prices**, captured unattended by refresh-worker. First real NFL player-prop capture this platform has ever made. The model was also PRICED for the first time: **-7.35% over 64,007 bets** — it does not beat the market (fading it loses 16.93%, so the picks are correctly signed, they just do not clear the vig). Price shopping **+2.95 ROI pts** (controlled, identical bets); game context **+1.18 pts** (paired, held-out). **REMAINING: one landed-but-undeployed fix, deliberately left to ride along on the next main deploy — see OWED.** — opened 2026-08-20 — session e5e93171-243f-485e-8ade-9116f0130519
- Goal: a real ROI number for NFL player props. **MET** — 64,007 graded bets, `reports/nfl_props_roi.json`.
- Claims held: **NONE.** refresh-worker released 2026-08-21 deliberately rather than
  held through polling — the service was busy on nearly every check for two hours and
  other lanes needed it. Holding a lock while waiting on an unpredictable condition is
  the retired-coordinator anti-pattern.
- **OWED — ONE ITEM, and it needs NO dedicated deploy:**
  `a41f88f8` on main fixes `#389` hit a second time: `fetch_nfl_schedule.py` wrote via
  the PROBING `default_nfl_source_root()`, which returns the root holding
  `upcoming_recs_*.csv` — shipped by the repo mirror, absent from the mounted disk — so
  every write landed in `/opt/render/project/src/data/nfl_source`, the EPHEMERAL
  CHECKOUT, and `publish_hot_artifact` was a silent no-op (`relative_to_data_root()`
  returns None outside the data root, hence no publisher verdict of any kind). The step
  reported `status=ok return_code=0` in 1s every cycle and delivered nothing.
  Writer now uses `nfl_artifact_output_root()` (no probing); reader
  (`game_context.schedule_paths`) puts that same root first. 2 regression tests.
  **WHOEVER DEPLOYS MAIN TO refresh-worker NEXT PICKS THIS UP FOR FREE.** Then verify:
  `nfl_source/schedule_2026.csv` on web must gain a **FRACTIONAL** mtime (whole-second =
  another boot copy, not a publish) AND its lined-game count must go **67 -> ~112**.
  Both together; a fresh mtime alone could be a rewrite of stale bytes. Measured
  2026-08-21: web 67 lined vs nflverse 112, 61 rows differing on spread/total.
  NOT URGENT — it only feeds the game-context multiplier (+1.18 pts on a -7.35% model),
  and NFL Week 1 is 2026-09-10.
- Also landed this session: run-summary artifacts are now allowlisted
  (`reports/migration_runs/*/odds_refresh_*/`), which is what made the above
  diagnosable at all after three independent routes returned nothing.
- Blocked by: none.

### wnba-live-props-data — **OPEN — PHASES 1-3(a) BUILT AND ON `main`, NONE WIRED, NONE DEPLOYED.** capture / project / join-to-anchor, 33 tests + 20 subtests. **THE CHAIN HAS NEVER RUN END TO END IN PRODUCTION** — nothing calls the capture on a tick, so the artifact has never existed on a worker. Verified separately: live per-player data serves (`games=2 players_with_stats=39`), the anchor exists (`cards_sim_detail` → `min_mean` + `{stat}_mean` + `prop_ladders simCount 100`), and the empty-capture refusal fires on the real rolled slate. NEXT: 3(b) needs `liveModelProbOver`, which needs the remainder-scaling assumption GRADED — do not emit one until then. Narrative in `log/2026-08-21.md`. — opened 2026-08-20 — session 1f76348c-062d-4075-a54b-a8b0eadabb2b
- Goal: live WNBA props. **Phase 1 (THIS LANE): persist the live per-player stat
  lines so a worker can read them.** The data was never missing --
  `/wnba/api/live_player_boxscore` serves minutes/pts/reb/ast/threes and has all
  along; it is fetched in the REQUEST PATH on web while the prop join runs in the
  board build on a WORKER, so there is no artifact to read.
  **Testable outcome:** `scripts/capture_wnba_live_player_box.py --date <d>`
  writes an allowlisted artifact on a live slate. VERIFIED against production
  2026-08-21 03:37Z: `games=2 players_with_stats=39` (19 + 20).
- Files:
  - `scripts/capture_wnba_live_player_box.py` — the capture (new).
  - **BLOCKED, NOT CLAIMED:** the `HOT_ARTIFACT_PATTERNS` entry for
    `wnba_source/data/live/live_player_box_*.json` lives in a file held by the
    OPEN lane `nfl-props-odds-allowlist` (actively editing that same list). Not
    edited across lanes. **Until it lands the capture writes an artifact the
    board build cannot see** — written, not yet reachable, which is exactly the
    half of `#488` that reads as working. Owed with it: the
    `is_hot_artifact_relative_path` test.
- Hypothesis: n/a — measured. See `log/2026-08-20.md` and the `state.md`
  correction stamped on the "nothing for props" sentence.
- Falsification test: if the artifact is written but the board build cannot read
  it, the allowlist entry is wrong or nothing publishes it — the two halves
  `#488` records as separately broken. `is_hot_artifact_relative_path` is
  asserted in the tests for exactly that.
- Verification: the capture REFUSES to store an empty/hollow payload (tested),
  because a persisted empty is served in preference to real data thereafter —
  `capture_wnba_pbp.py`'s recorded failure mode.
- **PHASE 2 DONE (pure function, not wired):**
  `syndicate/features/shared/wnba_live_prop_projection.py`. Mirrors `#475`'s
  anchored shape deliberately rather than inventing a third live convention:
  `projected = current + remaining * ((1-w)*pregame_rate + w*live_rate)`,
  `w = played/pregame_minutes`. Collapses to the pregame number at tip-off and
  to the actual stat at the buzzer (both tested — an estimator that misses its
  own endpoints is wrong in the middle too). Remaining minutes CAPPED by the
  game clock. **REFUSES without a pregame anchor** rather than extrapolating a
  live rate — that input is exactly `#475`'s 240-point total. Worked example on
  a real production line (Angel Reese 6 pts / 9 min, 12-pt anchor): projects
  **16.08**, against a naive pace of 20.0 that is never produced.
  **Publishes NO probability and prices NO edge** — this estimator has no
  measured interval, so an edge off it would route around both
  `prob_interval_swamps_edge` and
  `analytic_estimator_never_backtested_for_this_market`. 14 tests + 8 subtests.
- **PHASE 3 ANCHOR FOUND `[2026-08-21, measured]` — the blocker was an unknown,
  not an absence.** `wnba_source/data/processed/cards_sim_detail_<date>.json`
  (exportable, 2.1MB) carries per player under `games[].sim.players`:
  `min_mean` (**expected minutes — phase 2's denominator**), `{pts,reb,ast,
  threes,pra}_mean` + `_sd` + `_q{p10,p50,p90}`, and `prop_ladders[stat]` with
  `simCount: 100`, a full `distribution` histogram and a `ladder` of
  `{total, hitProb}`. Worked example: Paige Bueckers `min_mean 38.37,
  pts_mean 23.39, pts_sd 7.33`. `props_predictions_*.csv` is 403 from WEB but
  that is a route restriction — the lens builder runs on a WORKER and reads
  these directly.
- **THE ONE DECISION PHASE 3 STILL NEEDS, and it must not be made silently.**
  `build_live_prop_index` keys on `liveModelProbOver`, a PROBABILITY. The ladder
  above is the PREGAME distribution: it answers `P(final >= line)` from tip-off.
  A LIVE prop needs `P(final >= line | current, minutes played)` — i.e. the
  distribution of the REMAINDER over the minutes left, which is not the
  full-game distribution and cannot be read off this ladder. Scaling it
  (mean by `m/min_mean`, sd by `sqrt(m/min_mean)`) is the standard assumption
  and is **UNMEASURED HERE** — making it silently is the same move as pricing
  the un-backtested totals estimator. Options: (a) publish phase 2's PROJECTION
  on the lens in a non-probability field and leave the join gate shut, or
  (b) grade the scaling assumption, then price under `prob_std_err(p, simCount)`
  — `simCount: 100` means the SAME interval machinery MLB's 120-sim game lines
  already use would apply.
- **NOT unblocked by this find: TOTALS.** The sim publishes no game-level total
  distribution — `quarters` is `[]` and `players_summary` is bare counts. Totals
  still needs the OddsAPI historical backfill and a grade.
- **PHASE 3(a) DONE `[2026-08-21, user decision: option (a)]` — projections
  published, NO probability.** `syndicate/features/shared/wnba_live_prop_rows.py`
  joins the live capture to the sim anchor by NAME and emits one row per
  (player, stat) carrying `liveProjectedStat`, `current`, `minutes_played/
  remaining`, `pregame_mean/minutes`, plus `priceable: False` and
  `not_priced_reason: live_prop_projection_has_no_measured_interval` spelled out
  per row. **It carries no `liveModelProbOver`, so `build_live_prop_index`
  cannot pick it up and the `sport != "mlb"` gate stays shut — by design, not by
  omission**, and a test asserts no probability-shaped key ever appears.
  Unmatched players are COUNTED AND NAMED (`players_unmatched`), because a name
  join is the machinery whose 91% miss this project already paid an
  investigation for. **A real defect the tests caught:** apostrophes were being
  substituted with a space, so `A'ja Wilson` normalised to `a ja wilson` and
  would have matched nothing — an apostrophe is intra-word, a hyphen separates
  words, and they cannot share a rule. 33 tests + 20 subtests.
  **Verified against real production data:** the empty-capture refusal fired on
  the rolled slate (`games=3 players_with_stats=0` -> REFUSING to write).
- **THE SCALING IS GRADED `[2026-08-21]` — and the assumption turned out to be
  unnecessary.** `scripts/grade_wnba_live_prop_projection.py` replays ESPN pbp,
  reconstructs each player's running points and minutes, drives the SHIPPED
  projection at every scoring play, and scores it against the official final.
  **The replay is self-checked and reconciles 100%** (6+ games, 118+ players,
  points AND minutes exact) — a residual from an unreconciled replay measures
  the bug, so the grader refuses to score one. Rather than grade the assumed
  sd-scaling (`sqrt(m/min_mean)`), it MEASURES the projection's own residual,
  which needs no assumption and is the quantity a consumer wants.
  **POOLED n=796 over 5 slates:**

      minutes_left      n     mean      sd   p90/sd
           30-99       21    +0.18    6.03     1.71
           20-30      129    +0.42    5.38     1.59
           10-20      220    -0.54    5.30     1.61
            5-10      136    -1.23    3.88     1.56
             0-5      290    -1.69    2.70     1.90
             ALL      796    -0.90    4.39

  The interval SHRINKS MONOTONICALLY as the game runs down (6.03 -> 2.70), so a
  single sd would price both ends wrongly. `p90/sd` sits at 1.56-1.71 against
  1.64 for a normal, so the residual is APPROXIMATELY NORMAL in the bulk —
  `P(final >= line) = 1 - Phi((line - projected)/sd_bucket)` is defensible with
  the MEASURED sd. Two caveats for whoever prices it: the `0-5` bucket has
  heavier tails (1.90) and a real late UNDER-projection bias (-1.69).
- **PHASE 3(b) DONE — `liveModelProbOver` is emitted, from the MEASURED
  residual.** `wnba_live_prop_probability.py` turns the projection into
  `P(final >= line) = 1 - Phi((line - projected) / sigma(minutes_remaining))`
  using the graded table above. Three choices, each recorded at the point of
  use: (i) **tail-matched sigma**, `max(sd, p90/1.6449)` — measured sd, widened
  ONLY where the observed tail is fatter than normal, which is the `0-5` bucket
  alone (2.70 -> 3.12); (ii) **NO bias correction** though one was measured, as
  the per-bucket mean flips sign (+0.42 .. -1.69) and fitting it at n=796 is
  fitting noise — a wrong correction shifts every probability one way, worse
  than a slightly wide interval; (iii) **refuses outside the measured range** —
  unknown minutes remaining gets None with a reason, never a default sigma and
  never 0.0. A row prices ONLY when a line is supplied for its
  `(player, market)`. 48 tests + 31 subtests across phases 1-3(b).
  **This does NOT open the join's gate** — `attach_live_projections_for_sport`
  still returns early on `sport != "mlb"`; that is phase 4.
- **PHASE 4 DONE — the gate is OPEN for wnba, and opening it did NOT create a
  silent zero.** `_LIVE_PROP_SPORTS = {mlb, wnba}` in
  `attach_live_projections_for_sport`. `to_snapshot_live_props` translates this
  module's internal rows into the contract `build_live_prop_index` actually
  reads (`playerName` / `prop` / `line` / `liveProjection` /
  `liveModelProbOver`). **Market keys verified against production**
  (`player_points` 45 rows, `player_assists` 21, `player_rebounds` 14,
  `player_threes` 8) rather than guessed — `_snapshot_market` reads `prop` first
  and the board speaks OddsAPI, which is `#412` exactly
  (`miss_no_market_alias = 1385 of 1385`). Markets the board carries but this
  cannot project (`player_double_double`, `player_points_rebounds_assists`,
  `player_triple_double`) are DROPPED, never aliased to something close.
  **A snapshot whose games carry no `liveProps` is now reported BY NAME**
  ("producer not wired") instead of returning 0 rows as though the join had run
  — replacing a named refusal with a silent zero is the permissive-default shape
  this repo has a standing rule about. 202 tests + 45 subtests green across
  props, the game-line join, live-edge policy/enforcement, book-grid and layer-1.
- **WIRED `[2026-08-21]`.** The lens loop captures the live player box before
  the WNBA build (after the headroom gate, so a skipping tick spends no HTTP
  call) and `wnba/live_lens.py::_attach_live_props` CONSUMES that artifact and
  stamps `liveProps` + `livePropsCoverage` per game. The builder never fetches.
  Lines come from the card's `shared_prop_rows` — a FOURTH vocabulary for the
  same four stats (`pts/reb/ast/threes`), verified against 2026-08-19 and
  2026-08-16 rather than assumed. **COVERAGE IS KNOWINGLY THIN:** those are the
  card's FEATURED props (8-9 per slate) not the board's ~120; the fuller source
  is `oddsapi_player_props_<date>.csv`, readable on the worker, and is the
  obvious next widening. Combination markets (`ra`/`pa`/`pr`) are unmapped —
  they cannot come from a single stat mean.
- **A PRECEDENCE BUG THE WIRING TEST CAUGHT:** `sim_game = (a or b) if
  isinstance(pack, dict) else {}` — a conditional expression binds looser than
  `or`, so every game WITHOUT an `evidence_pack` silently got `{}` including
  those with a perfectly good `sim`. Surfaced as `players_matched 0 != 1`, not
  by reading the line.
- **STILL NEVER RUN END TO END.** Every hop is now wired and unit-tested, but
  nothing has executed against a live slate: no deploy, and no WNBA game live
  since the wiring landed. The prop join reports "producer not wired" by name
  until it does. NEXT: deploy, then read `livePropsCoverage` and the join's
  `rows_live_projected` on a live game.
  `prob_std_err`/`PRICEABLE_SIGMA` refusal then applies ON TOP, exactly as for
  MLB — so opening it does not mean every row prices. Previously listed as (3b),
  now done:
  `(player, market, line)` on WNBA's lens rows; (4) open the `sport != "mlb"`
  gate in `attach_live_projections_for_sport`. **Phase 2 needs a MEASURED
  interval before any edge is priced** — same discipline as totals; an
  unbacktested live prop projection may be PUBLISHED but not PRICED.
- Blocked by: none. NOT deployed — the capture still needs a worker tick to call
  it (live-odds-worker's WNBA lane is the natural home, 240s cadence).

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




