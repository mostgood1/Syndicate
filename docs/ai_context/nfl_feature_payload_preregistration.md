# Pre-registration — wiring the feature payload into smartsim2 (NFL regular season)

> ## HALTED 2026-08-18 BEFORE PHASE 3 — THE PAYLOAD IS LEAKED
>
> **`build_nflverse_game_metrics` computes its EPA / success-rate / pass-rate
> fields from THE GAME BEING PREDICTED**, not from prior form.
> `_match_game_rows` (`nflverse_ingestion.py:151`) filters play-by-play to rows
> where `home_team == home AND away_team == away` for that season and week —
> i.e. that one game's plays.
>
> **Falsification test, stated before running and then run:** prior-form team
> strength should correlate with a single game's final margin at roughly
> r = 0.3–0.5. In-game EPA would exceed 0.8, because EPA accumulated during a
> game nearly restates who won it.
>
> **Measured over 285 games of 2023: r = 0.988.**
>
> So the "1.125 pts of margin movement" I measured when wiring the payload was
> real and worthless — the engine was being handed the answer. **Any backtest
> built on this would have looked spectacular and meant nothing**, which is the
> `learnings.md` rule that a leaked backtest number is an UPPER BOUND, not
> merely an untrustworthy one.
>
> **What this does NOT invalidate:** that 0 of 3 production entrypoints pass the
> payload, and that the fed terms therefore reach the sim not at all. That
> finding stands. What changes is the REMEDY — wiring this payload as it exists
> today would ship a leaked model, not a better one.
>
> **What the experiment needs before it can run:** an as-of feature builder that
> computes team form from games STRICTLY BEFORE the one being predicted. That is
> a real piece of work and it does not exist. Everything below is retained
> because the sample, power and noise-floor analysis stay valid for it.

> Written 2026-08-18, lane `football-model-owner`, BEFORE any modelling work.
> Follows the pattern of `mlb_edge_scan_preregistration.md`: the decision rule is
> fixed in advance so a null result cannot be re-described as a win.
>
> Governed by `model_engine_standard.md`. §4.3 (reachability first), §4.4
> (mechanism vs estimator), §4.5 (a single-feature measurement understates a
> suppressed feature), §3b (Render is the substrate).

---

## 0. The claim being tested

**`build_drive_priors` reads 33 alias-terms out of `feature_generation_payload`,
and no production entrypoint passes that payload.** Wiring it changes **21 of 21**
drive-prior fields, and on one worked game moved margin **1.125 pts**, total
**1.685 pts**, home win prob **6.5 pts** (measured 2026-08-18, 400 seeds/arm).

**The claim is NOT "the model gets better."** It is:

> Feeding the payload, *with the calibration re-fitted for it*, produces a
> **lower CRPS against realised margins** than the current unfed engine, on
> held-out NFL games, by more than the harness's own noise.

**A movement of the numbers is not the result.** §4.4: a calibrated engine's
fitted rates have already absorbed the average effect of a missing mechanism, so
re-adding it without a re-fit double-counts. Two mechanisms added to MLB this way
produced a **negative interaction in 4 of 4 markets**.

---

## 1. SAMPLE — corrected 2026-08-18, my first figure was wrong

**RETRACTED: "the usable sample is ONE SEASON, n=272."** That was an artifact of
the LOADER I measured through, not of the data. `FootballSimulationAdapter.
load_features` routes via `build_cards_page_context`, whose season list comes from
`week_summaries()` — which globs **`upcoming_recs_*.csv`, the legacy UI
recommendation snapshots**. Those exist only for 2025/2026. It never consulted
play-by-play at all.

**What is actually present AND reachable** (verified by calling
`load_nflverse_rows`, not by listing files — presence is not reachability):

| season | pbp rows | games |
|---|---|---|
| 2022 | 49,434 | 284 |
| 2023 | 49,665 | 285 |
| 2024 | 49,492 | 285 |
| 2025 | 48,771 | 285 |
| **total** | **197,362** | **1,139** |

**No pbp fetch is required.** Substrate: the local git-tracked mirror
(`data/nfl_source/tracking/nflverse/pbp/`), which is legitimate for a BACKTEST —
§3b forbids drawing *production* conclusions from local, not offline model
testing. Any production claim still goes to Render.

### The real constraint is CLOSING LINES, not features

`real_betting_lines_*.json` runs **2025-09-01 → 2026-08-01** (160 files). So:

