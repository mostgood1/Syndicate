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

## Reading 4 — Sun 11-15 11:45 AM CST (17:45Z)

4 live cards (WNCAAB 3, NCAAB 1). NE @ DET is final; NFL `rows_inplay_last=0`. The served page
was re-read.

**Load:**
- `/intelligence` 6.5 s / 20.2 MB.
- Query 6.9 s / 57.4 MB (10.0 MB gz).
- Shortlist 0.55 s. Chips 0.31 s. Live-rail 0.016 s, 38 rows (~40 KB).

**Refresh:**
- Board build 265 s old. Shortlist `written_at` 337 s.
- Live-rail newest 33 / 43 / 53 s: the same build, read three times.
- Overlay gaps, last 24 min:

  | sport | builds | gap p50 / p90 / max |
  |---|---|---|
  | NCAAB | 16 | 66 / 198 / 205 s |
  | WNCAAB | 17 | 72 / 195 / 203 s |
  | NFL | 9 | 130 / 281 / 316 s (game ending) |

- NFL build p50 27.1 s, max 84.8 s. `deferred_slow` nfl on 2 of 27 ticks.
- Web merges: nfl / ncaab / wncaab fresh 19 / 19 / 19, 0 stale.

**Live recommendations:**
- **0 flags on 4 live cards; 0 false, 0 missed, 0 dark.**
- **The quotes went old.** 40 live rows:
  - priced age p50 265 s, p90 522 s; **only 1 of 40 <= 120 s** (11 of 23 at 11:21);
  - age now p50 319 s; **29 of 40 > 300 s**.
  - So no row could have flagged, whatever its gap.
- **It is partly OUR lag, not only the books.** On the 17:44:48Z overlay rows (38, from
  `/api/board/live-rail`), `quote_seen_age_seconds` (when we last looked) was median 216 s at
  pricing (values 187 / 216 / 298 s), against the ~78 s measured after #786's price-on-pull.
  - NCAAB pull heartbeats 17:35:43 -> 17:45:58Z had gaps of 42 / 65 / 137 / 44 / 38 / **203** /
    86 s; the 203 s hole is 17:41:09 -> 17:44:32Z.
  - In-play pulls with changed full-game lines over 25 min (`pull_cadence.py`): WNCAAB 17,
    median gap 51 s, p90 170 s, max 247 s. NFL 7, median 131 s. **NCAAB 1** (one live game).
  - Read: one build, during the pre-noon pull burst (about 30 games tip at 12:00).
    **Not yet a pattern.** The probe now records seen age at pricing on every reading, so this
    is tracked from here.
- 0 rows with no fair. 0 of 9 live markets lack OURS.

**Teams:** det1 / det2 / det3 0 / 0 / 0; 0 flipped; 0 truncated; 0 live chips without a live
card. The same 2 chip-less NCAAB cards.

## Reading 5 — Sun 11-15 12:02 PM CST (18:02Z), right at the noon tips

5 live cards: WNCAAB 4 (2 flags), NCAAB 1. **2 flags, 0 false, 0 missed, 0 dark.**
- **Our lag is back to normal:** seen age at pricing p50 13.4 s, p90 276 s. Reading 4's 216 s
  median did not persist.
- 10 live rows, 6 of them <= 120 s at pricing.
- Query 24.8 s / 57.7 MB. Shortlist 2.6 s. Board build 465 s old.
- **The noon round left a hole:**
  - tick gap max 320.7 s;
  - NCAAB overlay gap max 327 s, WNCAAB max 332.5 s, against web's 360 s cutoff;
  - NFL build max 120.3 s, NBA 57.7 s.
- Web merges:
  - nfl stale 12 of 12. No live NFL game between NE @ DET's final and the 12:00 kickoffs, so
    this is expected.
  - ncaab / wncaab fresh 12 / 12.
- **`/api/board/live-rail` served 0 / 0 / 11 rows over three reads** with college games in play.
  The per-sport counts were ncaab 0 / 0 / 0 and wncaab 0 / 0 / 11.

**The 0-row live-rail reads, measured on the role logs:**
- The college in-play overlay sometimes publishes **`cards=0` while it holds in-play rows**:
  - WNCAAB: **27 of 60 builds today** (26 of 195 on 11-14);
  - NCAAB: 9 of 185 (1 of 204);
  - NHL: 4 of 173 (24 of 140 on 11-14).
- Example: WNCAAB 17:56:11Z — `LIVE_GAMELINE_BUILD withheld_by_reason={"quote_older_than_live_pricing_ceiling":28}`,
  then `INPLAY_OVERLAY rows_inplay=13 opportunities=19 cards=0`. The live-rail then has nothing
  to swap, and those games' rail lines come from the ~10-15 min shortlist build.
- **H0, "our pulls went stale": falsified for 17:48-17:56Z.** The pull heartbeats covered both
  live WNCAAB events (EMU @ UK, SAM @ PUR) every 21-85 s through that window. The 3-4 min pull
  holes (17:55:05 -> 17:58:13 -> 18:02:35Z) came only after it.
- **H1, "halftime / intermission": supported, n = 3 games.**
  - The 0-card window matches halftime of the 11:00 tips. At 12:07 PM, EMU @ UK read Q3 4:45,
    SAM @ PUR Q3 6:41 and QUIN @ CCSU H2 17:51.
  - The books' full-game prices stand still at the break, so every quote passes the 120 s
    ceiling and the overlay keeps nothing.
  - On 11-14, NHL's 24 zero-card builds fit the same shape (intermissions). Not joined yet.
- Read: **probably by design** (a market at a break is not priceable). But the rail goes blank
  for that game at the break.
- The probe now logs `zero_card_builds_with_rows` per sport and each live chip's clock, so the
  join can be made on more breaks before anyone is asked to change anything.

## Reading 6 — Sun 11-15 12:07 PM CST (18:07Z), 7 minutes into the noon NFL window

**33 live cards** (WNCAAB 18, NCAAB 8, NFL 7) of 133.

**Load:**
- Query **15.8 s / 61.4 MB** (10.8 MB gz).
- Shortlist **4.0 s**. Chips 0.83 s.
- Live-rail 0.17 s, **0.45 MB, 277 / 472 / 488 rows**. The page polls this every 15 s.

**Refresh:**
- Board build 789 s old; shortlist `written_at` 910 s. The shortlist is lagging; the board was
  not rebuilt across the noon round.
- Live-rail newest 41 / 8 / 10 s.
- `deferred_slow` nfl 1, nba 1.
- Web merges: nfl stale 7 of 9 (the overlay was rebuilding after kickoff), fresh 2;
  ncaab / wncaab fresh 9 / 9.

