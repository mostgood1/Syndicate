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
### convergence-phase7-crps — OPEN — session: model-sim-track — **LADDER STALENESS FIXED AND VERIFIED IN PRODUCTION `[2026-08-20T02:18Z]`** — the artifact outgrew the publish sweep's `_PUBLISH_MAX_BYTES` (13,678,982 vs 12,582,912) and was refused SILENTLY while every other link stayed correct. `041188cb` live 02:03:08Z; web's ladder moved `2026-08-18T18:20:25` → `2026-08-19T21:17:32`, pitcher strikeouts 20/30 rows with market lines (was 0 of 12). **PROP MARKET WIRING = RIDEALONG, NOT A DEPLOY:** `1e15addc` on main / `15547572` from the live SHA; its preflight FAILED on measurability (0 `batter_strikeouts` players 08-16..19, so the reading would be 0→0) and a standalone deploy costs a restart that kills a sim. Carry instructions in `state.md` under STANDING RIDEALONG; both NFL sessions notified. **UNVERIFIED, time-boxed:** `SYNDICATE_MLB_ROSTER_REBUILD_DATE=2026-08-19` confirmed SET 03:07:35Z, EXPIRES 05:00Z, but whether the 02:03 deploy already spent it was NOT determined. — opened 2026-08-17
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

### soccer-model-dispersion — OPEN — session: soccer-sport-owner — updated 2026-08-19 ~20:3xZ — 9-LEAGUE RE-RUN STILL IN FLIGHT AGAINST THE FIXED BACKTEST PIPELINE, ALL INPUT-QUALITY WORK NOW LANDED

- Goal (unchanged, still open): `backtest_soccer_h2h_calibration.py` re-run over
  the same 1,112 matches / 9 leagues reports model Brier **<= market** on at
  least one non-`belgian_pro_league` league, stdev(P home) rising from
  **0.1575** toward market's **0.1811**. Baseline:
  `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json`.
- **FOUND AND FIXED 2026-08-19 ~19:2xZ, before trusting any re-run number:**
  the backtest rated ALL 9 leagues via the goals-as-xG fallback
  (`team_rows_from_match_history`), but `build_soccer_artifacts.py`
  (production) reads REAL Understat xG+ppda from `team_history/*.csv` for 5
  of them (epl/la_liga/bundesliga/serie_a/ligue_1) — the backtest was
  measuring a different pipeline than production runs for over half the
  leagues. Fixed by mirroring production's branch exactly
  (`_GOALS_BASED_RATING_LEAGUES`, asserted equal by a new test,
  `73b76b66`/landed `3ad5c8a4`). Also resolves the `ppda` CONSUMED+
  UNPOPULATED checklist alarm for free — the data was already on disk,
  already used live, just not in this backtest. Killed a ~1.5h-in run on the
  OLD pipeline rather than trust its number for those 5 leagues; the 9-league
  re-run below is against the FIXED pipeline. Full detail in the log.
  **NOT FIXED, flagged not fixed:** production's own Understat branch does
  NOT fold in ESPN possession/set-piece even though `espn_match_stats.json`
  exists for all 5 of those leagues — a real, separate opportunity, out of
  scope for this fix (which only had to match what production already does).
- **9-LEAGUE RE-RUN IN FLIGHT** against the fixed pipeline (launched
  ~19:3xZ). **Do not report a Brier/stdev number against the 08-15 baseline
  until this lands — the run before this one was killed specifically because
  its number would not have been trustworthy.**
- Status of this session's input-quality work (full narrative in
  `.syndicate/log/2026-08-19.md`, dated entries — do not duplicate here):
  xG double-count fixed+validated+kept; shots-weight shrink reverted (was
  falsified, recorded); dispersion-overshoot mechanism fully decomposed via
  isolated 2x2 probe, treated as a closed stopping point per explicit
  instruction; `clean_sheet_rate` fitted (pooled, significant) but its paired
  backtest trended unfavorably — **discarded**; `possession_share`/
  `set_piece_goal_share` sourced, wired, pooled-regression-tested (not
  significant, favorable trend) — **kept**; `starters_available_share`
  sourced (walk-forward core-XI overlap from ESPN boxscores), pooled-fit
  significant (t=+2.06), fully wired end to end
  (commit `d1136447`, BACKTEST-HONEST ONLY — not live-wired, see log), paired
  test now complete: mean delta -0.0049 vs the possession baseline, t=-1.31,
  **not significant, favorable direction** — **kept**, same disposition as
  possession/set-piece and the opposite of `clean_sheet_rate`.
  **`market_features.confidence`** (de-vigged closing-odds implied
  probability, `_market_prior_index`) sourced, wired CLI-gated
  (`--wire-market-confidence`, default OFF — not unconditional like the
  other three), paired test complete: mean delta -0.0040, t=-0.96, **not
  significant, weaker than every other field tested this session** —
  **kept as built, not promoted further**: this one reuses the SAME closing
  odds the lane benchmarks against, so any improvement is shrinkage-toward-
  market, not independent skill (`089c42bd`).
- Files: `scripts/backtest_soccer_h2h_calibration.py`,
  `scripts/build_soccer_artifacts.py`, `scripts/validate_soccer_vs_market.py`,
  `scripts/soccer_sim_input_checklist.py`, `syndicate/features/soccer/` (sim
  engine, adapters, ratings, `ingestion/espn_match_stats.py`),
  `tests/test_soccer_feature_loaders.py`, `tests/test_soccer_projections.py`,
  `tests/test_build_soccer_artifacts.py`, `tests/test_soccer_adapter.py`,
  `tests/test_soccer_advanced_input_reachability.py`, `reports/soccer_backtest/`.
