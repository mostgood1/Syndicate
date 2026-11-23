# Portfolio monitor -- 2026-11-23 (lane portfolio-monitor, session 69d80317)

Counts and percentages only (public repo).

## Purchaser vs Layer 2 board vs live rail -- 1:07 PM CST (19:07Z), same-instant read

The user asked how the purchaser's decisions line up with the rail and the Layer 2 board.

**Method, read-only, all at 19:07:04-05Z:**

- From the fleet API:
  - `/api/portfolio/live` (today's orders) and `/api/portfolio/live?on=all&show=all` (7-day history);
  - `/api/board/live-rail`;
  - `/api/board/layer2-shortlist?date=2026-11-23&limit=2000`. That returned 2000 rows, the route's own maximum, out of
    33,586 opportunities considered.
- Both venues' LIVE plans and paper2 plans, read from refresh-worker's store under its own environ (`/mnt/c/tmp/w_align/read_live_plans.py`). They were written 13:04 CST.
- Match key: event_id, market, line, player, segment and side.
- The board is read NOW, while the orders were placed earlier. A row that has moved or dropped since a purchase
  shows below as "not the same row"; it is not counted as a conflict.

**The chain, from the code:**

1. The Layer 2 shortlist feeds every plan (`pipeline/portfolio_commit.py`).
2. The live plans read the board's Suggested rows PLUS every row the Suggested flag refused for EV alone (the 0% live
   EV floor, `live_ev_floor_rows`).
3. Each row is repriced at the venue's own price (`scope_rows_to_venue`).
4. A row is placed only if it clears the venue's net-of-fee floor.

The rail's rows are `source=layer2_inplay_overlay`: the board's in-play overlay.

| reading | value |
|---|---|
| Board Suggested rows | 36 of 2000 (NHL 13, soccer 12, NCAAF 6, NCAAB 3, NFL 1, WNCAAB 1) |
| Suggested rows bought today / in a live plan now | **0 of 36 / 0 of 36** |
| Suggested rows the venue lists (paper2 scope) | Kalshi 20 (14 not quoting, 2 implausible); Polymarket 6 (29 not quoting, 1 implausible) |
| Those, at the venue's own price | 0 positions. Kalshi: 15 below min EV, 1 below min EV net of fee, 2 below min stake, 2 in-play market-fair. Polymarket: 3 below min EV, 1 below min stake, 2 in-play market-fair |
| Live plan positions now | 7 (Kalshi 1, Polymarket 6). All 7 `suggested=False` and `live_ev_floor=0`. Board rank 72-561 of 2000 for 5; the other 2 are not in the top 2000 |
| Live plan funnels | Kalshi: 480 rows in, 469 below the live net floor. Polymarket: 412 in, 291 below the floor, 102 aggregator-priced |
| Today's 32 orders vs the board now | 15 (47%) the same row, **none of them Suggested**: board EV <= 0 on 11 of 15, model edge <= 0 on 11 of 15. 5 (16%) the board now shows only the OTHER side of that line. 5 (16%) the same game and market at a different line. 7 (22%) not on the board (3 games started) |
| Today's orders' sim verdict at order time | disagrees 17, agrees 9, neutral 6 (of 32). `side_picked_by=price_shopping` on 32 of 32 |
| 7-day live orders (selected_date >= 11-16) | 446: 410 pregame, 36 in-play (8%) |
| 7-day sim verdict at order time | agrees 142 (32%), neutral 138, disagrees 126 (28%), none 40; `sim_share_of_stake > 0` on 0 of 446 |
| 7-day in-play orders | NBA 12, NHL 9, NFL 8, NCAAF 7; sized `inplay_order_dollars`; no EV recorded at order. Rejected 10 of 36 (28%), against 7 of 410 pregame (2%) |
| Rail now | 85 rows, all NCAAB in play (soccer `stale_55667s`, WNCAAB 0). Model edge on 2 of 85. 7 of 85 share a key with a board row. 0 of today's orders on a rail game; 0 NCAAB in-play orders in 7 days |
| Live plan in-play refusals | `in_play_market_fair`: Kalshi 3, Polymarket 5 (an in-play row with only a market fair is not bought) |
| 7-day graded win rate by sim verdict (WIN RATE, not ROI; prices differ) | agrees 56% (n=122), disagrees 59% (n=99), neutral 58% (n=131) |

**Reading.**

- **Shared universe.** Every purchase starts as a Layer 2 row.
- **Selection is not aligned.** The board's Suggested set is not what is bought: 0 of 36 today. Most of it is markets
  the venues do not list (alternate corners, NHL props), and the rest falls below min EV at the venue's own price.
- **What is bought instead.** The money goes to rows the board ranks lower but that clear the fee at a venue price,
  through the user's 0% live EV floor. The side is picked by price.
- **The sim.** It disagrees with about 28% of buys and agrees with about 32%. This is by design: stakes follow price
  until a model is measured to beat the market (state `[portfolio-sim-sizing-gate]`).
- **The rail.** It is almost disconnected from buying: 2% of its rows carry a model edge, and the plans refuse in-play
  rows with a market fair only. In-play buys are 8% of orders, recorded without an EV, and none is in the one sport the
  rail shows now.
- Nothing here was changed. No ledger or venue write.
