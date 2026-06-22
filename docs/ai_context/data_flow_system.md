# Syndicate Data Flow System

This document maps the actual code paths from source data to UI for each sport. It follows the route and builder chain used in the repository, not an inferred architecture.

## Shared Pattern

Most sports follow the same shape:

1. Source data comes from local artifacts, mirrored snapshots, remote source-app JSON, or weekly summary payloads.
2. A sport-specific cards or live-lens builder normalizes that input into a page context or API payload.
3. The blueprint route passes that context into a shared contract such as the game-board or rank-board payload builder.
4. The route renders either a shared template or a sport-specific template.

Shared contracts and helpers used across the app include `build_cards_page_context()`, `build_game_board_api_payload()`, `build_rank_api_payload()`, `game_board_contract`, `rank_board`, and `refresh_state_store`.

## MLB

**Source**

- Local MLB source artifacts and daily summary files from the MLB feature tree.
- Live-lens and props data from MLB-specific artifact readers.

**Fetch and transform**

- The cards layer loads source artifacts and normalizes them in `syndicate.features.mlb.cards`.
- Live-lens data is read through `read_latest_live_lens_page_context()` and `read_latest_live_lens_api_payload()`.
- Rank and props surfaces are built through sport-specific builders such as `build_hr_targets_page_context()`, `build_pitcher_ladders_page_context()`, `build_hitter_ladders_page_context()`, and `build_top_props_page_context()`.

**State and context**

- `build_cards_page_context(selected_date)` feeds the cards, game detail, and API routes.
- `build_season_page_context()` is used for season-level card views.
- `build_game_detail_page_context()` creates the detail-page state.

**UI render**

- Cards render to `shared/game_cards_board.html`, `mlb/cards.html`, or `mlb/cards_embed.html`.
- Rank-style views render to `shared/rank_board.html`.
- Live-lens views render to `mlb/live_lens.html`.
- Betting-card and props routes render to `mlb/betting_card.html` and `mlb/daily_top_props.html`.

**Route anchor**

- The main route cluster is in [syndicate/blueprints/mlb.py](../syndicate/blueprints/mlb.py).

## NBA

**Source**

- Remote source-app JSON fetched by the NBA cards layer.
- Live-lens and live-state snapshots from NBA-specific artifacts.

**Fetch and transform**

- `syndicate.features.nba.cards` fetches remote JSON and normalizes it into card payloads.
- Live-lens helpers provide current-state, player-lens, lines, and boxscore payloads.
- Sim detail, features, picks, props, and betting-card data are each built in dedicated NBA modules.

**State and context**

- `build_cards_page_context(selected_date, allow_stored_date_fallback=...)` is the primary cards context.
- `build_live_state_payload()` and the live-lens readers manage current-state rendering and API responses.
- `build_game_detail_page_context()` covers game detail.

**UI render**

- Cards render to `shared/game_cards_board.html` or `nba/cards_source.html`.
- Live-lens and accuracy surfaces render to `nba/live_prop_audit.html`, `nba/live_prop_accuracy.html`, `nba/live_game_accuracy.html`, `nba/live_lens_daily_accuracy.html`, and `nba/market_accuracy.html`.
- Picks and props render to `nba/picks.html` and `nba/prop_ladders.html`.
- Reconciliation renders to `nba/reconciliation.html`.

**Route anchor**

- The main route cluster is in [syndicate/blueprints/nba.py](../syndicate/blueprints/nba.py).

## NHL

**Source**

- Scoreboard snapshots and NHL web-client scoreboard pulls.
- NHL artifact bundles for live-lens, props, and reconciliation.

**Fetch and transform**

- `syndicate.features.nhl.cards` reads the scoreboard source and builds source bundles, sim boxscores, sim summaries, and props cards.
- Live-lens and daily accuracy payloads are built in NHL live-lens modules.
- Betting recap, player-props reconciliation, and props-lines payloads are built by dedicated NHL modules.

**State and context**

- `build_cards_page_context(_selected_date())` feeds the cards route.
- `build_live_lens_page_context(selected_date)` feeds the live-lens board.
- `build_betting_card_page_context(season, _selected_season_date(season))` feeds the betting-card route.

**UI render**

- Cards render to `shared/game_cards_board.html` or `nhl/cards_source.html`.
- Live-lens and rank-style boards render to `shared/rank_board.html`.
- Accuracy and reconciliation surfaces render to sport-specific NHL templates.
- Betting cards render to `nhl/betting_card.html`.

