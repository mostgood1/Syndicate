# Bobby Portis was missing from the 11-08 NBA engine frames — the roster filter's name key `[2026-11-09 ~8:20 AM CST, lane nba-roster-filter-name-key, session c7e5cb4c]`

**Substrate:** fleet data (`~/syndicate-prod/data/nba_source`), read with the fleet's own code (`~/Syndicate` at `e2558013c`) and with the fix, at nice 19, read-only. Nothing on the fleet was written or restarted. Fix on main `8fc72076d`, **NOT LOADED**.

## The question
Bobby Portis had 6-7 served live NBA prop rows on MIA @ SAC (2026-11-08, ~02:30Z 11-09), none with a Live proj. or actual. `live_resim.load_engine_inputs('2026-11-08','SAC','MIA')` had no Portis on either side. The live re-sim resumes from those frames, so no live prop row could exist for him.

## Cause (file:line on main before the fix, `e2558013c`)
- `smart_sim_2026-11-08_SAC_MIA.json` `context.props_pool.MIA` holds 16 names, including `BOBBY PORTIS JR.`. `context.excluded_players.MIA` = Norman Powell, Tre Donaldson, Vladislav Goldin (not Portis). `players.away` = 14, no Portis.
- The pool row's name is the 2026-27 `player_logs.csv` spelling, **"Bobby Portis Jr."** (the 2025-26 rows say "Bobby Portis"). `rosters_2026-27.csv` (ESPN writer, stats.nba spelling resolved by id) says **"Bobby Portis"**. PLAYER_ID **1626171** on both.
- `basketball_props_smart_sim._filter_team_players_against_processed_roster_local` (`basketball_props_smart_sim.py:2094-2099`) keeps a row only when `_norm_name_key(name)` is in the roster's key set. `_norm_name_key` (`:667-685`) keeps periods, so it strips `" JR"` but not `" JR."`: `'BOBBY PORTIS JR.' != 'BOBBY PORTIS'`.
- Called from the orchestrator's `_augment_team_players` (`orchestrator/smart_sim.py:1377`) on the props pool, after exclusions and before minutes, priors and the engine call. NBA does not prune the pool (`runtime.py:96 prune_pregame_pool=False`), so nothing else removes or re-adds a player.
- **Replay:** fleet code on the fleet's 11-08 pool (props_predictions rows minus the sim's own excluded set). The filter dropped exactly one player on the slate: MIA 15 -> 14, `['Bobby Portis Jr.']`. The fixed code drops 0.
- **The replay is faithful:** with fleet code, the filter replay's kept set equals the persisted engine frame on **14 of 14 teams** (canonical keys). With the fix, the only difference on the slate is MIA + `BOBBY PORTIS`.

## Did he play
Yes. ESPN box (recon_props_2026-11-08, source espn, event 401909951): **20 min**, 4 pts, 1 reb, 1 ast, 1 three. On 11-07 (MIA @ GS) his 4 blank live rows had the same cause.

## The 11-08 slate count
Players with any pre-tip line (raw `odds_nba_player_props_history_2026-11-08.csv`, snapshot < commence, plus the processed CSV), against the persisted engine frames, live re-sim key:
- **106 priced players, 5 absent from their game's engine frames.**
- Doncic (LAL), Markkanen (UTA), Sabonis (SAC): in the sim's excluded set, and absent from the ESPN box. **Correct.**
- **Bobby Portis** (MIA): dropped by the roster filter, played 20 min. **The defect.**
- **Terrence Shannon Jr.** (MIN): excluded as `TERRENCE SHANNON` by the NBA recency rule (`nba_sim_availability`, K=2; he was OUT 11-02..11-06, hip). He played **18 min**. **A second instance of the same defect** (below).
- (The brief said Shannon was not in the props CSV. He was in the pre-tip history from 06:01Z 11-08. The processed CSV is overwritten in play, per learnings 2026-10-22.)

