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

### soccer-model-dispersion — OPEN — session: soccer-sport-owner — updated 2026-08-20 ~06:2xZ — TESTABLE OUTCOME NOT MET; CORE HYPOTHESIS FALSIFIED BY ITS OWN PRE-REGISTERED TEST; INPUT-QUALITY AVENUE EXHAUSTED, NEXT SESSION NEEDS A NEW HYPOTHESIS

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
- Next action: **a new hypothesis, not another input pass.** Candidates not
  yet tried: per-league systematic bias decomposition (is the model wrong
  the same direction every time, or randomly — the reliability tables in the
  08-20 result suggest calibration issues at specific probability buckets,
  not a uniform shift); whether `belgian_pro_league` being the one exception
  says something about what's different there (league-specific effect worth
  isolating before assuming it's noise); or stepping back to question
  whether Brier-vs-closing-line is achievable at all for a model built on
  this data at this sample size, separate from whether the model is "good."
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

### basketball-model-owner — OPEN — **NINE COMMITS ON `origin/main` (`#474`-`#481` + served-payload verifier). DEPLOY STATE IS FRAGMENTED AND IS THE OPEN RISK — verified by CONTENT, not ancestry: web `ba1d3368` has `#481` ONLY; live-odds-worker `b5cf8ac2` has `#478`+`#479` ONLY (they SURVIVED a concurrent deploy at 13:15:46Z, checked); refresh-worker `041188cb` has NONE. `#480`'s geometry guard is on main but on NO service. `#481` is validated OFFLINE ONLY (Brier 0.1896->0.1644 over 212 games/73,878 samples) — scheduled task `verify-wnba-live-scale-481` fires 01:20Z mid-IND@DAL to confirm on a served payload. `#479` still UNCONFIRMED in production: autorun fired 04:16Z but both artifacts remain ABSENT.** — opened 2026-08-18 — session: basketball-model-owner
- Files: scripts/basketball_sim_input_checklist.py (new), docs/ai_context/basketball_sim_engine_reference.md (new), docs/ai_context/basketball_model_inventory.md (new). **Write access:** `syndicate/features/shared/basketball_props_smart_sim.py` (`#467`/`#468`'s fixes, plus `#474`'s home-court-advantage wiring), `vendor/{wnba,nba}_betting_repo/src/*/cli.py` (`#461`), `scripts/refresh_wnba_oddsapi_props.py` + `syndicate/features/shared/basketball_boxscores_history.py` (`#469`'s silent-success fix, UA change, and the `_player_logs_ready` masking-bug fix pt3), `scripts/build_basketball_home_court_advantage.py` (**NEW 2026-08-19, `#474`**: builds `home_court_advantage.json` from real schedule+boxscore joins — the sim has NO home/away split at all today, `home_adj`/`away_adj` are purely team-quality multipliers)), `syndicate/features/wnba/cards.py` (`#475`'s live cover/total probability fix — time-decaying scale + pregame-anchor blend + anchored total projection), `scripts/build_basketball_sim_calibration.py` (**NEW 2026-08-19, `#476`**: builds the four unwired calibration artifacts from paired production sim-vs-actual history)), `scripts/build_basketball_player_logs.py`, `syndicate/features/shared/artifact_publisher.py` (**`#482`**: allowlist entries for `player_logs.csv` + `home_court_advantage.json` -- taken 2026-08-20 after the file went UNCLAIMED; handed to `soccer-odds-capture-cadence-gap` twice and never actioned) (**NEW 2026-08-19, `#477`**: derives `player_logs.csv` from boxscores+schedule so the three dead opponent/career/venue split mechanisms can fire).
- Goal: NBA/WNBA smart-sim to `model_engine_standard.md`. Current goal: get `#480` onto a service, confirm `#479`'s artifacts actually appear, and read the scheduled `#481` verification.
- Verification: `#481` graded on real outcomes (game-level split, held-out 0.1922->0.1661). `#478` root cause was OURS (our fallback box dict overrode the engine's correct 150s geometry with a hardcoded 180), not the vendored league config — my filed hypothesis was wrong. Live re-sim measured at 4.90s/5.9MB per game; refresh mutex is per-service and already enabled, so contention is placement not architecture. Narrative: `.syndicate/log/2026-08-20.md`.
- Blocked by: nothing external. Next actions are deploys + reading one scheduled result.
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

### layer2-board-movement-display — CLOSED-VERIFIED 2026-08-20 17:28Z — **Both fixes live on web (`d77dfb9a`), verified against the board's own production payload: 169 of 169 tracked/flat rows now render real movement text. Steam badge logic fixed and confirmed correct by code; no live steam event to observe at deploy time (a real, expected quiet state, not a gap).** — opened 2026-08-20 — session 2bffd747-efb5-45d8-b4f3-ae067b645eb7
- Goal (met): fix #5 (movement/steam not showing), root-caused as a
  FRONTEND bug -- the Aug 16 backend fix (`#372`, commit `1d03855e`)
  already worked, computing real movement data into top-level fields
  nothing in the template read.
- Files: `syndicate/templates/intelligence.html` only.
- **Fix, as planned:** `renderMovement()` now checks `movement_state`
  first (`tracked`/`flat`/`no_opening_for_row`/`no_openings`/`unkeyable`/
  `no_comparable_price`/`not_tracked`) and renders real text from
  `movement_price_delta`/`movement_line_delta`/`movement_direction`/
  `movement_opened_at` when present, distinguishing "no opening recorded"
  from "flat" from "not tracked" -- legacy shapes kept as a fallback.
  `isSteamCandidate()` now also checks the real `item.steam` boolean
  (previously checked only `candidate_type === "steam"`, a field from a
  different pipeline that never reaches these rows).
- **Verification: DONE, measured against live production.** Deployed to
  `web` (scoped branch off web's own live SHA `0ddd8ede`, the earlier
  #2/#3 fix), live `d77dfb9a` at 17:28:30Z. Re-pulled the board's own
  production payload post-deploy (456 cards): **169 of 169 tracked/flat
  rows (100%)** now render real movement text (e.g. "Odds +226 · 12h
  ago", "Flat · 12h ago"). `steamRows: 0` at verification time -- no row
  currently clears the `>=15 points within 3h` bar, a real and expected
  state given how rare that event is, not a rendering gap; the badge
  logic itself is confirmed correct by code review.
- Full measurement chain in `.syndicate/deploys.md`'s 2026-08-20 17:28Z
  entry.
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




