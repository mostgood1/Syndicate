# Board query response cache (rail monitor I-13) — premise measured, NOT built

`[2026-11-17 ~2:27 PM CST, session local_004fdc3e "Cache the built board query response per board version", started by the rail monitor local_62433e58; no lane opened: read-only measurement, no code changed]`

**The proposal (rail monitor I-13, `findings_2026-11-17_layer2_rail_monitor.md`):** cache the built
`/api/intelligence/query` response per board version, instead of rebuilding it on every request. The
premise was: "The board changes every few minutes, but the same 5,100-row response is rebuilt and re-hashed
per request."

local_bc8d3e61 gave 6 design notes:
- mirror the home embed cache;
- key on the request flags + `sort_keys`;
- keep `timestamp` / `selected_date` / debug per request;
- cache the gzipped bytes;
- check `LAST_RESULT`;
- use `response_hash` equality as the test.

**Verdict: the premise holds only for duplicate requests seconds apart. For the page's own 60 s poll, the
served response changed every time it was measured (6 of 6), so a version-keyed cache would have hit 0 of 6.**
Nothing was built.

## What was measured (all read-only on the fleet, `http://127.0.0.1:10000`)

### 1. Who sends the query, and how often (`C:\tmp\i13\query_rate.py`, web.log `QUERY_STAGE_MS`)

