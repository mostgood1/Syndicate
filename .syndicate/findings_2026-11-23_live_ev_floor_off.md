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
