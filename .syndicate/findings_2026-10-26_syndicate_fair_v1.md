# Syndicate Fair v1 — stage-1 findings `[2026-10-26, lane syndicate-fair-v1, OFFLINE]`

Decision Engine Phase 1 (`#736`; todo `#737`). Plan: `docs/ai_context/plan_syndicate_decision_engine.md` §3 L1.

| | |
|---|---|
| **Pre-registration** | `be3fcf23` on `main`, committed ~17:59Z before any fit. Amendment A1 `7786ab1e` (18:07Z): adds a stage-2 lower-λ arm. It was committed after the stage-1 verdicts but before the post-hoc diagnostic returned, and it changes no stage-1 verdict. |
| **Code that produced these numbers** | `d1ff922d` on branch `claude/frosty-chandrasekhar-997092`: `scripts/syndicate_fair_fit.py`, `syndicate/features/shared/syndicate_fair.py`, 46 tests. For review; not on `main`. |
| **Substrate** | Fleet data root `~/syndicate-prod/data` (production since 09-30), read-only at nice 19 / ionice idle. Outcomes from the fleet web's public `game-chips` GET. **No OddsAPI call.** |
| **Window** | Kickoffs 2026-09-30T00:00Z ≤ commence < 2026-10-26T08:00Z |
| **Run** | Extract 17:46–17:51Z, outcomes ~17:55Z, fit ~18:00–18:04Z (Windows, Idle priority, off the fleet VM). Post-hoc diagnostic 18:05–18:2xZ (same code, scratch driver). |
| **Wired anywhere?** | **No.** Nothing imports the module, and `#704`'s staked probability is untouched. |
| **Baseline parity** | v1 is compared with `layer2_board._consensus_fair(..., method="shin")` on the same books at the same snapshot. **0 of 3,125 sampled rows differ** (tolerance 1e−9). |

## Verdict in one paragraph

**By the registered rule, 4 of 13 gated families PASS:**
- NCAAF game lines
- NHL game lines
- NHL props (outcome unmeasured)
- soccer game lines

NCAAF props FAIL. The other 8 are UNDERPOWERED: MLB, NBA regular, NFL and WNBA all have fewer than 30 held-out games.

**Read the passes with four qualifications, each measured below:**
1. **The effects are tiny.** v1 removes 2.4–3.9% of the Shin consensus's KL distance to the close in the non-mechanical passes. It moves the fair 0.15–0.30 pp from Shin on average.
2. **Two of the four passes are mostly mechanical.** On sharp-target rows Pinnacle is both an input and the target (pre-registration §8):
   - NHL props pass on the sharp rows. On the consensus-target rows v1 is **worse**.
   - NCAAF's gain also sits on the sharp rows.
3. **Log loss and absolute error disagree.** In every non-mechanical pass, v1 sits slightly FURTHER from the close in absolute pp than the Shin median (post-hoc, §6a). EV is linear in p.
4. **The registered ridge chose its lower edge at nearly every refit.** But a post-hoc run with λ down to 1e−8 found no hidden signal, only more mechanical Pinnacle weight and overfitting (§6b). The near-equal weights are the data's answer.

**Only soccer** shows a non-mechanical gain from learned weights, against a soft-book consensus close. Its outcome read leans the other way (not significant).

**Recommendation: the registered rule says shadow-wire, for the four passing families. I agree, scoped to `σ_fair`:**
- **Wire `σ_fair_v1`, with `p_fair_v1` beside it, in shadow.** ±1σ coverage is 0.70–0.74 in the three game families, and Phase 2's lower-bound EV needs exactly this.
- **Do NOT let `p_fair_v1` replace Shin's p in any EV, price, Suggested flag or stake** (qualification 3).
- **Stage 2 needs no wiring:** it reads offline from `book_quotes` the way stage 1 did.

Details in §7.

## 1. Coverage and the n every number rests on

The full coverage table (sport-level Pinnacle presence and per-family rows / games / dates / close / outcome
intersections) is in the pre-registration. It was measured before any fit. Held-out n per family is in the gate
table. Two facts shape everything:

