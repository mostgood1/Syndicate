# Scope — following proven prediction-market traders (our own "Prediction Traders"), 2026-11-17

Asked by the user: "https://oddsjam.com/prediction/traders, figure out how to integrate this into our app",
then "we may need to build our own version of this". Research only; nothing is built. Written by the
portfolio session (lane `portfolio-monitor`).

## What OddsJam sells (read 2026-11-17 in a browser; automated fetches get 403)

- **Prediction Traders**, a paid copy-trading signal service: $15/day ($6.60/day for the first month), 7-day
  trial. It follows "algorithmically selected" traders on Kalshi, Polymarket, ProphetX and Novig.
- **Per signal:** a 0-100 confidence score (trader's bet size, history, current slippage), a bet size, the
  exact market and side, a 1-click venue link, and an exit alert when the trader sells.
- **Its claims (marketing, unverified):** 88% of signals are sports; win rates 51-55%; 220% ROI entering at
  the trader's price vs 61% at -5c and **-20% at -10c**, so entry latency decides the edge. Sizing "optimal" vs
  same-size; exits vs hold-to-resolution; "99% of 5,000 simulated 30-day runs profitable".
- **How it picks traders:** consistent profit and ROI, copyable (no bots or high-frequency traders), category
  experts, 500+ bet history. It filters out arbitragers, high-frequency traders, gamblers, one-hit wonders
  and bots.
- **No API or webhook found** for these signals. OddsJam's public Odds API is a sportsbook-odds product.
  Scraping a paid page into a trading system would likely breach their terms; not pursued.

## What data exists to build it ourselves (verified 2026-11-17)

- **Polymarket (international, on-chain): trader identity is public.** Data API v2,
  `https://data-api.polymarket.com/v2` (v1 is retired, 410). No key needed. Endpoints and fields per the v2
  OpenAPI; leaderboard and trades confirmed live:
  - `GET /v2/trades` is the global tape. Rows carry `proxy_wallet`, `side`, `size` (shares), `price`,
    `condition_id`, `slug`, `event_slug`, `outcome`, `timestamp`, `transaction_hash`. Filters: `condition`,
    `event_id`, `side`, `taker_only`, `limit` (1000), `cursor`.
  - `GET /v2/trades?user=<wallet>` gives full history (`start=1`). `GET /v2/activity?user=` also covers
    REDEEM/MERGE.
  - `GET /v2/positions?user=<wallet>&status=CLOSED` carries `realized_pnl`, `entry_cost_usdc`, `total_pnl`.
  - `GET /v2/leaderboard?time_period=day|week|month|all&sort_by=PNL|VOLUME&category=` returns rows with
    `rank`, `user_id`, `user_name`, `pnl`, `volume`, `verified`. Also `/v2/user-pnl`, `/v2/user-stats`.
  - Rate limits: 800 req/10 s general, 300/10 s trades, 200/10 s positions and activity.
  - No per-wallet stream. The market WebSocket (`ws-subscriptions-clob`) has no wallet field, so
    near-real-time means polling `/v2/trades` (about every 15-30 s is well inside the limits).
- **Kalshi: anonymous.** The public `/markets/trades` rows are `trade_id, ticker, count_fp, yes/no_price_dollars,
  taker_side, taker_book_side, taker_outcome_side, is_block_trade, created_time`, with no trader id. We cannot
  follow Kalshi traders. ProphetX and Novig were not checked.
- **So our version follows Polymarket (international) wallets** and acts on the same game and line where we
  trade: Kalshi and Polymarket US, which lists separate markets from international Polymarket. We already read
  international market metadata (`polymarket_client.py`: gamma-api / clob) and map venues onto games
  (`polymarket_us_markets.py`, `kalshi_board_join.py`).

## A shape for our version (proposal, not decided)

1. **Tape ingest (worker job):** poll `/v2/trades` for sports markets; keep a wallet registry and every
   followed wallet's trades on disk under `SYNDICATE_DATA_ROOT`.
2. **Trader scoring (daily job), our own numbers, not their P&L:** over each wallet's closed sports positions,
   compute ROI, sample size (>= 500 bets), CLV against the close, consistency, category and price band. Exclude
   arbitrage, high-frequency, two-sided and one-hit patterns. Re-score daily; a wallet earns its place on
   measured edge.
3. **Signal:** a followed wallet's BUY on a sports market maps to our game identity and to the same line on
   Kalshi or Polymarket US. Record the venue's ask at signal time and the delay since the wallet's fill.
4. **Shadow first (non-negotiable):** paper orders on the signal, graded in the execution ledger. Measure ROI
   and fee-net CLV by delay bucket, confidence bucket and sport, against the adopted scale-up gate
   (`live_book_edge_readout.py`).
   - Live money only after it passes. Any live use is a betting change: it restarts the 800-event count and
     needs a register row.
5. **Latency path:** the live-odds-worker executes about every 5 min. OddsJam's own chart says -10c of delay
   turns +220% into -20%, so a live version needs an immediate path, not the batch tick.
6. **Economics check:** at today's caps (~$134 Kalshi + ~$72 Polymarket US a day), a 5% edge on full use is
   ~$10/day. A $15/day subscription would cost more than that; our own build costs compute and API calls only.

## Open questions

- Whether international Polymarket sports traders' edge carries over to Kalshi / Polymarket US prices; the
  shadow study answers it.
- Mapping coverage: the share of followed-wallet sports trades that map to a market we can trade.
- Whether OddsJam would sell an API feed (the user's call to ask).
