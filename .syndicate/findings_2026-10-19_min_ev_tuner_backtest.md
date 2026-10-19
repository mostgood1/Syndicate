# min_ev tuner — backtest on the fleet's production ledger (2026-10-19)

Lane `min-ev-tuner-shadow`. Session b98807bc.

## Data — what this rests on

Read 2026-10-19 ~18:16Z from the fleet: `execution_ledger.full_history_orders()` run inside WSL against
the refresh-worker's keyvalue state (`redis://127.0.0.1:6379/0`, reports root
`/home/amyn/syndicate-prod/data/reports`), checkout `~/Syndicate` at `71631544`. 10,414 rows (live doc +
`execution_ledger_archive/orders_2026-10.jsonl`), all `status=filled`; 9,150 graded.

| venue | mode | rows | settled | settled with ev_pct | settled with any CLV | dates |
|---|---|---|---|---|---|---|
| kalshi | live | 421 | 420 | **0** | 0 | 08-06..09-27 (32) |
| polymarket | live | 132 | 132 | **0** | 0 | 08-25..09-27 (23) |
| paper:kalshi | paper | 928 | 769 | 769 | 398 | 10-02..10-18 (17) |
| paper:polymarket | paper | 453 | 407 | 407 | 184 | 10-02..10-18 (17) |
| paper (all books) | paper | 4,789 | 4,045 | 4,045 | 3,000 | 10-02..10-18 (17) |
| paper:novig / :prophetx | paper | 3,691 | 3,377 | 3,377 | 3,003 | 10-02..10-18 |

- The 552 live rows are the 2026-10-02 `venue_rebuild` (one row per settled market, no plan fields):
  results with no `ev_pct`, so **no EV cut line decided them and they are not evidence about one**. The
  tuner skips them as `no_ev_pct`. The first real live order (10-19 16:59Z) is not settled yet.
- **So the tuner's evidence today is paper venue orders only: 1,176 settled rows over 17 dates.**
  Same code as live up to the submit, priced at the venue's own quote; fills assume the quoted price.
- Same-book CLV coverage on those rows, by venue x sport: kalshi ncaaf 182/359, kalshi mlb **49/266**,
  polymarket ncaaf 119/245, kalshi nfl 81/109, polymarket mlb **1/95**, polymarket nfl 1/30. MLB props on
  both venues are close to unclosable: those cells cannot move until that changes.

## Finding 1 — ROI does not rise with EV here either (learnings 2026-09-29 STANDING, third measurement)

ROI and same-book CLV by EV band, event-clustered t (`cell_evidence`):

| population | [2,3) | [3,4) | [4,5) | [5,7) |
|---|---|---|---|---|
| all paper books, ROI % (t) | +0.4 (0.07) | +2.1 (0.35) | −8.3 (−1.33) | −9.8 (−1.12) |
| all paper books, CLV % (t) | +1.24 (7.3) | +1.39 (8.6) | +1.73 (8.1) | +1.56 (6.0) |
| kalshi venue, ROI % | −4.9 | +13.1 | −5.9 | −10.3 |
| polymarket venue, ROI % | −25.3 | −13.2 | −18.1 | +8.3 |

No single band's ROI is significant; the ordering is the read. CLV is positive and highly significant in every band.
CLV runs flat with EV (1.2–1.7), so the extra claimed EV above ~4% is not showing up at the close either.
**Engine read:** claimed EV above ~4% is overstated relative to both the close and the result, which is
an overconfidence signature in the EV the board stamps, not a threshold problem.

**Design consequence (shipped):** the tuner does NOT decide on the whole cell. A cell lost by its 5%-EV
rows would otherwise raise the cut and remove its 2%-EV rows, the better ones. It decides on the
**marginal band** `[cut, cut + 1.0)`, the rows a one-step move actually stops (or starts) taking. Pinned by
`test_a_cell_lost_by_its_high_ev_rows_does_not_raise_the_cut`, mutation-checked (deciding on the whole cell
fails it).

## Finding 2 — at today's volume the tuner proposes nothing, and that is the honest output

