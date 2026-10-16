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

Run 2026-10-16 at Idle priority, after `61628cbd` (code, audit and coverage on main before the fit).
Driver: `scripts/fit_uefa_outscope_ratings.py run --root C:/tmp/uefa-offsets`.
Output: `C:/tmp/uefa-offsets/report_outscope.json` (research root, not git).
**6,187 held-out matches over the 2017-2026 test seasons, each with ≥1 OOS club.** 4,109 of them
are OOS vs OOS.

### Verdicts

| test | Δ 1X2 log loss | 95% CI | verdict |
|---|---|---|---|
| **H-FIT: (c) FITTED − (b) PRIOR-ONLY** | **−0.0072** | [−0.0113, −0.0032] | **SUPPORTED** |
| **H-PRIOR: (b) PRIOR-ONLY − (a) PROMOTED** | **−0.0653** | [−0.0737, −0.0560] | **SUPPORTED** |

Mean held-out log loss by arm:

| arm | log loss |
|---|---|
| (a0) silent 0.0 (`_rating_for`) | 1.0322 |
| (a) PROMOTED_TEAM_RATING | 1.0308 |
| (b) PRIOR-ONLY | 0.9654 |
| **(c) FITTED** | **0.9582** |

- **Read in proportion.** Almost all of the gain over what production would do comes from the
  association prior (−0.065). Club-level fitting adds a further −0.007, which is real (CI
  below 0, 8 of 10 seasons below 0) but about a tenth of the size. PROMOTED and the silent 0.0
  are indistinguishable (−0.0014 [−0.0078, +0.0042]). Both are bad because they rate every OOS
  club as one club.
- **Per season, FITTED − PRIOR:** 2017 −0.013, 2018 +0.002, 2019 −0.006, 2020 −0.019,
  2021 −0.018, 2022 −0.006, 2023 −0.021, 2024 +0.011, 2025 −0.004, 2026 −0.005. That is 8 of 10
  below 0. PRIOR − PROMOTED is below 0 in **10 of 10** seasons (−0.035 to −0.106).

### Secondary results (none used for a verdict)

- FITTED − PROMOTED −0.0725 [−0.0817, −0.0623]; FITTED − silent 0.0 −0.0740 [−0.0831, −0.0641].
- Δ Brier: FITTED − PRIOR −0.0046 [−0.0073, −0.0019]; PRIOR − PROMOTED −0.0430 [−0.0488, −0.0368].
- Subsets, FITTED − PRIOR (n):
  - OOS vs in-scope (2,078) −0.0097 [−0.0159, −0.0039]; OOS vs OOS (4,109) −0.0060 [−0.0114, −0.0005].
  - UCL (1,346) −0.0101 [−0.0179, −0.0018]; UEL (2,570) −0.0085 [−0.0147, −0.0026];
    **UECL (2,271) −0.0041 [−0.0117, +0.0039]**, which does not separate on its own.
  - **Main draw (3,503) −0.0041 [−0.0091, +0.0010]**, which does not separate either; qualifying
    (2,684) −0.0113 [−0.0181, −0.0044]. The club-level gain is mostly in qualifying, where the
    association prior is weakest. In the main draw, which is what Stage 1 would price, the prior
    already does most of the work.
  - Matches with a THIN OOS club (1,328) −0.0116 [−0.0209, −0.0021]; no thin club (4,859)
    −0.0060 [−0.0105, −0.0014]. Shrinkage works: even a thin club's few matches help.
- PRIOR − PROMOTED is largest in the UCL (−0.088) and on OOS vs OOS matches (−0.077).

### Descriptive half-life grid (no verdict; τ re-used from the primary inner selection)

| half-life | FITTED − PRIOR at that half-life | FITTED vs primary (365 d) FITTED |
|---|---|---|
| 182 d | −0.0064 [−0.0095, −0.0033] | +0.0073 [+0.0045, +0.0101] (worse) |
| **365 d (primary)** | −0.0072 | — |
| 730 d | −0.0078 [−0.0127, −0.0029] | −0.0015 [−0.0037, +0.0006] |
| no decay | −0.0060 [−0.0123, +0.0004] | +0.0046 [−0.0006, +0.0095] |

FITTED beats PRIOR at every half-life. Between 365 d and 730 d there is no separable difference,
and both beat no decay and 182 d. Unlike the league offsets (item (i)), club strength DOES want
recency, but the primary stays at 365 d per the registration.

### τ selection (the inner rule)

- **τ_club** (club deviations) chose 2 / 5 / 10 / 20 across seasons (2 in 2 of 10), and the
  snapshot chose **10**. It is interior to the grid.
