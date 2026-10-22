# NBA SmartSim: how a side's 240 minutes are allocated (lane `nba-sim-minutes-allocation`, todo `#723`)

Side session of `local_d458ff9c`. Follow-up to the `#714` truth reading
(`findings_2026-10-20_nba_no_history_admit.md`, Results). That reading found the stand-in's minutes prior accurate
(MAE 3.93) and the sim's minutes layer at fault. This file measures that layer on production sims, traces it, and
pre-registers a default-off fix.

Times are US Central unless marked Z. Substrate: **fleet production files**, read-only (`/home/amyn/syndicate-prod/data`).
The fleet code is `09e86a9d`. `git diff 09e86a9d origin/main` is empty for every file traced below.

## 1. Measurement: production sims vs the box (`scripts/nba_sim_minutes_audit.py`)

```
python scripts/nba_sim_minutes_audit.py --processed /home/amyn/syndicate-prod/data/nba_source/data/processed --since 2026-10-20
```

**Coverage (printed first by the tool, run 2026-10-22 9:27:52 AM CT / 14:27:52Z):**

| date | sims | box teams / rows | sides joined | built after tip | pre-tip prop rows | players with a points line |
|---|---|---|---|---|---|---|
| 10-20 | 3 | 6 / 68 | 6 | **3 of 3** | 105,768 | 48 |
| 10-21 | 11 | 22 / 254 | 22 | 0 | 189,059 | 157 |

10-22 and later have no box yet.

**10-20 is excluded from every number below: its sims saw the game.** All three 10-20 sims on disk were rewritten
11:08 PM CT, after the games, by the post-tip rebuild that `#720` (tip freeze) has since stopped. Their pool frames carry
each player's actual 10-20 minutes as `lag1_min`: DET `engine_inputs/2026-10-20/DET_BOS.pkl` has Cade Cunningham
`lag1_min` 35 against a box of 35, Duncan Robinson 28/28, Ausar Thompson 33/33. Their minutes MAE is 0.6-3.0 against
4.5-11.0 on 10-21. The rows are in the tool's output, tagged `[built after tip]`.

