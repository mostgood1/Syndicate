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
### convergence-phase7-crps — OPEN — **MLB LADDERS: native builder LIVE on refresh-worker (`3b76cef5`, 21:19Z) but the artifact has NOT rebuilt — still 2026-08-18T18:20, 12 rows, 0 market lines, CAUSE UNKNOWN because every trigger print is truncated out of the 8000-char log window. Status-artifact deploy `4d9f3cf1` pushed + claimed, waiting on a CLEAR window. Roster-rebuild gate SET, unspent, EXPIRES 05:00Z.** — opened 2026-08-17 — session: model-sim-track
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

### basketball-model-owner — OPEN — **WNBA CHAIN CLOSED WITH REAL PRODUCTION CONFIRMATION: `#461`/`#462`/`#464`/`#467`/`#468`/`#469`/`#472` all live, all measured, not just code-correct-in-isolation — `boxscores_history.csv`'s max game date advanced 2026-06-30 → 2026-08-18 in a real production run (real ESPN data, 101 verified rows). `#473`, NEW: checked whether NBA has `#468`'s defect too — it does NOT (wiring is reachable, proven by trace and a real scratch-data test), but it has a DEEPER one: both of NBA's team_advanced_stats rebuild data sources are structurally absent (a `boxscores/` subdirectory the vendor package expects, and `player_logs.csv`), so the rebuild returns nothing regardless of season or wiring. NOT FIXED — genuinely separate, scoped work, no current production impact since NBA is offseason with no autorun even attempting this path.** — opened 2026-08-18 — session: basketball-model-owner
- Goal: Basketball's counterpart to the Modeling (MLB), Soccer, and Football sessions — bring the NBA/WNBA smart-sim engine up to `docs/ai_context/model_engine_standard.md`. Original scope SHIPPED. This session's chain: `#461`→`#468`→`#469`→`#472`, each one uncovering the next real blocker rather than a false trail, ending in a real, measured production confirmation rather than a plausible-sounding stopping point — see `.syndicate/log/2026-08-19.md` and `.syndicate/deploys.md`'s "CONFIRMED WORKING end-to-end" entry for the full narrative, this block is status only. NCAAB still has no sim engine — documented design gap, deliberately not backfilled.
- Files: scripts/basketball_sim_input_checklist.py (new), docs/ai_context/basketball_sim_engine_reference.md (new), docs/ai_context/basketball_model_inventory.md (new). **Write access:** `syndicate/features/shared/basketball_props_smart_sim.py` (`#467`/`#468`'s fixes), `vendor/{wnba,nba}_betting_repo/src/*/cli.py` (`#461`), `scripts/refresh_wnba_oddsapi_props.py` + `syndicate/features/shared/basketball_boxscores_history.py` (`#469`'s silent-success fix, UA change, and the `_player_logs_ready` masking-bug fix pt3).
  **RELEASED, no longer claimed: `scripts/run_live_odds_refresh_worker.py`**
  — `#472`'s fix (both WNBA and soccer halves) is done, deployed, and
  confirmed live; not editing it further. Released 2026-08-19 on finding
  `soccer-odds-capture-cadence-gap` independently converging on the same
  mechanism for soccer's own symptom — messaged them directly with the
  fix detail so they don't duplicate it, rather than leave a stale claim
  blocking their own file access. If this lane needs the file again,
  re-claim it.
  Read-only over the rest of `basketball_props_*.py`, `syndicate/features/{nba,wnba,ncaab}/**`. Not touched: board_enrichment.py or wnba_fixture_identity.py.
  **RELEASED, no longer claimed: `syndicate/features/shared/artifact_publisher.py`**
  — released 2026-08-19 by `soccer-odds-capture-cadence-gap`, not this
  session. `#462`/`#471`'s own additions are SHIPPED and this lane's own
  header already says "no further action identified as ready" here.
  Released rather than left claimed-but-idle so a genuinely narrow,
  unrelated addition (one soccer `HOT_ARTIFACT_PATTERNS` line) does not
  have to wait on a closed-in-substance lane's formal close. Done under
  explicit user authorization, logged in `soccer-odds-capture-cadence-gap`'s
  own block. If this session resumes and needs the file again, re-claim it
  there — nothing here
  prevents that.
