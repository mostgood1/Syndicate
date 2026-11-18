# Findings — Understat outage: what frozen big-5 history costs, and whether the in-repo fallbacks beat it (lane `understat-fallback-backtest`, 2026-11-18)

Session a0334d60, started by session local_075eb2d2. Research only: no fleet load, no change to the served model.
Hypotheses H1-H6 and the design were committed in `13d4bb9f2` (3:12 PM CST) before any arm was scored.
Follows `findings_2026-11-18_understat_fetch_failures.md` (the outage itself; lane `understat-fetch-failures`).

## 0. Bottom line

All figures are 1X2 log loss per match against the outcome, leak-free, on **1,818 big-5 matches (2025-09-15..
2026-10-31), every one with a true close**, unless stated. Substrate: copies of the fleet's own inputs (section 1).

1. **The freeze costs little today and grows.** History frozen *k* rounds back, against current history:
   - +0.0007 [−0.0013, +0.0025] at 2 rounds (today: 1-2 rounds missing per club);
   - +0.0027 [−0.0003, +0.0058] at 4 (the 12-08 window);
   - +0.0067 [+0.0023, +0.0114] at 8 (about the 12-22 window).

   Totals (O/U 2.5) show no cost at any *k*. For scale, the served sim already trails the close by about +0.026.
2. **The splice is the fallback worth having.** It keeps the Understat rows and adds a goals-as-xG row per club
   for each match Understat missed.
   - It holds the cost at about **+0.0014 whatever the gap**.
   - Against the frozen history it is slightly worse at 1-3 rounds (up to +0.0007, CI spans 0), −0.0013 at 4,
     and **−0.0054 [−0.0103, −0.0004] at 8**.
   - On the 69 real outage matches (11-01..11-08) it was +0.0084 [+0.0015, +0.0185], one round in.
   - The real engine moves its probabilities 0.60-1.00× the way the link does for these arms.
   - It is **on main, default OFF**: `SYNDICATE_SOCCER_UNDERSTAT_SPLICE`, tested 20 of 20. Built on the fleet
     copies, it reproduces the measured arm exactly.
3. **A goals-based switch is not better.** G90 ties current Understat on 1X2 (+0.0008 [−0.0053, +0.0066]), but:
   - it is worse on totals;
   - it is four times noisier per match;
   - its window re-fit does not settle;
   - the real engine runs it 17% more dispersed. It would need an engine re-fit before it could even be tried.
4. **ESPN players are worse.** Realised goals and assists per 90 lose to Understat xG/xA by +0.0083 and +0.0138
   per appearance at equal data (9,366 appearances, CIs above 0). Two rounds of fresher player data are worth
   about 0 on goals and assists. Under 2% of outage-match shots came from players outside the frozen squad.
5. **Recommendation (section 8):**
   - change nothing now or at 11-24;
   - switch the splice on in the **12-08 window** if Understat is still down;
   - do not move the big 5 to goals ratings or to ESPN players.

   This is the user's decision: todo `#845`.

## 1. Substrate and coverage

**Substrate: `fleet`, read as copies.** Every model input was copied read-only from the fleet's disk to
`C:/tmp/ustale_1118/fleet_src` at 2026-11-18T21:00:25Z (pre-kickoff freezes and props at 21:14:15Z). A sha256
manifest of the 246 files is `fleet_src/_manifest.sha256`. The true closing odds are football-data.co.uk's raw
season files (`AvgC*` columns), fetched at 21:07Z into `C:/tmp/ustale_1118/fd_raw` (sha256 in `_manifest.sha256`
there). The fleet's own `history/matches_*.csv` keep only the pre-close `Avg*`. The fleet roles' env was read
from `/proc/<pid>/environ`, those keys only: `SYNDICATE_SOCCER_CURRENT_HISTORY=1` on refresh-worker,
live-odds-worker and web, so the few-match gate is ON; `SYNDICATE_SOCCER_RATING_V2` is absent, so ratings are v1.