| metric | needs | usable n |
|---|---|---|
| **paired ΔCRPS on margin vs OUTCOMES** (primary) | features + result | **1,139** |
| market-relative CRPS vs the closing line (§5 goal) | + closing line | **~285, 2025 only** |
| ATS hit rate / ROI | + closing line | ~285 — **still unusable** |

### Revised power

| metric | SE | detectable (2 SE) | verdict |
|---|---|---|---|
| paired ΔCRPS, n=1,139 | ~**0.12 pts** | ~**0.25 pts** | **good — 2× better than first stated** |
| paired ΔMAE, n=1,139 | ~0.15 pts | ~0.30 pts | usable |
| market-relative CRPS, n=285 | ~0.25 pts | ~0.5 pts | usable |
| **ATS hit rate, n=285** | **2.96 pts** | **~6 pts of edge** | **UNUSABLE** |

**Therefore ATS hit rate and ROI are FORBIDDEN as the decision rule for this
experiment.** They are reported as descriptive context only. This is the
2026-08-17 rule — score a distributional forecast with a distributional
baseline — and the 2026-08-18 rule that this harness's noise floor was **2.4×
the effects it was used to judge**.

**Paired** is load-bearing: both arms run the same games, so game difficulty
cancels and the SD of the *difference* is what matters, not the ~13.5-pt SD of
NFL margins.

### Monte Carlo noise — MEASURED, and my earlier reasoning was wrong

**Phase 2 ran 2026-08-18.** Two identical arms, disjoint seed blocks, one game:

| seeds | arm A | arm B | \|A−B\| |
|---|---|---|---|
| 200 | 2.600 | 2.550 | 0.050 |
| 500 | 1.874 | 1.728 | 0.146 |
| 1,000 | 1.800 | 1.263 | **0.537** |
| 2,000 | 1.245 | 1.025 | 0.220 |

**Read the non-monotonicity, do not average it away.** 1,000 seeds showing a
*larger* gap than 500 is not a property of the engine — a single |A−B| draw is
itself a random variable, so ONE pair cannot estimate a floor. **This table is
four noisy draws, not four floors.** Estimating it properly needs k repeats per
seed count; that is owed work. Magnitudes agree with theory (13.5/√2,000 = 0.30
vs 0.22–0.54 observed), which is all that can honestly be claimed.

**AND THE CONCLUSION I DREW BEFORE MEASURING WAS WRONG.** I wrote that "at 300
seeds the RNG noise swamps the effect." That is true PER GAME and irrelevant to
this experiment, which compares an AGGREGATE over ~1,139 games. Monte Carlo error
on an aggregate falls as `13.5/√(seeds × games)`:

| seeds | per-game noise | aggregate over 1,139 games |
|---|---|---|
| 300 | 0.78 | **0.023** |
| 500 | 0.60 | 0.018 |
| 2,000 | 0.30 | 0.009 |

Against a ~1.1-pt effect, **even 300 seeds leaves aggregate MC noise ~50× smaller
than the signal.** MC noise is NOT the binding constraint; sampling error across
games (SE ~0.12) is, and that is 5× larger than the MC term at 300 seeds.

**Cost consequence.** Phase 2 at 2,000 seeds is **38.8 hours** for two arms
(measured: 8.5 ms/sim). At 500 seeds it is **~9.7 hours** for a distributional
score that is still well-resolved. **The 2,000 figure was over-specified by my
own bad reasoning and would have burned ~29 hours of worker time for nothing.**

Use **500 seeds** for mean-based scoring. CRPS needs each game's predictive
distribution, not just its mean, so if CRPS is primary, justify the seed count
against the CRPS estimator's own convergence rather than reusing this table.

---

## 2. Phases, in order. Each gates the next.

### Phase 0 — Coverage, stated not assumed
Done, above. **1,139 games** for the primary metric; **~285** for anything
market-relative. Report which of the two any given statistic rests on — they are
not interchangeable, and quoting the 1,139 beside a market-relative number would
overstate it by 4×.

**OPEN DECISION — historical closing lines for 2022–2024.** Backfilling them would
lift the market-relative arm from ~285 to ~1,139 and is the ONLY thing that makes
ATS/ROI testable (SE 2.96 → 1.48 pts). OddsAPI historical endpoints are cheap
against the 5M cap, and `scripts/backfill_mlb_historical_odds.py` is a working
precedent to copy. **Not done unilaterally — it spends API budget and belongs to
whoever owns that budget.**

