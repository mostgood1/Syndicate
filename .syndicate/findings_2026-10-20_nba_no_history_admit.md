# NBA SmartSim: admitting priced players with no `player_logs.csv` history (lane `nba-no-history-admit`)

`[2026-10-20, session 15f24a49 (side session of nba-current-rosters); times US Central]`

## The population (10-21 slate, after the nba-current-rosters re-key)

11 current-roster players with a posted pre-tip prop line, absent from the sim because `build_features_for_date_local`
writes a feature row only for a player with a played `player_logs.csv` row (this season, else his most recent prior
season), and the fleet's file holds only 2025-26 (SEASON_ID 22025). Substrate: the sibling lane's scratch ON copy of
the fleet's `nba_source/data` (taken 8:28 PM CT), preseason boxes from the fleet's `rotation_stints/player_checks_*`
(read-only).

| player | team | posted pts / reb / ast (median over books) | preseason min (starts) | minutes prior |
|---|---|---|---|---|
| Kyrie Irving | DAL | 20.5 / 3.5 / 4.5 | 22, 25 (2/2) | 30.7 |
| Fred VanVleet | HOU | 13.5 / 3.5 / 5.5 | 24, 29 (2/2) | 32.5 |
| Keaton Wagler | LAC | 13.5 / 3.5 / 3.5 | 30, 23, 28 (1/3) | 22.6 |
| Darius Acuff Jr. | SAC | 18.5 / 2.5 / 4.5 | 27, 23, 27, 19 (4/4) | 31.0 |
| Yaxel Lendeborg | GSW | 14.5 / 7.5 / 2.5 | 19, 21, 24, 26, 26 (5/5) | 30.6 |
| Cameron Boozer | MEM | 17.0 / 7.5 / 3.5 | 18, 22, 12, 29 (4/4) | 28.8 |
| Darryn Peterson | UTA | 13.5 / 4.5 / 2.5 | 19, 30, 24, 29 (4/4) | 31.9 |
| Tyrese Haliburton | IND | 18.5 / 3.5 / 8.5 | 16, 18, 20 (3/3) | 27.6 |
| Damian Lillard | POR | 18.5 / 3.5 / 4.5 | 19, 23, 26 (3/3) | 30.2 |
| Caleb Wilson | CHI | 16.5 / 6.5 / 2.5 | 29, 32, 25, 24, 23 (5/5) | 32.5 |
| AJ Dybantsa | WAS | 13.5 / 5.5 / 1.5 | 23, 23, 25, 15 (4/4) | 29.6 (injury-excluded) |

## Veterans via a 2024-25 append (scope 2) -- the existing fallbacks WOULD admit them, and must not be used to

2024-25 regular season fetched from stats.nba (`nba_player_logs_fetch._fetch_season_player_logs("2024-25")`) into a
scratch file, never the data root: 26,306 rows, SEASON_ID 22024, 2024-10-22..2025-04-13, same columns as the fleet file.

| player | 2024-25 games / min / pts | posted pts line 10-21 | 2024-25 pts - line |
|---|---|---|---|
| Damian Lillard (MIL then; Achilles 2025) | 58 / 36.1 / 24.9 | 18.5 | **+6.4** |
| Kyrie Irving (ACL 2025) | 50 / 36.0 / 24.7 | 20.5 | **+4.2** |
| Tyrese Haliburton (Achilles 2025) | 73 / 33.6 / 18.6 | 18.5 | +0.1 |
| Fred VanVleet (ACL 2025) | 60 / 35.2 / 14.1 | 13.5 | +0.6 |

Mechanically the append works: `build_features_for_date_local` falls back to the max prior season with played rows,
which is 2024 for these four and stays 2025 for everyone with 2025-26 rows. But the admitted rows carry the
**pre-injury** player: Lillard and Irving would be simulated ~6 minutes and 4-6 points above the market, and because
they would be ordinary history players their OWN props would be priced -- spurious OVERs, on a venue that places live
orders. The market has information the history does not (age, the injury, a minutes restriction).

Every `player_logs.csv` reader was enumerated before deciding (subagent survey, the two load-bearing claims re-read):

- **CHANGED for players who are not the four:** `basketball_props_features` is called with `players=None`, so the
  append creates a feature row for EVERY 2024-25-only player (retired, overseas), tagged with his 2024-25 team and
  ~550 days rest -- the current-roster re-key drops them only while it is on (with `SYNDICATE_NBA_CURRENT_ROSTERS=0`
  they enter the pool). `_player_career_opponent_rate_context_local` uses a **720-day** window with no season filter
  (`basketball_props_smart_sim.py` ~:2877), so every player's career-vs-opponent multiplier changes. ONNX priors gain
  (2024-25 team, player) keys. `nba_team_inputs` team ratings and `nba_prop_calibration.prior_rates` change in
  2025-26 REPLAYS (the prior season now exists there). `nba/source_cli/features_enhanced` may start writing
  `team_advanced_stats_2025.csv` (unsure).
