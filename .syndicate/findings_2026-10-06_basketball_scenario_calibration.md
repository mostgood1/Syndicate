# Basketball scenario calibration (shared NBA/WNBA SmartSim; NCAAB real rates) — lane `basketball-scenario-calibration`

Opened 2026-10-06, session e0a3e383. User decisions (2026-10-06, in chat):
- "TAKE A LOOK AT the MLB backtest session ... Do the same for NBA/WNBA/NCAAB".
- Scope: the **NBA+WNBA engine, with NCAAB real rates only** (no in-repo NCAAB sim exists).
- Targets: **periods + live + props**. Full-game served probabilities are already pinned near the market (NBA
  per-line blend, WNBA anchor).

## Method (ported from `mlb-combined-calibration` / `football-scenario-calibration`)

1. Pre-register each scenario here BEFORE measuring: population, formula, CI, decision rule.
2. REAL rate from ESPN play-by-play / box scores on FIT games only.
3. SIM rate from production's own engine on the SAME FIT games, unmodified:
   - an as-of re-run (`scripts/resim_nba_availability.py`-style scratch harness, roster mode forced pregame);
   - a per-draw recorder extending `basketball_props_smart_sim._recording_sim_draws_local`, which keeps each draw's
     team box, per-quarter points, OT points, and `EventSimConfig.record_events` per-quarter event types.
   No engine code is modified to measure.
4. Reachability before correctness: any lever is shown `off != on` on one game before use.
5. Each mechanism is default-off and byte-identical (seeded sha256 of real output) + tests.
6. RARITY FLOOR (MLB amendment 10/11): a scenario with < 10 real events in FIT gets no mechanism; it is recorded as
   unmodelled.
7. Measured rates are FIXED in every arm; the rates that were absorbing them are jointly re-fit
   (`model_engine_standard.md` §4.4).
8. VALIDATION is read ONCE. Ship only if every gate clears its own SE.

## Splits (fixed now, before any reading)

| league | FIT | VALIDATION (read once) |
|---|---|---|
| NBA | 2025-26 regular season 2025-11-01..2026-02-28 (October left out: as-of inputs too thin) | 2026-03-01..2026-04-12 regular + 2026 play-in/playoffs |
| WNBA | 2026 regular season before 2026-08-01 (the `wnba-sim-availability` split) | 2026-08-01 onward (regular + playoffs) |
| NCAAB | 2025-26 season (real rates only; no gate) | — |

**Sim side:** 200 draws per game (production uses 500; 200 bounds compute -- the per-draw SE is reported). Production
config as of HEAD, with every live switch as on the fleet (NBA: prop calibration, availability; WNBA: availability,
rate shrink, shape, dispersion).

## Phase 1 — PRE-REGISTERED 2026-10-06 (before any measurement): real-vs-sim scenario table

No engine change in Phase 1. Output: one row per (league, scenario, bucket) with:
- real rate, sim rate, n (real games/events);
- 95% CI by GAME-clustered bootstrap (1000 reps) on the real side;
- sim SE from game-clustered bootstrap over the per-game sim means;
- the gap.

| id | scenario | metric (both sides) | buckets |
|---|---|---|---|
| S1 | pace | possessions per team-game = FGA + 0.44·FTA + TOV − OREB | overall; by tercile of the as-of matchup pace the sim received |
| S2 | quarter shares | share of the game total scored in Q1..Q4 | overall; by game state entering Q4 (|margin| ≤ 8 / 9-17 / ≥ 18 NBA, ≥ 15 WNBA) |
| S3 | quarter volatility | SD of quarter totals; corr(Q_i, Q_{i+1}) of team-quarter points | per quarter |
| S4 | half split | H1 share of the total; H2 − H1 points | overall |
| S5 | blowout incidence | P(|margin| ≥ 18 NBA / ≥ 15 WNBA entering Q4); Q4 total in those games | by |pregame spread| bucket (0-4, 4.5-8, 8.5+) |
| S6 | late free throws | Q4 FTA per game; Q4 FTA share of game FTA | Q4 entered within 6 vs not |
| S7 | overtime | P(tied after regulation) | by |pregame spread| bucket |
| S8 | game spread | SD of final total and of final margin, residual to the pregame line | overall |
| S9 | three-point volume | 3PA per team-game; Q4 3PA share | overall; trailing team in close Q4 |
| S10 | starter minutes vs game script | minutes of each team's top-5 (by as-of minutes) | final |margin| ≤ 6 / 7-19 / ≥ 20 |
| S11 | foul-outs | P(player-game ends with 6 PF NBA / 6 PF WNBA); minutes of those players | rarity floor applies |
| S12 | back-to-back | team points and pace on the 2nd night vs rested | — |

