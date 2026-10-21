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
