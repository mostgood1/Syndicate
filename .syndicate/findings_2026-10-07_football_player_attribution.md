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

## Amendment 2 — run-share correction, PRE-REGISTERED 2026-10-07 (user: "fix the rushing volume with a measured run-share correction")

**Defect (Phase B, FIT):** sim per team-game rush att 21.3 vs real ~27, pass att 35.2 vs ~33.5; the
engine also runs ~4-5 fewer offensive plays. Runs are starved, passing volume inflated -> rushing
attempts +0.336 LL vs production, rushing yards / receptions / receiving yards worse.

**Correction (two parameters, applied identically at prediction time, NFL and NCAAF fitted separately):**
1. `pass_odds_multiplier` c: on yard-GAINING plays, P(pass) -> c*odds / (1 + c*odds). (c = 1 = today.)
2. `incomplete_as_run` r: a share r of the sim's INCOMPLETE_PASS plays (0 yards) are credited as a
   RUN for 0 yards -- a stuffed run and an incompletion are the same in yardage, and the engine has no
   other way to produce a 0-yard run. (r = 0 = today.)
**Targets (FIT real, nflverse 2023-24 REG, per team-game):** rush attempts = `play_type` run + qb_kneel;
pass attempts = `play_type` pass, not a sack. **Fit:** grid c in {1.0, 0.85, 0.7, 0.6, 0.5, 0.4},
r in {0, 0.1, 0.2, 0.3, 0.4, 0.5} on every 8th FIT game (~46 games, 100 seeds, production engine);
minimise (sim/real - 1)^2 summed over rush att and pass att. The chosen (c, r) is FIXED, then Phase B is
re-run on all 366 FIT games at 300 seeds and reported beside the uncorrected run. Held-out 2025 is not
touched by any of this. NCAAF: the same fit on 2024 CFBD parsed targets when its Phase B is read.

**Amendment 2 fit (2026-10-07):** 46 FIT games (every 8th), 100 seeds, one engine run per game fanned to
36 grid points. Uncorrected rush/pass att 21.28 / 35.41. **Chosen (grid minimum): c = 0.7, r = 0.1** ->
rush att 25.61, pass att 31.08 (targets 27.0 / 33.24), rush yds 138.7, pass yds 222.4. Both targets cannot
be met at once -- the engine runs ~4-5 fewer offensive plays per team-game -- so the fit splits the
shortfall; rushing yards now OVERSHOOT (~139 vs ~115-120 real). Fixed as chosen; Phase B re-run on all
366 FIT games at 300 seeds with (0.7, 0.1).

## Amendment 3 — player share estimator, PRE-REGISTERED 2026-10-07 (user: "improve player carry and target shares")

**Why:** with team volume corrected, rushing attempts still score a calibration slope of 0.06 -- the attributed
probabilities say almost nothing about WHICH player clears his line. Shares are the input that decides that.

**Separable measurement (no sims):** for every FIT team-game (nflverse 2023-24 REG, weeks 2+), predict each
player's share of the team's CARRIES and of its TARGETS from plays strictly before the week, and score against
what happened. **Metric (fixed):** multinomial log-likelihood per team-game of the realised carries (targets)
over the predicted shares, with an "other" bucket for players the estimator did not list (the estimator's
leftover mass, floored at 0.02); reported per carry and per target, summed over FIT. Secondary: MAE of expected
touches for the players who were QUOTED that game (the rows props are graded on).

**Candidates (fixed now):**
- **E0** = today's `build_team_usage`: current season flat + prior season scaled to 4 games; available =
  touched the ball in the previous game, plus players quoted for this game.
- **E1(H)** = recency weighting: each past game weighted 0.5^(age/H) with half-life H in {2, 4, 8} games
  (prior-season games continue the same decay across the offseason gap); same availability as E0.
- **E2** = E0's weights with stricter availability: drop a player with no touches in the team's last TWO
  games unless he is quoted for this game; a quoted player with no current-season touches enters at his
  prior-season share.
- **E3(H)** = E1(H) with E2's availability.
The best candidate by summed FIT log-likelihood (carries + targets) is CHOSEN and FIXED, then Phase B is re-run on
all 366 FIT games with the run-share correction held at (0.7, 0.1), and reported beside the two earlier runs.
Held-out 2025 untouched.