| family | what | dates on the fleet copy |
|---|---|---|
| Understat team rows `team_history/teams_{2024,2025,2026}.csv` | xG, ppda, goals, points per club-match | 2024-08..2026-10-31 (frozen) |
| football-data `history/matches_{2023,2024,2025}.csv` + raw 2627 | results, shots, corners; pre-close odds | 2023-08..2026-11-08 |
| football-data raw 2526 / 2627 | TRUE close `AvgC*` (1X2, O/U 2.5) | 2025-08..2026-05, 2026-08..2026-11-08 |
| ESPN `espn_match_stats.json` | possession / set-piece share (goals path only) | as on the fleet (written 09-30) |
| Understat `players/players_{2024,2025,2026}.csv` | per-90 rates (2026 frozen at 10-31) | season aggregates |
| ESPN `history/player_match_log_{2024,2025,2026}.csv` | one dated row per player-match | 2024-08..2026-11-08 (2026: 500 big-5 events) |
| served pre-kickoff freezes `recommendations_prekickoff_*` | what the board priced | 10-30..11-08 |

**The intersection a result rests on** is stated with each table below: "hist" = big-5 matches 2025-09-15..
2026-05-24 plus 2026-09-15..10-31, where all of current Understat, football-data results and the close exist.
"now" = the 69 matches 11-01..11-08, which are every big-5 league match played while Understat was down (the
ESPN logs and football-data agree: epl 12, la_liga 15, bundesliga 11, serie_a 17, ligue_1 14; 11-09..11-18 was
an international break). On "now" there is no current Understat, so U arms cannot be compared with it there.

## 2. Design (pre-registered `13d4bb9f2`; deviations in section 9)

- **Arms**, each a ratings source as of the match day, all through production's own code
  (`compute_team_ratings`, then `_fill_promoted` + `_gate_few_match`):
  - **U*k***: Understat rows dated before a freeze `c_k(d)` = the (k·N/2)-th most recent league match before
    day d (so at least k rounds are missing), window 45 (production's path). **U0 = current.**
  - **G*W***: production's goals path (`team_rows_from_match_history` on football-data + `espn_match_stats`),
    window W. G90 is what the four goals-rated leagues run; **GR** picks W from {45, 60, 90, 120} on the training
    fold.
  - **S*k*** (splice): Understat rows before `c_k(d)` plus a goals-as-xG row per club for each match in
    [`c_k(d)`, d). A spliced row carries ONLY Understat's engine-read fields (`xg_for`/`xg_against` = goals,
    `goals_for`/`goals_against`, `points`), so no new metric enters the engine. **SA** is the real outage:
    every Understat row plus goals rows after 10-31.
