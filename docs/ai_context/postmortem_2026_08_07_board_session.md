# Post-mortem — 2026-08-06/07 board session

**What I broke, what I got wrong, and what I assumed without checking.**

Written at the user's instruction. Its purpose is that the next session does not
repeat any of it. Read it before touching refresh-worker or the Layer 2 board.

---

## 1. WHAT I BROKE (production impact)

### 1.1 refresh-worker restart loop — the serious one

**Days of stability, then restarts within hours of my changes.** The user
identified this before I did.

| window | BOOTED | worker deploys |
|---|---|---|
| 18:00–20:00Z (before my changes) | **0** | 0 |
| 22:00–00:00Z | 2 | 2 |
| 01:00–03:10Z | 6 | 2 |
| 03:34–03:56Z | 3 | 1 |

**Cause: `#241`.** I moved `pull_hot_artifacts` into the intelligence-state
background loop on a **120-second timer**. Before that it ran only inside
`_build_candidate_pool`, on a cache miss — rarely.

`pull_hot_artifacts` performs a bulk `/export` fetch that the worker
**`json.loads()` whole**. The code's own comment, which I had read, says it is
"unbounded on the worker too" and cites it as the cause of a previous
refresh-worker OOM. I put that on a 2-minute timer inside a process that
`handoff_refresh_worker_oom.md` documents as plateauing at **2.65–2.70 GB of
4 GB — ~1.4 GB headroom**.

**Reverted** in `94600923`, `d5028810`, `0d7c839c` (reverting `#241`, `#241
follow-up`, `#237`).

### 1.1a CORRECTION — the revert did NOT stop the restarts

Measured after the revert deployed at 04:08:13Z: **BOOTED at 04:12:58 and
04:15:39** — the same ~3 minute cadence. So `#241` is **not proven** to be the
cause, and my attribution above was another count-without-a-control.

What is still true: restarts began during this session (0 in 18:00–20:00Z,
before any of my changes) and the periodic pull was a genuine and documented
memory risk that should not have been added. Removing it was correct on its own
merits. But **the cause is unconfirmed and still live.**

Remaining suspects, none eliminated:
- **`#238`'s de-vig**, which runs on the worker during every board build.
  `market_sides_for_quote` scans and copies the identified rows *per quote*, on
  top of `read_book_quotes` already materialising ~122k dicts from a 90MB shard.
  This is the largest new per-build allocation and it was never load-tested.
- `#239`'s soccer lookahead adds 7 paths to the repair pass each cycle.
- Something unrelated to this session that began around 20:00–22:00Z.

**Next session: do not assume the cause. Bisect it.** Restarts leave no
traceback, no OOM line, and memory samples sit at 67–68.8% — so the sampler is
missing the spike, and the useful signal is what runs immediately before
`Instance restarted` (consistently `PERSIST_LOCKED_BEGIN`, i.e. the end of a
board build).

### 1.1b RESOLVED 2026-08-07 (#249) — and three claims in §1.1/§1.1a were false

Fixed in `431fc5a9`. Corrections to what is written above, because the two
paragraphs preceding this one sent the next session looking in the wrong place
with the wrong tools:

1. **"`Cause: #241`" (§1.1) was wrong, and §1.1a was right to withdraw it — but
   `#241` is now positively *exonerated*, not merely unproven.** It was live
   from 00:26 to 02:46 (**2h20m, zero OOM events**). The first OOM is
   **02:56:28**, three minutes after `75b79b8a` deployed at 02:53. Nine deploys
   that evening preceded it with no kills. The revert was therefore not just
   ineffective, it removed working code for no reason.
2. **"There is no OOM line" is false.** Every single restart is `server_failed`
   carrying `reason.oomKilled.memoryLimit = "4Gi"`. It lives in the Render
   **events** API (`GET /v1/services/{id}/events`), which was never queried —
   only the log stream was. 21 kills were sitting there, already labelled.
3. **"The sampler is missing the spike" is false.** The `CONTAINER_MEMORY`
   instrumentation catches it precisely. The 67–68.8% readings are the *middle*
   of a cycle; the end of one reads
   `nhl 3496MB 85.4% -> soccer 3947MB 96.4% -> soccer 4096MB 100.0%`. The data
   was already in production logs at the time that sentence was written.

**The actual cause** was not in any of the suspect commits. The circuit breaker
`_abort_build_candidate_pool_if_memory_critical` had a **900MB** floor — sized
for a 2GB container and a 350–450MB stage — in front of a stage that transiently
peaks at **~1873MB** on the 4GiB worker. It fired once in 1200 log lines, at
3629MB. So `#247` did not *introduce* a leak; the guard had been unable to stop
this class of failure for as long as the container had been 4GiB, and something
around that deploy pushed the pass over a line the guard was not watching.