**So the result rests on ONE slate, 10-21: 22 sides, 277 pool players, 217 who played.** Every 10-21 sim was written
before its tip (16:28-20:28 CT; the tip-freeze lane's 10-21 reading is 0 post-tip rebuilds).

### Per side, 10-21 (minutes; bias = sim - actual over pool players who played; box `starter` flag)

| team | pool | played | DNP | DNP sim min | starter bias (n) | bench bias (n) | outside-pool min (n) | MAE |
|---|---|---|---|---|---|---|---|---|
| BKN | 15 | 9 | 6 | 93.6 | -12.4 (5) | -3.4 (4) | 20 (1) | 11.03 |
| CHA | 11 | 9 | 2 | 29.1 | -6.2 (5) | +3.5 (4) | 13 (1) | 6.31 |
| HOU | 13 | 11 | 2 | 27.7 | -3.4 (4) | +2.7 (7) | 33 (2) | 4.62 |
| DAL | 9 | 8 | 1 | 13.8 | +3.9 (4) | +3.2 (4) | 45 (3) | 8.59 |
| LAC | 10 | 10 | 0 | 0.0 | +4.1 (5) | +3.7 (5) | 40 (3) | 6.36 |
| SAC | 9 | 8 | 1 | 28.3 | -1.9 (4) | +9.0 (4) | 57 (3) | 6.97 |
| LAL | 13 | 11 | 2 | 37.9 | -3.4 (4) | +0.7 (7) | 30 (1) | 4.84 |
| GSW | 10 | 9 | 1 | 32.9 | +5.2 (3) | +5.6 (6) | 82 (4) | 6.21 |
| MEM | 15 | 9 | 6 | 95.7 | -10.2 (4) | -4.4 (5) | 33 (1) | 6.96 |
| UTA | 14 | 10 | 4 | 24.8 | -7.7 (4) | +6.2 (6) | 31 (1) | 7.63 |
| MIA | 15 | 12 | 3 | 18.7 | -3.8 (5) | +0.5 (7) | 3 (1) | 5.55 |
| MIN | 12 | 11 | 1 | 3.3 | -7.1 (5) | +7.5 (6) | 14 (2) | 8.75 |
| NOP | 16 | 10 | 6 | 52.7 | -8.6 (5) | -2.1 (5) | 0 | 7.60 |
| IND | 11 | 9 | 2 | 38.9 | -6.8 (4) | +4.1 (5) | 34 (1) | 7.13 |
| ORL | 13 | 10 | 3 | 25.8 | -6.3 (5) | +1.4 (5) | 0 | 6.70 |
| ATL | 14 | 8 | 6 | 68.2 | -3.5 (5) | -12.3 (3) | 15 (1) | 6.77 |
| POR | 13 | 10 | 3 | 51.0 | +6.4 (3) | -1.6 (7) | 59 (3) | 7.68 |
| PHX | 14 | 13 | 1 | 5.0 | -3.1 (5) | +2.1 (8) | 7 (1) | 4.46 |
| TOR | 12 | 12 | 0 | 0.0 | +1.9 (5) | +2.1 (7) | 24 (2) | 5.41 |
| CHI | 11 | 8 | 3 | 75.5 | +3.0 (4) | +1.8 (4) | 95 (5) | 5.32 |
| WAS | 13 | 10 | 3 | 54.1 | -12.3 (5) | +1.5 (5) | 0 | 7.59 |
| MIL | 14 | 10 | 4 | 52.3 | -10.8 (5) | +3.6 (5) | 16 (1) | 10.50 |

### Pooled, 22 sides (95% CI, bootstrap over sides, 10,000 resamples, seed 7)

| statistic | value |
|---|---|
| DNP sim minutes per side | **37.7** [26.4, 49.4] |
| outside-pool box minutes per side | 29.6 [19.5, 40.6] |
| starter bias (box starters, n=98) | **-4.21** [-6.41, -1.87] |
| actual >= 28 min (n=70) | -6.71 [-8.79, -4.49] |
| bench bias (n=119) | +1.86 [+0.32, +3.29] |
| minutes MAE, played (n=217) | 6.87 [6.18, 7.62] |

The `#714` reading's 10 sides gave 13.8-89.2 DNP minutes and starters -5.6. The wider population agrees with it.

**Who the DNP minutes went to (829.2 min over 22 sides):**

| cause | sim min | what it means |
|---|---|---|
| `unlisted` | 566.1 (68%) | not on the injury feed, no pre-tip prop line: deep bench / coach's decision |
| `injury_listed` | 163.7 (20%) | OUT on the day's final injury report under his own name, but not excluded when the sim was built |
| `injury_listed_unmatched` | 99.4 (12%) | excluded under a name the pool never matches (§2, Q1a) |

**No DNP pool player had a pre-tip prop line. All 137 pool players with one played.** Of the 140 pool players
without one, 80 played (1,017 box min; the sim gave them 1,197) and 60 did not (the sim gave them 829).

**Outside the pool, 651 box minutes in total:**
- 421 min were played by priced players. They are the no-history stand-ins (`#714`) plus Stephen Curry, whom a
  parse error excluded (§2).
- 230 min were played by unpriced players: rookies and two-way players with no `player_logs` history.

### Against the market (the points line, the minutes-correlated line with the widest coverage)

Population: pool players who played and had a pre-tip points line. The line is the median over books of each book's
latest pre-tip Over line, from `raw/odds_nba_player_props_history_<D>.csv`. The processed `oddsapi_player_props_<D>.csv`
cannot be used: each pull overwrites it, so after tip it holds in-play rows only (measured on 10-21).

| | n | sim min - actual | line's minutes - actual | served pts - line |
|---|---|---|---|---|
| box starters | 97 | -4.20 [-6.43, -1.84] | -2.16 [-3.85, -0.17] | **-1.27** [-1.83, -0.64] |
| bench | 40 | +0.91 [-1.21, +3.05] | -1.81 [-3.51, -0.03] | **+1.37** [+0.77, +1.98] |

- "Line's minutes" = `min_mean x line / pts_mean`: the minutes the line implies at the sim's own scoring rate.
- The served points sit below the market on starters and above it on bench. That is the minutes compression showing
  through the calibration.
- The calibration blends 55% toward the player's own average (`nba_prop_calibration` `b.pts = 0.45`), so about half
  the minutes error survives into points.

## 2. Pipeline trace (file:line on `origin/main` 185634b0 = the fleet's code for these files)

```
refresh-worker props refresh -> basketball_props_smart_sim._smart_sim_run_date_local            B:5156
  props_df = props_predictions_<D>.csv  (the pool: every row on the team = current roster with player_logs history)
  excluded_map = _smart_sim_injuries_excluded_map_for_date_local(...)                             B:5194 -> B:4668
      raw/injuries.csv, LATEST snapshot <= D, status OUT/DOUBTFUL/SUSPENDED/INACTIVE/REST          B:4796
      keys = _norm_name_key(feed name); re-keyed to the props_df team when unique
  add_nba_recency_exclusions(excluded_map, ...)  K=2 regular-season games                          B:5206
  -> worker _smart_sim_worker_run_local                                                            B:4955
     excluded keys -> _excluded_keys_for_source_filter (both name forms)                           B:4393
     -> orchestrator simulate_smart_game                                                           O:1169
        pregame: asof_date = D-1                                                                   O:1239
        home_raw = _drop_excluded(_team_players_from_props(...))   exact key match                 O:1338, O:1359
        NBA: the pool is NOT pruned (prune_pregame_pool=False; WNBA prunes to 11)                  O:1507, runtime.py:96
        pregame_expected_minutes merge: NBA file is starter-columns only -> no exp_min_mean        B:1616
        rot_min = _rotation_sim_minutes_for_team -> no game id -> _rotation_sim_minutes_from_history  B:2526 -> B:2279
           same-phase stints only; before a team's first regular-season game -> "no_recent_history"   B:2361
        _apply_player_priors(home_raw, ..., sim_minutes=None, date_str=asof)                       O:1544 -> B:3390
           _sim_min = _derive_sim_minutes_local(...)                                               B:3415 -> B:3221
              base = _roll_minutes_unscaled: weighted roll5/roll10/roll3/lag1 minutes               O:984 (O:999)
                     (= LAST SEASON's player_logs rows; exp_min_mean absent for NBA),
                     starter signal only nudges weights and caps                                   O:570, O:664
              sum(base) > 240 -> _water_fill_minutes_local: the SAME minutes off every player       B:3177
           per-minute rates: 0.50 prior + 0.35 recent + 0.15 x (pred / _sim_min)                   B:3449, B:3577
        engine: lineups sampled with _sim_min as weights; players[].min_mean = the derived minutes
     -> nba_prop_calibration: served mean = 0.45 x (sim minutes x shrunk rate) + 0.55 x own average
                                                                                   nba_prop_calibration.py:88, :93, :362
  writes smart_sim_<D>_<H>_<A>.json and engine_inputs/<D>/<H>_<A>.pkl (the frames, _sim_min included)
```

`B` = `syndicate/features/shared/basketball_props_smart_sim.py`,
`O` = `syndicate/features/basketball_engine/orchestrator/smart_sim.py`.

### Q1. Why do DNP-bound players carry minutes?

All three suspected causes are real. Their shares on 10-21:

**(a) Injury-feed coverage. 263 of 829 min (32%).**

*Names that never match: 99.4 min, 8 players.* The NBA official injury-report PDF parser
(`syndicate/features/nba/source_cli/scrapers/injuries.py:1018`) builds a player's name from every token between
"Last," and the next status token (`:1159`). A reason that wraps onto the next line lands inside the next player's
name. The 10-21 props refresh logged these exclusions (`SMART_SIM_REUSE_STALE_EXCLUSIONS ... drift=`):
- ISAIAH WAY STEWART, JAVON WAY SMALL, MOUHAMED WAY GUEYE, KESHON WAY GILBERT, ROCCO WAY ZIKARSKY, JOHNNY WAY FURPHY.
  The "Way" is from "G League - Two-Way".
- BEN SUBLUXATION SIMMONS, MARK TENDINOPATHY WILLIAMS, DAILYN TENDINOPATHY SWAIN, DREW TENDINOPATHY TIMME,
  JETT BURSITIS HOWARD, JALEN TEAR WILSON, TONY BRUISE BRADLEY.

None of these matches a pool key, so each player stayed in the pool and was simulated. Jalen Wilson got 21.4 min,
Javon Small 17.0, Jett Howard 13.8, Isaiah Stewart 10.1. `_clean_injury_player_names` (`:174`) repairs a name only
when `_looks_noisy_player_name` (`:162`) flags it. Its token list (`:86`) has no WAY, TENDINOPATHY, SUBLUXATION,
BURSITIS, TEAR or BRUISE.

*Wrong player marked OUT (reproduced through the real `_parse_pdf_rows` on a synthetic token stream, with `PdfReader`
stubbed; not yet on the 10-21 PDF).* `STATUS_TOKS` (`:1050`) lacks "Available".
- The token stream `Curry, Stephen Available Moody, Moses Out Injury/Illness - Left Calf; Strain` parses to ONE row:
  player `Stephen Available Moody, Moses Curry`, status OUT. Moody's own row is gone.
- `_clean_injury_player_names` then flags it noisy (AVAILABLE, a comma) and maps it by last name + first initial to
  Stephen Curry.
- A wrapped `G League - Two-` / `Way` reason yields `Isaiah Way Two- Stewart` the same way.

The 10-21 logs show exactly that swap:
- `GSW:+STEPHEN CURRY/-MOSES MOODY`: Curry was excluded and played 21 min; Moody was simulated for 32.9 min and did
  not play.
- `CHI:+LEONARD MILLER,TOBE AWAKA,ZACH COLLINS/-...NIC CLAXTON`: Miller played 26, Awaka 14, Collins 9; Claxton was
  simulated for 22.2 and did not play.

*Later reports: part of the 163.7 `injury_listed` minutes.* The day's rows in `injuries.csv` are REPLACED on every fetch.
The final report lists players that the snapshot at build time either did not list or listed under a broken name.

**(b) Recency exclusions: inert at season start.** `nba_sim_availability` excludes a player who missed his team's last
K=2 regular-season games. On 10-21 no team had 2 regular-season games, and every log line reads `added 0`. This is the
designed opening-week no-op. After two games per team it starts working.

**(c) The roll-minutes prior: 566 of 829 min (68%), plus most of Q2.**
- Every props_predictions row on the team is in the pool. NBA is never pruned. On 10-21 the median pool was 13 and the
  median number who played was 10.
- Each pool player's base is LAST season's rolling minutes, which carry no information about this season's depth
  chart. Tanking-team garbage time inflated several of them: Jahmai Mashack roll3 39.7, Cody Williams 29.0 sim / 3
  actual, Moussa Cisse 32.0 / 3, Jericho Sims 22.4 / 2.
- The water-fill only takes out the excess over 240, so a deep-bench player with a big base keeps a big share.
- The market already knew: none of the 60 DNP pool players had any pre-tip prop line.

### Q2. Why are starters compressed?

1. **The water-fill takes the excess equally off everyone.** `_water_fill_minutes_local` (B:3177) was fit on WNBA
   (2026-09-17..29, 11-12-player pools). There, "same minutes off everyone" removes them from the end of the bench.
   A 13-15-player NBA pool built on last season's minutes has a large excess, and a starter loses as many minutes as
   the 13th man.
2. **Nothing in the NBA derive path gives starters a role level.**
   - `exp_min_mean` is absent: the NBA expected-minutes file holds starter columns only, `#473`.
   - `starter_prob` (preseason last-4 starts) changes only the roll weights (+4%) and the caps (O:570, O:664).
3. **The pool holds DNP-bound players (Q1).** Their 37.7 min/side is taken from the players who did play. The
   outside-pool players (29.6 min/side, mostly priced no-history players) only partly offset it.

The 2025-26 backtest measured the same direction mid-season: sim minutes bias -3.67, MAE 6.64 vs 5.27 for the player's
last-5 (`[nba-model-skill-2025-26]`).

### Reach: which path sets a side's minutes

- **Derive path (traced above):** used when same-phase rotation history is absent or refused. That was **22/22 sides on
  10-21**.
- **Rotation-history path (`_rotation_sim_minutes_from_history_local`, B:2279):** takes over once a team has
  regular-season stints.
  - Already 1 of 4 sides on 10-22 (OKC) and 3 of 8 sides on 10-23 (BOS, NYK, SAS).
  - The lineup-pools lane measured it feeding 34/44 regular-season sides, with the rest refused by its signal guard.
- **So a fix to the derive path reaches** opening week, plus roughly 1 side in 4 after that.
- **The history path has its own leak, not measured here:**
  - Its leftover minutes are the minutes of history players who are not in the pool, such as no-history rookies.
  - Those leftover minutes are spread over every pool player by the same roll-minutes weights (B:2429-2436).
  - The audit tags each side `[history path]` from now on, so that path gets its own reading on the next slates.

## 3. Overlap check (read `origin/main` lanes.md 2026-10-22 ~9:40 AM CT)

- **`nba-lineup-pools` (OPEN, `#696`).** It claims no code, only `todo.md #696`. Its scheduled reading is 10-25 (the
  `call.lineup_pools` input-checklist alarm on the history path). This lane changes nothing on the history path and
  nothing about lineup pools. One fact goes to them: that path is live from a team's second game.
- **Market anchoring.**
  - `nba-sim-anchor-staleness` is CLOSED 10-21. Its hooks are in the run loop's reuse/job-line code, not the derive.
  - `freeze-nba-pregame-sims` CLOSED this morning, `9cab6ac6`.
  - `basketball-scenario-calibration` (OPEN) claims the nba_engine_config loader/apply sites and engine sections. No
    overlap.
- **`nba-no-history-admit` (CLOSED).** Its three hooks sit after the props reads and the props_pool stamp, not in the
  derive. Stand-ins enter the pool as props rows with a posted line, so with both switches on a stand-in counts as
  PRICED. That is the right outcome: the market prices him. The `#714` re-run arms should say which switches each arm
  had.
- **The injury PDF parser** (`nba/source_cli/scrapers/injuries.py`) is claimed by no open lane. It is outside this
  lane's scope and is a proposed follow-up session.

## 4. The build: priced-first shrink, DEFAULT OFF

Code: `_priced_first_fill_local`, `_market_priced_keys_for_team_local` and `_nba_priced_first_minutes_local`, beside
`_water_fill_minutes_local`. There is one call in `_derive_sim_minutes_local`.

- **When it acts.** NBA only, and only when the base sums over 240 and at least 5 pool players have a posted player-prop
  line on the team's game.
- **What it does.** It takes the excess off the UNPRICED players first, with the same equal-subtraction water-fill
  among them (floored at 0). Only once they are all at 0 does it take the rest off the priced players.
- **Inputs.** The priced set comes from the props snapshot that the WNBA pool prune already protects
  (`_load_market_player_names_by_matchup_local`).
- **Date.** The slate date comes from the worker state. In pregame mode the derive receives the as-of date (D-1), which
  would read the wrong snapshot; a test pins this.
- **Switch `SYNDICATE_NBA_SIM_MINUTES_PRICED_FIRST`.**
  - absent / off: byte-identical to today.
  - `shadow`: computes and logs `NBA_SIM_MINUTES_PRICED_FIRST`, and returns off.
  - `on`: returns the priced-first minutes.
- **No fitted constant.** The 5 is the size of a lineup, not a fit.
- **Classification (standard §4.4): an ESTIMATOR change.** It changes how each player's minutes parameter is set from
  data. It does not change what the engine does with minutes. The re-fit question is in §5.

Tests: `tests/test_nba_sim_minutes_allocation.py`, 12 tests.
- The fill arithmetic.
- off = the water-fill, on differs, and shadow = off but logs.
- Fewer than 5 priced, no snapshot, or the as-of date: off. WNBA: untouched.
- **Reachability through the real worker:** `_smart_sim_worker_init_local` + `_smart_sim_worker_run_local` + the real
  orchestrator. The `_sim_min` the engine receives differs off vs on (priced players up, unpriced down, sum 240), and so
  does the published `min_mean`.

Also `tests/test_nba_sim_minutes_audit.py` (4 tests). 169 tests pass across the 12 neighbouring basketball suites.

**Replay check (mechanics only, truth-free dates 10-22 / 10-23):**
- On every derive-path side, the replayed off arm reproduces production's `_sim_min` with max deviation 0.000.
- On engages on 10-22's three derive-path sides (5-7 priced).
- On does not engage on 10-23's derive-path sides: those sims were built D-1, when 0 players were priced. That is the
  intended no-op until the game-day rebuild.

## 5. PRE-REGISTERED -- written 2026-10-22 ~9:45 AM CT, before any ON-arm minutes or points were compared with a box

**Arms.**
- **OFF:** production's own minutes. Each side's `engine_inputs/<D>/<H>_<A>.pkl` frame `_sim_min`, replayed through
  `_derive_sim_minutes_local` with the switch off. A side whose replay deviates from production by more than 0.05 min,
  or whose minutes came from the rotation-history path, is DROPPED and listed.
- **ON:** the same call on the same frozen frame with the switch on. The priced set is rebuilt from the pre-tip props
  history rows whose snapshot is no later than the pkl's `written_at`.
- Tool: `python scripts/nba_sim_minutes_audit.py --replay --processed <fleet processed> --dates <D,...>`.

**Population.** Engaged sides only (ON differs from OFF). Players = pool players who played (box minutes > 0, regular
season).

**PRIMARY (minutes).**
- The statistic: the paired |ON - actual| - |OFF - actual|, its mean, and a 95% CI by cluster bootstrap over sides
  (10,000 resamples, seed 7).
- **PASS:** CI upper < 0. **FAIL:** CI lower > 0. Otherwise **INCONCLUSIVE**.

**Two readings, by slate.**
- **DEVELOPMENT: 10-21.** The design used one 10-21 aggregate: every priced pool player played. It did not use any
  per-player outcome. The 10-21 verdict is reported and labelled development. It does not count toward enabling.
- **CONFIRMATORY: slates after 10-21.**
  - The same rule, pooled across slates until >= 150 played rows on engaged sides.
  - Below 150 the verdict is INCONCLUSIVE (`--min-rows 150`).
  - Each slate is read after its box lands, from production's own frozen inputs. No arm has to be built in advance.

**SECONDARY (points, must not FAIL).**
- Served `pts_mean`, after the calibration, from scratch worker arms built from the same frozen inputs with the switch
  off/on.
- The statistic: paired |ON - actual| - |OFF - actual| over played pool players on engaged sides. FAIL if CI lower > 0.
- **Read on 10-21 (development):**
  - The arms are copies of the `#714` lane's truth-free tree (`/home/amyn/nba_nohist_scratch/A`, fleet data 8:28 PM CT
    10-20), with that day's last pre-tip props snapshot (snapshot < first tip) as the raw props file.
  - The code is this lane's. Settings: `n_sims` 500, workers 2, `PYTHONHASHSEED=0`, seed 20261021. `SYNDICATE_DATA_ROOT`
    is forced to each arm's root.
  - The read is done only after checking that production's `engine_inputs` and `smart_sim` mtimes are unchanged.
  - Points truth = `player_logs.csv` rows with `GAME_DATE` = D.