- **Stage A, all matches:** a per-league Poisson link `log λ_home = μ + η + k·(att_h − def_a)`,
  `log λ_away = μ + k·(att_a − def_h)`, fitted on the other half of match days (2-fold by day parity). Two
  readings: **re-fit** (each arm gets its own μ, η, k: the information the input carries once level and
  dispersion are re-fitted, i.e. the mechanism change done properly) and **fixed map** (every arm scored with
  U0's fit: a source swapped in with no re-fit, as production would run it). 1X2 log loss vs the outcome is
  primary; Brier and O/U 2.5 secondary; CIs from 2,000 bootstrap resamples over matches.
- **Stage B, the real engine on a sample:** production's `build_soccer_simulation_input` + SoccerSim, 200
  simulations, same seed in every arm (`match_id`), on 24 random hist matches per league (three leagues completed;
  section 5), arms U0, U4, U8, S4, S8, G90. It checks the one thing the link cannot: that the engine moves its probabilities the way the link
  does (the RATING V2 lesson, `findings_2026-10-19_soccer_rating_v2_sim.md`). The engine costs 0.117 s of CPU
  per simulated match, so the full population cannot be run through it.
- **Players (Q3):** each appeared player-match priced with the player's per-90 rate × his ACTUAL minutes
  (Poisson); log loss of P(goal ≥ 1), P(shots ≥ 1), P(shots ≥ 2), P(assist ≥ 1); CIs resample MATCHES.

## 3. Q1 — the cost of staleness: small now, about +0.0007 log loss per match per missing round from round 4

Stage A at harness `84a1fa85e` (run from the local commit `e216b0bd5`, content-identical: no soccer code changed on
main during the runs), outputs `C:/tmp/ustale_1118/stageA/<league>/rows.jsonl` + `pooled/summary.json`,
readout `C:/tmp/ustale_1118/stageA_readout.txt`. **hist: 1,818 big-5 matches** (epl 388, la_liga 393, bundesliga
322, serie_a 405, ligue_1 310), 2025-09-15..2026-10-31, **every one with a true close.** Δ = arm − U0 (current
Understat), per match, 1X2 log loss:

| frozen k rounds | 1X2 re-fit | 1X2 fixed map | Brier | O/U 2.5 |
|---|---|---|---|---|
| 1 | +0.0010 [−0.0004, +0.0026] | +0.0008 | | −0.0007 [−0.0017, +0.0002] |
| 2 | +0.0007 [−0.0013, +0.0025] | +0.0005 | +0.0004 [−0.0010, +0.0017] | −0.0006 [−0.0020, +0.0007] |
| 3 | +0.0009 [−0.0015, +0.0033] | +0.0007 | | −0.0013 [−0.0031, +0.0003] |
| 4 | +0.0027 [−0.0003, +0.0058] | +0.0024 | +0.0018 [−0.0004, +0.0039] | −0.0013 [−0.0034, +0.0007] |
| 6 | **+0.0038 [+0.0002, +0.0077]** | +0.0032 | | −0.0004 [−0.0029, +0.0020] |
| 8 | **+0.0067 [+0.0023, +0.0114]** | **+0.0058 [+0.0009, +0.0109]** | **+0.0047 [+0.0016, +0.0079]** | −0.0000 [−0.0027, +0.0026] |

- **Scale:** on the same matches the link (U0) trails the close by +0.0208; the served sim trailed it by +0.0264 on
  the 69 outage matches (section 5) and by +0.020..0.028 in the season audits. Eight frozen rounds add about a
  third of that gap again.
- **Totals do not care.** O/U 2.5 shows no staleness cost at any k (every CI spans 0, point estimates ≤ 0): the
  projected total is mostly the league level, and ratings are league-relative.
- **By league (re-fit, U2 / U4 / U8 − U0):** epl +0.0002 / +0.0028 / +0.0066; la_liga −0.0015 / −0.0049 /
  −0.0012; bundesliga +0.0042 / +0.0078 / +0.0101; serie_a +0.0010 / +0.0024 / +0.0000; ligue_1 −0.0002 /
  +0.0074 / +0.0223. Bundesliga and Ligue 1 lose fastest; La Liga and Serie A show none within 8 rounds. Each
  league alone is ~320-400 matches, so these are directions, not verdicts.
- **Early season shows none:** on the 237 matches of 2026-09-15..10-31, U8 − U0 is −0.0016 [−0.0108, +0.0075].
  The cost is a mid-season effect (1,581 matches of 2025-26: U8 +0.0080 [+0.0027, +0.0134]).
- **The calendar (median missing rounds per club, from the served ESPN schedules):** today 1-2; the 11-24 window
  2-3; the 12-08 window 4-5; the 12-22 window 6-7; the 01-05 window 6-10. Each league plays its rounds on its own
  calendar (EPL 10 by 01-05, Bundesliga 6).
- **The gate:** the freeze stopped 8 promoted clubs' Understat row count below 10, so production keeps them on the
  flat promoted prior (`PROMOTED_TEAM_RATING`) for as long as the outage lasts: Coventry 9, Hull 9 (epl);
  Elversberg 8, Paderborn 8, Schalke 8 (bundesliga); Frosinone 9 (serie_a); Le Mans 9, Troyes 9 (ligue_1). With
  current history 5 of them would already have left the gate. The U arms include this effect.

**H1 (pre-registered: U2 − U0 in (0, +0.0015], U8 − U0 in (0, +0.006], increasing): FALSIFIED by its own rule**,
on the large-k half only: U8 is +0.0067, just above the +0.006 bound (the cost grows a little faster than
predicted). U2 is +0.0007, inside its range (CI spans 0), and the curve rises.

## 4. Q2 — the fallbacks: the SPLICE caps the cost; a goals-based switch is no better and four times noisier

Same 1,818 matches. Δ vs current (U0) and vs the frozen arm it would replace (U*k*):

| arm | vs U0, re-fit | vs U0, fixed map | vs frozen U*k*, re-fit | O/U 2.5 vs U0 |
|---|---|---|---|---|
| S1 | +0.0011 [+0.0003, +0.0019] | +0.0009 | +0.0000 [−0.0016, +0.0015] vs U1 | +0.0004 |
| S2 | +0.0014 [+0.0001, +0.0026] | +0.0010 | +0.0007 [−0.0013, +0.0029] vs U2 | +0.0003 |
| S3 | +0.0016 [+0.0001, +0.0031] | +0.0012 | +0.0006 [−0.0019, +0.0032] vs U3 | +0.0001 |
| S4 | +0.0014 [−0.0003, +0.0032] | +0.0010 | −0.0013 [−0.0047, +0.0019] vs U4 | +0.0006 |
| S6 | +0.0015 [−0.0007, +0.0037] | +0.0010 | −0.0024 [−0.0064, +0.0015] vs U6 | +0.0011 |
| S8 | +0.0014 [−0.0012, +0.0041] | +0.0009 | **−0.0054 [−0.0103, −0.0004]** vs U8 | +0.0005 |
| G90 | +0.0008 [−0.0053, +0.0066] | −0.0009 [−0.0073, +0.0054] | +0.0001 vs U2; −0.0020 vs U4; −0.0060 [−0.0124, +0.0003] vs U8 | +0.0033 [−0.0022, +0.0088] (fixed +0.0061) |
| G45 / G60 / G120 | +0.0072 [+0.0017, +0.0127] / +0.0026 / +0.0011 | | | +0.0045 / +0.0041 / +0.0040 |
| GR (window re-fit on the train fold) | +0.0019 [−0.0039, +0.0076] | +0.0010 | −0.0008 vs U4; −0.0048 vs U8 | +0.0031 |

- **The splice holds the cost flat at about +0.0014 whatever the gap** (S1..S8 − U0 = +0.0011..+0.0016). Against
  the frozen history it is slightly worse while the gap is 1-3 rounds (+0.0000..+0.0007, CIs span 0), even at
  4 (−0.0013), and better from there: −0.0024 at 6, **−0.0054 [−0.0103, −0.0004] at 8**. The crossing is between
  3 and 4 rounds.
- **Goals-based ratings (G90, what the four goals-rated leagues run) tie current Understat on 1X2** (+0.0008),
  which falsifies H2's "xG beats goals by ≥ 0.004". But its per-match differences are about four times the
  splice's (CI half-width ±0.006 against ±0.0015), it is worse on totals (+0.0033 re-fit, +0.0061 with no re-fit),
  Ligue 1 loses +0.0152 [CI above 0] with it, and the window re-fit does not settle (the training folds picked 45,
  60, 90 and 120 in different leagues; GR is no better than G90). Against frozen it crosses at about the same k
  as the splice, with a much wider CI. It also changes what the engine reads: the goals path adds shots,
  corners, clean-sheet rate, possession and set-piece share, and drops ppda and the separate goals term (section
  5 measures what the engine does with that).
- **H2 FALSIFIED** (G90 − U0 = +0.0008, not ≥ +0.004; its point estimate crosses frozen at k ≈ 2-4, though no CI
  clears 0 within 8 rounds). **H3 FALSIFIED by its own rule** (S2 − U2 = +0.0007 > 0, CI spans 0); its k ≥ 4 half holds
  (S4 − U4 −0.0013, S8 − U8 −0.0054 with the CI below 0). **H4 SUPPORTED for staleness, FALSIFIED for the fallbacks:** for U4/U6/U8 every
  |O/U Δ| is at most half the 1X2 Δ (−0.0013 vs +0.0027 at k = 4 is the closest), but G90's O/U Δ (+0.0033) is
  four times its 1X2 Δ, and S6's (+0.0011) is more than half of its +0.0015. A goals source moves totals more
  than it moves 1X2.

## 5. The 69 outage matches, and the real engine

**What was served (11-01..11-08, all 69 matches, all frozen before kickoff; script `C:/tmp/ustale_1118/served_now.py`,
joined output `now_joined.json`):** the served sim's 1X2 log loss 0.8852 against the close's 0.8588, **served − close
+0.0264 [−0.0213, +0.0722]**; on O/U 2.5 the served model was −0.0118 [−0.0512, +0.0268] against the close. The link's
U0 tracks the served sim closely here (p(H) − p(A) correlation 0.948), and trails the close by +0.0247.

Arms on the same 69 (U is frozen at 10-31 in every U arm, so they cannot be compared with current Understat):

| arm | 1X2 vs frozen (U0 here = served-equivalent), re-fit | fixed map | O/U 2.5 |
|---|---|---|---|
| SA (the actual splice: Understat + goals rows after 10-31) | **+0.0084 [+0.0015, +0.0185]** | +0.0065 [−0.0003, +0.0167] | +0.0092 [−0.0023, +0.0294] |
| G90 | +0.0077 [−0.0223, +0.0359] | −0.0047 [−0.0365, +0.0261] | +0.0089 [−0.0182, +0.0369] |
| G45 / G60 / G120 | +0.0205 / +0.0109 / +0.0027 | −0.0028 / −0.0061 / −0.0098 | |

On the real gap (one round for most of these matches: about half were the first round after 10-31, where SA and
U0 are identical), **nothing beat the frozen history.** One match, Cagliari v Frosinone (11-07), carries +0.25 of
the splice's loss: under SA Frosinone's row count reached 10, it left the few-match gate, and it was priced on
its own rows instead of the promoted prior. Without it SA − U0 is +0.0048 [+0.0004, +0.0100] (68 matches). That
agrees in sign with Stage A at one or two rounds (S1 − U1 +0.0000, S2 − U2 +0.0007) but is larger; on 69 matches
it is one draw of a noisy quantity, and the 1,818-match Stage A is the estimate to use.

**Stage B: the real engine** (`understat_staleness_simcheck.py`, outputs `C:/tmp/ustale_1118/stageB/*.jsonl`, readout
`stageB_readout.txt`). **73 matches** (epl 24, ligue_1 24, serie_a 24, plus the one la_liga match that completed
before that league's run was stopped; la_liga and bundesliga were stopped after 4-5 rows to let the other three
finish, because five engines at Idle shared the host with the fleet). 200 simulations, same seed per match in
every arm; binomial sd of one p(home) ≈ 0.033.

| arm | engine slope on the link's per-match Δ(p(H) − p(A)) vs U0 | correlation | engine spread sd(p(H) − p(A)) | engine 1X2 Δ vs U0 | link (fixed map) Δ on the same 73 |
|---|---|---|---|---|---|
| U0 | — (engine vs link map: slope 0.988, corr 0.938) | | 0.293 (link 0.279) | | |
| U4 | 0.75 | 0.44 | 0.289 | −0.0183 [−0.0490, +0.0124] | −0.0084 [−0.0187, +0.0011] |
| U8 | 1.00 | 0.59 | 0.287 | −0.0278 [−0.0615, +0.0057] | −0.0029 [−0.0175, +0.0117] |
| S4 | 0.82 | 0.34 | 0.295 | −0.0107 [−0.0365, +0.0163] | −0.0002 [−0.0056, +0.0053] |
| S8 | 0.60 | 0.39 | 0.306 | −0.0067 [−0.0333, +0.0183] | −0.0011 [−0.0106, +0.0079] |
| G90 | 1.12 | 0.65 | **0.344 (+17% vs U0)** | −0.0239 [−0.0760, +0.0299] | −0.0028 [−0.0296, +0.0246] |

- **The engine moves its probabilities the way the link does** for the stale and splice arms: slopes 0.60-1.00
  (the engine noise sits in the dependent variable, so the slopes are not attenuated; the correlations are). The
  engine's U0 map and the link's are nearly the same function (slope 0.988, corr 0.938). So the link's Q1/Q2 deltas
  carry to the engine at 60-100% of their size, and their SIGN carries. **H5 SUPPORTED.**
- **Goals-based inputs make the ENGINE 17% more dispersed** (0.344 against 0.293), while the re-fitted link made
  G90 3% LESS dispersed (0.278 against 0.286). The engine reads the goals path's extra fields (shots, corners,
  clean-sheet rate, possession, set-piece share) on top of the rating, the RATING V2 kind of divergence in the
  other direction. A goals switch would need an engine dispersion re-fit first (model engine standard 4.4).