**S10 is structural:** sim minutes are an INPUT (`_sim_min`), constant across draws. The sim side is the input
minutes split by the draw's final margin. A gap is expected and is a mechanism candidate, not a parameter.

**Decision rule (fixed):** a scenario-bucket is FLAGGED when the sim rate lies outside the real 95% CI AND the
implied effect on a target exceeds its materiality threshold:
- **quarter total:** ≥ 0.5 pts NBA / 0.4 WNBA;
- **half total:** ≥ 0.8 / 0.6;
- **game total:** ≥ 1.0 / 0.8;
- **starter minutes:** ≥ 1.0 min.

Flagged rows are ranked by effect and become Phase 2 candidates, each pre-registered separately. A row inside the CI
is recorded EXONERATED for this engine version.

**NCAAB (real-only table):** S1 pace, S4 half split (2 halves), S6 late FTs (last 4:00 of H2 within 6), S7 OT, S8
spread, S9 3PA, S11 foul-outs (5 PF), all for the 2025-26 season from ESPN mens-college-basketball summaries. It is
recorded as groundwork; there is no gate and no mechanism.

## Pre-measurement amendments (2026-10-06 ~22:00Z, BEFORE any sim measurement or any real-vs-sim comparison)

1. **S1 pace formula.** The sim's per-draw team box has FGA, FTA, TOV, 3PA and PF but NO offensive rebounds
   (`events.py` `finalize`). S1 is therefore FGA + 0.44·FTA + TOV (shot + turnover volume) on BOTH sides, not the
   pre-registered − OREB form. The real side also reports the full formula for reference (not compared).
2. **S6 / S9 fourth-quarter parts are real-only.** Recorded sim events are truncated at 500 per game
   (`events.py:986`, `events[:500]`), which cuts off Q4. Without modifying the engine there is no sim-side Q4
   FTA/3PA. S6 and S9 compare game-level FTA and 3PA per team-game; their Q4 rows are reported real-only. The
   engine has no intentional-foul free throws at all, so S6's late-game row is a structural mechanism candidate
   regardless.
3. **Real-side lines.** ESPN summaries carry no odds after the final. The pregame spread/total for the spread
   buckets comes from the OddsAPI pre-tip game-line backfill (NBA: C:	mp
ba_bt\out\cache\oddsapi_hist\games;
   WNBA: C:	mp\wnba_bt\odds_hist), joined by date + teams.
4. **Extraction counts (FIT only; validation NOT extracted):** NBA 816 games (2025-11-01..2026-02-28), WNBA 217
   games (2026-05-01..07-31), 0 fetch failures.

## Readings

(none yet)

### NBA Phase 1 reading `[2026-10-07 ~14:30Z, e0a3e383]`

**Substrate.**
- REAL: 816 ESPN games, 2025-11-01..2026-02-28 (regular season).
- SIM: production engine re-run as-of, code 6a666e71 + the fleet's prop-calibration and availability switch files,
  200 draws per game, 109 dates.
- **791 games paired** (25 real games had no sim: missing as-of inputs or props snapshot), all 791 with a pre-tip
  line.
- Validation NOT extracted or read. Output: C:\tmp\bball_sc\table_nba_2025-11-01_2026-02-28.json.

