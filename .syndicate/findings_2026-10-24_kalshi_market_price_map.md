# Kalshi market-wide price map (Test A): is there ANY structural edge in our sports series under today's fees?

Lane `pm-trader-strategies`, session dbda2142.
- **The user's decision**, via coordinator 332cb014, 2026-10-24: "A: Market-wide price map".
- **Design source:** `findings_2026-10-24_pm_trader_strategies.md` §3, Test A.
- **Scope:** research only. Public, unauthenticated Kalshi `GET`s and nothing else: no order, no credential, no fleet env/cap/deploy change. The job runs at Idle / nice 19.

## PRE-REGISTRATION (committed BEFORE any trade was fetched for analysis and before any return was computed)

**What had been looked at when this was written:** endpoint shapes only.
- `/markets?series_ticker&status=settled`: counts per series since about 08-18.
- `/historical/markets`: back to 2025-08 for KXNFLGAME.
- `/markets/trades` and `/historical/trades` with `max_ts`, and their fields (`taker_side`, `yes_price_dollars`, `count_fp`, `created_time`).
- `/series/<s>` fee types.
- That one moneyline market had 5,000 prints in its last 4 minutes, and that totals markets close mid-game once the line is crossed.
- The rate ceiling: about 4 requests/s, and parallel requests draw 429s.
- No trade was joined to a result and no return was computed.

### Series (game, spread, total, full game; today's `fee_type` / `fee_multiplier` read 2026-10-24)

| sport | series | fee type (game / spread / total) | multiplier |
|---|---|---|---|
| NFL | KXNFLGAME, KXNFLSPREAD, KXNFLTOTAL | maker-fee / maker-fee / maker-fee | 1 |
| NCAAF | KXNCAAF{GAME,SPREAD,TOTAL} | maker-fee x3 | 1 |
| NBA | KXNBA{GAME,SPREAD,TOTAL} | maker-fee x3 | 1 |
| NHL | KXNHL{GAME,SPREAD,TOTAL} | maker-fee / quadratic / quadratic | 1 |
| MLB | KXMLB{GAME,SPREAD,TOTAL} | maker-fee / quadratic / quadratic | 0.5 |
| soccer | KX{EPL,LALIGA,SERIEA,BUNDESLIGA,LIGUE1,UCL,MLS}{GAME,SPREAD,TOTAL} | maker-fee / quadratic / quadratic (MLS: quadratic x3) | 1 |

Fees are re-read from `/series` at run time; a series whose fee cannot be read is skipped and counted.

### Population and sampling (seed 20261024)

- **Games:** every settled event in those series with a moneyline close in **[2025-07-01, 2026-10-24]**, from `/historical/markets` plus `/markets`.
  - A GAME is the event-ticker suffix after the series prefix, e.g. `26OCT22NECHI`, keyed with the sport. It is the cluster unit.
  - **Game end** = the moneyline market's `close_time` (it closes when a winner is declared). Totals cannot supply it, since they close early.
- **Halves:**
  - **DISCOVER** = game end before 2026-09-01T00:00Z.
  - **CONFIRM** = game end on or after it.
- **Per sport and half:** a uniform random sample of up to **350 games**. Within each game:
  - 1 moneyline market (random side; soccer: random among the 3);
  - up to 2 random spread strikes;
  - up to 2 random total strikes.
- **Trades:** for each sampled market, 6 anchor windows, each the up-to-100 prints at or before the anchor (`max_ts`).
  - Pregame anchors: `start - 12h`, `start - 3h`, `start - 45m`.
  - In-play anchors: `end - D/2`, `end - 15m`, `end - 4m`.
  - Here `start = end - D`, with D = NFL 3.25h, NCAAF 3.5h, NBA 2.4h, NHL 2.6h, MLB 2.9h, soccer 1.95h.
  - Prints are de-duplicated by `trade_id`.
- **Phase of each print, by its own timestamp:**
  - pregame if `t < end - D - 45m`;
  - in_play if `end - D + 15m <= t < end - 15m`;
  - final if `t >= end - 15m`;
  - otherwise EXCLUDED (the start-time uncertainty band) and counted.
- **Excluded and counted:** a result not in {yes, no} (voided or scalar); a print after the market's own close; block trades.

### Returns (per contract, dollars)

Each print gives two positions:
- **TAKER:** side `taker_side`, price `p` = that side's price.
- **MAKER:** the opposite side, at `1 - p`.

For a side bought at price `q`:
- `r = 1[side won] - q - fee`.
- Taker fee = `0.07 * mult * q * (1 - q)`, per contract, unrounded. Real fees round up per order, which only makes takers worse.
- Maker fee = `0.0175 * mult * q * (1 - q)` on `quadratic_with_maker_fees` series, else 0. The 0.0175 coefficient comes from a third-party source, so maker fee 0 is reported as a sensitivity.

The fee is TODAY's schedule applied to every print: "would this have paid under current fees".

### Cells and statistics