- **The engine's outcome deltas on 73 matches are Monte Carlo noise** (CIs ±0.03-0.05; per-match correlation with
  the link's deltas 0.09-0.54). On this sample both the engine and the link score the stale arms slightly better
  than current, so the sample is a favourable draw for staleness, not an engine contradiction. The 1,818-match link
  estimates stand as the measurement; the engine sample licenses their direction.

## 6. Q3 — players: an ESPN re-source is WORSE, and the player freeze costs almost nothing

Script `scripts/soccer_season_audit/understat_players_fallback.py` (`84a1fa85e`), output
`C:/tmp/ustale_1118/players/summary.json`. Understat rows are used as stored (already shrunk toward a (league,
position) prior at ingestion); ESPN rows are aggregated from the match log exactly as
`aggregate_season_player_stats` does, then production's load-time `_shrink_espn_goal_rates`. Production keeps one
row per player: the one with the most minutes.

**P1 — source at equal data (2025-26 rows of each source predict 2026-27 appearances, 08-15..11-08, outfield,
paired on players both sources rate): 9,366 appearances in 498 matches.** Δ = ESPN − Understat log loss per
appearance:

| market | Understat | ESPN | Δ [95% CI] | mean p U / E / actual |
|---|---|---|---|---|
| anytime goal | 0.2804 | 0.2887 | **+0.0083 [+0.0029, +0.0134]** | 0.100 / 0.089 / 0.096 |
| assist | 0.2434 | 0.2572 | **+0.0138 [+0.0090, +0.0189]** | 0.077 / 0.067 / 0.072 |
| shots ≥ 1 | 0.6217 | 0.6215 | −0.0002 [−0.0007, +0.0003] | 0.501 / 0.501 / 0.534 |
| shots ≥ 2 | 0.4550 | 0.4545 | −0.0006 [−0.0011, +0.0001] | 0.236 / 0.236 / 0.268 |

