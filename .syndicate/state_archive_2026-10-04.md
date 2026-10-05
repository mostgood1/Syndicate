# state.md archive — 2026-10-04

Moved verbatim out of `state_worker.md`'s **[web-oom-leak]** section to bring that
part back under its 250,000-byte cap and `STATE_TOTAL` under 1,100,000. Archives are
excluded from that sum; counted files are not, which is why moving bytes between two
counted files could not help. **Nothing here is deleted and nothing is summarised.**
The live section keeps every retraction it needs and points here.

## What moved, and why this boundary

The 37 blocks up to and including **UPDATE 36** — the memory investigation:
instrument, anon mappings, glibc arenas, pymalloc, the diagnostic ring. It is
superseded as a LINE OF INQUIRY by `UPDATE 37`, *"WEB IS NOT DYING OF MEMORY. It is
dying of LATENCY"*, which stays in the live section.

**THE CUT ORPHANS NO RETRACTION, and that was measured rather than assumed.** Every
correction and retraction in this range names a referent INSIDE this range — 12→10,
21→20, 25→24, 30→28, 34→33 — so each travels with what it corrects. Checked in both
directions before cutting: **zero** blocks kept at UPDATE 37+ reference an archived
UPDATE number, and **zero** blocks here reference a kept one. `UPDATE 43`, which
retracts a general claim, names `UPDATE 37` and restates what it established, so it
stands alone in the live section.

Kept live in `state_worker.md`: UPDATE 37-44, plus the un-numbered
`UPDATE 2026-09-09 22:2x CT` block — which is the NEWEST of all 46 despite sitting
second in the file, so it is kept on its DATE, not its position.

Two numbering oddities in the chain, recorded so a reader is not confused: the first
block is un-numbered (`UPDATE —`, 2026-09-04) and there are TWO blocks numbered
`UPDATE 13`. Both are archived here, verbatim, unrenumbered.

---

### `[web-oom-leak]` UPDATE — the instrument is fixed and the growth has a SUSPECT, 2026-09-04T00:4xZ `[session b2b5b45b]`

**Supersedes the "needs an INSTRUMENT change" line in the entry above — that
change shipped (`442f82fe`) and is verified REACHED**, not merely deployed:
emissions carry `attribution_basis = process_anon_smaps_rollup` with a non-null
`process_anon_mb_now` and `unreadable = 0`. Attribution now differences THIS
PROCESS's anon (`/proc/self/smaps_rollup`), so its scope matches the per-worker
`inflight` guarantee.

**THE PREVIOUS CULPRIT WAS AN ARTEFACT.** `/api/ops/artifacts/publish` read
**211 MB** container-scoped and reads **1.15 MB across 81 solo requests**
per-process. A publish spawns a merge CHILD; the container-scoped instrument
charged the child to the parent's request. **Any earlier conclusion pointing at
publish came from measuring the wrong scope.**

**THE SUSPECT: `/api/intelligence/query`, ~82 MB PER CALL** — 408.0 MB over 5
calls, replicated on both workers. Infrequent and very expensive; nothing else is
within an order of magnitude (publish moves tens of MB across HUNDREDS of calls).
It does NOT recompute — `read_combined_intelligence_response` only reads what the
background loop already built — it MATERIALISES AND HYDRATES a large precomputed
payload, and CPython does not return freed arenas. `intelligence.py:1600` notes
slimming that payload would change an API contract, so the fix is not free.

**THE RANKING IS TRUSTWORTHY; THE SHARE IS NOT.** Attributed 408 MB against
342 MB of actual process growth. One contamination source remains and it is
named: `syndicate/app.py` runs the live-refresh and intelligence-state loops IN
THE SAME PROCESS, and `inflight` guarantees no other REQUEST, not no other
THREAD. Of three sources — cross-worker, merge children, same-process threads —
two are gone.
### `[web-oom-leak]` UPDATE 2 — the payload is down ~74% and the instrument is honest, 2026-09-04T02:3xZ `[session b2b5b45b]`

* **Per-request attribution now measures THIS PROCESS** (`/proc/self/smaps_rollup`),
  so its scope matches the per-worker `inflight` guarantee (`442f82fe`, verified
  REACHED). **Supersedes every earlier route ranking**: `/api/ops/artifacts/publish`
  read 211 MB container-scoped and **1.15 MB across 81 solo requests** per-process,
  because a publish spawns a merge CHILD that the old scope charged to the parent.
* **The largest per-request allocator is `/api/intelligence/query`, ~82 MB/call**
  (408 MB over 5 calls, both workers). It does NOT recompute; it materialises and
  hydrates a large precomputed payload.
* **That payload is now ~74% smaller.** The self-nested mirror is gone (50.0%,
  `53a1052b`) and the alias duplication is opt-in-slimmed (47.9% on a same-slate
  live A/B, `b3966bf1`): `recommendations` -> `top_opportunities`, `boardContract`
  -> `board_contract`, `by_sport` regrouped from `ranked_all`, described in
  `_response_aliases` and rebuilt client-side.
* **OPT-IN: a caller that does not send `slim_aliases` is byte-for-byte
  unaffected.** Verified live; a test exists whose only job is to fail if that
  ever changes.
* **STILL OPEN:** one contamination source remains and it is named —
  `syndicate/app.py` runs the live-refresh and intelligence-state loops IN THE
  SAME PROCESS, and `inflight` guarantees no other REQUEST, not no other THREAD.
  So the route RANKING is trustworthy and the exact SHARE is not.
* **NOT re-measured:** whether the ~74% cut moves the ~500 MB/h growth rate. That
  needs a fresh uninterrupted window.
### `[web-oom-leak]` UPDATE 3 — the rate is re-measured: +173 MB/h, down 66%, 2026-09-04T03:2xZ `[session b2b5b45b]`

**Supersedes the "NOT re-measured" line in UPDATE 2.** Fitted on 81 merge-child-free
plateau samples (25.5-62.7 min uptime) on web `b3966bf1`: **+173 MB/h, R^2 0.90**,
against the pre-cut **+503 MB/h, R^2 0.75, n=32**. Time to the 2,048 MB limit goes
**2.0 h -> 5.7 h**, i.e. past the 2.45-3.13 h uptimes at which this service was
being OOM-killed.

**Confounded in two ways, both registered before the measurement:** different time
of day (02:40Z vs 22:30Z), and the alias half of the payload cut is OPT-IN so it
only applies when a browser drives the page — meaning **-66% is most plausibly the
self-mirror half alone**. Consistent with the fix; not proof of it.
### `[web-oom-leak]` UPDATE 4 — rate down 66%, four mechanisms ruled out, 2026-09-04T14:5xZ `[session b2b5b45b]`

* **Growth rate re-measured after the payload cut: `+503 -> +173 MB/h`** (fitted,
  R^2 0.90, n=81 merge-child-free plateau samples). Time to the 2,048 MB limit
  **2.0 h -> 5.7 h**, past the 2.45-3.13 h uptimes at which web was being killed.
  Confounded by time of day, and the alias half of the cut is opt-in — so this is
  consistent with the fix, not proof of it.
* **The attributed SHARE is still not recoverable, and four candidates are now
  eliminated by measurement:** cross-worker cgroup scope (CONFIRMED, fixed by
  per-process anon); background loops (FALSIFIED — neither runs on web, and the
  gate built for them is INERT); GC timing (EXCLUDED — the one gen-2-overlapping
  request was POSITIVE while the non-overlapping group went negative);
  `LAST_RESULT` reassignment (EXCLUDED — 0.0 MB both halves).
* **THE CONSTRAINT THAT KILLS PER-STATEMENT PROBES:** CPython returns freed
  objects to pymalloc's ARENAS, not to the OS. An in-Python free cannot reduce
  `Anonymous:`. A negative anon delta therefore requires ARENA RELEASE — an
  emergent property of allocator free-list state, attributable to no statement,
  request or thread.
* **NEXT INSTRUMENT, if the symptom returns:** `malloc_info` / pymalloc arena
  counts around the negative windows, not another attribution probe.
  `memory_observability` already carries `parse_smaps` and `#435`'s arena-vs-anon
  comparison. The question is "when does an arena empty".
* The symptom is INTERMITTENT — zero negative routes in the last two windows.
  Nothing is confirmed; four things are ruled out.
### `[web-oom-leak]` UPDATE 5 — **POSITIVELY IDENTIFIED: 8-64MB anon mappings**, 2026-09-04T18:09Z `[session b2b5b45b]`

* **The growth is in LARGE ANONYMOUS MAPPINGS (8-64MB regions).** Measured on
  `76c0e174` via `smaps_trend` split by pid, gate pre-registered before the data:
  pid 79 `+148.70 MB / 37.3 min` with **80.5% in `8-64MB`**; pid 78
  `+54.10 MB / 34.6 min` with **85.4%** there. `UNNAMED` `0.00` on both — the
  breakdown sums to its own total. `<64KB` and `64KB-1MB` unchanged to the
  decimal across all 12 readings.
* **This is the first POSITIVE finding in `#632`; the previous five were
  exclusions.** It also explains WHY they were: pymalloc arenas cover ~40% of
  worker RSS and glibc `malloc_info` reached 13.9% coverage in `#435`. **Both are
  structurally blind to an allocation over 512 bytes**, so their flat readings
  were never evidence of a flat process.
* **CORRECTS an intermediate claim made the same session.** With only the size
  buckets recorded, the residual computed by subtraction read as 65-70%
  "non-mmap" and I proposed glibc's main arena. Recording `by_kind_mb` retired
  that: heap is **7.4% / 14.6%**, a minority term.
* **NOT ESTABLISHED:** what allocates those regions; and the rates
  (`+239.4` vs `+93.7 MB/h`) are EARLY-LIFE and not comparable to the `+173 MB/h`
  plateau figure. **The two workers differ 2.6x on one container in one window,
  unexplained.**
* **NEXT MEASUREMENT:** does the climb track which worker serves
  `/api/intelligence/query`? That discriminates the payload story from
  everything else, and it is answerable with the instrument already deployed.
### `[web-oom-leak]` UPDATE 6 — **query correlation is NULL, and `/api/intelligence/query` was never called**, 2026-09-04T18:2xZ `[session b2b5b45b]`

* **NO ROUTE'S CALL RATE EXPLAINS THE 8-64MB GROWTH.** Per-worker, per-interval,
  every quantity as a PER-MINUTE RATE (n=13 intervals, 2 workers): after
  dropping one high-leverage point every `|r| < 0.45`, and Pearson disagrees
  with Spearman in SIGN on three of five routes.
* **The `/api/intelligence/query` payload hypothesis is FALSIFIED for this
  window — the route received ZERO calls on either worker** while anon climbed
  +54.1 and +148.7 MB. The growth does not need an intelligence query to happen.