- **PRIMARY cells:** price bucket of the side's price (1-10, 10-25, 25-40, 40-55, 55-70, 70-85, 85-95, 95-99c) x side (taker / maker) x phase (pregame / in_play / final), POOLED over sports and families. That is 48 cells.
- **SECONDARY, reported and decided the same way only where large enough:** the primary cells split by sport, and by family (game / spread / total).
- **Primary metric:** mean `r` per print, equal weight per print, in cents per contract. Contract-weighted mean and ROI (`sum r*count / sum q*count`) are reported, never decided on.
- **CI:** game-clustered bootstrap, 2,000 draws, seed 20261024, 95%.

### Decision rule (fixed now)

**STRUCTURAL EDGE in a cell** iff all of:
- the CONFIRM mean `r` has a 95% CI lower bound **> 0**;
- the DISCOVER point estimate is **> 0**;
- **both halves have >= 300 games** contributing prints to the cell.

Any other outcome:
- **INSUFFICIENT:** a half has fewer than 300 games.
- **FALSIFIED:** the CONFIRM CI upper bound is <= 0.
- **OPEN:** otherwise.

**KILL (the test's stated purpose):** no PRIMARY cell reaches STRUCTURAL EDGE. Then, under today's fees, pregame and in-play structural edges in our series are closed to a price-band rule. The remaining lever is a model that beats the close (Test B, profit-program).

**What a pass means:**
- **TAKER cell passes:** a candidate entry band for the per-cell live gate (owner profit-program / coordinator). It is not a strategy by itself.
- **MAKER cell passes:** a PRIOR for maker-orders-study and kalshi-maker-shadow. A market-wide maker return is not our fill: our own fills were adversely selected (10-19 study).

**Known limits, stated now:**
- Anchored windows sample prints near 6 instants, not uniformly in time.
- `D` is a per-sport constant, not each game's real start. The exclusion band absorbs about ±45 min.
- Pre-cutoff history is read from `/historical/*`.
- The sample is random games, so a result describes the average game, not the most liquid one.

## Results (run 2026-10-24 23:20Z .. 10-25 08:15Z; recheck 08:20Z .. 10:22Z; Windows Idle priority)

**Substrate.**
- 3,566 sampled games, 98,853 public GETs, 3.51M prints read.
- Excluded: 110,856 in the start-time band, 634 after a market's own close.
- Games by sport (DISCOVER / CONFIRM):

  | sport | DISCOVER | CONFIRM |
  |---|---|---|
  | MLB | 350 | 350 |
  | NBA | 350 | 95 |
  | NCAAF | 350 | 350 |
  | NFL | 350 | 93 |
  | NHL | 350 | 228 |
  | soccer | 350 | 350 |

- Raw output on the host: `C:/tmp/kalshi_price_map/`: `report.md`, `report_makerfee0.md`, `recheck_report.md`, `games/`, `recheck/`.

### 1. As registered: KILL not met. 14 of 48 primary cells reach STRUCTURAL EDGE

- **All 14 are IN-PLAY or FINAL cells on the favourite side:**
  - maker 55-100c in_play and final;
  - taker 70-100c in_play and final.
- Point sizes run from about +1.3c (95-100c) to +10-14c (70-85c in the final 15 min).
- **No pregame cell passes.** All 16 pregame cells are OPEN or INSUFFICIENT.
- **Longshots are FALSIFIED in play, both sides:**
  - taker 1-10c: -2.1 to -2.8c;
  - 10-25c final: -11.8c;
  - 25-40c final: -16.2c.
- The maker-fee-0 sensitivity changes no conclusion (55 passes in all scopes vs 54).

### 2. The registered design has a look-ahead bias, and most of the 14 are that bias

The in-play windows and phases were anchored on each game's ACTUAL end (the moneyline close). "This game ends within 15 minutes" is not known in real time. It selects games with no comeback, overtime or extra innings, and those are games the leader wins. That inflates favourites by construction, most of all in the final-15-min cells, which is where the passes are biggest.

**The check (NOT pre-registered; labelled as such).**
- MONEYLINES only, re-sampled at windows anchored on the SCHEDULED start: `expected_expiration_time - 3h`, set before the game. MLB tickers carry the start time, and it agrees.
- Only windows that open before the market closed are kept, and phase is time elapsed since the scheduled start.
- Scheduled start to close, median hours (a sanity check on the offset):

  | sport | median hours |
  |---|---|
  | MLB | 2.92 |
  | NBA | 2.73 |
  | NCAAF | 3.64 |
  | NFL | 3.16 |
  | NHL | 3.08 |
  | soccer | 2.08 |

| moneyline, favourite cells | end-anchored (registered) | start-anchored (real-time) |
|---|---|---|
| taker 85-95c, final / late | +7.21c [+4.51, +9.08] | **+1.22c [-1.98, +4.28]**, OPEN |
| taker 70-85c, final / late | +15.44c [+4.80, +21.05] | **+1.78c [-2.95, +6.26]**, OPEN |
| maker 70-85c, final / late | +18.40c [+14.51, +21.13] | **+0.76c [-4.49, +5.62]**, OPEN |
| taker 85-95c, in play / mid | +2.20c [-0.31, +4.40] | +1.02c [-2.08, +3.82], OPEN |
| **taker 95-100c, late** | +1.42c [+0.90, +1.80] | **+1.09c [+0.15, +1.74], STRUCTURAL EDGE** |
| **taker 95-100c, mid** | n/a | **+1.63c [+0.96, +2.14], STRUCTURAL EDGE** |
| **maker 95-100c, late / mid** | +1.22 / +1.59c | **+1.41c [+1.02, +1.68] / +1.29c [+0.36, +1.99], STRUCTURAL EDGE** |

**What the comparison shows.**
- In real time, **every 55-95c favourite cell collapses to about 0 (OPEN). Only the 95-100c cells survive**, for both the taker and the maker, early, mid and late.
- The longshot cells stay FALSIFIED (1-10c: taker -1.3 to -1.7c, maker -1.7 to -2.4c).

**Independent confirmation from in-play-program's Test C** (`findings_2026-10-20_in_game_trading.md` §12, a3a9d770).
- It uses the recorder's real-time ESPN clock and the ask we would pay, on 69 games.
- Late favourites, taker 85-97c: **-1.7c per game [-4.6, +1.1]**.
- Late longshots, under 25c: -4.4c [-6.3, -2.3].
- Same verdict: the late-favourite edge is not there in real time, and the late-longshot overpricing is.

**The 95-100c cell (taker, in play, start-anchored) by sport.** The table is DISCOVER / CONFIRM, mean cents per contract.

| sport | DISCOVER | CONFIRM |
|---|---|---|
| MLB | +1.43 | +1.15 [-0.22, +2.17] |
| NBA | +1.44 | -1.38 (68 games) |
| NCAAF | +1.89 | +1.15 [-0.40, +2.16] |
| NFL | -0.63 | +2.26 (31 games) |
| NHL | +1.73 | **+2.19 [+2.03, +2.33]** |
| soccer | -0.30 | +1.42 [+0.86, +1.83] |

- Share of in-play 95c+ taker prints that LOST: NHL 0.44%, NCAAF 1.00%, MLB 1.14%, soccer 1.40%, NBA 1.41%, **NFL 2.74%**.
- In other words: a positive mean made of many +1-4c wins and rare -95c losses, and it is weakest in the NFL.

## Reading

1. **Pregame: no structural edge in our series under today's fees.**
   - Not one of the 16 pregame cells passes, taker or maker, at any price.
   - Pregame cells are barely touched by the end-anchoring issue: they sit 45+ min before the nominal start.
   - So a price-band rule alone cannot make the pregame book positive. The remaining pregame lever is a price that beats the close: Test B, where Pinnacle edge >= 0.4 is +11.2% on 721 orders, the one live lead.
2. **Longshots: never buy them.** Below 10c they lose in every phase. Late in a game, 10-40c loses 12-16c a contract. This agrees with Bürgi-Deng-Whelan, Moshrefi and our own in-play buckets.
3. **The one surviving structural cell is near-certain favourites in play (95-99c).**
   - Size: about +1.1 to +1.6c per contract, roughly 1.2-1.7% of stake, net of today's taker fee. It holds across five of six sports.
   - It matches the literature's high-price result (+3.1% pre-fee at 95c, Bürgi-Deng-Whelan).
   - **It is small and tail-heavy.**
     - A $10 stake earns about 12-17c expected, against a 1-3% chance of losing about $9.70.
     - Documented tails: Eagles-Jaguars 2026-10-11 traded at 97c+ with 8 s left and settled at 1c. The Giants-Angels score correction split settlements.
     - The mean rests on prints that happened, not on depth we could take.
4. **The registered verdict ("KILL not met, 14 cells") is the literal outcome, and it is recorded.** The 10 cells in the 55-95c range are an artifact of the design's look-ahead, shown by the recheck and by Test C. That is a design error in this lane's pre-registration. The general rule (do not anchor a real-time cell on an outcome-time quantity) is proposed for `learnings.md`.

## Recommendation (user decision, via the coordinator)

- **(R1) Pregame:** no price-band entry rule. Optionally refuse pregame buys under 10c; 044e2634 measured that as 0.1% of stake, so it is housekeeping.
- **(R2) In play:** keep "never buy under 25c late". in-play-program's exit and entry rules already point this way.
- **(R3) A PAPER cell for 95-99c in-play favourites (Kalshi moneylines), pre-registered, owned by in-play-program** (its recorder already samples the real-time ask).
  - Rule: buy the favourite at the ask when it is 95-99c with the game in play (real-time clock), at most once per market per game, held to settlement.
  - Metric: per-game net return.
  - GO: >= 150 games with a game-clustered 95% CI lower bound > 0. It must also hold with NFL excluded and with NFL alone reported.
  - Kill: CI upper bound < 0 at 150 games, OR a realised loss rate above 3% at 150 games.
  - **Not live.** Even at GO the expected value is about 1.5% of a small stake.
