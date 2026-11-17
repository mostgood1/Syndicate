# Board query: `drop_row_diagnostics` strips `top_live_opportunities` and drops `rationale` (lane `board-query-diag-strip`, todo `#827`), 2026-11-17

Origin: the two 11-17 leads from `board-query-row-refs` (`leads.md`) and that lane's findings,
"Left on the table" (`findings_2026-11-17_board_query_row_refs.md`). Brief from session
`local_bc8d3e61` (the row-refs load owner). Times are Central (CST) unless marked Z.

**Status: ON MAIN `25fc2e4f0`, NOT LOADED.** Loading it is the user's decision (see "State" at the end).
Read-only on production throughout: every number below comes from the response the rail monitor had
already recorded. The fleet was never called.

## The consumer survey (done BEFORE any change; recorded in the lane's Hypothesis)

The flag `drop_row_diagnostics` changes what four senders receive. Each was surveyed for both names,
in every access form (`.name`, `["name"]`, `.get("name")`, a quoted literal, a bare word), and for
GENERIC row consumption (`Object.keys` / `Object.entries` / `for..in` / `JSON.stringify` / a spread
or `Object.assign` of a row, a Python walk). Positive controls ran in the same pass: `top_opportunities`
and `quote` are found in the files that read them, so a 0 is an absence, not a blind pattern.

| sender | rows go to | `top_live_opportunities` | `rationale` | generic row use |
|---|---|---|---|---|
| `syndicate/templates/intelligence.html` | the page + `bet_slip.js`, `watchlist.js`, `ask_bar.js` (+ base: `polling.js`, `board_rail_toggle.js`) | 1, a comment in `rehydrateAliases` | 0 | none on a row (below) |
| `scripts/build_cheat_sheets.py` | `cheat_sheets.py`, `cheat_sheet_record.py` | 0 | 0 | reads `board_contract.cards` only |
| `scripts/layer2_rail_monitor_probe.py` | `layer2_rail_monitor_run.mjs`, `layer2_rail_flag_grade.py` | 0 | 0 | named fields of `top_opportunities` rows |
| `scripts/verify_layer2_row_parity.py` | | 0 | 0 | named fields of `top_opportunities` rows |

`scripts/watch_clamp_trigger.py` walks the payload generically (and reads `fair_probability`, the
documented trap), but it sends `{"question": ...}` only. The flag never touches its payload.

The generic uses in the page, each traced:
- `bet_slip.js` `addToSlip` and `watchlist.js` `addToWatchlist` build their entries from the card's
  `data-syndicate-*` attributes, not from a row. The slip's POST to `/api/portfolio/bets` sends that
  entry.
- `submitPortfolioEvent` POSTs `/api/intelligence/portfolio-event` with five named fields.
- The three object spreads (`mergeVersionedIntelligenceResponse`, `{...lastResponseForActions, ...data}`,
  `{...fresh, row}`) copy containers or derived objects, and no reader names either key.
- `ask_bar.js` reads `rationale_summary`, from `/api/syndicate/query`, a different endpoint.
- Every `Object.keys` in the template is over `patch`, `state`, `FILTER_DEFAULTS`, `dates` or the
  alias declarations. None is over a row.

**The cheat sheets do read stripped `quote` fields** (`book_prices` 7 + 3, `fair_method` 3 + 2). Those
reads are on the rows of `/api/board/layer2-shortlist`, a different endpoint. Their board-card path
(`select_picks` / `pick_record`) reads `quote.bookmaker`, `books_quoting` and `fair_probability`, none
of them dropped. Cards never carry `rationale` (0 of 6,295 on the recorded response).

Server-side readers after the drop: `_debug_state_fields` / `_line_move_tracking_fields` read
`recommendations` and `candidates`, `_response_candidate_count` reads lengths, and the stage log
reads row counts. None reads `top_live_opportunities` or `rationale`.

The embed (`_slim_embedded_board_payload`) ends in the same `_drop_unconsumed_row_diagnostics`, so the
change reaches it too. Its only consumer is this same page (both `render_template` sites render
`intelligence.html`).

**Verdict: every sender is safe, so the change rides the EXISTING flag.** No new opt-in.

## The change

- `_DIAGNOSTIC_ROW_LISTS` gains `top_live_opportunities`. Its rows now get exactly what the other
  lists get: `trace` / `score_breakdown` removed, the unconsumed `quote` fields and the all-null
  `movement` fields removed, and the rebuildable aliases (`game_pk`, `market_key`, `selection`)
  dropped and declared.
- `_UNCONSUMED_ROW_DIAGNOSTICS` gains `rationale`. It is declared in `_dropped_row_fields`.
- The page's `rehydrateAliases` restores row aliases on `top_live_opportunities` too. A test pins the
  page's list to `_DIAGNOSTIC_ROW_LISTS`.
- `row_refs` (`response_row_refs.py`) is unchanged; only its docstring is updated.

## Before / after, on the recorded fleet response