- **Pinnacle game lines** exist all window only for **MLB and NCAAF**. NFL, NBA and soccer have them from 10-25 only (≤ 11 events each); NHL and WNBA have none. Pinnacle quotes **NHL props** all window.
- **The training rule** (≥ 5 UTC dates and ≥ 30 games before the first test date) leaves NBA regular season, MLB and WNBA with 0–2 held-out games. Their stage-1 verdict is UNDERPOWERED by construction. **Stage 2 (read ≥ 11-24) is their first real read.**

## 2. The gate table (registered; units are 10⁻⁵ nats per row; lower is better)

Δ = CE(v1) − CE(Shin consensus) to the close target. CIs come from 2,000 game-clustered bootstrap resamples.
Bonferroni = the 1 − 0.05/13 interval. Reported beside the gate, not part of it.

| family | verdict | held-out rows / games / dates | Δ close [95% CI] | Bonferroni CI | equal-weight pool Δ [95% CI] | Δ outcome [95% CI] (games) |
|---|---|---|---|---|---|---|
| ncaaf·regular·game | **PASS** | 11,045 / 168 / 13 | −0.43 [−0.90, −0.08] | [−1.16, +0.07] ✗ | −0.15 [−0.74, +0.25] | −11.89 [−30.15, +5.66] (168) |
| ncaaf·regular·prop | **FAIL** | 4,482 / 110 / 13 | +0.28 [−0.13, +0.67] | [−0.35, +0.88] | +0.36 [−0.15, +0.81] | — |
| nhl·regular·game | **PASS** | 1,465 / 98 / 15 | −0.77 [−1.30, −0.29] | [−1.56, −0.07] ✓ | −0.64 [−1.11, −0.20] | −3.95 [−28.32, +20.88] (93) |
| nhl·regular·prop | **PASS (outcome unmeasured)** | 17,889 / 98 / 15 | −17.44 [−19.15, −15.77] | [−19.82, −14.88] ✓ | −0.87 [−1.52, −0.22] | — |
| soccer·regular·game | **PASS** | 8,606 / 268 / 14 | −3.12 [−5.13, −1.23] | [−6.06, −0.42] ✓ | −0.94 [−2.93, +0.91] | +17.83 [−5.01, +40.76] (267) |
| nfl·regular·game | UNDERPOWERED | 1,805 / 27 / 7 | −0.03 [−0.41, +0.33] | — | +0.12 [−0.31, +0.55] | +8.54 [−36.85, +55.15] (27) |
| nfl·regular·prop | UNDERPOWERED | 7,001 / 27 / 7 | −0.11 [−0.74, +0.59] | — | +0.48 [−0.26, +1.48] | — |
| mlb·postseason·game | UNDERPOWERED | 308 / 2 / 2 | −0.83 | — | −0.79 | +9.28 (2) |
| mlb·postseason·prop | UNDERPOWERED | 813 / 2 / 2 | −0.99 | — | −0.99 | — |
| nba·regular·game | UNDERPOWERED | 599 / 1 / 1 | +1.75 | — | +1.74 | (1) |
| nba·regular·prop | UNDERPOWERED | 328 / 1 / 1 | −8.24 | — | −7.74 | — |
| wnba·postseason·game | UNDERPOWERED | 0 (never trained: 14 games) | — | — | — | — |
| wnba·postseason·prop | UNDERPOWERED | 0 | — | — | — | — |
| *nba·preseason·game* | *not gated* | 771 / 27 / 5 | −0.01 [−4.24, +3.07] | — | +4.27 [+2.03, +6.51] | +1.47 [−62.5, +71.0] (27) |

Preseason NHL (1 held-out game each kind) is omitted.

## 3. Where the passes come from (breakdowns: reported, never a pass)

**By target source** (10⁻⁵ nats):

