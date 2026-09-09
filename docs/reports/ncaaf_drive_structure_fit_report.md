# NCAAF Drive-Structure Fit (S4a)

- Date: 2026-09-09
- Harness: `scripts/calibrate_ncaaf_drive_structure.py` (extended, not rebuilt)
- Truth: `docs/reports/ncaaf_historical_truth_report.md` — 53,548 real drives / 2,264 games, 2023-2025, **parsed from the report by the harness rather than re-typed**
- Flag: `SYNDICATE_NCAAF_DRIVE_PROFILE=s4a_drive_fit_v1`; **absent means today's profile exactly**
- Nothing was deployed, no env var was set, and no served number changed.

## The finding that reframes the package

**The drive-structure gap this package was scoped against was already closed on
2026-08-27, and the harness's own docstring did not know it.**

`ncaaf_calibration_profile.py` resolves through `load_versioned_profile`, and
`data/calibration/ncaaf_profile.json` (`ncaaf-goal-line-refit-1`) is present in
git. It turns the goal-line-touchdown mechanism ON and re-fits around it
(`drive_yardage_multiplier` 1.15 → 0.95, `touchdown_weight_multiplier` 0.66 →
0.55, `field_goal_attempt_base_probability` 0.88 → 0.58). The docstring's
"sim @ profile v2" column is the **in-source default**, which production has
not run since that promotion.

| metric | truth | in-source default | live artifact |
| --- | --- | --- | --- |
| plays per drive | 5.77 | 7.22 (+25.1%) | 6.30 (+9.3%) |
| seconds per drive | 165.4 | 182.5 (+10.3%) | 160.3 (−3.1%) |
| possessions per game | 23.65 | 20.13 (−14.9%) | 22.91 (−3.1%) |
| PRIMARY mean \|err\| | — | 12.8% | 4.2% |

**How the wrong baseline was nearly shipped.** A session worktree excludes
`data/` (34,690 of 37,745 tracked files, and correctly so — it is a lossy
mirror). `load_versioned_profile` returns the in-source default when the
artifact is absent, does not raise, and says so only in a metadata dict nothing
printed. Four sweep rounds ran against that default before an unrelated test
failure (`test_the_promoted_ncaaf_artifact_is_present_and_carries_the_refit`)
exposed it. Two guards now make the recurrence impossible rather than merely
unlikely:

- `profile_source_banner()` prints source/version on every harness run and
  prints a four-line `!!!` block when the artifact is missing;
- a variant declares the base version it is a delta from, and
  `resolve_ncaaf_drive_profile` **raises** when the loaded profile is not that
  version. A delta applied to the wrong base is a profile nobody measured.

## Two measurement defects fixed before fitting

1. **`missed_field_goal` was counted as `field_goal`.** `_outcome` scanned for
   the substring `"field_goal"`, which `"missed_field_goal"` contains. Truth's
   10.0% is made kicks only, so the reported field-goal error (+77% on the
   default) was an artefact of the bucket. Split correctly, the live profile's
   made rate is 8.3% against 10.0% and its **missed rate is 6.7% against 3.1%** —
   half the size, and pointing at a different lever.
2. **Outcome quality was not scored while fitting.** NFL's 2026-07-15
   recalibration improved game totals while q1 normalized error went 0.025 →
   0.063, q3 stood at 0.115, and q4 went 0.053 → 0.075 — three of four quarters
   worse or flat. The harness now scores three groups every run: PRIMARY
   (structure), SECONDARY (game total + four quarters + h1/h2), TERTIARY
   (outcome mix: TD/FG/missed-FG/punt/turnover/TOD rates and yards per drive).

## The sweep

Every candidate below is a delta from the **live artifact**, 800 games × 3
independent seed banks (9001 / 50001 / 777001) = 2,400 simulated games each.

`fgpen` = `field_goal_make_distance_penalty` (0.022 live), `fgab` =
`field_goal_attempt_base_probability` (0.58 live), `rz` =
`red_zone_touchdown_weight_bonus` (0.58 live), `ep`/`ey` = explosive
play/yardage multipliers. `qNe` is that quarter's normalized error.

