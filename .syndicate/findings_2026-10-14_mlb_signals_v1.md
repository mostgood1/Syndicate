# MLB matchup signals v1 -- the user's batter-vs-pitcher / arsenal / recency stack, tested on the bought 2026 season: not supported; a small hits-under tilt is -- 2026-10-14

Lane `signal-engine-mlb` (session 9e18a0e7). Registered at `caab303b` (2026-10-14T13:28:29Z) before any bought close was
joined to an outcome; thresholds came from `--mode distributions` (features only). Code: `scripts/mlb_props_pull.py`,
`scripts/mlb_signal_tests.py`.

## The question

The user's example: *"if a batter has a historical edge against a pitcher, has better statcast data against that
pitcher's arsenal, and recency of the batter performance show a positive streak this might indicate that the prop for
hitter to get a hit has a higher likelihood."* Tested as each piece alone and as the stack, plus pitcher strikeout
signals and the pooled under per market.

## Data

- **Purchase** (user: "Hits + TB + K"): OddsAPI history, 2,379 regular-season games (50 doubleheader games excluded --
  a team pair plus a date is not a game), batter_hits / batter_total_bases / pitcher_strikeouts at first pitch - 10 min,
  US region, 8 books typical. Probe 31 credits; full run 71,383 over 2,561 calls; **71,414 credits** in all (estimate
  ~73,000), 0 games without an event, 0 failed calls. Durable on the fleet: `backfill/mlb_props_2026/` (sha256 MANIFEST).
- **Features, all as-of** (the season walked day by day; each day's lines scored before that day is added): BvP from
  every pre-2026 legacy date + 2026 Statcast plate appearances before the day (production's counting rule); arsenal from
  2026 Statcast pitch mix x the batter's wOBA by pitch type; recency and K features from the 2026 game logs.
- **Graded:** 92,662 main lines, 90,022 joined (2,640 void: no box row), discover 44,587 / 1,182 games, confirm 45,435 /
  1,195 games (split 2026-06-25).

## Results (residual = hit rate - Shin probability on the signal's side; CI over games)

| signal (side) | discover resid [CI] (n) | confirm resid [CI] (n) | ROI best price, confirm | verdict |
|---|---|---|---|---|
| bvp_edge (over; >= +0.168) | +6.5% [-0.9, +14.0] (307) | -2.0% [-8.0, +4.0] (461) | -7.9% | NOT SUPPORTED |
| arsenal_edge (over; >= +0.023) | -1.2% (2,350) | -1.7% [-4.0, +0.4] (3,514) | -8.3% | NOT SUPPORTED |
| arsenal_bad (under; <= -0.017) | +0.1% (2,290) | +2.0% [-0.1, +4.2] (3,760) | -1.5% | NOT SUPPORTED |
| hot_streak (over; >= +0.113) | +0.2% (2,129) | +0.0% [-2.2, +2.2] (3,556) | -5.0% | NOT SUPPORTED |
| **matchup_stack -- the user's example** (over) | +25.1% [-0.0, +47.4] (22 / 11 games) | **-4.2% [-23.0, +15.3]** (38 / 19 games) | -16.8% | NOT SUPPORTED |
| k_trend_up (over; >= +0.074) | -2.0% (78) | +1.1% [-5.2, +7.5] (230) | -0.4% | NOT SUPPORTED |
| opp_k_high (over; >= 0.246) | -2.7% (193) | +0.0% [-7.1, +7.5] (181) | -2.5% | NOT SUPPORTED |
| opp_k_low (under; <= 0.199) | +1.9% (184) | +4.9% [-1.3, +11.6] (217) | +5.0% | NOT SUPPORTED |

BH (q = 0.10) on the eight: none.

| pooled UNDER | discover resid [CI] | confirm resid [CI] | ROI best book (d / c) | verdict |
|---|---|---|---|---|
| **batter_hits** | **+0.99% [+0.21, +1.79]** (21,195) | **+0.95% [+0.19, +1.71]** (21,653) | -3.6% / -3.7% | **SUPPORTED** |
| batter_total_bases | +0.64% [-0.10, +1.40] | +0.72% [-0.03, +1.48] | -3.9% / -3.8% | NOT SUPPORTED |
| pitcher_strikeouts | +0.58% | +1.44% [-0.64, +3.47] | -2.3% / -0.6% | NOT SUPPORTED |

## Reading

1. **The close already prices the matchup.** Batter-vs-arsenal, recent form and the pitcher's K trend carry no residual
   against the closing line -- the market knows them. The hot-streak result is as flat as it gets (+0.0% on 3,556 lines).
2. **The user's stack looked spectacular and was noise.** In the first half it hit 77% against a 52% price (+25 points,
   +48% ROI) -- on 22 lines from 11 games. On 38 unseen lines it went the other way (-4.2%). It fires rarely because only
   batters with 10+ career plate appearances against that starter are eligible; a few dozen lines a half cannot carry a
   claim. This is the reason the protocol splits windows: the discover number alone would have been a confident, wrong
   recommendation.
3. **BvP history is not an edge either** -- +6.5% then -2.0%: a small-sample history the market already discounts.
4. **The hits UNDER is under-priced by about one point, in both halves** -- the same shape as NBA (+1.0 / +1.6) and NCAAF
   (+2.4): a likelihood adjustment, not a bet; blind unders lose ~3.6% at the best book.
5. Near misses, not findings: arsenal_bad unders (+2.0% confirm), opponent-low-K unders (+4.9% confirm).

## Next (MLB), each a user decision

- Wire `mlb.hits_under_bias` (+0.95 points, the pooled residual) into the board's SHADOW likelihood, as NBA / NCAAF --
  not during the postseason (a regular-season number); from the 2027 regular season.
- Forward tests on 2027 for the two near misses, registered alone.