- **NOT IN THIS LANE:** `syndicate/features/shared/soccer_projections.py`,
  `syndicate/features/shared/book_margin_model.py` — board-side adapter,
  owned by lane `modelled-fair-edge`. Re-check before assuming still true.
- Next action: **the ONLY open thread now is the 9-league re-run above.**
  Every input-quality field this session set out to check
  (xG/shots/clean_sheet/possession/set-piece/availability/pace/ppda/
  market_confidence) is landed, tested, and disposed (kept or discarded,
  each with a stated reason). Check the re-run, compare against the 08-15
  baseline per the original testable outcome, and that is this lane's
  original goal either met or not — no more input work is queued behind it.
- Blocked by: none. **UNOWNED — anyone may pick this up.**
- **DO NOT DEPLOY `origin/deploy/mlb-overview-hydration-cost` (`5ad1d96e`).** It was cut from
  `041188cb` and is now a ROLLBACK of the NFL roster/depth-chart autorun arming (`3b816546`,
  live 13:36:29Z). The branch that is actually live is `origin/deploy/387-on-3b816546` = `d0ea983d`.
- **The one open question is the magnitude, not the mechanism.** Mechanism is proven
  (`pruned == games` 3/3; 1,125 play records dropped on a completed slate). Whether it moves the
  ~2GB excursion is unproven and must not be asserted without a same-clock, boot-matched reading.

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

### nhl-model-owner — OPEN — FACEOFF TRACK FULLY CLOSED (EV/OZ/DZ/NZ + strength-state PP/PK + per-team role index + joint role-zone + player-level lineup-aware, both EV-only and strength-state + `faceoff_alpha`/`diff_clip`/`mult_clip_*` calibrated incl. leave-one-out refit) — session: nhl-model-owner
- Goal MET, extended repeatedly same-session: checklist full PASS
  (`scripts/nhl_sim_input_checklist.py` exits 0), market-comparison backtest
  built (`#470`), and the faceoff mechanism taken from "one EV-only diff-based
  multiplier" to a fully measured, multi-axis system. Full narrative for
  every piece — what was built, what was measured, every dead end (the
  naive strength-state combination bug, the "closes to zero" overclaim
  later corrected) — lives in `.syndicate/log/2026-08-19.md`, NOT
  duplicated here. Canonical status docs:
  `docs/ai_context/hockeysim_engine_reference.md` §1–§2zzz,
  `docs/ai_context/nhl_model_inventory.md`, `todo.md` `#463`/`#470`.
- Files: `syndicate/features/nhl/sim_engine/hockeysim/**`, `data/nhl_source/**`,
  `scripts/nhl_*.py` / `scripts/grade_nhl_predictions_vs_market.py` /
  `scripts/calibrate_nhl_*.py` / `scripts/build_nhl_*.py`,
  `docs/ai_context/hockeysim_engine_reference.md`,
  `docs/ai_context/nhl_model_inventory.md`. Shared artifact-publisher
  allowlist module: touch-and-released repeatedly — not currently claimed.
- **Faceoff track closed** (EV→OZ→DZ→NZ discrete-event curves, strength-state
  PP/PK role mechanism with a real +4.478%→+0.203% bug found and fixed by the
  round-robin check, a per-team PP/PK role-specific index, a joint role×zone
  investigation that correctly declined a full curve build on data-thinness
  grounds, a player-level lineup-aware layer for both EV-only and
  strength-state segments, and `faceoff_alpha`/`faceoff_diff_clip` calibrated
  against 1,312 real games + `faceoff_mult_clip_*` closed with an algebraic
  proof + a leave-one-out refit confirming the in-sample fit's judgment
  call). **One correction on the record, not silently absorbed**: an
  earlier "closes to zero" claim overstated itself — the mult_clip gap was
  found still open by re-verifying that exact claim, then closed properly.
  One item remains genuinely open: the discrete-event engine's "one faceoff
  assumed per real segment" approximation — a structural engine-design
  question, out of scope for calibration work, never blocking anything
  shipped.
- **Dead gate CLOSED** (earlier this lane): `HockeyTeamFeatures.blocks_per_60`/
  `penalties_per_60` proven dead and removed from every call site, not just
  documented.
