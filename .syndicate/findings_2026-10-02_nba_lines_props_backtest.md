# NBA game lines + player props backtest and diagnosis, as-of, 2025-26 — lane `nba-lines-props-backtest`

Generated 2026-10-03 by `scripts/backtest_nba_lines_props.py` (worktree branch `session/nba-lines-props-backtest`),
same method and report shape as `scripts/backtest_nhl_props.py` (lane `nhl-player-props-projection`).
Full tables: `C:\tmp\nba_bt\out\report.md` / `report.json` (scratch; reproducible with
`py -3 scripts/backtest_nba_lines_props.py --out C:/tmp/nba_bt/out`).

## Directive, and what changed in this file `[2026-10-03]`

**User decision (prime directive, 2026-10-02):** *"every line is its own decision. we should have a model that
is accurate that then helps inform each decision."*
- Source: on file in this user's memory (`feedback_every_line_its_own_decision`, recorded 2026-10-02); relayed
  again on 2026-10-03 by the NCAAF backtest session.
- The first version of this file (`795d420b`) carried a market-level "MEAN_ONLY on every NBA market" gate list.
  That list was a market-wide exclusion and is **WITHDRAWN**.
- No NBA market is withheld. The backtest's job is to make the model accurate. Per-market numbers below are
  diagnosis and per-line scoring evidence, not a switch.

## Summary

- **The served model is less accurate than the player's own average, and the reasons are measurable:**
  - minutes: sim minutes are biased −3.7 and worse than a last-5 average;
  - per-minute rates: the sim's own rates are worse than the player's;
  - distribution width: the served sd is 1.4-1.9x too narrow for pts/reb/ast/pra.
- **Fixes that clear the player's own average out of sample** (test = 403 games / 79 dates, 2026-03-01
  onward plus the playoffs; fit on 145 earlier smart-sim games):
  - a mean shrunk toward the player's own per-minute rate and season average;
  - an NBA-fit sd scale.
  - Result at a book-like line: Brier better than the player's own-average distribution in **every** prop
    market. For example, pts −0.0080 [−0.0098, −0.0062] and pra −0.0091 [−0.0113, −0.0069].
- **Versus the de-vigged book these fixes are UNMEASURED.** Only 8 smart-sim games have two-sided prop prices.
  The OddsAPI backfill that would supply ~600 is owed and blocked on a key.
- **Game lines:**
  - The raw sim adds nothing beyond the line out of sample: the fitted model weight is 0.00 for margin and
    0.05 for total.
  - The raw total's level drifts (−10.0 bias in train, +0.2 in test).
  - The shipped market anchor (0.05 / 0.30) ties the line, which matches the WNBA lane's conclusion.
  - The win probability's gap to the book is in **resolution** (0.074 vs 0.080), which a transform cannot fix.
- No board or engine change was made. Each fix below is a model change for the user to decide, behind the
  model-engine standard.

## What was scored, and why that path (traced, not assumed)

- **The Layer-2 board has NO NBA projection source.** `board_enrichment._attach_projections_by_sport` falls
  through at `:1871` to `"no projection source wired for nba"`. NBA model numbers reach a user only on the NBA
  cards page / market board.
- **Game lines** (`syndicate/features/nba/cards.py:2064-2086`). The served margin/total is
  `game_cards.pred_margin/pred_total`, which is the **sum of q1..q4 smart-sim means** (regulation only;
  `refresh_nba_oddsapi_props._smart_sim_projection_index`, because `cards_sim_detail` drops `score`).
  Probabilities are fixed-scale logistics: win `m/6.5`, cover `(m+spread)/7.5`, over `(total-line)/10.5`,
  quarter win `/3.4`. The harness imports `cards._margin_win_prob`.
- **Market anchor.** Syndicate's port anchors the sim to the market by default (total 0.7·market + 0.3·model;
  margin 0.95·market + 0.05·model; `basketball_props_smart_sim._simulate_quarters_local`). The 2025-26
  upstream sims carry no `market_anchor`, so they are raw model output. Arm `smart_sim_anchored_replay`
  applies the anchor ARITHMETIC to the as-of line; it is not a re-sim.
- **Props.** Model mean = `mean_<stat>` (smart-sim) when that column exists, else `pred_<stat>` (ONNX); combos
  are sums. Two probabilities are served:
  - picks: `props_edges.model_prob`. With no `props_prob_calibration*.json` (none exists on the fleet or the
    mirror), pts/pra are shrunk to 0.5 by k=0.45/0.50, and ast/reb/pr/pa/ra are blended 65-85% toward the
    book's vig-inclusive implied price.
  - market board: `model_prob_over` = Normal(mean, sd), unblended (= `model_prob_raw`).
  - The harness CALLS `_compute_props_edges_file_only_local` on the as-of inputs. Parity check: the harness
    Normal reproduces `model_prob_raw` on 35,802 of 35,866 rows (64 off by > 0.002).
- **Not served, scored for context:** upstream `predictions_<date>.csv` (vendor games model), the only full-season
  game projection.

## As-of construction and substrate

- **Projections and odds = files the producers COMMITTED.** Sources are upstream `mostgood1/NBA-Betting`
  `data/processed/` (the source app Syndicate mirrored all season) and Syndicate `origin/main`
  `data/nba_source/` (2026 playoffs). For each (family, date) the harness takes the LAST version committed
  strictly before the date's FIRST tip (ESPN). Re-commits after the games are common (props_edges: 39 of ~200
  dates were last written after game day), and those versions are never used.
