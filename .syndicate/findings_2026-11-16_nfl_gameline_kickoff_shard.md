# NFL game-line quotes filed by Central kickoff date — lane `nfl-gameline-kickoff-shard`, todo `#817`

Session a64727a8 (side session of local_62433e58), 2026-11-16. Defect found by lane `layer2-rail-monitor`
(`.syndicate/findings_2026-11-15_layer2_rail_monitor.md`, "DEFECT — NFL game-line quotes are filed by the
UTC date").

## Hypothesis (written before the test, in the lane block)

`fetch_nfl_team_odds_local._append_nfl_team_book_quotes` writes every NFL game-market quote under the UTC
date of the capture. From 00:00Z (6 PM CST) all NFL game lines therefore go into tomorrow's shard,
including a live night game's in-play lines, and the Central date's board, in-play overlay and live-rail
never read them. Filing rows by `kickoff_shard_date(row)` puts them in the Central kickoff date's shard.
Pre-game lines of later games move to their own kickoff-date shards, which every board reader already reads.

**Falsification:** a read-only replay of the fleet's 11-15 and 11-16 shards does not put SNF's
01:22-01:53Z game rows under 11-15; or a reader relies on today's shard holding every upcoming NFL game's
game lines.

## Fix (code on main `ed63c7611`; todo #817 -- its first commits say 816, see the todo entry)

- `_append_nfl_team_book_quotes` buckets its rows with `odds_book_quotes.bucket_quote_rows_by_kickoff_date`.
  It appends each bucket under its Central kickoff date, with ONE `captured_at` for all buckets.
- A row with no parseable `commence_time` is not filed under any date. It is counted, with its event ids,
  on the always-printed `[odds_book_quotes] NFL_GAMELINE_QUOTE_SHARD basis=... shards=... unfiled_no_commence_time=N`
  line. This mirrors the NCAAF game-line writer and `kickoff_shard_date`'s own rule.
- **Off switch:** `SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD=0` (false/no/off). It restores the single
  UTC-capture-date write exactly, and the line then says `basis=utc_capture`.
  - **Default ON.** The writer runs in a child process (`ops_refresh.launch_refresh_run` →
    `refresh_odds_sources.py` → `refresh_nfl_oddsapi.py` → `fetch_nfl_team_odds_local`). It reads the
    checkout at each launch, so **a fleet ff alone loads it at the next NFL lines run, with no worker
    restart.** Env is built only at `up`, so a default-off switch would need a full down/up.
- **Not changed:** `fetch_nfl_preseason_odds._append_nfl_preseason_book_quotes` has the same UTC filing.
  But its reader `nfl/preseason_cards.py` opens grids by the game's UTC start date (`start_time[:10]`),
  so the writer and the reader must move together. Preseason is dormant until 2027-08; recorded under `#817`.

## Tests — `tests/test_nfl_gameline_kickoff_shard.py`, 18 pass

They run the REAL `append_book_quotes` into a temp data root and read the files back:
- off != on (same capture: `2026-11-15` on, `2026-11-16` off);
- every off spelling, and absent = on;
- SNF shape: kickoff 01:20Z, captured 01:45Z 11-16, full-game AND q1 rows land in `2026-11-15`;
- one Monday capture splits into MNF → 11-16, TNF (01:15Z Fri) → 11-19 (Central Thursday), next Sunday → 11-22;
- MNF captured in play at 01:40Z 11-17 stays on 11-16;
- null and blank kickoffs are not filed, are counted (8 rows), and are named on the printed line. The known
  game still files, and `rows` = filed + unfiled;
- the branch line also prints on the off path; empty input writes nothing; a failure never raises;
- `main()` still hands bulk events plus segment payloads to the writer.

Also re-ran `test_nfl_segment_request_reachability`, `test_all_sports_segment_wiring` and `test_pinnacle_capture`:
53 pass together.

## Replay — fleet shards, READ-ONLY

- **Run:** 2026-11-16 ~21:30Z, at nice 19 / ionice idle.
- **Script:** `C:\tmp\nflks816\replay_shards.py`. It uses the fleet checkout's own `kickoff_shard_date`
  at `db463b5be`.
- **Output:** `C:\tmp\nflks816\replay_1115_1116.json`.
- **Data:** `~/syndicate-prod/data/nfl_source/tracking/book_quotes/2026-11-1{5,6}.jsonl`, substrate fleet.
  The 11-16 shard was read mid-day, through ~21:19Z.

**SNF (PIT @ CIN, kickoff 01:20Z, live from ~01:22Z): falsification NOT met, hypothesis holds.**

| 11-16 shard, SNF game rows | full | quarter/half |
|---|---|---|
| captured 01:22-01:54Z | 1,505 | 396 |
| → kickoff shard under the new filing | **all 1,901 → `2026-11-15`** | |
| all in-play (captured ≥ commence) | 6,814 | 1,290 |
| pre-game captured 00:00-01:20Z | 896 | 273 |

- Last SNF game row in the 11-15 shard: 23:58:52Z. Last one in the 11-16 shard: 04:25:51Z.
- Every event's game rows in the 11-16 shard start at **00:00:17Z**. That is the first capture after UTC
  midnight: a full snapshot of every NFL event, because a new shard has no last-seen state.

**What moves (sportsbook `kind=game` rows; props and venue rows already file by kickoff and all stay):**

| shard | game rows | stay | move | moved to |
|---|---|---|---|---|
| 2026-11-15 | 122,627 | 118,566 | 4,061 (3.3%) | 11-16: 778 (MNF), 11-19: 591 (TNF), 11-22: 2,513, 11-23: 179 (next MNF) |
| 2026-11-16 | 22,551 | 1,355 (MNF) | 21,196 (94.0%) | **11-15: 10,668**, 11-19: 1,204, 11-22: 8,308, 11-23: 1,016 |

- Of the 10,668 rows going 11-16 → 11-15: SNF is 9,273. **The other ~1,395 belong to the three
  late-afternoon games** (SEA @ LV and LAR @ ARI 3:05 PM CST, SF @ DAL 3:25 PM CST): their in-play lines
  captured after 6 PM CST were misfiled too. So the defect also hits the end of every late-afternoon
  game, not only night games. (Not split by quarter here.)
- 0 rows with a null kickoff in either shard. 0 unparseable rows.
- **Size:** the 11-15 shard's game rows are 52.8 MB of its 224 MB (props dominate). Re-filed, it gains
  4.8 MB from the 11-16 shard. A game now accumulates its whole week in one shard instead of one full
  re-snapshot per UTC day, so the total game rows written should FALL. The 11-16 shard re-wrote every
  event from 00:00:17Z.

## Readers — named, with what changes

Production readers of NFL game-line shards:

1. **In-play overlay + Games Rail.** `book_grid_artifact._write_inplay_overlay_best_effort` builds the
   overlay from date D's grid, and web's `inplay_overlay_cards(date)` reads only the board date's overlay.
   - **Changes, and this is the fix:** night-game and late 4th-quarter in-play rows now reach the Central
     date's grid, overlay and `/api/board/live-rail`.
   - Before, refresh-worker built a separate `INPLAY_OVERLAY sport=nfl date=<D+1>` that nothing read.
2. **Refresh-worker grid tick** (`run_refresh_worker._run_book_grid_artifact_tick`).
   - Today's NFL grid now sees the in-play pulls. Price-on-pull (`_book_grid_sports_with_new_live_quotes`,
     today's shard mtime) and the live cadence (`live` = today's grid has in-play rows) now fire for NFL
     after 6 PM CST. Before, they could not.
   - **One real change:** upcoming games' pre-game rows on the LAYER 1 market board come from their own
     kickoff-date grids. NFL's 7-day window is in `_book_grid_forward_days` / `_sport_covers_date`.
     Those grids are built at the FORWARD cadence (`_BOOK_GRID_FORWARD_INTERVAL_MULTIPLE` = 6× the
     grid interval) instead of today's.
   - NFL props and NCAAF game lines already work this way. Layer 2 reads raw shards, so it is not affected.