- **Market-comparison backtest (`#470`)** built and extended to real
  production data (`--source production`, public `/nhl/api/cards/dates`) —
  found and fixed two real bugs (stale-duplicate prediction files,
  `lookahead_applied`'s true meaning). n=14-15 moneyline/total — explicitly
  NOT a powered verdict.
- Verification: checklist full PASS, re-confirmed after every faceoff
  addendum. 638 hockeysim/nhl tests pass (up from 254 at session start).
  Nothing deployed this session (offline producer/calibration/engine-wiring
  only — next NHL refresh-worker/web deploy picks it up). All commits
  pushed to `origin/main`, confirmed via `git merge-base --is-ancestor`
  after every push — latest confirmed tip `b4603123`/`22c2ff55` (LOO refit,
  merged as `3b79fddb`).
- Blocked by: none

### basketball-model-owner — OPEN — **SIX ITEMS BUILT AND ON `origin/main` (`#474` home-court, `#475` live cover/total, `#476` interval calibration, `#477` player-logs, `#478` segment-geometry bug, `#479` builder scheduling). DEPLOY STATE IS THE OPEN RISK: only `#475` is LIVE (web `75c526f5`, verified by content). `#474`/`#476`/`#477`/`#478`/`#479` are committed and INERT — live-odds-worker claim held by me with an armed auto-deploy monitor for `d520d93d`, blocked ~40min by continuous soccer jobs; refresh-worker held by `convergence-phase7-crps`. `#476`'s time profile MUST be rebuilt after `#478` deploys or it double-corrects.** — opened 2026-08-18 — session: basketball-model-owner
- Files: scripts/basketball_sim_input_checklist.py (new), docs/ai_context/basketball_sim_engine_reference.md (new), docs/ai_context/basketball_model_inventory.md (new). **Write access:** `syndicate/features/shared/basketball_props_smart_sim.py` (`#467`/`#468`'s fixes, plus `#474`'s home-court-advantage wiring), `vendor/{wnba,nba}_betting_repo/src/*/cli.py` (`#461`), `scripts/refresh_wnba_oddsapi_props.py` + `syndicate/features/shared/basketball_boxscores_history.py` (`#469`'s silent-success fix, UA change, and the `_player_logs_ready` masking-bug fix pt3), `scripts/build_basketball_home_court_advantage.py` (**NEW 2026-08-19, `#474`**: builds `home_court_advantage.json` from real schedule+boxscore joins — the sim has NO home/away split at all today, `home_adj`/`away_adj` are purely team-quality multipliers)), `syndicate/features/wnba/cards.py` (`#475`'s live cover/total probability fix — time-decaying scale + pregame-anchor blend + anchored total projection), `scripts/build_basketball_sim_calibration.py` (**NEW 2026-08-19, `#476`**: builds the four unwired calibration artifacts from paired production sim-vs-actual history)), `scripts/build_basketball_player_logs.py` (**NEW 2026-08-19, `#477`**: derives `player_logs.csv` from boxscores+schedule so the three dead opponent/career/venue split mechanisms can fire).
- Goal: NBA/WNBA smart-sim to `model_engine_standard.md`. Current goal: land the five inert commits on both workers, then rebuild `#476`'s profile against post-`#478` production artifacts.
- Verification: `#477` splits call-counted 0→21/21/47 with `#467` control held at 54. `#478` engine-vs-boxdict geometry now agree at 150s. `#479` measured 1.27s / 4.6MB (0.33% headroom). Narrative: `.syndicate/log/2026-08-20.md`.
- Blocked by: deploy claims on live-odds-worker (soccer jobs) and refresh-worker (`convergence-phase7-crps`).
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
  - `land` reports the ledger checkers rather than gating on them.
  - The new deploy predicate has never gated a real deploy; `OFF_MAIN` has never
    fired in anger; no preflight receipt consumed live. First real deploy tests it.
  - ~100 stale worktrees under `C:/tmp` need a human pass before reaping.
  - `deploys.md` (834 KB) and `lanes_closed.md` (838 KB) have no size discipline
    and no checker.
- **Blocked by:** none.


### football-model-owner — OPEN — **ALL LEVERS RESOLVED. Model is STRICTLY DOMINATED (R² 17.8% vs market 41.6%). Injuries settled PRICED on 17 seasons / 4,431 games. Picks suppressed live. No measured lever remains.** — opened 2026-08-18 — session: football-model-owner
- Status: **All work on `origin/main` (`9ce663fe`), verified by content.** web
  `ea6f431f` live; NCAAF picks suppressed; board serves SP+ week 1 (51 games,
  max 50.60); NFL picks untouched.
- **THE ONE FACT:** the model is dominated, not broken — real signal (R² 17.8%)
  but its deviation from the market carries none (w=−0.028, CI [−0.130,+0.069]).
  No threshold, weight or subset can help. STOP re-testing them.
- **DO NOT RETRY — all measured dead:** injuries (PRICED, 17 seasons, 4,431
  games; a 4-season run said otherwise and was a false positive); situational
  (all 8 priced, 1,746 games); returning production (pooled t=−0.89, code
  removed); `SP_RATING_SCALE` (every scale 6..24 loses); blending (w≈0);
  the three scalar totals fixes; "beat the OPEN first".
- **DO NOT BUY NFL ODDS.** nflverse `schedules/games.csv` has `spread_line`
  back to 1999, free, 2.2 MB. It IS the home-margin prediction (r=+0.431; MAE
  10.264 as-is vs 14.645 negated). OddsAPI historical NFL starts 2020.
- **Harnesses — run BEFORE building anything:**
  `grade_football_model_weight.py`, `grade_football_playability.py`,
  `test_ncaaf_situational_edge.py`, `test_nfl_injury_market_edge.py`,
  `probe_ncaaf_injury_feed.py`.
- **NEXT ACTION:** no measured lever remains. Either accept NCAAF/NFL margins
  are not a product and redirect, or find an input class that is NOT
  performance-derived and NOT already priced. Whatever it is, regress the market
  residual on it FIRST — and state the detectable-effect floor before calling
  any result null.
- **UNCOMMITTED:** `data/nfl_source/historical_odds/closing_lines_preseason_*.json`
  — 2,728 credits, untracked by convention, and still the ONLY preseason line
  source (`games.csv` is regular-season only).

