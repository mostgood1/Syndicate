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


### football-model-owner — CLOSED-VERIFIED 2026-08-20 — **NCAAF+NFL model track closed on measurement (dominated; every lever priced or null; picks SUPPRESSED live and verified). Consolidation shipped: 114 files / 3 deploys, content-verified.** — opened 2026-08-18 — session: football-model-owner
- **Nothing held:** no deploy claim, no file claims (this block never had a
  `Files:` section), no grants. `ahead 0` — all work on `origin/main`.
- **Live and verified:** picks SUPPRESSED (`/ncaaf/api/picks` 0 cards + reason);
  board serves SP+ wk1; consolidation grafts `db469003` / `a381d652` / `454f3caa`.
- **CLOSED ON MEASUREMENT — do not reopen without new data:** model is dominated
  (R² 17.8% vs market 41.6%, w=−0.028); injuries PRICED (17 seasons, 4,431
  games); situational all 8 priced (1,746 games); returning production null
  (pooled t=−0.89, code removed); every `SP_RATING_SCALE` 6..24 loses; blending
  w≈0. ATS: the model trails always-bet-the-underdog by ~4.3 pts in BOTH sports.
- **OWED BY OTHERS, not this lane:** `smartsim2_projections_*.csv` allowlist —
  orphaned after THREE failed handoffs; both football generators' publish calls
  stay INERT until someone adds the line. `tests/test_football_projection_publish.py`
  flips from xfail to unexpected-success when it lands.
- **Soccer suite:** `--deselect tests/test_soccer_market_anchoring.py` → 633 pass
  in 149.6s vs 875.8s. Do NOT lower its `simulations=` counts to speed it up.
- Full narrative: `.syndicate/log/2026-08-{19,20}.md`. Exit criterion and the
  dead levers: `docs/ai_context/ncaaf_beat_the_close_strategy.md`.

### mlb-overview-hydration-cost — OPEN — **DEPLOYED `d0ea983d` to refresh-worker 2026-08-20 13:59:33Z. THE BRANCH IS PROVEN TO FIRE IN PRODUCTION (`pruned=9/9`) AND THE MECHANISM DOES REAL WORK ON A COMPLETED SLATE — `date=2026-08-19 games=15 pruned=15 plays_dropped=1125`, against 1,067 measured locally on a 15-game completed slate. Pregame slates prune ~nothing (`plays_dropped=1`), which is correct, not inert. STILL UNPROVEN: that this moves the ~2GB excursion — that needs the live-slate window against a comparably-aged process.** — opened 2026-08-19 — **UNOWNED (session `80b3e432` archived 2026-08-20 ~10:4x CDT). The closing reading is SCHEDULED, not abandoned: `mlb-387-live-slate-read` fires 2026-08-20 22:15 CDT and takes the live-slate FEED_LIVE_PRUNE + memory reading. A MECHANISM ONLY verdict there does NOT close this lane.** — **BOTH CUTS LANDED ON `origin/main` (`ab99d236`), MEASURED LOCALLY, NOT DEPLOYED. Peak RSS 142.9 → 114.5 MB on a 15-game slate with a byte-identical games list; plus a per-build ~125MB dead odds_history read removed, proven dead by the shard WRITER's schema. The 3000MB floor is untouched and stays untouched.**
- Goal: `#387`'s named real fix — make the MLB overview hydration path (`build_cards_page_context` as reached from `_MLBDataProvider.games()`) cheap enough that refresh-worker can hydrate MLB under normal load, WITHOUT lowering `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` (3000MB). Testable outcome: a measured peak-RSS reduction for the worker-path call on a real 15-game slate, with byte-identical candidate-relevant output.
- Files: `syndicate/features/mlb/cards.py`, `syndicate/blueprints/home.py`, `tests/test_mlb_cards_worker_projection.py` (new), `scripts/measure_cards_context_rss.py` (new), `.syndicate/*`.
  **Released 2026-08-20 ~20:1xZ, user-authorized: the todo document.** Owning session `80b3e432`
  confirmed gone (not found in the session roster, archived or not); `nhl-model-owner` (session
  `46352c78`) took it to add its own, unrelated §2A/§2B addendum under `#470`, additive only, no
  touch to any `#387`-related content. The rest of this claim (the code/test files) stands, and
  covers any future `#387` writeup there too, until the scheduled closing reading
  (`mlb-387-live-slate-read`, 22:15 CDT) resolves the lane.
