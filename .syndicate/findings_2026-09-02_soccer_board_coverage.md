# Soccer board coverage is a DELIBERATE QUALITY FILTER, not a defect

Lane: `kalshi-soccer-club-aliases` (closed) → this finding. Session 41d46db0,
measured 2026-09-02 01:5x–02:0xZ against production. **Nothing was changed.**

This is the third requested "fix" in one session that turned out to be working
as designed — after the soccer title parser and the forward fixture horizon.
This is the one worth refusing most firmly: the other two would merely have
shipped inert, while this one would actively degrade a board that money reads.

## The question

Kalshi lists **171** open soccer fixtures; our board carried **28** of them, so
club resolution — even at 78.6% of what the board makes reachable — is capped at
a 16.4% ceiling. "Fix the board's soccer fixture coverage" is the obvious next
lever. It is not a defect.

## The measurement

`/api/board/layer2-shortlist?limit=2000`, one read, all sports:

| sport | selected | rows on the board | share |
|---|---|---|---|
| mlb | 850 | 804 | 95% |
| ncaaf | 467 | 467 | 100% |
| **soccer** | **1,547** | **129** | **8%** |

The counter that accounts for it, from the same payload:

    rows_uninformative_ev = 1547     <- exactly soccer's selected count
    rows_beyond_horizon   = 2424
    rows_excluded_market  = 3803
    rows_implausible_book = 1656

## Why the filter is right

`layer2_board._row_ev_is_hold_restatement` drops a row whose `ev_pct` is
arithmetically the book's own margin. `book_margin_model` prices a one-sided
market as `fair = implied × (1 − hold)`, and `expected_value_pct(price, fair)`
is `fair/implied − 1`, so **the price cancels and the EV is `−hold` for every
such row regardless of the bet.** Ranking on it ranks on WHICH BOOK QUOTED, not
on value.

It fires **only when the row has no model view** — with a projection the
`sim_component` is a real signal and the row ranks on something else. The
module's own measurement: after the `#601` join fixes, 2,611 rows that had just
gained a correct model edge scored a maximum of **−4.73** against a live
shortlist whose #50 was **+0.64**. Priced, correct, attributable, unreachable.

The value floor cannot catch these either — `_measured_floor_for_pool` derives
it from the same modelled hold, so soccer's floor was `−8.1425 = −1.25 × 6.514`
against rows whose EV IS `−6.514`. **A filter and its input moving together is
not a filter.**

## Why soccer specifically has no model view

By a recorded decision, not an oversight. `soccer-model-dispersion` measured the
model as **worse than market in 8 of 9 leagues** (dispersion falsified; the
remaining defect is discrimination, worst in serie_a −0.055 and bundesliga
−0.111) and its block states: *do not publish `model_edge_pct` on a partial
win — publishing is a separate decision from closing the Brier gap.*

Corroborated on the served board: only **19%** of the 129 soccer rows carry
`model_edge_pct` at all (mlb 5%, ncaaf 0% — every sport is thin here, and
soccer's 1,547 rejected rows are the ones with none).

So the chain is: **weak model → no published model edge → EV degenerates to the
book's hold → the hold-restatement filter correctly removes the row → few
soccer fixtures on the board → Kalshi soccer cannot match.** Every link is
deliberate and every link is evidenced.

## What "fixing coverage" would actually cost

1. **Publish soccer `model_edge_pct`.** Contradicts a recorded decision, on a
   model measured as not beating the market. This is manufacturing a model view
   to get rows onto a board.
2. **Exempt soccer from the hold-restatement filter.** Puts ~1,400 rows on a
   money-adjacent board ranked on the book's margin — exactly the failure the
   filter's 2,611-row measurement documents. If it is ever done it belongs
   behind a flag, default off, with the ranking caveat stated where the rows
   surface, and it must NOT be described as a coverage fix.

**Neither was taken.** The real lever is upstream of the board entirely: give
soccer a model view worth ranking on. That is `soccer-model-dispersion`'s open
work (per-league discrimination), not board plumbing.

## Bounds

* One read, ~02:00Z, on a THIN slate — 28 board fixtures against 76 earlier the
  same evening. The 8%/95%/100% split is the durable part; absolute counts move.
* `rows_uninformative_ev = 1547` matching soccer's selected count exactly is
  strong but is a single coincidence-shaped reading. It is consistent with the
  19% model-edge coverage and with the filter's stated predicate, and it should
  be re-read once before anyone acts on it.
* NOT established: that removing the filter would produce *usable* soccer rows.
  It would produce rows; the 2,611-row measurement says they would rank below a
  live shortlist's #50.