| family | sharp-target rows | consensus-target rows |
|---|---|---|
| ncaaf·game | −0.82 [−1.52, −0.16] (2,757) | −0.30 [−0.88, +0.07] (8,288) |
| nhl·game | — | −0.77 [−1.30, −0.29] (1,465) |
| nhl·prop | **−29.64 [−32.36, −26.69]** (11,004) | **+2.06 [+0.88, +3.21]** (6,885) — v1 WORSE |
| soccer·game | −0.53 [−2.72, +1.60] (125) | **−3.15 [−5.20, −1.25]** (8,481) |
| nfl·game | −2.25 [−5.17, +0.70] (113) | +0.12 [−0.19, +0.42] (1,692) |

**By snapshot:** the gains sit **far from the start and vanish at T−30m** in every passing family except NHL props:

| family | T−24h | T−6h | T−2h | T−30m |
|---|---|---|---|---|
| soccer·game | −8.95 [−12.92, −5.10] | −6.34 [−10.50, −2.58] | −1.88 [−4.78, +0.56] | +1.10 [−0.86, +2.69] |
| nhl·game | −2.54 [−4.21, −1.00] | −0.97 [−1.77, −0.22] | +0.19 | +0.16 |
| ncaaf·game | −1.81 [−6.30, +1.07] | −0.69 [−1.26, −0.17] | −0.42 [−0.67, −0.15] | +0.01 [−0.22, +0.22] |
| nhl·prop | −0.66 (161) | −16.45 | −17.61 | −18.62 |
| nfl·prop *(underpowered)* | −2.23 [−4.15, −0.47] | −2.18 [−3.25, −1.16] | +0.24 | **+1.70 [+0.86, +2.76]** |

**By market family:**
- NCAAF's gain is spreads −1.00 [−1.68, −0.36] and totals −0.59 [−1.01, −0.19]. Alts and segments are flat (−0.01).
- NHL game's gain is spreads −2.35 [−3.59, −1.12].
- Soccer's gain is `game_other`, mostly alternate corner totals: −4.92 [−8.16, −2.03]. Its h2h/spreads/totals are not separable from 0.

**What this means:**
- **NHL props:** the pass is Pinnacle predicting its own close (weight 4.5–8× an equal vote, below). Against the soft consensus close the learned weights are worse than the median. **Treat the NHL-prop pass as mechanical.**
- **NCAAF:** most of the gain is on the sharp rows, so it is also largely mechanical.
- **NHL game:** the equal-weight pool alone gets −0.64 of v1's −0.77. Most of that gain is the pooling form (a logit mean beats a median), not learned sharpness.
- **Soccer:** the only family where learned weights beat both the median and the equal pool against a target they are not part of. Even there the outcome read is +17.8 [−5.0, +40.8], the wrong direction and not significant. Until 10-25 soccer had no sharp book, and the "close" was a soft-book consensus that DraftKings appears to lead (§5). Leading the soft close is not shown to be leading the truth.

## 4. σ_fair calibration (held-out closes)

| family | scored | inside ±1σ (nominal 0.683) | inside ±2σ (0.954) | median σ (logit / pp) | calibrated [0.60, 0.76] |
|---|---|---|---|---|---|
| ncaaf·game | 11,045 | 0.717 | 0.916 | 0.031 / 0.75 pp | yes |
| nhl·game | 1,465 | 0.735 | 0.927 | 0.035 / 0.83 pp | yes |
| nhl·prop | 17,889 | 0.772 | 0.940 | 0.046 / 1.05 pp | **no (too wide)** |
| soccer·game | 12,108 | 0.700 | 0.899 | 0.059 / 1.22 pp | yes |
| ncaaf·prop | 4,482 | 0.863 | 0.955 | 0.022 / 0.55 pp | no (too wide) |
| nfl·game | 1,805 | 0.736 | 0.916 | 0.024 / 0.59 pp | yes |
| nfl·prop | 7,001 | 0.768 | 0.939 | 0.033 / 0.82 pp | no (too wide) |

