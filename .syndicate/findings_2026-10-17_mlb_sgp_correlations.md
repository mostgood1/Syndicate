# MLB same-game-parlay correlations — game logs 2023-25 (proxy lines) + REAL 2026 book lines — 2026-10-17

Lane `basketball-sgp-builder` (the all-sports SGP lane; worker agent for session 9e18a0e7, reviewed and landed by it).
Script `scripts/build_mlb_sgp_correlations.py`: the NFL estimator (`fit_rho`, `shrink_cells`, `clustered_se`,
`four_cell`) and the NHL pair / lookup machinery (`build_pairs`, `lookup_rho`, `attach_marginals`, `consensus_legs`)
are IMPORTED, not copied. Tests `tests/test_mlb_sgp_correlations.py` (21, synthetic). Agent commit `ee10f5ae`, landed
by cherry-pick. Ran on the fleet at nice 19 and `oom_score_adj 1000`: **19m09s wall (1:12-1:32 PM CT), peak RSS 3.25 GB**.
Outputs:
- `/tmp/mlb_sgp/mlb_sgp_correlations.json` is the file published. It is the proxy fit over 2023-25: 11 markets, 149 market cells.
- `_real_lines.json` is kept for reference. It is the 2026 real-line fit: 3 markets, 12 cells.

## Schema (what the runtime reads)

- **Cells.** `cells.type` is empty. `cells.market["A~B~relation"]` is read by `nfl.sgp.rho_for` for legs typed `MARKET|UNK`.
- **Key order.** Keys follow `rho_for`'s own ordering, the two `market|UNK` strings sorted.
- **Lookups.** All 149 cells resolve in both argument orders. The 38 combinations with no cell cannot occur: a batter market and a pitcher market for the same player, or two pitchers as teammates.
- **Market names.** Batter markets use the sheet's names. Pitcher markets use the board's bare names: `strikeouts`, `hits_allowed`, `earned_runs`, `outs`.
- **`nested_same_player`.** Eight pairs where one stat contains the other: hits~TB, hits~HRR, RBI~HRR, runs~HRR, HR~TB, HR~RBI, HR~runs, HR~HRR. Their fitted cells are +0.88 to +0.95, and they are never paired (`mlb_sgp_pool.exclude`).

## Data (coverage stated)

- **Scope.** Regular season only. A hitter-game needs PA >= 2, the "started" proxy: PA 0 is a defensive sub, PA 1 mostly a pinch hit. Pitchers are starters only.
- **Lines.** A leg needs >= 5 earlier games, and its line is the prior median rounded to x.5.

| season | games | started hitter-games | per team-game | SP starts | SP per game | legs |
|---|---|---|---|---|---|---|
| 2023 | 2,430 | 32,202 | 6.63 | 3,426 | 1.41 | 222,308 |
| 2024 | 2,429 | 36,845 | 7.58 | 3,806 | 1.57 | 253,433 |
| 2025 | 2,430 | 41,434 | 8.53 | 4,314 | 1.78 | 284,348 |
| 2026 | 2,429 | 45,540 | 9.37 | 4,858 | 2.00 | 310,259 |

Pairs: 24.50 M to train (2023-24), 17.26 M held out (2025), and 41.76 M in the published 2023-25 fit.

**Real 2026 pregame lines exist** in `backfill/mlb_props_2026/odds/<game_pk>.json`: one snapshot about 10 minutes before first pitch, 9 books, 3 markets (hits, total bases, pitcher strikeouts).
- 2,369 games, 88,593 legs graded, 1.62 M pairs.
- Of 92,414 legs: 1.4% were on hitters with PA < 2 and 2.6% were not in the log.

## Out of sample

Nats per pair; negative means the copula beats independence; z is clustered by game.
- **A:** proxy fit 2023-24, scored on 2025.
- **B:** proxy cells from 2023-25, scored on 2026 real lines.
- **C:** real lines, fit on 2026 H1, scored on H2.