- Verification, by commit, ALL LIVE: refresh-worker `f13ea05e`→`23e70a80`→`152c3292`(wnba-edge-263's own deploy, still carries `#469` pt3), live-odds-worker `e1d1bcf4`→`0c7962a7`→`97e85b66`(`#472`), web `b775255a`→`8833cfd6`→`450e0d6e`(log allowlist). **`#468` effect CONFIRMED** (real sim call rebuilt 3 fresh `team_advanced_stats` files). **`#472` effect CONFIRMED**: WNBA autorun launched 23min post-deploy vs. the 5h+ drought measured pre-fix. **`#469` effect CONFIRMED, the headline result**: a manually-triggered real refresh (fired rather than wait ~4h for the next natural cycle) produced a genuinely new `boxscores_2026-08-18.csv` (101 real ESPN rows) and advanced `boxscores_history.csv`'s own max date from 2026-06-30 to 2026-08-18 — the datacenter-IP-soft-block hypothesis was correct and the browser-UA fix resolves it.
- Two ops-tooling gaps found and fixed while chasing this, both real and reusable by future sessions: (1) `launch_refresh_run`'s autorun-launched children have `stdout=DEVNULL` by design, so `print()` markers (including `#469`'s own `BOXSCORE_BOOTSTRAP_STALLED`) never reach Render's log collector for those specific runs — the script's own `_append_log` file was the only surviving signal and was never allowlisted either (fixed). (2) `reports/migration_runs/**` stdout/stderr wrapper files are NOT cross-service visible at all — confirmed directly against this specific path family that they live on whichever service ran the job, not on web's disk; only the `HOT_ARTIFACT_PATTERNS` sweep crosses that boundary.
- `wnba-edge-263`: modeling decision made (WNBA h2h should read the sim's real `p_home_win` directly, not `_margin_win_prob`'s fixed-scale transform) and producer-half edits landed (`6933d263`) — their consumer half should be unblocked.
- `nfl-player-props-backtest`: `HOT_ARTIFACT_PATTERNS` gap fixed (`894b4135`) and **CONFIRMED LIVE** — `450e0d6e`'s own worktree was built from a `main` state that already carried `894b4135`, so it shipped as a side effect of the log-allowlist deploy without a separate deploy needed. Verified directly: `/api/ops/artifacts/export?pattern=*nfl_source*oddsapi_player_props*` returns `count: 14` (was `count: 0` before either fix).
- **`#473`, NBA's team_advanced_stats gap is NOT `#468`'s shape — full writeup in `.syndicate/deploys.md`.** Structural reachability IS symmetric with WNBA (traced: `refresh_nba_oddsapi_props.py` → `export_props_predictions_local` → `export_props_predictions_with_smart_sim_local` → the same monkeypatch → `_load_team_advanced_stats_asof_local`, no NBA-specific divergence, no env-var override). But a real scratch-data reachability test (mirroring `#468`'s own WNBA verification) proved the rebuild returns nothing for NBA: `compute_team_advanced_stats_from_boxscores` expects `<processed_root>/boxscores/` (a subdirectory) + `<raw_root>/games_nba_api.csv`, neither of which exist anywhere in NBA's actual data layout (Syndicate maintains flat `boxscores_2026-*.csv` files instead, the WNBA convention); the fallback needs `player_logs.csv`, also absent (platform-wide, `#462`'s original finding). Also confirmed: NBA has no dedicated pregame autorun at all (only WNBA/soccer do), and NBA's boxscore files are deliberately NOT in `HOT_ARTIFACT_PATTERNS` (rides git+bootstrap instead, ~20MB size tradeoff) so this had to be checked against the local mirror, not live production. **NOT FIXED** — real, scoped work (either a new NBA-native boxscore builder matching Syndicate's actual file convention, or populating the vendor's expected layout), correctly deferred since NBA is offseason with zero current production impact.
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


### football-model-owner — OPEN — **NCAAF PICKS SUPPRESSED LIVE (web `8833cfd6`). Model loses to the CLOSE (+3.419, t=16.3) AND the OPEN (+3.358) — no softer target. Stage 0 ledger built and backfilled.** — opened 2026-08-18 — session: football-model-owner
- Goal: NFL + NCAAF get the input-inventory, pipeline-trace and advanced-analytics
  treatment MLB and soccer have. **Testable:** gating checklist runs; inputs
  leak-free and reachable; defects measured on the SERVED payload.
- Files: `syndicate/features/football/**`, `syndicate/features/ncaaf/{cards,picks}.py`,
  `syndicate/features/nfl/preseason_cards.py`,
  `syndicate/features/shared/{publication_adapter,game_board_contract}.py`,
  `scripts/{football_sim_input_checklist,backfill_nfl_historical_odds,generate_smartsim2_ncaaf_projections}.py`,
  `docs/ai_context/{model_engine_standard,football_sim_engine_reference,nfl_feature_payload_preregistration,ncaaf_beat_the_close_strategy,ncaaf_data_pipeline}.md`,
  `tests/test_{ncaaf_board_slate_coverage,published_projection_means,asof_team_form,football_pick_gate}.py`
- **NOT claimed:** `shared/artifact_publisher.py` (basketball-model-owner),
  `scripts/deploy_preflight.py` (repo-coordination). Both handed over.
- Status: **2 deploys live+VERIFIED; 9 commits all on `origin/main`; nothing of
  mine uncommitted.** web `8833cfd6` 19:18:07Z — picks 0 cards (was 12) +
  suppression empty_state; projections still 51, NFL still 12. refresh-worker
  `f2eb719d` 18:51:08Z — SP+ ratings + as-of PPA leak fix.
- **OWED:** `f2eb719d` STAGE 2 — ~51/51 non-null `predictions.home_mean` on
  `/ncaaf/api/cards?week=1`, 86400s autorun, <=24h. **Shipped, not proven.**
- **IN FLIGHT:** clean 2024 backtest (2023 SP+ on 2024 games, leak-free,
  `--ratings-season`). Generation `binv22kma` wk7/15 at 21:07Z; grading chained
  `bb7bmickj`. **NO RESULT YET — do not quote one.** First grade of the
  production code path on out-of-sample data.
- Next: the gate is a PAUSE, not a fix. Plan + per-market exit criterion in
  `docs/ai_context/ncaaf_beat_the_close_strategy.md`.
- **Do not** retune `SP_RATING_SCALE` (all scales 6..24 lose; 10 vs 13 = 0.7σ),
  retry the three dead scalar fixes, or reopen "beat the OPEN first" — measured
  dead, the open is 0.06 MAE softer than the close.
- **Handed off:** `*_source/data/pick_ledger/pick_ledger_*.csv` allowlist ->
  `basketball-model-owner` (their `artifact_publisher.py`). Until then the
  evidence that would lift the gate is not readable from web.
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
- **DEPLOY PENDING, BUILT AND READY:** `f2eb719d`, branch
  `deploy/ncaaf-sp-ratings-20260819b`, 2 files on live SHA `23e70a80`, blobs
  identical to `origin/main`. **Blocked on the refresh-worker claim** held by
  `nfl-player-props-backtest`; `--force` was attempted (user-directed) and denied
  by the permission classifier — not worked around. Full recipe, two-stage
  verify, staleness precondition and the known-defect disclosure are in
  `.syndicate/deploy/requests/20260819T163000Z-ncaaf-sp-ratings.md`.
  **REFRESH-WORKER IS CONTENDED** — three sessions inside an hour, and my first
  graft was invalidated once already by a deploy landing mid-wait. Re-check the
  live SHA before firing.
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

### soccer-two-sided-edges-cut — CLOSED-VERIFIED 2026-08-19 — **DIAGNOSED, NOT A BUG: real cause is a soccer odds-capture cadence gap, not a Layer 2 defect. Scope reassigned, no follow-on lane opened yet.** — opened 2026-08-19 — session: soccer-two-sided-edges-cut
- Goal: identify and fix why soccer's genuinely two-sided, consensus-priced
  game markets (h2h/totals/spreads) with real positive EV never reach the
  Layer 2 shortlist. **Testable outcome:** on a live build, at least one
  soccer `game`-kind row with `fair_method: consensus` and positive
  `ev_pct` appears in `per_sport.soccer.game` (currently 0).
- Files:
  - `pipeline/layer2_shortlist.py` (the read/build path — quotes come from
    `read_book_quotes_latest`, a DIFFERENT function than the public
    `/api/board/book-grid` endpoint used to gather today's evidence; the
    two may not see the same rows)
  - `syndicate/features/shared/layer2_board.py` (`_fair_by_side`,
    `build_layer2_rows`, `select_shortlist` — confirmed correct in
    isolation against real data, but the full pipeline still drops these
    rows)
  - `syndicate/features/shared/opportunity_gate.py` (eligibility lanes —
    a live/pregame or staleness misclassification could silently demote a
    correct row)
  - `syndicate/features/shared/odds_book_quotes.py` (`read_book_quotes_latest`)
  - `syndicate/features/shared/book_grid.py` (`build_book_grid`)
  - **Collision-checked 2026-08-19 against every OPEN lane's Files block:
    zero overlap.** `soccer-model-dispersion` explicitly does NOT claim
    these files (only the sim/adapter side); the informal `modelled-fair-edge`
    lane claims `soccer_projections.py` + `book_margin_model.py`
    specifically, neither of which is in this lane's file set. If the trace
    leads into either of those two, STOP and raise with that lane rather
    than editing them here.
- Hypothesis: `pipeline/layer2_shortlist.py`'s own quote read
  (`read_book_quotes_latest`) does not see the same rows the public
  book-grid endpoint serves — either a different capture window, a
  different dedup/latest-key rule, or a live/pregame state misread inside
  `opportunity_gate.py` demotes these specific rows before they reach
  scoring. NOT the model-quality hold: these rows get `fair_method:
  consensus` already (verified by running `_fair_by_side` directly against
  real quote data pulled from production), so `_row_ev_is_hold_restatement`
  should not fire on them.
- **Already ruled out, measured 2026-08-19 (do not re-derive):**
  - Horizon window — both positive-EV matches kick off later TODAY
    (2026-08-19T23:30:00Z and 2026-08-19T19:00:00Z), well inside
    `horizon_days=1`.
  - `excluded_markets` — only `["goal_scorer"]`, does not touch h2h/totals/
    spreads.
  - Value floor — both rows (+1.11%, +0.84%) clear the flat -2.0% floor
    with room to spare.
  - `_fair_by_side` itself — confirmed correct in isolation: 17 genuinely
    two-sided game rows today (8 h2h, 8 totals, 1 spread, all MLS + one
    La Liga match), every one correctly resolves to `fair_method:
    "consensus"` when run directly against real production quote data.
  - The "100% one-sided" reading from `per_sport_ingest.soccer.
    enrichment.margin_model` is NOT itself the bug — soccer's candidate
    pool is genuinely dominated by one-sided player props (`sides:
    ['over']` confirmed at the source for `player_shots_on_target` etc.,
    same shape as MLB's `batter_home_runs`). `book_margin_model` is the
    correct handling for those; this lane is only about the 17 rows that
    ARE two-sided and still get cut.
- Falsification test: pull the EXACT quote rows `pipeline/layer2_shortlist.py`
  reads for today's date (via `read_book_quotes_latest("soccer", ...)` or by
  instrumenting the build) and diff against the public book-grid rows for
  the same two matches (FC Cincinnati vs NYCFC, Philadelphia Union vs Inter
  Miami). If the rows are IDENTICAL going in, the cut happens downstream
  (`opportunity_gate`/`build_layer2_rows`/`select_shortlist`) and the
  hypothesis about a read-path mismatch is WRONG — say so and move to the
  next candidate rather than forcing the read-path story to fit.
- Verification: on a live production build, `per_sport_ingest.soccer`
  reports at least one `game`-kind opportunity with `fair_method: consensus`
  and a stated `ev_pct`, and `per_sport.soccer.game > 0`. Report the
  specific gate/stage that was dropping them, with a measured before/after
  count — not just "it works now."
- Blocked by: none.

**FALSIFICATION TEST FIRED 2026-08-19 — HYPOTHESIS REFUTED, REAL CAUSE FOUND.**
Pulled `soccer_source/tracking/book_quotes/2026-08-19.jsonl` directly (the
raw capture shard, not the served board) and checked the exact rows behind
both positive-EV candidates:

- **FC Cincinnati vs NYCFC h2h, `away` @ 235 (betrivers)**: raw capture
  `captured_at: 2026-08-10T00:23:33Z`. Board's own `age_seconds: 851854.4`
  = **9.9 days**. Ceiling (`opportunity_gate.PREGAME_MARKET_MAX_AGE_SECONDS`)
  is 86,400s = 24h. **9.9x over.**
- **Philadelphia Union vs Inter Miami totals 3.5**: `age_seconds: 792481.4`
  = **9.2 days**, same ceiling, same overage.
- Both matches' h2h/totals markets have had **zero fresh captures since
  Aug 6–10** — not a missed-best-price-selection bug (checked: no more
  recent row for either key exists in the shard at all), a genuine capture
  gap. `opportunity_gate.evaluate()` correctly returns `LANE_DEAD` /
  `"pregame_market_stale"` for both — **this is the platform working
  correctly, refusing to price an edge off a week-old number.**

**HYPOTHESIS (read-path mismatch between `read_book_quotes_latest` and the
public book-grid) IS REFUTED** — the quote data itself is identical and
consistent; there is nothing to diff. Per this lane's own falsification
protocol: say so, don't force the story to fit. **Goal reframed**: this is
not a Layer 2 pipeline bug — it is a **soccer odds-capture cadence gap**
for game markets (h2h/totals/spreads) on at least these two matches, and
likely broader (untested: whether this is systemic across MLS, across all
9 leagues, or specific to certain books/markets). Next step for whoever
picks this up: check `scripts/refresh_odds_sources.py`'s soccer game-market
capture schedule/rotation — why hasn't it re-polled these specific markets
in over a week when kickoff is today — rather than anything in the Layer 2
scoring path. This may connect to the ALREADY-DOCUMENTED soccer odds
capture cadence issues in `state.md` `[odds-cadence]` (MLB's three-regime
finding); soccer's own capture regime for game (non-prop) markets has not
been separately measured there.
- Blocked by: none. Scope has moved from `layer2_board.py`/
  `opportunity_gate.py` (both exonerated) to the soccer odds-capture
  scheduler — files above are NOT the right ones for whoever continues
  this; re-scope before touching code.

### nfl-receptions-blend-stability — CLOSED-VERIFIED 2026-08-19 — CONFIRMED stable (hypothesis of instability was WRONG): half A/B = 0.1367/0.0771, ratio 1.77x. No code change. **Completes the full #471 blend/shrinkage constant audit — all 6 checked.** `922e2ab7` on `origin/main`. — session: nfl-receptions-blend-stability
- Goal: `receptions` is the last un-checked market from `#471`'s blend-
  weight family. Shipped `w=0.137` off a fit-half optimum of 0.1367 --
  the SMALLEST measured one-way OOS improvement of any weighted market
  (+0.000016, an order of magnitude smaller than `receiving_yards`'
  already-marginal +0.000065). A market whose realized benefit was this
  close to zero is a natural candidate for an estimate that doesn't
  replicate. **Testable outcome:** run the existing
  `scripts/check_nfl_blend_weight_stability.py --stats receptions`
  (already generalized, no new script needed) and report whether the
  independent 2024-2025 half agrees.
- Files:
  - `syndicate/features/nfl/props.py` — `_COVER_PROBABILITY_BLEND_WEIGHT["receptions"]`,
    ONLY if the check finds a real, stable reason to change it.
  - Read-only: `scripts/check_nfl_blend_weight_stability.py`,
    `scripts/calibrate_nfl_cover_probability_blend.py`,
    `reports/nfl_cover_probability_blend_calibration.json`,
    `reports/nfl_yardage_blend_stability_check.json`.
- Hypothesis: UNSTABLE, more likely than not -- `receiving_yards` (whose
  own one-way improvement was 4x larger) already came in at a wider
  1.74x ratio than `rushing_yards`' near-perfect 1.00x; `receptions`'
  order-of-magnitude-smaller realized benefit suggests its estimate is
  even less pinned down. Held loosely -- the point of running the check
  is to find out, not confirm this.
- Falsification test: if the independent half's optimal weight shares
  `receptions`' sign and sits within the pre-registered <=2.0x ratio,
  the hypothesis is wrong and the tiny shipped weight is real signal
  after all, not noise that happened to survive one clipping-free split.
- Verification: both halves' independently-computed optimal weights
  stated side by side, explicit stable/unstable verdict, same criterion
  as every other market this session.
- **RAN. Hypothesis WRONG — stable, not unstable.** `scripts/check_nfl_
  blend_weight_stability.py --stats receptions`: half A (2022-2023,
  n=35055) w=0.1367; half B (2024-2025, n=34523) w=0.0771 — ratio
  **1.77x**, same sign, within the pre-registered <=2.0x threshold. The
  lane's own hypothesis (that a tiny one-way improvement predicts
  instability) did not hold here — stated plainly rather than only
  reporting the confirmations. **No code change made.**
  `_COVER_PROBABILITY_BLEND_WEIGHT["receptions"]` stays at `0.137`.
  Report: `reports/nfl_receptions_blend_stability_check.json`.
  **THIS WAS THE LAST UNCHECKED MARKET — the full `#471` blend-weight +
  shrinkage-constant audit is now complete.** All 6 tuned constants
  individually verified against independent data: stable —
  `rushing_yards` (1.00x), `anytime_td` k (1.00x, exact), `receptions`
  (1.77x), `receiving_yards` (1.74x); correctly left at their safe
  value — `passing_attempts` (capped), `passing_tds`/`interceptions`
  (`w=0`).
- Blocked by: none.

### soccer-odds-capture-cadence-gap — OPEN — **ROOT CAUSE HAS TWO CONFIRMED PARTS (steps=0 dominant + mutex contention secondary, from live-odds-worker's own logs). ALLOWLIST FIX (`2431df26`) DEPLOYING TO live-odds-worker AT CHECKPOINT (build_in_progress); web NOT YET DEPLOYED (claim held elsewhere). Open question (genuine-empty-run vs reporting-schema-mismatch) still needs the newly-allowlisted status file read once both deploys land.** — opened 2026-08-19 — session: soccer-odds-capture-cadence-gap
- Goal: soccer's h2h/totals/spreads game-market odds capture actually
  refreshes within a bounded window (target: <24h old for a match kicking
  off within the next day) instead of sitting 8-10 days stale.
  **Testable outcome:** re-pull `soccer_source/tracking/book_quotes/
  <today>.jsonl` for a slate with same-day kickoffs; every distinct
  match's h2h/totals/spreads `captured_at` is <24h old, not just some.
- Files:
  - `syndicate/features/shared/artifact_publisher.py` — **claimed 2026-08-19,
    narrow: ONE new `HOT_ARTIFACT_PATTERNS` line
    (`reports/refresh_status/latest/soccer_pregame_autorun_status.json`)
    only. Was `basketball-model-owner`'s; released by them (their own
    header: "no further action identified as ready", `#462`/`#471` both
    shipped) rather than left claimed-but-idle. Done under explicit user
    authorization — see that lane's own block for the release note.**
  - **Not claimed here, read-only reference:** `scripts/run_live_odds_refresh_worker.py`
    (defines `_launch_autorun_soccer_pregame_refresh`, the SOLE producer,
    4h cadence; held by `basketball-model-owner`, `#472`). Traced only,
    never edited — `#472`'s own fix (preserve epoch on contention) is
    already live in this file; this lane's `steps=0` question needs a
    DIFFERENT change (still unscoped to a location). If an edit here does
    become necessary, re-claim it explicitly rather than relying on this
    reference. Also note: this file has real uncommitted changes sitting
    in the PRIMARY shared tree right now, not mine, likely from the
    informally-referenced "OOM band" session (flagged stale 40h in the
    roster, no formal lane header found).
    Any future edit here goes through a dedicated worktree
    (`scripts/session_worktree.py open --lane soccer-odds-capture-cadence-gap`),
    never the primary tree, so that uncommitted diff is never touched.
  - `scripts/run_refresh_worker.py` (referenced alongside the above in
    prior sessions' notes — confirm its actual soccer-relevance before
    editing; `phase=live` there has 0 odds steps by design per `#148`,
    so it may not be where the fix belongs at all)
  - `scripts/refresh_odds_sources.py` (`_build_soccer_steps`, confirmed:
    the actual h2h/totals/spreads fetch step is `phases=("pregame",)`
    only — this file is EXONERATED as the bug's location, kept in the
    list as read-only reference only)
  - `syndicate/features/shared/ops_refresh.py` (`launch_refresh_run`,
    `_assert_no_active_refresh_run`, `_resolve_launch_mode` — THIS is now
    the most likely location of the actual fix, per the mechanism traced
    below, not the files originally guessed at lane-open)
  - Read-only reference: `.syndicate/state.md` `[soccer]` section — the
    prior investigation's full history, DEAD hypotheses, and the now-
    contradicted "SUPERSEDED 2026-08-17" note.