| id | scenario | bucket | n | real [95% CI] | sim | gap | effect | verdict |
|---|---|---|---|---|---|---|---|---|
| S1 | FGA+0.44FTA+TOV per team-game | all | 791 | 114.0 [113.6, 114.5] | 119.6 | **+5.6** | volume, not points* | **FLAG** (props/live volume) |
| S2 | Q1 share | all | 791 | 0.2546 [0.2524, 0.2567] | 0.2509 | −0.0036 | −0.83 pts | **FLAG** |
| S2 | Q2 share | all | 791 | 0.2505 [0.2484, 0.2527] | 0.2512 | +0.0007 | +0.16 | EXONERATED (all 4 buckets inside or ≤ 0.53) |
| S2 | Q3 share | all | 791 | 0.2538 [0.2515, 0.2561] | 0.2493 | −0.0045 | −1.04 pts | **FLAG** |
| S2 | Q4 share | all | 791 | 0.2411 [0.2389, 0.2435] | 0.2486 | +0.0075 | **+1.71 pts** | **FLAG** |
| S2 | Q4 share | entering Q4 within 8 | 366 | 0.2405 [0.2369, 0.2438] | 0.2512 | +0.0108 | **+2.47 pts** | **FLAG** |
| S2 | Q4 share | entering Q4 by 18+ | 182 | 0.2377 [0.2332, 0.2426] | 0.2451 | +0.0074 | +1.69 pts | **FLAG** |
| S3 | SD of quarter total | Q1..Q4 | 791 | 8.48 / 8.49 / 8.73 / 8.89 | 9.64 / 9.69 / 9.67 / 9.68 | **+0.8..+1.2** | pts | **FLAG** (all four) |
| S4 | H1 share | all | 791 | 0.5050 [0.5024, 0.5077] | 0.5021 | −0.0029 | −0.67 pts | outside CI, below 0.8 -> not flagged |
| S5 | P(margin ≥ 18 entering Q4) | all | 791 | 0.230 [0.202, 0.260] | 0.348 | **+0.118** | (drives S8/S10) | **FLAG** |
| S5 | same | spread 0-4 / 4.5-8 / 8.5+ | 267/275/249 | 0.180 / 0.171 / 0.349 | 0.286 / 0.328 / 0.436 | +0.11 / +0.16 / +0.09 | | **FLAG** (every bucket) |
| S6 | FTA per team-game | all | 791 | 23.35 [22.95, 23.76] | 20.91 | **−2.44** | −1.9 pts/team | **FLAG** |
| S7 | P(tied after regulation) | all | 791 | 0.0455 [0.0329, 0.0594] | 0.0173 | −0.028 | ~−0.6 pts game total | outside CI, below 1.0 -> not flagged alone (see S8) |
| S8 | SD(final total − total line) | all | 791 | 18.29 [17.42, 19.21] | 20.19 | +1.9 | pts | **FLAG** |
| S8 | SD(final margin + home spread) | all | 791 | 14.00 [13.19, 14.71] | **19.38** | **+5.38** | pts | **FLAG** (largest) |
| S9 | 3PA per team-game | all | 791 | 37.00 [36.68, 37.33] | 39.42 | +2.43 | threes props | **FLAG** (props) |
| S10 | top-5 minutes | final margin ≤ 6 | 242 | 31.32 [30.98, 31.61] | 29.73 | −1.58 | min | **FLAG** |
| S10 | top-5 minutes | final margin ≥ 20 | 156 | 26.87 [26.49, 27.26] | 29.73 | **+2.87** | min | **FLAG** |
| S11 | foul-outs (≥ 6 PF) per game | all | 791 | 0.193 [0.162, 0.226] | 0.360 | +0.17 | (PF too high) | **FLAG** (see S6) |

*S1's sim points are anchored to the target, so the volume gap shows up as LOWER efficiency on MORE plays, not as
more points. It matters for FGA/3PA props and the live clock, not the game total.

**What the table says, by root cause (Phase 2 candidates, ranked by effect; each pre-registered separately):**
1. **Too much game-to-game spread.**
   - Final margin SD is 19.4 vs 14.0 around the spread (the largest gap), and the total SD 20.2 vs 18.3.
   - Every quarter's SD is about 1 pt wide.
   - Blowouts entering Q4 are 35% vs 23%.
   - OT is too rare (1.7% vs 4.6%), which is the same symptom: a wide margin distribution has less mass at zero.
   - The engine stacks jitter that the real game does not have: a per-quarter environment draw `q_env_mult` clipped
     0.82-1.22, a ±6% possession-count draw, and the stress term on quarter sigma.
   - Mechanism candidate: shrink those jitters (default-off scale factors), measured against S3/S5/S8.
2. **Quarter shares are hardcoded wrong.**
   - Real ≈ .255 / .250 / .254 / .241; the engine's split is .245/.245/.255/.255.
   - Q4 runs +1.7 pts hot (+2.5 in close games), Q1 and Q3 run cold.
   - This is the period-line target directly; a share refit is a fitted-constant change, not a mechanism.