### Phase 1 — Reachability, BEFORE correctness (§4.3)
Flag `SYNDICATE_SMARTSIM2_FEATURE_PAYLOAD`, as a **declared dataclass field** —
`dataclasses.replace()` silently drops attributes set with `setattr`.

```python
assert run(payload=off, seed=S) != run(payload=on, seed=S)
```

**If off == on, everything downstream is meaningless.** Four inert features were
caught by exactly this check and by nothing else.

### Phase 2 — The harness's own noise floor
Run the **same config twice** with disjoint seed blocks. The spread between two
identical arms IS the noise floor.

**Any effect smaller than this floor is unmeasurable, full stop.** Publish the
floor beside every later number. Raise seeds until the floor is < ⅓ of the
effect being chased.

### Phase 3 — Mechanism ON, calibration UNCHANGED
Wire the payload. Re-measure. **Expect possible DEGRADATION** — this is the
double-count, and observing it is a successful measurement, not a failure.
Record it; it sizes the re-fit.

### Phase 4 — Re-fit the absorbed rates
Re-fit the `CalibrationProfile` rates that were absorbing the mechanism, on
**training games only**. Hold out a test set fixed **before** any fitting.

**Do not grid-search.** 2026-08-18 rule: measure the count matrix, don't sweep
it. A sweep on 1,139 games still fits noise when the candidate grid is wide.

### Phase 5 — Judge, market-relative
Primary: **paired ΔCRPS on margin, held-out games, vs the closing line as the
benchmark forecaster.** Beating the *previous engine* is a screen; beating the
*market* is the goal (§5).

Report `n` on every statistic.

---

## 3. Decision rule, fixed now

| outcome | conclusion |
|---|---|
| ΔCRPS improves > 2× noise floor, held out | **SHIP.** Wire it, re-fit, deploy. |
| ΔCRPS improves but < noise floor | **NULL.** Record as unmeasurable at this n. Do NOT ship. Do NOT re-describe as promising. |
| ΔCRPS unchanged | **NULL**, and the 21-of-21 field movement was cosmetic. |
| ΔCRPS degrades after re-fit | **REJECT.** The features are not informative for this engine's structure. |
| Phase 1 fails (off == on) | **STOP.** The wiring is inert; nothing else is interpretable. |

**A null result is a publishable, valuable outcome** and closes a 65-key question
that has been open since the engine was built.

---

## 4. Explicitly out of scope

- **Preseason.** `nfl_preseason_v1` deliberately shrinks toward league-neutral
  because preseason outcomes are driven by playing-time decisions, not team
  strength. Adding team-strength mechanisms to a model calibrated on that
  shrinkage is §4.4's trap with an obvious causal story. **Preseason needs its
  own re-fit and its own experiment.**
- **NCAAF.** Different profile (`ncaaf_v2`), different unfed set, and its
  projection pipeline only started working today.
- **The unfed terms themselves** (player usage, pace, red zone). Population is
  NOT the binding constraint — **wiring is.** Fixing population before wiring
  changes no output. Revisit only after Phase 5.
- **ATS/ROI as a decision rule.** Underpowered at n=285 (the market-relative
  sample, NOT the 1,139); see §1. Revisit only if 2022-2024 closing lines are
  backfilled.

---

## 5. Cost, honestly

Phase 2 alone is **1,139 games × 2 arms × ≥2,000 seeds = ~4.6M game-sims**, and
phases 2-4 re-run that several times. **This is roughly 4x what the original
n=272 figure implied** — re-estimate before committing worker time. **This is a sim-heavy job and belongs on refresh-worker as a
detached run, never in a request path** — and it must not collide with the MLB
daily sim, which was measured holding 2 in-flight jobs on 2026-08-18.

**Estimate the wall-clock from a single-game timing before launching a full arm.**


---

## PHASE 1 COMPLETE — 2026-08-19. Reachability PASSES, and the required re-fit is now MEASURED rather than assumed.

**20 games, weeks 6-7 of 2023, 300 seeds/arm, as-of payload vs empty.**

| metric | units-buggy | units-fixed |
|---|---|---|
| mean \|Δ margin\| | 0.463 | **0.544** |
| mean signed Δ margin | +0.309 | +0.300 (SE 0.119) |
| mean \|Δ total\| | 8.024 | **3.563** |
| mean signed Δ total | — | **−2.644 (SE 0.695)** |
| total/margin asymmetry | 17.3× | **6.5×** |