**Reported, not gating.**
- Starter / bench minutes bias, OFF vs ON.
- DNP sim minutes per engaged side.
- The priced / unpriced split of the paired statistic: unpriced rotation players are where ON can hurt.
- Served pts - line for starters and bench, OFF vs ON, on the scratch arms.

**Mechanism-vs-estimator check (standard §4.4), stated before the reading.**

This is an estimator change to the engine's minutes input. Three downstream pieces were fitted on the compressed
minutes:

1. **`nba_prop_calibration` mean blend.** `b.pts = 0.45`: 55% of the served mean is the player's own average.
   - That blend shrinks toward an unbiased target, so it does not double-count a fix. It only dilutes the gain.
   - Prediction: the served-points change is about 0.45 x rate x the minutes change.
2. **`nba_prop_calibration` width.** `k.pts = 1.25` was fit to residuals that include the minutes error.
   - If ON's residuals are narrower, the served widths are too wide. Probabilities then lean toward 50%: fewer edges,
     never wrong-signed ones.
   - Measured on the scratch arms as IQR(z)/1.349 of served pts for played priced players, OFF vs ON.
   - Before `on` in production, a value below 1.0 under ON means k is re-fit first (`scripts/fit_nba_prop_calibration.py`,
     lane `nba-prop-calibration`).
