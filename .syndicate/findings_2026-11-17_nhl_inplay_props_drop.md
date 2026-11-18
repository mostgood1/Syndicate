# NHL in-play props drop — findings (lane `nhl-inplay-props-drop`, Tue 11-17)

Session 8edcf8eb, started by the layer2-rail-monitor session (I-21 / I-22). All readings are read-only on
the fleet (`~/syndicate-prod`), nice 19. Times are UTC with Central in brackets where it matters
(CST = UTC − 6).

## Hypothesis (written to the lane before testing, `0bad47113`)

NHL live player-prop quotes are captured ONLY by `scripts/refresh_nhl_oddsapi.py` inside the single live
odds sweep, so their capture cadence IS the sweep's. When a sweep runs long or is refused `lane_busy`,
every NHL prop row's `seen_age_seconds` crosses the overlay's 300 s in-play window together, and
`select_inplay_rows` drops the whole props set in one build.

**Result: CONFIRMED. 76 of 76 NHL overlay builds 00:07–02:41Z (6:07–8:41 PM CST) fall on the side of
300 s that the hypothesis predicts. The falsification test did not fire.**

## Q1 — which job writes NHL live player-prop quotes, at what cadence, inside the blocked lane?

- **The only writer:** `refresh_odds_sources.py --phase live` → step `nhl_oddsapi_refresh`
  (`_build_nhl_steps`, `scripts/refresh_odds_sources.py:1022`) → `scripts/refresh_nhl_oddsapi.py`
  → `_collect_owned_nhl_artifacts` (`:125`) → `collect_and_write_player_props`
  (`syndicate/local_nhl_odds.py:1093`) → `collect_oddsapi_props` (`:632`, every event of the date, 5
  markets, 10 books) → `_append_nhl_book_quotes(kind="prop")` (`:955`) → the quote shard
  `nhl_source/tracking/book_quotes/<date>.jsonl` + its last-seen state.
- **Yes, inside the blocked lane.** That sweep runs every live sport one after another on the single
  `live-odds-worker` lane. Each sweep does scoreboard → team odds → props for today, then the same for
  tomorrow (`--days-ahead 1`), plus the full generation every 30 min.
- **NHL has no in-play capture of its own.** Every other live sport has a lane on the live-odds-worker's
  30 s capture thread (`scripts/run_live_odds_refresh_worker.py` `_launch_inplay_capture_autoruns`):
  WNBA, NCAAF, soccer, NBA, NCAAB, WNCAAB, NFL. NHL is not on it.
- **Cadence tonight** (oddsapi prop capture instants in the 11-17 shard, since 23:30Z): **18 captures,
  median gap 335 s, max 1,869 s.** In-play gaps from 00:09:03Z, in seconds:
  335, 495, 129, 221, 351, 154, 300, 152, 266, 642, 417, 241, 256, 539, **1,859, 1,869**, then 1,131+
  (open at 02:45Z). **8 of 16** closed gaps exceed 300 s.
  - The median, 335 s, is already ABOVE the 300 s window. So props drop even when no NHL step hangs.
    00:09–01:24Z had no hang: 6 of 14 gaps > 300 s.
- **Other prop sources do not cover it.** Kalshi NHL props (`venue_direct`) have 840 rows in 20 captures,
  median gap 617 s. A game-line row stays fresh while any book saw it within 300 s (row age = the
  freshest cell, `book_grid.py:1311`): Kalshi and Polymarket do that for game lines. Props have no such
  second clock, so they age out as one block.

## Q2 — what window decides `rows_inplay` for a props row?

- **Code path:** `book_grid_artifact._remember_inplay_rows` (`:991`, before the row cap) and
  `_write_inplay_overlay_best_effort` (`:1203`) → `select_inplay_rows` (`:986`) → `is_inplay_fresh_row`
  (`:975`): `game.state == "live"` AND `seen_age_seconds` (else `age_seconds`) `<= limit`.
- **Constant:** `SYNDICATE_INPLAY_OVERLAY_MAX_PRICE_AGE_SECONDS`, default **300**
  (`inplay_overlay_max_price_age_seconds`, `:917`).
- **`seen_age_seconds`** = grid build time − the quote key's last-seen stamp
  (`book_grid._seen_age_seconds`, `:255`). The stamp is refreshed by every capture that SEES the
  quote, moved or not (`odds_book_quotes.append_book_quotes`, state `current + [captured_at]`).