- Hypothesis: `_launch_autorun_soccer_pregame_refresh` has stopped firing
  successfully again (or was never actually fixed on 08-17 — that read
  used aggregate `quote_rows`/`dates_with_rows` counts, which can stay
  healthy-looking while specific matches never get a fresh capture, the
  exact "healthy sibling masks an outage" shape `learnings.md` already
  names). NOT league-specific (this session's own measurement: 8 of 8
  affected matches span MLS AND La Liga) — that hypothesis is DEAD twice
  over now.
- **Already established, measured 2026-08-19 (do not re-derive):**
  - **8 of 8** distinct matches with TODAY's kickoffs, checked across
    every league present in the shard, have their freshest h2h/totals/
    spreads `captured_at` at **211-236 hours old (8.8-9.8 days)**.
    Freshest capture found anywhere in the file: 2026-08-11.
  - This directly contradicts `state.md`'s `[soccer]` note "SUPERSEDED
    2026-08-17 21:3xZ — capture is WORKING" — that note's own evidence
    (`quote_rows 16,044`, `dates_with_rows` spanning many dates) never
    checked PER-MATCH freshness, only that SOME rows existed somewhere.
  - **Already DEAD, from the prior session (state.md `[soccer]`), do not
    retry:** step truncation at #27 of 50 (falsified by a scoped ~6-step
    run that captured nothing); three-specific-leagues (all ten were
    affected then; this session's finding — MLS + La Liga both affected
    now — is independent confirmation).
  - **Known blocker from the prior session:** the run's own logs are
    UNREADABLE FROM WEB — `launch_refresh_run` spawns the child with
    `stdout=DEVNULL, stderr=DEVNULL` onto the WORKER's own disk, and
    Render's log collector only captures a service's own top-level
    stdout. A log-based diagnosis failed for 4 days before on this exact
    account; do not restart from "read the logs."
