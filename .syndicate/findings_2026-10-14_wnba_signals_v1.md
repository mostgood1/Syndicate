# WNBA signals v1 -- the NBA tests on the bought 2026 regular season: nothing supported; the under tilt faded -- 2026-10-14

Lane `signal-engine-wnba` (session 9e18a0e7). Registered in the lane block at 2026-10-14T03:03:32Z (landed `8c895c81`)
before any close was joined to an outcome. Code: `scripts/wnba_props_pull.py`, `scripts/wnba_signal_tests.py`.

## Data

- **Why bought:** the fleet held no usable 2026 WNBA prop close (41 events over 32 dates, snapshots 1-22 h before tip).
- **Purchase** (user: "All 8 markets", probe first): OddsAPI history, the 331 regular-season games between real clubs
  (the July 25 All-Star game COOP vs SPO and all playoff games excluded), one events call per game day, props at
  tip - 10 min, US region, points / rebounds / assists / threes / PRA / PR / PA / RA. Probe 1 game = 81 credits;
  full run 330 games + 111 event days = 26,321; **26,402 credits** in all (estimate ~26,600), 0 games without an event,
  0 failed calls. Typical books: DraftKings, FanDuel, Caesars, BetRivers, BetOnline. Durable on the fleet:
  `backfill/wnba_props_2026/` (446 files, sha256 MANIFEST).
- **Outcomes / features:** the fleet's ESPN game log `player_game_log_2026.csv` (regular season, All-Star dropped).
- **Graded:** 19,251 main lines, 18,716 graded (535 void: no row or 0 minutes), 165 games each side of 2026-07-10.
- **Playoffs:** excluded throughout -- a different population, and the Finals are being played now. Nothing here changes
  the board during the playoffs.

## Results (residual = hit rate - Shin probability on the signal's side; CI over games)

| test (side) | discover resid [CI] (n) | confirm resid [CI] (n) | blind ROI best book (d / c) | verdict |
|---|---|---|---|---|
| minutes_trend_up (over; >= +3.3) | -2.0% (850) | -1.6% [-5.7, +2.8] (1,918) | -- | NOT SUPPORTED |
| minutes_trend_down (under; <= -3.3) | +8.6% [-1.0, +18.7] (328) | +3.3% [-0.7, +7.5] (1,702) | -- | NOT SUPPORTED |
| start_promotion (over) | +0.3% (178) | -8.8% [-18.5, +1.2] (268) | -- | NOT SUPPORTED |
| b2b (under; MIN >= 23.3) | +6.8% (157 / 8 games) | +3.7% [-6.2, +16.7] (325 / 17 games) | -- | NOT SUPPORTED |
| **W6a every main line, UNDER** | **+2.3% [+0.4, +4.5]** (8,490) | +0.3% [-1.3, +2.1] (10,226) | -1.1% / -4.7% | NOT SUPPORTED |
| W6b prior-10 MIN >= 25, UNDER | +2.2% [-0.2, +4.5] | -0.3% [-2.2, +1.8] | -1.4% / -5.8% | NOT SUPPORTED |

BH (q = 0.10) on the four signals: none. Unders by market (discover / confirm): **rebounds +3.0% [+0.2, +5.9] / +2.4%
[+0.2, +4.7]** (meets the per-test bar; BH across eight markets: no; best-book ROI +0.6% / -0.7%), assists +4.4% / +0.4%,
threes +3.7% / -0.1%, RA +4.0% / +0.6%, points +2.2% / -0.1%, PRA +0.7% / -1.1%, PR +0.7% / +0.1%, PA +0.7% / +0.3%.

## Reading

1. **Role changes are priced in the WNBA too** -- minutes trends and promotions carry no residual against the close, as in
   the NBA. The minutes-falling under is the nearest miss (+8.6% / +3.3%), not a finding.
2. **The under tilt is not stable in the WNBA.** It was there in May-early July (+2.3%) and gone after (+0.3%) -- the
   reverse of the NBA, where it strengthened late. Across the four sports tested: NBA and NCAAF props carry a ~1.5-2.5
   point under tilt in both windows; WNBA had it for half a season; NHL and NFL (on the registered rule) do not.
3. **Rebounds unders** are the one WNBA market that held in both halves (+3.0% / +2.4%), and rebounds were also a
   per-market survivor of NBA H6 (+1.7%). Across eight markets it does not survive multiplicity, and the best-book ROI is
   ~0. A cross-league "rebounds unders" hypothesis is a candidate for its own registration, not a finding.

## Next (WNBA)

- Nothing goes on the board: no signal passed, and the season is in its playoffs.
- If wanted: a forward test of rebounds unders (WNBA + NBA) registered now, read on the 2026-27 NBA regular season and the
  2027 WNBA season.
