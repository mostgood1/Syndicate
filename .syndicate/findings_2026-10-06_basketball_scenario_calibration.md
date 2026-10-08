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

**USER DECISION 2026-10-08 (~19:40Z): "Accept, carry into Phase 2".**
- The S2 guard is judged against run-to-run noise (above), recorded as an explicit user override of the literal guard.
- J1 (possession_alternation = 1.0, possessions_jitter = 0.0) is the Phase 2 #1 config. Later Phase 2 steps build on
  it.
- Production adoption ONLY after the end-of-Phase-2 VALIDATION read, for the combined config.
- **Follow-up for future guards:** state the threshold in units of measured run-to-run noise (√2 × sim-SE, or a
  measured same-config re-run), never the single-run sim SE.

## Phase 2 #1b — MARGIN-EXCESS DIAGNOSIS, PRE-REGISTERED 2026-10-08 (user: "start the margin-excess diagnosis"), BEFORE computing

**Target:** S8 margin-vs-spread SD, sim 18.89 (J1) vs real 14.00 [13.19, 14.71]. L1-L3 are exonerated.

**Data:**
- J1 full-FIT draws (`C:	mpball_scit_j1\sim_nba`, 200 draws × 791 paired games).
- Real ESPN boxes (`real_nba.jsonl`), FIT window, regular season, the same 791 games.
- Fields common to both: per-team FGA, 3PA, FTA, TOV. Sim draws carry no makes and no OREB; real carries OREB but no
  makes in the stored record.

**Decomposition (identical regression on both sides):**
- margin = b0 + b1·ΔFGA + b2·Δ3PA + b3·ΔFTA + b4·ΔTOV + e, where Δ = home − away.
- The VOLUME component is the fitted part; the EFFICIENCY component is the residual e (makes per attempt, i.e. shot
  luck plus true shooting difference).
  - REAL: across games, margin + home spread (centred on the line) on the Δs. Report SD(volume), SD(e).
  - SIM: WITHIN-game, each draw minus its game mean for the margin and every Δ, pooled. Report SD(volume), SD(e).
- Real SD(e) includes line mis-centring and true talent differences, so it is an UPPER bound on real within-game
  efficiency luck. Sim within-game excludes both. A sim within-game component ABOVE the real total component is
  therefore conclusive in direction.
- CIs: game-clustered bootstrap, 1000 reps.

**Hypotheses:**
- **H-S (shot level):** sim within-game SD(e) > real SD(e) upper bound, CIs not overlapping.
  - Falsified if sim SD(e) ≤ the real upper CI.
- **H-V (volume):** sim within-game SD(volume) > real SD(volume), CIs not overlapping.
  - Falsified if sim ≤ the real upper CI.
- **Binomial check on H-S** (sim only, no real makes needed): per team-draw, the expected points variance from
  independent shots given its own FGA/3PA/FTA at league rates (2P .545, 3P .360, FT .780, rounded 2025-26 league
  values). Compare it with the sim's within-game per-team points variance after removing volume.
  - A ratio > 1.3 means the engine adds efficiency noise beyond shot independence (e.g. per-draw efficiency
    multipliers).
  - ≈ 1 means its shot luck is binomial, and the excess must then be over-dispersed volume or something not
    measured.
- **Remainder rule:** if neither H-S nor H-V holds, the excess is attributed to what the saved draws cannot see
  (lineup/rotation, OREB), which needs new per-draw instrumentation. That is NOT inferred from these numbers.

**What happens next under each outcome** (fixed now):
- H-S confirmed → read events.py for efficiency noise sources: per-draw or per-quarter make-probability multipliers,
  hot-hand terms. Add default-off levers, then the same sweep protocol.
- H-V confirmed → the same for possession/TOV/FTA generation.
- VALIDATION is untouched.

### Phase 2 #1b — RESULT 2026-10-08 (791 games; J1 draws; script scratchpad margin_decomp.py)

**Pre-registered readings:**

| component | real, across games (upper bound) | sim, within game |
|---|---|---|
| total margin SD | 13.99 [13.22, 14.81] | 17.62 [17.55, 17.68] |
| VOLUME (ΔFGA/Δ3PA/ΔFTA/ΔTOV fitted) | 3.63 [2.77, 4.76] | **8.14** [8.05, 8.23] |
| EFFICIENCY (residual) | 13.51 [12.74, 14.24] | **15.62** [15.56, 15.67] |
| β(ΔFGA, Δ3PA, ΔFTA, ΔTOV) | 0.04, 0.13, 0.21, −0.49 | 0.02, 0.20, 0.40, −1.16 |