**Amendment 3 result (2026-10-07):** 1,024 FIT team-games. LL/carry, LL/target, MAE on quoted players (carries /
targets): E0 -1.4026, -2.1627, 1.357 / 1.689; **E1(H=2) -1.3899, -2.1436, 1.287 / 1.628 (CHOSEN)**; E1(H=4)
-1.3920, -2.1524; E1(H=8) -1.4174, -2.1816; E2 -1.4625, -2.2157; E3(H=2) -1.4402, -2.1870. Recency helps
everywhere (~5% less carry error on quoted players); the stricter availability rule HURTS -- it drops players
returning from absence who carry the ball without a prop line, pushing their touches into "other". Modest
gain; Phase B re-run with E1(H=2) + (c, r) = (0.7, 0.1).

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

### NCAAF data step — first validation FAILED; parser amendment (2026-10-07, bar unchanged)

First parse: coverage 96-99% for 2023-24 and wk1-8 of 2025, but **0-6% from 2025 week 9 on** -- CFBD's
`playText` switched to an official-gamebook style ("(14:14) Shotgun #47 B.Bachmeier pass complete short
left to #11 P.Kingston caught at BYU34, for 1 yard ..."): jersey numbers, initial.last names. The
2025 validation FAILED the pre-registered bar on every stat (rush yds 0.576, rec yds 0.604, rush att
0.607, receptions 0.755, pass yds 0.616 vs 0.90) and the parse was NOT used.
**Amendment (the pre-registration allows "the parser is fixed"; the bar does not move):** add rules for
the gamebook style (`#N <name> rush`, `#N <a> pass complete ... to #N <b>`, `pass incomplete ...
(intended for|to) #N <b>`, `#N <a> sacked`, `#N <a> pass intercepted`), and key players by FIRST
INITIAL + LAST NAME in every format (and the box scores the same way), since gamebook rows carry only
the initial. Re-validated on 2025 against the same bar.

Second validation (after the gamebook rules): coverage 98-99%; receptions PASS 0.960; rush yds 0.762,
rush att 0.819, rec yds 0.862, pass yds 0.800 still FAIL -> not used. Decomposed: QB rows are 1,415 of the
2,296 rushing failures and adding sack yardage fixes 832 of them -- **NCAAF box scores count sacks as QB
rushing** (an NFL/NCAAF stat-definition difference, so the NCAAF attribution must also charge a sim
sack to the QB's rushing); the rest are two unhandled text shapes (summary TD lines "X 7 Yd Run (..
Kick)" / "X 76 Yd pass from Y", and multi-word gamebook names "#7 C.Del Rio-Wilson"). **Amendment:** sacks
count as QB rush attempts/yards for NCAAF; both text shapes added. Same bar.

Third validation: rush att 0.908 PASS, receptions 0.968 PASS; rush yds 0.851, rec yds 0.885, pass yds 0.840
FAIL -> not used. Counts pass and yards fail, so the defect is the YARD field: on 2-9% of plays CFBD's
`yardsGained` folds in penalty yardage ("pass complete ... for 13 yds ... Personal Foul" -> 28) or is
corrupt (a "no gain" run at -62). **Amendment (reverses the pre-registered "yards from yardsGained,
never parsed"):** yards come from the play TEXT when it states them ("for N yd(s)/yard(s)", "for N
yard(s) loss", "for a loss of N", "for no gain", "N Yd Run/pass"), `yardsGained` only as the fallback.
Same bar.

Fourth validation (text yards): receiving yds 0.901, rush att 0.908, receptions 0.968 PASS; **rushing yds
0.873 and passing yds 0.868 still FAIL -> NOT ACCEPTED, not used.** Open leads: kneel-downs in the
"B. Lowry takes a knee" shape are unparsed while box scores count them as QB rushes; 447 passer rows
parse with no box match (a join, not a parse, problem -- unexamined).

**Amendment (2026-10-07, user: "fix the kneel-down and passer join"; bar unchanged).** Of 3,188 parsed
passer-games, 447 had no box row: (i) spelling/nickname variants of ONE player ("Zolten Osborne" vs box
"Osbourne", "Goose" vs "Will" Crowder); (ii) junk captured as a name from 2-pt / penalty fragments
("Drew Allar, Two Point Conversion Failed...", "to Griffin Wilde, Preston Stone"); (iii) players absent
from the box entirely (unfixable here; they stay misses). Fixes: a NAME SANITY rule (no digits, commas,
"to ", > 4 words -> unparsed); an IDENTITY RESOLVER applied identically wherever parsed players meet a
roster -- an unmatched parsed key maps to the team-game roster player with the SAME last name, else a
same-initial near-spelling (difflib >= 0.85), ONLY when exactly one candidate qualifies; kneel-downs
("<A> takes a knee" / "<A> kneels", "for loss of N") parsed as QB rushes. Team kneels ("Kneel down by
Kansas") name no player and stay unattributed.
Fifth validation (after that amendment): unmatched passer rows 447 -> 10 (join FIXED); rec yds 0.914,
rush att 0.924, receptions 0.980 PASS; **rush yds 0.894 and pass yds 0.860 FAIL -> not used.** Pass-yard
misses are mostly the parse running LOWER by 20-50 yds (287 of 381): whole plays missing. Measured
cause: ~1,900 2025 offensive plays live under OTHER playTypes -- "Pass Completion" (753, an unlisted
type name, text "X pass to Y for N yds"), fumble recoveries whose text starts with the run/catch
(1,065), counted penalties (62), "Fumble" (60). **Amendment (same request, same bar):** "Pass
Completion" + the "pass to ... for" shape; for Fumble*/Penalty/Uncategorized types, parse the leading
run/pass from the text unless it says "no play"; the summary-line passer stops at the first comma.

**Sixth validation -- ACCEPTED (2026-10-07).** 2025, 888 games with both parse and box, identity resolver
remapped 1,829 of 148,883 player references: rush yds 0.932, rec yds 0.937, rush att 0.937, receptions
0.986, pass yds 0.917 -- all >= 0.90. Plays attributed: 2023 110,305 / 2024 110,984 / 2025 115,432.
Stated limit: box scores exist for 2025 only, so 2023-24 are validated only through the 2025 weeks that
share their (classic) text style (wk1-8); the parser and resolver are identical across seasons.

## NCAAF Phase B/C — PRE-REGISTERED 2026-10-07 (user: "run the NCAAF attribution backtest when the props pull finishes")

Same design as NFL, with these NCAAF-specific choices fixed now:
- **Engine:** production's NCAAF `build_projection` (promoted `ncaaf-goal-line-refit-1`, all scenario
  switches OFF), as-of SP+/PPA blend tasks from the scenario harness (FBS-vs-FBS, weeks 3-15), 300 seeds.
- **Tables:** P(pass | down, to-go, diff, time, yards), real yard quantiles and P(INT | turnover) measured
  on CFBD 2024 plays (FIT) through the ACCEPTED parser. **NCAAF sack rule:** a sim sack is a QB rush
  attempt with its (negative) yards, as in the box scores.
- **Usage:** as-of from the parsed plays (current season before the week + prior season scaled to 4
  games); availability = touched the ball in the team's previous game, plus every player quoted for this
  game (A1). Players are keyed by first initial + last name; quote names and roster keys meet through the
  same `resolve_key` the parser validation used.
- **Rows:** OddsAPI historical quotes (private root), two-sided only, de-vigged per book; anytime TD
  needs yes AND no. **Actuals:** the parsed per-player-game totals (the accepted parser) for both seasons.
- **Phase B (FIT 2024):** attribution vs the de-vigged BOOK only -- production's NCAAF yardage props
  (`prop_projections`) are built from player box scores, which exist for 2025 only, so production has
  nothing to say about 2024. Construction check: simulated team pass/rush attempts and yards vs parsed.
- **Phase C (held-out 2025, read once):** attribution vs production's `prop_projections.prob_over` (as-of
  week) vs the book, same rows, game-clustered paired log-loss per market. Falsification as for NFL.

**Part 2 probe (2026-10-07, 11 credits):** OddsAPI historical NCAAF events for 2024-10-12 15:50Z = 76
events (1 credit); Alabama vs South Carolina `player_rush_yds` = 5 books, 63 outcomes (10 credits);
4,127,431 credits remaining. The 2024 NCAAF props archive EXISTS. Bulk estimate, from the repo's
measured billing (`backfill_nfl_historical_props.py`: 10 credits per market-region per event): ~7
markets x 10 = ~70 credits per game with props; 2024 + 2025 FBS ~1,300 games -> <= ~91k credits
(~2% of the cap; fewer, since not every game has props). Not run at scale yet.

## Results

### NFL Phase B (FIT 2023-24) — 366 games, 122,955 quote rows, 300 seeds, production engine (2026-10-07)

Log-loss per row; deltas paired, game-clustered 95% CI (negative = attribution better). Slopes =
calibration slope of y on p (1 = calibrated, 0 = no information).

| market | n | LL attr | LL prod | LL book | attr - prod | attr - book | slope attr / prod / book |
|---|---|---|---|---|---|---|---|
| passing_yards | 10,297 | 0.7136 | 0.7872 | 0.6651 | **-0.074 [-0.135, -0.016]** | +0.049 | **0.58** / 0.30 / 0.90 |
| passing_attempts | 4,059 | 0.7544 | 0.7854 | 0.6919 | -0.031 [-0.096, +0.033] | +0.062 | 0.10 / -0.03 / 0.98 |
| passing_tds | 5,590 | 0.6555 | 0.6506 | 0.6398 | +0.005 [-0.009, +0.018] | +0.016 | 0.80 / 0.96 / 1.06 |
| interceptions | 4,201 | 0.6834 | 0.6742 | 0.6664 | +0.009 [-0.001, +0.020] | +0.017 | 0.75 / 0.91 / 1.05 |
| receiving_yards | 44,115 | 0.7548 | 0.7309 | 0.6663 | +0.024 [+0.005, +0.042] | +0.089 | 0.32 / 0.41 / 0.99 |
| receptions | 28,946 | 0.8067 | 0.7318 | 0.6630 | +0.075 [+0.050, +0.101] | +0.144 | 0.27 / 0.43 / 1.03 |
| rushing_yards | 19,258 | 0.8416 | 0.7556 | 0.6687 | +0.086 [+0.050, +0.124] | +0.173 | 0.20 / 0.26 / 0.93 |
| rushing_attempts | 6,058 | 1.1087 | 0.7728 | 0.6901 | **+0.336 [+0.271, +0.406]** | +0.419 | 0.09 / 0.14 / 0.99 |
| anytime_td | 383 | 0.5666 | 0.5179 | 0.4838 | +0.049 [+0.002, +0.099] | +0.083 | 0.42 / 0.70 / 1.02 |

**Construction check (sim per team-game, n = 732):** pass att 35.2, pass yds 253.2, rush att **21.3**,
rush yds 112.4 -- against real NFL roughly 33.5 / ~215 / ~27 / ~115. The engine produces too few
yard-gaining plays and the attribution starves runs (a volume defect, measured at smoke and now on
the full FIT set).

**Reading (FIT, not a ship decision):** attribution BEATS production on passing yards (-0.074, CI
excludes 0) with a much better calibration slope (0.58 vs 0.30) -- game script carries information
for the QB's volume. It LOSES where its volume input is wrong: rushing attempts badly (+0.336),
rushing yards, receptions and receiving yards. Nothing beats the book (production does not either).
48 rows unattributed. The next design step is the run-volume defect (an engine property: the
scenario lane's v2 re-fit, or a measured run-share correction in the layer) -- to be pre-registered
before any held-out read.

### NFL Phase B WITH the run-share correction (c = 0.7, r = 0.1) — same 366 games / 122,955 rows (2026-10-07)

| market | attr - prod, uncorrected | **attr - prod, corrected** | slope attr (corrected) |
|---|---|---|---|
| passing_yards | -0.074 | **-0.078 [-0.132, -0.030]** | 0.52 (prod 0.30) |
| passing_attempts | -0.031 | +0.032 [-0.026, +0.086] | 0.12 |
| passing_tds | +0.005 | **+0.026 [+0.011, +0.042]** | 0.79 |
| interceptions | +0.009 | +0.007 [-0.002, +0.017] | 0.78 |
| receptions | +0.075 | +0.069 [+0.048, +0.092] | 0.31 |
| receiving_yards | +0.024 | +0.028 [+0.011, +0.044] | 0.36 |
| rushing_attempts | +0.336 | **+0.226 [+0.167, +0.289]** | **0.06** |
| rushing_yards | +0.086 | +0.089 [+0.053, +0.130] | 0.18 |
| anytime_td | +0.049 | +0.042 [-0.003, +0.091] | 0.44 |

Team volume moved as designed (rush att 25.6, pass att 30.9, rush yds 138.1, pass yds 219.5 per team-game).
**Reading:** the correction recovers a third of the rushing-attempts loss and costs passing attempts and
passing TDs (pass volume now undershoots). Volume was NOT the main rushing defect: a calibration slope of
0.06 on rushing attempts means the attributed probabilities carry almost no information about WHICH player
clears his line -- the weak link is player-level (carry shares, committee backfields, availability), not the
team total. Passing yards remains the only market beating production, corrected or not. No market beats the
book. Next design candidates (each to be pre-registered): per-player carry-share quality (recency weighting,
injury/availability), and using attribution only where it has shown information (QB passing yards).
