# UEFA offsets: recency weighting, on PRODUCTION's ratings (todo #699 Stage 1 item (i)) — 2026-10-16

Lane `uefa-offsets-recency-prod`, session 570a6cd1. Research only: nothing in this lane
touches the sim, the board, a worker, `render.yaml` or a deploy.

Follows `.syndicate/findings_2026-10-16_uefa_league_offsets.md` (lane `uefa-league-offsets`),
which found H-OFFSET SUPPORTED but left two blockers: the offsets DRIFT (since 2020 the EPL
has pulled ~0.1-0.2 further ahead of every league), and they were fit on that module's own
goals-Poisson domestic ratings, not on production's `compute_team_ratings`.

## 1. PRE-REGISTRATION (committed BEFORE any fit)

Written and committed before the first fit. Production's rating INPUTS (Understat team
history, football-data match history) may already have been pulled when this was committed;
coverage counts are not outcomes. No rating, offset, likelihood or held-out number on
production's scale had been computed. Any later change is a deviation and gets its own dated
line in section 5, never an edit here.

### Questions

- **H-REC (primary).** Does a per-league offset fit with exponential RECENCY weights predict
  held-out cross-league UEFA 1X2 better than the single constant offset fit with equal weight
  over every training season, when the club component is production's own rating?
- **H-PROD (replication).** On production's rating scale, does the constant offset still beat
  no offset? (The 2026-10-16 SUPPORTED verdict was on a different club component.)

### Data

- **UEFA results, placement, flags:** exactly the 2026-10-16 inputs, reused from the research
  root `C:/tmp/uefa-offsets` (ESPN; `uefa/`, `domestic_rows.json`, `uefa_flags.json`). Club ->
  league placement per season by ESPN team id, `build_membership` majority rule, unchanged.
