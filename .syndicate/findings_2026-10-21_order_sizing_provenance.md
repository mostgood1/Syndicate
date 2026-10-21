# todo #722: the sizing provenance now travels onto the order — four hops, no new computation, and the reading it unblocks is FORWARD ONLY

`[2026-10-21 22:30Z / 17:30 CDT]` session `4ab694ed`
lane `order-sizing-provenance` — shipped `966e0b5f` (+ lane `1772d054`)
`[no outcomes used; this is an instrumentation fix with a measured byte cost]`

## Why

The armed 2026-10-21 reading returned **0 settled positions in every cell** —
`findings_2026-10-21_staked_probability_version_reading.md` has the numbers. Not
underpowered: **958 of 3,000** ledger orders are settled (**576 live**) and none
could be attributed to a sizing basis, because all **658 live orders** were
unjoinable to a plan and **552 carry no `position_key`**.

`sizing.basis`'s own comment at `portfolio_commit.py:1456` had already stated the
purpose it was failing to serve — *"Without it, model-edge and market-fair
positions land in one settlement pool and their ROIs stop being separable."* It
delivered that in the PLAN and lost it at SETTLEMENT, the only place an ROI
exists.

## What shipped

Four hops, each following this file's own precedent for `model_edge_pct` and
`sim_view` (whose comment says those too "already exist on the plan position at
commit time and were simply dropped here"):

1. `OrderRequest.staked_probability_version` / `.sizing_basis` — `str | None = None`.
2. Both added to **`_LEAN_FIELDS`** (47 entries), so the ledger's trim cannot
   drop them — provenance that survives only while a row is young is the
   opposite of what a settled-ROI split needs.
3. The record builder persists both.
4. `_order_from_position` populates them from the position.

**The nested read is the part that would have shipped inert.** The position nests
these under `sizing`, exactly as `attribution` nests `side_picked_by` — and the
adjacent comment names the failure mode, "presence is not reachability". A flat
`position.get("staked_probability_version")` would return `None` forever while
every direct-construction test still passed. `test_the_nested_read_is_reachable`
is the one assertion that catches that, and it asserts `off != on`.

**Absent stays absent.** No default: `"unfitted"` is a REAL profile, so
defaulting to it would mislabel a row into the very population the split exists
to separate. **Not in `idempotency_key`** — a row re-sized under a new profile is
the same bet; had these entered the key, #704's 2026-10-19 activation would have
made every open position look like a fresh order. Both pinned by test.

## Measurements

- **Falsification did not fire.** Checked before writing code: every position in
  the `kalshi`, `novig` and `prophetx` venue plans for 10-20/10-21 carries both
  fields (e.g. kalshi 10-21 `market_fair@unfitted` / `model_edge`). So the fix
  belonged at the `OrderRequest` boundary, not in `position_key` coverage. Venue
  plans matter specifically because **live execution reads them**
  (`execute_portfolio.py:612`), not the main plan.
- **Byte cost, measured against the live ledger rather than estimated**, because
  this file holds itself to a per-order budget: **1,341 B/order** today (the
  file's own comment says 1,094 — it has grown), **+52** for the version alone,
  **+80** for both → 1,421 B/order. At `_MAX_RECORDS` **3,000** that is
  **4.02 MB → 4.26 MB**, i.e. **50% → 53%** of the store's 8 MB refusal ceiling.
  The cap is already 3,000 and the ledger sits AT it, so this widens each record
  and not the document's horizon.
- **Tests:** 6 new, plus **248 passing** across this file, `test_execution_ledger`
  and `test_execute_portfolio`. Re-run after rebasing onto upstream.

## What is NOT done, and it matters

- **Attribution is FORWARD ONLY.** The 958 already-settled orders stay
  unattributable forever — nothing reconstructs which profile sized them. So
  lane `published-negative-ev`'s reading cannot simply be re-run: it must be
  **re-armed for a date after this reaches the fleet**, and its pre-period will
  be empty rather than merely thin.
- **Not on the fleet.** A peer ff'd at 21:48:15Z; this landed after. Until the
  next ff plus a live-odds-worker restart (the executor imports
  `execute_portfolio` in-process), no order carries the fields.
- **`position_key` coverage is still broken** — 552 of 658 live orders have none.
  This fix routes around that rather than repairing it, which is the cheaper and
  more direct half. If a future reading needs to join orders back to plans for
  anything else, that gap is still there.
- **The paper ladder path was not touched.** `PaperLedgerBatch.place` is held by
  lane `paper-alongside-live`; paper orders placed through it may not carry the
  fields even after this. Not checked, and named rather than assumed.
