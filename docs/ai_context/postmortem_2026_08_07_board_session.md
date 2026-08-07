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

### 1.1b-RETRACTION — `#247` is NOT implicated, and neither is any single deploy

The paragraph above says "something around that deploy pushed the pass over a
line the guard was not watching." That framing is withdrawn. It let `#247` sit
in §4 as verified-and-sound while §1.1b implied it was the trigger, and `#247`
is a settlement market-gate fix that touches no memory path whatsoever. The
02:53 deploy carried ~40 commits; naming the newest one is attribution by
proximity, which is precisely §5.0's error committed a second time.

A third session proposed `#232` instead — it added `book_quotes` to
`_required_daily_artifact_paths`, finally delivering the 90MB shard to
refresh-worker and making a long-standing uncached per-row read expensive there
for the first time. The mechanism is right and it is the best available account
of *why the read costs anything on this service at all*. **But the timing does
not support a deploy trigger either**, and this is measured:

```
20:51:22Z  #232 (e5b1a8cb) deployed to refresh-worker
21:50:04Z  repair pass logs ABSENT for nba/nhl/ncaaf/ncaab/soccer
           and NOT for mlb/wnba/nfl -> those three shards were ALREADY local
02:56:28Z  first OOM
```

The repair pass only fires for files that are missing, so MLB's shard was on the
worker by 21:50Z — **five hours before the first OOM**, and across several
deploys that produced none. So shard *presence* is necessary and not sufficient.

**The likeliest remaining explanation is gradual, not a deploy at all:** the
shard is append-only and grows all day, and one read costs ~6.3x its byte size
(measured, below). At 21:50 it is small; by 02:53 it is 90MB, i.e. ~572MB per
read. The OOM begins when shard size x that multiplier, plus the rest of the
board build, crosses 4GiB. That predicts onset drifting later each day as the
slate starts, and it is falsifiable: log the shard's size against OOM onset over
two days. **Nobody has done that yet. Until someone does, "why now" is open, and
three separate confident answers to it have now been wrong.**

#### ANSWERED 2026-08-07 14:31Z — and my retraction above conflated two claims

The shard-growth account in this section is **also wrong**, and so is the part of
my `#247` retraction that went too far. Both corrected here rather than edited
away, because the shape of the error is the point.

**What it actually was:** the settlement autorun crash-looped. It reads 21 days
of ledger into one list, a *diagnostic* then re-reads all 21 chunks whole
(`read_text().splitlines()` on the same 367MB and 480MB files, to produce a line
count), and the status file is written **after** all of it. Combined with a gate
whose own docstring says it is "self-catching-up by construction", a kill
mid-run means the status never advances and it fires again on the next boot.
~4 minutes per iteration, for eleven hours. Resolved by `#253` (retention:
≤96 retained cards contexts → ≤2) plus disabling the autorun; 77 minutes clean,
container memory 2508–3102MB → 380–870MB.

**Where my retraction was right, and where it overreached.** I withdrew "`#247`
pushed the pass over" as attribution-by-proximity in a ~40-commit deploy. That
was correct on the evidence I had: proximity without a mechanism is not a cause.
But I then wrote that `#247` "touches no memory path whatsoever" and treated it
as fully exonerated, and **that was a second claim I had not tested.**

`#247` is the **trigger, not the leak.** It unblocked 4,560 of 8,276 records
from `no_key_match`, so every settlement run afterwards drove thousands of
`_replace_ledger_line` read-modify-writes over those same chunks. The control is
clean and is the strongest single piece of evidence anyone produced: **`#243`
has the identical 21-day reads *without* the matching and ran 73 minutes clean.**

So the honest verdict is neither "it was `#247`" nor "`#247` is irrelevant" —
it is that a correctness fix fed work into an uncapped, non-idempotent path, and
the path was the defect. I collapsed those into one claim in both directions on
the same night.

