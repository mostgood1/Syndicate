# Basketball (WNBA + NBA) same-game-parlay correlations — box scores + REAL book lines — 2026-10-17

Lane `basketball-sgp-builder`. The worker agent for session 9e18a0e7 wrote `scripts/build_basketball_sgp_correlations.py` (commit e0eb9b65, landed by cherry-pick). It imports the NFL estimator (`fit_rho`, `shrink_cells`, `clustered_se`, `four_cell`) and the NHL pair machinery; it copies neither.
- Tests: `tests/test_basketball_sgp_correlations.py` (23 pass).
- Fleet runs at nice 19: WNBA 4m54s at 0.97 GB; NBA 22m42s at 2.86 GB.
- Outputs, in `/tmp/basketball_sgp/<sport>/`:
  - `<sport>_sgp_correlations.json` — the REAL-LINE fit.
  - `<sport>_sgp_correlations_proxy.json` — the box-score proxy fit, carrying the full out-of-sample tables, the audit and the engine read.
- Every cell resolves to its own value through `nfl.sgp.rho_for` (0 mismatches).
- `nested_same_player`: 12 contained pairs.

## PUBLISHED (session 9e18a0e7, 2026-10-17 2:09 PM CT)

**Files.** The real-line files went to `<data root>/<sport>_source/sgp/<sport>_sgp_correlations.json` with `cells.type` EMPTIED.
- WNBA: source sha256 73807e1bfa6841f3; 682 role cells removed, 88 market cells kept.
- NBA: source sha256 d5a6b69a96c68c93; 6,808 role cells removed, 143 market cells kept.
- Each file carries a `published_note` field saying so.

**Why the role cells were removed.**
- `shrink_cells` shrinks toward 0, and `rho_for` returns the role cell first, so a role cell shrunk to 0 hides its live market cell.
- The masking was severe: 272 of 284 WNBA teammate role cells (95% of those pairs) and 3,464 of 3,471 NBA opponent role cells (100%).
- In test C, market cells alone score as well as role + market cells, or better, for every NBA relation. The WNBA C fit is market-only by construction.
- Removing them also sidesteps the mismatch between the fit's role rule and the runtime's (`basketball_sgp_pool.roles`).

**Runtime change.** Two combos of one player that share a part are never one ticket: P+A x P+R +0.92, P+R x R+A +0.48 (commit b67ff316).

**First served.** WNBA ATL @ GSV: 3 tiered parlays at 2:09 PM CT.
- Two "Higher hit rate" 3-leg tickets at 64% and 66%.
- One 4-leg "Bigger payout" ticket at 54%.
- All at rho level `market`; the joint is within 1 point of independence.

## Falsification line (stated in the script before any run)

- A relation is MEASURED only if its out-of-sample gain is below zero at |z| >= 2.
- Otherwise every cell of that relation is set to rho 0 (the fitted value is kept as `rho_fitted`).
- Each file is judged on its own test: A for the proxy file, C for the real-line file.

## Data (production data root)

**Box scores, regular season** (All-Star games are labelled `regular` in the ESPN logs; they were dropped):

| league | season | games | player-games |
|---|---|---|---|
| WNBA | 2024 | 241 | 4,513 |
| WNBA | 2025 | 287 | 5,410 |
| WNBA | 2026 | 331 | 6,584 |
| NBA | 2024-25 | 1,231 | 26,231 |
| NBA | 2025-26 | 1,231 | 26,565 |

**Real book lines:**

| | WNBA 2026 | NBA 2025-26 |
|---|---|---|
| source | `backfill/wnba_props_2026/odds` | `backfill/nba_props_2025_26/asof/props_odds_hist` |
| snapshot | ~14 min pregame | ~49 min pregame |
| games | 326 | 1,208 |
| books / markets | 5 / 8 | 8 / 10 |
| legs graded | 18,606 | 146,346 |
| pairs | 527 k | 8.78 M |

**Roles:** each team's players ranked by average minutes over its last 8 earlier games, S1-S5 then B1-B3. The S1-S5 slots match ESPN's starter flag 83-88% of the time.

## Out of sample (nats/pair, negative = the copula beats independence; z is clustered by game)

- **A:** proxy cells fitted on earlier seasons, scored on the latest season.
- **B:** A's cells scored on real book lines.
- **C:** real-line cells fitted on one half of the season, scored on the other half. C governs the published real-line file.

