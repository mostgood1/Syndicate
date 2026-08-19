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

### live-game-line-projection — OPEN, UNOWNED (session `live-gameline-eval` checkpointed 2026-08-16 15:2xZ) — **BOTH HALVES SHIPPED. v2 IS PROVEN TO RECORD — 3,748 ROWS, 2026-08-17. WHAT IS STILL UNMEASURED IS THE v2 DISCRIMINATOR AND DEDUP; THE EVALUATION HAS NOT STARTED.**
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
### convergence-phase7-crps — OPEN — opened 2026-08-17 — session: model-sim-track
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

### soccer-model-dispersion — OPEN — opened 2026-08-18 — session: soccer-sport-owner

- Goal: soccer's model stops losing to the closing line on at least one league.
  **Testable outcome:** `scripts/backtest_soccer_h2h_calibration.py` re-run over the
  SAME 1,112 matches / 9 leagues reports model multiclass Brier **<= market** on at
  least one league that is not `belgian_pro_league`, and mean model `stdev(P home)`
  rises from **0.1575** toward market's **0.1811**. Baseline to beat is committed:
  `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json`.
- Files:
  - `scripts/backtest_soccer_h2h_calibration.py`
  - `scripts/build_soccer_artifacts.py`
  - `scripts/validate_soccer_vs_market.py`
  - `syndicate/features/soccer/` (sim engine, adapters, ratings)
  - `tests/test_soccer_feature_loaders.py`, `tests/test_soccer_projections.py`,
    `tests/test_build_soccer_artifacts.py`, `tests/test_soccer_adapter.py`
  - `reports/soccer_backtest/`
- **NOT IN THIS LANE, and the reason matters:**
  `syndicate/features/shared/soccer_projections.py` and
  `syndicate/features/shared/book_margin_model.py` are being edited RIGHT NOW by
  session `7c041356` under informal lane `modelled-fair-edge` (uncommitted work,
  `.current-lane` marker, no lane header). They are the BOARD-side adapter; this lane
  is the SIM side. Do not take them.
- Hypothesis: the model is UNDER-DISPERSED, not merely inaccurate. Measured
  2026-08-15: mean model `stdev(P home)` **0.1575** vs market **0.1811**, narrower in
  **8 of 9** leagues; eredivisie's reliability curve is too timid at both ends
  (predicted 0.144 -> actual 0.000; predicted 0.823 -> actual 1.000). Two independent
  routes agree on the shape (production artifact stdev 0.1364 / 166 rows).
- Falsification test: sharpen the distribution and re-run. **If the Brier gap does not
  close while stdev rises to market's, under-dispersion is NOT the binding constraint**
  and the cause is the ratings/inputs, not the spread. That is a real outcome and must
  be recorded, not retried with a bigger knob.
  Second, cheaper falsifier first: `adapters._DEFAULT_SIMULATIONS` is **300**, which is
  **+/-2.9pp of pure Monte Carlo noise** against a gap of **+0.0139**. **Raise the sim
  count and re-run BEFORE changing any model term** — if the gap moves on sim count
  alone, the 2026-08-15 number was partly noise and every conclusion drawn from it
  needs re-reading.
- Verification: the re-run's own JSON in `reports/soccer_backtest/`, compared
  league-by-league against the 08-15 baseline on the same match set. **A gap that
  improves on a DIFFERENT match set proves nothing** — the 1,112 are the control.
- Blocked by: none.

**INHERITED, DO NOT RE-DERIVE:**
- **A leak-free backtest ALREADY EXISTS** — `backtest_soccer_h2h_calibration.py`,
  committed `5a94b134`. The retired-for-leakage artifacts are
  `data/soccer_source/*/validation/*_backtest_*.csv`, a DIFFERENT thing. I generalised
  those into "soccer accuracy is unmeasured" earlier today and was wrong.
- **MLS CANNOT be backtested from its current source** — `fetch_asa_mls_team_history`
  returns undated season aggregates; no `as_of` can repair it. Non-MLS leagues only.
- **Do not publish `model_edge_pct` on the strength of a partial win.** Standing
  decision: a model that loses to the closing line emits edges that are noise, and its
  errors are systematically on favourites, so those edges point at underdogs.
  Publishing is a SEPARATE decision from closing the gap.
- Fixes #1 (seeds), #3 (accent join), #4 (as-of) were built and tested and are safe to
  ship; **#2 removes a stale BLOCK and does not make the number publishable.**

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

### nhl-model-owner — OPEN — CHECKLIST FULL PASS + dead-gate REMOVED + market-comparison backtest (`#470`) + faceoff-zone track (EV/OZ/DZ, `#463`) all CLOSED — session: nhl-model-owner
- Goal: NHL sim engine reaches the same deep-dive rigor MLB/soccer already have —
  **testable outcome MET**: `python scripts/nhl_sim_input_checklist.py` exits 0.
  Extended goal, also MET: does the resulting model show any edge over a
  real market — `scripts/grade_nhl_predictions_vs_market.py` (`#470`)
  answers that, pulling real production data, not just the local mirror.
  Third extension, also MET: does the faceoff-driven shot-share mechanism
  actually use zone-appropriate data — three per-team faceoff indices
  (EV-blended, offensive-zone, defensive-zone) built and wired. Full
  detail: `docs/ai_context/hockeysim_engine_reference.md` §1–§2o, §8/§8b,
  `docs/ai_context/nhl_model_inventory.md`, `todo.md` `#463`/`#470`,
  `.syndicate/log/2026-08-19.md` (full narrative by
  file/verified/believed/dead-ends across all checkpoints today),
  `.syndicate/state.md` `[nhl-sim-engine]`.
- Files: `syndicate/features/nhl/sim_engine/hockeysim/**`, `data/nhl_source/**`,
  `scripts/nhl_*.py`/`scripts/grade_nhl_predictions_vs_market.py`/`scripts/calibrate_nhl_*.py`
  (producer/calibration/backtest scripts), `docs/ai_context/hockeysim_engine_reference.md`,
  `docs/ai_context/nhl_model_inventory.md`. Shared artifact-publisher allowlist
  module: touch-and-released repeatedly, each addition committed and released
  same-turn — not currently claimed.