* **Two correlations that looked real and were not:**
  - Unnormalised, `/healthz` ranked TOP at `r=+0.682` — a route with
    `max_mb 0.00`. Differencing over UNEQUAL intervals let duration drive both
    sides. `/api/ops/artifacts/export` fell from `+0.348` to **`+0.037`** once
    normalised; the export hypothesis died there.
  - `/api/ops/artifacts/publish` at `r=-0.882` collapsed to **`-0.271`** when one
    3.1-minute interval was dropped. That was a claim about one point.
* **NEW AND POSITIVE: the 8-64MB memory IS RETURNED TO THE OS.** One interval
  (pid 79, 18:09:52->18:13:00) fell **-43.4 MB**. Large mappings are `munmap`ped
  back, unlike pymalloc arenas. **So this is not monotonic retention** — it is
  churn with a high-water mark, which is a different defect and admits different
  fixes (bounding concurrent peak, not finding a "leak").
* **INSTRUMENT LIMIT, stated so the null is read correctly:** emissions fire
  every 200 solo requests, giving 3-9 minute intervals and n=13. That is coarse
  enough to hide a real per-call effect. **This null bounds the effect size; it
  does not prove independence.**
### `[web-oom-leak]` UPDATE 7 — per-request attribution **FAILED ITS SHARE CHECK**, 2026-09-04T19:3xZ `[session b2b5b45b]`

* **A per-request smaps sampler was built, deployed (`5314e85b`, live 19:11:55Z)
  and its verdict WITHDRAWN.** It reported `/api/ops/artifacts/export` at
  **+145.10 of +145.10 MB** (100%); the share check against each process's own
  8-64MB climb gave **pid 79 = 0.0%** (process +90.30 MB, sampled requests
  +0.00) and **pid 80 = 175.0%** (process +23.20, attributed +40.60).
* **`sum(sampled)/sum(sampled)` is 100% by construction.** The denominator was a
  set of routes I chose, not the process's climb. Failing in BOTH directions
  rules out a scale error.
* **WHAT STANDS:** three events where ONE `/api/ops/artifacts/export` call grew
  anon by **39.9 / 56.9 / 48.3 MB** in the 8-64MB bucket and had not released it
  at teardown; two fired **one second apart**. 16 of 19 export calls cost
  **exactly 0.00**. The bimodality explains why five earlier probes read flat and
  why the route correlation was `r=+0.037`: a rare ~50 MB event averaged over
  3-9 minute intervals disappears.
* **WHAT DOES NOT STAND:** any claim about the FRACTION of `#632` those events
  represent.
* **WHY, hypothesised not established:** the sampler covers SOLO requests on an
  allowlist of two routes, and `skipped_concurrent` was **285** — most export
  calls are never sampled. pid 80's >100% additionally implies memory released
  after the window, consistent with the observed `-43.4 MB` interval.
* **INSTRUMENT COST: 64.93 ms mean / 150.50 ms max per sampled request**, 28-64x
  the synthetic estimate. Allowlist set to the sentinel `__off__`.
* **NEXT:** attribution must cover ALL requests, not an allowlist, and needs
  process readings dense enough to divide by — an emission every 200 solo
  requests cannot verify a 10-minute window.
### `[web-oom-leak]` UPDATE 8 — `proc_token` shipped INERT (fork inheritance); residual still unmeasured, 2026-09-04T20:3xZ `[session b2b5b45b]`

* **`proc_token` was generated at IMPORT and gunicorn forks workers AFTER the
  import**, so every worker inherited the same value — pid 99 and pid 98 both
  emitted `6178fc632433` (measured 20:24-20:26). Fixed by deriving it lazily and
  re-minting whenever `os.getpid()` changes (`b36d993f`).
* **The broken version produced a CONFIDENT WRONG ANSWER, not a null:**
  `r = +0.870`, "residual tracks skipping", 18.0% coverage over 3 "clean"
  windows. **DISCARDED** — those windows differenced one worker against another.
  The tell was a window reporting `solo 0` beside `attributed -103.22 MB`.
* **The residual is therefore STILL UNMEASURED.** Nothing about skipped requests
  as the gap is established; the earlier `r = +0.870` must not be quoted.
* Two instrument defects fixed and landed before it (`63e45361`): `routes` is
  truncated to `top=12` (differencing it read **4842% unexplained**), so
  `attributed_total_mb` is now untruncated; and `skipped_concurrent` counts
  CONTAMINATED WINDOWS, not requests — one overlap increments it twice.
* **NEXT:** collect >= 3 windows on `b36d993f`, with the collector refusing any
  token that spans more than one pid.
### `[web-oom-leak]` UPDATE 9 — **the residual is measured: 82.3% covered, and skipping is NOT the gap**, 2026-09-04T21:3xZ `[session b2b5b45b]`

* **16 clean windows, 2 distinct process tokens, ~50 min: process `+669.30 MB`,
  attributed `+550.67 MB`, residual `+118.63 MB` — 82.3% COVERED.** Stable under
  doubling n (75.9% at n=8). This is `#632`'s first stable share.
* **FALSIFICATION TEST FIRED — the residual does NOT track `skipped_concurrent`:**
  pearson `+0.236`, spearman `-0.047`, and `+0.087` without the single leverage
  window. Skipped requests are not the gap; the solo-only rule is not what hides
  the memory.
* **PER-WINDOW COVERAGE IS UNUSABLE** (`-130%` to `+452%`, over 100% in five
  windows, negative in four). Under munmap-heavy churn, a per-request delta and a
  net process change are different quantities. **Quote the aggregate, never a
  window.**
* `residual` vs `process climb` (pearson `+0.856`) is PARTLY DEFINITIONAL —
  `residual = process - attributed`. Not independent evidence.
* **Three earlier verdicts from this same collector were wrong**, all small-n
  coefficients: `-0.999` at n=3, `+0.870` on merged workers, `+0.710` at n=8
  collapsing to `-0.297` on leave-one-out. Gate is now n>=8 + leave-one-out +
  Spearman beside Pearson.
* **NEXT for `#632`:** the 8-64MB mappings are identified and requests own ~82%
  of the movement, but no single route owns it and per-request attribution
  cannot be made to compose. The open question is the remaining ~18% and whether
  the churn HIGH-WATER MARK — not a leak — is what OOMs the service.
### `[web-oom-leak]` UPDATE 10 — **RETENTION, not churn. Two independent instruments agree**, 2026-09-04T22:4xZ `[session b2b5b45b]`

* **`VmHWM - VmRSS` is ~29 MB on BOTH workers** (pid 98: 682.98 vs 654.28; pid 97:
  640.88 vs 612.09), and `process_anon_mb_now` EQUALS the running peak on both.
  A process sitting at its own all-time high-water mark has not returned memory.
  **Churn would show a large HWM-RSS gap. It does not.**
* **Independent confirmation from a 60-sample RSS poll of `/api/ops/memory`**
  (20 min, 20 s cadence): in EVERY series the floor equals the FIRST reading —
  worker 97 `380.8 -> 612.1`, worker 98 `434.8 -> 811.0 peak`, container
  `1248.0 -> 2037.0 peak`, unreclaimable `793.4 -> 1403.3 peak`. **Nothing ever
  returned below where it started.**
* **The container touched `2037.0 MB` — 99.5% of the 2048 MB limit**, ~11 MB of
  headroom, at a moment when a transient merge child (pid 198, 94 MB) was
  present. Steady state at the time of writing: **1888.5 MB, 92.2%, 159.5 MB
  headroom**.
* **THE SYNTHESIS, and it corrects an earlier reading in this same session:**
  worker retention is the DOMINANT term and transient children are a small
  additive one. An earlier note called them roughly equal partners; the
  `VmHWM-VmRSS` reading settles it. The children matter only because they land
  on a floor that retention has already raised.
* **INSTRUMENT DEFECT, mine:** `anon_extremes.floor_mb` is a RUNNING MINIMUM,
  and a running minimum over a rising series is always the FIRST reading — it
  can never rise, so it cannot detect a rising floor, which is the question it
  was built for. Both floors are pinned at their boot values. What answered the
  question was `VmHWM` vs `VmRSS`, added as a secondary reading. A WINDOWED
  minimum (last N) is the correct design.
* **`unexplained_memory_mb` is 385.5 MB** and is not yet investigated.
### `[web-oom-leak]` UPDATE 11 — merge caps lowered and **UNTESTED**; growth is NOT merges; the restart buys ~15 min, 2026-09-04T23:0xZ `[session b2b5b45b]`

* `SYNDICATE_ARTIFACT_MERGE_CHILD_CAP` **2 -> 1** (`e3a5154f`) and
  `SYNDICATE_ARTIFACT_MERGE_INFLIGHT_MB` **-> 16** (`3a9153f4`), both deployed on
  CLEAR preflights. **verify: UNTESTED — 0 merge children in 75 polls / ~20 min.**
* **The container ramped `1066.8 -> 1988.5 MB` (52% -> 97%) with NO merge child
  running.** Merges are not the driver of the current growth; both changes bound
  a path that is not firing.
* **The restart bought ~15 MINUTES, not hours:** `1888.5 (92.2%) -> 1133.4
  (55.3%)` at go-live, back to `1871.4` within 20 min.
* **CORRECTS my own earlier estimate.** I said "a few hours", carrying the
  `+173 MB/h` plateau rate from a quiet period into a much busier regime.
  Measured: `52% -> 96.7% in 11 minutes`. Stale baseline, different regime.
* Merge children are INTERMITTENT (two in flight at 22:29Z, pids 281/284, which
  delayed the first deploy) — so the caps may be exercised in a later window.
* **`#632` STILL HAS NO FIX.** Retention is the dominant mechanism (`VmHWM -
  VmRSS` ~29 MB both workers; every polled series floor == first reading), it has
  no identified owner, and neither env change touches it.
### `[web-oom-leak]` UPDATE 12 — **CORRECTION to UPDATE 10: it is BOTH, and my "retention, not churn" rested on one time point**, 2026-09-04T23:2xZ `[session b2b5b45b]`

* **UPDATE 10 said "RETENTION, not churn" on the strength of `VmHWM - VmRSS`
  reading ~29 MB on both workers. A later emission from the SAME session
  undercuts it.** The full series, in time order:

        22:17:09  pid 98   HWM 436.0  RSS 389.3   gap  46.8
        22:20:49  pid 97   HWM 606.2  RSS 571.9   gap  34.4
        22:22:57  pid 98   HWM 683.0  RSS 606.0   gap  77.0
        22:29:14  pid 97   HWM 640.9  RSS 612.1   gap  28.8
        22:31:00  pid 98   HWM 683.0  RSS 654.3   gap  28.7
        22:36:33  pid 97   HWM 766.8  RSS 612.1   gap 154.7   <-- 155 MB RETURNED

* **pid 97 reached 766.8 MB and came back down ~155 MB** — memory RETURNED, which
  is churn. **pid 98 held its HWM flat at 683.0 while RSS climbed 606.0 -> 654.3**
  — memory RETAINED. **Two workers in one container doing different things.**
* **The 29 MB reading I built a verdict on was a COINCIDENCE of one sample
  instant**, when both workers happened to sit near their peaks. Two emissions
  later the same worker read 154.7.