- Falsification test: confirm `_launch_autorun_soccer_pregame_refresh` is
  still being INVOKED at all (a scheduler-liveness question, separate
  from whether its fetch succeeds) — e.g. a process-list check on
  live-odds-worker at a moment straddling its 4h cadence boundary, or any
  observable side effect it writes regardless of fetch outcome. If it is
  firing but the FETCH itself fails, the bug is downstream (HTTP/auth/
  odds-source), not the scheduler — say so and retarget rather than
  assuming the scheduler is the fault by default.
**MECHANISM TRACED 2026-08-19, from code (not yet directly observed firing
live — see "still needs verification" below).**

1. **Confirmed by reading `_build_soccer_steps` directly**
   (`scripts/refresh_odds_sources.py:1168`): `soccer_{league}_odds`,
   `_props`, `_picks` are ALL `phases=("pregame",)` ONLY — never `"live"`.
   Only `soccer_{league}_artifacts` (the sim) runs in both. **`state.md`'s
   "phase=live builds 0 odds steps" claim is CORRECT, not stale** — this
   session's own earlier suspicion that it might be outdated is now
   resolved in the ORIGINAL note's favor.
2. Pulled `/api/ops/odds-refresh/status` live: `phase=live` soccer runs
   ARE firing constantly — every ~5 minutes, alternating between
   `refresh-worker` and `live-odds-worker`, both "finished" successfully.
   **This is a red herring by design (1) already explains** — these runs
   were never going to capture odds regardless of how healthy they look,
   which is exactly the "healthy-looking activity masks the real gap"
   shape.
