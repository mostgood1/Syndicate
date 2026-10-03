# NCAAF game lines + player props — as-of backtest vs naive baseline and the de-vigged book (2026-10-02)

Lane `ncaaf-lines-props-backtest`, session 7e94d2ff. Method mirrors `nhl-player-props-projection`
(deploys.md 2026-10-02 21:38Z). Harness `scripts/backtest_ncaaf_lines_props.py` (fetch / sim / score),
tests `tests/test_backtest_ncaaf_lines_props.py` (10). **Measurement only: no deploy, no env change,
no board change.** Every difference below is model MINUS comparator (negative = model better), with a
GAME-clustered bootstrap 95% CI (2,000 reps); no verdict is printed below 20 games.

## USER DECISION governing this file (recorded 2026-10-02)

**"Every line is its own decision. We should have a model that is accurate that then helps inform each
decision"** (user, 2026-10-02 ~7:05 PM CT, said about MLB; the app's prime directive; relayed to this lane
by the peer NCAAF session `local_379fd729` and corroborated on `origin/main` by `1ece602a`, which closed
`mlb-board-mean-only` unshipped for the same reason). **The task prompt's rule -- "a market earns a
probability/edge on the board only if it beats the baseline AND the book" -- is a MARKET-WIDE exclusion
and is WITHDRAWN.** This file delivers NO gate list and recommends NO mean-only / withheld-probability
posture for any market. The backtest is the DIAGNOSIS; per-line decisions stay with per-line scoring.

## Bottom line

- **Where NCAAF loses, and why (evidence below):** full-game MARGIN and MONEYLINE lose to the book because
  the RATINGS are worse than the market's, not because the distribution is wrong -- the model's
  disagreement with the close carries no information (slope -0.15, corr -0.09, n=113) and its win
  probabilities are no more extreme than the book's (|p-0.5| 0.251 vs 0.244). TOTALS lose because the
  engine spreads its means 2.6x wider than the market (prediction SD 12.67 vs 4.91; actual-on-model slope
  0.28) -- team quality over-applied to the total, the known `[smartsim2-total-carrier]` defect. COVER/OVER
  probabilities are mis-calibrated because they price the model-vs-line gap as signal with the model's
  own SD (cover bin p<0.35: predicted 0.235, observed 0.548). SEGMENTS under-project the first half by
  2.7 points (Q2 -2.38) and over-project the second (+1.39). PROPS lose information to stale/missing
  inputs: losing 2026 wk1-2 (as the fleet has) costs receiving yards +3.02 MAE [+2.24, +3.80] and rushing
  yards +1.80 [+0.64, +2.93].
- **Ranked fixes, with measured or out-of-sample impact,** are in "What would make each market accurate".
  The two largest are operational and engine-level: restore the lost player weeks, and correct the
  total's over-applied team quality.
- The 2025 full-season arm (L25) is PARTIAL (94 of 644 games, paused for host memory); its 94 games agree
  with L26. Resume: `sim --arm L25`.

## Substrate — what each number rests on

Render is billing-suspended (since 2026-09-30) and its disk is unreachable, so pre-fleet production
history exists only where a session saved it. Families, and where each came from:

| family | coverage | substrate |
|---|---|---|
| final scores + quarter line scores | 2025 wk1-16; 2026 wk1-5 (333 finals) | fleet `historical_truth/games_<S>.json.gz` (sha256-verified copy, 18/18 files) + CFBD `/games` 2026 wk5 |
| CFBD close (spread, total, both-side moneylines) | 2025 wk2-16, 1,420 games; 2026 wk3-4 | checkout `data/ncaaf_source/data/cfbd_lines_wk*.json` (immutable CFBD history); 09-28 grade's CFBD pulls |
| in-season PPA for the as-of blend | 2025 wk1-15 | CFBD `/ppa/games` via the generator's own loader (15 calls) |
| production pregame projections | 2026 wk3 (57 rows), wk4 (58) | `C:/tmp/ncaaf_677_snapshots` — production CSVs saved and sha256-checked by `ncaaf-blend-forward-grade` |
| OddsAPI two-sided quotes | games kicking off 2026-09-24..27 (captured 09-01..09-23 22:35Z); 2026-10-02T00-02Z | Render-era `C:/tmp/bq_ncaaf_2026-09-2{4,6}.jsonl`; fleet `tracking/book_quotes/2026-10-01.jsonl` |
| player game logs | 2024 wk1-16, 2025 wk1-16, 2026 wk1-5 | fleet snapshot (2025, 2026 wk3-4) + CFBD `/games/players` (2024 all, 2026 wk1-2 and wk5) |
| calibration profile | `ncaaf-goal-line-refit-1` | origin/main, byte-identical to the fleet's (sha256 `a7aaa953…`) |

