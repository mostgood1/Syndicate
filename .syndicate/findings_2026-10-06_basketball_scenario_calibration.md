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

### Phase 2 #1d — RESULT 2026-10-09 ~00:30Z (7:30 PM CDT 10-08)

**Run:**
- T2 = J1 + no stacking (control). P = T2 + the six ported switches (SHOOTER_FT_RATE, FOULED_MISS_NOT_FGA,
  EXACT_TARGET_CALIBRATION, TOV_PER_ATTEMPT, PLAYER_REBOUND_CREDIT, BLOCK_MODE = team_prior, BLOCK_ALLOC_BY_RATE).
- Both 87/87 games, all engine calls carrying every lever and switch.
- The first P launch ran 0 games because of a harness bug (fixed 2681c800, see the log). That launch was discarded.
- Real side: re-extracted ESPN boxes (realx, 816 games).

**Per-switch target rows** (team per game; real / T2 / P; P − T2 [95% CI]; run noise T2 vs T):

| switch | row | real | T2 | P | P − T2 [95% CI] |
|---|---|---|---|---|---|
| FOULED_MISS_NOT_FGA | FGA | 89.63 | 94.11 | **88.59** | −5.53 [−5.68, −5.37] |
| FOULED_MISS_NOT_FGA | FG% | .468 | .449 | **.462** | — |
| EXACT_TARGET_CALIBRATION | sim total − anchored target, per game | — | +5.71 | **−1.18** | −0.59/team, \|bias\| < 1 PASS |
| SHOOTER_FT_RATE | FTA | 22.76 | 20.72 | 21.18 | +0.47 [+0.28, +0.65] |
| TOV_PER_ATTEMPT | TOV | 14.24 | 15.67 | **14.35** | −1.32 |
| PLAYER_REBOUND_CREDIT | REB | 44.20 | 44.57 | **44.13** | −0.44 |
| BLOCK_MODE + BLOCK_ALLOC_BY_RATE | BLK | 4.94 | 2.77 | **5.24** | +2.47 |

- SHOOTER_FT_RATE's top-2 concentration is **UNREAD** (no player-level reading in this harness); only its team FTA
  row passed.
- Run noise T2 vs T is ≤ 0.10 on every row read. **Every pre-registered target row moved toward real, by far more
  than noise.**

**Guards** (T2 → P, moves vs real):
- **Toward real:** S1 pace 118.9 → 112.3 (real 113.9); S8 total SD 18.56 → 18.37; S8 margin SD 17.92 → 17.63;
  S9 3PA; S7 ties.
- **Away, small:** S3 P1 quarter-total SD 8.93 → 8.76 (real 8.92, still inside the real CI); S11 foul-outs +0.020;
  S5 rows ≤ 0.013 (within noise).
- **Not guarded, moved away:** AST 24.5 → 23.7 (real 27.3); STL 8.59 → 7.88 (real 8.36); FT% .812 → .781 (real .796);
  3P% .380 → .394 (real .360).

**MATERIAL FINDING — the NBA totals TARGET is low; EXACT calibration exposes it:**
- On the 87 games: market total 230.70, real 230.62 (market unbiased, −0.07). But **model_total_raw 215.40
  (−15.3 vs market)**.
- At total_w 0.7 the anchored target is 226.11, ~4.5 low. The old engine overshot its target by +5.7 and hid this.
  With EXACT calibration the sim lands ON the low target: points/team 112.7 vs real 115.3.
- **This is WNBA's G1** (lane wnba-game-total-level, closed 2026-10-01): the vendored game model's raw total is
  biased, and the designed correction (`calibration_totals_<date>.json`, read by `_apply_totals_calibration_local`)
  is written by NOTHING for NBA. WNBA got `scripts/build_wnba_totals_calibration.py`; NBA has no builder.
- => EXACT_TARGET_CALIBRATION must NOT be adopted for NBA without an NBA totals-calibration builder. Production today
  is "right" on totals only because two errors cancel.

**Verdict #1d:**
- All six switches CONFIRMED on their own target rows.
- Combined adoption BLOCKED on the NBA totals-target bias (new item, port of WNBA G1).
- No production change.

## Phase 2 #1e — NBA TOTALS CALIBRATION, PRE-REGISTERED 2026-10-09 ~00:45Z (user: "Build NBA totals calibration"), BEFORE any code