- **Does NOT help the four where it matters:** `nba_prop_calibration.prior_rates` reads only the season immediately
  before the slate (2025-26), so they get nothing there.
- **Mechanics:** `nba_history_refresh` MERGES (keeps every row whose `SEASON` differs from the one it fetches), so an
  append survives if it carries `SEASON="2024-25"` and `SEASON_ID`; but `player_logs.parquet`, when present, is read
  FIRST by the props features (so a CSV-only append is invisible until the next refresh write), and
  `_PLAYER_LOGS_CACHE` / the orchestrator's `lru_cache` hold the old frame until a restart.

**Verdict on scope 2: NO-GO for the append.** It admits the four with stale, biased rates, prices their own props,
and changes other players' inputs. The four are admitted the same way as the rookies instead (below). Nothing was
written to production.

## The mechanism (built default-off): a market-implied stand-in

`syndicate/features/shared/nba_no_history_standins.py`, switch `SYNDICATE_NBA_NO_HISTORY_STANDINS` = `off` (default,
absent = off) | `shadow` (log who would be admitted, change nothing) | `on`.

- WHO: on the ESPN current roster for the date, a posted pre-tip `player_*` line in this game, not already in the pool,
  >= 2 preseason appearances this season.
- MINUTES: 2.012 + 0.577 x preseason mean minutes + 15.148 x preseason start share, clamped [10, 36]. Fitted on
  2025-26 `player_checks` (394 players with >= 2 preseason games; target = mean minutes over the games played among the
  team's first 5 regular-season games): in-sample MAE **5.26** vs 7.40 for "regular = preseason" (bias -1.13) and
  6.92 without the start share. (Counting a DNP as 0, the same form gives 5.73; the stand-in population is priced
  players, i.e. expected to play.)
- RATES: the posted line / minutes for each stat with a line; league per-minute rate otherwise.
- **The stand-in is hidden from every pricer by construction.** A subagent survey of every consumer of the sim's
  per-player output found SEVEN paths that would price a stand-in's own props, pregame and live, two of them into the
  order plan: `_merge_smart_sim_into_preds` APPENDS any sim player with no props_predictions row;
  `cards_sim_detail_<D>.json` copies every sim player row and `nba_projections.load_nba_prop_projections` joins board
  prop rows to it (the pregame order path); `basketball_market_board`, `prop_evidence`, the live player lens; and the
  live re-sim (`live_resim.resim_live_game` collects every pool player, `build_live_props` prices every one with a
  posted line). Layer 2's market-EV-only path can seat a row even with no model view. So the sim keeps the stand-in
  IN the simulation and takes his row OUT of `players[]` before the JSON is written (`tag_sim_output`), recording
  minutes and means in `context.no_history_standins`. That closes every pregame reader at one point. The live re-sim
  needs its own filter (engine inputs are persisted before the strip) -- see "Live" below.

## PRE-REGISTERED -- written 2026-10-20 ~9:40 PM CT, before any result of the scratch run below was read

### Scratch cost measurement (H3)

Substrate: three copies of the sibling lane's scratch ON tree (fleet data 8:28 PM CT + ESPN current rosters), code =
`origin/claude/nba-current-rosters` + this lane's module and hooks, the refresh-worker's NBA/props env keys by name,
`_smart_sim_run_date_local` for 2026-10-21 (n_sims 500, workers 2, overwrite, PYTHONHASHSEED=0). Arms: **B** = `on`,
seed 20261021; **A** = `off`, seed 20261021; **A2** = `off`, seed 777 (noise floor). Affected games: HOU_DAL, LAC_SAC,
LAL_GSW, MEM_UTA, NOP_IND, POR_PHX, TOR_CHI, WAS_MIL (11 sides).

Predictions:
- P1 reachability: B logs `NBA_NO_HISTORY_STANDINS` admitting 11; B's sims carry 10 in `context.no_history_standins`
  (Dybantsa injury-excluded) and none of them in `players[]`; A logs nothing and its sims carry no such key.
- P2 conservation: on each side with a stand-in, sum of teammates' `min_mean` (B - A) = -(stand-in's B `min_mean`)
  within 2 min.
- P3 the stand-in's B `min_mean` is within 4 min of his minutes prior.
- P4 sum of teammates' `pts_mean` (B - A) is negative on every side with a stand-in, and its size is 0.6-1.0 x the
  stand-in's B `pts_mean`.
- P5 DAL: P.J. Washington `min_mean` falls from ~39 to <= 35.
- Reported, not predicted: the A-vs-A2 per-player |d min| and |d pts| distribution (the noise floor), and the number of
  teammates' posted main lines (pts/reb/ast/threes) whose sim P(over) moves by >= 3 pp B vs A, against the same count
  A vs A2.

### The go / no-go rule for enabling `on` (evaluated on TRUTH, after the 10-21 games are final)

