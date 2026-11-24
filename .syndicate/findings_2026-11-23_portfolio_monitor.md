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

## The 6:04 PM reading's token failure -- HYPOTHESIS (written 2026-11-23 6:29 PM CST, before testing)

Flag from the fleet-watcher (session local_379fd729): in the 6:04 PM reading (`20261124T000432Z`) all 8 endpoint reads
failed with `ValueError: Invalid header value b'A\x00 \x00c\x00o\x00n...'`, the reading counted 8 anomalies, and
`run.log` still logged `probe: rc 0`.

- **H-T1.** `scripts/_base_url._read_fleet_token` returns `wsl.exe`'s own error text as the token. It keeps `stdout`
  whatever the return code, and validates nothing. When WSL fails to connect, `wsl.exe` writes its error message to
  stdout in UTF-16, and `text=True` decodes that as cp1252: every other character is a NUL. The probe then sends that as
  the `X-Admin-Token` header, and urllib refuses it. The failure was transient: the same run's log and alignment reads
  through WSL succeeded.
- **H-T2.** The probe never checks the token, and `main()` returns 0 unconditionally, so `run.log`'s `rc` cannot show a
  failed reading.
- **Falsified if** `wsl.exe` with an unreachable target exits 0, or does not write a NUL-laden message to stdout. Then
  the garbage came from somewhere else, for example the env file itself.

### RESULT (2026-11-23 6:34 PM CST): H-T1 and H-T2 hold; fixed (lane `fleet-token-read-guard`)

**Reproduced the failure class without the real token.** The token reader's exact argv was run against a distro that
does not exist: `wsl.exe` returned rc 4294967295 and a 482-character stdout full of NULs, with stderr empty. The old
reader returned that text. The same run's log and alignment reads through WSL succeeded, so the failure was transient
and hit only the first WSL call.

**The fix:**
- `scripts/_base_url._read_fleet_token`:
  - A non-zero `wsl.exe` rc, or output that is not printable ASCII without whitespace (`_plausible_token`), reads as
    `""`.
  - It retries once after 3 s.
  - A failure is no longer cached, so a long-running caller recovers. A success is still read once per process.
  - The real token passes the shape check (checked with booleans only).
- `scripts/portfolio_monitor_probe.py`: with no token, it reads nothing. It writes ONE `TOKEN` anomaly and a
  `probe_failed: token` reading, and exits 3, so `run.log` shows `probe: rc 3`.
- `scripts/portfolio_watch/build_page_data.py`: a `probe_failed` reading stays out of the charts and the performance
  table; its anomaly shows only while it is the newest reading. Installed in `C:\SyndicateProd\portfolio_watch`.
- The 6:04 PM reading is tagged `probe_failed: token` in `readings.jsonl`, with a backup
  `readings.jsonl.before_tag_0604`. The day's anomaly count no longer carries its 8 ENDPOINT lines.

**Measured:**
- Tests: `tests/test_base_url.py` 32 passed; `tests/test_portfolio_monitor_probe.py` + `tests/test_portfolio_watch.py`
  32 passed.
- Forced failure (`SYNDICATE_FLEET_WSL_DISTRO=NoSuchDistro-xyz`) through the real probe: rc 3 in 3.5 s, one anomaly,
  one reading.
- Real token: rc 0, 8 of 8 endpoints 200, and the one standing GATE anomaly.
- The scheduled 6:34 PM reading (still the old code) was clean: rc 0, 8 of 8, the GATE anomaly only.
- The fix reaches the scheduled task at the primary tree's next fast-forward.

### Lead found while verifying (2026-11-23 7:06 PM CST): the :04 runs' token read is slow

**The 7:04 PM reading, the first on the new code:** probe rc 0, 8 of 8 endpoints 200, only the GATE anomaly, and
`page data` printed the new suffix (`probe-failed readings left out 1`). The lane's verification reading holds.

**But that probe took 31.7 s.** Its reading is stamped `01:04:28Z`, and the stamp is taken after the token read, so
the token read took about 25 s. The failed 6:04 PM run had the same shape: 32.6 s, stamped `00:04:32Z`.

Probe durations on 11-23 from 1 PM:

| runs | probe duration |
|---|---|
| :34 runs | 3.5-13.6 s, most 4-6 s |
| :04 runs | 6.6-14.8 s |
| 6:04 PM run | 32.6 s |
| 7:04 PM run | 31.7 s |

**H-T3 (written before instrumenting).** At :04 the first `wsl.exe` call contends with other work that starts at the
top of the hour, so it is slow. At 6:04 it slowed into a failed connection. Nothing yet says whether the 7:04 read
needed the new retry. The instrument: each reading records `token_read` (seconds, attempts, and each attempt's result:
`ok` / `rc=N` / `error` / `not_a_token` / `no_line`). It is a diagnostic only, and not an anomaly.
- **H-T3, first readings with the instrument:**

  | reading | token read | attempts | probe | endpoints |
  |---|---|---|---|---|
  | 7:34 PM | 0.25 s | 1, `ok` | 7.3 s | 8 of 8 |
  | 8:04 PM | 0.36 s | 1, `ok` | 10.2 s | 8 of 8 |

  So a :04 run is not slow by itself, and the 6:04/7:04 slowness was a passing spell (2 of the 8 :04 runs from 1 PM to 8 PM
  ran ~30 s). Unanswered: whether 7:04's ~25 s included a retry, since it ran before the instrument. Left open with the
  instrument running. A `token_read` over 10 s, or more than one attempt, in a later reading answers it.

## DAILY SUMMARY — Mon 11-23 (Central), written Tue 11-24 1:58 AM CST by the daily learning review

Sources: `daily_rollup.json` and `performance.json` built from the 1:34 AM CST 11-24 watch reading (ledger saved
07:34:02Z), and the 49 watch readings dated 11-23 CST. Every 11-23 game is graded: 0 started and unsettled, 0 late.

**Performance.**
- **11-23: 33 graded bets / 13 games, ROI +5.84% [-28.7, +40.4].** Won 54.5% against a 62.5% breakeven (excess
  -2.6 wins, z -0.96); before fees +9.23%. A small day; noise.
- **7 d: 364 bets / 194 games, -0.94% [-10.5, +8.6]** (11-22: -1.90%); before fees +2.43%.
- **30 d: 1,703 bets / 759 games, -5.09% [-10.5, +0.34]** (11-22: -4.75%). The range has included 0 for three days.
  All-time: 2,360 bets / 1,273 games, -10.41% [-17.3, -3.5].
- **Fee-net CLV:** 30 d -0.49 pp (646 bets / 440 games with a priced close; gross +1.24, beat close 61.8%, se 0.21);
  7 d -1.18 pp (178 / 130; gross +0.66, beat close 56.7%, se 0.37); 11-23 alone -3.37 pp on 9.
- **Fees: 3.38% of stake on 11-23 and over 7 d, 3.99% over 30 d.** 30 d before fees -1.10%, so fees are ~78% of the
  30 d loss.
- **Gate: 121 of 800 events**, clock BC-053 since 11-19 17:00Z (11:00 AM CST): 198 bets, ROI -1.52% (lower -14.2),
  excess wins -15.6. 2 deploys.md loads still unclassified (the GATE anomaly on 48 of 49 readings).

**30-day slices beyond noise (95% range excludes 0):**
- price 0.30-0.45 -12.24% [-24.1, -0.39] (260 bets / 176 games), beyond noise every day since 11-17.
- Passing TDs -66.3% [-112, -20.6] on 10 bets / 10 games: too few to read.
- At the edge: EV band 2-5 -7.55% [-15.2, +0.04] against a predicted +4.13% (1,074 / 585); totals -11.04%
  [-22.5, +0.43] (395 / 313). Noise: Kalshi -3.44%, Polymarket -10.66% [-23.1, +1.8], h2h +5.97%, spreads +0.87%.
- Stake quartiles as on 11-22: Q1 (5.9% of $) -8.48%, Q2 (8.8%) -8.70%, Q3 (21.9%) -6.11%, Q4 (63.4%) -3.92%; all
  ranges include 0.

**Operations (49 readings).** Anomaly kinds, by readings flagged:
- GATE 48.
- LEDGER grade_conflicts 17 (12:04-8:04 AM). Gone after NOP@OKC was acknowledged at 8:26 AM; lane
  `kalshi-no-grade-check` MET.