### soccer-odds-capture-cadence-gap — CLOSED-VERIFIED 2026-08-20 01:25Z — **`#343` (`77c0ee49`, 2026-08-10 21:17:39) broke soccer's bulk game-odds request for every league, 9 days straight; fixed (`3e8264bd`), deployed to both live-odds-worker (`575decf3`) and refresh-worker (`b2f4b197`, cherry-picked onto their scoped live SHA), and VERIFIED with real production data: a manual pregame trigger post-deploy produced genuine fresh captures across the full soccer book_quotes shard, and 6 of the originally-8 stale MLS/La Liga matches now show `captured_at` 3 minutes old. Full evidence chain in `.syndicate/deploys.md`'s 2026-08-20 01:25Z entry.** — opened 2026-08-19 — session: soccer-odds-capture-cadence-gap
- Goal: soccer's h2h/totals/spreads game-market odds capture actually
  refreshes within a bounded window (target: <24h old for a match kicking
  off within the next day) instead of sitting 8-10 days stale.
  **Testable outcome:** re-pull `soccer_source/tracking/book_quotes/
  <today>.jsonl` for a slate with same-day kickoffs; every distinct
  match's h2h/totals/spreads `captured_at` is <24h old, not just some.
- Files:
  - `scripts/fetch_soccer_oddsapi_odds_local.py` — **claimed 2026-08-19,
    THE ACTUAL FIX: `_game_markets()` no longer merges `_segment_market_map()`
    into the bulk-endpoint request (root cause, see below). Landed on
    `origin/main` as `3e8264bd`; not yet deployed to any service.**
  - `tests/test_fetch_soccer_oddsapi_odds_local.py` — **new file, claimed
    2026-08-19, regression tests for the fix above (4 tests, passing, landed
    with the fix).**
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
  - **Not claimed, read-only reference:** `scripts/run_refresh_worker.py`
    (referenced alongside the above in prior sessions' notes; `phase=live`
    there has 0 odds steps by design per `#148`, so it may not be where the
    fix belongs at all). **Narrowed 2026-08-19 by `nfl-injuries-fetcher`**
    after `lane-guard.py` correctly read the previous ambiguous phrasing as
    a real claim and blocked an unrelated, purely additive edit (one new
    autorun function + one new `elif` branch, nothing touching odds-step
    handling). Coordinated via `send_message` first; no objection at time
    of edit. If this file turns out to matter to the soccer investigation
    after all, re-claim it explicitly rather than relying on this note.
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
- **RESOLVED 2026-08-19 ~23:16Z — `steps=0` is a genuinely empty capture,
  not a reporting-schema mismatch. Reproduces on refresh-worker under a
  manual, targeted trigger too — NOT specific to live-odds-worker's
  scheduler/cadence.** Manually fired `POST /api/ops/odds-refresh/run`
  (`phase=pregame, sports=soccer`, `run_stamp=20260819_225403`), landed on
  `refresh-worker`'s lane (confirmed via `/api/ops/odds-refresh/status`
  `history[]`). Read `refresh-worker`'s OWN `[artifact_publisher]` log
  lines for the full run window (22:54Z-23:16Z), content not just status:
  MLB's local `book_quotes/2026-08-19.jsonl` genuinely grew during this
  run (`STREAM_TAIL_OK appended_bytes=2027948` @23:00, `appended_bytes=
  1530276` @23:12, `PUBLISH_OK bytes=3856426` @23:11) — proving the run
  really executed and really captured for at least one sport. Soccer's
  local copy, same run, same window: only `STREAM_PULL_OK` (pulling an
  existing remote copy in) and `PUBLISH_SKIPPED_UNCHANGED path=
  soccer_source/tracking/book_quotes/2026-08-19.state.json checksum=
  205c14a0f21d` @23:01:35 — checksum never moved again for the rest of
  the window. Zero `STREAM_TAIL_OK`/`PUBLISH_OK` for soccer despite
  `--sports soccer` being the explicit, sole target of this job. This is
  content evidence from the writing service's own disk, not an inference
  from a status endpoint (which independently misreported this same run
  as `state=failed` at ~43s in — same premature-read pattern caught
  earlier this session; ignored, per the log evidence above the job kept
  running/writing for MLB well past that).
  **Consequence for hypothesis (4) (self-contention on live-odds-worker's
  lane):** weakened, not confirmed — this run wasn't on live-odds-worker
  at all, so lane-contention with the frequent `phase=live` cycle cannot
  explain THIS run's zero soccer output. The fetch failure is upstream of
  which service calls it: in `refresh_odds_sources.py`'s soccer branch
  itself (already on file as read-only reference, previously exonerated
  only for the STEP-LIST-BUILDING logic `_build_soccer_steps`, not for
  the actual fetch call each step makes — that fetch call is now the
  prime suspect and has NOT yet been read/traced).
