# refresh-worker — thread map and entry-point map

> **Scope: deliberately narrow.** This is not an architecture document —
> `worker_architecture.md` and `runtime_execution_model.md` already are, and
> `end_to_end_context.md` covers the platform. This answers two questions those
> do not, which between them caused **six wrong attributions in one session**
> (2026-08-16, lane `refresh-worker-oom-recurrence`):
>
> 1. **What runs concurrently inside the worker process?**
> 2. **For a hot path, which function must every caller pass through?**
>
> Written 2026-08-16. Every env value below was read from the LIVE service
> (`srv-d91dpertqb8s73co8ls0`, 105 keys across 2 pages), not from `render.yaml`.
> **Re-read before trusting: loop ownership is an env flag that moves with no
> code diff.**

---

## 1. Thread map — what is running at once

The refresh-worker is **one process (pid 39) with several daemon threads**, plus
short-lived child processes for sims. This is the fact that matters most, and it
is why per-process globals cannot attribute anything.

| thread / loop | started by | env gate | live value |
|---|---|---|---|
| main worker loop | `scripts/run_refresh_worker.py` | — | always |
| intelligence-state loop (`syndicate-intelligence-state-loop`) | `start_intelligence_state_background_loop()` (`run_refresh_worker.py:3498`) | `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` | **`true`** |
| live-lens loop | `start_live_lens_loop()` (`run_refresh_worker.py:3533`) | `SYNDICATE_ENABLE_LIVE_LENS_LOOP` | **`true`** |
| live-lens publish sampler | `live_lens_loop.py:814` | (inside the loop) | with the loop |
| live-refresh loop | `live_refresh_loop.py:5418` | `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP` | **`false`** |
| memory watchdog sampler | `memory_observability.py:1594` | `memory_watchdog_enabled()` — **default ON**, kill-switch only | on |
| watchdog census threads (heap / untracked / pymalloc / smaps) | `memory_observability.py:908, 1157, 1507` | anon thresholds | on |
| MLB sim children | `run_refresh_worker.py` sim trigger | `SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER` | **`true`** |
| settlement autorun | gated | `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN` | **`false`** |

### The trap this map exists to prevent

**`_WATCHDOG_STATE` (`memory_observability.py:774`) is a module-level dict with
no thread-locals.** `_note_stage_seen` writes `last_stage` from whichever thread
last emitted a stage marker. With the loops above running concurrently,
`MEMORY_WATCHDOG`'s `last_stage` names **the last thread to speak, not the
thread allocating**.

An entire evening's attribution was built on reading `last_stage` as if it were
thread-scoped. The refutation took one covered log window: during the excursion
it blamed, `OVERVIEW_SPORT_BEGIN`/`END` did not appear at all — the loop it
pointed to was not running.

**Rule: before attributing anything to an instrument field, ask what its SCOPE
is.** A process-global read as thread-local is not a weak signal; it is a wrong
one that looks precise. If you need per-thread attribution, use
`faulthandler.dump_traceback(all_threads=True)` — already used in this repo at
`scripts/refresh_odds_sources.py:447`. **Do NOT use `tracemalloc`**: ruled out in
`state.md:556`, it starved the sampler and made kills more frequent.

### Cost rule for anything added to a loop

`learnings.md` — worker periodic work is never free; `#241` put the worker in a
restart loop. Heavy work must run **off the sampler thread** (see the comments at
`memory_observability.py:877` and `:1491`): a blocked sampler is
indistinguishable from a calm system.

---

## 2. Entry-point map — choke points vs wrappers

The pattern that produced two wasted instruments: **a function with siblings that
reach the same work by another route measures your route, not the work.** In both
cases the function chosen had "wrapper" in its own docstring.

### Evaluation ledger reads

```
_stream_chunked_ledger_records   intelligence_evaluation.py:625   <-- CHOKE POINT
    emits LEDGER_CHUNKS_ACCEPTED / SKIP_OVERSIZED_LEDGER_CHUNK
    no date scoping: manifest chunk list, else glob("*.jsonl")
    |
    +-- _load_chunked_ledger_records  :615   materialising wrapper -- ZERO CALLERS (dead)
    +-- _stream_record_payloads       :1406
            +-- _iter_record_payloads :1298   MATERIALISING wrapper ("holds every
            |                                  record of every accepted chunk at once")
            |     +-- recommendation_engine._load_records_from_ledger
            |           defaults to DEFAULT_EVALUATION_LEDGER -- a FLAT path
            |           that does not exist in production (records=0)
            +-- _ledger_index                        :737
            +-- compute_metrics                      :1580
            +-- build_evaluation_history_summary     :1638
            +-- build_recommendation_performance_analytics :2070
            +-- build_segmented_reliability_profile  :2423
            +-- build_accuracy_summary               :2480
```

