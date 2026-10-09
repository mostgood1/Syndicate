# Historical team / player data behind game lines and props — can charts be added to Layer 2 and Ask the Syndicate?

Session 43e4d5fe, 2026-10-09, user: "look into the team and player historical data around all game lines and player
props to ensure that historical charts can be added to the layer2 board and ask the syndicate". Read-only survey by
three subagents (code + the local fleet disk `~/syndicate-prod/data`, scanned at nice 19). [disk] = measured on the
fleet; [code] = read in the repo. No code or data was changed.

## Bottom line

Charts are NOT greenfield: both surfaces already draw history (inline SVG / CSS bars, no chart library). The work is
coverage. Player-game ACTUALS exist with stable ids, 2+ seasons deep, for MLB, NHL, soccer, NBA, WNBA and NCAAF; NFL's
player table is stale; NCAAB has no player logs. **Historical LINES exist only from 2026-09-30 (~10 days) in every
sport** — a chart can show a player's/team's actual results against TODAY's line, but past-game line overlays only for
those days. Never draw a flat line or a 0.5 midpoint in place of a missing line; show an empty state.

## The two surfaces [code]

- **Layer 2 board:** rows are built on the WORKER (`pipeline/layer2_shortlist.py:2047` ->
  `syndicate/features/shared/layer2_board.py:3627`); chart data attaches at ONE point,
  `layer2_board.py:3786` -> `_chart_columns` (`:3810-3863`); served read-only by
  `syndicate/blueprints/intelligence.py:3967`; rendered in `syndicate/templates/intelligence.html` (team form
  `:4782-4864`, prop recent form `:4866-4914`, movement sparkline `:1482-1517`, sim spread `:4739`).
  - Prop history today = `recent_values_for` (`syndicate/features/intelligence_recent_matchup.py:814`), a
    process-local side channel filled when the "Recent form" sentence is computed; values only, dates mostly absent.
  - Team history = `syndicate/features/shared/team_recent_results.py:248`: NFL, NCAAF, NHL, MLB, soccer; NBA/WNBA
    deliberately excluded (box scores end last season); 120-day window.
  - Card identity: sport, league, event_id, commence_time, market, line, side, home/away team + canonical keys,
    player_name, pick_id. **No player_id and no team id on L2 cards** -> props need a name-to-id join per sport.
  - Payload is already a known problem (~5k rows/board; a 48.7 MB embed recorded at `intelligence.py:2068`). Dated
    per-game arrays on every row should be a separate per-row history artifact fetched lazily by `pick_id`.
- **Ask the Syndicate:** `syndicate/blueprints/ask_the_syndicate.py:743` already returns
  `visuals = {tables, charts}` from `focused_evidence` built in `ask_the_syndicate_data.py` (last-10 builders
  `_basketball_last10_evidence:1093`, `_nhl_last10_evidence:1159`, `_boxscore_last_n:1046`); rendered by
  `syndicate/static/shared/ask_bar.js:335` and `syndicate/templates/syndicate.html:589` (bars only, <= 30 points).
  New per-sport evidence renders in both UIs with no front-end change; line/time-series charts need both renderers
  extended. The LLM stays off (decision); answers are the snapshot path.
- **Web reachability:** the local fleet has ONE shared disk (`scripts/local_production.py:60-72`), so every file below
  is readable by web today; `HOT_ARTIFACT_PATTERNS` (`syndicate/features/shared/artifact_publisher.py:37`) matters
  only if Render returns.

## Per-sport sources [disk unless noted]

| sport | player-game actuals | team-game history | gap |
|---|---|---|---|
| MLB | `mlb_source/source_artifacts/data/derived/mlb_player_game_log_<yr>_{hitting,pitching}.csv`, stable player_id + game_pk, 2023-03..2026-10-08 (52k hitting rows 2026), daily 11:25 | none precomputed; aggregate player logs by game_pk, or raw `feed_live` / `finals_*.json` | build a team-game table |
| NHL | `nhl_source/source_artifacts/data/raw/player_game_log_<season>.csv`, player_id + gamePk, 2023-10..2026-06 (43-50k/season); 2026-27 in `raw/player_game_stats.csv` (to 10-09, NO opponent column) | none; aggregate or cached boxscores | 2026-27 opponent column; team table |
| Soccer (10 lg) | `<league>/history/player_match_log_<yr>.csv`, ESPN player_id + event_id, 2024..2026-09-20, shots/SOT/goals/assists/minutes/starter, daily 11:15 | `history/matches_<yr>.csv` (football-data: score, shots, SOT, corners, odds; big five end 2026-05-24, 4 summer leagues to 09-20); `team_history/teams_<yr>.csv` (Understat xG, big five, to 09-20) | big-five 2026-27 match stats only via Understat (goals/xG); MLS corners only; ids differ across soccer files (ESPN vs understat_*) |
| NBA | `nba_source/data/processed/player_game_log_{2024,2025}.csv` (PLAYER_ID; 2025-26 complete to 06-13; 2026 file empty pre-season), daily 11:20 | `features.csv` seed ends 2026-04-12 | team table (aggregate logs); playoffs only in some files |
| WNBA | `wnba_source/.../player_game_log_{2024,2025,2026}.csv` (2026 to 10-07) + `boxscores_history.csv` (already read by Ask) | none; aggregate | team table |
| NCAAF | `ncaaf_player_game_history.csv` 2023-24 (player_id, opponent) + `ncaaf_player_game_stats_snapshot.csv` 2025 wk1..2026 wk6 (NO opponent) | none | opponent in the current snapshot; team table |
| NFL | `tracking/nflverse/player_stats/player_stats_2026.csv` STALE at week 3 (written 10-01); `pbp_<season>.csv` 2022-26 refreshed 10-08 (22-99 MB) | `tracking/nflverse/schedules_games.csv` 1999-2026: scores + spread/total/ML lines per game — the only complete team + line + result source | fresh player-game log (derive from pbp) |
| NCAAB | none | `ncaab_source/data/processed/team_game_box_2026.csv` 2025-11..2026-04 (12.6k rows) | player logs |

**Lines and results (all sports):** `tracking/odds_history/<date>.json`, `tracking/book_quotes/`, opening /
movement-signal CSVs, `settlement_inputs/closing_lines_<date>.csv` (closing line + actual + result, all markets) and
`finals_<date>.json` — all start 2026-09-30. The evaluation ledger is mostly unresolved (e.g. NFL 13,553 pending).

## Recommended order (not started; needs a lane + user decision)

1. **Prop "last N games vs this line"** for MLB, NHL, soccer, NBA, WNBA, NCAAF: replace the sentence side channel
   with a worker-built, DATED per-row history keyed by a per-sport name-to-id join (all six have stable ids). NFL after
   a pbp-derived player-game log; NCAAB has no player data.
2. **Team trend:** NFL from `schedules_games.csv` (can include ATS/O-U, the only sport that can); NBA/WNBA/MLB/NHL via a
   team-game table aggregated from player logs (also closes `team_recent_results`' NBA/WNBA exclusion); soccer from
   matches/Understat; NCAAB from `team_game_box`.
3. **Past-line overlay:** only from 2026-09-30; label the window on every chart.
4. **Ask the Syndicate:** per-sport evidence builders following `_nhl_last10_evidence`; extend both renderers only if
   line charts are wanted.
5. Before editing: check lanes.md claims on `layer2_board.py` / `intelligence.html`; measure served payload before and
   after; serve dated history as a lazy per-row artifact, not inline on ~5k rows.