- **Dead gate CLOSED, not left open**: `HockeyTeamFeatures.blocks_per_60`/
  `penalties_per_60` were confirmed dead (proven, not assumed) AND confirmed
  to have no legitimate consumption mechanism that wouldn't double-count
  already-live real data. Removed from `HockeyTeamFeatures`/`TeamRates`
  and every call site across 15 files, not just documented.
- **Market-comparison backtest (`#470`) built and extended to real production
  data** — the instrument that answers "does this show an edge," distinct
  from every calibration the checklist proves. `--source production` pulls
  the public `/nhl/api/cards/dates` route (no admin token). Found and fixed
  two real bugs by checking real responses, not assuming: stale-duplicate
  prediction files, and `lookahead_applied`'s actual meaning (date-fallback,
  not live adjustment). Measured n=14-15 moneyline/total — explicitly NOT a
  powered verdict, stated with equal weight to every other caveat.
- **Faceoff-zone track (§2m/§2n/§2o) fully closed**: `_faceoff_multipliers`
  was gated EV-only but fed an all-situations blend — three per-team
  indices now close that, in order: EV-blended (fallback tier 1),
  offensive-zone (preferred over EV when present, tier 0 — a refinement,
  not a separate mechanism), defensive-zone (an ADDITIONAL multiplicative
  layer composed with the OZ/EV chain, not a fourth tier — winning a DZ
  draw both suppresses the opponent's shots AND springs the winner's own
  transition chance, a dual effect a fallback chain can't represent).
  `zoneCode` confirmed empirically relative to the WINNER (two draws at the
  identical rink coordinates showed opposite zone labels depending who
  won), OZ/DZ confirmed genuinely independent (correlation 0.69, not
  ±1.0). Every index verified not to shift the league-wide shot average
  (992-pairing round-robin each time, all landed under 0.5% — one under
  0.02%) and reachability/priority/gating-tested, not just populated.
- Verification: `python scripts/nhl_sim_input_checklist.py` — full PASS.
  356 hockeysim/nhl tests pass (up from 254 at session start). Nothing
  deployed (offline artifact-producer + engine-wiring work only; next NHL
  refresh-worker/web deploy picks it up). All commits pushed to
  `origin/main`, confirmed via `git merge-base --is-ancestor` after every
  push — latest confirmed tip `fc7c717d` (this lane's work) with
  `361d0498` (another session's checkpoint, pushed alongside) on top.
- Blocked by: none

### basketball-model-owner — OPEN — **#468's WIRING FIX LIVE on BOTH refresh-worker (`f13ea05e`) and live-odds-worker (`e1d1bcf4`), verified end-to-end with real data pre-deploy (uncached-date build + stale-schema rebuild, both correct). #469 (boxscore-capture root cause — earlier "no caller found" hypothesis was WRONG, see below) FOUND+FIXED+DEPLOYED to live-odds-worker (`e1d1bcf4`). #467 LIVE on refresh-worker. #462 LIVE+VERIFIED on web. #464 CLOSED. Runtime effect of #468/#469 on a real served prediction NOT YET OBSERVED — WNBA smart-sim fires per-game, not on a fixed interval, and the next real game (TOR@WSH) is ~19h out from 2026-08-19T04:xxZ.** inventory pass SHIPPED (#460-#469 filed) — opened 2026-08-18 — session: basketball-model-owner
- Goal: Basketball's counterpart to the Modeling (MLB), Soccer, and Football sessions — bring the NBA/WNBA smart-sim engine up to `docs/ai_context/model_engine_standard.md`. Original scope (checklist + pipeline-trace + inventory docs, #440 fallback reachability) SHIPPED. Extended scope this session: `#461` (WNBA `games` column, code-fixed, deployed, and now WIRED — `#468`), allowlist gap `#462` (live), population gap `#464` (closed), dead-gate bug `#467` (live), reachability defect `#468` (wiring shipped AND deployed), boxscore-capture stall `#469` (root cause found and fixed, deployed). Current goal: observe #468/#469's effect on a real served WNBA prediction once the next game's pregame sim cycle fires (~19h out); no further code work identified as ready until that reading comes back. NCAAB still has no sim engine — documented design gap, deliberately not backfilled.
- Files: scripts/basketball_sim_input_checklist.py (new), docs/ai_context/basketball_sim_engine_reference.md (new), docs/ai_context/basketball_model_inventory.md (new). **Write access:** `syndicate/features/shared/basketball_props_smart_sim.py` (`#467`'s dead-gate fix, `#468`'s wiring fix — 3 new functions: `_team_adv_stats_cache_is_fresh_local`, `_import_advanced_stats_builders_local`, `_ensure_team_advanced_stats_asof_local`), `syndicate/features/shared/artifact_publisher.py` (`#462`'s `HOT_ARTIFACT_PATTERNS` additions only), `vendor/{wnba,nba}_betting_repo/src/*/cli.py` (`#461`'s cache-freshness guard), `scripts/refresh_wnba_oddsapi_props.py` + `syndicate/features/shared/basketball_boxscores_history.py` (`#469`'s silent-success fix + ESPN User-Agent change). Read-only over the rest of `basketball_props_*.py`, `syndicate/features/{nba,wnba,ncaab}/**`. Does NOT touch board_enrichment.py, run_live_odds_refresh_worker.py, or wnba_fixture_identity.py (held by wnba-live-tier / wnba-phase2-migration).
- Hypothesis (#468's second half, CLOSED — was WRONG): "no caller of update-boxscores-history/backfill-boxscores found anywhere" was true only of the VENDOR CLI's own functions. A PARALLEL Syndicate-owned mechanism (`_ensure_player_logs_for_props_refresh` → `_bootstrap_local_boxscores_history_for_props` → `bootstrap_boxscores_history_local`, ESPN-based) IS reachable from `main()` and runs on every autorun tick. The real cause, measured 2026-08-19: `_bootstrap_local_boxscores_history_for_props` checked the file's cumulative `history_rows` (always >0 once any history exists) instead of the current pull's own `rows`, so a fetch that added zero new rows still reported success — silently, for weeks (`boxscores_history.csv`'s max game date frozen at 2026-06-30 while mtime kept advancing every ~2h tick). Root-caused further: ESPN's site API soft-blocks a custom bot User-Agent (`syndicate/1.0`) from Render's datacenter egress IP (200 OK, empty body) while a browser-shaped UA and/or residential IP works.
- #469 fix: (1) `basketball_boxscores_history.py` tracks `days_checked`/`days_fetch_failed` so an empty scoreboard payload is distinguishable from a genuine no-games day; (2) `refresh_wnba_oddsapi_props.py` keeps the existing leniency (does not hard-block predict-props) but now emits a loud `flush=True` `BOXSCORE_BOOTSTRAP_STALLED` marker instead of a silent, healthy-looking log line when new rows are genuinely zero; (3) ESPN User-Agent changed to browser-shaped. Verified via a live unmodified-code ESPN pull (674 real rows, 2026-08-09..08-18) both before and after the UA change — did not regress the working path.
- Verification: `#461`/`#462`/`#467`/`#468`(wiring)/`#469` — all code DONE and all now LIVE (refresh-worker `f13ea05e`, live-odds-worker `e1d1bcf4`, web `b775255a`). Runtime effect of `#468`/`#469` on a real served prediction still unobserved — not stuck, just untriggered: WNBA smart-sim generation is tied to actual game slates (newest `smart_sim_*.json` artifact was 5.9h old at last check, predating this deploy), and the next real game is ~19h out. Re-check `/api/ops/artifacts/export?pattern=wnba_source/*/team_advanced_stats_*.csv` for a fresh as-of file, and worker logs for `BOXSCORE_BOOTSTRAP_STALLED` (absence of it on the next tick is the `#469` positive signal), once that window passes.
- Blocked by: none.

### repo-coordination — OPEN — **deployment, assignment and documentation. NOT any sport, model or engine.** — opened 2026-08-18 — session: repo-coordination

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
  - `land` reports the ledger checkers rather than gating on them.
  - The new deploy predicate has never gated a real deploy; `OFF_MAIN` has never
    fired in anger; no preflight receipt consumed live. First real deploy tests it.
  - ~100 stale worktrees under `C:/tmp` need a human pass before reaping.
  - `deploys.md` (834 KB) and `lanes_closed.md` (838 KB) have no size discipline
    and no checker.
- **Blocked by:** none.


### football-model-owner — OPEN — **NCAAF MARGINS CALIBRATED (SD 1.74 -> 15.37, ratio 1.06). Totals still 1.67x, carrier IDENTIFIED (scoring rate 20.8->53.9%). Two model leaks fixed, 2026 data built. Payload experiment NULL.** — opened 2026-08-18 — session: football-model-owner
- Goal: NFL + NCAAF get the input-inventory, pipeline-trace and advanced-analytics
  treatment MLB and soccer have. **Testable:** a gating checklist exists and runs;
  every model input is leak-free and reachable; board defects measured on the
  SERVED payload.
- Files: `syndicate/features/football/**`, `syndicate/features/ncaaf/cards.py`,
  `syndicate/features/nfl/preseason_cards.py`,
  `syndicate/features/shared/{publication_adapter,game_board_contract}.py`,
  `scripts/{football_sim_input_checklist,backfill_nfl_historical_odds,generate_smartsim2_ncaaf_projections}.py`,
  `docs/ai_context/{model_engine_standard,football_sim_engine_reference,nfl_feature_payload_preregistration}.md`,
  `tests/test_{ncaaf_board_slate_coverage,published_projection_means,asof_team_form}.py`
- **NOT claimed:** `syndicate/features/shared/artifact_publisher.py` — held by
  `basketball-model-owner`; allowlist patterns handed to them via `send_message`.
  `scripts/deploy_preflight.py` — `repo-coordination`'s charter; defect handed over.
- Status: **14 commits, all on `origin/main`, 0 unpushed.** 3 web deploys live and
  measured (`5fdabc46`, `4c3b0aa5`, `841b6d84`). `CFBD_API_KEY` set by the user.
- **BLOCKED ON NOTHING.** Two handoffs outstanding with other lanes (above).
- **Phase 3 DONE, n=269: NULL** (`dCRPS +0.0226`, 0.97 SE). Payload does not
  ship; Phase 4 moot. The ratings path carries 4.2x the leverage and production
  already uses it.
- **NCAAF MARGINS CALIBRATED** — SD 1.74 -> 15.37 (market 14.46, ratio 1.06), max
  margin 7.80 -> 50.64 (market 49.50). Cause was the rating SOURCE: PPA is a
  per-play rate, replaced by SP+ (points/game), backtested r 0.506 vs 0.372 over
  ~740 games/season in two independent pairs.
- **TOTALS 1.67x, CARRIER IDENTIFIED, NOT FIXED.** `total = drives x score% x
  pts/score`; score% runs 20.8% -> 53.9% across the slate against a real ~35-45%,
  while drives barely move. **Three scalar fixes are DEAD and must not be
  retried** (index clamp, yardage weights, scoring_environment weights) — all
  damp inputs to a loop whose outputs compound. The fix is in `drive_simulator`'s
  conversion and is SHARED WITH NFL, so it needs its own NFL-impact measurement.
- **NCAAF ratings leak fixed** (r 0.663 -> 0.509 as-of, 30% inflation). Opener
  unaffected — no in-season history means the prior-season fallback.
- **2026 data built and slate-complete** (94-team coverage verified); five of
  seven builders were unrunnable and are fixed at the choke point.
- **OWED:** (1) **NOTHING IS DEPLOYED** — production still serves 0 of 51; the
  worker autorun has not fired since the key landed and no football code is live.
  (2) NCAAF opener verification, PASS = ~51 of 51 non-null
  `predictions.home_mean`. (3) totals scoring-rate compression — evidence in
  `log/2026-08-19.md`. (4) allowlist `smartsim2_*projections_*.csv` — with
  `basketball-model-owner`. (5) web cannot pass preflight — with
  `repo-coordination`.
- **NOT A CAPABILITY, don't mistake for a gap:** NCAAF props. No route, no
  module, and `SmartSim2SimulationOutput` has NO player-level fields — the engine
  never tracks players. Props would be a build, not a wiring fix.
- Narrative + evidence: `.syndicate/log/2026-08-18.md`. History: `lanes_history.md`.

### wnba-edge-263 — OPEN — opened 2026-08-19 — session: wnba-edge-263
- Goal: WNBA Layer 2 rows carry a real `model_edge_pct` (or an honestly-labeled
  approximation) instead of `None` on every row. **Testable outcome:**
  `/api/board/layer2-shortlist?sport=wnba` on a live slate reports
  `per_sport_ingest.wnba.rows_with_model_edge > 0`, up from the measured
  **0 of 1,072** candidates on 2026-08-19 (verified live, by content — see
  below).
- Files:
  - `syndicate/features/shared/basketball_props_recommendations.py` —
    `_build_model_map` (line 132) reads only `mean_*`/`pred_*` columns from
    `props_predictions_<date>.csv` and silently drops the `sd_*` columns that
    file already carries (confirmed present in the writer,
    `basketball_props_predictions.py:346-357`).
  - `syndicate/features/shared/wnba_projections.py` — `WnbaProjectionIndex` /
    `attach_wnba_projections` hard-null `model_prob_over` /
    `edge_vs_market_pct` on every row (`probability_fields: "null by
    design"`), because the `model` dict they read from
    `props_recommendations_<date>.csv` is means-only by construction.
  - `tests/test_wnba_projections.py`, `tests/test_basketball_props_recommendations.py`
  - **Read-only reference, do NOT edit without raising with
    `basketball-model-owner`** (holds write access to both):
    `syndicate/features/shared/basketball_props_predictions.py`,
    `vendor/wnba_betting_repo/src/wnba_betting/props_edges.py`. Also do not
    touch `syndicate/features/shared/artifact_publisher.py`
    (`HOT_ARTIFACT_PATTERNS`) — same owner, raise instead of take, per that
    lane's own "hand off, don't take" convention with `football-model-owner`.
  - **Coordination note:** this lane sits inside `basketball-model-owner`'s
    active WNBA smart-sim domain (`#460`-`#469`) but does not claim any file
    they hold — `basketball_props_recommendations.py` and `wnba_projections.py`
    are outside their stated write-access list. Flagged, not blocked.
  - **ADDED 2026-08-19, spreads/totals sub-fix:**
    `syndicate/features/shared/wnba_game_projections.py`,
    `tests/test_wnba_game_projections.py` — checked against every OPEN lane's
    Files block, zero overlap (not under `syndicate/features/{nba,wnba,ncaab}/**`,
    `basketball-model-owner`'s read-only scope — lives in `shared/`).
    **`tests/test_wnba_game_market_projections.py` DROPPED from scope on
    inspection** — it tests `syndicate/features/wnba/cards.py`
    (`_source_betting`/`_source_game_market_recommendations`), a different,
    unrelated WNBA UI path that never imports `wnba_game_projections.py` and
    that this sub-fix does not touch. Originally listed on a name-match with
    "wnba_game_market_projections" alone; wrong, corrected before writing code.
  - **BLOCKED, not taken: `scripts/refresh_wnba_oddsapi_props.py`.**
    `lane-guard` caught this live — `basketball-model-owner`'s Files block
    (line 583) explicitly holds WRITE on this exact file for `#469`'s
    silent-success fix. The producer half of the spreads/totals sub-fix
    (`_smart_sim_projection_index`, `_sim_projection_fields`,
    `_GAME_CARDS_HEADER_ORDER` — all three at the lines scoped above) needs
    this file. **Not editing it.** Proceeding on the consumer half
    (`wnba_game_projections.py`) against the NEW column names as a contract,
    with synthetic fixtures carrying them, so it activates the moment the
    producer half lands — by either owner.
- Hypothesis: the sim already computes a real per-market probability/edge for
  WNBA props. `props_edges.py::compute_props_edges` prices each `play` using
  `sd_pts`/`sd_reb`/... (preferring the simulated sd, falling back to a
  league-level constant sigma when absent — `_safe_sd_series` +
  `fallback_sig`), and that edge already reaches
  `props_recommendations_<date>.csv`'s `plays`/`top_play` columns. The
  `wnba_projections.py` path that feeds Layer 2 is a SEPARATE, later-built join
  that goes back to `props_predictions_<date>.csv` for MEANS ONLY and
  explicitly nulls the probability fields — it never reads what `props_edges.py`
  already computed. So this is very likely a **threading problem** (surface an
  edge that already exists downstream), not a **new-model problem** (derive a
  distribution from scratch) — confirmed on production 2026-08-19:
  `props_recommendations_2026-08-19.csv`'s `model` cell is means-only
  (`{'pts': 12.15, 'reb': 3.94, ...}`, no `_sd` keys) for every player sampled.
- Falsification test: pull a live slate's `props_recommendations_<date>.csv`
  and check whether `plays[].edge`/`ev_pct` on the SAME (player, market, line)
  as a Layer 2 row is a real, sport-appropriate probability edge and not a
  placeholder/constant. **Partial disconfirmation already observed**: the one
  row sampled 2026-08-19 (Veronica Burton) had `ladders: []` and
  `sim_ladders: []` — empty — so those two columns are NOT a usable source;
  `plays[].edge` itself is the one still untested. If `plays[].edge` turns out
  equally degenerate for most rows, the fix has to go one level deeper into
  `props_edges.py`'s own sd inputs, and this lane's scope grows — say so rather
  than forcing the threading story to fit.

**RUN 2026-08-19, on production `props_recommendations_2026-08-19.csv` (20
players, GSV/MIN/TOR/WSH — the exact two games that reached Layer 2 today).**

- **`plays[].edge` HALF-CONFIRMS.** 165 play entries across 16 of 20 players
  (4 have zero plays); **140 distinct edge values, range 0.0007-0.412, mean
  0.065** — a real, varying computation, not a placeholder or constant. The
  `props_edges.py` sd-based pricing IS alive in production. `ladders`/
  `sim_ladders` are empty on ALL 20 rows (0/20) — confirmed dead, drop them
  from the plan entirely.
- **BUT COVERAGE IS THE CATCH, and it lands exactly on today's one prop row.**
  Veronica Burton's `plays` covers ast/pa/ra/reb/threes — **not `pts`** — while
  the ONE prop that actually reached today's Layer 2 shortlist is her
  `player_points` line (13.5). `props_edges.py` never priced that specific
  (player, market) pair, so a join keyed on (player, market, line) would leave
  **this exact row** at `None` even after the fix. Threading `plays[].edge`
  helps WNBA props in general wherever `props_edges.py` covered the market —
  it would not have moved a single number on today's board.
- **AND THE BIGGER MISS: 11 of today's 12 WNBA rows are `game`-kind
  (spreads_alt/totals_alt/h2h), not props.** Those come from a completely
  separate file, `game_cards_<date>.csv` (pulled and inspected live), whose
  columns are `pred_margin, pred_total` — **means only, no sigma column at
  all**, not even an unused one. `basketball_props_smart_sim.py` computes
  `final_total_sigma`/`final_margin_sigma` in-memory (its `QuarterSummaryLocal`
  dataclass) but nothing persists them into `game_cards`. This is the SAME
  shape of defect as the props one (a real sigma computed, then dropped before
  the artifact boundary) but a DIFFERENT file, and — unlike props — the sigma
  isn't sitting on disk waiting to be read; it has to be added to the
  `game_cards` export first. **This is the higher-leverage half of the fix for
  what the board actually shows today: 11 of 12 rows, not 1 of 12.**
- **SCOPE THEREFORE GROWS, exactly as this test was written to allow for.**
  Two independent sub-fixes, not one:
  1. **Props** (existing scope, coverage-limited): thread `props_edges.py`'s
     `plays[].edge` into the Layer 2 prop row when a (player, market, line)
     match exists; leave `None` honestly when it does not (as it would not
     have today, for Burton's `pts`).
  2. **Game lines** (NEW, higher-leverage, not yet scoped to a file list):
     persist `final_margin_sigma`/`final_total_sigma` out of
     `basketball_props_smart_sim.py`'s in-memory sim into `game_cards_<date>.csv`
     at export, then give `board_enrichment.py`'s WNBA game-projection path
     (wherever it reads `game_cards`) a probability-space edge for
     spreads/totals/h2h the same way MLB's margin model already does for game
     markets. File-level trace for sub-fix 2 is NOT done yet — next step.
- Verification: on a live production build, `per_sport_ingest.wnba` reports
  `rows_with_model_edge > 0` with values that are NOT constant/degenerate
  across rows, and each row carries a field that HONESTLY states whether its
  edge came from a simulated sd or a fallback sigma — never silently upgrading
  a heuristic default to look like a measured one (mirrors `#242`'s house rule
  against fabricated values). Add a test asserting a row with no usable sd
  anywhere stays `None`, never a fabricated number. **Given the measured
  coverage gap, "done" for props means bounded, attributable coverage — not
  100% — and the game-line sub-fix needs its own verification once scoped.**
- Blocked by: none.

**GAME-LINE PRODUCER TRACED 2026-08-19 — BETTER THAN SCOPED. Not a sigma-persistence
job; the sim already publishes real probabilities and nothing reads them.**

Pulled today's actual artifacts, `smart_sim_2026-08-19_GSV_MIN.json` and
`_WSH_TOR.json` (609KB/606KB, the REAL vendored engine output — not the
`basketball_props_smart_sim.py` `_local` fallback I traced first, which uses a
different, legacy `quarters` key that this real payload doesn't even have). The
persisted `score` block already carries, per game, from real Monte Carlo
(**n_sims=100**, worth flagging as thin):

```
home_mean, away_mean, margin_mean, total_mean,
home_q/away_q/margin_q/total_q: {p10, p50, p90},
p_home_win, p_away_win, p_home_cover, p_total_over
```

`p_home_cover`/`p_total_over` are computed **against the market line the sim
was given** (`market.market_home_spread=2.0`, `market.market_total=164.5` for
GSV/MIN) — i.e. these are real, model-free, empirically-simulated probabilities,
not a fitted/Normal approximation. `periods.q1..q4/h1/h2` carry the identical
shape per segment. No raw draw array is persisted anywhere (checked `intervals`/
`intervals_1m` too) — only 3-point quantiles, so a full arbitrary-line CDF isn't
directly available, only the one line the sim priced.

**The break, confirmed against these exact files:**
`_smart_sim_projection_index` (`scripts/refresh_wnba_oddsapi_props.py:2812-2851`)
— the function that populates `game_cards_<date>.csv`'s `pred_margin`/
`pred_total` — tries `payload["quarters"]` first (**absent**, that key belongs
to the `_local` fallback engine, not this real payload), falls through to
`payload["periods"]["q1..q4"]`, and pulls out **only `home_mean`/`away_mean`
per quarter**, summing them. Confirmed by exact match: summed quarters equal
`score.margin_mean`/`score.total_mean` to the JSON's own precision
(-9.32/163.08, identical to what's live in `game_cards`'s `pred_margin`/
`pred_total` today). **Everything else in `score` — `p_home_win`,
`p_home_cover`, `p_total_over`, `margin_q`, `total_q` — is read out of the same
already-open file and then dropped.** This is a cheaper, higher-confidence fix
than the sigma-threading plan: no reconstruction needed, just read three more
keys off a payload the function already parses.

**REVISED SUB-FIX 2, replacing the "persist final_margin_sigma/final_total_sigma"
plan (that plan targeted the `_local` fallback engine, which is not what's
running):**
1. `scripts/refresh_wnba_oddsapi_props.py` — `_smart_sim_projection_index`:
   also read `payload["score"]["p_home_win"]`, `["p_home_cover"]`,
   `["p_total_over"]`, `["margin_q"]`, `["total_q"]`; write them as new
   `game_cards` columns (additive — do not touch `pred_margin`/`pred_total` or
   reorder `OUTPUT_COLUMNS`, per the existing `#262`/reader-compat rule already
   in this file's own comments).
2. `syndicate/features/shared/wnba_game_projections.py` —
   `attach_wnba_game_projections`: for **h2h**, a policy choice now exists —
   keep `_margin_win_prob(pred_margin)` (current, "the one sanctioned
   transform") or switch to the sim's own `p_home_win` directly (model-free,
   arguably better, but a second producer for the same number if not done
   carefully — flag, don't decide unilaterally). For **spreads/totals AT THE
   SIM'S OWN MARKET LINE**, `p_home_cover`/`p_total_over` can populate
   `model_prob_over` directly — real progress. For **spreads_alt/totals_alt AT
   A DIFFERENT LINE** (10 of today's 11 game rows), the single-point
   probability does not apply; would need a `margin_q`/`total_q`-derived
   approximate CDF, honestly labeled as coarse (n=100) — or stay `None` for alt
   lines specifically, which is still strictly better than today (main lines
   go from 0% to priced).
3. Still deliberately NOT touching `h2h`'s `edge_vs_market_pct` gate — that
   null is a **stated model-validation policy decision**
   (`model_skill: sample_games=0, "model never backtested"`), not a plumbing
   gap, and stays with whoever owns validating the margin model.
- Next concrete step: confirm with `basketball-model-owner` (adjacent active
  WNBA lane) whether `p_home_win` vs `_margin_win_prob` is theirs to decide,
  since it touches validated-model territory, before writing code for h2h.
  Sub-fix 2's spreads/totals-at-market-line half has no such dependency and can
  proceed first. **Message sent 2026-08-19, queued for after their in-flight
  turn.**

**SPREADS/TOTALS-AT-MARKET-LINE SUB-FIX — FULLY SCOPED 2026-08-19, no
dependency on `basketball-model-owner`'s answer. Ready to implement.**

Choke points confirmed by reading, not guessed — every `game_cards` write path
already funnels through ONE function, so this is a 2-file change, not N:

1. **`scripts/refresh_wnba_oddsapi_props.py:2812` `_smart_sim_projection_index`**
   — extend to also pull `payload["score"]["p_home_cover"]`,
   `["p_total_over"]`, and `payload["market"]["market_home_spread"]`,
   `["market_total"]` (the LINE the sim priced — needed for the gate below,
   NOT assumed identical to `game_cards`'s own `home_spread`/`total`, even
   though measured equal on today's two games). Store all four alongside the
   existing `pred_margin`/`pred_total` in the same index entry.
2. **`_sim_projection_fields` (same file, line 2515)** — single choke point,
   confirmed by grep: all **3** `game_cards` row-building call sites (2591,
   2729, 2798) spread `**_sim_projection_fields(...)` into the row, so
   returning the 4 new keys from this ONE function threads them everywhere
   with no per-branch duplication.
3. **`_GAME_CARDS_HEADER_ORDER` (line 2209)** — **MUST add the 4 new column
   names to this list, appended at the end.** `csv.DictWriter` here uses
   `fieldnames=_GAME_CARDS_HEADER_ORDER` with the DEFAULT `extrasaction`
   (`"raise"`) — an unlisted key in a row dict is a hard `ValueError` at build
   time, not a silent drop. That's a safety net (a missed column fails the
   build loudly) but it means step 1-2's new keys are INERT, not additive,
   until this list is updated in the SAME change. `wnba/cards.py`'s
   `_load_game_cards_csv_rows_from_keyvalue` reads via plain `csv.DictReader`
   with no fixed fieldname allowlist, so the READ side needs no change.
4. **`syndicate/features/shared/wnba_game_projections.py`**:
   - `WnbaGameProjectionIndex`/`load_wnba_game_projections` — index the 4 new
     columns alongside `pred_margin`/`pred_total`.
   - `attach_wnba_game_projections` — for `spreads`/`totals` (h2h excluded,
     blocked on the message above): compute `edge_vs_market_pct` **only when
     the row's own `line` matches the entry's `sim_market_home_spread` /
     `sim_market_total` within a small float epsilon** (main lines only —
     10 of today's 11 game rows are `spreads_alt`/`totals_alt` and will
     correctly stay `None` under this gate, with an honest NEW reason string,
     e.g. `"sim priced only the game's own line (<X>); this is an alternate
     line"` — distinct from the current blanket
     `"sim ships a margin/total mean, not a distribution"`, which will
     become false once this ships and must not linger as the reason on rows
     it no longer describes).
   - **REUSE, do not hand-roll a 5th edge computation.** `prop_projections.py`
     (`_no_vig_over_probability`, line 747) and `live_edge_policy.py`
     (`live_edge_unavailable_reason`, line 61) are both pure, already-shared,
     already-imported-elsewhere functions (WNBA's OWN prop path imports
     `live_edge_unavailable_reason` already). Call the SAME pattern
     `prop_projections.py:918-946` uses (`fair = _no_vig_over_probability(row)`,
     `edge = round((model_prob - fair) * 100.0, 2)`, live-suppression check
     first) rather than inventing new math — the alternative (a full switch to
     `attach_projections`/`project_game_market`'s shared pipeline) would fix
     `#329`'s "fourth producer" duplication for good but means touching
     `prop_projections.py`, which MLB/soccer/NFL also depend on — bigger,
     riskier, and NOT required to close `#263`. Flagged as a follow-on, not
     taken here.
5. **Tests**: `tests/test_wnba_game_projections.py`,
   `tests/test_wnba_game_market_projections.py` — cases: (a) row line == sim
   market line → `model_prob_over`/`edge_vs_market_pct` populate; (b) row line
   != sim market line (alt) → stays `None`, new reason string, never a
   fabricated number; (c) `_GAME_CARDS_HEADER_ORDER` round-trip test (write
   then `DictReader` back) so a future column addition can't silently regress
   into the same `extrasaction` trap; (d) h2h untouched by this sub-fix
   (regression guard while the h2h question is still open with
   `basketball-model-owner`).
- Verification: on a live build, `game_cards_<date>.csv` carries the 4 new
  columns; `/api/board/layer2-shortlist?sport=wnba` shows `model_edge_pct` non-null
  on spreads/totals rows sitting AT the main line, still null (with the new
  reason) on alt lines — both readable in `per_sport_ingest.wnba`.

**CONSUMER HALF IMPLEMENTED, TESTED, COMMITTED 2026-08-19 — NOT PUSHED.**
Own worktree (`C:\tmp\syndicate-sessions\wnba-edge-263`, branch
`session/wnba-edge-263`), commit `6135559e`, `git diff --stat` confirmed only
the two intended files touched (318 insertions / 13 deletions,
`wnba_game_projections.py` + `tests/test_wnba_game_projections.py`).
- `WnbaGameProjectionIndex` entries now carry `p_home_cover`/`p_total_over`/
  `sim_market_home_spread`/`sim_market_total`, defaulting to `None` — an older
  `game_cards` row (predates the producer half) degrades to exactly the prior
  behaviour, verified by test, not just asserted.
- `attach_wnba_game_projections` gates spreads/totals `model_prob_over`/
  `edge_vs_market_pct` on the row's line matching the sim's own market line
  (`_lines_match`, 1e-6 tolerance). Reuses `_no_vig_over_probability` +
  `_edge_unavailable_reason` (`prop_projections.py`) and
  `live_edge_unavailable_reason` (`live_edge_policy.py`) rather than a fifth
  edge implementation — same functions MLB/soccer/NFL's game markets already
  call.
- New reason string for alt lines, distinct from the old "not a distribution"
  one which becomes false once the main line prices: `"sim priced only its
  own market line (<X>); this is an alternate line the sim's 3-point quantile
  summary cannot answer"`.
- h2h untouched — verified by a dedicated regression test with the new index
  fields populated, confirming they don't leak into h2h's branch.
- **16/16 tests pass** (9 original unchanged + 7 new): main-line spreads,
  main-line totals, alt-line honest-reason, sim-line-absent degrades to
  original reason, one-sided-book-at-market-line reports via the shared
  reason function, live-market suppression, h2h regression guard. Also ran
  `tests/test_wnba_fixture_identity.py` + `tests/test_wnba_projections.py`
  (69 total) clean — no adjacent regressions.
- **INERT until the producer half lands** — `game_cards` rows have none of
  the 4 new columns today, so this ships zero behavior change on its own.
  Correctly additive: confirmed a build with the columns absent degrades to
  the original mean-only reason via `test_sim_line_absent_keeps_the_original_mean_only_reason`.
- **NOT PUSHED to `origin/main`** — commit sits local to the worktree branch
  pending the producer half (still with `basketball-model-owner`, message
  queued) so the two land together rather than shipping dead columns-reading
  code with nothing to read.

### nfl-player-props-backtest — CLOSED-VERIFIED 2026-08-19 — measured 152,919 rows/2,406 players/4 seasons; 8 of 9 markets beat baseline in AND out of sample; two calibration defects + one allowlist gap flagged. Full write-up `todo.md` `#471`, measurement `deploys.md`. — opened 2026-08-19 — session: nfl-player-props-backtest
- Goal: measure whether `syndicate/features/nfl/player_stats.py`'s rolling
  season-to-date rate model (mean/stdev per player per stat, feeding
  `syndicate/features/nfl/props.py`'s Normal-CDF cover probability) predicts
  anything, across ALL players/weeks/markets — not just the sparse weeks that
  happen to carry real quoted odds. Reference rigor: `scripts/backtest_mlb_props.py`
  (per-market denominators, DNP exclusion, constant-baseline comparison) and the
  MLB pitcher-ladder "ultimate outcome" pattern (`syndicate/features/mlb/pitcher_ladders.py`
  → `k_ladder_targets.py`) as the bar for what a mature player-production model
  looks like. **Testable outcome:** a new backtest script reports, per of the 9
  `STAT_KEYS` in `player_stats.py`, `n`, `mae_model` vs `mae_constant_baseline`,
  and (wherever a real quoted line exists) hit-rate of the Normal-CDF cover call
  against the real settled outcome — run over real, complete nflverse pbp seasons
  already on disk (2022-2025, `data/nfl_source/tracking/nflverse/pbp/pbp_<season>.csv`,
  local historical/static data, not a "Render is truth" live-state question).
- Files (all NEW or read-only — collision-checked 2026-08-19 against every OPEN
  lane in `lanes.md`; zero overlap):
  - `scripts/backtest_nfl_props.py` (NEW)
  - `tests/test_backtest_nfl_props.py` (NEW)
  - Read-only reference (NOT claimed for write): `syndicate/features/nfl/player_stats.py`,
    `syndicate/features/nfl/props.py`, `syndicate/features/mlb/pitcher_ladders.py`,
    `syndicate/features/mlb/k_ladder_targets.py`, `scripts/backtest_mlb_props.py`.
- **NOT claimed, deliberately:** `syndicate/features/football/**`,
  `syndicate/features/ncaaf/cards.py`, `syndicate/features/nfl/preseason_cards.py`,
  `scripts/football_sim_input_checklist.py` — all held by `football-model-owner`
  (NCAAF/game-margin focus, Phase 3 closed NULL). This lane is player-props-only
  and does not touch that lane's files.
- Hypothesis (stated before measuring): the rate model is UNDER-VALIDATED —
  `player_stats.player_rate` has never been backtested against real outcomes at
  all (only used live), and it carries no distribution (confirmed by
  `convergence-phase7-crps`: NFL absent from every projection-spread family
  checked, 165 files/160 dates). I predict it beats a constant per-stat baseline
  on volume markets (attempts, receptions) and underperforms or ties on
  high-variance yardage/TD markets.
- Falsification test: if `mae_model` >= `mae_constant_baseline` on a market, the
  model has no measured value there and that must be reported as such, not
  papered over — same discipline `backtest_mlb_props.py`'s docstring states.
- Verification: a report (written to `reports/` and `.syndicate/deploys.md`)
  with per-market `n`, MAE-vs-baseline, and — for the weeks with real odds
  (`oddsapi_player_props_2025_wk10..22.csv`) — cover hit-rate, with the sample
  size stated next to every number (rule: "a rate, not a count").
- Blocked by: none.

### nfl-player-props-calibration-fix — OPEN — opened 2026-08-19 — session: nfl-player-props-calibration-fix
- Goal: fix the two calibration defects `#471` found and measured but did not
  fix. **Testable outcome, defect 1 (this pass):** `anytime_td`'s predicted
  probability at a rolling rate of exactly 0.0 stops reading as 0% when the
  real hit rate for that bucket is ~13-14% (measured, `reports/nfl_props_
  backtest_2022_2025.json`) — a shrinkage estimator blends the raw small-n
  rate toward a data-derived league baseline, tuned and verified out-of-sample
  via `scripts/backtest_nfl_props.py`'s own existing harness (re-run, not
  rebuilt). **Defect 2 (yardage/count markets overconfident near their own
  mean — predicts ~50% cover, actual ~37-44%) is explicitly SECOND, not
  started this pass** — user instruction was "start with the anytime_td
  shrinkage".
- Files:
  - `syndicate/features/nfl/player_stats.py` — new shrinkage function,
    additive (does not change `player_rate`'s existing signature/behavior for
    any other market).
  - `syndicate/features/nfl/props.py` — `_nfl_prop_model_probability`'s
    `anytime_td` branch switches to the shrunk rate.
  - `tests/test_nfl_player_stats.py`, `tests/test_nfl_props.py` — updated/new
    tests for the shrinkage behavior.
  - `scripts/backtest_nfl_props.py` — read/run only this pass (used to tune
    and verify the shrinkage constant out-of-sample); not expected to need
    edits, but not ruled out if the tuning needs a CLI hook.
  - Read-only reference: `docs/ai_context/todo.md` `#471` (the source of the
    defect), `reports/nfl_props_backtest_2022_2025.json` (baseline numbers).
- Hypothesis: a Gamma-Poisson (count) shrinkage toward the population's own
  empirical anytime_td-per-game mean, weighted by a small pseudo-count `k`,
  closes most of the 0%-predicted/13-14%-actual gap for n=2-4 samples without
  measurably hurting players who already have a real history (large n is
  barely pulled).
- Falsification test: if the shrunk estimator's out-of-sample Brier score on
  `anytime_td` (scored 2024-2025, tuned on 2022-2023) is not better than the
  unshrunk baseline's, the hypothesis is wrong and this reports a null result
  rather than shipping a change that doesn't help.
- Verification: re-run `scripts/backtest_nfl_props.py --seasons 2022,2023,2024,2025`
  after the change; Section 1's `anytime_td` OOS row and Section 2's
  `anytime_td` calibration buckets (low end specifically) both improve,
  with the numbers stated, not just "looks better".
- Blocked by: none.

### lane-guard-disclaimer-marker-fix — CLOSED 2026-08-19 — fix shipped and verified, `f52fc91b` live on `origin/main`. — session: lane-guard-disclaimer-marker-fix
- Goal: `_DISCLAIMER_MARKERS` in `.claude/hooks/lane-guard.py` recognizes
  "read-only reference" as a disclaimer phrase, so a `Files` bullet like
  `Read-only reference: docs/ai_context/todo.md` stops being misread as an
  exclusive claim. **DONE.**
- Files: `.claude/hooks/lane-guard.py` — one string added to the existing
  `_DISCLAIMER_MARKERS` tuple (same list that already holds `"read-only
  dependency"`), no other logic touched — and `tests/test_lane_guard_files_forms.py`
  (one new regression test, `test_read_only_reference_disclaimer_is_skipped`).
- **Collision check, stated explicitly:** this path sits inside
  `repo-coordination`'s claimed territory (`.claude/hooks/`,
  lines 616-617 above). `repo-coordination` is recorded UNMAPPED by the
  2026-08-18 orphan sweep (line 53 of this file) — no live session in the
  roster resolves to it, so there is no one to message. Left guarded there
  rather than released, so this lane does NOT take over that charter; it
  claims only this one file for this one string addition and should be
  folded back into `repo-coordination` (or closed on its own) once a live
  owner resurfaces.
- Trigger: measured live 2026-08-19 — `nfl-player-props-calibration-fix`'s
  block wrote `Read-only reference: docs/ai_context/todo.md` (an explicit
  disclaimer, not a claim), and the guard's `_is_disclaimer`/
  `_claimable_prefix` did not recognize the phrase, so it blocked
  `nhl-model-owner` from editing `todo.md` — a file every lane in this repo
  edits as a shared append-only ledger.
- Hypothesis: n/a (mechanical fix, not diagnostic).
- Falsification test: n/a.
- Verification: construct a lanes.md fixture containing a
  `Read-only reference:` bullet and confirm `_claims()` no longer yields
  that path as a claim; run the hook's existing test suite if one covers
  `_DISCLAIMER_MARKERS`. **DONE** — added
  `test_read_only_reference_disclaimer_is_skipped` to
  `tests/test_lane_guard_files_forms.py`; full suite 11/11 pass. Also ran
  the fixed guard directly against the real, live `.syndicate/lanes.md`
  (not just the fixture): `docs/ai_context/todo.md` no longer appears in
  `_claims()`'s output.
- Blocked by: none.
- **Shipped:** `f52fc91b` on `origin/main` (rebased clean onto
  `930a0a1e`, which already carried an unrelated same-day commit to the
  same file — merged, not overwritten; both disclaimer-marker additions
  survive). Landed via `session_worktree.py` (own worktree, own index).

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