Source: `C:\tmp\railmon\readings\20261117T014841Z\query.json`, the page's own request at 7:48 PM CST
11-16 (`slim_aliases` + `drop_row_diagnostics`), recorded by the rail monitor's probe.

Harness (this session's scratchpad, `C:\Users\TEMPAD~1\AppData\Local\Temp\claude\a933b06cd53920a7\7389580d-6ff0-4b6b-a07c-58db00a92407\scratchpad\`):
- `measure_diag_strip.py` applies the repo's `_drop_unconsumed_row_diagnostics` to the recorded
  response. The fleet's older copy already stripped it, so re-applying the old rules is a no-op;
  `before` reproduces the row-refs lane's numbers to the byte. `--simulate-change` set the two
  constants before the edit could land. The landed code, run without it, gives the identical bytes
  (25,559,058 / 4,575,384) and passes the same node check. It serialises with the provider's settings
  (json_safe, `sort_keys`, compact, ASCII) and gzips at level 1 (the fleet default).
- `rehydrate_diag_check.mjs` checks with the template's real `rehydrateAliases` under node.
- `server_path_diag.py` times the server path, old vs new, interleaved.

| | before | after | change |
|---|---|---|---|
| raw, `row_refs` ON (the page's request since `5db26434e`) | 33,144,917 | **25,559,058** | -22.9% |
| gzip-1, `row_refs` ON | 5,689,938 | **4,575,384** | -19.6% |
| raw, `row_refs` OFF | 80,281,791 | 73,750,559 | -8.1% |
| gzip-1, `row_refs` OFF | 14,383,596 | 13,628,477 | -5.2% |

The brief expected "~33 -> ~26 MB". It came in at 25.6.

Where it came from, with `row_refs` on (encoded spec bytes per list):

| list | before | after | the top patch keys before -> after |
|---|---|---|---|
| `top_live_opportunities` | 5,244,154 | 493,502 | quote 1.52 MB, rationale 1.42, score_breakdown 0.83, trace 0.47 -> advanced_readiness 65 KB, normalized_edge 65 KB |
| `top_opportunities` | 3,855,227 | 1,020,008 | rationale 2.83 MB -> advanced_readiness 135 KB, normalized_edge 135 KB |
| `board_contract.cards` | 126,469 | 126,469 | unchanged (`gate` 60 KB) |

Once stripped like the others, top_live's `quote` equals its `ranked_all` row's, so the patch no
longer carries it.

**Server time** for drop -> encode -> `_versioned_query_response` -> provider dumps -> gzip-1, Idle
priority, old and new interleaved. A parsed file shares no objects, which is the encoder's worst case.

| ms | rep 1 | rep 2 |
|---|---|---|
| `row_refs` on, old | 3,624 | 4,363 |
| `row_refs` on, new | **3,337** | **3,999** |
| `row_refs` off, old | 8,325 | 8,655 |
| `row_refs` off, new | **7,917** | **7,450** |

The drop itself costs +120-160 ms (56-80 -> 179-243 ms): it now copies 2,176 more rows and
`rationale` on 6,676. Serialising less pays that back with ~300 ms to spare. The bytes here differ
from the table above by ~300 B because this wraps the response in a fresh `_versioned_query_response`
envelope instead of the recorded one.

## Equivalence

1. **Python reference.** `decode_row_refs` of the parsed flag-on wire, re-serialised WITHOUT sorting,
   equals the flag-off wire: **True** both before and after.
2. **The page's own function under node, on the full response** (`rehydrate_diag_check.mjs`).
   - after-on rebuilt == after-off rebuilt (JSON.stringify): **true**.
   - before vs after, every row of `ranked_all` (6,295), `top_opportunities` (4,500),
     `top_live_opportunities` (2,176) and `board_contract.cards` (6,295) differs ONLY by the declared
     drops: 0 keys lost, 0 values changed and 0 keys added outside them. `rationale` is gone on 4,500 +
     2,176 rows; `trace` / `score_breakdown` on 2,176.
   - Every top_live alias comes back: 0 missing and 0 wrong of 6,528 (2,176 x 3).
   - **Negative control:** HEAD's template on the same payloads gives `ok: false`, with 6,528 top_live
     aliases missing.
3. **The rendered page:** not re-run in a browser. Neither name has a reader, and the page JSON the
   renderer receives is identical outside the declared drops (2). `board-query-row-refs` ran the
   14-section Chromium A/B for the row-refs encoding.

## Tests

`tests/test_intelligence_query_diag_strip.py`, 12 tests:
- **Reachability:**
  - the recorded slice carries the fields, so a null has a population;
  - off != on through the real route;
  - the OLD constants leave both alone through the same route;
  - top_live aliases are dropped and declared.
- **Size:** the route serves fewer bytes than with the old constants, with and without `row_refs`.
- **Nothing else lost:**
  - the page's alias list equals `_DIAGNOSTIC_ROW_LISTS`;
  - under node, the real `rehydrateAliases` on route responses (flag off, on, on + `row_refs`): every
    list differs only by the declared drops, and `row_refs` is byte-identical.
- **The survey, on every run:**
  - the set of senders is discovered by scanning `syndicate/` and `scripts/` and must equal the
    surveyed set (a new sender fails until surveyed);
  - a positive control proves the read patterns can see a read;
  - no sender or file its rows flow into reads a `_UNCONSUMED_ROW_DIAGNOSTICS` name;
  - no reader of `top_live_opportunities` reads a stripped `quote` field.

**Negative control:** the same file against the unchanged code fails 6 of 12. They are the 6 that
assert the change: off/on, the aliases, both sizes, the page-list parity, and the node check, where
top_live's `quote` / `movement` were unstripped.

Updated: `tests/test_intelligence_query_payload.py` `test_it_DECLARES_what_it_dropped` (the declared
list gains `rationale`).

**Run on the landed code** (not simulated):
- 157 passed in the 7 files that touch the payload, the template's alias rebuild or the embed:
  `test_intelligence_query_diag_strip`, `_payload`, `_row_refs`, `test_home_embed_cache`,
  `test_home_payload_duplication`, `test_intelligence_alias_slimming` and
  `test_layer2_board_ui_redesign`.
- `test_intelligence.py` + `test_ask_the_syndicate.py`: 333 passed (21 min).
- `tests/js`: 21 of 22. `board_chip_freshness_badge` fails on this Windows checkout's CRLF copy of
  the template (the 11-17 lead from `board-query-row-refs`) and passes on an LF copy of the edited
  template.

## State

- Code: ON MAIN `25fc2e4f0`. `syndicate/blueprints/intelligence.py`'s edit waited ~1 h on a claim-parser
  quirk. Lane `paper-page-retirement` declared its section with commas inside the parentheses, and
  `lane_claims` splits Files on commas first, so its section read as a whole-file claim. The two
  scopes were disjoint. Its owner changed the commas to " + " (`7975eb4d6`). A lead records the
  parser.
- **Load: the user's decision.** It takes an ff of `~/Syndicate` from `5db26434e` (loaded 18:58:45Z)
  to this SHA, then `local_production.py reload-web`. Workers are unaffected, with no env change.
  **Betting change: no**: it changes what web serialises, not what is bet.
  - That ff carries everything on main after `5db26434e`. List the ride-alongs at load time
    (`git log --oneline 5db26434e..25fc2e4f0` on the fleet, and diff `vendor/`, per learnings).
  - A tab that has not reloaded keeps working: an old page does not restore top_live's aliases, and
    it reads neither name.
- **Read after a load:**
  - the served `/api/intelligence/query` Content-Length, ~5.7 -> ~4.6 MB gzipped with `row_refs`;
  - `_dropped_row_fields` lists `rationale`;
  - top_live rows carry no `trace`.

## Loaded `[2026-11-17 21:56:24Z (3:56 PM CST), lane board-query-diag-strip-load]`

- **The load.** User "Load it", then the option "Carry them (Recommended)" for the ride-alongs.
  - Lane `render-config-retirement` first restarted the fleet onto `91d865fd5` (21:53:00Z), which loaded the ride-alongs.
  - This lane then ran `git merge --ff-only 25fc2e4f0` at 21:56:24Z and `reload-web` (failures 0, web workers 30025/30026). The workers were not restarted; their code is identical to `91d865fd5`.
- **Readings** (the page's body plus `row_refs`, `C:\tmp\rowrefs827\read_query.py`):

  | | before (21:55:37Z, `91d865fd5`) | after (21:56:36Z, `25fc2e4f0`) |
  |---|---|---|
  | gzipped | 4,429,180 B | **3,962,869 B (89.5%)** |
  | uncompressed | 24,427,841 B | 21,723,439 B |
  | time | 11.8 s | 8.9 s |
  | `top_opportunities` rows carrying `rationale` | 4,500 of 4,500 | **0 of 4,500** |
  | `top_live_opportunities` rows carrying trace / score_breakdown / rationale | 4 / 4 / 4 of 4 | **0 / 0 / 0 of 7** |

- **Why the cut is 10.5% here, against 19.6% on the recorded 11-16 response:**
  - top_live had 6,528 rows on that response and had 4-7 at load time, so tonight the cut is mostly `rationale`;
  - it grows with the number of live rows.
- `_dropped_row_fields` reads `["trace", "score_breakdown", "rationale"]` (read ~22:01Z).
- `QUERY_STAGE_MS` at 21:56:43Z: `refs` true, `row_refs` 241.9 ms.
- **The fleet's `/intelligence` page, headless:**
  - 0 page errors;
  - "Showing 1,347 of 2,238 plays", 7 live, rail drawn;
  - the 18 console errors are the known `cdn.nba.com` logo failures.
- Record: deploys.md 21:56:24Z, BC-038 (no).