3. **The props book-blend weight** (`nba_prop_book_blend.json`) was fit while the model was worse.
   - With a better model it under-weights the model. That is conservative, not double counting.
   - Re-fit owed with (2) if ON is enabled.

**Decision.**
- **CONFIRMATORY PASS + SECONDARY not FAIL** -> propose `shadow`, then `on`, to the user, with the re-fit in (2)/(3)
  done first or measured unnecessary. Enabling is the user's decision.
- **CONFIRMATORY FAIL or SECONDARY FAIL** -> NO-GO recorded here, and the switch stays off.
- **INCONCLUSIVE** -> keep reading slates.
- **Before `on`, whatever the verdict:** a reused sim keeps the minutes it was built with. A switch flip, or a newly
  posted line, only reaches a game when something else rebuilds it. The reuse check needs a priced-set stamp first.

## Results

(appended below this line, never above it)

### DEVELOPMENT minutes reading, 10-21 (`--replay`): PASS in development; does not count toward enabling

`[pre-registration 8301efcd committed 9:47:54 AM CT; run 1 written 9:48:26 AM CT (14:48:26Z), run 2 9:50:35 AM CT on a
bridge file byte-identical to 4b12deca, committed 9:55:44]`

**Run 1, on 8301efcd as committed.**
- Primary -0.570 [-1.268, +0.123], n=163 over 16 of 22 sides: INCONCLUSIVE.
- Run 1 exposed a matching bug, not a design change. The priced set was keyed by `_norm_name_key`, which keeps
  periods and apostrophes. So props_predictions' "Jabari Smith Jr." / "Jaime Jaquez Jr." / "De'Anthony Melton" never
  matched the books' "Jabari Smith Jr" / "Jaime Jaquez Jr" / "DeAnthony Melton". MIL logged 4 priced instead of 6 and
  did not engage; HOU logged 5 of 6.
