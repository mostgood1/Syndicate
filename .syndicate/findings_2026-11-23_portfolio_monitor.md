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

## Who cancelled the 11-21 unfilled Kalshi order? Its own kickoff expiry -- 1:13 PM CST

The ask was relayed by the fleet-watcher on the user's words, about 1:10 PM CT: "no, I didn't cancel it", then
"yes, ask the portfolio session to trace it". The order is one Kalshi h2h order of 11-21: a men's NCAAB away moneyline,
placed on the WOMEN's game market (the series is the women's-basketball game series). It ended with 0 of 1 contract
filled. The order id and ticker are kept out of this public file; the fleet-watcher has them.

Everything below is read-only: the fleet role logs, the ledger row via `/api/portfolio/live?on=all`, and ONE
`GET /portfolio/orders/{id}` at Kalshi under live-odds-worker's environ (`/mnt/c/tmp/w_align/kalshi_order_read.py`, which
prints an allowlist of fields).

| time (11-21, UTC) | source | what |
|---|---|---|
| 17:40:33 | live-odds-worker `[kalshi_orders] SUBMIT` | `tif=good_till_canceled`, `expiry=1795296600` = **21:30:00Z**, the board game's `commence_time` (`SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF`, user decision 2026-10-20 "Build option C") |
| 17:40:50 | `[execution_ledger] RECONCILED` | `venue_status='resting'`, 0 contracts |
| 18:26:35 | `[execution_ledger] CANCEL_SKIPPED_NO_PRICE` | the stale pass could not read a price and left the order resting; no cancel request was sent |
| 21:25-21:36 | all role logs | NO cancel or exit request for this order from any role |
| **21:30:00.000078** | **Kalshi's own record** | `status=canceled`, `expiration_time=2026-11-21T21:30:00Z`, `last_update_time=2026-11-21T21:30:00.000078Z`, fill 0 of 1, remaining 0 |
| 21:32:16 | `[execution_ledger] RECONCILED` | `submitted->rejected venue_status='canceled'`: our reconciler RECORDED it; it did not cause it |

**Verdict.** Nobody cancelled it.
- Kalshi expired it at the `expiration_time` our own executor set at submit, the kickoff of the board game. Kalshi
  reports an expired order as `canceled`.
- The venue's update time is 0.08 ms after the expiry, which leaves no room for a person, another process or another
  session.
- So nothing outside our three roles placed or cancelled a live order. I did not search the session transcripts: the
  venue's record settles it.

**Two side notes, not causes.**
1. This order is an **F27 case**: a men's game paired with a women's Kalshi market. F27's fix,
   `SYNDICATE_KALSHI_JOIN_SPORT_SCOPE=on`, is CHANGE L of the 11-24 batch.
2. The ledger row's `venue_resolved_at` / `settled_at` read 17:40:34Z, the submit acknowledgement, on a row that ended
   at 21:30Z. Do not read those fields as the cancel time; that misled the first timing guess here.

## Alignment check added to every Portfolio Watch reading -- 1:45 PM CST

The user, 11-23: "yes, add the alignment check to the readings".

**The probe** (`scripts/portfolio_monitor_probe.py`) has a new `alignment` section and prints an `ALIGNMENT` block. It
covers:
- the board's Suggested rows bought today and in a live plan;
- per venue: how many Suggested rows it lists, how many clear its price, and the live plan's positions;
- today's orders against the board's row: same row (and whether that row is Suggested, board EV > 0, model edge > 0),
  other side only, other line, off board;
- the sim's verdict at purchase and the in-play share, over the last 7 CST days;
- the rail: rows, how many carry a model edge, how many are also board rows, and today's orders on a rail game.

**The reader** (`scripts/portfolio_alignment_reader.py`, new) reads the whole shortlist and the venue plans from the
fleet's store, under refresh-worker's environ, at nice 19. It is run through WSL, and it prints key fields and flags
only.
- Why the store and not web: web caps a shortlist reply at 2,000 rows. The board holds about 4,500, and per-sport web
  reads would cost about 14 MB a reading.
- Measured cost: 1.9 s, 205 MB peak, 1.1 MB of JSON. The whole reading takes 12.5 s.

**The page.** It gains a "Purchaser vs Layer 2 board and rail" panel: five tiles and a series chart
(`scripts/portfolio_watch/build_page_data.py` `_align_fields`, `build_dashboard.py`).
- Informational: it raises no anomaly.
- Tests: 24 probe tests and 7 Portfolio Watch tests pass. The page build was checked in the browser.