| candidate | PRIM | SEC | TERT | mean | q1e | q2e | q3e | q4e | total | sd | gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **live artifact** | 4.16% | 7.36% | 26.79% | 12.77% | 0.098 | 0.140 | 0.035 | 0.037 | 49.67 | 13.18 | — |
| P fgpen .014 + fgab .85 | 3.95% | 5.77% | 24.61% | 11.44% | 0.070 | 0.104 | 0.017 | 0.057 | 51.40 | 12.89 | PASS |
| **R fgpen .014 + rz .80** | 4.25% | 6.34% | **16.02%** | **8.87%** | 0.077 | 0.117 | 0.006 | 0.070 | 51.31 | 13.24 | **PASS — chosen** |
| S fgpen + fgab .85 + rz .80 | 3.99% | 6.30% | 23.91% | 11.40% | 0.065 | 0.102 | 0.022 | 0.087 | 52.19 | 13.13 | PASS |
| T fgpen + ey 1.45 | 4.48% | 5.31% | 16.55% | 8.78% | 0.057 | 0.074 | 0.016 | 0.092 | 52.75 | 13.52 | FAIL a, b |
| U fgpen + fgab .85 + ep 1.60 | 4.27% | 5.81% | 26.12% | 12.07% | 0.038 | 0.067 | 0.054 | 0.106 | 53.65 | 12.81 | FAIL b |
| fgpen .014 alone | 4.21% | 6.49% | 16.57% | 9.09% | 0.083 | 0.116 | 0.024 | 0.060 | 50.83 | 12.97 | PASS |
| fgab .85 alone | 3.88% | 6.45% | 32.61% | 14.31% | 0.089 | 0.130 | 0.019 | 0.027 | 50.14 | 13.04 | FAIL a |

Earlier rounds (250-400 games, single bank) that narrowed the field to these:
`drive_yardage_multiplier` 0.98-1.10, `touchdown_weight_multiplier` 0.30-0.90,
`fourth_down_conversion_multiplier` 0.20-0.80, all four punt-probability bands,
`field_goal_make_ceiling` 0.88/0.90, `red_zone_gain_stiffening` 0.90/1.00,
`drive_success_sensitivity` 0.55/0.70/0.85, `explosive_play_multiplier`
1.20-1.70, `explosive_yardage_multiplier` 1.15-1.55.

### Selection rule, written before the numbers were read

Minimise `mean(PRIMARY, SECONDARY, TERTIARY)` subject to
(a) none of the three worse than the live profile by more than 0.2 points and at
least two strictly better, and
(b) **no single quarter's normalized error worse than the live profile by more
than 0.05** — the guard that would have caught the NFL recalibration.

### Rejected, and why

- **`fgab .85` (raising field-goal attempts) — rejected on gate (a).** It is the
  best single move on drive structure (PRIM 3.88%, the lowest in the table) and
  it is the *worst* on outcome mix (TERT 32.6% against 26.8%), because the extra
  attempts land in the missed-FG bucket, which is already 2.2× truth. This is
  exactly the metric-group trade the three-way score exists to expose: scored on
  PRIMARY alone it would have been the winner.
- **`U` and `T` — rejected on gate (b), the quarter guard.** Both post the best
  q1/q2 in the table and the best game totals (53.65 and 52.75 against a truth
  53.35), and both do it by pushing q4 from a near-exact 0.037 to 0.106 and
  0.092. That is the NFL recalibration's failure mode precisely — buy the game
  total, pay in a quarter nobody was scoring — and the guard is the only thing
  that stopped it, since `U` beats the chosen candidate on SECONDARY.
- **`drive_success_sensitivity` (0.55 / 0.70 / 0.85) — rejected, moves the wrong
  way.** `calibration_profile.py` documents this as the dial for NCAAF's total
  over-dispersion. Shrinking it *raised* game totals (62.9 / 62.8 / 61.7 against
  a shipped-default 61.5 at that stage) and did not reduce neutral-rating
  dispersion. It is not a scoring-level lever, and no setting of it helped here.
- **`drive_yardage_multiplier`, `touchdown_weight_multiplier`, punt-probability
  bands, `fourth_down_conversion_multiplier` — rejected as already fitted.** The
  promoted artifact set the first two and its re-fit left punt rate at −2.8% and
  turnover rate at −8.4%. Every move on them traded one group for another with
  no net gain; the two the fit does use are the two the goal-line re-fit did not
  look at, for the reason given in each.
- **Pace was not re-derived.** The harness docstring already records that feeding
  the true league mean (26.27 s/play) moves every metric further from truth and
  that hitting truth through it would need ~22.0, below the hardcoded 24.0.
  Taken as given, as instructed.

## Before / after on both dimensions