- **Not used:** the checkout's `data/**`. **Not available:** Render (all three services billing-suspended
  since 2026-09-30) and the fleet disk (NBA files only from 2025-05 and 2026-10, i.e. preseason).
- **Actuals:** stats.nba.com `playergamelogs` (2025-26 Regular Season + Playoffs) and ESPN scoreboards
  (finals, linescores incl. OT, tip times), fetched 2026-10-02.
  - Join by NBA PLAYER_ID: 12,894 rows.
  - The upstream 2026 playoff files carry **ESPN ids**, so those rows use a unique same-date name match: 6,359.
  - Unmatched rows (not on the slate, DNP, or no unique name): 7,055.
- **Baselines:** (a) the player's 2025-26 per-game average over games strictly before the date, (b) last-10,
  (c) for games, the captured book line.
- **Frozen / not as-of:** model code and constants as they stood in the producers on each date. This scores
  what was served, not a re-run of today's code. Today's code differs in one known way: the market anchor,
  covered by the replay arm.

### Coverage: per family, pre-tip versions only

| | regular (166 dates, 1,235 ESPN games) | playoff (44 dates, 85 games) |
|---|---|---|
| props_predictions | 163 (2 post-tip-only excluded) | 43 (1 excluded) |
| — of which smart-sim `mean_*` | 55 dates scored | 42 dates scored |
| props_odds (raw two-sided prop prices) | **5** (10-24..10-27, 03-26) | **6** (05-30..06-13) |
| game_odds (consensus) | 161 | 38 |
| period_lines | 40 | 38 |
| smart_sim per-game JSON | 553 games / 72 dates | 81 games / 40 dates |
| player logs | 164 | 44 |

**Intersections the results rest on:**
- Props, point accuracy: regular smart-sim 55 dates / 428 games / 8,434 player-games; regular ONNX 96 dates /
  703 games / 8,681; playoff smart-sim 42 dates / 83 games / 1,820.
- Props vs book: **ONNX 4 dates / 37 games; smart-sim 6 dates / 8 games.**
- Served game lines: 524 regular games with smart-sim + book (70 dates), 79 playoff games.
- Periods with book lines: 173-258 regular games.

## Player props: point accuracy (dMAE = MAE model − MAE own as-of average; game-clustered 95% CI)

Smart-sim engine (what production serves):

| market | regular n / games | bias | MAE model | MAE avg | dMAE [CI] | verdict | playoff dMAE [CI] (n 1,820 / 83 games) |
|---|---|---|---|---|---|---|---|
| pts | 8,434 / 428 | −1.11 | 5.473 | 4.837 | +0.636 [+0.535, +0.739] | WORSE | +0.016 [−0.195, +0.229] |
| reb | 8,434 / 428 | −0.38 | 2.122 | 1.928 | +0.193 [+0.158, +0.229] | WORSE | −0.015 [−0.086, +0.051] |
| ast | 8,434 / 428 | −0.47 | 1.532 | 1.406 | +0.126 [+0.101, +0.150] | WORSE | −0.062 [−0.124, +0.003] |
| threes | 8,434 / 428 | −0.05 | 0.987 | 0.897 | +0.090 [+0.077, +0.104] | WORSE | −0.017 [−0.044, +0.007] |
| pra | 8,434 / 428 | −1.96 | 7.434 | 6.463 | +0.971 [+0.825, +1.126] | WORSE | −0.010 [−0.345, +0.323] |
| pr | 8,434 / 428 | −1.49 | 6.667 | 5.864 | +0.803 [+0.673, +0.938] | WORSE | −0.069 [−0.336, +0.195] |
| pa | 8,434 / 428 | −1.59 | 6.220 | 5.407 | +0.813 [+0.692, +0.933] | WORSE | +0.030 [−0.238, +0.296] |
| ra | 8,434 / 428 | −0.85 | 3.018 | 2.728 | +0.290 [+0.235, +0.347] | WORSE | −0.083 [−0.213, +0.045] |
| stl | 8,434 / 428 | −0.08 | 0.767 | 0.724 | +0.043 [+0.032, +0.053] | WORSE | **−0.064 [−0.085, −0.043] BETTER** |
| blk | 8,434 / 428 | −0.19 | 0.503 | 0.506 | −0.003 [−0.009, +0.005] | NO DIFF | **−0.028 [−0.049, −0.004] BETTER** |
| tov | 8,434 / 428 | −0.04 | 1.030 | 0.910 | +0.120 [+0.102, +0.138] | WORSE | +0.019 [−0.014, +0.053] |

- The ONNX era (Oct to mid-Jan, `pred_*` only) is worse still on every market, e.g. pts +1.138 [+1.037, +1.233]
  over 8,681 player-games.
- The smart-sim engine **under-projects systematically** in the regular season (pra −1.96, pts −1.11). The
  last-10 average beats the season average for most markets.
- In the playoffs the smart-sim engine ties the player's average, and slightly beats it for stl and blk. That
  population is one postseason of 83 games; NHL's playoff arm is the same kind of evidence.

## Player props vs the de-vigged book (proportional de-vig of two-sided lines; latest pre-tip snapshot per line/book)

