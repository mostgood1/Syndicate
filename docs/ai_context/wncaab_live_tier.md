# WNCAAB live tier: the women's live re-sim

Lane `wncaab-module`. Built 2026-11-03 on the user's "Build it". Model engine standard:
`docs/ai_context/model_engine_standard.md`. The men's tier, which this one reuses hop for
hop, is `docs/ai_context/ncaab_live_tier.md`.

## What it is

The NCAAB live re-sim (`syndicate/features/ncaab/live_resim.py`) run with
`league="wncaab"`. It resumes P1's possession engine from the live ESPN state of every
in-progress women's D-I game, under the women's rules:

- four 10:00 quarters and 5:00 overtimes;
- two shots from the 5th team foul of a quarter, with no 1-and-1;
- overtime continues the 4th quarter's team-foul count.

It publishes one `gameLens` lane per game to `live/wncaab_live_resim.json`. The board prices
live women's game lines from that lane, exactly as it does the men's.

There is no second copy of the code. Every function on the path takes `league` and defaults
to `ncaab`, so the men's tier is unchanged and its tests still pin it.

## Pipeline trace (file:line as of 2026-11-03)

1. **Thread start.** `live_lens_loop.py:1277` calls `start_ncaab_live_resim_loop`
   (`live_resim.py:941`), which also calls `start_wncaab_live_resim_loop` (`:936`). The
   women's thread starts in `_start_loop` (`:921`) and runs `_loop` (`:912`).
   - The switch is `wncaab_live_resim_enabled` (`:851`). `SYNDICATE_WNCAAB_LIVE_RESIM` wins
     when set. ABSENT, it follows `SYNDICATE_NCAAB_LIVE_RESIM`, so the women's thread runs
     only where the men's does (the live-odds-worker).
   - `SYNDICATE_WNCAAB_LIVE_RESIM=0` stops the women's thread alone.
   - The start lives inside the men's starter because `live_lens_loop.py` belongs to lane
     `wnba-native-live-cutover`.
2. **Tick.** `run_live_resim_tick(league="wncaab")` (`:888`) takes its sims and budget from
   `_tick_kwargs` (`:872`).
   - `SYNDICATE_WNCAAB_LIVE_RESIM_SIMS`: default 200, the men's value.
   - `SYNDICATE_WNCAAB_LIVE_RESIM_BUDGET_SECONDS`: default 120. The women's slate is about
     half the men's, and the two threads share one interpreter (one GIL).
   - Interval: `SYNDICATE_WNCAAB_LIVE_RESIM_INTERVAL_SECONDS`, default 120 s.
   - Log line: `WNCAAB_LIVE_RESIM_TICK date=.. live=.. resimmed=.. refused=.. carried_forward=.. not_reached=.. refusals={..} bytes=.. written=.. elapsed_s=..`.
3. **Live games.** `build_live_lens_snapshot` (`:710`) calls
   `basketball_pbp.fetch_scoreboard("wncaab", ..)` (`basketball_pbp.py:165`). That fetches
   `basketball/womens-college-basketball`, with `groups=50&limit=500` for D-I. It keeps
   events in state `in` and rotates through them with the cursor key `wncaab|<date>`
   (`_cursor_key`, `:680`), so it never moves the men's cursor.
4. **Live state.** `fetch_summary("wncaab", id)` (`basketball_pbp.py:170`) is passed to
   `resume_from_summary(league="wncaab")` (`:404`).
   - That calls `pbp.reconstruct` (`basketball_pbp.py:603`) and `build_live_game_state`
     (`basketball_live_state.py:235`), under `pbp.rules_for("wncaab")`.
   - Those rules derive from the rulebook entry `basketball_league_rules.WNCAAB`, scope
     `"quarter"`.
   - Team-foul buckets are `min(period, 4)`.
   - The resume refuses `regulation_over` only at the end of the 4th quarter. At the end of
     Q1-Q3 it resumes the next quarter's tip.