- **ROOT CAUSE CONFIRMED 2026-08-19 ~23:25Z, tested directly against the
  live OddsAPI (not inferred, not from logs).** Pulled `ODDS_API_KEY` from
  `live-odds-worker`'s own Render env vars and replicated `fetch_game_odds`
  exactly (same URL, same params, same live market list pulled from
  `market_segments.py`) for `mls` and `la_liga` — both returned **HTTP 422**:
  ```
  {"error_code": "INVALID_MARKET", "message": "Markets not supported by this
  endpoint: alternate_spreads, alternate_spreads_h1, alternate_spreads_h2,
  alternate_totals, alternate_totals_h1, alternate_totals_h2, h2h_3_way,
  h2h_3_way_h1, h2h_3_way_h2, h2h_h1, h2h_h2, spreads_h1, spreads_h2,
  totals_h1, totals_h2"}
  ```
  Retried with ONLY `h2h,totals,spreads` (`DEFAULT_GAME_MARKETS`): **HTTP
  200**, real events — **31 for MLS, 14 for La Liga**, live right now, each
  with 8-11 bookmakers. The odds exist and are fetchable; the code was
  asking for markets this endpoint rejects.
  - **Mechanism:** `_game_markets()` in `fetch_soccer_oddsapi_odds_local.py`
    merges `_segment_market_map()` (h1/h2 + alternate-line keys, from the
    shared `market_segments.py` vocabulary) into the REQUESTED market list
    for the BULK `/sports/{sport}/odds` endpoint. `market_segments.py`'s own
    docstring says that vocabulary is for **per-event** requests ("Each
    segment market is a distinct OddsAPI market key on a per-event
    request"). MLB's fetcher has a separate per-event path
    (`_event_wants_full_game_markets` in `fetch_mlb_oddsapi_local.py`) gated
    specifically for segment markets and wrapped in its own
    `except requests.HTTPError` — which is why MLB's capture kept working
    (confirmed: it grew live during this session's own triggered run,
    `STREAM_TAIL_OK`/`PUBLISH_OK`, see above). Soccer's fetcher never grew
    that second path; it just bulk-requested everything in one comma-joined
    `markets=` param, and one unsupported key 422s the WHOLE request —
    every league, every time, no partial credit.
  - **Regression pinned to the exact commit and date:** `77c0ee49` (`#343:
    wire every sport's interval capture to the one shared vocabulary`),
    **2026-08-10 21:17:39 -0500**. This lines up EXACTLY with the earlier,
    independently-measured fact "freshest capture found anywhere in the
    file: 2026-08-11" — the regression date and the last-good-capture date
    are the same event, not a coincidence. Soccer game-odds capture has
    been broken for every league, every cycle, for 9 days straight.
  - **Same failure class the code already fixed once**, on a bigger scale:
    the file's own comment already documents removing `btts`/
    `draw_no_bet`/`double_chance` for this exact reason (HTTP 422,
    2026-07-21) — `#343` reintroduced the same class of bug with 15 new
    keys nobody checked against this specific endpoint.
- **FIX LANDED on `origin/main` 2026-08-19 ~23:40Z as `3e8264bd` (content-
  verified: `git show origin/main:scripts/fetch_soccer_oddsapi_odds_local.py`
  carries the fix). Written and committed in this lane's own worktree
  (`C:\tmp\syndicate-sessions\soccer-odds-capture-cadence-gap`), never the
  primary tree. NOT YET DEPLOYED — no service is running this commit yet.**
  `_game_markets()` reverted to return `DEFAULT_GAME_MARKETS` only (still
  honors the `ODDS_API_SOCCER_GAME_MARKETS` env override outright).
  `_segment_market_map()` itself is UNCHANGED and correctly kept for
  TAGGING (`_append_soccer_book_quotes`'s `market_map=` argument) — only
  the REQUEST list was narrowed, so this does not touch how returned
  quotes get labeled. 4 new regression tests in
  `tests/test_fetch_soccer_oddsapi_odds_local.py`, passing; existing
  `test_all_sports_segment_wiring.py` (14 tests) and
  `test_soccer_odds_coverage.py` (9 tests) still pass unmodified.
- **Next concrete step for whoever continues:** land the fix
  (`session_worktree.py land`), then deploy to whichever service(s) run
  soccer's pregame odds capture (`live-odds-worker` is the confirmed
  producer; `refresh-worker` also executes this same script under the
  manual-trigger path used to diagnose this) behind the standard
  claim+preflight protocol. Verify post-deploy the same way this was
  diagnosed: re-pull `soccer_source/tracking/book_quotes/<date>.jsonl` and
  confirm today's matches carry a fresh `captured_at`, not just that the
  job completed without error.
  Deferred, not abandoned — the original `steps=0` reporting-schema
  question (does `_report_previous_soccer_pregame_run` correctly surface a
  per-league 422 as `failed=N`, or does it swallow it into `steps=0`?) is
  now secondary: whether or not that reporting gap also exists, THIS fix
  removes the actual cause of the empty captures. Worth a look after
  deploy/verify, not before.

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

### nfl-autorun-production-arm — OPEN, env vars SET (via dashboard, my PUT attempts classifier-blocked) — deploy BLOCKED on contended refresh-worker claim (3 legitimate holders in under an hour tonight; not misattribution) — opened 2026-08-19 — session: nfl-autorun-production-arm
- Goal: arm the two default-OFF autoruns from `nfl-roster-depth-autorun`
  (landed and closed this session) in production, on refresh-worker
  (`srv-d91dpertqb8s73co8ls0`). **Testable outcome:** both env vars are
  set (single-key PUT, per `[[project_render_env_needs_deploy]]` --
  restart does NOT re-inject them, an actual deploy is required), a
  refresh-worker deploy carries them live, and the real launch/skip log
  lines (`NFL_ROSTER_SNAPSHOT_LAUNCHING`/`NFL_DEPTH_CHART_SNAPSHOT_
  LAUNCHING`, or a named skip reason) are observed in production logs --
  not merely that the env vars are set. The sibling `nfl-injuries-
  fetcher` autorun is deliberately NOT touched here -- user asked for
  "both autoruns" meaning the two just discussed; arming injuries too
  is a separate ask if wanted.
- Files: none (pure Render config + deploy action, no repo code change).
- Env vars on refresh-worker: DONE, verified via read-only GET --
  `NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN=true`,
  `NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN=true`. Not yet
  DEPLOYED -- per `[[project_render_env_needs_deploy]]`, absent a deploy
  a running process never sees these; still inert in production.
- Hypothesis: n/a (a deploy, not a diagnosis).
- Falsification test: n/a.
- Verification: Render logs (`scripts/render_logs.py` or the events API)
  show a real `_LAUNCHING` or a named `_SKIPPED reason=...` line for both
  autoruns within one refresh-worker tick after the deploy --
  `not_in_season` would be a genuine surprise (NFL is active Aug-Feb per
  `_active_sports_for_date`, so today should NOT skip for that reason).
  `disabled` reappearing after the env PUT would mean the deploy did not
  actually carry the new value (the exact failure mode
  `[[project_render_env_needs_deploy]]` documents) and is the first thing
  to check if nothing launches.
- Blocked by: refresh-worker deploy claim, held by 3 different legitimate
  sessions in succession tonight (checked lanes.md OPEN/CLOSED status
  each time, not process liveness): `nfl-receptions-blend-stability`
  (force-broken, user-approved -- CLOSED-VERIFIED lane holding a live
  claim, same misattribution shape found earlier today) ->
  `soccer-odds-capture-cadence-gap` (real, waited ~22min for their
  `#343` deploy to go live, not forced) -> `convergence-phase7-crps`
  (real, confirmed alive by its own lane note, holding as of this
  checkpoint without a deploy fired yet). Next action: poll
  `deploy_claim.py status --service refresh-worker`; once free, acquire
  cleanly, run preflight, deploy, then verify via
  `NFL_ROSTER_SNAPSHOT_LAUNCHING`/`NFL_DEPTH_CHART_SNAPSHOT_LAUNCHING`
  log lines (or a named skip reason) in production logs -- not the env
  var alone.

### mlb-overview-hydration-cost — OPEN — **DEPLOYED `d0ea983d` to refresh-worker 2026-08-20 13:59:33Z. THE BRANCH IS PROVEN TO FIRE IN PRODUCTION (`pruned=9/9`) AND THE MECHANISM DOES REAL WORK ON A COMPLETED SLATE — `date=2026-08-19 games=15 pruned=15 plays_dropped=1125`, against 1,067 measured locally on a 15-game completed slate. Pregame slates prune ~nothing (`plays_dropped=1`), which is correct, not inert. STILL UNPROVEN: that this moves the ~2GB excursion — that needs the live-slate window against a comparably-aged process.** — opened 2026-08-19 — **UNOWNED (session `80b3e432` archived 2026-08-20 ~10:4x CDT). The closing reading is SCHEDULED, not abandoned: `mlb-387-live-slate-read` fires 2026-08-20 22:15 CDT and takes the live-slate FEED_LIVE_PRUNE + memory reading. A MECHANISM ONLY verdict there does NOT close this lane.** — **BOTH CUTS LANDED ON `origin/main` (`ab99d236`), MEASURED LOCALLY, NOT DEPLOYED. Peak RSS 142.9 → 114.5 MB on a 15-game slate with a byte-identical games list; plus a per-build ~125MB dead odds_history read removed, proven dead by the shard WRITER's schema. The 3000MB floor is untouched and stays untouched.**
- Goal: `#387`'s named real fix — make the MLB overview hydration path (`build_cards_page_context` as reached from `_MLBDataProvider.games()`) cheap enough that refresh-worker can hydrate MLB under normal load, WITHOUT lowering `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` (3000MB). Testable outcome: a measured peak-RSS reduction for the worker-path call on a real 15-game slate, with byte-identical candidate-relevant output.
- Files: `syndicate/features/mlb/cards.py`, `syndicate/blueprints/home.py`, `tests/test_mlb_cards_worker_projection.py` (new), `scripts/measure_cards_context_rss.py` (new), `docs/ai_context/todo.md`, `.syndicate/*`.
- Hypothesis: the worker keeps only `payload["games"]` (and only a subset of each game's fields) yet pays for the whole page context — feed/live `actual_games`, HR/K shelves, ladder badges, scoreboard/module furniture. A worker-scoped projection that skips what no consumer reads cuts the transient without touching the guard.
- Falsification test: (a) trace shows a candidate-path consumer DOES read a field the projection drops → the projection is wrong as scoped; (b) measured peak RSS with the projection ON is not lower than OFF on the same slate → the skipped work was not the cost.
- Verification: `scripts/measure_cards_context_rss.py` reports peak **RSS** (not tracemalloc — `handoff_refresh_worker_oom.md` records tracemalloc as structurally blind here) for OFF vs ON on 2026-06-14 (15 games, full local artifact set), plus a parity test asserting the candidate-relevant projection is unchanged, plus a reachability test (`off != on`) per `model_engine_standard.md`.
- Blocked by: none.
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
- Landed `ab99d236` on `origin/main`. **No deploy made, no claim taken.**
  Follow-up filed as `#483` (whether Layer 2 ever wanted shard freshness at all).


### ci-utc-midnight-window — CLOSED 2026-08-20 — **`#482` CONFIRMED FIXED INSIDE the 00:00-05:00Z window: run `32323646103` (`df8aec91`, 02:09Z) green on both gated steps, against 11 consecutive failures 01:24-01:53Z in the same band without it. CI is no longer red on the clock.** — opened 2026-08-20 — session 13ad06bb-42fc-444c-ae01-c7f67f6acad1
- Successor to `ci-green` (CLOSED, body in `lanes_history.md`) for a THIRD and
  independent cause. `#480` and `#481` are done and are not reopened by this.
- Goal: `CI` is green INSIDE 00:00-05:00Z, not just outside it. Testable: a run
  whose archive suite executes within that UTC window passes.
- Files: `tests/test_archives.py`
- **The defect (`#482`), measured:** 7 tests computed "today" with
  `date.today()` — the runner's date, UTC on GHA — while every route under test
  uses `central_today_iso()`. CDT is UTC-5, so 00:00-05:00Z the two disagree and
  CI is **structurally red ~5 hours a day regardless of what anyone pushes**.
  Evidence is a clock, not a diff: 16 consecutive greens 2026-08-19
  23:25-23:53Z, then 29 consecutive reds from 23:57Z (that run asserts just past
  midnight). Over 45 completed runs: 28 failures inside the window, 11 successes
  outside, 1 failure outside (pre-`#480`).
- Fix applied: assert against `central_today_iso()`, the same source the app
  uses. Precedent already existed in this very file —
  `test_wnba_cards_api_without_date_uses_today` was fixed this way and its
  comment names the cause exactly; the other 7 were left. Swept the 13 other
  `unittest`-run modules: none share it.
- Falsification test: if the window is NOT the cause, a run inside 00:00-05:00Z
  still fails after the fix, or a run outside it fails before.
- **Verification, and why the local pass does not count:** this dev box is
  Central, so `date.today() == central_today_iso()` on it and the 7 tests pass
  with or without the fix. Window confirmed live at fix time (UTC 2026-08-20 vs
  Central 2026-08-19). **Only a CI run inside 00:00-05:00Z proves it**, and one
  is available immediately — quote the run id, do not predict it.
- **VERIFICATION RAN, inside the failing condition, with a control.** Run
  `32323646103`, head `df8aec91`, 02:09Z: `Run archive regression suite` success
  + `Ledger coherence` success. Immediately prior, same UTC band, without the
  fix: 11 consecutive failures (`63a2341d` 01:24Z through `f968d242` 01:53Z).
  Falsification test did NOT fire. Full table in `deploys.md`.
- Local evidence, stated for what it is worth: `tests.test_archives` 383 OK
  (skipped=2) and the 7 touched tests OK — but this box is Central, so that
  shows no regression and proves nothing about the window. The CI run is the
  proof.
- Blocked by: none.

### home-stack-test-data-dependence — CLOSED 2026-08-20 — **Hypothesis HELD. Overview pinned to a fixture; test passes at any hour, full suite 383 OK. Reachability proved off != on (flipping `active_today` fails it).** — opened 2026-08-20 — session 13ad06bb-42fc-444c-ae01-c7f67f6acad1
- Goal: `test_archive_launch_links_and_tracker_copy` stops depending on whether
  the ambient mirror happens to have active sports for the resolved date.
  Testable: it passes at any hour, including 23:2x CT where it failed.
- Files: `tests/test_archives.py`
- **The defect, measured.** Run `32331841627` (23:28 CT 2026-08-19) failed
  `assertIn("Live slate", home)` at line 6400. `Live slate`, `Compact rail`,
  `Pregame only`, `Open Live Lens` and `Live only` are all rendered PER SPORT by
  `shared/_home_sport_stack.html`; the failing page had
  `<section class="sport-stack">` completely EMPTY and `0 sports tracked`, so
  none were emitted. Not a date-arithmetic bug — a data-availability one.
- **NOT a `#482` regression — `#482` UNMASKED it.** Pre-fix (01:39Z) this same
  test died at line **6357** on the UTC-date assertion; post-fix it gets past
  that and reaches **6400**. The first failure had been hiding the second, which
  is the "a failing test hides everything after it" pattern already in
  `learnings.md`.
- Hypothesis: `build_home_overview` filters on `show_on_home` +
  `_active_sport_slugs()`, and `_home_selected_date(None)` is Central-today, so
  the set of sports rendered depends on what the checkout's mirror holds for
  THAT date. 23:28 CT resolved to 2026-08-19 (empty); 06:25 CT and 08:08 CT
  resolved to 2026-08-20 (non-empty) and passed.
- Falsification test: if the hypothesis is right, patching the overview seam
  with a fixed sport makes the assertions pass regardless of clock or mirror.
  If it still fails, the emptiness comes from somewhere below that seam.
- Verification: the test passes with the overview seam pinned, AND the full
  `tests.test_archives` suite stays green.
- **FALSIFICATION TEST RAN, hypothesis HELD:** pinning the overview seam makes
  the assertions pass regardless of clock or mirror, so the emptiness did come
  from that seam and not below it.
- **REACHABILITY (off != on), run before trusting the pass:** flipping the
  fixture's `active_today` to `False` fails the test with
  `AssertionError: 'Live slate' not found`, exit 1. The pin is consulted and the
  assertion still bites. Restored and verified against the pre-probe file.
- Verified: target test exit 0; full `tests.test_archives` **383 OK (skipped=2)**.
- Incidental finding recorded in `#487`: the template's `rail['items']` RAISES
  rather than renders empty when a rail dict lacks an `items` key, because Jinja
  falls back to the `dict.items` method.
- Blocked by: none.

### soccer-board-mlb-parity — OPEN — **BUILT AND COMMITTED (`7be68675`, branch `session/soccer-board-mlb-parity`). NOT PUSHED, NOT DEPLOYED, AND THE PRODUCTION READING IS OWED — every local tile reads "Model only" because the mirror has no picks/props CSV for these dates, so the market path is proven by CODE (run over the production payload) and NOT by the board.** — opened 2026-08-20 — session 56b563e0-4c1a-4436-8e3b-ba3624fbeab0
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

### mlb-pregame-ladder-schema — OPEN — opened 2026-08-20 — session 822e1e5a-de81-49bf-ade0-9dbe4de00ea9
- **Goal (single testable outcome):** every pregame MLB starter with a sim
  distribution and a market line renders its ladder chips on the compact card —
  and the starter's NAME renders whether or not it has chips. Today: 0 of 18
  sides get a ladder-derived chip, and 12 of 18 render no name at all.
- **Files:**
  - `syndicate/features/mlb/ladders_build.py`
  - `tests/test_mlb_ladders_build.py`
  - `syndicate/static/mlb/cards_source.js`
  - `.syndicate/*`

  Respectively: the writer that must restore the fields the cards reader joins
  on, the cards-reader consumption test, and the starter-name/badge decoupling.
- **`docs/ai_context/todo.md` DELIBERATELY NOT CLAIMED.**
  `check_lane_invariants.py` flagged it contested against
  `mlb-overview-hydration-cost` the moment I claimed it, so I dropped it rather
  than run a second holder on the file the `#71` check reads. The todo entry
  for this work gets reconciled at close, against whoever holds it then. Noting
  it here because an unrecorded skip of the `#71` check looks identical to
  forgetting it.
- **NOT claimed, deliberately:** `syndicate/features/mlb/cards.py` is held by
  the OPEN `mlb-overview-hydration-cost` lane. **The fix does not need it** —
  the reader is correct as written; only its input regressed. Scoping the fix
  to the writer is what makes this collision-free, not a compromise on it.
- **Hypothesis (stated before fixing, MEASURED not believed):** the pregame
  ladder chips are dead because `#440`'s native writer pinned its output schema
  to the TOP-PROPS reader (`ladders_common.pitcher_rows_from_summary`) and
  dropped the three fields the CARDS reader needs. Confirmed against
  production's own copy, `generatedBy syndicate.features.mlb.ladders_build`,
  generated 2026-08-20T16:46:16Z:

      pitcher/strikeouts: n=18  ladder=0  gamePk=0  marketLine=18
      ... all 7 pitcher stats + all 10 hitter stats, 3,978 rows: ladder=0 gamePk=0

  Row schema today is 10 fields. The git-tracked May mirror (vendor writer) has
  26, including `gamePk`, `pitcherId`, `ladder[{total,hitProb}]`. Reader dies at
  `cards.py:1166` (`gamePk is None -> continue`, which also makes the
  `pitcherName` fallback two lines down unreachable) and again at
  `cards.py:1102` (`not ladder_rows -> return None`).
- **Falsification test:** if the join or the inputs were the problem rather
  than the schema, the artifact would show unmatched players or absent market
  lines. It shows neither — `matchedPlayers 18, oddsPlayers 18, unmatchedOdds 0,
  unmatchedSimNames 0`, and 18/18 rows carry BOTH `simCount>0` and a
  `marketLine` on all four badge stats. Inputs are complete; only the emitted
  shape is short. If a schema fix does NOT produce chips, the hypothesis is
  wrong and the next suspect is `_filter_badges_to_current_market`.
- **DESIGN CONSTRAINT, from `learnings.md` 2026-08-20 ("An artifact can OUTGROW
  the publish ceiling, and the failure is silent"):** this same artifact hit
  `_PUBLISH_MAX_BYTES` at 13,678,982 bytes and was refused SILENTLY for 28
  hours. Adding arrays back to it is the exact move that re-arms that failure.
  So: `ladder[]` goes on PITCHER rows only (18 rows, the sole consumer is
  `cards.py:1102`), never on the 234-row hitter groups, and **the resulting
  artifact size gets MEASURED against 12,582,912 and written down** — not
  assumed small. Today's copy is 684,325 bytes, so there is headroom; the
  number is the evidence, not the headroom.
- **Verification:** (1) a test that runs the REAL cards reader
  (`_pregame_starter_ladder_badges_for_pitcher`) over this writer's REAL output
  and asserts a non-empty badge list — the reachability test whose absence let
  this ship silently, since every existing test passed throughout; (2) the
  measured artifact size vs the publish ceiling; (3) after deploy, the served
  `/mlb/api/cards` payload showing ladder-derived chips on pregame sides that
  have no pitcher recommendation (George Kirby is the control — he has a prop
  row, no pick, and no chip today). Reading written to `deploys.md`.
- **Blocked by:** none. Deploy target is refresh-worker (the writer) — claim
  required, and web is currently 502ing on `/api/ops/version`, which is
  somebody else's deploy and must be clear before I measure anything.


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