`s4a_drive_fit_v1` = `field_goal_make_distance_penalty` 0.022 → **0.014**,
`red_zone_touchdown_weight_bonus` 0.58 → **0.80**. Everything else is the live
artifact untouched. 800 games, seed bank 9001, ~18,350 simulated drives each.

| metric | truth | live | variant | live err | variant err | |
| --- | --- | --- | --- | --- | --- | --- |
| **structure** | | | | | | |
| possessions per game | 23.65 | 22.938 | 22.964 | −3.0% | −2.9% | ≈ |
| plays per drive | 5.77 | 6.297 | 6.282 | +9.1% | +8.9% | ≈ |
| seconds per drive | 165.4 | 160.16 | 159.95 | −3.2% | −3.3% | ≈ |
| yards per play (measured) | 7.364 | 7.469 | 7.519 | +1.4% | +2.1% | worse |
| PRIMARY mean \|err\| | | | | **4.19%** | **4.29%** | worse |
| **outcome mix** | | | | | | |
| yards per drive | 42.49 | 32.98 | 32.97 | −22.4% | −22.4% | ≈ |
| touchdown rate | 0.264 | 0.273 | 0.275 | +3.3% | +4.4% | worse |
| field-goal rate (made) | 0.100 | 0.083 | 0.098 | −17.0% | **−2.2%** | better |
| missed field-goal rate | 0.031 | 0.068 | 0.048 | +118.5% | **+55.8%** | better |
| punt rate | 0.351 | 0.341 | 0.345 | −2.8% | −1.7% | better |
| turnover rate | 0.109 | 0.100 | 0.100 | −8.4% | −7.9% | ≈ |
| turnover-on-downs rate | 0.073 | 0.058 | 0.057 | −20.6% | −22.0% | worse |
| TERTIARY mean \|err\| | | | | **27.57%** | **16.62%** | better |
| **outcome quality** | | | | | | |
| game total | 53.35 | 49.51 | 51.02 | −7.2% | **−4.4%** | better |
| total SD (neutral ratings) | — | 13.58 | 13.52 | — | — | ≈ |
| q1 scoring | 12.03 | 11.178 | 11.330 | −7.1% | −5.8% | better |
| q2 scoring | 15.74 | 13.596 | 13.915 | −13.6% | −11.6% | better |
| q3 scoring | 11.99 | 11.582 | 11.877 | −3.4% | **−0.9%** | better |
| q4 scoring | 13.22 | 12.960 | 13.685 | −2.0% | +3.5% | **worse** |
| h1 scoring | 27.77 | 24.774 | 25.245 | −10.8% | −9.1% | better |
| h2 scoring | 25.21 | 24.543 | 25.562 | −2.6% | +1.4% | better |
| SECONDARY mean \|err\| | | | | **6.67%** | **5.25%** | better |

## Dispersion

The `total_sd` column is measured at **neutral ratings** (both teams 0.0), so it
is the residual game-to-game spread only. It does **not** contain the
team-quality term that produces the ~2.17×-market over-dispersion recorded in
`drive_priors.py:92`, which is a live-slate measurement with real SP+ ratings.
`--rated` samples ratings (SD 0.7 on the engine scale, matching
`SP_RATING_SCALE = 10.0` over SP+ components) so the slate-level term is present
and two profiles can be compared on it; the absolute there is still not a market
comparison.

**What this harness can and cannot say about the 2.17× figure.** It cannot
reproduce it. That number compares the SD of *projected* totals across a real
slate against the SD of *market* totals across the same slate. This harness
measures the SD of *realised* simulated totals, which also contains within-game
variance and is a different quantity — it is ~13.5 neutral and ~23.8 rated
against a market total SD near 3.5, and those are not comparable numbers. What
it can say is whether the fit **moves** dispersion, and it does not:

| | live | variant | change |
| --- | --- | --- | --- |
| total SD, neutral ratings (800 games) | 13.583 | 13.515 | −0.5% |
| total SD, sampled ratings (500 games) | 23.879 | 23.679 | −0.8% |

The over-dispersion is untouched, as expected: neither parameter in the fit
touches the rating→yardage path or `drive_success_probability`, which is where
`calibration_profile.py` and `drive_priors.py` both locate it.

**The rated run also contradicts the neutral run on game totals, and that
matters more than the dispersion result.** With team ratings sampled at SD 0.7
on the engine scale (the scale `SP_RATING_SCALE = 10.0` implies for SP+
components — an assumption, not a measurement of the live slate):

| | truth | live | variant |
| --- | --- | --- | --- |
| game total, rated | 53.35 | 52.43 (−1.7%) | 54.53 (+2.2%) |
| SECONDARY mean \|err\|, rated | | **5.33%** | **6.94%** |