Model xG/xA beats realised goals/assists per 90 as a scorer/assist estimator, clearly. Shots are the same
quantity from two providers and tie.

**P2 — the actual choice on the 69 outage matches (11-01..11-08): frozen Understat (production) vs ESPN current
(logs before each match day), 1,907 appearances.** ESPN − Understat: goal +0.0076 [+0.0000, +0.0151], assist
+0.0077 [−0.0003, +0.0158], shots ≥ 2 +0.0168 [+0.0033, +0.0377], shots ≥ 1 +0.0820 [+0.0209, +0.1620]. The
shots rows are worse than P1 because production's ESPN path leaves `shots_per90` UNSHRUNK (only xg/xa are shrunk at
load), and the max-minutes dedup selects thin current-season rows for new players: a 3-appearance row with zero
shots prices P(shots ≥ 1) at 0. **Freshness within ESPN (frozen at 10-31 vs current, same rows otherwise):** goal
+0.0004 [−0.0002, +0.0011], assist +0.0004 [+0.0000, +0.0010], shots ≥ 1 −0.0207 [−0.0521, +0.0004]. Two more
rounds of player data buy nothing on goals or assists.

**P3 — exposure of the 69 outage matches (2,149 appearances, 1,922 shots, 169 goals):**

| production row of the player who appeared | appearances | shots | goals |
|---|---|---|---|
| a 2025-26 (or 2024-25) row: more minutes there than in 2026-27, so the freeze does not touch his rate | 64.2% | 67.0% | 71.6% |
| the FROZEN 2026-27 row (his current season is his biggest sample) | 32.2% | 31.1% | 27.2% |
| no Understat row at all (debut after 10-31, or a name the join could not place) | 2.8% | 1.7% | 1.2% |
| only a 2024/2025 row, not in the 2026 file (reaches a squad only through the ESPN-roster rescue) | 0.8% | 0.3% | 0.0% |

