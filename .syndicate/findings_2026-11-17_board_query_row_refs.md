# Board query sends each opportunity row once — `row_refs` (lane `board-query-row-refs`, todo `#826`), 2026-11-17

Origin: layer2-rail-monitor backlog **I-2** (`findings_2026-11-17_layer2_rail_monitor.md`).
User 11-17 ~11:0x AM CST: "start the board query de-dup session".
Times are Central (CST) unless marked Z.

**Status: ON MAIN `5db26434e` (ledger `2e638ee61`), NOT LOADED.** Loading it is the user's decision: an ff plus `reload-web`, with no env
change. Read-only on production throughout: every measurement below runs on a response the monitor had
already recorded. The fleet was never called.

## Before: the recorded fleet response

Source: `C:\tmp\railmon\readings\20261117T014841Z\query.json`. It is the page's own request
(`slim_aliases` + `drop_row_diagnostics`) at 7:48 PM CST 11-16, recorded by the rail monitor's probe:
80,281,792 bytes raw, 14.4 MB on the wire, 78 s to serve.

| list | rows | bytes |
|---|---|---|
| `ranked_all` | 6,295 | 23,889,971 |
| `board_contract.cards` | 6,295 | 23,064,774 |
| `top_opportunities` | 4,500 | 21,340,843 |
| `top_live_opportunities` | 2,176 | 11,904,010 |
| everything else | | < 3 KB |

**The brief's premise needed one correction: no row in any list is an exact copy of its `ranked_all`
row.** Every `pick_id` in `ranked_all` is unique, and every row of the other three lists has its
`pick_id` there, in `ranked_all` order. Their contents differ, though:

- **`top_opportunities`:** all 4,500 rows are the `ranked_all` row PLUS 8-10 keys: `rationale`,
  `normalized_edge`, `advanced_ready`, `missing_advanced_inputs`, `american_odds`,
  `market_fit_score`, `advanced_readiness`, `pick`, and `name` / `subject_key` on 4,193. No shared
  key has a different value.
- **`board_contract.cards`:** all 6,295 lack `home_logo` / `away_logo`. Values differ in `gate` on
  498, `board_lane` on 54, `live_total` / `live_projection` on 40, and `actual` on 12; `actual` is
  absent on 31.
- **`top_live_opportunities`:** all 2,176 differ in `quote` and `movement`, and still carry `trace`,
  `score_breakdown`, `game_pk`, `market_key` and `selection`. `drop_row_diagnostics` never touches
  this list: it is not in `_DIAGNOSTIC_ROW_LISTS`. The 1,983 that are also in `top_opportunities`
  differ from those rows only by those unstripped fields and the logos.

