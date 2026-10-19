# UEFA #699 gate re-run with the domestic (a2) favourite temperature — 2026-10-19

Lane `uefa-favourite-temper`, session ca3c8313. Research only: wired into nothing, no deploys, no new
OddsAPI spend (the closes are cached in `C:/tmp/uefa-closes`). Stage 0's no-sim guards stay whatever
this finds.

Follows `findings_2026-10-16_uefa_close_backtest.md` (step 3: NO-GO, model − close +0.0286, top
decile model 0.778 vs close 0.821 vs actual 0.854), `findings_2026-10-19_uefa_market_anchored.md`
(anchored: NO-GO, w = 0 every season) and `findings_2026-10-19_soccer_favourite_gain.md` (domestic
stage 3: arm (a2) passes its FIX rule marginally, −0.0005, but KL to the close gets worse). The recipe
is todo #699, "HOW TO RE-RUN".

## 1. PRE-REGISTRATION (committed BEFORE any scoring)

Nothing tempered has been computed or scored when this is committed. Any change after this point is a
deviation and goes in section 5.

### Data

- The step-3 set, unchanged: 2,474 ESPN UEFA main-draw matches 2020-2026 joined to a de-vigged close.
- Model rates `(λ_h, λ_a)` and `p_model` from a FRESH
  `scripts/backtest_uefa_vs_close.py run --uefa-root C:/tmp/uefa-offsets --closes C:/tmp/uefa-closes --dump-features`.
  The anchored script's self-check (dumped `ll_model` equals step 3's to 1e-9, and `λ -> probs`
  reproduces it) must pass, or the run stops.

### The tempered model (frozen domestic values, nothing fitted on UEFA)

- `T0 = −0.066`, `T1 = +0.271`, `K = 1.577`: the domestic 2026 test-season fit on 2014-2025
  (`C:/tmp/team-strength/stage3_report.json` `groups.main.params.2026`: `a2_t`, `ref_k`).
- `ĝ = (log(λ_h/λ_a) − H) / K`. Domestically `log(λ_h/λ_a) = η + K·g`, so H plays the role of the
  domestic home term η and ĝ is the UEFA rate gap in domestic rating units.
- **H rule:** H is ONE scalar, the unweighted mean of `log(λ_h/λ_a)` over every joined match of seasons
  **2020, 2021, 2022** (the seasons before the first gate season). It uses rates only, never outcomes
  or closes, and no gate-season match contributes to it. Its value is printed and recorded before any
  verdict is read.
- `p_temp = soccer_team_strength_experiments.temper(p, |ĝ|, T0, T1)`, applied to every row's
  `p_model` and to every row's `p_anchored` (ĝ always from the step-3 rates, not the anchored rates).

### Arms, metric and verdicts

- **PRIMARY H-TEMPER, per competition (UCL, UEL, UECL) and pooled:** `BLEND_T = w·p_temp_model +
  (1−w)·p_close`, `w ∈ {0, 0.05, …, 1}` chosen by `uefa_close_backtest.choose_weight` on all joined
  matches of seasons 2020..S−1 (pooled across competitions, ties to the smaller w). Test seasons
  **S = 2023..2026**. Δ = LL(BLEND_T) − LL(CLOSE), per-match 1X2 log loss, paired 95% bootstrap CI
  (`uefa_league_offsets.paired_bootstrap_ci`).
  - **GO** if the CI lies entirely below 0;
  - **NO-GO / NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0;
  - **NO-GO / FALSIFIED** if the point estimate is ≥ 0.
- **SECONDARY (same rule, NOT the gate):** the anchored script's own gate with the anchored
  probabilities tempered (`BLEND_A` of `temper(p_anchored)`, w fit on 2022..S−1, test 2023-2026).
  Untempered BLEND_A and the untempered model blend are recomputed alongside as controls.
- **Reported, no verdict:** w per season for every blend; TEMPERED − MODEL and TEMPERED − CLOSE
  against outcomes (2020-2026 and 2023-2026); KL(close ‖ model) before and after tempering; the
  favourite decile **by the close's favourite probability AND by the model's own favourite
  probability** (close / model / tempered / actual); a sensitivity with H = 0.

### Prior expectation, stated up front

Domestically (a2) improved log loss by 0.0005 but moved AWAY from the close in KL: it sharpens what
the rating already says, it adds no information the close lacks. The blend needs that information,
so **the expected outcome is w ≈ 0 and NO-GO in all three competitions.** TEMPERED − MODEL is expected
to be small and negative (UEFA favourites are underrated even more than domestic ones). A GO would be
surprising and would need a forward test before any serving decision.

### What this does NOT establish

A NO-GO here says the domestic (a2) temperature does not make the model useful next to the UEFA close.
It does not test lineups, rotation or any other information source (lane `soccer-team-strength` (c)).

## 2. CODE AND INPUTS (committed BEFORE the gate was scored)

- Registration `8d6ef805`; code `63ae69e3` (`scripts/backtest_uefa_anchored.py` `--favourite-temper`,
  `--gap-k`, `--home-term`, `--print-home-term`; `tests/test_uefa_favourite_temper.py`, 6 hermetic tests
  incl. a reachability test, off != on). 11 passed with `tests/test_uefa_market_anchor.py`.
- Fresh dump (`backtest_uefa_vs_close.py run --dump-features`, Idle priority): 2,474 rows,
  **byte-identical** to the 2026-10-19 anchored-lane dump, and it reproduces step 3's top decile
  (model 0.778 / close 0.821 / actual 0.854).
- **Registered H = 0.27609310702396533** (`--print-home-term`: mean log(λ_h/λ_a) over the 923 joined
  matches of seasons 2020-2022). Domestic η for comparison is ~0.25-0.3 log-goal units, so the
  centring is plausible.
- Gate command: `backtest_uefa_anchored.py --closes C:/tmp/uefa-closes --skip-live --favourite-temper
  -0.066,0.271 --gap-k 1.577 --home-term 0.27609310702396533`, Idle priority. `--skip-live`: the
  live-refit arm is not part of this registration.

## 3. RESULT

(filled after the run)

## 5. DEVIATIONS

(none yet)