3. **REFUTED SUB-HYPOTHESIS, recorded so it is not retried:** suspected
   `_launch_autorun_soccer_pregame_refresh`'s `launch_mode="web_process"`
   routed its concurrency check through refresh-worker's OWN lane (which
   is almost always saturated with MLB/NFL sims) via the
   `external_runner`/queue path. **Checked `_resolve_launch_mode` directly
   (`ops_refresh.py:161`): `"web_process"` is not a recognized value and
   silently falls back to `"detached_subprocess"`**, which is NOT
   `external_runner_mode` — so it runs directly on the CALLING service
   (live-odds-worker) under live-odds-worker's OWN lane, not refresh-
   worker's. The refresh-worker-starvation theory is dead.
4. **CURRENT LEADING HYPOTHESIS, not yet directly confirmed:**
   self-contention on live-odds-worker's OWN lane. The very frequent
   `phase=live` cycle (every ~5 min) and the rare `phase=pregame` soccer
   cycle (every 4h) BOTH launch via `launch_refresh_run(...,
   launch_mode="web_process", ...)` on the SAME service, both resolving to
   the SAME `detached_subprocess` lane. `_assert_no_active_refresh_run`
   (`ops_refresh.py:636`) is a genuine hard per-lane block — confirmed by
   reading it, not inferred. If the frequent cycle's lane is occupied
   (or was, moments earlier) essentially every time the 4-hour pregame
   timer comes due, the pregame odds-capture steps may simply never win
   the race. The contention-handling code
   (`_is_refresh_run_contention_error`) preserves the original epoch on
   failure rather than resetting it, so a starved autorun retries on
   EVERY subsequent tick rather than backing off — consistent with a
   sustained, indefinite gap rather than a one-off miss.
