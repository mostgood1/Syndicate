# Why live execution finds almost nothing to trade: the funnel, 2026-10-19 and 10-20

Session 6200a74b (side session of b87af0fc). READ-ONLY on the fleet: no env, cap, restart or deploy change.
Fleet HEAD `854b59ed`. Times are Central (CDT = UTC-5); UTC in brackets where a log line is quoted.

## Answer

**The first stage that goes to zero is the EV gate at the venue's OWN price, net of the venue's taker fee.**
The stages before it are thin but never zero. After it, Polymarket has had 0 positions in every build since live
began, and Kalshi has had 0 in 24 of 30 builds. In the other 6, the single position is refused by the executor on
`over_max_order_dollars`.

An independent check over the whole board, not just the Suggested rows, agrees. The 10-19 shortlist (4,172 rows)
has **556 Kalshi-quoted sides, 0 of them at >= +2% net of fee, and 23 at 0 to +2%**. Polymarket has 324 quoted,
**0 at >= +2%, and 5 at 0 to +2%**. Before the fee, Kalshi has 41 at >= +2% and Polymarket 24. **The taker fee is
what empties the plan.** It is not a gate we chose. On the consensus-fair basis, the exchanges' ask prices are
almost never better than the sportsbook consensus once the fee is paid.

## Sources (all fleet, read-only)

- `~/syndicate-prod/logs/refresh-worker.log{,.1}`: `SUGGESTED_GATE`, `PLAN_WRITTEN`, `VENUE_SCOPE`,
  `PAPER2_PLAN_WRITTEN` and `LIVE_PLAN_WRITTEN`. 253 builds dated 10-19 (00:03Z..21:13Z), 31 of them in the live
  window, and 8 builds dated 10-20.
- `~/syndicate-prod/logs/live-odds-worker.log{,.1}`: `EXECUTED`. 55 live passes per venue on 10-19, and none yet
  for 10-20, because the executor runs today's date only.
- Shortlist and plans read under refresh-worker's /proc environ (`read_layer2_shortlist`,
  `read_live_portfolio_plan_for_venue`). The 10-19 build is from 5:11 PM CT [22:11Z]; the 10-20 build is from
  3:40 PM CT [20:40Z].
- Caps, stored limits and the balance stamp read under live-odds-worker's environ at about 5:15 PM CT [22:15Z]
  (`limits()`, `stored_limits()`, `_venue_available_dollars`, `venue_capital`).
- The venue-pool count re-prices every shortlist row at `quote.book_prices[kalshi|polymarket]` against
  `quote.fair_probability`, with `cheat_sheets.ev_pct` and `taker_fee` (`venue_fees`). This is the board's captured
  venue quote, not the executor's live re-read, so it is an estimate. The plan's own refusals agree with it.
- Scripts are in this session's scratchpad: `parse_pc.py`, `window.py`, `read_plans.py`, `venue_pool.py`,
  `read_caps.py`, `read_stamp.py`.

## Live settings as resolved (not as believed)

| setting | believed | **live** | source |
|---|---|---|---|
| commit `min_ev_pct` | 2.0 | **0.0** | env `SYNDICATE_PORTFOLIO_MIN_EV_PCT=0` |
| `max_positions` | 12 | **25** | env |
| bankroll / slate ceiling | | $1,000 / 0.2 ($200) | env / default |
| min EV net of fee (commit) | | 0.0 ("positive after fees") | code |
| **Suggested flag min EV (board)** | | **2.0, net of fee** | code `SUGGESTED_MIN_EV_PCT` |
| market-fair sports | | all 8 | env |
| in-play market-fair cells | | nfl:prop, ncaaf:totals | default |
| order cap | $25 | **$25** | stored |
| Kalshi / Polymarket day cap | $200 / $100 | **$200 / $100** | stored |
| all-venues day cap | $150 | **$150** | stored (orders 15/15/25) |

The live plan's real EV floor is therefore the Suggested flag's **+2% net of fee at the BEST book**, not the commit
floor of 0. The commit floor is applied afterwards, to the venue's own price.

## Funnel: 10-19 live window, 11:14 AM to 4:13 PM CT (31 builds; min / median / max per build)

| stage | Kalshi | Polymarket |
|---|---|---|
| board shortlist rows | 3,889 / **4,096** / 4,471 | same |
| `SUGGESTED_GATE` suggested (+2% net at the best book, two-sided fair, fresh) | 14 / **21** / 32 | same |
| `VENUE_SCOPE` scoped (the venue quotes the line at all) | 7 / **9** / 11 (11.4 `venue_not_quoting`) | 3 / **5** / 9 (15.4 `venue_not_quoting`) |
| priced from the venue's own feed (`venue_priced`) | 7 / **9** / 11 | 0 / **1.5** / 7 (3.0 `aggregator_priced`) |
| EV gates at the venue price | below_min_ev 2.6, net_of_fee 3.3, zero_kelly 2.0 per build | below_min_ev 0.65, net_of_fee 0.52, in_play_market_fair 0.52 |
| **live plan positions** | 0 / **0** / 1, >0 in 6 of 30 builds | **0 in 30 of 30** |
| executor (`EXECUTED mode=live`, 55 passes) | positions>0 in 16 passes: 1 `insufficient_shard_balance` (11:05 AM), **1 filled** (Thornton, 11:59 AM), **14 `over_max_order_dollars`** (3:02 PM to 5:08 PM) | positions>0 in **0** passes |

