# Soccer team ratings: too compressed for DOMESTIC 1X2? (lane `soccer-team-strength`, todo #699) — 2026-10-16

Lane `soccer-team-strength`, session 2eff0a12. Research only: nothing in this lane touches the
sim, the board, a worker, `render.yaml` or a deploy. Production rating code
(`syndicate/features/soccer/features/loaders.py`) is READ, never edited.

Follows `.syndicate/findings_2026-10-16_uefa_offsets_recency_prod.md`. On production's ratings,
cross-league UEFA goals needed β = 1.66 [1.44, 1.90], so rating gaps had to be amplified 1.66×.
611 of 3,206 UEFA-match attack ratings (19%) sat exactly on the +0.35 clamp. That lane ran no
domestic test. This lane runs one.

## 1. PRE-REGISTRATION (committed BEFORE any data pull or fit)

Written and committed before the football-data pull. Production's rating inputs
(`C:/tmp/uefa-offsets/prod_history`, pulled 2026-10-16 by lane `uefa-offsets-recency-prod`) exist.
No domestic rating, likelihood, odds or outcome number has been computed in this lane. Any later
change is a deviation. It gets its own dated line in section 5 and never an edit here.

### Question

Production's rating is `r = clamp(0.55 · x, ±0.35)`, with `x_att = xg_for/league_mean − 1` and
`x_def = 1 − xg_against/league_mean` (`compute_team_ratings`, `_RATING_SCALE` and `_RATING_CAP`).
Is this rating too COMPRESSED to predict domestic 1X2 outcomes? Two mechanisms:

- **H-SCALE (primary 1).** The scale is too small. A refit multiplier `m` on the shipped rating
  predicts held-out domestic 1X2 better than the rating read at face value, and `m > 1`.
- **H-CLAMP (primary 2).** The ±0.35 clamp destroys information. Removing it predicts held-out
  domestic 1X2 better, with the slope refit in BOTH arms, so the test does not depend on the
  face-value convention below.

### Data

- **Leagues:** `epl`, `la_liga`, `bundesliga`, `serie_a`, `ligue_1` (big 5), and `eredivisie`,
  `primeira_liga`, `belgian_pro_league` (goals leagues).
  - MLS: excluded. ASA history is undated season aggregates, and `compute_team_ratings` says MLS
    cannot be backtested.
  - Championship: excluded. No production history was pulled.
- **Rating inputs:** reused exactly as lane `uefa-offsets-recency-prod` held them.
  - Big 5: Understat `teams_*.csv` for 2014..2026, `window=45`, the season containing the match
    plus the 2 before it.
  - Goals leagues: football-data `matches_*.csv` for 2013..2026 through
    `team_rows_from_match_history`, `window=90`, the season plus the 3 before it.
  - This is the call shape of `build_soccer_artifacts._load_team_ratings` and the fleet's disk
    depth. It is the `ProdRatingIndex` of `scripts/fit_uefa_offsets_prod_ratings.py`.
- **Matches, outcomes and the close:** football-data.co.uk raw season CSVs (`E0 SP1 D1 I1 F1 N1 P1
  B1`), seasons 2014..2026 (2026 partial to 2026-10-16). They are pulled raw into
  `C:/tmp/team-strength/fd_raw/`, because production's `normalize_match_history` drops the closing
  columns.
  - **Close** = Pinnacle closing `PSCH/PSCD/PSCA`. Where that is absent, the market-average close
    `AvgCH/AvgCD/AvgCA`. Where that is absent, `B365CH/B365CD/B365CA`. Otherwise there is no close
    and the match is excluded.
  - De-vig: proportional (each implied probability divided by their sum).
  - Counts by close source are reported.

### Club component, as of each kickoff

- For a match on day `t`, the club's ratings come from production's `compute_team_ratings(rows,
  as_of=t, window=W)` on the depth above.
  - `as_of` drops every row dated on or after the kickoff day.
  - The driver also asserts this.
- **Raw deviation `x`.** This is the same call with the research process's own copies of
  `loaders._RATING_SCALE = 1.0` and `loaders._RATING_CAP = inf` (a module-global patch inside the
  research process only, nothing written).
  - **Reachability/identity check:** `clamp(0.55·x, ±0.35)` must equal production's unpatched output
    for every rated team on a sample of at least 200 (league, day) tables, to a tolerance of 2e-4
    (4-dp rounding). If it does not, the run stops.
- **Team join:** football-data names are matched to rating keys with production's
  `match_team_name`.
  - Goals leagues share one source, so the names are identical.
  - Big 5: the football-data -> Understat map is written out and AUDITED BEFORE THE FIT.
  - A wrong or missing pairing gets an explicit alias, recorded in section 5.
