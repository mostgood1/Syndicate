# Pre-registration — wiring the feature payload into smartsim2 (NFL regular season)

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

### The Monte Carlo noise floor may exceed the effect

Per-game MC standard error on the margin mean is `13.5 / sqrt(seeds)`:

| seeds/game | per-game MC noise | vs the 1.1-pt observed effect |
|---|---|---|
| 200 (preseason default) | **0.95 pts** | noise ≈ effect — **hopeless** |
| 300 (NCAAF default) | 0.78 pts | still swamped |
| 2,000 | 0.30 pts | workable |
| 5,000 | **0.19 pts** | comfortable |

**Phase 2 must measure this rather than trust the formula**, but the design
implication is already clear: **raise seeds before judging anything.** Running
this at 300 seeds and reporting "no effect" would be measuring the RNG.

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