5. **Inputs.** `build_engine_inputs(league="wncaab")` (`:256`) reads the women's tables under
   `<data root>/wncaab_source/data/processed/`:
   - `team_ratings_<season>_asof_*` through `live_team_model.prior_for_game`
     (`live_team_model.py:272`). The per-game prior-season fallback applies.
   - `player_priors_<season>_asof_*`, with preseason rows filling teams that have not
     played (`load_player_priors`, `:157`).
   - NO men-fitted adjustment: no half split, no live mechanisms.
   - Refreshed daily by the pregame launcher's `--refresh-inputs` after 11:00Z.
6. **Engine.** `ncaab_engine(league="wncaab")` (`:323`) binds
   `basketball_engine.league.WNCAAB`: four quarters, 30 s shot clock, five fouls.
   `resim_live_game(league="wncaab")` (`:495`) returns full-game plus q1..q4 / h1 / h2
   distributions.
7. **Write.** The lane goes to `live_lens_snapshot_path("wncaab")` (`:656`), which is
   `live/wncaab_live_resim.json` through `refresh_state_store.write_json_file`. That path
   is keyvalue on the fleet, so it crosses services.
8. **Board.** `board_enrichment.attach_live_gamelines_for_sport` (`board_enrichment.py:2768`):
   - admits `wncaab` (`_LIVE_GAMELINE_SPORTS`);
   - reads `_LIVE_GAMELINE_SNAPSHOT_PATHS["wncaab"]` (`:2617`);
   - indexes lanes stamped `live_resim` (`live_gameline_join.LIVE_LENS_SOURCES_BY_SPORT["wncaab"]`,
     `live_gameline_join.py:124`);
   - prices live rows through `attach_live_gamelines` (`live_gameline_join.py:1473`).

   Called from `book_grid_artifact.py:652` and `pipeline/layer2_shortlist.py:1415`
   (refresh-worker).

Board names: a lane carries the OddsAPI spelling from `odds_<date>.csv` under the women's
tree (`odds_team_names(league="wncaab")`). A game with no quote falls back to ESPN's display
name, and has no board row to join anyway. Measured 2026-11-03 morning: all 6 quoted teams
matched.

## Gates

- **Input checklist:**
  `py -3 scripts/ncaab_live_input_checklist.py --league wncaab --date <d>`. It exits non-zero
  on any of:
  - a consumed ratings field under the floor, in this season's table or in the fallback;
  - D-I coverage under 95% (rated this season or last);
  - player-prior coverage under 95%;
  - no ratings table or no player-priors table (exit 2).

  Fleet data, 2026-11-03 (worktree code): **PASS**. Rated 0.9972 (1 unrated: 2697).
  Player priors 0.9862: Duke 150, Providence 2507, Florida A&M 50, 2523 and 309 have none,
  so their games refuse `team_has_no_player_priors`.
- **Reachability (`off != on`), all in `tests/test_wncaab_live_resim.py`:**
  - the same halftime summary resumes Q3 under `wncaab` and refuses `regulation_over` under
    `ncaab`;
  - the real engine resumed in Q4 moves with the lead;
  - the snapshot runs every hop under `wncaab`;
  - the men's starter starts the women's thread;
  - a women's lane indexes and prices a board row.
- **Coverage registry:** `scripts/live_tier_coverage_check.py` declares `wncaab` (LIVE_RESIM,
  no props).

## Known limits

- **Pricing:** OddsAPI quotes no women's quarter or half lines (measured 2026-11-02), so the
  q1..q4 / h1 / h2 distributions price nothing. Full-game lines only.
- **Coverage:** OddsAPI prices roughly 14 of about 94 D-I women's games a night. A live lane
  for an unpriced game is published, but it joins no row.
- **Rates:** every engine rate is NCAAB's, which are themselves the NBA defaults (no women's
  fit). The pace comes from the women's tempo ratings. No women's live backtest exists yet.
- **Throughput:** the men's tick managed at most about 11 games per 240 s tick at 73-80 live
  games (11-02). The women's thread competes for the same interpreter, so measure both ticks'
  `resimmed` after it starts.
