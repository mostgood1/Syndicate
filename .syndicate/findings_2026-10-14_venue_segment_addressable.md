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

---

## THE LIVE HALF, ANSWERED on a live frame: 2026-10-15 00:55:01Z

The 22:0xZ attempt could not answer this — **0 live rows, proven empty three
ways** — so the reading was armed rather than guessed. The task
`venue-segment-live-reading-1014` fired at **00:45:20Z** and succeeded; this is
an independent re-reading nine minutes later, because a number from another run
is a claim until I measure it.

**The frame was live, and that is checked rather than assumed:**
`/api/board/game-chips` returned 230 chips — **137 pregame, 71 final, 21 LIVE, 1
postponed**. 21 games in play is a population; the 22:0xZ frame had 0.

### Measured, live rows only, row cap defeated (`rows == total_rows` per sport)

| sport | rows | live | `segment=full` | share | other segments on live rows |
|---|---|---|---|---|---|
| nba | 22 | 19 | 19 | **100%** | — |
| soccer | 1,930 | 157 | 154 | **98.1%** | h1=2, h2=1 |
| nhl | 1 | 1 | 1 | 100% | — |
| ncaaf | 346 | 12 | 7 | **58.3%** | **h1=3, q2=1, q1=1** |
| nfl / ncaab / wnba | 1,207 / 0 / 0 | 0 | — | — | no live rows |
| **NON-MLB TOTAL** | | **189** | **181** | **95.8%** | |
| mlb (postseason) | 3 | 3 | 3 | 100% | *not a conclusion — see below* |

### The decision rule, applied

The findings above committed to a rule before the reading: *"If LIVE rows are
predominantly `full` — the constraint was MLB-specific, venue full-game quotes
can price most of the live board, and wiring full-game venue pricing is worth
it."*

**95.8% of non-MLB live rows are full-game. The rule fires: the segment
constraint is MLB-specific, and wiring full-game venue pricing is worth it.**
That is consistent with the pregame half (99.3% full, MLB the sole outlier at
88.0%) and with the lane's hypothesis.

### Three caveats, each of which narrows the claim

1. **NCAAF is the exception and it is a real one:** 58.3% full over 12 live rows,
   with `h1`, `q1` and `q2` present. Segment markets DO appear live there. n=12
   is small, so this is a flag for a second reading rather than a finding — but
   it means "the live board is full-game" is a statement about nba and soccer,
   which supplied 173 of the 189 rows.
2. **Nothing is concluded about MLB, which is the sport the whole lead came
   from.** MLB is in the postseason: 3 live rows tonight, all full-game. The
   original finding — 427 live MLB sides, 23 matching a venue quote, 17 of those
   refused `SEGMENT_MISMATCH_GRID` on `mlb|first5|h2h` — was a regular-season
   slate and **stands unchallenged**. A postseason sample cannot speak to it, and
   the task was told so explicitly.
3. **TWO READINGS NINE MINUTES APART DISAGREE, and the gap is worth more than
   either number.** The 00:45:20Z task run reported **89.1% non-MLB full (90 of
   101)**; this 00:55:01Z reading reports **95.8% (181 of 189)**. Same frame,
   same question, **88 more rows and 6.7 points apart**. The live board gains and
   loses rows as games progress, so a single live reading carries more variance
   than its own denominator suggests. Both support the same verdict, which is why
   the verdict survives — had they pointed opposite ways, neither would have
   been enough.

---

## CORRECTION, 2026-10-15 02:0xZ: "the constraint is MLB-specific" is WRONG, and the served snapshot is why

Lane `ncaaf-live-segment-history` took the NCAAF follow-up this file filed and,
measuring every sport from the `opportunity_population` ledger instead of a
served snapshot, refuted the verdict above. **212,665 live priced sides, 16
dates:**

| sport | live sides | `full` | share |
|---|---|---|---|
| ncaaf | 48,873 | 26,457 | **54.1%** |
| nba | 17,682 | 11,560 | **65.4%** |
| mlb | 14,173 | 10,571 | **74.6%** |
| wnba | 18,964 | 14,455 | 76.2% |
| nfl | 52,610 | 45,346 | 86.2% |
| soccer | 43,001 | 41,763 | 97.1% |
| nhl | 17,362 | 17,362 | **100%** |

**MLB is the third-most full-game of the five segment-carrying sports.** NCAAF
and NBA are worse. Segment markets are platform-wide.

**The served board at 00:55Z is why this read the other way, and NBA is the
proof:** it was **19 of 19 = 100% full** there, the healthiest sport in the
snapshot, and it is **65.4%** over 17,682 priced live sides. The served live
board is a tiny score-ranked subset of what is priced (10-14: 709 NCAAF live
sides priced, **12** served). Caveat (3) above — that two readings nine minutes
apart disagreed by 88 rows and 6.7 points — was pointing straight at this and I
did not follow it far enough: the problem was not variance between two snapshots,
it was the snapshot being the wrong denominator for the question.

**And the premise this file inherited is false.** It says above: *"Kalshi and
Polymarket quote full-game contracts. The live MLB board is mostly
first3/first5."* The second sentence was never measured. MLB live is **74.6%
full-game, 25.4% segment**. From the originating lane's own numbers — 427 live
MLB sides, 23 matched a venue quote, 17 of those 23 refused
`SEGMENT_MISMATCH_GRID` — segment mismatch explains **17 of 427 = 4.0%** of the
failure, and the **404 (94.6%) that matched no venue quote at all** is the
dominant loss. `17/23 = 74%` is a share of *matched sides*, not of the board.

**What survives:** wiring full-game venue pricing is still worth doing, because
full-game is a majority of live sides in all seven sports (54.1% at worst). The
gain is **broad and partial**, not narrow and total. The pregame numbers in this
file are unaffected — they were measured on the served board, which is the right
denominator for "what does the board show pregame", and MLB really is the
pregame outlier at 88.0%.
