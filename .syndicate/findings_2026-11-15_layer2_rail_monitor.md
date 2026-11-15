# Layer 2 Games Rail — standing monitor, 2026-11-15 (lane `layer2-rail-monitor`)

Production = the fleet at `http://127.0.0.1:10000`. Times are Central (CST) unless marked Z.
Readings are append-only, one dated block each. Each says what was measured, the denominator,
and where the data came from.

## How a reading is taken

- `scripts/layer2_rail_monitor_probe.py` (read-only, run at Idle priority). It writes
  `C:\tmp\railmon\readings\<stamp>\` (raw payloads + `reading.json`), plus
  `readings.jsonl` (one line per reading) and `flags.jsonl` (every shown flag, kept for
  grading against finals).
- **The rail is computed by the SERVED page's own code.** `scripts/layer2_rail_monitor_run.mjs`
  slices these out of the `/intelligence` HTML that was served, so the reading follows any
  rail change another lane loads: `deriveGameCards`, `chipForGame`, `gameKey`,
  `mergeLiveRailFresh`, `liveRailSummary`, `liveRowFreshEdge` and `matchesDateFilter`. It
  runs them over:
  - the page's own board query (`/api/intelligence/query`, the page's exact payload,
    `background: true`);
  - the chips (`/api/board/game-chips`, all nine sports);
  - the third of three `/api/board/live-rail` reads, ~10 s apart.
  The default rail is today, Central, as the page opens it.
- **The flag cross-check is independent.** From each live row's own fields, the probe
  re-derives the rule:
  - gap >= 3 pp. The gap is the live sim probability minus the no-vig fair; if that is
    missing, a `live_aware` row's `model_edge_pct`;
  - `book_age_seconds` <= 120 s at pricing;
  - age now <= 300 s. Age now = priced age + time since `price_grid_generated_at`, else the
    page's `boardBuildEpochMs` rule.

  Counts: **false** = shown but not qualifying; **missed** = qualifying but not shown;
  **dark** = gap and fresh pricing, but the price is now > 300 s old.
- **Team-mismatch detectors** are those of `tests/js/game_rail_production_replay.mjs`, run
  with the probe's OWN chip join (learnings 2026-09-16 FORBIDDEN). Detector 3 is the one that
  sees the 09-16 shape. The probe also counts chip-less cards (with their rows), flipped
  home/away, abbreviations that look truncated, and live chips with no live card.
- **Fleet logs** (last 30 min, nice 19): from refresh-worker `INPLAY_OVERLAY` /
  `BOOK_GRID_TICK` / `LAYER2_BOARD_HEALTH` / `LIVE_GAMELINE_JOIN`, and from web
  `INPLAY_OVERLAY_MERGED`.

## Reading 1 — Sun 11-15 10:45 AM CST (16:45Z)

Slate: 1 game live, NE @ DET (NFL, London 8:30 AM CST kickoff). The noon NFL window and
college basketball start ~12:00. Default rail = 133 cards (wncaab 68, ncaab 38, nfl 12, nba 9,
nhl 5, ncaaf 1). Chips today: 131.

**Load** (curl-equivalent, from this host):

| request | time | wire | body |
|---|---|---|---|
| `/intelligence` (page + embed) | 2.3 s (5.6 s at 10:35) | 3.6 MB gz | 20.3 MB |
| `/api/intelligence/query` (page's own query) | 18.4 s (19.0 s at 10:36, 33.4 s at 10:42) | 9.8 MB gz | 57.0 MB |
| `/api/board/layer2-shortlist` | 0.9 s (1.1 / 2.5 s earlier) | 0.13 MB | 0.80 MB |
| `/api/board/game-chips` (9 sports) | 0.20 s | 0.05 MB | 0.35 MB |
| `/api/board/live-rail` | 0.016-0.22 s | — | 3.8-6 KB (2-6 rows) |

- The page query is the heavy item: 57 MB uncompressed, 18-33 s. That is the "~80 s after the
  embed paints" the board rail waits for, before browser parse.

**Refresh:**
- Board build (`state_meta`) 407 s old.
- Shortlist `written_at` 600 s old (`build_age_seconds` 559).
- `/api/board/live-rail` newest overlay 24 / 35 / 45 s old over three reads.
- NFL in-play overlay, last 30 min: 16 builds; gap p50 80 s, p90 238 s, **max 348.5 s**
  (16:33:33 -> 16:39:22Z). Web's cutoff is 360 s.
- NFL grid `build_seconds`: p50 31.9 s, p90 86.7 s, **max 122.0 s**, and rising toward the
  noon slate (recent ticks 21.1, 46.1, 86.7, 122.0 s).
- `deferred_slow: ["nfl"]` on 2 of 21 ticks. Web merged NFL fresh 19 of 19.

**Live recommendations:**
- 1 live card, 3 markets.
- **0 flags shown; 0 false, 0 missed, 0 dark.**
- 7 live rows. Priced age p50 157 s (0 of 7 <= 120 s). Age now p50 293 s, 3 of 7 > 300 s.
- NFL can flag only on the moneyline today: NFL live totals and spreads carry no
  `live_model_probability` (`LIVE_GAMELINE_JOIN nfl considered=56 priceable=0 withheld=56`,
  `prob_interval_swamps_edge`; also lane `nfl-live-width-fit`).
- The ML row (DET -10000) has sim 95.3% vs fair 98.5%, a gap of -3.2 pp. Correctly unflagged.

**Teams:**
- det1 / det2 / det3 = 0 / 0 / 0. 0 flipped. 0 truncated abbrs. 0 live chips without a live
  card.
- **2 of 38 NCAAB cards chip-less.** Both have clean keys, so it is not a name mismatch. In
  both, the odds feed's schedule disagrees with ESPN's:
  - **Florida A&M @ UTEP**, 3 rows. OddsAPI `commence_time` is 2026-11-16 01:00Z (Sun 7 PM CST).
    ESPN has event 401929419 at **2026-11-16 19:00Z (Mon 1 PM CST)**, 18 h later. So the board
    files it under today, with no chip.
  - **Washington @ Utah**, 3 rows. OddsAPI has 2026-11-15 19:00Z (event
    `b7e664d76ab994de4f92bccb1f592097`, 165 quote rows in today's ncaab shard). ESPN's D1
    scoreboard (groups=50) has **no Washington @ Utah game 11-14..11-17**; the nearest is
    Eastern Washington @ Utah on 11-18 01:30Z. Not in the wncaab chips either.
- Owner: none (upstream schedule data, not the rail join). Logged as a lead. If ESPN never
  lists the game, the card stays chip-less all day; watch it at 1 PM.

**Registered before the noon slate (prediction, to be read 12:30-1:30 PM CST):**
- With ~10 NFL games live, NFL's grid build will exceed the 45 s slow-sport threshold on most
  rounds. NFL will then be `deferred_slow` every other round.
- So the NFL in-play overlay gap will pass web's 360 s cutoff at least once in that hour, web
  will log `nfl: 'stale_...'`, and live NFL rail rows will fall back to the shortlist.
- **Falsified if** NFL overlay gaps stay <= 360 s with 0 stale web merges over 12:30-1:30 PM.