Filters (all 10 dates): 84,858 edge rows, 2,903 dd/td excluded (yes/no), 668 one-sided, 1,060 void/unmatched,
61 with no baseline, 0 ambiguous player matches. 1 date (2026-05-26) was refused by production itself
("No edges computed").

| engine\|market | n / games | Brier book | Brier picks (blended) | Brier board (raw Normal) | dBrier picks−book [CI] | dBrier board−book [CI] |
|---|---|---|---|---|---|---|
| smart-sim pts | 1,408 / 8 | 0.2409 | 0.2900 | 0.3921 | +0.049 [+0.033, +0.066] | +0.151 [+0.109, +0.195] |
| smart-sim pra | 1,019 / 8 | 0.2447 | 0.2565 | 0.3917 | +0.012 [+0.001, +0.021] | +0.147 [+0.077, +0.201] |
| smart-sim reb | 781 / 8 | 0.2434 | 0.2394 | 0.2771 | −0.004 [−0.013, +0.004] | +0.034 [+0.001, +0.069] |
| smart-sim ast | 569 / 8 | 0.2445 | 0.2583 | 0.3623 | +0.014 [+0.002, +0.025] | +0.118 [+0.052, +0.171] |
| smart-sim threes | 511 / 8 | 0.2541 | 0.3097 | 0.3097 | +0.056 [+0.014, +0.103] | same |
| ONNX pts | 6,030 / 37 | 0.2444 | 0.2519 | 0.2705 | +0.008 [+0.001, +0.014] | +0.026 [+0.011, +0.041] |
| ONNX pra | 5,570 / 37 | 0.2412 | 0.2436 | 0.2768 | +0.002 [−0.001, +0.005] | +0.036 [+0.018, +0.054] |
| ONNX reb | 3,184 / 37 | 0.2459 | 0.2486 | 0.2725 | +0.003 [+0.000, +0.006] | +0.027 [+0.013, +0.039] |

- **Every market with a reading, both engines:** the unblended Normal (what the NBA market board shows) is
  significantly worse than the book. The exceptions are ONNX stl, which is no different
  (+0.0095 [−0.006, +0.027], 263 rows), and tov, which is unmeasurable (19 rows).
- The blended pick probability is never better than the book. It ties only where it is 65-85% the book's own
  price.
- Flat-stake ROI on the picks' +EV side is negative or indistinguishable from 0 in every market (best: ONNX
  ast +0.8% [−7.3%, +8.7%] on 1,933 bets). For the smart-sim engine, pts is −29.8% [−45.1%, −15.4%] on 1,179
  bets.
- **This half is THIN for the served engine: 8 games.** The OddsAPI historical backfill (approved,
  ~139k credits) would extend it to about 600 smart-sim games. It is the measurement of whether the fixed
  model (below) is better or worse than the book, line by line.

## Game lines (served = smart-sim quarter sum; regular season, 524 games with a pre-tip book)

| arm | margin dMAE vs line [CI] | total dMAE vs line [CI] | ML dBrier vs book [CI] | cover dBrier [CI] | over dBrier [CI] |
|---|---|---|---|---|---|
| smart_sim (raw, 2025-26 as served) | +1.903 [+1.290, +2.543] WORSE | +3.270 [+2.344, +4.169] WORSE | +0.040 [+0.025, +0.056] WORSE | +0.047 [+0.028, +0.066] WORSE | +0.047 [+0.027, +0.069] WORSE |
| anchored replay (2026-27 default) | +0.006 [−0.027, +0.042] = | +0.250 [−0.035, +0.552] = | +0.0005 [−0.002, +0.004] = | +0.0004 [−0.001, +0.002] = | +0.005 [−0.002, +0.013] = |
| predictions_csv (vendor, not served; 816 games) | +2.745 [+2.172, +3.331] WORSE | +2.495 [+1.842, +3.210] WORSE | +0.085 [+0.066, +0.104] WORSE | +0.069 WORSE | +0.039 WORSE |

- Raw smart-sim total bias is **−6.69** in the regular season (and **+13.6** over 79 playoff games). It is
  not OT: the regulation-only sum misses about 0.6 pts on average.
- **Periods:** h1 and q1-q4 totals are significantly worse than the period lines (q1 +0.97 [+0.52, +1.45],
  h1 +1.81 [+0.95, +2.71]; 173-258 games). Margins are worse or no different. Quarter win probabilities have
  no book to compare against.
- **A false edge, found and removed.** Before the price fix, the anchored replay showed cover MODEL_BETTER
  with +31% ROI. Cause: the upstream consensus `game_odds` pairs main points with alt-line prices (e.g.
  −245/+180), and 502 of 1,281 rows are unpriced. Spread/total prices are now used only inside a main-line
  band (431 cover / 538 over pairs kept; 172 / 68 reset to −110). After the fix: NO_DIFFERENCE, 86 bets,
  ROI −4.8% [−27.2%, +16.0%]. **Spread/over book Brier here is a coin with noise,** so beating it means little
  unless the model also beats p = 0.5.

## Why each prop market loses, and what fixes it (`--diagnose`; fit < 2026-03-01, scored on 403 later games incl. playoffs)

Data: 10,997 smart-sim player-games with sim minutes; train 2,635 rows / 145 games, test 8,362 rows / 403 games
(1,726 playoff).

### Cause 1, minutes (the largest single error)