So plain references (the embed's exact-match `_embed_row_refs`) would have referenced nothing, and
dropping any key would have lost data. The encoding below is lossless instead.

## What the page reads (traced in `syndicate/templates/intelligence.html` and the three included scripts)

- Rows are rendered from `top_opportunities`, falling back to `recommendations`; see
  `normalizeIntelligenceResponse`.
- `ranked_all` is read only by `rehydrateAliases`, to rebuild `by_sport`.
- `board_contract` is read, but its `cards` never are: only the row-alias loop touches them, and
  `tests/test_home_payload_duplication.py` guards that.
- **`top_live_opportunities`: 0 references.**
- **`rationale`: 0 references.**
- `ask_bar.js` reads its own endpoint's `top_opportunities`, not this one.
- No code assigns into a row object or deletes from one. The only property writes are on derived
  summary objects (`out`, `group`, `last`). So a JSON-identical payload renders identically, even
  though rebuilt rows share nested objects with `ranked_all`.

## The change (opt-in; default OFF)

- **Server.** `syndicate/features/shared/response_row_refs.py` (`encode_row_refs`) runs after
  `drop_row_diagnostics` on the three slim exits of `intelligence_query_api`. Each of the three lists
  becomes `{from: "ranked_all", index, order, patch, drop}` and stays `null` in place.
  - `patch` holds the keys that are new on a row or whose value differs.
  - `order` holds the wire order of the list's keys. Flask's provider sorts keys, so `order` is
    sorted.
  - `drop` lists the base keys a row lacks.
  - A value is left out of a patch only when `_same_on_wire` proves it serialises the same:
    type-strict, key order included, with NaN and -0.0 always patched.
- **Route.** Only the copy that is serialised is encoded. The debug fields and the stage log keep
  reading the unencoded payload, because `candidate_count` is `len(top_opportunities)`. A test
  catches the 0 that reading the encoded copy would serve.
- **Page.** `intelligenceQueryPayload` sends `row_refs: true`. `rehydrateAliases` rebuilds the lists
  FIRST, before `_dropped_row_aliases` restores `game_pk` / `market_key` / `selection` onto every
  list, then deletes `_response_row_refs`.
- **Off switches.**
  - Server: `SYNDICATE_QUERY_ROW_REFS=off`. ABSENT honours the request. It is env, so changing it
    needs a drained down/up.
  - Client: delete the one template line. A server without the change ignores the flag, and a page
    without it never asks.

## After: measured on the same recorded response

The scratch harness is in this session's scratchpad: `measure_row_refs.py`, `server_path.py`,
`rehydrate_check.mjs` and `browser_ab.py`. It serialises with the provider's own settings
(json_safe, `sort_keys`, compact separators, ASCII) and gzips with `response_compression.gzip_bytes`
at level 1, the fleet default.

| | flag off | flag on | |
|---|---|---|---|
| raw bytes | 80,281,791 | 33,144,917 | **41.3%** |
| gzip-1 bytes (wire) | 14,383,596 | 5,689,938 | **39.6%** |

Encoded spec bytes per list:
- `top_opportunities`: 3,855,227. All 4,500 rows are patched; `rationale` alone is 2.78 MB.
- `top_live_opportunities`: 5,244,154. All 2,176 are patched.
- `board_contract.cards`: 126,469. 524 are patched and 31 drop a key.

**Server time after `drop_row_diagnostics`.** This covers encode + `_versioned_query_response`
(json_safe copy + `_response_hash` dump) + the provider dump + gzip, at Idle priority, two
repetitions:

| | rep 1 | rep 2 |
|---|---|---|
| OFF | 11,962 ms | 18,217 ms |
| ON | 5,111 ms | 7,617 ms |

In the ON runs the encoder itself took 1,507 ms and 1,657 ms. That is its WORST case: a parsed file
shares no objects between lists, while the live build often shares them, and identity short-cuts
`_same_on_wire`. The falsification "encoder costs more than it saves" is **not met**: the encoder
costs ~1.6 s and saves ~7-10 s.

**Browser side** (node, the template's real `rehydrateAliases`):

| | flag off | flag on |
|---|---|---|
| JSON.parse | 2,083 ms | 408 ms |
| rebuild | 156 ms | 424 ms |

**Equivalence, three ways.**
1. **Python reference.** `decode_row_refs` of the parsed flag-on wire, re-serialised WITHOUT sorting,
   equals the flag-off wire: True.
2. **The page's own function under node.** `JSON.stringify` of the response after `rehydrateAliases`
   is identical: 149,957,250 chars each. Negative control: HEAD's template fails it (rc 1,
   `top_opportunities` rebuilt as 0 rows).
3. **The rendered page.** Headless Chromium, the real `/intelligence` served in-process from this
   worktree (`RENDER=true`, so no background loops), the board reader patched to the recorded
   response, chips and live-rail served from the same reading, and the clock fixed at 01:48:41Z.
   It compares 14 board sections' innerHTML, page as-is (`row_refs: true`) vs the same request with
   `row_refs` removed. **IDENTICAL in all 14**, with 0 page errors in either run. That covers the
   cards (7,012,788 chars of HTML, 1,292 card nodes, "Showing 646 of 1,010 plays", 4,500
   candidates), the games rail, the summary strip, freshness, ranks, portfolio, parlays and all the
   filter tabs with their counts.
   - Served through the real route and compression: **14,409,147 B gzipped off vs 5,757,487 B on**.
   - Page-to-render was 88.4 s off vs 63.2 s on. This is local and includes the embed build, so it
     is indicative only.
   - On the 17-row fixture slice the first attempt differed in the games rail. That was a fetch race,
     not the change: chips came from a cold local ESPN call. It was identical once chips and
     live-rail were served from the recorded reading.

## Tests

`tests/test_intelligence_query_row_refs.py` has 29 tests:
- **Reachability:** off != on through the body flag AND through `SYNDICATE_QUERY_ROW_REFS=off`, via
  the real route.
- **Debug fields:** they still read the unencoded payload.
- **Route equivalence:** hydrate -> slim -> drop -> encode -> provider, rebuilt.
- **Size:** reduction on the recorded slice and through the route.
- **Fixture equivalence:** Python and node (the real template function) on
  `tests/fixtures/intelligence_query_row_refs_sample.json`. It is a 294 KB slice of the recorded
  response (17 `ranked_all` rows plus their top / top_live / card rows, values unmodified, chosen to
  cover every case), with a test that it keeps covering them.
- **Order guard:** the page rebuilds before the row aliases.
- **Edge cases:** no base, duplicate ids, int/float/bool, -0.0, NaN, key order, unsorted providers,
  inputs that cannot be encoded, no mutation.

Also run, all passing:
- 142 other tests that touch the query payload or slice this template (10 files), plus 215 more in
  12 files.
- All 22 `tests/js/*.test.mjs` files, on the template with LF endings.

One JS file, `board_chip_freshness_badge`, fails on this Windows checkout's CRLF copy. HEAD's
template fails it the same way, so it is not a regression; it is recorded as a lead.

## Load (the user's decision) and what to read after it

- **What it takes:** an ff of `~/Syndicate` to the landed SHA, then `local_production.py reload-web`.
  Workers are unaffected. No env change. Betting change: **no**, since it changes what web
  serialises, not what is bet. A browser tab that has not reloaded keeps the old page and gets the
  old response.
- **Read after it:**
  - web.log `QUERY_STAGE_MS` should show `"refs": true` with a `row_refs` stage.
  - The served `/api/intelligence/query` Content-Length should fall from ~14.4 MB to ~5.7 MB gzipped.
  - Request time should fall with it.
  - `WEB_WORKER_MEMORY_RECYCLE`: the rate per request against the 5-15-requests baseline
    (expected fewer; unmeasured until loaded).

## Left on the table (leads, not done here)

- `top_live_opportunities` is not in `_DIAGNOSTIC_ROW_LISTS`. Its patch is still 5.2 MB of the 33.1:
  quote 1.5, rationale 1.4, score_breakdown 0.8, trace 0.45. The page never reads the list. Changing
  it changes an existing flag for four callers, so it needs its own consumer survey.
- `rationale` (2.78 MB) has 0 reads on the page.
- Together these are roughly 33 -> 26 MB, the brief's "about 27 MB".