3. **Layer 1 board** (`layer1_board.artifact_read_dates` + `merge_grid_rows_across_dates` + the local-date
   filter). No change needed.
   - It reads window ∪ next days ∪ today.
   - When one market sits in two grids, the fresher copy (`updated_at`) wins.
   - Every row is filtered by its own Central game date.
4. **Layer 2 shortlist** (`layer2_shortlist`). No change needed.
   - It reads `read_book_quotes_latest` for every date of NFL's 7-day slate window, and `last_seen` takes
     the newest across dates.
   - Projections are joined over the window (`#587`).
   - Next week's MNF (Central D+7) leaves day D's read set. That is outside the window by design.
   - The served 11-16 shortlist (read ~21:3xZ) carried NFL cards for 11-17..11-22 only, nothing for 11-23.
5. **`#802` market-gone drop** (`_drop_market_gone_rows`). No change needed.
   - Its judging files are the UTC commence date, the Central kickoff date and the selected date.
   - Only a file that holds the row's group judges, and EVERY judge must say `market_gone`. So a stale
     pre-load copy in the UTC file cannot drop a row that the Central file keeps fresh.
6. **Moved-kickoff drop** (`drop_events_moved_to_another_date`). It acts only on rows "this shard filed by
   its own kickoff", which NFL game lines now are. So it now covers NFL game-line kickoff moves, as designed.
