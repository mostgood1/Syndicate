# UEFA cross-league strength offsets (todo #699 Stage 1 step 2) — 2026-10-16

Lane `uefa-league-offsets`, session 77922136. Research + library only: nothing in this lane
touches the sim, the board, a worker, `render.yaml` or a deploy.

## 1. PRE-REGISTRATION (committed BEFORE any model was fit)

Written and committed before the first fit. The UEFA results pull and the domestic membership
pull may already have run (coverage counts are not outcomes); no offset, no likelihood and no
held-out number had been computed when this section was committed. Any later change to it is
a deviation and gets its own dated line in section 5, never an edit here.

### Question

Production soccer ratings are fit per domestic league and centred on that league's mean
(`compute_team_ratings`). A UEFA fixture between clubs from two of our leagues therefore
compares two different scales. Stage 1 plans to add a per-league strength offset `o_L` to
those league-centred ratings. **Does a single per-league offset, measured from past
cross-league UEFA results, improve held-out cross-league prediction over using the
league-centred ratings as if all leagues were equal?**

### Data

- UEFA results: UCL + UEL + UECL, main draw and qualifiers, ESPN scoreboards, seasons
  2014-15 .. 2026-27 (the last one partial, to 2026-10-16). Pulled with
  `scripts/fetch_uefa_history.py` into a research root outside git, plus a raw-payload pass
  that records each event's status name and `neutralSite`.
- Domestic results: the ten `LEAGUE_ESPN_SLUGS` domestic leagues, ESPN scoreboards, calendar
  years 2013 .. 2026, completed matches only.
- Club -> league membership is **per season** (July..June window) by ESPN team id: the league
  in whose matches the club appears that season. A club appearing in two leagues in one season
  window takes the league with more matches (the count of such clubs is reported).

### Eligible matches

- **Cross-league**: both clubs placed that season, in two DIFFERENT leagues of our ten.
- Both clubs must have a domestic rating as of kickoff: >= 5 domestic matches in the window
  below. Matches failing this are counted and excluded from both arms.
- **Extra time**: a match whose ESPN status is after-extra-time or penalties
  (`STATUS_FINAL_AET`, `STATUS_FINAL_PEN`, or any status name containing `AET`/`PEN`) has a
  score that includes extra time. It is EXCLUDED from training and scored as a DRAW in
  evaluation (the 90-minute result was level by construction). Count reported.
- `neutralSite` true -> no home advantage term.

### Club component (identical in both arms)

Domestic rating as of the UEFA kickoff date `t`, per league:
`log λ = μ_L + η_L·home + a_i − d_j` on that league's completed matches dated in
`[t − 365 days, t)`, Poisson likelihood, L2 penalty `0.5·κ·Σ(a² + d²)` with **κ = 10**
(fixed, not tuned), μ_L and η_L unpenalised. No input dated at or after kickoff (leak check
asserted in code).

### The two arms (cross-league goals model, independent Poisson)

- **NO-OFFSET**: `log λ_home = μ + η·(1 − neutral) + β·(a_i − d_j)`,
  `log λ_away = μ + β·(a_j − d_i)`. Free: μ, η, β.
- **OFFSET**: the same plus `+ (o_{L(i)} − o_{L(j)})` on the home rate and
  `+ (o_{L(j)} − o_{L(i)})` on the away rate. One scalar per league, sum-to-zero over the
  leagues present in training (reported both centred and relative to EPL). Unpenalised.
- Fit by maximum likelihood on the eligible cross-league TRAINING matches only.
- 1X2 from the two Poisson rates, goals truncated at 10.

### Held-out split

Walk-forward by season. Test season S in **2017 .. 2026** (2026 partial); training = eligible
cross-league matches of seasons 2014 .. S−1. Parameters are frozen through the test season.
Domestic ratings are as-of each match date in every season, train and test alike.

### Metric and test

- **Primary**: per-match 1X2 log loss, paired difference `Δ = OFFSET − NO-OFFSET`, pooled over
  every test match of every test season. 95% CI by bootstrap over matches (each match is the
  resampling unit; 2,000 resamples, seed 699).
- **Secondary** (reported, not used for the verdict): 3-way Brier, goals Poisson deviance,
  per-season Δ, and the same on the big-5-only subset.