- **H-S CONFIRMED** and **H-V CONFIRMED** as pre-registered.
- **Binomial check:** sim per-team points variance after volume is 122 vs 140 for independent shots, ratio 0.87
  (p10 0.74, p90 1.01).
  - That is NOT > 1.3, so the engine adds no per-team efficiency noise beyond shot independence.
  - The efficiency excess is exactly two INDEPENDENT teams' binomial luck: √(2 × 122) = 15.6.
  - Real games sit BELOW that (13.5 even including talent and line error). So real margins are compressed by
    something that couples the two teams.
- **Volume:** the per-diff SDs are NOT inflated (exploratory: sim within vs real across, ΔFGA 7.07 vs 9.31, Δ3PA
  7.38 vs 10.13, ΔFTA 9.46 vs 8.94, ΔTOV 5.15 vs 5.40).
  - The volume component is large because in the sim each ΔTOV/ΔFTA is worth ~2× more points (β −1.16 vs −0.49;
    0.40 vs 0.21).
  - In real games, volume swings are offset by other channels.

**EXPLORATORY (not pre-registered, a lead for the next pre-registration) — score effects:**

| slope | real [95% CI] | sim, within draw |
|---|---|---|
| Q4 margin on margin entering Q4 | −0.076 [−0.116, −0.034] | **+0.096** |
| H2 margin on H1 margin | −0.053 [−0.124, +0.015] | **+0.212** |

- Real games REVERT: the leader gives some back. That holds even though the real across-game slope includes team
  talent, which pushes it positive.
- The sim COMPOUNDS within a draw: a draw that leads at half keeps out-scoring. Within a draw there is no talent
  term, so a positive slope means a PERSISTENT per-draw shock.
  - Examples: per-draw rotation/minutes or lineup sampling, per-draw team adjustments, player availability or form.
  - Sim per-quarter environment (L2) is exonerated.
- Together with the missing negative feedback (real garbage time / effort / fouling), this explains margin SD too
  wide (18.9 vs 14.0) and blowouts too frequent (0.34 vs 0.23).
- **Next (to pre-register):**
  1. Enumerate every per-draw-persistent random term in the SmartSim path (smart_sim.py, events.py,
     basketball_props_smart_sim.py) and measure each one's share of the within-draw H1→H2 slope with a default-off
     lever (target slope ≤ 0).
  2. Separately, score-effect feedback: blowout pace/efficiency scaling (`garbage_time_*`, `blowout_*`), tested
     against the real Q4 slope −0.076.

### Phase 2 #1b — CORRECTION 2026-10-08 ~20:45Z: the exploratory "persistent per-draw shock" is RETRACTED

**The error:**
- The "within-draw" slopes (+0.212 H2-on-H1, +0.096 Q4) pooled draws ACROSS games with only the grand mean removed.
  They were mostly the spread of game means, not a within-draw effect.
- Caught by the code survey: there is NO random term drawn once per draw, per half or per stint in the NBA PBP path.
  - Lineups are redrawn every possession.
  - Every per-quarter draw is shared by both teams or is already exonerated.
  - Team, player and minutes inputs are fixed per game.
- The volume/efficiency decomposition above DID demean per game and stands.

**Re-measured** (script scratchpad slope_fix.py; 791 games):

| slope | SIM, within game, per-game demeaned | REAL, line-adjusted (each period minus its share of −spread) |
|---|---|---|
| H2 margin on H1 | **−0.001** [−0.006, +0.004] | **−0.174** [−0.240, −0.106] |
| Q4 margin on margin entering Q4 | **+0.001** [−0.002, +0.004] | **−0.141** [−0.184, −0.096] |

- Line error in the real adjustment biases the real slope UP, so −0.17 is conservative.
- **Reading:** the sim has NO momentum and NO reversion: its halves are independent. Real games revert strongly
  once the market expectation is removed. That negative covariance is what compresses real full-game margins.
  - The code survey agrees: garbage time scales both teams equally, the only margin-dependent foul term favours the
    LEADER, possession count ignores the score, and `bench_weight_boost` is dead (always called with
    blowout_boost_bench=False).
  - => **missing score-effect feedback** (exploratory, to pre-register).