**Live recommendations:**
- **11 flags on 6 of 33 live cards. 0 false, 0 missed, 1 dark.**
- By sport: NCAAB 9 (QUIN @ CCSU 3, BOISE @ NEB 3, NORF @ GAST 2, LOU @ MEM 1). WNCAAB 2
  (EMU @ UK u128.5 +26.1, VAN @ IOWA u152.5 +5.8).
- Largest gaps: QUIN @ CCSU o143.5 +21.3 and h2 o71.5 +21.2; BOISE @ NEB u164.5 +24.7.
- Dark: LOU @ MEM moneyline home, +7.1 pp, priced on 68 s, now 355 s.
- 246 live rows:

  | measure | p50 | p90 | count |
  |---|---|---|---|
  | priced age | 132 s | 343 s | 122 of 246 <= 120 s |
  | seen age at pricing | 38 s | 178 s | — |
  | age now | 166 s | 406 s | 57 of 246 > 300 s |

  0 rows with no fair.
- **37 of 61 live markets have no OURS. 33 of the 37 are NFL: every NFL market on all 7
  games.**
  - The NFL live chips carry no `intervals` block (`game_chip_intervals ATTACHED ... nfl:none:live=7`).
  - Cause: **first-tick latency, not a dead re-sim.** `NFL_LIVE_RESIM` ticks every ~6-7 min. The
    18:01:46Z tick saw 0 games in progress; the first tick on the noon games was **18:09:57Z**:
    `live_games=7 live_resimmed=3 refused=4 (uninformative_probability) elapsed_seconds=58.0`
    of a 90 s budget.
  - So for ~10 min after kickoff the NFL rail has no OURS. Watch the 58 s / 90 s budget with 7
    games (plus 3-4 more at 3:05 PM).
- The other 4: WNCAAB h2h 2 of 3, WNCAAB spread 1 of 1, NCAAB h2h 1 of 4.
- **16 of 33 live cards show no live lines at all:** WNCAAB 12, NCAAB 3, NFL 1. Most tipped
  minutes earlier. Re-read next time before calling it anything.

**Teams:** det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated. 0 live chips without a live
card. The 2 chip-less NCAAB cards persist (FAMU @ UTEP now 4 rows).

## Reading 7 — Sun 11-15 12:21 PM CST (18:21Z), noon slate in Q1 / H1

35 live cards: WNCAAB 18, NCAAB 8, NFL 7, NCAAF 1, NBA 1.

**Load:**
- Query **29.8 s / 68.6 MB** (12.0 MB gz). The payload grows with live rows: 57 -> 61 -> 69 MB.
- Shortlist 1.75 s. Chips 1.53 s. Live-rail 0.09 s, 208 rows (0.19 MB).

**Refresh — the noon load, from BOOK_GRID_TICK 18:01-18:21Z:**
- NFL is repriced every other round:

  | tick (Z) | NFL grid build | next round |
  |---|---|---|
  | 18:01:43 | 120.3 s | 18:03:21 `deferred_slow ["nba","nfl"]` |
  | 18:08:47 | 82.7 s | 18:12:27 deferred |
  | 18:17:54 | 77.8 s | 18:19:38 deferred |

- **NFL overlay gap 579 s** (18:07:14 -> 18:16:53Z); NBA overlay gap 391 s. Both are over web's
  360 s cutoff.
- The NBA overlay took **69.3 s** at 18:15:35Z (cards_ms 64,207, evidence 20.2 s).
- Web merges: nfl stale 2 of 17, nba stale 1 of 5. College fresh 17 / 17.
- `nflcontend.py` over 17:55-18:23Z: both NFL builds overlap a Kalshi tick (129 / 125
  `kalshi_odds` lines). n = 2, so no long/short split is possible yet.
- **Shortlist `written_at` 1,732 s old**:
  - `BOARD_WINDOW_QUEUED date=2026-11-15 elapsed_s=1314.5` at 18:18:59Z, then re-queued every
    ~66 s.
  - Whether a build completes is not traced.
  - Board `state_meta` build 273 s old.
- **Sent to local_208683f1** (owner of the grid-speed lanes) as an interim at ~12:28 PM CST. The
  formal registered read stays at 1:30 PM.

**Live recommendations:**
- **22 flags on 13 of 35 live cards. 0 false, 0 missed, 0 dark.**
  - By sport: NCAAB 17, WNCAAB 5.
  - By market: totals 19, spreads 3.
  - By segment: full 14, h1 5, h2 3.
  - Gap min / median / max: 3.5 / 15.9 / 26.2 pp.
- `flags.jsonl` now holds 43 rows across readings.
- 579 live rows:

  | measure | p50 | p90 | count |
  |---|---|---|---|
  | priced age | 140 s | 775 s | 188 <= 120 s |
  | seen age at pricing | 73 s | 536 s | — |
  | age now | **601 s** | 955 s | **467 of 579 > 300 s** |

  The age-now jump is mostly NFL (1,298 rows in play on an overlay 5+ min old).
- 0 rows with no fair.
- **53 of 109 live markets have no OURS** (NFL 32 / 37, NBA 8 / 15, NCAAB 6 / 33, WNCAAB 5 / 14,
  NCAAF 2 / 10).
  - NFL after the re-sim ticks (18:09:57Z resimmed 3, elapsed 58.0 s; 18:18:22Z resimmed 5,
    21.9 s). 5 of 7 NFL chips carry `live_resim` (as of 18:17:59Z), and their full-game totals
    show OURS.
  - MIN @ GB and MIA @ IND were refused as `uninformative_probability`, so they have no OURS.
  - NFL spreads, intervals and the moneyline are blank by the known decisions (#767 (c), margin
    FAIL, live join withholding).
- **(c) answered.** 10 of 18 live WNCAAB cards show no lines, and **all 10 have 0 in-play quotes
  from any book since 18:05Z.** The feed quotes 8 WNCAAB games in play. This is book-side, not
  ours. Not a defect.
- **(a) halftime join:** 0 zero-card builds in this window (all sports), and no live game at a
  break. Still owed.

**Teams:** det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated. 0 live chips without a live
card. The same 2 chip-less NCAAB cards.

## Reading 8 — Sun 11-15 12:37 PM CST (18:37Z). Pre-#810 window; both workers restarted 12:24-12:25 PM

**Splits.** refresh-worker BOOTED 18:24:37Z and live-odds-worker started 18:25:55Z, for lane
`live-player-exit-gate`'s load (deploys.md 18:24:27Z + 18:25:41Z, fleet
`05fee7b69 -> f6f1ad93a`). This reading is the PRE window for #810 (college 60 s pulls, load
expected ~12:50 PM).

36 live cards: WNCAAB, NCAAB, NFL 7, NBA, NCAAF.

**Load:**
- `/intelligence` **8.6 s / 29.4 MB** (5.3 MB gz). It was 20 MB this morning; the embed grows
  with live rows.
- Query 26.3 s / 68.7 MB. Shortlist 1.2 s.
- Live-rail 0.13 s, 491-513 rows (0.48 MB).

