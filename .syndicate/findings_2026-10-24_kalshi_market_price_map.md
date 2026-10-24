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

## Results

(not yet run)