**SECOND DEFECT, found by the same re-measure: team-strength over-extrapolation.**
- The SD across games of the sim's mean margin is **13.06** vs the market's expected margin **7.56**.
  - corr 0.919, slope of sim mean on −spread **1.59**, mean offset −0.52.
  - The sim turns a 10-pt favourite into a ~16-pt favourite.
- This is the "6.7 between-game mis-centring" from Phase 1: √(13.06² + 7.56² − 2 · 0.919 · 13.06 · 7.56) ≈ 6.8.
- Code-survey candidate (unverified): `eff_mult` (events.py:1163-1173) stacks calibration to the quarter targets,
  which already carry ratings, market anchor and home court, with `eff_prior` from advanced stats and home court
  again (wrapper :4240-4284), clipped 0.75-1.25. That may double-count strength.
- **Production impact:** the raw sim spread/ML probabilities are biased toward favourites. The served NBA game
  lines are blended toward the de-vigged book (nba_game_book_blend.json, preseason weights 0), which limits but does
  not remove this. Measure before claiming the size.
- **Variance budget:** S8 margin 18.89² ≈ within 17.6² + mis-centring 6.8². Fixing the mean alone leaves 17.6 vs
  real total 14.0, so BOTH defects must move.

**Next pre-registration (two mechanisms, one at a time, default-off levers):**
- **M-A team-strength shrink:** lever on the eff_prior stacking. Target: slope of sim mean on −spread → 1.0 and
  mis-centring SD down. Guard: S1 pace, S6, S9 unchanged.
- **M-B score-effect feedback:** asymmetric leader-side scaling and/or trailing-team fouling that grants possessions.
  Target: within-game H2-on-H1 slope → −0.17 and Q4 → −0.14; S8 margin toward 14; S5 blowouts toward 0.23.
- Per model_engine_standard, mechanism-vs-estimator: adding M-B to a calibrated engine needs a re-fit of the rates
  it absorbs. Measure joint, not additive.

## Phase 2 #1c — M-A TEAM-STRENGTH SHRINK, PRE-REGISTERED 2026-10-08 (user: "start the team-strength shrink"), BEFORE any engine change

**Mechanism (read, file:line):**
- In PBP mode, `events.py:1159-1173` first calibrates each team's make/FT multiplier to its per-game point target
  (`eff_mult = clip(target_ppp / base_ppp, 0.85, 1.15)`).