- **Verdict on H-OFFSET ("a single per-league offset improves cross-league prediction over no
  offset"):**
  - **SUPPORTED** if the pooled Δ log loss CI lies entirely below 0;
  - **NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0;
  - **FALSIFIED** if the point estimate is >= 0.

### Offsets reported

Fit once on ALL eligible cross-league matches 2014 .. 2026: each `o_L` with a 95% percentile
bootstrap interval (1,000 resamples over matches, seed 699) and its match count. A league
whose cross-league match count is below 30, or that has none, is reported as **NOT
ESTIMABLE**, not imputed. MLS and the Championship are expected to land there.

### What this does NOT establish

Beating the de-vigged UEFA close (Stage 1 step 3) or anything about out-of-scope clubs
(509 of them; their ratings are a later step). A SUPPORTED verdict here licenses nothing
on the board.

## 2. Coverage (measured 2026-10-16 ~14:50Z; research root `C:/tmp/uefa-offsets`, not in git)

**Inputs.**
- **UEFA:** `fetch_uefa_history.py --seasons 2014-2026` (UCL + UEL + UECL, main draw and qualifiers): 9,623 completed matches.
- **Domestic:** the ten `LEAGUE_ESPN_SLUGS` leagues, calendar years 2013-2026, 4,122 (Portugal) to 7,602 (Championship) completed matches each.
- **Requests:** 224 ESPN requests for the domestic and UEFA status payloads, 0.3 s apart, at Idle priority.
- Every number below comes from ESPN, not from git-tracked `data/`.

**Placement** (club -> league per season, by ESPN team id):

| | matches | both clubs placed | share | cross-league | clubs | never placed |
|---|---|---|---|---|---|---|
| all | 9,623 | 1,669 | **17.3%** | **1,618** | 646 | **524** |
| UCL | 2,804 | 1,011 | 36.1% | 984 | 275 | 210 |
| UEL | 4,470 | 580 | 13.0% | 556 | 553 | 445 |
| UECL | 2,349 | 78 | 3.3% | 78 | 396 | 345 |

- **Other match counts:** 2,723 matches have one club placed and 5,231 have neither. 51 are same-league UEFA matches, which are not used.
- **524 of 646 clubs (81%) never play in our ten leagues.** 196 of them have 20+ UEFA matches and need ratings fit from UEFA results (the next step).
- **Club appearances by league:**
  - EPL 957, La Liga 955, Serie A 849, Bundesliga 834;
  - Ligue 1 707, Eredivisie 596, Portugal 595, Belgium 568;
  - **MLS 0 and Championship 0.**
- **Membership conflicts: 14**, all resolved correctly by the majority rule:
  - 8 come from an MLS All-Star match (Tottenham, Arsenal x2, Real Madrid, Atletico, Bayern, Roma, Juventus);
  - 6 come from the COVID-extended 2019-20 EPL/Championship seasons spilling into July 2020.
- **The 2026-27 season (to 2026-10-16)** has 518 matches, but only 5.2% are placed. Most are July/August qualifiers between out-of-scope clubs, and only 2 league-phase matchdays have been played.
- **Cross-league pairs: all 28** pairs of our 8 European leagues are covered.
  - Thickest: EPL-La Liga, 141.
  - Thinnest: Belgium-Eredivisie 19, Belgium-Portugal 21, Eredivisie-Portugal 26, Belgium-Serie A 27, Bundesliga-Eredivisie 28.

**Eligible for the model:**
- All 1,618 cross-league matches had a domestic rating for both clubs (0 skipped).
- 39 went to extra time or penalties: excluded from training and scored as draws.
- 21 are finals, treated as neutral.
- 3 have no status payload and were treated as non-neutral 90-minute results.

## 3. Results

### The registered test: H-OFFSET is SUPPORTED

Walk-forward over test seasons 2017-2026, on **1,278 held-out cross-league matches**:

| | 1X2 log loss |
|---|---|
| base rate (train-season H/D/A frequencies; descriptive, not registered) | 1.0668 |
| NO-OFFSET | 1.0551 |
| OFFSET | **1.0110** |

- **Primary, Δ log loss (OFFSET − NO-OFFSET): −0.0441 [−0.0601, −0.0279]** (bootstrap over matches, 2,000 resamples, seed 699). The CI is entirely below 0, so the verdict is **SUPPORTED**.
- **Secondary, Δ Brier:** −0.0318 [−0.0435, −0.0203].
- **Big-5-only subset, Δ log loss:** −0.0196 [−0.0318, −0.0070].
- **Every test season has Δ < 0**, and the CIs of 4 seasons exclude 0:
  - 2017 −0.032, 2018 −0.067, 2019 −0.042, 2020 −0.061, 2021 −0.013;
  - 2022 −0.021, 2023 −0.056, 2024 −0.033, 2025 −0.064;
  - 2026 (partial, n=27) −0.092.

### Offsets (fit on all 1,579 non-extra-time cross-league matches 2014-2026)

**How to read them:**
- The unit is the log goal rate. A club's expected goals are multiplied by exp(o_own − o_opponent).
- The offset is applied ON TOP of league-centred domestic ratings (κ 10, 365-day window).
- Intervals are 95% percentile bootstrap intervals, 1,000 resamples over matches.

| league | matches | offset (centred) | 95% CI | vs EPL | 95% CI |
|---|---|---|---|---|---|
| EPL | 559 | +0.249 | [+0.206, +0.295] | 0 | — |
| La Liga | 537 | +0.125 | [+0.083, +0.167] | −0.124 | [−0.183, −0.068] |
| Bundesliga | 483 | +0.120 | [+0.071, +0.170] | −0.130 | [−0.197, −0.061] |
| Serie A | 460 | +0.069 | [+0.024, +0.118] | −0.181 | [−0.248, −0.116] |
| Ligue 1 | 395 | +0.004 | [−0.046, +0.055] | −0.246 | [−0.318, −0.175] |
| Primeira Liga | 280 | −0.135 | [−0.196, −0.072] | −0.384 | [−0.467, −0.299] |
| Eredivisie | 241 | −0.202 | [−0.268, −0.136] | −0.451 | [−0.536, −0.369] |
| Belgian Pro League | 203 | −0.230 | [−0.310, −0.154] | −0.479 | [−0.576, −0.382] |
| MLS | 0 | **NOT ESTIMABLE** | | | |
| Championship | 0 | **NOT ESTIMABLE** | | | |

The other fitted terms are η (home advantage) = 0.263 and μ = 0.147. **β = 0.80 with offsets, 0.55 without.**

### Engine read (beyond the verdict)

- **The NO-OFFSET model barely beats base rates** (1.0551 vs 1.0668). League-centred ratings carry almost no cross-league information until the scales are aligned; the offsets recover 0.044 nats.
- **β < 1 is a calibration signal.**
  - Without offsets, β falls from 0.72 to 0.52 as the training window grows: the fit damps a rating contrast that is mis-scaled across leagues.
  - With offsets, β is 0.76-0.89. Domestic rating gaps still need shrinking by about 20% when carried into a UEFA match. The cause could be rotation or the regression of in-league form.
  - This is a parameter to re-measure against production ratings, not one to copy.
- **The offsets DRIFT** (a descriptive era split, NOT registered; offsets vs EPL):

  | era | La Liga | Bundesliga | Serie A | Ligue 1 | Portugal | Eredivisie | Belgium |
  |---|---|---|---|---|---|---|---|
  | 2014-19 (n 659) | −0.00 | −0.05 | −0.12 | −0.20 | −0.34 | −0.39 | −0.41 |
  | 2020-26 (n 920) | −0.21 | −0.19 | −0.22 | −0.27 | −0.41 | −0.48 | −0.53 |

  - Since 2020 the EPL has pulled away from every league, by about 0.1-0.2.
  - **A single offset fit over 12 seasons is therefore stale for 2026 use:** it understates the EPL's current edge.
  - A recency-weighted or rolling offset has to be registered and tested before anything is served.

## 4. What cannot be estimated

- **MLS and Championship offsets.** They have 0 cross-league UEFA matches in 2014-2026, so UEFA results cannot place them, and nothing was imputed. This does not affect UEFA pricing, because no MLS or Championship club played in UEFA in this window.
- **Pair-specific offsets** (for example Belgium vs Eredivisie directly, 19 matches). Only a single additive offset per league was fit. The Belgium and Eredivisie estimates rest mostly on matches against the big 5 (203 and 241 matches in total).
- **Offsets on PRODUCTION's rating scale.** These offsets are relative to THIS module's domestic ratings (goals Poisson, κ 10, 365 days).
  - Production `compute_team_ratings` uses xG inputs, its own shrinkage and promoted-team priors.
  - **The offsets must be refit against production's own ratings before use.**
  - The library accepts any per-club (attack, defence) pair as the club component, so the refit is a substitution, not a rewrite.
- **The 524 out-of-scope clubs** (81% of UEFA clubs, present in 82.7% of UEFA matches). Nothing here rates them.
- **Anything about beating the market.** No de-vigged UEFA closing line was used.

## 5. Deviations from the registration

- **Neutral venue (2026-10-16 ~14:48Z, decided before the first fit).**
  - The registration said: "`neutralSite` true -> no home advantage".
  - ESPN's soccer scoreboard has **no `neutralSite` field** (0 of 9,998 UEFA event payloads).
  - Finals were taken as neutral by `season.slug == "final"` instead (21 eligible matches).
  - The 2020 COVID single-venue knockout rounds (Lisbon, Germany) are NOT marked neutral.
- **Added after the results, descriptive only and not part of the verdict:** the base-rate log loss, the 2014-19 / 2020-26 era split, and the pair counts.

## 6. Code (lane `uefa-league-offsets`)

- **`syndicate/features/soccer/uefa_league_offsets.py`**
  - Placement: `build_membership`, `place_matches`, `coverage`, `match_flags`.
  - As-of domestic ratings: `DomesticRatingIndex`, which asserts that no input is dated on or after kickoff.
  - The cross-league model: `fit_cross_league`, `outcome_probs`, `score_match`.
  - Statistics: `paired_bootstrap_ci`, `verdict`.
- **`scripts/fit_uefa_league_offsets.py pull|run`:** the research driver. It writes `report.json` to the research root.
- **`tests/test_uefa_league_offsets.py`:** 17 hermetic tests:
  - season-scoped promotion and relegation, and the conflict majority rule;
  - no leak from the kickoff day, and the 365-day window;
  - recovery of known offsets, and off != on reachability;
  - extra time scored as a draw, neutral venues, and the verdict rule.
- **Wired into NOTHING:** no worker, board, sim or `HOT_ARTIFACT_PATTERNS` change.