- **±1σ is about right in the game families. ±2σ is short everywhere (0.90–0.94):** the residual to the close is heavier-tailed than a Gaussian.
- σ is 0.6–1.2 pp at the median. That is the scale at which an edge should be shrunk.
- **The fitted residual by snapshot** (√r², last refit) is the engine-side number:
  - NCAAF spreads close a further 0.06 logit (~1.4 pp) after T−24h but only 0.02 (~0.6 pp) after T−30m.
  - Soccer h2h: 0.14 → 0.035 logit.
  - NHL props: 0.12 → 0.01.

## 5. Engine read — which books lead the close, and by how much

β = Σxy/Σx² on two-way rows (pre-registration §9). x = a book's logit gap to the Shin consensus at the snapshot; y = the consensus's move to the close. β = 1: the close moves all the way to that book. β = 0: its disagreement is noise. In-sample, game-clustered 95% CIs, cells with ≥ 200 rows. **Against the CONSENSUS close**, the non-mechanical read:

- **Soccer:**
  - **DraftKings leads:** β 0.55 [0.40, 0.72] at T−24h, 0.48 [0.33, 0.61] at T−6h, 0.27 [0.16, 0.40] at T−2h, 0.16 [0.08, 0.25] at T−30m, on gaps of ~1.25 pp.
  - **Bovada:** 1.11 [0.42, 1.83] at T−24h (n = 205), 0.28 at T−6h.
  - **FanDuel, BetRivers, Polymarket and Ballybet carry ~0 information** (β ≈ 0 on gaps of 0.5–2 pp). They are the books the fit down-weights.
- **NFL game:** Bovada 0.45 [0.28, 0.59] at T−6h, 0.21 at T−2h. FanDuel 0.13. DraftKings ~0.
- **NHL game:**
  - BetOnline / LowVig (one feed: identical β) 0.46 [0.07, 0.86] at T−24h.
  - BetMGM 0.32 [0.15, 0.46] at T−24h.
  - Bovada 0.31 [0.19, 0.45] at T−6h.
  - BetRivers and William Hill ≤ 0.
- **NHL props:** Pinnacle leads even the soft consensus: 0.18 [0.15, 0.22] at T−6h, 0.13 at T−2h, 0.09 at T−30m. FanDuel and BetOnline 0.15–0.20 at T−6h. DraftKings, Hard Rock and ESPN Bet are ~0 or slightly negative.
- **NCAAF game:**
  - Matchbook 0.28 [0.17, 0.38] at T−6h.
  - Novig 0.38 [0.21, 0.55] at T−24h.
  - Betfair 0.37 at T−6h.
  - **Pinnacle only 0.09 [−0.05, 0.22] at T−6h against the consensus close.**

**Against the SHARP target** (mechanical where Pinnacle is the target):
- **NCAAF:** Pinnacle 0.42 / 0.56 / 0.73 at T−6h / T−2h / T−30m; Matchbook 0.33 / 0.30 / 0.27.
- **NHL props:** Pinnacle 0.81–0.96.

The NCAAF exchanges (Matchbook, Novig, Betfair) lead both closes, so that part is not mechanical.

**Fitted weights** (last refit, relative to an equal vote = 1.0, at quote age < 15 min):

- **NHL props:** Pinnacle **4.5× at T−24h, 6.4× T−6h, 7.6× T−2h, 8.1× T−30m**. Every other book is 0.6–1.0. BetMGM and Hard Rock are lowest.
- **NCAAF game:** Pinnacle 1.13–1.26 (highest on spreads and totals near the start). Matchbook 1.11–1.17, Bovada 1.09–1.19. ProphetX 0.69–0.87 is lowest; Polymarket is 0.83–0.91.
- **Soccer game:** DraftKings 1.17–1.95 (highest at T−24h / T−6h). Bovada 1.15–1.24. Polymarket 0.53–0.83 is lowest; FanDuel and BetRivers are 0.74–0.87.
- **NHL game:** Bovada 1.16–1.26, BetMGM up to 1.40 (spreads, T−24h). BetRivers 0.72–0.89 and William Hill 0.81–0.90 are lowest.
- **Quote-age terms:** within ±0.12 log-weight everywhere. Staleness did not earn a separate weight, which matches H5's 10-16 finding that an unchanged price is still the price.

