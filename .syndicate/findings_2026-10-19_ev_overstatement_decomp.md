# Why claimed EV above ~4% under-delivers: the EV stamp holds at the close; the sim's stake does not

Lane `ev-overstatement-decomp`, session 24ac7737, 2026-10-19. Asked by the session behind lane
`min-ev-tuner-shadow` (`findings_2026-10-19_min_ev_tuner_backtest.md`): name the component that inflates
claimed EV above ~4% and propose an engine or EV-stamp fix, not a threshold.

**Answer, short.** No component of the market EV stamp (`ev_pct`) is shown to inflate EV above 4%.

- **At the close:** against the closing consensus fair the stamp keeps its band order, with a uniform
  ~1.3-point decay in every band. Every fair-quality component tested is flat.
- **In the tuner's numbers:** the band-shaped loss in its stake-weighted ROI is mostly **the sim's added
  stake**. From 10-05 the sizer stakes the raw sim probability (`fair + model_edge_pct/100`) at full weight,
  because no staked-probability profile exists on the fleet. That stake is 58–69% of the dollars in each band
  and returns −11.2 / −17.5% at [4,5) / [5,7).
- **The sim adds variance, not a bias:** pooled over EV ≥ 2, its dollars are no worse than the EV-only ones
  (−2.9 vs −3.2). It amplifies whatever the band's outcome noise is.
- **What the stake has not earned:** the sim's fitted weight on these same orders is **w = −0.27 [−0.78,
  +0.18]**, against the 1.0 the sizer applies.
- **The engine component** is the **staked probability**, the EV the stake implicitly claims. The fix is a
  sizing seam, not a cut line.
- **The flat-unit anti-correlation** itself is ~1–1.5σ on this sample.

## Data: what this rests on (substrate: the local fleet, read-only)

- `execution_ledger.full_history_orders()` read 2026-10-19 ~18:50Z inside WSL (worker keyvalue state,
  `~/Syndicate` at `71631544`): 10,414 rows. **Settled won/lost with `ev_pct`: 8,546** (52 pushes excluded),
  **428 events, 17 selected dates 10-02..10-18**, all PAPER: `paper` 4,017 / `paper:prophetx` 2,030 /
  `paper:novig` 1,323 / `paper:kalshi` 769 / `paper:polymarket` 407. The 552 live venue rows carry no
  `ev_pct` and are not in this population.
- **The same bet appears in several venue books** (4,730 distinct opening keys under 8,598 orders). Every ±
  below is one event-clustered standard error, so the duplication does not shrink the errors.
- Openings: each order's `clv_openings` record, matched by `opening_key`. 4,310 of 4,730 keys found. The
  files for 10-04, 10-10, 10-11, 10-17 and 10-18 sit at the 32 MiB tripwire, so they are TRUNCATED. Only
  **2,952 orders match their opening exactly** (same price, |Δev| < 0.05); most orders went in at a later
  price than the first sighting.
- Book quotes: every book's price on both sides, at submit and at kickoff, rebuilt from
  `<sport>_source/tracking/book_quotes` for the **7,230 pregame two-sided orders**. 5,419 have a two-sided
  close fair. A book whose last quote on the market was at ANOTHER line is dropped (it moved off the number).
  The rebuilt submit fair matches the stamped one at a median |Δ| of 0.39 pp, with a mean of −0.78 pp
  (multiplicative here vs shin on the board from 10-14).
- Reproduce: `scripts/ev_overstatement_decomp.py` (`dump` / `openings` / `quotes` on the fleet at nice 19,
  then `report`).

## Two sizing regimes, never pooled silently

Sim share of paper dollars by submit date: 10-02..10-04 **0.00** (sizing gate), 10-05 0.35, **10-06..10-13
0.71–0.83**, 10-14..10-17 0.52–0.62, 10-18 0.27. The un-gating is lane `stop-market-withholding` (10-05).
The sizer then falls through to `portfolio_commit.py:761`, `raw_model = fair + model_edge_pct/100`. Only a
β>0 cell in the staked-probability profile replaces it (`:773-780`). **The fleet has no profile**:
`<data root>/calibration/` does not exist, no `staked_probability_profile*.json` exists anywhere under
`~/syndicate-prod`, and the refresh-worker's environment sets no path override. So every cell is
"unfitted", and `staked_probability_profile.py` documents that case as "raw model, bit for bit". The module
names this as a known gap: a cell whose best β is 0 is "REPORTED and NOT WRITTEN".

## Finding 1: the EV stamp keeps its band order at the close (the market side)

Pregame orders, EV of the SAME fill price measured against the rebuilt closing consensus fair:

| claimed band | orders / events | claimed EV | EV at close fair | on line-stable rows (EV at close) |
|---|---|---|---|---|
| [2,3) | 1,272 / 256 | 2.43 | +1.49 ± 0.21 | 671 / 190: +1.27 ± 0.32 |
| [3,4) | 1,198 / 261 | 3.48 | +3.19 ± 0.54 | 485 / 153: +2.27 ± 0.52 |
| [4,5) | 1,299 / 248 | 4.40 | +4.11 ± 0.53 | 445 / 131: +3.78 ± 0.45 |
| [5,7) | 340 / 126 | 5.09 | +4.84 ± 1.35 | 103 / 51: +3.69 ± 0.63 |