- **Still needs verification before this is called done** (next concrete
  step for whoever continues): read `soccer_pregame_autorun_status.json`
  directly off live-odds-worker's disk (path:
  `reports_root()/refresh_status/latest/soccer_pregame_autorun_status.json`
  — NOT currently in `HOT_ARTIFACT_PATTERNS`, so `/api/ops/artifacts/
  stream` 403s on it; either add it to the allowlist or find another
  read path) to see its actual `epoch`/`error` history — this is the one
  artifact that would show contention errors directly rather than by
  inference. If it shows repeated `_is_refresh_run_contention_error`
  hits, hypothesis (4) is CONFIRMED; if it shows successful launches with
  no error, the bug is elsewhere (the odds fetch itself, not the
  scheduler) and this whole mechanism trace is a dead end to record, not
  retry.

**FALSIFICATION RESOLVED 2026-08-19 21:5xZ — CONFIRMED FROM LOGS, not
inference.** Did not wait on the `HOT_ARTIFACT_PATTERNS` addition (asked
`basketball-model-owner`, no reply yet) — found a path that did not need
it: `render_logs.py` reads live-odds-worker's OWN stdout (the print
statements `_report_previous_soccer_pregame_run`/
`_launch_autorun_soccer_pregame_refresh` themselves emit, NOT the
redirected child's `DEVNULL` stdout `#433` already worked around this
for). `py -3 scripts/render_logs.py --service live-odds-worker --text
SOCCER_PREGAME --start 2026-08-19T00:00:00Z` returned the full day's
history directly:

