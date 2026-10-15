# Is the venue segment-mismatch constraint MLB-specific or general?

`[2026-10-14, session 4ab694ed, lane venue-segment-addressable, taking the lead filed on closing mlb-live-gameline-venue-freshness]`

## The question, and why it is a decision rather than a bug

Lane `mlb-live-gameline-venue-freshness` (CLOSED 2026-10-14, GOAL NOT MET) found
that venue quotes fail to price the live MLB board because of **segment shape**,
not freshness and not key vocabulary:

- of **427** live MLB sides, only **23** matched a venue quote at all;
- **17 of those 23** were refused `SEGMENT_MISMATCH_GRID`, e.g.
  `mlb|first5|h2h <- kalshi|full|h2h|KXMLBGAME-...`;
- the club/token shape was separately shown healthy (pregame 24/24/24/24; live
  8 offered, 8 present), so more key-matching buys nothing.

Kalshi and Polymarket quote **full-game** contracts. The live MLB board is mostly
**first3/first5**. So the lead posed a binary: wire full-game venue pricing, or
accept that venue quotes cannot price the live board. **Neither answer is
defensible without knowing how much of the live board is full-game** — and that
number did not exist, because the MLB reading was one slate of one sport.

## What was measured, 2026-10-14 22:01:49Z–22:01:59Z

Off the served board, `/api/board/layer2-shortlist?sport=<s>&limit=5000`, with
the **row cap defeated**: every sport reported `rows == total_rows`, so no share
below is computed over a truncated page. (`rows_truncated` can stay 0 while rows
are missing, so it was not relied on.)

### PREGAME — measured, and it supports the hypothesis

| sport | pregame rows | `segment=full` | share |
|---|---|---|---|
| mlb | 150 | 132 | **88.0%** |
| nba | 21 | 21 | 100% |
| nhl | 238 | 238 | 100% |
| nfl | 1,185 | 1,185 | 100% |
| ncaaf | 428 | 428 | 100% |
| soccer | 1,957 | 1,949 | 99.6% |
| ncaab / wnba | 0 | 0 | n/a (out of season) |
| **pooled** | **3,979** | **3,953** | **99.3%** |

**MLB is the outlier, and it is the only one.** Every other in-season sport is
at or within half a point of 100% full-game pregame. That is consistent with the
MLB finding being a property of MLB's market structure (first3/first5 exist as
traded markets) rather than of venue quoting.

### LIVE — NOT MEASURED, because the frame was empty

**Zero live rows, across all eight sports.** This is a proven-empty frame, not an
instrument failure, and it was confirmed three independent ways:

1. all 238 NHL rows carried `is_live: False`, `market_state: pregame`,
   `game_state: pregame`;
2. `/api/board/game-chips` returned 230 chips — **158 pregame, 71 final, 1
   postponed, 0 in play**;
3. `scripts/check_e2e_coverage.py` reported `live_games` as `attributed_zero`
   for mlb, nba, ncaaf, nfl, nhl and soccer — zero **with a stated reason**,
   which is the attribution guard working rather than a gap.

22:0xZ is 5:0x PM CDT, between slates: NHL puck drop is ~23:00Z. **No share over
zero live rows is reported here**, which is the whole point of stating the
denominator.

## Status

- **The pregame half is answered**: segment markets are an MLB phenomenon,
  99.3% of the pregame board is full-game, and MLB at 88.0% is the sole outlier.
- **The live half decides the lead** and is armed, not guessed: one-time task
  `venue-segment-live-reading-1014`, fires **2026-10-14 19:45 CDT (2026-10-15
  00:45Z)**, during tonight's NHL slate. Its prompt refuses to report a share if
  no game is in play and re-arms instead.
- **Nothing about MLB will be concluded from tonight**: MLB is in the postseason
  and its slate is one or two games. The task is told so explicitly.

## What the answer will mean

- If LIVE rows are predominantly `full` — the constraint was MLB-specific, venue
  full-game quotes can price most of the live board, and wiring full-game venue
  pricing is worth it.
- If LIVE rows are predominantly segment markets across sports — the constraint
  is general, venue quotes structurally cannot price the live board, and the
  honest action is to accept that rather than build more matching.

The pregame number leans hard toward the first, but pregame is not live: a live
board can be re-shaped into segment markets precisely because that is where
in-play trading concentrates. That is why the reading is being taken rather than
inferred.

## LIVE reading -- 2026-10-15T00:49Z (2026-10-14 19:46 CDT), scheduled task `venue-segment-live-reading-1014`

**Live population existed.** `/api/board/game-chips` at 00:46:03Z (artifact age 5.5s): 230 chips, **20 live** -- mlb 1, nba 6, nhl 2, ncaaf 2, soccer 9 (plus nba 1 / soccer 137 pregame, soccer 71 final, 1 postponed).

`/api/board/layer2-shortlist?sport=<s>&limit=5000`, fetched 00:46:47-00:46:54Z, one shortlist build (`written_at` 00:44:05Z). **Row cap defeated for every sport: `rows == total_rows`** (per_sport_limit 2000; soccer 1,942 is the largest). Live = `is_live` true / `market_state == live` (the two agreed on every row).

| sport | LIVE full / LIVE rows | non-full LIVE mix | live games | PREGAME full / rows |
|---|---|---|---|---|
| mlb | 4/4 (100%) | -- | 1 | 0/0 |
| nba | 18/18 (100%) | -- | 6 | 3/3 |
| nhl | 0/0 (2 games live, **0 rows**) | -- | 0 | 0/0 |
| nfl | 0/0 (nothing in play) | -- | 0 | 1,211/1,211 |
| ncaaf | 6/12 (50.0%) | h1 2, q1 1, q2 1, q3 1, q4 1 | 2 | 332/332 |
| ncaab | 0/0 (off-season) | -- | 0 | 0/0 |
| wnba | 0/0 (off-season) | -- | 0 | 0/0 |
| soccer | 66/71 (93.0%) | h1 3, h2 2 | 9 | 1,867/1,871 (h1 4) |
| **pooled ex-MLB** | **90/101 (89.1%)** | h1 5, h2 2, q1-q4 4 | 17 | 3,413/3,417 (99.9%) |
| pooled incl. MLB | 94/105 (89.5%) | | 18 | |

**Answer to the lead:** LIVE rows are predominantly `segment=full` (89.1% of 101, over nba/soccer/ncaaf), so the 2026-09-24 SEGMENT_MISMATCH_GRID constraint is MLB-specific, venue full-game quotes can in principle price most of the live board, and wiring full-game venue pricing is worth it. NCAAF is the one sport where live segments are material (half its 12 live rows), on 2 games.

**Limits, stated rather than pooled:**
- **No MLB conclusion.** Postseason, 1 live game, 4 rows (3 batter_hits, 1 batter_hits_runs_rbis -- player props, which no venue quotes). The 427-side MLB board of the closed lane is a different population.
- NHL had 2 live games and 0 shortlist rows at all (pregame also 0) -- a zero, not a share. NFL had nothing in play (Wednesday); its 1,211 rows are all pregame.
- This is the served Layer 2 shortlist, i.e. after the value/quote-age gates -- not the full live odds grid.
- **`full` is necessary, not sufficient.** By market, ex-MLB live full rows: h2h 16, totals 31, spreads 17 (= 64 of 90) vs soccer alternate_totals_corners 21, btts 4, player_goal_scorer_anytime 1. Whether Kalshi/Polymarket quote corners/btts was not checked here; the addressable share for plain game-line contracts is therefore 64/101 (63.4%), still a majority.
