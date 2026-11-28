# The 0% live EV floor, turned OFF in the 11-24 window -- findings 2026-11-23 (lane live-ev-floor-off)

Counts and percentages only (public repo).

## Decision

**The user, 2026-11-23 ~2:15 PM CST, typed in session 69d80317:** "Yes, add it tonight". That answered "Add the floor
shut-off to tonight's 2:15 AM batch?", which followed my recommendation to turn the floor off.

It loads as **CHANGE P** of the 11-24 window batch (scheduled task `nfl-level-refit-load-1120`).
- It is a BETTING CHANGE, inside the window, with no `--outside-window`.
- No code change. The fleet checkout already reads the key: absent means off
  (`pipeline/portfolio_commit.live_ev_floor_requested`).

## Evidence

`.syndicate/findings_2026-11-23_portfolio_monitor.md`, sections "Why none of the board's Suggested rows are bought" and
"The floor by venue EV at purchase".

**The floor's bets lose beyond noise.** Settled live bets since 2026-10-20 admitted by the floor: 1,249 bets in 663
games, ROI **-7.06%**, 95% range clustered by game **[-13.60, -0.46]**.

**A higher edge bar does not rescue it:**

| recorded EV at purchase | bets | ROI | 95% range |
|---|---|---|---|
| 4%+ | 845 | -6.10% | [-15.27, +3.06] |
| 2-4% | 386 | -9.16% | [-19.46, +1.58] |

**The floor's own stop rule is met.** The user set it 2026-10-20: "revert to Suggested-only if live 0-2% rows show ROI
below -5% after 100 settled bets". It was replaced 10-24 by the per-cell gate.

**What the floor admits.** Rows the board's Suggested flag refused for EV alone. The board's own Suggested rows almost
never clear at Kalshi or Polymarket prices: 0 of 34 at >= 2% net on 11-23.

## The change

ONE role-scoped line in `~/syndicate-prod/local_production.env`, at line 141 on 11-23:
`REFRESH_WORKER__SYNDICATE_LIVE_EV_FLOOR=0`.
- P REMOVES it. It is the only line naming the key; web and live-odds-worker read it as ABSENT.
- Env is built only at `up`, so P rides the batch's drained full down/up.

**Kit:** `C:\tmp\w1124_floor\` (WSL `/mnt/c/tmp/w1124_floor/`).
- `kit_env_floor.sh check | apply | restore <backup>`.
  - `apply` backs up the file with its mode kept, then removes the line ONLY if it is there exactly once in exactly
    that form.
  - Absent prints `already_absent`. Anything else prints `CONFLICT`, exits rc 5 and writes nothing.
  - No argument prints usage, rc 2.
  - Self-test `kit_selftest_floor.sh`, 2026-11-23 ~2:16 PM CST, 11 of 11 ok on dummy files: remove, mode 600 kept,
    other lines kept, idempotent, byte-identical restore, CONFLICT on `=1`, on a global line and on a doubled line;
    the real file untouched by `check`.
- `kit_after_up_floor.sh <from_utc> [to_utc]` is read-only. From the role logs, it reports `LIVE_EV_FLOOR date=` lines
  (one per plan commit while the floor is on), each venue's newest `LIVE_PLAN_WRITTEN` rows_in and positions, and
  live-odds-worker's `LIVE_ORDER` count.

**Baseline**, 3 h to 2:17 PM CST 11-23 (`baseline_preload_1123.txt`):

| reading | value |
|---|---|
| `live_ev_floor_on_lines` | 38 (every plan write) |
| Kalshi live plan | rows_in 514, positions 3 |
| Polymarket live plan | rows_in 463, positions 2 |
| live orders submitted | 5 |

## Predictions, pre-registered

- **P-F1, environ.** After the up, refresh-worker's environ has no `SYNDICATE_LIVE_EV_FLOOR` (`kit_role_env.py`),
  and `fleet_role_env_reading.py compare --expect-removed SYNDICATE_LIVE_EV_FLOOR` reads OK.
- **P-F2, plans.** From the first plan write after the up:
  - `live_ev_floor_on_lines=0`;
  - each venue's live plan `rows_in` falls to the Suggested rows that venue scopes: tens, against 514 and 463;
  - no live-plan position carries `live_ev_floor=0`.
- **P-F3, orders.** Floor-admitted pregame live orders stop. The next CST day's pregame live orders are only Suggested
  rows, expected 0-2 a day at current venue prices. In-play entries, a separate path sized `inplay_order_dollars`, and
  the maker pilot are unaffected.
- **Falsified if** a `LIVE_EV_FLOOR date=` line or a `live_ev_floor=0` position appears after the up while the role
  env reads ABSENT.

## Revert

Re-add the one line (`kit_env_floor.sh restore <P's backup>`, or append it by hand), then a drained full down/up.
Re-enabling is itself a BETTING CHANGE, so it goes in a later window on the user's yes.

