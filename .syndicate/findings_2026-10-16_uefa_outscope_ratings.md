# UEFA out-of-scope club ratings (todo #699 Stage 1 item (ii)) — 2026-10-16

Lane `uefa-outscope-ratings`, session 436c79e2. Research only: nothing in this lane touches
the sim, the board, a worker, `render.yaml` or a deploy. Stage 0 keeps serving no UEFA
projection.

Follows `.syndicate/findings_2026-10-16_uefa_league_offsets.md` (step 2, offsets SUPPORTED) and
`.syndicate/findings_2026-10-16_uefa_offsets_recency_prod.md` (item (i): CONST offsets on
production's scale SUPPORTED, recency FALSIFIED for the OFFSETS).

## 1. PRE-REGISTRATION (committed BEFORE any fit)

Written and committed before the first fit. Before this was written, only COUNTS were read
(no outcome, rating or likelihood): 9,623 UEFA matches 2014-2026 in the research root
`C:/tmp/uefa-offsets`; **7,954 with at least one out-of-scope club, 5,231 with two**; 525
out-of-scope clubs; the ESPN venue country is present on 9,524 of 9,999 events, and 63
out-of-scope clubs have no home match carrying a country. Any later change is a deviation and
gets its own dated line in section 5, never an edit here.

### Definitions

- **In-scope club (per match):** placed in one of our domestic leagues for that season by
  step 2's `build_membership` (ESPN team id, July..June window, majority rule), unchanged.
- **Out-of-scope (OOS) club (per match):** not placed in any of our leagues that season.
- **Rating scale = production's, with the measured offsets.** An in-scope club's EFFECTIVE
  attack and defence are `A = β·a + o_L`, `D = β·d + o_L`, where `(a, d)` is production's
  `compute_team_ratings` as of the kickoff day, exactly as item (i) builds it
  (`scripts/fit_uefa_offsets_prod_ratings.py` `ProdRatingIndex`: Understat window 45 for the big
  5, football-data window 90 for the rest, the fleet's disk depth, the deviation-1 Sporting
  alias), and `β`, `o_L` are the **CONST** fit of item (i) on cross-league matches of the
  training seasons only. The goals model is item (i)'s:
  `log λ_home = μ + η·(1 − neutral) + A_home − D_away`, `log λ_away = μ + A_away − D_home`,
  independent Poisson, 1X2 truncated at 10 goals.
  An OOS club's rating is an `(A, D)` pair in these same effective units. Its production-unit
  equivalent (offset 0 = the centred mean league) is `(A/β, D/β)`; both are reported.
- **Association (country):** the mode of the ESPN venue country over the club's NON-neutral
  home UEFA matches, all seasons (metadata, not outcomes). A tie or no country -> unknown.
  **The country map is AUDITED BEFORE THE FIT** (clubs whose mode holds < 80% of their home
  matches, and every club on a tie). A wrong country found by the audit is corrected by an
  explicit override listed in section 2 (e.g. ESPN tags Sparta Prague's home matches "Austria":
  Generali Arena is also Austria Wien's stadium name). The audit decides overrides on
  geography only, never on results.

### The OOS model (penalised Poisson MAP, one fit per training set)

For an OOS club `c` in association `k`:
`A_c = g_A + m_A[k] + u_A[c]`, `D_c = g_D + m_D[k] + u_D[c]`.

- `g_A, g_D`: one out-of-scope mean (unpenalised). `m[k]`: association effects, penalty
  `τ_k/2 · Σ m²` (unknown association: `m = 0`). `u[c]`: club deviations, penalty `τ_c/2 · Σ u²`.
  `μ, η` refit (unpenalised) on the same training matches. In-scope `(A, D)` are fixed inputs.
- **Training matches:** UEFA matches with ≥1 OOS club in seasons 2014 .. S−1, excluding extra
  time (score includes ET), each weighted `w = 0.5 ** (age_days / 365)`, age measured to
  **July 1 of the test season S**. **Half-life 365 days, fixed here** (clubs turn over faster
  than leagues; item (i)'s FALSIFIED recency was for league offsets, not clubs — the
  descriptive grid below is the check, and it cannot change the primary).
- **τ selection (inner walk-forward, training data only):** fit on seasons < S−1 (weights to
  July 1 of S−1), score 1X2 log loss on season S−1's eligible matches; pick
  `τ_c, τ_k ∈ {2, 5, 10, 20, 50}` (arm (b): `τ_k` only) at the minimum; refit on < S with the
  chosen values. Ties go to the larger τ.
- **Eligibility (all arms score the same matches):** ≥1 OOS club; every in-scope participant
  has a production rating with `matches >= 5` (item (i)'s rule); matches failing it are
  excluded and counted. Extra time / penalties are scored as a draw; finals neutral (as before).

### Arms

- **(a) PROMOTED (what production would actually do).** Stage 0 serves nothing, so the
  comparison is what an enabled sim would do with today's code: `build_soccer_artifacts`
  `_fill_promoted` gives an unmatched fixture team `PROMOTED_TEAM_RATING` (−0.18, −0.18), and
  there is no league offset for it (0 = the centred mean). So `A = D = β·(−0.18)`. (`_rating_for`'s
  silent `0.0` is the path when `_fill_promoted` is skipped; it is reported as a secondary arm
  (a0), `A = D = 0`.) `μ, η` refit on the training matches like every arm.
- **(b) PRIOR-ONLY.** The model with `u ≡ 0`: out-of-scope mean + association effect.
- **(c) FITTED.** The full model.

### Held-out split

Walk-forward by season, test seasons **S = 2017 .. 2026** (2026 partial); parameters (CONST
β/offsets, μ, η, g, m, u, τ) frozen at July 1 of S for the whole test season. In-scope
production ratings as of each kickoff day (they are inputs, not parameters).

### Metric, verdicts, falsification

Per-match 1X2 log loss on eligible test matches; paired differences pooled over every test
match of every test season; 95% CI by bootstrap over matches (2,000 resamples, seed 699).

- **H-FIT (primary): Δ = (c) FITTED − (b) PRIOR-ONLY.**
  **SUPPORTED** if the CI lies entirely below 0; **NOT DEMONSTRATED** if the point estimate is
  below 0 and the CI includes 0; **FALSIFIED** if the point estimate is ≥ 0.
  **FALSIFIED means: fitting club ratings from UEFA results does not beat the association prior,
  and Stage 1 should serve the prior (or nothing) for OOS clubs.**
- **H-PRIOR (secondary, same rule): Δ = (b) − (a) PROMOTED.**
- Secondary (reported, no verdict): (c) − (a); (c) − (a0); Δ Brier for each; per-season Δ (and
  how many seasons are below 0); subsets: OOS-vs-in-scope vs OOS-vs-OOS; UCL / UEL / UECL;
  main draw vs qualifying; matches with a THIN OOS club vs none.
- **Descriptive only** (never used for a verdict or to change the primary): arms (b) and (c) at
  half-lives 182 d, 730 d and no decay.

### Coverage threshold

**THIN = an OOS club with fewer than 6 UEFA matches in the 3 seasons before the test season**
(S−3 .. S−1; for the snapshot, seasons 2023 .. 2026-to-date). A thin club still gets the model's
rating (it is shrunk toward its prior by construction); the threshold is what coverage is
reported against and what a later serving rule may gate on.

### Snapshot reported, with uncertainty

The full model fit as of **2026-10-16** (all eligible matches through that day, weights to that
day, τ by the same inner rule with S = 2027, CONST β/offsets on all 2014-2026 cross-league):
every OOS club seen in seasons 2025-2026 with `A, D`, the production-unit `(A/β, D/β)`, an
approximate standard error (diagonal Laplace: `1/sqrt(Σ w·λ + τ_c)` per component), its
association and match counts; every association effect; `g`, `μ`, `η`, the chosen τ. Coverage:
how many OOS clubs of 2025-26 are fitted (≥ 6) vs thin (< 6).

### What this does NOT establish

Beating the de-vigged UEFA close (Stage 1 step 3, the go/no-go gate), knockout / two-legged
handling, or anything about MLS / Championship clubs (0 UEFA matches). A SUPPORTED verdict
licenses nothing on the board.

## 2. Coverage and the pre-fit country audit

(written after the audit, BEFORE any fit)

- **Eligible OOS matches: 7,914** of 7,954 with ≥1 OOS club, 2014-2026. Excluded 40: 19 whose
  in-scope club has no production rating and 21 whose in-scope club has < 5 rated matches
  (mostly 2014, the start of the fleet-depth window). 18 have no status payload and are kept as
  non-neutral 90-minute results; 379 went to extra time (not trained on, scored as draws).
  **5,231 are OOS vs OOS.** Per season: 2014 553, 2015 614, 2016 560, 2017 531, 2018 617,
  2019 581, 2020 441, 2021 672, 2022 651, 2023 657, 2024 775, 2025 771, 2026 491 (to date).
  **Test seasons 2017-2026: 6,187 matches.**
- **Associations** (`scripts/fit_uefa_outscope_ratings.py assoc`, `outscope_assoc_audit.json` in the
  research root): ESPN venue country on 9,524 of 9,998 events; 525 OOS clubs; 50 associations.
  **66 OOS clubs are UNKNOWN** (63 with no home match carrying a country, 3 ties: Hapoel Tel Aviv,
  Hapoel Kiryat Shmona, Dinamo Brest). Registration-literal: they get the out-of-scope mean `g`,
  and no country was filled in for them by hand.
- **Audit result.** The < 80%-share / tie rule flagged 18 clubs. 13 of them, and 7 more seen on a
  skim of the full per-country list, are exile or stadium-name artefacts. The mode is right for the
  flagged Ukrainian and Israeli clubs (Shakhtar 42 of 67 in Ukraine, Maccabi Tel-Aviv 49 of 68),
  so they are not overridden. **13 explicit overrides (`OVERRIDES` in the driver), geography
  only:** Sparta Prague and Bohemians 1905 Austria -> Czechia (ESPN's "Generali Arena" is also
  Austria Wien's stadium); Maccabi Petah-Tikva Bulgaria -> Israel; ND Gorica Estonia -> Slovenia;
  Gomel Greece -> Belarus; Isloch Minsk, ML Vitebsk, Neman Grodno, Torpedo Zhodino Hungary ->
  Belarus; Radnicki Nis North Macedonia -> Serbia; Kryvbas, Polissya Zhytomyr, SC Dnipro-1
  Slovakia -> Ukraine.
- 3 OOS clubs sit in one of OUR countries (Zulte Waregem, Go Ahead Eagles, Torreense;
  Welsh clubs are Wales). They are treated as any other association, as registered.

## 3. Results

## 4. What cannot be estimated

## 5. Deviations from the registration