7. **CLV close** (`clv_join._candidate_shard_dates`). No change: it reads the Central date and then the
   UTC date, so it finds both pre-fix and post-fix rows.
8. **Movement / openings on Layer 2 cards.** No change: they read our own opening ledger
   (`clv_opening_ledger.load_openings(date)`) and price trail, not the quote shard.
9. **Settlement closes** (`emit_settlement_inputs`: `closing_quotes(iter_book_quotes(sport, date))`) and
   paper policy (`decision_policy_paper`). These read one date shard.
   - **Improves:** a night game's true close now sits in its own date's shard. Before, SNF's last
     pre-kickoff quote in the 11-15 shard was 23:58:52Z, 1h21m before kickoff.
10. **`/api/ops/quote-feed-age`** (`quote_feed_age.feed_age`, one date shard). On a day with no NFL game,
    NFL now reads UNKNOWN ("no quote shard for this sport and date"), as NCAAF and soccer already do.
    No caller found under `scripts/`.
11. **`/api/board/book-grid` live-pivot fallback and the cross-book endpoint** (`blueprints/intelligence.py`
    `read_book_quotes(sport, selected_date)`). A date's shard now holds that date's games, as for every
    other sport.
12. **`nfl/preseason_cards.py`.** Unchanged, because the preseason writer is unchanged.

## Today's split 11-16 shard — recommendation: LEAVE IT

What it holds:
- SNF and late-afternoon in-play rows (games of 11-15);
- MNF pre-game rows (correct);
- 10,528 next-week pre-game rows captured 00:00Z until the load.

Why not move or rewrite it:
- The shards are append-only change logs. The grid's incremental reader (`read_grid_quote_rows`, `#790`)
  keeps a per-shard reduce and parses only appended lines, so a rewrite under it risks today's grid.
- No reader needs those rows moved:
  - The 11-16 board filters out the 11-15 games by game date.
  - Next week's games read fresher copies from their kickoff shards (Layer 1 `updated_at`, Layer 2
    newest `last_seen`).
  - `#802` needs every judge to agree.
  - CLV reads the Central and UTC dates.
- From 11-17 nothing reads the 11-16 shard for next week's games, because the window moves.
- Transitional and cosmetic: until each forward grid rebuilds after the load, the 11-16 Layer 1 board can
  show the 11-16 copy of a next-week market. Prices match it; its seen-age is older.

## Fleet verification owed (after the user's load)

During MNF 11-16 (LAC @ BAL, 01:15Z 11-17):
- the NFL lines run log prints `NFL_GAMELINE_QUOTE_SHARD basis=kickoff_central`;
- NFL game rows with `captured_at` ≥ 00:00Z 11-17 land in `2026-11-16.jsonl`, and none in `2026-11-17.jsonl`;
- `INPLAY_OVERLAY sport=nfl date=2026-11-16` carries MNF in-play rows;
- `/api/board/live-rail` serves NFL game-line rows for MNF with seen-age at overlay cadence.

Before the load the falsifier is the opposite: MNF in-play rows in `2026-11-17.jsonl`.