## 6. Post-hoc diagnostics (NOT pre-registered; no verdict changes)

This is the same code with the same rows, re-run by a scratch script. The registered arm reproduces the report exactly (NCAAF Δ −4.29086e−6 both times), so the run is deterministic. Per-row arrays are kept at `C:\tmp\sfv1\diag\*.npz` on the host (not in git).

**(a) Effect size in fair-price terms, registered v1, held-out rows with a close target.** KL is in 10⁻⁵ nats; pp is the mean absolute distance on outcome 0, or half the L1 distance for a 1X2.

| family | KL(close‖Shin) | KL(close‖v1) | KL removed | \|Shin − close\| pp | \|v1 − close\| pp | \|v1 − Shin\| pp (p95) |
|---|---|---|---|---|---|---|
| ncaaf·game | 17.76 | 17.33 | **2.4%** | 0.560 | **0.594** | 0.150 (0.48) |
| nhl·game | 29.20 | 28.42 | **2.6%** | 0.754 | **0.770** | 0.147 (0.41) |
| soccer·game | 80.19 | 77.07 | **3.9%** | 1.177 | **1.206** | 0.297 (0.99) |
| nhl·prop *(mechanical)* | 45.70 | 28.26 | 38.2% | 1.007 | 0.763 | 0.522 (1.77) |
| ncaaf·prop | 14.33 | 14.60 | −1.9% | 0.307 | 0.354 | 0.096 (0.46) |
| nfl·game | 10.78 | 10.75 | 0.3% | 0.409 | 0.472 | 0.168 (0.51) |
| nfl·prop | 24.96 | 24.85 | 0.4% | 0.544 | 0.610 | 0.204 (0.69) |

- **Log loss and absolute error disagree.** In every non-mechanical passing family, v1 has LOWER KL to the close but a LARGER mean absolute distance from it. The logit mean wins in the tails (confident lines, 1X2 draws), where log loss is most sensitive. The median is the more robust estimate in the middle.
- **EV is linear in p**, so for pricing, absolute error is the measure that matters. On this evidence **v1's p_fair should not replace Shin's in any EV**, even in a family that passes on log loss.
- Stage 2 should report |fair − close| beside the gate (reported, not gated).