* **Correct statement: BOTH mechanisms are present.** Peaks are returned
  sometimes, and the baseline still trends up. UPDATE 10's exclusive framing is
  withdrawn; the container-level facts in it (ramp `1066.8 -> 1988.5`, restart
  buying ~15 min) stand.
* The `anon_extremes` collector printed `VERDICT: ... CHURN` — **ignore that
  line.** It is computed from `floor_mb`, a running minimum that cannot rise
  (UPDATE 10 records the defect). Its own caveat says to read `VmHWM - VmRSS`
  instead, which is what the series above does.
* **METHOD NOTE:** a single-timepoint reading of a monotone-vs-current gap cannot
  distinguish these mechanisms — the gap is near zero whenever a process happens
  to be AT its peak, regardless of whether it returns memory later. It needs a
  SERIES, and UPDATE 10 did not have one.
### `[web-oom-leak]` UPDATE 13 — **the retainer is NOT a module-level container: census explains 6.1% of growth**, 2026-09-05T02:5xZ `[session b2b5b45b]`

* **Two readings, one worker, 13.7 min apart, budget not exhausted:** census
  `59.0 -> 64.9 MB` (+5.9) while process anon went `389.3 -> 486.1 MB` (+96.8).
  **The census explains 6.1% of the growth.** Level coverage 15.6% / 12.5% on the
  two workers.
* **NAMED RETAINERS (level, not growth):**
  `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` **~20 MB in ONE entry**;
  `soccer.cards._CARDS_CONTEXT_CACHE` 14.45 MB / 29;
  `mlb.cards._MLB_CARDS_CONTEXT_CACHE` 6-10 MB / 4 (**+11.21 MB on one added
  entry**); `_MLB_TODAY_CACHE` 7.6-10 MB; `LAST_RESULT` ~5 MB.
* **`LAST_RESULT` reconciles two earlier readings:** it HOLDS ~5 MB and grows
  0.0 MB per request. The per-request probe was right and so is this.
* **READ THE LIMIT BEFORE QUOTING THE 6.1%:** the walk's ROOTS are module globals
  that are already containers. A module-level OBJECT with caches in its
  `__dict__`, a class attribute, a closure, or thread-local state is never
  reached. The claim is **"not in container-typed module globals"**, NOT "not in
  Python". Widening the roots is the next step.
* **Instrument cost:** 1.2 s, ~10 MB transient, walk completes at 2M nodes. At
  lower caps the budget exhausts and the ranking becomes *biggest among whatever
  was reached first* — the 20k/100k/400k runs are NOT quotable.
* Worker anon grew **+96.8 MB in 13.7 min (~424 MB/h)** during this window,
  consistent with the fast regime measured earlier tonight.
### `[web-oom-leak]` UPDATE 13 — **the retained bytes are NOT Python objects (28.3%). The object-graph line is CLOSED.**, 2026-09-05T20:4xZ `[session b2b5b45b]`

* **Measured on pid 98 with a CONVERGED walk (891,276 nodes, not truncated):
  process anon `373.17 MB`, live Python objects `105.56 MB` — `28.3%`.
  `267.61 MB` (71.7%) is not Python objects.** Threshold pre-registered before
  the reading (`>=70%` Python / `<=35%` not).
* Convergence was the whole point: the same call read `7.2%` at a 200k cap and
  `28.5%` at 800k, both TRUNCATED. **A truncated walk reads as "not Python" —
  the correct answer here, reached for the wrong reason at any smaller cap.**
* **CORROBORATION, not proof:** an arena reading from a different worker hours
  earlier gave `bytes_in_allocated_blocks = 105.731 MB` against this walk's
  `105.56 MB` — independent methods agreeing to `0.16%`. Different epochs, so
  suggestive only.
* Implied decomposition (same caveat): `105.6 MB` live objects, `44.3 MB`
  pymalloc fragmentation, `223.2 MB` **outside pymalloc arenas entirely** —
  where the 8-64MB mappings identified earlier must live.
* **CLOSED: no Python-level probe can reach the 71.7%.** Root sets, retainer
  censuses and per-request attribution are all blind to non-object bytes.
  Remaining candidates: C-extension buffers, allocator behaviour below CPython,
  per-thread state.
* **STILL WORTH DOING, on its own merits and not as an OOM fix:**
  `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` **37.50 MB** and
  `_CARDS_CONTEXT_CACHE` **12.67 MB** are real, nameable, unbounded caches.
* The census table and the heap ratio came from DIFFERENT workers (pid 99 vs
  98) — the endpoint round-robins. The ratio is self-consistent; the table is
  not a breakdown of it.
### `[web-oom-leak]` UPDATE 14 — **the GROWTH is non-Python too, not just the standing total**, 2026-09-05T21:0xZ `[session b2b5b45b]`

* UPDATE 13 measured a STOCK ratio at one instant (28.3%). That does not answer a
  GROWTH question — a heap could hold 28% of anon and still be the entire
  growing term. **Measured over 10.9 min, per worker, every walk CONVERGED (0
  truncated readings discarded):**

        pid 97   anon  +56.26 MB   heap  +0.19 MB   =  0.3% of the growth
        pid 98   anon +107.06 MB   heap +24.50 MB   = 22.9% of the growth

* **pid 97 is the decisive case: its Python heap sat at `104.68 -> 104.87 MB`,
  flat to 0.2 MB, while anon climbed 56 MB.** The verdict is upgraded from a
  snapshot to a trend: the growth itself is non-Python.
* **pid 98's 22.9% is an UPPER BOUND, not a measurement.** Consecutive walks on
  that worker swung `184.23 -> 167.18 MB` (~17 MB), so its `+24.50 MB` delta is
  only modestly above the instrument's own noise. Quote pid 97's `0.3%`.
* **RATE, measured in the same window and it is steep:** pid 97 `~307 MB/h`,
  pid 98 `~590 MB/h`, ~900 MB/h combined. Container at the end: **1756.6 MB,
  85.8%, 291 MB headroom.**
* Nothing changes about the `#632` conclusion except its strength: no
  Python-level probe can find the growing bytes.
### `[web-oom-leak]` UPDATE 15 — **CORRECTION: I quoted page cache as OOM pressure. Real pressure is 54%, not 86%.**, 2026-09-05T21:2xZ `[session b2b5b45b]`

* **`container_memory_mb` INCLUDES RECLAIMABLE PAGE CACHE and is NOT the OOM
  metric.** I quoted `1756.6 MB / 85.8% / 291 MB headroom` and projected an OOM
  in ~20 minutes. Minutes later the same figure had FALLEN to `1509.1 MB` while
  both workers' RSS went slightly UP — a ~247 MB move that no process made.
* Split over 5.1 min (7 samples, 50 s apart):

        total           +151.2 MB   -> +1786 MB/h   (cache swung 469 -> 588 MB)
        UNRECLAIMABLE    +98.8 MB   -> +1167 MB/h
        pid 98 rss       +53.9 MB
        pid 97 rss       +44.2 MB   (sum 98.1 ~= unreclaimable 98.8: consistent)

* **Standing pressure is `1103.7 MB` unreclaimable of 2048 = 54%**, not the 86%
  I reported. The difference is ~570 MB of file cache the kernel evicts under
  pressure before it OOMs anything.
* **GROWTH IS BURSTY, so no rate from a short window is trustworthy — including
  the ones above.** Both workers rose ~98 MB between 16:17:43 and 16:19:25 and
  were then FLAT to the decimal (`595.3` / `509.4`) for the remaining 3.5 min.
  Extrapolating `+1167 MB/h` across a window containing one burst is exactly the
  error that produced the "~20 minutes to OOM" claim.
* This is the standing `memory.current is page cache` rule, which I had recorded
  and did not apply: **split anon from file before calling anything pressure.**
### `[web-oom-leak]` UPDATE 16 — **bursts are ORDINARY TRAFFIC, and the "both workers" observation that started the lane was a SAMPLING ARTIFACT**, 2026-09-05T22:2xZ `[session b2b5b45b]`

* **7 settled bursts at 10 s cadence, 0 restarts inside the window:**
  `0/7 hit both workers`; sizes `17.6-41.8 MB` (mean `28.0`); gaps
  `3.3, 0.2, 1.6, 4.0, 0.2, 3.4 min`, spread/mean `1.79` against a periodicity
  bar of `<=0.35`. **Not simultaneous, not periodic — demand-driven request
  traffic on one worker at a time.** The scheduled-job / fan-out hypothesis is
  FALSIFIED.
* **THE LANE'S FOUNDING OBSERVATION DOES NOT SURVIVE.** It was opened on "both
  workers rose ~98 MB in ~100 s — one request cannot do that", taken from
  **50-SECOND sampling** (pid 98 `+53.9`, pid 97 `+44.2` over 5.1 min). At 50 s
  resolution *"one worker then the other"* is INDISTINGUISHABLE from *"both at
  once"*. At 10 s resolution it resolves into single-worker bursts, 7 for 7.
  **A conclusion drawn at a resolution coarser than the phenomenon.**
* **A FIRST RUN WAS DISCARDED ENTIRELY.** A peer deployed web at
  `16:29:52-16:32:58` and the detector had no restart guard, so it reported
  warm-up as bursts — including `+570 MB` and `+284 MB`. Pids are REUSED across a
  restart (97 and 98 both times), so the pid set looked continuous. Rebuilt with
  restart inference (RSS drop or a run of failed fetches) and a 10-minute settle
  window; the rerun excluded 3 warm-up bursts explicitly rather than silently.
* Consistent with the rest of `#632`: ~28 MB increments match the 8-64MB
  anonymous mappings already identified, and none of it is reachable from Python.
* Weak signals, recorded as such: pid 98 took **6 of 7** bursts (lopsided for
  round-robin, but n=7), and ONE burst coincided with a 98 MB child process
  (`272:pro`, the only child all window) — an anecdote, not a mechanism.
### `[web-oom-leak]` UPDATE 17 — intelligence response cache **BOUNDED and VERIFIED**: `22.503 -> ~13.1 MB` (-42%), 2026-09-06T02:3xZ `[session b2b5b45b]`

* `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` now carries a **row budget** beside the
  entry cap, **loop eviction** (the old code popped exactly ONE entry per insert,
  so a cache over budget by more than one never caught up), and a **one-entry
  floor** so an oversized slate cannot turn the cache into a permanent miss.
  Deployed `814fda97`.
* **Measured: `~13.1 MB` vs a `22.503 MB` control taken on the old code minutes
  before the deploy — 58%, a 42% reduction, flat over 22.9 min (largest climb
  `+0.477 MB`), both workers agreeing.**
* **THE BOOT CONFOUND IS RULED OUT BY THE SAME WINDOW:** census total recovered
  to `73.66`/`67.89 MB` against a `77.38`/`69.97` control (~95%) while the cache
  stayed at 58%. The process matured; the cache did not. No cross-epoch
  comparison was needed.
