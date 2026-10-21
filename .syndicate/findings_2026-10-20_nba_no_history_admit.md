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
