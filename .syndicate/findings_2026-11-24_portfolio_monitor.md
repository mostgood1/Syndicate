# Portfolio monitor -- 2026-11-24 (lane portfolio-monitor, session 69d80317)

Counts and percentages only (public repo).

## Kalshi's live positions read "0 Suggested" after CHANGE P -- HYPOTHESIS (10:33 AM CST)

User 11-24, asked whether to trace it: "Yes, trace it".

**The reading.** 10:04 AM CST reading, alignment section:
- Kalshi live plan (9:58 AM): 2 positions, `live_positions_suggested` 0.
- The board's `suggested_in_live_plan`: 2, counted over both venues. Polymarket's live plan has 0 positions, so both are Kalshi's.
- Kalshi paper2 `suggested_positions`: 2.

**Hypothesis H-S1.** The 2 positions ARE Suggested board rows. The 0 is my probe's own instrument fault:
- `live_positions_suggested` reads a `suggested` flag on each live-plan POSITION (`portfolio_alignment_reader.compact`).
- A position is built from `_POSITION_IDENTITY_FIELDS` plus a carried block (`syndicate/features/shared/portfolio_commit.py:1375`). Neither copies `suggested`.
- The only writer of `suggested` on a position is the floor tag, `pipeline/portfolio_commit.py:453`, and it writes `False`.
- So the field reads 0 for every position, floor or not. It has read 0 on every reading since it was added on 11-23.
- The live plan's rows are paper2's scoped rows, the Suggested rows the venue quotes. With the floor off since 2:30 AM, every live position is a Suggested row by construction.

**Falsification test.** Read the live Kalshi plan on the fleet, read-only. For each position, record whether a `suggested` key is present and whether its key (event, market, line, player, segment, side) matches a board row with `suggested: true`. Either result below proves H-S1 wrong:
- a position that carries `suggested`;
- a position that matches no Suggested board row.

### RESULT (10:36 AM CST): H-S1 CONFIRMED. The positions are Suggested rows; the count was broken

**Fleet read.** A read-only script under refresh-worker's environ, at nice 19, took 7.1 s. It read the board as of 10:29 AM (4,477 rows, 45 Suggested) and the live plans as of 10:31 AM.

| | Kalshi | Polymarket |
|---|---|---|
| live positions | 2 | 0 |
| ...carrying a `suggested` key | 0 | - |
| ...carrying a `live_ev_floor` key | 0 | - |
| ...matching a Suggested board row | **2 of 2** | - |
| ...in paper2 by `position_key` | 2 of 2 | - |
| paper2 positions (Suggested rows at the venue's price) | 2, both matching Suggested rows | 2, both matching Suggested rows |
| floor block on the live plan | none | none |

So after CHANGE P every Kalshi live position is a Suggested row, as designed. The live plan's rows are paper2's scoped rows, and with the floor off that means the Suggested rows the venue quotes. The "0 Suggested" was my probe's fault, and so was the run's "2 in a live plan vs 0 Suggested" mismatch: the two counts measured different things.

**11-23's claim stands.** "All 7 `suggested=False` and `live_ev_floor=0`" read the floor tag. The tag writes both fields explicitly, so this fault cannot have touched it.

**Fix, tooling only (lane portfolio-monitor):** `scripts/portfolio_monitor_probe.py` `alignment()`.
- `live_positions_suggested` now counts live positions whose key matches a Suggested board row, the same join as `suggested_in_live_plan`.
- A new `live_positions_floor` counts positions tagged `live_ev_floor == 0`.
- The rendered line reads "(N Suggested on the board now, M from the 0% floor)".
- New test `test_a_live_position_is_suggested_by_the_board_row_not_by_a_flag_it_never_carries`. 26 of 26 probe tests pass.
- Scratch probe run at 10:35 AM CST: Kalshi "live plan 2 positions (2 Suggested on the board now, 0 from the 0% floor)". Suggested bought today: 2 of 45.
- Caveat: the board is read now and the plan was built earlier, so a row that drops out of Suggested in between reads as not Suggested. That is drift, the same caveat as the order join.

**Lead, not followed:**
- Polymarket's paper2 sizes 2 Suggested rows at its own price, but its live plan holds 0.
- Its live refusals include `aggregator_priced` 8: `placeable_refusal` drops a row whose price is not the venue's own.
- Not yet checked whether those 2 are among the 8.

**Verified on the scheduled watch (11:04 AM CST reading, 17:04:04Z, from the primary tree at `2fd5e87b8`).**
- Kalshi: 2 positions, 2 Suggested on the board, 0 from the floor.
- Polymarket: 0 positions.
- The probe returned rc 0 in 9.5 s, and every step after it returned rc 0.