## Log

- 2026-11-23 2:18 PM CST: kit built and self-tested; baseline taken; lane opened. CHANGE P added to the 11-24 batch
  prompt (below).
- 2026-11-23 2:22 PM CST: CHANGE P installed in `nfl-level-refit-load-1120` (sha 773c2fc22179384b -> 57a40bb886a54f1f). The first real run REFUSED on its hash guard: session 1f9c9a40 had added a STEP 4 line for `80dbb08f3` minutes earlier. Re-read, re-dry-run, then applied; the peer's line is intact, and N and O are intact. P reaches the description, the intro (sixteen / thirteen betting), the decision line, THE BATCH, RULES, THE KIT, STEP 0, 4, 4b, 6 (apply + baseline), 7 (refresh-worker expect), 8, a STEP 9 verify line, OWED, STEP 10 (heading, revert, BC register, lane line, todo) and THEN. The daily portfolio-learning-review gained the P-F2/P-F3 item.
- 2026-11-23 2:59 PM CST: user "show me the panel after tomorrow's batch loads". One-time READ-ONLY task `portfolio-panel-after-batch-1124` fires 2026-11-24 7:40 AM CST, after the 7:34 Portfolio Watch reading. It reads the batch outcome and the LOADED line, then runs `kit_after_up_floor.sh <LOADED UTC>` (P-F2), and sends the user a screenshot of the alignment panel (`scripts/portfolio_watch/panel_shot.py`; installed copy `C:\SyndicateProd\portfolio_watch	ools\`). The daily review item is the backstop if it misses.
- 2026-11-24 CST (from LOADED 08:30:37Z to 11-25 06:00Z; read 11-25 2:05 AM CST = 08:05Z by the daily learning
  review): live_ev_floor_on_lines 0 (28 in 06:00-08:30Z, before the load). Live orders after the load: pregame 8
  (Kalshi 6, Polymarket 2), in-play 3 (Kalshi 3, Polymarket 0). The 7-day pre-load means a day: pregame 29.3 / 19.3,
  in-play 8.3 / 2.1 (Kalshi / Polymarket). Newest live-plan rows_in: Kalshi 9, Polymarket 8 (05:57Z). Pregame 8 is
  above the expected 0-2 a day; there are no floor lines, so it is not a defect, but which rows those 8 were is worth a
  look.
- 2026-11-25 CST (06:00Z 11-25 to 06:00Z 11-26; read 11-27 2:00 AM CST = 08:00Z by the daily learning review):
  live_ev_floor_on_lines 0, but NOT COVERED: the refresh-worker log starts 15:44:48Z 11-25 and the kit saw 0 plan
  writes and 0 orders, so its 0 is not evidence. Ledger: pregame 19 (Kalshi 12, Polymarket 7), in-play 3 (Kalshi 3,
  Polymarket 0). Newest live-plan rows_in: none in the kit's window.
- 2026-11-26 CST (06:00Z 11-26 to 06:00Z 11-27; read 11-27 2:00 AM CST = 08:00Z): live_ev_floor_on_lines 0.
  Ledger: pregame 6 (Kalshi 6, Polymarket 0), in-play 2 (Kalshi 2, Polymarket 0); the kit counted
  live_orders_submitted 3. Newest live-plan rows_in: Kalshi 6, Polymarket 6 (05:58Z). Pregame has now been 8, 19, 6 a
  day against the registered 0-2: no floor lines, so not a defect, but the prediction is not holding.

## Why pregame live orders run 6-19 a day, not 0-2 -- HYPOTHESES (written 2026-11-27 10:21 AM CST, before the per-order test)

The user, 11-27, answering "Should I diagnose why pregame live orders run 6-19 a day instead of the predicted 0-2?": "Yes, diagnose it". Read-only.

**Already read before this was written** (so not a test): the ledger in the 10:04 AM CST watch reading (`live_all.json`, 2,708 orders) splits each CST day's pregame live orders by `sizing_basis` and `execution_style`. After the load, 2 a day are `execution_style=maker_pilot` (2 on each of 11-24, 11-25, 11-26), the same as before the load (1-3 a day). The rest are `sizing_basis=model_edge` with no execution style: 17 on 11-25, 4 on 11-26. Those come from the live plan.

- **H-A, the prediction used the wrong bar.** The 0-2 came from 11-23's "0 of 34 Suggested rows at >= 2% net at the venue". But the live plan buys a Suggested row at any EV net of the venue's fee above 0 (`min_ev_pct` 0.0; `below_min_ev_pct_net_of_fee`). On 11-23, 6 of the 34 (Kalshi 3, Polymarket 3) were above 0 in that one snapshot. Before the load, the non-floor paths were already about 19 orders a day (660 in about 34 days: Suggested, in-play and maker pilot). So the code is right and the prediction was not.
  - *Test:* match each post-load `model_edge` pregame order (11-24 08:30:37Z .. 11-27) to the live-plan position that bought it, in the Portfolio Watch readings' ALIGNMENT plans. Those carry each position's `suggested` flag and EV, for readings from 11-24 (with gaps at the alignment failures and the 11-26 outage).
  - *Survives if:* the matched orders are all `suggested=True` with no `live_ev_floor` tag, and most have a recorded EV at purchase between 0% and 2%.
- **H-B, another admission path.** Some of these orders come from rows that are not Suggested: a live-plan input other than `suggested_rows`. *Confirmed if* any matched position reads `suggested=False` or carries `live_ev_floor`.
- **H-C, repeat orders.** A few positions take several orders each (re-submits, increments), which inflates the count. *Test:* distinct `position_key` per day against orders per day.

### RESULT, 2026-11-27 10:25 AM CST: H-A SURVIVES; H-B and H-C REJECTED. The floor is off and the code does what it should; the 0-2 prediction was wrong

**Method, read-only.**
- The ledger in the 10:04 AM CST watch reading (`live_all.json`).
- The floor's own position log, `reports/intelligence/live_ev_floor_positions.json`, read from the fleet store under refresh-worker's environ at nice 19. It holds 3,998 entries, 10-20 4:29 PM CST .. **11-24 2:22:35 AM CST**, 8 minutes before the load.
- An order counts as floor-admitted when its venue and `position_key` are in that log.
- Definitions: "pregame" means submitted before commence. "Plan" means `sizing_basis=model_edge` with no execution style.

**Live orders a day, by path:**

| path | 30 d before the load | 7 d before | after the load (3.31 d, to 16:04Z 11-27) |
|---|---|---|---|
| pregame, plan, floor-admitted | 38.2 | 46.9 | **0** |
| pregame, plan, Suggested (not in the floor log) | 5.1 | 4.9 | **9.1** (30 orders) |
| pregame, maker pilot | 2.5 (2.3 of them floor) | 2.0 (1.9 floor) | 1.8 (0 floor) |
| in-play entries (`inplay_order_dollars`) | 9.8 | 5.3 | 2.4 |

**H-A survives.** The 0-2 came from one 11-23 snapshot, measured at the wrong bar (>= 2% at the venue). The plan buys at > 0 net of the venue's fee. The Suggested path was already placing 4.9-5.1 pregame orders a day before the load, and the 9.1 a day after it is that path alone. The review's daily counts match this split: 11-25 = 17 plan + 2 maker, 11-26 = 4 + 2.

**H-B is rejected, by the code and the log; per-order flags not read.**
- *Code:* with the key absent, `_live_ev_floor_population` returns None. Each venue's live plan then takes `scoped`, the venue-scoped `suggested_rows` set that paper2 uses too (`pipeline/portfolio_commit.py`, the `live_floor_rows` branch).
- *Log:* it took no entry after 08:22:35Z 11-24, and 0 of the 44 post-load live orders (30 plan, 6 maker pilot, 8 in-play) are in it.
- *Not read:* each order's `suggested` flag at purchase. The stored readings keep the board-match summary, not the plans.

**Not a valid test, for the record.** The day-end board match (`orders_today` in the readings) puts only 1-3 of each day's orders on a Suggested row, and 4-6 on a line the board no longer carries. The board at 5:34 PM CST is not the board at purchase: flags and lines move during the day.

**H-C is rejected.** 30 post-load plan orders, 30 distinct position keys, all filled.

**P-F3 verdict.**
- Half 1, floor-admitted pregame orders stop: **MET.**
- Half 2, 0-2 a day: **FALSIFIED as a prediction.** It is not a defect.
- The live-order count fell 82% for plan pregame orders (51.3 to 9.1 a day), not to near zero.

**Lead, not followed.** The Suggested path rose from about 5 to 9.1 a day after the load. There are two candidate causes, neither tested, on 3.3 days of data:
- the floor's rows had held the plans' `max_positions` slots and budget;
- Thanksgiving's football slate (post-load plan orders: NCAAF 14, NFL 8, NBA 8).

**For the daily review.** Its line still compares against 0-2 and will keep reading "not holding". The measured baseline is about 5 plan orders a day from Suggested rows plus about 2 maker-pilot orders.
- 2026-11-27 10:30 AM CST: **daily review's CHANGE P step updated** (user, 11-27, in session 69d80317: "Yes, update it", answering "Should I change the nightly review to expect about 5-9 pregame orders a day instead of 0-2?").
  - Task `portfolio-learning-review`, set through the scheduled-tasks tool. SKILL.md sha256 went from `bc093609704405b1` to `b7fa10b5857e3ecf`, and the pre-edit copy is in the session scratchpad (`pf3/SKILL.before_pf3.md`).
  - One line changed: the EV-floor step (b). Every other line and the frontmatter are identical by diff.
  - Step (b) now splits pregame orders into PLAN (`sizing_basis=model_edge`, no execution style) and MAKER-PILOT. It expects about 5-9 plan orders a day plus about 2 maker-pilot orders, says the registered 0-2 was a wrong prediction and not a defect, and mentions a day's count only above 20 plan orders.
  - Unchanged: the floor-on line check (non-zero = DEFECT), the daily Log line, and the 12-01 7-day summary.
- 2026-11-27 (CST) daily line (daily review, 2:10 AM CST 11-28; window 06:00Z 11-27..06:00Z 11-28): live_ev_floor_on_lines=0. Pregame plan 16 (Kalshi 10, Polymarket 6), maker-pilot 2 (Kalshi 0+2), in-play 8 (Kalshi 8, Polymarket 0). Newest live-plan rows_in: Kalshi 15, Polymarket 17 (05:49Z 11-28).