* **The control had to be re-taken.** The lane quoted `37.50 MB` from hours
  earlier on a bigger slate; the live value was `22.503 MB`. Against the stale
  number, doing nothing would have passed.
* Row count was chosen over byte-sizing on MEASUREMENT: an accurate deep walk
  costs `228 ms` per insert; a truncated walk reported `11.31 MB as 1.44 MB`;
  `json.dumps` costs `70-174 ms` and allocates a `9.44 MB` transient string.
* **NOT AN OOM FIX** — `#632`'s bytes are not Python objects (28.3% of anon,
  0.3% of the growth).
* **NEXT, and NOT shipped:** `slice_intelligence_board_state_for_request` builds
  `top_opportunities` and `recommendations` as two INDEPENDENT deep copies of the
  same rows. Every use is a reassignment, never an in-place mutation, so sharing
  the row dicts would roughly halve that term. Separate change, separate risk.
### `[web-oom-leak]` UPDATE 18 — **FOUND: ~200 MB per worker is FREED-BUT-RETAINED in glibc's arena**, 2026-09-06T15:4xZ `[session b2b5b45b]`

* **`mallinfo2` on both live workers, 16 samples after an 8-minute settle:**
  arena `269.4`/`275.5 MB`, **in use only `72.8`/`72.1 MB`**, **free-but-retained
  `196.6`/`203.4 MB` (72.9% / 73.7% of what glibc holds)**. Both workers agree to
  within 1%.
* **This is the first mechanism `#632` has identified that admits a FIX.** The
  memory is not lost — it is freed, and glibc is holding it rather than returning
  it. `malloc_trim()` is the mechanism that hands it back; `releasable_top_mb`
  alone was `41.6 MB`.
* **NOT the call `#435` tried.** That was `malloc_info` (per-arena XML, 13.9%
  coverage). `mallinfo2` is a different function.
* **COVERAGE CAVEAT — 61% IS A FLOOR:** `mallinfo2` reports the MAIN ARENA ONLY,
  and web runs `GUNICORN_THREADS=4`, so per-thread secondary arenas (created via
  `mmap`) are excluded. This RECONCILES what looked like a contradiction: smaps
  `by_kind` gave `anon_mmap 370.0` vs `heap 81.2 MB`, while `mallinfo2` gives
  `arena 275.5` vs `mmapped 0.387 MB` — different arenas, not different truths.
* Consistent with everything else measured: not Python objects (28.3%), not
  returned by freeing, grows with request traffic, lives in large anon regions.
* **NEXT: measure `malloc_trim()` before/after.** Not called yet — it mutates
  allocator state and takes the malloc lock across arenas.
### `[web-oom-leak]` UPDATE 19 — **`malloc_trim` returns ~50 MB/worker in ~14 ms; the first intervention that gives memory back**, 2026-09-06T16:1xZ `[session b2b5b45b]`

* **Measured on both live workers after a 12-min settle, POST once each:**
  pid 97 `354.2 -> 296.1 MB` (**-58.1**) in `14.2 ms`; pid 98 `339.8 -> 292.6`
  (**-47.3**) in `4.1 ms`. glibc returned `1` on every call and `in_use` did not
  move, so the drop is attributable to the trim.
* **~105 MB across the container**, for ~14 ms of malloc-lock hold.
* **IT DOES NOT RECOVER THE FULL ~200 MB.** pid 97 held `144.3 MB` free and gave
  back `30.0`. The remainder is FRAGMENTED — free chunks interleaved with live
  ones, so whole pages cannot be released. **Trim recovers the releasable
  fraction, not the free total.**
* **The anon drop EXCEEDS the main-arena drop** (`-58.1` vs `-31.3`), which
  corroborates the `mallinfo2` coverage caveat: that call sees the MAIN ARENA
  only, `malloc_trim` iterates ALL arenas, so ~27 MB came from per-thread arenas
  the measurement cannot see. The two instruments disagree exactly as their
  documented scopes predict.
* **Repeat calls return ~0** (`-0.4`, `-0.2`, `+0.0 MB`, sub-ms) — trim is
  idempotent until free space re-accumulates.
* **STILL NOT A FIX.** This is a manual call. Automating it needs a cadence, a
  trigger, and a cost measurement under concurrent load rather than under a probe.
### `[web-oom-leak]` UPDATE 20 — **automatic `malloc_trim` is LIVE and VERIFIED: 1,481 MB returned in 34 min**, 2026-09-06T17:0xZ `[session b2b5b45b]`

* `SYNDICATE_MALLOC_TRIM_AUTO=1` on web, code `f6af42cf`, gated at a 300 s
  interval and a 64 MB free-arena threshold, riding the existing
  `teardown_request` hook (no new thread).
* **12 trims / 33.9 min across both workers, ALL with glibc returning 1 and
  `in_use` unmoved. Mean `-123.5 MB` per trim, total `1,481.4 MB`.** Container
  unreclaimable fell in 12 separate intervals — an independent source agreeing
  with the log lines.
* **NET STILL RISING: `676.6 -> 879.8 MB` (+203.2) in the same window**, so gross
  growth was ~1,685 MB (~2,982 MB/h). **Without the trims the container would
  have reached ~2,361 MB against a 2,048 limit inside 34 minutes** — not a
  controlled proof, but the first `#632` intervention whose size is comparable to
  the problem.
* **NOT A FIX — a faster drain on a running tap.** The growth mechanism is
  untouched; only the freed-but-retained portion is reclaimed.
* **COST: 3 of 12 trims held the malloc lock 62-75 ms** (median 12.3). One
  request per interval per worker pays it. The median understates the tail.
* Re-accumulation is fast: ~100 MB per five minutes per worker against ~120
  returned.
### `[web-oom-leak]` UPDATE 21 — **RETRACTION: the auto-trim headline was my own artifact; flag OFF**, 2026-09-06T18:0xZ `[session b2b5b45b]`

* **RETRACTED from UPDATE 20:** *"without the trims the container would have
  reached ~2,361 MB"*. That assumed the `1,481 MB` returned would otherwise have
  ACCUMULATED; it would not — it was free arena space being REUSED in place.
* **Matched short windows (>=50 publish calls each):** pre-trim `n=62`, median
  **`0.000 MB/call`** (50 of 62 read exactly zero); post-trim `n=28`, median
  **`0.893 MB/call`**. Boundary `16:24:41`, the instant the flag went live.
* **MECHANISM:** `malloc_trim` returns pages via `MADV_DONTNEED`;
  `smaps_rollup`'s `Anonymous` counts RESIDENT pages, so the next request
  re-faults them and the per-request delta records that as fresh allocation. The
  trim turns *reuse-in-place* into *return-then-refault*.
* **The "~3 GB/h allocation rate" is therefore substantially the trim's own
  doing.** Pre-trim, `/api/ops/artifacts/publish` — ~1,300 calls per window, the
  busiest route — cost nothing measurable in anon.
* **SURVIVES:** the trim does return memory (12 trims, glibc returning 1,
  `in_use` unmoved, 12 independent container falls). **DOES NOT SURVIVE:** that
  the memory would otherwise have accumulated.
* **NET EFFECT UNDETERMINED** — lowers RSS, adds page-fault churn, nothing
  measured says which wins. Needs a controlled on/off comparison over matched
  windows. **Flag set to `0`** rather than run a production change on an
  invalidated inference. The code stays, inert.
### `[web-oom-leak]` UPDATE 22 — the trim A/B is **DEFERRED to a quiet window, with a runnable harness committed**, 2026-09-06T18:3xZ `[session b2b5b45b]`

* **The question left open:** is automatic `malloc_trim` net-positive? It returns
  memory (12 trims, glibc confirming, two independent sources) AND causes the
  returned pages to be re-faulted. Nothing measured says which wins.
* **FIRST ATTEMPT DIED AFTER 3.4 CLEAN MINUTES.** A peer deployed web at
  `18:22:36`, mid-window. A restart resets every memory metric, so the arm was
  discarded rather than salvaged.
* **THIS IS THE ENVIRONMENT, NOT BAD LUCK: web took a deploy roughly every 20-30
  minutes** through the working day (`15:22`, `15:53`, `16:21`, `18:04`,
  `18:22`). The experiment needs **~84 uninterrupted minutes** — a 12-minute
  settle plus a 30-minute window, twice.
* **DEFERRED by user decision** rather than rushed. Shortening the settle would
  produce a FALSE NEGATIVE — a fresh worker has not accumulated the free arena
  space the trim returns — and that is the failure mode that reads as an honest
  disappointing result.
* **`scripts/malloc_trim_ab.py` is committed and runnable.** `arm OFF <ts>`,
  `arm ON <ts>`, `compare`. It detects a mid-window restart and says DISCARD; it
  refuses to call a winner if the arms' request volumes differ by >25%; and its
  decision metric is CONTAINER UNRECLAIMABLE, never the trim's own reported
  savings — those are the numbers that produced the retracted claim.
* **Current production state: flag `SYNDICATE_MALLOC_TRIM_AUTO=0`, code live and
  inert** (`4f62d937`). Nothing is degraded; pressure ~55%.
### `[web-oom-leak]` UPDATE 23 — **THE PROGRAM'S LIVE DATA IS NOT GROWING. `in_use` is flat-to-FALLING while anon climbs.**, 2026-09-06T20:2xZ `[session b2b5b45b]`

* **Clean 31-minute window, both workers, trim OFF, no restart, under a HELD
  deploy claim** (three earlier windows had been killed by peer deploys):

        pid 97  n=32  arena +7.2   IN USE -10.3 (62.4..81.8)   free +17.6   anon +42.4
        pid 98  n=44  arena +8.3   IN USE  -2.9 (67.7..73.3)   free +11.2   anon +26.9

* **THE HEADLINE, robust across every reading taken today: `in_use` sits at
  62-82 MB while process anon is 536-677 MB. Live program data is UNDER 12% of
  the process's memory, and over this window it FELL while anon rose.** Whatever
  the other 88% is, the program is not using it.
* **The growth is NOT in the main arena.** Anon rose `+42.4`/`+26.9 MB` while the
  main arena moved `+7.2`/`+8.3` — so ~80% of it landed where `mallinfo2` cannot
  look. That call reports the MAIN ARENA ONLY, and web runs
  `GUNICORN_THREADS=4`, so per-thread SECONDARY arenas exist and are created via
  `mmap`.
* **The lane's own test could not fire** and said so: with the main arena flat
  there was nothing to attribute, so the formal verdict is *NOT a result*. The
  hypothesis was about main-arena fragmentation and this window shows the main
  arena is not where the action is.
* **Two earlier hand-read segments (17% and 5% of arena growth becoming live
  data) describe the BOOT PHASE**, when the main arena fills to ~330-390 MB with
  ~80% free. They are not contradicted; they are a different phase. Steady state
  plateaus the main arena and pushes growth to the secondary ones.
