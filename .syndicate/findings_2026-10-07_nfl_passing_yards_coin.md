# Why production's NFL passing-yards prop probability is worse than a coin — lane `nfl-passing-yards-prop-coin`

2026-10-07, session f628c245. Measurement only: no production code changed, nothing deployed.
Trigger: `findings_2026-10-07_football_player_attribution.md` "NFL Phase C" — production passing yards LL 0.869
on 2025 (coin 0.693), slope -0.20; FIT 2023-24 LL 0.787.

**Substrate:** `checkout` — the primary tree's untracked `data/nfl_source` (nflverse pbp 2022-25, OddsAPI historical
`tracking/book_quotes`, kickoff -10 min). This is evidence about the CODE's probability on historical inputs, never
about what the fleet served. Rows: `scripts/diagnose_nfl_passing_yards_prop.py build`, same control flow as
`backtest_football_attribution_props.build_rows` and reproducing its counts exactly (FIT 10,297 passing-yards +
4,059 attempts rows over 359/354 games; 2025 3,195 + 2,739 over 224/223 games) and its production LL (0.7872 FIT,
0.8688 2025). Caches: `C:\tmp\football_scenarios\passing_yards_coin\` (`rows_*.jsonl`, `report_*.json`).
**2025 was re-read here a SECOND time** (diagnostic only; every candidate below was defined and measured on FIT
first, and nothing was selected on 2025).

## Verdict

**Cause #1 — QB identity / as-of log (DOMINANT).** `player_rate` averages EVERY game a passer has a play in.
A QB quoted for a START whose log is mostly relief, mop-up or injury-exit appearances (mean 59-73 passing yards per
partial game) gets a mean far below the line and P(over) ~0.07 — and he goes over ~51% of the time.

| | FIT 2023-24 | 2025 |
|---|---|---|
| rows / excess LL over coin (sum) | 10,297 / 969 | 3,195 / 561 |
| rows whose as-of log has a partial game (team dropback share < 0.7) | 2,909 (28%) carry **93%** | 911 (29%) carry **87%** |
| …of which < 2 full starts in the log | 523: LL **1.954**, p 0.071, over 0.507 | 200: LL **2.302**, p 0.062, over 0.505 |
| …of which ≥ 2 starts: production → starts-only rate | 2,386: 0.796 → 0.729 | 711: 0.924 → 0.752 |
| rows with NO partial game in the log | 7,388: LL **0.702** | 2,284: LL **0.726** |
| rows with mean ≥ 20% below the line | 1,496: LL 1.285, p 0.13, over 0.44 (76% have a partial game) | 414: LL 1.816, p 0.12, over 0.61 (90%) |

The < 2-starts rows alone are 5-6% of rows and carry 68% (FIT) / 57% (2025) of the whole excess.

**Cause #2 — the log-normal blend leans UNDER on a symmetric market (small, real).** At mean = line, production
says P(over) < 0.5 (blend weight 0.689 assumes right skew; passing yards' mean/median is 0.987 —
`findings_2026-09-28_nfl_mean_bias.md`): LL 0.700 vs the coin's 0.693 on FIT, 0.7006 on 2025. Mean P(over)
0.42 vs a realised over-rate of 0.505 (FIT) / 0.524 (2025). Turning the blend off ALONE makes production worse
(0.787 → 0.799), because the blend was fitted on top of the biased mean and absorbs part of it — the
"mechanism vs estimator" coupling `model_engine_standard.md` warns about. Fix it only together with cause #1.

**Cause #3 — even repaired, the mean carries ~no information beyond the line.** On the clean rows production is
0.702 / 0.726 — at or worse than a coin. (actual − line) on (mean − line): slope **+0.20 FIT, −0.11 2025**. Best
FIT candidate (starts-only rate + blend off + mean shrunk 75% toward the line) reaches **0.7033** FIT / 0.7357
2025: still not better than a coin, and nowhere near the book (0.665 FIT). No input fix measured here produces an
edge; the information is in the line (as `findings_2026-10-03_nfl_prop_predictive_spread.md` already found for the
other markets).

**Exonerated (FIT, held on 2025):**
- **Spread / Normal tail:** the model's median sd (79.7) matches the realised residual sd of actual − mean (82.8;
  2025 78.7 vs 81.4). Widening helps (×2: 0.787 → 0.749) only by flattening the biased lean, and slopes stay ≤ 0.43.
- **Context multiplier:** p10-p90 0.96-1.04; turning it off is slightly WORSE (0.791 FIT, 0.878 2025).
- **Market/grading convention for passing yards:** production's pbp passing yards equal nflverse official stats on
  561/561 2025 QB-games; over-rate under official grading is identical.
- **Prior-season fallback:** those rows (LL 0.778 FIT) are no worse than the current-season rows (0.789).

## Passing attempts — a separate CONVENTION defect, plus the same identity defect

**Production counts SACKS as passing attempts** (`player_stats._STAT_EXTRACTORS["passing_attempts"]` reads nflverse
`pass_attempt`, which includes sacks): +2.42 attempts per QB-game vs official, exact on only 12% of 561 2025
QB-games (my sack/2pt-free recomputation is exact on 100%). It inflates BOTH the model mean AND every harness's
graded outcome: the attempts over-rate reads 0.607 FIT / 0.584 2025 under production's convention and
**0.492 / 0.467 under official grading** (the book's slope does NOT recover under official grading: 0.98 → 0.56 FIT,
0.43 → 0.46 2025 — the book carries almost no spread on attempts, so its slope is noise). Graded officially: book 0.6931 / 0.6929, production **0.798 / 0.788**. Fixing the convention alone does
not help (official log 0.806 FIT) because the starts/identity defect dominates here too (partial-log rows LL 0.971
FIT / 1.089 2025 vs 0.712 / 0.699 clean). **Every past NFL attempts backtest graded on the inflated count.**

## What production actually publishes

The board takes a model edge only when |model − fair| ≤ 15 points (`_MODEL_EDGE_MAX_POINTS`). Betting production's
side at the DE-VIGGED fair (zero-vig, so this flatters it), game-clustered 95% CI:

| market | season | 3-15 pt edges (what reaches the score) | > 15 pt (capped out) |
|---|---|---|---|
| passing_yards | FIT | n 5,718 (56% of rows), **−10.5% [−18.9, −1.6]** | n 2,677, +1.7% [−11.3, +14.6] |
| passing_yards | 2025 | n 1,707, −6.2% [−18.0, +7.0] | n 932, −10.4% [−28.2, +6.3] |
| passing_attempts | FIT | n 2,075, −0.2% [−10.1, +8.7] | n 1,306, −2.8% |
| passing_attempts | 2025 | n 1,453, +0.9% [−12.7, +14.7] | n 771, +0.5% |

(Attempts ROI is graded on production's sack-inflated outcome; not re-graded officially.)

## Recommendation (needs a user decision — it touches a standing rule)

The standing user directive is "every line is its own decision" (no market-wide pauses; learnings 2026-10-02/06).
Within that rule, the measured defect is PER LINE and so is the fix:

1. **Refuse the model probability for a passing-yards / passing-attempts row whose as-of log has fewer than 2
   full starts** (team dropback share ≥ 0.7). This is an input-quality refusal per line, not a market pause: the
   rows are the 5-6% that carry 57-68% of the loss, and their probability (~0.07 against a ~0.5 outcome) is the
   board's widest wrong edge. Pre-register the threshold on FIT, then wire it in its own lane.
2. **Fix the attempts convention** (exclude `sack == 1` and two-point plays in the extractor AND the grader), then
   re-fit the attempts blend/spread in the same pass.
3. **Rate on full starts only** (≥ 2 starts) and re-fit the passing-yards blend weight on top of it in the same
   pass — never ship the blend change alone (measured: worse).

**Whether to go further and stop publishing NFL passing-yards model EDGES market-wide until this ships is the
user's call against the standing rule.** The evidence for it: the edges that reach the score lost −10.5%
[−18.9, −1.6] at zero vig on FIT, and nothing measured here — fixed or not — beats a coin on log-loss. The evidence
against: lines are still shown either way; a per-line refusal (1) removes the worst rows without a market-wide
switch. My recommendation: **(1) now as the per-line refusal, and treat the model's passing-yards edge as carrying
no positive evidence — it should not raise any row's rank — until (2)/(3) are re-measured.**

Not measured: venue execution (Kalshi/Polymarket) of NFL passing-yards edges; the served board (substrate is
checkout); other markets' identity defect (rushing/receiving use the zero-game imputation instead, a different path).

## Shipped in code 2026-10-08: the under-2-starts refusal (user: "Do the per-line refusal for under-2-starts QBs")

`player_stats.qb_starts_refused` + `qb_full_starts` (a full start = >= 0.7 of the team's `pass_attempt` plays in
that game, counted over the SAME as-of log `player_rate_with_prior` priced from); `props.nfl_props_rows_for_week`
withholds the passing_yards / passing_attempts probability when full starts < 2 and counts it
(`refused_qb_starts=` on the `[nfl_props] JOIN` line). The odds row survives. Switch:
`SYNDICATE_NFL_QB_STARTS_REFUSAL` (absent = ON). Threshold fixed from the 10-07 diagnosis; checked on FIT only
(2025 NOT read a third time). Through the shipped function on FIT 2023-24:

| market | refused | agrees with diagnosis | LL all -> kept | refused rows: LL, mean p, over-rate | share of excess LL |
|---|---|---|---|---|---|
| passing_yards | 539 / 10,297 (5.2%, 36 games) | 99.8% | 0.7872 -> **0.7214** | 1.978, 0.071, 0.521 | 71% |
| passing_attempts | 211 / 4,059 (5.2%, 33 games) | 99.8% | 0.7854 -> **0.7338** | 1.726, 0.128, 0.673 | 58% |

**The kept rows are still worse than a coin** (0.721 / 0.734 vs 0.693; book 0.665 / 0.692): causes #2 and #3 and
the attempts sack convention remain. This removes the worst rows; it does not make the market's model edge
positive. IN EFFECT NOWHERE until deployed AND the weekly prop artifact rebuilds (the builder calls
`nfl_props_rows_for_week(use_artifact=False)`; the line reprice cannot resurrect a refused player+stat because no
artifact row exists to reprice from).