**The full board corrects the first reading's order match.** The 1:07 PM reading above used the API's capped 2,000
rows. The 1:34 PM test reading read all 4,479 rows:
- today's 33 orders: **same row 22 (67%), none of them Suggested**; board EV > 0 on 10 of 22, model edge > 0 on 4 of 22;
- other side only 4, other line 4, off board 3;
- Suggested rows: 45, of which **0 were bought today**. Kalshi lists 21 (1 clears its price) and Polymarket 7 (1 clears);
- live plans: Kalshi 3 positions and Polymarket 4, none Suggested;
- 7 days: the sim agreed with 31% of 396 purchases and disagreed with 29%. In-play buys were 8%, and 27% of them were
  rejected, against 1% pregame;
- rail: 15 of 169 rows carry a model edge.

**Lane.** The `portfolio-monitor` `Files:` line read "(NEW, read-only probe)", and "read-only" is a lane-claims
disclaimer marker. Every path after it had been claimed by nobody. The line was rewritten without marker words and
now claims 9 of 9 paths, 0 lost (`.claude/hooks/lane_claims._claims`). The new reader was added to it.

## Why none of the board's Suggested rows are bought -- HYPOTHESIS (written before the per-row test), 1:44 PM CST

The user, 11-23: "why are none of the board's picks being bought? ... we need to solve for this since portfolio
endpoint is trading on real money".

**H1, venue price.** The board's Suggested flag (`layer2_board._suggested_reasons`) requires:
- +2% EV net of fee at the BEST book quoting the line (any sportsbook);
- a two-book fair.

The purchaser can trade only Kalshi and Polymarket, and repricing at the venue's own price (`venue_scope`) removes the
edge. So a Suggested row is either not listed at the venue, or listed at a price with EV <= 0. The plan's `min_ev_pct`
is 0.0 (env), so a `below_min_ev_pct` refusal means EV < 0 at the venue's price.

**H2, two populations.** The rows the purchaser does buy are mostly ones the board refused for EV alone
(`live_ev_floor` = 0, user 2026-10-20). For those, the venue is itself the best book, or close to it, with a net EV
between 0% and 2%.

**Falsified if** most listed Suggested rows show EV >= 0 net of fee at the venue's price and are refused for another
reason (stake, cap, positions, a join, or a price-source problem). That would make it a purchaser defect, not a price
difference.

### RESULT, 1:49 PM CST: H1 SURVIVES; H2 SURVIVES; the purchaser is not dropping good bets

Method, read-only. Each Suggested row, and each row of today's live orders, was repriced at Kalshi and Polymarket by
the plan's own code (`_venue_price_resolver` + `scope_rows_to_venue`), under refresh-worker's environ, at 19:46Z
(`/mnt/c/tmp/w_align/suggested_diag.py`). The board had 4,550 rows, 34 of them Suggested.

**Where the board's edge comes from.** The board's best book on its 34 Suggested rows:

| best book | Suggested rows |
|---|---|
| BetMGM | 10 |
| DraftKings | 5 |
| BetRivers | 5 |
| FanDuel | 4 |
| ProphetX | 3 |
| Novig | 3 |
| Bovada | 2 |
| Kalshi | 1 |
| Pinnacle | 1 |

That is 33 of 34 at a book the purchaser does not trade. Median net EV at that book: +2.9%.

**The same rows at the venues the purchaser trades:**

| venue | listed | not listed | net EV > 0 at the venue's price | net EV >= 2% |
|---|---|---|---|---|
| Kalshi | 23 | 9 not quoting, 2 implausible | 3 (+0.3, +0.3, +1.0%) | **0** |
| Polymarket | 10 | 23 not quoting, 1 implausible | 3 (+0.3, +0.8, +1.0%) | **0** |

The other listed rows are negative at the venue: Kalshi typically -3 to -8% net, NHL props -3 to -7%.

**The venue joins are correct.** For every listed row, the matched market is the same game, player, line and side (for
example `KXNHLAST-...-UTAMWEEGAR52-1`). The pregame gap is the price itself: sportsbooks pay more than the two
exchanges on these lines.

**A SECOND DEFECT, in the board and not the purchaser: 7 of the 34 Suggested rows are NCAAB games already in play.**
Their best-book price is far from the live venue price:
- Charlotte @ FGCU moneyline: the board shows Kalshi -669, while Kalshi's live feed reads -9900;
- Long Beach St @ FIU: +390 at DraftKings, against +178 on Kalshi and +156 on Polymarket;
- Ole Miss @ Clemson under 149.5: -115 at Bovada, against -156 and -203.

The purchaser refuses these correctly (`in_play_market_fair`, or EV < 0). But the board labels them Suggested on
prices that no longer exist, and `suspect_stale_quote` did not catch them.

**What the purchaser buys instead.** Today's 33 live orders: 19 matched a board row at 19:46Z. All 19 are
non-Suggested. Their reasons were EV-only for 11 (`ev_below_min` and/or `ev_net_of_fee_below_min`), and
`ev_below_min` + `suspect_stale_quote` for 8 (NBA alt lines). The board's best book for those rows was the order's own
venue on 7 of them.