**Problem (measured, #1d):**
- 87 FIT games: NBA `model_total_raw` 215.40 vs market 230.70 vs real 230.62. The raw is −15.3; the market is
  unbiased.
- The anchor (total_w 0.7) leaves targets ~4.5 low. EXACT_TARGET_CALIBRATION then lands the sim on that low target.

**Why no correction applies:**
- The designed correction (`calibration_totals_<date>.json`, read by `_apply_totals_calibration_local`: global
  bias ±15, team ±4) has NO NBA writer. Fleet NBA processed root `/home/amyn/syndicate-prod/data/...`: 0 files.
  The replay pristine also has 0, so every raw total in this lane is UNcalibrated.
- WNBA got `scripts/build_wnba_totals_calibration.py` (lane wnba-game-total-level, closed 2026-10-01).
- The NBA raw total is NOT a game-model prediction as in WNBA. It is ratings × pace in `_simulate_quarters_local`
  (basketball_props_smart_sim.py ~1199-1245):
  `home_mu = (home_off − (away_def − baseline_off)) / 100 × pace + adj`, pace reduced by back-to-back
  (1/team) and 0.3 × injuries_out per team, then the calibration file, then the anchor.

**Structural suspects (recorded, measured, NOT fixed in this step):**
- (S-a) NBA `baseline_off_rating` = `baseline_def_rating` = 110.6 (basketball_props_smart_sim.py:341) vs the
  2025-26 as-of league ~113.1 (team_advanced_priors). This mis-centres the def subtraction by ~2.5/team.
- (S-b) the injury pace drag 0.3 × injuries_out (production contexts show injuries_out = 5 per team), ~−3
  possessions.
- (S-c) baseline pace 100.

**Builder (G1 port), `scripts/build_nba_totals_calibration.py`:**
- WNBA recipe unchanged: winsorized (5/95) mean(actual − raw total) over the last 14 days (season-to-date under 8
  games), clip ±15; team terms = residual sum / (n + 20), clip ±4. The anchor is the day before the slate. Atomic
  write; skip if the file exists unless --force.
- **Input:** NBA's own per-game `smart_sim_<date>_*.json` on the processed root (`market_anchor.model_total_raw`),
  which the fleet already retains.
  - When a calibration file was in effect for a past date, its terms are backed out to recover the uncalibrated
    raw. The reader picks the newest file dated ≤ day − 1; the builder uses the same rule.
- **Actuals:** NBA final scores from an existing fleet artifact; the source is stated in the implementation.
- **REGULAR-SEASON games only** (nba_season_phase). Preseason sims never feed it.
- **Opening night:** with < 8 regular-season games, fall back to a SEED file. It is written once from this lane's
  2025-26 FIT-window fit (the final 14 days), labelled `seed`, read only until 8 games exist.

**Measurement (walk-forward, no new sim for the fit):**
- Data: the full-FIT combined-config run launched 2026-10-09 00:35Z (`fit_combo`). Its per-game summaries carry
  uncalibrated model_total_raw for ~791 games.
- For each date D: fit on games before D, correct D's raw. Report raw-total bias and MAE vs actual, before/after,
  with a game-clustered CI on the paired MAE change.
- **Gate:** |bias after| < 2 and MAE change CI < 0. The anchored target follows: the post-calibration target bias
  vs real is reported.
- **End-to-end:** the 12-date point with the combined config + calibration files written walk-forward into its
  scratch.
  - PASS if sim total bias vs real is within ±1.5 per game AND S8 total SD is no worse than run noise vs T2 / P.
  - That verifies EXACT_TARGET_CALIBRATION + calibration together.
- **Wiring** (default OFF; a file switch like the other NBA switches) is decided with the user AFTER the
  measurement: the builder called from `scripts/refresh_nba_oddsapi_props.py` before the sim, as WNBA does. No
  production change in this step.

### Phase 2 #1e — WALK-FORWARD RESULT 2026-10-09 ~03:05Z (10:05 PM CDT 10-08)

**Data:** the full-FIT combined-config run (`fit_combo`: J1 + no stacking + the six ported switches).
- 2026-10-09 00:35Z-03:01Z. 109 dates; the two NBA Cup dates fail identically as in every run.
- All engine calls carried every lever and switch. 791 games with raw total + actual.
- For each date the recipe is fitted on earlier games only (777 of 791 had terms).

| quantity vs actual total | bias | MAE |
|---|---|---|
| raw model total (uncalibrated) | −16.91 | 21.84 |
| **calibrated raw** | **−2.26** | **17.46**; paired −4.38 [−5.24, −3.43] |
| anchored target (raw) | −4.92 | 15.17 |
| **anchored target (calibrated)** | **−0.53** | **14.81**; paired −0.35 [−0.65, −0.04] |
| market | +0.15 | 14.52 |

**Gate by the letter:**
- MAE change CI < 0: PASS.
- |bias after| < 2: **FAIL by 0.26** (−2.26).
- Cause: the raw bias (−16.9) exceeds the ±15 global clip, which is applied by the WNBA recipe AND by the sim's
  reader (`_apply_totals_calibration_local`, ±15). The clip binds, and the seed fit (final 14 days) is also 15.0
  (clipped).
- The quantity the sim consumes, the anchored target, is near-unbiased (−0.53) and improves with CI < 0.
- Not re-scored. The options go to the user:
  - accept on the target reading;
  - remove part of the bias structurally (S-a: the stale 110.6 baseline; S-b: injury pace drag) so the remainder
    fits under the clip;
  - widen the clip in the reader. That file is claimed by lane basketball-injury-exclusion-reinclusion.

**Next (pre-registered):** the end-to-end 12-date point.
- Combined config + walk-forward calibration files (each date's file fitted on fit_combo games before it) copied
  into the scratch.
- PASS if sim total bias vs real is within ±1.5/game and S8 total SD is no worse than run noise.

### Phase 2 #1e — END-TO-END RESULT 2026-10-09 ~03:40Z (10:40 PM CDT 10-08)

**Run:** 12 dates, 87/87 games, all engine calls with every lever and switch.
- E2E = combined config (J1 + no stacking + six ported switches) + the walk-forward calibration files. Each date's
  file is fitted on fit_combo games strictly before it; global bias 7.3 → 15.0 (clipped) across the window.
- **Reachability:** model_total_raw E2E − P is +12.77 on average (min +4.89, max +21.79, n = 87), so the reader
  applied the files.

| point | sim total bias vs real [95% CI] | MAE | target bias | S8 total SD | S8 margin SD |
|---|---|---|---|---|---|
| T2 (old engine overshoot, no calibration) | +1.68 [−2.09, +5.55] | 13.64 | −4.51 | 18.56 | 17.92 |
| P (combined, no calibration) | −5.15 [−8.76, −1.56] | 14.19 | −4.51 | 18.37 | 17.63 |
| **E2E (combined + calibration)** | **−1.18** [−4.99, +2.73] | **13.53** | **−0.68** | 18.45 | **17.48** |

- **VERDICT: PASS** as pre-registered. The sim total bias is within ±1.5. S8 total SD is 18.45 vs P 18.37, +0.08,
  inside run noise (~0.2).
- The combined config now lands on an unbiased target, with the best total MAE of the three. The margin SD is the
  lowest yet.
- T2's near-zero bias was two cancelling errors: target −4.5, plus engine overshoot +6.
- **Open:**
  - The raw-bias |2| gate missed by 0.26, the ±15 clip (walk-forward above). User decision.
  - The bias GROWS through the season: the fitted global term is 7.3 in early Nov and at the 15 clip from late Nov.
    That points to a structural drift in the ratings × pace raw (S-a/S-b/S-c), not a constant offset.
  - The seed value for opening night is still unset: the final-14-day fit is 15.0, clipped.
  - Production wiring is a user decision. Per the pre-registration, adoption follows the end-of-Phase-2 VALIDATION
    read.

## Phase 2 #1f — NBA RAW-TOTAL DRIFT, PRE-REGISTERED 2026-10-09 (user: "Fix the drift's cause"), BEFORE measuring

**Observation (#1e):** the walk-forward global bias rises 7.3 (early Nov) → ≥ 15 (from late Nov, clipped).

**Mechanism read** (basketball_props_smart_sim.py, job build ~5800-5895; `_simulate_quarters_local` ~1199-1245):
- `home_off_rtg = (0.5 × (pred_total + pred_margin)) / matchup_pace × 100`. That is the vendor game model's
  predicted points, which already price the opponent.
- `off_rtg_from_points` is set True ONLY for WNBA ("NBA has not been backtested"). So for NBA:
  `home_eff = home_off − (away_def − 110.6)`, i.e. the opponent's defense subtracted again, centred on the stale
  NBA baseline 110.6 (as-of 2025-26 league def ~113.1).
- Pace: `pace = mean(home_pace, away_pace) − b2b (1/team) − 0.3 × home_outs − 0.3 × away_outs`, floored at
  baseline − 8. `*_outs` = number of players in the sim's excluded map (injury / availability), capped at 5.
- Then `mu = eff / 100 × pace + _adjustments_local(team)`.

**Hypotheses:**
- **H-D1 (G2 analog):** the def subtraction on points-derived ratings double counts. Expected sign: mostly
  negative, because opp def − 110.6 > 0 for an average team when the league def is 113.1.
  - Counterfactual: no subtraction (the WNBA rule).
- **H-D2 (injury pace drag drifts):** `*_outs` rises through the season, lowering pace and the raw.
  - Counterfactual: no outs drag. Read the slope of outs vs date and its share of the trend.
- **H-D3 (input drift):** the vendor game model's own pred_total is biased or drifting. The raw inherits it.
  - Counterfactual: raw = pred_total.
- **H-D4 (pace floor/scale):** the matchup pace and the clip/floor change the level.
  - Read: the counterfactual with pace = matchup_pace.

**Measurement:**
- A fast full-FIT re-run (combined config, 4 draws; the raw is computed before any draw) with the harness recording
  each game's sim JOB (pred mu via off_rtg × matchup_pace, def, pace, outs, b2b, rest).
- **IDENTITY CHECK FIRST:** recompute model_total_raw from the recorded inputs with the module's own functions.
  It must match the recorded raw within 0.05 on ≥ 99% of games, else the decomposition is wrong and nothing below
  is read.
- For each counterfactual: bias vs real (mean), MAE, and the bias-vs-date slope (pts per 30 days), with
  game-bootstrap CIs.
- A hypothesis is **CONFIRMED** if its counterfactual cuts |bias| AND the season trend (slope CI excludes the
  baseline slope, or the slope CI includes 0 where the baseline's does not).
- **Fix:** whatever is confirmed goes behind a default-off switch in basketball_props_smart_sim.py. That file is
  CLAIMED by lane basketball-injury-exclusion-reinclusion, so a loan is needed. The totals calibration is then
  re-read: the global term must fall well inside its ±15 clip. No production change without the user.

### Phase 2 #1f — RESULT 2026-10-09 ~17:35Z (12:35 PM CDT)

**Data:** fast full-FIT combined-config run (`fit_raw`, 4 draws, 2026-10-09 16:29Z-17:21Z, nice 19), 109 dates
(the two Cup dates fail as always), 809 recorded jobs, 806 with a recorded raw.

**Identity check:**
- 0.9864 by the letter (pre-registered ≥ 0.99): **FAIL as written**.
- All 11 misses sit on 11 DUPLICATED matchup keys: the same game was simulated twice on one date with different
  game-model inputs (e.g. LAL-DET 12-30 home off 119.07 vs 106.54), and only one smart_sim file survives.
- Exactly one job of every duplicated pair reproduces the recorded raw (11/11). On the 784 non-duplicated games the
  identity is exact (100%, max |dev| 0.000).
- The decomposition is therefore valid, and is read on the 780 non-duplicated games with an actual. Stated, not
  hidden.

| raw-total counterfactual (780 games, 107 dates; date-clustered CIs) | bias | MAE | slope per 30 days |
|---|---|---|---|
| recorded raw | −17.05 [−18.78, −15.38] | 21.93 | −0.60 [−2.00, +1.00] |
| D1 no def subtraction | −11.95 [−13.46, −10.45] | 18.65 | −0.03 |
| D1b def centred on the day's league def | −12.02 | 19.41 | −0.06 |
| D2 no outs (pace drag + −0.5/out) | −8.57 [−10.14, −6.88] | 18.15 | +0.63 |
| **D1 + D2** | **−3.34** [−4.81, −1.89] | **16.36** | +1.22 [−0.12, +2.57] |
| D3 game-model pred total | −3.35 [−4.86, −1.82] | 16.36 | +1.21 [−0.03, +2.55] |

- Monthly means: outs per team 2.71 / 3.87 / 4.08 / 4.30 (Nov-Feb); opp def − 110.6 +1.9 / +3.0 / +2.9 / +2.6;
  recorded bias −15.0 / −20.9 / −15.2 / −18.2.

**Verdicts:**
- **"Drift" premise REFUTED.** The recorded raw has no significant season trend (slope CI spans 0). The pre-registered
  trend criterion cannot be met by any counterfactual because there is no trend to cut. The rising walk-forward term
  (7.3 → 15) reflected the short early-season window and the ±15 clip, not a drifting model.
- **It is a LEVEL bias, fully decomposed.**
  - D1, the def subtraction on points-derived ratings (WNBA G2 analog): −5.1 pts.
  - D2, the outs penalties (pace −0.3/out and −0.5 pts/out at ~3.7 outs per team): −8.5 pts.
  - With both removed the raw equals the vendor game model's own prediction exactly (−3.34 vs −3.35). The game
    model's −3.3 is the only true model bias, and that is what the calibration file should mop up, well inside ±15.
  - D1 and D2 each cut |bias| and MAE with CIs clear of the recorded raw.
- **Note on D2:**
  - The game model's prediction may already price injuries, so the outs penalty may double count the same
    absences.
  - The sim's player pool already excludes the out players, and the market prices injuries too.
  - Its removal is judged on the walk-forward and end-to-end readings, not on this argument.

**Next (to pre-register with the fix):**
- Two default-off switches in `_simulate_quarters_local` / the job build: NBA points-derived ratings skip the def
  subtraction (the WNBA rule), and NBA skips the outs penalties when ratings are points-derived.
- The file is CLAIMED by lane basketball-injury-exclusion-reinclusion, so a loan is needed.
- Then: the walk-forward global term should fall to ~+3 (inside the clip), and the end-to-end 12-date re-run.

**LEAD:** duplicated matchups. 12 keys on 6 dates in Dec-Jan get two sim jobs with different game-model inputs; the
later one overwrites the smart_sim file. Source not traced; see the next leads.md entry.

### Phase 2 #1f — FIX BUILT + measurement PRE-REGISTERED 2026-10-09 ~18:00Z, BEFORE reading it

**Fix (51d08f7a):** file switch `nba_sim_total_inputs.json` on the NBA processed root.
- `skip_def_subtraction`: the WNBA points-derived rule.
- `skip_outs_penalties`: no injury pace drag, no −0.5/out.
- NBA only; absent = today. Recorded in market_anchor.nba_total_inputs when present.
- basketball_props_smart_sim.py: user-approved edit. At edit time NO open lane claimed the file
  (lane basketball-injury-exclusion-reinclusion is no longer OPEN; `lane_claims._claims` shows no claim), so no loan
  was needed. Tests 3/3, plus 44 neighbouring tests.

**Measurement:**
- **(1) Walk-forward:** the #1e recipe re-run on the switched raw (fit_raw D1 + D2 counterfactual, identity-validated
  on 784 games).
  - Gate as #1e: |calibrated raw bias| < 2 and MAE change CI < 0. Expect a global term near +3, inside ±15.
- **(2) End-to-end, 12 dates:** combined config + switch file ON (both keys) + calibration files re-fitted
  walk-forward on the switched raw.
  - PASS if sim total bias vs real is within ±1.5, S8 total SD no worse than run noise vs E2E (the #1e point), and
    S8 margin / S5 / S3 rows not worse than run noise vs E2E.
- No production change without the user.

### Phase 2 #1f — measurement (1) RESULT: walk-forward on the SWITCHED raw (780 games, 107 dates)

| | bias | MAE |
|---|---|---|
| switched raw (D1 + D2) | −3.34 | 16.36 |
| switched raw, calibrated | **+0.59** | 16.16 |
| anchored target, switched raw | −0.93 | 14.68 |
| anchored target, calibrated | +0.26 | 14.69 |

- Paired MAE change, calibrated − switched raw: −0.19 [−0.53, +0.17].
- The global term: min −1.79, median 3.81, max 7.17. **Well inside the ±15 clip:** the clip no longer binds.
- **Gate by the letter:** |bias| < 2 PASS (+0.59). MAE change CI < 0 **FAIL** (the CI includes 0).
- **Reading:** the two structural switches remove ~14 of the 17 points. The calibration file then mops up only the
  game model's ~3-pt level, with no significant MAE gain on top. The switches do the work; the calibration is a small
  safety term.
- Seed for opening night (final 14 days, switched raw): +2.50.
- Calibration files for the 12 dates were written to `C:	mpball_sc\calfiles_sw` (walk-forward, switched raw)
  for measurement (2), which was launched 2026-10-09 17:51Z.

### Phase 2 #1f — measurement (2) RESULT: end-to-end with the switches (read 2026-10-09)

**Run:** E2E_sw = combined config + `nba_sim_total_inputs.json` (both keys on) + calibration files re-fitted
walk-forward on the switched raw.
- 12 dates, 87/87 games, 17,400/17,400 engine calls with every lever and switch.
- **Reach:** market_anchor.nba_total_inputs both-on in 87/87 games.

| point | sim total bias vs real [95% CI] | MAE | target bias | S8 total SD | S8 margin SD |
|---|---|---|---|---|---|
| E2E (#1e: calibration only) | −1.18 | 13.53 | −0.68 | 18.45 | 17.48 |
| **E2E_sw (switches + calibration)** | **−0.35** [−4.03, +3.51] | **13.47** | +0.33 | 18.51 | 17.68 |

**Guards** (E2E_sw vs E2E; run noise ≈ √2 × single-run sim SE):
- Within noise: S8 total +0.06 (noise 0.17), S3 quarter totals, S1, S6, S9, S7, S11, S10.
- **Away from real, beyond noise:**
  - S8 margin SD +0.20 (noise 0.13);
  - S5 blowouts all +0.010 (noise 0.006).
- S5 at |spread| 8.5+ moved TOWARD real (+0.021).

**VERDICT by the letter:**
- Total bias PASS (within ±1.5); S8 total PASS.
- **Guard FAIL on S8 margin and S5-all**, small (+1.1% / +1 pt).
- Likely mechanism, stated not proven: the switches raise scoring ~4 pts/game to its real level, and margin
  dispersion scales with points. This is the known margin excess (M-B, missing late-game catch-up) showing more at
  the correct level, not a new defect.
- Not re-scored. The decision is the user's.

**USER DECISION 2026-10-09: "Accept, then late-game".**
- The S8-margin / S5-all guard miss in #1f (2) is overridden as the user's decision.
- The accepted Phase 2 config is now:
  - J1 (possession_alternation 1.0, possessions_jitter 0.0);
  - team_prior_stacks_on_target False;
  - the six ported WNBA switches;
  - `nba_sim_total_inputs.json` both keys on;
  - the NBA totals calibration builder (seed +2.50 from the switched-raw fit).
- Production adoption only after the end-of-Phase-2 VALIDATION read.
- **Next:** M-B late-game catch-up (score-effect feedback). The real line-adjusted H2-on-H1 slope is −0.174 and Q4
  −0.141; the sim's is 0.00.
- **Engine note:** the native engine switch landed (c2b99d4f, lane basketball-native-engine). The sim now runs
  syndicate/features/basketball_engine/, so vendor events.py edits are inert. M-B levers go in engine.py on a loan
  from that lane. tests/test_basketball_sim_jitter_levers.py and tests/test_nba_sim_engine_port.py still test the
  vendored module and are owed a repoint.

## Phase 2 #2 (M-B) — LATE-GAME CATCH-UP / SCORE EFFECTS, PRE-REGISTERED 2026-10-09, BEFORE any engine change

**Measured gap (#1b correction, 46247612):**
- Within-game slopes, sim (per-game demeaned) vs real (each period minus its share of −spread; line error biases the
  real slope UP, so the real values are conservative):
  - H2 margin on H1 margin: sim −0.001 vs real −0.174 [−0.240, −0.106];
  - Q4 on margin entering Q4: sim +0.001 vs real −0.141 [−0.184, −0.096].
- The sim's halves are independent; real games revert.

**Engine read (native engine, c2b99d4f; the code survey of the vendored copy agrees):**
- Garbage time (`garbage_time_eff_scale` 0.96, `garbage_time_pace_scale` on TOV) scales BOTH teams.
- The only margin-dependent foul term favours the LEADER.
- Possession count ignores the score.
- `bench_weight_boost` is dead (always called with blowout_boost_bench=False).

**Mechanism:**
- New `EventSimConfig.score_effect_k: float = 0.0` (0 = byte-identical: no branch taken, no RNG draw).
- On every shot, the offense's make probability (and FT% for its free throws) is multiplied by
  `clip(1 − k × dev, 0.85, 1.15)`, where `dev` = the offense's current lead minus its EXPECTED lead to date.
  - Expected lead to date = (target own − target opponent) × the share of regulation elapsed; 0 when there is no
    target.
- Symmetric around expectation, so it should not move the mean margin. It pulls deviations back: the team ahead of
  expectation shoots slightly worse, the team behind slightly better (effort, rotations, fouling folded into one
  term).
- Location: syndicate/features/basketball_engine/engine.py, the make-probability and FT sites. **LOAN required**
  from lane basketball-native-engine (session d10f7421).

**Sweep:**
- On the accepted Phase 2 config: the same 12 dates (87 games), 200 draws, nice 19.
- k ∈ {0 (control), 0.005, 0.01, 0.02} per point of deviation.

**Readings:**
- PRIMARY: within-game H2-on-H1 slope (target −0.17) and Q4 slope (target −0.14).
- Secondary: S8 margin SD (real 15.2 on these games), S5 blowouts (real 0.253), S7 ties.
- Guards (vs run noise, √2 × single-run SE): sim mean margin vs −spread slope and mean offset (must not move), S8
  total SD, S3 quarter totals, S1 pace, team points vs target.

**Calls:**
- **Confirmed** if some k brings both slopes within ±0.05 of real AND S8 margin falls by more than run noise with no
  guard worse than noise.
- **Refuted** if even k = 0.02 leaves the H2 slope above −0.10. Then the reversion is not an efficiency effect;
  next candidates are possession/foul-driven (trailing teams gaining possessions).
- The k is chosen from the grid only. A full FIT re-run follows a confirmation. VALIDATION is untouched.

**OWNERSHIP SPLIT for score_effect_k (2026-10-09, from the basketball-native plan coordinator, session d48f3a34, with the user's go-ahead):**
- This lane owns the PREGAME score-effect mechanism (`score_effect_k`, 18e5eba5) and its re-fit.
- Lane nba-native-live-resim (P3, session 6c348b8f) consumes it UNCHANGED and re-fits only the live-specific pieces:
  end-game fouling/clock, foul trouble, live rotations, asymmetric garbage time.
- P3 measured the same gap independently: real H2-on-H1 −0.164 [−0.233, −0.096] vs sim −0.001
  (findings_2026-10-09_nba_live_situation_targets.md).
- **Owed:** post the chosen k (and its readings) here and to P3 when the sweep reads.

**HOLD (USER DECISION 2026-10-09, relayed by the basketball-native coordinator d48f3a34):** NBA mechanism RE-FITS are
on hold, including fitting `score_effect_k`, until #473 is fixed.
- #473: NBA team_adj was unfed on 0/30 team-sides and starter flags on 0/517 over real 10-05..08 production sims.
- **This lane's corpus, checked directly** (probe at the native engine boundary, own as-of replay, 2 dates
  2025-11-13 and 2026-02-25, 18 engine calls; script C:	mpball_sc\probe_inputs.py):
  - home/away_team_adj present and non-neutral on 18/18 calls: FED here, unlike production;
  - starter flags (`starter_prob` / `is_starter` non-zero) on 0/18: UNFED here too.
- => The corpus is PARTLY affected. The M-B sweep running since 22:06Z is kept as a dose-response
  CHARACTERISATION of the mechanism only. No k is chosen, recorded as fitted, or handed to P3 until #473 is fixed and
  `scripts/basketball_engine_input_checklist.py` is re-run.

**score_effect_k default proof + LOAN RETURNED (2026-10-10 ~01:40Z):**
- `scripts/basketball_engine_parity.py --corpus ~/bn_corpus/corpus` on the engine with 18e5eba5: 5,400/5,400 real
  production calls reproduce production output, 0 mismatched (NBA 3,000, WNBA 2,400; 27 games), verdict PASS.
- The engine.py loan from basketball-native-engine is returned (removed from this lane's Files).

### Phase 2 #2 (M-B) — CHARACTERISATION (NOT a fit; NBA re-fits on hold, #473), read 2026-10-10 ~01:45Z

**Run:** accepted Phase 2 config + score_effect_k ∈ {0, 0.005, 0.01, 0.02}; 12 dates, 87/87 games each;
17,400/17,400 engine calls with every lever and switch. Within-game slopes are per-game demeaned.

| k | H2-on-H1 (real −0.174) | Q4 (real −0.141) | within-game SD | S8 margin (real 15.21) | blowouts (real 0.253) | sim-vs-market slope | total bias |
|---|---|---|---|---|---|---|---|
| 0 | +0.007 | +0.000 | 17.56 | 17.71 | 0.274 | 0.919 | −0.48 |
| 0.005 | −0.392 | −0.215 | 11.71 | 11.83 | 0.152 | 0.943 | +0.69 |
| 0.01 | −0.558 | −0.334 | 9.51 | 9.62 | 0.097 | 0.953 | +1.27 |
| 0.02 | −0.670 | −0.411 | 8.16 | 8.28 | 0.063 | 0.960 | +1.77 |

- **Reading:** the mechanism works as designed: monotone reversion, the mean margin vs the market unmoved, totals
  barely moved.
- **The whole pre-registered grid OVERSHOOTS.** k = 0.005 already doubles the real H2 reversion and takes the
  margin SD to 11.8 (real 15.2), because the factor applies on every shot and compounds.
- The pre-registered refutation ("even k = 0.02 leaves H2 above −0.10") is NOT met. The mechanism is too strong,
  not too weak.
- The real-matching k lies in (0, 0.005). By interpolation it is near 0.0015-0.0025; that is a guess, not a
  measurement.
- **When the hold lifts** (#473 fixed + input checklist re-run): a finer pre-registered grid
  k ∈ {0.001, 0.002, 0.003} on the same protocol, then a full FIT re-run. Nothing is chosen or handed to P3 now.

**SECTION LOAN GRANTED 2026-10-10 to lane nba-sim-team-adj-473 (#473, user-approved there):**
- Scope: `_nba_total_inputs_switch_local`, a 2-line edit. File ABSENT + `SYNDICATE_NBA_TEAM_INPUTS` on →
  {skip_def_subtraction: True, skip_outs_penalties: False}. A file present wins; flag off = today exactly.
- Conditions:
  - the source (flag / file) recorded in market_anchor;
  - tests added to tests/test_nba_sim_total_inputs.py (flag-on/no-file, file-wins, flag-off unchanged, WNBA
    ignores);
  - strict env parsing; the reader never raises.
- Their same-seed A/B on 22 preseason games: skip_def adds raw +4.35 / published +1.95, consistent with this lane's
  −5.1 (780 FIT games). Preseason totals already over; not regular-season evidence.
- The return SHA is owed by that lane. The NBA re-fit hold persists until it is live and the input checklist passes.

**Correction to the loan above (2026-10-10):** nba-sim-team-adj-473 WITHDREW the code-loan request. Per the user's
decision relayed by d48f3a34, the approved change is the DATA file only.
- It will write `nba_sim_total_inputs.json` = {"skip_def_subtraction": true} to the fleet's NBA processed root in its
  deploy, recorded there as a cross-lane write. The reader code is untouched.
- Checked 2026-10-10: no fleet copy existed (`/home/amyn/syndicate-prod/data/nba_source/data/processed`), so there is
  nothing to merge.
- Reachability field: market_anchor.nba_total_inputs on every NBA sim.

**Final #473 shape (2026-10-10, from nba-sim-team-adj-473; the withdrawal of the withdrawal):**
- (a) The DATA file `nba_sim_total_inputs.json` = {"skip_def_subtraction": true} on the fleet; skip_outs_penalties
  is not set.
- (b) No-stack is coupled to `SYNDICATE_NBA_TEAM_INPUTS` inside `_engine_for_league_local` (on a loan from P1). With
  the flag on, and ABSENT = ON, `_engine_for_league_local("nba")` returns the `nba:nostack` engine object.
- **For every future NBA sweep from this lane:** set `SYNDICATE_NBA_TEAM_INPUTS` EXPLICITLY in the launch line.
  - With it on, a sweep inherits team_prior_stacks_on_target = False at the engine level regardless of the cfg lever.
  - `=0` gives the old stacking engine and neutral team inputs.
- This lane's engine tests now pin the flag to 0 when fetching the engine (09e3d940).

**Code loan NOT taken (final, 2026-10-10):** `_nba_total_inputs_switch_local` and tests/test_nba_sim_total_inputs.py
stay untouched.
- skip_def ships ONLY as the data file {"skip_def_subtraction": true} on the fleet NBA processed root, written at the
  #473 deploy and recorded in deploys.md. market_anchor.nba_total_inputs shows it per sim.
- **ROLLBACK of skip_def = delete that file.** `SYNDICATE_NBA_TEAM_INPUTS=0` rolls back the ratings, starters and
  no-stack, but NOT skip_def.
- The key is this lane's to control. Owed from nba-sim-team-adj-473: the deploy SHA plus the input-checklist reading
  (that lifts the NBA re-fit hold).

**#473 option A LIVE (reported by nba-sim-team-adj-473, re-read here 2026-10-10 15:09Z):**
- Code a31ba2bf reached the fleet via ff to 62909c36 at 14:54:10Z.
- This lane's key file, checked directly: `/home/amyn/syndicate-prod/data/nba_source/data/processed/nba_sim_total_inputs.json`
  = `{"skip_def_subtraction": true}` (31 bytes, mtime 15:06:05Z), matching deploys.md 0974846c.
- At 15:09Z the newest fleet NBA sim was smart_sim_2026-10-10_TOR_LAC.json from 12:38 local, BEFORE the file. No sim
  has read it yet, so the first market_anchor.nba_total_inputs reading is owed (their watcher).
- Owed by that lane: todo #695, the regular-season totals reading (≥ 30 finals; delete the file if totals stay
  ≥ ~+2 worse than OFF).
- The NBA re-fit hold stands until the post-deploy input checklist passes.

## Phase 2 #2b — score_effect_k FINE GRID, PRE-REGISTERED 2026-10-10 (hold lifted by nba-sim-team-adj-473 after its post-deploy checklist), BEFORE running

**Inputs re-checked in THIS lane's replay** (code origin/main b0c8c6b7, which carries #473; probe 2025-11-13 + 2026-02-25,
18 engine calls):
- team_adj present and non-neutral 18/18;
- starter flags non-zero 18/18, after scratch-builder fix a7a6fdf3 (as-of player_checks).
- Earlier replays had starters 0/18, so EVERY earlier NBA reading in this file used starters unfed.

**Config (all explicit in the launch line):**
- SYNDICATE_NBA_TEAM_INPUTS=1;
- J1 levers + team_prior_stacks_on_target=0;
- the six ported switches;
- nba_sim_total_inputs.json both keys (the accepted config; the fleet has skip_def only);
- calibration files calfiles_sw.

**Run:**
- Grid k ∈ {0 (control, the new baseline under the new inputs), 0.001, 0.002, 0.003}.
- The same 12 dates, 200 draws, nice 19.

**Readings / calls (as #2):**
- Primary: within-game H2-on-H1 (real −0.174) and Q4 (real −0.141).
- **Confirmed** for a k whose H2 and Q4 are both within ±0.05 of real, with S8 margin moving toward 15.21 by more
  than run noise and no guard (mean margin vs market, S8 total, S3, S1, total bias) worse than run noise.
- If two grid points qualify, the one with H2 nearer real is taken. No interpolated k is adopted.
- A confirmation is followed by a full FIT re-run. The chosen k and its readings are then sent to P3
  (nba-native-live-resim). VALIDATION is untouched.

### Phase 2 #2b — FINE GRID RESULT 2026-10-10 ~16:30Z (11:30 AM CDT)

**Run:** #473 inputs fed (team_adj + starters 18/18), SYNDICATE_NBA_TEAM_INPUTS=1, the accepted config. 12 dates,
87/87 games each, 17,400/17,400 engine calls with every lever and switch.

| k | H2-on-H1 (real −0.174) | Q4 (real −0.141) | within-game SD | S8 margin (real 15.21) | S8 total | blowouts (real 0.253) | mkt slope | total bias |
|---|---|---|---|---|---|---|---|---|
| 0 (new baseline) | −0.015 | −0.003 | 17.52 | 17.65 | 18.21 | 0.280 | 0.939 | −0.20 |
| 0.001 | −0.085 | −0.044 | 16.10 | 16.22 | 18.32 | 0.253 | 0.925 | −0.16 |
| 0.002 | −0.162 [−0.180, −0.147] | −0.085 [−0.096, −0.075] | 14.82 | **14.91** | 18.38 | 0.222 | 0.938 | +0.38 |
| 0.003 | −0.233 | −0.127 | 13.72 | 13.85 | 18.44 | 0.197 | 0.944 | +0.40 |
| old inputs k = 0 (MB_k000) | +0.007 | +0.000 | 17.56 | 17.71 | 18.30 | 0.274 | 0.919 | −0.48 |

**VERDICT by the letter: NOT CONFIRMED.** No grid point has BOTH slopes within ±0.05 of real.
- k = 0.002: H2 PASS (off 0.012), Q4 FAIL (off 0.056).
- k = 0.003: Q4 PASS (off 0.014), H2 FAIL (off 0.059).
- No interpolated k is adopted (pre-registered).
- Guards hold at every k: sim-vs-market slope 0.93-0.94, total bias within 0.4, S8 total ~18.2-18.4.

**Reading, NOT a re-score:**
- One uniform per-shot k cannot match both the half-level and the Q4-level reversion. Real reversion is relatively
  stronger in Q4.
- That Q4 excess is the territory P3 (nba-native-live-resim) owns: end-game intentional fouling and clock management.
- k = 0.002 matches the H2 slope and the S8 margin SD (14.91 vs 15.21, the closest of any config so far); its Q4
  shortfall would be left to P3's end-game mechanisms.
- The new #473 inputs alone moved H2 to −0.015 and the mkt slope to 0.939 (from 0.919).
- **User decision owed:**
  - accept k = 0.002 with the Q4 tolerance overridden and P3 owning the Q4 remainder;
  - pre-register a late-weighted variant;
  - or keep k off.

**USER DECISION 2026-10-10: "Accept k=0.002".**
- The Q4 tolerance miss (−0.085 vs real −0.141, off 0.056 against ±0.05) is overridden as the user's decision.
- The Q4 remainder is left to P3 (nba-native-live-resim: end-game fouling / clock).
- `score_effect_k = 0.002` joins the accepted Phase 2 config.
- **Next (pre-registered):** the full FIT re-run with k = 0.002 on the #473 inputs, launched 2026-10-12 ~13:40Z.
  - 3 workers, nice 19, SYNDICATE_NBA_TEAM_INPUTS=1.
  - Walk-forward calibration files for all FIT dates: 105 files, C:	mpball_sc\calfiles_sw_all.
  - Then k and its readings go to P3.
- Nothing in production.

**#473 CLOSED + VERIFIED in production (reported by nba-sim-team-adj-473; re-read here 2026-10-12 ~13:45Z):**
- All 8 fleet NBA sims since the deploy (10-11 + 10-12) carry
  market_anchor.nba_total_inputs = {skip_def_subtraction: true, skip_outs_penalties: false}, with
  team_advanced_priors applied on each.
- First: smart_sim_2026-10-11_CHA_MIL.json (05:43:19Z). Deploy a31ba2bf; fleet 64909dba.
- **todo #695 handed to this lane:** the regular-season totals reading (≥ 30 finals; delete the data file if
  published totals stay ≥ ~+2 worse than OFF).

## Phase 2 #2c — LINEUP POOLS GAP + score_effect_k RE-MEASURE, PRE-REGISTERED 2026-10-12, BEFORE running

**Gap (reported by nba-lineup-pools, eb2ba139; verified here):**
- The replay scratch builder DELETED rotation_stints_history.{csv,parquet} (REMOVE_ALWAYS), and the pristine copy
  had neither file. So every replay in this lane, including the #2b fine grid that chose k = 0.002, ran with NO
  engine lineup pools (`no_rotation_stints_history`). Production regular-season sims carry them.
- Fix 2cb08409: the CSV is kept and truncated as-of (date < slate); the parquet is still removed, so the reader
  (parquet first) falls back to the truncated CSV.
  - The production copy is in pristine: 63,971 rows, 2025-10-02..2026-10-11, 40,739 in the FIT window.
  - The reader also filters date < slate within 28 days, same phase.
- Probe (2 dates, 18 calls): lineup pools home 18/18, away 16/18; team_adj 18/18; starters 18/18.
- The stopped full-FIT k = 0.002 run (17/109 dates, no pools) is kept as a reference only.

**Re-measure:**
- The #2b grid again, k ∈ {0, 0.001, 0.002, 0.003}, same 12 dates, same config, now with lineup pools.
- **Decision rule (fixed now):**
  - If k = 0.002 still has H2 within ±0.05 of real and S8 margin moves toward 15.21 by more than run noise (the
    user's acceptance covered the Q4 miss), k stays 0.002 and the full FIT re-run follows.
  - If another grid k fits H2 better under the #2b rule, or 0.002 no longer fits H2, the choice goes back to the
    user.
- **Open check, not in this step:** REMOVE_ALWAYS also deletes pair_minutes_history, play_context_history,
  lineup_player_baselines, lineup_teammate_effects and pbp_espn_history. Whether production sims consume them is
  unverified. Run the engine input checklist on a replay corpus before the full FIT.

**#2c open check, partly answered (2026-10-12, grep over syndicate/):** the other REMOVE_ALWAYS histories.
- pair_minutes_history, play_context_history: read only by artifact_publisher (allowlist), NOT by the sim. Deleting
  them in replays is harmless.
- pbp_espn_history.csv: read in basketball_props_smart_sim.py ~:2097 as a FALLBACK (game-id map path). It is unclear
  whether production takes that branch.
- **lineup_teammate_effects:** applied to player priors by the native orchestrator
  (orchestrator/smart_sim.py:1534-1545, connected_game._apply_lineup_teammate_effects_to_priors). Production has the
  file.
  - It is a FITTED artifact over all history, so copying it into a replay would leak future games; that is why the
    builder deletes it.
  - Replays therefore run WITHOUT teammate effects while production runs WITH them.
  - The size of that effect on the score-effect / margin readings is UNMEASURED.
  - Reproducing it as-of needs a per-date rebuild.
  - **Recorded as a known replay-vs-production difference. Not fixed in #2c.**

### Phase 2 #2c — RESULT 2026-10-12 ~15:45Z (10:45 AM CDT): k = 0.002 STAYS (with lineup pools)

**Run:** lineup pools + #473 inputs fed, SYNDICATE_NBA_TEAM_INPUTS=1, accepted config. 12 dates, 87/87 games each,
17,400/17,400 engine calls with every lever and switch.

| k | H2-on-H1 (real −0.174) | Q4 (real −0.141) | within-game SD | S8 margin (real 15.21) | S8 total | blowouts (real 0.253) | mkt slope | total bias |
|---|---|---|---|---|---|---|---|---|
| 0 | +0.000 | +0.002 | 17.58 | 17.74 | 18.42 | 0.279 | 0.888 | −0.64 |
| 0.001 | −0.082 | −0.045 | 16.07 | 16.26 | 18.39 | 0.253 | 0.933 | −0.52 |
| **0.002** | **−0.170** [−0.182, −0.154] | −0.084 [−0.094, −0.074] | 14.79 | **14.94** | 18.29 | 0.222 | 0.925 | −0.37 |
| 0.003 | −0.236 | −0.126 | 13.69 | 13.84 | 18.67 | 0.199 | 0.939 | −0.07 |
| no pools, 0.002 (#2b) | −0.162 | −0.085 | 14.82 | 14.91 | 18.38 | 0.222 | 0.938 | +0.38 |

**VERDICT per the #2c rule:** k = 0.002 STAYS.
- H2 is within ±0.05 (off 0.004).
- S8 margin goes 17.74 → 14.94, far beyond noise.
- No other grid k fits H2 better.
- Lineup pools barely move the k = 0.002 readings. Q4 still misses (user override, remainder to P3).

**Next:**
- message P3 k = 0.002 (its fit reads ~/nba_live_bt/k_value.json);
- the full FIT re-run with k = 0.002 + lineup pools, launched 2026-10-12 ~15:50Z.

### Phase 2 #2 — FULL FIT CONFIRMATION, score_effect_k = 0.002 with lineup pools (read 2026-10-12 ~20:00Z, 3:00 PM CDT)

**Run:** fit_k002_pools, 2026-10-12 15:45Z-19:55Z, 109 dates; the 2 NBA Cup dates fail as always. All engine calls
carry every lever and switch. Paired 791 games. Inputs: #473 team_adj + starters, lineup pools, accepted config,
105 walk-forward calibration files, SYNDICATE_NBA_TEAM_INPUTS=1.

| 791 FIT games | real [CI] | full J1 (Phase 2 #1) | full combo (+ports, no k, no calib) | **full k = 0.002 + pools** |
|---|---|---|---|---|
| H2-on-H1 (demeaned) | −0.174 | −0.001 | −0.004 | **−0.172** [−0.176, −0.167] |
| Q4 | −0.141 | +0.001 | −0.004 | −0.093 [−0.097, −0.090] |
| S8 margin SD | 14.00 [13.19, 14.71] | 18.89 | 17.65 | **14.91** (just outside) |
| S8 total SD | 18.29 [17.42, 19.22] | 18.95 | 18.59 | **18.46** IN |
| S5 blowouts, all | 0.230 [0.202, 0.260] | 0.337 | 0.280 | **0.228** IN |
| sim-vs-market margin slope | 1.0 | 1.588 | 0.867 | 0.918 |
| total bias vs actual | — | +0.71 | −5.61 | **−0.22** |

- **Guard rows vs full J1:**
  - TOWARD real: S1 pace 113.1 (real 114.0), S3 P1-P4, S5 all buckets, S6, S7, S8 total, S9 3PA. Inside the CI
    now: S3 P3/P4, S5 0-4 / 4.5-8 / all, S7 4.5-8, S8 total, S9.
  - **AWAY:**
    - S10 top-5 minutes when the final |margin| ≥ 20: 29.7 → 31.7 (real 26.9). Starters now play a FLAT 31.7
      regardless of game script; the new starter flags, with no blowout rest.
    - S11 foul-outs 0.361 → 0.473 (real 0.193).
  - Both are input/rotation effects, not k. They are Phase 2 #4 (minutes vs game script) and a foul-out item.
- **VERDICT:** the 12-date k = 0.002 readings REPRODUCE on the full FIT (H2 −0.172 vs −0.170). k = 0.002 is
  confirmed. The Q4 remainder (−0.093 vs −0.141) stays with P3.
- Still a PROPOSAL: production k = 0. Adoption follows the end-of-Phase-2 VALIDATION read.
- Real readings note: the readout scripts print the 12-date real values for S8 margin / blowouts (15.21 / 0.253).
  The full-FIT reals are 14.00 / 0.230 (table above).

## Phase 2 #4 — MINUTES vs GAME SCRIPT, PRE-REGISTERED 2026-10-12 (user: "start phase 2#4 minutes vs game script"), BEFORE measuring

**What the S10 row actually measured:** the sim side of S10 is the INPUT minutes. The engine's per-player `min`
(native engine.py:1798) is `mins[i]`, constant across draws, and the harness keeps minutes once per game. So
"starters flat at 31.7 regardless of game script" is true by construction of the INSTRUMENT. It says nothing yet
about simulated playing time.

**What the engine does in blowouts (read, native engine):**
- When `blowout` (quarter-start: Q3+ |margin| ≥ 18, or Q4 ≥ 15), it skips the lineup pools and samples a lineup
  each possession with context weights (`_contextual_minutes_weights` blowout branch).
- The dedicated bench boost (`sample_lineup_minutes_weighted(..., blowout_boost_bench)`, cfg `bench_weight_boost`
  1.35) is hard-coded `blowout_boost_bench=False` at both call sites (~:1290, :1299). It is DEAD.
- No per-draw playing time is reported.

**Step 1 — instrument, no engine change:**
- The harness counts per draw the possessions each player is on court, by wrapping the two lineup producers in the
  harness process only:
  - engine module `_pick_lineup_from_pool`, attributed to home/away by the lineups object's identity;
  - the LeagueEngine's bound `sample_lineup`, attributed by the players frame's identity.
- Sim minutes for player i = on-court possessions / team possessions × 48 (regulation).
- Per draw: the mean sim minutes of the top-5 by INPUT minutes, per team, keyed to the draw's final |margin|.
- **Reachability:** the counted team possessions per draw must equal the engine's possession count (sum of lineup
  selections), and the mean sim minutes over all draws must be ≈ the input minutes share.

**Readings (accepted config incl. score_effect_k = 0.002 + lineup pools, the same 12 dates, 200 draws):**
- **S10-sim:** top-5 mean minutes by final |margin| bucket (≤ 6, 7-19, ≥ 20), vs real ESPN starters (FIT window:
  31.3 / 30.0 / 26.9).
- The game-script SLOPE: the minutes drop from ≤ 6 to ≥ 20, real −4.4.
- Foul-outs alongside (real 0.193, sim 0.473 on the full FIT).

**Hypotheses:**
- **H-M1:** the sim's starter minutes drop less with margin than real: sim ≥ 20-bucket drop < 50% of the real −4.4.
  - Falsified if the sim drop is within ±1.5 min of real.
- **H-M2:** foul-outs track starter on-court time: foul-outs higher in draws where the top-5 play more.

**If H-M1 holds** (next, separately pre-registered):
- a default-off lever enabling the dead blowout bench boost (cfg field + the two call sites), on an engine.py LOAN
  from basketball-native-engine;
- swept against the S10-sim slope;
- guards S8 margin, S5, H2/Q4, totals.

**#4 side finding (2026-10-12, code read): the PREGAME engine loop has NO foul-out disqualification.**
- `_fouled_out_names` (resume.py) is used only in the RESUME branch (engine.py ~:1014-1021), to drop pool lineups
  containing players who already fouled out in a live state.
- In a pregame draw a player who reaches 6 PF stays on court, keeps playing and keeps fouling.
- Consistent with S11: foul-outs 0.473/game vs real 0.193 (full FIT), up from 0.361 once #473 starters put
  starters on court more.
- The sim's "foul-outs" count players ending ≥ 6 PF, so a missing disqualification inflates it directly. It likely
  also inflates star minutes and stats in high-foul draws.
- **Ownership:** foul trouble is P3's under the agreed split (nba-native-live-resim), but this is a PREGAME gap.
  Flagged to P3 and to the user; not fixed in #4.

**Foul-out disqualification: TAKEN by P3** (nba-native-live-resim, 2026-10-12). engine.py's live-mechanism section is now
P3's.
- Default-off EventSimConfig field, byte-identical off, graded vs real 0.193 on top of k = 0.002 + pools. Then
  foul-trouble benching.
- Applies to pregame too; enabling it for pregame is a user decision P3 brings.
- **Interaction rule for #4:** P3's disqualification and any #4 blowout-rest lever BOTH move starter minutes.
  Whichever lands second is measured JOINTLY with the first on (mechanism vs estimator), never assumed additive.

**#4 ownership split with P3 (agreed 2026-10-12):**
- **BLOWOUT REST** (`blowout_boost_bench`, a pregame-shape lever): this lane.
- **P3:** "asymmetric garbage time", built ON TOP of it (with it ON) for the band-dependent asymmetry it cannot
  express: the trailer concedes first at 11-20 from 6:00 Q4, the leader benches first at 21+, the trailer's pace
  rises. Also P3's: foul-out disqualification and foul-trouble benching.
- P3 builds no separate leader-bench lever.
- Order: whichever of #4 and P3's M-FT lands second is measured with the first ON.
- Owed to P3: the #4 starter-minutes-by-margin baseline (M4_base, running).

### Phase 2 #4 — BASELINE RESULT 2026-10-12 ~22:30Z (5:30 PM CDT): simulated starter minutes vs game script

**Run:** M4_base, the accepted config incl. k = 0.002 + lineup pools + #473 inputs, --track-oncourt. 12 dates, 87
games, 17,400/17,400 engine calls with levers; 0 unattributed possessions.

| final \|margin\| | real ESPN starters min (team-sides) | sim top-5 min (team-side draws) | sim INPUT top-5 min |
|---|---|---|---|
| ≤ 6 | 31.06 (n 44) | 32.27 (10,290) | 32.04 |
| 7-19 | 30.77 (90) | 31.96 (16,452) | 32.05 |
| ≥ 20 | 26.69 (40) | **31.11** (8,058) | 32.05 |

- Game-script drop (≥ 20 minus ≤ 6): real −4.38, sim −1.17.
- **H-M1 HOLDS:** the sim drop is < 50% of real. In ≥ 20-pt games sim starters play +4.4 min more than real.
- **H-M2:** foul-outs rise with draw top-5 minutes, slope +0.0142 per minute. Mean foul-outs 0.379 (real 0.193;
  the disqualification gap is P3's).

## Phase 2 #4b — BLOWOUT BENCH REST lever, PRE-REGISTERED (before any engine change)

**Mechanism:** the dead bench boost in `sample_lineup_minutes_weighted` (top-5 by minutes weight ÷ b, the rest × b,
n ≥ 8) is hard-coded off at the two blowout-path sampler call sites (native engine ~:1290, :1299).
- New `EventSimConfig.blowout_bench_rest: bool = False`; when True, those two calls pass
  `blowout_boost_bench=blowout`.
- Strength = the existing `bench_weight_boost` (1.35).
- Off = byte-identical: proven on the 5,400-call corpus parity + seeded sha.
- **LOAN needed:** engine.py, from P3 (nba-native-live-resim), whose section covers the EventSimConfig fields.

**Sweep:** the accepted config, --track-oncourt, the same 12 dates. Points: rest off (= M4_base) / rest on with
b ∈ {1.35, 2.0, 3.0}.

**Readings:**
- PRIMARY: the sim ≥ 20 bucket top-5 minutes vs real 26.69, and the drop vs real −4.38.
- **Guards** (run noise): the ≤ 6 bucket unchanged within 0.5 min; S8 margin SD, S5 blowouts, H2/Q4 slopes, total
  bias, and foul-outs not worse.
- **Confirmed** for a b whose drop is within ±1.5 min of real with all guards holding. If none, refuted: the blowout
  flag (quarter-start Q3+ ≥ 18 / Q4 ≥ 15) is too coarse a trigger. P3's band-dependent asymmetric garbage time is then
  the next candidate.

**#4b AMENDMENT (2026-10-12, BEFORE any engine change):**
- The engine.py LOAN is granted by P3: blowout_bench_rest field + the two sample_lineup blowout_boost_bench arguments
  only.
- Condition: branch from P3's commit. Its `foul_out_in_sim` + `foul_trouble_bench_mult` edit the same lineup block
  and land after its corpus replay (~1 h).
- **Arms are now doubled:** every #4b point is run with P3's two fields OFF and ON (foul_out_in_sim on,
  foul_trouble_bench_mult 0.05, P3's chosen value).
- Read foul-outs in each arm too (real 0.193; P3's fit alone 0.213).
- Same readings and confirmation rule otherwise.

**#4b lever BUILT (1e85bbc5)** on P3's c9d6795e; the engine.py loan is covered.
- `EventSimConfig.blowout_bench_rest` (default False); the two sampler calls pass `blowout and cfg.blowout_bench_rest`.
- **Off checks:** synthetic parity 0 mismatches; parity tests 23/23; new tests 3/3.
- **Effect** (fixture with real minutes): blowout lineups' top-5 on court go 3.05 → 1.73 per lineup at boost 3.
- **Two facts found while testing:**
  1. The boost ranks its "top-5" by the weights it is handed, which in blowouts are already blowout-adjusted
     (starters ×0.76-0.92, bench ×1.34). A heavy-minutes 6th man (24 min → weight 32.2) outranks a starter
     (36 → 27.4), so the boost can penalise him and spare a starter. That is the engine's existing design; it is
     recorded, not changed.
  2. A test frame with only `min` (no `_sim_min`) gives every player equal base weight. The boost then ranks the
     BENCH as top-5 and INVERTS (top-5 on court rose 1.9 → 4.2). The tests now use `_sim_min`, as the engine does.
- **Running since 00:19Z 10-13:**
  - the 5,400-call corpus parity proof on code with the edit;
  - the 8-arm #4b sweep: b ∈ {off, 1.35, 2, 3} × P3 foul-trouble fields off/on, --track-oncourt, 12 dates.

**#695 note (2026-10-13):** P3's partial regular-season gate (~375 games, k = 0.002, live mechanisms off) shows the
native re-sim over-projecting rest-of-game totals by ~+3. Hypothesis (d48f3a34): skip_def is the source.
- **This lane's reading:** skip_def's effect depends on the CONFIG.
  - **In production today** (EXACT_TARGET_CALIBRATION off, no NBA calibration file): the engine overshoots its target
    by ~+5.7. Without skip_def the target is ~−4.5, so published ≈ +1.2 over actual. With skip_def the target is
    ~−3.0, so published ≈ +2.7 over actual. That is consistent with P3's +3.
  - **In the accepted Phase 2 config** (EXACT + the six ports + calibration + skip_def): full-FIT total bias −0.22.
- P3 has been asked to grade skip_def ON vs OFF in the PRODUCTION config only (vary only the data file).
- The likely decision for the user: revert the file as an interim fix, or ship the Phase 2 totals stack (EXACT +
  builder) with it. Owed when P3's numbers land.

### Phase 2 #4b — RESULT (sweep done 2026-10-13 02:00Z; read 13:45Z)

**Off proof:** corpus parity on code with 1e85bbc5: 5,400/5,400, 0 mismatched (NBA 3,000, WNBA 2,400), PASS. The
engine.py LOAN is RETURNED to nba-native-live-resim.

**Sweep:** 8 arms, 12 dates, 87/87 games each, 17,400/17,400 engine calls with levers, --track-oncourt.

| arm (rest b × P3 FT) | top-5 min ≤ 6 / 7-19 / ≥ 20 | drop (real −4.38) | foul-outs (real 0.193) | H2 | Q4 | S8 margin (real 15.21) | blowouts (real 0.253) | mkt slope | total bias |
|---|---|---|---|---|---|---|---|---|---|
| off, P3 off | 32.29 / 31.95 / 31.15 | −1.14 | 0.383 | −0.171 | −0.090 | 14.86 | 0.224 | 0.945 | −0.23 |
| 1.35, P3 off | 32.13 / 31.74 / 30.48 | −1.65 | 0.374 | −0.189 | −0.098 | 14.82 | 0.224 | 0.929 | −0.08 |
| 2, P3 off | 32.12 / 31.42 / 29.59 | −2.53 | 0.365 | −0.176 | −0.089 | 14.95 | 0.221 | 0.920 | −0.09 |
| **3, P3 off** | 32.00 / 31.15 / 28.98 | **−3.02** | 0.372 | −0.174 | −0.096 | 14.89 | 0.221 | 0.907 | −0.23 |
| off, P3 on | 31.63 / 31.35 / 30.44 | −1.19 | 0.151 | −0.174 | −0.088 | 14.93 | 0.224 | 0.930 | −0.36 |
| 1.35, P3 on | 31.51 / 31.06 / 29.92 | −1.59 | 0.146 | −0.190 | −0.098 | 14.67 | 0.218 | 0.921 | −0.26 |
| 2, P3 on | 31.46 / 30.83 / 29.02 | −2.44 | 0.150 | −0.164 | −0.085 | 14.93 | 0.220 | 0.909 | −0.26 |
| **3, P3 on** | 31.32 / 30.56 / 28.29 | **−3.03** | 0.154 | −0.198 | −0.100 | **14.75** | **0.216** | 0.896 | +0.00 |

- Real starters (same 87 games): 31.06 / 30.77 / 26.69.

**VERDICT by the letter:**
- **P3 OFF, b = 3: CONFIRMED.** The drop is within ±1.5 min of real (−3.02 vs −4.38). The ≤ 6 bucket moves −0.29
  (≤ 0.5). H2, Q4, S8 margin, S5, total bias and foul-outs are all within noise or better.
- **P3 ON, b = 3: GUARD FAIL** (the decisive arm, since P3's c9d6795e landed first). The drop passes (−3.03), but:
  - S8 margin 14.93 → 14.75 (−0.18 vs noise ~0.13) and S5 0.224 → 0.216 (−0.008 vs ~0.006), both away from THESE 87
    games' real values (15.21 / 0.253);
  - the H2 overshoot −0.198 is within ±0.05.
- b = 2 misses the drop in both arms (−2.53 / −2.44).
- **Not re-scored, argument for the user:** on the full FIT the real S8 margin is 14.00 and blowouts 0.230 (sim
  full-FIT 14.91 / 0.228). The same −0.18 / −0.008 moves would be TOWARD the full-FIT real values.
- P3's foul-trouble ON brings foul-outs to ~0.15 vs real 0.193 (P3's own fit read 0.213).
- **User decision owed:**
  - accept b = 3 with P3 on (override the two small guard misses on the 12-date sample);
  - or run the joint arm on the full FIT first, where the reals are tighter;
  - or keep the lever off.

**USER DECISION 2026-10-13: "accept bench rest b=3 with P3's fixes on".**
- The two P3-ON guard misses (S8 margin −0.18, S5 −0.008 on the 12-date sample) are overridden as the user's decision.
- The accepted Phase 2 config now adds `blowout_bench_rest = True`, `bench_weight_boost = 3.0`, together with P3's
  `foul_out_in_sim = True` + `foul_trouble_bench_mult = 0.05`.
- Not enabled in production. Adoption follows the end-of-Phase-2 VALIDATION read; P3's own enablement decision is
  separate.
- **Next per protocol:** the full FIT re-run of the accepted config with these on, then Phase 2 #3 / #5.

### Phase 2 #4 — FULL FIT of the combined config (read 2026-10-13 ~19:25Z, 2:25 PM CDT)

**Run:** fit_rest3, 14:00Z-19:21Z, 109 dates (the 2 Cup dates fail as always), all engine calls with levers, paired 791.
- Config: accepted Phase 2 + k = 0.002 + blowout_bench_rest b = 3 + P3 foul_out_in_sim + foul_trouble_bench_mult 0.05,
  lineup pools, #473 inputs, walk-forward calibration files.

| 791 FIT games | real | k = 0.002 full FIT (no rest, no P3 FT) | **combined (fit_rest3)** |
|---|---|---|---|
| sim top-5 minutes, ≤ 6 / 7-19 / ≥ 20 final margin | 31.32 / 29.98 / 26.87 | (INPUT 31.7 flat) | **30.89 / 30.08 / 27.63** |
| game-script drop | −4.45 | ~−1.2 (12-date) | **−3.26** (within 1.5) |
| foul-outs/game | 0.193 [0.162, 0.226] | 0.473 | **0.206 IN** |
| H2-on-H1 / Q4 | −0.174 / −0.141 | −0.172 / −0.093 | −0.171 / −0.092 |
| S8 margin SD | 14.00 [13.19, 14.71] | 14.91 | 14.96 |
| S5 blowouts, all | 0.230 | 0.228 | **0.230** |
| total bias | — | −0.22 | −0.22 |

- Other guard rows vs the k = 0.002 full FIT: all moves ≤ 0.05 (S1 −0.01, S3 ≤ +0.05, S8 total +0.07, S9 −0.03,
  S7 ≤ 0.001), within run noise.
- The 12-date P3-ON guard misses (S8 margin −0.18, S5 −0.008) do NOT reproduce on the full FIT (+0.05 / +0.002).
- **VERDICT:** Phase 2 #4 DONE.
  - Simulated starter minutes now follow game script, within ~0.8 min of real in every bucket.
  - Foul-outs are inside the real CI.
  - Nothing else moves.
- Still a PROPOSAL (production unchanged).
- **Remaining Phase 2:** #3 FT bonus (P4's bonus-FT mechanism exists; S6 FTA still −2.3/team), #5 volume
  (S1 pace / S9 3PA now inside or near), the end-of-Phase-2 VALIDATION read.

**#695 READING (P3, findings_2026-10-09 §10a; production config, skip_def ON vs OFF, same seeds, 100 sims from the tip):**

| | n | ON (live) total bias | OFF total bias | paired OFF − ON | \|err\| change |
|---|---|---|---|---|---|
| regular season | 1,205 | +3.14 | +1.93 | −1.21 [−1.35, −1.08] | −0.01 [−0.16, +0.14] (MAE 15.49 vs 15.48) |
| postseason | 85 | +8.70 | +8.33 | −0.37 [−0.82, +0.08] n.s. | — |

- Minus the market: +3.89 / +2.68. Market MAE 14.60 beats both. Margin MAE n.s.
- This lane predicted +2.7 / +1.2: confirmed.
- **The #695 revert rule** (published totals ≥ ~+2 worse than OFF) **is NOT met**: a 1.2-pt level shift at zero MAE
  cost. **Keep the data file.**
- The remaining +1.9 regular-season overshoot is the engine overshooting its target with EXACT_TARGET_CALIBRATION
  off. Its fix is the Phase 2 totals stack (EXACT + the NBA calibration builder): full-FIT total bias −0.22.
- **The postseason +8.7 is NOT skip_def.** It is a separate open defect.
- **Integrity** (P3): 40 sampled pickle pairs differ only in targets/quarters, except 1/40 (code drift between the
  recording days, noise-level).
- Part 2, the in-game grade, is owed by P3 (~02:00Z).

**#695 part 2 (P3 §10b, in-game, k = 0, production config, regular season, paired n ~1,180 per checkpoint):**

| | end Q1 | end Q2 | end Q3 | 5:00 Q4 |
|---|---|---|---|---|
| skip_def OFF − ON, level | −0.92 | −0.64 | −0.29 | −0.11 |
| \|err\| change | −0.06 n.s. | −0.12 [−0.21, −0.03] | −0.07 [−0.13, −0.02] | −0.02 n.s. |
| bias ON → OFF | +2.94 → +2.02 | +1.82 → +1.17 | +1.99 → +1.70 | −0.14 → −0.26 |

- Margin n.s.; postseason all n.s.
- OFF still loses to pregame_rate on total at Q1-Q3.
- **Reading, with part 1:** skip_def is ~1/3 of the level and almost none of the accuracy (in-game |err| gains at Q2/Q3
  ≤ 0.12). The remaining overshoot is the EXACT-off engine term.
- **#695 stays KEEP.** The fix for the overshoot is the Phase 2 totals stack (EXACT + NBA calibration builder), a
  user decision. P3 re-gates on Phase 2-config inputs once the user accepts it.

**USER DECISION 2026-10-13: "Validate first".**
- The Phase 2 totals stack is NOT fast-tracked. The pre-registered order stands: finish Phase 2 (#3 FT bonus,
  #5 volume), read the held-out VALIDATION window once for the whole proposed config, then the user decides on
  production.
- Production NBA totals stay ~+2-3 high until then (known, measured by #695).

## Phase 2 #3 — FREE-THROW BONUS, PRE-REGISTERED 2026-10-13 (user: "start phase 2 #3 free-throw bonus"), BEFORE measuring

**Gap:** S6 FTA/team, full FIT combined config 21.04 vs real 23.35 [22.95, 23.76] (−2.3/team, outside the CI).
- The sim has no team-foul bonus: non-shooting fouls are PF only (`base_nonshooting_foul_per_poss`), never free
  throws.
- **Real targets (ESPN, regulation-only team-games):**
  - 12 sweep dates: FTA/team 22.69 (n 162), Q4 FTA/team 6.38, Q4 share 0.279;
  - full FIT: 23.41, Q4 share 0.291 (uniform would be 0.25).

**Mechanism (exists, default off; lane ncaab-native-live-tier, 3dcc513e; NBA rules in basketball_league_rules):**
- A bonus-eligible non-shooting foul is drawn at the start of a possession with rate `bonus_nonshoot_foul_per_poss`.
- In the NBA bonus (5th team foul per quarter, 4th in OT, 2nd in the last 2:00) it is a 2-shot trip that ENDS the
  possession; otherwise it is a PF.
- `bonus_second_half_mult` scales the rate after halftime.
- All three are EventSimConfig fields, so the levers need no engine change and no loan.

**Instrument:** `record_events` (an existing diagnostics cfg field, off in production) logs FTA events with their
quarter. The harness adds per-quarter team FTA to the compact draw when events are present. Reachability: the summed
event FTA equals box `team_total_fta` on every draw.

**Sweep** (the accepted config incl. k = 0.002 + rest b = 3 + P3 FT fixes; 12 dates):
- control (bonus off) + bonus on with rate ∈ {0.02, 0.04, 0.06}, h2_mult 1.0;
- plus the rate nearest real FTA re-run with h2_mult 1.5 (a second step, only if the Q4 share is short).

**Readings:**
- PRIMARY: FTA/team vs 22.69, and Q4 FTA share vs 0.279.
- **Guards** (run noise): total bias (bonus FTs add points the EXACT target solve does not know about), S8
  total/margin, H2/Q4 slopes, foul-outs (bonus fouls are PF), S1 pace.

**Calls:**
- **Confirmed** for a rate with FTA within ±0.5 of real AND Q4 share within ±0.02, with all guards within noise.
- If FTA fits but total bias rises > 1 pt, the mechanism is right but needs a target-solve interaction (recorded,
  user decision).
- **Refuted** if even 0.06 leaves FTA > 1 short: the shortfall is shooting-foul rate, not bonus.

### Phase 2 #3 — RESULT 2026-10-14 ~02:00Z (sweep done 01:53Z): bonus FT level fits; shape and foul-outs do not

**Run:** accepted config (k = 0.002, rest b = 3, P3 FT fixes, record_events), 12 dates, 87 games each, 17,400/17,400
engine calls with levers.

| bonus rate | FTA/team (real 22.69) | Q4 FTA share (real 0.279) | foul-outs (real 0.193) | sim team PF | total bias | H2 / Q4 slope | S8 margin |
|---|---|---|---|---|---|---|---|
| off | 20.99 | 0.252 | 0.154 | 15.21 | +0.05 | −0.170 / −0.097 | 14.81 |
| 0.02 | 21.78 | 0.254 | 0.252 | — | +0.26 | −0.176 / −0.089 | 14.95 |
| **0.04** | **22.83** | 0.254 | **0.379** | 19.05 | +0.69 | −0.165 / −0.091 | 14.89 |
| 0.06 | 24.26 | 0.253 | 0.529 | — | +1.52 | −0.180 / −0.093 | 14.85 |

- Real team fouls (ESPN `fouls`, 800 FIT team-games): **20.52/game**.

**VERDICT by the letter: NOT CONFIRMED.**
- Rate 0.04 fits the FTA level (+0.14), but the Q4 share stays flat (0.254 vs 0.279, off 0.025) and foul-outs rise to
  0.379.
- The H2/Q4 slopes, S8 margin and blowouts are within noise. Total bias +0.69 (< 1).

**What it showed (a belief overturned):** the foul-out rise is NOT too many fouls. The sim UNDER-fouls: team PF 15.2 vs
real 20.5, still 19.1 at rate 0.04.
- Foul-outs rise because realistic foul volume lands on too few players.
- P3's foul_trouble_bench_mult = 0.05 was fitted at ~5 too few team fouls a game, so it needs a re-fit WITH the bonus
  on (mechanism vs estimator).
- The flat Q4 share is the late-game fouling that P3's end-game intentional-foul mechanism models (off in this
  config).

**Next (to pre-register jointly with P3, nba-native-live-resim):**
- bonus 0.04 + P3's end-game fouling ON (its fitted p by deficit) + a joint re-fit of P3's foul_trouble_bench_mult
  against foul-outs 0.193 and team PF 20.5.
- Readings: FTA level and Q4 share, team PF, foul-outs, the guards.

### Phase 2 #3b — PRE-REGISTRATION 2026-10-14 ~02:00Z (before any run): joint foul re-fit with P3 (nba-native-live-resim)

**Why:** #3 showed the bonus fits the FTA level at 0.04/poss, but foul-outs reach 0.379, because P3's
foul_trouble_bench_mult = 0.05 was fitted when the sim committed ~5 fewer team fouls a game than real teams.

**Config:**
- The accepted Phase 2 config (k = 0.002, rest b = 3, P3 FT fixes, record_events), plus bonus_free_throws = 1 and
  bonus_nonshoot_foul_per_poss = 0.04.
- P3's end-game fouling ON, exactly as P3 fitted it (§7b), held FIXED and not re-fitted here:
  - endgame_foul_window_s = 120, endgame_foul_max_deficit = 10, endgame_foul_p_by_deficit = (0.2, 0.0, 0.2),
    endgame_foul_seconds = 5, endgame_extend_possessions = 1, endgame_foul_p = 0.
- foul_out_in_sim = 1, foul_trouble_thresholds = (2, 3, 4, 5), foul_trouble_release_s = 240.

**Grid:** foul_trouble_bench_mult ∈ {0.0, 0.01, 0.02, 0.05, 0.1}. The same 12 seed-7 sweep dates (87 games, 200 sims).

**Objective:** foul-outs per team-game, real FIT 0.193.

**A point PASSES only if all of these hold:**
- foul-outs within 0.193 ± 0.04;
- FTA/team within 22.69 ± 0.7;
- H2-on-H1 slope inside the real CI [-0.19, -0.155];
- Q4 slope no worse than #3's −0.091 by more than 0.01;
- S8 margin within 14.81 ± 0.6;
- |total bias| < 1.0;
- Q4 FTA share no further from 0.279 than #3's 0.254.

**Readings reported, not gated:**
- team PF/game against real 20.52. The bench mult is not expected to move volume.
- Q4 FTA share against 0.279.

**Pick:** among passing points, the smallest |foul-outs − 0.193|; ties go to the larger mult (less intervention).

**Then:**
1. P3 re-runs its game-matched §7 check (last-2:00 points + trailer FTA by deficit bucket, FIT only) at the picked point.
   A bucket outside the §7 FIT tolerance is re-fitted there.
2. A full FIT re-run.

**Fallback, pre-registered:** if mult 0.0 still overshoots foul-outs by more than 0.04, the next lever is
foul_trouble_thresholds (e.g. (2, 3, 4, 4)) or foul_trouble_release_s, not the mult. That gets its own pre-registration.
If no point passes for a reason other than foul-outs, #3b is NOT CONFIRMED and the failing reading is the next
diagnosis.

**Windows (double-dip disclosure):**
- P3's §7 VALIDATION 2026-03-01..04-12 is exactly this lane's held-out regular-season window, and P3 has already read it
  once for the end-game p.
- So the end-of-Phase-2 VALID read is NOT a first look for the end-game component. It stays a first look for
  everything else, and the 2026 play-in/playoffs part is untouched by both lanes.
- Report the end-game buckets on VALID as already-seen.

**Co-sign:** P3 co-signs this before the readings are read. The runs may start first; nothing is read until then.

**Harness change:** `--lever` takes a comma list as a tuple (scripts/basketball_scenario_rates.py, this commit).

**#3b AMENDMENT + CO-SIGN (P3, read at 18baf568; added 2026-10-14 02:00Z, before any reading):**

1. **The pick is PROVISIONAL.** The 12-date subsample is the one whose 0.15 foul-out reading did not reproduce (full FIT
   0.206).
   - The planned full-FIT re-run must also land foul-outs within 0.193 ± 0.04, with the FTA, H2/Q4/S8 and total guards
     holding.
   - If it does not, re-pick from the grid ON THE FULL FIT; never ship the subsample pick.
2. **Unit correction:** foul-outs are per GAME (both teams), not per team-game.
   - The sim's `fo` is per draw and real S11 0.193 is per game, so the comparison was already like for like. Only the
     pre-reg's label was wrong.
3. **Subsample base rate, real** (`real_nba.jsonl`, regular season):
   - FIT: 816 games, **0.194** foul-outs/game.
   - The 87 sweep games: **0.103**.
   - The subsample's own real rate is about half the FIT's (binomial SE on 87 games ≈ 0.047). The target stays the FIT
     0.193, but a subsample hit is weaker evidence, which is why (1) gates on the full FIT.

### Phase 2 #3b — RESULT 2026-10-14 02:50Z (sweep done 02:49Z; read after P3's co-sign): NOT CONFIRMED, no grid point passes

**Run:** 5 points, 12 dates, 87 games, 17,400/17,400 engine calls carrying the levers, 0 errors.

| bench_mult | foul-outs/game (target 0.193 ± 0.04) | FTA/team (22.69 ± 0.7) | Q4 FTA share (≥ 0.254 toward 0.279) | team PF (real 20.52) | H2 | Q4 slope (≥ −0.101) | S8 margin | total bias (< 1.0) |
|---|---|---|---|---|---|---|---|---|
| 0.0 † | 0.908 | 23.13 | 0.265 | 19.23 | −0.175 | −0.083 | 15.02 | +1.14 ✗ |
| 0.01 | 0.390 ✗ | 23.17 | 0.264 | 19.23 | −0.184 | −0.093 | 14.79 | +0.97 |
| 0.02 | 0.398 ✗ | 23.14 | 0.264 | 19.23 | −0.178 | −0.091 | 14.86 | +1.17 ✗ |
| 0.05 | 0.415 ✗ | 23.17 | 0.264 | 19.21 | −0.163 | −0.080 | 15.05 | +1.13 ✗ |
| 0.1 | 0.440 ✗ | 23.19 | 0.264 | 19.27 | −0.184 | −0.094 | 14.82 | +1.23 ✗ |
| #3 0.04 (end-game off, mult 0.05) | 0.379 | 22.83 | 0.254 | 19.05 | −0.165 | −0.091 | 14.89 | +0.69 |

- The real 87-game subsample base rate is 0.103; FIT is 0.194.
- FTA, H2, Q4 slope and S8 pass at every point. The Q4 FTA share moved toward real (0.254 → 0.264), so end-game fouling
  adds Q4 FTs, but it does not reach 0.279.

**† mult 0.0 is NOT "strongest benching". It is benching OFF.**
- engine.py:1088 reads `float(getattr(cfg, "foul_trouble_bench_mult", 1.0) or 1.0)`, so 0.0 becomes 1.0.
- 0.908 is the no-benching foul-out rate with the bonus and end-game on.
- A falsy-zero lever (learning: unknown/absent must not default permissive). The pre-registered fallback trigger
  ("if 0.0 still overshoots") was therefore not evaluable as written. P3 owns the code and has been told.

**What it showed:**
- The mult is SATURATED. From 0.1 down to 0.01 (near-total benching of a player in foul trouble) foul-outs only fall
  0.440 → 0.390.
- The excess is not something possession-level benching can reach. Candidates, untested:
  - the 240 s release window (nobody is benched late);
  - end-game intentional fouls charged to on-court players. End-game adds about +0.04 (0.379 → 0.415 at mult 0.05);
  - per-player PF concentration from the bonus foul assignment.
- Team PF stays 19.2 vs real 20.5, so volume is not the excess.
- End-game + bonus add about +0.45 total points (bias +0.69 → +1.13), which fails the total guard at 4 of 5 points.

**Next (not run, needs its own pre-registration):** diagnose WHEN and TO WHOM the sixth foul lands in the sim vs real
before choosing the pre-registered fallback lever (thresholds or release_s):
- quarter and clock of foul-outs;
- the PF share of each team's top fouler, vs ESPN player boxes.

### Phase 2 #3c — PRE-REGISTRATION 2026-10-14 02:55Z (before any run): WHEN and TO WHOM the sixth foul lands (diagnosis, P3 co-design)

**Also queued (P3's request):** re-run grid point bench_mult 0.0 with P3's fix ab6d34de (0.0 = full benching), as
`JF_m000b`. That evaluates the #3b fallback trigger as written: if 0.0 still overshoots 0.193 by more than 0.04, the
saturation is structural.

**Diagnosis run:**
- The #3b config at bench_mult = 0.05 (P3's fitted value), the same 12 dates.
- Instrumentation: a RESEARCH-ONLY patch on the WSL code copy, never on main. It is gated by a cfg field
  `diag_foul_outs` (default absent).
- Each possession snapshots the context: period, clock, release-window flag, each player's PF and the quarter's
  threshold, the foul-trouble list, the on-court line, and whether the possession was an end-game intentional foul.
- At the next possession start, or at game end, every player who crossed the foul limit since the snapshot is logged
  with that context.

**Categories, assigned in this priority order:**
- (b) end-game intentional foul possession;
- (a) inside the Q4 release window (the last 240 s, no benching);
- (d) a possession that added ≥ 2 PF and started BELOW the quarter threshold, so benching could not act;
- (c) started at or over the threshold outside the release window, so benching failed to remove him: depleted
  roster, first line, or < 5 eligible. Also logged: whether he was on the flagged trouble list.

This is a complete partition: reaching 6 from below the threshold with a single foul is impossible (thresholds 2/3/4/5,
OT 5).

**Real comparison** (ESPN cached summaries, FIT regular season, all ~816 games; the 87-game subsample has only ~9 real
foul-outs):
- Foul-out timing from play-by-play: the sixth personal foul, excluding technicals, by Q1–Q3, Q4 > 4:00, Q4 ≤ 4:00 and
  OT, against the sim's same windows.
- Top-fouler share: max player PF / team PF, and P(top fouler ≥ 5 PF), against the sim (a harness field `pfmax`, committed).

**Decision rule (P3's mapping):** compare categories by their share of the sim's EXCESS foul-outs per game over
real. Where real has the same window (a), the excess is sim − real in that window. For (b)/(c)/(d) the whole sim count
is treated as excess, since real has no comparable split.
- (a) largest and ≥ 40% → foul_trouble_release_s;
- (c) → roster depth / eligibility;
- (d) → foul_trouble_thresholds;
- (b) → end-game fouler choice;
- no category ≥ 40% → per-player PF assignment concentration, checked with the top-fouler share.

Diagnosis only: no parameter is chosen from this run. The chosen lever gets its own pre-registered sweep.

### Phase 2 #3c — RESULT 2026-10-14 03:27Z (runs done 03:26Z): the excess foul-outs are in the Q4 release window

**Fallback trigger, as written** (`JF_m000b`, mult 0.0 = full benching after P3's fix ab6d34de):
- foul-outs **0.386**/game (target 0.193 ± 0.04). The saturation is STRUCTURAL; the mult cannot fix it.
- FTA 23.08, H2 −0.181, Q4 −0.092, S8 14.81; total bias +1.17.

**Sim diagnosis** (`JF_diag`, mult 0.05, research-only instrumentation): 7,131 foul-outs logged over 17,400 draws.
The rows match the box foul-outs exactly (0.410/game both); smoke test 47 = 47.

| category (priority order) | sim/game | share |
|---|---|---|
| (b) end-game intentional possession | 0.037 | 0.09 |
| **(a) Q4 release window, last 240 s, no benching** | **0.331** | **0.81** |
| (d) multi-foul jump from below the threshold | 0.013 | 0.03 |
| (c) at/over the threshold, benching failed (all on the trouble list) | 0.029 | 0.07 |

**Timing vs real** (ESPN pbp, 816 FIT games). Real pbp finds 141 of the 158 box foul-outs; the second real column
scales to the box total.

| window | sim/game | real/game (pbp) | real scaled | sim − real |
|---|---|---|---|---|
| Q1–Q3 | 0.005 | 0.002 | 0.003 | +0.002 |
| Q4 > 4:00 | 0.035 | 0.053 | 0.059 | −0.024 |
| **Q4 ≤ 4:00** | **0.368** | 0.096 | **0.107** | **+0.261** |
| (Q4 ≤ 2:00, inside the row above) | — | 0.067 | 0.075 | — |
| OT | 0.002 | 0.022 | 0.025 | −0.023 |
| total | 0.410 | 0.173 | 0.194 | +0.216 |

- pbp counting excludes technicals and the duplicate "Offensive Foul Turnover" rows; including those had double-counted
  (390).
- The whole excess is in the last 4:00 of Q4: +0.261 of +0.216 (the other windows are slightly UNDER).
- **By the pre-registered mapping: (a), 81% → the lever is foul_trouble_release_s.**

**Top fouler** (pbp-independent, box):
- sim top-fouler PF 4.58, 24.4% of team PF, P(≥ 5) 0.541;
- real 4.30, 22.4%, P(≥ 5) 0.414.
- Mild concentration, secondary.

**CORRECTION to #3:**
- Real team PERSONAL fouls are **19.67**/team-game (ESPN player-box PF sum, 1,632 team-games).
- The 20.52 used in #3/#3b was ESPN's team "fouls" stat, which likely includes technicals.
- So the sim at 19.2 is only ~0.45 under real. "The sim under-fouls by ~5" was an artefact of the wrong target. The
  pre-bonus sim (15.2) was still ~4.5 under.

**Mechanism note (belief, untested):**
- Real players at 5 PF late in Q4 stay on the floor but foul less. The sim assigns a foul by `_prior_pf_pm` whatever
  the player's current PF.
- release_s trades closers' minutes for foul-outs. A "foul avoidance in trouble" weight on the fouler draw would be
  the more faithful mechanism (P3's domain; not built).

### Phase 2 #3d — PRE-REGISTRATION 2026-10-14 03:28Z (before any run): foul_trouble_release_s sweep (the lever #3c's mapping selected)

**Config:** the #3b config at bench_mult = 0.05, the same 12 dates.

**Grid:** foul_trouble_release_s ∈ {0, 60, 120, 180}. 240 is already measured (`JF_diag`/`JF_m005`, foul-outs
0.410/0.415).

**Objective:** foul-outs 0.193 ± 0.04 per game.

**Pass/fail guards, as in #3b:**
- FTA 22.69 ± 0.7;
- H2 inside [−0.19, −0.155];
- Q4 slope ≥ −0.101;
- S8 14.81 ± 0.6;
- Q4 FTA share no further from 0.279 than 0.254.

**One guard moved to a reading, disclosed:**
- |total bias| < 1.0 is now a READING. It failed at every #3b point (+0.97..+1.23) from the bonus + end-game points
  themselves, which the release window cannot move.
- This is a mechanism-vs-estimator debt: the NBA totals calibration was fitted without bonus or end-game fouling, so it
  must be RE-FIT on the chosen config before adoption.
- That re-fit is a REQUIRED step before the full-FIT read, not optional.

**Readings:**
- foul-outs in the Q4 ≤ 4:00 window vs real 0.107 and Q4 > 4:00 vs 0.059 (pbp scaled);
- P(top fouler ≥ 5) vs 0.414;
- starter minutes (`--track-oncourt` is not on in this config, so not read).

**Pick:** among passing points, the smallest |foul-outs − 0.193|; ties go to the LARGER release_s (closers play).
PROVISIONAL until the full FIT, per P3's amendment.

**If no point passes:** release_s is insufficient. The next candidate is the more faithful mechanism, "foul avoidance
in trouble" (a lower fouler-draw weight for a player at or over the threshold). It is unbuilt, P3's domain, and gets its
own pre-registration.

**#3d AMENDMENT + CO-SIGN (P3; recorded before any reading; the first launch was killed unread to add this):**

1. **New pass/fail guard: closers stay on.** For starters who reach a 5th PF in Q4 with ≥ 4:00 left, the on-floor share
   of the rest of Q4 must sit inside real **0.455 [CI 0.409, 0.501]**, widened to ±0.08 → **[0.375, 0.535]**.
   - Source: P3 findings_2026-10-09 §2d, `targets_fit/targets.json` `foul_trouble.5pf_in_q4.event_on_share`, n = 208.
   - P3's message quoted "real 0.60". That is the CONTROL (other starters, same clock, 0.601), not the event share.
     Corrected here from the file.
   - A release_s point that reaches 0.193 by sitting closers down FAILS.
2. **Reading:** mean starters on the floor in Q4, per possession, vs real `rotation_starters_on_floor_by_minute`
   minutes 37-48: close finals (≤ 10) 3.15, blowouts (≥ 20) 1.56.
3. **Instrumentation:** the research-only patch v2 (`fo_diag_patch2.py`, WSL copy only). Starters = the top 5 by
   minutes weight. It is possession-weighted, and a fouled-out player counts as off the floor.
   - Smoke test, synthetic 60 games: release 240 → share 0.354; release 0 → 0.121.
   - Harness keys `fot5`/`foq4` are committed.
4. **Grid extended to release_s ∈ {0, 60, 120, 180, 240}.** 240 is re-run, because the earlier `JF_diag` has no
   on-floor data.
5. The totals re-fit is a REQUIRED step before the full FIT. Ties go to the larger release_s.
6. **P3 is building `foul_trouble_foul_mult`** (foul avoidance in trouble, all windows, every fouler draw), default
   off, with a reachability test and the parity gate. It gets its own pre-registered sweep.

### Phase 2 #3e — PRE-REGISTRATION 2026-10-14 03:55Z (before any run): foul avoidance in trouble, `foul_trouble_foul_mult` (P3, 917b40a8)

**Mechanism:** P3, 917b40a8 on origin/main, corpus parity 5,400/5,400, default 1.0 = off.
- A player at or over the period threshold has his weight multiplied in EVERY fouler draw (shooting, non-shooting/bonus,
  end-game), in all windows, including the Q4 release window.
- It reallocates WHO fouls, not team PF.

**Config:** release_s = 240 (closers play), bench_mult = 0.05, thresholds (2, 3, 4, 5), bonus 0.04, end-game ON as
fitted, the same 12 dates, 200 sims.

**Grid:** foul_trouble_foul_mult ∈ {1.0, 0.7, 0.5, 0.3, 0.15}. 1.0 is the in-run control.

**Objective:** foul-outs 0.193 ± 0.04 per game.

**Pass/fail guards:**
- the #3d set: FTA 22.69 ± 0.7, H2 inside [−0.19, −0.155], Q4 slope ≥ −0.101, S8 14.81 ± 0.6, Q4 FTA share no further
  from 0.279 than 0.254;
- closers stay on: the 5th-PF-in-Q4 starter on-floor share inside [0.375, 0.535];
- **NEW, the mechanism's own target:** P(a starter fouls out by game end | his 5th PF lands in Q4 with ≥ 4:00 left)
  inside real **0.212 [0.161, 0.264]**.
  - Source: ESPN pbp + box starter flag, 240 events in 816 FIT games (P3's §2d counted 239 for the same state).
  - All players: 0.221.

**Readings:** total bias (the totals re-fit is a REQUIRED step before the full FIT), team PF vs real 19.67, foul-outs by
window vs real, P(top fouler ≥ 5) vs 0.414, Q4 starters on the floor vs 3.15 / 1.56.

**Instrumentation:** research copy `code_fa` = `code_diag` + P3's 917b40a8 engine hunks (patch applied cleanly; the
engine equals origin/main apart from the research-only diag) + patch v3 (fouled-out flag per 5th-PF event).
- Smoke test, synthetic 60 games, mult 1.0 → 0.3: P(6th | 5th) 0.328 → 0.154, foul-outs 0.867 → 0.467, team PF
  23.62 → 23.62 (unchanged).

**Pick:** among passing points, the smallest |foul-outs − 0.193|; ties go to the LARGER mult (less intervention).
PROVISIONAL until the full FIT (P3's amendment).

**Launch:** after the #3d sweep finishes (shared host memory). #3d and #3e are read as separate pre-registrations.

**#3e CO-SIGN (P3, as pre-registered at 8994c21c, before any reading):**
- Accepted as written.
- No real in-trouble PF/48 exists: §2d measured on-floor shares, not foul rates.
- If #3e passes with a borderline closers-on guard, P3 computes PF/48 from the P2 stints as a follow-up reading. #3e is
  not held for it.

### Phase 2 #3d — RESULT 2026-10-14 04:15Z (done 04:12Z, co-signed): NOT CONFIRMED; release_s reaches 0.193 only by benching closers

**Run:** 5 points × 12 dates, 17,400/17,400 calls with levers, 0 errors.

| release_s | foul-outs (0.193 ± 0.04) | Q4 ≤ 4:00 | closers-on [0.375, 0.535] | FTA | H2 | Q4 slope | S8 | Q4 FTA share | total bias |
|---|---|---|---|---|---|---|---|---|---|
| 0 | **0.182 ✓** | 0.138 | **0.126 ✗** | 23.16 | −0.163 | −0.088 | 14.98 | 0.265 | +1.22 |
| 60 | 0.267 ✗ | 0.222 | 0.188 ✗ | 23.19 | −0.165 | −0.089 | 14.95 | 0.265 | +1.26 |
| 120 | 0.331 ✗ | 0.290 | 0.251 ✗ | 23.14 | −0.173 | −0.083 | 15.00 | 0.264 | +1.12 |
| 180 | 0.378 ✗ | 0.334 | 0.310 ✗ | 23.17 | −0.171 | −0.091 | 14.98 | 0.263 | +1.37 |
| 240 | 0.413 ✗ | 0.370 | 0.359 ✗ | 23.23 | −0.182 | −0.099 | 14.85 | 0.263 | +1.16 |

- Q4 starters on the floor: close 3.16–3.20 (real 3.15 ✓); blowout 2.32–2.34 (real 1.56, the known blowout gap).
- P(top fouler ≥ 5) is 0.54 at every point (real 0.414). Team PF 19.2.
- **Verdict:** the only point inside the foul-out band (release 0) gets there by keeping 5-PF starters on the floor
  12.6% of the rest of Q4, against real 45.5%. That is the failure P3's amended guard exists to catch. No point
  passes, so release_s is rejected as the lever.
- Even the current 240 s sits just under the band (0.359).

**New discrepancy (reading, not a guard): the sim produces too MANY 5th-PF-in-Q4 events.**
- Starters reaching their 5th PF in Q4 with ≥ 4:00 left: sim ~0.64/game (11,181 events / 17,400 draws), against real
  0.29/game (240 / 816).
- Together with P(top fouler ≥ 5) of 0.54 vs 0.41, fouls are concentrated on starters BEFORE the foul-out stage.
- Foul avoidance (#3e) acts from each period's threshold on, so it should also cut this. #3e reads the event rate.
- The JR runs used patch v2, so P(6th | 5th) is not available for #3d (the readout printed 0.000; that means n/a).

### Phase 2 #3f — PRE-REGISTRATION (diagnostic reading, before any run): is the fouler draw over-weighting starters? (P3's suspect)

**Suspect (P3):** the fouler draw `_usage_w(players, "_prior_pf_pm", line)` blends the per-minute PF prior with a
minutes weight, so it tilts fouls toward high-minute players BEYOND their per-minute rate. That would explain sim 0.64
vs real 0.29 5th-PF-in-Q4 starter events/game, and P(top ≥ 5) 0.54 vs 0.41.

**Real** (ESPN box, 1,632 FIT team-games):
- the top 5 by minutes commit **0.585** of team PF (starters 0.583);
- starters foul LESS per minute than the bench: PF/48 3.70 vs 4.32.

**Sim:** one run, `PS_base`.
- The #3e control config (release 240, bench 0.05, foul_mult 1.0, bonus 0.04, end-game on), the same 12 dates.
- New harness field `pft5`: [PF of the top 5 by expected minutes, team PF] per side.

**Reading:** the sim top-5 PF share vs 0.585.
- If the sim exceeds it by > 0.03, the minutes blend is implicated → P3's separate default-off field (a pure per-minute
  fouler weight over the on-court five).
- Otherwise the starter excess lies elsewhere.

Diagnostic only, no parameter choice.

### Phase 2 #3e — RESULT 2026-10-14 04:57Z (done 04:56Z, co-signed): NOT CONFIRMED by the letter; foul_mult 0.3 misses one guard by 0.0008

**Run:** 5 points × 12 dates, 17,400/17,400 calls with levers, 0 errors. Release 240, bench 0.05.

| foul_mult | foul-outs (0.193 ± 0.04) | Q4 ≤ 4:00 | closers-on [0.375, 0.535] | P(6th\|5th) [0.1607, 0.2643] | FTA | H2 | Q4 slope | S8 | Q4 FTA sh | total bias |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 0.404 ✗ | 0.364 | 0.361 ✗ | 0.348 ✗ | 23.13 | −0.182 | −0.088 | 14.81 | 0.262 | +1.14 |
| 0.7 | 0.337 ✗ | 0.304 | 0.376 ✓ | 0.282 ✗ | 23.18 | −0.171 | −0.087 | 14.93 | 0.264 | +1.25 |
| 0.5 | 0.273 ✗ | 0.248 | 0.390 ✓ | 0.232 ✓ | 23.20 | −0.176 | −0.091 | 14.78 | 0.264 | +1.37 |
| **0.3** | **0.188 ✓** | 0.174 | **0.405 ✓** | **0.1599 ✗ (by 0.0008)** | 23.21 ✓ | −0.168 ✓ | −0.085 ✓ | 15.07 ✓ | 0.264 ✓ | +1.37 |
| 0.15 | 0.112 ✗ | 0.104 | 0.421 ✓ | 0.097 ✗ | 23.15 | −0.175 | −0.084 | 14.90 | 0.264 | +1.18 |

**Reading:**
- The mechanism works as designed. P(6th | 5th) and foul-outs fall together, closers STAY ON (0.361 → 0.405, into
  the real band), and team PF is unchanged (19.2).
- At 0.3 every guard passes except P(6th | 5th): 1,804/11,282 = 0.1599 (SE 0.0035), against a band lower edge of
  0.1607. Statistically indistinguishable from the band, but by the pre-registered letter it FAILS. No point passes;
  nothing is overridden here.
- The interpolated point between 0.3 and 0.5 (~0.35) would plausibly pass both.

**But see #3f:**
- The fouler allocation upstream is biased. The 5th-PF-in-Q4 starter events did NOT fall with foul_mult (~0.64/game
  at every point vs real 0.29).
- A foul_mult fitted on top of that bias would be absorbing it (mechanism vs estimator).

### Phase 2 #3f — RESULT 2026-10-14 04:57Z (`PS_base`, done 04:57Z): the minutes blend in the fouler draw IS implicated

- Sim top-5-by-expected-minutes PF share **0.659** (34,800 team-draws, pooled 0.658), against real **0.585**: +0.074,
  past the pre-registered +0.03 threshold.
- PS_base reproduces FA_f100: foul-outs 0.406 vs 0.404, P(6th | 5th) 0.343 vs 0.348.
- Real starters foul LESS per minute than the bench (PF/48 3.70 vs 4.32). The minutes-blended `_prior_pf_pm` weight
  pushes the other way.

**Next, by #3f's rule:**
1. P3 builds the pure per-minute fouler weight (a separate default-off field).
2. A pre-registered sweep reads the top-5 share (target 0.585), the 5th-PF-in-Q4 event rate (0.29/game) and
   P(top ≥ 5) (0.414).
3. Then foul_mult is RE-SWEPT on top of it (re-fitting the rate that was absorbing the bias). That includes the
   ~0.35 point.

#3e's 0.3 is NOT carried forward as a pick.

### Phase 2 #3g — PRE-REGISTRATION 2026-10-14 05:00Z (before any run): per-minute fouler weight `fouler_per_minute` (P3)

**Mechanism (P3, commit to follow after its corpus parity gate):** `EventSimConfig.fouler_per_minute: bool = False`.
- On: every fouler draw weights the on-court players by raw `_prior_pf_pm` alone (no minutes blend). A missing or zero
  prior takes the on-court median.
- foul_mult still multiplies on top. Team PF volume is unchanged.
- P3's synthetic fixture: top-5 share 0.454 → 0.411.

**Run:** ON only (`PG_on`). OFF = `PS_base`: the identical config, already read (top-5 share 0.659, foul-outs 0.406,
5th-PF-in-Q4 starter events ~0.64/game, P(top ≥ 5) 0.540).
- Config: release 240, bench 0.05, foul_mult 1.0, bonus 0.04, end-game on, the same 12 dates, 200 sims.

**CONFIRMED if ALL of these hold:**
- top-5 PF share within **0.585 ± 0.03**;
- 5th-PF-in-Q4 starter events/game move at least half the way from 0.64 toward real **0.29** (≤ 0.465);
- P(top ≥ 5) moves toward 0.414;
- team PF within ±0.3 of PS_base (19.22). Allocation only.
- Guards: FTA 22.69 ± 0.7, H2 inside [−0.19, −0.155], Q4 slope ≥ −0.101, S8 14.81 ± 0.6.

**Foul-outs:** read, not gated. foul_mult is re-swept on top afterwards.

**If the share stays above 0.615 with it ON:** the next suspect is `_prior_pf_pm` itself for starters (a per-minute
prior built on a minutes denominator other than the sim's `_sim_min`). That is checked before anything else is touched
(P3's caveat).

**Then, if CONFIRMED:** a pre-registered foul_mult re-sweep on top, including ~0.35, with the #3e guard set. A
provisional pick needs the full FIT and the totals re-fit.

**#3g CO-SIGN (P3, as pre-registered at 95794e11, before the run).** Mechanism landed in f9a2617b, corpus parity
5,400/5,400.

### Phase 2 #3g — RESULT 2026-10-14 05:40Z (done 05:40Z): CONFIRMED, fouler_per_minute fixes the starter over-allocation

**Run:** `PG_on`, 17,400/17,400 calls with levers, 0 errors. Research copy `code_pg` = code_ps + f9a2617b's engine
hunks (applied cleanly; the engine equals origin/main apart from the research-only diag).

| reading | OFF (`PS_base`) | ON (`PG_on`) | real | condition |
|---|---|---|---|---|
| top-5 PF share | 0.658 | **0.597** | 0.585 | ± 0.03 ✓ |
| 5th-PF-in-Q4 starter events/game | 0.636 | **0.439** | 0.29 | ≤ 0.465 ✓ |
| P(top fouler ≥ 5) | 0.540 | 0.460 | 0.414 | toward ✓ |
| team PF | 19.22 | 19.23 | 19.67 | ± 0.3 of OFF ✓ |
| FTA / H2 / Q4 slope / S8 | 23.19 / −0.172 / −0.090 / 14.95 | 23.15 / −0.186 / −0.094 / 14.90 | — | all ✓ |

**Readings:**
- foul-outs 0.406 → **0.298** (Q4 ≤ 4:00 0.366 → 0.270);
- closers-on 0.363 → 0.372;
- P(6th | 5th) 0.343 → 0.325 (real 0.212). Still the in-trouble foul rate, which is foul_mult's job;
- total bias +0.93 → +1.40 (reading; the totals re-fit is required).

**Remaining gaps:** the 5th-PF event rate is still 1.5× real, and P(6th | 5th) is high. foul_mult acts on the second.

### Phase 2 #3h — PRE-REGISTRATION 2026-10-14 05:41Z (before any run): foul_mult re-sweep ON TOP of fouler_per_minute

**Why:** #3e's foul_mult was fitted on a biased fouler allocation. #3g removed most of that bias, so the rate is re-fit
(mechanism vs estimator).

**Config:** the #3g ON config (fouler_per_minute = 1, release 240, bench 0.05, bonus 0.04, end-game on), the same 12
dates, 200 sims.

**Grid:** foul_trouble_foul_mult ∈ {0.7, 0.5, 0.4, 0.35, 0.3}. 1.0 = `PG_on`, already read.

**Objective:** foul-outs 0.193 ± 0.04.

**Pass/fail guards, the #3e set unchanged:**
- FTA 22.69 ± 0.7;
- H2 inside [−0.19, −0.155];
- Q4 slope ≥ −0.101;
- S8 14.81 ± 0.6;
- Q4 FTA share no further from 0.279 than 0.254;
- closers-on [0.375, 0.535];
- P(6th | 5th) [0.1607, 0.2643].

**Readings:** top-5 PF share (0.585), 5th-PF events (0.29), P(top ≥ 5) (0.414), team PF, total bias.

**Pick:** among passing points, the smallest |foul-outs − 0.193|; ties go to the larger mult.
- PROVISIONAL. Before any adoption read, the totals calibration is RE-FIT on the picked config.
- Then a full-FIT re-run must hold foul-outs within 0.193 ± 0.04 and the guards (P3's amendment).
- Then P3's game-matched §7 end-game check.

**If no point passes:** report the failing guard. No override.

**#3h CO-SIGN (P3, as pre-registered at 97e35b18, before any reading).**
- Ordering amendment: P3's game-matched §7 end-game check runs AFTER the totals re-fit. Last-2:00 points depend on the
  team targets, so a §7 read before the re-fit would test a config that will not ship.
- The order is therefore: pick (provisional) → totals re-fit → full FIT → §7.

### Phase 2 #3h — RESULT 2026-10-14 06:19Z (done 06:18Z, co-signed): CONFIRMED, provisional pick foul_mult = 0.5 (on fouler_per_minute)

**Run:** 5 points × 12 dates, 17,400/17,400 calls with levers, 0 errors.

| foul_mult | foul-outs [0.153, 0.233] | closers-on [0.375, 0.535] | P(6th\|5th) [0.1607, 0.2643] | FTA ± 0.7 | H2 [−0.19, −0.155] | Q4 ≥ −0.101 | S8 ± 0.6 | Q4 FTA sh | total bias | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.7 | 0.234 ✗ | 0.388 | 0.2553 | 23.11 | −0.162 | −0.084 | 15.02 | 0.264 | +0.98 | fail (by 0.001) |
| **0.5** | **0.194 ✓** | **0.400 ✓** | **0.2145 ✓** | 23.22 ✓ | −0.188 ✓ | −0.094 ✓ | 14.79 ✓ | 0.265 ✓ | +1.23 | **PASS** |
| 0.4 | 0.155 ✓ | 0.409 ✓ | 0.1715 ✓ | 23.22 ✓ | −0.178 ✓ | −0.091 ✓ | 14.94 ✓ | 0.265 ✓ | +1.29 | PASS |
| 0.35 | 0.145 ✗ | 0.413 | 0.1642 | 23.21 | −0.175 | −0.094 | 14.89 | 0.264 | +1.26 | fail |
| 0.3 | 0.125 ✗ | 0.416 | 0.1333 ✗ | 23.17 | −0.190 | −0.093 | 14.76 | 0.264 | +0.86 | fail |

**Pick by the rule: 0.5**, |foul-outs − 0.193| = 0.001 (0.4 gives 0.038).
- P(6th | 5th) 0.2145 against real 0.2125.
- Closers-on 0.400 against real 0.455, inside the band but still low.
- Unchanged by foul_mult: top-5 PF share 0.596, 5th-PF events 0.44–0.46/game (real 0.29), P(top ≥ 5) 0.45, team PF
  19.2.

**PROVISIONAL CONFIG for the rest of Phase 2 #3:**
- bonus_free_throws = 1, bonus_nonshoot_foul_per_poss = 0.04;
- end-game (window 120, max deficit 10, p by deficit (0.2, 0.0, 0.2), seconds 5, extend = 1);
- foul_out_in_sim = 1, thresholds (2, 3, 4, 5), bench_mult 0.05, release 240;
- **fouler_per_minute = 1, foul_trouble_foul_mult = 0.5**.

**Next, in order** (P3's amendment + ordering):
1. Re-fit the NBA totals calibration on this config (total bias +1.23 here).
2. Full-FIT re-run, which must hold foul-outs 0.193 ± 0.04 and the guards.
3. P3's §7 game-matched end-game check.

**Open, carried:**
- the Q4 FTA share is still 0.265 vs 0.279;
- 5th-PF events are 1.5× real.

### Phase 2 #3 — CORRECTION 2026-10-14 06:20Z: "re-fit the totals calibration" is ILL-POSED for the foul-mechanism overshoot; the cause is FT volume

**The pre-registered step 1 cannot act on this overshoot** (#3d onward, carried into #3h).
- `build_nba_totals_calibration.py` fits actual − `market_anchor.model_total_raw`. That is the RAW model total from
  ratings × pace, UPSTREAM of the engine, so the foul mechanisms do not change it.
- The +1.2 is the ENGINE exceeding its own target. A re-fit would reproduce the same terms and leave it in place.

**Decomposition** (same 87 games; totals, FTA, FTM and non-FT points per game, both teams):

| run | total | FTA | FTM | non-FT pts |
|---|---|---|---|---|
| FT_b000 (no bonus) | 230.67 | 42.08 | 33.29 | 197.38 |
| FT_b004 (bonus 0.04) | 231.31 | 45.75 | 36.20 | 195.11 |
| JF_m005 (+ end-game) | 231.75 | 46.49 | 36.80 | 194.96 |
| PG_on (+ per-minute fouler) | 232.02 | 46.46 | 36.79 | 195.23 |
| PH_f050 (+ foul_mult 0.5) | 231.85 | 46.57 | 36.82 | 195.03 |

- Real FTA is 45.38/game (22.69 × 2). The picked config sits at **46.57, +1.2 FTA ≈ +0.9 points over real**.
- The bonus rate 0.04 was fitted in #3 WITHOUT end-game fouling. End-game adds ~0.7 FTA/game on top, so the bonus rate
  must be re-fitted with end-game ON (mechanism vs estimator, again).
- The rest (~+0.3) is bonus trips replacing shot possessions at a higher points-per-possession, which the
  EXACT_TARGET solver (`_solve_eff_mult`) does not account for. That is an engine change, the bonus owner's domain
  (P4/P3), and only worth it if a residual remains after the re-fit.

**Corrected step 1:** re-fit bonus_nonshoot_foul_per_poss with end-game ON (#3i). The totals calibration re-fit is
dropped from the sequence (P3's §7-after-re-fit ordering then applies to #3i).

### Phase 2 #3i — PRE-REGISTRATION 2026-10-14 06:22Z (before any run): re-fit the bonus rate with end-game ON

**Config:** the #3h pick (fouler_per_minute = 1, foul_mult 0.5, release 240, bench 0.05, end-game on), the same 12
dates, 200 sims.

**Grid:**
- bonus_nonshoot_foul_per_poss ∈ {0.025, 0.03, 0.035} at foul_mult 0.5;
- plus (0.03, foul_mult 0.6). Fewer bonus fouls means fewer foul-outs, which may need a weaker foul_mult.
- 0.04 is `PH_f050`, already read.
- The expected landing comes from #3's slope (+0.26 FTA/team per +0.005): ~0.028 for FTA 22.69.

**Pass/fail, all of these:**
- FTA/team **22.69 ± 0.3** (tightened: the FTA level is now the objective);
- foul-outs 0.193 ± 0.04;
- **|total bias| < 1.0** (restored as a pass guard; this step exists to fix it);
- the #3e guard set: H2 inside [−0.19, −0.155], Q4 ≥ −0.101, S8 14.81 ± 0.6, Q4 FTA share no further from 0.279 than
  0.254, closers-on [0.375, 0.535], P(6th | 5th) [0.1607, 0.2643].

**Pick:** among passing points, the smallest |FTA − 22.69|, then the smallest |foul-outs − 0.193|. Ties go to the larger
bonus rate. PROVISIONAL.

**If |total bias| ≥ 1.0 at the FTA-matched rate:** the residual is the solver's (bonus possessions not in
`_solve_eff_mult`). Report it, and propose that engine change to the bonus owner. No override.

**Then:** full FIT → P3's §7.

**#3i CO-SIGN (P3, as pre-registered at c3bb5143, before any reading).**
- P3 agrees with the correction: the totals calibration sits upstream of the engine, so the +1.2 is engine FT volume.
- The bonus rate moves team PF, so the foul_mult pick can drift. The (0.03, 0.6) point and the #3e guards cover that.

### Phase 2 #3i — RESULT 2026-10-14 13:53Z (relaunched 13:04Z after the WSL restart killed the first run at 3/12 unread; done 13:52Z): CONFIRMED by the letter at bonus 0.03 / foul_mult 0.5. The total bias is NOT fixed.

**Run:** 4 points × 12 dates, 17,400/17,400 calls with levers, 0 errors.

| bonus / foul_mult | FTA/team (22.69 ± 0.3) | foul-outs [0.153, 0.233] | total bias (< 1.0) | P(6th\|5th) | closers-on | team PF | H2 / Q4 / S8 | verdict |
|---|---|---|---|---|---|---|---|---|
| 0.025 / 0.5 | 22.46 | 0.145 ✗ | +1.16 ✗ | 0.206 | 0.406 | 17.84 | −0.179 / −0.089 / 14.97 | fail |
| **0.03 / 0.5** | **22.62** | **0.155** | **+0.99** | 0.196 | 0.407 | 18.28 | −0.181 / −0.093 / 14.79 | **PASS** |
| 0.035 / 0.5 | 22.91 | 0.175 | +1.16 ✗ | 0.214 | 0.402 | 18.75 | −0.172 / −0.082 / 14.98 | fail |
| 0.03 / 0.6 | 22.65 | 0.175 | +1.10 ✗ | 0.222 | 0.397 | 18.28 | −0.179 / −0.088 / 14.92 | fail |
| (0.04 / 0.5, `PH_f050`) | 23.29 | 0.194 | +1.23 | 0.2145 | 0.400 | 19.26 | — | — |

- The Q4 FTA share is 0.262–0.265 at every point (passes its no-worse guard).
- **Pick by the rule: bonus 0.03 / foul_mult 0.5**, the only passing point.

**HONEST READING, the belief overturned:**
- The total bias barely responds to the bonus rate: +0.99..+1.16 across the grid at FTA 22.46..22.91, vs +1.23 at 23.29.
- Dropping FTA by 1.7/game removed ~0.1–0.2 points, not the ~0.9 that CORRECTION 06:20Z attributed to FT volume.
- A bonus trip that does not happen becomes a shot possession worth most of the same points. So the overshoot is
  STRUCTURAL: points from mechanism possessions the EXACT_TARGET solver does not model (end-game extension
  possessions + the bonus-vs-shot points-per-possession gap).
- +0.99 passes by the letter but is within noise of the failing +1.10 / +1.16. Expect the full FIT to sit near +1.0–1.2,
  and the |bias| < 1.0 guard to be at risk there.
- The fix for that is the solver change (count bonus / end-game possessions in `_solve_eff_mult`), in the bonus /
  end-game owners' code (P4/P3).
- Team PF falls to 18.28 at 0.03 (real 19.67). The FTA level now matches, but the PF volume moved away. The bonus rate
  cannot match both, which suggests the non-bonus PF base is ~1.4 low.

**PROVISIONAL CONFIG** (supersedes #3h's bonus 0.04):
- bonus 0.03;
- end-game as fitted;
- foul_out_in_sim, thresholds (2, 3, 4, 5), bench 0.05, release 240;
- fouler_per_minute = 1;
- foul_mult 0.5.

**Next:** full FIT (P3's amendment: foul-outs 0.193 ± 0.04 plus the guards) → P3's §7. Whether to do the solver change
first is a decision for the user and P3.

**USER DECISION 2026-10-14 (after #3i): "Fix the solver first".**
- Before the full FIT, the EXACT_TARGET solver (`_solve_eff_mult`) must account for bonus and end-game possessions.
  That work is asked of P3/P4 (engine owners): default-off, with a reachability test and the parity gate.
- Then a 12-date check of the #3i pick, with |total bias| < 1.0 and every #3i guard; then the full FIT; then P3's §7.

### Phase 2 #3j/#3k — PRE-REGISTRATION 2026-10-14 14:40Z (before any run): measure-then-freeze the two solver constants, then check

**Mechanism (P3, commit to follow after corpus parity):** two EventSimConfig fields, both default 0.0. Each is used only
with EXACT on AND its mechanism on.
- `solver_bonus_trip_share` s: bonus FT trips per team possession. The solve models
  (1 − s)·loop_ppp + s·2·ftp.
- `solver_endgame_pts_per_team` Δ: subtracted from each team target before the solve.
- Off / 0 = the old solve, byte-identical.

**#3j MEASURE** (FIT only, on 12 FIT dates DISJOINT from the 12 sweep dates: seed 8 from the other 97 FIT dates):
2025-11-06, 11-15, 11-22, 11-23, 12-01, 12-03, 12-06, 12-08, 12-30, 12-31, 2026-01-17, 02-20.
- Config: the #3i pick (bonus 0.03, foul_mult 0.5, fouler_per_minute, end-game as fitted, bench 0.05, release 240).
- Counters: research-only patch v4 (`code_pj`). They count possessions per side, bonus trips and intentional trips in
  the engine, not from the capped event list. Smoke test: counters = events (21/21, 6/6).
- **M1:** both solver terms 0 → **s = Σ bonus trips / Σ team possessions.**
- **M2 / M3:** end-game ON / OFF, with s applied and the end-game term 0, the same seeds →
  **Δ = mean team points (ON − OFF).**
- M1 can run on the current code. M2/M3 need P3's commit.
- **Flag to P3:** if Δ > 1.5/team, the extension itself over-runs.

**#3k CHECK** (the 12 sweep dates, so the constants are measured on different dates from the check):
- the #3i pick with s and Δ frozen;
- PASS = |total bias| < 0.5 ("well inside 1.0");
- every #3i guard still holds: FTA 22.69 ± 0.3, foul-outs [0.153, 0.233], P(6th | 5th) [0.1607, 0.2643],
  closers-on [0.375, 0.535], H2 [−0.19, −0.155], Q4 ≥ −0.101, S8 14.81 ± 0.6, Q4 FTA share ≥ 0.254.

**Then:**
1. The joint base_nonshooting_foul_per_poss + bonus fit against FTA 22.69 and PF 19.67 (its own pre-registration).
2. The full FIT.
3. P3's §7.

**#3j/#3k CO-SIGN (P3, as pre-registered at f66cdbc5, before any reading), with two additions:**
1. Report what Δ is made of: extension possessions and intentional trips per team-game (from the same counters).
2. Ordering: the joint base-nonshoot-PF + bonus fit comes AFTER #3k. Changing the bonus rate changes s, so s and Δ
   are RE-MEASURED on the #3j dates at the joint fit's chosen point (same measure-then-freeze, same disjoint dates)
   BEFORE the full FIT. Otherwise the full FIT runs a stale s.
- P4 has been cc'd on the bonus term (P3's design, two-shot award), to OK or veto it.

**#3j M1 (s) — MEASURED 2026-10-14 15:08Z** (`MJ_m1`, 12 measure dates, 16,400 draws, all calls with levers, 0 errors):
- **s = 0.00709** bonus trips per team possession, i.e. 0.719 trips/team-game over 101.29 possessions/team-game.
- Intentional end-game trips: 0.180/team-game. Points 116.86/team-game.
- s is FROZEN at 0.00709.
- M2/M3 (end-game ON/OFF, s applied, Δ term 0; research copy `code_pk` = code_pj + 6f092c74's engine hunks) started
  15:09Z.

**#3j M2/M3 (Δ) — MEASURED 2026-10-14 15:37Z** (end-game ON / OFF, s = 0.00709 applied, Δ term 0, 12 measure
dates, 80 paired games, 16,400 draws each, 0 errors):
- **Δ = +0.108 points/team/game (SE 0.107)**, frozen at 0.108. Well under P3's 1.5 flag.
- Breakdown: extension possessions +0.057/team-game; intentional trips 0.175/team-game (OFF 0).
- Applying s alone took points from 116.86 (M1) to 116.40/team-game (M2): **−0.46/team, −0.92/game**. So the bonus
  term carries almost all of the correction, and end-game fouling adds very little once the solver knows the bonus.
- s is stable across runs: 0.00707 / 0.00706.
- **#3k CHECK launched 15:36Z** on the 12 sweep dates (s = 0.00709, Δ = 0.108).

### Phase 2 #3k — RESULT 2026-10-14 16:00Z (done 16:00Z): CONFIRMED, the solver terms remove the total bias

**Run:** `PK_check`, the 12 sweep dates (disjoint from the measure dates), the #3i pick + s = 0.00709, Δ = 0.108;
17,400/17,400 calls with levers, 0 errors.

| reading | #3i pick without solver terms (`PI_b030_f05`) | **with s, Δ (`PK_check`)** | target |
|---|---|---|---|
| total bias | +0.99 | **+0.11** | \|·\| < 0.5 ✓ |
| FTA/team | 22.62 | 22.74 | 22.69 ± 0.3 ✓ |
| foul-outs | 0.155 | 0.159 | [0.153, 0.233] ✓ |
| P(6th \| 5th) | 0.196 | 0.201 | [0.1607, 0.2643] ✓ |
| closers-on | 0.407 | 0.405 | [0.375, 0.535] ✓ |
| H2 / Q4 slope / S8 | −0.181 / −0.093 / 14.79 | −0.167 / −0.095 / 14.97 | all ✓ |
| Q4 FTA share | 0.264 | 0.265 | ≥ 0.254 ✓ |

- Team PF: 18.36 (real 19.67).
- **Next, pre-registered below:** #3l, the joint base-nonshoot-PF + bonus fit; then s and Δ re-measured at its point
  (P3's ordering); then the full FIT; then P3's §7.

### Phase 2 #3l — PRE-REGISTRATION 2026-10-14 16:00Z (before any run): joint base non-shooting PF + bonus rate, against FTA and team PF

**Why:**
- Team PF is 18.36 against real 19.67 at FTA 22.74.
- The bonus rate alone cannot match both: lowering it to fit FTA (#3i) took PF away.
- `base_nonshooting_foul_per_poss` (default 0.05, a draw per shot iteration) adds PF only, and those fouls count toward
  the bonus.

**Config:** the #3k config (s = 0.00709 and Δ = 0.108 held for the grid; they are re-measured after the pick), the
same 12 sweep dates.

**Grid:** base_nonshooting_foul_per_poss ∈ {0.065, 0.08} × bonus ∈ {0.02, 0.025, 0.03}. Six runs; (0.05, 0.03) is
`PK_check`.

**Objective, PASS = all of these:**
- FTA/team 22.69 ± 0.3;
- team PF 19.67 ± 0.4;
- the #3i guards except total bias and foul-outs: P(6th | 5th), closers-on, H2, Q4, S8, Q4 FTA share.

**Readings, not gated here:**
- foul-outs, re-gated at the final check; more PF may need a foul_mult re-fit, its own step;
- total bias, re-gated after s/Δ are re-measured.

**Pick:** among passing points, the smallest |FTA − 22.69| + |PF − 19.67| / 2. Ties go to the smaller base.

**Then:**
1. Re-measure s and Δ at the pick on the #3j dates.
2. Run a #3k-style check (|bias| < 0.5, all #3i guards incl. foul-outs).
3. The full FIT.
4. §7.

**#3l CO-SIGN (P3, as pre-registered at e1715d13, before any reading).**
- Added reading: bonus trips per possession at each grid point, next to s = 0.00709 (base PF counts toward the bonus),
  to show how stale s is before the re-measure.
- A passing point more than ~20% off s should move the re-gated total bias by about that share of the 0.92/game the
  term carries.

### Phase 2 #3l — RESULT 2026-10-14 16:46Z (done 16:45Z, co-signed): CONFIRMED, pick base_nonshooting 0.065 + bonus 0.03

**Run:** 6 points × 12 dates, 17,400/17,400 calls with levers, 0 errors. s = 0.00709 and Δ = 0.108 held during the grid.

| base / bonus | FTA (22.69 ± 0.3) | team PF (19.67 ± 0.4) | trips/poss (s held 0.00709) | foul-outs (read) | P(6th\|5th) | closers-on | H2 / Q4 / S8 | total bias (read) | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 0.065 / 0.02 | 22.30 ✗ | 18.79 ✗ | 0.00489 | 0.176 | 0.206 | 0.404 | −0.156 / −0.077 / 15.11 | −0.33 | fail |
| 0.065 / 0.025 | 22.56 | 19.23 ✗ | 0.00630 | 0.194 | 0.212 | 0.400 | −0.176 / −0.090 / 14.86 | −0.03 | fail |
| **0.065 / 0.03** | **22.76 ✓** | **19.68 ✓** | **0.00802 (+13%)** | 0.211 | 0.214 ✓ | 0.401 ✓ | −0.169 / −0.084 / 14.96 ✓ | +0.10 | **PASS** |
| 0.08 / 0.02 | 22.39 | 20.19 ✗ | 0.00550 | 0.227 | 0.216 | 0.397 | −0.169 / −0.084 / 15.03 | −0.09 | fail |
| 0.08 / 0.025 | 22.74 | 20.73 ✗ | 0.00712 | 0.258 | 0.219 | 0.399 | −0.175 / −0.088 / 14.92 | +0.11 | fail |
| 0.08 / 0.03 | 23.03 ✗ | 21.13 ✗ | 0.00889 | 0.275 | 0.224 | 0.396 | −0.167 / −0.087 / 14.94 | +0.05 | fail |

- The Q4 FTA share is 0.263–0.264 everywhere (passes).
- **Pick: base 0.065 / bonus 0.03**, the only passing point. FTA and PF both on real, foul-outs 0.211 (inside its
  band), total bias +0.10.
- Its trips/possession is 0.00802, +13% over the frozen s (under P3's 20% flag).
- **Next, as pre-registered:**
  1. Re-measure s and Δ at the pick on the #3j measure dates (M1′, then M2′/M3′).
  2. The #3k-style check: |bias| < 0.5 and every #3i guard, foul-outs included.
  3. The full FIT.
  4. §7.

**#3l follow-up, s′ / Δ′ RE-MEASURED 2026-10-14 17:48Z** (measure dates, at the #3l pick; 16,400 draws each, 0 errors):
- **s′ = 0.00802** (0.813 trips/team-game; was 0.00709).
- **Δ′ = 0.138 points/team** (ON − OFF, 80 paired games; was 0.108).
- Both are FROZEN.
- The PK2 check (sweep dates, s′, Δ′) was due at 17:48Z. The PLANNED WINDOWS REBOOT (deploys.md 17:48Z, session d4409ac4)
  will kill it. If it dies, it is relaunched UNREAD with the same values after the fleet is back.

### Phase 2 #3l — PK2 CHECK RESULT 2026-10-14 18:35Z (relaunched unread 18:04Z after the planned reboot killed it at 1/12; done 18:33Z): CONFIRMED

**Run:** `PK2_check`, the 12 sweep dates, the #3l pick with s′ = 0.00802 and Δ′ = 0.138. 17,400/17,400 calls with
levers, 0 errors.

| reading | PK2 | target | |
|---|---|---|---|
| total bias | **+0.08** | \|·\| < 0.5 | ✓ |
| FTA/team | 22.79 | 22.69 ± 0.3 | ✓ |
| team PF | 19.72 | real 19.67 | (reading) |
| foul-outs | 0.212 | [0.153, 0.233] | ✓ |
| P(6th \| 5th) | 0.2142 (8,617 events) | [0.1607, 0.2643] | ✓ |
| closers-on | 0.400 | [0.375, 0.535] | ✓ |
| H2 / Q4 slope / S8 | −0.179 / −0.088 / 14.83 | inside / ≥ −0.101 / ± 0.6 | ✓ |
| Q4 FTA share | 0.264 | ≥ 0.254 | ✓ |

- Trips/possession in-run 0.00802 equals the frozen s′.
- P(top fouler ≥ 5) 0.482 (real 0.414).

**PHASE 2 #3 CONFIG (provisional, 12-date confirmed):**
- bonus_free_throws = 1, bonus rate 0.03;
- base_nonshooting_foul_per_poss 0.065;
- end-game (window 120, max deficit 10, p by deficit (0.2, 0.0, 0.2), seconds 5, extend = 1);
- foul_out_in_sim = 1, thresholds (2, 3, 4, 5), bench 0.05, release 240;
- fouler_per_minute = 1, foul_trouble_foul_mult 0.5;
- solver_bonus_trip_share 0.00802, solver_endgame_pts_per_team 0.138.

**Next:** the full FIT (P3's amendment: foul-outs 0.193 ± 0.04 plus the guards), then P3's §7.

**FULL FIT LAUNCHED 2026-10-14 19:27Z (user: "yes, run the full FIT").**
- The Phase 2 #3 config exactly as written under the PK2 result; FIT window 2025-11-01..2026-02-28.
- 3 workers at nice 19, 200 sims, `--track-oncourt`. Out `C:	mpball_scit_f3`, logs `~/bball_sc/fit_f3_w*.log`,
  research copy `~/bball_sc/code_pk`.
- Pass rule (P3's amendment): foul-outs 0.193 ± 0.04, with the guards (FTA, H2/Q4/S8, total bias, P(6th | 5th),
  closers-on) on the full window. Then P3's §7.

**FULL-FIT ENGINE CONFIG, machine-readable** (for P3's live re-gate, which loads it verbatim; copy at `C:	mpball_scit_f3_config.json`):

```json
{
 "_what": "basketball-scenario-calibration full FIT fit_f3 (launched 2026-10-14 19:27Z), engine config exactly as the harness applies it",
 "harness": "scripts/basketball_scenario_rates.py sim (levers -> _lever_cfg rebuilds the frozen EventSimConfig per engine call, ~:252/:338/:359; engine flags -> setattr on the native engine module, ~:535-545)",
 "engine_code": "origin/main native engine incl. 6f092c74 (+ research-only diag patches v1-v4: diag_foul_outs counters, no RNG draws, outcome-neutral; omit them)",
 "env": {
  "SYNDICATE_NBA_TEAM_INPUTS": "1"
 },
 "engine_module_flags": {
  "SHOOTER_FT_RATE": true,
  "FOULED_MISS_NOT_FGA": true,
  "EXACT_TARGET_CALIBRATION": true,
  "TOV_PER_ATTEMPT": true,
  "PLAYER_REBOUND_CREDIT": true,
  "BLOCK_MODE": "team_prior",
  "BLOCK_ALLOC_BY_RATE": true
 },
 "event_sim_config": {
  "possession_alternation": 1.0,
  "possessions_jitter": 0.0,
  "team_prior_stacks_on_target": false,
  "score_effect_k": 0.002,
  "blowout_bench_rest": true,
  "bench_weight_boost": 3.0,
  "foul_out_in_sim": true,
  "foul_trouble_thresholds": [
   2,
   3,
   4,
   5
  ],
  "foul_trouble_bench_mult": 0.05,
  "foul_trouble_release_s": 240,
  "fouler_per_minute": true,
  "foul_trouble_foul_mult": 0.5,
  "bonus_free_throws": true,
  "bonus_nonshoot_foul_per_poss": 0.03,
  "base_nonshooting_foul_per_poss": 0.065,
  "endgame_foul_window_s": 120,
  "endgame_foul_max_deficit": 10,
  "endgame_foul_p_by_deficit": [
   0.2,
   0.0,
   0.2
  ],
  "endgame_foul_seconds": 5.0,
  "endgame_extend_possessions": true,
  "endgame_foul_p": 0.0,
  "solver_bonus_trip_share": 0.00802,
  "solver_endgame_pts_per_team": 0.138,
  "record_events": true,
  "diag_foul_outs": true
 },
 "data_files_in_scratch_processed_root": {
  "nba_sim_total_inputs.json": {
   "skip_def_subtraction": true,
   "skip_outs_penalties": true
  },
  "nba_sim_availability.json": "fleet copy (enabled, k=2, readmit_with_prop_line)",
  "nba_prop_calibration.json": "fleet copy",
  "calibration_totals_<date>.json": "walk-forward, C:/tmp/bball_sc/calfiles_sw_all, 105 files 2025-11-02..2026-02-27 (FIT ONLY; switched raw, both total-input keys)"
 },
 "replay_inputs": "scripts/resim_nba_availability.py prepare_scratch as-of: player_checks < slate, rotation_stints_history truncated as-of; lineup_teammate_effects REMOVED (known gap)",
 "sims": 200,
 "window": "2025-11-01..2026-02-28 regular season"
}
```
- Unlike production, `nba_sim_total_inputs.json` here has BOTH keys true (production: skip_def only).
- The walk-forward calibration files cover FIT dates only. VALID dates need their own walk-forward files before the VALID read.
- Windows (agreed with P3): P3's Phase 2 re-gate grades FIT only until this lane's single VALID read. Its VALID part runs once, in the same pass. The postseason is graded once, at the end, by both.

### Phase 2 #3 — FULL FIT RESULT 2026-10-15 00:40Z (done 00:38Z): PASSES P3's amendment; the Phase 2 #3 config holds on the whole FIT window

**Run:** `fit_f3`, 109/109 dates, 791 paired games, 161,200 draws, 0 errors, every engine call carrying the levers.
Compared with `fit_rest3` (the Phase 2 config before #3).

| reading | fit_rest3 (before #3) | **fit_f3 (#3 config)** | real FIT | rule |
|---|---|---|---|---|
| foul-outs/game | 0.206 | **0.201** | 0.194 | ± 0.04 ✓ |
| FTA/team (games without OT) | — | **22.83** | 23.07 (779 games) | ± 0.3 ✓ |
| team PF | — | 19.69 | 19.67 | ✓ |
| total bias | −0.22 | **−0.08** | 0 | \|·\| < 0.5 ✓ |
| P(6th \| 5th in Q4) | — | **0.2117** (78,753 events) | 0.212 | [0.1607, 0.2643] ✓ |
| closers-on | — | 0.396 | 0.455 | [0.375, 0.535] ✓ |
| H2-on-H1 | −0.171 | −0.166 [−0.172, −0.161] | −0.174 | inside [−0.19, −0.155] ✓ |
| Q4 slope | −0.092 | −0.086 | −0.141 | ≥ −0.101 ✓ (the Q4 remainder stays with P3) |
| S8 margin SD | 14.96 | 15.00 | (readout label 15.21) | ✓ |
| blowouts | 0.230 | 0.228 | 0.253 | — |

**Other readings:**
- foul-outs by window: Q4 last 4:00 0.186, Q4 > 4:00 0.014, OT 0.001 (real 0.107 / 0.059 / 0.025 scaled). The late
  concentration remains, at the right total.
- bonus trips/possession 0.00798 (frozen s′ 0.00802);
- Q4 starters on the floor: close 3.18 (real 3.15), blowout 2.27 (real 1.56, known);
- P(top fouler ≥ 5) 0.475 (real 0.414).

**The Phase 2 #3 config is now CONFIRMED on the full FIT** (provisional; not enabled; the held-out VALID read is still
owed for the whole Phase 2 config).

**Next:**
1. P3's §7 game-matched end-game check, FIT only (P3 has the machine-readable config, e9e8c31f).
2. Phase 2 #5 (volume).
3. Build the walk-forward calibration files for the VALID dates.
4. The single end-of-Phase-2 VALID read.
5. A user decision on production.

**P3 §7c pre-registered (findings_2026-10-09 §7c, ff42dd48) and queued.**
- Method: game-matched at 2:00 Q4, 40 draws, the p grid, FIT only, base = `fit_f3_config.json` verbatim, on as-of inputs
  re-recorded with this lane's calibration files.
- If any bucket's FIT-optimal p moves off (0.2, 0.0, 0.2): that bucket is re-fitted, and **Δ is re-measured on the
  #3j measure dates before the VALID read** (this lane's job).

### Phase 2 #5 — READING 2026-10-15 00:47Z (existing full-FIT runs, no new sim): the volume flag is GONE; the defect is shot COMPOSITION

**Data:** full FIT, 1,510 team-games (games without OT). `fit_f3` = the Phase 2 #3 config; `fit_rest3` = before #3.
Real = ESPN box.

| per team-game | fit_f3 | real [95% CI] | diff |
|---|---|---|---|
| S1 (FGA + 0.44·FTA + TOV) | 112.70 | 113.46 [113.13, 113.79] | −0.76 |
| FGA | 88.20 | 88.84 [88.50, 89.18] | −0.65 |
| 3PA | 36.46 | 36.90 [36.56, 37.25] | −0.45 |
| **3PM** | **14.61** | **13.26** [13.06, 13.46] | **+1.35** |
| FGM | 41.11 | 41.65 [41.38, 41.91] | −0.53 |
| **3P%** | **0.4008** | **0.3594** | **+0.041** |
| **2P%** ((FGM − 3PM) / (FGA − 3PA)) | **0.512** | **0.547** | **−0.035** |
| FT% | 0.791 | 0.783 | +0.008 |
| TOV / REB | 14.46 / 43.58 | 14.44 / 43.77 | ≈ 0 |
| **AST** | **23.85** | **26.57** [26.31, 26.83] | **−2.72** |
| STL / BLK | 7.95 / 5.30 | 8.42 / 4.86 | −0.47 / +0.44 |
| points | 114.88 | 114.67 | +0.22 |

**Reading:**
- Phase 1's volume flag (+5.6 plays, +2.4 3PA) is gone under the accepted Phase 2 config: S1 −0.76, 3PA −0.45. It is
  EXONERATED for this config; the #1 jitter/ports/EXACT changes removed it.
- What remains is make COMPOSITION:
  - 3P% is +4.1 points too high and 2P% −3.5 too low. Points stay right because EXACT pins the total.
  - **3PM is +1.35/team (+10%)**, a direct THREES-PROPS bias.
- AST −2.7/team (−10%) is a second, separate props bias.

**Root cause (code, engine.py ~:895):**
- The 2PA make probability uses `_player_pct(_prior_fgm_pm / _prior_fga_pm)`, the player's OVERALL FG%, threes
  included (~0.47), not his 2P% (~0.55).
- Every consumer reads it as the two-point rate: the loop make probability (:1730/:1854), the EXACT solve's fg2
  (:1017), the TOV iteration count (:929) and the block rate (:571).
- The EXACT solver then raises one shared efficiency multiplier (~1.11) to hit the target. That lifts 3P% from
  ~0.36 to ~0.40 and 2P% only from ~0.47 to ~0.51, exactly as observed.
- The same construction is in the vendored engine, so production has it too.

### Phase 2 #5a — PRE-REGISTRATION 2026-10-15 00:47Z (before any build or run): two-point make rate from the 2PA split

**Mechanism:** EventSimConfig `fg2_from_two_point_split: bool = False` (native engine, default off, byte-identical).
- On: a player's two-point make rate = (`_prior_fgm_pm` − `_prior_threes_pm`) / (`_prior_fga_pm` −
  `_prior_threes_att_pm`), clipped [0.30, 0.80]; 0.53 when 2PA ≤ 0 or unknown.
- It replaces `h_fg_pct` / `a_fg_pct` at its single construction site, so every consumer listed above uses the
  2P rate consistently.

**Tests:**
- off = byte-identical (unset == explicit False);
- reachability (off ≠ on);
- corpus parity 5,400 with it off.

**Prediction:** 3P% → ~0.36, 2P% → ~0.55, 3PM −1.3/team, points unchanged (EXACT). FGA may fall slightly (more 2P
makes means fewer offensive-rebound continuations).

**Measure:** the 12 sweep dates, the fit_f3 config (s′ and Δ′ frozen) with the switch ON vs `PK2_check` (the same config
OFF).

**CONFIRMED if all of these hold:**
- 3P% within 0.3594 ± 0.008;
- 2P% within 0.547 ± 0.012;
- 3PM/team within real ± 0.4;
- |total bias| < 0.5;
- every #3 guard held: FTA ± 0.3, foul-outs [0.153, 0.233], P(6th | 5th), closers-on, H2 / Q4 / S8.

**Readings:** FGA, 3PA, AST, REB, STL, BLK, trips/possession vs s′ (re-measure s′/Δ′ if it moves > 20%).

**Then:** the full FIT. AST (−10%) is a separate later candidate (#5b), pre-registered on its own.

**Lane claim added:** engine.py, the fg2_from_two_point_split field + 2P make-rate construction section only, and
tests/test_basketball_engine_two_point_split.py (NEW). P3 is told; it is a shared file.

**P3 §7c RESULT (findings_2026-10-09 §7c, on main): end-game p RE-FIT to (0.2, 0.2, 0.3)** (was (0.2, 0.0, 0.2)), FIT only.
- Last-2:00 points error at the new p: +0.17 / +0.40 / +0.09 by bucket (n 157 / 108 / 123).
- P3's caveat: sim trailer FTA after 2:00 stays 0.5–1.5 below real, while points match.

**Consequence for this lane (the final-config sequence):**
1. Read #5a (running).
2. The final config = the #3 config + the new p + #5a (if confirmed).
3. Re-measure s′ and Δ at that config on the #3j disjoint dates.
4. A 12-date check on the sweep dates.
5. The full FIT on the final config.
6. Write `fit_f5_config.json` for P3's §7c / live re-gate re-run.
7. The single VALID read.

### Phase 2 #5a — RESULT 2026-10-15 01:52Z: NOT CONFIRMED by the letter (3P% misses its band by +0.008); every other target met

**Run:** `P5_on`, the 12 sweep dates, the PK2 config + `fg2_from_two_point_split`. 17,400/17,400 calls with levers,
0 errors.
- Code: 361a5286 (main), corpus parity 5,400/5,400 PASS with it off.
- Paired against `PK2_check` (the same config, switch off), 166 team-games without OT. The subsample's real is shown
  beside the FIT real.

| reading | PK2 (off) | **P5 (on)** | real (subsample / FIT) | rule | |
|---|---|---|---|---|---|
| 3P% | 0.3978 | **0.3748** | 0.3611 / 0.3594 | 0.3594 ± 0.008 | **✗ (+0.015)** |
| 2P% | 0.5152 | **0.5545** | 0.5446 / 0.547 | ± 0.012 | ✓ |
| 3PM/team | 14.42 | **13.45** | 13.28 / 13.26 | ± 0.4 | ✓ |
| total bias | +0.08 | +0.32 | 0 | < 0.5 | ✓ |
| FTA / foul-outs / P(6th \| 5th) / closers-on | 22.79 / 0.212 / 0.214 / 0.400 | 22.67 / 0.205 / 0.208 / 0.400 | — | #3 guards | ✓ |
| H2 / Q4 / S8 | −0.179 / −0.088 / 14.83 | −0.178 / −0.095 / 14.59 | — | | ✓ |
| FGA / 3PA | 88.24 / 36.24 | 88.01 / 35.89 | 89.08 / 36.77 | reading | |
| AST / REB / STL / BLK | 23.91 / 43.52 / 7.92 / 5.11 | 24.55 / 42.25 / 7.97 / 5.13 | 27.20 / 43.81 / 8.32 / 4.94 | reading | |

**Reading:**
- The switch does what it was built for. 3P% error falls 0.037 → 0.014, 2P% is fixed (−0.029 → +0.010), and **3PM
  (the props quantity) is fixed: +1.14 → +0.17/team.**
- 3P% still runs +1.4 points over its subsample real. 3PM matches only because 3PA fell 0.35 (more 2P makes, fewer
  offensive-rebound continuations).
- Relative to real, 2P% runs 1.018× and 3P% 1.038×. Since the EXACT multiplier is shared, the residual sits in the
  per-player 3P% PRIOR itself.
- Suspect (untested): low-volume shooters' per-minute 3P% priors are unshrunk and clipped up to 0.50.
- REB fell 1.3 (fewer misses) to −1.56 vs real. AST is still −2.65 (#5b, its own step).
- Trips/possession 0.00792 against the frozen s′ 0.00802 (−1%, well inside 20%).

**Not overridden.** The user decides between:
- (a) carrying #5a into the final config with the 3P% guard overridden (3PM, the priced quantity, passes);
- (b) pre-registering #5c, 3P% prior shrinkage for low-volume shooters, on top of #5a first.

**USER DECISION 2026-10-15 (after #5a): "Fix the 3P% priors first".**

### Phase 2 #5c — PRE-REGISTRATION 2026-10-15 02:51Z (before any run): where the residual 3P% (+1.4 pts) comes from

**Step 1, diagnostic (no mechanism yet):** dump the per-player shooting priors exactly as they reach the engine.
- Harness `--dump-priors`, committed with this entry. Run the P5 config on the 12 sweep dates (20 draws: priors do not
  depend on draws).
- Compute, per team-game:
  - the team 3P% implied by the priors, weighted by expected 3PA (`_sim_min` × `_prior_threes_att_pm`), vs real;
  - the same for 2P%;
  - the share of 3PA from players at the clip edges (3P% ≥ 0.50 or ≤ 0.20) and from low-volume shooters
    (`_prior_threes_att_pm` × `_sim_min` < 1 per game).

**Decision rule:**
- If the prior-implied team 3P% exceeds real by ≥ 0.01, the PRIOR is the source. Step 2 is a pre-registered prior
  correction: shrink each player's 3P% toward the league rate by attempt volume (empirical-Bayes,
  k = league-fit pseudo-attempts). Built default-off, measured like #5a.
- If not, the residual is in the engine (shot selection or score effect). Diagnose that instead.

**USER DECISION 2026-10-15 (supersedes "fix the 3P% priors first"; given in session d48f3a34, CONFIRMED in this chat):**
- ACCEPT #5a (`fg2_from_two_point_split`) as is, OVERRIDING the 3P% guard miss (0.375 vs 0.359 ± 0.008).
- 3PM (+1.14 → +0.17) and 2P% are fixed. **3P% about +1.5 points high is recorded as a KNOWN RESIDUAL for a later
  round.**

### Phase 2 #5c — DIAGNOSTIC RESULT 2026-10-15 13:51Z (run done 03:02Z; step 1 only; step 2 dropped by the decision above): the priors are EXONERATED

**Data:** the `--dump-priors` run on the 12 sweep dates, 149 team-sides, the priors exactly as they reach the engine.
- Prior-implied team 3P%, 3PA-weighted: raw 0.3624, engine-clipped 0.3573. Real 0.3594 (subsample 0.3611).
- Prior-implied 2P%: 0.5426. Real 0.547 (0.5446).
- Clip-edge 3PA share 0.063; low-volume (< 1 3PA per game) share 0.024. Player 3P% p10 / p50 / p90:
  0.261 / 0.35 / 0.50.
- By the pre-registered rule (prior ≥ real + 0.01 → the prior is the source), **the priors are NOT the source**.
- The residual is in the ENGINE. Sim ÷ prior is 1.022 for 2P% but 1.049 for 3P%, so something lifts threes more than
  twos beyond the shared EXACT multiplier. Untested candidates: shot selection, the fouled-miss / and-one bookkeeping,
  the block path. That is the known-residual lead for the later round.

**FINAL CONFIG SEQUENCE starts now:**
1. #3 config + P3's end-game p (0.2, 0.2, 0.3) + #5a.
2. Re-measure s″ and Δ″ on the #3j disjoint dates.
3. PK3 check on the sweep dates (|bias| < 0.5 + every #3 guard + the #5a readings).
4. Then, after a user go-ahead, the full FIT on the final config.
5. `fit_f5_config.json` to P3.

**USER DECISION 2026-10-15 (given in d48f3a34, CONFIRMED in this chat): the final full FIT is APPROVED, conditional on PK3.**
- If PK3 passes EVERY pre-registered guard, start the full FIT immediately (nice 19) and hand P3 `fit_f5_config.json`.
- The PK3 guards: |total bias| < 0.5, FTA 22.69 ± 0.3, foul-outs [0.153, 0.233], P(6th | 5th) [0.1607, 0.2643],
  closers-on [0.375, 0.535], H2 [−0.19, −0.155], Q4 ≥ −0.101, S8 14.81 ± 0.6, Q4 FTA share ≥ 0.254.
- 3P% is excluded: a known residual by the earlier decision.
- If PK3 fails ANY guard: do not start; report to the user.
- Research run only. Production enablement is a separate user decision.

### FINAL CONFIG — s″/Δ″ RE-MEASURED + PK3 CHECK RESULT 2026-10-15 15:45Z (PK3 done 15:42Z): ALL GUARDS PASS → final full FIT STARTED (per the user's conditional approval)

**Re-measure on the #3j disjoint dates** (#3 config + `fg2_from_two_point_split` + end-game p (0.2, 0.2, 0.3); 16,400
draws each, 0 errors):
- **s″ = 0.00791** (was 0.00802).
- **Δ″ = 0.262 points/team** (was 0.138). The 4–6 bucket's p moved 0 → 0.2. Intentional trips are now 0.316 per
  team-game (was 0.17).

**PK3** (the 12 sweep dates, the final config; 17,400/17,400 calls with levers, 0 errors):

| guard | PK3 | rule | |
|---|---|---|---|
| total bias | +0.36 | \|·\| < 0.5 | ✓ |
| FTA/team | 22.92 | 22.69 ± 0.3 | ✓ |
| foul-outs | 0.218 | [0.153, 0.233] | ✓ |
| P(6th \| 5th) | 0.2241 (8,171 events) | [0.1607, 0.2643] | ✓ |
| closers-on | 0.399 | [0.375, 0.535] | ✓ |
| H2 / Q4 slope / S8 | −0.183 / −0.093 / 14.65 | inside / ≥ −0.101 / ± 0.6 | ✓ |
| Q4 FTA share | **0.272** (was 0.265) | ≥ 0.254 | ✓ (P3's new p moves it toward real 0.279) |

- Readings: team PF 19.69; P(top ≥ 5) 0.478.
- **FULL FIT `fit_f5` STARTED 15:44Z:** 3 workers at nice 19, `--track-oncourt`, out `C:	mpball_scit_f5`, research
  copy `~/bball_sc/code_5a_diag`.
- **FINAL CONFIG, machine-readable** (supersedes fit_f3; handed to P3 for §7c / the live re-gate; copy at
  `C:	mpball_scit_f5_config.json`):

```json
{
 "_what": "basketball-scenario-calibration FINAL Phase 2 config fit_f5 (full FIT launched 2026-10-15 15:44Z); supersedes fit_f3_config.json",
 "harness": "scripts/basketball_scenario_rates.py sim (levers -> _lever_cfg rebuilds the frozen EventSimConfig per engine call, ~:252/:338/:359; engine flags -> setattr on the native engine module, ~:535-545)",
 "engine_code": "origin/main native engine incl. 6f092c74 + 361a5286 (fg2_from_two_point_split) (+ research-only diag patches v1-v4: outcome-neutral counters; omit them)",
 "env": {
  "SYNDICATE_NBA_TEAM_INPUTS": "1"
 },
 "engine_module_flags": {
  "SHOOTER_FT_RATE": true,
  "FOULED_MISS_NOT_FGA": true,
  "EXACT_TARGET_CALIBRATION": true,
  "TOV_PER_ATTEMPT": true,
  "PLAYER_REBOUND_CREDIT": true,
  "BLOCK_MODE": "team_prior",
  "BLOCK_ALLOC_BY_RATE": true
 },
 "event_sim_config": {
  "possession_alternation": 1.0,
  "possessions_jitter": 0.0,
  "team_prior_stacks_on_target": false,
  "score_effect_k": 0.002,
  "blowout_bench_rest": true,
  "bench_weight_boost": 3.0,
  "foul_out_in_sim": true,
  "foul_trouble_thresholds": [
   2,
   3,
   4,
   5
  ],
  "foul_trouble_bench_mult": 0.05,
  "foul_trouble_release_s": 240,
  "fouler_per_minute": true,
  "foul_trouble_foul_mult": 0.5,
  "bonus_free_throws": true,
  "bonus_nonshoot_foul_per_poss": 0.03,
  "base_nonshooting_foul_per_poss": 0.065,
  "endgame_foul_window_s": 120,
  "endgame_foul_max_deficit": 10,
  "endgame_foul_p_by_deficit": [
   0.2,
   0.2,
   0.3
  ],
  "endgame_foul_seconds": 5.0,
  "endgame_extend_possessions": true,
  "endgame_foul_p": 0.0,
  "solver_bonus_trip_share": 0.00791,
  "solver_endgame_pts_per_team": 0.262,
  "record_events": true,
  "diag_foul_outs": true,
  "fg2_from_two_point_split": true
 },
 "data_files_in_scratch_processed_root": {
  "nba_sim_total_inputs.json": {
   "skip_def_subtraction": true,
   "skip_outs_penalties": true
  },
  "nba_sim_availability.json": "fleet copy (enabled, k=2, readmit_with_prop_line)",
  "nba_prop_calibration.json": "fleet copy",
  "calibration_totals_<date>.json": "walk-forward, C:/tmp/bball_sc/calfiles_sw_all, 105 files 2025-11-02..2026-02-27 (FIT ONLY; switched raw, both total-input keys)"
 },
 "replay_inputs": "scripts/resim_nba_availability.py prepare_scratch as-of: player_checks < slate, rotation_stints_history truncated as-of; lineup_teammate_effects REMOVED (known gap)",
 "sims": 200,
 "window": "2025-11-01..2026-02-28 regular season",
 "known_residuals": [
  "3P% ~+1.5 pts high (engine-side; priors exonerated #5c) -- user-accepted",
  "AST ~-2.7/team (#5b, not done)",
  "Q4 margin slope -0.09 vs real -0.14 (P3)"
 ]
}
```

### FINAL CONFIG — FULL FIT RESULT 2026-10-15 18:30Z (done 18:24Z): PASSES; the final Phase 2 config holds on the whole FIT window

**Run:** `fit_f5`, 109/109 dates, 791 paired games, 161,200 draws, 0 errors, every engine call carrying the levers.
Against `fit_f3` (the #3 config). Team-game rows are for games without OT (1,510).

| reading | fit_f3 | **fit_f5 (final)** | real FIT | rule |
|---|---|---|---|---|
| foul-outs/game | 0.201 | **0.209** | 0.194 | ± 0.04 ✓ |
| FTA/team | 22.81 | **22.87** | 23.13 | ± 0.3 ✓ |
| total bias | −0.08 | **+0.12** | 0 | < 0.5 ✓ |
| P(6th \| 5th) | 0.212 | 0.220 (77,583 events) | 0.212 | ✓ |
| closers-on | 0.396 | 0.395 | 0.455 | ✓ |
| H2 / Q4 slope / S8 | −0.166 / −0.086 / 15.00 | −0.175 / −0.089 / 14.70 | −0.174 / −0.141 / — | ✓ |
| **3PM/team** | 14.61 | **13.58** | 13.26 | +0.32 (was +1.35) |
| 3P% | 0.4008 | 0.3756 | 0.3594 | +0.016, KNOWN residual (user-accepted) |
| 2P% | 0.5122 | **0.5524** | 0.5465 | +0.006 |
| FGA / 3PA / TOV | 88.20 / 36.46 / 14.46 | 87.95 / 36.15 / 14.52 | 88.84 / 36.90 / 14.44 | |
| AST | 23.85 | 24.47 | 26.57 | −2.1 (#5b, open) |
| **REB** | 43.58 | **42.35** | 43.77 | **−1.4: NEW residual** (fewer misses after #5a) |
| STL / BLK | 7.95 / 5.30 | 7.98 / 5.30 | 8.42 / 4.86 | |
| team PF | 19.69 | 19.66 | 19.67 | |

- Bonus trips/possession in-run 0.00782 (frozen s″ 0.00791).

**Residuals carried into the VALID read** (none gated here):
- 3P% +1.6 points (engine-side, user-accepted);
- AST −2.1;
- REB −1.4 (new: with 2P% now right there are fewer misses, and the rebound rates were fitted on the old miss
  volume — mechanism vs estimator, a candidate for later);
- the Q4 slope (P3);
- blowout starters on the floor 2.27 vs 1.56.

**Phase 2 build is COMPLETE** (#1–#5 with #5b/#5c residuals recorded).

**Owed before the single VALID read:**
1. P3's §7c re-run + live re-gate on fit_f5 (running).
2. Walk-forward calibration files for the VALID dates (2026-03-01..04-12).
3. Pre-register the VALID read itself against the lane goal's gates (quarter/half margin + total Brier vs book,
   live-interval replay Brier, player minutes / prop MAE, each clearing its own SE vs production).

**P3 §7c on the FINAL config: HOLDS.**
- The FIT-optimal end-game p is still (0.2, 0.2, 0.3). Last-2:00 points error −0.00 / +0.31 / −0.01 (n 157 / 108 / 123).
- **Δ″ = 0.262 stands; no re-measure.**
- Trailer FTA after 2:00 is still low (sim 3.55 / 3.71 / 4.04 vs real 4.76 / 5.25 / 4.52). A read-only residual.
- P3's live re-gate (§12) on fit_f5 is in progress. P3 flags that the REB −1.4 residual may read slightly low on live
  remaining points (via offensive-rebound continuation).

**P3 §12 live re-gate on fit_f5 (findings_2026-10-09 §12 RESULT): NOT PASSED by P3's rule.** FIT only, regular season,
n ≈ 780 per checkpoint.
- Native live total is worse than `pregame_rate` at end Q1 (+0.23 [+0.02, +0.44]) and ties from Q2 on.
- The Phase 2 config fixed the LEVEL that the production gate failed on. Native total bias at end Q1/Q2: +3.98/+2.57
  → +0.19/+0.11.
- Paired vs native-in-production: total |err| −0.52 (Q1), −0.16 (Q3), both with CI < 0. Margin −0.38 / −0.18.
- Native now BEATS `pregame_rate` on ML log-loss at Q1–Q3, and on margin at 5:00 Q4.
- End-Q3 total bias is +1.14 native / +1.31 pregame_rate: checkpoint truth, not this config. Whether REB −1.4
  contributes is unmeasured.
- VALID and the postseason are untouched; both are graded once with this lane's VALID read.

### VALID PREPARATION — plan 2026-10-15 (user: "build the VALID calibration files and pre-register"); NO VALID performance number is computed or printed before the VALID read is pre-registered and co-signed

**Walk-forward calibration files for the VALID dates (2026-03-01..2026-04-12 regular; postseason dates read the newest
file on or before the day before):**
1. Extract real ESPN boxes for 2026-03-01..2026-06-30 into `C:	mpball_scealv` (harness `real` phase; FIT's
   `realx` is untouched). These are needed causally: date D's file uses only games before D, as production would.
2. A raw-inputs pass on the VALID dates (harness `sim`, n-sims 1, no calibration files) for each game's pregame job
   (ratings, pace, outs, market).
   - Its sim draws are NOT read and are deleted after the jobs are copied.
3. Build the files with the #1f recipe (`wf_switched_all.py`: switched raw = no def subtraction, no outs penalty;
   `build_nba_totals_calibration.calibration_terms`, 14-day window) over FIT + VALID jobs, one file per VALID date,
   anchored the day before. Out: `C:	mpball_sc\calfiles_sw_valid`.
4. Printed: only file counts, global-term ranges and the identity check (recomputed raw = recorded raw). No sim-vs-real
   or calibrated-vs-real error on VALID.

**Then:** pre-register the VALID read (gates per the lane goal) as its own entry, co-signed by P3 for the live part.

## THE VALID READ — PRE-REGISTRATION 2026-10-15 18:50Z (read ONCE; before any VALID sim is run or any VALID number is computed)

**Window (lane goal):**
- **regular** 2026-03-01..2026-04-12, the GATED population;
- **postseason**: 2026 play-in + playoffs, a separate stratum (a different population per the season-phase learning).

**Arms, both run by this harness on the same as-of replay inputs, 200 draws, the same seeds per game:**
- **PROD:** the production NBA config as it is today.
  - Native engine defaults: no levers, no engine flags (EXACT off).
  - Production switch files: `nba_sim_total_inputs.json` = {skip_def_subtraction: true}, the availability and prop
    calibration files.
  - NO calibration_totals files (0 on the fleet). `SYNDICATE_NBA_TEAM_INPUTS=1`.
- **FINAL:** `fit_f5_config.json` exactly: the levers, engine flags, both total-input keys, and the walk-forward
  `calfiles_sw_valid`.

**Gates, all on regular VALID. FINAL ships only if EVERY gate's paired difference FINAL − PROD has a 95% CI wholly < 0
(game-clustered bootstrap, 2,000 resamples). That is "clearing its own SE".**
- **G1, period lines vs book:** Brier of P(over) on q1–q4 + h1 totals, and of P(home covers) on q1–q4 + h1 spreads,
  pooled.
  - Book lines from `asof/period_lines` (pre-tip versions only; 14 VALID dates, ~100 games). Pushes are dropped.
  - The book's de-vigged probability Brier is reported as the reference.
- **G2, full-game margin + total:** the same Brier on the full-game spread and total from `asof/game_odds`, plus |error|
  of the sim mean margin and total vs actual.
- **G3, live-interval replay:** P3's §12 VALID part, run once in the same pass (P3 owns its method). The FINAL-vs-PROD
  paired ML log-loss and total/margin |error| at its checkpoints, each CI < 0.
- **G4, player minutes + props:** paired |error| of the served per-player means (min, pts, reb, ast, threes; harness
  summary field `players`, committed with this entry) vs ESPN actuals.
  - Players who played; the mean over the five stats is gated, and each stat is reported.

**Readings, not gated:** total bias, the #3/#5 rows (FTA, foul-outs, 3PM/3P%/2P%, AST, REB), S8 margin SD, and the
postseason stratum.
- The postseason must not be WORSE beyond its SE on G1/G2/G4. If it is, that is reported as a block on the postseason,
  not on regular-season use.

**Hygiene:**
- The VALID calibration files and the raw-inputs pass print no performance numbers.
- The VALID sim outputs are read only by the gate script, once, after P3 co-signs this entry.
- No re-tuning after the read: a failure is a verdict, not a fitting signal.

**Decision:** pass → the user decides production enablement. Fail → nothing ships, and the failing gate is the finding.

**THE VALID READ — CO-SIGN (P3, at 9c445774, before anything VALID is read) + the G3 specification, verbatim in
substance (P3 findings_2026-10-09 §13, 6741818e):**
- **G3 (live)**: regular VALID 03-01..04-12, game-clustered paired bootstrap, FINAL − PROD.
  - **PROD arm:** P3's `gate_v4_k0` native projections, the production recipe: v4 as-of inputs with #473 + the skip_def
    file, native defaults, EXACT off, k = 0, no calibration files.
  - **DISCLOSED:** P3 has already seen the PROD arm's VALID values once, in its §9 whole-season gate. The FINAL arm on
    VALID is unseen.
  - **FINAL arm:** `fit_f5_config.json` on inputs_p2, re-recorded for the VALID dates with this lane's walk-forward
    VALID calibration files. Same seeds, 100 sims.
  - **PASS needs both:**
    - (a) pooled over end Q1/Q2/Q3: total |err|, margin |err| and ML log-loss, each with 95% CI upper < 0;
    - (b) at 5:00 Q4: each of the three not worse (CI upper ≤ +0.05).
    - The pooling and the Q4 carve-out come from the FIT pairing's SHAPE, not from VALID values.
  - Reported once, not gated: P3's §12 rule on VALID (FINAL vs pregame_rate per checkpoint) and total bias.
  - The postseason is a separate stratum, on the last regular-season calibration file (the same as this lane).
- **Order:** this lane's DONE marker → P3 records the VALID inputs and fills its cache. No grade is computed by either
  lane until this lane announces THE READ; then G1/G2/G4 here and G3 at P3 run in the same pass.

**USER DECISION 2026-10-15 ~18:55Z (given in d48f3a34, CONFIRMED in this chat): production enablement, CONDITIONAL on the
VALID read.**
- If THE VALID READ passes EVERY pre-registered gate, switch the FINAL config (fit_f5) on for NBA PREGAME production in
  ONE coordinated deploy with P3's full NBA live switch-on (the user overrode P3's §12 gate for live). Target: the
  2026-10-20 opener.
- If any gate fails: enable nothing; report to the user.
- **Deploy mechanics, required:**
  - exact-SHA fast-forward; claims; `check_deploy_safety` read in full; env change via a full supervisor down/up;
  - a `deploys.md` entry with the published-output A/B on the same games and seed (the #473 lesson), every ride-along
    and env change listed, rollbacks named;
  - the post-deploy input checklist on fresh production sims.
- Known residuals, stated: REB −1.4, 3P% +1.6, AST −2.1.

**PREREQUISITE FOUND (production wiring, not yet built):**
- Production builds the engine cfg from `EventSimConfigLocal()` DEFAULTS (basketball_props_smart_sim.py ~:725), and the
  LeagueParams flags (EXACT and the six ports) are fixed per league.
- No production path applies the fit_f5 levers or flags. The totals-calibration builder is not wired into the NBA
  refresh.
- **Before any enablement:**
  - (i) a data-file switch (e.g. `nba_engine_config.json` in the NBA processed root) that applies the fit_f5
    EventSimConfig fields + the LeagueParams overrides. Absent = byte-identical (tests + corpus parity). Shared with
    P3's live re-sim so both read one config.
  - (ii) `build_nba_totals_calibration.py` scheduled daily on the fleet, with its opening seed.
  - (iii) `nba_sim_total_inputs.json` with skip_outs_penalties added.
- Built default-off while the VALID runs go, so that a pass can ship.

**VALID READ — AMENDMENT 2026-10-15 19:14Z (before any VALID run or read): "the same seeds per game" is NOT achievable as
written.**
- Measured: the harness pipeline is run-to-run NONDETERMINISTIC. The same code, the same date, PYTHONHASHSEED=0, run
  twice gave 0/11 games with identical draws (the smart sim's seed is not fixed per game).
- So PROD and FINAL draws are independent. The pairing is BY GAME, and the game-clustered bootstrap CI includes the
  200-draw simulation noise of both arms (conservative: it widens the CI and never favours FINAL).
- Every gate and threshold is unchanged.

**PRODUCTION WIRING landed (9beb1677, nothing enabled):** `nba_engine_config.json` (absent = unchanged) + a gated
daily totals-calibration job + seed +2.50.
- Tests: 5 new + 4 updated, 61 neighbouring pass.
- "Absent = identical" is proven by a DETERMINISTIC unit test: the same engine object and the same draws as a direct
  call. A harness A/B cannot show it, by the measurement above.

**VALID calibration files BUILT 2026-10-15 19:36Z** (`C:	mpball_sc\calfiles_sw_valid`, `DONE` marker written):
- Real VALID boxes extracted into `realv`: 422 games. Regular 335 (03: 239, 04: 96); play-in 6; playoffs 81.
  4 ESPN summary 404s (events 401869402, 401871334, 401871337, 401873343).
- Raw-inputs pass: 42 VALID slate dates, 334 regular-season jobs, 0 tracebacks. Its sim draws were DELETED unread.
- Identity: the recomputed switched raw equals the recorded raw on 334/334 VALID games (within 0.05).
- **42 files**, one per VALID slate date (anchored the day before), from FIT + VALID jobs with the #1f recipe. The global
  term ranges −1.34..+12.08, inside the ±15 clip; that is wider than FIT's −1.79..+7.17.
- No VALID performance number was computed.
- P3 is notified to record its VALID live inputs.

**THE VALID ARMS LAUNCHED 2026-10-15 19:37Z** (both co-signed; nothing is read until both finish and THE READ is
announced):
- **PROD** (`C:	mpball_scalid_prod`): no levers or engine flags, the total-inputs file {skip_def only}, no
  calibration files.
- **FINAL** (`valid_final`): fit_f5 levers + flags, both total-input keys, calfiles_sw_all + calfiles_sw_valid.
- Shared by both arms: 2026-03-01..2026-06-30 (regular VALID + postseason), 200 draws, 3 workers each at nice 19,
  SYNDICATE_NBA_TEAM_INPUTS=1, the same availability and prop-calibration files, code copy `code_5a_diag` (diag patches
  are outcome-neutral).
- The wiring parity job was stopped (it exercises the engine only, not the wiring) to free memory. Wiring identity rests
  on the deterministic unit test.

**P3 DISCLOSURE (before any VALID number exists): G3, as registered, FAILS on the FIT window** (P3's grader smoke test,
FIT only, FINAL − PROD).
- Pooled Q1–Q3: total |err| −0.26 [−0.44, −0.08] ✓, margin −0.23 [−0.37, −0.10] ✓, but ML log-loss −0.008
  [−0.020, +0.006] ✗ (not significant).
- At 5:00 Q4: total −0.004 [−0.08, +0.08] fails the +0.05 bar on noise. **ML +0.010 [+0.000, +0.021]: FINAL is
  significantly WORSE on late win probability.**
- G3 is NOT amended (no fitting the gate to the data). Expect G3 to fail on VALID unless VALID differs materially. The
  VALID read proceeds unchanged. Under the user's rule a G3 fail means nothing is enabled.
- **Lead for this lane (a real finding, independent of the read):** the end-game / bonus fouling in the final config
  shifts LATE win probabilities the wrong way. To diagnose after the read: late-Q4 sim P(win) vs real by margin
  bucket, mechanism on vs off. Not acted on before the read.

**THE VALID READ — scoring decisions fixed BEFORE the read** (the arms finished 23:07Z: 83 dates each, 0 errors; the
script `C:	mpball_sc\diagalid_read.py` was dry-run on FIT data only (fit_f3 vs fit_f5) and on a 1-date FIT pair
for G4; no VALID number computed):
- **G1:** per game, the mean Brier over every available q1–q4 + h1 total (P over) and spread (P home covers) line, from
  `asof/period_lines`. Sim pushes are excluded from P; actual pushes are dropped. One pooled number per game, then the
  paired FINAL − PROD bootstrap.
- **G2:** THREE components, EACH must have CI upper < 0:
  - the per-game mean Brier over the full-game spread + total from `asof/game_odds` (the consensus line);
  - |sim mean margin − actual| (OT included);
  - |sim mean total − actual|.
- **G4:** per game, the mean over common player-games of the mean |error| over (min, pts, reb, ast, threes). Players
  matched by normalized name; only players who played (MIN > 0). One gated number per game; the five stats reported.
- **Bootstrap:** 2,000 resamples of games, seed 20261015. PASS = 95% CI upper < 0.
- **Postseason:** the same metrics, with season_type 3 and 5. Reported; "worse beyond SE" = CI lower > 0.
- **G3:** P3's, as specified.

## THE VALID READ — RESULT 2026-10-15 23:12Z (read ONCE): **FAIL**. FINAL does not clear every gate; nothing is enabled

**Population:** regular VALID 2026-03-01..04-12, 334 of 335 games paired. PROD vs FINAL, game-clustered paired
bootstrap (2,000). Raw output is in `C:	mpball_scalid_read_regular.txt` / `valid_read_post.txt`.

| gate | n | PROD | FINAL | FINAL − PROD [95% CI] | verdict |
|---|---|---|---|---|---|
| **G1** period lines Brier (q1–q4, h1 totals + spreads) | 96 games, 706 markets | 0.2679 | 0.2720 | **+0.0040** [−0.0016, +0.0096] | **FAIL** |
| G2 full-game Brier (spread + total) | 321 | 0.2578 | 0.2561 | −0.0017 [−0.0079, +0.0044] | ✗ |
| G2 \|margin err\| | 334 | 11.37 | 11.05 | **−0.32** [−0.64, −0.005] | ✓ |
| G2 \|total err\| | 334 | 14.98 | 14.94 | −0.05 [−0.44, +0.36] | ✗ |
| **G2** | | | | | **FAIL** |
| **G4** player mean \|err\| (min, pts, reb, ast, threes) | 334 games, 6,592 player-games | 3.1375 | 3.1365 | −0.0010 [−0.0017, −0.0004] | **PASS** (negligible size) |
| G3 (live, P3) | — | — | — | P3 runs it now, in the same pass | — |

**Readings, regular VALID:**
- total bias PROD −2.44 vs FINAL −2.82;
- margin-error SD (draws vs actual) 23.24 → 20.06;
- G4 per stat: min 6.297 / 6.297 (minutes are inputs, identical), pts 4.867 / 4.863, reb 1.914 / 1.913,
  ast 1.419 / 1.418, threes 0.912 / 0.912.

**Postseason** (play-in + playoffs, 82 of 87 games paired; reported, not gated):
- G1: −0.0072 [−0.0170, +0.0022], n.s.
- G2: Brier −0.0150 [−0.0288, −0.0010] ✓, |margin| −0.53 [−0.96, −0.07] ✓, **|total| −2.43 [−3.79, −0.98] ✓**.
- G4: −0.0007 [−0.0014, −0.0000].
- Total bias PROD **+10.45** vs FINAL **+3.89**.
- FINAL is never worse beyond its SE, so nothing is blocked for the postseason. It is clearly better on full-game totals
  and margins, but that is not the gated population.

**VERDICT by the pre-registered rule: FAIL.**
- G1 (FINAL nominally worse on period lines) and G2 (only margin clears) fail on regular VALID; G4 passes trivially.
- **Per the user's rule, NOTHING is enabled in production.** No re-tuning on this window.

**What the read says:**
- FINAL fixed the margin SPREAD: margin |err| −0.32, error SD 23.2 → 20.1. It is much better on postseason totals.
- On regular-season VALID the period-line and full-game PRICING gains are not there. Period-line Brier is, if anything,
  slightly worse.
- Together with P3's FIT disclosure (late-Q4 ML worse), the Phase 2 mechanisms improved the simulated game's SHAPE
  more than its betting probabilities.
- Candidates for a later round, NOT on this window: the late-game win-probability regression (P3's lead), and period
  shares (the Q4 slope residual).

**G3 RESULT (P3, findings_2026-10-09 §13 RESULT): FAIL.** Regular VALID, 331 games, FINAL − PROD.
- Pooled Q1–Q3: total −0.10 [−0.32, +0.13] ✗; margin −0.20 [−0.39, −0.01] ✓; ML −0.017 [−0.032, −0.003] ✓.
- 5:00 Q4: total upper +0.07 ✗; margin −0.14 ✓; ML −0.021 ✓.
- **THE VALID READ is FAIL on G1, G2 and G3; G4 passes trivially. Nothing is enabled; no joint deploy.**
- **Correction:** P3's FIT "late-Q4 ML regression" did NOT replicate. On VALID, FINAL is BETTER late on ML (−0.021
  [−0.035, −0.008]). The lead recorded above is WITHDRAWN.
- Reported only: native vs pregame_rate on VALID is worse on total at end Q1/Q2 (+0.47 / +0.28); native's early total
  bias is −1.67 / −1.42.
- Consistent picture across both lanes: FINAL improves MARGIN and win-probability skill (G2 margin, G3 margin + ML)
  but not TOTALS or period-line pricing.

**Postseason live stratum (P3, findings_2026-10-09 §13, 0b2f34d6; informational, user "do it"):** FINAL − PROD, 83–85
games per checkpoint.
- Pooled Q1–Q3: total −0.63 [−1.16, −0.12] BETTER; margin +0.20 n.s.; ML −0.016 n.s.
- Total by checkpoint: end Q1 −1.10 [−2.03, −0.14], end Q2 −0.67 [−1.35, −0.01], end Q3 −0.12 n.s., 5:00 Q4 +0.22
  [−0.03, +0.49] n.s.
- ML: end Q2 −0.036 [−0.063, −0.011] better; the rest n.s.
- Worse beyond SE: NONE.

**Both lanes agree:** FINAL's clearest gain is the POSTSEASON TOTAL LEVEL (pregame |total| −2.43, bias +10.45 → +3.89;
live total −0.63). On regular-season VALID the shipping gates fail. A postseason-only config would need its own
pre-registration and an unseen window (2026 is now seen).

# NBA ROUND 2 (user 2026-10-16: "NBA round 2", confirmed in this chat after d48f3a34's relay "keep moving ahead")

## ROUND 2 HELD-OUT TEST — PRE-REGISTRATION 2026-10-16 (before ANY round-2 tuning)

**The 2025-26 windows are all spent.**
- FIT (11-01..02-28) is the tuning window.
- VALID (03-01..04-12) and the 2026 postseason were read once (THE VALID READ).
- October 2025 was excluded: as-of inputs too thin.

So round 2's held-out is FORWARD.

**Window:** 2026-27 NBA REGULAR season, 2026-11-01 onward. October 2026 is excluded for the same thin-input reason as
2025.

**Read once**, when BOTH hold:
- ≥ 250 regular-season finals in the window with pre-tip period lines;
- ≥ 400 with pre-tip full-game lines.
- Expected: mid-to-late December 2026.
- Before the read: refresh the replay mirror (pristine + as-of inputs) through the read date. Inputs and finals are
  pulled, and nothing is scored until the read.

**Arms:**
- PROD: the production config on the read date;
- R2: the round-2 config (fit_f5 + whatever round 2 confirms on FIT).
- The same harness and replay inputs, 200 draws, paired by game.

**Gates: the same as THE VALID READ, verbatim** (G1 period-line Brier, G2 full-game Brier + |margin| + |total|,
G4 players; P3's G3 if P3 joins).
- EVERY gate needs FINAL − PROD 95% CI upper < 0, game-clustered bootstrap.
- Scoring definitions as fixed at ad695e38.

**Tuning:** round-2 work tunes ONLY on FIT. VALID is not re-read as validation. A finding that needs a second window
waits for this read.

**Production:** only on a pass AND a user decision.

## ROUND 2 WORK PLAN (each step pre-registered on its own, FIT only)

1. **R2-a: quarter shares.**
   - Phase 1 FLAGGED them and they were NEVER fixed: real Q1 .2546 / Q3 .2538 / Q4 .2411 vs sim .2509 / .2493 / .2486;
     Q4 +1.71 pts, +2.47 in close games.
   - It is the period-line target directly (G1 failed).
   - First a diagnostic on `fit_f5` (existing runs): the current shares vs real, overall and by state entering Q4. Then
     find where the shares come from (quarters calibration / team splits).
2. **R2-b: REB −1.4/team** (rebound rates fitted on the old miss volume, before #5a).
3. **R2-c: 3P% +1.6 pts** (engine-side; the priors were exonerated): shot selection, fouled-miss bookkeeping, block
   path.
- The Q4 margin slope (−0.09 vs −0.14) stays with P3. The late-game win-probability lead is WITHDRAWN (it did not
  replicate).

### R2-a — DIAGNOSTIC 2026-10-16 (existing runs) + PRE-REGISTRATION of step 1 (before any new run)

**Diagnostic** (`fit_f5`, 791 FIT games, games without OT, points per quarter):

| | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| real | 58.39 | 57.44 | 58.23 | 55.32 |
| sim fit_f5 | 57.54 | 57.57 | 57.31 | 57.51 |
| diff | −0.84 | +0.13 | −0.92 | **+2.19** |

- Shares: real .2545 / .2504 / .2539 / .2412 vs sim .2503 / .2504 / .2493 / .2501, i.e. the sim is FLAT.
- fit_rest3 (before #3) had Q4 +1.82: end-game fouling added Q4 points.
- **Cause:** production has NO `quarters_calibration.json` (absent from the production mirror). So
  `_quarter_splits_for_team_local` falls back to the hardcoded `_quarter_splits_local` = [.245, .245, .255, .255]: Q3/Q4
  HEAVY, the opposite of real.
- The engine does honour the per-quarter targets (engine.py ~:2018–2033, q_pace/q_eff = √(quarter mu ÷ game mu ÷ 4)).
  Its other mechanisms flatten the output.
- Real FIT splits (816 games):
  - home .2567 / .2490 / .2535 / .2408;
  - away .2534 / .2519 / .2538 / .2409;
  - total .2550 / .2505 / .2537 / .2408.

**The mechanism already exists as a DATA FILE** (`quarters_calibration.json`: league_split / league_split_home /
league_split_away / team splits, read by the pregame path). No code change.

**R2-a step 1 (elasticity), pre-registered:**
- Run the fit_f5 config on the 12 sweep dates with a `quarters_calibration.json` carrying the REAL FIT league splits
  (home, away, total). Compare with PK3, which had no file.
- Reading: the output share per quarter → elasticity e_q = Δoutput ÷ Δtarget.

**Step 2:**
- If e_q ≥ 0.3 for Q1 and Q4: a corrected target T* = T + (real − O) ÷ e, confirmed on the 12 dates.
- CONFIRMED if every quarter's output share is within its real FIT CI (± ~0.0022) AND the #3 guards hold (FTA,
  foul-outs, P(6th | 5th), closers-on, H2, S8, |total bias| < 0.5).
- Then the full FIT.
- If e_q < 0.3, the engine flattens the shares. Diagnose why (garbage-time efficiency, rotation fatigue) before any
  mechanism.
- Team-level splits: a later step, only if league-level passes. FIT only; the round-2 forward test decides.

### R2-a — STEP 1 RESULT + ROOT CAUSE 2026-10-16 16:57Z: the engine has NEVER used the per-quarter targets in production (a dead input)

**Step 1** (`R2A_real`, the 12 sweep dates, fit_f5 + `quarters_calibration.json` = the real FIT splits; 17,400
calls, 0 errors):
- Output points per quarter barely move: Q4 57.66 → 57.61, against real 55.33. Elasticity Q1/Q2/Q3/Q4 =
  0.02 / 0.03 / 0.20 / 0.008.
- The guards still hold (FTA 22.95, foul-outs 0.216, bias +0.18).

**Tracing it:**
- The split file IS read (`_quarter_splits_for_team_local` returns the real split from the scratch root).
- The per-quarter targets DO reach the native engine boundary: `--dump-priors` now also writes `quarters`; with the
  file Q4 is 58.1 → 54.9.
- In isolation the engine RESPONDS. With dict quarters, Q4 −1.8 under the full config and −4.0 with EXACT only.
- **In-pipeline probe, same rng seeds, the targets swapped: IDENTICAL output** for given, T0 and T1 on 3 games.

**ROOT CAUSE (engine.py ~:1275 and ~:2009–2013):**
- `float(getattr(qr, "home_pts_mu", (qr or {}).get("home_pts_mu")))`. Python evaluates the getattr DEFAULT eagerly.
- Production passes `QuarterResultLocal` DATACLASSES, not dicts, so `(qr or {}).get` raises AttributeError.
- The surrounding `except` then sets q_env_mult = q_pace_mult = 1.0 and game_mu_total = None, silently, for every
  quarter of every game.
- So the quarter MEAN shift and the random quarter environment (env_sd_scale) have never been active in production.
  Every Phase 1 / 2 measurement ran without them. The tests passed dicts.
- This is model_engine_standard's canonical trap: CONSUMED, never influential, no log line.
- The hardcoded split being Q3/Q4-heavy never mattered for the same reason. The sim's flat shares are the engine's
  own dynamics.

**Implications:**
1. A bare fix would switch ON the split shaping AND the random quarter env at once in production. The latter adds
   variance that every Phase 2 fit (S8, jitter J1) was tuned without. So the fix MUST be a default-off switch, with the
   mean shift and the random env separable.
2. The same eager-default pattern may exist in the vendored engine. Parity-wise it is the same behaviour.

**R2-a step 1b, PRE-REGISTERED:**
- Build (native engine, default off = byte-identical) `EventSimConfig.quarter_targets_mode`:
  - "off" = today;
  - "mean" = read the quarter targets correctly and apply ONLY the mean shift (q_pace/q_eff), q_sd_mult = 1;
  - "full" = mean + the random env.
- Tests: off byte-identical, reachability with dataclass quarters, corpus parity.
- Then measure "mean" + the real-split file on the 12 dates.
- CONFIRMED if every quarter's output share is inside its real FIT CI (± ~0.0022) and the #3 guards hold.
- "full" is measured separately, against S8 / S3 / within-SD.

### R2-a step 1b — RESULT 2026-10-16 18:03Z: CONFIRMED on the 12 sweep dates; quarter shares now match real

**Code:** `quarter_targets_mode` (see the engine commit after d0d30f21, corpus parity 5,400/5,400 PASS with it off).

**Run:** `R2A_mean`, the 12 sweep dates, fit_f5 + `quarter_targets_mode=mean` + `quarters_calibration.json` = the real
FIT league splits (home / away / total). 17,400/17,400 calls with levers, 0 errors.

| | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| real FIT share (95% half-width) | .2550 (± .0021) | .2505 (± .0022) | .2537 (± .0022) | .2408 (± .0023) |
| PK3 (fix off) share | .2500 | .2504 | .2491 | .2504 |
| **R2A_mean share** | **.2550** | **.2509** | **.2530** | **.2411** |
| R2A_mean pts − real (12 dates) | +0.66 | −0.22 | −0.26 | **+0.15** (PK3 +2.32) |

- Every quarter is inside its real CI.
- Elasticity in "mean" mode is about 1: the target split equal to the real split reproduces the real shares, so no
  T* iteration is needed.
- **Guards, all pass:**
  - FTA 22.93;
  - foul-outs 0.215;
  - P(6th | 5th) 0.216;
  - closers-on 0.400;
  - H2 −0.169;
  - Q4 slope −0.081 (≥ −0.101; P3's real −0.141 is unchanged, as expected — that is the margin, not the level);
  - S8 14.75;
  - total bias +0.14;
  - Q4 FTA share 0.268.
- **Provisional round-2 config:** fit_f5 + `quarter_targets_mode=mean` + `quarters_calibration.json` (real FIT
  splits).
- The production data file is a DATA change: absent on the fleet today. It ships only through `nba_engine_config.json`
  + the split file, at a passing round-2 read and a user decision.

**Lane rule (P3, agreed):** quarter_targets_mode, like every Phase 2 field, reaches production ONLY via
`nba_engine_config.json` (P3's live label carries its sha). Never by flipping the code default.

**Next:** R2-b (REB −1.4) and R2-c (3P% +1.6) on FIT, then ONE full FIT of the round-2 config. The "full" mode (random
quarter env) is measured separately against S8 / S3 / within-SD, as pre-registered.

### R2-b / R2-c — DIAGNOSIS + PRE-REGISTRATION 2026-10-16 (before any build or run)

**R2-b (REB −1.4) is downstream.**
- Sim misses per team-game (fit_f5) are 45.76 vs real 47.19: −1.43, about all of the REB gap at ~0.93 rebounds per miss.
- That comes from FGA −0.89 plus FGM +0.54, the extra makes being the 3P% excess.
- The rebound credit rates are not wrong; the misses are. So R2-c goes first and R2-b is re-read after it.

**R2-c (3P% +1.6 pts) ROOT CAUSE (engine.py ~:1758 / :1767 / :1891 and ~:1826–1830):**
- The shooting-foul draw has ONE rate for 2PA and 3PA (`foul_per_fga` × the shooter FT mult).
- With FOULED_MISS_NOT_FGA a fouled MISSED three leaves FGA/3PA (3 FTs instead).
- **Real:** 0.411 three-shot FT trips per team-game. ESPN pbp, 816 FIT games ("Free Throw - 1 of 3": 635; vs
  "1 of 2": 9.56/team-game; "1 of 1": 2.48).
- **The sim (estimate):** ~36 3PA × ~0.095 × ~0.64 miss × 0.70 ≈ 1.5 three-shot trips per team-game, about 3.6× real.
  Each is a missed three removed from 3PA: 13.5 / 36 = 0.375 against 13.5 / 37.5 = 0.360. That is the whole residual.

**Mechanism:** EventSimConfig `foul_3pa_mult: float = 1.0` (1.0 = off, byte-identical).
- It multiplies the shooting-foul probability on a three at all three draw sites (no extra RNG draw).
- It is threaded into the EXACT solver (`_loop_points_per_possession` / `_iterations_per_possession` /
  `_solve_eff_mult` gain `foul3_mult`, exact old arithmetic at 1.0) so the target still holds.
- The block-rate denominator keeps 1.0 (a minor, disclosed inconsistency).

**Step 1 (12 sweep dates, round-2 config = fit_f5 + quarter mean + real split):**
- Grid foul_3pa_mult ∈ {0.5, 0.3, 0.2}. The harness records three-shot trips per side (`ft3`, from record_events).
- **Reading:** three-shot trips per team-game vs real 0.411; 3P% vs real 0.3594 (± 0.008); FTA; total bias.
- **Pick:** trips closest to 0.411 with 3P% in its band. FTA is expected to FALL (~2–3/team): fewer 3-shot trips.
- **Step 2, pre-registered now:** re-fit the FT volume at the pick, with the base non-shooting PF + bonus grid
  (as #3l) against FTA 22.69 and PF 19.67. Then re-measure s/Δ on the disjoint dates (P3's ordering), then the
  12-date check with all guards.
- R2-b is re-read after R2-c. Then ONE full FIT of the round-2 config.

**Lane claim added:** engine.py, the foul_3pa_mult field + the three shooting-foul draw sites + the `foul3_mult`
keyword of the three solver helpers and their EXACT call sites, section only.

### R2-c step 1 — RESULT 2026-10-16 20:50Z (grid done 20:46Z; code 1d592fab, parity 5,400/5,400): NOT CONFIRMED; the cause hypothesis is REFUTED, but the FT-trip composition is badly wrong

**Run:** the round-2 config (fit_f5 + quarter mean + real split), the 12 sweep dates, foul_3pa_mult ∈ {1.0, 0.5, 0.3,
0.2}; 166 team-games without OT.

| foul_3pa_mult | 3-shot trips/team-game (real 0.41) | 3P% (real .3611) | 2P% (real .5446) | 3PM | 3PA | FGA | FTA (real 22.52) | REB (real 43.81) | bias |
|---|---|---|---|---|---|---|---|---|---|
| 1.0 | **3.49** | .3736 | .5549 | 13.41 | 35.90 | 87.94 | 22.96 | 42.24 | +0.63 |
| 0.5 | 1.72 | .3713 | .5737 | 14.03 | 37.79 | 90.16 | 16.70 | 42.66 | +0.63 |
| 0.3 | 1.02 | .3697 | .5826 | 14.26 | 38.56 | 91.07 | 14.19 | 42.78 | +0.57 |
| 0.2 | 0.67 | .3696 | .5874 | 14.39 | 38.93 | 91.47 | 12.95 | 42.76 | +0.65 |

**Verdict by the rule: NOT CONFIRMED** (no point has 3P% in [.3514, .3674]).

**Belief overturned:** the fouled-miss removal explains only ~0.004 of the 3P% excess (.3736 → .3696 at 0.2), not the
~0.0125. The residual 3P% lies elsewhere.

**The real finding: the FT-trip COMPOSITION is grossly wrong, and FTA only matched by compensation.**
- The sim takes **3.49 three-shot trips per team-game, 8.5× real** (~10.5 FTA from fouled threes vs real ~1.2).
- 2-shot FTA ≈ 22.96 − 10.47 − ~2.7 and-ones ≈ 9.8, i.e. ~4.9 two-shot trips vs real 9.56 ("1 of 2", including bonus
  and intentional).
- So 2PA shooting fouls are about HALF of real, and the #3/#3l FT-volume fit (bonus 0.03, base non-shoot 0.065) was
  built on top of the inflated three-shot trips.
- Cutting foul_3pa_mult alone collapses FTA (−10 at 0.2). EXACT then lifts every make rate to keep points (2P% .555 →
  .587) and FGA rises (no FT trip ends the possession).

**R2-c step 2 — PRE-REGISTRATION (before any run): re-fit the shooting-foul composition jointly.**
- New default-off EventSimConfig `foul_2pa_mult` (1.0 = off), the twin of foul_3pa_mult (the same draw sites and
  solver plumbing).
- Fix foul_3pa_mult = 0.12 (3-shot trips ≈ 3.49 × m ≈ 0.42).
- Grid foul_2pa_mult ∈ {1.4, 1.7, 2.0}, with bonus 0.03 and base non-shoot 0.065 held.
- **Targets:**
  - 3-shot trips 0.41 ± 0.10;
  - FTA 22.69 ± 0.3 (FIT target);
  - team PF 19.67 ± 0.4;
  - foul-outs [0.153, 0.233] and P(6th | 5th) [0.1607, 0.2643] guarded.
- **Readings:** 3P%, 2P%, FGA, 3PA, REB, total bias, the quarter shares (R2-a must hold).
- **If FTA and PF cannot both hold:** a joint m2 × base-non-shoot grid follows (its own pre-reg).
- Then s/Δ re-measured on the disjoint dates, the 12-date check, the full FIT.
- R2-b (REB) and the residual 3P% are re-read on the re-fit composition. They are not tuned on this window until
  then.

### R2-c step 2 — RESULT 2026-10-16 21:35Z (done 21:32Z; foul_2pa_mult committed, parity 5,400/5,400): NOT CONFIRMED; it exposes a STRUCTURAL defect in the shooting-foul model

**Run:** the round-2 config + foul_3pa_mult 0.12, foul_2pa_mult ∈ {1.4, 1.7, 2.0}, the 12 sweep dates, 166 team-games.

| foul_2pa_mult | 3-shot trips (real 0.41) | FTA (target 22.69 ± 0.3) | PF (19.67 ± 0.4) | foul-outs | 3P% (.3611) | 2P% (.5446) | FGA (89.08) | 3PA (36.77) | REB (43.81) | bias |
|---|---|---|---|---|---|---|---|---|---|---|
| (1.0, 3PA 1.0 = before) | 3.49 | 22.96 | 19.66 | 0.207 | .3736 | .5549 | 87.94 | 35.90 | 42.24 | +0.63 |
| 1.4 | 0.42 | 16.17 ✗ | 18.00 ✗ | 0.150 | **.3612** | .5939 | 89.94 | 39.05 | 42.21 | +1.05 |
| 1.7 | 0.41 | 19.23 ✗ | 19.64 ✓ | 0.212 | .3534 | .5970 | 88.55 | 38.92 | 41.78 | +0.76 |
| 2.0 | 0.41 | 22.35 ✗ (−0.34) | 21.35 ✗ | 0.293 ✗ | .3483 | .6004 | 87.20 | 38.93 | 41.33 | +1.15 |

- Quarter shares hold at every point.
- **Verdict:** no point meets FTA and PF together. NOT CONFIRMED.

**What it shows, the structural defect:**
- Every shot type that gets fouled more gets an INFLATED make %. With 2PA fouls up, 2P% goes .555 → .600 against real
  .545, and 3P% falls as 3PA fouls drop.
- **Mechanism (belief, from the code):** the loop draws make/miss with the player's REAL 2P% / 3P%. That rate is
  already net of fouled misses, because real stats exclude fouled misses from FGA. FOULED_MISS_NOT_FGA then removes the
  fouled misses AGAIN, so the recorded % is p / (1 − 0.7·f·(1 − p)).
- So the sim's make % depends on its own foul rate. Any re-fit of the foul composition moves the shooting
  percentages. The pre-round "3P% +1.6" was largely this, with threes over-fouled.
- **A correct model needs:** (i) a make probability defined on ALL attempts (de-netted from the prior using the foul
  rate); (ii) a realistic foul share by shot type (2PA ≫ 3PA); (iii) the FT / PF volume re-fitted on top.
- That is a coherent engine change, larger than one lever, and the #1d FOULED_MISS_NOT_FGA port is part of it.

**Status:**
- foul_3pa_mult / foul_2pa_mult stay on main at 1.0 (off). R2-c is PAUSED pending a decision on building the coherent
  shooting-foul model.
- **Round-2 config so far:** fit_f5 + quarter_targets_mode=mean + quarters_calibration.json (R2-a, CONFIRMED on 12
  dates).

**USER DECISION 2026-10-19: "Build the shooting-foul model".**

### R2-c' — COHERENT SHOOTING-FOUL MODEL — PRE-REGISTRATION 2026-10-19 (before any build or run)

**Real targets** (ESPN pbp + box, the 816 FIT games, per team-game):
- Shooting fouls: 10.34. Trips after a shooting foul: two-shot 7.56 (fouled missed 2PA), "1 of 1" 2.34 (and-ones:
  ~2.22 on twos and ~0.12 on threes, from the 1.79 / 0.095 lookback attribution scaled to 2.34), three-shot 0.39.
- Non-shooting FT trips (penalty / take / loose ball) ~1.9 two-shot.
- Recorded 2PA 52.31 / 2PM 28.59 (2P% .5465); 3PA 36.98 / 3PM 13.27 (3P% .3589).
- **Rates on ALL attempts** (fouled misses included):
  - **twos:** attempts 59.87, make q2 .4775; P(fouled | missed 2) **b2 = .2417**; P(and-one | made 2) **a2 = .0776**;
  - **threes:** attempts 37.37, q3 .3551, **b3 = .0161**, **a3 = .0090**.

**Mechanism:** EventSimConfig `shooting_foul_model: str = "legacy"` (default = today, byte-identical), plus
`"coherent"`, with league rate fields sf_a2 / sf_b2 / sf_a3 / sf_b3 (the NBA values above).
- In coherent mode, per shot:
  - Make with q = denet(p) × eff × q_env × score, where denet(p) = p(1 − b)/(1 − p·b). p is the player's recorded
    2P% / 3P% (the two-point split from #5a), and b = b_type × r.
  - If made: an and-one with probability a_type × r.
  - If missed: fouled with probability b_type × r. The FT trip is 2 or 3 shots and is not an FGA.
  - r = team factor (the team's foul_per_fga ÷ base_shooting_foul_per_fga, clipped [0.6, 1.6]) × the shooter FT-rate
    multiplier.
  - Each shooting foul charges a defender PF (as now).
  - The legacy single draw (`foul` with 0.32 / 0.70) and foul_3pa / 2pa_mult are bypassed.
- The EXACT solver uses the coherent points-per-possession formula in this mode.
- Bonus, non-shooting and end-game fouling are untouched.
- Tests: legacy byte-identical, reachability, recorded 2P%/3P% ≈ the prior on synthetic games, solver
  consistency, corpus parity.
- Harness counters: shooting two-shot trips, three-shot trips, and-ones, bonus trips.

**Step 1 (12 sweep dates, the round-2 config + coherent):**
- **Readings vs real:** shooting two-shot trips 7.56, and-ones 2.34, three-shot trips 0.39, 2P% / 3P% (subsample real
  .5446 / .3611), FTA, PF, foul-outs, FGA, REB, bias, the quarter shares.
- **CONFIRMED if:** the three shooting-trip rates are each within ±15% of real, AND 2P% within ±.012, AND 3P% within
  ±.008.
- **Step 2:** re-fit the non-shooting volume (bonus × base non-shoot) to FTA 22.69 ± 0.3 and PF 19.67 ± 0.4. Then s/Δ
  re-measured on the disjoint dates, the 12-date check with every guard, and the full FIT.
- The round-2 forward test decides adoption.

### R2-c' step 1 — RESULT 2026-10-19 17:30Z (coherent model committed; corpus parity 5,400/5,400): NOT CONFIRMED by the letter; the trip composition is fixed, and the make-% excess now traces to SHOT VOLUME

**Run 1 (`R2CC_coh`) — DISCLOSED BUG, superseded.**
- The team factor was the legacy `foul_per_fga` ÷ base 0.095. The legacy rate is clipped at 0.20 while the league
  FTA/FGA is ~0.25, so most teams sat at the 1.6 clip.
- Trips came out 1.3–1.7× real (two-shot 12.52, and-ones 2.93, three-shot 0.60), with FTA 32.8 and foul-outs 0.58.
- It did show 2P% .554 / 3P% .365 inside their bands.
- **Fix:** the team factor = UNclipped prior FTA/FGA ÷ `sf_team_ref` 0.2541 (the real league ratio), then re-run.

**Run 2 (`R2CC_coh2`, the 12 sweep dates, the round-2 config + coherent; 166 team-games, 0 errors):**

| | sim | real | rule |
|---|---|---|---|
| shooting two-shot trips | 8.74 | 7.56 | ±15% ✗ (+15.6%) |
| and-ones | 2.47 | 2.34 | ✓ (+5.6%) |
| three-shot trips | 0.44 | 0.39 | ✓ (+13%) |
| 2P% | .5636 | .5446 | ±.012 ✗ |
| 3P% | .3719 | .3611 | ±.008 ✗ |
| FTA / PF / foul-outs | 23.72 / 21.29 / 0.300 | 22.52 / 19.67 / 0.193 | readings |
| FGA / 3PA / 3PM | 85.96 / 38.94 / 14.48 | 89.08 / 36.77 / 13.28 | readings |
| REB / AST | 41.63 / 23.75 | 43.81 / 27.20 | readings |
| total bias | +1.43 | 0 | reading |

- Quarter shares hold (.2551 / .2507 / .2529 / .2412).

**Reading:**
- The composition is now near real: and-ones and three-shot trips within 15%, two-shot trips just outside.
- The recorded % lands on the prior only when EXACT's eff = 1 (unit test). Here eff > 1, and the SAME scaling lifts
  2P% and 3P% together, because the sim's shot VOLUME is short.
- Real: 102.54 possessions per team-game, FGA per possession .871, OREB 11.47. Sim: 101.06 possessions, FGA per
  possession .851 (85.96 FGA).
- Fewer shots → EXACT raises the make rates to hit the points target.
- So the make-% excess (in every run since #5a) is downstream of shot VOLUME: possessions −1.5%, shots per possession
  −2.3%, i.e. OREB continuation, with REB short too. Not the foul model.
- The first run's in-band % were a coincidence of excess FT points lowering eff.

**Next (R2-d, pre-registered next):** a volume diagnostic.
- Sim vs real possessions per team-game, OREB per own miss, and shots per possession, on the coherent config.
- Then the volume levers (`possessions_per_game` / the pace input, `base_oreb_rate`) re-fitted on FIT.
- Then the coherent rates re-checked; the two-shot rate gets a ×0.87 trim if it still runs over.
- The coherent model stays default-off.

**USER: "proceed with step d".**

### R2-d — VOLUME: DIAGNOSIS + PRE-REGISTRATION 2026-10-19 (before any build or run)

**Diagnosis** (the fit_f5 jobs, 809 FIT games):
- Team pace reaching the orchestrator is REAL: mean 102.72 (sd 1.56; p05 / p50 / p95 99.7 / 102.9 / 105.1), against
  real possessions 102.54 per team-game.
- But `orchestrator/smart_sim.py` (~:1192–1195) then subtracts `inj_drag = 0.3 × outs` per team (3.68 outs per team on
  average → **−2.21 possessions per game**) plus b2b. That is the SAME injury-count penalty that
  `nba_sim_total_inputs.json` `skip_outs_penalties` removes from the raw TOTAL (#1f: −8.5 points). It was never
  removed from the PACE.
- So the sim plays 101.06 possessions where real games have 102.54, and EXACT lifts the make rates (2P% / 3P%) to hit
  the points target on too few shots.

**Mechanism:** extend `skip_outs_penalties` (the existing key) to the orchestrator's pace injury drag.
- When the key is set, the drag is 0.
- Production today has `{skip_def_subtraction: true}` only, so it is UNCHANGED. The research configs since #1f set
  both keys, so the drag now goes there as well, consistently.
- b2b drag is kept.
- Lane claim: orchestrator/smart_sim.py, the pace injury-drag line only.
- Tests: key absent = byte-identical; key set = no drag.

**Measurement:** the 12 sweep dates, the round-2 config + coherent + this.
- **CONFIRMED if:**
  - possessions per team-game within 102.54 ± 0.7;
  - FGA within 89.08 ± 1.0 (subsample real);
  - 2P% within ±.012 and 3P% within ±.008 of the subsample real;
  - the three shooting-trip rates within ±15%.
- **Readings:** FTA, PF, foul-outs, REB, AST, total bias, the quarter shares.
- **Then:** the non-shooting volume re-fit (FTA 22.69 / PF 19.67), s/Δ re-measured, the 12-date check, the full FIT.

### R2-d — RESULT 2026-10-19 18:40Z (`R2D_vol`, done 18:37Z, 0 errors): NOT CONFIRMED by the letter, but shooting % and REB are fixed

**Run:** the 12 sweep dates, the round-2 config + coherent + the pace injury drag gated by skip_outs_penalties; 166
team-games without OT. Against `R2CC_coh2` (the same config without the drag fix).

| | R2CC_coh2 | **R2D_vol** | real | rule |
|---|---|---|---|---|
| possessions/team-game | 100.71 | **102.82** | 102.54 (FIT; this subsample's extract 101.34) | ± 0.7 ✓ |
| FGA | 85.96 | 87.92 | 89.08 | ± 1.0 ✗ (−1.16) |
| **2P%** | .5636 | **.5498** | .5446 | ± .012 ✓ |
| **3P%** | .3719 | **.3623** | .3611 | ± .008 ✓ |
| shooting two-shot trips | 8.74 | 9.18 | 7.56 | ± 15% ✗ (+21%) |
| and-ones | 2.47 | 2.47 | 2.34 | ✓ |
| three-shot trips | 0.44 | 0.47 | 0.39 | ✗ (+20%) |
| **REB** | 41.63 | **43.57** | 43.81 | (reading) fixed |
| FTA / PF / foul-outs | 23.72 / 21.29 / 0.300 | 24.83 / 22.02 / 0.342 | 22.52 / 19.67 / 0.193 | readings |
| AST | 23.75 | 23.73 | 27.20 | open (#5b) |
| total bias | +1.43 | +1.70 | 0 | (s / Δ not yet re-measured) |

- The quarter shares hold.

**Reading:**
- The volume fix lands the possessions. With them, EXACT no longer inflates the make rates: **2P% and 3P% sit on real,
  and REB is fixed** (−2.18 → −0.24), the round-2 residuals R2-b and R2-c.
- What is left: the shooting-foul trips run ~20% high across types. The mean team factor is ~1.2, so the priors'
  FTA/FGA averages above the 0.2541 reference (the prior FTA includes non-shooting FTs).
- That pushes FTA, PF and foul-outs up.

**R2-d step 2, PRE-REGISTERED now:** re-fit the one constant `sf_team_ref` so the mean factor is 1.
- 0.2541 × (9.18/7.56 + 0.47/0.39)/2 = **0.307**. Expect trips ≈ real, FTA −2 to −3, PF and foul-outs down, FGA up.
- **CONFIRMED if:**
  - the three trip rates are each within ±15%;
  - 2P% and 3P% hold their bands;
  - FGA within ±1.0;
  - possessions within ±0.7.
- **Readings:** FTA, PF, foul-outs, REB, bias.
- **Then:** the non-shooting volume (bonus × base non-shoot) re-fit to FTA 22.69 / PF 19.67, s/Δ re-measured, the
  12-date check (every guard, |bias| < 0.5), the full FIT.

### R2-d step 2 — RESULT 2026-10-19 20:05Z (`R2D_ref`, sf_team_ref 0.307; done 20:00Z): trips fixed; NOT CONFIRMED by 0.06 on FGA; a new 3PA-share finding

| | R2D_vol (ref .2541) | **R2D_ref (.307)** | real | rule |
|---|---|---|---|---|
| shooting two-shot trips | 9.18 | **7.34** | 7.56 | ✓ (−2.9%) |
| and-ones | 2.47 | **2.16** | 2.34 | ✓ (−7.7%) |
| three-shot trips | 0.47 | **0.38** | 0.39 | ✓ |
| 2P% / 3P% | .5498 / .3623 | .5539 / .3656 | .5446 / .3611 | ✓ / ✓ |
| FGA | 87.92 | 90.14 | 89.08 | ✗ (+1.06 vs ± 1.0) |
| possessions | 102.82 | 102.82 | 102.54 | ✓ |
| FTA / PF / foul-outs | 24.83 / 22.02 / .342 | 20.28 / **19.78** / .228 | 22.52 / 19.67 / .193 | readings |
| **3PA / 3PM** | 39.91 / 14.46 | **40.13 / 14.67** | **36.77 / 13.28** | readings |
| REB / AST / bias | 43.57 / 23.73 / +1.70 | 44.21 / 24.61 / +1.33 | 43.81 / 27.20 / 0 | readings |

**New finding:** the 3PA share is inflated by the same RECORDED-vs-ATTEMPTS bookkeeping.
- The prior 3PA share (.414 real) excludes fouled misses, which are nearly all twos.
- The coherent loop draws the shot type on ALL attempts at the recorded share, then drops the fouled 2PA misses.
- Recorded 3PA/FGA becomes .445: +3.4 3PA and **+1.4 3PM per team, a threes-props bias of +10%**.
- The real attempts share is .384 (37.37 / 97.24).

### R2-d step 3 — PRE-REGISTRATION 2026-10-19 (before any run): 3PA share on all attempts, coherent mode only

**Mechanism:** in coherent mode, the team's p3 becomes p3_att = (p3/k3)/(p3/k3 + (1−p3)/k2), with k_type = 1 −
b_type·r·(1 − q_type), the recorded fraction of each type's attempts.
- It is used by the shot-type draw, the solver and the TOV iterations alike.
- Legacy is untouched.
- Unit test: the recorded share lands on the prior (± .015). 6/6 pass. Corpus parity runs before the commit.

**Run:** R2D_ref + this, the 12 sweep dates.

**CONFIRMED if:**
- 3PA within 36.77 ± 1.0 and 3PM within 13.28 ± 0.4;
- the trips within ±15%;
- 2P% / 3P% in their bands;
- FGA within ± 1.0 and possessions within ± 0.7.

**Then:** the non-shooting volume re-fit (FTA 20.3 → 22.69: bonus × base non-shoot, PF held 19.67), s/Δ re-measured,
the 12-date check (every guard, |bias| < 0.5), the full FIT.

### R2-d step 3 — RESULT 2026-10-19 21:15Z (`R2D_p3`, done 21:10Z; code 45f9272b, parity 5,400/5,400): CONFIRMED

| | R2D_ref | **R2D_p3** | real | rule |
|---|---|---|---|---|
| 3PA | 40.13 | **37.25** | 36.77 | ± 1.0 ✓ |
| 3PM | 14.67 | **13.60** | 13.28 | ± 0.4 ✓ |
| two-shot / and-ones / three-shot trips | 7.34 / 2.16 / 0.38 | 7.69 / 2.28 / 0.36 | 7.56 / 2.34 / 0.39 | ± 15% ✓ ✓ ✓ |
| 2P% / 3P% | .5539 / .3656 | .5539 / .3652 | .5446 / .3611 | ✓ / ✓ |
| FGA / possessions | 90.14 / 102.82 | **89.62** / 102.82 | 89.08 / 102.54 | ✓ / ✓ |
| FTA / PF / foul-outs | 20.28 / 19.78 / .228 | 21.12 / 20.24 / .254 | 22.52 / 19.67 / .193 | readings |
| REB / AST / bias | 44.21 / 24.61 / +1.33 | 43.51 / 24.68 / +1.45 | 43.81 / 27.20 / 0 | readings |

- Quarter shares hold (.2547 / .2503 / .2528 / .2421).
- **Round 2's shot-level residuals are closed on 12 dates:** 3PA, 3PM, 2P%, 3P%, REB, FGA, possessions and the
  shooting-foul composition.
- Left: FTA (−1.4), PF (+0.6), foul-outs (high), AST (−2.5, #5b), total bias (s/Δ are stale).

### R2-d step 4 — PRE-REGISTRATION 2026-10-19 (before any run): re-fit the non-shooting volume

**Why:** the shooting part of FTA is now real (trips at real rates), so the FTA gap (−1.4) is NON-shooting. Real is
~1.9 non-shooting two-shot trips per team-game; the sim has 0.83 bonus trips + ~0.3 intentional.
- PF is +0.6 high, so the base non-shooting PF (PF only) should FALL while the bonus rate RISES.

**Grid:** bonus_nonshoot_foul_per_poss ∈ {0.045, 0.055, 0.065} × base_nonshooting_foul_per_poss ∈ {0.045, 0.055}.
The R2D_p3 config otherwise; the 12 sweep dates.

**PASS = all of these:**
- FTA 22.69 ± 0.3 (FIT target);
- PF 19.67 ± 0.4;
- foul-outs [0.153, 0.233];
- the step-3 guards hold: 3PA ± 1.0, 3PM ± 0.4, the trips ± 15%, 2P% / 3P% bands, FGA ± 1.0, possessions ± 0.7.

**Pick:** the smallest |FTA − 22.69| + |PF − 19.67|. Ties go to the smaller bonus.

**Then:** s/Δ re-measured on the disjoint dates (the bonus rate moves s), the 12-date check (every guard,
|bias| < 0.5), the full FIT.

### R2-d step 4 — RESULT 2026-10-19 23:20Z (6 runs done 23:15Z, 0 errors): NOT CONFIRMED; no point meets FTA and PF together

| bonus / base non-shoot | FTA (22.69 ± .3) | PF (19.67 ± .4) | foul-outs | bonus trips | bias |
|---|---|---|---|---|---|
| (R2D_p3: .03 / .065) | 21.12 | 20.24 | .254 | 0.87 | +1.45 |
| .045 / .045 | 21.78 ✗ | 19.75 ✓ | .230 | 1.25 | +1.67 |
| .045 / .055 | 21.95 ✗ | 20.70 ✗ | .265 | 1.35 | +2.01 |
| .055 / .045 | 22.56 ✓ | 20.76 ✗ | .273 | 1.66 | +2.17 |
| .055 / .055 | 22.69 ✓ | 21.64 ✗ | .318 | 1.76 | +2.60 |
| .065 / .045 | 23.25 ✗ | 21.65 ✗ | .318 | 2.09 | +2.65 |
| .065 / .055 | 23.58 ✗ | 22.64 ✗ | .381 | 2.24 | +2.68 |

- Every step-3 guard holds at all 6 points: 3PA 36.7–37.1, 3PM 13.4–13.6, the trips, 2P% / 3P%, FGA, possessions.
- Bias rises with the bonus rate because s (solver_bonus_trip_share 0.00791) is stale. It is re-measured at the pick
  (as planned).
- **Reading:** a bonus trip adds both FTA and PF. Hitting FTA needs bonus ≈ .055, and PF then needs base non-shoot
  BELOW .045 (slope ≈ −0.09 PF per +.001 base).

**R2-d step 4b — PRE-REGISTRATION 2026-10-19 (before the run):**
- Grid: bonus ∈ {.055, .060} × base non-shoot ∈ {.030, .035}.
- The same PASS (FTA 22.69 ± .3, PF 19.67 ± .4, foul-outs [.153, .233], step-3 guards) and the same pick rule.
- Then s/Δ re-measured, the 12-date check, the full FIT.

### R2-d step 4b — RESULT 2026-10-20 00:35Z (4 runs done 00:33Z, 0 errors): CONFIRMED, pick bonus .060 / base non-shoot .030

| bonus / base | FTA (22.69 ± .3) | PF (19.67 ± .4) | foul-outs [.153, .233] | verdict |
|---|---|---|---|---|
| .055 / .030 | 22.23 ✗ | 19.28 | .203 | fail |
| .055 / .035 | 22.32 ✗ | 19.76 | .230 | fail |
| **.060 / .030** | **22.60 ✓** | **19.79 ✓** | **.232 ✓** | **PASS** |
| .060 / .035 | 22.67 ✓ | 20.24 ✗ | .247 ✗ | fail |

**At the pick, the step-3 guards hold:**
- 3PA 36.90 and 3PM 13.48 (real 36.77 / 13.28);
- trips 7.63 / 2.26 / 0.36;
- 2P% .5541, 3P% .3653;
- FGA 88.90, possessions 102.83.

**Readings:** REB 43.13 (43.81), AST 24.50 (27.20, #5b open), quarter shares hold, bias +2.32 (s stale: bonus trips are
now 1.68 against the 0.00791 frozen in the solver).

**ROUND-2 CONFIG (provisional):** the fit_f5 fields plus:
- `quarter_targets_mode=mean` + `quarters_calibration.json` (the real FIT splits);
- `shooting_foul_model=coherent`, `sf_team_ref=0.307`;
- `skip_outs_penalties` now also removes the pace injury drag;
- `bonus_nonshoot_foul_per_poss=0.060`, `base_nonshooting_foul_per_poss=0.030`.

**Next, chained:** s″′ and Δ″′ re-measured on the #3j disjoint dates, then the 12-date check (|bias| < 0.5 + every
step-3/4 guard), then the full FIT, then `fit_r2_config.json` for P3 and the forward test.

### R2-d step 4b — 12-DATE CHECK RESULT 2026-10-20 02:43Z (chain done 02:40Z, 0 errors): FAILS on total bias; full FIT NOT launched

**Re-measured on the #3j measure dates** (M1 / M2 / M3, 12/12 each):
- s‴ = 0.01615 (was 0.00791);
- Δ‴ = 0.103 (was 0.262).

**PKR2_check** (12 sweep dates, 87 games, 17,400 draws). The guards hold:
- FTA 22.57 (real 22.76 on these dates); team PF 19.81;
- foul-outs .233 (FIT band [.153, .233], the edge);
- P(6th | 5th) .226; 3PA 37.08 (37.10);
- quarter shares inside the real CI overall;
- S8 total SD 18.11 (17.74); pace proxy 113.4 (113.9).

**FAIL: total bias vs actual** (team codes normalised; all 87 games):

| run | bias | 95% CI |
|---|---|---|
| R2A_mean (fit_f5 + quarter mean) | +0.14 | [−3.54, +3.79] |
| R2D_ref | +0.98 | |
| R2CC_coh2 (coherent) | +1.05 | |
| R2F_b060_n030 (stale s) | +1.96 | |
| **PKR2_check** | **+1.46** | [−2.42, +5.14] |

**The gate is |bias| < 0.5.** The clean signal is paired against R2A_mean on the same games: **+1.32, SE 0.23**. The
re-measured s/Δ recovered only 0.50 of the step-4b +1.82.

**Reading (believed, not measured):** the excess entered with the coherent model (R2D/R2CC, about +0.9) and with the
higher non-shooting volume, so the EXACT solve under-counts some point source the loop now produces. Candidates:
- and-one FT points;
- base non-shooting trips in the bonus;
- the coherent make-rate de-net under the solver's eff multiplier.

**Next (to be pre-registered):** a solver-accounting diagnostic. Dump, per game, the solver's target points vs the
sim's mean points, split by source (FG / and-one FT / shooting trips / bonus trips / intentional), at PKR2_check, and
find which source carries the +1.3.

### R2-d SOLVER-ACCOUNTING DIAGNOSTIC — PRE-REGISTRATION 2026-10-20 12:41Z (user go-ahead in chat)

**Question:** which point source carries the +1.32 (SE 0.23) per game that PKR2_check scores over R2A_mean?

**Instrument** (research copy `~/bball_sc/code_r2s_diag`, never on main; diagnostic-only, under `diag_foul_outs`):
- engine counters of points by source per side: FG, and-one FT, shooting-trip FT, bonus-trip FT, intentional FT;
- per side, the EXACT solve's record: tpp, tpp_eff, poss, the solved eff and the coherent model's per-possession
  split at that eff (FG / and-one / shooting FT / bonus FT).

**Run:** the PKR2_check config exactly (s 0.01615, Δ 0.103), the 12 sweep dates, 200 draws.

**Readout,** per team-game, mean over games:
- (a) target = tpp·poss vs sim points;
- (b) realised possessions (counter) vs the solver's poss;
- (c) per source, sim points / realised poss vs model per-possession;
- (d) the bonus-trip share and the end-game residual.

**Attribution rule:** the source whose (sim − model) gap, in points per team-game, is the largest and ≥ 0.3 is named
the carrier. The decomposition must close: sum of source gaps + possession gap ≈ total gap, within 0.2 per
team-game. If it does not close, report that and name no carrier. No fix is chosen in this step; a fix gets its own
pre-registration.

### R2-d SOLVER-ACCOUNTING DIAGNOSTIC — RESULT 2026-10-20 14:15Z (SV_check, 12/12 dates, 87 games, 0 errors)

**Checks:** the counters sum exactly to the box score (116.087 = 116.087 per team-game). The decomposition is an
algebraic identity (residual 0.000), so the pre-registered closure test is met by construction. The box-score match
is the substantive check.

| per team-game | sim | model | gap (SE) |
|---|---|---|---|
| **total vs target T = tpp·poss** | 116.087 | 115.474 | **+0.612** (= +1.22 per game; matches the paired +1.32) |
| FG rate | 98.368 | 98.294 | −0.275 (0.083) |
| and-one FT rate | 1.761 | 1.842 | −0.088 (0.010) |
| shooting-trip FT rate | 12.841 | 12.615 | +0.182 (0.045) |
| bonus-trip FT rate | 2.620 | 2.621 | −0.009 (0.045); s real 0.01619 vs 0.01615 |
| **possessions (realised − solver) × model ppp** | 103.179 vs 102.814 | | **+0.410 (0.034)** |
| intentional FT pts − Δ | 0.496 | 0.103 | +0.393 (not a clean source gap, see below) |

**Carrier, by the pre-registered rule** (largest gap, ≥ 0.3): **possessions beyond the solve, +0.41.** Overtime is
most of it: OT points are 0.327 per team-game, about 0.29 of the 0.365 extra possessions. The rest is end-game
extension.

**The coherent model is NOT the carrier:** its per-source rates net to −0.19 per team-game, each within ±0.3. The
intentional-foul line is not a source gap: Δ is the NET on − off effect (M2 − M3 = 117.028 − 116.925), because
intentional trips displace ordinary possessions. So "pig − Δ" double-counts the possessions they displace, and it
and the possession line are entangled.

**Believed, not measured:** R2A_mean has the same OT (0.300) and the same intentional trips (0.318), yet it lands on
actual (+0.14). So the legacy loop must have scored about 0.6 per team-game BELOW its own solver model, which offset
OT and the end-game. The R2-c double-netting finding predicts exactly that direction. The coherent solve removed the
shortfall and exposed the unmodelled OT / end-game points. R2A carries no solver record, so this cannot be checked
from it.

**The target is not stale:** calibration_totals_* correct the PREGAME raw total against actual; they are
engine-independent. The target sits on actual on these games (T 230.95 per game; actual ≈ 230.7).

**No fix chosen** (per the pre-registration). Candidate to pre-register: replace Δ with ONE measured structural term,
`solver_endgame_pts_per_team` re-measured as mean(sim − model·solver_poss) over OT + end-game on the #3j measure
dates, at this config.
