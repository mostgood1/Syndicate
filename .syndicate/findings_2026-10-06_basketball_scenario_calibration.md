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

## Readings

(none yet)