- **Production rating inputs**, pulled with production's own fetcher
  (`scripts/fetch_soccer_history_local.py`, the producer of the fleet's files) into
  `C:/tmp/uefa-offsets/prod_history/<league>/`:
  - big 5 (`epl`, `la_liga`, `bundesliga`, `serie_a`, `ligue_1`): `--kind teams` (Understat
    xG team history), season start years 2014 .. 2026 (Understat begins 2014-15);
  - `eredivisie`, `primeira_liga`, `belgian_pro_league`: `--kind matches` (football-data.co.uk),
    season start years 2013 .. 2026.
  - MLS and Championship: not pulled (0 UEFA appearances in 2014-2026; NOT ESTIMABLE as before).

### Club component = production's rating, as of each kickoff

For a UEFA match on day `t`, each club's `(attack_rating, defense_rating)` is the output of
production's `compute_team_ratings(rows, as_of=t, window=W)` (`features/loaders.py`), called
exactly the way `scripts/build_soccer_artifacts.py:_load_team_ratings` calls it:

- big 5: Understat `teams_*.csv` rows, `window=45`;
- goals leagues: `team_rows_from_match_history(matches_*.csv rows)` (no ESPN stats), `window=90`.
- **History depth mirrors the fleet's disk.** `compute_team_ratings`'s `league_mean` depends on
  which seasons are handed in, so the input is the files a fleet would hold at `t`: read
  2026-10-16 on `~/syndicate-prod/data/soccer_source`, Understat holds 3 seasons
  (2024..2026) and football-data 4 (2023..2026). So: big 5 = the season containing `t` and the
  2 before it; goals leagues = the season containing `t` and the 3 before it (season = July..June,
  labelled by start year). `as_of=t` drops every row dated on or after the kickoff day (the
  function's own strict-before rule); the driver additionally asserts it.
- **Team join = production's.** The club's ESPN name is matched to that league's ratings keys
  with production's `match_team_name` (what `_rating_for` does). Where production would return a
  silent `0.0` (no match), the match is EXCLUDED and counted, never scored at 0.0. The full
  ESPN -> production name map is written to the report and AUDITED BEFORE THE FIT; a wrong pairing
  found by the audit is corrected by an explicit alias recorded in section 5.
- **Eligibility:** both clubs matched and `matches >= 5` in the rating. Excluded matches are
  counted and are excluded from every arm (all arms score the same matches).
- Extra time / penalties excluded from training and scored as a draw; finals (`season.slug ==
  "final"`) neutral — both as in the 2026-10-16 registration and its section-5 deviation.

### The three arms (independent Poisson, same functional form as 2026-10-16)

`log λ_home = μ + η·(1 − neutral) + β·(a_i − d_j) [+ o_L(i) − o_L(j)]`,
`log λ_away = μ + β·(a_j − d_i) [− (o_L(i) − o_L(j))]`, 1X2 truncated at 10 goals.

- **NONE:** no offset. Free μ, η, β. Equal weights.
- **CONST:** one offset per league, equal weights over all training seasons 2014 .. S−1
  (the 2026-10-16 OFFSET arm).
- **REC:** the same parameters (μ, η, β and the offsets — the WHOLE likelihood is weighted, not
  the offsets alone), each training match weighted `w = 0.5 ** (age_days / 730)`, where
  `age_days` = days from the match to **July 1 of the test season S** (the moment the
  parameters are frozen). **Half-life = 2 seasons (730 days), fixed here, not tuned.**
  Chosen up front because the 2014-19 -> 2020-26 drift is ~0.1-0.2 over ~6 seasons and an
  inner walk-forward for the early test seasons would rest on two training seasons.

### Held-out split (identical to 2026-10-16)

Walk-forward by season. Test season S in **2017 .. 2026** (2026 partial); training = eligible
cross-league matches of seasons 2014 .. S−1; parameters frozen through the test season.
Club ratings as of each match date in every season.

### Metric, test and verdicts (identical rule to 2026-10-16)

- Per-match 1X2 log loss; paired differences pooled over every test match of every test season;
  95% CI by bootstrap over matches (2,000 resamples, seed 699).
- **H-REC (primary): Δ = REC − CONST.** **H-PROD: Δ = CONST − NONE.** Each gets its own verdict:
  **SUPPORTED** if the CI lies entirely below 0; **NOT DEMONSTRATED** if the point estimate is
  below 0 and the CI includes 0; **FALSIFIED** if the point estimate is >= 0.
- **Secondary** (reported, not used for a verdict): REC − NONE; Δ Brier for both contrasts;
  per-season Δ; the big-5-only subset; the 2020-26 test seasons alone.
- **Descriptive only** (reported, never used for a verdict or to change the primary half-life):
  the same walk-forward at half-lives 1, 3 and 4 seasons.

### Parameters reported, with intervals

95% percentile bootstrap over matches (1,000 resamples, seed 699), the weights travelling with
their matches:

- **CONST** fit on all eligible 2014 .. 2026: μ, η, β, each offset centred and vs EPL;
- **REC** fit as of **2026-10-16** (ages measured to that day, half-life 730 days): μ, η, β,
  each offset centred and vs EPL, and each league's effective match count `(Σw)² / Σw²`;
- **NONE** β with its interval.
- A league below 30 cross-league matches (raw count) is **NOT ESTIMABLE**, not imputed.

### What this does NOT establish

Beating the de-vigged UEFA close (Stage 1 step 3), anything about the 524 out-of-scope clubs,
or that production's ratings are the right club component (only that the offsets are measured
on the scale production would serve with). A SUPPORTED verdict licenses nothing on the board.

## 2. Coverage

(written after the pull and the name audit, BEFORE any fit)

- **Production inputs pulled:** 107 of 107 season files, 0 failures. Understat (big 5)
  covers 2014..2026 and football-data (Eredivisie, Primeira Liga, Belgium) covers 2013..2026,
  so each league-season holds what a fleet would hold.
- **Cross-league UEFA matches: 1,618** (the same placement as 2026-10-16).
- **Name audit** (`prod_name_map.json` in the research root): 111 clubs.
  - 40 ESPN names differ from production's key, and **all 40 pairings are correct**: for example
    `Internazionale` -> `Inter`, `RB Leipzig` -> `RasenBallsport Leipzig`, `Braga` -> `Sp Braga`,
    `Union St.-Gilloise` -> `St. Gilloise`. No ESPN name maps to more than one production key.
  - **`Sporting CP` NEVER matches (63 of 63 matches).** football-data spells it `Sp Lisbon`, and
    `match_team_name` finds nothing. That is the case where production's `_rating_for` hands back a
    silent `0.0`. See deviation 1.
  - Athletic Club (1 match) and Napoli (2) are unmatched only on dates where their row is absent
    from the as-of table. They are excluded as registered.
- **Eligible with the deviation-1 alias: 1,603.** Excluded: 2 with no production rating, 13 with
  under 5 rated matches. 3 have no status payload and are kept as non-neutral 90-minute results.
  **Registration-literal (no alias): 1,540**, because 63 Sporting matches drop out.

## 3. Results

Run 2026-10-16 ~15:30Z at Idle priority. Driver: `scripts/fit_uefa_offsets_prod_ratings.py run`.
Output: `C:/tmp/uefa-offsets/report_prod.json` (and `report_prod_no_alias.json`).
The primary arm uses the deviation-1 alias: **1,603 eligible matches, 1,278 of them held out over
the 2017-2026 test seasons.**

### Verdicts

| test | Δ 1X2 log loss | 95% CI | verdict |
|---|---|---|---|
| **H-REC: REC(half-life 730 d) − CONST** | **+0.0010** | [−0.0024, +0.0048] | **FALSIFIED** |
| **H-PROD: CONST − NONE** | **−0.0555** | [−0.0724, −0.0378] | **SUPPORTED** |
| sensitivity, registration-literal (no alias, 1,540): H-REC | +0.0011 | [−0.0027, +0.0046] | FALSIFIED |
| sensitivity, registration-literal: H-PROD | −0.0552 | [−0.0717, −0.0378] | SUPPORTED |

Mean held-out log loss by arm:

| arm | log loss |
|---|---|
| NONE | 1.0593 |
| **CONST** | **1.0039** |
| REC 730 d | 1.0049 |
| REC 365 d (descriptive) | 1.0067 |
| REC 1095 d (descriptive) | 1.0044 |
| REC 1460 d (descriptive) | 1.0042 |

For comparison, the 2026-10-16 module's own goals ratings scored OFFSET 1.0110 and NO-OFFSET 1.0551.
So **production's xG ratings with the constant offset are the best club component measured so
far** (1.0039). The match sets differ slightly (1,278 test matches in both runs, but the
eligibility rules differ), so this comparison is descriptive.

**Secondary results** (none used for a verdict):
- REC − NONE: −0.0544 [−0.0720, −0.0362].
- Δ Brier: REC − CONST +0.0005 [−0.0019, +0.0032]; CONST − NONE −0.0403 [−0.0524, −0.0276].
- Big-5-only subset: REC − CONST +0.0000 [−0.0046, +0.0049]; CONST − NONE −0.0270 [−0.0395, −0.0141].
- **2020-26 test seasons only** (the era where the drift was seen): REC − CONST +0.0004
  [−0.0042, +0.0049]; CONST − NONE −0.0530 [−0.0728, −0.0332].
- Per season, REC − CONST:
  - 2017 +0.001, 2018 +0.007, 2019 +0.001, 2020 +0.001, 2021 −0.007;
  - 2022 +0.008, 2023 +0.011, 2024 −0.007, 2025 −0.002, 2026 +0.003.
  - The CIs of 2 seasons (2018, 2023) lie entirely ABOVE 0; none lie below.
- Per season, CONST − NONE is below 0 in all 10 seasons.

**Descriptive half-life grid:** REC 365 d is +0.0029, 730 d +0.0010, 1095 d +0.0005 and
1460 d +0.0003, all relative to CONST. The loss falls steadily toward CONST as the half-life
grows. **No half-life beats equal weighting.**

### Parameters (95% bootstrap, 1,000 resamples over matches, seed 699)

| arm | μ | η (home) | **β** |
|---|---|---|---|
| NONE (2014-26) | 0.170 [0.119, 0.219] | 0.255 [0.194, 0.318] | **0.93 [0.71, 1.17]** |
| CONST (2014-26) | 0.083 [0.035, 0.130] | 0.261 [0.205, 0.320] | **1.66 [1.44, 1.90]** |
| REC as of 2026-10-16 | 0.087 [0.014, 0.151] | 0.282 [0.209, 0.367] | **1.74 [1.40, 2.06]** |

**Offsets vs EPL** (log goal rate, on production's rating scale). `eff n` is the REC effective
match count, `(Σw)²/Σw²`.

| league | n | CONST vs EPL | 95% CI | REC vs EPL (2026-10-16) | 95% CI | eff n |
|---|---|---|---|---|---|---|
| EPL | 553 | 0 | — | 0 | — | 286 |
| La Liga | 533 | −0.109 | [−0.165, −0.050] | −0.193 | [−0.283, −0.110] | 259 |
| Bundesliga | 477 | −0.136 | [−0.210, −0.064] | −0.213 | [−0.305, −0.119] | 238 |
| Serie A | 456 | −0.200 | [−0.259, −0.132] | −0.253 | [−0.341, −0.162] | 239 |
| Ligue 1 | 391 | −0.239 | [−0.307, −0.172] | −0.273 | [−0.373, −0.181] | 194 |
| Primeira Liga | 278 | −0.467 | [−0.543, −0.381] | −0.495 | [−0.602, −0.381] | 148 |
| Eredivisie | 240 | −0.519 | [−0.598, −0.421] | −0.624 | [−0.740, −0.485] | 131 |
| Belgian Pro League | 200 | −0.529 | [−0.628, −0.432] | −0.581 | [−0.710, −0.444] | 99 |
| MLS | 0 | **NOT ESTIMABLE** | | | | |
| Championship | 0 | **NOT ESTIMABLE** | | | | |

Centred CONST offsets are EPL +0.275, La Liga +0.166, Bundesliga +0.139, Serie A +0.075,
Ligue 1 +0.035, Primeira −0.192, Eredivisie −0.244 and Belgium −0.254. All centred values are in
`report_prod.json`.

### Engine read (beyond the verdicts)

- **The drift is real on production's scale too, but it does not pay.**
  - Recency-weighted offsets as of today put the EPL further ahead of every league:
    - La Liga −0.19 vs −0.11 under CONST, Bundesliga −0.21 vs −0.14, Eredivisie −0.62 vs −0.52.
    - The walk-forward shows the same thing: the CONST La Liga offset moves +0.03 (2017) ->
      −0.09 (2025), and REC moves −0.18 by 2025.
  - Yet REC never beats CONST out of sample, at any half-life.
  - The likely reason is visible in β. **β drifts as well:** CONST β is 1.80 (2017), 1.72 (2020),
    1.71 (2023) and 1.57 (2025); REC β falls to 1.36 by 2025. Recency weighting moves the offsets
    and β together, and the variance it adds (effective n roughly halves) outweighs the bias it
    removes.
  - **Serve the constant offset.** Do not carry a recency weight forward without a new
    registration, for example a separate drift term on β or a per-pair test.
- **β = 1.66 is the larger finding, and it is about production's ratings, not about UEFA.**
  - On its own module's goals ratings β was 0.80 (domestic gaps shrink in UEFA). On production's
    ratings β is **1.66 [1.44, 1.90]**: production's rating gaps must be **amplified ×1.66** to
    match UEFA goal rates.
  - Production's ratings are linear in the xG ratio, scaled by `_RATING_SCALE = 0.55` and
    **clamped at ±0.35** (`_RATING_CAP`).
  - **611 of 3,206 UEFA-match attack ratings (19%) sit exactly on the +0.35 clamp**, and 614 of
    6,412 attack + defence values (9.6%) sit on a clamp. So production cannot tell the top clubs
    apart — exactly the clubs that play in the UCL.
  - This lines up with #699's existing domestic note: pregame 1X2 loses to the de-vigged close and
    **favourites are underrated**. A compressed, clamped rating predicts precisely that. It is a
    LEAD for lane `soccer-team-strength`, not a measured domestic defect: no domestic test was run
    here.
- **Production name join defect:** `match_team_name` does not match `Sporting CP` to
  football-data's `Sp Lisbon` (0 of 63). Production's `_rating_for` would return a silent `0.0`
  for Sporting wherever an ESPN-spelled name reaches it. A UEFA Stage 1 sim needs an explicit
  ESPN -> production alias map, audited the way section 2 audited it.

## 4. What cannot be estimated

- **MLS and Championship offsets:** 0 cross-league UEFA matches, so NOT ESTIMABLE (as before).
- **Whether a drift model of another form helps:** for example a time-varying β, a per-pair
  offset, or a random walk on offsets. Only exponential whole-likelihood weighting was registered
  and tested.
- **The domestic consequence of β = 1.66 and the clamp.** No domestic backtest was run in this lane.
- **The 524 out-of-scope clubs**, and **beating the de-vigged UEFA close.** Those are Stage 1
  items (ii) and (iii).

## 5. Deviations from the registration

- **1. Sporting CP alias (2026-10-16 ~15:40Z, decided after the name audit and BEFORE any fit).**
  - The registration says an unmatched club is excluded, and only a WRONG pairing gets an alias.
  - Sporting is a MISSING pairing. Excluding it drops 63 of 1,603 matches and removes Portugal's
    strongest UEFA club, which would bias Portugal's offset.
  - So one explicit alias, `("primeira_liga", "Sporting CP") -> "Sp Lisbon"`, is applied, and the
    **primary results use it.**
  - The **registration-literal run (no alias, 1,540 matches) is reported beside the primary
    results** as a sensitivity check (`run --no-aliases`).
