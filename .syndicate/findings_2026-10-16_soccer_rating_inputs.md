# Soccer team ratings: do better rating INPUTS close the domestic 1X2 gap to the close? (lane `soccer-team-strength` stage 1, H39; todo #699) — 2026-10-16

Lane `soccer-team-strength`, session 8b75e513 (re-adopted from 2eff0a12). Research only: nothing in this lane
touches the sim, the board, a worker, `render.yaml` or a deploy. Production rating code
(`syndicate/features/soccer/features/loaders.py`, `scripts/build_soccer_artifacts.py`) is READ, never edited.

Follows `.syndicate/findings_2026-10-16_soccer_rating_compression.md`. There, the shipped rating at its
outcome-optimal slope (arm C, m̂ 1.583, which equals the served engine's gain of 1.593) still trailed the
de-vigged close by +0.0218 [+0.0195, +0.0239] log loss over 26,547 held-out matches. On top-decile favourites
it gave 0.743, against 0.804 from the close and 0.821 actual. Scale and clamp were ruled out, so the remaining
gap is INFORMATION in the rating inputs. This file tests the inputs.

## 1. PRE-REGISTRATION (committed BEFORE any variant is computed or fit)

Written 2026-10-16 17:4xZ. No variant rating, likelihood or score has been computed. The inputs on disk are
the ones the compression study used: `C:/tmp/uefa-offsets/prod_history` and `C:/tmp/team-strength/fd_raw`,
the same 8 leagues, the same aliases and wrong-pairing exclusions (its deviation 1), and the same close
(Pinnacle, else average, else B365; proportional de-vig). Any later change is a deviation and gets its own
dated line in section 5, never an edit here.

### What "shipped" means now (the reference arm, `C*`)

Production's rating for a club on day `t` is:

- `compute_team_ratings(rows, as_of=t, window=W0)` on the fleet's depth (big 5: Understat xG, `W0 = 45`,
  the match season plus 2 before; goals leagues: football-data goals, `W0 = 90`, the season plus 3 before);
- then `clamp(0.55·x, ±0.35)`;
- then **the few-match gate**: a club with 0 rated rows (`_fill_promoted`) or 1..9 rated rows
  (`_gate_few_match`, ON in production since 2026-10-07 18:54Z: `SYNDICATE_SOCCER_CURRENT_HISTORY=1`) gets
  `PROMOTED_TEAM_RATING = (−0.18, −0.18)`.

The compression study's arm C did NOT include the gate. It scored only matches where both sides had at least
5 rated rows. **`C*` = arm C plus the gate**: the per-league Poisson link with `k` refit, on the shipped rating
with production's few-match handling. Every variant changes only the rating INPUT and keeps everything after
it: clamp(0.55·x, ±0.35), then the link with μ_L, η_L and k refit.

### Population

- **FULL (primary):** every football-data match with a close where each side either resolves to a rating key
  or resolves to nothing (0 rows in the depth, which means a promoted club). Wrong pairings are excluded, as
  before. Held out = test seasons 2016..2026, walk-forward, training = 2014..S−1.
- **CORE (secondary):** FULL matches where both sides have at least 10 rated rows under the shipped window,
  so the gate does not fire. This is close to the compression study's set.
- **PROMOTED (secondary):** FULL minus CORE.
- Every arm scores the same matches. Counts by reason are printed.

### Variant families (raw deviation `x`, before the shipped transform)

Notation: for a club as of day `t`, its rows in the depth dated before `t`, sorted by day; `n` = rows used;
`m_f`, `m_a` = its (weighted) mean xG for and against; `μ` = production's league mean (unweighted mean of
`xg_for` over every club's window rows); `x_att = m_f/μ − 1`, `x_def = 1 − m_a/μ`. A club is **ESTABLISHED**
if it has a row in the depth from a season before the match season, otherwise **PROMOTED**.
`p0 = −0.18/0.55 = −0.3273` is the shipped prior in raw space.

| family | what changes | grid (shipped value first) |
|---|---|---|
| **W — window length** | last `W` rows (capped by the depth); `μ` recomputed on the same window | `W/W0 ∈ {1, 1/3, 2/3, 4/3, 2}`: big 5 {45, 15, 30, 60, 90}, goals {90, 30, 60, 120, 180} |
| **R — recency weighting** | weights `0.5^(age/h)` on the window rows, where `age` = 0 for the latest row, 1 for the one before, and so on; `μ` unchanged | `h ∈ {∞, 40, 20, 10}` matches |
| **B — current-season blend** | `x = (1−b)·x_window + b·x_current`, where `x_current` uses only the club's match-season rows (same `μ`) and `b = n_cur/(n_cur + c)` (`b = 0` when `n_cur = 0`) | `c ∈ {∞, 40, 20, 10, 5}` |
| **S — shrinkage strength** (replaces the gate's hard switch) | `x = (n·x_obs + n0·target)/(n + n0)`, where target = 0 (league mean) for ESTABLISHED clubs and `p0` for PROMOTED clubs; `n = 0` gives the target | `n0 ∈ {gate (shipped), 5, 10, 20, 40}` |
| **P — promoted-team prior value** (keeps the gate, changes the value) | the gate's value is `x_prior,L` in place of `p0`, separately for attack and defence: the mean raw `x` of PROMOTED clubs over their promotion-season rows in training seasons `< S` of league `L` (rows rated against that league-season's `μ`) | `{p0 (shipped), fitted}` |

