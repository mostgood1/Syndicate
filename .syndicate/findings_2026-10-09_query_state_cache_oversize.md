# query_state_cache.json refused at the 8 MB keyvalue cap: cause, cost, fix (2026-10-09)

Lane `query-state-cache-oversize` (session f2414f71). Builds on lane
`execution-ledger-keyvalue-growth`'s H3 (findings_2026-10-08_execution_ledger_growth.md),
which showed this is not an accumulator.

## Measured before the fix (fleet, refresh-worker logs, emitter-prefix anchored)

| log | KEYVALUE_WRITE_REJECTED (qsc) | window | sizes | fallback |
|---|---|---|---|---|
| refresh-worker.log.5 | 8 | 10-03 05:13Z..22:21Z | 8.46-9.16 MB | TRIMMED kept_full=0 (of=2/4) |
| refresh-worker.log.3 | 24 | 10-05 22:03Z..23:46Z | 8.39-9.04 MB | TRIMMED kept_full=0 of=3 |
| refresh-worker.log.2 | 232 | 10-07 05:11Z..10-08 00:45Z | 8.63-12.48 MB | TRIMMED kept_full=0 |
| refresh-worker.log.1 | 297 | 10-08 19:10Z..10-09 10:04Z | 8.41-12.84 MB | TRIMMED kept_full=0 |
| refresh-worker.log | 285 | 10-09 10:06Z..17:33Z (every write) | 11.68-13.59 MB | TRIMMED kept_full=0 of=3 |

The 10-08 lead's "0 since 00:45Z" was a window artefact: refusals resumed at 19:10Z.

**Every refusal was followed by a SUCCESSFUL fallback write with `kept_full=0`.**
So readers never got a stale copy. They got a cache with no response at all.
Read-only probe of the live keyvalue copy at ~16:50Z: `snapshots` 1,342 B, 3
entries (2026-10-08 computed 04:59Z, 10-09, 10-10), every `response=None`.

## What drives the size

- **Count:** one snapshot per board-window date the loop keeps warm, 2-3
  (yesterday's lingers inside `_max_snapshots=12`). This explains the bursts:
  refusals start when the 2nd/3rd date's snapshot lands and stop after a
  restart, when only 1 is held.
- **Per-snapshot size:** `response.layer2_shortlist` = **40,805,534 of
  42,396,873 raw bytes (96%)**: cards 21.7 MB + rows 19.1 MB. That is 5.36 MB
  compressed per snapshot (zlib level 6, 7.9x, 5.9 s CPU each). Without it the
  snapshot is 1.59 MB raw / **~215 KB** compressed.
- **The trim cannot help.** `_budgeted_snapshots_payload` budgets RAW bytes at
  6 MB, written before #322 compression existed. A 42 MB-raw snapshot never
  fits, so `kept_full=0` is structural.

## Cost (reader survey, origin/main)

- Web, background loop off: `read_latest_response` syncs from STATE_PATH,
  and on keyvalue that sync CLEARS `_snapshots` before reloading. With every
  response stripped it returns None, and every route falls back to
  board_snapshot.json / dated board_snapshot / dated intelligence_state /
  Layer 2 artifacts. The served board degraded, it did not break. The "worker"
  state source was dead, and a non-latest date read the dated files instead.
- Refresh-worker: no regular path force-syncs (`status()`/`get_response()`
  have no callers), so its in-memory snapshots stayed 2-3 the whole time. The
  per-hour PERSIST_LOCKED_BEGIN counts confirm it. Warm-start after a reboot
  got nothing.
- CPU: each persist compressed ~127 MB raw (3 x 42 MB) about 40x/hour, then
  re-serialised every entry for the trim.
- Other readers: the ops candidate trace (`ops.py:4361/4569`, reports keys
  only). Nothing else.

## Fix (fc1762da)

`_query_state_persist_response`: the persisted copy of each snapshot replaces
`layer2_shortlist` with a marker `{omitted_from_query_state_cache, read_from:
read_layer2_shortlist, selected_date, rows_count, cards_count}`. The marker
deliberately has no `rows` key. The in-memory snapshot and the board_snapshot
write are unchanged. Every served Layer 2 surface already reads
`read_layer2_shortlist(date)`, the shortlist's own per-date artifact. Nothing
on web or in the templates reads `response.layer2_shortlist`; only the
canonical board-state builder does (`:8974`), from a freshly computed
response. Expected size: ~0.2 MB per snapshot, < 1 MB for 3.

Kept: compression (first line) and the raw-byte trim (second line). The trim
is now reachable only by a response that is huge without Layer 2.

Rejected alternatives: bounding snapshot count (2 x 5.36 MB still refuses), a
dated keyvalue path per date (the 09-03 TTL learning, and it still carries
40 MB raw per date), raising the cap (Redis closes the connection near 9 MB).

## Verification

See deploys.md (2026-10-09 refresh-worker restart, lane query-state-cache-oversize).