- **Eligibility:** both clubs matched, `matches >= 5` in both ratings, and a close present. Every
  arm scores the SAME matches. Exclusions are counted by reason.

### The model (identical in every arm)

Independent Poisson, per league `L`:

`log λ_home = μ_L + η_L + k·(A_home − D_away)`, `log λ_away = μ_L + k·(A_away − D_home)`.

1X2 from the score grid, truncated at 10 goals and renormalised. `μ_L` and `η_L` are always fit.

### Arms

| arm | A, D | k |
|---|---|---|
| **A — shipped** | `clamp(0.55·x, ±0.35)` | fixed **1** |
| **B — clamp removed** (the literal arm b) | `0.55·x` | fixed **1** |
| **C — refit scale multiplier** | `clamp(0.55·x, ±0.35)` | **refit** (`k = m`) |
| D — clamp removed + refit (secondary; the scale-free clamp contrast) | `0.55·x` | refit |

**Why `k = 1`, and what it does NOT mean.** `k = 1` reads the rating at face value as a log
goal-rate gap. That is the convention under which the UEFA lane reported β = 1.66.

- The engine does NOT consume ratings this way. `possession_priors` maps `0.5 + r` into
  possession probabilities and averages it with a second xG-derived index.
- So `k = 1` is a CONVENTION, not the engine's gain. H-SCALE answers "compressed relative to face
  value".
- H-CLAMP (D − C) is independent of the convention.
- Neither verdict measures the served sim.

### Held-out split

- Walk-forward by season (July..June, labelled by start year).
- Test season `S` in **2016 .. 2026** (2026 partial).
- Training = eligible matches of seasons 2014 .. S−1.
- Parameters frozen through the test season. Club ratings are as of each match date in every season.

### Metric, test and verdicts

- Per-match 1X2 log loss vs the outcome. Paired differences are pooled over every test match. 95%
  CI by bootstrap over matches (2,000 resamples, seed 699). The match is the cluster: both goal
  counts travel together.
- **H-SCALE: Δ = C − A.**
  - **SUPPORTED** if the CI lies entirely below 0 AND the full-period `m̂` (fit on 2014..2026,
    bootstrap 1,000, seed 699) is above 1 with its CI excluding 1.
  - **OVER-DISPERSED (falsified as compression)** if the CI lies below 0 but `m̂ < 1` with its CI
    excluding 1.
  - **NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0.
  - **FALSIFIED** if the point estimate is ≥ 0.
- **H-CLAMP: Δ = D − C.** SUPPORTED if the CI lies entirely below 0. NOT DEMONSTRATED if the point
  estimate is below 0 and the CI includes 0. FALSIFIED if the point estimate is ≥ 0.
- **Literal arm (b): Δ = B − A**, with the same three-way rule. Reported as a secondary verdict.
- **Against the close:** for every arm and for the close, mean held-out log loss, plus Δ(arm −
  close) with its CI. The gap to the book "narrows" if Δ(best arm − close) < Δ(A − close) with
  the paired Δ(best − A) CI below 0, which is one of the contrasts above.
- **Favourite calibration**, on held-out matches. The favourite is the side with the highest
  de-vigged close probability among home and away. For each arm report the mean model probability
  of that side, the mean close probability and the actual win rate. Also report the top decile by
  close probability.
- **Secondary** (reported, never used for a verdict): Δ Brier for every contrast; per league; per
  test season; big 5 vs goals leagues; 2026 alone (the season of lane `soccer-team-strength`'s
  shipped-model gap); full-period `μ_L`, `η_L` and `k` for C and D with intervals.

### Clamp census (descriptive)

On the shipped rating (arm A), over every eligible match of 2014..2026:

- per league × season, the count and share of the 4 values per match (home attack, home defence,
  away attack, away defence) sitting on +0.35 and on −0.35;
- distinct clubs with at least one clamped value in that league-season;
- distinct clubs clamped in the as-of table on the last match day of each season;
- the largest `|0.55·x|` (arm B) per league-season, i.e. how far past the clamp the information
  runs.

### What this does NOT establish

- Anything about the SERVED sim's 1X2. The engine's gain on the rating is not measured, and no sim
  is run.