- **7,108 queries, 2026-11-10 .. 11-17.** 220 to 1,581 a day.
- **Gaps between queries with the same flags:** p10 28 s, p25 57 s, median 60 s, p75 62 s. That is one client
  polling every 60 s (the page's poll), plus a little else.
- **Share of queries that arrived within T s of the previous same-flag query** (an upper bound on a shared
  cache's hit rate with TTL T):

  | T | share | server time inside that share |
  |---|---|---|
  | 15 s | 4.5% | 1,854 of 35,064 s |
  | 30 s | 10.5% | 4,446 s |
  | 60 s | 51.5% | — |
  | 120 s | 84.6% | — |

  Past 30 s, every "hit" is the page's next poll, which (section 3) gets a different response.
- **Since the 13:51 CST restart (to 20:2xZ): 6 queries**, 4 of them this probe's. The user's tab had not
  polled since the reboot.

### 2. What the server spends per query (`C:\tmp\i13\stage_summary.py`)

Since 19:51Z (n = 6):

| stage | median | max |
|---|---|---|
| `board_read` | 4,972 ms | 10,676 ms |
| `version_and_debug` | 2,273 ms | 7,189 ms |
| `hydrate_and_mirror` | 1,428 ms | 4,879 ms |
| `drop_row_diagnostics` | 575 ms | 1,794 ms |
| `slim` | 208 ms | 449 ms |
| `row_refs` | 177 ms | 713 ms |
| **total** | **8,637 ms** | **22,831 ms** |

Web runs `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS=180`, which is not the code default of 15. In-play
overlays expire that cache after `SYNDICATE_INPLAY_OVERLAY_CACHE_MIN_AGE_SECONDS=22`, and the overlay warmer
rebuilds watched boards between requests. `WEB_CONCURRENCY=2`, so each gunicorn worker has its own board cache.

### 3. Does the served response change between the page's polls? (`C:\tmp\i13\change_probe.py`)

The probe sent the page's own body (`slim_aliases`, `drop_row_diagnostics`, `row_refs`) twice back to back,
then six more times about 70 s apart, 20:19:22-20:26:21Z (2:19-2:26 PM CST, Tuesday afternoon). It kept only
hashes and field names. Results, `C:\tmp\i13\change_probe_20261117.jsonl`:

| pair | gap | same `version` | rows added / removed / changed | top changed fields |
|---|---|---|---|---|
| 0 → 1 | 5 s | **yes** (only `timestamp` differs) | 0 / 0 / 0 | — |
| 1 → 2 | 70 s | no | 2 / 1 / 13 | `quote`, `book_age_seconds`, `gate`, `price_grid_generated_at`, `live_model_probability` |
| 2 → 3 | 69 s | no | 238 / 72 / 3,798 | `book_age_seconds`, `gate`, `quote`, `movement_age_seconds`, `movement_series`, `score` |
| 3 → 4 | 70 s | no | 6 / 0 / 28 | `quote`, `book_age_seconds`, `gate`, `edge`, `score` |
| 4 → 5 | 70 s | no | 18 / 27 / 3,950 | `book_age_seconds`, `quote`, `gate`, `movement_*`, `score` |
| 5 → 6 | 68 s | no | 4 / 40 / 297 | same, plus `by_date` / legacy counts |
| 6 → 7 | 67 s | no | 3 / 3 / 11 | `quote`, `book_age_seconds`, `gate`, `edge`, `actual` |

Other readings from the same probe:
- **`state_last_updated` was `2026-11-17T20:17:26Z` on BOTH 6 and 7.** The worker-published state did not move
  between those polls. The churn is web-side: book-grid quotes and in-play overlays merged at read time, plus
  their ages.
- **The duplicate request was cheap already:** 2.94 s warm vs 5.70 s cold. The board-level cache did half the
  work, and a response cache would have saved the rest.
- **The served response is deterministic for unchanged inputs** (0 → 1). So `response_hash` equality is a sound
  test, and the page already uses it: it skips re-rendering when the hash is unchanged
  (`intelligence.html:6152`).

### 4. What a correct cache key would need (read from the code)

Beyond the board's identity and the request flags, the key would need:
- **The live-column artifacts read at request time.** `_refresh_live_columns_from_artifact` reads the NBA lens,
  the NHL/NFL box and the MLB lens on every request (`intelligence.py:1518`).
- **The gate's clock.** `opportunity_gate` demotes a row once its `commence_time` has passed
  (`opportunity_gate.py:199`), and `_regate_board_rows` re-runs it per request "so the answer is current as of
  the request" (`intelligence.py:1307`).

A cache that omitted either would freeze live columns or lane assignments for its TTL.

`LAST_RESULT` has no reader anywhere in the repo (write-only), so skipping it on a hit would change nothing.

## So

- **A version-keyed response cache saves at most the duplicate requests**: about 4.5% within 15 s, mostly a
  second tab, a script or a probe beside the page. It saves nothing on the page's own poll while the board is
  moving, which is when it matters.
- **Leads, not built:**
  - **(a) Serialize once.** `version_and_debug` runs `_json_safe_value` over the whole payload and `json.dumps`
    of the ~24 MB wire payload for the hash. `jsonify` then serializes it again, and the app's JSON provider
    does its own NaN pass. Hashing the bytes that are actually sent would remove one full walk and one dump per
    request. That is an estimate, not a measurement; the post-stage `jsonify` + gzip time is not in
    `QUERY_STAGE_MS`. It changes the `version` values (opaque; the page compares them only for equality) and
    needs the provider's exact bytes.
  - **(b) A short dedupe window, 10-15 s,** keyed on flags + the combined board's identity + the live-artifact
    mtimes. It is only worth building if multi-client traffic grows. I-16 (scripts should send `row_refs`) is
    the related item.

## Lead (a) built: serialise once (lane `board-query-serialize-once`, user "Build serialize-once") -- ON MAIN `64daca46f`, NOT LOADED

`[2026-11-17 ~4:35 PM CST, session local_004fdc3e]`

**The change.** `_versioned_query_json_response` (`syndicate/blueprints/intelligence.py`) replaces
`_versioned_query_response` + `jsonify` on the four exits of `intelligence_query_api`:
- it walks the wire payload with `_json_safe_value` once and `json.dumps` it once, with the app
  provider's own settings (`default`, `ensure_ascii`, `sort_keys`, compact separators);
- it hashes those bytes for `version` / `response_hash`;
- it dumps the small envelope through the provider, with a uuid placeholder as `response`, and
  splices the payload bytes in (the placeholder must occur exactly once).

Fallbacks to the old exit: `SYNDICATE_QUERY_SERIALIZE_ONCE=off` (absent = on; on the fleet, env is
built only at `up`), a provider that is not Flask's default kind, and pretty-printing (debug mode).
`QUERY_STAGE_MS` gains `"serialize_once"`. Its `version_and_debug` stage now covers the whole
serialisation; under the old exit, the `jsonify` half ran after the timer stopped.

**Correction to lead (a) above.** It said the change "changes the `version` values". It does not,
for any payload in which nothing needs a JSON `default`, and the fleet's does not. The provider's
dump of the payload is the same string the old hash was taken over. Measured: the new `version` ==
the version the fleet served for the same response. Only a non-native value (e.g. a `datetime`)
would move it, and then it hashes the bytes actually sent.

**Measured on a fleet page response** (`C:\tmp\i13\serialize_bench.py`): the page's own body,
fetched 2026-11-17 21:46:25Z, 4,432,490 B gzipped / 24,446,438 B payload, saved as
`C:\tmp\i13\page_query_20261117T2200Z.json.gz`. One process, the arms alternated, Idle priority.

| | old exit | new exit |
|---|---|---|
| response bytes | 24,446,956 | 24,446,956, **identical** |
| `version` | the served hash | the same |
| median, 10 runs each, quiet CPU | **2,259 ms** (hash part 1,080 + `jsonify` part 1,004) | **950 ms** (856-1,214) |
| median, 5 runs each, under a parallel test run | 3,482 ms | 2,177 ms |
| tracemalloc peak | 109.9 MB | 79.4 MB |

Falsification (lane block) not met: 0 bytes differ, 58% saved (the bar was 20%), and the peak fell.
The new exit costs about what the old hash alone cost, so post-load `version_and_debug` should stay
near its pre-load median, while the ~1.0-1.3 s the old `jsonify` spent after the timer disappears.

**Tests:** `tests/test_intelligence_query_serialize_once.py`, 14 tests.
- **Reachability, off != on:** the `QUERY_STAGE_MS` field follows the switch, and when on the
  provider never dumps more than the 5 KB envelope.
- **Bytes:** identical to the old exit through the route (page body, slim+drop, no flags) and
  through the helper (NaN/Infinity, non-ASCII, placeholder look-alikes).
- **Hash:** the old hash on the recorded board, and a hash of the response bytes sent.
- **Fallbacks:** pretty-print, and a `response` key in the envelope fields.

Beside it, all passing: 199 tests in the neighbouring query suites, and the 51 query-route tests in
`test_intelligence.py`. The full `test_intelligence.py` exceeded a 25-minute timeout at ~32%, with
0 failures by then.

**Owed after a load** (todo `#828`):
- `QUERY_STAGE_MS` `"serialize_once": true`;
- `version_and_debug` within noise of its pre-load median (read it just before the load);
- the page query's client-side seconds against a pre-load series, same body, several samples (this
  endpoint's run-to-run spread is ~4.8 s, so 1 s needs a series, not a pair);
- the served `version` still matching across the reload when the board has not moved.