**Refresh:**
- **(c) answered: the shortlist recovered.** `written_at` 197 s old, against 1,732 s at 12:21.
  It rebuilt after the 12:24 refresh-worker restart.
- Live-rail newest 13 / 7 / 4 s.
- Overlay gaps, last 16 min. These include the restart, so gaps that span it are inflated:

  | sport | gap max |
  |---|---|
  | NFL | 487.7 s (1 over 360) |
  | NBA | 465.3 s (1 over 360) |
  | NCAAF | 349 s |
  | NCAAB | 308 s |
  | WNCAAB | 306 s |

- Build seconds: NBA p50 70.0 s, max 149.5 s. NFL p50 66.4 s, max 98.7 s. NCAAB p50 12.2 s,
  max 33.2 s. WNCAAB p50 2.6 s.
- `deferred_slow` nba 1, nfl 1.
- Web merges: nfl stale 3 of 20, nba stale 2 of 20; college / NCAAF fresh 20 of 20.

**Live recommendations:**
- **38 flags on 16 of 36 live cards. 0 false, 0 missed.**
- By sport: NCAAB 30, WNCAAB 7, NCAAF 1, NBA 0, NFL 0.
- **Dark: 46 rows / 12 markets, ALL NBA, all from the 18:34:30Z NBA grid build.** These are NBA
  live lines with sim vs fair >= 3 pp on a quote <= 120 s old at pricing. By the read they were
  > 300 s old, because the NBA overlay is rebuilt every ~465 s (slow-sport rule).
  - **So the cadence alone hides about 12 NBA flags per reading.**
  - This is the user-facing cost of the slow-sport rule beside NFL's. NFL has no flags at all
    because its live join withholds.
- Per sport, live rows:

  | sport | rows | priced <= 120 s | seen age at pricing p50 / p90 | age now p50 | flagged rows |
  |---|---|---|---|---|---|
  | NBA | 270 | 136 (50%) | 60 / 60 s | 369 s | 0 |
  | NCAAB | 198 | 88 (44%) | 37 / 291 s | 164 s | 45 |
  | WNCAAB | 46 | 24 (52%) | 88 / 144 s | 99 s | 11 |
  | NFL | 115 | 23 (20%) | 124 / 276 s | 355 s | 0 |
  | NCAAF | 22 | 5 (23%) | 538 / 789 s | 993 s | 1 |

  - NCAAF's few live rows are mostly old, priced p50 796 s.
- 0 rows with no fair. 71 of 152 live markets have no OURS (NFL, NBA intervals, NCAAF; the
  causes in readings 6-7).

**(a) halftime join:** 0 zero-card builds in this window, and no live chip at HALF / an
intermission at the read. Still owed. The noon college games reach halftime ~12:40-12:55 PM.

**Teams:** det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated. 0 live chips without a live
card. 2 chip-less NCAAB cards: FAMU @ UTEP now 5 rows, Washington @ Utah 4.

## Reading 9 — Sun 11-15 12:50 PM CST (18:50Z). Pre-#810 (no worker boot in 12:35-12:50 PM); 15 college games at HALF

35 live cards. **15 live college chips read HALF** (NCAAB 5, WNCAAB 10).

**Load:** query 13.5 s / 71.3 MB (12.6 MB gz). Shortlist 0.8 s. Live-rail 0.11 s, 580-599
rows (0.54 MB).

**Refresh:**
- Board build 81 s old; shortlist 270 s.
- Overlay gap p50 / max:

  | sport | p50 | max |
  |---|---|---|
  | NFL | 111 s | 342 s |
  | NBA | 109 s | 126 s |
  | NCAAB | 78 s | 303 s |
  | WNCAAB | 76 s | 298 s |
  | NCAAF | 118 s | 174 s |

  0 gaps over 360 s.
- Builds: NFL p50 36.9 s, max 98.7 s. NBA p50 27.6 s, max 70.0 s. NCAAB 12.2 s. WNCAAB 2.3 s.
- `deferred_slow` nba 1, nfl 1. Tick gap p50 51 s, max 118 s.
- Web merges: nfl stale 1 of 36, nba stale 1 of 36; the rest fresh.

**Live recommendations:**
- **23 flags on 9 cards. 0 false, 0 missed, 0 dark.**
- **NBA flags reached the rail: 32 flagged rows**, against 0 shown and 46 dark rows at 12:37.
  The NBA overlay ran a normal cadence this window (gap max 126 s, 1 deferral). This fits
  reading 8's dark rows being a cadence effect.
- Per sport, live rows:

  | sport | rows | priced <= 120 s | seen age p50 / p90 | age now p50 | flagged rows |
  |---|---|---|---|---|---|
  | NBA | 250 | 136 (54%) | 38 / 282 s | 110 s | 32 |
  | NFL | 150 | 58 (39%) | 87 / 87 s | 179 s | 0 |
  | NCAAB | 147 | **28 (19%)** | 51 / 247 s | 242 s | 14 |
  | WNCAAB | 23 | **4 (17%)** | 52 / 248 s | 216 s | 1 |
  | NCAAF | 25 | 9 (36%) | 63 / 295 s | 185 s | 4 |