Stake-weighted it is the same: ≥4% claims 4.54 and gets +3.17 at the close, 2–4% claims 2.96 and gets +1.66.
That is a ~1.3-point decay in BOTH. **The higher bands still carry more EV at the close.** Same-book CLV
being flat (the brief's evidence) measures the taken venue's own price movement, not the fair. It is
consistent with this.

Outcomes against that close fair (pregame, flat): hit − close consensus at ≥4% **−2.0 ± 2.2 pp** (1,639
orders / 264 events), at 2–4% +2.1 ± 2.1 pp. The difference is ~1.4σ. Line-stable rows only: [4,5) −3.3 ±
3.7, [5,7) +3.5 ± 5.4.

## Finding 2: the pre-registered "thin / noisy fair" hypothesis is FALSIFIED

Registered in the lane before any decomposition: high-EV rows rest on fewer books, a one-sided or venue-own
fair, or an off-consensus venue quote. Measured on the 2,952 exact-match orders (opening fields = order
state), EV ≥ 2:

- **Books quoting**: 1–2 books ROI−EV **+3.0 ± 6.2** (1,162 / 211 events), 3–4 −8.0 ± 7.2, 5–7 −0.7 ± 8.7,
  8+ −3.3 ± 8.1. The thinnest fairs are not the worst.
- **Fair method**: consensus/multiplicative +0.1 ± 5.3, consensus/shin −6.8 ± 7.4, sharp_anchor/pinnacle
  +3.8 ± 9.7. No ordering. book_margin_model (8) and two_sided_same_book (3) are too few to read.
- **Venue's own two-sided fair vs consensus** (log loss on outcomes, 7,230 pregame): no band separates; every
  difference is within 1σ. The fitted weight on the venue's own fair is +0.45 [−0.35, +1.35], and on the
  exchange median +0.25 [−1.00, +1.50].
- **Price drift since first sighting** (same / longer / shorter): no consistent sign by band.
- **Outlier gap** (taken price vs the median of the other books): gap 4–6 pp is worse at ≥4% (−12.1 ± 7.8),
  but gap 6+ is BETTER (+16.7 ± 8.8 overall). It is not monotone, so it is not a component.
- **Exact 0.500 fairs** (−110/−110 herds against an exchange at +104..+110, 1,661 orders): not worse than the
  rest ([4,5) ROI −1.8 vs −5.9).
- **Fair-noise discount** (5/√books, from 10-06; model-backed rows are exempt): the would-be-refused rows
  are not the losers either (submitted from 10-07, model-backed: effEV<2 flat −2.3 ± 5.0 on 2,816 orders,
  effEV≥2 −0.7 ± 7.6 on 817).

## Finding 3: the band-shaped loss is the sim's added dollars (the engine component)

Every order carries `sim_share_of_stake`, the exact counterfactual "this row with `model_edge_pct = 0`"
(`stake_attribution`). PnL is linear in stake, so each order's dollars split into EV-only and sim-added
parts:

| band | stake ROI, all $ | EV-only $ ROI | sim-added $ ROI | sim-added $ |
|---|---|---|---|---|
| [<2) | −14.9 ± 7.9 | −10.8 ± 8.0 | **−16.0 ± 8.4** | 11,974 |
| [2,3) | +0.4 ± 6.5 | −0.4 ± 5.4 | +0.8 ± 7.8 | 12,088 |
| [3,4) | +2.1 ± 5.9 | −0.7 ± 4.7 | +3.8 ± 7.7 | 10,515 |
| [4,5) | **−8.3 ± 6.2** | −4.2 ± 4.4 | **−11.2 ± 8.8** | 11,790 |
| [5,7) | **−9.8 ± 8.7** | −4.0 ± 6.8 | **−17.5 ± 15.1** | 2,145 |

(The all-$ column reproduces the tuner's −8.3 / −9.8.) In the sim-sizing regime (10-05..10-18) at ≥4%:
sim-added $ **−12.2 ± 8.4** vs EV-only $ −3.3 ± 4.3. Flat-unit hit − close consensus there is −0.6 ± 2.6,
so the market EV of those bets was close to right, and the stake on top of it was not.

**The sim has no weight to earn that stake.** Log-loss-optimal w in `p = fair + w·model_edge`, event
bootstrap (400 draws):

| population | orders / events | mean model edge | w (sizer applies 1.0) |
|---|---|---|---|
| EV ≥ 2 | 4,876 / 403 | +6.1 pp | **−0.27 [−0.78, +0.18]** |
| EV 2–4 | 2,846 / 357 | +6.3 pp | −0.12 [−0.65, +0.40] |
| EV ≥ 4 | 2,030 / 297 | +5.9 pp | −0.50 [−1.00, +0.08] |

This agrees with lane `sim-gap-ev-study` (w ≈ 0 for nfl / ncaaf / nhl / mlb pregame on 84,344 bets;
"the sim agreeing does not make a bet better"). By sim view at EV ≥ 4%: **agrees** −8.4 ± 6.0 flat
(1,725 orders / 275 events, 85% of the band's dollars); **unpriced** +1.8 ± 6.2, with **no** anti-correlation
across bands (2–4% −1.6, ≥4% +1.8).

**Why it shows up as "high EV loses", and what is and is not established.** The sim adds ~60–80% of the
dollars wherever it agrees, and its edge averages +6 to +8 pp regardless of band. A stake priced at
`fair + 0.077` claims an EV near `ev_pct + 16` points.

- **Pooled over all EV ≥ 2 from 10-05, the sim's dollars are NOT worse than the EV-only dollars.** They
  return −2.9 ± 5.9 on $38,997 against −3.2 ± 4.6 on $13,260 (paired +0.3 ± 4.3; 4,189 orders / 332
  events). Its stake is **unearned rather than biased**. It multiplies each band's outcome noise by ~2–3×
  for no measured mean gain, which is over-betting in Kelly terms.
- On this sample that noise landed hardest on [4,5) and [5,7). The band ordering of the sim's dollars
  (+0.8 / +3.8 / −11.2 / −17.5) is NOT significant (2–4% vs ≥4% ≈ 1.35σ).
- **Established:** the sim's weight is far below the 1.0 it is staked at. The CI excludes 1 by a wide margin,
  and it excludes 0.5 at EV ≥ 2 (w = −0.27 [−0.78, +0.18]; from 10-05 alone −0.30 [−0.88, +0.23]).
- **Therefore** the honest form of the original question is: claimed EV above 4% is not shown to be
  overstated by any component of the EV stamp. The tuner's stake-weighted band shape is mostly
  sim-amplified noise. The anti-correlation itself is ~1–1.5σ in flat units here, and stays a STANDING
  pattern (learnings 2026-09-29) to keep measuring, not a mechanism this sample proves.

## What is left unattributed (stated, not explained)

- **The 3 gated days, 10-02..10-04** (one NCAAF/NFL weekend, ~100 events, sim share 0): market-only EV fell
  short at 3–5% (hit − close consensus [3,4) −11.0 ± 4.3, [4,5) −8.2 ± 3.7). 10-05..10-13 used the same
  devig (multiplicative) without the shortfall, so it is not the devig method. One slate; no component found.
- **The uniform ~1.3-point decay** of claimed EV to the closing consensus is in every band. That is a lead
  for the fair (the market drifts ~0.6 pp against the taken side by kickoff). It is not this question.

## Proposed change (lane `sim-stake-unfitted-market-only`)

**An unfitted staked-probability cell sizes on the MARKET fair (β = 0), not on the raw sim (β ≈ 1).** The sim
re-enters a cell only through a β > 0 that `scripts/fit_staked_probability.py` fits and that beats
market-only on a chronological hold-out. "Fitted, best β = 0" becomes a written cell (`market_only`), not an
absent one. A row whose staked probability is then the market fair takes the same fair-noise treatment as any
market-only row.

- **Not a threshold, not an exclusion.** Every line still stakes on its own EV. Nothing is refused that is
  admitted today. Only the multiplier the sim adds without measured skill goes away.
- **It is the user's 2026-09-19 principle** ("only a model measured to beat the market sizes money") applied
  at the stake, not as a market-level withhold. The 10-05 PRIME DIRECTIVE removed the withhold, and with it
  the stake gate.
- **Global sizing change**, so default-OFF behind a flag, and a user decision before it is switched on. It
  needs `portfolio_commit.py` on loan from lane `published-negative-ev`.

**Engine read** (`feedback_sim_improvement_is_the_secret_sauce`): the sims priced against these orders carry
no information beyond the market at the stake level (w ≈ 0, CI excluding 0.5). The improvement path is the
sims' own calibration, for example the fixed-rating football pricers with no rating uncertainty
(`findings_2026-10-15_sim_gap_ev_study.md`, handed to `football-scenario-calibration`). Until a cell's sim
measures w > 0, its stake contribution should be zero. Staking it at 1.0 turns engine noise into
stake-weighted losses that read like an EV problem.

**For lane `min-ev-tuner-shadow`:** its stake-weighted ROI evidence is ~60–80% sim dollars after 10-05.
Grading the min_ev cut on EV-only dollars (or flat units) would keep the sim's sizing out of the
threshold's evidence. That is a suggestion to that lane's owner; this lane changes nothing there.

## Process notes

- The first `w` bootstrap was pure Python at normal priority. It was stopped and re-run vectorised. A
  research job on this host belongs at Idle priority (`feedback_research_jobs_idle_priority`).
- Near-miss on learnings 2026-10-09 FORBIDDEN: the refresh-worker's environment was read with
  `tr '\0' '\n' < /proc/<pid>/environ | grep -o "^SYNDICATE_..."`. The grep was anchored to five
  `SYNDICATE_*` names, so the only output was the data-root path, but the rule forbids line-splitting environ
  in a shell pipeline at all. Read it in Python next time.
