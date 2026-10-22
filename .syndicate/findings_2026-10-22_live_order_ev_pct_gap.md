# Findings: live-order-ev-pct-gap (todo #728, 2026-10-22)

Lane `live-order-ev-pct-gap`, session c75c910c (side session of local_c7606dbb).
Question: which LIVE write path leaves execution-ledger orders without `ev_pct` or a price,
attributed by time window and builder.

## s0. Read

- Fleet execution ledger, read-only, 2026-10-22T17:12:56Z.
  - Read with `/home/amyn/.venvs/syndicate/bin/python`, nice 19, keyvalue backend.
  - `read_json_file_result(_ledger_path())[1] is True` was asserted. The script refuses with exit 4 otherwise.
- Code: fleet checkout `0a2986b4`.
- Population: 12,229 orders (3,000 in the document, 9,229 archive-only). 677 live, 627 settled live (257 won / 369 lost / 1 push).
- Tool: `scripts/ledger_live_ev_pct_census.py` (new, read-only).
  - Each field is classified as absent / null / value with `in`, never `.get()`.
  - A row's builder signature is the set of attribution keys it carries.
  - "No price" uses the fitters' own lookup: the first of `requested_price`, `fill_price`, `price` that parses.

## s1. RESULT: no live write path omits `ev_pct`

Every settled live row without `ev_pct` comes from one writer: `venue_ledger_rebuild` (`source=venue_rebuild`).
That writer reconstructs the Render-era live book from the venues' settlement history. It does not place orders.

Settled live rows, by builder signature x (`ev_pct` state | price):

| builder (signature) | n | `ev_pct` absent / null / value | no price | usable by the fitters |
|---|---:|---|---:|---:|
| `venue_rebuild` (2026-10-02 apply, `331eaebe`) | 552 | 0 / **552** / 0 | 132 | 0 |
| `place_order` via `execute_portfolio._order_from_position` (`ev+sim+attr`, plus `sizing` from 10-22) | 75 | 0 / 0 / **75** | 0 | **75** |

- **Key ABSENT on 0 rows.** No old builder wrote any surviving live row. `ev_pct` has been on `OrderRequest` since `04187cdf` (2026-09-03). Every live order the old builder placed before then lived only in Render's ledger.
- **Key NULL on 552 rows.** All 552 are the rebuild, which writes `ev_pct: None` deliberately (`venue_ledger_rebuild.py:157`). Its docstring says so: "WHAT IT CANNOT RECOVER ... the plan, model edge, sim view". The rebuild rows have no `market`, `line` or `event_id` either (0 of 552). They carry only the venue ticker or slug.
- **The current builder: 125 of 125 live orders carry `ev_pct` and a price.** That is every live row placed on the fleet, 10-19..10-22, including the 50 not yet settled and 1 rejected.

The numbers match todo #728's exactly, split by the fitter's drop order (`no_price` is checked first):

| fitter drop reason | n | who |
|---|---:|---|
| `no_price` | 132 | polymarket `venue_rebuild`. Polymarket settlement gives a realized P&L delta, not a price, so `requested_price` and `fill_price` are both null. |
| `no_ev_pct` | 420 | kalshi `venue_rebuild`. `fill_price` is set (the average cost), so the row passes the price check and then fails on `ev_pct`. |
| usable | 75 | fleet-placed live orders |

(#728 read 131 / 420 / 74 at 16:46Z. One more order had settled by 17:12Z.)

## s2. By time window

| window (by `submitted_at` week; rebuild rows use the venue's settle time) | builder | settled live | `ev_pct` null | no price | usable |
|---|---|---:|---:|---:|---:|
| 2026-W32 .. W40 (slates 2026-08-06 .. 09-27; Render era) | `venue_rebuild` | 552 | 552 | 132 | 0 |
| 2026-W40 .. W42 (09-30 .. 10-18; fleet, live plan empty) | none | 0 | - | - | - |
| 2026-W43 (10-19 .. 10-22; fleet live trading) | `place_order` | 75 | 0 | 0 | 75 |

- The rebuild rows' slates split 293 August and 259 September.
- Fleet-placed settled live orders by day: 10-19 1, 10-20 15, 10-21 59. Unsettled 10-20..10-22: 50.
- The empty middle window is the live-plan funnel (state `[live-plan-empty-funnel]`): no live bet cleared the taker fee until 10-19.
- The usable rows are mostly kalshi NBA `spreads_alt` (29) and kalshi NBA/WNBA player props (26).

## s3. Can the 552 be recovered? No, from any source on hand

`ev_pct` is a decision-time number. It existed on Render's plan positions and in Render's ledger, and both stayed in the suspended Render keyvalue. Checked on 2026-10-22:

- The fleet's `clv_openings/` starts at 2026-09-30. 1 file is in Aug/Sep, and it is 09-30.
- The fleet's `portfolio_*plan*` files start at 2026-09-30.
- `origin/main` tracks no execution ledger, no Aug/Sep plan and no Aug/Sep openings.
- `~/syndicate-prod-backup/` holds only the daily snapshots from 10-16 on. The pre-rebuild backup named in `state_worker.md` held the fleet's 22 paper rows, not Render's.

Even with Aug/Sep openings, an opening's `ev_pct` is a first-sighting value keyed by (market, line, book). It is not the `ev_pct` the sizer used. Joining it onto a ticker-only row would make up a decision-time number, which `#425` and the rebuild's own contract forbid. **The 552 should stay null.**

## s4. Verdict and fix

- **No write-path fix is warranted.** The live write path (`execute_portfolio._order_from_position` -> `OrderRequest` -> `_record_into_state`) records `ev_pct` and a price on 125 of 125 fleet live orders. Hypothesis "a live path builds `OrderRequest` without `ev_pct`" is FALSIFIED. Hypothesis "pre-`ev_pct` builders (key absent)" is FALSIFIED: 0 absent.
- **What #728 measured is a short history, not a leak.** The measurable live book is the fleet-era book. It started 10-19 and is growing about 15-60 settled orders a day.
  - At the 10-21 rate, the live book passes the 552 unmeasurable rows in roughly 1-2 weeks.
  - It will not reach any single cell's 200-held-out floor soon. The usable rows are spread across about 20 venue x sport x market cells.
- **A reader-side legibility fix is warranted, but it is not mine to make.** All three fitters (`fit_staked_probability.derive_row`, `fit_probability_calibration`, `ev_overstatement_decomp`) report these rows as `no_ev_pct` / `no_price`. That reads as "the live book is missing its EV", which is how #728 was framed.
  - The proposed fix: name the drop `venue_rebuild` (checked on `source` before any price or EV check) so the decision record's absence is legible.
  - It changes no fitted number, because those rows are dropped either way. So it needs no default-off switch. The test is that the drop counts move from `no_ev_pct`/`no_price` to `venue_rebuild` with the same total.
  - The files are claimed by lanes `sim-stake-unfitted-market-only` and `fitter-contract-price-units` (loans), so this is recorded as a lead for them, not done here.

## s5. Rule this confirms

When a fitter drops a large share of a population under a field-missing reason, run the builder-signature census before looking for a leaking writer. Here one non-placing writer (a reconstruction) accounted for 552 of 552.
