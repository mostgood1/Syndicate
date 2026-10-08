# execution_ledger growth — findings (lane `execution-ledger-keyvalue-growth`, 2026-10-08)

## What was measured (fleet, read-only, before any change)

Sources: `[execution_ledger] SIZE_WARNING` lines in refresh-worker.log.3 .. .log,
2026-10-03T23:47Z .. 2026-10-08T15:54Z. Also one read-only read of the keyvalue copy
at ~15:10Z (probe: role env loaded into a dict from `/proc/<pid>/environ`, then
`read_json_file(_ledger_path())`; only sizes, counts and dates printed).

| reading | orders | bytes | B/order |
|---|---|---|---|
| 10-03 23:47Z | 1,741 | 2,098,299 | 1,205 |
| 10-05 13:49Z | 2,641 | 3,191,907 | 1,209 |
| 10-07 04:01Z | 3,819 | 4,993,376 | 1,308 |
| 10-08 10:17Z | 4,589 | 6,117,497 | 1,333 |
| 10-08 15:54Z | 4,707 | 6,266,807 | 1,331 |

Keyvalue copy at ~15:10Z: 4,698 orders, 6,255,391 B. Of these, 4,146 are paper,
all dated 10-02 or later (the fleet's first day), at about 600 a day. 552 are
live, dated 08-06 .. 09-27. Graded: paper 1,122 L / 885 W / 13 P, with 2,126
ungraded, every one of them `filled`. Of the 1,332 ungraded rows dated before
10-07, 1,218 are NCAAF. Largest per-order fields: `opening_key` 121 B,
`closing_mark` 106 B, `venue_resolved_at` 50 B. B/order by date ranges
1,173-1,461.

## What that means

- **The brief's 8 MB-by-10-10 projection was wrong.** It extrapolated the total
  linearly. `_MAX_RECORDS=5000` + `_trim_to_cap` bound the document, and
  SIZE_WARNING itself said `projected_at_cap=6.66MB, 79%`. H2 CONFIRMED in
  part: the residual refusal risk is B/order creep. At 5,000 the ceiling sits at
  1,678 B/order, and the worst date was already 1,461.
- **H1 CONFIRMED: the real event was the cap firing.** It would have been reached
  around 10-09 03:00Z. Then `_trim_to_cap` permanently DROPS the oldest paper
  rows, ~600 a day, and nothing archives them (a subagent survey found no archive
  or copy anywhere). Six full-history readers would quietly have become
  last-week readers: the paper page's all-time tile and past dates
  (`intelligence.py`), `settlement_summary` / `settled_decisions_by_sport` /
  `sim_view_roi_summary` (all-time ROI and the portfolio credibility sample), the
  scorecard's 28-day staked window, `fit_staked_probability`,
  `fit_probability_calibration`, and ops `?days=` beyond the window.
- **H3 CONFIRMED (different class): `query_state_cache.json` is not an
  accumulator.** It is the compressed board snapshot (`intelligence_state.py:4481`),
  whose size follows the slate: 7.2-11.1 MB, 232 refusals from 10-07 05:11Z to
  10-08 00:45Z, 0 since. Recorded as a lead, not fixed here.

## The fix (this lane)

1. `_trim_to_cap` MOVES rows instead of dropping them. It returns the rows it
   takes out, settled paper first (oldest first), then ungraded paper. `_persist`
   appends them to `reports/intelligence/execution_ledger_archive/orders_<YYYY-MM>.jsonl`
   BEFORE the document that omits them is SET (write-ahead, per CAS attempt). Plain
   disk IO with `flock` and `fsync`, never the keyvalue store. If the append fails,
   the rows stay in the document and `LEDGER_ARCHIVE_FAILED` is printed.
2. `full_history_orders()` = archive + document (the document wins; last
   archived copy per identity). `archived_orders(months)` reads shards through a
   parse cache keyed on (mtime, size).
3. Switched to full history: `paper_settlement` all-time defaults and the settle
   pass's `SETTLEMENT_SUMMARY`, the paper page, `ledger_summary(date)` (that
   month's shard), ops `/execution-summary`, the scorecard, both fitters.
   Operational readers (placement, idempotency, reconciliation, settlement of
   open rows, venue repairs) keep `_load()`.
4. `_MAX_RECORDS` 5000 -> 3000 (user-approved), giving 4.0-4.4 MB at the cap
   (48-52% of the ceiling) and a break-even of 2,796 B/order.

## Known limits (stated, not fixed)

- An ungraded row archived is never graded later. Settled rows leave first, so
  this happens only once the ungraded backlog plus live rows exceed the cap.
  Today that is 2,126 ungraded paper (1,218 NCAAF) + 552 live = 2,678 of 3,000.
  **The NCAAF grading gap is the thing that makes this bite** (lead).
- Live rows are never trimmed, so they grow without bound, slowly: 552 in ~7 weeks.
- The archive is read whole for all-time figures. That is ~0.8 MB of JSONL a day,
  parsed once per shard per process. A year of it would want a rollup.
- On a deployment whose services do not share a disk, each service archives only
  what IT trimmed. On the local fleet all roles share one reports root (verified
  by hash).
- `apply_segment_regrade` matches `_load()` only, so it cannot regrade an archived
  row.