```
03:20Z LAUNCHED date=2026-08-18 -> 03:21Z NO_ARTIFACT (child wrote nothing)
07:26Z LAUNCHED date=2026-08-19 -> 07:42Z SUMMARY steps=0 ok=0 failed=0
11:32Z LAUNCHED date=2026-08-19 -> 11:48Z SUMMARY steps=0 ok=0 failed=0
15:38Z LAUNCHED date=2026-08-19 -> 15:53Z SUMMARY steps=0 ok=0 failed=0
19:39Z-19:47Z  AUTORUN_FAILED ValueError: A refresh run is already active
               (pid=64). Cancel it before starting a new run.  [x8, ~1/min]
19:48Z LAUNCHED pid=492 -> 19:49Z NO_ARTIFACT (child wrote nothing)
```

**TWO CONFIRMED, DISTINCT FAILURE MODES, not one:**

1. **`steps=0` on every one of TODAY's clean cycles (07:26/11:32/15:38) —
   the DOMINANT cause of the multi-day staleness.** The run launches,
   completes without error, but the reporting artifact's
   `results[].generation.steps[]` is empty. Traced the parser itself
   (`_report_previous_soccer_pregame_run`, `run_live_odds_refresh_worker.py:150`)
   — **NOT YET DISTINGUISHED: is this a genuinely empty run (something
   upstream of `_build_soccer_steps` produces zero league_slugs for real),
   or a schema mismatch between what the reporting code expects
   (`payload["results"][i]["generation"]["steps"]`) and what a
   `phase="pregame"` child actually writes?** Checked `_build_soccer_steps`
   directly and RULED OUT the obvious season-window explanation:
   `_MLS_OFF_SEASON_MONTHS = (1,)`, `_EUROPEAN_OFF_SEASON_MONTHS = (6, 7)`
   — August is in-season for every league, so `active_leagues_for_date`
   should not be empty. The `steps=0` cause is still open; next step is
   reading one actual `odds_refresh.json` result artifact (needs the
   `HOT_ARTIFACT_PATTERNS` addition, or `basketball-model-owner` reading it
   directly off their own disk access) rather than guessing further.
2. **Mutex contention IS real and directly confirmed** (not just
   hypothesized) — the exact `#472`-shaped error, firing repeatedly late
   in the sampled window. Independent of failure mode 1 — even a
   contention-free pregame run this same day still produced `steps=0`
   three times before contention ever appeared.
- Verification: re-pull the book_quotes shard for a live same-day slate
  after any fix and confirm ALL distinct matches (not a sample) show
  `captured_at` inside the target window. Report the per-match count,
  not just "capture resumed."
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