- **The join (capture age at each overlay write vs `rows_inplay`, refresh-worker.log, 00:07–02:41Z):**

  | class | builds | rows_inplay | age of latest prop capture |
  |---|---|---|---|
  | props present | 43 | 464–956 | 3.8–298.3 s |
  | props gone | 33 | 0–99 | 327.8–1,825 s |

  - The boundary is tight. The freshest drop came 327.8 s after a capture (00:14:30Z, 20 rows); the
    stalest full build 298.3 s after one (00:33:41Z, 475 rows).
  - The two 99-row builds (01:41:15 / 01:43:10Z, prop capture 1,034 / 1,149 s old) carried 0 cards:
    non-prop and venue rows, not the props set.
  - Per UTC hour: 00Z **9 of 42** builds dropped (2 before the first in-play capture); 01Z **11 of 19**;
    02Z to 02:41 **13 of 15**. The 01Z build count fell because the refresh-worker was overloaded
    (rail monitor reading 14).
- **Replay on the fleet's own grid** (`book_grid_2026-11-17.json`, generated 02:44:34Z; the rule
  re-applied read-only):
  - **477** live rows: **459 props, 18 game lines**.
  - **317 of the 459 props sit in ONE seen-age minute (18 min)**: the 02:26:09Z capture, the last.
    The rest are older (lines the books stopped quoting).
  - **Kept at 300 s: 6 rows, 0 props.** It would also be 0 props at 450, 600 and 900 s.
  - So the props leave together because they were seen together, by one capture.
- **Effect, time-weighted** (gap − 300 s, summed over 00:09–02:45Z):
  - **4,938 of 9,357 s (53%)** of tonight's NHL in-play window had no fresh live props on the overlay;
  - **979 of 4,498 s (22%)** in 00:09–01:24Z, before the hangs.
  - While the overlay has none, web keeps only what the shortlist carries for those lines. The shortlist is
    rebuilt only about every 12–14 min (`intelligence_state._merge_inplay_overlay`). The rail monitor
    measured the merge going 272 → 1 → 7 → 180 NHL cards around 00:22Z.

## The third hang tonight (production state at 02:45Z — NOT acted on)

- `refresh_nhl_oddsapi.py --date 2026-11-17 --days-ahead 1` pid 138879: started ~02:25:36Z, **1,165 s at
  1.2% CPU** at 02:45:00Z. This time WITHOUT `--mode fast`, so the full generation was due.
- It captured the props at **02:26:09Z, at the START of the run**, then stuck. Live sweeps at 02:28,
  02:36 and 02:43Z were refused `lane_busy` (run pid 138663).
- The fix for the lane belongs to lane `odds-lane-sport-deadline` (I-22, session bb342d07). Ending the
  child early is a production action for the user.

## Q3 — what should the board show per line when a props quote lapses?

Today: the props drop. The overlay drops every lapsed line, and web falls back to the 12–14-min
shortlist. With one capture clock, every line lapses at once. The display choice is put to the user. See
"Decisions owed".

## The props-side fix (built, OFF by default — see the lane for the commit)

An NHL in-play props pull on its own clock, outside the shared sweep: the lane every other live sport
already has.
- **Its own lane:** a 120 s gate on the live-odds-worker's 30 s capture thread.
- **Live games only:** OddsAPI `/events` (free), then games that started under 4 h ago.
- **Each pull:** one `event_odds` call per live game: the same 5 prop markets and 10 books as the sweep.
  No fallback retries, no historical calls.
- **The same writer:** `_append_nhl_book_quotes(kind="prop")`.
- **Bounded:** one child at a time, killed past 90 s. It never calls the NHL web API, which is what hung
  tonight.

Each line's last-seen stamp then refreshes every ~2 min, whether or not the sweep is blocked.

**Cost (upper estimate):**
- 5 credits per live game per pull;
- tonight's 11 games ≈ 28.6 live game-hours × 30 pulls/h × 5 ≈ **4,300 credits per 11-game night**;
- **0.09% of the 5M monthly cap**, about 2.6% of a pro-rata day (166,667).

`record_oddsapi_quota` records every call, so the real spend is measurable.

## Prediction for the next NHL night (a weeknight slate of ~10 games)

| state of the fleet | NHL overlay builds with props gone | share of in-play time with no fresh props |
|---|---|---|
| unchanged | 9–13 per UTC hour (tonight 33 of 76) | ~50% with a hang, ~20% without |
| I-22's per-sport deadline only | ~7–9 per hour | ~20% (the 335 s median gap stays) |
| + the NHL in-play props pull loaded (120 s) | **≤ 1 per hour** (two pulls in a row must fail) | **≤ 5%** |

The reading that grades it is this file's join: `rows_inplay` per build against the age of the newest
oddsapi prop capture, from `refresh-worker.log` and the shard.

## Decisions owed (the user's)

1. **Display when a line's quote lapses** — today it drops. The alternative: keep the last price, marked
   as aged.
2. **Load the NHL in-play props pull** — the cost above, a live-odds-worker restart, and the switch on.
