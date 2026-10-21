# NBA SmartSim ran last season's rosters on opening night — trace, measurement, fix (lane `nba-current-rosters`)

`[2026-10-20, session 8e69dd3f; times US Central]`

## The symptom (user report, ~7:40 PM CT)

PHI @ NYK (ESPN 401909089): ESPN's box lists LeBron James, Jaylen Brown, Anfernee Simons, Kentavious
Caldwell-Pope, Adem Bona for PHI; the pregame `smart_sim_2026-10-20_NYK_PHI.json` has none of them and carries
Paul George, Kelly Oubre Jr., Kyle Lowry, Quentin Grimes, Trendon Watford, Dalen Terry. The live re-sim missed
24 of 132 live NBA prop rows as "player not live". The props log printed
`NBA_SIM_AVAILABILITY {"applied": true, ..., "teams": 0}`.

## Pipeline trace (origin/main 859e96e6 + this lane's 4d535e36; file:line at each hop)

```
refresh-worker -> scripts/refresh_odds_sources.py:857  (subprocess per run)
  -> scripts/refresh_nba_oddsapi_props.py:2785 _ensure_player_logs_for_props_refresh
       :2818 refresh_current_rosters            [NEW]  writes processed/rosters_<season>.csv
  -> :3139 export_props_predictions_local
    -> basketball_props_predictions.py:162 build_features_for_date_local
         basketball_props_features.py:385 current_roster_index   [NEW]
         :447 team_now = roster_now.team_for(...)  -> as-of team (was: team of the LAST player_logs row)
    -> basketball_props_smart_sim.py:5922 _apply_basic_slate_filter (by that team)
         writes processed/props_predictions_<D>.csv
    -> _smart_sim_run_date_local
         :5183 current_roster_active ; :5482 reuse branch -> smart_sim_reuse.props_pool_verdict [NEW]
         worker :5044 context.props_pool stamp [NEW]
      -> orchestrator/smart_sim.py:1169 simulate_smart_game
           :1359 _team_players_from_props(props_df, team)       -> the pool
           :1377 _filter_team_players_against_processed_roster  -> bpss:2060 -> :1981 reads rosters_<season>.csv
                 (pick: rosters_<season>.csv, else the newest rosters_*.csv -- on the fleet rosters_2025-26.csv)
           priors: bpss:3350 _prior_rates_for_player_local (team-keyed; latest_team fallback [NEW])
      writes processed/smart_sim_<D>_<HOME>_<AWAY>.json + engine_inputs/<D>/<HOME>_<AWAY>.pkl (live re-sim input)
```

`NBA_SIM_AVAILABILITY teams=0` is EXONERATED as a cause: it only ADDS exclusions, from this season's regular-season
rows of `player_logs.csv`, and on opening night there are none (the designed no-op). It never builds the pool.

## The measurement BEFORE (substrate: the fleet's production data root, read-only; truth: ESPN current rosters, live)

`scripts/nba_sim_roster_audit.py --date 2026-10-20 --date 2026-10-21` over the 14 sims as built:

| | |
|---|---|
| sides | 28 (3 games 10-20, 11 games 10-21) |
| sides with a stale player | **28 / 28** |
| simulated players not on the team they were simulated for | **179 of 460** |
| current-roster players missing from the sim | 202 |
| ... of them with a posted prop line in that game | **39** (22 sides) |
| stale players whose sim team == their rosters_2025-26 AND last player_logs team | **179 / 179** |

PHI 10-20: 10 of 15 simulated players stale. `player_logs.csv` holds ONLY 2025-26 (SEASON_ID 22025, 26,651 rows,
ends 2026-04-12); `rosters_2025-26.csv` written 2026-09-30; no 2026-27 roster file and no producer for one.

Name spelling check (ESPN 517 current players vs 582 log players): 82 / 147 unmatched each way, and 0 same-surname
pairs that are one person — no ESPN-vs-stats.nba spelling mismatch to drop a real player.

11 of the 39 priced-missing players have NO NBA history in the file at all: 7 rookies (Dybantsa, Boozer, Peterson,
Wilson, Acuff, Lendeborg, Wagler) and 4 who missed 2025-26 (Lillard, Haliburton, Irving, VanVleet). A team re-key
cannot admit them: they have no feature row. Open follow-up, not built.

## The fix (4d535e36, on branch `claude/nba-current-rosters`, NOT on main / the fleet)