- It THEN multiplies by `eff_prior` (`events.py:1087-1088`, from `home_team_adj["eff_mult"]`), clipped 0.75-1.25.
- `eff_prior` is built by `_team_adj_from_advanced_stats_local` (basketball_props_smart_sim.py ~:4240-4284):
  off_rtg/league × opponent def_rtg/league, then × the home-court multiplier (#474).
- The targets are the market-anchored quarter means: SYNDICATE_BASKETBALL_SIM_MARKET_ANCHOR on, margin_w 0.95,
  total_w 0.7. So they already carry strength and home court, and eff_prior counts them a second time.

**Pre-change evidence:**
- Full FIT: sim mean margin vs −spread slope **1.59**, SD 13.06 vs 7.56.
- 26 surviving scratch games: target margin vs market slope 0.93, but sim mean margin vs TARGET slope **1.32**. The
  amplification happens after the targets.
- One game, CHA-POR 2026-02-28: market −7.5, target +6.96, sim +10.05.
  - eff_prior about ×1.03 home vs ×0.99 away, plus HCA.

**Lever:**
- New `EventSimConfig` field `eff_prior_weight: float = 1.0` in BOTH vendor engines (nba, wnba).
- Applied ONLY where the target calibration ran (tpp present): `eff_mult *= eff_prior ** w`.
- `w == 1.0` takes the unchanged expression, for byte-identity. Where no target exists, eff_prior stays the only
  strength signal and is untouched.
- Default 1.0 = byte-identical (seeded sha256 proof, both leagues, as for fcba19a7). Reachability: w = 0 vs 1 changes
  the mean margin on one game.

**Sweep:**
- On top of the accepted J1 config: the same 12 seed-7 FIT dates (87 games), 200 draws, nice 19.
- w ∈ {1.0 (J1 control, re-run in this sweep for a same-time baseline), 0.5, 0.0}.

**Readings:**
- PRIMARY: OLS slope of the per-game sim mean margin on −spread (target 1.0) and SD(sim mean − (−spread)).
- Secondary: S8 margin SD (real 14.0), S5 blowouts, S8 total SD, S3 quarter-total SD.
- Guards: S1 pace, S6 FTA, S9 3PA, judged against measured run noise. The w = 1.0 re-run vs the existing J1 sweep
  point on the same 87 games gives that noise directly. Never against the single-run sim SE (lesson of 804385c2).

**Calls (fixed now):**
- **Confirmed** if w = 0 brings the slope inside [0.85, 1.15] and S8 margin SD falls by more than its run noise.
- **Refuted** if w = 0 leaves the slope > 1.30. Then the amplification lives elsewhere: the 0.85-1.15 target
  clip, `tov_mult`/`oreb_mult`/`foul_mult` four-factor priors, or player-rating spread in base_ppp. Next: the same
  lever on those.
- The intermediate w = 0.5 is read only for shape. A w outside {0, 0.5, 1} is not picked from these data.
- The full FIT re-run follows a confirmation, as in #1. VALIDATION is untouched.
- Mechanism-vs-estimator: if adopted, the S8 total and quarter rows are re-read jointly with J1, not assumed additive.

**AMENDMENT to #1c (2026-10-08, BEFORE any engine change or data read):**

- **Precedent found:** the WNBA engine already ships this fix. Commit c0d406d3 (2026-10-01, upstream-merged) adds
  `TEAM_PRIOR_STACKS_ON_TARGET = False`: "stacking the prior counted it twice"; LVA-IND anchored total 180.8 vs sim
  198.0. Tests are in tests/test_basketball_sim_team_calibration.py.
- **The NBA engine has NONE of the eight WNBA engine switches:** SHOOTER_FT_RATE, FOULED_MISS_NOT_FGA,
  EXACT_TARGET_CALIBRATION, TEAM_PRIOR_STACKS_ON_TARGET, TOV_PER_ATTEMPT, PLAYER_REBOUND_CREDIT, BLOCK_MODE,
  BLOCK_ALLOC_BY_RATE (grep count 0 each).
- **Lever changed to match the WNBA mechanism:**
  - `EventSimConfig.team_prior_stacks_on_target: bool = True` in the NBA engine (True = today = byte-identical).
  - False = no team prior on top of a target; still applied without one.
  - Binary, so the w = 0.5 point is DROPPED. The confirm/refute calls are unchanged, with w = 0 ≡ False.
- **EXACT_TARGET_CALIBRATION is NOT ported in this step:** its solver (`_solve_eff_mult` /
  `_loop_points_per_possession`) models the WNBA loop including SHOOTER_FT_RATE and FOULED_MISS_NOT_FGA, which the
  NBA loop lacks. Porting it alone would calibrate against the wrong loop.
  - The residual sim-vs-target slope after this step decides whether it is next. That is read on the per-game
    target in the smart_sim JSONs, which needs the sweep to keep its scratch output.
- **Sweep points (12 dates, J1 levers in both):**
  - C = J1 control, re-run now: the same-time baseline, and the run-noise measure vs the existing J1 sweep point.
  - T = J1 + team_prior_stacks_on_target = 0.

## Phase 2 #1d — PORT THE WNBA ENGINE FIXES TO NBA, PRE-REGISTERED 2026-10-08 (user: "run these"), BEFORE any code change

**Scope:** the six WNBA engine commits of 2026-10-01 not present in the NBA engine.
- **8fd37ff3** SHOOTER_FT_RATE: free throws follow the shooter's own foul-drawing.
- **c0d406d3** FOULED_MISS_NOT_FGA + EXACT_TARGET_CALIBRATION (`_solve_eff_mult` / `_loop_points_per_possession` /
  `_loop_shot_share`). Its TEAM_PRIOR_STACKS_ON_TARGET is already ported as an NBA cfg field (b08aeb72).
- **9f561ca3** TOV_PER_ATTEMPT: p_tov per shot iteration. Its wrapper half (PRIOR_BLEND_MISSING_RECENT_IS_ABSENT)
  is league-wide and already applies to NBA.
- **863e9e09** PLAYER_REBOUND_CREDIT.
- **cbb14a73** BLOCK_MODE.
- **4ec1fd72** BLOCK_ALLOC_BY_RATE.
- 066ac9ea was reverted upstream (80bdd00c) and is NOT ported.

**Implementation rules:**
- Module-level switches with the WNBA names. NBA default = today's behaviour, so the port is byte-identical (seeded
  sha256 HEAD vs patched, with team_adj and targets present). Each switch must be reachable (off != on), with tests
  mirroring the WNBA tests.