| relation | A | B | C |
|---|---|---|---|
| all | -0.00695 (z -70.5) | -0.0113 (-146) | -0.00043 (-6.4) |
| same player, not nested | **-0.0648 (-80.0)** | — | — |
| teammate | **-0.00210 (-16.4)** | -0.00065 (-6.1) | -0.00065 (-5.5) |
| - batter x batter | -0.00232 (-16.4) | -0.00073 (-6.1) | -0.00073 (-5.6) |
| - SP x own batters | -0.000009 (-0.4) | -0.00001 (-0.3) | +0.00008 (+1.2) |
| opponent | **-0.00098 (-19.7)** | -0.00027 (-7.8) | -0.00027 (-4.9) |
| - SP x opposing batters | -0.0116 (-20.2) | -0.0028 (-7.8) | -0.0028 (-4.9) |
| - batter x batter | -0.000001 (-0.3) | -0.000001 (-0.3) | +0.000001 (+0.5) |
| - SP x SP | -0.00003 (-0.2) | -0.00025 (-1.5) | -0.00041 (-1.9) |

- **Pre-stated falsification**, judged per relation on test A: same player z -80.0, teammate -16.4, opponent -19.7. **All three are measured; 0 cells were zeroed.**
- **Classes with no measured gain:** SP x own batters, batter x batter opponents, and SP x SP. Their cells are near 0, so they price as about independent.
- **The proxy fit transfers to real lines.** On the same 2026 H2 pairs, proxy cells vs real-line cells give teammate -0.000669 vs -0.000647, opponent -0.000264 vs -0.000265.

## Calibration: both-over, predicted vs realised (independent in brackets)

**2025:**
- same player, not nested: 0.2003 vs 0.1989 (0.1610)
- teammate: 0.1573 vs 0.1569 (0.1483)
- opponent: 0.1490 vs 0.1466 (0.1479)
- SP x opposing batters: 0.1998 vs 0.1961 (0.1912)

**2026 real lines:**
- teammate: 0.2831 vs 0.2815 (0.2737)
- opponent: 0.2725 vs 0.2716

## Strongest cells

- **Same player:**
  - Batter: RBI x TB +0.73, runs x TB +0.69, hits x RBI +0.66; batter K x hits -0.25.
  - Starter: ER x hits allowed +0.68, ER x outs -0.50, K x outs +0.40.
- **Teammates:** RBI x runs +0.22, HRR x runs +0.21, runs x runs +0.20. Hits x hits is only +0.07.
- **SP x opposing batters:**
  - ER x runs +0.44, ER x HRR +0.40.
  - Hits allowed x HRR +0.33.
  - Outs x runs -0.31.
  - K x batter K +0.22, K x hits -0.10.

## Engine read

1. **Runs are shared, hits are not.** Teammate runs/RBI cells run 0.20-0.22 against hits x hits at 0.07. A per-batter independent prop model prices teammate RBI x runs at 0.
2. **The starter's exit reacts to his line.** Outs x opposing runs is -0.31, and ER x outs is -0.50. The sim has the mechanisms (the pitch-count hook and the shelled rule), but their STRENGTH is unmeasured.
3. **Bullpen dilution.** Hits allowed x an opposing batter's hits is only +0.31.
4. **No shared run environment across lineups.** Batter x batter opponents is about 0.
5. **Game logs are incomplete before 2026.** Started hitters per team-game run 6.63 / 7.58 / 8.53 / 9.37 for 2023-26. That leaves per-pair rho unbiased, but the marginals carry survivorship.
6. **Books are calibrated on these markets.** Hits: fair 0.5638 vs realised 0.5651. TB: 0.4853 vs 0.4833. Pitcher K: 0.4945 vs 0.4850 (not significant).
7. **Inherited shrinkage defect.** `shrink_cells` shrinks toward 0, but the effect is immaterial here. Its failure mode shows in the real-line file: a relation with a single cell gets shrunk to 0.

## Review (session 9e18a0e7)

- **Published:** the proxy file goes to `<data root>/mlb_source/sgp/mlb_sgp_correlations.json`, the path `mlb_sgp_pool.load_cells` reads.
- **Pool vs fit, PA rule.** The pool's hitter history now uses the same PA >= 2 rule as the fit (aligned at landing).
- **Pool vs fit, postseason.** The pool's last-10 includes postseason games; the fit is regular season only. These are regular-season cells applied in the 2026 postseason (follow-up 5).

## Follow-ups (not done)

1. Compute these cells from the MLB sim's own draws: outs x opposing runs, ER x outs, teammate RBI x runs, K x batter K.
2. Class-level falsification: zero the three near-0 classes if a class-level rule is adopted.
3. Backfill the missing 2023-25 players, or refit on 2025-26.
4. Score the cells on postseason games (about 700 hitter-games a season).
5. Chunk `score_pairs` to cut about 1 GB of peak memory.