Neutral, the live profile under-scores by 7.2% and the variant closes half of
that. Rated, the live profile is already within 1.7% and the variant
**overshoots**, and SECONDARY — the outcome-quality group this fit exists to
improve — gets *worse*, not better. The asymmetry documented at
`calibration_profile.py:40` (offense weight 3.0 exceeds defense weight 2.2, so
the sum inflates while the difference does not) means team quality adds points;
a fit calibrated at neutral ratings is fitting a game that production never
simulates, because production always passes real SP+ ratings.

## Recommendation

**It is a trade, and I recommend AGAINST flipping the flag.**

The fit is real — the missed-FG rate halves (+118% → +56%), the made rate lands
almost exactly (−17% → −2%), and three of four quarters improve. But:

1. **It does not do what this package was for.** The drive-structure gap (plays
   +25%, possessions −15%) was already closed by `ncaaf-goal-line-refit-1`. On
   the live profile the structure score is 4.19% and the fit takes it to 4.29% —
   **slightly worse**. Nothing here fixes drive structure because there is not
   much left to fix.
2. **Q4 regresses from near-exact to a real error** (−2.0% → +3.5%; normalized
   0.037 → 0.070). Small, inside the pre-stated gate, and still the same shape
   as the NFL recalibration that this package was told not to repeat.
3. **The gain reverses under real ratings.** Neutral, SECONDARY goes 6.67% →
   5.25%. Rated, it goes 5.33% → **6.94%**, because the live profile's totals
   are already right once team quality is in and the fit pushes them past truth.
   Production always passes SP+ ratings, so the rated run is the one that
   describes the served number, and by that measure this fit is a regression on
   outcome quality. One measurement disagreeing with the other is sufficient
   reason not to ship either.
4. **The flag is the wrong vehicle even if the fit were right.** NCAAF ships a
   profile through `data/calibration/ncaaf_profile.json`. A two-field delta held
   in code behind an env var is how a candidate is MEASURED, not how it is
   promoted, and promotion of these two fields would want a full re-fit around
   them — the FG accounting they correct is an input to every other rate.

**What should happen instead, in priority order.**

1. **Re-derive the whole NCAAF profile at REALISTIC RATINGS.** Every NCAAF
   calibration to date — v1, v2, the goal-line re-fit, and this one — was scored
   with both teams at 0.0. The rated numbers above show that is a different
   game: totals move ~3 points and the ranking of candidates changes. The fix is
   to score against the real slate the projections generator already builds.
2. **Re-open the field-goal accounting on the promoted artifact.** The
   `missed_field_goal`-as-`field_goal` bug means the FG-related choices in v1,
   v2 and the goal-line re-fit were all made against a merged bucket. The
   artifact's `field_goal_attempt_base_probability` 0.58 in particular was set
   to suppress a rate that was over-counted by ~60%.
3. **The h1/h2 shape and the yards-per-drive accumulation gap are larger errors
   than anything a profile parameter reaches**, and both are engine work.

The variant stays registered and measurable. Flipping it is a decision that
needs the rated re-derivation first.

## Residual defects this fit does not touch

- **The h1/h2 shape is inverted and no profile parameter can fix it.** Truth is
  h1 27.77 / h2 25.21 (ratio 1.10); the sim is flat-to-inverted in both the live
  profile and every candidate. Q2 is truth's highest-scoring quarter (15.74) and
  the sim's lowest-relative one. The suppressor is
  `play_simulator.py`'s `URGENCY_HALFTIME_PRESERVATION` branch (`gain += 0.30`,
  `incomplete_pass *= 0.25`, `explosive_gain *= 0.40`), which is engine
  behaviour, not a profile seam. Any uniform scoring lever raises q3/q4 — already
  near truth — as much as it raises q2.
- **`yards_per_play_derived` (drive yards ÷ drive plays) sits ~29% below the
  measured per-play mean.** In real football the two are equal by construction
  (42.49 / 5.77 = 7.36). The sim's gross play gains are not accumulating into
  drive yardage. This is engine accounting, and it is why `yards_per_drive`
  reads −22% while `yards_per_play` reads +1%. The promoted artifact's own
  `fit_from.known_costs` already records `yards_per_drive_pct: -23.1` as an
  accepted cost.
- **Turnover-on-downs stays low** (5.9% against 7.3%) and no lever moved it
  without a larger cost elsewhere.