**WNBA**

| relation | A shrunk | B | C |
|---|---|---|---|
| same player | -0.0303 (z -26.7) | -0.0536 (-19.8) | -0.0550 (-13.9) |
| teammate | -0.00006 (-3.3) | -0.00014 (-2.6) | -0.00010 (-2.6) — FRAGILE |
| opponent | -0.000001 (-2.5) | 0.0 (+0.6) | +0.000004 (+0.1) — NO MEASURED CORRELATION |

**NBA**

| relation | A shrunk | B | C | C, market cells only |
|---|---|---|---|---|
| same player | -0.0322 (-50.8) | -0.0349 (-44.1) | -0.0345 (-35.0) | -0.0348 (-33.7) |
| teammate | -0.00011 (-8.3) | +0.00003 (+1.9) | -0.00005 (-4.7) | -0.00014 (-5.3) |
| opponent | 0 | 0.0 | -0.000002 (-2.5) | -0.00001 (-3.6) |

**Notes on the verdicts:**
- **WNBA teammates are fragile.** A run with 137 fewer legs read "no measured".
- **NBA proxy teammate cells FAIL on real lines (B).** Books price the common shocks; see the engine read.
- **Effect sizes:** teammates ~1e-4 nats/pair, 10-25x below NHL; same player 0.03-0.055.

## Calibration (C, both-over: predicted / realised / independent)

- WNBA: same player 0.298 / 0.297 / 0.238; teammate 0.242 / 0.239 / 0.241.
- NBA: same player 0.271 / 0.253 / 0.227; teammate 0.235 / 0.218 / 0.235.
- The NBA level gap comes from book overs realising below the de-vigged fair price, not from the correlation.

## Strongest market cells (real fit; proxy in brackets)

**Same player:**

| pair | NBA | WNBA |
|---|---|---|
| PA x PR (near-duplicate; now excluded) | +0.917 | +0.909 |
| FG3M x PTS | +0.717 | +0.730 |
| FG3M x PRA | +0.625 | +0.613 |
| PTS x REB | +0.236 [+0.306] | +0.198 [+0.302] |
| AST x PTS | +0.150 | +0.135 |

**Teammates:**
- NBA PTS x PTS -0.061 [proxy +0.005].
- NBA PRA x PRA -0.037.
- AST x PTS: NBA +0.033, WNBA +0.080.

**Opponents:** about 0.

## Engine read

1. **Teammates compete for points once the book's information is in.**
   - At book lines, NBA teammate PTS x PTS is -0.061; in raw residuals it is +0.020.
   - The positive raw number is common shocks: blowouts, rest, who is out.
   - A sim conditioned on the projected rotation should show a NEGATIVE teammate points correlation. Check the basketball engine's joint draws.
2. **Assists feed teammates' points** (+0.03 to +0.08 at every level).
3. **Lines are set on recency.** Book combo lines sit above the season-to-date mean and still realise at or below 50% (PRA +0.55).
4. **NBA 2025-26 overs realise below de-vigged fair in all 10 markets** (z -2.1 to -5.7).
   - WNBA 2026 shows the same in REB, AST and FG3M.
   - So the SGP builder's market-anchored leg probability on overs is about 1-2 points rich.
   - That is UNVERIFIED for the high-probability alt rungs the tiers use. The tier grades will tell (owed).

## Anomalies

- All-Star games are labelled `regular` (form10 and the ladders may include them).
- WNBA 2026: Nia Coffey (MIN) and Megan Gustafson (POR) appear in book lines (33 and 34 games) but not in the regular-season game log. UNVERIFIED which side is wrong.
- Name forms are fixed in the script: Diggins / Diggins-Smith, Bub / Carlton Carrington, and a namesake guard.

## Follow-ups (NOT done)

1. Fix the shrinkage properly: shrink each role cell toward its market cell, then re-run out of sample for NFL, NHL and basketball. Only then restore role cells.
2. Re-test the WNBA teammate verdict on 2027 lines.
3. Align the role rule: the runtime's sum over the last 8 games vs the fit's average over games played, re-ranked. It is moot while `cells.type` is empty.
4. Check the two missing WNBA players against ESPN.
5. Check the basketball engine's teammate PTS x PTS sign at a fixed rotation.
6. Postseason was not studied; there are no SGP prices to study.
7. Grade the tiers per sport; this is the over-side richness check.