- MLS or the Championship.
- Whether a better rating (shrinkage, recency, promoted-team prior: the lane's stage 1) helps.
  That needs its own registration.

A SUPPORTED verdict licenses nothing on the board. Stage 2 of the lane is a user decision.

Run at Idle priority. Driver: `scripts/soccer_team_strength_experiments.py`.

## 2. Coverage

(written after the pull and the name audit, BEFORE any fit; `C:/tmp/team-strength/audit.json`)

- **football-data raw CSVs:** 104 of 104 league-season files (8 leagues × 2014..2026), 32,656
  played matches with a score.
- **Close source** over eligible matches: Pinnacle close 29,712; market-average close 1,818. That is
  every 2026-27 match, because Pinnacle closing columns are absent from football-data this season.
  B365 close was never needed. 10 matches had no close.
- **Identity / reachability check PASSED:** `clamp(0.55·x, ±0.35)` equals production's unpatched
  `compute_team_ratings` output for every rated team in 432 sampled (league, day) tables. The max
  error was 7.5e-5, which is the 4-dp rounding.
- **Name audit** (262 football-data club names; deviation 1 below):
  - **Six clubs production NEVER matches**, so `_rating_for` would hand them a silent `0.0`:
    - Bundesliga: `FC Koln` -> Understat `FC Cologne` (345 matches); `M'gladbach` ->
      `Borussia M.Gladbach` (413).
    - La Liga: `Ath Bilbao` -> `Athletic Club` (462); `La Coruna` -> `Deportivo La Coruna` (160).
    - EPL: `QPR` -> `Queens Park Rangers` (38).
    - Ligue 1: `Ajaccio GFCO` -> `GFC Ajaccio` (38).
  - **Nine one-off WRONG pairings.** Each fires on a single day when the right club is absent from
    the as-of table, so the fuzzy match falls through to a neighbour:
    - big 5: `Man City` -> Manchester United; `Newcastle` -> Manchester United; `Paris FC` -> PSG;
    - goals leagues: `Cercle Brugge` -> Club Brugge, `Aves` <-> `Chaves`, `Farense` -> Feirense,
      `Feirense` -> Moreirense, `Mouscron` -> Mouscron-Peruwelz.
    - Excluded, never scored.
- **Eligible: 31,530** of 32,656. Excluded: 224 with no rating (promoted clubs with no history in
  the depth, plus the wrong pairings), 892 under 5 rated matches, and 10 with no close.
  - By league: EPL 4,452; La Liga 4,461; Serie A 4,437; Ligue 1 4,136; Bundesliga 3,582;
    Primeira 3,619; Eredivisie 3,572; Belgium 3,271.
  - By season: 2014 2,391; 2015 2,592; 2016..2025 2,425..2,680 each; 2026 431.
  - **Held out (test seasons 2016..2026): 26,547 matches.** Training for the first test season is
    2014..2015 (4,983 matches).
- **One family, one date window.** Ratings, outcomes and the close all come from the same matches
  over 2014..2026 (Understat begins 2014-15), so the CLAUDE.md cross-family intersection trap does
  not bite here. The intersection is the eligible set itself.

## 3. Results

## 4. What cannot be estimated

## 5. Deviations from the registration

- **1. Name aliases and wrong-pairing exclusions (2026-10-16 ~17:00Z, after the name audit and
  BEFORE any fit).** These are the six MISSING and nine WRONG pairings listed in section 2. The
  registration allowed an explicit alias for a wrong or missing pairing. Without the aliases, 1,456
  club-appearances of six clubs (1,377 eligible matches: 30,153 -> 31,530) would drop out, including Athletic Club and Gladbach for whole seasons.
  The wrong pairings are excluded and counted, not re-aliased, because on those days the right club
  has no rating. **Production defect, beyond this lane:** a fixture spelled the football-data way
  would get a 0.0 rating for those six clubs, and it would rate the wrong club on those nine days.
  Production's fixture names come from the odds/ESPN feeds, not football-data, so whether the
  defect is reachable in serving is NOT measured here.
- **2. Descriptive engine-gain read (added 2026-10-16 ~17:00Z, BEFORE any fit; never a verdict).**
  Lane `soccer-1x2-ratings-xg-source` (H37 harness, no market anchoring) left the SERVED sim's
  per-match goal means for 2025-26 in `C:/tmp/soccer-lpb/h2h_armA_<league>.jsonl`.
  - `scripts/soccer_team_strength_experiments.py engine` joins them to this run's as-of ratings
    and regresses `log(home_mean / away_mean)` on the rating gap `(A_h − D_a) − (A_a − D_h)`.
  - The slope is the ENGINE's `k`, on the same scale as arm C's refit `k`. That makes `k = 1` in
    arms A and B a measured quantity instead of a convention.
  - It also reports the engine's own 1X2 log loss against the close on those matches.