**Six of the eight callers use `_latest_by_recommendation_id(_stream_record_payloads(...))`
— a single-pass reduce that never materialises the full list.** Only
`_iter_record_payloads` materialises, and in production it is reached with a flat
path that does not exist.

**Measured:** the 830MB chunked loads (`count=8 bytes=830,832,574 records=22,078`)
do **not** pass through `_iter_record_payloads`. Instrumenting it showed
`records=0` while `LEDGER_CHUNKS_ACCEPTED` fired three times in the same window.
**If you want to see every ledger read, instrument
`_stream_chunked_ledger_records`.** It is the only placement that cannot be
routed around, because it is where the accepted/skipped lines come from.

**Reading its skip lines:** it emits skips in **sorted date order**, so
`08-05/06/07` is a scan's *opening* and `08-14/08-16` its *close*. A log window
that starts mid-scan will make one scan look like two callers. (It did. Widen the
window until the query returns **under** the 100-row cap.)

### Board / cards reads

```
apply_game_board_contract   game_board_contract.py:833   <-- CHOKE POINT (all 8 sports)
    emits board_contract_begin / games_normalized / end
    called by: nba:2562  nhl:1052  nfl:505  soccer:697
               wnba:3533 ncaab:181 ncaaf   mlb:5773
```

**`_log_cards_context_memory` (`mlb/cards.py:182`) exists for MLB and nowhere
else.** The other seven sports hydrate with no stage markers of their own, which
is why `intelligence.py:2604` can conclude "MLB is in a class of its own" and
size two production floors on measurements only MLB is capable of producing. **An
uninstrumented sport reads cheap the way an unplugged meter reads zero.**

For non-MLB sports the board contract is the LAST statement of the cards builder
(e.g. `nfl/cards.py:505` is `return apply_game_board_contract(...)`), so
`board_contract_end` is the final marker before the stack unwinds.

### Overview hydration

```
build_intelligence_overview loop   intelligence.py:2793-2835
    guard   _overview_headroom_exhausted   (BETWEEN sports only)
    print   OVERVIEW_SPORT_BEGIN            <-- a bare print; does NOT set last_stage
    call    _build_sport_overview           home.py:6733
    call    _emit(sport_row)
    marker  overview_sport_end
```

The guard is checked **between** sports, so an excursion **inside** one sport is
invisible to it by construction — `intelligence.py:2530` says exactly this about
the caller's breaker, and the per-sport breaker added to fix that has the same
shape one level down.

Floors: `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` 3000MB (expensive) vs
`_OVERVIEW_MIN_SAFE_HEADROOM_STREAMED_BYTES` 1500MB for seven "cheap" sports
(`:2621-2624`). Measured excursion-start headroom is **2231–2953MB** — below 3000
and above 1500 in all 7 observed cases, which is precisely why
`OVERVIEW_STOPPED_FOR_MEMORY` never fires.

---

## 3. Instruments currently live on refresh-worker

| marker | where | fires |
|---|---|---|
| `board_contract_end` | `game_board_contract.py` | every board build, all 8 sports |
| `SMAPS_ANON reason=watchdog_PEAK_anon_*` | `memory_observability.py` | anon ≥2600MB, ≤3× per process |
| `PAYLOAD_LOAD` | `intelligence_evaluation.py:1298` | every `_iter_record_payloads` call |
| `LEDGER_CHUNKS_ACCEPTED` | `intelligence_evaluation.py:724` | every chunked scan (pre-existing) |
| `SMAPS_SKIPPED_CAPPED` | `memory_observability.py` | a capped-out SMAPS says so |

---

## 4. How to read this worker's logs without inventing findings

- **Kills are EVENTS, not log lines.** Use
  `/v1/services/<id>/events` (`scripts/render_events.py`, which pages).
- **The logs API returns an arbitrary slice.** `learnings.md:2917` forbids rates
  and counts from it. A query returning exactly `limit` rows is **truncated** —
  widen or narrow until it comes back under the cap, then read ordering.
- **Env vars paginate.** `limit=100` is the cap and page 1 looks complete; the
  service has **105** keys.
- **After any deploy, memory resets to ~16%.** It will look healthy for minutes
  regardless. Nothing is proven until the next excursion.
- **Always pair a null with a control.** `PAYLOAD_LOAD records=0` means nothing
  until you know whether `LEDGER_CHUNKS_ACCEPTED` fired in the same window. Both
  false conclusions this session came from a zero read without its denominator.