Walk-forward replay (`scripts/min_ev_tuner_readout.py replay`): 18 nights (night D sees orders graded
before D 12:00Z), state carried forward. **0 moves.** Final: 60 cells, all `hold / insufficient_events`.
The largest marginal band holds 17 events (polymarket ncaaf h2h) against a 40-event minimum.

Whole-cell decision (before the marginal-band change), for comparison: also 0 moves, and still 0 at
z=1.5 / min 25 events. NCAAF cells there showed ROI −6..−15% (not significant) with CLV +1.4..+2.2
(t 4.3–5.0), which held as `only_clv_significant`.

Rough time to first possible move: one cell's marginal band gains about 1–2 events a day at current paper
volume, so expect **weeks, not days**. The one-week shadow readout will most likely show holds. What it
CAN show is that the job runs nightly, persists, and accumulates evidence correctly.

## Parameters as shipped (all env-overridable, bounded, refuse-not-clamp)

step 0.5, floor 1.0, ceiling 6.0, band 1.0, trailing 150 events, min 40 events, min 30 CLV events, cooldown
20 new events, z 2.0, CLV scope `same_book`, evidence modes `live,paper`, run hour 12Z. Mode
`SYNDICATE_MIN_EV_TUNER` = off / shadow (default; absent and unrecognised resolve here) / apply.

## Not done (decision owed by the user)

- **Apply wiring.** `effective_min_ev_pct` exists and is tested but nothing calls it. The cut lines are in
  `portfolio_commit.py:1102-1108` (claimed by lane `published-negative-ev`) and
  `polymarket_us_orders.py:1251`. Wiring them needs that lane's loan plus the user's apply decision.
- **Cell granularity.** If weeks are too slow, pooling `market` into its family (game_line / game_total /
  player_prop) inside venue x sport x phase roughly triples events per cell. It is still a threshold and
  never an exclusion. This is a user choice: the brief named market-level cells.


## CORRECTION 2026-10-19 19:4xZ -- production's cut line is 0.0, not 2.0, and the band was anchored wrong

**What I assumed:** that the base cut was `DEFAULT_MIN_EV_PCT = 2.0`. Both the brief and the ledger survey said so, and both
were wrong for the fleet. **What production read:** the first nightly line on the fleet, `2026-10-19T19:25:36.467Z [min_ev_tuner]
MIN_EV_TUNER mode=shadow ... base=0.0`. refresh-worker carries `SYNDICATE_PORTFOLIO_MIN_EV_PCT=0`, the user decision of
2026-09-16 (`state.md`, beside the family-exclusion removal). There is no stored settings key on the fleet's Redis, so the env wins.

**Consequence for the design:** anchored at the configured 0.0, the marginal band `[0, 1)` held 0-5 events in every cell. Rows
reach the ledger at EV >= ~2 because other gates bind first (fair noise, net of fee, the shortlist). So the tuner could NEVER move:
holds by construction, not by evidence. Also, the shipped floor of 1.0 sat above the base, so a first raise to 0.5 would have
been refused as out of bounds.

**Fixed (commit below):**
- The band is anchored at the cell's EFFECTIVE cut: max(configured cut, 5th-percentile EV taken).
- A raise steps from that cut.
- A lower is proposed only when the configured cut is the binding gate (`cut_not_binding` otherwise).
- The floor defaults to 0.0.

Mutation-checked: anchoring back at the configured cut fails 2 tests.

**Replay at base 0.0 with the fix:** still 0 moves over 18 nights, but now for evidence reasons. Two NCAAF cells have 45-46 events in
their band and hold only on CLV sample (18 and 28 of 30): kalshi ncaaf spreads band [3.79, 4.79) ROI -12.6% (t -0.64), CLV +1.97
(t 4.2); polymarket ncaaf totals band [3.34, 4.34) ROI -5.3% (t -0.28), CLV +1.65 (t 4.5). Both would hold as `only_clv_significant`
once the CLV sample fills. So the earlier "weeks, not days" estimate was too pessimistic for those two cells, and still right for
the rest.