- Sim projected minutes vs actual: bias **−3.67 min**, MAE 6.64, against 5.27 for the player's last-5 average.
  The sim is worse by +1.36 [+1.22, +1.52].
- 1,942 sim players projected ≥ 10 min have no box line that day. That is DNP or unmatched; unmatched names
  are included in the count, so it is an upper bound on availability misses.
- **Diagnostic bound** (uses the result, not a fix): rescale the sim mean to the minutes actually played and
  pts MAE falls 5.26 → 4.28 (own average 4.87), pra 7.13 → 5.17 (own average 6.52).
- WNBA fix #2 (availability) targets exactly this. It changes minutes inside the sim, so measuring it on NBA
  needs a re-sim; that is owed.

### Cause 2, per-minute rates and mean shrink

Replacing or shrinking the sim's per-minute rate toward the player's own as-of rate, then blending toward the
own average, gives these test MAE deltas:

| market | model − own avg | rate shrink (WNBA w, as-is) vs model | NBA-fit rate shrink vs own avg | blend toward own avg vs own avg (w_model) |
|---|---|---|---|---|
| pts | +0.390 [+0.293, +0.489] | −0.373 [−0.424, −0.319] | +0.017 (tie) | **−0.109 [−0.130, −0.088]** (0.20) |
| reb | +0.114 [+0.079, +0.147] | −0.120 [−0.136, −0.104] | +0.002 (tie) | **−0.029 [−0.035, −0.023]** (0.15) |
| ast | +0.079 [+0.051, +0.104] | −0.098 [−0.112, −0.083] | −0.013 (tie) | **−0.031 [−0.038, −0.024]** (0.25) |
| threes | +0.047 [+0.033, +0.061] | −0.055 [−0.060, −0.049] | **−0.024 [−0.034, −0.015]** | 0 (w = 0) |
| stl | +0.005 (tie) | n/a | **−0.028 [−0.034, −0.022]** | −0.003 |
| blk | −0.017 [−0.024, −0.009] | n/a | **−0.025 [−0.030, −0.020]** | −0.011 |
| tov | +0.066 [+0.049, +0.084] | n/a | **−0.019 [−0.028, −0.009]** | 0 (w = 0) |
| pra | +0.605 [+0.451, +0.755] | −0.478 [−0.554, −0.400] | n/a | **−0.185 [−0.217, −0.155]** (0.20) |

- **WNBA #3 (rate shrink) transfers to NBA as-is.** Its WNBA weights land within 0.003 of the NBA re-fit for
  pts/reb/ast.
- Fitted model weights in the blend are 0.15-0.30. The sim carries real information beyond the average, but
  much less than it is given today.
- **Bias-only shift and linear recalibration HURT out of sample** in most markets: the bias is not stable.
  Don't ship them.

### Cause 3, distribution width and shape (the probability the market board shows)

The served sd is too narrow. On the test set, IQR(z)/1.349 is pts 1.52, reb 1.44, ast 1.39, pra 1.85,
blk 1.14, threes 1.05. The ±0.674-sd band holds 36% of pts and 30% of pra outcomes, against 50% for a correct
model.