**Prediction stated before the run — margin rises, total falls sharply — held on
both counts.**

### The residual −2.6 total shift is BIAS, and it is the ENGINE's baselines

`_offense_strength` centres each term on a hardcoded constant. Those constants
do not match real NFL distributions:

| term | engine baseline | real league mean | bias per team |
|---|---|---|---|
| `success_rate` | 0.500 | **0.422** | **−0.094** |
| `explosive_play_rate` | 0.100 | **0.066** | −0.031 |
| `red_zone_efficiency` | 0.500 | 0.575 | +0.060 |
| `pass_rate` | 0.500 | 0.496 | −0.002 |
| `offensive_epa` | 0.000 | −0.034 | −0.030 |
| **net** | | | **−0.097** |

**League mean `offense_index` = 0.405 against an engine neutral of 0.500.** Every
team is pushed below neutral, so every game's scoring environment drops — which
is exactly the −2.644 signed total shift, and why 17 of 20 games moved down.

### This is §4.4, measured

**The engine's rates were fitted with these terms ABSENT — so the defaults ARE
the calibration.** Feeding real data that sits below an assumed baseline
systematically suppresses scoring. That is the mechanism-vs-estimator trap, no
longer a warning but a number: **−0.097 of index, ≈ −2.6 points of total.**

**Phase 4 is therefore not optional and its target is known:** re-centre each
term on its real league mean (or re-fit the profile rates around the new index
distribution). Shipping the mechanism without it ships a systematic under-total.

### Verdict

- **Phase 1: PASS.** The leak-free payload reaches the engine and discriminates
  (`offense_index` 0.050–0.825, 30 distinct values, ranking football-accurate).
- **Phase 3 must not be judged before Phase 4.** A −2.6-point total bias would
  dominate any CRPS result and read as a model finding.


---

## RE-CENTRING COMPLETE — 2026-08-19. Both systematic biases eliminated.

Same 20 games / weeks 6-7 / 300 seeds throughout, so the three columns are
directly comparable.

| metric | units-buggy | units-fixed | **re-centred** |
|---|---|---|---|
| mean \|Δ margin\| | 0.463 | 0.544 | 0.394 |
| **signed Δ margin** | +0.309 | +0.300 (SE 0.119) | **+0.065 (SE 0.105)** |
| mean \|Δ total\| | 8.024 | 3.563 | **2.189** |
| **signed Δ total** | — | −2.644 (SE 0.695) | **−0.283 (SE 0.597)** |
| asymmetry | 17.3× | 6.5× | 5.6× |

**Both signed effects are now within 1 SE of zero** — margin at 0.62 SE, total at
0.47 SE. The systematic −2.6-point total suppression is gone, and so is the
+0.3-point home-favouring margin shift I had attributed to the home-only
`drive_priors` structure.

**That is the correct shape for a properly centred feature payload:** it moves
INDIVIDUAL games (|Δ margin| 0.394, |Δ total| 2.189) without shifting the
league-wide mean. Dispersion without bias.

### The remaining 5.6× asymmetry is a DESIGN PROPERTY, not a defect

`build_drive_priors` produces one game-level profile that drives
`scoring_environment`; per-team differentiation happens in
`play_simulator.py:258-259`, which this payload does not touch. So the payload
should be expected to move totals more than margins. **The asymmetry stopped
being alarming the moment the bias came out of it** — 17.3× of systematic
suppression was a bug; 5.6× of unbiased dispersion is the architecture.

### What is now TRUE of the payload

- **leak-free** — as-of window enforced at the read, certified r = 0.235 (was 0.988)
- **reachable** — 20 of 20 games change
- **discriminating** — `offense_index` 0.115–0.922, 31 distinct values, zero clamped
- **unbiased** — both signed effects within 1 SE of zero
- **football-accurate** — MIA/BUF/SF/BAL top, NYJ/NYG/LV/CAR bottom for 2023

### What is still NOT known, and must not be assumed

**None of the above is ACCURACY.** Reachability says the payload moves the
engine; unbiasedness says it does not tilt the league. **Neither says the
projections got better.** That is Phase 3, it needs realised outcomes and a
proper scoring rule, and the decision rule in §3 above stands unchanged:
paired ΔCRPS on held-out games, improvement > 2× the noise floor, or it is a
NULL and does not ship.