* **NEXT, and it is a specific instrument:** `malloc_info`'s per-arena XML is the
  only thing that can see secondary arenas. `#435` dismissed it at 13.9%
  coverage, but that was measuring a different question — coverage of TOTAL anon,
  not the per-arena split. It should be re-read with this question in hand.
### `[web-oom-leak]` UPDATE 24 — **A DUPLICATE DEFINITION HAD SILENTLY KILLED `#285`'s PROOF LINE**, plus the per-arena instrument is built (and INERT), 2026-09-06T21:1xZ `[session b2b5b45b]`

* **THE DEFECT, and it is live code.** `_MALLOC_TRIM_STATE` and
  `_resolve_malloc_trim` were each defined **TWICE** at module scope in
  `syndicate/features/shared/memory_observability.py` — once by `#285`
  (~line 2397) and again ~1,900 lines later, beside the `mallinfo2` work **this
  session added earlier the same day**. Python keeps the LAST binding, so
  `#285`'s resolver was dead code. Fixed in `67af1276`.
* **Nothing failed loudly, which is why it survived.** `malloc_trim` still bound
  and still trimmed. What the duplicate removed was the EVIDENCE:
  * **`MALLOC_TRIM_INIT`** — the one-time line `#285` added *precisely because*
    the binding cannot be exercised on any dev machine here, so a production log
    line is its only proof. Grepping for it after a deploy returned nothing,
    which reads as *"the binding failed"* and actually meant *"the emitter is
    gone"*. This is `[feedback_absent_signal_is_about_the_emitter]` again, and
    this time I caused it.
  * **commit `daed5d92`**, *"hold the CDLL, not just the function pointer taken
    off it"* — the duplicate kept only the pointer, re-opening a FIXED lifetime
    bug.
  * the `libc.so.6` → `find_library("c")` → `None` fallback chain, narrowed to a
    single `CDLL(None)`.
* **Blast radius is real, not theoretical:** `release_freed_memory_to_os()` is
  called from **five sites** in `pipeline/intelligence_state.py` (layer2 refresh
  guards, candidate pool, overview headroom). Also, `malloc_trim_now()` was
  reading a `why` key that the surviving state dict does not have, so it reported
  *"malloc_trim not found in libc"* **whatever the real reason was**.
* **How it was found:** `tests/test_malloc_trim_release.py` had a RED test
  asserting `MALLOC_TRIM_INIT` is emitted. It was failing, it was in the area I
  was working, and it was telling the truth. `[feedback_documented_caveat_is_a_scheduled_defect]`.
* **A repo-wide AST sweep found TWO MORE instances**, both outside this lane and
  both FREE at the time: `syndicate/features/nba/live_lens.py`
  (`build_live_lens_api_payload`, lines 747 and 807 — a LIVE API payload
  builder) and `syndicate/features/nhl/cards.py` (`_sim_hist_rows`, 521 and 539).
  Flagged, not fixed here. A test now pins the no-duplicate invariant for
  `memory_observability.py`; a repo-wide check is the better home for it.

* **THE INSTRUMENT, built and landed but NOT YET LIVE.**
  `parse_malloc_info_arenas()` splits `malloc_info` XML **per `<heap>`**, which
  `parse_malloc_info_xml` discards by design (top-level totals only, to avoid
  double counting). Each `<heap nr=N>` IS an arena, so this is the only
  instrument that can see the secondary arenas `mallinfo2` does not report.
* **It does NOT inherit my own assumption.** I have been asserting `mallinfo2`
  is main-arena-only. `man mallinfo2` says so under BUGS; glibc's
  `__libc_mallinfo2` walks the arena ring; neither runs on any machine here, and
  **the entire "80% is invisible" claim from UPDATE 23 rests on which is right.**
  So `mallinfo2.arena` is compared against BOTH heap 0 and the top-level total
  and the scope is decided FROM THE DATA — including `indistinguishable` when
  there is one arena and the comparison has no power to say anything.
  **If it comes back `all_arenas`, UPDATE 23's premise is falsified** and the
  growth is outside glibc entirely.
* Every derived number is paired with its residual: per-heap sum vs glibc's own
  top-level total, and a FAILED reconciliation blocks every downstream verdict
  rather than yielding a confident split off a misread tree. Coverage against
  cgroup anon gates it too — below 50% the arenas are not where the memory lives.
* **INERT until deployed AND enabled.** `SYNDICATE_MALLOC_ARENA_DETAIL` defaults
  **OFF**, and web runs a deploy branch with `autoDeploy = no`, so landing on
  `main` ships nothing. It is flag-gated and throttled because
  `get_all_process_memory_snapshot()` is also reached from
  `log_all_process_memory()` at worker STAGE CHECKPOINTS — unconditional libc
  work there is the `#241` shape. The call reports its own `duration_ms`, and a
  cached reading is stamped `age_s`, so neither the cost nor the freshness has to
  be assumed.
* Reachability note: it rides the EXISTING `/api/ops/memory` rather than a route
  of its own, because `syndicate/blueprints/ops.py` is held by
  `ncaaf-live-resim-wire`. 36 new tests; 89 pass across the memory-instrument
  files, including the previously-red `MALLOC_TRIM_INIT` test.
### `[web-oom-leak]` UPDATE 25 — **THE ARENA HAS A CEILING (~390 MB in ~30 min). `mallinfo2` WAS NEVER BLIND, so UPDATE 23's headline is CORRECTED.**, 2026-09-06T22:2xZ `[session b2b5b45b]`

* **`mallinfo2` READS EVERY ARENA. `82 of 82` readings returned
  `mallinfo2_scope == "all_arenas"`**, matching the all-arena total to `0.0 MB`
  and missing the main arena by `70.1 MB` with 15-20 arenas live — so the
  comparison had power, unlike the single-arena case the instrument refuses.
  `man mallinfo2`'s BUGS note ("only the main memory allocation area") does NOT
  describe this glibc; `__libc_mallinfo2` walks the arena ring.
* **CORRECTION TO `UPDATE 23`.** I wrote that ~80% of the growth "landed where
  `mallinfo2` cannot look". **Wrong — it was never blind.** Re-reading the SAME
  numbers with correct semantics says something stronger: of `+69.3 MB` anon
  growth, glibc's whole allocator took `+15.5 MB`, so **77.6% was outside the
  allocator**, not hiding in secondary arenas.
* **ALSO CORRECTED: the "58-72% coverage" I quoted was MISPAIRED** — it crossed
  one worker's arena with the other's anon. Paired correctly the mature figure is
  **58.6-61.3%**.
* **THE RAMP IS THE OPPOSITE OF THE PLATEAU, and that is the finding.** A 33-min
  window on a freshly restarted process, both workers, no restart, trim OFF:

        pid 97  n=37  anon +266.9  glibc ALL +211.7 (79%)  main +20.7  secondary +190.9
        pid 98  n=37  anon +213.9  glibc ALL +194.5 (91%)  main +34.9  secondary +159.8

  In the ramp the allocator takes **79-91%** of the growth and **~85% of THAT
  goes to SECONDARY arenas** (arena count 15 -> 20). In the mature phase it takes
  **22.4%**. Both are true; they are consecutive phases.
* **THE CEILING IS REPRODUCIBLE ACROSS THREE INDEPENDENT WINDOWS** on pid 97:
  `387.7` at the end of the ramp, `388.2 -> 395.4` through UPDATE 23's window,
  `390.1` on a later spot read. **The arena fills to ~390 MB in ~30 minutes and
  then stops.** Everything after that is growth the allocator does not take.