- CAP: Polymarket dollars at 90-105% of the day cap, 15 readings (8:04 AM-11:34 PM).
- ENDPOINT: 9 lines in 2 readings. One is the 6:04 PM token failure (8 of 8 endpoints, fixed under lane
  `fleet-token-read-guard`); the other is 1 slow read.

Endpoint reads over 2 s: 4, of which 1 over 3 s (9:04 AM live_today 3.5 s). Plan age: median 2.8 min, max 43 min
(12:04 AM, the overnight tail; 1 reading > 15 min). Orders 11-23: 50, of which 48 filled, 2 were maker posts that
expired unfilled, and 0 failed or were rejected by error.

**Studies.**
- **S8 LOOK 1 READ: PASS.** Net $176.0/day, 95% [$81.8, $288.2], over 3.72 days: 169 markets / 71 events, 484 M1
  fills (196 settled, 22 unpriced). The scorer first crashed on a sort tie; I fixed the tie-break only (see the S8
  file). Recorded in `findings_2026-11-20_s8_lip_shadow.md`. Nothing goes live: the next step is the user's decision.
  Heartbeat 07:52:57Z (cycle 5,273, 0 errors), fresh.
- S5 forward: 234 bets / 133 events with selected_date >= 11-19 (need 150), counted from the 1:34 AM `live_all.json`
  with the tool's own loader; not run.
- S6: read 11-23 (NO-GO); nothing owed.
- Not yet due at 1:58 AM: the 11-24 window ledger-field check (after 7:00 AM), and the 12:00 PM CHANGE N / CHANGE P
  checks. F27: lane `kalshi-join-sport-scope` has no `LOADED` line yet, so nothing is written.

### What the data teaches (11-23)
- The 30 d book has held at about -5% for three days (-4.92, -4.75, -5.09; 759-782 games), up from -7 to -9% through
  11-20. The 7 d has included 0 every day since 11-09. Fees (3.99% of stake) are ~78% of the 30 d loss: before fees
  the 30 d book is -1.10%.
- **The close-beat is shrinking.** 7 d gross CLV is +0.66 pp against +1.24 over 30 d, and beat-close 56.7% against
  61.8%. Fee-net 7 d CLV went -0.99 pp (11-22) → -1.18 pp (11-23, se 0.37). The 7 d ROI is better than the 30 d while
  its CLV is worse, so the recent ROI gain is probably variance, not skill.
- **The 0.30-0.45 band's loss is in stake weighting, not in hits.** It wins 44.2% against a 44.9% breakeven, -1.8
  excess wins on 176 games, yet loses -12.2% of stake. So within the band the bigger stakes lose. Totals are the
  opposite: 44.1% against 49.0%, -19.7 excess wins on 313 games, a real hit-rate deficit.
- **Market type splits about 17 pp:** h2h +5.97% (64.9% vs 62.6% breakeven, +5.5 excess wins, 207 games) against
  totals -11.04%. Both ranges include 0; the gap between them is the clearest contrast in the slices.
- Stake quartiles held their 11-22 order (Q4 best -3.9%, Q1/Q2 -8.5/-8.7%) for a second day. The 11-22 min-stake
  lead stands as written; it is not repeated here.

**One optimization lead (pre-registrable, offline, changes nothing live).**
- *Hypothesis:* our fair probability is over-confident on totals (game and alternate totals) and calibrated on h2h.
  If so, the totals hit-rate deficit (-19.7 excess wins on 313 games) is a fair-price error, not bad luck at the venue.
- *Data:* 30 d graded totals and totals_alt bets in `live_all.json`, against h2h as the control. Per game, compare
  the stake-weighted fair probability at submit (fill price + model edge) with the realised win rate,
  event-clustered. Then a forward copy on bets with selected_date >= 11-24 once totals reach 150 games, scored the
  same way.
- *Decision rule:* GO (name a totals fair-shrink toward the market as a calibration challenger for a later window)
  iff realised − fair on totals has a 95% upper bound < 0 on BOTH the 30 d and forward sets, AND the same statistic on
  h2h has a range that includes 0. Otherwise KILL. Report the shrink weight that the 30 d set fits, frozen before the
  forward read.
