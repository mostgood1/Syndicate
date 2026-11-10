# NBA prop rows for book-named players the engine spells differently — findings `[2026-11-10, lane nba-prop-engine-name-join, session 2ba5509d, todo #775]`

**Status: fix on main (`c468657e5`), NOT LOADED.** The fleet runs `564f8dbde`. A load needs the user's yes and the
CLAUDE.md deploy protocol: this is the money path, and the change gives rows a model edge they never had.

## 1. The symptom (from the session that found it)

Served `POST /api/intelligence/query`, 2026-11-10 03:20Z. Herb Jones (NOP@GSW) had 20 live prop rows. Each carried
`live_projection` and `actual`, and none carried `sim_projection`, `sim_ladder`, `model_edge_pct`, `projected`,
`player_side`, `headshot_url` or `recent_values`. `sim_view` was "unpriced". Teammate Saddiq Bey carried all of them.
Earlier that night, Paul Reed Jr and Carlton Carrington rows also had `model_edge_pct` null.

## 2. Every name-keyed join on an NBA prop row (file:line before the fix)

| join | where | key on the BOOK spelling | engine source | splits it misses |
|---|---|---|---|---|
| pregame sim projection / ladder / edge | `nba_projections._match_player` :188 | `prop_projections._norm_name` (keeps "jr", periods to spaces, no nicknames) | `cards_sim_detail` players | all 8 measured |
| headshot | `player_headshots.headshot_url` :206 -> `home._basketball_resolve_player_id` :1926 | `_mlb_name_key` (lowercase only) | `player_ids.csv` | all 8 (fleet: 8 of 8 book names miss, 8 of 8 engine names hit) |
| player side (crest) | `player_headshots._player_team` :245 -> `_basketball_teams` | `_mlb_name_key` | `player_ids.csv` team | all 8 |
| recent form, matchup, advanced | `prop_evidence` via `PropSubject.from_board_row` (`contract.py:143`), `names_match` | suffix-loose, collapsed initials, NO nicknames | box scores + `player_game_log_*.csv`, `cards_sim_detail` | the nickname cases: Herb Jones 0 games vs Herbert 64; Carlton 0 vs Bub 80; Ron 0 vs Ronald Holland II 87 |
| vs-position sentence | `intelligence_recent_matchup.basketball_vs_position_text` :691 | `names_match` | DvP positions table | nickname cases |
| OUT-player flag | `board_enrichment._flag_out_player_props` :1453 | `basketball_props_availability.player_key` (suffixes, periods; no nicknames) | injury feed | a feed spelling "HERBERT JONES" (official report) vs book "Herb Jones" |
| live projection / actual | `live_projection_join._resolve_player` | exact, then unique engine key (`e2558013c`) | lens | none: already fixed, display only |
| live EDGE | `live_projection_join.attach_live_projections` :892 | needs `projection.market_fair_prob_over` | written only by the PREGAME join | every split player: no pregame join, so no fair value, so no live edge |
| recommendation p_win | not a Layer 2 join for NBA: `props_recommendations` means are a copy of the same ladder (`nba_projections` docstring) | | | |
| NBA cards-page market board | `basketball_market_board_rows_for_game` :419 | `_canonical_player_key` (casefold) | sim display names | all 8: the book quotes are never attributed, so the rows are absent |
| odds history, closing lines, pick_id, venues | `player_name` | book spelling on both sides | book data | none: correctly left on the book spelling |

The last row of the live chain is why the brief saw Herb Jones's live rows show a Live proj. but no edge. The live
join's edge prices `live_prob_over` against the row's `market_fair_prob_over`, and only the pregame projection writes
that field.

## 3. Count (fleet, read-only, fleet code `564f8dbde`, book grids rebuilt from `iter_book_quotes`)

Probe `C:/tmp/nbaname/miss_count.py`. Per slate, prop rows that miss `_match_player`, and those whose engine key
resolves to exactly one sim player:

| slate | prop rows | resolvable by engine key | players |
|---|---|---|---|
| 11-04 | 10,969 | 67 | Paul Reed Jr->Paul Reed 60, Ron Holland->Ronald Holland II 7 |
| 11-05 | 1,507 | 0 | |
| 11-06 | 7,229 | 109 | A.J.->AJ Green 44, R.J.->RJ Barrett 65 |
| 11-07 | 5,337 | 58 | C.J.->CJ McCollum 50, Carlton->Bub Carrington 8 |
| 11-08 | 5,416 | 133 | AJ Green 8, Derrick Jones->Derrick Jones Jr. 40, Herb->Herbert Jones 17, Paul Reed 68 |
| 11-09 | 6,239 | 243 | CJ McCollum 47, Bub Carrington 6, Herbert Jones 41, Paul Reed 67, RJ Barrett 82 |
| 11-10 | 1,989 | 0 | (tonight's sims not built at read time 15:29Z) |
| **total** | 38,686 | **610 rows, 15 player-slates, 8 players** | **0 ambiguous** |

The other misses are players not in the sim: the game is not simmed yet, an injury exclusion, or the
`nba-roster-filter-name-key` cases (Bobby Portis, Terrence Shannon Jr.). They are not this defect.

OUT feed, 11-04..11-10: 0 book names matched an OUT entry only by the engine key (probe `out_feed.py`). The feed
spells NIC CLAXTON, the book's form. So the out-flag change prevents a future miss and changes nothing today.

## 4. Fix (`c468657e5`)

- `syndicate/features/shared/nba_player_identity.py` (NEW): `resolve_engine_name`. It applies the live join's rule
  through the live join's own key function (`engine_key` IS `live_projection_join._canonical_player`, imported):
  - exact `_norm_name` first;
  - else the canonical key, but only when it names exactly one engine player;
  - ambiguity refuses.
- **The choke point:** `nba_projections.stamp_engine_player_names`, at the top of `attach_nba_prop_projections`.
  - All three grid producers reach it through `board_enrichment.attach_projections`: `book_grid_artifact`,
    `layer2_shortlist._attach_projections_over_window`, and web's serve-time book grid.
  - It stamps `engine_player_name` only on a row whose exact key no sim player carries. Every row that joins today
    is byte-identical.
  - The scope is the row's own game when the sim has that game, else the window.
- `player_name` is NOT rewritten. It is `pick_id`, the venue and odds-history key, and the display name. The test
  pins `pick_id` unchanged.
- Readers that join ENGINE data now read the stamp:
  - `_match_player`;
  - `headshot_url` and `_player_team` (NBA/WNBA branch);
  - `PropSubject.from_board_row` (every evidence layer);
  - `basketball_vs_position_text`.
- `build_layer2_rows` copies the stamp onto the candidate, and `layer2_rows_to_board_cards` onto the card. The key
  is absent on every other row.
- `_flag_out_player_props` (NBA only): also matches the stamp and a unique engine key. It can only ADD a flag, which
  clears an edge. Its log line gains `via_engine_name=`.
- `basketball_market_board._engine_name_raw_keys` (NBA only): book quotes under a split name are attributed to the
  sim player. It never borrows a key that is another attributed player's own exact key.
- New log line: `[nba_projections] NBA_PROP_ENGINE_NAME alias_rows= alias_players= ambiguous_rows= sample= ambiguous=`.
  It prints only when a row resolved or refused. The coverage payload carries `engine_name_resolution`.

Tests: `tests/test_nba_prop_engine_name_join.py`, 32. Every behaviour has an OFF arm (the pre-fix path) that must
differ. They cover:
- the Gary Payton II / Gary Payton ambiguity refusal;
- an exact name never taking the fallback;
- game scoping;
- the board entry point;
- face, side, subject, candidate, card and pick_id;
- the OUT flag;
- the cards board.

Neighbouring suites: 295 + 152 + 162 passed.

## 5. Replay on fleet artifacts (read-only; same grids, fleet code vs this code)

Probe `C:/tmp/nbaname/replay.py`. It runs `board_enrichment.attach_projections` on the book grid with no game
state, which is the pregame view:

| slate | rows with projection (fleet -> fixed) | rows with an edge (fleet -> fixed) |
|---|---|---|
| 11-04 | 3,857 -> 3,923 | 3,811 -> 3,877 (+66) |
| 11-07 | 5,073 -> 5,130 | 4,975 -> 5,032 (+57) |
| 11-08 | 5,095 -> 5,225 | 4,932 -> 5,062 (+130) |
| 11-09 | 5,809 -> 6,048 | 5,516 -> 5,755 (+239) |

- Per-row diff over 27,961 rows: **501 changed, every one stamped, 0 unstamped rows changed.** None of the changed
  rows had a projection before. 492 went from no edge to an edge; the other 9 are no-ladder markets (DD/TD) or
  certainty refusals.
- Herb Jones on 11-09: 41 rows, 40 with a projection, probability and edge. Paul Reed: 67 rows, 66 of each.
  CJ McCollum: 47 of 47. RJ Barrett: 82 rows, 80 of each.
- Readers, 11-09, fixed code on fleet data (probe `readers.py`, ON vs OFF on the same row):
  - Face and side: OFF gave none for any of the 5 players; ON gave all, the same shape as Saddiq Bey's row.
  - Recent form: Herb Jones and Carlton Carrington went from 0 to 10 games.
  - Ladder: OFF none, ON present.

## 6. Expected change on the fleet, stated BEFORE any deploy

- **Grid:** on a typical slate, 2-5 more players and ~60-240 more NBA prop rows carry a pregame projection,
  probability and edge. 0 other rows change.
- **Live:** the same players' live rows become live-edge-priceable (they gain `market_fair_prob_over`). The live
  join's own refusals still apply.
- **Served Layer 2 board (`ranked_all`):** a shortlist, so it gains only the subset of those rows that rank. The
  priced NBA prop row count rises by at most the grid delta. 03:20Z on 11-10 served 20 Herb Jones rows.
  - These rows can now rank on a model edge, be suggested and reach the venue plan.
  - Kalshi in-play entries stay refused (`cd0901bf`).
- **`NBA_PROP_ENGINE_NAME`:** prints on each NBA board build with `ambiguous_rows=0` expected. `OUT_PLAYER_PROPS_FLAGGED`
  is expected to read `via_engine_name=0` unless the feed spells a nickname differently.
- **Reading (MET if):** on the next slate where one of the 8 players has posted props, after the sims build:
  - the served rows carry `engine_player_name`, `sim_projection`, `model_edge_pct`, `player_side` and `headshot_url`;
  - the role log shows `NBA_PROP_ENGINE_NAME alias_rows>0 ambiguous_rows=0`.
- **Roles that run it:** refresh-worker (book grid artifact and Layer 2 shortlist), web (serve-time book grid; cards
  page) and live-odds-worker (the cards context). Confirm with `check_deploy_safety.py` at load time.

## 7. Not done / not claimed

- A player with NO sim entry in the window gets no stamp, so before the day's sims build a split player has no face or
  side. A standard-spelled player does: `player_ids.csv` resolves him without the sim. This is display only, with no
  model either way.
- `live_projection_join._resolve_player` keeps its own index-scoped resolution. It shares the key function but does not
  read the stamp.
- WNBA rows are never stamped. The engine key's aliases are NBA names.
