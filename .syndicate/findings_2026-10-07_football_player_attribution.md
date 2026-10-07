# Football sim player attribution (props from the game sim) — lane `football-sim-player-attribution`

Opened 2026-10-07, session 20aa7f5b. User decisions: "Lines first, then attribution" (2026-10-06),
"start the player attribution lane for props while that runs" (2026-10-07). **NFL first**; NCAAF after
NFL has a reading (CFBD plays carry no player ids in the local cache -- a separate data step).

## Why

NFL props today (`nfl/props.nfl_props_rows_for_week`) are a player rolling rate with a prior, times a
game-context multiplier, through a Normal/lognormal/Poisson cover probability. The sim never touches
them. Measured (`findings_2026-10-02_nfl_lines_props_backtest.md`, `..._10-03_nfl_prop_predictive_spread.md`):
7 of 8 continuous markets lose to the de-vigged book, anytime TD loses even to the vig-inclusive price,
calibration slope at the line ~0. Game script -- how many plays a team runs, its pass rate when
leading/trailing, the opponent -- reaches a prop only through one scalar multiplier.

## Design — PRE-REGISTERED 2026-10-07, before any measurement

**No change to the team engine.** Attribution is a READ-ONLY layer over each seed's
`SmartSim2SimulationOutput` (the `segment_accumulator` seam, as in the scenario lane), with its OWN rng
seeded from the game seed, so the engine's stream and every game-line number are untouched. Engine
profile = production's (all scenario switches OFF); re-measured if a re-fit candidate ships.

Per simulated offensive play (`possession_log` steps of the team with the ball):
- **Play type.** INCOMPLETE_PASS, SACK -> pass. TURNOVER -> interception w.p. P(INT | turnover), else a
  fumble on a pass/run drawn as below. GAIN / EXPLOSIVE_GAIN / TOUCHDOWN -> pass w.p.
  **P(pass | down, to-go bucket, score-diff bucket, time bucket, yards bucket)**, measured on FIT pbp.
  Field goals, punts, penalties: not attributed.
- **Passer:** the team's as-of primary QB (most dropbacks over its last 3 games before the week).
- **Pass target / receiver.** Completion: receiver drawn with weight reception_share_i x
  f_i(yards), f_i = exponential with the player's as-of yards-per-reception mean; incompletion / INT:
  drawn by (targets - receptions) share. Passing yards = the play's yards; sacks add none (NFL rule).
- **Rusher:** drawn by as-of carry share, QB scrambles included in the QB's share, with weight
  g_i(yards) = exponential on max(yards, 0) + 1 with the player's as-of yards-per-carry mean.
- **Touchdowns:** to the receiver (and a pass TD to the QB) or the rusher.
- **Availability proxy:** shares among players who appeared in the team's most recent game before the
  week, renormalised. Stated limitation: no as-of inactive list exists locally.
- **Usage tables as-of:** plays strictly before the week; current season with the prior season as a
  prior (k = 4 games, production's convention for team ratings).

**Per player per seed:** pass att, completions, pass yds, pass TD, INT, rush att, rush yds,
receptions, rec yds, anytime TD. P(over line) = share of the 300 seeds above the line (lines are .5;
an integer line is graded with pushes removed).

**Phase A (measure, FIT only):** the P(pass | ...) table, P(INT | turnover), and a usage-table builder,
from nflverse pbp 2023-24 (2022 as prior only). Buckets fixed now: down 1/2/3/4; to-go 1-3, 4-7, 8+;
score diff (offense) <= -9, -8..+8, >= +9; time = Q1-3 / Q4 > 5 min / Q4 <= 5 min; yards < 0, 0-5,
6-15, 16+. Cell smoothing = counts + 20 x the cell's (down, to-go) pooled rate.

**Phase B (FIT check, 2023-24):** attribution props vs production props on the same quote rows
(`tracking/book_quotes`, kickoff -10 min, de-vigged per book), per market: log-loss, Brier,
calibration slope at the line. A construction check also runs: simulated team pass attempts, rush
attempts, passing yards and rushing yards per game vs real, game-weighted.

**Phase C (held-out, 2025 props, READ ONCE):** the same table. Lane falsification: no market beats
production on paired log-loss with a game-clustered 95% CI excluding 0 -> hypothesis rejected,
nothing wired. Any market that does beat it is a candidate for wiring (a separate decision); markets
that do not keep the rate model -- every market is its own decision (learnings: "every line is its own
decision").

## Results

(none yet)