Truth = the 10-21 regular-season box minutes and points (fleet `rotation_stints/player_checks_2026-10-21.csv`, ESPN box,
P2 producer). Arms = A and B above (inputs frozen 8:28 PM CT 10-20, run before any 10-21 game).
Population = teammates: players on a side with a stand-in, present in both arms' `players[]`, actual minutes > 0.

- **PRIMARY:** paired difference of absolute minutes error, |B - actual| - |A - actual|, mean over the population,
  95% CI by cluster bootstrap over sides (10,000 resamples). **PASS** if the mean < 0 and the CI upper bound < 0.
  **FAIL** if the CI lower bound > 0. Otherwise INCONCLUSIVE.
- **MUST NOT FAIL (secondary):** the same paired statistic for teammates' points; FAIL if its CI lower bound > 0.
- **MINUTES PRIOR SANITY:** mean |minutes prior - actual| over stand-ins who played <= 8.0 min (fit MAE 5.26); above
  that the prior is broken and the verdict is NO-GO regardless.
- **Decision:** PASS + secondary not FAIL + sanity -> propose `on` to the user (production change, needs explicit
  approval). FAIL or sanity breach -> NO-GO recorded here, module stays off. INCONCLUSIVE -> `shadow` in production
  if the user approves, and the rule is re-run on the next slates with a NEW pair of arms per slate until >= 250
  teammate rows.
- **Whatever the verdict, a stand-in's OWN props are never priced** -- the module hides them; enabling `on` does not
  change that.

## Results

(pending -- appended below this line, never above it)

### Scratch cost measurement -- read 2026-10-20 ~10:15 PM CT (arms B 9:39-9:53, A 9:53-10:03, A2 10:03-10:12 PM CT)

All three arms wrote 11/11 sims, 0 failures. Production's 10-21 sims and engine inputs untouched (the arms' roots were
forced to `/home/amyn/nba_nohist_scratch/<arm>`; production's 11 `engine_inputs/2026-10-21/*.pkl` and 11
`smart_sim_2026-10-21_*.json` were last written 1:48-1:50 PM CT 10-20, none since the run began).

**Noise floor (A vs A2, different seed, same pool):** teammates' `min_mean` moved by exactly 0.00 (median and p90 --
the minutes layer is deterministic), `pts_mean` by a median 0.04 (p90 0.12); 11 of 158 priced main lines moved >= 3 pp.
WAS_MIL (Dybantsa injury-excluded, so B's pool == A's pool) is identical to the last digit between A and B. Every
on-vs-off difference below is the stand-in's.

| side | stand-in (B: sim min / pts) | minutes prior | teammates | sum teammates d min | sum teammates d pts | d pts / stand-in pts |
|---|---|---|---|---|---|---|
| HOU | Fred VanVleet 24.3 / 15.9 | 32.5 | 14 | -24.3 | -8.3 | 0.52 |
| DAL | Kyrie Irving 32.7 / 23.5 | 30.7 | 9 | -32.7 | -12.1 | 0.51 |
| LAC | Keaton Wagler 19.8 / 13.7 | 22.6 | 12 | -19.8 | -7.0 | 0.51 |
| SAC | Darius Acuff Jr. 27.7 / 18.6 | 31.0 | 10 | -27.7 | -9.7 | 0.52 |
| GSW | Yaxel Lendeborg 28.1 / 18.8 | 30.6 | 11 | -28.1 | -10.3 | 0.55 |
| MEM | Cameron Boozer 20.7 / 13.6 | 28.8 | 14 | -20.7 | -8.1 | 0.60 |
| UTA | Darryn Peterson 26.2 / 14.0 | 31.9 | 14 | -26.2 | -9.7 | 0.69 |
| IND | Tyrese Haliburton 19.7 / 15.5 | 27.6 | 13 | -19.6 | -7.7 | 0.50 |
| POR | Damian Lillard 24.3 / 15.8 | 30.2 | 14 | -24.4 | -10.0 | 0.63 |
| CHI | Caleb Wilson 25.6 / 15.1 | 32.5 | 13 | -25.6 | -9.1 | 0.60 |

Per teammate (137 rows): |d min| median **1.74** (p90 2.77), |d pts| median **0.65** (p90 1.09). DAL's thin pool is the
largest: P.J. Washington 39.1 -> 33.6 min (17.4 -> 15.3 pts), Cooper Flagg 34.2 -> 29.4 (21.4 -> 19.0), Moussa Cisse
32.0 -> 27.5, Max Christie 31.1 -> 26.8. Elsewhere the minutes come off EVERY teammate about equally (HOU: -1.7 each,
the 2.6-minute end of the bench to 0.8), not from the stand-in's position group -- the sim's minutes layer has no
position competition.

**Priced rows moved:** teammates' posted main lines (pts/reb/ast/threes, median over books, pre-tip): **91 of 158
(58%)** move their sim P(over) by >= 3 pp, against 11 of 158 under the noise arm.