- Fixed in 4b12deca: both sides use the orchestrator's `normalize_player_name_key`, with a regression test. That
  implements the registered design ("players with a posted line"). Both runs are reported.

**Run 2, on the 4b12deca bridge (the code the verdicts are read on).**
- Production frames: 22/22 sides on the derive path; the OFF replay reproduces production `_sim_min` with max deviation
  **0.000** on all 22.
- **17 of 22 sides engage.** The other 5 are CHA, DAL, LAC and SAC (thin pools whose base sums below 240, so there is
  nothing to shrink) and GSW (4 priced).

| (played pool players, engaged sides) | OFF | ON | paired ON - OFF |
|---|---|---|---|
| **PRIMARY** \|err\|, n=173 | MAE 6.877 [6.03, 7.82] | MAE 5.981 [5.27, 6.73] | **-0.895 [-1.552, -0.278] -> PASS (development)** |
| priced, n=110 | | | -1.444 [-2.307, -0.695] |
| unpriced, n=63 | | | +0.062 [-0.871, +1.048] |
| box starters, n=77 | bias -5.53 [-7.73, -3.17] | bias -1.11 [-2.73, +0.56] | -2.557 [-3.629, -1.474] |
| bench, n=96 | bias +1.11 [-0.63, +2.67] | bias +0.07 [-1.35, +1.34] | |
| DNP sim minutes per engaged side | 42.7 | 28.5 | |