## The same split, a second path: the recency rule's prop-line readmit
- `add_nba_recency_exclusions` readmits a player with a posted pre-tip line by comparing `name_key(book name)` with `name_key(player_logs name)`, where `name_key` is the caller's `_norm_name_key`.
- The books write "Terrence Shannon Jr." and player_logs "Terrence Shannon Jr": `'TERRENCE SHANNON JR.' != 'TERRENCE SHANNON'`. His lines were posted from 06:01Z; the MIN_UTA inputs were built 00:03:44Z 11-09 (tip 00:10Z). Only the name kept him out.
- **11 slates, 10-28..11-08** (each sim's own `context.excluded_players`, against ESPN box minutes and pre-tip lines): 997 sim exclusions; 85 of them played (the rule's known, user-adopted cost); 4 played with a pre-tip line; **1 of the 4 is a name split** (Shannon). The other 3 (Marcus Smart 10-30, Reed Sheppard 11-02, Gui Santos 11-07) have matching keys. Their line most likely posted after the build. That is unproven, and it is not this defect.
- **Replay of the rule on fleet data:** a scratch copy of player_logs, the rule's json and the season-types cache, plus the props snapshot rebuilt from the raw history as of the build (snapshot <= 00:03:44Z and < commence; 710 Shannon rows). Fleet code: MIN excluded = Edwards, C. Williams, I. Evans, **TERRENCE SHANNON**, Pullin (matches the sim's context), added 72, readmitted 1. Fixed code: Shannon readmitted, added 71, readmitted 2. No other change.
- Latent elsewhere: rosters_2026-27 rows whose `_norm_name_key` differs from the newest player_logs spelling for the same id = **2** (Portis, Shannon). Both match under `normalize_player_name_key`.
- **The expected-minutes merge** (`_merge_pregame_expected_minutes_for_team_local`) missed both the same way. pregame_expected_minutes has no player_id, so Portis got `starter_prob` NaN instead of 0.0. 7 other misses on 11-08 are players simply not in that file, not name splits.

## Fix (`8fc72076d`; only ever adds a match)
- Roster filter: a row is also on the roster when its stats.nba id is on the team's roster, or when its `normalize_player_name_key` (orchestrator; drops periods/apostrophes/suffixes, applies aliases) matches. `[basketball_roster_filter] ROSTER_FILTER_DROPPED date= team= n= names=` prints what the filter removes, so a drop is no longer silent.
- Recency readmit: also matches on `normalize_player_name_key`.
- Expected-minutes merge: a last-resort fill on `normalize_player_name_key`, into cells still empty.
- `tests/test_nba_roster_filter_name_key.py`, 5 tests. Each drives the function the sim calls (through `orchestrator/hooks.py` where one exists) on production-shaped fixtures, and each has an OFF arm. With the widened match disabled, the 11-08 production behaviour comes back: Portis dropped, starter_prob NaN, `TERRENCE SHANNON` excluded. 81 neighbouring tests pass (availability, team inputs, injury re-inclusion, WNBA availability, current rosters, props predictions).

## Owed
- **Load:** the NBA pregame sims are built under the live-odds-worker (the props refresh is its child). A fleet ff to a tree containing `8fc72076d` plus a claimed live-odds-worker TERM loads it. This session restarted nothing (brief: no restarts). It can ride with `#762` (7)'s owed load.
- **Reading after load**, on the next MIA or MIN slate (neither plays 11-09/11-10): Portis in `load_engine_inputs(<date>, ..., 'MIA')`; `ROSTER_FILTER_DROPPED` lines in live-odds-worker.log name only departed players; a healthy Shannon is readmitted when priced; his served live prop rows carry Live proj.
- Not touched: `_norm_name_key` itself. It is the key of the exclusion map, the `context.props_pool` reuse stamp and the props tracking, so changing it would re-key all of them (stamp churn, exclusion keys moved). The WNBA `add_recency_exclusions` readmit has the same shape. WNBA is out of season and the rule is off unless `SYNDICATE_WNBA_SIM_AVAILABILITY` is set.

Probes (read-only, this session's scratchpad): `portis_probe1.py` .. `frames_probe8.py`, `split_probe7.py`, `shannon_probe9.py`.