**Selection is walk-forward, never on the test season.** For each test season `S` and each family, the grid
value is the one with the lowest IN-SAMPLE log loss of the link fitted on training seasons `< S`. Every value
has the same parameter count, so in-sample comparison is fair. The family's held-out score is the
concatenation of each season's selected value. Every grid point's held-out score is also reported, but only
as description: picking the best of those after the fact is not a verdict.

**Singly:** each family with the other four at their shipped values.

**Cumulatively, in this fixed order: W → R → B → S → P.** For each test season, choose W first, then R given
that W, and so on, each by in-sample training log loss. When S selects a non-gate value, P's fitted prior
becomes S's PROMOTED target instead of `p0`. The order is fixed in advance and is not tuned.

### Metric, test and verdicts

- Per-match 1X2 log loss vs the outcome, with Brier as a secondary. Paired differences are pooled over every
  held-out FULL match. 95% CI from 2,000 bootstrap resamples over matches, seed 699.
- **Per family and for the cumulative arm: Δ = V − C\*.**
  - **SUPPORTED** if the CI lies entirely below 0.
  - **NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0.
  - **FALSIFIED** if the point estimate is ≥ 0. A family whose selection picks the shipped value in every
    season scores Δ = 0 identically, which is FALSIFIED, and is reported as such.
- **Gap to the close:** for C\*, each family, the cumulative arm and the close: mean held-out log loss,
  Δ(arm − close) with its CI, and the share of C\*'s gap closed, `1 − Δ(V−close)/Δ(C*−close)`. The gap
  "narrows" only when Δ(V − C\*) is SUPPORTED.
- **Favourite calibration** (favourite = the side, home or away, with the higher de-vigged close probability):
  for every arm, the mean model probability of that side, the mean close probability and the actual win rate,
  over all held-out matches and over the top decile by close probability.
- **Spread:** sd of p(home) − p(away) per arm and for the close.
- **Reference rows:** N, the naive link with `k = 0` (league μ and η only, the as-of naive baseline the lane
  goal names), and the compression study's arm C without the gate.
- **Lane H39 verdict:** the lane's falsification test reads "no rating variant reduces held-out 1X2 vs the
  SHIPPED model with a CI excluding 0, OR the best variant's rating spread is not wider than shipped". Here:
  - H39 is **FALSIFIED** if neither any family nor the cumulative arm is SUPPORTED, OR if the best
    SUPPORTED arm's model spread (the sd above) is not wider than C\*'s.
  - It is **SUPPORTED as a mechanism** if some arm is SUPPORTED with a wider spread.
  - Separately, the lane GOAL is met only if the favourite gap closes (top-decile model probability moves
    materially toward the actual win rate). The size is reported, not pre-judged.
- **Secondary** (never used for a verdict): CORE and PROMOTED subsets, per league, per test season, big 5 vs
  goals leagues, 2026 alone, and the selected grid value per season and family.

### Identity / reachability check (the run stops if it fails)

The variant code reimplements the window mean so that it can weight and blend. **At the shipped config
(W0, h = ∞, c = ∞, gate, p0) it must reproduce production's `compute_team_ratings` raw output** (scale 1,
cap ∞, the harness's module-global patch) and its `matches` count, for every rated side of every FULL
match, to within 2e-4. A **reachability check** follows: every family's non-shipped grid values must change
the rating vector of at least 1% of FULL matches (`off != on`). A family that changes nothing is reported as
INERT, not scored.

### What this does NOT establish

- The SERVED sim's 1X2 under a changed rating. No sim is run. The compression study measured the engine's gain
  on the rating as linear (R² 0.87) and equal to the refit slope, so a linear-link gain is the expected
  direction, but its size in the sim is not measured.
- Inputs the rating never sees (squad, lineup, injuries, market information). If no family helps, those are
  what remain, and this lane says so.
- MLS and the Championship, which are not rated here.

A SUPPORTED verdict licenses nothing on the board. Stage 2 (production rating code, which sits with another
lane) is a user decision through the model-engine standard.

Run at Idle priority. Driver: `scripts/soccer_team_strength_experiments.py stage1`.

## 2. Coverage

(written after the run's population and identity check, before any score is read)

## 3. Results

## 4. What cannot be estimated

## 5. Deviations from the registration