**Intersections each result rests on** are in the tables (`n`, `g` = games).

## Controls (the harness is production, and it reproduces the prior grade)

- **The rebuild IS production:** each 2026 wk3/4 game rebuilt from the snapshotted blend entry through
  the shipped `build_projection` (300 seeds, promoted profile) matches production's CSV on **113 of 113**
  graded games (margin, total and win rate to 3 dp). So the segment distributions graded below are the
  ones production would have priced. The other 2 rows are dropped as non-pregame (`generated_at` after
  kickoff: Syracuse @ Pittsburgh, Liberty @ Coastal Carolina), exactly as the 09-28 grade did.
- **It reproduces the 09-28 forward grade (n=113):** margin MAE 12.015 vs DK close 10.062, model−close
  **+1.95 [+0.85, +3.02]** (09-28: +1.95 [+0.88, +3.04]); total 13.80 vs 12.38, **+1.42 [−0.05, +2.75]**
  (09-28: [+0.01, +2.79] — same point, bootstrap noise moves the lower end across 0).

## L25 — 2025 season as-of rebuild (PARTIAL: 94 of 644 games, weeks 3-5)

The full arm is 663 FBS-vs-FBS finals in weeks 3-15; 644 have both teams in the 2024 SP+ prior (the
other 19 would borrow current-season SP+, which has no as-of copy). **It was PAUSED at 94 games**
(2026-10-03 ~01:05Z): the host reached 96% memory with two peer backtests and the fleet running, and
the workers were thrashing (~0.2 s CPU per 20 s, working sets trimmed to 35 MB) while also adding
pressure to production. Each game is cached; `sim --arm L25` resumes at game 95.

What the 94 games (weeks 3 = 45, 4 = 45, 5 = 4) say — consistent with L26, and NOT a season result:

| market | n | model | comparator | model − comparator [95% CI] | verdict |
|---|---|---|---|---|---|
| margin MAE vs CFBD close | 94 | 13.475 | 12.197 | +1.279 [+0.093, +2.490] | **LOSES to book** |
| margin MAE vs naive | 92 | 13.475 | 18.337 | −4.889 [−8.048, −1.909] | beats naive |
| total MAE vs CFBD close | 94 | 13.188 | 12.628 | +0.561 [−0.957, +2.153] | unresolved |
| total MAE vs naive | 92 | 13.188 | 11.616 | +1.334 [−0.233, +2.895] | unresolved |
| h2h Brier vs de-vigged ML | 89 | 0.1876 | 0.1938 | −0.0061 [−0.0330, +0.0214] | unresolved |
| spread cover Brier @ close (book 0.5) | 93 | 0.2740 | 0.2500 | +0.0240 [−0.0120, +0.0640] | unresolved (behind) |
| total over Brier @ close (book 0.5) | 94 | 0.2676 | 0.2500 | +0.0176 [−0.0246, +0.0652] | unresolved (behind) |

Bias: margin −4.55, total −3.34 (early-season 2025). Blend points scale 44.66 (2024 fit; production's
44.497 is fit on 2025 and would leak). The calibration profile was fit on 2023-2025 drives, so it is
in-sample for this arm — a frozen constant, as NHL's SimConfig was.

## L26 — 2026 weeks 3-4, PRODUCTION's pregame projections (n = 113 games)