Per side (paired mean):
- BKN -4.07, MIN -2.90, WAS -2.33, IND -2.22, LAL -1.56, MIL -1.51, UTA -1.36, PHX -0.71, ORL -0.71, MIA -0.61,
  NOP -0.45, MEM -0.05.
- ATL +0.08, TOR +0.24, CHI +0.42, HOU +1.12, POR +1.21.

**Where ON did nothing.**
- The DNP minutes it cannot remove belong to OUT players with broken names on sides that were all-but-unpriced:
  CHI 75.5 -> 74.0 and POR 51.0 -> 47.7.
- It also does nothing about the starters missing from thin pools (DAL, LAC, SAC: the no-history stand-ins of `#714`).

**Reading.** On the one slate the design was drawn from, the priced-first shrink:
- takes 14 of 43 DNP minutes per side off players who did not play;
- removes ~80% of the starter compression;
- cuts played-player minutes MAE by 0.9;
- leaves unpriced players who played no worse.

This is development evidence only. The CONFIRMATORY reading is owed on slates after 10-21.

### DEVELOPMENT points secondary, 10-21 scratch worker arms: NOT FAIL

`[arms OFF 14:53:18-14:58:38Z, ON 14:58:41-15:03:18Z (9:53-10:03 AM CT); scored 10:03:38 AM CT (15:03:38Z)]`