**The methodological lesson, and it is the same one as §5.0:** three separate
"we cannot know this" statements were all answerable from data that already
existed. Two required querying a different API endpoint; one required reading
to the end of a log cycle instead of sampling the middle. *Absence of evidence
in the one place you looked is not evidence of absence.*

### 1.1c MEASURED 2026-08-07 — the real per-build cost, and §1.1a's "prime suspect" was wrong

Asked by a third session to check for a cache in `read_book_quotes`. There is
none — and looking for it found something bigger.

**MEASURED (source):**
- `read_book_quotes` has **no cache of any kind**. No `lru_cache`, no
  module-level dict, no memoised loader. It opens the file, `json.loads` each
  line, returns a fresh list.
- `_QUOTE_CACHE_KEY = "_quote_rows_cache"` (`quote_enrichment.py:44`) is
  **declared and never used anywhere**. The original author anticipated exactly
  this and never wired it.
- `read_book_quotes` has exactly **one** caller: `quote_ref_for_bet`
  (`odds_book_quotes.py:757`), as its **first statement**.
- `quote_ref_for_bet` is called from **three** sites in `quote_enrichment.py`
  (258, 363, 486) and **every one is inside a `for row in rows:` loop**.

⇒ **Every enriched row re-reads and re-parses the entire shard.** MLB's is
90,155,656 bytes / ~122k rows. At ~200 candidates that is ~200 complete
materialisations of a 122k-dict list per board build.

This predates me (original `#215` code). What I changed: **`#235` added
`enrich_prop_rows` to the intelligence prop lane**, multiplying how often it runs
*on refresh-worker*. I did not add the per-call read; I made it hotter.

**INFERRED (untested):** this is the mechanism behind the reported "+2.9GB in 73s
that does not come back down". Hundreds of large short-lived allocations
fragment pymalloc arenas; glibc does not return them to the OS, so `anon`
ratchets while nothing is actually retained — retention-shaped RSS from pure
transient churn. Falsify cheaply: loop `read_book_quotes` N times against the
real shard holding no reference and watch RSS.

**Fix shape:** hoist the read out of `quote_ref_for_bet` and pass rows in, or
wire the cache `_QUOTE_CACHE_KEY` was meant for, keyed `(sport, date, mtime)`.
One read per sport per build instead of one per row.

**AND: §1.1a's "prime unexamined suspect: `#238`'s de-vig" was wrong.**
`market_sides_for_quote` receives `identified` — the output of a *hard* identity
filter (event_id / player_name / team pair) — not the 122k row set. For a player
prop that is tens of rows. It is O(quotes × identified), bounded and small next
to the per-row full-shard read above. I named it "prime suspect" having never
measured it; the source says it is not. Deprioritise it.

### 1.2 Things I shipped that made the board *look* fixed while it wasn't

- `#242`: I rendered suppressed values as real ones. `Number(null)` is `0` and
  `0` is finite, so every correctly-suppressed fair price displayed as
  **"0 at 0.0% hold"** — a missing value wearing a number's clothes, which is
  worse than a blank because it looks authoritative. The user caught it.
- `#244`: I wrote the dead-market staleness rule **twice, in two languages**
  (Python + JavaScript) because I did not trust my own server-side stamp to be
  fresh. Two rules that can disagree. Removed in `#245`.

---

## 2. WHAT I GOT WRONG (claims I made that were false)

Each of these was stated to the user as a finding before being checked.

### 2.1 "Publishing is failing right now — a systemic break"
**False.** I counted 100 `PUBLISH_FAILED` in one hour and called it systemic.
The full measurement: **1000 `PUBLISH_OK` vs 223 failed**, and every failure
burst landed at 01:33 and 01:54–55 — **exactly my own two web deploys**
(finished 01:34:06 and 01:55:10). The 74 MB shard specifically was 127 OK / 9
failed. I measured failures without measuring successes, and without checking my
own deploy log. It was Phase 0 of the plan; the premise was invented.

### 2.2 "The settlement cadence is broken — it hasn't run in 15 hours"
**False.** `_evaluation_settlement_should_run_now` is *designed* to run once per
Central day at 06:00 and to self-catch-up. 11:03 UTC = 06:03 Central. It ran
exactly on schedule. I read a designed cadence as a fault.

### 2.3 "Settlement grades nothing"
**False.** It emitted `closing_rows=7316 graded_rows=192` for the current slate
at 23:07. I had been reading `/api/ops/evaluation-settlement/status`, which
reports **whatever refresh-worker last wrote** and is therefore stale by
construction. I treated a status artifact as live state.

