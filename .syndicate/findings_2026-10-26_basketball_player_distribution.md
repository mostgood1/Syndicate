# Basketball player distribution — lane `basketball-player-distribution`

Opened 2026-10-26 at the user's request ("as we tune game stats, we should do potential team/player modeling based on
pbp and rotations"). Engine: the NBA native engine, round-2b + #5b candidate config (fit_5bA_config.json in
findings_2026-10-06_basketball_scenario_calibration.md).

## Prior facts (measured elsewhere)

- **The served NBA prop sd is too narrow:** IQR(z)/1.349 is pts 1.52, reb 1.44, ast 1.39, pra 1.85 (2026-10-03,
  state `[nba-model-skill-2025-26]`). That is AFTER the calibration layer; the raw engine was never read.
- **The engine reports a player's INPUT minutes in the box** (`finalize`: `"min": _sim_min`), constant across draws.
  Simulated playing time varies only through the lineup sampler / pool, and is not reported.

## PHASE 1 — PRE-REGISTRATION 2026-10-26 13:20Z

**Instrument** (research only, never on main):
- The research engine copy counts, per draw, each player's on-floor possessions (both lineups at every possession
  iteration) and the iteration count.
- Simulated minutes = game minutes (48 + 5·OT) × on_i / n.

**Recorder:** the harness flag `--record-player-draws` (on main; default off, so output is unchanged) writes per draw,
per player (game-fixed order), [pts, reb, ast, threes, sim_min].

**Run:** the fit_5bA config on the full 2025-26 FIT window (109 dates), 200 draws, 3 workers at nice 19.

**Truth:** ESPN summary player boxes (C:/tmp/bball_sc/cache/nba/summary_<event>.json.gz; MIN > 0 = played), joined
by normalised name.

**Population:**
- player-games where the player is in the sim AND played;
- separately counted: sim-only (DNP in reality) and real-only (not simulated).

**Per stat** (min, pts, reb, ast, threes), from the 200 draws:
- the randomised PIT u = P(X < y) + U·P(X = y);
- tail coverage, P(u < .1) and P(u > .9) (nominal .10 each);
- the central-80% miss = their sum (nominal .20);
- the width ratio = sd(y − sim mean) / rms(sim sd);
- the bias = mean(y − sim mean).
- CIs from a game-clustered bootstrap (2,000).

**Splits:**
- starters (top-5 by input minutes) / bench;
- close (final abs margin ≤ 10) / blowout (≥ 20).

**Decomposition:**
- (a) MINUTES: the sim minute coverage vs actual, and the input-minutes bias;
- (b) a MINUTES-ORACLE arm: each draw's stat × (actual min / that draw's sim min), stats only. If the central-80% miss
  falls to within ±.05 of .20, the width deficit is minutes; otherwise the residual is the per-minute rate / width.

**FLAG rule:** a stat × role cell is FLAGGED when its central-80% miss lies outside [.15, .25] with the CI excluding
.20.

**Lane falsification:** every stat's overall miss is within ±.05 of .20 → the engine is EXONERATED and the narrowness
is downstream.

Phase 2 (mechanisms from pbp / rotation stints) is pre-registered only after this read. Minutes mechanisms are
coordinated with the nba-sim-minutes lanes.
