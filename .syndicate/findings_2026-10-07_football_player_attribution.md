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

## Phase A — measured (FIT 2023-24, nflverse REG)

51,422 yard-gaining pass/run plays, 386 (down, to-go, diff, time, yards) cells. P(INT | turnover) 0.649
(817 INT, 442 lost fumbles); P(pass | lost fumble) 0.686. Pooled P(pass | gaining play) runs from 0.145
(1st and 1-3) to 0.843 (4th and 8+). Tables: `C:\tmp\football_scenarios\attribution\attribution_tables_2023-2024.json`.

## Amendment 1 — 2026-10-07, after a 4-game FIT SMOKE run, before any Phase B reading

The smoke run (plumbing; 4 FIT games, 1,405 quote rows; not a result) exposed two construction defects:
- **A1 starter QB.** The "most dropbacks over the last 3 games" proxy credited Pickett on 2023 wk14 PIT
  (Trubisky started) and Richardson on 2024 wk5 IND@JAX (Flacco started) -- the quoted QB's attempts
  were 0 in every seed. Fix: a QB with a passing quote for the game IS the passer (the quotes are pregame,
  kickoff -10 min, and production holds the same rows when it builds props); any player with a quote for
  the game joins the availability set.
- **A2 yards.** The engine's per-play yards are not a real pass/run mixture: smoke team rushing 133-173
  yds on 20-22 carries (6.3-7.9 ypc vs real ~4.3), team offense ~380 yds vs real ~330. Fix: the sim still
  supplies game SCRIPT -- play count, game state, outcome class and the pass/run choice -- but the YARDS
  credited to players are drawn from the REAL empirical distribution of that play type in that
  (down, to-go) bucket (FIT pbp quantiles; completions and runs separately), conditioned on the sim's
  sign (a loss stays a loss); a touchdown keeps the sim's yards-to-goal.

Nothing else changes. Phase B runs after both fixes, on the FIT seasons.

## NCAAF data step — PRE-REGISTERED 2026-10-07 (user: "start the NCAAF attribution data step while that runs")

**What is missing for NCAAF, measured:** local CFBD plays carry no player ids; player box scores exist
for 2025 only (`ncaaf_player_game_stats_snapshot.csv`, 35,829 player-games); historical prop quotes
exist for 2026 wk1 only (409 rows, captured 3 days pre-kickoff) -- nothing for FIT 2024 or held-out 2025.

**Part 1 -- who touched the ball, from CFBD `playText` (no API calls).** Rules, fixed now:
`<A> run for ...` -> rusher A (Rush, Rushing Touchdown, fumble rows of that shape); `<A> pass complete
to <B> for ...` -> passer A, receiver B (Pass Reception, Passing Touchdown); `<A> pass incomplete( to
<B>)?` -> passer A, target B; `<A> sacked by` -> passer A (sack); `<A> pass intercepted` -> passer A.
Yards from CFBD `yardsGained`, never parsed. Names normalised (lower, punctuation and suffixes
Jr/Sr/II/III/IV stripped). Team = the play's `offense`.
**Acceptance (before use), on 2025 vs the box scores, joined on (game, team, normalised name):** among
player-games with a touch on either side, >= 90% within +-5 yds for rushing yards AND receiving yards,
and >= 90% within +-1 for rush attempts AND receptions; passing yards >= 90% within +-10. Parse
coverage (plays of those types matched by a rule) reported. Below the bar -> the parser is fixed or
the NCAAF arm stops; it is never used below the bar.

**Part 2 -- what the book offered (grading data).** OddsAPI historical event odds for NCAAF player
props, FIT 2024 and held-out 2025, snapshot at kickoff - 10 min (the NFL convention). One probe call
first to measure the credit cost per event; the bulk pull is sized from that and reported before it
runs at scale. Stored in a PRIVATE root (`C:\tmp\football_scenarios\ncaaf_props\`), never the shared
mirror.

## Results

(none yet)
