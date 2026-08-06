# MLB conditional-edge scan — PRE-REGISTRATION

**Written 2026-08-05, BEFORE any segment numbers were computed.** Committed
deliberately so the pass/fail rules cannot be adjusted after seeing results.
If a rule below is changed later, the change must be a separate commit with a
stated reason, dated after the results were seen, and any result it rescues is
downgraded to exploratory.

## Why this exists

Everything measured in #186–#201 asked a **marginal** question: does the model
beat the market *on average, across all rows*? Answer: no, in every market.

That is the wrong question for finding an edge. A model can be net-zero overall
and still be systematically right in a subset. The **conditional** question —
where within a market are we right? — is what this scan answers.

**The danger is precisely quantified.** Slicing ~15 dimensions × ~4 buckets is
~60 tests; at p<0.05 roughly 3 will look like edges by pure chance. This session
already produced two such artifacts (a +51.9% moneyline from a bad join, and a
1.85× HR lift that fell to 1.59× on more data). Both looked real. The rules
below exist because my own judgement after seeing a number has repeatedly been
wrong today.

Corroborating evidence that feature engineering is not the answer: the most
sophisticated competitor sheet found (Worst Pickz — six weighted components,
BvP, zone-fit, damage windows, park/weather) publishes its own last-7-days
record as **1W–4L and 0W–4L**. They already have the features.

## Data basis

- **48 dates** (2026-06-04 … 08-05) for anything needing rosters
- **66 dates** (2026-05-28 … 08-05) for market/sim-only work
- Predictions + odds: Render artifacts. Outcomes: StatsAPI, validated 30/30.
- Accessor: `season_data.py` (`usable(*families)` — always report date count)

**Known limitation, stated up front:** 48 dates ÷ 4 buckets ≈ 12 dates/cell.
That is thin. Widening to Render's full sim history (2026-04-10 onward, ~76
dates) roughly halves per-cell noise and should happen before any result here
is treated as decided.

## Phase 1 — pre-registered hypotheses (mechanism required)

Each has a stated mechanism and a **directional prediction**. A result in the
wrong direction is a failure, not a discovery.

| # | market | slice | mechanism | prediction |
|---|---|---|---|---|
| H1 | K props | pitcher season K-rate tier (quartiles) | #187/2026-07-31 found the sim structurally underprojects top-end K-rate | edge concentrated in the TOP quartile, OVER side |
| H2 | K props | opposing lineup avg K-rate (quartiles) | lineup K-rate is a model input; if the sim underweights it, error correlates | monotone in lineup K-rate |
| H3 | K props | market line height (≤4.5 / 5.5 / 6.5 / ≥7.5) | high lines imply workhorse starters, where the sim's pull-logic matters most | edge at high lines |
| H4 | HR | park HR multiplier (extremes vs neutral) | park is a multiplier the sim applies directly; extremes are where mis-scaling shows | edge at extreme parks, either direction |
| H5 | HR | platoon-edge magnitude | platoon mult is a direct model input | edge at large platoon edges |
| H6 | HR | pitch-mix fit strength (`mix_hr_score`) | this feature was DEAD until today (#198); never before tested | edge where mix score deviates from 1.0 |
| H7 | game | favourite vs underdog | sim is overconfident on favourites (#201, 0.65+ bucket 69.0% → 52.9%) | edge betting AGAINST sim favourites |
| H8 | first1 / NRFI | ungraded market, whole-market test first | sim emits `first1`; market in feed at 6.23% hold | none — this is a first look |

## Phase 1 — pass/fail rules (fixed now)

A slice is a **CANDIDATE** only if it clears **all** of:

1. **Size**: ≥ 60 bets in the cell on the full sample. Smaller cells are
   reported but never called an edge.
2. **Both halves positive**: split the dates chronologically 50/50. ROI must be
   > 0 in **both** halves independently. (This is what killed the moneyline:
   +11.4% then +3.6%, decaying.)
3. **Fragility**: dropping the top 5 winning bets must leave ROI > 0.
   (This is what actually killed the moneyline: 5 of 358 bets erased it.)
4. **Bootstrap**: 2,000-resample 95% CI on full-sample ROI must exclude zero.
5. **Direction**: matches the pre-registered prediction above.
6. **Monotonicity**: where the mechanism implies ordering (H1, H2, H3), adjacent
   buckets must trend rather than spiking in one cell.

**Reporting requirement**: state the total number of tests run and how many
candidates survived. If survivors ≈ what chance predicts (~5% of tests), the
honest conclusion is "no edge found," regardless of how good any single cell
looks.

**Nothing from Phase 1 gets shipped to the board.** A surviving candidate earns
one thing: a forward-looking paper-trade log, graded on new dates it was not
discovered on.

## Phase 2 — evaluate every stat (the fuller sweep)

Once Phase 1 is executed, sweep every available feature for conditional edge:
all `hr_dataset_v2` columns, all pitcher/batter profile fields, Statcast
families (2025 leak-free and 2026), park/weather, lineup slot, BvP from the
`statcast_bvp` cache, plus rest/workload.

**Phase 2 rules differ, because the test count explodes** (hundreds, not ~60):

- **FDR control**, not per-test thresholds: Benjamini-Hochberg at q=0.10 over
  the full family of tests. Per-test p-values are meaningless at this scale.
- **Holdout is mandatory, not confirmatory**: discover on the first half only;
  the second half is touched **once**, at the end, for surviving candidates.
- **Mechanism required before promotion**: a surviving slice with no plausible
  causal story is logged as unexplained, not acted on. Pure data-mined edges in
  a 48-date sample are the most likely thing here to be noise.
- Report the full distribution of results, not just survivors — if the survivor
  count matches the FDR expectation, that IS the finding.

## Order of execution

1. **H8 (NRFI/first1)** — a whole market never graded, two competitor sheets
   built entirely on it, and we hold both sides of the data.
2. **H1–H3 (K)** — the only slices with a pre-existing mechanistic finding
   behind them rather than a fishing expedition.
3. **H4–H6 (HR)** — H6 especially, since `mix_hr_score` was dead until #198 and
   has genuinely never been tested.
4. **H7 (game)** — cheapest market (4.53%), but #201 showed the favourite effect
   is mostly noise on n=34, so expectations are low.
5. **Phase 2** — only after Phase 1, and only with FDR control.

## Prior

Stated now so it cannot be revised afterward: **the most likely outcome is that
no slice survives all six rules.** Every market in #195's hold map requires
beating 52.3–54.2% just to break even, the model beats the sim but not the
price everywhere tested, and the most sophisticated competitor observed is
publicly losing. A null result here is the expected result and should be
reported as a real finding, not as a failed search.