- **Halftime confounds #810.** College priced <= 120 s fell from 44% / 52% (12:37) to 19% /
  17% with half the college slate at HALF. The books' full-game prices stand still at the
  break, so their unchanged clock passes 120 s.
  - The #810 post window (60 s pulls from ~12:50 PM) runs into 2H play. A pre/post comparison
    must match game phase, not just the clock. Faster pulls cannot shorten a frozen price's
    book age (#786's verdict).
  - Sent to local_1f10ce63.

**(a) halftime join — H1 NOT supported per game:**
- Of the 15 college games at HALF, **9 carry overlay rows on `/api/board/live-rail`**. Of the 11
  in play, **7** do (60% vs 64%).
- The games without rows are mostly ones with no in-play book quotes (reading 7: 10 WNCAAB
  games had none).
- 0 zero-card builds in the window: a build goes to 0 only when every live game of the sport
  has nothing.
- **So the 11:48-12:02 zero-card builds (3 live games, all at the break, every quote
  `quote_older_than_live_pricing_ceiling`) remain unexplained per game.** Low impact (2-3 games,
  ~10 min). The overlay logs no per-row drop reason, so it cannot be traced from the log.
  Parked for the daily summary; not handed off.

**Teams:** det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated. 2 chip-less NCAAB cards
(FAMU @ UTEP 7 rows, Washington @ Utah 4).

## Reading 10 — Sun 11-15 12:52 PM CST (18:52Z). A refresh-worker restart lands mid-read; still pre-#810

**Split:**
- refresh-worker `BOOTED` 18:52:23Z. supervisor.log: `CLAIMED_RESTART code=0
  holder=nba-grid-per-build-lookups`, the NBA grid incremental quote read load (`8deae4ee9`).
  A deploy drain had held the board build and the MLB tick from 18:51:07Z
  (`DEFERRED_BOARD_BUILD reason=deploy_drain_requested`).
- refresh-worker boots so far today: 18:24:37Z (live-player-exit-gate) and 18:52:23Z.
- live-odds-worker: no boot since 18:25:55Z, so #810 is not loaded yet.

**Readings** (2 min after reading 9, so not independent of it):
- **27 flags on 13 cards. 0 false, 0 missed, 0 dark.**
- Live-rail newest 60 / 70 / 80 s: the overlay was held through the drain. Shortlist 400 s.
- Query 13.1 s / 70.0 MB.
- **Phase split** (new in the probe, `live_by_sport_phase`), rows priced <= 120 s:

  | sport | at a break | in play | flagged rows (break / play) |
  |---|---|---|---|
  | NCAAB | 14 of 77 (18%) | 12 of 44 (27%) | 10 / 8 |
  | WNCAAB | 6 of 16 | 5 of 11 | 2 / 3 |
  | NBA | — | 117 of 235 (50%) | 18 |
  | NFL | — | 27 of 157 (17%) | 0 |
  | NCAAF | — | 2 of 25 | 1 |

- Builds over the 15 min before the boot: NFL p50 33.2 s, max 44.9 s (under 45). NBA p50 25.1 s,
  max 43.5 s. `deferred_slow` nba 1, nfl 1. Overlay gaps all <= 303 s. Web merges: nba stale
  1 of 36, the rest fresh.

## Reading 11 — Sun 11-15 1:06 PM CST (19:06Z). FIRST POST-#810 READ (college 60 s pulls)

**Splits:**
- live-odds-worker started 18:53:22Z (pid 1771964), the #810 load: fleet ff to `295ccfa6c` at
  18:50:59Z per local_1f10ce63.
- refresh-worker unchanged since 18:52:23Z.

**Load:**
- `/intelligence` 9.8 s / 27.9 MB.
- Query 8.8 s / 67.0 MB. Shortlist 1.0 s. Live-rail 0.06 s, 497 rows.
- The shortlist is fresh (44 s).

**Refresh:**
- Overlay gap p50 / max:

  | sport | p50 | max | note |
  |---|---|---|---|
  | NCAAB | 47 s | 149 s | pre 69-78 / 303-308 s |
  | WNCAAB | 52 s | 151 s | |
  | NCAAF | 67 s | 131 s | |
  | NFL | 293 s | 343 s | |
  | **NBA** | 166 s | **402 s** | |

- Builds: NFL p50 50.6 s, max 103.4 s. NBA p50 32.2 s, max 73.0 s. NCAAB 9.2 s (pre 12.2 s).
  WNCAAB 1.8 s.
- `deferred_slow` nfl 2, nba 1. Web merges: nba stale 1 of 13.

**Live recommendations:**
- **24 flags on 14 cards. 0 false, 0 missed, 3 dark.**
- Flagged rows: NCAAB 1H 26, NCAAB 2H 13, WNCAAB 5, NCAAF 1, NBA 0, NFL 0.
- **Our-look age at pricing** (what #810 changes; halftime cannot move it), p50 / p90:

  | sport | post | pre |
  |---|---|---|
  | NCAAB | **10 / 160 s** | 37 / 291 (12:37), 51 / 247 (12:50) |
  | WNCAAB | **17 / 173 s** | 88 / 144, 52 / 248 |
  | NFL (control) | 94 / 236 s | — |
  | NBA (control) | 190 / 190 s | — (cadence) |

- Rows priced <= 120 s, phase-matched (pre 12:21 / 12:37 / 12:50 -> post):
  - NCAAB 1H 61% / 44% / 11% -> **59%** (69 / 116).
  - NCAAB 2H 79% / 46% / 25% -> **57%** (28 / 49).
  - WNCAAB 2H -> 72% (13 / 18).
  - Break rows 4 / 44 and 0 / 9: frozen, as expected.
  - NFL control 37%. **NBA control 1% (2 / 208)**: its overlay ran 402 s; the cadence again.
- One read. Single reads swing 11-82% within a phase, so pool before judging. Reported to
  local_1f10ce63, who owns the #810 verdict.

**Teams:** det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated. The same 2 chip-less NCAAB
cards.

## REGISTERED NFL PREDICTION — VERDICT, read 1:30 PM CST (window 12:30-1:30 PM = 18:30-19:30Z)

**The prediction (registered 10:45 AM, reading 1):** at least one NFL in-play overlay gap
> 360 s, and a web `nfl 'stale_...'` merge, in the window.

**Split at the boots** (refresh-worker 18:52:23Z `CLAIMED_RESTART nba-grid-per-build-lookups`,
19:26:20Z NCAAF pivot fix; live-odds-worker 18:53:22Z, #810):

| segment | NFL overlay gaps > 360 s | web nfl stale merges | NBA gaps > 360 s | web nba stale |
|---|---|---|---|---|
| A: 18:30-18:52Z | **1: 487 s** (18:28:47 -> 18:36:54Z, no boot inside) | **3** (18:35:24-18:35:56Z, 398-430 s) | 2 (465 s, 396 s) | 3 |
| B: 18:52-19:26Z | 0 (max 343 s) | 0 | 1 (403 s) | 1 (19:00:03Z, 367 s) |
| C: after the 19:26Z boot | 1 (578 s, spans the restart) | 4 (369-533 s) | — | — |

- **Verdict: MET in segment A**, with no restart inside the gap.
- **NOT met in segment B**: NFL stayed <= 343 s for 34 min with ~8 NFL games live.
- Segment C is restart-caused, so it is excluded.
- So the slow-sport cadence pushes NFL past web's cutoff **sometimes, not always**. NBA crossed it
  in both clean segments.

**Mechanism** (`grid809_tickrows.py` + `nflcontend.py`, 18:30-19:30Z):
- **On-pull:** NFL took price-on-pull whenever its last build was < 45 s (18:47:14, 18:50:13,
  18:51:08, 19:08:51, 19:17:18, 19:18:43Z). It was deferred after builds >= 45 s (18:57:48,
  19:03:30, 19:13:40, 19:23:04Z).
- **NFL build length vs other work in the same process,** 17 builds split at the median:
  - **`kalshi_odds` lines: 46.1 average in the long half vs 0.8 in the short half**;
  - the two longest builds (98.7 s from 18:35:16, 103.4 s from 18:54:03Z) each overlap a Kalshi
    tick (139 / 134 lines);
  - long builds without much Kalshi exist too: 84.9 s (10 lines), and 61.5 s (`portfolio_commit`
    31 lines);
  - so the Kalshi tick is the largest single correlate, **not proven the cause**.
- **The user-facing cost:**
  - NFL: rail lines up to 8 min old in segment A. NFL never flags anyway (the join withholds).
  - **NBA flags: 46 dark rows / 12 markets at 12:37 PM.** NBA priced <= 120 s was 1% at 1:06
    (2 / 208) and 1:30 (1 / 158), against 50-54% when the NBA overlay ran every round (12:37,
    12:50).

## Reading 12 — Sun 11-15 1:30 PM CST (19:30Z), 4 min after the 19:26 refresh-worker restart

- **23 flags on 14 cards. 0 false, 0 missed, 2 dark.**
- 58 live chips.
- Restart effects: shortlist 887 s old; NBA live rows age now p50 ~999 s and priced p50 736 s
  (1 of 158 <= 120 s). Not representative.
- College, rows priced <= 120 s, post-#810:
  - NCAAB 1H 47 / 135 (35%), 2H 25 / 98 (26%), break 0 / 14;
  - WNCAAB 2H 13 / 45 (29%).
  - Seen age p50: NCAAB 75 s, WNCAAB 113 s. Higher than 1:06; the restart again.
- Query 9.2 s / 67.2 MB. Live-rail 0.53 s.
- Web merges: nfl stale 4 of 39 (all at the restart).
- **Teams:** Washington @ Utah left the board, so 1 chip-less NCAAB card remains (FAMU @ UTEP).
  det1 / det2 / det3 0 / 0 / 0; 0 flipped; 0 truncated.

## Reading 13 — Sun 11-15 1:46 PM CST (19:46Z). Post-#810, post-19:26 restart; no new boot

59 live chips.
- **19 flags on 15 cards. 0 false, 0 missed, 0 dark.**
- **NBA flags are back: 20 flagged rows.** NBA rows priced <= 120 s: 49 of 167 (29%).
- **Load:** query 11.7 s / 67.8 MB. Shortlist 1.0 s (written 138 s ago). Live-rail 0.23 s, 559-664 rows.
- **Refresh:**
  - Overlay gap max: NFL 330 s, NBA 348 s, NCAAB 213 s, WNCAAB 232 s, NCAAF 194 s. 0 over 360 s.
  - `deferred_slow` nba 2, nfl 2.
  - Builds: NBA p50 37.5 s, max 132.6 s. NFL p50 43.9 s, max 75.6 s. NCAAB 13.5 s.
  - Web merges: 0 stale of 23.
- **Rows priced <= 120 s, by phase:**
  - NCAAB 1H 39 / 141 (28%), 2H 28 / 146 (19%), break 7 / 25.
  - WNCAAB 1H 6 / 24, 2H 7 / 33.
  - NFL 2H 16 / 75. NBA 2H 49 / 167.
- **Our pulls are on #810's cadence:** in-play full-game pulls with changes over 16 min (`pull_cadence.py`):
  - NCAAB 25, median gap **40.6 s**, max 63.5 s. WNCAAB 24, median 41.2 s.
  - NFL 11, median 70 s. NBA 4, median 246 s.
- **But NCAAB seen age at pricing rose to p50 168 s / p90 241 s** (10 / 160 s at 1:06 PM).
  WNCAAB 56 / 176 s.

**Seen-age lag vs the pull heartbeats** (`C:\tmp\railmon\lagcheck.py`, book-aware):
- For each live-rail row: the newest `book_quotes_heartbeat` look listing the row's event AND its
  book, before the row's grid build, minus the look the row implies (build - seen age).

  | read (CST) | NCAAB rows > 60 s behind | lag p50 / p90 |
  |---|---|---|
  | 12:37 | 53 / 142 | -3 / 127 s |
  | 1:06 | 70 / 193 | -9 / 141 s |
  | 1:30 | 90 / 234 | -16 / 244 s |
  | 1:46 | **149 / 268** | **114 / 187 s** |

  WNCAAB at 1:46: 21 / 67, p50 58 s.
- Of 185 NCAAB rows with seen > 60 s at the 19:46:38Z build (`supersede.py`):
  - **33** had their book quote the same market at a DIFFERENT line later. These are superseded
    lines, expected.
  - **0** had a newer capture of the SAME line.
  - **152** had no newer capture by their book at all, while a heartbeat listing that event and
    book was newer.
- So **either unchanged quotes do not get their seen time advanced from book-level heartbeats, or
  a heartbeat's `books` lists books that did not answer for that event.**
- It grows through the afternoon and was present before the 12:52 incremental read.
- **Cost:** seen age feeds the observation gate (`live_quote_unobserved` > 300 s), so rows can
  die earlier than our pulls warrant. It also inflates this probe's "our lag" metric.
- **Handed to local_208683f1** (owner of the grid read and the incremental read) as a question.
  Not mine to fix.

**Teams:** 1 chip-less NCAAB card (FAMU @ UTEP, 5 rows). det1 / det2 / det3 0 / 0 / 0. 0 flipped.
0 truncated. 0 live chips without a live card.

### Reading 13 addendum — the seen-age lag, corrected (~1:5x PM CST)

- **Premise withdrawn.** local_208683f1 (0f519972; code + the 19:51Z NCAAB state file, `C:\tmp\railload\grid809_seenlag.py`):
  - A heartbeat's `events` and `books` are independent fetch-level sets (`odds_book_quotes._heartbeat_note`),
    not (event, book) pairs.
  - Seen age is per quote key, and `append_book_quotes` restamps it on every observation,
    unchanged prices included.
  - So a stale seen age means the book did not return that key.
  - **My "heartbeat not advancing seen time" inference is wrong.**
  - Their state-file split: segment markets carry the lag (h1 spreads 78 of 108, h1 totals 79 of
    110, h2 24 / 24 of 27) against full spreads 3 of 308 and full totals 8 of 345.
- **But the live-rail rows** (what the rail shows) split differently. At the 19:46:38Z build, the
  185 stale NCAAB rows are:
  - **full totals 100** (of 165 on the rail) and **full spreads 20** (of 31);
  - h2 totals 34, h1 totals 28, h1 spreads 2, h2h 1.
- **120 full-game keys** were sent for tracing (`C:\tmp\railmon\stale_full_keys.json`; betmgm 32,
  draftkings 31, fanduel 28, fanatics 15, bovada 11).
- **Untested guess:** these are alt lines the books stop returning as the in-play ladder moves.
  If so, the gate acts correctly.
- Caveat: "no newer capture" reads the change-only capture shard and cannot prove non-return.
- **Status: OPEN with the grid owner. Not a confirmed defect.**

## Reading 14 — Sun 11-15 2:02 PM CST (20:02Z). No new boot since 19:26:20Z

46 live chips. **9 flags on 5 cards. 0 false, 0 missed, 0 dark.**

**Load:**
- `/intelligence` 12.4 s / 27.5 MB (5.0 MB gz).
- Query 13.8 s / 67.1 MB. Shortlist 0.9 s (317 s old). Chips 1.3 s.
- Live-rail 0.44 s, 434-459 rows.

**Refresh:**
- **NFL back on every-other-round:** 4 overlay builds in 17 min, gap p50 329 s, max 340 s.
  `deferred_slow` nfl 3 of the window's ticks; NFL builds p50 52.9 s, max 83.5 s.
- NBA overlay gap max 164 s (8 builds), NBA builds p50 20.0 s.
- College gaps max 167-185 s.
- Web merges: 0 stale of 27.

**Live rows priced <= 120 s:**
- NCAAB 1H 10 / 24, 2H 19 / 68, break 2 / 78.
- WNCAAB 2H 7 / 22.
- NFL 2H 25 / 104 (24%).
- **NBA 0 / 150**: priced age p50 235 s on a normally rebuilt overlay. So it is the books'
  unchanged clock, not ours (late game). Not chased.
- Seen age p50: NCAAB 37 s, NFL 195 s.

**Teams:** 1 chip-less NCAAB card (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

### Slow-sport rule — what the two grid loads removed (0f519972, deploys.md 2026-11-15 20:01Z, `5b8a97338`; `C:\tmp\railload\grid809_under45.py`)

NBA and NFL builds under 45 s, and NFL slow deferrals, per window:

| window (Z) | code | NBA < 45 s | NFL < 45 s | NFL deferred |
|---|---|---|---|---|
| 18:25-18:52 | old read + old pivot | 6 / 8 | 7 / 9 | 2 |
| 18:55-19:26 | incremental read | 9 / 12 | 3 / 9 | 4 |
| 19:29-20:00 | + anchor index | **10 / 12** | **3 / 8** | 4 |

- **NBA now mostly fits under the 45 s rule. NFL does not.**
  - Today's NFL quote file grew 95 -> 147 MB over the afternoon.
  - The two loads together save ~3 s of NFL pivot (5.9 -> 2.8 s on the same rows) plus part of
    the read.
  - Live NFL build median went 50.6 -> 55.4 s anyway.
- So the NFL cadence decision put to the user (1:4x PM CST) still stands. NBA's half of it is
  largely settled by the loads, matching reading 13-14's NBA overlay gaps of 126-164 s.

## Reading 15 — Sun 11-15 2:20 PM CST (20:20Z). No new boot

56 live chips.
- **29 flags on 14 cards. 0 false, 0 missed, 0 dark.**
- Flagged rows: NCAAB 28, NBA 15, WNCAAB 8, NCAAF 1, NFL 0.

**Load:** query 11.5 s / 67.4 MB. Shortlist 0.8 s (89 s old). Live-rail 0.05 s, 543 rows.

**Refresh, a calm window:**
- Overlay gap max: NFL 242 s, NBA 139 s, NCAAB 177 s, WNCAAB 183 s, NCAAF 168 s. 0 over 360 s.
- `deferred_slow` nfl 1. NFL builds p50 38.2 s, max 93.6 s. NBA p50 22.0 s, max 26.4 s.
- Web merges: 0 stale of 29.

**Live rows priced <= 120 s:**
- NBA 38 / 86 (44%). NCAAB 1H 51 / 181, 2H 45 / 141. WNCAAB 1H 23 / 41, 2H 12 / 33.
- NFL 14 / 121 (12%): NFL seen age at pricing p50 218 s.

**Teams:** 1 chip-less NCAAB card (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.
0 live chips without a live card.

**The slow-sport decision** (NFL cadence) is still open with the user, re-asked at 2:1x PM CST
after 0f519972's numbers.

## Reading 16 — Sun 11-15 2:42 PM CST (20:42Z). No new boot; the noon NFL games are late in 2H; no NBA game live

53 live chips.
- **34 flags on 11 cards. 0 false, 0 missed, 0 dark.** Flagged rows: NCAAB 48, WNCAAB 1.
- **Load:** `/intelligence` 8.5 s / 25.5 MB. Query 10.6 s / 65.0 MB. Shortlist 1.7 s (62 s old).
  Live-rail 0.49 s, 497 rows.
- **Refresh:**
  - **NFL overlay gap max 368 s (1 over 360)**, p50 204 s. `deferred_slow` nfl 3; NFL builds p50
    39.1 s, max 94.3 s.
  - College gaps max 167-215 s.
  - Web merges: 0 NFL stale of 37. The 368 s gap did not catch a merge past the cutoff.
  - nba stale 11 of 37: the 12:10 PM NBA game is final, so the NBA overlay ages until the 3:10 PM
    tip. Expected.
- **Rows priced <= 120 s:** NCAAB 1H 60 / 128, 2H 80 / 197, break 8 / 27. WNCAAB 1H 9 / 40,
  2H 12 / 37. NFL 16 / 68 (seen age p50 141 s).
- **Teams:** 1 chip-less NCAAB card (FAMU @ UTEP, 5 rows). det1 / det2 / det3 0 / 0 / 0. 0 flipped.
  0 truncated.

## Reading 17 — Sun 11-15 3:10 PM CST (21:10Z). 3:05 PM NFL kickoffs; the noon NFL games in their last minute

39 live chips. NFL: KC @ ATL, HOU @ CLE, MIA @ IND, CAR @ NO and JAX @ TEN in Q4 (0:21-1:56 left);
LAR @ ARI and SEA @ LV in Q1.
- **19 flags on 11 cards. 0 false, 0 missed, 0 dark.** Flagged rows: NCAAB 30, WNCAAB 8.
- **Load:** query 7.2 s / 59.3 MB, shrinking as games end. Shortlist 0.8 s. Live-rail 0.03 s,
  292 rows.
- **Refresh:**
  - NFL overlay 19 builds in 28 min, gap p50 58 s, max 261 s. NFL builds p50 17.8 s, max
    63.0 s, as the noon games' in-play rows thin out. `deferred_slow` nfl 2.
  - College gaps max 119-122 s.
  - Web merges: nfl / college fresh 62 / 62. nba stale 62 / 62: no NBA game live until the
    3:10 PM tip. Expected.
- **NFL live re-sim, 3:05 PM games:**
  - first tick on them **21:09:15Z, ~4 min after kickoff** (noon: ~10 min);
  - `live_games=7 resimmed=6`, elapsed 8.3 s (noon: 58.0 s).
  - Both new games carry `live_resim` as of 21:09:03Z.
  - **The player-exit gate is visible:** `key_player_out` refused 1 game at 20:57:25 and
    21:03:31Z (lane `live-player-exit-gate`, loaded 12:24 PM).
- **Rows priced <= 120 s:**
  - NCAAB 66 / 200, WNCAAB 23 / 49.
  - NFL 8 / 77: priced age p50 688 s, the end-of-game prices of the noon games standing still.
- **Teams:** 1 chip-less NCAAB card (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 18 — Sun 11-15 3:29 PM CST (21:29Z). NBA LAL @ PHX live; NFL LAR @ ARI, SEA @ LV, SF @ DAL in Q1

32 live chips.
- **24 flags on 9 cards. 0 false, 0 missed, 1 dark.**
- **NBA flags on a normal cadence:** 64 flagged NBA rows.
  - NBA rows priced <= 120 s: **216 / 335 (64%)**, seen age p50 6 s.
  - NBA overlay gap max 137 s; NBA builds p50 20.5 s.
  - Web nba stale merges cleared after the tip (4 of 46, all before the first overlay).
- **NFL:** overlay gap p50 73 s, max 235 s. `deferred_slow` nfl 1. NFL builds p50 16.0 s, max
  55.5 s. Rows priced <= 120 s: 18 / 43.
- College: NCAAB 50 / 195 (seen age p50 191 s; old lines, see the lead), WNCAAB 13 / 39.
- Web merges: ncaaf stale 17 of 46. The last NCAAF game is over, so its overlay ages. Expected.
- **Load:** `/intelligence` 7.4 s / 25.4 MB. Query 7.3 s / 62.6 MB. Live-rail 0.05 s, 589 rows.
- **Teams:** 1 chip-less NCAAB card (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 19 — Sun 11-15 3:57 PM CST (21:57Z)

27 live chips.
- **35 flags on 12 cards. 0 false, 0 missed, 0 dark.** NBA 74 flagged rows (2 NBA games live).
- Rows priced <= 120 s: NBA 322 / 581 (55%, seen age p50 65 s). NCAAB 73 / 213. NFL 10 / 73.
- Overlay gap max: NFL 230 s, NBA 286 s, college 187-192 s. `deferred_slow` nba 1, nfl 1.
- Web merges: 0 stale apart from ncaaf 61 / 61 (no NCAAF game live).
- Query 8.1 s / 69.3 MB. Live-rail 0.61 s, 855-946 rows (0.81 MB): the 15 s poll's payload
  peaks here.
- **Teams:** 1 chip-less (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## FLAGS GRADED ON OUTCOMES — first pass, 3:5x PM CST (`C:\tmp\railmon\grade_flags.py`)

**Method:**
- The 347 flag sightings in `flags.jsonl` (readings 1-19) collapse to **326 unique flags**,
  deduped on (game, market, segment, side incl. line).
- Each is graded at its FIRST sighting (the price a viewer could act on) against the final chip
  linescore: NCAAB halves, OT in 2H; quarters elsewhere.
- 92 are not yet final.
- A flag is information, not a bet (user 2026-11-14). This is #780's question: does the fresh-quote
  sim-vs-book gap carry realised value?

**Result, 234 graded flags from 29 games:**

| bucket | decided | W-L-P | hit rate | mean sim p | mean fair p | Brier sim | Brier fair |
|---|---|---|---|---|---|---|---|
| ALL | 233 | 117-116-1 | **50.2%** | 0.625 | 0.499 | **0.2705** | **0.2478** |
| NCAAB | 158 | 72-86-1 | 45.6% | 0.627 | 0.501 | 0.2828 | 0.2472 |
| WNCAAB | 45 | 26-19 | 57.8% | 0.642 | 0.499 | 0.2483 | 0.2488 |
| NBA (one game, IND @ PHI) | 22 | 13-9 | 59.1% | 0.566 | 0.456 | 0.2461 | 0.2531 |
| totals, full | 111 | 54-57 | 48.6% | 0.639 | 0.493 | 0.2820 | 0.2576 |
| totals, segments | 55 | 26-29-1 | 47.3% | 0.634 | 0.504 | 0.2790 | 0.2373 |
| spreads, full | 34 | 18-16 | 52.9% | 0.587 | 0.487 | 0.2466 | 0.2480 |
| spreads, segments | 23 | 13-10 | 56.5% | 0.599 | 0.512 | 0.2646 | 0.2498 |
| moneyline | 10 | 6-4 | 60.0% | 0.613 | 0.554 | 0.1907 | 0.1921 |

- **The book's no-vig fair was better calibrated than the sim on the flagged lines** (Brier 0.2478
  vs 0.2705). The flags' average 12.6 pp disagreement realised ~0: hit rate 50.2% against a 49.9%
  fair.
- That matches #780's prior (fresh-quote gaps realise ~0). NCAAB totals carry most of the shortfall.
- **The effective n is 29 games, not 233.** Game level: flags mostly won in 13, mostly lost in 16.
  Largest clusters: IND @ PHI 13-9, LOU @ MEM 13-6, BOISE @ NEB 5-10, UNH @ BU 5-10.
- **No optimization is proposed from this.** It was not pre-registered, and slicing it further now
  would be forking paths.

**PRE-REGISTERED for tonight, written 4:0x PM CST before any outcome after 4 PM is read:**
- **Population:** flags first shown on the rail at or after 22:00Z (4:00 PM CST) 11-15. Graded at
  finals by `grade_flags.py` (first sighting), with the readings at the planned cadence.
- **Measure:** Brier(sim) - Brier(fair) over decided flags. Also the game-level majority share.
- **Prediction** (from #780 and the 234 above): Brier(sim) >= Brier(fair), and the hit rate within
  +-5 pp of the mean fair.
- **Decision rule:**
  - Only if Brier(sim) < Brier(fair) - 0.01 across >= 20 distinct games: propose a gap-band study
    to the user, still not a rule change.
  - Otherwise the flag rule stays as is, and the rail stays information (user 2026-11-14).

## Reading 20 — Sun 11-15 4:30 PM CST (22:30Z). First reading inside tonight's pre-registered population (flags first shown >= 22:00Z)

22 live chips.
- **37 flags on 11 cards. 0 false, 0 missed, 0 dark.** Flagged rows: NBA 102, NCAAB 16,
  WNCAAB 2, NFL 0.
- **Cadence:**
  - **0 `deferred_slow` in 33 min.**
  - Overlay gap max: NFL 171 s, NBA 204 s, NCAAB 109 s, WNCAAB 146 s.
  - Builds: NFL p50 19.7 s, max 52.0 s. NBA p50 22.8 s, max 41.8 s.
  - Web merges: 0 stale apart from ncaaf 66 / 66 (no NCAAF game live).
  - 1 WNCAAB zero-card build with rows.
- **Rows priced <= 120 s:** NBA 428 / 831 (52%, seen age p50 23 s). NCAAB 36 / 106. NFL 19 / 76.
  WNCAAB 8 / 25.
- **Load:**
  - `/intelligence` 8.2 s / **31.1 MB** (5.5 MB gz), the largest page today.
  - Query 6.6 s / 71.2 MB.
  - **Live-rail 0.13 s, 1,003-1,031 rows, 0.94 MB.** The 15 s rail poll now moves ~1 MB
    uncompressed, ~80 KB on the wire. It was ~20 KB at its 11-14 design reading.
- **Teams:** 1 chip-less (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 21 — Sun 11-15 5:02 PM CST (23:02Z). No new boot

18 live chips.
- **25 flags on 9 cards. 0 false, 0 missed, 0 dark.** Flagged rows: NBA 68, NCAAB 8, WNCAAB 7.
- **Cadence:**
  - `deferred_slow` nba 2. NBA builds p50 29.0 s, max 60.3 s. NBA overlay gap max 309 s (under
    360).
  - NFL gap max 202 s; NFL builds p50 18.0 s. College gaps max 152 s.
  - Web merges: 0 live-sport stale (ncaaf 72 / 72, no NCAAF game).
- **Rows priced <= 120 s:** NBA 199 / 541 (37%). NCAAB 37 / 96. WNCAAB 13 / 30. NFL 6 / 37.
- **Load:** query 8.8 s / 64.5 MB. Shortlist 0.7 s. Live-rail 0.11 s, 693 rows (0.65 MB).
  - local_208683f1 is leaving the ~1 MB rail payload as is (~80 KB on the wire, 0.13 s server);
    they raise it with the user only if the page gets slow in use.
- **Teams:** 1 chip-less (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 22 — Sun 11-15 5:34 PM CST (23:34Z). Evening NBA slate starting; no new boot

18 live chips.
- **38 flags on 8 cards. 0 false, 0 missed, 0 dark.** NBA 154 flagged rows.
- **NBA is back on every-other-round cadence with more NBA games live:**
  - NBA builds p50 **64.5 s**, max 90.0 s, on **939 in-play rows** (335 at 3:29 PM, one game).
  - `deferred_slow` nba 5, nfl 3 in 32 min.
  - **NBA overlay gap p50 370 s, max 437 s.** NFL gap max 398 s.
  - Web merges stale: nba 3 of 64, nfl 2 of 64.
  - **This corrects the 2:1x PM conclusion that NBA was "largely settled" by the grid loads.** That
    held with ONE NBA game live (10 of 12 builds < 45 s). With several, NBA's builds pass 45 s
    again. NFL is the same with 3 games.
- Rows priced <= 120 s: NBA 605 / 939 (64%, seen age p50 47 s). NFL 11 / 54. College tail small.
- **Load:**
  - `/intelligence` 10.3 s / 24.1 MB. Query 9.5 s / 68.6 MB.
  - Live-rail 0.17 s, **1,049 rows, 0.99 MB**.
- **Teams:** 1 chip-less (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 23 — Sun 11-15 5:57 PM CST (23:57Z). Evening NBA; pre-load baseline for #811

13 live chips.
- **5 flags on 2 cards. 0 false, 0 missed, 1 dark.** Flagged rows: NCAAB 4, WNCAAB 2, **NBA 0**.
- **NBA could not flag:** **0 of 719** NBA live rows were priced on a quote <= 120 s. Two clocks
  compound:
  - **Our NBA look:** in-play pulls every ~249 s (`NBA_LIVE_AUTORUN_LAUNCHED ... interval_s=240`;
    5 changed-line pulls in 20 min). Seen age at pricing p50 216 s.
  - **The NBA overlay:** 4 builds in 23 min, gap p50 292 s, max 343 s. NBA builds p50 70.9 s,
    max 91.7 s. `deferred_slow` nba 5.
  - Against that: NFL pulls every 55 s and college every ~41 s (since #810).
- **This is #811's pre-load baseline** (NBA live game lines 240 -> 60 s, on main `b2ae202d4`, NOT
  loaded, the user's call). Sent to local_1f10ce63.
  - Caution, already in #811: price-on-pull re-prices per pull, so NBA builds per hour could rise
    up to 4x. NBA builds are already 64-71 s p50 with the evening slate, past the slow-sport 45 s.
- Overlay gaps: NFL max 170 s, college max 225-309 s. Web merges: 0 live-sport stale (ncaaf 51 /
  51, no game).
- **Probe correction:** the 3 `MALLOC_ARENA_INIT` lines at 23:35:01Z were child processes, not a
  restart (supervisor.log: no new live-odds-worker pid since 18:53Z, pid 1771964). The probe now
  reads live-odds-worker restarts from supervisor.log.
- **Load:** query 8.3 s / 64.6 MB. Live-rail 0.08 s, 774-777 rows.
- **Teams:** 1 chip-less (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 24 — Sun 11-15 6:20 PM CST (00:20Z 11-16). No restart (live-odds-worker pid still 1771964)

14 live chips. **29 flags on 8 cards. 0 false, 0 missed, 0 dark.** Flagged rows: NBA 98, NCAAB 11.

**NBA:**
- 325 / 762 rows priced <= 120 s (43%), seen age p50 57 s. A pull had just landed: the read
  saws with the ~249 s pull, 0 / 719 at 5:57.
- NBA overlay gap p50 360 s, **max 402 s**. NBA builds p50 62.7 s, max 106.4 s. `deferred_slow`
  nba 3.
- Web merges: no nba stale this window.

**Other sports:**
- NFL gap max 213 s (SNF not started). College gaps max 193-288 s.
- Web merges: ncaaf stale 50 / 50 (no NCAAF game).

**Load:** `/intelligence` 5.0 s / 27.3 MB. Query 10.9 s / 67.2 MB. Live-rail 0.14 s, 839-844 rows
(0.80 MB).

**Teams:** 1 chip-less (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 25 — Sun 11-15 6:43 PM CST (00:43Z). NHL started; no restart (live-odds-worker pid 1771964)

12 live chips (NHL EDM @ PHI P1 18:23).
- **7 flags on 5 cards. 0 false, 0 missed, 0 dark.** Flagged rows: NCAAB 9, WNCAAB 2, NBA 0.
- **NBA at the bottom of its pull saw:** 3 / 577 rows priced <= 120 s, seen age p50 244 s.
  - NBA overlay gap max 226 s; NBA builds p50 28.5 s, max 69.7 s; `deferred_slow` nba 3.
  - So a 0-flag NBA read is now the ~249 s pull, not the overlay.
- **NHL:** 3 live rows, 2 priced <= 120 s. NHL overlay 3 builds, gap max 80 s, builds p50 1.6 s.
  Web merges nhl fresh 10 / 10.
- **NFL:**
  - 9 zero-card overlay builds with in-play rows, between the 3:25 PM games' finals and SNF at
    7:20 PM. Those are leftover rows of finished games; benign.
  - `deferred_slow` nfl 2. 4 NFL "live" rows on the rail, aged 376-434 s.
- Web merges: 0 live-sport stale (ncaaf 64 / 64, no game).
- **Load:** query 9.5 s / 63.7 MB. Live-rail 0.05 s, 665 rows.
- **Teams:** 1 chip-less (FAMU @ UTEP). det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.