The 14 refusals are one row. NCAAF, Missouri St at Delaware, DEL -3.5 (`KXNCAAFSPREAD-26OCT20MOSUDEL-DEL4`, kickoff
10-20 6:00 PM CT). Venue EV +3.99%, model edge 13.57, **stake $26.52 against the $25 order cap**. 98.9% of that stake
is sim-attributed ($26.22).

**10-20 (8 builds so far, through 3:40 PM CT):** board 3,047..4,940 → suggested **7.5** median (3..10) → Kalshi
scoped 4.5 / Polymarket 3 → venue-priced 4.5 / **0** → positions 0, with Kalshi >0 in 3 of 8 builds and Polymarket
0 of 8. Nothing has executed for 10-20 yet.

## Per sport (snapshot builds: 10-19 at 5:11 PM CT, 10-20 at 3:40 PM CT)

"K net>0" is the count of Kalshi-quoted sides that are positive after the fee, across the WHOLE board.

**10-19**

| sport | board | suggested | K quoted | K net>0 | P quoted | P net>0 | live plan outcome |
|---|---|---|---|---|---|---|---|
| soccer | 1,905 | 2 | 91 | 0 | 58 | 0 | K: 1 net_of_fee |
| nhl | 611 | 4 | **0** | 0 | **0** | 0 | not scoped on either venue |
| nfl | 584 | 2 | **22** | 1 | **0** | 0 | K: 1 below_min_ev |
| wnba | 469 | 2 | 118 | 7 | 51 | 0 | none scoped at the last build |
| ncaaf | 448 | 6 | 214 | 7 | 153 | 1 | K: **1 position (DEL -3.5, refused at $25)**, 1 below_min_ev, 1 net_of_fee, 1 zero_kelly; P: 2 aggregator_priced |
| mlb | 155 | 3 | 111 | 8 | 62 | 4 | K: 2 below_min_ev, 1 net_of_fee; P: 1 below_min_ev, 2 net_of_fee |
| **total** | **4,172** | **19** | **556** | **23** (0 at >=2%) | **324** | **5** (0 at >=2%) | K 1 / P 0 |

**10-20**

| sport | board | suggested | K quoted | K net>0 | P quoted | P net>0 |
|---|---|---|---|---|---|---|
| soccer | 1,920 | 3 | 100 | 1 | 8 | 0 |
| ncaaf | 777 | 5 | 335 | 8 | 222 | 2 |
| nfl | 288 | 0 | 4 | 0 | 0 | 0 |
| nba | 50 | 0 | 49 | 1 (>=2%) | 0 | 0 |
| nhl | 12 | 1 | 0 | 0 | 0 | 0 |
| **total** | **3,047** | **9** | **488** | **10** (1 at >=2%) | **230** | **2** (0) |

The one 10-20 Kalshi side at >=2% is LeBron James UNDER 19.5 points at -203 (Kalshi is the best book). Its fair is
0.7045 (consensus, 2 books), +2.78% net and +5.15% gross. It is **not Suggested because `suspect_stale_quote`**: a
per-line refusal working as designed.

Fee band, all pregame, both snapshots:

| | quoted | gross>0 | gross>=2 | net <-5 | -5..-2 | -2..0 | 0..2 | >=2 |
|---|---|---|---|---|---|---|---|---|
| Kalshi 10-19 | 556 | 136 | 41 | 180 | 252 | 101 | 23 | **0** |
| Polymarket 10-19 | 324 | 75 | 24 | 130 | 141 | 48 | 5 | **0** |
| Kalshi 10-20 | 488 | 109 | 37 | 226 | 193 | 59 | 9 | 1 |
| Polymarket 10-20 | 230 | 37 | 13 | 114 | 89 | 25 | 2 | 0 |

The Suggested flag is computed at the best book, but it is **not** what loses the venue's +EV lines. A side that is
>= +2% net at the venue would also be >= +2% at the best book. On 10-19, 21 of the 23 Kalshi sides that are positive
after the fee are not Suggested: 20 are `ev_net_of_fee_below_min` (they sit between 0 and 2%), 9 are `ev_below_min`
and 2 are `single_book_fair`. A side can carry more than one reason. The venue's positive population lives entirely
in the 0 to +2% band. The board flag excludes that band, while the commit gate (floor 0) would admit it.

## Caps and balances (read at about 5:15 PM CT)