**Route anchor**

- The main route cluster is in [syndicate/blueprints/nhl.py](../syndicate/blueprints/nhl.py).

## NFL

**Source**

- Weekly recommendation snapshots and season-scoped card data.
- NFL archive and live-lens snapshots.

**Fetch and transform**

- `syndicate.features.nfl.cards` reads recommendation rows and groups them into matchup bundles.
- Archive, game detail, live-lens, picks, and betting-card builders convert those bundles into route-ready context objects.

**State and context**

- `build_cards_page_context(_selected_week(season), season=season)` is the primary cards state.
- `build_game_detail_page_context()` handles detail views.
- `build_live_lens_page_context()` and `build_picks_page_context()` drive the board-style outputs.

**UI render**

- Cards and detail render to `shared/game_cards_board.html`.
- Archive, live-lens, picks, and betting-card surfaces render to `shared/rank_board.html`.

**Route anchor**

- The main route cluster is in [syndicate/blueprints/nfl.py](../syndicate/blueprints/nfl.py).

## WNBA

**Source**

- Processed WNBA artifacts, smart-sim indexes, and live snapshot state.
- Live lines, player lenses, boxscore data, and play-by-play state for live surfaces.

**Fetch and transform**

- `syndicate.features.wnba.cards` merges processed artifacts with raw smart-sim and source-card inputs.
- `build_source_cards_payload()` is the source-card API layer.
- `build_live_state_payload()`, `build_live_player_boxscore_payload()`, `build_live_player_lens_payload()`, `build_live_lines_payload()`, and `build_live_pbp_stats_payload()` provide live state slices.

**State and context**

- `build_cards_page_context(selected_date, allow_stored_date_fallback=...)` controls the cards page.
- Explicit-date routes are protected from silent fallback when the route requires a specific slate.
- `build_game_detail_page_context()` handles detail state.

**UI render**

- Cards render to `shared/game_cards_board.html` or `wnba/cards_source.html`.
- Picks and props render to `wnba/picks.html` and `wnba/prop_ladders.html`.
- Live prop and accuracy surfaces render to the WNBA live-lens and accuracy templates.
- Betting cards render to `wnba/betting_card.html`.

**Route anchor**

- The main route cluster is in [syndicate/blueprints/wnba.py](../syndicate/blueprints/wnba.py).

## NCAAF

**Source**

- Weekly summary JSON built from college-football recommendation and slate data.

**Fetch and transform**

- `syndicate.features.ncaaf.cards` loads the weekly summary payload and collapses rows into grouped card entries.
- The card payload is then passed through `apply_game_board_contract()` or the shared board payload builders.

**State and context**

- `build_cards_page_context(_selected_week())` is the primary cards state.
- `build_game_detail_page_context()` handles game detail.
- `build_live_lens_page_context()` and `build_betting_card_page_context()` handle the board-style routes.

**UI render**

- Cards render to `shared/game_cards_board.html`.
- Archive, picks, live-lens, and betting-card views render to `shared/rank_board.html`.

**Route anchor**

- The main route cluster is in [syndicate/blueprints/ncaaf.py](../syndicate/blueprints/ncaaf.py).

## NCAAB

**Source**

- Mirrored recommendation payloads and season/date-specific college-basketball artifacts.

**Fetch and transform**

- `syndicate.features.ncaab.cards` consumes mirrored recommendations and groups them into card entries.
- Season, live-lens, results archive, and detail builders convert the source payload into route-ready context.

**State and context**

- `build_cards_page_context(_selected_date())` feeds the cards route.
- `build_live_lens_page_context(_selected_live_date())` feeds live-lens.
- `build_results_archive_page_context(_selected_date())` feeds archive and results views.
- `build_season_page_context(season, _selected_season_date(season))` and `build_season_betting_card_page_context()` cover season views.

**UI render**

- Cards render to `shared/game_cards_board.html`.
- Live-lens and results/archive views render to `shared/rank_board.html`.
- Season and betting-card views also use the shared board templates.

**Route anchor**

- The main route cluster is in [syndicate/blueprints/ncaab.py](../syndicate/blueprints/ncaab.py).

## Takeaway

- MLB is the most artifact-heavy and source-local implementation.
- NBA and WNBA mix local state with live snapshot hydration and explicit fallback rules.
- NHL and NFL lean heavily on snapshots and weekly grouping.
- NCAAF and NCAAB are simpler board builders that mostly collapse weekly or mirrored recommendation payloads into shared contract views.