At a book-like line (the player's as-of average rounded to x.5), Brier vs the player's own-average
distribution:

| market | served Normal | NBA-fit wider sd | + blend mean | + rate-shrink mean | WNBA k (#1) vs served | WNBA NB D (#4) vs served |
|---|---|---|---|---|---|---|
| pts | +0.0261 [+0.0196, +0.0322] | +0.0081 | **−0.0080 [−0.0098, −0.0062]** | −0.0020 (tie) | −0.0106 | n/a |
| reb | +0.0252 | +0.0064 | **−0.0055 [−0.0068, −0.0042]** | −0.0026 (tie) | −0.0120 | −0.0066 |
| ast | +0.0162 | +0.0050 (tie) | **−0.0083 [−0.0103, −0.0064]** | −0.0056 | −0.0073 | −0.0045 |
| threes | +0.0167 | +0.0157 | 0 | **−0.0074 [−0.0115, −0.0032]** | −0.0030 | **−0.0121** |
| stl | 0.0000 (tie) | +0.0019 (tie) | −0.0026 | **−0.0131 [−0.0175, −0.0088]** | n/a | n/a |
| blk | +0.0070 | +0.0036 (tie) | **−0.0065 [−0.0080, −0.0050]** | −0.0045 | n/a | n/a |
| tov | +0.0153 | +0.0169 | 0 | **−0.0056 [−0.0096, −0.0011]** | n/a | n/a |
| pra | +0.0349 [+0.0272, +0.0422] | +0.0053 (tie) | **−0.0091 [−0.0113, −0.0069]** | n/a | −0.0176 | n/a |

- Murphy decomposition of the served Normal, pts: reliability 0.037 (very poorly calibrated) and resolution
  0.008.
- After blend + width: reliability 0.002, resolution 0.007. **The served probability's loss is almost all
  reliability**, which is fixable.
- The negative binomial with a variance fitted per market from the whole residual is **worse** than the scaled
  Normal for pts/stl/blk/tov. The WNBA NB-D constants help reb/ast/threes, and threes most (−0.0121 vs served).

### Ranked model fixes for NBA before opening night (by measured out-of-sample impact)

1. **Mean: shrink sim per-minute rates toward the player's own, then blend toward the season average.** WNBA #3
   transfers; NBA weights are in `diagnose.json`. It is the largest MAE gain on every market and the only fix
   that beats the player's own average on point accuracy. Post-hoc evaluable, so it is ready to implement
   behind a flag.
2. **Width: an NBA-fit sd scale** (pts 1.5, reb 1.4, ast 1.4, pra 1.85; ~1.0 for threes/stl/tov). WNBA #1 k
   values point the same way but are smaller. Combined with fix 1, the board's probability beats the player's
   own-average distribution in all 8 markets.
3. **Minutes / availability: re-sim with WNBA #2 enabled for NBA.** It is the largest error source by the
   diagnostic bound, but needs a re-sim, so impact is UNMEASURED. It also requires editing the module's
   hard-coded `!= "wnba"` check and an NBA re-fit.
4. **threes shape: NB with D ≈ 1.13 (WNBA #4 transfers).** The best threes probability, −0.0121 vs served.
5. **Not recommended on this evidence:** bias-only shift, linear recalibration, and a residual-fit NB for
   pts/stl/blk/tov.
6. **Vs the book: all of the above is UNMEASURED** (8 smart-sim games). The OddsAPI backfill is the
   measurement.

## Game lines: why the raw sim loses (`--diagnose`, 209 train / 394 test games)

- **The sim's departures from the line carry no information out of sample.** For w·model + (1−w)·line, the
  fitted w is **0.00 for margin and 0.05 for total**, before and after a bias shift.
  - Raw sim vs line, MAE: margin +1.33 [+0.62, +2.00], total +2.95 [+2.00, +3.93].
  - Shipped anchor (0.05 / 0.30) vs line: margin −0.024 [−0.064, +0.015], total +0.176 [−0.164, +0.509], both
    ties.
- **The raw total's level is unstable:** bias −10.0 in train (Jan-Feb) and +0.2 in test. A fitted level shift
  does not carry forward.
- **Win probability:**
  - Served (logistic 6.5): Brier 0.185, reliability 0.017, resolution 0.074.
  - Book: Brier 0.169, reliability 0.005, resolution 0.080.
  - A re-fit scale does not help (0.189). The gap is resolution, so a transform cannot close it; only a
    better margin model can.
- **Raw-model fix candidates:** these are the same mechanisms the WNBA lane found (the raw ridge is worse than
  the line; slope 0.07). The game-line model needs better inputs (minutes, availability, lineup), not
  recalibration. Until it beats the line, **the shipped anchor is the honest serving config**; per line it
  returns the line's own number.

## Daily accuracy / weekly backtests: what covers NBA

- `publish_model_scorecard.SEASON_WINDOWS` has `nba: (10-01, 06-25)`, so the daily scorecard switches NBA on
  from Oct 1. The skill doc says it is "registered, reachability proved, correctness not yet measurable".
- It grades board rows with `row["projection"]`. NBA board rows get no projection (`board_enrichment:1871`), so
  **NBA model skill is ungradable there** (inferred from code, not read off a published scorecard). Only
  market-side rows will exist.
- `run_weekly_backtests.py` has a `wnba_projection` job and **no NBA job**. This script is the obvious
  candidate.
- The existing NBA accuracy code (`nba/market_accuracy.py`, `live_*_accuracy.py`) scores selected picks'
  W/L/ROI only. It has no MAE, Brier or baseline.

## Defects found in passing

- **`basketball_props_edges` short-key fallback is a many-to-many merge.** `PROP_NAME_JOIN` printed
  `unmatched_after_fallback` 142k-333k against `rows_considered` 9k-25k on 2025-10-24..27. Recorded as a lead
  (`.syndicate/leads.md`, 2026-10-03). In the scored rows it produced 0 ambiguous player assignments after
  dedup, but the counter is meaningless.
- **Upstream 2026 playoff `props_predictions` switched to ESPN player ids.** Any id-joined NBA grader
  silently drops them.
- **Upstream consensus `game_odds` spread/total prices are unreliable** (see above). Any Brier or ROI computed
  against them is suspect.
- **The repo `.env` `ODDS_API_KEY` is deactivated** (HTTP 401 `DEACTIVATED_KEY`, 2026-10-03).

- **Price converters guarded (2026-10-03, at lane `nhl-props-converter-guard`'s request).** `_implied` and
  `_american_to_dec` now refuse None/''/text/0 and |price| < 100, and score 5/5 in
  `scripts/probability_differential.py`. Re-score impact: every served-path cell is identical. Only the
  unserved `predictions_csv` win_prob arm lost 33 consensus rows (816 → 783), still MODEL_WORSE (+0.0835
  [+0.0642, +0.1034]).

## Not done / owed

- **OddsAPI historical backfill** (user-approved ~139k credits). Blocked: the repo key is deactivated, and
  auto mode refused reading the fleet's key twice as credential exploration, even after the user authorised it
  in chat. The harness is ready:
  `--fetch-odds` (dry run, 139,203-credit estimate) → `--fetch-odds --execute --max-credits 150000`, then
  `--analyze-only`. It writes only under `--out/cache`. The backfilled odds are not yet wired into scoring
  (`hist_props_csv` / `hist_game_book` exist; the book arm still reads the committed files).
- **NBA re-sim** with WNBA #2 (availability) and #3 (rate shrink) enabled for NBA, to measure the minutes fix.
- No board or engine change; nothing deployed.

## The calibrated model vs the de-vigged book, and the out-of-sample book-blend weight `[2026-10-05, a032251a]`

**Data.**
- OddsAPI historical backfill (user-approved): 137,863 credits, 1,325 games over 212 dates, 0 errors.
- One pre-tip snapshot per game, 45 min before its own tip, from every US book, in the 10 priced prop markets.
- Lines are proportionally de-vigged per book, and only two-sided, non-integer lines are kept.
- Scored rows are the calibration's held-out set: 400 games, 2026-03-01 onward plus the playoffs; constants were fit
  on 145 earlier games.
- 249,884 (line, book) rows on test and 86,534 on train. 22,705 test lines had no sim player that date.
- Several books often price the same line, so every CI is game-clustered.

**The calibrated model loses to the book in every market** (`fit_nba_prop_calibration.py --vs-book`):

| market | lines | Brier book | calibrated | raw served | own avg | calibrated − book [95% CI] | +EV bets ROI [CI] |
|---|---|---|---|---|---|---|---|
| all | 249,884 | 0.2438 | 0.2672 | 0.3110 | 0.2709 | +0.0234 [+0.0204, +0.0268] | −6.5% [−8.4, −4.7] |
| pts | 61,456 | 0.2420 | 0.2696 | 0.3079 | 0.2746 | +0.0276 [+0.0236, +0.0322] | −6.9% [−9.6, −4.4] |
| reb | 34,367 | 0.2437 | 0.2539 | 0.2959 | 0.2564 | +0.0102 [+0.0065, +0.0140] | −2.4% [−5.4, +0.8] |
| threes | 24,211 | 0.2406 | 0.2555 | 0.2667 | 0.2595 | +0.0149 [+0.0114, +0.0183] | −9.6% [−13.1, −6.2] |
| ast | 22,896 | 0.2435 | 0.2668 | 0.3166 | 0.2685 | +0.0233 [+0.0189, +0.0282] | −9.0% [−12.3, −5.6] |

pra, pr, pa, ra, blk and stl follow the same pattern; full table in `fit_nba_prop_calibration_vs_book.json`.
The calibration closes about two-thirds of the raw model's gap to the book (+0.067 -> +0.023 pooled), but none of it.

**How much should the model's departure from the book be trusted?** (`--book-blend`)
- The blend is p = book + w (calibrated − book). w is fit on TRAIN lines by Brier, in logit and probability space, and
  scored on TEST.
- Fitted w: 0.05 pooled (logit), 0.05-0.15 per market, and 0 for blk and stl.
- On test, the blend TIES the book: pooled +0.00010 [−0.00010, +0.00029]. No market is better; the best is reb,
  −0.00028 [−0.00068, +0.00023]. ast is WORSE even at w = 0.10: +0.00099 [+0.00038, +0.00165].
- The blended model's +EV bets have ROI CIs spanning 0 in every market.

**Conclusion.**
- On these lines, the calibrated NBA prop model carries no measurable information beyond the de-vigged book.
- Per line, the honest probability is the book's own price (w ≈ 0.05). An edge shown against the book is model error.
- This is consistent with the WNBA lane's book-information finding: the book is right ~94% of the way when the two
  disagree, through minutes, late absences and lineups.
- The largest error source measured here is minutes, and the fix aimed at it, availability (WNBA #2), is still
  untested on NBA. That, not recalibration, is where any edge would have to come from.

**Not done:**
- The ladder path (what Layer 2 serves) was not scored separately. Its mean equals the evaluated mean, and its width
  is approximately the evaluated width.
- The harness's served-model-vs-book arm on the backfilled odds was STOPPED. The production edges function
  short-key merge blew up to 3.36M rows / 4.8 GB per date (the many-to-many lead), and the host had 2.2 GB free with
  the fleet on the same machine. Do not re-run it on backfilled odds without first filtering to one line per
  (player, stat, book).

## NBA sim availability: does the pre-tip sim simulate players who are not playing? `[2026-10-05, e0a3e383]`

Pre-registered as H-A1/H-A2 in lanes.md (8b24e2b3) before measuring.

**Substrate.**
- Committed pre-tip smart-sim JSONs, C:\tmp\nba_bt\out\asof\smart_sim (640 files), joined to stats.nba 2025-26
  regular-season logs.
- 159 team-games were skipped because their sim minutes do not sum to 240. That covers all of January 2026
  (`min_mean` = 0, an old format) and a few empty sims.
- Measured: 930 team-games over 62 dates. Train is before 2026-03-01 (285 team-games, February only); test is on or
  after it (645).
- Players are joined by a season-wide unique normalized name. 6,999 of 13,742 sim ids are not NBA ids (ESPN ids)
  and 11 names are unknown.
- Script: scratchpad nba_avail_measure.py (not committed).

**H-A1 HOLDS.** The sim gives **44.5 of every 240 team minutes (18.5%)** to players with no log that day. That is
4.8 sim rows per team-game, 1,673 of them projected at 10 minutes or more. WNBA's figure was 42.6 of 200 (21%).
Played players: minutes bias −2.75, MAE 6.91 (n 9,253).

**H-A2 REFUTED as stated.** WNBA's K=1 rule (left out if absent from the team's last game) removes 55% of those
minutes, but it drops **1.43 real players per team-game** (pre-registered bar: < 1). It removes 16.2 real-player
minutes for every 24.4 non-player minutes, a 1.5 : 1 ratio against WNBA's 6.4 : 1. NBA players miss single games
far more often (rest and load management), so a one-game absence is weak evidence there.

**Exploration** (post-hoc; selected on train only by net non-player minutes, the WNBA criterion; confirmed on test):

| rule | split | non-player min removed /tg (share) | real-player min wrongly removed /tg | real players dropped /tg | ratio |
|---|---|---|---|---|---|
| missed last 1 | train | 19.15 (52%) | 14.09 | 1.11 | 1.4 |
| missed last 1 | test | 26.70 (56%) | 17.13 | 1.57 | 1.6 |
| missed last 2 | train | 13.02 (36%) | 3.74 | 0.49 | 3.5 |
| missed last 2 | test | 19.24 (40%) | 6.39 | 0.75 | 3.0 |
| missed last 3 | train | 9.83 (27%) | 1.97 | 0.32 | 5.0 |
| missed last 3 | test | 15.71 (33%) | 3.50 | 0.47 | 4.5 |
| never played for team (≥3 team games) | train | 0.09 | 0.55 | 0.04 | 0.2 |
| never played for team (≥3 team games) | test | 0.43 | 0.13 | 0.02 | 3.2 |

- Net minutes per team-game: K=2 is +9.28 on train and +12.85 on test. K=3 is +7.86 / +12.21. K=1 is +5.06 / +9.57.
  **K=2 is selected.**

**What this does NOT establish.**
1. **Confound.** These sims ran pre-2026-10-04 code. The injury-exclusion fixes (ff4ca730 re-admit only on a truthy
   playing_today, 500a5643 team re-keying, 1111942f punctuated-name keys) apply to NBA too. Production's residual
   non-player minutes under current code are unmeasured. WNBA measured its rule on as-of re-runs of current code.
2. **No prop effect measured.** Minutes are an input; the WNBA lane needed an engine re-run (500 sims, paired) to show
   the prop/Brier effect.
3. **The book-blend ceiling.** With the NBA book blend serving ≈ the book (w ≈ 0), better minutes change served
   probabilities only if they raise the out-of-sample blend weight. WNBA's oracle found that perfect injury
   information barely moves props at the book line. The more likely payoff is the served means and projections, not
   the edges.

**Next, if wanted:** an as-of engine re-run on held-out NBA games with current code, base vs K=2 (paired). It would
measure the residual non-player minutes, minutes bias/MAE, prop MAE vs own average, and Brier vs book, then refit the
blend weight on the result.

## NBA season phase: where it is and is not handled `[2026-10-05, e0a3e383; audit, read-only]`

Asked for by the user's preseason direction, relayed by the NCAAF session. **Nothing in the NBA lines or props path
reads the season phase.** The label exists only in two places, and neither reaches an artifact row:
- the vendor schedule's `game_label` (`vendor/.../schedule.py:172,199`; its fallback `:114` hardcodes
  "Regular Season");
- OddsAPI's `basketball_nba_preseason` sport key (`vendor/.../odds_api.py:26-27`). It is dropped from the rows at
  `:133-145` and from `scripts/fetch_basketball_oddsapi_props_local.py:170-183,390-410`.

ESPN scoreboards label it `season.type` (1 = pre), verified on the 10-03/04 games.

| component | file:line | phase-aware? | preseason impact |
|---|---|---|---|
| boxscores_history writer | shared/basketball_boxscores_history.py:297-395; ESPN `scoreboard?dates=` (smart_sim.py:488) | no | preseason AND playoffs included |
| player_logs writer | vendor/player_logs.py:234 (fallback :293-298) | yes (Regular Season) | pure, unless the fallback rewrites it from boxscores_history |
| sim minutes priors | basketball_props_smart_sim.py:3381-3422 (:3403 -> player_logs, 21 days) | no | regular-season priors |
| rotation-history minutes | basketball_props_smart_sim.py:2324,2380 (28-day lookback); vendor rotations_espn.py:512 | no | **at the opener the window is all preseason** |
| pool prune | basketball_props_smart_sim.py:1799 (max_keep 13) | no | same depth every phase |
| prop calibration own rates | nba_prop_calibration.py:82-85 (season from Aug 1), :236-239 | no | preseason becomes "season-to-date" after 3 games and stays mixed into early regular season |
| prop calibration prior | nba_prop_calibration.py:242-246 (player_logs) | yes | last regular season |
| prop calibration constants | backtest_nba_lines_props.py:460 (Regular Season + Playoffs) | fit without preseason | applied to preseason unchanged |
| availability K rule | wnba_sim_availability.py:85-114 (NBA gated off at :144) | no | WNBA: a preseason game counts as a team game |
| game Elo / rolling | vendor cli.py:12302-12372; features.py; scrape_nba_api.py:96,183 | regular-season source | preseason slates get end-of-last-season features |
| market anchor | vendor sim/quarters.py:218-252 | no | same weights every phase |
| team advanced stats | vendor advanced_stats_boxscores.py:150-162 | no | preseason included |
| props bias calibration 7/30 days, totals calibration | refresh_nba_oddsapi_props.py:2998-2999; vendor props_calibration.py:50,187; cli.py:11017 | no | preseason inside the windows after the opener |
| skill registry / optimizer | measured_market_skill.py:117; daily_optimizer.py:14 | phase = pregame/live only | NBA preseason and regular season would share a cell |

**Live consequence (measured 2026-10-05 ~22:05Z).** Layer 2 prices NBA game lines from the raw smart-sim score
histogram (`nba_game_projections.py:274-291`), which is not market-anchored.
- On the 10-05/06 slates the sim's home margin is 4-6 pts more lopsided than the market in 5 of 6 games, and its
  totals are 1-11 pts higher.
- The served board's NBA rows showed +15.5 (spread, 0.57 vs fair 0.415) and +10.4 (ML, 0.67 vs 0.566) points of
  edge.
- Preseason games already graded (ESPN finals): MIA@TOR sim −0.7/233.8 vs −24/234; UTA@DEN +6.5/241.7 vs −12/206;
  GSW@LAC −3.1/232.4 vs +3/205.
- Even in the 2025-26 regular season, the raw sim's OOS weight vs the line was 0.00 (margin) / 0.05 (total).
- The user chose "blend to market, build it" (pre-registered H-G1 in lanes.md).

## NBA availability (K=2), engine re-run, paired: H-A3 MET; still no information beyond the book `[2026-10-06, e0a3e383]`

**Substrate.**
- `scripts/resim_nba_availability.py` (9d60ef66): today's engine re-run as-of per date, twice, identical except
  for the rule (scratch code copy; roster mode forced to pregame).
- Base arm: availability off. Avail arm: K=2, i.e. left out if absent from the team's last 2 games, read from
  regular-season player_logs.
- **42 dates (2026-03-01..04-12), 334 games, 500 sims, 0 errors.**
- Paired on (date, game, player) for players who played: **6,488 rows**. Book lines: the OddsAPI backfill, pre-tip,
  two-sided, de-vigged; 149,677 lines scored.
- **No pregame injury feed in either arm**: none exists before 2026-09-30. This measures the no-injury-feed case;
  production has had injury exclusions working since 10-04/05.
- Scored with `score` -> C:\tmp\nba_bt\availability_compare.json.

**H-A3 (pre-registered b02481a4) -- MET on all three gates.**

| measure | base | K=2 | paired diff [95% CI, game-clustered] |
|---|---|---|---|
| (a) played-player minutes MAE | 7.39 | 5.47 | **−1.92 [−2.08, −1.76]** |
| minutes bias | −6.10 | −2.36 | +3.74 [+3.54, +3.93] |
| (b) sim minutes to NON-players / team-game | 67.4 / 240 | 38.0 / 240 | — |

**(c) Brier at the de-vigged book line** (no market worse):

| market | lines | base | K=2 | diff [CI] | book | K=2 − book [CI] |
|---|---|---|---|---|---|---|
| pts | 49,527 | 0.3042 | 0.2784 | −0.0257 [−0.0304, −0.0214] | 0.2426 | +0.0358 [+0.0299, +0.0421] |
| pra | 29,983 | 0.3275 | 0.2922 | −0.0352 [−0.0405, −0.0299] | 0.2474 | +0.0448 [+0.0370, +0.0529] |
| reb | 27,396 | 0.2829 | 0.2695 | −0.0134 [−0.0173, −0.0095] | 0.2441 | +0.0254 [+0.0203, +0.0308] |
| threes | 19,444 | 0.2621 | 0.2556 | −0.0065 [−0.0102, −0.0029] | 0.2417 | +0.0138 [+0.0098, +0.0178] |
| ast | 18,040 | 0.3119 | 0.2907 | −0.0212 [−0.0251, −0.0176] | 0.2434 | +0.0473 [+0.0392, +0.0554] |
| blk | 3,506 | 0.2451 | 0.2409 | −0.0042 [−0.0061, −0.0025] | 0.2176 | +0.0233 [+0.0148, +0.0325] |
| stl | 1,781 | 0.2449 | 0.2440 | −0.0009 [−0.0050, +0.0032] | 0.2317 | +0.0122 [+0.0058, +0.0187] |

**Prop mean MAE** (reported, not a gate): pts −0.36 [−0.43, −0.30], pra −0.81 [−0.91, −0.70], reb −0.10, ast −0.07;
**threes +0.009 [+0.002, +0.016] (worse)**, as in WNBA (more minutes means more attempts).

**Costs and limits, stated with the result.**
- **Coverage.** The rule drops **539 player-games of players who DID play** (7,302 actual minutes, ~13.5 each). That is
  7.7% of played player-games, and those players get no projection at all. It adds only 2. The paired rows exclude
  those 539 by construction, so the gains above are on the players BOTH arms project.
- **Still worse than the book in every market** (K=2 − book CI > 0 everywhere). Better minutes do not make the model
  carry information beyond the line. With the served blend at w ≈ 0, the per-line served probability is unchanged; the
  gain is in the projected means/minutes the board shows.
- **No injury feed.** The base arm's non-player minutes (67.4) exceed the committed production sims' 44.5 because
  production then had partial exclusions. With the 10-04/05 injury fixes the real gain will be smaller. Measure it on
  production 2026-27 sims.
- Regular season only (March–April). Not measured: preseason (where rest is the norm and the rule is not applied, per
  the design) or the postseason.

**Next, per the pre-registration:** refit the per-line book-blend weight on the K=2 arm (does w rise above ~0?), and
decide on wiring K=2 for NBA (file switch, regular season only) with the coverage cost made visible.

