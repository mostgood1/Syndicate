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