| market | n | model | comparator | model − comparator [95% CI] | verdict |
|---|---|---|---|---|---|
| margin MAE vs DK close | 113 | 12.015 | 10.062 | +1.953 [+0.851, +3.023] | **LOSES to book** |
| margin MAE vs naive (team as-of averages) | 112 | 12.015 | 20.617 | −8.742 [−11.667, −5.869] | beats naive |
| total MAE vs DK close | 113 | 13.797 | 12.376 | +1.421 [−0.051, +2.745] | unresolved (behind) |
| total MAE vs naive | 112 | 13.797 | 12.997 | +0.846 [−0.820, +2.476] | unresolved |
| h2h Brier vs DK de-vigged ML | 107 | 0.1722 | 0.1334 | +0.0388 [+0.0133, +0.0641] | **LOSES to book** (log-loss +0.104 [+0.039, +0.175]) |
| h2h Brier vs OddsAPI de-vig (wk4, early-week) | 55 | 0.1795 | 0.1364 | +0.0432 [+0.0086, +0.0794] | **LOSES to book** |
| spread cover Brier @ DK close (book 0.5) | 111 | 0.2816 | 0.2500 | +0.0316 [−0.0045, +0.0657] | unresolved (behind) |
| spread cover Brier vs OddsAPI de-vig | 54 | 0.2771 | 0.2495 | +0.0277 [−0.0165, +0.0749] | unresolved (behind) |
| total over Brier @ DK close (book 0.5) | 113 | 0.2723 | 0.2500 | +0.0223 [−0.0208, +0.0642] | unresolved (behind) |
| total over Brier vs OddsAPI de-vig | 55 | 0.2534 | 0.2490 | +0.0044 [−0.0577, +0.0681] | unresolved |

Bias: margin −0.79, total −1.53. **No full-game market beats the book; every point estimate is on the
book's side.** A model probability that sits ~0.03 Brier behind a coin-flip at the book's own line
(spreads, totals) is what an over-confident distribution produces (`NCAAF_MEASURED_SKILL` already
records margins 1.28× and totals 2.48× the close's dispersion).

**Segments (q1-q4, h1, h2), point accuracy vs the naive share baseline, n = 113:** margin beats naive
on q1 (−1.58 [−2.36, −0.77]), q2 (−1.45 [−2.61, −0.16]) and h1 (−4.84 [−6.55, −3.05]); q3/q4/h2
unresolved. Segment TOTALS never beat naive and lose on q3 (+0.51 [+0.02, +1.05]) and h2 (+0.87
[+0.01, +1.79]). **Segments vs the BOOK are UNMEASURABLE:** the Render-era captures carry no segment
markets, and the only completed games with segment quotes are the 2 Thursday 10-01 games (L26C) —
every cell there is `insufficient (<20 games)` and none is quoted as a result.

## Player props

Markets PRICED in the captured odds (Render wk4 + fleet): Anytime TD, Receiving Yards, Rushing Yards,
Receptions, Passing TDs, Passing Yards — nothing else, so nothing else is graded.

### P25 — 2025 weeks 2-16, the SHIPPED `prop_projections.payload_from_players` as-of (prior season 2024 present)

Baseline = the player's own as-of season mean (the entry's `season_mean`). No book exists for 2025.
"Brier" here is at a proxy line (floor of the baseline + 0.5), model vs the SAME distribution
re-centred on the baseline — a calibration check, NOT a market comparison.

| market | n | games | MAE model | MAE own avg | dMAE [95% CI] | proxy-line dBrier | bias |
|---|---|---|---|---|---|---|---|
| Passing Yards | 4,114 | 1,482 | 57.69 | 59.19 | −1.505 [−2.087, −0.927] | −0.0228 [−0.0267, −0.0187] | −3.98 |
| Passing TDs | 4,114 | 1,482 | 0.751 | 0.779 | −0.0284 [−0.0378, −0.0191] | −0.0221 [−0.0260, −0.0181] | −0.01 |
| Rushing Yards | 12,890 | 1,487 | 21.28 | 21.94 | −0.660 [−0.814, −0.521] | −0.0189 [−0.0218, −0.0160] | +0.42 |
| Receiving Yards | 15,936 | 1,487 | 20.54 | 20.97 | −0.430 [−0.535, −0.319] | −0.0122 [−0.0147, −0.0097] | +1.76 |
| Receptions | 15,936 | 1,487 | 1.400 | 1.391 | **+0.0089 [+0.0039, +0.0137]** | +0.0004 [−0.0006, +0.0014] | +0.12 |
| Anytime TD (prop_model rate, as-of) | 20,157 | 1,233 | Brier 0.1833 | 0.1938 (own raw rate) | — | −0.0105 [−0.0115, −0.0094] | — |