**Rule this earns, stronger than "don't attribute without a control":**
*retracting a wrong attribution is not the same as establishing innocence.*
"Not proven guilty" and "proven not guilty" are different findings, and writing
the second when you have only the first is how a real trigger gets protected
from investigation for hours. Say which one you have.

**Attribution caveat on the fix itself, kept deliberately:** the winning hour
contained a rollback, two env changes and a four-commit build. `#253` is
credited by *mechanism* plus the `#243` control (which held neither `#253` nor
`#254`, ran with settlement already disabled, and still died 5 times in 18
minutes) — **not** by an isolated window. Do not upgrade this to "proven" in a
later summary.

#### 1.1c-ENV — an unrecorded factor in the ONSET, and it was mine (not a commit)

Added at session close by the board session. Every attribution attempt above
bisected **commits**. One input that night was not a commit, and it is not in
any account so far.

**MEASURED:**
- At ~02:47Z I set `EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS=3600` on
  refresh-worker, to force settlement off its designed once-per-Central-day
  06:00 gate for diagnosis.
- Env changes require a deploy, so it was **injected by the 02:53:15Z deploy** —
  the same deploy everything else has been attributed to.
- **First OOM: 02:56:28Z**, ~3 minutes later.
- The var is **no longer set** (removed by another session; likely one of the
  "two env changes" in the winning hour noted above).

**INFERRED, and deliberately limited:** the settlement autorun is now
established as the crash-looping leak. My change multiplied how often that exact
operation was attempted by **24×** (daily → hourly), and in interval mode
`last_epoch` was ~15h old, so it would fire on the **first cycle after boot**
rather than at 06:00 the next morning. That is a credible account of *onset
timing*, which commit-bisection structurally could not find because the input was
configuration.

**Where this claim STOPS, and this is the part that matters:** it cannot explain
the *sustained* eleven-hour loop. The gate is "self-catching-up by construction"
— once a run is killed mid-way the status never advances, so it re-fires on
every boot **regardless of interval**. After the first crash my setting is
irrelevant. So: plausible contributor to when it started, **no** explanatory
power for why it continued, and not proven for either.

Recorded because "why 02:56" was called open after three wrong answers, and
because a config change made by a session that then spent hours bisecting
commits is precisely the kind of input that stays invisible. **When bisecting,
enumerate env changes alongside commits — a deploy carries both.**

### 1.1d FALSIFIED — the read does not ratchet, so caching it is a CPU fix

Third session probed the real shard (15.1MB / 39,370 rows), looping
`read_book_quotes` while retaining nothing, then again interleaved with retained
per-row objects to defeat arena reuse:

```
baseline                34.4MB
ONE read               130.3MB   (+95.8MB = 6.3x file size)
after del + gc          130.3MB   (returned to OS: 0.0MB)
25 more reads            flat     (ratchet +0.0MB, both variants)
```

So §1.1c's "~200 full materialisations per board build" is real **as CPU**, and
its memory conclusion is **falsified**: reads 2..200 are free. Peak is set
entirely by the *first* read and is never returned to the OS.

Consequences, stated plainly because two of them contradict work already
shipped:
- **`#252`'s cache is a latency fix, not a memory fix.** It removes ~200 redundant
  parses per build. Expected effect on peak RSS: approximately zero. It was
  committed describing itself as the memory mechanism; that claim is withdrawn.
- The lever that moves peak is **not materialising the whole shard at all** —
  stream-and-filter inside the reader, which already knows the identity filter it
  is about to apply. Caching leaves the ~572MB first read exactly where it was.
- Caveat the probe author stated and which is kept here: this is Windows/CPython.
  The *no-ratchet* result is pymalloc-level and should port to Render; the
  *0MB-reclaimed* figure is glibc-dependent and may not. Re-run on Render before
  building on the second number.
- Their first probe reported +227MB because `tracemalloc` was active and
  inflating it. 95.8MB is the honest figure — the same instrument that has now
  misled this incident three times.

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

### 1.1d MEASURED by a third session — #232 is the trigger, and my §1.1c fix was wrong

