# NBA Elo bug: what it did to live money (2026-11-18)

- **Asked by the user** in session 9383ef18: "size the money impact of the NBA Elo bug". Read-only, on the fleet, at nice 19. Finished 3:04 PM CST (21:04Z).
- **The bug:** the NBA games history is duplicated, with 1,563 rows for 196 games. That moves every team's Elo by a mean of 119 points, up to 293.
  - Source: `findings_2026-11-18_nba_midnight_bootstrap_hold.md` §3 and §8 (todo `#843`).
  - The fix (`4178ba866`, made default ON in `a3104a5b6`) **LOADED by fleet ff at 3:02 PM CST (21:02:51Z)**: deploys.md, BC-052, a betting change loaded outside a window on the user's override.
  - The history is de-duplicated only at the first NBA props bootstrap fetch after that. That reading is owed.
  - So every fill below was placed on the duplicated history.

## Answer

**No live NBA bet's admission, stake or exit depended on the Elo.** The bug can only have reordered near-equal rows on the board, and that is unpriced.

| live NBA fills, 10-20..11-18 | fills | staked | graded | P&L |
|---|---|---|---|---|
| all | 743 | $1,374.39 | 719 | -$101.12 (-7.5%) |
| in-play (`ingame:` positions) | 234 | $448.09 | 234 | -$18.60 |
| pregame, model edge 0 and sim stake share 0 | 321 | $612.94 | 306 | -$48.00 |
| pregame, nonzero sim term (the Elo can reach these) | 188 | $313.36 | 179 | -$34.52 |

### The 555 fills the Elo cannot reach ($1,061.03)

- **In-play, 234 fills.** The fair is the median multiplicative no-vig price across at least 3 books, read through OddsAPI (`inplay_entries_paper.py`, `FAIR_VERSION = "inplay_book_median_novig/1"`). The sim is never read.
- **Pregame, 321 fills, every one with `model_edge_pct` = 0.** That covers h2h, spreads, spreads_alt, and player points, assists, threes and blocks.
  - `nba_game_book_blend.json` on the fleet gives the sim weight 0 on h2h, spreads and the default (alt lines), and 0.05 on `totals:full`.
  - Both ranking and sizing read that blended edge, so with weight 0 the sim term is exactly 0.

### The 188 reachable fills ($313.36)

By market: totals_alt 166, totals 8, player_rebounds 8, spreads_alt 3, player_steals 2, player_threes 1.

- **Admission: the sim did not decide it.**
  - The commit refuses a row whose raw price `ev_pct` is below the cut (`portfolio_commit.py:1207-1211`; `DEFAULT_MIN_EV_PCT` = 2.0). That test has no sim term. The lowest `ev_pct` on these fills is 2.35, and the mean is 4.21.
  - NBA's board value floors are all negative. Read from the served `layer2_shortlist_2026_11_18`: total -5.36, spread -2.0, moneyline -5.60, player_prop -7.56.
- **Stake: the sim did not set it.** `sim_share_of_stake` is nonzero on 4 of the 509 pregame fills:

  | fill | sim share | staked | P&L |
  |---|---|---|---|
  | player_threes, 10-23 | -3.96 | $5.04 | -$5.17 |
  | spreads_alt, 11-06 | -0.0009 | $0.76 | |
  | spreads_alt, 11-06 | +0.0008 | $0.73 | |
  | spreads_alt, 11-17 | -4.34 | $0.01 | |

- **Ranking is the only open channel.** The term is `0.125 x model_edge_pct`, capped at 1.5 (`opportunity_signals.py:940`).
  - Its size: mean |term| 0.061 EV points, max 0.474.
  - It was positive on 90 fills (staked $145.87, P&L -$20.14).
  - It can swap rows of near-equal price EV when NBA's shortlist row budget binds. Pricing that needs a shortlist replay, which was not done.
- **Exits: the sim did not trigger them.** The fleet runs `SYNDICATE_EXIT_MODE=live` with `SYNDICATE_EXIT_LIVE_RULES=take_profit`.
  - All 46 filled live NBA exits are `take_profit+model_fair`. The model-fair half only co-signed, because take_profit is the live rule.
  - 13 of the 46 were totals_alt entries with a nonzero edge; the other 33 had edge 0.
- **Ceiling:** the most the bug could have touched is these 188 fills, $313.36 staked, P&L -$34.52. The real effect is a ranking swap between near-equal rows, far smaller than that and not measured.

## Where the bad Elo does land (no live money)

- `nba_sim_total_inputs.json` on the fleet has `"feed_game_model": true`. So the NBA smart sim's team means come from `pred_total` / `pred_margin`, the Elo-fed game model. That reaches:
  - player-prop sim distributions;
  - game-line sim distributions;
  - the live re-sim's starting state.
- Board display: `home_win_prob`, `pred_margin`, and the `sim_view` labels (SYNDICATE PICK vs PRICE PLAY) on NBA cards.
- 22,320 NBA paper fills.
- **Model grading.** The optimizer grades the NBA sim on these inputs and gives it weight 0 where its interval spans 0.
  - Example record, 11-17: `nba|totals_alt|full|live` w* 0.108 [-0.250, +0.499], "overconfident", 174 games, `w_model` 0.
  - A corrupted input makes the sim grade worse and keeps it at weight 0. That is an opportunity cost, not measured.
- Any bet placed by hand off the NBA cards is outside this sizing.

## When this answer stops being true

The Elo would start reaching money if any of these changes:
- NBA's book-blend weights rise above 0;
- the optimizer starts giving the NBA sim weight;
- `model_fair` joins `SYNDICATE_EXIT_LIVE_RULES`.

The history fix is loaded (`a3104a5b6`, 3:02 PM CST). Before any of these changes, confirm its first fetch wrote one row per game.

## Method and what was read

- **Execution ledger:** read on the fleet through the repo's own reader (`refresh_state_store.read_json_file`, keyvalue backend; env from the live-odds-worker process, with no value printed).
  - `execution_ledger.json`: 3,000 rows.
  - The archive `reports/intelligence/execution_ledger_archive/orders_2026-10.jsonl` + `orders_2026-11.jsonl`: 72,998 rows.
  - Filter: sport nba, mode live, status filled.
- **Exits:** `execution_exits.json` (2,886 exits, 1,096 NBA).
- **Floors:** shortlist documents `layer2_shortlist_2026_11_08..19` (keyvalue).
- **Decision records:** `decision_records/2026-11-17.json.gz`.
- **Switch files:** `nba_game_book_blend.json` and `nba_sim_total_inputs.json` (NBA processed root).
- **Scripts:** `C:\tmp\nbaelo\c.py` (ledger dump), `e.py` / `f.py` / `g.py` (splits), `j.py` (floors), `k.py` (exits), `l.py` (in-play check).
- **Fill classes:** in-play means a `position_key` prefix of `ingame:` (234 of 234 unlabelled rows; 205 submitted after tip, 29 with no tip time). Pregame means `side_picked_by = price_shopping` (509).