**Unlike NHL, the NCAAF shrunk mean DOES beat the player's own average on 4 of 5 continuous
markets** (and Anytime TD beats its own raw rate); **receptions loses**. Without the 2024 prior
(first run) the same 4/1 split held (passing yds −1.00 [−1.54, −0.46]; receptions +0.010
[+0.006, +0.014]), so it is not an artefact of the prior path. Refusals (all weeks): 13,687 players
with no game before the week, 39,394 spot-role-only players, 22,297 projected player-weeks with no
week-N line (did not play, or CFBD lists no line — the module's stated survivorship bias).

### P26 — 2026 vs REAL prices (wk4 Render captures ≤ 09-23, plus the 10-01 slate)

Model = the same shipped code over a snapshot holding 2025 + 2026 weeks < N (wk4 input weeks 1-3).
Book = per-book latest pregame two-sided pair at one line, proportional de-vig, modal line, mean over
books. 1,462 player-market groups: **350 scored** over 22 games; 1,055 Anytime TD groups excluded as
ONE-SIDED (books quote "yes" only — there is no fair to de-vig to); 32 player not in the artifact;
25 no actual line.

| market | n | games | Brier model | Brier book | dBrier [95% CI] | dMAE vs book line | dMAE vs own avg |
|---|---|---|---|---|---|---|---|
| Receiving Yards | 120 | 21 | 0.2687 | 0.2488 | +0.0199 [−0.0049, +0.0452] | −0.02 [−2.17, +2.14] | −0.61 [−2.01, +1.05] |
| Rushing Yards | 78 | 22 | 0.2597 | 0.2503 | +0.0094 [−0.0162, +0.0377] | +1.20 [−1.62, +3.61] | −0.60 [−1.96, +0.73] |
| Passing Yards | 41 | 22 | 0.2491 | 0.2505 | −0.0014 [−0.0372, +0.0335] | −3.38 [−11.21, +4.27] | −3.75 [−10.03, +2.33] |
| Passing TDs | 41 | 22 | 0.2547 | 0.2428 | +0.0119 [−0.0368, +0.0610] | +0.01 [−0.18, +0.18] | −0.175 [−0.242, −0.105] |
| Receptions | 70 | 17 | 0.2416 | 0.2423 | −0.0007 [−0.0308, +0.0313] | — | insufficient (<20 games) |

**Every prop market is UNRESOLVED against the book**, and the point estimates are on the book's side
in 3 of 5. This is a power limit, not a null: the CI half-width is ~0.025-0.05 Brier at ~22 games; to
resolve a 0.005-0.01 Brier difference needs on the order of 10-25× these games — most of a season of
two-sided captures. Prices are early-week (captured ≥ 2.5 days before kickoff), which flatters the
model if anything (an early line is softer than the close).

## Why each losing market loses (evidence; 2026 wk3-4 production pregame, n = 113 unless stated)

| market | loses to | cause | evidence |
|---|---|---|---|
| margin / spread point | book (+1.95 MAE) | RATING quality (the means) | corr(model, actual) 0.665 vs corr(book, actual) 0.776; model-minus-book does NOT predict actual-minus-book (slope -0.149, corr -0.085); spread of means about right (actual-on-model slope 0.88; prediction SD 15.43 vs book 15.54); bias -0.79 (book +0.85) |
| moneyline (h2h) | book (Brier +0.039) | the same rating error, carried through | not over-confident: mean abs(p-0.5) 0.251 vs book 0.244; tempering the logits makes it WORSE (k=0.8 -> 0.1738, k=0.5 -> 0.1835 vs 0.1722); Normal(margin, sd) at 0 gives the same Brier (0.1723), so the win-rate link is fine |
| total point | book (+1.42, unresolved) | DISPERSION of means: team quality over-applied to the total | prediction SD 12.67 vs book 4.91 (2.6x); actual-on-model slope 0.28; corr(model, actual) 0.225 = book 0.229 -- the information is there, the scale is ~3.5x too big; bias -1.53 |
| spread cover probability | book (+0.032, unresolved) | the model-vs-line gap priced as signal with the model's own SD | calibration: p<0.35 bin predicted 0.235 / observed 0.548 (n=31); 0.55-0.65 bin 0.590 / 0.417; model-side hit rate 0.505 |
| total over probability | book (+0.022, unresolved) | same, plus a per-game SD that is too NARROW | model SD 13.22 vs residual SD 17.97; p<0.35 bin predicted 0.167 / observed 0.444 (n=36) |
| segment totals q3, h2 | naive share (+0.51, +0.87) | the engine's SCORING CLOCK | model minus actual points: q1 -0.30, **q2 -2.38**, q3 +0.81, q4 +0.47; **h1 -2.68, h2 +1.39** -- too little end-of-half scoring, too much after the break |
| props, all 5 (vs book, unresolved) | -- | STALE/MISSING inputs + over-stated probabilities | (a) the fleet snapshot lost 2026 wk1-2: rebuilding wk4 from wk3 only vs wk1-3 costs receiving yds +3.02 MAE [+2.24, +3.80], rushing yds +1.80 [+0.64, +2.93], receptions +0.25 [+0.19, +0.31] (683-862 player-games, 122 games) and drops ~25% of projected players (receivers 1,295 -> 966); passing unaffected (-2.09 [-6.97, +2.69]). (b) the median priced row rests on 3 prior games. (c) model probabilities sit 0.11-0.15 from 0.5 while its mean-minus-line carries only weak information (corr with actual-minus-line +0.08 receptions ... +0.29 rushing) |
| receptions (vs own average, +0.009) | own as-of mean | role-prior shrink on the wrong rows; a shared regression-to-mean bias | by role: lead bias +0.674 (own avg +0.677), lead+rusher +1.886 -- shared by both; the model is worse than own avg mainly on `spot` rows (bias +0.407 vs +0.172, n=102) |

## What would make each market accurate (ranked by expected impact)

1. **Restore the lost 2026 wk1-2 player logs on the fleet snapshot, and find why the refresh dropped
   them** (operational). Measured above: +3.0 / +1.8 / +0.25 MAE on receiving yds / rushing yds /
   receptions, and a quarter of the projected players. Every prop line tonight is priced on 2 of 4 weeks.
   Cheapest fix with the largest measured effect.
2. **Correct the total's over-applied team quality** (engine, under `model_engine_standard.md`).
   `[smartsim2-total-carrier]` already fitted NCAAF keeps (offence 0.112 / defence 0.399) and named a
   PRE-ENGINE shrink as the right lever (as NFL's `[nfl-total-level-gain]`). Out-of-sample here: a level
   shrink fitted on 2025 (k=0.397, n=94) takes 2026 total MAE 13.80 -> **12.11, below the book's 12.38**
   (n=113). Re-fit per that section, never in isolation.
3. **Price each line's probability from a calibrated distribution, not the raw model-vs-line gap**
   (pricing layer; every line keeps its own probability). Market line as prior, model as evidence, weights
   and residual SD fitted on history. Out-of-sample (fit 2025 n=94, test 2026 n=113): spread cover Brier
   +0.0316 -> **+0.0001 vs the book** (w_model 0.15, SD 15.89); total over +0.0223 -> **-0.0083
   [-0.0198, +0.0029]** (w_model 0.25, SD 14.95); point MAE margin 12.02 -> 10.04 (book 10.06), total
   13.80 -> 12.02 (book 12.38). It states honestly how much the model adds beyond the line (little on
   margins, some on totals) and ends 0.235-probabilities that come in at 0.548. Props need the same
   treatment: their probabilities overstate weak information. Training sample is 2025 weeks 3-5 only --
   refit on the full L25 when it completes.
4. **Better ratings for margin and moneyline** -- the only route to a margin/h2h edge. The forward grade's
   arm S (refreshed 2026 SP+) led the blend by 0.63 MAE (unresolved); the blend's k and PPA scale were
   tuned against prior-season SP+, a weaker baseline. Candidates to test as-of: weight toward in-season
   SP+, a market-spread prior in the rating, handling FCS-padded early schedules. No measurement here says
   which wins.
5. **The engine's scoring clock for segments**: first half 2.7 points short (Q2 -2.38), second half +1.39
   high on 113 games -- end-of-half / two-minute behaviour in the drive simulator, or a measured
   per-segment share correction on the accumulator. Grading segments against a book needs captured
   segment closes for completed games (2 exist).
6. **Receptions**: the shrink loses to own average mainly on `spot` rows; widen K / drop the role prior
   for them; keep the Poisson for this under-dispersed market (measured better than a normal in the
   module).
7. **Anytime TD**: not gradable against a book until a two-sided quote is captured; the as-of rate beats
   the player's raw rate (Brier -0.0105 [-0.0115, -0.0094], n=20,157). The legacy `props.py` path still
   calls `anytime_td_probability`, which reads the WHOLE season (lookahead) -- switch it to the as-of rate.

Served context (fleet `/api/board/layer2-shortlist`, 2026-10-03 ~00:1xZ): 114 NCAAF rows, 103 full-game
rows carry `model_prob_over` and an edge. Under the user decision that is the right SHAPE -- each line
keeps its own probability; the work is to make that probability accurate (items 1-3), not to remove it.

## What the existing accuracy jobs cover, and what they miss

- **Daily model scorecard (`daily-accuracy`, fleet `model_scorecard_20261002`)**: grades NCAAF board
  rows per game, pregame and live, full game AND segments (q1-q4, h1, h2), props included —
  `brier(model) − brier(market)` per game with a bootstrap CI and BH-FDR. It is the right instrument,
  but it only sees what the fleet has served since 2026-09-30: **NCAAF 2 games, 1 date, 1,144 graded
  rows; every NCAAF cell reads `insufficient`.** The Render-era scorecard history did not carry over.
- **Weekly backtests (`run_weekly_backtests.py`, job `ncaaf_player_props`)**: runs
  `backtest_ncaaf_player_props.py --season <current>`, which grades `prop_model` (Anytime TD + an old
  shrink), NOT the `prop_projections` model the board serves; it has no book comparison; and its fixture
  output graded **0 weeks** (n=0, all NaN — the 2026 snapshot held weeks 1-2 against `--min-week 5`).
  There is **no NCAAF game-line job** in the weekly suite at all.
- **Missing everywhere until this lane:** as-of game-line accuracy over a full season, h2h against a
  de-vigged price, segment accuracy, and any prop comparison against a real price.

## Data defects found on the fleet (recorded, not fixed — outside this lane)

1. `ncaaf_source/data/processed/oddsapi_player_props_2026_wk4.csv` (and `tracking/book_quotes/2026_wk4.jsonl`)
   hold ONLY week-5 games (kickoffs 10-02..10-04): the week label is wrong.
2. The fleet's player-game-stats snapshot has **lost 2026 weeks 1-2** (holds 2025 + 2026 wk3-4;
   production held 8,115 wk1-2 rows on 09-18). The served wk5 prop artifact therefore rests on 2 of 4
   weeks — the projections the board shows tonight are thinner than the code intends.
3. The fleet's `smartsim2_projections_2026_wk4.csv` and `ncaaf_prop_projections_2026_wk4.json` were
   regenerated 2026-09-30, AFTER the week-4 games, and the wk5 CSV rows for the Thursday 10-01 games were
   stamped after kickoff — the daily re-write overwrites pregame rows (the 09-28 grade found the same).
   Nothing on the fleet preserves a pregame copy, so the next forward grade needs a snapshot taken
   before kickoff.

## Reproduce

    py -3 scripts/backtest_ncaaf_lines_props.py fetch --work C:/tmp/ncaaf_lpb   # 19 CFBD calls (+16 for 2024 logs)
    py -3 scripts/backtest_ncaaf_lines_props.py sim   --work C:/tmp/ncaaf_lpb --arm L26 --workers 7
    py -3 scripts/backtest_ncaaf_lines_props.py sim   --work C:/tmp/ncaaf_lpb --arm L25 --workers 7
    py -3 scripts/backtest_ncaaf_lines_props.py score --work C:/tmp/ncaaf_lpb

Work dir `C:/tmp/ncaaf_lpb`: `fleet_inputs.sha256` (18 files, verified), `sim_*.jsonl`, `report*.json`.