**Results by admission path.** Settled live orders since the 0% floor began, 2026-10-20 (floor position log, 3,910
entries). ROI on stake with a 95% range clustered by game, 2,000 resamples:

| path | bets | games | ROI | 95% range | won-lost |
|---|---|---|---|---|---|
| admitted by the 0% floor (non-Suggested) | 1,249 | 663 | **-7.06%** | **[-13.60, -0.46]** | 717-531 |
| every other live order (Suggested path, in-play, maker pilot) | 660 | 396 | -6.37% | [-13.83, +1.15] | 328-332 |

The floor population **loses beyond noise**. The floor's own stop rule (user 2026-10-20: "revert to Suggested-only if
live 0-2% rows show ROI below -5% after 100 settled bets") would read TRIPPED, 1,249 settled at -7.06%. That global
stop was replaced on 2026-10-24 by the per-cell gate (user "Per-cell trip only (C)"), which keeps admitting rows cell
by cell. The other path is not better at the venue price either: its point estimate is the same and its range includes
zero.

**Verdict.**
- Nothing in the purchaser drops a good bet. The board's Suggested flag answers "is this +EV at the best sportsbook?",
  and the purchaser can only ask "is this +EV at Kalshi or Polymarket?". On today's board the answer to the second is
  no for all 34 picks (0 at >= 2% net).
- The money goes through the 0% floor, onto thin venue edges the board itself rates below its bar, and that
  population has lost beyond noise.
- Separately, the board marks stale in-play NCAAB rows Suggested.
- Decisions owed to the user (no change made): the floor (a betting change, window or risk reduction); a venue-priced
  view on the board (display only); the in-play stale Suggested label (board defect, Layer 2).

### The floor by venue EV at purchase -- 2:14 PM CST (asked for a recommendation on the floor)

Settled live bets since 2026-10-20, split by the order's recorded `ev_pct` at purchase. ROI on stake, with a 95%
range clustered by game:

| path | EV band | bets | games | ROI | 95% range |
|---|---|---|---|---|---|
| floor | 2-4% | 386 | 256 | -9.16% | [-19.46, +1.58] |
| floor | 4%+ | 845 | 516 | -6.10% | [-15.27, +3.06] |
| floor | <2% | 18 | 14 | n too small | |
| not floor | 2-4% | 64 | 57 | -37.14% | [-60.58, -10.70] |
| not floor | 4%+ | 127 | 103 | +3.11% | [-17.16, +21.96] |
| not floor | no EV (in-play) | 469 | 285 | -4.87% | [-13.42, +3.62] |

**A higher edge bar does not rescue the floor.** The bets recorded at 4%+ EV lost about as much as the rest, so the
EV the purchaser computes at the venue's price is not showing up in results.

**The switch** is ONE role-scoped line in `~/syndicate-prod/local_production.env` (line 141):
`REFRESH_WORKER__SYNDICATE_LIVE_EV_FLOOR=0`. refresh-worker's environ reads it; web and live-odds-worker are ABSENT.
Absent means off, which makes the live plans Suggested-only. Removing the line is a betting change. It would load in a
drained full down/up, and the 11-24 2:15 AM batch is already doing one.

## The in-play market-fair refusal's env key: no exposure -- 2:25 PM CST

Raised by the consistency-oversight session (surface-consistency-oversight): `_refuses_in_play_market_fair` returns
False on a role without `SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS`. live-odds-worker lacks the key, and no env layer
it parsed sets it. Traced, read-only:

- **Where the key is set.** In `~/syndicate-prod/fleet_env/refresh-worker.json`, the frozen 10-01 snapshot layer. That
  parse missed it. refresh-worker's environ reads `mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,soccer`. live-odds-worker and the
  supervisor read ABSENT.
- **Who runs the refusal.** Only `commit_portfolio` and `paper_ladder` call it. The plan commit runs ONLY on
  refresh-worker: over the 3 h to 2:25 PM CST, refresh-worker logged 38 `PLAN_WRITTEN` and 152 `LIVE_PLAN_WRITTEN`,
  live-odds-worker 0 and 0. live-odds-worker executes those plans (`read_placeable_plan_for_venue`) and never
  re-sizes.
- **Absent is stricter, not looser.** With the allowlist empty, `sizing_inputs_with_provenance` refuses EVERY row with
  no model edge as `no_model_edge_pct`, pregame or in play, before the in-play check would matter. So a commit on a
  keyless role would buy fewer market-fair rows, never more.
- **In-play live orders** (33 of 396 over 7 days) come from the in-play entry program, sized `inplay_order_dollars`.
  That program does not call this refusal.

**Verdict: no unguarded path.** If anyone edits the key, the place is `fleet_env/refresh-worker.json`, followed by a
drained full down/up (or a role-scoped `REFRESH_WORKER__` line in `local_production.env`, which wins over the
snapshot).