By league, the frozen-2026 share of shots: epl 21.5%, la_liga 30.5%, bundesliga 33.2%, serie_a 32.2%, ligue_1
37.1%; no-row 0.6-2.8%. The no-row count is after an accent-folded name join with a club-level fuzzy fallback;
before that fallback it read 9.8% of appearances, almost all spelling ("Gabriel" / "Gabriel Magalhães"), so the
true squad gap is at most the 1.7% of shots shown.

**What a clean per-league re-source would take** (for the record; not recommended):

1. All seasons of the league from ESPN, not just 2026: `test_no_league_is_served_by_two_sources` forbids a squad
   mixing realised-goal and xG rows, and production's dedup reads every `players_*.csv` on disk. The per-match
   source already exists for all three seasons (`build_soccer_player_match_log.py`, scheduled daily at 11:15).
2. Move the league from the Understat set to `_SOCCER_ESPN_PLAYER_LEAGUES` (`refresh_odds_sources.py`) so its
   `_players` step runs `aggregate_season_player_stats`, and amend the two-sources test.
3. Shrink ESPN `shots_per90` the way Understat's ingestion shrinks every per-90 (`_shrink_toward_prior`,
   180-minute stabilizer). Without it, P2 shows shots priced at 0 for thin rows.
4. Player ids change from `understat_<n>` to ESPN's. That would FIX the live-stat id mismatch (`learnings.md`:
   live ESPN stats can never meet an `understat_<n>` row), but every name/id join to the squad
   (confirmed XI, prop projections, settlement) needs a replay.