- **τ_k** (association effects) chose **2, the grid's lower edge, in 5 of 10 seasons** (2018-21,
  2024), for both the prior and the fitted arm. It also chose 2 in the snapshot. The rest chose 5.
  - The boundary is on the ASSOCIATION shrinkage, not the club shrinkage. The data want the
    association effects shrunk LESS than the grid allows.
  - The PRIMARY verdict stays on the registered grid. No exploratory arm below 2 was run.
  - Testing τ_k < 2 (or a flat, unpenalised association effect) is a pre-registered follow-up.
    The direction suggests a small further gain for both (b) and (c), not a change of sign.

### Snapshot as of 2026-10-16 (full model)

- **CONST** fit on all 2014-26 cross-league matches: β = 1.662. Offsets are item (i)'s, centred:
  EPL +0.275 … Belgium −0.254.
- **OOS model:** μ 0.052, η 0.356, out-of-scope mean **g_A −0.568, g_D −0.507**, τ_club 10, τ_k 2.
  So an OOS club with no data and no association sits well below every one of our leagues. The
  Belgian centred offset is −0.25.
- **Associations, m_A + m_D:**
  - Strongest: Greece +0.99, Norway +0.93, Türkiye +0.90, Denmark +0.87, Cyprus +0.74, Poland +0.70,
    Czechia +0.69.
  - Weakest: San Marino −1.53, Wales −1.26, Northern Ireland −0.99, Luxembourg −0.91, Gibraltar −0.91.
  - These are 365-day-weighted, so they describe the RECENT era. Norway's place is mostly
    Bodø/Glimt.
- **Coverage, OOS clubs that played in season labels 2025 or 2026 (2025-26, and 2026-27 to date): 241,
  every one rated.**
  - **196 are fitted (≥ 6 UEFA matches in season labels 2023-2026) and 45 are THIN (< 6).**
  - 7 have an unknown association, so they get g plus their club deviation.
  - Over 2014-26 there are 525 OOS clubs in all. The other 284 have not played since the 2024-25 season,
    so the snapshot table leaves them out (the library still rates any of them on request).
- **Examples** (effective A / D; production units A/β, D/β with offset 0 in brackets; n = UEFA
  matches in season labels 2023-2026):

| club | assoc | A | D | prod units | n |
|---|---|---|---|---|---|
| Bodø/Glimt | Norway | +0.35 ±0.15 | +0.03 ±0.16 | (+0.21, +0.02) | 56 |
| Galatasaray | Türkiye | +0.13 | −0.14 | (+0.08, −0.08) | 40 |
| Olympiacos | Greece | −0.11 | +0.16 | (−0.06, +0.10) | 43 |
| Shakhtar Donetsk | Ukraine | +0.01 | −0.08 | (+0.01, −0.05) | 38 |
| Celtic | Scotland | −0.07 | −0.28 | (−0.04, −0.17) | 32 |
| RB Salzburg | Austria | −0.06 | −0.26 | (−0.04, −0.15) | 36 |
| Dinamo Zagreb | Croatia | −0.08 | −0.20 | (−0.05, −0.12) | 44 |
| Young Boys | Switzerland | −0.16 | −0.31 | (−0.10, −0.19) | 30 |

  Read against in-scope clubs: a mid-table Belgian or Eredivisie club is about A = D = −0.25, and
  an average EPL club is A = D = +0.27. On this scale the top OOS clubs sit at or above
  Belgian/Dutch mid-table and below an average EPL side. The approximate SEs are ±0.15-0.20 for
  established clubs and ±0.25-0.30 for thin ones.

## 4. What cannot be estimated

- **Whether these ratings beat the de-vigged UEFA close.** That is Stage 1 step 3, the go/no-go
  gate, and it is not run here. Log loss here is against outcomes only.
- **Knockout ties and second legs.** They are scored as ordinary 90-minute matches. Aggregate
  state (a team protecting a lead) is not modelled.
- **MLS and Championship clubs:** 0 UEFA matches.
- **66 clubs (7 of the current 241) with no known association.** They sit on g plus their club
  deviation, which is registration-literal. Filling them in by geography is a cheap follow-up.
- **The association prior is fit from the same UEFA results.** It is not UEFA's published
  coefficient, though that is computed from the same results. No external coefficient was
  compared.
- **The bootstrap resamples matches, not clubs.** Matches of one club are correlated, so the CIs are
  somewhat optimistic. The season count (8 of 10 below 0) is the cruder, cluster-robust check.

## 5. Deviations from the registration

- **None to the primary.** One CLARIFICATION, where the registration was silent: the descriptive
  half-life arms re-use the τ that the primary (365 d) inner rule chose for that season, rather
  than re-selecting τ per half-life. This was decided before the run and is written in the driver
  (`cmd_run`).
