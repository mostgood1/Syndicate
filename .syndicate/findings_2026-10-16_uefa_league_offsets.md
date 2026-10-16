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

## 2. Coverage

(written after the pull)

## 3. Results

(written after the fit)

## 4. What cannot be estimated

(written after the fit)

## 5. Deviations from the registration

(none yet)
