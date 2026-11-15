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
- **Peer note, 11:0x AM** (session 0f519972 / [Layer 2 rail: live edge line](#local_208683f1-10cc-4da1-8a83-c2e1ab44d604),
  lane `ncaaf-grid-build-speed`). NFL's own grid compute is about 6 s: pivot 3.2 s plus a 1-2 s
  parse over 41,674 kept rows. The long builds line up with the Kalshi odds tick and paper
  settlement in the same process, apparently competing for the GIL:
  - 68 builds between 15:30 and 17:10Z, split at the median build time;
  - `kalshi_odds` lines logged during a build: 40.1 average in the long half, 0.0 in the short;
  - this is a correlation, not a proven cause.
  - **So the 1:30 PM reading also runs `C:\tmp\railload\nflcontend.py 18:30Z 19:30Z`
    (read-only).** It counts Kalshi / paper-settlement overlap per NFL build, so a stale
    overlay can be put down to contention or to the slate's size.

## Reading 2 — Sun 11-15 11:08 AM CST (17:08Z)

Slate: 5 live cards on the default rail (133 cards): NFL 1 (NE @ DET, Q4 12:51), WNCAAB 3,
NCAAB 1. The 11:00 college tips are live.

**Load:**
- `/intelligence` 11.5 s / 20.7 MB. This is variance against 2.3-5.6 s earlier; one read, so
  not a trend.
- Query 8.5 s / 58.4 MB (10.2 MB gz). Shortlist 1.7 s. Chips 0.06 s. Live-rail 0.016 s (~20 KB,
  16-20 rows).

**Refresh:**
- Board build 163 s old; shortlist `written_at` 163 s.
- Live-rail newest 66 / 76 / 3 s over three reads 10 s apart: a new overlay landed between
  reads 2 and 3.
- Overlay gaps, last 25 min:

  | sport | builds | gap p50 / p90 / max |
  |---|---|---|
  | NFL | 22 | 72.5 / 112.7 / 130.0 s |
  | WNCAAB | 3 | 111 / 162 s |
  | NCAAB | 2 | 75 s |

- NFL grid build p50 31.8 s, max 70.2 s, 0 `deferred_slow` in the window. Tick gap p50 64 s,
  max 150 s.
- Web merges: nfl 17/17, ncaab 3/3, wncaab 3/3 fresh, 0 stale.

**Live recommendations:**
- **1 flag shown, on 1 of 5 live cards. 0 false, 0 missed, 0 dark.**
  - NCAAB Quinnipiac @ Central Connecticut, total **o137.5**: ours 151.7, sim 79.9% vs fair
    48.3%, **+31.6 pp**. Priced on a 40 s quote, 203 s old at the read, 8 minutes after tip.
  - Source row: `layer2_shortlist`, not the overlay.
  - Logged to `flags.jsonl` for grading against the final. #780's prior: early-game live
    totals' big gaps realised ~0.
- 25 live rows. Priced age p50 178 s, p90 259 s; **5 of 25 <= 120 s**. Age now p50 263 s,
  p90 420 s; **9 of 25 > 300 s**. 0 rows with no fair.
- **4 of 8 live markets have no OURS**, all expected:
  - NFL spread: blank by decision (lane margins graded FAIL).
  - NFL 2H Total, Q3 Spread, Q3 Total: the live NFL chip carries `intervals.source=live_resim`
    with **0 periods** in all three readings so far (Q3 7:24 -> Q4 12:51). This is #767 (c):
    live re-sims publish the projected final only, and per-period blocks are not built.
- 1 live card with no lines at all: WNCAAB **WGA @ UML**, chip-seeded, 0 board rows. No odds
  for the game; not a defect.

**Teams:**
- det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated. 0 live chips without a live card.
- Chip-less NCAAB cards unchanged: 2 of 38 (FAMU @ UTEP, Washington @ Utah; reading 1).

## Reading 3 — Sun 11-15 11:21 AM CST (17:21Z)

5 live cards (NFL 1, WNCAAB 3, NCAAB 1) of 133. The page fetch was skipped (`--no-page`); the
rail code was the 11:08 served copy.

**Load:** query 13.4 s / 59.3 MB (10.4 MB gz). Shortlist 0.75 s. Chips 0.70 s. Live-rail
0.016 s, 9-12 rows.

**Refresh:**
- Board build 57 s old.
- Live-rail newest 68 / 6 / 16 s.
- Overlay gaps, last 15 min:

  | sport | builds | gap p50 / p90 / max |
  |---|---|---|
  | NFL | 10 | 62 / 113 / **271** s |
  | NCAAB | 11 | 76 / 134 / 141 s |
  | WNCAAB | 9 | 102 / 143 / 196 s |

- NFL build p50 32.8 s, max 70.2 s. `deferred_slow` nfl on 1 of 21 ticks. Tick gap p50 43 s,
  max 92 s.
- Web merges: nfl / ncaab / wncaab fresh 19 / 19 / 19, 0 stale.

**Live recommendations:**
- **2 flags shown, on 2 of 5 live cards. 0 false, 0 missed, 0 dark.**
  - WNCAAB EMU @ UK, **u140.5**: ours 127.3, sim 82.4% vs fair 50.0%, **+32.4 pp**. Priced on a
    49 s quote, 105 s old now.
  - WNCAAB SAM @ PUR, **u138.5**: ours 131.2, sim 63.2% vs 49.1%, **+14.1 pp**. Priced on 65 s,
    122 s old now.
- The 11:08 flag (QUIN @ CCSU o137.5) is gone, **with the line unchanged at 137.5**. OURS moved
  151.7 -> 144.6 in 13 min, which put the gap under 3 pp. So the live sim's total moved 7.1
  points in 13 min of game time while the book's did not. This goes to the outcome grade,
  together with #780's prior.
- 23 live rows. Priced p50 131 s, p90 327 s; **11 of 23 <= 120 s** (5 of 25 at 11:08). Age now
  p50 190 s, p90 415 s; 6 of 23 > 300 s. 0 rows with no fair.
- **4 of 11 live markets have no OURS**, all NFL and all known:
  - Spread: blank by decision.
  - 2H Spread, 2H ML, Q4 Spread: there are no live period blocks, #767 (c).
- `flags.jsonl` holds 3 rows (one per flag per reading). Grading dedupes on
  (game, market, segment, side).

**Teams:** det1 / det2 / det3 0 / 0 / 0; 0 flipped; 0 truncated. The same 2 chip-less NCAAB
cards. WGA @ UML is live with 0 lines.