- Constants the WNBA fitted on WNBA data are RE-FITTED on NBA FIT-window ESPN boxes (2025-11-01..2026-02-28,
  regular season). They are never copied: player OREB per own miss, DREB per opponent miss, block rate on missed
  2PA, and any other league-fitted rate in these commits. VALIDATION is untouched.
- The harness gets `--engine-flag NAME=VALUE`, which sets module switches on the real events module per run, with
  the same LEVER_FAIL / reachability-count discipline as `--lever`.
- The compact draw records team FGM, 3PM, FTM, REB, BLK, STL and AST. The real extractor adds the same from the
  cached ESPN summaries (no new fetch).

**Measurement:**
- Same 12 dates / 87 games, 200 draws, nice 19. Run AFTER #1c reads, on top of its chosen stacking state.
- Points: control vs all six switches ON jointly. The WNBA shipped them together and they interact: EXACT
  calibration solves against the loop that SHOOTER_FT_RATE and FOULED_MISS_NOT_FGA define. Then a leave-one-out only
  for any switch whose own target row does not move.
- Per-switch target rows, team per game, sim vs real (FIT, same 87 games):
  - FOULED_MISS_NOT_FGA: FGA and FG%.
  - EXACT_TARGET_CALIBRATION: team points vs the anchored target; |bias| < 1 pt.
  - SHOOTER_FT_RATE: FTA (team) and the FTA concentration on the top-2 shooters. The latter needs a player-level
    reading, so if it cannot be read it is labelled UNREAD, not passed.
  - TOV_PER_ATTEMPT: TOV.
  - PLAYER_REBOUND_CREDIT: REB.
  - BLOCK_MODE / BLOCK_ALLOC_BY_RATE: BLK.
- Pass per row: the sim moves toward real by more than run noise (C vs prior J1 point, same config).
- Guards: S8 total/margin, S3, S5, S1 pace do not move AWAY from real by more than run noise.
- **Adoption:** none from this step. The combined config goes to the end-of-Phase-2 VALIDATION read, and the user
  decides. The vendor change goes upstream to mostgood1/NBA-Betting (CLAUDE.md: a vendor-only fix is reverted by
  the next re-pull).

### Phase 2 #1c — RESULT 2026-10-08 (sweep done 22:15Z / 5:15 PM CDT; 87/87 games every point; levers on 17,400/17,400 engine calls)

| point | sim mean margin on −spread slope [95% CI] | mis-centring SD | target → sim slope | S8 margin SD (real 14.0) | S8 total SD |
|---|---|---|---|---|---|
| J1 (earlier run) | 1.493 [1.309, 1.672] | 6.54 | — | 18.84 | 18.79 |
| C = J1, re-run | 1.454 [1.256, 1.652] | 6.50 | 1.525 | 18.64 | 18.79 |
| **T = J1 + team_prior_stacks_on_target = False** | **0.869** [0.762, 0.983] | **3.72** | 0.918 | **17.99** | 18.80 |

- Paired T − C slope: **−0.585** [−0.772, −0.416].
- Run noise, same config (C vs the earlier J1): slope −0.038; per-game mean margin SD of the difference 1.79;
  S8 margin 0.20.
- **VERDICT: CONFIRMED** as pre-registered.
  - The slope is inside [0.85, 1.15] (point estimate).
  - Mis-centring falls 6.50 → 3.72.
  - S8 margin SD falls 0.65, more than its run noise of 0.20.
  - Totals are unchanged, as expected for a margin-only mechanism. Within-game SD is unchanged (17.6): that excess is
    M-B, score effects.
- The slope now sits slightly UNDER 1, and target → sim is 0.92. The old ±15% eff clip can stop a team reaching an
  extreme target. EXACT_TARGET_CALIBRATION (#1d, ported 27ef92f8) addresses exactly that and is read next.
- Team priors were applied on 62/87 games; early-season games lack them, which is why the November-only early peek
  showed no difference.
- **Next:** #1d measured on top of T (J1 + no stacking) on the same 12 dates. The full FIT re-run waits until #1d
  reads, so ONE full re-run covers the combined config.
  - Deviation from #1c's "full FIT re-run follows a confirmation" (amended here, before #1d data): it saves a ~6 h
    run and reads the same rows.