* **THE RESIDUAL IS NOT `malloc` AT ALL.** `hblkhd` — glibc's large-allocation
  mmap path — is **0.4 MB in 3 regions**. So "outside the arena" is not "large
  chunks mmapped by malloc"; it is outside `malloc` entirely. `205.1 MB` (34.4%)
  on pid 97, `142.1 MB` (27.6%) on pid 98, and it grows steadily in BOTH phases
  (`+55.2` over the ramp, `+35.2` over UPDATE 23's mature window).
* **AND THE ARENA IS MOSTLY NOT LIVE DATA.** At ~50 min: `in_use` `51.8`/`54.0 MB`
  against `338.3`/`319.2 MB` free-in-arena. **87% of what glibc holds is free
  chunks it has not returned** — ~660 MB across two workers, against a 2,048 MB
  limit. That is the standing cost `malloc_trim` addresses and the A/B
  (`scripts/malloc_trim_ab.py`) is still owed on.
* **A DEFECT IN MY OWN INSTRUMENT, caught in its first window and BEFORE any
  conclusion was drawn from it.** **Pids 97 and 98 both reported
  `process_anon_mb` = `701.6`** — identical, which is impossible for a
  per-process figure, because I had paired per-process arena numbers with the
  CONTAINER cgroup's anon. Coverage was
  understated by roughly the worker count (`15.9-32.3%` measured, `47.8-56.1%`
  true). `_process_anon_mb()` exists in the same file for exactly this and its
  docstring records the same substitution producing a 61-150% attributed share on
  2026-09-03. Fixed in both callers, with the source now REPORTED in
  `anon_source` — a fallback indistinguishable from the real thing is how it
  survived a whole window.
* **NEXT, and it is now a narrow question:** name the ~150-205 MB of per-worker
  anon that is not `malloc`. CPython's pymalloc arenas are `mmap`ped directly and
  would land exactly here, as would thread stacks (`GUNICORN_THREADS=4`) and
  C-extension buffers. `#632`'s earlier heap census put Python objects at 28.3%
  of anon, which is the right order of magnitude — that census should be re-read
  against THIS denominator rather than repeated.
### `[web-oom-leak]` UPDATE 26 — **THE NON-MALLOC ANON IS PYMALLOC (162-165 MB/worker) AND IT IS A CONSTANT, NOT A LEAK. Growth is INTERMITTENT.**, 2026-09-07T00:0xZ `[session b2b5b45b]`

* **THE PARTITION CLOSES.** `anon = glibc_malloc + pymalloc_arenas +
  so_private_dirty + main_thread_stack`. **50 of 50** mature readings and 49 of 50
  ramp readings scored `explained`, residuals `-0.8` to `-8.2 MB` on a 105-583 MB
  process, and `smaps`'s own total agrees with `smaps_rollup` to `0.0 MB`. This is
  a complete account of a web worker's anonymous memory, not a best guess.
* **THE `205 MB` HOLE FROM `UPDATE 25` IS NAMED: CPython's pymalloc arenas,
  162-165 MB per worker.** CPython `mmap`s them, so glibc never allocated them
  and `mallinfo2` was structurally incapable of seeing them. The other two
  non-`malloc` terms are real and negligible: `.so` private-dirty **exactly
  `4.4 MB`** and the main stack `0.1 MB`, both unmoved across 66 minutes.
* **AND IT IS A CONSTANT.** Over 31 mature minutes `pymalloc_arenas` did not move
  ONE megabyte on either worker — `162.0 -> 162.0`, `165.0 -> 165.0`. **I had
  written that pymalloc "becomes the growth driver" once the arena plateaus; that
  was speculation stated as a finding and the measurement refutes it.** In the
  ramp it takes 7.5-14.2% of growth; at maturity, 0.0%.
* **THE MATURE WINDOW DID NOT REPRODUCE THE GROWTH.** Anon moved `-5.8` and
  `+15.3 MB` in 31 min, against `UPDATE 23`'s `+42.4`/`+26.9` over the same span.
  On pid 98 the little growth there was went **98.7% to glibc**. So the episode
  UPDATE 23 caught is NOT attributed by this window — it did not occur during it.
  **Growth on web is INTERMITTENT**, and one stable window is not evidence it
  stopped (`[feedback_absence_in_a_window_is_not_absence]`).
* **WHAT THIS CHANGES ABOUT `#632`.** The steady-state composition is now fully
  known and contains no mystery: ~400 MB glibc arena (of which only ~52 MB is
  live data — 87% free chunks retained), ~165 MB pymalloc, ~4.5 MB everything
  else. Nothing is unaccounted for. **The OOM question is therefore no longer
  "what is the memory" but "what causes the intermittent growth episodes", and
  the single largest standing cost is the ~340 MB/worker of free-but-retained
  arena that `malloc_trim` addresses** — `scripts/malloc_trim_ab.py`, still owed.
* **INSTRUMENT COST, measured not assumed:** partition median `47-96 ms`, **max
  `1,700.6 ms`** — `/proc/self/smaps` is O(regions) and the throttle bounds
  frequency, not duration. `SYNDICATE_ANON_PARTITION` is back **OFF** (deployed
  `cc598278`). `SYNDICATE_MALLOC_ARENA_DETAIL` stays ON at `0.9-1.0 ms` median.
* **A CALIBRATION BUG OF MY OWN, caught in production within minutes.** The
  partition shipped with ONE tolerance serving two questions and false-tripped
  `terms_overlap` at residual `-4.3 MB` on a `209 MB` process. The overlap bar is
  now set against the FAULT it exists to catch — a whole pymalloc term double
  counted, ~100 MB — not against zero: 5%/8 MB, an order of magnitude above the
  slack and below the fault. The read-agreement check keeps the tight 2%/2 MB bar
  because it compares two reads of the SAME quantity.
### `[web-oom-leak]` UPDATE 27 — **SEVEN EPISODES CAUGHT. BOTH ALLOCATORS GROW, ALTERNATING — and PYMALLOC IS NOT THE CONSTANT `UPDATE 26` CALLED IT.**, 2026-09-07T02:1xZ `[session b2b5b45b]`

* **The in-process detector caught 7 episodes in 55 minutes**, both workers,
  every one `attributed` with the unattributed term between `-2.0%` and `+24.9%`
  — so the cheap capture (allocators only, no `smaps`) was sufficient throughout,
  which was the assumption it was built to expose if wrong.
* **THE LANE'S HYPOTHESIS IS REFUTED.** It predicted glibc. **4 episodes are
  glibc-dominant, 3 are PYMALLOC-dominant at 74-98.4%.** They alternate:

        96 @  955s  +19.9 MB  glibc 75.1%      97 @ 1121s  +19.1 MB  pymalloc 89.1%
        97 @ 1517s  +17.6 MB  pymalloc 74.0%   96 @ 2013s  +33.8 MB  glibc 98.4%
        96 @ 2080s  +18.3 MB  pymalloc 98.4%   97 @ 2511s  +55.4 MB  glibc 90.8%
        96 @ 3032s  +49.3 MB  glibc 102.0%

* **CORRECTION TO `UPDATE 26`, which called pymalloc "a large CONSTANT, not a
  leak".** It grows — in DISCRETE JUMPS of `+6.0`, `+13.0`, `+17.0`, `+18.0 MB`,
  all near-integer and consistent with 1 MB arena granularity. The 31-minute
  mature window that measured `+0.0 MB` on both workers did not span a jump. That
  is the difference between a continuous instrument and a sampled one, and it is
  exactly `[feedback_absence_in_a_window_is_not_absence]` — which UPDATE 26 cited
  about anon and then failed to apply to its own pymalloc reading.
* **THE RATE IS AN OOM TRAJECTORY.** Sustained post-warm-up: **3.68 MB/min** on
  pid 96 and **3.98 MB/min** on pid 97, `2.6-2.9x` `UPDATE 23`'s 1.4 MB/min. Two
  workers is **~7.4 MB/min of container growth** against a 2,048 MB limit.
* **THE ROUTE MIX IS NOT AN ATTRIBUTION, and the arithmetic says so.**
  `/api/ops/artifacts/publish` appears in all seven, but growth does NOT scale
  with it: **224 requests / 101 publishes → `+17.6 MB`**, while **36 requests / 9
  publishes → `+55.4 MB`**. This is the same route whose attribution I RETRACTED
  earlier this session as trim-inflated (pre-trim it cost ~0 MB in anon terms),
  and a co-occurrence is not grounds to re-adopt it.
* **THE DETECTOR ITSELF NEEDED A WARM-UP, found in production.** Its first run
  fired 18.4 s after boot on `+230.3 MB at 750 MB/min` with `/` and `/healthz`
  the only routes — the boot ramp, three orders of magnitude faster than the
  phenomenon. That cost the episode slot and, worse, polluted
  `max_anon_rise_seen_mb`, the one field that separates "the process was flat"
  from "the trigger is mis-sized". Warm-up now 900 s; process age is derived
  LAZILY PER PID because gunicorn forks after import (the trap that shipped
  `proc_token` inert earlier in `#632`).
* **NEXT, and it is now two separate questions:** (a) what triggers a pymalloc
  arena jump — 1 MB granularity means it is a real allocation burst, not
  fragmentation; (b) whether glibc's episodes are the arena re-expanding above
  the ~390-400 MB ceiling, which `malloc_trim` would address and
  `scripts/malloc_trim_ab.py` is still owed on.
### `[web-oom-leak]` UPDATE 28 — **THE PYMALLOC GROWTH IS PER-REQUEST, NOT PER-ROUTE. `/healthz` retains as fast as the artifact endpoints.**, 2026-09-07T03:0xZ `[session b2b5b45b]`

* **Per-route RETAINED pymalloc blocks, ~1,340 solo requests per worker,
  gen2-free windows only.** Among routes with a real sample (`n>=80`) the
  per-request retention spans **18.6-32.8 blocks** (pid 97) and **21.2-37.9**
  (pid 98) — a **1.8x spread, IDENTICAL on both workers**. A route-specific leak
  would be orders of magnitude apart.
* **THE LANE'S FALSIFICATION CONDITION FIRED, as written:** *"retained blocks
  spread evenly across routes"*. They do. **No route drives the arena jumps; the
  request COUNT does.**
* **`/healthz` RETAINS 26.6-28.0 BLOCKS PER REQUEST** — a trivial health check,
  and the cleanest control available. It leaks at the same rate as
  `/api/ops/artifacts/stream` and `export`. Whatever retains is in the SHARED
  request path or the interpreter, not in any handler.
* **`/api/ops/artifacts/publish` leads on TOTAL (38-41%) purely because it is
  served most** (762 and 680 of ~1,340 solo requests) — and it has the **LOWEST
  per-request rate of the four**. Ranking by total would have re-adopted an
  attribution I already retracted once today as trim-inflated. That is three
  separate times this route has looked guilty by co-occurrence and been wrong.
* **THE RECONCILIATION PASSES, which is what licenses the conclusion.** The solo
  sample covers 78-81% of requests, so scaled up it is ~42.7k and ~48.3k blocks
  against the **9.0 and 13.0 MB of arena jumps** caught on those same pids —
  **221 and 282 bytes per retained block**, against ~50-200 B for a small object
  with pymalloc overhead. Same order. The blocks measured DO account for the
  arenas, so the growth is not hiding somewhere the sample never saw.
* **CAVEAT I CANNOT CLOSE FROM THIS DATA:** this session added per-request
  instrumentation, and uniform per-request retention is exactly what that would
  look like. The phenomenon PREDATES it — `UPDATE 23` measured the growth hours
  before any of this code existed — so the leak is not mine; but I cannot say
  from these numbers how much of the ~25 blocks/request the instruments
  themselves contribute. Measuring that needs the profile toggled OFF and the
  arena rate re-read.
* **NEXT:** the target is now a SHARED per-request retainer of ~20-38 small
  objects, not a route. Candidates in order of testability: this session's own
  instrumentation (toggle it off and re-measure the arena rate — cheapest and
  also closes the caveat above), Flask/Werkzeug per-request caches, and logging.
  A route allowlist is no longer the right tool; a before/after on the shared
  path is.
### `[web-oom-leak]` UPDATE 29 — **THE LEAK IS NOT MOSTLY MINE. With every per-request instrument OFF, anon still grows 1.01-2.39 MB/min.**, 2026-09-07T04:5xZ `[session b2b5b45b]`

* **The A/B that `UPDATE 28` owed.** `SYNDICATE_REQUEST_MEMORY_PROFILE` ON vs OFF,
  two sequential arms, each measured over the SAME process-age window
  (`900-2400s`) so both sit in the same phase of the lifecycle. The measuring
  instrument — the growth detector — stayed ON in both arms, because letting an
  intervention supply its own measurement is what produced this session's
  retracted counterfactual. Request-volume skew **15%**, inside the 25% gate.
* **THE HEADLINE, and it is robust:** with the profile OFF — no per-request anon
  reads, no block counting — anon still grows at **1.01 and 2.39 MB/min**. The
  per-request retention `UPDATE 28` found is **REAL and mostly not my
  instrumentation's**.
* **THE MAGNITUDE IS NOT DETERMINED, and the mean hides why:**

        ON   pid 80  2.91   pid 79  2.39    mean 2.65 MB/min
        OFF  pid 79  2.39   pid 78  1.01    mean 1.70 MB/min

  The harness reported *"PARTIAL: 36% of the anon rate"*. But **the ranges
  TOUCH** — one OFF worker ran at exactly the rate of an ON worker — and the
  whole gap rests on OFF pid 78, whose anon **FELL** (`442.1 -> 417.3`) in its
  tail. With n=2 workers per arm, 36% is a DIRECTION, not a magnitude. No OFF
  worker exceeded any ON worker, so a contribution is plausible; its size is not
  measured. **This overlap check was NOT pre-registered** — I added it after
  seeing the arms, and it is stated as a limitation rather than folded into the
  estimate.
* **pymalloc: NO VERDICT, as pre-registered.** ON `0.362 -> ` OFF `0.000 MB/min`,
  but **1 of 2 workers jumped ON and 0 of 2 OFF** — a difference of ONE discrete
  1 MB-arena event. That gate was written after seeing the ON arm and BEFORE
  collecting OFF, precisely because a `0.000` OFF arm was always a plausible coin
  flip and would otherwise have read as *"the profile was the cause"*.
* **WHAT THIS SETTLES FOR `UPDATE 28`.** Its `~25 blocks/request` figure carries
  some instrumentation contribution that cannot be sized from here — the profile
  IS the thing that counts blocks, so turning it off removes the measurement.
  What survives is the part that matters: the shared-path retention is real,
  route-independent, and persists with all of it off.
* **DECISION: the profile stays OFF.** Its measurement job is done, it plausibly
  costs something, and web is a 2 GB service. `SYNDICATE_GROWTH_EPISODE` stays ON
  at ~4-5 ms per 15 s interval.
* **NEXT:** the target is unchanged and now cleaner — a shared per-request
  retainer that is NOT this session's code. Flask/Werkzeug per-request caches and
  logging are the candidates. If a future arm wants a real magnitude for the
  instrumentation's own share, it needs more workers or repeated windows; two
  workers and one window each cannot separate a 36% effect from worker variance.
### `[web-oom-leak]` UPDATE 30 — **RETRACTION: my block instrument over-counts 16x. `UPDATE 28`'s reconciliation FAILS, and Flask/Werkzeug are NOT the retainer.**, 2026-09-07T05:2xZ `[session b2b5b45b]`

* **THE DEFECT, measured locally where it can be run to ground.** The instrument
  reads `getallocatedblocks()` in `teardown_request`. That hook fires **BEFORE**
  the response object, the request context and the WSGI environ are released, so
  everything still alive at that instant is scored as RETAINED when most of it is
  about to die. Same 500 requests, two measurement points:

        measured AT teardown_request (what the instrument does):  64.7 blocks/req
        measured AFTER the request fully returns (ground truth):   4.1 blocks/req

  **A 16x over-count.** After a `gc.collect()` the true figure is **under 1
  block/request**.
* **RETRACTED from `UPDATE 28`: "~19-38 blocks retained per request".** That is
  per-request SCAFFOLDING counted at the wrong point in the lifecycle, not
  retention.
* **RETRACTED from `UPDATE 28`: "the reconciliation PASSES ... 221 and 282 bytes
  per retained block ... same order as a small object".** I called that the thing
  that *licensed the conclusion*. Corrected for the 16x, the same arithmetic
  gives **3,539 and 4,516 BYTES PER BLOCK** — and **pymalloc only handles objects
  <= 512 B, so that is impossible.** The retained blocks I measured **CANNOT**
  account for the arena growth. The reconciliation passed only because its
  numerator was inflated.
* **WHAT SURVIVES `UPDATE 28`, and it is now better explained:** *no route
  dominates*. Retention looked uniform across routes including `/healthz` because
  the instrument was largely measuring FRAMEWORK per-request objects, which are
  uniform by construction. The conclusion stands; the stated reason was wrong.
* **`UPDATE 29` IS UNAFFECTED.** That A/B compared the **anon rate**, not blocks,
  so the "leak is not my instrumentation" result does not depend on this.
* **THE QUESTION ASKED — Flask/Werkzeug caches — IS ANSWERED: NO.** Locally,
  after full request completion, `/healthz` retains `4.1` blocks/request raw and
  **under 1 after GC**, against a production-instrument reading of `26.6-28.0`.
  Toggling both my flags moved it not at all (`2.0` / `1.0` / `2.3` blocks/req).
  Per-request framework caches are not the retainer.
* **THE REFRAME, and it is the useful part.** Arena count is driven by **PEAK
  SIMULTANEOUS live blocks, not retained blocks.** A transient burst that needs
  17 MB of concurrently-live small objects forces 17 new arenas, and pymalloc
  rarely returns an arena to the OS — so a big TRANSIENT permanently grows the
  arena. My instrument measured the wrong quantity for the question it was built
  to answer.
* **NEXT:** `blocks_max` is already recorded per route and is much closer to the
  right quantity (local `/healthz` peak: 131). The hunt is for peak concurrent
  allocation, not for something that leaks. Fixing the instrument means measuring
  in WSGI middleware wrapping the full call — after `close()` — rather than in
  `teardown_request`, which is the last Flask hook but not the last thing to run.
### `[web-oom-leak]` UPDATE 31 — **STEADY-STATE RETENTION IS ZERO. The arena is driven by a PEAK, and one route peaks at 44,007 blocks in a single request.**, 2026-09-07T07:3xZ `[session b2b5b45b]`

* **The table re-read with the FIXED instrument (`8bcdef11`), as a DELTA between
  two warm snapshots** — cumulative totals are useless here: on this deploy
  `retained_blocks` read `663,143` at n=34 and `663,803` at n=239, so the first
  34 requests carried ~19,500 blocks each (caches, lazy imports) while the next
  205 averaged **3.2**. Reading the cumulative figure would have republished boot
  as a leak.

        pid 78   +794 solo requests   TOTAL RETAINED    -18 blocks  = -0.0/req
        pid 79   +722 solo requests   TOTAL RETAINED  +3,969 blocks = +5.5/req

  Local ground truth was `4.45/req`, so **the fix transfers from `test_client` to
  gunicorn**. Steady-state per-request retention is **~0**. There is no
  per-request leak.
* **`UPDATE 28` IS CONFIRMED AS AN INFLIGHT MEASUREMENT.** The renamed
  `blocks_inflight` column reads **17.1-30.7/req** here, against UPDATE 28's
  reported "18.6-37.9". Same quantity, same numbers — it was measuring
  per-request scaffolding and calling it retention. The retraction in `UPDATE 30`
  is now corroborated by the corrected instrument, not just by a local test.
* **THE RECONCILIATION FAILS, exactly as `UPDATE 30` predicted:**
  * pid 79: `7.0 MB` of arena jump against ~`5,150` retained blocks =
    **1,425 bytes per block**, and pymalloc caps at 512 B.
  * pid 78 is the cleanest case available: **`53.0 MB` of arena growth against
    NET `-18` blocks retained.** Retention cannot account for the arenas at all.
* **THE PEAK COLUMN IS THE LEAD, and it is very concentrated:**

        route                             peak blocks (78/79)   calls
        /wnba/api/live_player_boxscore       44,007 /  3,277      9 / 11
        /api/ops/memory                       3,370 /     43      5 /  8
        /api/ops/artifacts/export               761 /    114     63 / 77
        /api/ops/artifacts/publish              701 /    277    493 /428
        /healthz                                148 /    145    142 /132

  **`/wnba/api/live_player_boxscore` peaks 13-60x above every other route**, on
  9-11 calls. At 64-128 B per small object that is **2.7-5.4 MB of simultaneously
  live objects in ONE request** — and arenas are allocated to cover the peak,
  which pymalloc then rarely returns.
* **AN ARITHMETIC COINCIDENCE THAT IS A HYPOTHESIS, NOT A RESULT:** pid 78's
  `53 MB` jump would need **10-20** such requests, and that route was served
  **9** times in the window. Suggestive and the right order — but I have NOT
  shown the jump coincided with those calls, and this is the same route-shaped
  reasoning that made `/api/ops/artifacts/publish` look guilty three times and be
  wrong each time. **It needs a direct test:** correlate the episode timestamp
  against that route's calls, or call it in isolation and watch the arena.
* **NOTE the peak asymmetry between workers** — `44,007` on pid 78 vs `3,277` on
  pid 79 for the same route. Either the work is input-dependent (a big game vs a
  small one) or one call did something the others did not. That difference is
  itself measurable and worth resolving before acting.
* Profile returned to **OFF** after the reading, per `UPDATE 29`.
### `[web-oom-leak]` UPDATE 32 — **THE DIAGNOSTIC RING IS A PEAK GENERATOR: ~18,600 simultaneously-live objects per checkpoint, ~15x/min, retaining nothing.**, 2026-09-07T08:1xZ `[session b2b5b45b]`

* **Tested `/wnba/api/live_player_boxscore` in isolation** — `UPDATE 31`'s lead.
  It peaks **196x the control** locally but moved the arena **+0.0 MB**. The lead
  is NOT confirmed, and I am not calling it the cause.
* **Its SIBLING is the one that grows the arena.**
  `/wnba/api/final_player_boxscore`, order-independent, two controls flat:

        order reversed, n=20      final  +2,321.9 blocks/req   arena +16.0 MB
                                  live      +69.0 blocks/req   arena  +0.0 MB
                                  healthz    -1.4 blocks/req   arena  +0.0 MB

        4 successive batches of 20:   +347.6 -> +10,589.9 -> +17,134.0 -> +18,536.1 /req
                                      arena  +0.0 -> +38.0 -> +13.0 -> +33.0 MB

  **It ACCELERATES**, which is the signature of an O(n) cost over something that
  is itself growing.
* **`tracemalloc` names the chain, at 100% coverage** (244,637 of 243,443 blocks):

        route -> pipeline/intelligence_state.py:5958 _diag_log_all_process_memory
              -> memory_observability.py:2174 log_and_persist_process_memory
              -> memory_observability.py:2049 dump_process_memory_checkpoint
              -> refresh_state_store read_json_file -> json.loads  **+11.32 MB**

  `dump_process_memory_checkpoint` **READ-MODIFY-WRITES THE WHOLE RING**: it
  `json.loads` the entire file, appends one record, truncates to 300, re-encodes
  and writes it back — on every checkpoint.
* **AT THE DESIGNED SIZE, which is what matters for production.** Reconstructed
  the ring exactly as documented (300 records, 6 container processes) — 359 KB
  at **1,224 B/record against the docstring's 1,233**:

        json.loads        peak  +18,620 blocks SIMULTANEOUSLY LIVE
        + re-encode       peak  +18,644 blocks
        retained after            +11 blocks

  **It retains nothing and peaks enormously**, ~15 times a minute. `UPDATE 30`
  and `31` established that arena count follows PEAK simultaneous live blocks and
  that pymalloc rarely returns an arena. For scale, the production
  `blocks_inflight_max` measured 3,370 (`/api/ops/memory`) and 44,007
  (`live_player_boxscore`) — 18,600 sits squarely between them.
* **THE DIAGNOSTIC MACHINERY BUILT TO INVESTIGATE THE OOM IS A PLAUSIBLE DRIVER
  OF IT.** The ring's docstring reasons carefully about the WRITE cost ("~1.1MB
  rewritten ~15x/min on a memory-constrained worker"); the READ side, which
  materialises ~18,600 live objects each time, is not considered anywhere.
* **WHAT DOES NOT TRANSFER, stated because the local numbers are dramatic.** The
  84 MB of arena growth from 80 local calls is inflated by process count: each
  local record embeds **337 Windows processes with cmdlines** against Render's
  **~6**, roughly 50x. **The local MAGNITUDE is not a production number.** What
  transfers is the MECHANISM and the designed-size figure above.
* **STILL NOT PROVEN:** that this accounts for production's arena jumps. I have a
  mechanism, a chain and a plausible magnitude — not a production measurement.
  The direct test is to correlate a `GROWTH_EPISODE` timestamp against checkpoint
  writes, or to cut the ring's read cost and re-measure the arena rate.
* **SEPARATE DEFECT, seen in the same trace:** the route emits
  `WARNING: compute in request path (operation=wnba_has_games_for_date_espn_fetch)`
  — a live upstream fetch inside a Flask handler, which `CLAUDE.md`'s
  load-bearing rule forbids outright.
### `[web-oom-leak]` UPDATE 33 — **THE RING CUT IS WORTH 38 MB PER WORKER, MEASURED, RANGES SEPARATED.**, 2026-09-07T17:2xZ `[session b2b5b45b]`

* **A/B on the diagnostic-ring cut, both arms running the SAME runtime code**
  (toggled by `SYNDICATE_RING_KEEP_CMDLINE`, so the control did not require
  deploying a stale commit):

        arm    pids   pymalloc@600s  @1200s  @1800s
        FAT     2         209.0       209.0   209.0
        SLIM    2         170.0       170.0   171.0

* **`-38 MB` per worker at every age point, and the PER-WORKER RANGES DO NOT
  OVERLAP** (`max(SLIM) 176 < min(FAT) 198`). Volume skew **14%**, inside the
  gate. **~76 MB of a 2,048 MB container, 3.7%.**
* **The separation check was in the harness BEFORE either arm ran.** `UPDATE 29`
  had to add it afterwards, having nearly called a coin flip a result; this time
  a mean difference alone would not have been reported.
* **`UPDATE 32`'s MECHANISM IS CONFIRMED AS LOAD-BEARING, not just real.** The
  ring's read-modify-write was not merely an expensive thing that existed —
  halving its peak measurably lowered the arena. The diagnostic built to
  investigate this OOM was contributing ~38 MB per worker to it.
* **AND THE MAGNITUDE IS NOT EXPLAINED.** The cut removes 9,002 blocks per
  checkpoint (~0.86 MB at 100 B) and the arena fell **44x** that. Unverified
  candidates: `GUNICORN_THREADS=4` concurrent peaks, per-size-class arenas that
  cannot be reused across classes, and the peak recurring ~15x/min through the
  ramp. **The measurement stands; the multiplier is an open question and should
  not be quoted as understood.**
* **METHOD NOTE:** pymalloc was FLAT across the window in BOTH arms (`209.0` at
  all three FAT ages), so this compares plateau LEVELS, not ramp rates — the
  arena reaches its ceiling before age 600. The plateau is set by ramp-phase
  peaks that were not directly observed.
* limits: n=2 workers per arm, one pair, not repeated. A peer's 13-file /
  947-insertion landing between arms was checked and touches **zero** runtime
  files.
### `[web-oom-leak]` UPDATE 34 — **RETRACTION OF `UPDATE 33`: the arms were NOT comparable, and the mechanism cannot produce 38 MB.**, 2026-09-07T18:0xZ `[session b2b5b45b]`

* **I set out to explain `UPDATE 33`'s 44x multiplier and the explanation
  falsified the result instead.** Two independent checks, both against the
  measurement I had just published.
* **CHECK 1 — the mechanism is ~60x too small.** My hypothesis was pymalloc POOL
  fragmentation: pools are per-size-class and an arena frees only when every pool
  in it is free, so a peak could strand `POOL_SIZE` per straggler. **Measured
  directly out of `_debugmallocstats`** rather than argued:

        FAT   json.loads  +76 pools  1.26 MB live  ->  1.19 MB of pools
        SLIM  json.loads  +35 pools  0.66 MB live  ->  0.55 MB of pools
        the cut removes  41 pools, 634 KB live
        pool bytes / live bytes = **1.1x**, not 44x

  **Pools are nearly fully packed. There is no fragmentation amplification.** One
  checkpoint's cut saves ~`0.64 MB` of pool footprint — the mechanism can produce
  well under 1 MB, not 38. (Note this build reports **16,384-byte pools**, not the
  4,096 I first assumed; the arithmetic I nearly published was wrong twice over.)
* **CHECK 2 — the arms differed in memory the cut CANNOT TOUCH.** At age 1800 s:

        arm    pymalloc   total anon   NON-pymalloc anon
        FAT      209.0       563.2          354.2
        SLIM     171.0       491.8          320.8
        delta    -38.0       -71.4          **-33.4**

  The cut removes pymalloc-domain allocations only. It cannot change the glibc
  arena, `.so` private-dirty or thread stacks. **A 33.4 MB gap there — 47% of the
  total anon difference — proves the two arms did not see the same workload.**
* **SO `UPDATE 33`'s "38 MB per worker" IS RETRACTED.** The separated per-worker
  ranges and the 14% volume gate BOTH passed and the result was still confounded.
* **WHY THE GATE MISSED IT, and this is the transferable lesson: I gated on
  REQUEST COUNT, which is not WORK PER REQUEST.** The arms ran ~50 minutes apart;
  a lighter game slate gives the same request count with far less allocation per
  request. Every future arm on this service needs a work proxy — payload bytes,
  or a non-target memory term used as a control — not a request tally.
* **WHAT SURVIVES.** The ring cut is still a real, deterministic reduction:
  `18,644 -> 9,642` blocks and `360 -> 151 KB` per checkpoint, measured locally
  and reproducible. It removes data that is redundant by construction (`cmdline`
  is constant per pid, stored up to 300 times), so it stays. **What is withdrawn
  is its production VALUE, not its correctness.** On the pool measurement its
  true worth is ~`0.6 MB` of transient footprint per checkpoint, ~15x/min — real,
  small, and nothing like 38 MB.
* **`UPDATE 32` NEEDS THE SAME DISCOUNT.** The ring is a peak generator, and that
  measurement stands; but "plausible driver of the OOM" rested on the arena
  response now retracted. It is a contributor of ~0.6 MB per checkpoint.
### `[web-oom-leak]` UPDATE 35 — **THE RING IS INERT ON WEB. It never writes a checkpoint, so the cut could not have affected web's memory and `UPDATE 32`'s premise is wrong for web.**, 2026-09-07T18:2xZ `[session b2b5b45b]`

* **MEASURED, two ways.** `ring_cost` — the per-checkpoint accounting deployed in
  `224dc5a8` — is **ABSENT on both web workers** (pids 77 and 78) after live
  traffic, and a collector polled for ~5 minutes without ever seeing it. The env
  says why: **`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP='false'` on
  web.** No loop, no `_diag_log_all_process_memory`, no checkpoint.
* **SO THE RING IS A REFRESH-WORKER COST, NOT A WEB COST.** `#632` is about
  WEB's OOM. **The ring cannot be a contributor to it.**
* **`UPDATE 32` IS WRONG FOR WEB.** "The diagnostic machinery built to
  investigate the OOM is a plausible driver of it" describes a code path web does
  not execute. The mechanism is real and the local measurement stands — it is
  simply about the refresh-worker.
* **AND THIS EXPLAINS `UPDATE 33` STRUCTURALLY.** That A/B toggled
  `SYNDICATE_RING_KEEP_CMDLINE` on web and read a 38 MB arena difference. **The
  treatment was INERT on web, so the difference was NECESSARILY confound.**
  `UPDATE 34` retracted it on evidence (47% of the gap in memory the cut cannot
  touch); this is the reason that evidence looked the way it did. Two independent
  routes to the same retraction.
* **WHY THE LOCAL REPRODUCTION MISLED ME.** Locally the app is not a Render web
  dyno, so `_start_background_loops()` DOES run and the route really did reach
  the checkpoint — `tracemalloc` traced it honestly. **The trace was true of my
  laptop and false of production web**, and nothing in the trace could say so.
* **THIS IS `[project_which_service_runs_the_code]`, and I had it in front of
  me.** Loop ownership is an env flag that moves with no diff. I built THREE
  experiments on web — an arena A/B, its retraction, and a per-checkpoint A/B —
  before checking whether web runs the code under test. The check that settled it
  took one request and one env read.
* **WHAT SURVIVES.** The cut is still correct and still worth having: `18,644 ->
  9,642` blocks and `360 -> 151 KB` per checkpoint, deterministic, removing data
  redundant by construction. **Its beneficiary is the REFRESH-WORKER**, where the
  loop runs and the checkpoint fires ~15x/min. It is live there by default (the
  flag was only ever set on web).
* **NEXT, if the ring is worth pursuing:** run the `ring_cost` A/B on
  **refresh-worker**, not web. The instrumentation is deployed and service-
  agnostic. And for `#632` proper, the ring is now eliminated as a web-OOM
  candidate — the field is clear again.
### `[web-oom-leak]` UPDATE 36 — **THE RING A/B IS DEFERRED: refresh-worker has NO quiet window, and waiting cannot create one.**, 2026-09-07T20:0xZ `[session b2b5b45b]`

* **MEASURED, 75 minutes of polling.** A waiter watched refresh-worker for both
  conditions — claim free AND no job in flight — and **never found a clear
  moment**. Board builds started at `18:57, 19:05, 19:10, 19:23, 19:30, 19:35,
  19:39, 19:46` (every **5-8 minutes**), interleaved with MLB sims
  (`tip_off_window`, `fingerprint_change`, `props_now_available`) and odds
  refreshes. The claim itself freed several times; a JOB was in flight every
  time.
* **WAITING CANNOT SOLVE IT, and that is the finding.** A deploy takes ~5 minutes
  to go live while builds start every 5-8. **Even catching a gap lands the
  restart inside the NEXT build**, so a tighter poll does not help. The
  experiment needs a genuinely quiet period (overnight / no games) or a
  deliberate decision to kill one board build per arm. **Same shelf and the same
  reason as `scripts/malloc_trim_ab.py`** — now confirmed on a second service.
* **DEFERRED WITH A RUNNABLE HARNESS**, not a note: `scripts/ring_cost_ab.py`
  (`plan` / `read FAT|SLIM` / `compare`). It reads via the **Render logs API**
  because refresh-worker has no HTTP server, drops lines whose `keep_cmdline`
  belongs to the other arm, **gates on ring length** (the read cost scales with
  it), and reports the SPREAD — refusing a verdict when ranges overlap even at N
  in the hundreds.
* **A MISTAKE I MADE AND UNDID.** I set `SYNDICATE_RING_KEEP_CMDLINE=1` on
  refresh-worker BEFORE checking the claim, which a peer held. An env change is
  inert until a deploy — so it would have ridden along on **their** deploy and
  silently switched their service to the fat records. Reverted to `0` within the
  minute. **Setting config on a service another session holds is the same class
  of error as deploying into their window; the flag just makes it quieter.**
* **AND THE VALUE IS LIMITED EVEN WHEN IT RUNS.** `UPDATE 35` established the
  ring is inert on web, so this measures the WORKER's efficiency. `#632` is a WEB
  OOM and the ring is already eliminated as a candidate for it. Worth doing for
  the 4 GB worker's own sake; it will not move the OOM investigation.
* **NOT held, NOT pending:** no claims held, and no env change left on any
  service (web `RING_KEEP_CMDLINE='0'`, `REQUEST_MEMORY_PROFILE='off'`,
  `GROWTH_EPISODE='1'`).