**(b) EXPLORATORY: the λ grid extended down to 1e−8** (amendment A1's arm B, run here on stage-1 data):

| family | Δ close [CI], registered | Δ close [CI], λ ≤ 1e−5 | consensus-target rows, registered | λ ≤ 1e−5 | Δ outcome, λ ≤ 1e−5 |
|---|---|---|---|---|---|
| ncaaf·game | −0.43 [−0.90, −0.08] | −0.26 [−0.99, +0.93] | −0.30 [−0.88, +0.07] | +0.73 [−0.11, +2.22] | +10.61 [−18.5, +38.6] |
| nhl·game | −0.77 [−1.30, −0.29] | −0.67 [−1.42, +0.03] | (same rows) | | −2.55 [−34.2, +30.3] |
| soccer·game | −3.12 [−5.13, −1.23] | −3.05 [−5.06, −1.09] | −3.15 [−5.20, −1.25] | −3.09 [−5.23, −1.17] | +11.61 [−18.5, +40.2] |
| nhl·prop | −17.44 [−19.15, −15.77] | −18.90 [−20.83, −17.02] | **+2.06 [+0.88, +3.21]** | **+3.22 [+2.03, +4.42]** | — |
| nfl·game | −0.03 [−0.41, +0.33] | −0.02 [−0.38, +0.36] | | | |

**A looser ridge does not find hidden signal.** Inner validation does pick 1e−6 to 1e−8 when allowed, but the held-out
result is no better anywhere non-mechanical.
- What grows is the mechanical Pinnacle weight: NCAAF Pinnacle 3–10× an equal vote, NHL props 25–176×.
- NHL props get worse against the consensus close.
- NFL's weights blow up on 27 games (BetUS 43× on T−6h h2h, Bovada 31× on T−6h spreads): overfitting.

**The near-equal weights at stage 1 were the data's answer, not only the ridge's.** Arm B stays registered for stage 2 (A1), and this read predicts it will not beat arm A.

## 7. Recommendation

1. **Shadow-wire, as the registered rule says, scoped to the 4 passing families.** In the DecisionRecord, write `σ_fair_v1` (the useful part), `p_fair_v1` and `fair_v1_basis` beside the Shin fair:
   - NCAAF game, NHL game and soccer game with σ marked calibrated;
   - NHL props with σ **flagged uncalibrated** (1σ coverage 0.772, too wide);
   - every other family keeps only the Shin fair.
   - **±2σ is short everywhere** (0.90–0.94 vs 0.954). Any lower-bound EV built on σ should use a heavier tail, or a ×1.2–1.3 multiplier at 95%, until stage 2 re-reads it.
   - **Owner:** `decision-record-shadow` (`decision_record.py` is theirs). This lane does not edit it.
   - **What it buys:** a per-line σ for Phase 2's lower-bound EV, plus decision-time pairing for E1, at no risk.
   - **What it does not buy:** the stage-2 read, which is offline.
2. **Do not use `p_fair_v1` for any price, Suggested flag, EV or stake on this evidence.**
   - The non-mechanical gains are 10⁻⁵ nats per row.
   - The fair moves ~0.15–0.30 pp from Shin and lands slightly further from the close in absolute pp.
   - The outcome reads are all within noise, and soccer's leans the wrong way.
   - The Phase-2 edge gate governs money either way.
3. **The real read is stage 2, on or after 2026-11-24** (kickoffs 10-26 08:00Z .. 11-23 08:00Z). It has:
   - Pinnacle on NBA / NFL / soccer game lines for the first time;
   - the first NBA regular-season test;
   - amendment A1's lower-λ arm beside the registered arm.
4. **Engine owners, from §5:**
   - Pinnacle is the only book that leads NHL prop closes by a wide margin.
   - DraftKings leads the soccer consensus.
   - Bovada leads the NFL / NHL consensus at T−6h.
   - The NCAAF exchanges (Matchbook, Novig, Betfair) lead both closes.
   - FanDuel, BetRivers and Polymarket deviations are noise in soccer.

   A sharp-anchored fair should come from **Pinnacle where it quotes**, and the exchanges where it does not. The soft books' consensus adds little.

## 8. Found along the way

- **`"line": NaN` in the quote change log** on NBA / WNBA / NHL h2h and yes/no rows: NaN ≠ NaN, so every quote row became its own line (667,804 NHL h2h "lines" for 179 events). Fixed in this lane's code. `scripts/fair_price_eval.py::group_key` (lane `fair-price-v2`) has the same shape: `_f` returns nan and `round(nan)` stays nan. It may silently drop NHL h2h quote joins in the H5/Shin evaluations. **Recorded as a lead for `fair-price-v2`; not edited and not verified there.**
- **Soccer chips** for recent dates are mostly `pregame` (10-24: 252 of 351 soccer chips), presumably leagues the scoreboard never settles. Only 9 of our soccer graded lines lacked a final, so it did not bite here.

## 9. Owed

- **Stage-2 read on or after 2026-11-24** (both arms), with the same code (`d1ff922d`) and constants. Registered in the pre-registration §11 + A1. Listed in todo `#737`. Report beside the gate (not gated): |fair − close| in pp, and σ's ±2σ coverage.
  - The stage-2 run needs a `--start/--end` window on `fit`'s TEST dates.
  - Today `fit` scores every date that has training, so the stage-1 window must be excluded from the read: filter the report's rows to commence ≥ 10-26 08:00Z, or add the flag in a reviewed commit that leaves the scored logic unchanged.
- **The shadow-wiring decision** (§7.1) is for the program session / `decision-record-shadow`.