5. And it would still lose 0.008 (goals) and 0.014 (assists) log loss per appearance against Understat at equal
   data (P1).

**Q3 verdict: do NOT re-source big-5 players to ESPN.** Frozen Understat rates beat ESPN rates on scorer and assist
props at equal data and on the actual outage matches; the freeze touches the rate of about a third of the shots
priced, and two rounds of extra data are worth ≈ 0 on goals/assists. The squad gap is under 2% of shots.

## 7. Verdicts against the pre-registration (`13d4bb9f2`)

| H | registered | result |
|---|---|---|
| H1 | U2 − U0 in (0, +0.0015], U8 − U0 in (0, +0.006], increasing | **FALSIFIED by its own rule on the large-k half**: U8 +0.0067 (bound +0.006). U2 +0.0007 in range; the curve rises |
| H2 | G90 − U0 ≥ +0.004, no crossing within 8 rounds | **FALSIFIED**: G90 − U0 +0.0008; point estimates cross frozen at k ≈ 2-4 (no CI clears 0 within 8) |
| H3 | S*k* − U*k* ≤ 0 at k 2, 4, 8; CI below 0 at 8 | **FALSIFIED by its own rule at k = 2** (+0.0007, CI spans 0); holds at 4 (−0.0013) and 8 (−0.0054 [−0.0103, −0.0004]) |
| H4 | O/U Δ at most half the 1X2 Δ | **SUPPORTED for staleness, FALSIFIED for the fallbacks** (G90 O/U +0.0033 vs 1X2 +0.0008; S6) |
| H5 | real-engine slope ≥ 0.5 on U/S differences; G90 spread differs from U0's by > 10% | **SUPPORTED**: slopes 0.60-1.00 (U4, U8, S4, S8; 73 matches); G90 engine spread +17% |
| H6 | (a) frozen Understat beats ESPN goals/90 on scorer; (b) ESPN-current shots no worse; (c) < 3% of shots from players outside the frozen squad; (d) the dedup leaves few priced rates on the frozen file | **FALSIFIED by its own rule** on (b) (+0.082: production's ESPN path leaves shots unshrunk) and (d) (31% of shots ride on frozen 2026 rows). (a) SUPPORTED (P1 +0.0083, CI above 0; P2 +0.0076); (c) SUPPORTED (2.0%) |

## 9. Deviations from the pre-registration

1. **Name aliases (before any number was read for a decision).** The first Stage A run joined football-data club
   names to Understat's through production's matcher alone; four did not resolve (Ath Bilbao, M'gladbach, FC Koln,
   La Coruna), so Athletic Club, Borussia M.Gladbach and FC Cologne were priced on the promoted prior in every U/S
   arm. An explicit alias table was added (`FD_TO_UNDERSTAT_ALIASES`) and ALL five leagues were rerun at
   `e216b0bd5` (pushed as `84a1fa85e`); epl, serie_a and ligue_1 reproduced byte-identically, bundesliga and la_liga changed. The first
   run's outputs are kept in `C:/tmp/ustale_1118/stageA_old/` and are not cited. Production joins ESPN names, which
   all resolve (the splice's audit line on the fleet copies: 0 unresolved in five leagues).
2. **Fixed map added beside re-fit** (before any number was read): the registration named the re-fit; the fixed
   map (U0's link for every arm) is what production would run with no re-fit, so both are reported.
3. **SA** (the actual splice on the outage window) was added for the 69 "now" matches; the registered S*k* arms
   need current Understat to define *k*, which those matches lack.
4. **Players population:** H6 was registered on 11-01..11-08; P1 (2025-26 rows → 2026-27 appearances, 9,366) was
   added because 1,907 appearances in 69 matches cannot separate the sources on scorer props.

## 8. Recommendation (the user's to accept or refuse)

1. **Now, and in the 11-24 window (2-3 rounds missing): change nothing.** At 1-3 missing rounds the frozen history
   costs +0.0007..+0.0010 log loss per match (no CI clears 0), and no fallback beats it: the splice is
   +0.0000..+0.0007 against frozen there, and on the 69 real outage matches it was worse.
2. **If Understat is still down at the 12-08 window (4-5 rounds missing then, 6-7 by 12-22): switch the splice on
   there.** `SYNDICATE_SOCCER_UNDERSTAT_SPLICE=1`, env-only (a drained down/up inside the window), betting change
   **yes** (it moves every big-5 rating, pregame and in-play: `poll_soccer_live_state` reads the same loader, so the
   key must reach refresh-worker AND live-odds-worker; a global key in `local_production.env` does). The
   code is on main default-OFF (section 10), with 20 tests, and on the fleet copies it found exactly the 69 outage
   matches with 0 unresolved club names. From 4 rounds it is at least break-even (−0.0013) and the gain grows to
   −0.0054 [−0.0103, −0.0004] at 8; it caps the cost at about +0.0014 against current history however long the
   outage lasts. When Understat refetches, the splice adds nothing (tested), so it never has to be switched off
   for correctness; switching it off after recovery is tidiness.
3. **Do not switch the big 5 to goals-based ratings.** It ties current Understat on 1X2 but is worse on totals, has
   four times the per-match variance, its window re-fit does not settle, and it changes six engine inputs at once.
4. **Do not re-source big-5 players to ESPN.** Realised goals/assists per 90 lose to Understat xG/xA by 0.008 /
   0.014 log loss per appearance at equal data; the player freeze is worth ≈ 0 on goals and assists over 1-2
   rounds; under 2% of outage-match shots came from players outside the frozen squad.
5. Not decided here, and not needed for the above: a freshness signal in the artifact (the newest history row per
   league), and the season-audit sim's own +0.020..0.028 gap to the close, which dwarfs today's staleness cost
   (+0.0007) and is about four times the 8-round cost.

## 10. Code

- Research harnesses (no production path imports them): `scripts/soccer_season_audit/understat_staleness_backtest.py`
  (Stage A), `understat_staleness_simcheck.py` (Stage B), `understat_players_fallback.py` (Q3).
- **`SYNDICATE_SOCCER_UNDERSTAT_SPLICE`** (`1ef73b910`) in `scripts/build_soccer_artifacts.py` (`_understat_splice_enabled`,
  `_understat_splice_rows`, one call in `_load_team_ratings`'s Understat branch). Absent / `0` / `off` / `false` /
  `no` / anything else = today's code exactly. `tests/test_soccer_understat_splice.py`, 20 of 20: off != on through
  the real loader first; absent and falsy values equal `compute_team_ratings` on the Understat rows alone; the
  spliced rows carry exactly Understat's engine-read field set (no shots / corners / possession reach the engine,
  ppda stays the Understat mean); a match Understat holds is never spliced twice; nothing on or after the build date;
  a missing schedule is a no-op; the goals-rated leagues ignore it. Neighbours: 152 of 152 (`test_soccer_team_ratings_as_of`,
  `test_soccer_few_match_gate`, `test_soccer_rating_v2`, `test_backtest_matches_production_rating_source`,
  `test_build_soccer_artifacts`, `test_service_marker_readers`, `test_soccer_player_substrate`,
  `test_soccer_anytime_scorer`).
- Loading it with the switch absent is **betting change: no** (it is today's code). Switching it on is **yes**, and
  goes in a window.
- **The shipped splice IS the measured one:** on the fleet copies, as of 2026-11-19, `_load_team_ratings` with the
  switch on returns exactly the harness's SA ratings for all 96 big-5 clubs (attack, defense and row count; max
  difference 0), although it reads the ESPN schedule where the harness read football-data.
- It prints `SOCCER_UNDERSTAT_SPLICE league=.. as_of=.. understat_last_day=.. spliced_matches=.. unresolved=[..]` once
  per build, so a load can be verified from the role log.