Session `local_69697977` measured what §1.1c only inferred. Their numbers
supersede mine:

- **One `read_book_quotes` call on a real 15.1MB MLB shard = +95.8MB RSS
  (6.3× file size), and 0MB is ever returned to the OS.** Projected to
  production's 90.2MB shard: **~572MB per sport, per build**, summed across
  eight sports.
- **Repeated reads are FREE.** 25 reads cost exactly the same as 1, including
  when interleaved with retained per-row objects.

⇒ The memory is spent entirely on the **first** read of each sport. The per-row
loop is a **CPU** problem, not a memory one.

**This invalidates my proposed fix.** §1.1c recommended wiring the dead
`_QUOTE_CACHE_KEY` cache. That would fix the CPU and **do nothing for the
memory**, because the cost is the first read and it is never reclaimed. The
repair belongs **inside `read_book_quotes`** — stream and filter rather than
materialising the whole shard into a list.

**And the trigger is `#232`, mine — but it was not a wrong fix.** On
refresh-worker the per-row read had always cost nothing, because the shard was
never there: `path.is_file()` was False and the read returned instantly. My own
`#232` commit message says it — *"book_quotes had NEVER reached refresh-worker,
zero log lines there, ever."* `#232` added book_quotes to
`_required_daily_artifact_paths` and delivered the 90MB shard, at which point the
latent per-row read stopped being free. Correct fix, exposed a latent defect.

They also independently exonerated **`#238`** (as §1.1c had) and **`#247`**
(blamed by proximity — auto-deploy is off, so that deploy was the first to carry
`#232` to the worker: ~40 commits, not one; `#247` touches no memory path).

**Nothing I shipped needs reverting on this evidence** — including the `#237`/
`#241` reverts, which on their measurement were unnecessary.

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
9. **A constant is only correct for the job it was written for. Re-derive it
   when the job changes, and name which job it serves.** This produced *four*
   separate wrong turns in one incident, which is why it is a rule and not four
   anecdotes:

   | constant | correct for | reused by | result |
   |---|---|---|---|
   | `_MIN_SAFE_MEMORY_HEADROOM_BYTES = 900MB` | a 2GB container, 350-450MB stages | a 4GiB container with a ~1873MB stage | guard fired once in 1200 log lines, always too late (`#249`) |
   | "the returned payload is only ~2.3MB" | the *serialised* payload | inferring that retained deepcopies are harmless | ≤96 live dict graphs never counted (`#253`) |
   | `_MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES = 32` | bounding count | bounding *memory* | count-only, no age or byte bound, invisible for three weeks (`3ca6c11d`) |
   | `_HOME_OVERVIEW_TTL_SEC = 10s` | how long an entry may be **served** | how long an entry must **survive** | pruner deleted the entry the rate limiter needed; `#251` was a no-op (`#255`) |

   The tell is always the same: a comment stating a measurement, with no
   statement of what it was measured against. `#249`'s own comment still said
   "the container's hard limit is 2GB" while running on 4GiB.

   Two clocks called "TTL" is the general case. If a name does not say *which*
   question the number answers, the next reader will answer a different one.
10. **A change that never executed is not evidence about the idea it
    implements.** `#251` was deployed, measured, produced no effect, and was
    written off by three sessions as "a rate fix against a floor problem" — then
    found to have been dead on arrival, because the pruner evicted its cache
    entries at 10s while it asked for 300s. Two of the three "measured failures"
    in this incident turned out to be measuring something other than what they
    claimed. Before concluding a fix does not work, prove the code ran: a log
    line, a counter, a test that fails when it is removed.
11. **Sequence deploys when you need attribution, and pin the commit.** The
    02:53 deploy carried ~40 commits and its newest one was blamed for hours.
    Deploy by pinned `commitId`, not branch head, so a pushed-but-unready commit
    cannot ride along; give each change its own window; and set the threshold
    that counts as an effect *before* looking (the longest quiet gap observed
    with nothing fixed was 14.6 minutes, so anything shorter is noise).