**Substrate.**
- Both arms are copies of `/home/amyn/nba_minutes_scratch/BASE`: the `#714` lane's truth-free tree (fleet data 8:28 PM CT
  10-20), with the raw props file replaced by 10-21's last pre-tip snapshot (22:33:56Z, 43,526 rows, 155 players; first
  tip 23:00Z).
- Code: the bridge as 4b12deca.
- Run: the real `_smart_sim_run_date_local` under `env -i`, with only `SYNDICATE_DATA_ROOT`=arm,
  `SYNDICATE_NBA_NO_HISTORY_STANDINS=off` and the switch set. `PYTHONHASHSEED=0`, seed 20261021, `n_sims` 500,
  workers 2, overwrite.
- Both arms wrote 11/11, 0 failures. The ON run logged 19 `NBA_SIM_MINUTES_PRICED_FIRST ... engaged=1` lines.
- **Production untouched:** md5 and mtime of the 11 production `smart_sim_2026-10-21_*.json` and 11
  `engine_inputs/2026-10-21/*.pkl` match the pre-run fingerprints.
- Truth: fleet `player_checks_2026-10-21.csv` (minutes) and `player_logs.csv` `GAME_DATE` 10-21 (points).
- Tool: `scripts/nba_sim_minutes_audit.py --arms`.