- Hypothesis: the worker keeps only `payload["games"]` (and only a subset of each game's fields) yet pays for the whole page context — feed/live `actual_games`, HR/K shelves, ladder badges, scoreboard/module furniture. A worker-scoped projection that skips what no consumer reads cuts the transient without touching the guard.
- Falsification test: (a) trace shows a candidate-path consumer DOES read a field the projection drops → the projection is wrong as scoped; (b) measured peak RSS with the projection ON is not lower than OFF on the same slate → the skipped work was not the cost.
- Verification: `scripts/measure_cards_context_rss.py` reports peak **RSS** (not tracemalloc — `handoff_refresh_worker_oom.md` records tracemalloc as structurally blind here) for OFF vs ON on 2026-06-14 (15 games, full local artifact set), plus a parity test asserting the candidate-relevant projection is unchanged, plus a reachability test (`off != on`) per `model_engine_standard.md`.
- Blocked by: none. **UNOWNED — anyone may pick this up.**
- **DO NOT DEPLOY `origin/deploy/mlb-overview-hydration-cost` (`5ad1d96e`).** It was cut from
  `041188cb` and is now a ROLLBACK of the NFL roster/depth-chart autorun arming (`3b816546`,
  live 13:36:29Z). The branch that is actually live is `origin/deploy/387-on-3b816546` = `d0ea983d`.
- **The one open question is the magnitude, not the mechanism.** Mechanism is proven
  (`pruned == games` 3/3; 1,125 play records dropped on a completed slate). Whether it moves the
  ~2GB excursion is unproven and must not be asserted without a same-clock, boot-matched reading.
- **2026-08-20 STATUS.** Shipped on `origin/main` (`ab99d236`, `9b66e841`, `6980f910`) and deployed to
  refresh-worker as `d0ea983d`, re-cut onto `3b816546` (the live SHA at deploy time) after
  `nfl-autorun-production-arm` deployed mid-poll and turned the prepared branch into a rollback of
  their work. Claim acquired 13:51:45Z after theirs expired, preflight CLEAR, released 14:0xZ.
- **WHAT `/preflight` CAUGHT, and it was worth running.** The candidate had (a) no production-observable
  signal that the prune fired — the exact way three prior `#387` candidates became unfalsifiable;
  (b) a parity harness comparing stdout, so it broke the moment the new log line existed; (c) two
  load-bearing comments naming a test file AND a test name that do not exist.
- **STILL OWED, and it is the whole question:** re-read `FEED_LIVE_PRUNE` during the live/post-game
  window. `plays_dropped` in the thousands = the mechanism works. Still ~0 at 02:00Z = the payloads
  reaching this loader never carry play-by-play in production, and the 66.38% premise — true of the
  artifact on disk — is wrong for the production regime. That would not be a small correction; it
  would retire the main reason this change exists.
- This lane does NOT close until that reading is taken.
- **RESULT `[2026-08-19]` — the hypothesis was HALF RIGHT, and the half that was
  wrong is the more useful finding.** The projection idea ("the worker keeps only
  `games`, so skip the page furniture") was not needed: the two real costs were
  *inside* what the worker does read.
  - **Feed/live prune.** `liveData.plays.allPlays` is **66.38%** of a StatsAPI
    feed/live document and `playsByInning` a further **3.05%** (measured over the
    15 documents of 2026-06-14, 12,605,243 JSON bytes), and **nothing in
    `syndicate/` reads either** — every `allPlays` reader is an offline script or
    `vendor/`, each opening the artifact off disk itself. `_daily_actual_by_game`
    holds one such document per game live for the whole build. Denylist, not
    allowlist, so every other consumer is untouched.
  - **A dead shard load.** `_enrich_games_with_tracked_market_lines` read the
    whole odds_history shard to consult `doc["games"]`. **The shard has no
    `games` key and never has had one** — one writer, one literal schema, `git
    log -S` finds no revision that emitted it, and all three real shard copies on
    disk confirm `has_games=False`. Worker-only, today-only (= every board
    build), uncached. `.syndicate/deploys.md` 2026-08-16 called this "the best
    candidate on the table" and asked for an in-pass measurement to settle it;
    **the WRITER's schema settles it, and was readable the whole time.**
- **VERIFICATION RAN.** `scripts/measure_cards_context_rss.py`, worker path
  (`SYNDICATE_WEB_DYNO=0`), 15-game slate, 5 repeats per arm, prune the only
  variable:

      peak RSS       142.9 MB -> 114.5 MB   (-28.4 MB, -19.9%)
        spread    142.7-143.1   114.1-114.9
      transient       +55.7 MB ->  +35.0 MB
      retained        +11.8 MB ->   +2.8 MB
      _daily_actual_by_game retention  +13.6 MB -> +1.9 MB
      serialised games list   343,503 B both arms -- IDENTICAL

  RSS on a sampling thread, **not `tracemalloc`** — `handoff_refresh_worker_oom.md`
  records tracemalloc as structurally blind to this exact failure mode.
  10 tests in `tests/test_mlb_cards_worker_hydration_cost.py`, incl. the
  reachability pair (`off != on`) and a schema-coupling test that fails if the
  shard ever grows a `games` key. 103 MLB cards tests green. The 6 red
  `test_archives` cases are PRE-EXISTING in a `data/`-less worktree — verified by
  re-running them on a stashed tree, same 6.
- **FALSIFICATION NOT TRIGGERED, and the limits are stated rather than implied.**
  (a) No candidate-path consumer reads the dropped sections. (b) `off != on`, so
  the mechanism fires. **BUT:** the ~125MB shard figure is NOT in the table — the
  local mirror has no dated shard and the harness runs a PAST date, so that path
  is never exercised locally. It is a production-only claim derived from a
  measured file size (19,798,176 B) and `#435`'s ~6.3x resident ratio.
- **NOT CLAIMED: that the ~2GB production excursion is fixed.** Three named
  candidates before this one were live, exercised, and moved the transient by
  nothing measurable. Ship, then read `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb`
  as a RATE against a same-clock-window baseline — never a post-deploy hour,
  because only a cold process clears that bar.
- Landed `ab99d236` on `origin/main`, then DEPLOYED as `d0ea983d` (refresh-worker, 2026-08-20T13:59:33Z). Claim acquired 13:51:45Z, preflight CLEAR, claim RELEASED. Superseded the same day: this line previously read "No deploy made, no claim taken."
  Follow-up filed as `#483` (whether Layer 2 ever wanted shard freshness at all).


### wnba-live-odds-capture-gap — OPEN, VERIFICATION PENDING — **FIX SHIPPED AND DEPLOYED (commit `170505ec`, deploy `b5cf8ac2` live 13:15:46Z; flag flip `cb322dd1` live 13:31:11Z). Isolated WNBA-only live-phase autorun, own lane+cadence, mode=fast. No WNBA game has been live since the flag flipped, so real end-to-end behavior is UNOBSERVED — that is the one thing left.** — opened 2026-08-20 — session 2bffd747-efb5-45d8-b4f3-ae067b645eb7
- Goal: WNBA's in-game (live-phase) odds capture actually refreshes once a
  game goes live, instead of freezing at its last pregame quote.
  **Testable outcome:** for a WNBA game currently in live state, re-pull
  `wnba_source/tracking/book_quotes/<date>.jsonl` and confirm at least one
  market's `captured_at` is newer than the game's own kickoff time.
- Files:
  - `scripts/refresh_odds_sources.py` (`_build_wnba_steps`) — read-only
    reference until the actual defect location is confirmed; do not edit
    without re-claiming narrowly, same convention the soccer lane used for
    this same file.
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
- **verify: PARTIAL.** Confirmed: env var reads `"1"` live, zero `WNBA_LIVE_AUTORUN_ERROR`, tick loop
  healthy. NOT confirmed: no WNBA game was live at deploy time (all three of today's games still
  pregame, kickoffs 00:00Z/02:00Z the next day) — `WNBA_LIVE_AUTORUN_LAUNCHED` has never fired for
  real. **This is the one thing left, and it is the lane's actual falsification test.**
- Next concrete step for whoever continues: once a WNBA game goes live, `render_logs.py --service
  live-odds-worker --text WNBA_LIVE_AUTORUN_LAUNCHED` should show it firing within one 240s cycle of
  kickoff; re-pull that game's `book_quotes` shard and confirm a `captured_at` newer than kickoff.
  If it does NOT fire, re-check `_wnba_has_live_game`'s two sub-checkers
  (`_wnba_has_live_game_via_artifact`, `_espn_has_live_game`) directly — not yet independently
  verified against a real live game, only unit-tested with a monkeypatched return value.
- Blocked by: none.

### layer2-board-chip-race — OPEN, CODE LANDED, NOT YET DEPLOYED — **Reconciliation check 2026-08-20 19:58Z found this: landed on `origin/main` (`164a38bf`) but content-verified ABSENT from web's live SHA (`d9a23a38`, 19:46:49Z) -- never actually deployed, only merged. web's claim is held by `soccer-board-mlb-parity` (genuinely active). Handing off: deploy the next time web's claim frees up, scoped onto its then-current live SHA, then content-verify `gameChipsLoadedOnce` is present before closing.** — opened 2026-08-20 — session 2bffd747-efb5-45d8-b4f3-ae067b645eb7
- Goal: fix a confirmed render-order race on the Layer 2 board's compact
  game-card strip -- a follow-on to `layer2-board-pick-clarity` /
  `layer2-board-movement-display`, both CLOSED, same file.
  **Testable outcome:** on a fresh page load, today's real games' mini
  cards render directly in the chip-based (scores/live-status) style,
  with no visible flash-then-relayout from the plain fallback style.
- Files: `syndicate/templates/intelligence.html` (`loadGameChips()`,
  the initial synchronous render call site at the bottom of the IIFE,
  `renderGameCards`/`deriveGameCards` if the fix ends up needing to gate
  the strip's own first paint rather than just reordering two calls).
- Hypothesis: n/a (root-caused already, see below).
- **Already established, measured 2026-08-20 (do not re-derive):**
  - The board's mini game-card strip has two render styles: a chip-based
    one (team abbrs, live score, status token) when `chipForGame(group)`
    finds a match in `gameChipsById`/`gameChipsByMatchup`, and a plain
    fallback (matchup text only) when it doesn't.
  - **This is NOT a chip-matching bug.** Measured live against the
    production board (`/api/board/game-chips`, `/api/intelligence/query`):
    of 89 total game groups, 56 failed to match a chip -- but re-scoped to
    ONLY today's (`game_date` 2026-08-20) real games, **15 of 15 (100%)
    matched.** Every one of the 56 apparent mismatches was a future-dated
    game (1-3 days out, `source_board_date` 2026-08-20 spanning a
    multi-day `combined_board_window`), where a scoreboard chip correctly
    does not exist yet. The simpler card for those is correct, expected
    behaviour, not a defect.
  - **The real, reproducible cause is a load-order race.** On page load,
    if `initialIntelligenceResponse` is present (server-rendered, the
    normal case), `renderIntelligence(merged)` runs SYNCHRONOUSLY
    (`intelligence.html:2547-2552`) -- including the first paint of the
    mini game-card strip -- while `gameChipsById`/`gameChipsByMatchup`
    are still their initial empty `Map()`s, because `loadGameChips()`
    is not called until the NEXT line, 2557. So the strip's first paint
    is always the plain fallback style for every game, including today's
    real ones, and then re-renders into the richer chip style a moment
    later once `loadGameChips()`'s fetch resolves (it calls
    `renderBoardBody()` itself, `intelligence.html:1322`). Confirmed by
    code read (call-site line numbers), not yet reproduced with a timed
    screenshot/network-waterfall capture -- that is the next concrete
    step, not a re-derivation of the mechanism.
- Falsification test: n/a, implementation lane, mechanism confirmed by
  code read. If a timed capture shows the strip using the chip style on
  its FIRST paint even before `loadGameChips()`'s network request
  resolves, the mechanism above is wrong and needs re-diagnosis.
- Verification: reload the live board with network throttling (or just a
  slow enough connection to observe the transition) and confirm no
  visible flash-then-relayout for today's games; re-run this session's
  same "100% chip-match for today" measurement post-deploy as a
  regression check that the reorder did not break matching itself.
- Blocked by: none.

### soccer-board-mlb-parity — OPEN, UNOWNED (session `aeb71be7` closed 2026-08-20 22:1xZ; DEPLOYED, only the live-clock reading outstanding) — **LANDED ON `origin/main` (`51b7e765` + `9849e9b5`) AND LIVE ON WEB (`547b541b`, 18:07:09Z, grafted onto the live SHA — NOT main, see `deploys.md` for why deploying main's tip would have reverted ten commits). PRODUCTION READING TAKEN on the SAME card, same service: density 139 → 176 items/Mpx, height 1074 → 878px, em-dash cells 6 → 0, prop status rows 0 → 8, and the tiles now serve real prices (`COV ML +1400 | Model 8.7% | Market 6.3% | Edge +2.4 pts`). ONE USER-FOUND REGRESSION: the date board filtered on the UTC day, so eight MLS matches played 08-19 Central appeared on the 08-20 board already Final — fixed, deployed, re-verified with a PREDICATE (0 off-date cards across three dates) rather than a count. **DENSITY TARGET NOW MET (`bfdd0179` + `0514f2d7`, live 18:59:52Z): 363/Mpx against a 2x bar of 331 (MLB re-read at 663 this session), card 1074 → 970px, box tab 30 → 238 items, visible panel 51 → 97/Mpx. The FIRST of those two deploys DID NOT WORK — production read 255 where local read 427, because the local mirror has no odds and the overview grid collapses to a shape production never renders; the fix was probed against the LIVE page. Blast radius verified on NFL, NCAAF and mobile: 0 clipped elements, 0 body overflow. MLB does not load this stylesheet.** — opened 2026-08-20 — session 56b563e0-4c1a-4436-8e3b-ba3624fbeab0
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


### soccer-stale-artifact-overwrite — OPEN — **CAUSE FOUND, FIX LANDED (`32148cac`) AND LIVE ON WEB (`15a0be64`, 22:36:32Z, grafted onto the live SHA — main was 462 files away). THE HANDED-DOWN HYPOTHESIS WAS WRONG: no worker publishes anything here. Web's OWN boot sync (`bootstrap_data_root.py` via `_bootstrap_render_data`) copied the git checkout over its own disk on every boot, repo-always-wins, and its logs bracket the incident exactly (sync 21:42:31Z → 21:43:28Z; the good read at 21:42:5xZ sits INSIDE that window). Served bytes were sha256-identical to the committed mirror. `copy2` preserves the SOURCE mtime, so the clobbered file's mtime (21:36:27Z) PREDATES the last good read of the file it replaced — that inversion is the fingerprint, and a whole-second mtime shared by 7 files across 4 leagues is the other half. SCOPE: 1,114 of 8,016 hot artifacts web served were the checkout's copy; 88 live ones (incl. MLB sim input `batted_ball_2026.json`) were scheduled for destruction at the next boot — both LOWER BOUNDS, the sync walks ~33k files. WEB ONLY: neither worker imports `syndicate.app`, so `SYNDICATE_BOOTSTRAP_ON_START=1` is inert on both — which VOIDS `#357`'s standing counter-argument. POST-DEPLOY: control group 88/88 survived, 0 clobbered, 0 artifacts flipped to the mirror, and la_liga `recommendations_2026-08-20` now reads `generated_at 22:37:07Z`. **NOT DISCHARGED, and the reason is worse than "slow": THAT BOOT'S SYNC WAS KILLED 63 SECONDS IN.** `/healthz` went unanswered ~30s and Render fired `server_failed` (`unhealthy: HTTP health check`) at 22:37:52.78Z while the container served 4 concurrent multi-MB glob exports (1 mine, 3 the platform's) alongside a 31,147-file walk, workers already at 594/607 MB of 2 GB. It died inside root 1 of 16; `soccer_source` syncs LAST and was never reached — so the 67 mlb files are in-flight evidence and the 21 soccer files are an INFERENCE. Worse, the graceful shutdown never joined the daemon thread, so `_run_bootstrap`'s `finally` left `.bootstrap_sync.lock` behind and the replacement instance SKIPPED the sync entirely (<1800s lock, `app.py:109`). **No complete bootstrap has run since the fix went live.** A killed bootstrap poisoning the next boot for 30 min is a separate pre-existing defect, filed in `#494`. DISCHARGE = one `Bootstrap totals: … kept=` line + one control-group re-read; both ways to force a boot are correctly blocked (classifier on raw restart, preflight `HOLD: redundant` on same-SHA) and neither was worked around, so **the web claim was RELEASED for the next session's deploy to supply it**, with a monitor on the Render logs API.** — opened 2026-08-20 — session eb7a0536-82ff-45d7-8ce8-748a9034b388
- Goal: web's runtime disk stops being overwritten with the month-old
  git-mirror copy of `soccer_source/*/api/recommendations/recommendations_*.json`.
  **Testable outcome:** `/api/ops/artifacts/export?path=soccer_source/la_liga/
  api/recommendations/recommendations_<today>.json` returns a `generated_at`
  from TODAY, and still does on a re-read >=30 min later (the 22:00Z lesson:
  one green read is timing, not a property).
- Files: `syndicate/features/shared/artifact_publisher.py`,
  `scripts/run_refresh_worker.py`, `syndicate/app.py` (`_bootstrap_render_data`
  only), `tests/test_artifact_publisher.py`, `.syndicate/*`.
- **NOT IN THIS LANE (declared overlaps, will not edit):**
  `scripts/build_soccer_artifacts.py` and `syndicate/features/soccer/` sim dirs
  (`soccer-model-dispersion`); `syndicate/features/soccer/cards.py`,
  `sources.py`, `syndicate/blueprints/soccer.py` (`soccer-board-mlb-parity`).
- Hypothesis (from `deploys.md` 22:00Z): a service whose own runtime disk holds
  the git-shipped mirror copy publishes it through `HOT_ARTIFACT_PATTERNS` and
  overwrites web's fresher file. **FALSIFIED 2026-08-20 22:1xZ.** No publisher is
  involved and the allowlist is irrelevant: `_write_published_artifact` writes
  with sub-second mtimes, and the clobbered file carried a whole-second mtime
  copied from the checkout. The `_bootstrap_render_data` half of that hypothesis
  was right, but as web's OWN boot sync overwriting web's OWN disk — not as a
  cross-service publish.
- Falsification test: if the file's `mtime` on web has NOT moved since before
  21:42Z, nothing overwrote anything and the fresh reading came from somewhere
  other than this file — the hypothesis is dead and the question becomes which
  root served the 21:42Z read. Equally: if no other service's disk holds a
  `generated_at 2026-07-20` copy, there is nothing to have pushed.
- Verification: the goal reading above, taken TWICE separated by >=30 min, with
  the INPUT stated both times. **First reading TAKEN 22:37-22:39Z and clean, but
  it lands inside the boot sync it is meant to outlast — the same defect the
  22:00Z entry named, repeated on the lane opened to fix it. The second reading
  is the one that counts, and it must be taken after that boot's sync is
  confirmed COMPLETE, not merely after N minutes.**
- Blocked by: none.

### intel-empty-pool-fallback-test — CLOSED-VERIFIED 2026-08-20 — THE ASSERTION WAS THE STALE SIDE: it asserted a `force_refresh` kwarg `#387` deliberately removed, while the empty-pool fallback branch under test was behaving correctly all along. Fixed in `tests/test_intelligence_state.py` only; production code byte-identical. Written up as `todo.md` `#494`. — opened 2026-08-20 — session dee8e41c-9e17-4dc8-9cc3-06678a05df92
- Goal: `tests/test_intelligence_state.py::IntelligenceStateTests::test_collect_candidates_with_fallback_merge_falls_back_on_empty_pool` passes on `origin/main` for the RIGHT reason — the stale side is fixed, not the assertion loosened.
- Files: `tests/test_intelligence_state.py`, `docs/ai_context/todo.md`
- Hypothesis: THE ASSERTION IS THE STALE SIDE, not the fallback path. `#387` deliberately removed `force_refresh` from the `collect_all_recommendations:empty_fallback` call site (`syndicate/features/intelligence.py:10527-10542`); the test still asserts `force_refresh=True`. The empty-pool branch itself behaves correctly.
- Falsification test: the reproduce diff is ONLY the `force_refresh` kwarg, and the fallback otherwise fires and returns the richer pool. Measured: `Expected: collect_all_recommendations(selected_date='2026-06-10', force_refresh=True, log_pipeline=False, overview=[])` / `Actual: (selected_date='2026-06-10', log_pipeline=False, overview=[])`, with `COLLECT_SPAN_EXIT stage=collect_all_recommendations:empty_fallback rows=20` and `result == richer_pool`. If the delta had been anything MORE than that kwarg — wrong rows, branch not taken — the code would have been the stale side instead. It was not.
- Verification: **RAN, ALL THREE PARTS DISCHARGED.**
  - named test **PASSES**; `-k "fallback_merge or candidate_identity"` in this file **4 passed**; `tests/test_candidate_fallback_gate.py` **4 passed**.
  - **THE CORRECTED ASSERTION STILL DISCRIMINATES** — proved by perturbation, not by inspection (08-16 rule: *a verifier that cannot FAIL cannot PASS*; a loosened assertion is not a fix). Adding a fourth kwarg `force_refresh=False` to the production call site makes the corrected test **FAIL**. The call site was then restored **byte-identical** — sha256 `f8d0f67a36d546d8…` before and after, `git diff` empty on `syndicate/features/intelligence.py`.
- **LEDGER CORRECTION OWED BY THIS LANE, recorded in `#494`:** `state.md` `[test-baselines]` records TWO pre-existing failures in this file. The second, `..._recomputes_when_cached_snapshot_is_stale`, **passes on `main`** (re-measured 2026-08-20, 72s). That baseline is dated 08-14/15 against lineage `2b14fbeb` and must not be inherited as current. A full-file run was started for a complete replacement baseline and had not finished at close; the individual re-measurement above stands on its own and is what the correction rests on.
- **NOT FIXED, DELIBERATELY, AND HANDED TO `#385`:** `#387`'s "`force_refresh` was already inert here" is true of the call site it was written about and NOT universally. The streamed board caller (`pipeline/intelligence_state.py:4636-4653`) passes `overview=None` on purpose, so there the kwarg DOES reach `build_intelligence_overview` — its removal turned a forced re-hydration into a cached one. Restoring it would reinstate exactly the re-hydration `#387` removed for memory reasons, and the branch is unreachable in production today because the same caller sets `apply_empty_pool_fallback=not board_l2a_fallback_enabled()`. It becomes a live behaviour delta the moment `#385`'s gate opens.
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