### 2.4 "Soccer captures no book quotes"
**False.** Soccer captures plenty — it shards by **fixture date**, so the quotes
for the 8th live in `2026-08-08.jsonl`. The puller only ever asked for today,
got a 404, and logged "absent", which I read as "does not exist". (`#239` fixed
the pull; the diagnosis in between was wrong.)

### 2.5 "The 75 MB duplicated payload is causing the persist spike"
**False.** A compaction mechanism already exists and already aliases
`response.analysis`, trims the 1.98 MB evaluation record, and collapses
duplicate lists — **8.9 MB → 2.4 MB persisted**. The 75 MB is the *serve-time*
payload, not what the worker writes.

### 2.6 "716 arbitrage opportunities"
**False**, and I caught this one myself before reporting it as fact. Three bugs
in my own measurement: spreads are **signed per side** (home −1.5 pairs with
away **+1.5**), 3-way markets need their **draw** leg, and the shard is an
all-day append log so "freshest per book" pairs a pregame price with an
8th-inning one. After correction: **~3 real arbs**. Requiring simultaneity
dropped **88%** of raw pairs.

### 2.7 "0 of 138 priced" (inherited from the previous session, repeated by me)
Stale. The board was partially priced; the *prop lane* specifically was not.

---

## 3. ASSUMPTIONS I MADE WITHOUT CHECKING

1. **That a status endpoint reports live state.** It reported the last thing a
   different service wrote. (§2.3)
2. **That a failure count is a failure rate.** No success denominator, no
   correlation against my own deploys. (§2.1)
3. **That a cadence I did not read was broken.** (§2.2)
4. **That adding periodic work to the worker was free.** It has ~1.4 GB of
   headroom and one serial process. This is *the* documented constraint in
   `CLAUDE.md`, and I planned without reading
   `runtime_execution_model.md` / `worker_architecture.md`. (§1.1)
5. **That "a whole file re-fetch every 2 minutes" was cheap** because a 304 makes
   the *no-change* case cheap. On a live slate the shard changes constantly, so
   the 304 path essentially never fired.
6. **That fixing one call site fixed the lane.** `#235`: I enriched
   `/api/home`'s prop lane and the board's, and the board still read zero,
   because the pool was served from cache.
7. **That the board I was measuring was the board the user sees.** I verified
   card view; the **blotter** is the default above 900px and had none of the
   price columns. Three rounds of "fixed and verified" were on a surface the
   user does not land on. (`#240`)

---

## 4. WHAT IS ACTUALLY SHIPPED AND SOUND

Keep these; they are verified and add no worker load.

| item | what | verified |
|---|---|---|
| `#236` | WNBA put the whole display pick in every identity field | 4/4 rows now join |
| `#238` | **No-vig fair value.** EV was measured against a vigged price; median hold 6.25%, so every EV was ~3.1 points low | 10/10 rows priced offline; live on the board |
| `#239` | soccer fixture-date lookahead (paths only) | 0/3 → 3/3 priced |
| `#240` | blotter price columns (Book/Fair/EV/Age) | rendered live |
| `#242` | `Number(null)` → fake zeros | zero fake zeros live |
| `#243` | two boards + blended score with visible components | 230 → 34 opportunity rows |
| `#245` | **one eligibility gate, pure, run at serve time** | 20 dead markets removed live |
| `#246` | settlement inputs allowlisted | unverified |
| `#247` | **settlement's market gate blocked every prop match** | unverified in prod |
| `#248` | tail reads for append-only shards (90 MB → KB) | verified live |

`#247` is the one to verify first next session — it is the likely unlock for
`settled: 0`.

---

## 5. THE RULES THAT WOULD HAVE PREVENTED ALL OF IT

0. **Do not attribute a regression without a control.** I blamed `#241`,
   reverted it, and the restarts continued (§1.1a). A correlation with my own
   changes is a hypothesis, not a cause.
1. **A rate is a measurement; a count is an anecdote.** Always compute the
   denominator, and always check your own deploys before calling anything
   systemic.
2. **A status artifact is not live state.** Ask who wrote it, when, and on which
   disk.
3. **Read the cadence before calling it broken.**
4. **New periodic work on refresh-worker is never free.** ~1.4 GB headroom, one
   serial process, autoruns in an `elif` chain. State the cost or do it at serve
   time.
5. **Verify on the surface the user actually looks at.** The blotter, at desktop
   width — not the card view, not the API payload.
6. **Absent must never render as a value.**
7. **One rule, one place.** If you are writing the same rule twice, the design is
   wrong.
8. **Measure before and after on the same instant.** Most of the wrong findings
   came from comparing a live read against a stale artifact.