19 of 22 sides engaged. This tree's pools were built 10-20 evening, so they differ from production's.

| played pool players, engaged sides | value |
|---|---|
| **SECONDARY: paired \|ON-actual\| - \|OFF-actual\|, served pts (n=196)** | **-0.076 [-0.321, +0.140] -> NOT FAIL** |
| the same, priced players (n=124) | +0.023 [-0.330, +0.378] |
| minutes, paired (n=196) | -0.802 [-1.597, -0.053] (agrees with the replay on another vintage) |
| starters' points bias | -2.57 [-3.68, -1.35] -> -0.72 [-1.83, +0.50] |
| starters' served pts - points line (n=88) | -1.94 [-2.45, -1.43] -> **-0.09** [-0.71, +0.47] |
| bench served pts - points line (n=36) | +0.95 [+0.26, +1.67] -> **+2.55** [+1.77, +3.30] |
| served pts width IQR(z)/1.349, priced (n=124) | 1.028 -> 1.020 |

**By group (means; minutes and points bias = sim - actual):**

| group | n | min bias off -> on | min \|err\| off -> on | pts bias off -> on | pts \|err\| off -> on |
|---|---|---|---|---|---|
| priced starters | 88 | -6.01 -> **-1.05** | 6.97 -> **4.44** | -2.57 -> -0.72 | 5.88 -> 5.61 |
| priced bench | 36 | -0.34 -> **+4.71** | 4.63 -> 6.07 | +2.04 -> +3.63 | 4.21 -> 4.97 |
| unpriced bench | 72 | +0.72 -> -3.51 | 7.70 -> 7.88 | +1.62 -> +0.18 | 3.97 -> 3.72 |

**What this says.**
- **The design over-protects PRICED BENCH players.**
  - Their base is last season's roll minutes, and priced-first leaves it whole.
  - Examples: AJ Green 25.1 -> 34.2 sim, 15 actual; Tari Eason 18.5 -> 25.0, 3 actual; Derik Queen 22.7 -> 29.8, 18
    actual; Reed Sheppard 16.7 -> 23.2, 16 actual.
- **The gains and losses cancel in points.**
  - The minutes gain concentrates on priced starters, who move to within 0.1 pt of the market.
  - Priced bench players move 1.6 pts further above it.
  - The served points' 55% own-average blend dilutes both.
- **The registered design stands as registered.** A refinement drawn from this table would be tuned on the evaluation
  slate. For example, protect only priced STARTERS (`starter_prob >= 0.55`), or protect priced players down to a
  role level rather than to their full base. Any such variant is a NEW design: it is pre-registered in its own entry
  and read only on the confirmatory slates, beside this one.

**Mechanism-vs-estimator check (2), as pre-registered.** The served width under ON is 1.020 (OFF 1.028), not below
1.0. So on this slate the k scale is not shown too wide, and no re-fit is triggered by this check (one slate, n=124).
Check (3), the book-blend weight, is owed with any enablement.

**Development verdicts on 10-21.**
- Minutes primary: PASS, -0.895 [-1.552, -0.278].
- Points secondary: NOT FAIL.
- Neither counts toward enabling.
- **The CONFIRMATORY reading is owed:** `--replay --min-rows 150` over slates after 10-21. The first candidates are 10-22's
  DEN, PHI and CLE (derive path, 5-7 priced at build); their box lands ~6:45 AM CT 10-23.