**Game lines barely move** (the market anchor holds team totals): |d total| <= 2.3 (POR_PHX 231.0 -> 233.3), d
p_home_win at most 0.062 (LAC_SAC 0.634 -> 0.572).

**The player layer already over-sums the anchored team score**, and the stand-in returns the affected teams to the
league's normal state. Sum of player `pts_mean` minus the team's score mean: unaffected sides (12) **+8.5** on
average; affected sides without stand-ins (A) **+3.0** (DAL -7.1, LAC -6.2, SAC -4.0: the missing player's points
were nowhere); with stand-ins (B) **+10.2**. That is why teammates give back only ~0.5-0.7 of the stand-in's points:
the player layer is not constrained to the team score in any sim. The NBA prop calibration (book blend, own-rate
shrink) was fitted on sims of complete pools, so B is the population it was fitted on -- this is the opposite of a new
mechanism the calibration had been absorbing (standard: "mechanism vs estimator").

**Reachability / coverage:** `nba_sim_roster_audit.py` (sibling's tool, reads `players[]`) reports priced-missing 13
in both arms -- as it must, the stand-ins are hidden. Of B's 13, **10 are simulated stand-ins** recorded in
`context.no_history_standins`; the **3 left are all injury exclusions** (Podziemski GSW and Nesmith IND with history,
Dybantsa WAS without). (The lane block's "<= 2" forgot Dybantsa is also injury-excluded.) Engine inputs: B's persisted
`engine_inputs/2026-10-21/*.pkl` carry the stand-ins with `pool_source`, so the live re-sim plays them and
`resim_live_game` hides them (unit-tested).

### Pre-registered predictions, scored

- **P1 reachability -- MET.** B: `NBA_NO_HISTORY_STANDINS` admitted 11 in the parent and both workers (same list);
  8 sims (10 sides) carry them in `context.no_history_standins`, none in `players[]`. A and A2: 0 lines, 0 sims
  with the key.
- **P2 conservation -- MET** (within 0.1 min on every side).
- **P3 stand-in sim minutes within 4 of his prior -- FAILED** (4 of 10: Kyrie +2.0, Wagler -2.8, Acuff -3.3,
  Lendeborg -2.5; misses VanVleet -8.2, Boozer -8.1, Haliburton -7.9, Wilson -6.9, Lillard -5.9, Peterson -5.7; mean
  -4.9). Not a stand-in defect: the sim compresses EVERY high-minute player in a deep pool (A, HOU: Amen Thompson
  roll10 39.0 -> 32.6 simulated, Jabari Smith 35.9 -> 29.1); the misses are exactly the 13-15 player pools. The prior is
  an input like every player's roll minutes and is compressed the same way.
- **P4 teammates' points 0.6-1.0 x the stand-in's -- FAILED** (0.50-0.69; 5 of 10 inside). Cause above: the player
  layer is not tied to the team score.
- **P5 P.J. Washington <= 35 -- MET** (39.1 -> 33.6).

### Reuse path (the standard's "publishing is not sufficient")

Arm C = a copy of A's finished tree (stand-ins OFF sims on disk), re-run with stand-ins ON and overwrite OFF, so the
REAL reuse branch decides (10:15-10:20 PM CT). It rebuilt exactly the games whose pool changed and reused the rest:
`SMART_SIM_REUSE_STALE_POOL ... drift=DAL:+1/-0;HOU:+1/-0 reuse=False` for HOU_DAL, LAC_SAC, LAL_GSW, MEM_UTA, NOP_IND,
POR_PHX, TOR_CHI and WAS_MIL; `reuse=True` for BKN_CHA, MIA_MIN, ORL_ATL (md5 unchanged); `wrote 8, skipped 3, 0
failures`. So switching `on` needs no forced re-sim -- the sibling lane's pool stamp already invalidates. WAS_MIL
rebuilds although Dybantsa is then injury-excluded (the stamp is taken before the injury map): one wasted re-sim, no
output change. Switching back `off` invalidates the same way (the pool shrinks).

### Truth reading -- analysis choices fixed BEFORE any 10-21 truth exists

`[written 2026-10-21 8:23 AM CT (13:23Z), session 89514daa (side session of 23b33819); no 10-21 game has tipped, the
fleet has no player_checks_2026-10-21.csv and no player_logs.csv 10-21 row]`. The rule above is unchanged; these fix
how the committed tool's output is read where it and the rule's text could differ.

1. **Sides = sides where B SIMULATED a stand-in** (a non-empty `context.no_history_standins[team]`): 10 sides. B's
   WAS_MIL carries `"WAS": []` (Dybantsa admitted, then injury-excluded; B == A to the last digit), and the tool keys
   on the team being present, so as committed it would add WAS's teammates as exact zeros, an 11th cluster. WAS is not
   "a side with a stand-in"; the verdict uses 10 sides. The tool's 11-cluster numbers are printed beside it, and if the
   two give different verdicts that is said.
2. **Sanity population = the 10 simulated stand-ins who played.** Their `minutes_prior` is recomputed from B's frozen
   inputs (the sims predate that context field); checked just before this note that the recomputation equals the table above for
   all 11. Dybantsa's prior error is reported separately if he plays; it does not enter the 8.0 bound.
3. **Truth join:** box minutes by (team, `name_key`) from `player_checks_2026-10-21.csv` `season_type=regular`; points
   by `name_key` from `player_logs.csv` `GAME_DATE` 2026-10-21. Checked on the 10-20 slate: the box file holds only
   players who played (68 rows = 68 player_logs rows), every matched player who played has a points row, team codes are
   the sim's tricodes (GSW/UTA/NOP/WAS). Before the verdict, every A-and-B teammate with no box row is listed against
   his team's unmatched box rows: a DNP stays out; a name-key miss on the same player is reported, with the statistic
   given both with and without him.
4. If the box minutes exist and the points rows do not, the minutes verdict is recorded and the points half is owed.
5. Instrument: `/home/amyn/nba_nohist_scratch/code_test/scripts/nba_standin_cost.py`, identical to main's
   `scripts/nba_standin_cost.py` modulo CRLF (checked 8:20 AM CT, WSL clock); bootstrap seed 7, 10,000 resamples, as committed.

### Truth reading -- MINUTES: INCONCLUSIVE; points OWED (read 2026-10-22 6:56 AM CT)

`[session 89514daa; tool run 6:56:11-6:56:14 AM CT 10-22 on the frozen arms, read-only on the fleet data root]`

**Truth used.** Fleet `rotation_stints/player_checks_2026-10-21.csv`, written 6:45:07 AM CT 10-22: 254 rows, all
`season_type=regular`, 11 events, 22 teams (every game on the slate). `player_logs.csv` holds **0 rows for 10-21**: it
was last written 6:49 PM CT 10-21, the refresh attempt before the first tip (marker `attempted_at` 23:49Z; 6 h
throttle, it runs inside the props refresh). **So the points half is owed.** It is read when those rows land.

**PRIMARY: paired |B - actual| - |A - actual| minutes, over 97 teammates who played on the 10 sides with a simulated
stand-in, cluster bootstrap by side (10,000 resamples, seed 7): mean +0.080, 95% CI [-0.455, +0.601] -> INCONCLUSIVE.**
Neither bound is on the PASS side (upper < 0) or the FAIL side (lower > 0). Teammates' minutes MAE: A 6.32, B 6.40.
The tool as committed counts WAS's all-zero cluster (11 clusters, n=107): +0.072 [-0.417, +0.554] -> INCONCLUSIVE.
That is the same verdict, so choice 1 above did not decide anything.

**SECONDARY (points): not readable.** 0 truth rows (above). Owed.

**SANITY: minutes-prior MAE over the 10 simulated stand-ins who played = 3.93 (bound 8.0) -> OK.**

| stand-in | team | minutes prior | B sim min | actual min |
|---|---|---|---|---|
| Kyrie Irving | DAL | 30.7 | 32.7 | 24 |
| Fred VanVleet | HOU | 32.5 | 24.3 | 30 |
| Keaton Wagler | LAC | 22.6 | 19.8 | 29 |
| Darius Acuff Jr. | SAC | 31.0 | 27.7 | 35 |
| Yaxel Lendeborg | GSW | 30.6 | 28.1 | 29 |
| Cameron Boozer | MEM | 28.8 | 20.7 | 33 |
| Darryn Peterson | UTA | 31.9 | 26.2 | 31 |
| Tyrese Haliburton | IND | 27.6 | 19.7 | 34 |
| Damian Lillard | POR | 30.2 | 24.3 | 24 |
| Caleb Wilson | CHI | 32.5 | 25.6 | 32 |
| AJ Dybantsa | WAS | 29.6 | injury-excluded | not in the box (did not play) |

All 10 simulated stand-ins played, a mean of 30.1 min. Their minutes were predicted three ways:

- The prior: MAE 3.93, inside the fit's 5.26.
- The B sim's own minutes: MAE 6.99, mean -5.2. That is P3's compression.
- Arm A, which leaves them out entirely: error 30.1.

None of this enters the rule, because a stand-in's own props are never priced.

**Join check (choice 3): 0 name-key misses.**

- 27 A-and-B teammates on the 10 sides have no box row. All are DNPs or inactive (e.g. Steven Adams, Brandon Ingram,
  Malik Monk, Nic Claxton, Patrick Williams).
- The box rows on those sides that match nobody are 11 different players, outside BOTH arms' pools, 117 min in total.
  GSW: Georges Niang 20, Graham Ike 12. CHI: Jaylin Sellers 14, Tobe Awaka 14. SAC: Emanuel Sharp 17, Alex Karaban 5.
  DAL: Morez Johnson 14, Sergio de Larrea 7. LAC: Baba Miller 9, Nick Martinelli 2. HOU: Bruce Thornton 3.
- These are the unpriced no-history players this lane left out of scope. Niang is one of H2's four unplanned admits.

**Engine read -- why a correct stand-in leaves teammates no better.**

- **The stand-in's minutes come off the pool pro rata, so mostly off the teammates who played.** Teammates' signed
  minutes bias (sim - actual) goes from -0.36 in A to -2.43 in B.
  - Starters (actual >= 28, n=24): -5.57 -> -7.91. Paired +1.29, worse.
  - Everyone else (n=73): +1.35 -> -0.63. Paired -0.32, better.
- **The pool gives minutes to players who did not play.** In A, pool players who then did not play hold 13.8 to 89.2
  sim minutes per side (MEM 89.2, IND 72.6, CHI 63.2, LAC 53.7). Adding a stand-in takes back only about 5 of those
  per side.
- **Where B hurt:** sides where A already UNDER-predicted the played teammates. MEM +1.43, HOU +0.97, LAC +0.75.
- **Where B helped:** sides where the pool missed real players and A OVER-predicted the played teammates. DAL -1.32
  (A +3.53), GSW -1.29 (A +4.30).
- **The binding constraint is the minutes layer, not the stand-in.** That layer has no position or starter structure:
  it spreads minutes onto bench players who DNP and squeezes starters by ~5.6 min. Another slate on the same engine
  should be expected to stay near zero. That is a forecast, not a measurement.

**Decision per the rule:** INCONCLUSIVE.

- `shadow` in production is allowed only if the user approves. It changes nothing: it logs who would be admitted. The
  fleet checkout (09e86a9d) contains 73082de2, and the switch key is absent on the refresh-worker (pid 3658328, started
  1:21 AM CT 10-22), so the switch is OFF.
- The rule is then re-run with a NEW pair of arms per slate (off/on, built before tip, frozen inputs) until >= 250
  teammate rows. This slate gave 97.
- `on` is NOT supported by this reading.
- The points secondary for this slate is owed. It cannot turn INCONCLUSIVE into a PASS; it can only flag a FAIL.

### Truth reading -- POINTS (secondary): NOT FAIL (read 2026-10-22 7:49 AM CT); overall verdict unchanged, INCONCLUSIVE

`[session 89514daa; tool re-run 7:49:14-7:49:18 AM CT on the same frozen arms]` The fleet `player_logs.csv` gained 254
rows for 10-21 at 7:40:05 AM CT (refresh marker 12:40Z). That equals the box's 254. All 97 population rows have a
points row. The box file is unchanged (6:45:07, 22,720 bytes), and the minutes numbers re-read identical.

**SECONDARY: paired |B - actual| - |A - actual| points, same 97 teammates / 10 sides: mean -0.127, 95% CI [-0.256,
-0.009] -> NOT FAIL.** The CI's lower bound is not > 0. The interval sits on the PASS side, though the secondary only
has to avoid FAIL. Teammates' points MAE: A 4.98, B 4.85. The tool as committed (11 clusters, n=107) gives
-0.115 [-0.237, -0.006].

How solid it is (reported, not part of the rule):

- **Above the noise floor.** The noise arm under the same statistic (|A2 - actual| - |A - actual|, A2 = off with
  another seed) is +0.012 [-0.004, +0.028]. -0.127 is about 10x that.
- **Fragile at the edge.** Leave one side out: the mean stays negative in all 10 drops (-0.088 to -0.154). The upper
  bound crosses 0 when DAL, SAC, UTA, POR or CHI is dropped (5 of 10).
- **Signed points bias (sim - actual) goes from +0.76 in A to -0.03 in B.**
  - B helps where A over-predicted the played teammates: DAL -0.50, UTA -0.46, SAC -0.23, CHI -0.20, POR -0.18,
    GSW -0.06.
  - B is neutral to slightly worse where A under-predicted: HOU +0.09, IND +0.08, MEM +0.07, LAC +0.06.
  - Same shape as minutes. Points improve and minutes do not because the stand-in takes usage, not only minutes.

**Stand-ins' actual points** (their own props are never priced; for the record, B sim / actual): Irving 23.5 / 15;
VanVleet 15.9 / 6; Wagler 13.7 / 15; Acuff 18.6 / 12; Lendeborg 18.8 / 12; Boozer 13.6 / 7; Peterson 14.0 / 9;
Haliburton 15.5 / 23; Lillard 15.8 / 25; Wilson 15.1 / 16.

**Decision per the rule, now complete for this slate.** PRIMARY INCONCLUSIVE, secondary not FAIL, sanity OK ->
INCONCLUSIVE.

- `on` is not supported.
- `shadow` in production is allowed only if the user approves.
- The rule is re-run with new off/on arm pairs per slate until >= 250 teammate rows. This slate gave 97.
- The points signal is the reason to keep collecting rather than record a NO-GO.

## Pipeline trace (code = `origin/claude/nba-current-rosters` + this lane's hooks)

```
refresh-worker -> scripts/refresh_odds_sources.py -> scripts/refresh_nba_oddsapi_props.py (export_props_predictions_local)
  -> basketball_props_smart_sim.export_props_predictions_with_smart_sim_local
       writes processed/props_predictions_<D>.csv            (unchanged: a stand-in never gets a row here)
    -> _smart_sim_run_date_local
         props_df = read props_predictions_<D>.csv
         [HOOK 1] nba_no_history_standins.add_standins        reads rosters_<season>.csv (current_roster_index),
                                                              oddsapi_player_props_<D>.csv, rotation_stints/player_checks_*,
                                                              player_logs.csv (league per-minute rates only)
                                                              logs NBA_NO_HISTORY_STANDINS {admitted, skipped, detail}
         injury map / recency exclusions / reuse pool check (props_pool_verdict) all see the stand-in row
      -> worker: _smart_sim_worker_init_local re-reads props_predictions_<D>.csv
         [HOOK 2] add_standins again (same files, same rows)
      -> _smart_sim_worker_run_local -> orchestrator simulate_smart_game (_team_players_from_props -> pool)
           -> _persist_engine_inputs_once_local: engine_inputs/<D>/<HOME>_<AWAY>.pkl (pool frames WITH pool_source)
         [HOOK 3] after the props_pool stamp: nba_no_history_standins.tag_sim_output -- removes the stand-in from
                  players[], writes context.no_history_standins {team: [{player_name, minutes_prior, min/pts/reb/ast/threes
                  means}]}
       writes processed/smart_sim_<D>_<HOME>_<AWAY>.json
live: nba live tick -> live_resim.load_engine_inputs -> resim_live_game
         [FILTER] _hide_standin_remainders drops pool_source == SOURCE players from player_remainders
                  (out["no_history_standins_hidden"]) -> build_live_props never sees him
```

Inputs, all disk-backed under `SYNDICATE_DATA_ROOT` and allowlisted: `rotation_stints/*.csv` and
`oddsapi_player_props_*.csv` (HOT_ARTIFACT_PATTERNS), `rosters_*.csv` (EXPORT_ONLY, sibling lane). No engine
dataclass field is added -- the stand-in populates columns every pool row already has -- so the basketball input
checklists have nothing new to gate; the switch is an env flag.

## H1 / H2, measured (scratch, 10:35 PM CT)

**H1 CONFIRMED:** none of the 11 has a `props_predictions_2026-10-21.csv` row (322 rows) or a `player_logs.csv` row in
the ON copy.

**H2 (2024-25 append), run for real** -- `H2/` = arm A's processed tree with `player_logs.csv` replaced by 2025-26 +
the fetched 2024-25 (52,957 rows, same columns, no parquet present), worktree-branch code:

- The existing fallback DOES admit all four: feature rows 435 -> 443. Lillard (POR, re-keyed from MIL) roll10 34.5 min
  / 23.0 pts; Irving 36.0 / 25.4; Haliburton 31.2 / 19.8; VanVleet 35.5 / 13.9 -- against posted lines 18.5 / 20.5 /
  18.5 / 13.5 -- with `days_rest` 556-597 and `season_game_number` 51-74 (far outside anything the props model saw).
- It also admits **4 more** current-roster players who missed 2025-26: Ben Simmons, Georges Niang, Reece Beekman,
  Trey Lyles.
- No other player's feature row changed (435 / 435 identical, every numeric column). ONNX priors: 661 -> 989 keys
  (+328 (2024-25 team, player) keys), 0 shared keys changed.
- Not exercised here, by code: the 720-day career-vs-opponent split changes every player who played 2024-25 from the
  first 2026-27 game on (it needs split rows, which no one has on opening night).

So H2's first clause holds and its "nothing else changes" clause holds for features and priors but not for the sim's
career split or the admitted population. The verdict above stands: the append admits the veterans with their
pre-injury selves, and their own props would be priced from that.

## The build (default-off)

| file | what |
|---|---|
| `syndicate/features/shared/nba_no_history_standins.py` (NEW) | `mode()` off/shadow/on; `posted_lines`, `preseason_minutes` (this season's files only), `league_rates_pm`, `minutes_prior`, `build_standins`, `standin_rows`, `add_standins` (never raises: any failure returns the pool as given), `tag_sim_output` (hide + record), `is_standin` |
| `syndicate/features/shared/basketball_props_smart_sim.py` | 3 hook insertions, no other line: `_smart_sim_run_date_local` after the props read; `_smart_sim_worker_init_local` after its props read; the worker after the `context.props_pool` stamp |
| `syndicate/features/nba/live_resim.py` | `resim_live_game` hides `pool_source == SOURCE` players from `player_remainders` (`_hide_standin_remainders`); a pool without the column is untouched |
| `scripts/nba_standin_cost.py` (NEW) | arm comparison (cost, priced lines moved, noise floor) and the pre-registered truth reading (`--truth`) |
| `tests/test_nba_no_history_standins.py` (NEW) | 14 tests: switch states, the fitted prior, line pooling (latest pre-tip Over per book, median; post-tip / alternate / Under ignored), who is admitted and why not, off == pool untouched / shadow == logged only / on == appended row consistent with its minutes, NBA-only + never raises, no current roster -> nobody, output hiding + record, an empty sim untouched, **the real sim-worker hook off != on**, **the live re-sim off != on** (hidden remainders, same game), **no live prop row for a stand-in** |

Verified on `origin/claude/nba-current-rosters` + these files (the module imports `nba_current_rosters`, which is not on
main until that lane lands): the 14 new tests plus `tests/test_nba_live_resim.py` and
`tests/test_nba_live_prop_coverage.py` unchanged -- 58 passed.

## What is owed, and the decision

- **LANDED on main 2026-10-21 ~7:45 AM CT** (6487034f module/live filter/tool/tests, 085561bc parent-row reuse, 0cdbadf4 co-claim, 73082de2 the 3 hooks; tip 73082de2), after `nba-current-rosters` (d9b1f5ae, 085fe1e8) was on main AND on the fleet (fleet ff to 085fe1e8 seen 7:43 AM CT), per the user's "push once the fleet ff lands". NOT on the fleet: it ships with the next fleet ff past 73082de2, inert while the switch is absent. Pre-land test run (exact copy of the landing tree, fleet python): 131 passed, 1 skipped, 1 failed -- `test_nba_live_resim.py::test_league_keyword_threads_through_storage_and_names`, PRE-EXISTING (fails the same with main's live_resim.py and without this lane's tests, passes alone; todo #713's open ci-suite failure).
- (was) Land after `nba-current-rosters` is on main (its two commits), then sync and land these files. Pushing `.py`
  changes nothing on the fleet until a fleet ff; with the switch absent the code is inert (unit-tested), and the live
  filter is a no-op for every pool built without stand-ins.
- **The truth reading** (pre-registered rule above) after the 10-21 games are final and the fleet's
  `rotation_stints/player_checks_2026-10-21.csv` (minutes) and `player_logs.csv` 10-21 rows (points) exist:

      cd /home/amyn/nba_nohist_scratch && python code_test/scripts/nba_standin_cost.py --date 2026-10-21 \
          --off A/nba_source/data/processed --on B/nba_source/data/processed \
          --noise A2/nba_source/data/processed --truth /home/amyn/syndicate-prod/data/nba_source/data/processed

  Arms A, A2, B are frozen in `/home/amyn/nba_nohist_scratch` (inputs 8:28 PM CT 10-20, run 9:39-10:12 PM CT); keep
  them until the reading. The tool is read-only on `--truth`.
- **Enabling** `shadow` or `on` in production is an env change [CORRECTED 2026-10-22: the pregame sims are built by
  the LIVE-ODDS-WORKER (the NBA props refresh runs under it), so the key must be unprefixed or LIVE_ODDS_WORKER__; the
  original text said refresh-worker and the first staging was inert -- deploys.md 2026-10-22 20:03:53Z] (it builds the pregame
  sims; the live filter keys on the persisted `pool_source` column, not on the switch) -- the user's decision, after
  the reading. Until then: OFF everywhere.
- **Not done here, by scope:** unpriced no-history players (DAL's other rookies) -- no line, so no market-implied
  rate; WNBA has the same defect class for 2027 (no WNBA roster producer, sibling lane's note).

### USER DECISION 2026-10-21 ~5:00 PM CT (typed in session 15f24a49), recorded before the truth reading ran

"if it's inconclusive, go ahead with shadow mode". So, applied to the pre-registered rule:
- **INCONCLUSIVE:** set `REFRESH_WORKER__SYNDICATE_NBA_NO_HISTORY_STANDINS=shadow` on the fleet. Env changes take
  effect only at a full down/up, so this needs all three deploy claims and a `deploys.md` entry.
- **PASS:** the numbers go to the user for an `on` decision. Nothing is enabled without it.
- **FAIL:** NO-GO; the switch stays absent (OFF).

Fleet state when recorded: the fleet runs ac248f07, which contains 73082de2 (this lane's code), and the switch is absent
from `local_production.env`. So the hooks are live and OFF.

USER DECISION, second part, 2026-10-21 ~5:10 PM CT (typed in session 15f24a49), also before the reading: "if it passes, go
ahead and turn it on". So a full PASS of the pre-registered rule means
`REFRESH_WORKER__SYNDICATE_NBA_NO_HISTORY_STANDINS=on` on the fleet: env change, full down/up under all three claims,
`deploys.md` entry. A full PASS is PRIMARY PASS, secondary (points) not FAIL, and minutes-prior MAE <= 8.0. A primary
pass with a secondary FAIL or a sanity breach is NO-GO, as pre-registered. Expected on the first `on` refresh: one round
of SMART_SIM_REUSE_STALE_POOL rebuilds for every game with a stand-in. Stand-ins' own props stay unpriced either way.