- **Does the combined cap bind? No, not today.** Spent live today: $4.53 in 1 order, all venues, against a $150
  ceiling (3%). It is checked after the per-venue cap. It would bind only on a day when the two venues together
  pass $150, below Kalshi's $200 plus Polymarket's $100 = $300. **The binding cap today is the $25 per-order cap**,
  14 times, on the one row the plan had. Lane `caps-revamp` (session 332cb014) is already building trim-to-cap on
  the user's decision 10-19 ("Trim to the cap").
- **Polymarket buyingPower counts the pending deposit. Yes.** The stamp's `dollars` is $586.05. `venue_capital`
  reads that as buying power $586.05 minus a $500.00 pending deposit, for capital of **$86.05**. The order guard
  (`_venue_available_dollars`) uses the $586.05. The user decided 10-19 that "the $500 pending on polymarket CAN be
  used", and `caps-revamp` is aligning `venue_capital` with that. The two readers disagree until that lands. It does
  not matter today: no Polymarket position reached the guard.
- Kalshi capital: $485.48 cash plus $4.50 in positions. Shards: 0 = $170.00, 1 = $75.01, 2 = $0.00, 3 = $240.47.
  Shard 3 carries MLB, WNBA and NBA. The 11:05 AM `insufficient_shard_balance` refusal came before the funding move.

## Ranked fix proposals (per line and EV-gated; no market-wide exclusion, per learnings 2026-09-16)

1. **Trim the over-cap order to the cap instead of refusing it.** This is ALREADY in progress in lane `caps-revamp`,
   on a user decision. It unblocks the only current live position (DEL -3.5, $26.52 → $25). It is the one change
   that turns today's zero into a fill. Caveat, measured here: 98.9% of that stake is sim-attributed.
   `findings_2026-10-19_ev_overstatement_decomp` puts sim-added dollars at w = -0.27. Once
   `SYNDICATE_STAKED_PROBABILITY_UNFITTED=market` loads (bd9b0571, written 4:01 PM CT and not yet running), this
   row's stake likely shrinks to near the $1 minimum. Trim-to-cap is correct, but it adds little volume.
2. **Enter Kalshi as a MAKER, not a taker, on `quadratic` series.** This is the biggest lever, because the fee is
   the measured zero. The ask after fee is at or below consensus on 533 of 556 sides. Before the fee, 41 are at
   >= +2%. `venue_fees` records maker fills on `quadratic` series as free (the evidence is 2 fills). Rest a bid at a
   price where `fair - bid >= min edge`, gated per line on EV at the maker price. This is literal buy-low. It needs
   a pre-registered paper study first: fill rate, plus adverse selection. `findings_2026-10-02_layer2_market_moves_away`
   says the market moves away from us, so fills will be adversely selected. On `quadratic_with_maker_fees` series
   the maker fee is still unverified (third parties put it at 0.0175). Build, then paper.
3. **Widen the venue join.** On 10-19, NHL had **0 of 611** sides joined on Kalshi or Polymarket. NFL had 22 of 584
   on Kalshi and 0 on Polymarket. Polymarket's own feed priced only 1.5 of 5 scoped Suggested rows per build; the
   other 3.0 were `aggregator_priced`, all NCAAF on the last build. Lane `kalshi-join-all-game-lines` already built
   `SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES` (off by default; replay +428 to +518 Kalshi matches a day). It needs the
   user's yes. **Expected yield is small at today's rate:** 4.1% of Kalshi-quoted sides are positive after the fee
   (23 of 556), and about 0% are at >= 2%. So this widens the pool but does not by itself fill the plan. Polymarket
   is 1.5% (5 of 324).
4. **The 0 to +2% venue band: settle it per cell.** The live plan stakes only the Suggested set (user decision
   10-13, "one definition"), which needs +2% net. The commit gate's own evidence (09-08..09-20 paper venue orders)
   was: "positive after fees" kept 415 orders at +4.2% net, while a 2% bar kept 85 at 0.0%. That argues the band is
   worth staking. It is the user's decision, because it reopens 10-13, and it is not a market-wide loosening. The
   route is per cell, through the min_ev tuner (`min-ev-tuner-shadow`, shadow, 0 moves; its marginal band holds 17
   events at most, so expect weeks). Size of the prize: 23 Kalshi and 5 Polymarket sides on 10-19, and 9 and 2 on
   10-20, per snapshot.
5. **No action on the $150 all-venues cap.** It does not bind (3% used). Revisit only after items 1 to 3 raise
   volume. The Polymarket deposit disagreement between the two readers is `caps-revamp`'s.

Not proposed: lowering the in-play market-fair refusal. It refused 0.1 of a row per build on Kalshi and 0.5 on
Polymarket. The pregame sides are all at or below zero after the fee anyway.

## Believed, not verified

- The venue-pool counts use the board's captured `book_prices`, not the executor's live ask re-read.
- The executor re-reads its prices live, so it may disagree with the captured quotes; a live read would settle it.
- Both snapshots are single builds with no in-play rows. A live slate may differ.
- All the per-sport counts come from those two builds.
- The day-level funnel (per build, from the log lines) is not split by sport: the log lines carry no sport field.