3. **Free throws too low while fouls run too high.**
   - FTA is −2.4 per team while foul-outs are nearly double: the engine's non-shooting fouls award nothing (no bonus)
     and there is no late intentional fouling (code, `events.py:1492`).
   - Mechanism candidate: a bonus rule (team fouls per period -> FTs) plus late-game intentional fouls, measured on
     S6/S11 and the real-only Q4 FTA row.
4. **Minutes do not respond to game script.**
   - Starters play 31.3 min in close games and 26.9 in 20+ blowouts; the sim gives 29.7 in both (minutes are an
     input).
   - Mechanism candidate: scale each draw's top-rotation minutes by its own margin path (props target). It interacts
     with #1, since too many sim blowouts would over-apply it, so it goes after #1.
5. **Volume composition.** +5.6 shots+TOs and +2.4 3PA per team at lower efficiency: the per-player rate priors and
   the pace term. Props target (FGA/threes); re-fit after #1-#3.

Not flagged:
- S2 Q2 (EXONERATED);
- S4 (outside the CI, below the half threshold);
- S7 alone (below materiality; it moves with #1).

S12 (back-to-back) was not computed: it needs the schedule join -- owed.

## Phase 2 #1 — SPREAD JITTER, PRE-REGISTERED 2026-10-07 ~15:10Z (user: "Spread jitter first"), BEFORE any engine change

**Diagnosis already measured (NBA FIT sims, 794 games with lines):**
- The sim's margin dispersion around the spread (19.4) is mostly WITHIN-game: the draw SD of the final margin is
  **18.2**. Only 6.7 is between-game mis-centring of the sim mean vs the line (offset −0.6).
- Total: within-game 19.3, between-game 6.1.
- NOT the driver:
  - **per-draw targets:** fixed per game (`smart_sim.py:3735`);
  - **team volume difference:** sim within-game SD 8.05 plays vs real 7.12 (real true-possession difference SD
    3.0).
- So the excess is possession-level randomness inside `events.py::simulate_pbp_game_boxscore`.

**Levers (each a NEW `EventSimConfig` field, default = today's hardcoded value, so unset == byte-identical):**
- L1 `possession_alternation` (default 0.85, `events.py:1323`): the probability the next possession switches to the
  other team. Today the other 15% is a coin flip, an unrealistic source of possession imbalance. Real possessions
  alternate; offensive rebounds extend inside a possession (already modelled).
- L2 `env_sd_scale` (default 0.65, `events.py:1786`): the scale of the per-quarter environment random draw
  `q_sd_mult`.
- L3 `possessions_jitter` (already a config field, 0.06): the per-quarter possession-count draw.
- The same fields go in the WNBA engine copy (`vendor/wnba_betting_repo/.../sim/events.py`). Vendor edits also go
  upstream (CLAUDE.md: a vendor-only fix is reverted by the next re-pull).

**Measurement protocol:**
1. Byte-identical proof first: seeded sha256 of real output on a fixed 3-game NBA fixture, fields unset vs HEAD.
2. Reachability: L1 = 1.0 vs default on one game changes the margin SD (off != on).
3. **Lever sweep on a FIXED FIT subsample: 12 FIT dates chosen by seed 7 (all games on them), 200 draws, the Phase-1
   harness.** Each lever is moved alone over a pre-set grid:
   - L1 ∈ {0.85, 0.95, 1.0};
   - L2 ∈ {0.65, 0.4, 0.2, 0.0};
   - L3 ∈ {0.06, 0.03, 0.0}.
   Each point reports within-game margin SD, S8 margin/total SD, S3 quarter SDs, S5 blowout rate, S7 OT rate.
4. **Joint fit:** over the product of the grid points that moved the targets, choose the config minimising
   Σ ((sim − real) / real CI half-width)² over S3 (4 rows), S5 (all), S8 (2 rows), S7 (all) on the subsample.
   The quarter-share rows (S2) are NOT in this objective: that is Phase 2 #2.
5. Re-run the FULL FIT window with the chosen config; the Phase-1 table must show S8 margin SD inside or nearer
   the real CI with no S2/S6/S9 row moving by more than its own SE.
6. VALIDATION is not read here; it is read once at the end of Phase 2, for the combined config.

**Refuted if:** no lever setting brings within-game margin SD below 16.0 on the subsample (the excess is then
elsewhere: shot-level or lineup randomness, to be diagnosed next) -> L1-L3 recorded as EXONERATED as the driver.

## Phase 2 #1 — RESULT 2026-10-07 (read once, against the pre-registration above)

- **Sweep:** 12 seed-7 FIT dates, 87 games, 200 draws, each lever moved alone.
  - Every point paired 87/87 games with the baseline.
  - Every engine call carried the lever (harness fix 129c7cc2; the first launch had silently run the baseline for
    L1/L2).
- **Within-game margin SD**, paired difference vs baseline (18.10), game-bootstrap 95% CI:

| point | SD | diff vs baseline [95% CI] |
|---|---|---|
| L1 0.95 | 17.68 | −0.42 [−0.64, −0.19] |
| L1 1.0 | 17.51 | −0.59 [−0.81, −0.35] |
| L2 0.4 | 18.12 | +0.02 |
| L2 0.2 | 18.02 | −0.08 |
| L2 0.0 | 18.30 | +0.20 [−0.06, +0.49] |
| L3 0.03 | 18.15 | +0.05 |
| L3 0.0 | 18.06 | −0.04 |

- **VERDICT: REFUTED.** No setting gets below 16.0, so per the pre-registration L1-L3 are **EXONERATED** as the
  driver of the excess margin spread.
  - L1 has a real but small effect (~15% of the 18.1 → ~14 gap at its extreme).
  - L2 and L3 are null.
- **Next, as pre-registered:** diagnose shot-level and lineup randomness.
- **Joint fit (step 4):** not run as a fix for this target. Whether L1 = 1.0 is worth adopting on its own is read off
  the S3/S5/S7/S8 per-point tables, then decided with the user.

### Phase 2 #1 — per-point S3/S5/S7/S8 table (2026-10-07 ~23:00Z, 87 paired games, real n = 87)

Columns are base / L1 1.0 / L3 0.0. The real CI half-width is in brackets.

| row | real | base | L1 1.0 | L3 0.0 |
|---|---|---|---|---|
| S3 quarter-total SD, P1 [±1.5] | 8.92 | 9.61 | 9.59 | 9.03 |
| S3 quarter-total SD, P2 [±1.2] | 8.62 | 9.62 | 9.78 | 8.97 |
| S3 quarter-total SD, P3 [±1.4] | 9.96 | 9.68 | 9.70 | 9.05 |
| S3 quarter-total SD, P4 [±1.2] | 8.91 | 9.64 | 9.62 | 9.08 |
| S8 total-vs-line SD [±2.6] | 17.74 | 19.98 | 19.98 | 18.77 |
| S8 margin-vs-spread SD [±2.3] | 15.21 | 19.12 | 18.69 | 19.17 |
| S5 blowout entering the last period, all [±0.09] | 0.253 | 0.329 | 0.315 | 0.333 |
| S7 tied after regulation, all [±0.04] | 0.046 | 0.020 | 0.020 | 0.019 |

- Pre-registered objective Σ((sim − real)/CI half-width)²:
  - base 10.1;
  - L1 0.95 9.7; L1 1.0 **8.9**;
  - L2 0.4 10.6; 0.2 10.9; 0.0 11.4;
  - L3 0.03 9.4; L3 0.0 **9.0**.
- **Reading:**
  - **L3 (possessions_jitter) is a TOTALS lever.** At 0 it brings the quarter-total SDs onto real (~9.0 vs 8.6-10.0)
    and the total-vs-line SD from 19.98 to 18.77. Margins do not move, as expected, since possession count hits both
    teams equally.
  - **L1 is the only MARGIN lever** (−0.4 on S8 margin).
  - **L2 makes things slightly worse.**
  - The base quarter SDs were already inside the real CIs, so the S3 gains are not by themselves decisive. The S8
    total gain (−1.2 of a 2.2 excess) is the material one.
- **Candidate joint point** (pre-registration step 4, the product of levers that moved targets): L1 1.0 + L3 0.0.
  NOT run; it needs a user decision (~5 h at nice 19).
  - The margin excess (S8 margin 19.1 vs 15.2; S5 blowouts) stays unexplained by any lever. That is the refuted
    target.

### Phase 2 #1 — JOINT point L1 = 1.0 + L3 = 0.0 (run 00:19Z-02:57Z 10-08, nice 19)

- **Run:** 87/87 games on the 12 dates. LEVER_REACH carried both levers on every engine call (17,400/17,400
  cumulative).
- **Composes:**

| row | real | base | J1 |
|---|---|---|---|
| S8 total-vs-line SD | 17.74 | 19.98 | **18.80** |
| S8 margin-vs-spread SD | 15.21 | 19.12 | **18.84** |
| S3 quarter-total SD | 8.6-10.0 | ~9.6 | 9.0-9.1 |
| S5 blowouts, all | 0.253 | 0.329 | 0.327 |
| S7 tied after regulation | 0.046 | 0.020 | 0.017 |

  - The L3 totals gain is kept in full, and about half the L1 margin gain is kept.
- **Objective:** base 10.1 → **J1 8.4**, the best of all 9 points.
- **Guard rows:**
  - S1 pace −0.04 (SE 0.35), S6 FTA −0.08 (SE 0.16), S9 3PA +0.02 (SE 0.44), S10 unchanged: no move.
  - S2 quarter shares move ≤ 0.001 of share, beyond the sim's own tiny SE (~0.0003) but ~0.2 pt, which is
    immaterial. Some move toward real, some away.
  - S11 foul-outs 0.331 → 0.275 (real 0.103): toward real.
- **Next (pre-registration step 5):** re-run the FULL FIT window with J1 before any adoption. That is ~791 games, so
  ~24 h at nice 19 at the J1 pace (87 games in 2.6 h). This needs a user decision.

### Phase 2 #1 — step 5, FULL FIT re-run with J1 (L1 = 1.0 + L3 = 0.0), read 2026-10-08 ~19:35Z

- **Run:** 13:26Z-19:28Z, 3 workers, nice 19. 806 games / 109 dates, identical to Phase 1 per date (0 mismatched).
  - LEVER_REACH: every engine call on every worker.
  - Table: paired = 791, the same population as Phase 1.
  - 2025-12-09 (2 games) and 2025-12-16 (1 game), NBA Cup knockout dates, fail identically in BOTH runs ("no player
    rows", draws = 0) and drop out of both tables.

| row | real [CI] | Phase 1 | J1 | reading |
|---|---|---|---|---|
| S8 total-vs-line SD | 18.29 [17.42, 19.22] | 20.19 | **18.95** | NOW INSIDE |
| S8 margin-vs-spread SD | 14.00 [13.19, 14.71] | 19.38 | 18.89 | nearer, still far outside |
| S3 quarter-total SD P1-P4 | 8.48-8.89 | 9.64-9.68 | 9.02-9.06 | all nearer; P3, P4 now inside |
| S5 blowouts entering the last period, all | 0.230 | 0.348 | 0.337 | nearer, small |
| S6 FTA / S9 3PA / S1 pace / S10 / S11 | — | — | — | unchanged (≤ 0.03 SE) |
| S7 tied after regulation, \|spread\| 4.5-8 | — | — | — | −0.001, crosses the CI edge (0.018): immaterial |

- **Guard on S2 (quarter shares), against the literal pre-registration:**
  - 7 of 16 rows move by more than the sim's own SE. **By the letter, the guard FAILS.**
  - The largest is P4 "entering last: 9-17": −0.0007, 4.6 sim-SE, ~0.16 pt, toward real. Every other row is
    ≤ 0.0004 (≤ 0.09 pt). Every S2 move is < 0.35 of the REAL SE.
- **Why the literal guard is mis-specified** (stated, NOT used to re-score):
  - The harness is not deterministic (measured 10-07), so Phase 1 vs J1 differ by run-to-run noise of ~√2 × sim-SE
    even at an identical config.
  - Under pure noise, |d| > 1 sim-SE is expected in ~48% of rows, ~7.7 of 16. Observed: 7.
  - Only P4 9-17 stands out (~3.2σ of run noise), and it moves toward real.
  - The S2 guard threshold was below the instrument's own repeatability. Whether to accept this reading is the
    user's call, recorded with the decision.
- **Not done, per the pre-registration:**
  - VALIDATION is not read here; it is read once at the end of Phase 2, for the combined config.
  - The margin excess (18.9 vs 14.0) stays open: shot-level / lineup diagnosis.