- `nba_current_rosters.refresh_current_rosters`: ESPN 30 team rosters -> `rosters_<season>.csv` (stats.nba columns +
  ESPN_ID/ESPN_NAME/ROSTER_SOURCE/FETCHED_AT; PLAYER = stats.nba spelling and PLAYER_ID resolved by name). Complete
  or nothing (a partial file would hide the old season's for a missing team), a failed team carries its previous
  ESPN rows, 90-min throttle, kill switch `SYNDICATE_NBA_CURRENT_ROSTERS=0` (absent = ON).
- `current_roster_index` refuses a roster fetched more than one day after the slate (an as-of replay must not see
  later moves), an incomplete file, and an ambiguous key.
- Features: the as-of team is the current roster's; a player on no current roster is dropped.
- Priors: `PlayerPriors.latest_team` — a moved player's lookup under his new team falls back to his own rates.
- Reuse: every sim stamps `context.props_pool`; a pool change rebuilds the game; an unstamped NBA file is stale while
  the re-key is active (those were built from 2025-26 teams).

Reachability, each off != on: 16 unit tests; on real data (10-21 scratch) the priors fallback hits 86 / 86 moved
players vs 1 / 86 without it, 236 / 236 unmoved identical either way.

## AFTER (scratch re-sim of 10-21 on a copy of the fleet data, worktree code)

Substrate: a `cp -a` of the fleet's `nba_source/data/{processed,raw}` taken 2026-10-20 ~8:28 PM CT, worktree code
4d535e36, the refresh-worker's sim-related env keys (names only read, values passed through, never printed),
`SYNDICATE_DATA_ROOT` / `SYNDICATE_NBA_SOURCE_ROOT` forced to the scratch copy (production's 10-21 engine inputs and
sims verified untouched afterwards). Same entry point the props refresh calls (`export_props_predictions_local`,
n_sims 500, overwrite False so the REAL reuse branch decides). ESPN rosters fetched 2026-10-21T01:28Z (8:28 PM CT).

- `NBA_CURRENT_ROSTERS`: wrote, 30 teams, 517 players, 440 with a stats.nba id, 0 failed.
- `NBA_CURRENT_ROSTER_REKEY` (league-wide feature rows): moved 110, departed 147, kept 325
  (LeBron James LAL->PHI, Paul George PHI->BOS, Kawhi Leonard LAC->TOR, Anthony Davis DAL->WAS ...; departed: Chris
  Paul, Kyle Lowry, Russell Westbrook, Kevin Love ...).
- Reuse: all 11 old 10-21 sims `SMART_SIM_REUSE_STALE_POOL ... reason=no_pool_stamp_current_roster_active` -> rebuilt.
- `props_predictions_2026-10-21.csv` 430 -> 322 rows (departed dropped; rookies have no feature row).

`nba_sim_roster_audit.py --date 2026-10-21` against the same ESPN snapshot, the same 22 sides:

| | before (fleet, as built) | after (ON) |
|---|---|---|
| simulated players | 363 | 292 |
| **stale** (not on the team simulated for) | **146** | **0** |
| sides with a stale player | 22 / 22 | **0 / 22** |
| missing current-roster players | 163 | 88 |
| **missing with a posted prop line** | **34** | **13** |

The 13 left: 11 with NO NBA history in `player_logs.csv` (7 rookies + Lillard, Haliburton, Irving, VanVleet; Dybantsa
also injury-excluded) and 2 with history the injury feed excludes (Podziemski GSW, Nesmith IND) although a line is
posted (the injury path, not a roster defect). **Every priced player with history and no injury exclusion is now
simulated for his current team.**

Priors fallback on the same data: 86 moved players in the 10-21 pool, own prior found for 86 / 86 (1 / 86 without
the fallback); 236 unmoved players identical either way.

### ON vs OFF on identical inputs (OFF = switch off, roster file removed, every game re-simulated)

OFF reproduces production exactly in shape: props_predictions 430 rows, no re-key line, audit stale 145 / 352
(production's as-built sims: 146 / 363; the difference is the later injury feed).

Game level, 11 games: mean |d total| 1.47 pts (max 5.4, BKN_CHA 224.7 -> 219.4), mean |d margin| 1.72 (max 3.6),
mean |d p_home_win| 0.044 (max 0.078: HOU_DAL 0.726 -> 0.668, POR_PHX 0.652 -> 0.574).

Minutes vs each player's OWN 2025-26 average (>= 10 games; a PROXY, not truth -- the truth is the 10-21 box):

| | OFF | ON |
|---|---|---|
| players compared | 326 | 278 |
| MAE (sim - own) | 6.37 | **5.69** |
| mean (sim - own) | -5.60 | -4.08 |
| under-simulated by >= 8 min | **111** | 70 |
| over-simulated by >= 8 min | 1 | **5** |
| teams with <= 11 simulated players | 0 | 4: DAL 9, SAC 10, CHA 11, GSW 11 |

**THE NEW RISK, ACCEPTED BY THE USER:** a team missing no-history rotation players gets a thin pool, and the sim
spreads 240 minutes over fewer players: DAL (Kyrie Irving + 4 rookies no-history, 3 injury-excluded) simulates P.J.
Washington 39.1 min (own 30.9), Moussa Cisse 32.0 (own 14.3); CHI Leonard Miller +12.9, WAS Anthony Gill +8.8, SAC
Nique Clifford +8.8. Their props can show spurious OVER edges. Production as it stands has the opposite bias at
larger scale (111 players under-simulated by 8+ min -> spurious UNDERS). The sim's own pregame-starters input
(`pregame_expected_minutes_<D>.csv`, nba_starters_v1 from 2027 preseason boxes) already lists Kyrie (starter prob
0.5) and Morez Johnson Jr.; the pool cannot take a player with no feature row. Follow-up card: "Admit no-history NBA
players with a posted prop line".

USER DECISION 2026-10-20 ~9:15 PM CT (AskUserQuestion): "Deploy as approved (Recommended)" -- with the thin-pool risk
stated; the 5 inflated players are named here and in deploys.md.

ROLLBACK NOTE: `SYNDICATE_NBA_CURRENT_ROSTERS=0` stops the refresh and the re-key, but the sim's roster filter, the
injury scraper and the live tick read `rosters_2026-27.csv` by FILE PRESENCE. A full rollback is the switch AND
deleting that file (or `git revert` + delete).
