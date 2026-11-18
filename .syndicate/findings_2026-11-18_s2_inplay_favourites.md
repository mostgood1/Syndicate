# Findings — study S2 of the profit learning program: in-play 95-99c favourites (2026-11-18)

Asked for by the user 2026-11-18 ~2:10 PM CST: "start study S2 on the in-play favourites". Written by the portfolio
session (lane `portfolio-monitor`). Read-only: nothing live, no env, no fleet state changed. Not financial advice.

## Verdict: KILL, under the cell's own pre-registration — S2 is closed and no challenger goes to a window

## Origin

- `findings_2026-10-24_kalshi_market_price_map.md`: on public Kalshi prints, the only structural cell to survive
  fees in real time was **in-play favourites at 95-100c**: +1.1..+1.6c per contract, taker and maker, positive in 5
  of 6 sports.
- That lane's recommendation R3 became a **pre-registered PAPER cell owned by lane `in-game-trading`**:
  `findings_2026-10-20_in_game_trading.md` section 14, locked 2026-10-25 (commit `679bd119`), before any result.
- The program plan's S2 ("forward-confirm on the recorder nights with the ESPN clock") is that same test. So S2 is
  read under R3's registration, not under a new one: a fresh registration written after seeing R3's first read
  would be weaker.

## R3's registered rule (verbatim in `scripts/inplay_late_cells.py`)

- Kalshi moneyline tickers (`KX*GAME`) for NBA, NHL, NCAAF and NFL, settled only.
- In play means the latest ESPN row at or before the quote says "in". This is real time, never the game's end.
- Buy the favourite at the ask when the ask is in [0.95, 0.99). One entry per game: the first qualifying quote.
  Held to settlement.
- Net return per game = won - ask - fee, with fee = 0.07 x p x (1 - p).
- **GO:** >= 150 games, and the game-clustered 95% CI lower bound > 0 (also ex-NFL).
- **KILL:** at >= 150 games, a CI upper bound < 0, **or a realised loss rate above 3%**.

## The read

- **Source:** `C:\tmp\inplay_late_cells.txt` / `.json`, written by the nightly recorder task (`inplay_nightly.py`)
  at 2026-11-18 02:13 CST over every recorded night.
- **Nights:** 27 (10-20, 10-22..11-17; 10-21 was not recorded). The same nights are now also in the fleet research
  store (`~/syndicate-prod/data/research/inplay_recorder/`).

| set | games | mean net per game | 95% CI | games won |
|---|---|---|---|---|
| **pooled (registered)** | **476** | **+0.26c** | **[-1.59, +1.95]** | **457 (loss rate 3.99%)** |
| ex-NFL | 439 | +0.37c | [-1.60, +2.10] | 422 |
| NBA | 151 | +1.07c | [-2.21, +3.72] | 146 |
| NCAAF | 130 | +1.25c | [-1.87, +3.61] | 126 |
| NHL | 158 | -1.02c | [-4.25, +2.09] | 150 |
| NFL | 37 | -1.02c | [-9.10, +4.47] | 35 |
| pooled, fee rounded up to 1c (sensitivity) | 476 | -0.43c | [-2.29, +1.25] | 457 |

- **KILL as registered.** 19 of 476 entries lost, a loss rate of 3.99%, above the 3% line at 476 >= 150 games. The CI
  also spans 0, so it could not have been a GO.
- **After the lock alone** (derived arithmetic, not a separate run):
  - the 10-25 first read was 67 games, -3.2c, 5 losses, on nights 10-20..10-24;
  - the remaining 409 games average about +0.8c with 14 losses: a loss rate of about 3.4%, also above the line.
- **The shape is the one the price map warned of.** Each win earns +1 to +4c, and each loss costs about -96c. At a
  ~0.97 ask, about 3% losses already eat the margin. The real-time first-qualifying ask loses about 4%.

## What it means for the program

- The near-certain in-play favourite is priced about right after fees in real time. The +1.1-1.6c on public prints
  does not survive the first-qualifying-ask entry that a bot would actually make.
- Nothing goes to the 11-24 window from S2. No new variant is registered here: with 19 losses in 476 games, a filter
  fitted on what predicts those losses (time left, margin, sport) would be fitted on about 19 events.
- What is left of the cell belongs to **S3 (maker entry)**. The price map's maker 95-100c cells were +1.3-1.4c. A
  resting bid does not pay the ask, but its fills are adversely selected: it fills when someone sells to it, which is
  more often just before a flip. Testing that needs fill modelling, not a quote replay. That makes it S3's question,
  not S2's.
- R3 keeps printing nightly in `inplay_late_cells.txt` to its 12-31 stop. A KILL at >= 150 games is final under its
  registration, so later prints are descriptive.
- Lane `in-game-trading` owns R3. Its findings file has no read after 10-25. This file records the verdict, and that
  lane may copy it into its own section.
