# NCAAF cards build cost on web -- where the memory and time go (lane `ncaaf-cards-build-cost`)

Session 9ef6a9cf, 2026-11-27 ~8:40-9:30 PM CST (2026-11-28 02:40-03:30Z). Started from session
`local_671bbd22` (surface-consistency oversight), which measured the symptom:
`build_smartsim_cards_page_context(default_week())` took peak RSS 286 -> 1,100 MB and 15-24 s.
Display only: no betting path reads these pages, and the fix leaves every output byte-identical.

Probes and kit: `C:\tmp\ncc_9ef6\` (run with `fleetpy_kv.sh <script> [tree]`, which exports the web role's
path and store keys only and prints no values; everything at `nice -n 19`).

## 1. Where it goes

All readings use fleet data, week 13 (69 games) and an ext4 copy of the fleet checkout's code at
`bcbb5465f`, with `data/` symlinked to the fleet checkout's `data/` (`/tmp/ncc_9ef6/base`). A first
profile that imported the code from `/mnt/c` overstated the box stage: `lstat` on 9p cost 3.1 s. Each
stage's OWN peak is measured by resetting VmHWM (`/proc/self/clear_refs` 5) before it.

| stage | cold | warm | own peak |
|---|---|---|---|
| `oddsapi_lines.load_week_line_index` | 2.88 s | 2.48 s | **+984 / +939 MB** |
| 69 card contracts | 1.42 s | 0.09 s | +106 MB cold |
| `_attach_live_state` (incl. box sections) | 1.13 s | 0.17 s | +138 MB cold |
| `apply_game_board_contract` | ~1.6 s | ~0.07 s | -- |
| **whole build** | **5.17 s** | **3.06 s** | **+961 / +866 MB** |

**Mechanism.** `load_week_line_index` read every row of the week's NCAAF quote shards into one Python
list, then collapsed it to the latest quote per (home, away, market, selection, book). On 11-27 + 11-28
that is 174 MB, 382,883 JSON lines, 10,874 distinct keys and 66 priced games. It ran on EVERY build, cold
or warm: nothing cached it. In the served route (`/ncaaf/api/cards` = build + board attach +
`jsonify`), the same call sits under `/ncaaf/picks`, the season betting card, game detail, live lens and
`/ncaaf/api/market-board`, through `_smartsim2_standalone_rows`.

**Why web recycles.** glibc keeps the freed ~1 GB as anon RSS. Web's recycler restarts a worker over
~623-638 MB anon. Recycles were 11 / 21 / 39 / 41 / 31 per UTC hour from 22Z to 02Z. Over the 4 h to
03:09Z, 49 of 104 (47%) fired while an NCAAF build was in flight or within 30 s after one. Builds cover
about 33% of the time by chance. A 120 s window catches 91%, but the poller fires every 120 s, so that
window covers nearly all the time and proves nothing. The recycle `anon_mb` median was 958 (max 1,617).
Example: 03:06:25Z, `anon_mb 1143.7`, `limit_mb 623.1`, 5 requests.

**The 2-minute client** (`Python-urllib/3.12`, 97 of the 104 NCAAF build requests in those 4 h) is
`C:\tmp\ncaaf859to\poll_fleet.py` (PID 3848, started 11-27 5:56:20 PM CST). It is todo #859's read-only
sampler of NCAAF live timeouts, `GET /ncaaf/api/cards` every 120 s until 2026-11-28T06:30Z (12:30 AM CST),
and then it exits by itself. It was left alone.

## 2. The fix (`syndicate/features/ncaaf/oddsapi_lines.py`)

1. **Collapse as you read.** A shard never exists as a list. Each key keeps only `(line, price)`, the
   only two row fields the index reads.
2. **Append-aware per-process cache.** A plain shard is append-only (`append_book_quotes` opens it "a";
   the sanitize pass swaps it in by `os.replace`, a new inode). The collapse of the bytes already read is
   kept per path (16 shards, LRU), and a later read parses only the appended bytes. Another inode, a
   shorter file, or different bytes in the first 64 KB or the 64 KB before the offset all trigger a full
   re-read. A `.gz` is reused while (inode, size, mtime_ns) hold.
3. **`resolve_team` / `_selection_side` memoised per call:** 21,748 calls for one week's index.
4. One log line per read, `[ncaaf_odds] LINE_INDEX_READ ... full_reads= parsed_bytes= reused_bytes= keys=`,
   so the path that ran can be read back from `web.log`.

**What "identical" covers**, against the old text-mode reader, one case at a time:
- Universal newlines: "\r\n" and a lone "\r" both end a line.
- Strict UTF-8: an undecodable byte anywhere drops the whole date. That path caches nothing, so the
  date stays dropped while the bytes are there.
- A last line with no newline is parsed but never cached.
- Last quote wins per key, and each key keeps its first-seen position, across dates too.
- Empty dates, absent dates and duplicate dates behave as before.

`_iter_quote_rows` (oddsapi_lines' own, with no other caller) is deleted. `build_line_index(rows)` keeps
its signature and output.

## 3. A/B on the same inputs

**Line index, frozen copies of the 11-27 / 11-28 shards** (`ab_line_index.py`):
- Old reader: 2.54 s / 2.29 s, **+989 / +924 MB** own peak.
- New, cold: **1.50 s, +1 MB**. New, warm: **0.038 s, +0 MB**.
- Identical: the items, their order and the JSON.
- Append path: the shards started at 55% (cut mid-line) and were grown in 9 uneven chunks. The new
  reader took **0.05-0.27 s** per read and the old one 1.6-2.9 s. **Identical at all 10 steps.** The grown
  files ended equal to the frozen ones.
- The cache keeps **5.8 MB** for 2 shards / 10,874 keys.

**Served body** (`ab_payload.py`):
- Setup: one process, frozen shards, the live-state index read once and replayed. The body is serialized
  the way web's `_NaNSafeJSONProvider` does, and builds alternate OLD, NEW, OLD, NEW, NEW.
- **Every body is 1,546,902 B, sha256 `a5b35072ca842374`. BYTE_IDENTICAL**, and OLD 1 == OLD 3, so
  nothing else drifted.
- Timings, served route including the board attach:

  | build | time | own peak |
  |---|---|---|
  | OLD, first in process | 12.82 s | +992 MB |
  | OLD, warm | 3.33 s | +888 MB |
  | NEW, cold line cache | 2.59 s | ~0 MB |
  | NEW, warm | **0.46 / 0.47 s** | **+0 MB** |

**Fresh process, patched tree, live shards** (`stage_peaks.py /tmp/ncc_9ef6/patched`), as a just-recycled
worker sees it:
- Cold: the line read is 2.45 s and +7 MB. The whole cold build peaks at **362 MB RSS** (was 1,101-1,229).
- Warm: the build takes **0.45 s** with +0 MB (was 3.06 s with +866 MB).

## 4. Tests

- `tests/test_ncaaf_oddsapi_line_index_stream.py` (NEW, 14 tests). Each compares the new reader with a
  verbatim copy of the old one. Cases: a mixed two-date week (BOM, blank, non-JSON, non-object, glued,
  CRLF, lone CR, unterminated last line, other segments and kinds, unresolved team, duplicate and absent
  dates); appends cut mid-line, where only the first read is full (off != on, `reused_bytes > 0`); a torn
  UTF-8 tail; an undecodable complete line; `os.replace`; an in-place rewrite; a shorter file; `.gz` reuse
  and replacement; a truncated `.gz`; the LRU limit; a cached collapse never mutated; peak memory under
  1/10 of the old reader's (tracemalloc).
- With the git registry CSV provided in the worktree, the existing `test_ncaaf_oddsapi_game_lines.py`,
  `test_ncaaf_cards_2026_shift.py`, `test_ncaaf_market_board.py` and `test_ncaaf_game_projections.py`
  give **107 passed, 2 skipped with the old module and with the new one**. Without the CSV, the same 32
  fail under both (the registry is absent from a worktree).

## 5. Side effects of this work

- The first three probe processes (`stage_profile.py`, the first `stage_peaks.py`) ran the real build,
  which appends one line per build to the fleet's `ncaaf_source/data/smartsim2_trial_monitoring.jsonl`
  (`record_trial_page_view`). **5 lines** were appended (route `/ncaaf/cards`, week 13), at 02:40:42,
  02:40:54, 02:42:44, 02:43:09 and 02:43:41Z, and they were left in place. Every later probe stubs that
  call. The sibling session's `cost_1g.py` appends the same way. Separate from these: bursts of 4 lines
  within ~20 s recur at 02:00, 02:11, 02:28, 02:49 and 03:01Z. They predate this session's probes and come
  from some other caller, not identified here.
- All other probe output went to `/tmp/ncc_9ef6` in WSL and `C:\tmp\ncc_9ef6`. The shard copies there
  (175 MB) can be deleted.

## 6. Not addressed (cold-only, measured, left for a decision)

- The cold card contracts (1.4 s, +106-176 MB) and the cold live state + box sections (1.1-1.3 s,
  +138 MB) fill per-process caches.
- `apply_game_board_contract` reads ~210 MB of `odds_events` JSONL cold (~1.6 s, cached after).
- The step-1g board attach is ~3.7 s cold with a 60 s cache (lane `surface-consistency-oversight`).
  The #859 poller asks every 120 s, so that attach is cold on most polls.

## 7. Deploy plan (web only; the user's call; betting change: no)

Runtime code: `syndicate/features/ncaaf/oddsapi_lines.py` only, plus a test.

1. Land the code commit on main (`session_worktree.py land --lane ncaaf-cards-build-cost`). Note its
   SHA from the push output.
2. Ride-along check: `git log --oneline bcbb5465f..<sha>` and a code-dir diff (`syndicate scripts
   pipeline engines vendor`). At 03:10Z the only commits beyond the fleet's `bcbb5465f` were 9 ledger
   commits with no code. Re-read this at deploy time.
3. `python scripts/deploy_claim.py acquire --service web --holder ncaaf-cards-build-cost`. Gate on its
   exit code.
4. Baseline within 15 min, from `web.log` (`C:\tmp\ncc_9ef6\web_baseline.sh`,
   `recycle_attrib.py 1 30`):
   - `/ncaaf/api/cards` median ms over the last hour (02Z: n=30, 12,125);
   - `web_recycles_per_hour` (02Z: 31);
   - `LINE_INDEX_READ` lines = 0.
5. Preflight, run from a worktree at `origin/main`:
   `python scripts/deploy_preflight.py --service web --holder ncaaf-cards-build-cost --target-commit <sha>
   --betting-change no --expect line_index_read_lines=>0 --expect line_index_full_reads_after_first=0
   --expect ncaaf_api_cards_median_ms=<=6000 --expect web_recycles_per_hour=<=20
   --baseline line_index_read_lines=0 --baseline ncaaf_api_cards_median_ms=<reading>
   --baseline web_recycles_per_hour=<reading> --baseline-read-at <UTC>`. It must return CLEAR.
6. On the fleet: `git -C ~/Syndicate merge --ff-only <sha>`, then
   `python3 scripts/local_production.py reload-web`. Expect
   `RELOAD_WEB {"failures": 0, "state": "done"}`.
7. Verify by reading `web.log`:
   - `LINE_INDEX_READ` appears, and each worker's second and later reads show `full_reads=0` with small
     `parsed_bytes`;
   - `/ncaaf/api/cards` median, which is predicted at <= 6 s and not ~0.5 s, because the step-1g attach
     (~3.7 s cold, 60 s cache) still runs on most of the poller's 120 s requests;
   - recycles per hour, and recycle `anon_mb`;
   - UNHANDLED_500, Traceback and WORKER TIMEOUT all 0.

   The #859 poller stops at 06:30Z. A load before then is measured under the same client load as the
   baseline.
8. Record the result in `.syndicate/deploys.md` with `- betting change: no`, then
   `deploy_claim.py release --service web`.

**Revert:** `git revert <sha>` on main, then ff + `reload-web`. Nothing on disk changes: the cache is
per process.
## 8. Loaded on web 2026-11-28 06:01:23Z (12:01:23 AM CST), `4bfaa108a`

The full entry is in deploys.md `2026-11-28 06:01:23Z`. The measurement used the same 5 GETs of `/ncaaf/api/cards`
before and after, 130 s apart (`C:\tmp\ncc_9ef6\deploy_probe.py`).

| | old code (05:50-06:00Z) | new code (06:01-06:13Z) |
|---|---|---|
| request ms | 9,245 / 9,067 / 8,272 / 13,769 / 11,995 | 9,096 cold / **4,960** warm / 9,777 cold / 9,928 cold / **5,664** warm |
| fresh worker VmHWM after its first build | 151 -> 1,193 MB | 151 -> **512 MB** (twice) |
| hard recycle mid-request | 2 of 5 (1,348 and 1,130 MB anon) | **0 of 5** |
| `LINE_INDEX_READ` | none | 5; full reads only on a worker's first build; second reads parsed 16 KB and 326 KB |

- **Missed:** the 6 s median and the 500 MB peak. 3 of 5 requests met a worker's first NCAAF build, because web
  recycled both workers at 06:04-06:05Z for memory from other routes. A cold build is as slow as before (~9-10 s):
  - its line read is a full read (~2.4 s), the same cost as the old one, and
  - the card contracts, live state, board contract and step-1g attach caches are all cold-only and per process.
- **Web recycles without NCAAF.** It recycled 21 times in the hour to 05:49Z, with 0 NCAAF builds; the #859 poller
  had stopped at ~04:12Z. Worker 1348200 reached 785 MB anon and was hard-recycled at 06:05:18Z without serving one
  NCAAF request. Which routes drive this was not identified: todo #867 (a).
- **Log:** 06:01:20-06:13:49Z had UNHANDLED_500 0, Traceback 0, WORKER TIMEOUT 0, and all 5 requests returned 200.
- **Side effect:** the 10 probe GETs appended 10 lines to `smartsim2_trial_monitoring.jsonl` (05:50-06:13Z), left in
  place. Add the 5 from section 5 for 15 in all.
